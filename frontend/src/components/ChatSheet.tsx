/**
 * ChatSheet — bottom-sheet variant of the premium chatroom.
 *
 * Renders as an absolutely-positioned 55% height panel at the bottom of
 * the dashboard, so the top half stays fully interactive (user can still
 * scroll asset columns, see candlestick preview, tap other buttons).
 *
 * This is a lightweight rewrite of `/app/chat.tsx` — same backend API,
 * same rendering rules — but without full-page navigation. Uses the
 * KeyboardAvoidingView from react-native-keyboard-controller so the
 * input floats above the keyboard on Android and iOS.
 */
import { Ionicons } from "@expo/vector-icons";
import * as ImageManipulator from "expo-image-manipulator";
import * as ImagePicker from "expo-image-picker";
import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  FlatList,
  Image,
  Linking,
  Platform,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from "react-native";
import { KeyboardAvoidingView, useKeyboardHandler } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { getDeviceId } from "@/src/lib/deviceId";
import { useSubscription } from "@/src/lib/subscriptionContext";
import { useTheme } from "@/src/theme/ThemeContext";
import { storage } from "@/src/utils/storage";

const NICKNAME_KEY = "aicrypstockpro.chat.nickname";
const POLL_INTERVAL_MS = 3000;
const RATE_LIMIT_MS = 3000;
const MAX_MSG_LEN = 500;
const IMG_TARGET_WIDTH = 900;
const IMG_JPEG_QUALITY = 0.55;

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
  // Expand sheet to full-page when keyboard is up so the composer + at
  // least 7-8 lines of chat history stay visible above the keys.
  const [keyboardShown, setKeyboardShown] = useState(false);
  useKeyboardHandler(
    {
      onStart: (e) => {
        "worklet";
        if (e.height > 0) {
          // schedule state update on JS thread
          // eslint-disable-next-line no-undef
          (globalThis as any)._setKb?.(true);
        }
      },
      onEnd: (e) => {
        "worklet";
        // eslint-disable-next-line no-undef
        (globalThis as any)._setKb?.(e.height > 0);
      },
    },
    [],
  );
  useEffect(() => {
    (globalThis as any)._setKb = setKeyboardShown;
    return () => {
      (globalThis as any)._setKb = null;
    };
  }, []);

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
      const data = await res.json();
      const msgs: Msg[] = data.messages || [];
      setMessages(msgs);
    } catch {
      /* silent */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!visible) return;
    fetchMessages();
    const id = setInterval(fetchMessages, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [visible, fetchMessages]);

  const saveNickname = async () => {
    const nick = nickInput.trim();
    if (!nick) return;
    if (nick.length > 20) {
      Alert.alert("Too long", "Max 20 characters.");
      return;
    }
    setNickname(nick);
    await storage.setItem(NICKNAME_KEY, nick);
  };

  const pickAttachment = async () => {
    if (!isPremium) return;
    setAttaching(true);
    try {
      if (Platform.OS === "ios") {
        const perm = await ImagePicker.getMediaLibraryPermissionsAsync();
        if (perm.status !== "granted") {
          if (perm.canAskAgain) {
            const asked = await ImagePicker.requestMediaLibraryPermissionsAsync();
            if (asked.status !== "granted") {
              Alert.alert("Photo Access", "Enable photo access in Settings.", [
                { text: "Cancel", style: "cancel" },
                { text: "Open Settings", onPress: () => Linking.openSettings() },
              ]);
              return;
            }
          }
        }
      }
      const picked = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ImagePicker.MediaTypeOptions.Images,
        quality: 1,
        allowsEditing: false,
      });
      if (picked.canceled || !picked.assets?.[0]) return;
      const manipulated = await ImageManipulator.manipulateAsync(
        picked.assets[0].uri,
        [{ resize: { width: IMG_TARGET_WIDTH } }],
        {
          compress: IMG_JPEG_QUALITY,
          format: ImageManipulator.SaveFormat.JPEG,
          base64: true,
        },
      );
      if (!manipulated.base64) return;
      const dataUrl = `data:image/jpeg;base64,${manipulated.base64}`;
      if (dataUrl.length > 750_000) {
        Alert.alert("Image Too Large", "Pick a smaller photo.");
        return;
      }
      setAttachment(dataUrl);
    } catch (e: any) {
      Alert.alert("Attach Failed", e?.message ?? String(e));
    } finally {
      setAttaching(false);
    }
  };

  const sendMessage = async () => {
    const text = input.trim();
    if (!text && !attachment) return;
    if (!isPremium) return;
    const now = Date.now();
    if (now - lastSentRef.current < RATE_LIMIT_MS) return;
    setSending(true);
    try {
      const res = await fetch(`${backendBase()}/chat/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text,
          nickname: nickname ?? "guest",
          device_id: deviceIdRef.current,
          image_data: attachment ?? undefined,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Send failed" }));
        Alert.alert("Send Failed", err.detail);
      } else {
        setInput("");
        setAttachment(null);
        lastSentRef.current = now;
        fetchMessages();
      }
    } finally {
      setSending(false);
    }
  };

  if (!visible) return null;

  const canSend = isPremium && !sending && (input.trim().length > 0 || !!attachment);

  return (
    <View
      style={[
        styles.sheet,
        {
          backgroundColor: colors.background,
          borderColor: colors.border,
          // When keyboard is up, expand to full page so composer + ~8
          // lines of chat history remain visible above the keys.
          height: keyboardShown ? "100%" : "62%",
        },
      ]}
      pointerEvents="box-none"
    >
      <View style={[styles.sheetInner, { backgroundColor: colors.background }]}>
        {/* Drag handle + close */}
        <View style={styles.headerBar}>
          <View style={styles.handleBar} />
          <View style={{ flexDirection: "row", alignItems: "center", paddingHorizontal: 14 }}>
            <Ionicons name="chatbubbles" size={16} color={colors.accentBlue} />
            <Text style={[styles.title, { color: colors.textPrimary }]}>Chatroom</Text>
            <View style={{ flex: 1 }} />
            <TouchableOpacity
              onPress={onClose}
              hitSlop={10}
              testID="chatsheet-close"
              style={[styles.closeBtn, { backgroundColor: colors.surface, borderColor: colors.border }]}
            >
              <Ionicons name="close" size={18} color={colors.textPrimary} />
            </TouchableOpacity>
          </View>
        </View>

        <KeyboardAvoidingView
          behavior="translate-with-padding"
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
            <FlatList
              ref={listRef}
              data={messages}
              keyExtractor={(m) => m.id}
              contentContainerStyle={{ padding: 10, paddingBottom: 4 }}
              keyboardShouldPersistTaps="handled"
              keyboardDismissMode="on-drag"
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
          )}

          {nickname !== null && (
            <View
              style={[
                styles.inputRow,
                {
                  backgroundColor: colors.surface,
                  borderTopColor: colors.border,
                  // Push input up above Android gesture bar / iPhone home
                  // indicator so it stays fully tappable — the previous
                  // version got clipped by the system nav on some devices.
                  paddingBottom: Math.max(insets.bottom, 12) + 6,
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
                  value={input}
                  onChangeText={setInput}
                  placeholder="Type a message…"
                  placeholderTextColor={colors.textMuted}
                  multiline
                  maxLength={MAX_MSG_LEN}
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
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  sheet: {
    position: "absolute",
    left: 0,
    right: 0,
    bottom: 0,
    height: "62%",
    borderTopLeftRadius: 18,
    borderTopRightRadius: 18,
    borderTopWidth: 1,
    overflow: "hidden",
    // subtle elevation shadow (Android + iOS)
    elevation: 12,
    shadowColor: "#000",
    shadowOpacity: 0.18,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: -4 },
    zIndex: 200,
  },
  sheetInner: { flex: 1 },
  headerBar: { paddingVertical: 6 },
  handleBar: {
    alignSelf: "center",
    width: 44,
    height: 4,
    borderRadius: 2,
    backgroundColor: "#999",
    opacity: 0.4,
    marginTop: 4,
    marginBottom: 6,
  },
  title: { fontSize: 14, fontWeight: "800", marginLeft: 8, letterSpacing: 0.4 },
  closeBtn: {
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
