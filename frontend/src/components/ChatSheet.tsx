/**
 * ChatSheet — bottom-sheet variant of the premium chatroom.
 *
 * v8.1.5 — Reply-to-message + voice notes (WhatsApp style):
 *  - Swipe LEFT on any bubble to reply. Reveal a reply icon during the
 *    drag; release past the threshold to attach the message as a reply.
 *    The keyboard auto-opens and the composer focuses so the user can
 *    immediately type + send.
 *  - Reply preview strip sits above the composer with a coloured bar,
 *    original nickname, and a snippet (or thumbnail for images / "Voice
 *    note 0:12" for audio). Tap ✕ to cancel the reply.
 *  - Every outgoing message may carry a `reply_to` object which the
 *    receiver renders inline (indented, coloured bar, tap-to-scroll).
 *  - Hold the 🎤 mic to record a voice note (M4A/AAC, mono, 24 kbps).
 *    Live timer updates every 100ms. Slide LEFT past 60px to cancel.
 *    Release to send. Max 60 s (soft cap; backend hard caps at 90 s).
 *  - Voice bubbles show a play/pause button + waveform placeholder +
 *    live duration; playback uses expo-audio's AudioPlayer.
 *  - All new features are gated by isPremium (existing) so non-subs
 *    still see the "Members Only" popup.
 *
 * v7.0.10 keyboard + drag rework (unchanged): KeyboardAvoidingView from
 * react-native-keyboard-controller ensures the composer sticks above
 * the on-screen keyboard on both platforms; PanResponder on the header
 * drag-handle powers the collapsed↔expanded snap points.
 */
import { Ionicons } from "@expo/vector-icons";
import {
  AudioModule,
  RecordingPresets,
  createAudioPlayer,
  useAudioRecorder,
  useAudioRecorderState,
} from "expo-audio";
import * as FileSystem from "expo-file-system/legacy";
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
const IMG_TARGET_WIDTH = 900;
const IMG_JPEG_QUALITY = 0.55;

// Swipe-to-reply thresholds.
const REPLY_SWIPE_TRIGGER = 60;   // px — release past this to fire reply
const REPLY_SWIPE_MAX = 90;       // px — cap so bubble doesn't fly off

// Voice-note thresholds.
const VOICE_MAX_SECONDS = 20;
const VOICE_CANCEL_SLIDE = 60;    // px — slide left this far to cancel

// Snap-point ratios of screen height.
const COLLAPSED_RATIO = 0.62;
const EXPANDED_RATIO = 0.95;

type ReplyInfo = {
  id: string;
  nickname: string;
  snippet?: string;
  has_image?: boolean;
  has_audio?: boolean;
};

type Msg = {
  id: string;
  text: string;
  nickname: string;
  device_id: string;
  created_at: string;
  image_data?: string | null;
  audio_data?: string | null;
  audio_duration_ms?: number | null;
  reply_to?: ReplyInfo | null;
};

// Pending draft reply carries an optional thumbnail so the composer
// preview can show it without re-fetching from Mongo.
type DraftReply = ReplyInfo & { image_thumb?: string | null };

function backendBase() {
  const raw = process.env.EXPO_PUBLIC_BACKEND_URL || "";
  return raw.replace(/\/$/, "") + "/api";
}

function fmtDuration(ms: number | null | undefined): string {
  const s = Math.max(0, Math.round((ms || 0) / 1000));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${r.toString().padStart(2, "0")}`;
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

  // v8.1.5 — Mic button pan responder. Press-and-hold to record;
  // slide LEFT past VOICE_CANCEL_SLIDE while recording to cancel.
  // Release: send (or discard if cancelling). Declared AFTER
  // startRecording/stopRecording to avoid temporal-dead-zone.
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
  // v8.12.19 — Live count of devices currently polling the chatroom.
  const [onlineCount, setOnlineCount] = useState<number>(0);
  // v8.1.5 — Reply state: the message currently being replied to, or null.
  const [replyTo, setReplyTo] = useState<DraftReply | null>(null);
  // v8.1.5 — Voice recording state.
  const audioRecorder = useAudioRecorder(RecordingPresets.LOW_QUALITY);
  const recorderState = useAudioRecorderState(audioRecorder);
  const [voiceCancelling, setVoiceCancelling] = useState(false);
  const [voiceElapsedMs, setVoiceElapsedMs] = useState(0);
  const voiceTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const voiceMaxCutoffRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Playback (only one audio active at a time). Ref because switching
  // messages must eagerly stop the previous player before creating a
  // new one; keeping this in a ref (not state) avoids extra re-renders.
  const [playingId, setPlayingId] = useState<string | null>(null);
  const activePlayerRef = useRef<ReturnType<typeof createAudioPlayer> | null>(null);
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
      const did = deviceIdRef.current;
      const q = did ? `?limit=100&device_id=${encodeURIComponent(did)}` : "?limit=100";
      const res = await fetch(`${backendBase()}/chat/messages${q}`);
      if (!res.ok) return;
      const j = await res.json();
      const list = (j?.messages || []) as Msg[];
      setMessages(list);
      // v8.12.19 — Backend now returns `online` (count of distinct
      // devices polling within the last PRESENCE_WINDOW_SEC seconds).
      if (typeof j?.online === "number") {
        setOnlineCount(j.online);
      }
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

  // v8.1.5 — Trigger reply on a message. Called by the SwipeableRow
  // when the user releases past the swipe threshold. Auto-focuses the
  // composer so the OS keyboard pops up immediately.
  const startReply = useCallback((m: Msg) => {
    if (!isPremium) {
      Alert.alert("Premium Only", "Subscribe to reply in the chatroom.");
      return;
    }
    setReplyTo({
      id: m.id,
      nickname: m.nickname,
      snippet: (m.text || "").slice(0, 80),
      has_image: !!m.image_data,
      has_audio: !!m.audio_data,
      image_thumb: m.image_data || null,
    });
    // Expand sheet + focus composer so the keyboard shows up.
    if (snapRef.current < expandedH - 5) snapTo(expandedH);
    setTimeout(() => {
      try {
        inputRef.current?.focus();
      } catch {
        /* ignore */
      }
    }, 60);
  }, [isPremium, expandedH, snapTo]);

  const clearReply = useCallback(() => setReplyTo(null), []);

  // v8.1.5 — Voice recording controls. `startRecording` is called on
  // press-in of the mic button; `stopRecording` on release. During
  // recording, the parent uses PanResponder to detect a leftward slide
  // and set `voiceCancelling` — if true when the finger lifts, we throw
  // away the recording instead of sending it.
  const startRecording = useCallback(async () => {
    if (!isPremium) {
      Alert.alert("Premium Only", "Subscribe to send voice notes.");
      return;
    }
    if (recorderState.isRecording) return;
    try {
      const perm = await AudioModule.requestRecordingPermissionsAsync();
      if (!perm.granted) {
        if (!perm.canAskAgain) {
          Alert.alert(
            "Microphone Permission",
            "Enable microphone access in Settings to send voice notes.",
            [
              { text: "Cancel", style: "cancel" },
              { text: "Open Settings", onPress: () => Linking.openSettings() },
            ],
          );
        }
        return;
      }
      // v8.1.5 — Ensure the input keyboard does not compete with the
      // mic during recording (particularly on Android). Also stop any
      // ongoing playback so the mic isn't polluted by app audio.
      try { activePlayerRef.current?.remove(); } catch { /* ignore */ }
      activePlayerRef.current = null;
      setPlayingId(null);
      setVoiceElapsedMs(0);
      setVoiceCancelling(false);
      await audioRecorder.prepareToRecordAsync();
      audioRecorder.record();
      voiceTimerRef.current = setInterval(() => {
        setVoiceElapsedMs((prev) => prev + 100);
      }, 100);
      voiceMaxCutoffRef.current = setTimeout(() => {
        // Auto-stop + send at soft cap (60 s).
        void stopRecording(false);
      }, VOICE_MAX_SECONDS * 1000);
    } catch (e) {
      Alert.alert("Recording Failed", String(e));
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isPremium, audioRecorder, recorderState.isRecording]);

  const stopRecording = useCallback(async (cancel: boolean) => {
    if (voiceTimerRef.current) {
      clearInterval(voiceTimerRef.current);
      voiceTimerRef.current = null;
    }
    if (voiceMaxCutoffRef.current) {
      clearTimeout(voiceMaxCutoffRef.current);
      voiceMaxCutoffRef.current = null;
    }
    let uri: string | null = null;
    try {
      await audioRecorder.stop();
      uri = audioRecorder.uri;
    } catch {
      /* ignore — nothing to stop */
    }
    const durationMs = voiceElapsedMs;
    setVoiceElapsedMs(0);
    setVoiceCancelling(false);
    if (cancel || !uri || durationMs < 500) {
      // Too short OR cancelled — discard.
      return;
    }
    // Read file → base64 → data URL.
    try {
      const b64 = await FileSystem.readAsStringAsync(uri, {
        encoding: FileSystem.EncodingType.Base64,
      });
      // expo-audio records M4A container on iOS/Android by default.
      const dataUrl = `data:audio/m4a;base64,${b64}`;
      await sendMessage({ audio_data: dataUrl, audio_duration_ms: durationMs });
    } catch (e) {
      Alert.alert("Voice Note Failed", String(e));
    }
  // sendMessage is defined below via useCallback; TS is fine because
  // both are captured lexically in the same render.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [audioRecorder, voiceElapsedMs]);

  // v8.1.5 — Mic button pan responder. Press-and-hold to record;
  // slide LEFT past VOICE_CANCEL_SLIDE while recording to cancel.
  // Release: send (or discard if cancelling).
  const micPanResponder = useMemo(
    () =>
      PanResponder.create({
        onStartShouldSetPanResponder: () => true,
        onMoveShouldSetPanResponder: () => true,
        onPanResponderGrant: () => {
          void startRecording();
        },
        onPanResponderMove: (_e, g) => {
          const cancel = g.dx < -VOICE_CANCEL_SLIDE;
          setVoiceCancelling((prev) => (prev === cancel ? prev : cancel));
        },
        onPanResponderRelease: (_e, g) => {
          const cancel = g.dx < -VOICE_CANCEL_SLIDE;
          void stopRecording(cancel);
        },
        onPanResponderTerminate: () => {
          void stopRecording(true);
        },
      }),
    [startRecording, stopRecording],
  );

  // Playback: single-active. Tapping a bubble either starts a fresh
  // player OR stops the currently playing one.
  const togglePlayback = useCallback((m: Msg) => {
    if (!m.audio_data) return;
    if (playingId === m.id) {
      try { activePlayerRef.current?.pause(); } catch { /* ignore */ }
      setPlayingId(null);
      return;
    }
    // Stop previous
    try { activePlayerRef.current?.remove(); } catch { /* ignore */ }
    activePlayerRef.current = null;
    try {
      const p = createAudioPlayer({ uri: m.audio_data });
      activePlayerRef.current = p;
      p.play();
      // Auto-clear playing state when finished.
      const durMs = m.audio_duration_ms || 3000;
      setTimeout(() => {
        if (activePlayerRef.current === p) {
          try { p.remove(); } catch { /* ignore */ }
          activePlayerRef.current = null;
          setPlayingId((cur) => (cur === m.id ? null : cur));
        }
      }, durMs + 400);
      setPlayingId(m.id);
    } catch (e) {
      Alert.alert("Playback Failed", String(e));
    }
  }, [playingId]);

  // Cleanup on unmount.
  useEffect(() => {
    return () => {
      if (voiceTimerRef.current) clearInterval(voiceTimerRef.current);
      if (voiceMaxCutoffRef.current) clearTimeout(voiceMaxCutoffRef.current);
      try { activePlayerRef.current?.remove(); } catch { /* ignore */ }
    };
  }, []);

  // Send. v8.1.5 — accepts optional overrides for audio-note flow.
  const sendMessage = async (
    overrides: { audio_data?: string; audio_duration_ms?: number } = {},
  ) => {
    if (sending) return;
    if (!isPremium) {
      Alert.alert("Premium Only", "Subscribe to post in the chatroom.");
      return;
    }
    if (!nickname) return;
    const text = input.trim();
    const isVoice = !!overrides.audio_data;
    if (!isVoice && !text && !attachment) return;
    const now = Date.now();
    if (now - lastSentRef.current < RATE_LIMIT_MS) return;
    setSending(true);
    try {
      // Snapshot reply so we can clear the draft immediately without a
      // race where the just-sent message re-appears with stale reply.
      const snapshotReply = replyTo
        ? {
            id: replyTo.id,
            nickname: replyTo.nickname,
            snippet: (replyTo.snippet || "").slice(0, 80),
            has_image: !!replyTo.has_image,
            has_audio: !!replyTo.has_audio,
          }
        : null;
      const res = await fetch(`${backendBase()}/chat/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: isVoice ? "" : text,
          nickname,
          device_id: deviceIdRef.current,
          image_data: isVoice ? null : attachment,
          audio_data: overrides.audio_data ?? null,
          audio_duration_ms: overrides.audio_duration_ms ?? null,
          reply_to: snapshotReply,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Send failed" }));
        Alert.alert("Send Failed", err.detail);
      } else {
        if (!isVoice) {
          setInput("");
          setAttachment(null);
        }
        setReplyTo(null);
        lastSentRef.current = now;
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
      if (!isVoice) {
        setTimeout(() => {
          try {
            inputRef.current?.focus();
          } catch {
            /* ignore */
          }
        }, 50);
      }
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
              // v8.1.1 — keep the keyboard OPEN when the user swipes to
              // scroll the message history. Previously `on-drag` closed
              // the keyboard as soon as the user tried to look back at
              // older messages, which killed the chat flow.
              keyboardDismissMode="none"
              showsVerticalScrollIndicator={true}
              // v8.0.4 FlatList perf props — cheap virtualisation gains.
              windowSize={5}
              maxToRenderPerBatch={10}
              removeClippedSubviews={true}
              initialNumToRender={12}
              renderItem={({ item }) => {
                const isMine = item.device_id === deviceIdRef.current;
                return (
                  <SwipeableRow
                    onReply={() => startReply(item)}
                    accentColor={colors.accentBlue}
                    isMine={isMine}
                  >
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
                          selectable
                        >
                          {item.nickname}
                        </Text>

                        {/* v8.1.5 — Inline reply preview inside the bubble.
                            Coloured bar on the left, original nickname
                            in bold, then snippet or media hint. */}
                        {item.reply_to ? (
                          <View
                            style={[
                              styles.replyInside,
                              {
                                backgroundColor: isMine
                                  ? "rgba(255,255,255,0.14)"
                                  : "rgba(255,255,255,0.05)",
                                borderLeftColor: isMine ? "#fff" : colors.accentBlue,
                              },
                            ]}
                          >
                            <Text
                              style={[
                                styles.replyInsideNick,
                                { color: isMine ? "#fff" : colors.accentBlue },
                              ]}
                              numberOfLines={1}
                            >
                              {item.reply_to.nickname}
                            </Text>
                            <Text
                              style={[
                                styles.replyInsideSnippet,
                                { color: isMine ? "rgba(255,255,255,0.85)" : colors.textSecondary },
                              ]}
                              numberOfLines={2}
                            >
                              {item.reply_to.has_audio
                                ? "🎤 Voice note"
                                : item.reply_to.has_image
                                  ? "📷 Photo"
                                  : (item.reply_to.snippet || "")}
                            </Text>
                          </View>
                        ) : null}

                        {item.image_data ? (
                          <Image
                            source={{ uri: item.image_data }}
                            style={styles.attachmentImage}
                            resizeMode="cover"
                          />
                        ) : null}

                        {/* v8.1.5 — Voice note bubble. Play/pause button
                            + duration + waveform placeholder. */}
                        {item.audio_data ? (
                          <TouchableOpacity
                            onPress={() => togglePlayback(item)}
                            activeOpacity={0.75}
                            style={[
                              styles.voiceRow,
                              { backgroundColor: isMine ? "rgba(255,255,255,0.15)" : colors.surfaceAlt },
                            ]}
                          >
                            <Ionicons
                              name={playingId === item.id ? "pause" : "play"}
                              size={18}
                              color={isMine ? "#fff" : colors.accentBlue}
                            />
                            <View style={{ flex: 1 }}>
                              <View
                                style={[
                                  styles.voiceWave,
                                  { backgroundColor: isMine ? "rgba(255,255,255,0.35)" : colors.border },
                                ]}
                              />
                              <Text
                                style={[
                                  styles.voiceDur,
                                  { color: isMine ? "rgba(255,255,255,0.9)" : colors.textSecondary },
                                ]}
                              >
                                {fmtDuration(item.audio_duration_ms)}
                              </Text>
                            </View>
                          </TouchableOpacity>
                        ) : null}

                        {item.text ? (
                          <Text
                            style={[styles.text, { color: isMine ? "#fff" : colors.textPrimary }]}
                            selectable
                          >
                            {item.text}
                          </Text>
                        ) : null}
                      </View>
                    </View>
                  </SwipeableRow>
                );
              }}
            />
          </View>
        )}

        {nickname !== null && (
          <View>
            {/* v8.12.19 — Online users indicator strip. Sits at the
                bottom of the slideable chat frame, right above the
                composer. Small green dot + "N users online" text so
                the user can tell how many peers are currently watching
                the chat. */}
            <View
              style={[
                styles.onlineStrip,
                {
                  backgroundColor: colors.surface,
                  borderTopColor: colors.border,
                },
              ]}
              testID="chat-online-count"
            >
              <View style={styles.onlineDot} />
              <Text style={[styles.onlineText, { color: colors.textMuted }]}>
                {onlineCount > 0
                  ? `${onlineCount.toLocaleString()} ${onlineCount === 1 ? "user" : "users"} online`
                  : "\u2014"}
              </Text>
            </View>
            {/* v8.1.5 — Reply preview strip above composer (WhatsApp-style). */}
            {replyTo ? (
              <View style={[styles.replyPreview, { backgroundColor: colors.surfaceAlt, borderTopColor: colors.border }]}>
                <View style={[styles.replyPreviewBar, { backgroundColor: colors.accentBlue }]} />
                <View style={{ flex: 1 }}>
                  <Text style={[styles.replyPreviewNick, { color: colors.accentBlue }]} numberOfLines={1}>
                    Replying to {replyTo.nickname}
                  </Text>
                  <Text style={[styles.replyPreviewSnip, { color: colors.textSecondary }]} numberOfLines={1}>
                    {replyTo.has_audio
                      ? "🎤 Voice note"
                      : replyTo.has_image
                        ? "📷 Photo"
                        : (replyTo.snippet || "")}
                  </Text>
                </View>
                {replyTo.image_thumb ? (
                  <Image source={{ uri: replyTo.image_thumb }} style={styles.replyThumb} />
                ) : null}
                <TouchableOpacity onPress={clearReply} hitSlop={10} testID="reply-cancel">
                  <Ionicons name="close" size={20} color={colors.textMuted} />
                </TouchableOpacity>
              </View>
            ) : null}

            {/* v8.1.5 — Recording state overlay strip. Shows live timer +
                "slide to cancel" hint. */}
            {recorderState.isRecording ? (
              <View
                style={[
                  styles.recordingStrip,
                  {
                    backgroundColor: voiceCancelling ? "#7f1d1d" : colors.accentBlue,
                  },
                ]}
              >
                <Ionicons
                  name={voiceCancelling ? "trash" : "radio-button-on"}
                  size={14}
                  color="#fff"
                />
                <Text style={styles.recordingText}>
                  {voiceCancelling
                    ? "Release to cancel"
                    : `Recording…  ${fmtDuration(voiceElapsedMs)}  ·  slide ← to cancel`}
                </Text>
                <View style={{ flex: 1 }} />
                <Text style={styles.recordingText}>
                  {Math.max(0, VOICE_MAX_SECONDS - Math.floor(voiceElapsedMs / 1000))}s left
                </Text>
              </View>
            ) : null}

            <View
              style={[
                styles.inputRow,
                {
                  backgroundColor: colors.surface,
                  borderTopColor: colors.border,
                  paddingBottom: Math.max(insets.bottom, 10),
                },
              ]}
            >
              <TouchableOpacity
                onPress={pickAttachment}
                disabled={attaching || sending || recorderState.isRecording}
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
                  placeholder={
                    recorderState.isRecording ? "Recording voice note…" : "Type a message…"
                  }
                  placeholderTextColor={colors.textMuted}
                  multiline
                  editable={!recorderState.isRecording}
                  blurOnSubmit={false}
                  onFocus={() => {
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
              {/* v8.1.5 — Mic button (press-and-hold to record).
                  When user is typing/has text/attachment, show send
                  arrow instead. */}
              {canSend ? (
                <TouchableOpacity
                  onPress={() => sendMessage()}
                  disabled={!canSend}
                  testID="chat-send"
                  style={[
                    styles.sendBtn,
                    {
                      backgroundColor: colors.accentBlue,
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
              ) : (
                <View
                  {...micPanResponder.panHandlers}
                  style={[
                    styles.sendBtn,
                    {
                      backgroundColor: recorderState.isRecording
                        ? (voiceCancelling ? "#dc2626" : colors.accentBlue)
                        : colors.surfaceHighlight,
                    },
                  ]}
                  testID="chat-mic"
                >
                  <Ionicons
                    name="mic"
                    size={20}
                    color={recorderState.isRecording ? "#fff" : colors.textPrimary}
                  />
                </View>
              )}
            </View>
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
  // v8.1.5 additions
  replyInside: {
    borderLeftWidth: 3,
    paddingLeft: 8,
    paddingRight: 6,
    paddingVertical: 4,
    borderRadius: 4,
    marginBottom: 4,
  },
  replyInsideNick: { fontSize: 10, fontWeight: "800" },
  replyInsideSnippet: { fontSize: 11, marginTop: 1 },
  replyPreview: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderTopWidth: 0.5,
  },
  replyPreviewBar: { width: 3, alignSelf: "stretch", borderRadius: 2, minHeight: 32 },
  replyPreviewNick: { fontSize: 11, fontWeight: "800" },
  replyPreviewSnip: { fontSize: 11, marginTop: 1 },
  replyThumb: { width: 32, height: 32, borderRadius: 4 },
  recordingStrip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingHorizontal: 12,
    paddingVertical: 6,
  },
  recordingText: { color: "#fff", fontSize: 11, fontWeight: "600" },
  voiceRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    borderRadius: 20,
    paddingHorizontal: 8,
    paddingVertical: 6,
    minWidth: 160,
    marginBottom: 2,
  },
  voiceWave: { height: 2, borderRadius: 1, marginBottom: 2 },
  voiceDur: { fontSize: 10, fontWeight: "600" },
  swipeReplyIcon: {
    position: "absolute",
    top: 0,
    bottom: 0,
    justifyContent: "center",
    alignItems: "center",
    width: 40,
  },
  // v8.12.19 — Online users footer strip (sits above the composer).
  onlineStrip: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    paddingHorizontal: 12,
    paddingVertical: 4,
    borderTopWidth: 0.5,
  },
  onlineDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    backgroundColor: "#22c55e",
  },
  onlineText: {
    fontSize: 10,
    fontWeight: "600",
    letterSpacing: 0.2,
  },
});

// v8.1.5 — SwipeableRow: horizontal pan gesture wrapper that slides the
// child left/right by up to REPLY_SWIPE_MAX pixels. Fires `onReply`
// when released past REPLY_SWIPE_TRIGGER. Reveals a coloured reply
// icon on the side opposite to the swipe direction (mimics WhatsApp).
function SwipeableRow({
  children,
  onReply,
  accentColor,
  isMine,
}: {
  children: React.ReactNode;
  onReply: () => void;
  accentColor: string;
  isMine: boolean;
}) {
  const translateX = useRef(new Animated.Value(0)).current;
  const [progress, setProgress] = useState(0); // 0..1 for icon opacity
  const responder = useMemo(
    () =>
      PanResponder.create({
        // Only claim the gesture when the movement is clearly horizontal;
        // otherwise let the parent FlatList handle vertical scrolling.
        onStartShouldSetPanResponder: () => false,
        onMoveShouldSetPanResponder: (_e, g) =>
          Math.abs(g.dx) > 12 && Math.abs(g.dx) > Math.abs(g.dy) * 1.4,
        onPanResponderMove: (_e, g) => {
          // Only allow LEFT swipe (dx < 0) per user's spec ("Swipe ke
          // kiri saja"). Right swipe becomes a no-op.
          const dx = Math.min(0, Math.max(-REPLY_SWIPE_MAX, g.dx));
          translateX.setValue(dx);
          setProgress(Math.min(1, Math.abs(dx) / REPLY_SWIPE_TRIGGER));
        },
        onPanResponderRelease: (_e, g) => {
          const triggered = g.dx <= -REPLY_SWIPE_TRIGGER;
          Animated.spring(translateX, {
            toValue: 0,
            useNativeDriver: true,
            friction: 8,
            tension: 80,
          }).start();
          setProgress(0);
          if (triggered) onReply();
        },
        onPanResponderTerminate: () => {
          Animated.spring(translateX, { toValue: 0, useNativeDriver: true, friction: 8 }).start();
          setProgress(0);
        },
      }),
    [translateX, onReply],
  );

  return (
    <View style={{ position: "relative" }} {...responder.panHandlers}>
      {/* Reply icon revealed under the bubble on the right side (since
          bubble slides left). Fades in with progress. */}
      <View style={[styles.swipeReplyIcon, { right: 4, opacity: progress }]}>
        <View
          style={{
            width: 32,
            height: 32,
            borderRadius: 16,
            backgroundColor: accentColor + "26",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <Ionicons name="arrow-undo" size={16} color={accentColor} />
        </View>
      </View>
      <Animated.View style={{ transform: [{ translateX }] }}>
        {children}
      </Animated.View>
      {/* silence "unused" lint for isMine — reserved for future use */}
      {isMine ? null : null}
    </View>
  );
}
