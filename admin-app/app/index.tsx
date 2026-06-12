import { Ionicons } from "@expo/vector-icons";
import * as Clipboard from "expo-clipboard";
import React, { useState } from "react";
import {
  ActivityIndicator,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { generateUnlockCode } from "@/lib/unlockCode";

type History = { email: string; code: string; at: string };

export default function AdminGenerator() {
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [history, setHistory] = useState<History[]>([]);
  const [error, setError] = useState("");

  const generate = async () => {
    setError("");
    setCopied(false);
    const trimmed = email.trim().toLowerCase();
    if (!trimmed) {
      setError("Masukkan email user dulu.");
      return;
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmed)) {
      setError("Format email tidak valid.");
      return;
    }
    setBusy(true);
    try {
      const c = await generateUnlockCode(trimmed);
      setCode(c);
      setHistory((h) => [
        { email: trimmed, code: c, at: new Date().toLocaleTimeString("id-ID") },
        ...h.filter((x) => x.email !== trimmed),
      ].slice(0, 20));
    } finally {
      setBusy(false);
    }
  };

  const copy = async () => {
    if (!code) return;
    await Clipboard.setStringAsync(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const copyMessage = async () => {
    if (!code || !email) return;
    const msg = `Hi! Berikut unlock code KevinAI Pro Anda:\n\nEmail: ${email.trim().toLowerCase()}\nUnlock Code: ${code}\n\nBuka app KevinAI Pro → tombol LOGIN (pojok kanan atas) → isi email & code. Sekali login berlaku selamanya.`;
    await Clipboard.setStringAsync(msg);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <ScrollView contentContainerStyle={{ paddingBottom: 32 }}>
        <View style={styles.header}>
          <View style={styles.headerIcon}>
            <Ionicons name="key" size={24} color="#F0B90B" />
          </View>
          <Text style={styles.title}>KevinAI Pro</Text>
          <Text style={styles.subtitle}>Unlock Code Generator</Text>
          <Text style={styles.warn}>⚠ ADMIN ONLY · Jangan distribusikan APK ini</Text>
        </View>

        <View style={styles.card}>
          <Text style={styles.label}>EMAIL USER</Text>
          <TextInput
            value={email}
            onChangeText={setEmail}
            placeholder="user@example.com"
            placeholderTextColor="#5E6673"
            autoCapitalize="none"
            keyboardType="email-address"
            autoCorrect={false}
            style={styles.input}
            testID="admin-email-input"
          />

          {error ? <Text style={styles.error}>{error}</Text> : null}

          <TouchableOpacity
            onPress={generate}
            disabled={busy}
            style={[styles.genBtn, { opacity: busy ? 0.6 : 1 }]}
            testID="admin-generate-button"
          >
            {busy ? (
              <ActivityIndicator color="#0B0E11" size="small" />
            ) : (
              <>
                <Ionicons name="construct" size={16} color="#0B0E11" />
                <Text style={styles.genBtnText}>GENERATE UNLOCK CODE</Text>
              </>
            )}
          </TouchableOpacity>

          {code ? (
            <View style={styles.resultBox}>
              <Text style={styles.resultLabel}>UNLOCK CODE</Text>
              <Text style={styles.codeBig} selectable testID="admin-code-output">{code}</Text>
              <Text style={styles.resultEmail}>untuk: {email.trim().toLowerCase()}</Text>
              <View style={styles.actionRow}>
                <TouchableOpacity onPress={copy} style={styles.copyBtn} testID="admin-copy-code-button">
                  <Ionicons name="copy" size={14} color="#EAECEF" />
                  <Text style={styles.copyBtnText}>Salin Code</Text>
                </TouchableOpacity>
                <TouchableOpacity onPress={copyMessage} style={[styles.copyBtn, { backgroundColor: "#2962FF" }]} testID="admin-copy-message-button">
                  <Ionicons name="chatbubble-ellipses" size={14} color="#fff" />
                  <Text style={[styles.copyBtnText, { color: "#fff" }]}>Salin Pesan</Text>
                </TouchableOpacity>
              </View>
              {copied ? <Text style={styles.copied}>✓ Berhasil disalin</Text> : null}
            </View>
          ) : null}
        </View>

        {history.length > 0 && (
          <View style={[styles.card, { marginTop: 12 }]}>
            <Text style={styles.label}>HISTORI ({history.length})</Text>
            {history.map((h, i) => (
              <View key={`${h.email}-${i}`} style={styles.histRow}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.histEmail} numberOfLines={1}>{h.email}</Text>
                  <Text style={styles.histTime}>{h.at}</Text>
                </View>
                <Text style={styles.histCode} selectable>{h.code}</Text>
              </View>
            ))}
          </View>
        )}

        <Text style={styles.footer}>
          🔒 Code dihitung lokal (offline). Hanya admin yang punya SECRET dapat menghasilkan kode yang valid.
        </Text>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: "#0B0E11" },
  header: { padding: 24, alignItems: "center" },
  headerIcon: {
    width: 56, height: 56, borderRadius: 28,
    backgroundColor: "#F0B90B22", alignItems: "center", justifyContent: "center",
    borderWidth: 1, borderColor: "#F0B90B",
  },
  title: { fontSize: 22, fontWeight: "700", color: "#EAECEF", marginTop: 10 },
  subtitle: { fontSize: 13, color: "#848E9C", marginTop: 2 },
  warn: { fontSize: 10, color: "#F6465D", marginTop: 12, letterSpacing: 0.5 },
  card: {
    marginHorizontal: 16, padding: 16, borderRadius: 14,
    backgroundColor: "#181A20", borderWidth: 1, borderColor: "#2B3139",
  },
  label: { fontSize: 10, color: "#848E9C", letterSpacing: 0.7, marginBottom: 6 },
  input: {
    height: 46, borderRadius: 10, borderWidth: 1, borderColor: "#2B3139",
    backgroundColor: "#1E2329", color: "#EAECEF",
    paddingHorizontal: 12, fontSize: 14,
  },
  error: { color: "#F6465D", fontSize: 12, marginTop: 8 },
  genBtn: {
    marginTop: 14, height: 46, borderRadius: 10, backgroundColor: "#F0B90B",
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
  },
  genBtnText: { color: "#0B0E11", fontWeight: "800", fontSize: 13, letterSpacing: 0.7 },
  resultBox: {
    marginTop: 18, padding: 14, borderRadius: 12,
    backgroundColor: "#0B0E11", borderWidth: 1, borderColor: "#F0B90B",
  },
  resultLabel: { fontSize: 10, color: "#F0B90B", letterSpacing: 0.8 },
  codeBig: {
    fontSize: 28, fontWeight: "800", color: "#F0B90B",
    fontVariant: ["tabular-nums"], letterSpacing: 2, marginTop: 4, textAlign: "center",
  },
  resultEmail: { fontSize: 11, color: "#848E9C", textAlign: "center", marginTop: 6 },
  actionRow: { flexDirection: "row", gap: 8, marginTop: 12 },
  copyBtn: {
    flex: 1, height: 38, borderRadius: 8, backgroundColor: "#2B3139",
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
  },
  copyBtnText: { color: "#EAECEF", fontSize: 12, fontWeight: "700" },
  copied: { color: "#0ECB81", fontSize: 11, textAlign: "center", marginTop: 8 },
  histRow: {
    flexDirection: "row", alignItems: "center",
    paddingVertical: 8, borderBottomWidth: StyleSheet.hairlineWidth, borderColor: "#2B3139",
  },
  histEmail: { color: "#EAECEF", fontSize: 13, fontWeight: "600" },
  histTime: { color: "#5E6673", fontSize: 10, marginTop: 2 },
  histCode: { color: "#F0B90B", fontSize: 12, fontWeight: "700", fontVariant: ["tabular-nums"] },
  footer: { color: "#5E6673", fontSize: 10, textAlign: "center", marginTop: 18, paddingHorizontal: 24, lineHeight: 14 },
});
