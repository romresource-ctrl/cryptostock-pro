/**
 * AlertModal — bottom-sheet form for creating (or editing) a price alert.
 * Called from the detail page's "🔔 Alert" button.
 *
 * Fields:
 *   • Direction (above / below) — segmented toggle
 *   • Target price — decimal input, pre-filled with current price
 *   • Note (optional) — freeform
 */
import { Ionicons } from "@expo/vector-icons";
import React, { useState } from "react";
import {
  Modal,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useI18n } from "@/src/i18n/I18nContext";
import { useAlerts } from "@/src/lib/alerts";
import { useTheme } from "@/src/theme/ThemeContext";

type Props = {
  visible: boolean;
  onClose: () => void;
  market: string;
  symbol: string;
  currentPrice: number | null;
};

export default function AlertModal({
  visible, onClose, market, symbol, currentPrice,
}: Props) {
  const { colors } = useTheme();
  const { t } = useI18n();
  const alerts = useAlerts();
  const [direction, setDirection] = useState<"above" | "below">("above");
  const [target, setTarget] = useState<string>(
    currentPrice != null && Number.isFinite(currentPrice)
      ? String(currentPrice.toFixed(currentPrice < 1 ? 6 : 2))
      : "",
  );
  const [note, setNote] = useState<string>("");

  const targetNum = parseFloat(target);
  const canSave = Number.isFinite(targetNum) && targetNum > 0;

  const handleSave = () => {
    if (!canSave) return;
    alerts.add({
      market,
      symbol,
      direction,
      target: targetNum,
      note: note.trim() || undefined,
    });
    onClose();
  };

  return (
    <Modal
      visible={visible}
      transparent
      animationType="slide"
      onRequestClose={onClose}
    >
      <Pressable style={styles.backdrop} onPress={onClose}>
        <Pressable style={{ flex: 1 }} onPress={() => {}}>
          <SafeAreaView
            edges={["bottom"]}
            style={[
              styles.sheet,
              { backgroundColor: colors.surface, borderColor: colors.border },
            ]}
          >
            <View style={[styles.grabber, { backgroundColor: colors.border }]} />
            <View style={styles.header}>
              <TouchableOpacity onPress={onClose} testID="alert-cancel">
                <Text style={{ color: colors.textMuted, fontSize: 15 }}>
                  {t("common_cancel") || "Batal"}
                </Text>
              </TouchableOpacity>
              <Text style={[styles.title, { color: colors.textPrimary }]}>
                🔔 {t("alert_title") || "Buat Alarm Harga"}
              </Text>
              <TouchableOpacity
                onPress={handleSave}
                disabled={!canSave}
                testID="alert-save"
              >
                <Text
                  style={{
                    color: canSave ? colors.accentUp : colors.textMuted,
                    fontSize: 15,
                    fontWeight: "800",
                  }}
                >
                  {t("common_save") || "Simpan"}
                </Text>
              </TouchableOpacity>
            </View>

            <View style={{ paddingHorizontal: 16, paddingTop: 6 }}>
              <Text style={[styles.subtitle, { color: colors.textMuted }]}>
                {symbol.toUpperCase()} · {market}
              </Text>

              {/* Direction segmented control */}
              <Text style={[styles.label, { color: colors.textMuted }]}>
                {t("alert_direction") || "Notifikasi ketika harga"}
              </Text>
              <View style={styles.segmentRow}>
                <TouchableOpacity
                  onPress={() => setDirection("above")}
                  testID="alert-dir-above"
                  style={[
                    styles.segment,
                    {
                      backgroundColor:
                        direction === "above" ? colors.accentUp + "22" : colors.background,
                      borderColor: direction === "above" ? colors.accentUp : colors.border,
                    },
                  ]}
                >
                  <Ionicons name="arrow-up" size={16} color={colors.accentUp} />
                  <Text
                    style={{
                      color: direction === "above" ? colors.accentUp : colors.textMuted,
                      fontWeight: "800",
                    }}
                  >
                    {t("alert_above") || "Naik di atas"}
                  </Text>
                </TouchableOpacity>
                <TouchableOpacity
                  onPress={() => setDirection("below")}
                  testID="alert-dir-below"
                  style={[
                    styles.segment,
                    {
                      backgroundColor:
                        direction === "below" ? colors.accentDown + "22" : colors.background,
                      borderColor: direction === "below" ? colors.accentDown : colors.border,
                    },
                  ]}
                >
                  <Ionicons name="arrow-down" size={16} color={colors.accentDown} />
                  <Text
                    style={{
                      color: direction === "below" ? colors.accentDown : colors.textMuted,
                      fontWeight: "800",
                    }}
                  >
                    {t("alert_below") || "Turun di bawah"}
                  </Text>
                </TouchableOpacity>
              </View>

              {/* Target price */}
              <Text style={[styles.label, { color: colors.textMuted }]}>
                {t("alert_target") || "Harga target"}
              </Text>
              <TextInput
                testID="alert-target-input"
                value={target}
                onChangeText={setTarget}
                keyboardType="decimal-pad"
                placeholder="0.00"
                placeholderTextColor={colors.textMuted}
                style={[
                  styles.input,
                  {
                    color: colors.textPrimary,
                    borderColor: colors.border,
                    backgroundColor: colors.background,
                  },
                ]}
              />
              {currentPrice != null ? (
                <Text style={{ color: colors.textMuted, fontSize: 11.5, marginTop: 4 }}>
                  {t("alert_current_price") || "Harga sekarang"}: {currentPrice.toFixed(
                    currentPrice < 1 ? 6 : 2,
                  )}
                </Text>
              ) : null}

              {/* Note */}
              <Text style={[styles.label, { color: colors.textMuted }]}>
                {t("alert_note") || "Catatan (opsional)"}
              </Text>
              <TextInput
                testID="alert-note-input"
                value={note}
                onChangeText={setNote}
                placeholder={t("alert_note_placeholder") || "misal: Take profit dari long BTC"}
                placeholderTextColor={colors.textMuted}
                style={[
                  styles.input,
                  {
                    color: colors.textPrimary,
                    borderColor: colors.border,
                    backgroundColor: colors.background,
                  },
                ]}
              />

              <Text style={[styles.hint, { color: colors.textMuted }]}>
                {t("alert_hint") ||
                  "Alarm akan terkirim sebagai notifikasi begitu harga sesuai kondisi. Tiap alarm bekerja sekali (one-shot)."}
              </Text>
            </View>
          </SafeAreaView>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.55)", justifyContent: "flex-end" },
  sheet: {
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    borderTopWidth: 1,
    borderLeftWidth: 1,
    borderRightWidth: 1,
    paddingTop: 6,
    paddingBottom: 20,
    ...Platform.select({
      ios: { shadowColor: "#000", shadowOffset: { width: 0, height: -3 }, shadowOpacity: 0.2, shadowRadius: 8 },
      android: { elevation: 12 },
    }),
  },
  grabber: { width: 42, height: 4, borderRadius: 2, alignSelf: "center", marginTop: 6, marginBottom: 8 },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 16,
    paddingBottom: 8,
  },
  title: { fontSize: 15, fontWeight: "800", flex: 1, textAlign: "center" },
  subtitle: { fontSize: 12, marginBottom: 4 },
  label: { fontSize: 11, marginTop: 12, marginBottom: 4, letterSpacing: 0.4, textTransform: "uppercase" },
  segmentRow: { flexDirection: "row", gap: 8 },
  segment: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 5,
    paddingVertical: 10,
    borderRadius: 10,
    borderWidth: 1,
  },
  input: {
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
    fontSize: 15,
    fontWeight: "700",
    fontVariant: ["tabular-nums"],
  },
  hint: { fontSize: 11, marginTop: 14, fontStyle: "italic", lineHeight: 15 },
});
