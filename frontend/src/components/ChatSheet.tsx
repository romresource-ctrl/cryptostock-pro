/**
 * ChatSheet — bottom-sheet variant of the premium chatroom.
 *
 * v7.0.10 keyboard + drag rework:
 *  - Uses `useKeyboardAnimation()` from react-native-keyboard-controller
 *    to bind the sheet's bottom padding directly to the current keyboard
 *    height. This works reliably on Android regardless of the underlying
 *    `windowSoftInputMode`, and it survives being nested inside an
 *    absolutely-positioned container (the previous `KeyboardAvoidingView`
 *    approach did not push our composer up on Android).
 *  - Sheet height is now driven by an Animated value between two snap
 *    points — collapsed (~62%) and expanded (~95%). A PanResponder on
 *    the top handle bar lets users drag the sheet upward to expand
 *    (and downward to collapse back / dismiss).
 *
 * Renders as an absolutely-positioned panel at the bottom of the
 * dashboard, so the top half stays interactive when collapsed.
 */
import { Ionicons } from "@expo/vector-icons";
import * as ImageManipulator from "expo-image-manipulator";
import * as ImagePicker from "expo-image-picker";
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Animated,
  Dimensions,
  FlatList,
  Image,
  Linking,
  PanResponder,
  Platform,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from "react-native";
import { KeyboardAvoidingView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { getDeviceId } from "@/src/lib/deviceId";
import { useSubscription } from "@/src/lib/subscriptionContext";
import { useTheme } from "@/src/theme/ThemeContext";
import { storage } from "@/src/utils/storage";

const NICKNAME_KEY = "aicrypstockpro.chat.nickname";
const POLL_INTERVAL_MS = 3000;
const RATE_LIMIT_MS = 3000;
// v8.0.8 — no client-side message length limit anymore.
const IMG_TARGET_WIDTH = 900;
const IMG_JPEG_QUALITY = 0.55;

// Snap-point ratios of screen height.
const COLLAPSED_RATIO = 0.62;
const EXPANDED_RATIO = 0.95;

type Msg = {
  id: string;
  text: string;
  nickname: string;
  device_id: string;
  created_at: string;
  image_data?: string | null;
};

function backendBase() {
  const raw = process.env.EXPO_PUBLIC_BACKEND_URL || "";
  return raw.replace(/\/$/, "") + "/api";
}

export default function ChatSheet({
  visible,
  onClose,
}: {
  visible: boolean;
  onClose: () => void;
}) {
  const { colors } = useTheme();
  const { isPremium } = useSubscription();
  const insets = useSafeAreaInsets();

  // ── Keyboard tracking ──────────────────────────────────────────────
  // The composer is wrapped in a `KeyboardStickyView` from
  // react-native-keyboard-controller: this native-driven view is
  // guaranteed to translate above the on-screen keyboard, regardless of
  // Android softInputMode / iOS adjustments. This replaces the previous
  // hand-rolled `useKeyboardAnimation` + paddingBottom scheme which
  // double-compensated on Android with adjustResize.
  const inputRef = useRef<TextInput>(null);

  // ── Sheet height snap points + drag gesture ───────────────────────
  const { height: SCREEN_H } = Dimensions.get("window");
  const collapsedH = Math.round(SCREEN_H * COLLAPSED_RATIO);
  const expandedH = Math.round(SCREEN_H * EXPANDED_RATIO);
  const heightAnim = useRef(new Animated.Value(collapsedH)).current;
  // "current" snap — used by the pan responder to know starting height
  // on drag begin.
  const snapRef = useRef<number>(collapsedH);
  // Force-remount FlatList data when snap changes so it re-measures.
  const [snapTick, setSnapTick] = useState(0);

  const snapTo = useCallback(
    (target: number) => {
      snapRef.current = target;
      Animated.spring(heightAnim, {
        toValue: target,
        useNativeDriver: false,
        friction: 9,
        tension: 60,
      }).start(() => setSnapTick((t) => t + 1));
    },
    [heightAnim],
  );

  const panResponder = useMemo(
    () =>
      PanResponder.create({
        onStartShouldSetPanResponder: () => true,
        onMoveShouldSetPanResponder: (_e, g) => Math.abs(g.dy) > 3,
        onPanResponderGrant: () => {
          heightAnim.stopAnimation((v) => {
            snapRef.current = v;
          });
        },
        onPanResponderMove: (_e, g) => {
          // Drag up (dy < 0) grows the sheet; drag down shrinks it.
          const next = Math.max(
            240,
            Math.min(expandedH, snapRef.current - g.dy),
          );
          heightAnim.setValue(next);
        },
        onPanResponderRelease: (_e, g) => {
          const currentH = snapRef.current - g.dy;
          // Fling / significant drag decides snap.
          if (g.vy < -0.8 || currentH > (collapsedH + expandedH) / 2) {
            snapTo(expandedH);
          } else if (g.vy > 1.2 && currentH < collapsedH - 60) {
            // Strong downward fling → dismiss.
            onClose();
          } else {
            snapTo(collapsedH);
          }
        },
      }),
    [collapsedH, expandedH, heightAnim, onClose, snapTo],
  );

  // Reset snap to collapsed only when the sheet transitions from
  // hidden → visible. IMPORTANT: we intentionally do NOT depend on
  // `collapsedH` / `expandedH` here — on Android with adjustResize the
  // window height shrinks when the keyboard opens, which would otherwise
  // trigger this effect and violently snap the sheet back to collapsed
  // mid-conversation. Recompute the fresh height at the moment of
  // (re)open using Dimensions.get.
  const wasVisibleRef = useRef(false);
  useEffect(() => {
    if (visible && !wasVisibleRef.current) {
      const H = Math.round(Dimensions.get("window").height * COLLAPSED_RATIO);
      heightAnim.setValue(H);
      snapRef.current = H;
    }
    wasVisibleRef.current = visible;
  }, [visible, heightAnim]);

  // ── Chat state ────────────────────────────────────────────────────
  const [nickname, setNickname] = useState<string | null>(null);
  const [nickInput, setNickInput] = useState("");
  const [messages, setMessages] = useState<Msg[]>([]);
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [input, setInput] = useState("");
  const [attachment, setAttachment] = useState<string | null>(null);
  const [attaching, setAttaching] = useState(false);
  const lastSentRef = useRef(0);
  const deviceIdRef = useRef("");
  const listRef = useRef<FlatList<Msg>>(null);

  // Initial device id + nickname load
  useEffect(() => {
    if (!visible) return;
    (async () => {
      deviceIdRef.current = await getDeviceId();
      const stored = await storage.getItem<string | null>(NICKNAME_KEY, null);
      if (stored) setNickname(stored);
    })();
  }, [visible]);

  const fetchMessages = useCallback(async () => {
    try {
      const res = await fetch(`${backendBase()}/chat/messages?limit=100`);
      if (!res.ok) return;
      const j = await res.json();
      const list = (j?.messages || []) as Msg[];
      setMessages(list);
      // Auto-scroll to newest (list is chronological)
      setTimeout(() => {
        try {
          listRef.current?.scrollToEnd({ animated: false });
        } catch {
          /* ignore */
        }
      }, 30);
    } finally {
      setLoading(false);
    }
  }, []);

  // Poll while visible
  useEffect(() => {
    if (!visible) return;
    fetchMessages();
    const t = setInterval(fetchMessages, POLL_INTERVAL_MS);
    return () => clearInterval(t);
  }, [visible, fetchMessages]);

  // Nickname save
  const saveNickname = async () => {
    const n = nickInput.trim();
    if (n.length < 2) return;
    await storage.setItem(NICKNAME_KEY, n);
    setNickname(n);
  };

  // Attachment
  const pickAttachment = async () => {
    if (attaching || sending) return;
    setAttaching(true);
    try {
      const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!perm.granted) {
        if (!perm.canAskAgain) {
          Alert.alert(
            "Photos Permission",
            "Please enable Photos access in Settings so you can share images.",
            [
              { text: "Cancel", style: "cancel" },
              { text: "Open Settings", onPress: () => Linking.openSettings() },
            ],
          );
        }
        return;
      }
      const res = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ImagePicker.MediaTypeOptions.Images,
        allowsMultipleSelection: false,
        quality: 1,
      });
      if (res.canceled || !res.assets?.length) return;
      const uri = res.assets[0].uri;
      const out = await ImageManipulator.manipulateAsync(
        uri,
        [{ resize: { width: IMG_TARGET_WIDTH } }],
        { compress: IMG_JPEG_QUALITY, format: ImageManipulator.SaveFormat.JPEG, base64: true },
      );
      const b64 = out.base64 ? `data:image/jpeg;base64,${out.base64}` : null;
      if (b64) setAttachment(b64);
    } catch (e) {
      Alert.alert("Attachment Failed", String(e));
    } finally {
      setAttaching(false);
    }
  };

  // Send
  const sendMessage = async () => {
    if (sending) return;
    if (!isPremium) {
      Alert.alert("Premium Only", "Subscribe to post in the chatroom.");
      return;
    }
    if (!nickname) return;
    const text = input.trim();
    if (!text && !attachment) return;
    const now = Date.now();
    if (now - lastSentRef.current < RATE_LIMIT_MS) return;
    setSending(true);
    try {
      const res = await fetch(`${backendBase()}/chat/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text,
          nickname,
          device_id: deviceIdRef.current,
          image_data: attachment,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Send failed" }));
        Alert.alert("Send Failed", err.detail);
      } else {
        setInput("");
        setAttachment(null);
        lastSentRef.current = now;
        // Refresh list and auto-scroll to the newest message so the
        // just-sent text stays visible to the user without them having
        // to scroll manually.
        await fetchMessages();
        setTimeout(() => {
          try {
            listRef.current?.scrollToEnd({ animated: true });
          } catch {
            /* ignore */
          }
        }, 60);
      }
    } finally {
      setSending(false);
      // Keep the composer focused so the OS keyboard stays open and the
      // user can continue chatting without re-tapping the field. On
      // Android the Touchable that fires this handler steals focus from
      // the TextInput first, so we defer the refocus by a small margin
      // to let the touch release settle before we re-open the keyboard.
      // This pairs with `blurOnSubmit={false}` on the TextInput.
      setTimeout(() => {
        try {
          inputRef.current?.focus();
        } catch {
          /* ignore */
        }
      }, 50);
    }
  };

  if (!visible) return null;

  // v8.0.8 — Send button enablement is now decoupled from `isPremium`
  // and `sending`. The button turns blue the moment the user types any
  // non-whitespace character (or attaches an image). If a non-premium
  // user taps it, `sendMessage` still shows the "Premium Only" alert —
  // but the UI no longer looks broken/disabled while typing.
  const canSend = input.trim().length > 0 || !!attachment;

  return (
    <Animated.View
      style={[
        styles.sheet,
        {
          backgroundColor: colors.background,
          borderColor: colors.border,
          height: heightAnim,
        },
      ]}
      pointerEvents="box-none"
    >
      {/* Header bar — drag target (PanResponder attached) */}
      <View {...panResponder.panHandlers} style={styles.headerBar}>
        <View style={styles.handleBar} />
        <View style={{ flexDirection: "row", alignItems: "center", paddingHorizontal: 14 }}>
          <Ionicons name="chatbubbles" size={16} color={colors.accentBlue} />
          <Text style={[styles.title, { color: colors.textPrimary }]}>Chatroom</Text>
          <View style={{ flex: 1 }} />
          <TouchableOpacity
            onPress={() =>
              snapRef.current >= expandedH - 5 ? snapTo(collapsedH) : snapTo(expandedH)
            }
            hitSlop={10}
            testID="chatsheet-expand"
            style={[styles.iconBtn, { backgroundColor: colors.surface, borderColor: colors.border }]}
          >
            <Ionicons
              name={snapRef.current >= expandedH - 5 ? "chevron-down" : "chevron-up"}
              size={16}
              color={colors.textPrimary}
            />
          </TouchableOpacity>
          <TouchableOpacity
            onPress={onClose}
            hitSlop={10}
            testID="chatsheet-close"
            style={[styles.iconBtn, { backgroundColor: colors.surface, borderColor: colors.border, marginLeft: 6 }]}
          >
            <Ionicons name="close" size={18} color={colors.textPrimary} />
          </TouchableOpacity>
        </View>
      </View>

      {/* Body — messages fill remaining space; composer + FlatList are
          wrapped in a KeyboardAvoidingView so the whole content column
          resizes above the on-screen keyboard. v8.0.6: added flex:1 on
          BOTH the KAV and the inner list container so the FlatList can
          actually take up all remaining height and remain scrollable
          when the keyboard is open. `flexGrow:1` on contentContainerStyle
          also lets the list expand to fill the viewport. */}
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : "height"}
        keyboardVerticalOffset={0}
        style={{ flex: 1 }}
      >
        {nickname === null ? (
          <View style={{ padding: 16, gap: 10 }}>
            <Text style={[styles.title, { color: colors.textPrimary, marginLeft: 0 }]}>
              Set nickname
            </Text>
            <TextInput
              value={nickInput}
              onChangeText={setNickInput}
              placeholder="Your nickname (max 20)"
              placeholderTextColor={colors.textMuted}
              style={[
                styles.nickInput,
                {
                  backgroundColor: colors.surfaceAlt,
                  borderColor: colors.border,
                  color: colors.textPrimary,
                },
              ]}
              maxLength={20}
            />
            <TouchableOpacity
              onPress={saveNickname}
              style={[styles.saveBtn, { backgroundColor: colors.accentBlue }]}
            >
              <Text style={{ color: "#fff", fontWeight: "800" }}>Continue</Text>
            </TouchableOpacity>
          </View>
        ) : loading && messages.length === 0 ? (
          <View style={{ padding: 24, alignItems: "center" }}>
            <ActivityIndicator color={colors.accentBlue} />
          </View>
        ) : (
          <View style={{ flex: 1 }}>
            <FlatList
              key={`chat-list-${snapTick}`}
              ref={listRef}
              data={messages}
              keyExtractor={(m) => m.id}
              style={{ flex: 1 }}
              contentContainerStyle={{
                flexGrow: 1,
                padding: 10,
                paddingBottom: 4,
                justifyContent: "flex-end",
              }}
              keyboardShouldPersistTaps="handled"
              keyboardDismissMode="on-drag"
              showsVerticalScrollIndicator={true}
              // v8.0.4 FlatList perf props — cheap virtualisation gains.
              windowSize={5}
              maxToRenderPerBatch={10}
              removeClippedSubviews={true}
              initialNumToRender={12}
              renderItem={({ item }) => {
                const isMine = item.device_id === deviceIdRef.current;
                return (
                  <View style={[styles.row, { justifyContent: isMine ? "flex-end" : "flex-start" }]}>
                    <View
                      style={[
                        styles.bubble,
                        {
                          backgroundColor: isMine ? colors.accentBlue : colors.surface,
                          borderColor: colors.border,
                        },
                      ]}
                    >
                      <Text
                        style={[
                          styles.nick,
                          { color: isMine ? "#fff" : colors.accentBlue },
                        ]}
                      >
                        {item.nickname}
                      </Text>
                      {item.image_data ? (
                        <Image
                          source={{ uri: item.image_data }}
                          style={styles.attachmentImage}
                          resizeMode="cover"
                        />
                      ) : null}
                      {item.text ? (
                        <Text style={[styles.text, { color: isMine ? "#fff" : colors.textPrimary }]}>
                          {item.text}
                        </Text>
                      ) : null}
                    </View>
                  </View>
                );
              }}
            />
          </View>
        )}

        {nickname !== null && (
          <View
            style={[
              styles.inputRow,
              {
                backgroundColor: colors.surface,
                borderTopColor: colors.border,
                // Bottom safe-area padding is only applied when keyboard is
                // closed — once it opens, the outer Animated.View padding
                // (=kbHeight) already lifts the whole row above the keys.
                paddingBottom: Math.max(insets.bottom, 10),
              },
            ]}
          >
            <TouchableOpacity
              onPress={pickAttachment}
              disabled={attaching || sending}
              style={[
                styles.attachBtn,
                { backgroundColor: colors.surfaceAlt, borderColor: colors.border },
              ]}
            >
              {attaching ? (
                <ActivityIndicator size="small" color={colors.accentBlue} />
              ) : (
                <Ionicons name="image-outline" size={20} color={colors.accentBlue} />
              )}
            </TouchableOpacity>
            <View style={{ flex: 1 }}>
              {attachment ? (
                <View style={[styles.preview, { backgroundColor: colors.surfaceAlt }]}>
                  <Image source={{ uri: attachment }} style={styles.previewImg} />
                  <TouchableOpacity onPress={() => setAttachment(null)} hitSlop={8}>
                    <Ionicons name="close-circle" size={18} color={colors.textMuted} />
                  </TouchableOpacity>
                </View>
              ) : null}
              <TextInput
                ref={inputRef}
                value={input}
                onChangeText={setInput}
                placeholder="Type a message…"
                placeholderTextColor={colors.textMuted}
                multiline
                // v8.0.8 — removed maxLength so long chat messages are
                // no longer truncated mid-typing. Backend still bounds
                // stored size (chat_messages schema) as a safety net.
                blurOnSubmit={false}
                onFocus={() => {
                  // Expand automatically when the user starts typing so we
                  // never end up with the composer above the keyboard but
                  // only two visible bubbles.
                  if (snapRef.current < expandedH - 5) snapTo(expandedH);
                }}
                style={[
                  styles.textInput,
                  {
                    backgroundColor: colors.surfaceAlt,
                    color: colors.textPrimary,
                    borderColor: colors.border,
                  },
                ]}
              />
            </View>
            <TouchableOpacity
              onPress={sendMessage}
              disabled={!canSend}
              style={[
                styles.sendBtn,
                {
                  backgroundColor: canSend ? colors.accentBlue : colors.surfaceHighlight,
                  opacity: sending ? 0.6 : 1,
                },
              ]}
            >
              {sending ? (
                <ActivityIndicator size="small" color="#fff" />
              ) : (
                <Ionicons name="arrow-up" size={18} color="#fff" />
              )}
            </TouchableOpacity>
          </View>
        )}
      </KeyboardAvoidingView>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  sheet: {
    position: "absolute",
    left: 0,
    right: 0,
    bottom: 0,
    borderTopLeftRadius: 18,
    borderTopRightRadius: 18,
    borderTopWidth: 1,
    overflow: "hidden",
    elevation: 12,
    shadowColor: "#000",
    shadowOpacity: 0.18,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: -4 },
    zIndex: 200,
  },
  headerBar: {
    paddingVertical: 6,
    // Bigger hit slop for the drag handle — the whole strip is grabbable.
    paddingTop: Platform.OS === "ios" ? 10 : 8,
    paddingBottom: 4,
  },
  handleBar: {
    alignSelf: "center",
    width: 48,
    height: 5,
    borderRadius: 3,
    backgroundColor: "#999",
    opacity: 0.55,
    marginTop: 4,
    marginBottom: 6,
  },
  title: { fontSize: 14, fontWeight: "800", marginLeft: 8, letterSpacing: 0.4 },
  iconBtn: {
    width: 32,
    height: 32,
    borderRadius: 16,
    borderWidth: 1,
    alignItems: "center",
    justifyContent: "center",
  },
  row: { flexDirection: "row", marginBottom: 6 },
  bubble: {
    maxWidth: "82%",
    borderRadius: 12,
    borderWidth: 1,
    paddingHorizontal: 10,
    paddingVertical: 6,
  },
  nick: { fontSize: 10, fontWeight: "800", marginBottom: 2 },
  text: { fontSize: 13, lineHeight: 18 },
  attachmentImage: { width: 200, height: 200, borderRadius: 8, marginBottom: 4 },
  inputRow: {
    flexDirection: "row",
    alignItems: "flex-end",
    gap: 6,
    padding: 6,
    borderTopWidth: 0.5,
  },
  attachBtn: {
    width: 36,
    height: 36,
    borderRadius: 18,
    borderWidth: 1,
    alignItems: "center",
    justifyContent: "center",
  },
  preview: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    padding: 4,
    borderRadius: 8,
    marginBottom: 4,
  },
  previewImg: { width: 30, height: 30, borderRadius: 4 },
  textInput: {
    minHeight: 36,
    maxHeight: 100,
    fontSize: 13,
    paddingHorizontal: 10,
    paddingVertical: 8,
    borderRadius: 10,
    borderWidth: 1,
    textAlignVertical: "top",
  },
  sendBtn: {
    width: 40,
    height: 40,
    borderRadius: 20,
    alignItems: "center",
    justifyContent: "center",
  },
  nickInput: {
    fontSize: 15,
    padding: 12,
    borderRadius: 10,
    borderWidth: 1,
  },
  saveBtn: {
    paddingVertical: 12,
    borderRadius: 10,
    alignItems: "center",
  },
});
