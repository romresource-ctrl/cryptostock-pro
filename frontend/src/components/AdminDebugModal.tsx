/**
 * Admin-only Debug Modal — accessed via SECRET long-press on the "Ver x.y.z" text.
 * Shows backend fingerprint + admin tool URL. This is intentionally NOT visible
 * on any regular screen so end users cannot discover the admin URL.
 */
import { Ionicons } from "@expo/vector-icons";
import * as Clipboard from "expo-clipboard";
import React, { useEffect, useState } from "react";
import {
  Modal,
  Platform,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from "react-native";

import { API_BASE } from "@/src/lib/api";
import { useTheme } from "@/src/theme/ThemeContext";

type Whoami = {
  backend_origin: string;
  db_name: string;
  codes_count: number;
  admin_tool_url: string;
  server_time: string;
};

type Props = {
  visible: boolean;
  onClose: () => void;
};

export default function AdminDebugModal({ visible, onClose }: Props) {
  const { colors } = useTheme();
  const [data, setData] = useState<Whoami | null>(null);
  const [copiedField, setCopiedField] = useState<"origin" | "admin" | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!visible) return;
    let cancelled = false;
    setErr("");
    (async () => {
      try {
        const res = await fetch(`${API_BASE}/whoami`);
        const j = await res.json();
        if (!cancelled) setData(j);
      } catch (e: unknown) {
        if (!cancelled) setErr(String((e as Error)?.message ?? e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [visible]);

  const copy = async (value: string, field: "origin" | "admin") => {
    try {
      await Clipboard.setStringAsync(value);
      setCopiedField(field);
      setTimeout(() => setCopiedField(null), 1500);
    } catch {}
  };

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <View style={[styles.overlay, { backgroundColor: colors.overlay }]}>
        <View style={[styles.box, { backgroundColor: colors.surface, borderColor: colors.accentBlue }]}>
          <View style={styles.header}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
              <Ionicons name="shield-checkmark" size={18} color={colors.accentBlue} />
              <Text style={[styles.title, { color: colors.textPrimary }]}>Admin Debug (private)</Text>
            </View>
            <TouchableOpacity onPress={onClose} hitSlop={8}>
              <Ionicons name="close" size={22} color={colors.textMuted} />
            </TouchableOpacity>
          </View>

          <Text style={[styles.warn, { color: colors.textMuted }]}>
            Panel ini hanya untuk Anda (admin). Jangan tampilkan / screenshot ke user umum.
          </Text>

          {err ? (
            <Text style={[styles.err, { color: colors.accentDown }]}>{err}</Text>
          ) : !data ? (
            <Text style={[styles.err, { color: colors.textMuted }]}>Memuat…</Text>
          ) : (
            <>
              <Text style={[styles.label, { color: colors.textMuted }]}>BACKEND ORIGIN (APK terhubung ke)</Text>
              <TouchableOpacity onPress={() => copy(data.backend_origin, "origin")} activeOpacity={0.7}>
                <View style={[styles.field, { borderColor: colors.border, backgroundColor: colors.surfaceAlt }]}>
                  <Text style={[styles.fieldText, { color: colors.textPrimary }]} numberOfLines={2} selectable>
                    {data.backend_origin}
                  </Text>
                  <Ionicons
                    name={copiedField === "origin" ? "checkmark-circle" : "copy-outline"}
                    size={16}
                    color={copiedField === "origin" ? colors.accentUp : colors.accentBlue}
                  />
                </View>
              </TouchableOpacity>

              <View style={styles.metaRow}>
                <View>
                  <Text style={[styles.metaLabel, { color: colors.textMuted }]}>DB</Text>
                  <Text style={[styles.metaVal, { color: colors.textPrimary }]}>{data.db_name}</Text>
                </View>
                <View>
                  <Text style={[styles.metaLabel, { color: colors.textMuted }]}>Codes stored</Text>
                  <Text style={[styles.metaVal, { color: colors.textPrimary }]}>{data.codes_count}</Text>
                </View>
                <View>
                  <Text style={[styles.metaLabel, { color: colors.textMuted }]}>Platform</Text>
                  <Text style={[styles.metaVal, { color: colors.textPrimary }]}>{Platform.OS}</Text>
                </View>
              </View>

              <Text style={[styles.label, { color: colors.textMuted, marginTop: 10 }]}>ADMIN TOOL URL (buka di browser)</Text>
              <TouchableOpacity onPress={() => copy(data.admin_tool_url, "admin")} activeOpacity={0.7}>
                <View style={[styles.field, { borderColor: colors.accentBlue, backgroundColor: colors.surfaceAlt, borderStyle: "dashed" }]}>
                  <Text style={[styles.fieldText, { color: colors.textPrimary }]} numberOfLines={2} selectable>
                    {data.admin_tool_url}
                  </Text>
                  <Ionicons
                    name={copiedField === "admin" ? "checkmark-circle" : "copy-outline"}
                    size={16}
                    color={copiedField === "admin" ? colors.accentUp : colors.accentBlue}
                  />
                </View>
              </TouchableOpacity>
              {copiedField ? (
                <Text style={[styles.copied, { color: colors.accentUp }]}>URL disalin ke clipboard ✓</Text>
              ) : null}

              <Text style={[styles.tip, { color: colors.textMuted }]}>
                💡 Selalu generate unlock code dari URL Admin Tool di atas — URL yang berbeda = database yang berbeda = code tidak akan cocok.
              </Text>
            </>
          )}
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  overlay: { flex: 1, alignItems: "center", justifyContent: "center", padding: 20 },
  box: { width: "100%", maxWidth: 400, borderRadius: 14, borderWidth: 2, padding: 16 },
  header: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 8 },
  title: { fontSize: 15, fontWeight: "800" },
  warn: { fontSize: 11, lineHeight: 15, marginBottom: 12 },
  label: { fontSize: 10, letterSpacing: 0.6, marginBottom: 4, marginTop: 2, fontWeight: "700" },
  field: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8,
    borderRadius: 8,
    borderWidth: 1,
    paddingHorizontal: 10,
    paddingVertical: 9,
    marginBottom: 4,
  },
  fieldText: { flex: 1, fontSize: 11, fontWeight: "700" },
  metaRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    marginTop: 10,
    marginBottom: 4,
    paddingHorizontal: 4,
  },
  metaLabel: { fontSize: 9, letterSpacing: 0.4 },
  metaVal: { fontSize: 13, fontWeight: "800", marginTop: 2 },
  copied: { fontSize: 11, textAlign: "center", fontWeight: "700", marginTop: 6 },
  tip: { fontSize: 10.5, lineHeight: 15, marginTop: 12, fontStyle: "italic" },
  err: { fontSize: 12, marginTop: 8 },
});
