import { Ionicons } from "@expo/vector-icons";
import { router, Stack } from "expo-router";
import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  FlatList,
  KeyboardAvoidingView,
  Platform,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { getDeviceId } from "@/src/lib/deviceId";
import { useSubscription } from "@/src/lib/subscriptionContext";
import { useTheme } from "@/src/theme/ThemeContext";
import { storage } from "@/src/utils/storage";

const NICKNAME_KEY = "aicrypstockpro.chat.nickname";
const POLL_INTERVAL_MS = 3000;
const RATE_LIMIT_MS = 3000;
const MAX_MSG_LEN = 500;
const MAX_NICK_LEN = 20;

type Msg = {
  id: string;
  text: string;
  nickname: string;
  device_id: string;
  created_at: string;
};

function backendBase(): string {
  const RAW = process.env.EXPO_PUBLIC_BACKEND_URL ?? "";
  return `${RAW.replace(/\/+$/, "")}/api`;
}

function isValidNickname(n: string): boolean {
  return /^[A-Za-z0-9_\.\-]{3,20}$/.test(n);
}

export default function ChatScreen() {
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const { isPremium } = useSubscription();

  const [nickname, setNickname] = useState<string | null>(null);
  const [nickInput, setNickInput] = useState("");
  const [nickError, setNickError] = useState<string | null>(null);

  const [messages, setMessages] = useState<Msg[]>([]);
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [input, setInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const lastSentRef = useRef<number>(0);
  const deviceIdRef = useRef<string>("");
  const listRef = useRef<FlatList<Msg>>(null);

  // Load nickname + device id
  useEffect(() => {
    (async () => {
      const nk = await storage.getItem<string | null>(NICKNAME_KEY, null);
      if (nk) setNickname(nk);
      deviceIdRef.current = await getDeviceId();
    })();
  }, []);

  // Initial fetch + polling
  const fetchMessages = useCallback(async () => {
    try {
      const res = await fetch(`${backendBase()}/chat/messages?limit=100`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const list: Msg[] = data.messages ?? [];
      setMessages(list);
      setError(null);
    } catch (e: any) {
      setError(e?.message ?? "Failed to load messages");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchMessages();
    const id = setInterval(fetchMessages, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [fetchMessages]);

  // Auto-scroll on new messages
  useEffect(() => {
    if (messages.length > 0) {
      setTimeout(() => listRef.current?.scrollToEnd({ animated: true }), 60);
    }
  }, [messages.length]);

  const saveNickname = async () => {
    const clean = nickInput.trim();
    if (!isValidNickname(clean)) {
      setNickError("3-20 chars, letters/numbers/._- only");
      return;
    }
    setNickError(null);
    await storage.setItem(NICKNAME_KEY, clean);
    setNickname(clean);
  };

  const sendMessage = async () => {
    const text = input.trim();
    if (!text) return;
    if (!isPremium) {
      Alert.alert("Premium Only", "Only premium subscribers can post in the chatroom.");
      return;
    }
    if (text.length > MAX_MSG_LEN) {
      Alert.alert("Too Long", `Max ${MAX_MSG_LEN} characters.`);
      return;
    }
    const now = Date.now();
    if (now - lastSentRef.current < RATE_LIMIT_MS) {
      Alert.alert(
        "Slow Down",
        `Please wait ${Math.ceil(
          (RATE_LIMIT_MS - (now - lastSentRef.current)) / 1000,
        )}s before sending again.`,
      );
      return;
    }
    setSending(true);
    try {
      const res = await fetch(`${backendBase()}/chat/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text,
          nickname: nickname ?? "guest",
          device_id: deviceIdRef.current,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Send failed" }));
        Alert.alert("Send Failed", err.detail ?? "Please try again");
      } else {
        setInput("");
        lastSentRef.current = now;
        fetchMessages();
      }
    } catch (e: any) {
      Alert.alert("Network Error", e?.message ?? String(e));
    } finally {
      setSending(false);
    }
  };

  // ---- Nickname setup screen ----
  if (!nickname) {
    return (
      <View style={[styles.container, { backgroundColor: colors.background }]}>
        <Stack.Screen options={{ title: "Chat Room" }} />
        <View style={{ padding: 24, flex: 1, justifyContent: "center" }}>
          <Ionicons
            name="chatbubbles"
            size={48}
            color={colors.accentBlue}
            style={{ alignSelf: "center", marginBottom: 16 }}
          />
          <Text style={[styles.setupTitle, { color: colors.textPrimary }]}>
            Welcome to Global Chat
          </Text>
          <Text style={[styles.setupBody, { color: colors.textMuted }]}>
            Pick a nickname to join the worldwide traders&apos; community.
          </Text>
          <TextInput
            value={nickInput}
            onChangeText={setNickInput}
            placeholder="Your nickname (e.g. Trader_BTC)"
            placeholderTextColor={colors.textMuted}
            maxLength={MAX_NICK_LEN}
            autoCapitalize="none"
            autoCorrect={false}
            style={[
              styles.nickInput,
              {
                backgroundColor: colors.surface,
                borderColor: colors.border,
                color: colors.textPrimary,
              },
            ]}
          />
          {nickError ? (
            <Text style={styles.errText}>{nickError}</Text>
          ) : (
            <Text style={[styles.setupHint, { color: colors.textMuted }]}>
              3-20 characters · letters, numbers, . _ -
            </Text>
          )}
          <TouchableOpacity
            onPress={saveNickname}
            style={[styles.saveBtn, { backgroundColor: colors.accentBlue }]}
          >
            <Text style={styles.saveBtnText}>JOIN CHAT</Text>
          </TouchableOpacity>
        </View>
      </View>
    );
  }

  // ---- Main chat screen ----
  return (
    <KeyboardAvoidingView
      behavior={Platform.OS === "ios" ? "padding" : "height"}
      keyboardVerticalOffset={0}
      style={[styles.container, { backgroundColor: colors.background }]}
    >
      <Stack.Screen options={{ title: `Chat · ${nickname}` }} />

      {loading ? (
        <View style={styles.loader}>
          <ActivityIndicator size="large" color={colors.accentBlue} />
        </View>
      ) : (
        <FlatList
          ref={listRef}
          data={messages}
          keyExtractor={(m) => m.id}
          contentContainerStyle={{ padding: 12, paddingBottom: 16 }}
          renderItem={({ item }) => {
            const isMine = item.device_id === deviceIdRef.current;
            const bubbleColor = isMine ? colors.accentBlue : colors.surface;
            const textColor = isMine ? "#fff" : colors.textPrimary;
            return (
              <View
                style={[
                  styles.msgRow,
                  { justifyContent: isMine ? "flex-end" : "flex-start" },
                ]}
              >
                <View
                  style={[
                    styles.bubble,
                    {
                      backgroundColor: bubbleColor,
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
                  <Text style={[styles.msgText, { color: textColor }]}>
                    {item.text}
                  </Text>
                  <Text
                    style={[
                      styles.ts,
                      { color: isMine ? "#fff" : colors.textMuted },
                    ]}
                  >
                    {new Date(item.created_at).toLocaleTimeString([], {
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </Text>
                </View>
              </View>
            );
          }}
          ListEmptyComponent={
            <View style={{ padding: 40, alignItems: "center" }}>
              <Ionicons name="chatbubbles-outline" size={40} color={colors.textMuted} />
              <Text style={{ color: colors.textMuted, marginTop: 8, textAlign: "center" }}>
                No messages yet. Be the first to say hello!
              </Text>
            </View>
          }
        />
      )}

      {error ? (
        <Text style={[styles.errBar, { color: colors.accentDown }]}>{error}</Text>
      ) : null}

      {/* Input bar */}
      <View
        style={[
          styles.inputRow,
          {
            backgroundColor: colors.surface,
            borderTopColor: colors.border,
            paddingBottom: (insets.bottom || 0) + 6,
          },
        ]}
      >
        <TextInput
          value={input}
          onChangeText={setInput}
          placeholder={isPremium ? "Type a message…" : "Premium only — subscribe to chat"}
          placeholderTextColor={colors.textMuted}
          editable={isPremium}
          multiline
          maxLength={MAX_MSG_LEN}
          blurOnSubmit={false}
          textAlignVertical="top"
          style={[
            styles.input,
            {
              backgroundColor: colors.surfaceAlt,
              color: colors.textPrimary,
              borderColor: colors.border,
              opacity: isPremium ? 1 : 0.5,
            },
          ]}
        />
        <TouchableOpacity
          onPress={isPremium ? sendMessage : () => router.back()}
          disabled={sending || !input.trim()}
          style={[
            styles.sendBtn,
            {
              backgroundColor: isPremium && input.trim() ? colors.accentBlue : colors.surfaceHighlight,
              opacity: sending ? 0.6 : 1,
            },
          ]}
        >
          {sending ? (
            <ActivityIndicator size="small" color="#fff" />
          ) : (
            <Ionicons
              name={isPremium ? "arrow-up" : "star"}
              size={18}
              color="#fff"
            />
          )}
        </TouchableOpacity>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  loader: { flex: 1, alignItems: "center", justifyContent: "center" },
  msgRow: { flexDirection: "row", marginVertical: 4 },
  bubble: {
    maxWidth: "78%",
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 12,
    borderWidth: 0.5,
  },
  nick: { fontSize: 10, fontWeight: "800", letterSpacing: 0.4, marginBottom: 2 },
  msgText: { fontSize: 13, lineHeight: 18 },
  ts: { fontSize: 9, marginTop: 4, textAlign: "right", opacity: 0.85 },
  inputRow: {
    flexDirection: "row",
    alignItems: "flex-end",
    gap: 8,
    padding: 8,
    borderTopWidth: 0.5,
  },
  input: {
    flex: 1,
    minHeight: 40,
    maxHeight: 120,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 20,
    borderWidth: 1,
    fontSize: 13,
  },
  sendBtn: {
    width: 40,
    height: 40,
    borderRadius: 20,
    alignItems: "center",
    justifyContent: "center",
  },
  errBar: {
    fontSize: 11,
    textAlign: "center",
    paddingVertical: 4,
    fontStyle: "italic",
  },
  // Nickname setup
  setupTitle: {
    fontSize: 20,
    fontWeight: "900",
    textAlign: "center",
    marginBottom: 8,
  },
  setupBody: {
    fontSize: 13,
    textAlign: "center",
    marginBottom: 20,
    lineHeight: 19,
  },
  nickInput: {
    height: 46,
    borderRadius: 10,
    borderWidth: 1,
    paddingHorizontal: 14,
    fontSize: 15,
  },
  setupHint: {
    fontSize: 11,
    marginTop: 8,
    textAlign: "center",
  },
  errText: {
    fontSize: 11,
    marginTop: 8,
    textAlign: "center",
    color: "#ef4444",
  },
  saveBtn: {
    marginTop: 20,
    height: 48,
    borderRadius: 10,
    alignItems: "center",
    justifyContent: "center",
  },
  saveBtnText: {
    color: "#fff",
    fontSize: 14,
    fontWeight: "900",
    letterSpacing: 0.6,
  },
});
