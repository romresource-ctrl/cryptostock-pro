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

// v9.1.6 — AI Suggestions HANYA berjalan dengan profil Scalper, Day Trader
// (Intraday), atau Swing. Tanpa profil (Confluence default) atau profil
// Long-term → tampilkan popup pengarahan, sheet TIDAK dibuka.
const AI_SUGGESTION_PROFILES: TraderProfile[] = ["scalper", "day", "swing"];

export default function TraderProfileModal({ visible, onClose, onOpenAISuggestions }: Props) {
  const { colors } = useTheme();
  const { t } = useI18n();
  const { profile, setProfile, explicit } = useTraderProfile();
  const [profileRequiredOpen, setProfileRequiredOpen] = React.useState(false);

  const aiProfileReady = explicit && AI_SUGGESTION_PROFILES.includes(profile);

  const handleAISuggestionsPress = () => {
    if (!aiProfileReady) {
      // Tampilkan popup pengarahan — modal profil tetap terbuka agar
      // user bisa langsung memilih Scalper / Day Trader / Swing.
      setProfileRequiredOpen(true);
      return;
    }
    onClose();
    onOpenAISuggestions();
  };

  const pick = (p: TraderProfile) => {
    // v9.3.0 — Toggle: ketuk kartu yang aktif = lepas pilihan (kembali ke
    // mesin default Confluence). Modal tetap terbuka agar user melihat
    // state "tidak ada yang aktif".
    const wasActive = explicit && profile === p;
    setProfile(p);
    if (!wasActive) {
      // Small delay so the "checked" state animates before we close.
      setTimeout(onClose, 180);
    }
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
                  Trader Profile
                </Text>
                <Text style={[styles.subtitle, { color: colors.textMuted }]}>
                  Tune signals to your trading horizon
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
                        {meta.description}
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

            {/* v9.1.6 — Popup pengarahan: AI Suggestions butuh profil
                Scalper / Day Trader / Swing yang dipilih eksplisit. */}
            <Modal
              visible={profileRequiredOpen}
              animationType="fade"
              transparent
              onRequestClose={() => setProfileRequiredOpen(false)}
            >
              <Pressable
                style={styles.warnBackdrop}
                onPress={() => setProfileRequiredOpen(false)}
                testID="ai-profile-required-backdrop"
              >
                <Pressable
                  style={[
                    styles.warnCard,
                    { backgroundColor: colors.surface, borderColor: "#F0B90B" },
                  ]}
                  onPress={(e) => e.stopPropagation()}
                >
                  <Text style={styles.warnEmoji}>🧭</Text>
                  <Text style={[styles.warnTitle, { color: colors.textPrimary }]}>
                    {t("ai_profile_required_title")}
                  </Text>
                  <Text style={[styles.warnBody, { color: colors.textMuted }]}>
                    {t("ai_profile_required_body")}
                  </Text>
                  <TouchableOpacity
                    onPress={() => setProfileRequiredOpen(false)}
                    testID="ai-profile-required-ok"
                    style={styles.warnButton}
                    accessibilityLabel={t("ai_profile_required_title")}
                  >
                    <Text style={styles.warnButtonText}>{t("ai_profile_required_btn")}</Text>
                  </TouchableOpacity>
                </Pressable>
              </Pressable>
            </Modal>

            <Text style={[styles.footer, { color: colors.textMuted }]}>
              Tap the active profile again to unselect — default engine: Confluence.
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
  warnBackdrop: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.7)",
    justifyContent: "center",
    alignItems: "center",
    padding: 24,
  },
  warnCard: {
    width: "100%",
    maxWidth: 340,
    borderRadius: 16,
    borderWidth: 1.5,
    paddingHorizontal: 20,
    paddingVertical: 22,
    alignItems: "center",
  },
  warnEmoji: { fontSize: 30 },
  warnTitle: { fontSize: 15, fontWeight: "900", letterSpacing: 0.3, marginTop: 10 },
  warnBody: { fontSize: 12.5, lineHeight: 18, textAlign: "center", marginTop: 8 },
  warnButton: {
    marginTop: 16,
    backgroundColor: "#F0B90B",
    borderRadius: 10,
    paddingHorizontal: 24,
    paddingVertical: 12,
    minWidth: 180,
    alignItems: "center",
  },
  warnButtonText: { color: "#0B0E11", fontWeight: "900", fontSize: 12.5, letterSpacing: 0.8 },
});
