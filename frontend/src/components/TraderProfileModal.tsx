/**
 * v8.12.57 — Trader Profile picker modal.
 *
 * Small centered modal shown when the user taps the compass-shaped
 * button next to the Live News icon in the dashboard header. Four
 * cards, one for each preset. Tap a card → persist choice → close.
 *
 * Only affects signal generation for crypto / forex / gold_silver
 * (per backend PROFILE_APPLICABLE_MARKETS). Stocks, ETFs, and generic
 * commodity keep the market-neutral defaults.
 */
import { Ionicons } from "@expo/vector-icons";
import React from "react";
import {
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useTheme } from "@/src/theme/ThemeContext";
import { useI18n } from "@/src/i18n/I18nContext";
import {
  PROFILE_META,
  PROFILE_ORDER,
  type TraderProfile,
  useTraderProfile,
} from "@/src/lib/useTraderProfile";

type Props = {
  visible: boolean;
  onClose: () => void;
  // v9.2.0 — Tombol AI Suggestions (khusus member Premium; modal ini
  // sendiri sudah premium-only dari sisi pemanggil).
  onOpenAISuggestions: () => void;
};

export default function TraderProfileModal({ visible, onClose, onOpenAISuggestions }: Props) {
  const { colors } = useTheme();
  const { t } = useI18n();
  const { profile, setProfile, explicit } = useTraderProfile();

  const handleAISuggestionsPress = () => {
    // v9.7.9 — AI Suggestions SELALU bisa dibuka untuk profil apa pun:
    //   • scalper / day / swing → mesin VWAP sesuai profil.
    //   • longterm ATAU belum pilih profil → mesin Confluence (default).
    // Backend sudah map non-VWAP profile → engine "CONFLUENCE", jadi
    // aset pilihan selalu tersedia. Popup "pilih profil dulu" dihapus.
    onClose();
    onOpenAISuggestions();
  };

  const pick = (p: TraderProfile) => {
    // v9.7.9 — Modal TIDAK auto-close setelah pilih profil. User bisa
    // langsung menekan tombol AI Suggestions di bawah tanpa membuka
    // modal ulang. Toggle (ketuk profil aktif) tetap melepas pilihan.
    setProfile(p);
  };

  return (
    <Modal
      visible={visible}
      animationType="fade"
      transparent
      onRequestClose={onClose}
    >
      <Pressable
        style={styles.backdrop}
        onPress={onClose}
        testID="trader-profile-backdrop"
      >
        <Pressable
          style={[
            styles.sheet,
            { backgroundColor: colors.surface, borderColor: colors.border },
          ]}
          onPress={(e) => e.stopPropagation()}
        >
          <SafeAreaView edges={["top"]} style={{ width: "100%" }}>
            <View style={styles.header}>
              <View style={{ flex: 1 }}>
                <Text style={[styles.title, { color: colors.textPrimary }]}>
                  {t("profile_modal_title")}
                </Text>
                <Text style={[styles.subtitle, { color: colors.textMuted }]}>
                  {t("profile_modal_sub")}
                </Text>
              </View>
              <TouchableOpacity onPress={onClose} hitSlop={8}>
                <Ionicons name="close" size={22} color={colors.textMuted} />
              </TouchableOpacity>
            </View>
            <ScrollView
              contentContainerStyle={{ paddingBottom: 20, gap: 10 }}
              showsVerticalScrollIndicator={false}
            >
              {PROFILE_ORDER.map((p) => {
                const meta = PROFILE_META[p];
                const active = explicit && profile === p;
                return (
                  <TouchableOpacity
                    key={p}
                    onPress={() => pick(p)}
                    activeOpacity={0.7}
                    style={[
                      styles.card,
                      {
                        backgroundColor: active ? meta.color + "18" : colors.surfaceAlt,
                        borderColor: active ? meta.color : colors.border,
                      },
                    ]}
                    testID={`trader-profile-${p}`}
                  >
                    <Text style={styles.emoji}>{meta.emoji}</Text>
                    <View style={{ flex: 1 }}>
                      <View style={{ flexDirection: "row", alignItems: "baseline", gap: 8 }}>
                        <Text style={[styles.label, { color: colors.textPrimary }]}>
                          {meta.label}
                        </Text>
                        <Text style={[styles.tf, { color: meta.color }]}>
                          {meta.timeframe}
                        </Text>
                      </View>
                      <Text style={[styles.desc, { color: colors.textMuted }]}>
                        {/* v10.1.1 — Deskripsi profil terlokalisasi
                            (sebelumnya hardcode Bahasa Indonesia). */}
                        {t(`profile_desc_${p}`)}
                      </Text>
                    </View>
                    {active ? (
                      <Ionicons
                        name="checkmark-circle"
                        size={22}
                        color={meta.color}
                      />
                    ) : (
                      <Ionicons
                        name="ellipse-outline"
                        size={20}
                        color={colors.textMuted}
                      />
                    )}
                  </TouchableOpacity>
                );
              })}
            </ScrollView>
            {/* v9.2.0 — AI Suggestions: pindai aset bersinyal terkuat
                per kategori market, lengkap Entry/SL/TP. Premium only. */}
            <TouchableOpacity
              onPress={handleAISuggestionsPress}
              testID="ai-suggestions-button"
              style={styles.aiButton}
              accessibilityLabel="AI Suggestions (Premium)"
            >
              <Text style={styles.aiButtonEmoji}>✨</Text>
              <View style={{ flex: 1 }}>
                <Text style={styles.aiButtonTitle}>{t("ai_suggestions_title")}</Text>
                <Text style={styles.aiButtonSub}>
                  {t("ai_suggestions_sub")}
                </Text>
              </View>
              <View style={styles.aiButtonBadge}>
                <Text style={styles.aiButtonBadgeText}>PREMIUM</Text>
              </View>
            </TouchableOpacity>

            <Text style={[styles.footer, { color: colors.textMuted }]}>
              {t("ai_profile_footer_hint")}
            </Text>
          </SafeAreaView>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.6)",
    justifyContent: "center",
    alignItems: "center",
    padding: 16,
  },
  sheet: {
    width: "100%",
    maxWidth: 400,
    borderRadius: 16,
    borderWidth: 1,
    paddingHorizontal: 16,
    paddingBottom: 12,
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    paddingVertical: 14,
  },
  title: { fontSize: 16, fontWeight: "900", letterSpacing: 0.3 },
  subtitle: { fontSize: 11, marginTop: 2, letterSpacing: 0.2 },
  card: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    borderRadius: 12,
    borderWidth: 1.5,
    paddingHorizontal: 12,
    paddingVertical: 12,
  },
  emoji: { fontSize: 24 },
  label: { fontSize: 14, fontWeight: "800", letterSpacing: 0.3 },
  tf: { fontSize: 11, fontWeight: "700", letterSpacing: 0.4 },
  desc: { fontSize: 11.5, marginTop: 3, lineHeight: 15 },
  footer: {
    fontSize: 10,
    textAlign: "center",
    marginTop: 6,
    letterSpacing: 0.3,
  },
  aiButton: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    borderRadius: 14,
    backgroundColor: "#F0B90B",
    paddingHorizontal: 16,
    paddingVertical: 14,
    marginTop: 14,
  },
  aiButtonEmoji: { fontSize: 20 },
  aiButtonTitle: { color: "#0B0E11", fontWeight: "900", fontSize: 14, letterSpacing: 0.8 },
  aiButtonSub: { color: "rgba(11, 14, 17, 0.65)", fontSize: 10.5, marginTop: 1 },
  aiButtonBadge: {
    backgroundColor: "#0B0E11",
    borderRadius: 6,
    paddingHorizontal: 7,
    paddingVertical: 3,
  },
  aiButtonBadgeText: { color: "#F0B90B", fontSize: 8.5, fontWeight: "900", letterSpacing: 0.6 },
});
