import { Ionicons } from "@expo/vector-icons";
import React, { useState } from "react";
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
import { useTheme } from "@/src/theme/ThemeContext";

type Props = {
  visible: boolean;
  onClose: () => void;
};

export default function LoginModal({ visible, onClose }: Props) {
  const { colors } = useTheme();
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

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
              <Text style={[styles.title, { color: colors.textPrimary }]}>Login KevinAI Pro</Text>
            </View>
            <TouchableOpacity onPress={close} testID="login-close-button" hitSlop={8}>
              <Ionicons name="close" size={22} color={colors.textMuted} />
            </TouchableOpacity>
          </View>

          <Text style={[styles.sub, { color: colors.textMuted }]}>
            Masukkan email Anda dan unlock code yang Anda terima dari admin.
            Sekali login, tidak perlu login ulang.
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
});
