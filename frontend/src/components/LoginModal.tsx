import { Ionicons } from "@expo/vector-icons";
import * as Clipboard from "expo-clipboard";
import React, { useEffect, useState } from "react";
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Modal,
  Platform,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from "react-native";

import { useAuth } from "@/src/auth/AuthContext";
import { useI18n } from "@/src/i18n/I18nContext";
import { useTheme } from "@/src/theme/ThemeContext";
import { API_BASE } from "@/src/lib/api";

type Props = {
  visible: boolean;
  onClose: () => void;
};

export default function LoginModal({ visible, onClose }: Props) {
  const { colors } = useTheme();
  const { t } = useI18n();
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [whoami, setWhoami] = useState<{ backend_origin: string; db_name: string; codes_count: number; admin_tool_url: string } | null>(null);
  const [copied, setCopied] = useState(false);

  // Fetch backend fingerprint when modal opens — helps user verify APK & admin
  // are pointed to the SAME backend / database.
  useEffect(() => {
    if (!visible) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${API_BASE}/whoami`);
        const data = await res.json();
        if (!cancelled) setWhoami(data);
      } catch {
        if (!cancelled) setWhoami(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [visible]);

  const copyAdminUrl = async () => {
    if (!whoami?.admin_tool_url) return;
    try {
      await Clipboard.setStringAsync(whoami.admin_tool_url);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {}
  };

  const reset = () => {
    setEmail("");
    setCode("");
    setError("");
    setBusy(false);
  };

  const submit = async () => {
    setError("");
    setBusy(true);
    try {
      const res = await login(email, code);
      if (res.ok) {
        reset();
        onClose();
      } else {
        setError(res.error || "Login gagal.");
      }
    } finally {
      setBusy(false);
    }
  };

  const close = () => {
    reset();
    onClose();
  };

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={close}>
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : undefined}
        style={[styles.overlay, { backgroundColor: colors.overlay }]}
      >
        <View style={[styles.box, { backgroundColor: colors.surface, borderColor: colors.border }]}>
          <View style={styles.header}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
              <Ionicons name="key" size={18} color={colors.accentBlue} />
              <Text style={[styles.title, { color: colors.textPrimary }]}>{t("login_modal_title")}</Text>
            </View>
            <TouchableOpacity onPress={close} testID="login-close-button" hitSlop={8}>
              <Ionicons name="close" size={22} color={colors.textMuted} />
            </TouchableOpacity>
          </View>

          <Text style={[styles.sub, { color: colors.textMuted }]}>
            {t("login_modal_body")}
          </Text>

          <Text style={[styles.label, { color: colors.textMuted }]}>EMAIL</Text>
          <TextInput
            value={email}
            onChangeText={setEmail}
            placeholder="anda@example.com"
            placeholderTextColor={colors.textMuted}
            autoCapitalize="none"
            keyboardType="email-address"
            autoCorrect={false}
            testID="login-email-input"
            style={[styles.input, { color: colors.textPrimary, borderColor: colors.border, backgroundColor: colors.surfaceAlt }]}
          />

          <Text style={[styles.label, { color: colors.textMuted, marginTop: 12 }]}>UNLOCK CODE</Text>
          <TextInput
            value={code}
            onChangeText={(t) => setCode(t.toUpperCase())}
            placeholder="XXXX-XXXX-XXXX"
            placeholderTextColor={colors.textMuted}
            autoCapitalize="characters"
            autoCorrect={false}
            testID="login-code-input"
            style={[styles.input, styles.codeInput, { color: colors.textPrimary, borderColor: colors.border, backgroundColor: colors.surfaceAlt }]}
          />

          {error ? (
            <Text style={[styles.error, { color: colors.accentDown }]} testID="login-error">
              {error}
            </Text>
          ) : null}

          {/* Backend fingerprint — critical for debugging Preview vs Production DB mismatch */}
          {whoami ? (
            <View style={[styles.whoamiBox, { borderColor: colors.border, backgroundColor: colors.surfaceAlt }]}>
              <View style={{ flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 4 }}>
                <Ionicons name="server" size={11} color={colors.textMuted} />
                <Text style={[styles.whoamiLabel, { color: colors.textMuted }]}>APK ini terhubung ke:</Text>
              </View>
              <Text style={[styles.whoamiUrl, { color: colors.accentBlue }]} numberOfLines={2} selectable>
                {whoami.backend_origin}
              </Text>
              <Text style={[styles.whoamiMeta, { color: colors.textMuted }]}>
                DB: <Text style={{ color: colors.textPrimary, fontWeight: "700" }}>{whoami.db_name}</Text>
                {"   "}Codes: <Text style={{ color: colors.textPrimary, fontWeight: "700" }}>{whoami.codes_count}</Text>
              </Text>
              <View style={styles.whoamiDivider} />
              <Text style={[styles.whoamiLabel, { color: colors.textMuted, marginBottom: 4 }]}>
                Buka Admin Tool di URL YANG SAMA:
              </Text>
              <TouchableOpacity onPress={copyAdminUrl} activeOpacity={0.7} testID="copy-admin-url">
                <View style={[styles.copyUrlBox, { borderColor: colors.accentBlue }]}>
                  <Text style={[styles.copyUrlText, { color: colors.textPrimary }]} numberOfLines={2} selectable>
                    {whoami.admin_tool_url}
                  </Text>
                  <Ionicons name={copied ? "checkmark-circle" : "copy-outline"} size={16} color={copied ? colors.accentUp : colors.accentBlue} />
                </View>
              </TouchableOpacity>
              {copied ? (
                <Text style={[styles.copiedHint, { color: colors.accentUp }]}>URL disalin ke clipboard ✓</Text>
              ) : null}
            </View>
          ) : null}

          <TouchableOpacity
            onPress={submit}
            disabled={busy}
            testID="login-submit-button"
            style={[styles.submitBtn, { backgroundColor: colors.accentBlue, opacity: busy ? 0.6 : 1 }]}
          >
            {busy ? (
              <ActivityIndicator color="#fff" size="small" />
            ) : (
              <>
                <Ionicons name="lock-open" size={16} color="#fff" />
                <Text style={styles.submitText}>UNLOCK</Text>
              </>
            )}
          </TouchableOpacity>

          <Text style={[styles.hint, { color: colors.textMuted }]}>
            Belum punya unlock code? Hubungi admin dan berikan email Anda.
          </Text>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  overlay: { flex: 1, alignItems: "center", justifyContent: "center", padding: 24 },
  box: { width: "100%", maxWidth: 380, borderRadius: 14, borderWidth: 1, padding: 18 },
  header: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  title: { fontSize: 16, fontWeight: "700" },
  sub: { fontSize: 12, lineHeight: 17, marginTop: 8, marginBottom: 12 },
  label: { fontSize: 10, letterSpacing: 0.6, marginBottom: 4 },
  input: { height: 44, borderRadius: 10, borderWidth: 1, paddingHorizontal: 12, fontSize: 14 },
  codeInput: { letterSpacing: 1.5, fontVariant: ["tabular-nums"], textAlign: "center", fontSize: 15, fontWeight: "700" },
  error: { fontSize: 12, marginTop: 10, lineHeight: 17 },
  submitBtn: {
    marginTop: 16, height: 44, borderRadius: 10,
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
  },
  submitText: { color: "#fff", fontSize: 13, fontWeight: "700", letterSpacing: 0.8 },
  hint: { fontSize: 10, textAlign: "center", marginTop: 14, lineHeight: 14 },
  whoamiBox: {
    marginTop: 14,
    padding: 10,
    borderRadius: 10,
    borderWidth: 1,
  },
  whoamiLabel: { fontSize: 10, letterSpacing: 0.4 },
  whoamiUrl: { fontSize: 11, fontWeight: "700", marginBottom: 4 },
  whoamiMeta: { fontSize: 10 },
  whoamiDivider: { height: 1, backgroundColor: "rgba(255,255,255,0.08)", marginVertical: 8 },
  copyUrlBox: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8,
    borderWidth: 1,
    borderStyle: "dashed",
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 8,
  },
  copyUrlText: { flex: 1, fontSize: 10.5, fontWeight: "600" },
  copiedHint: { fontSize: 10, marginTop: 6, textAlign: "center", fontWeight: "700" },
});
