/**
 * v9.6.4 — PremiumLocked: layar kunci untuk halaman premium-only
 * (ASI-Bot, Copy Trade). Mengikuti pola premium card di News page.
 */
import React from "react";
import { StyleSheet, Text, TouchableOpacity, View } from "react-native";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

import { useTheme } from "@/src/theme/ThemeContext";
import { useI18n } from "@/src/i18n/I18nContext";

const ACCENT = "#4ADE80";

export default function PremiumLocked({ bodyKey }: { bodyKey: string }) {
  const router = useRouter();
  const { colors } = useTheme();
  const { t } = useI18n();
  return (
    <View style={s.wrap}>
      <View style={[s.card, { backgroundColor: colors.surface, borderColor: ACCENT }]}>
        <Ionicons name="lock-closed" size={40} color={ACCENT} />
        <Text style={[s.title, { color: colors.textPrimary }]}>
          {t("premium_locked_title")}
        </Text>
        <Text style={[s.body, { color: colors.textSecondary }]}>
          {t(bodyKey)}
        </Text>
        <TouchableOpacity
          onPress={() => router.replace("/" as never)}
          testID="premium-locked-cta"
          style={[s.cta, { backgroundColor: ACCENT }]}
        >
          <Text style={{ color: "#FFFFFF", fontWeight: "900", letterSpacing: 0.4 }}>
            {t("premium_locked_cta")}
          </Text>
        </TouchableOpacity>
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  wrap: { flex: 1, alignItems: "center", justifyContent: "center", padding: 24 },
  card: {
    width: "100%", borderWidth: 1.5, borderRadius: 16, padding: 24,
    alignItems: "center", gap: 10,
  },
  title: { fontSize: 16, fontWeight: "900", textAlign: "center" },
  body: { fontSize: 12.5, lineHeight: 19, textAlign: "center" },
  cta: {
    marginTop: 8, paddingHorizontal: 20, paddingVertical: 12,
    borderRadius: 10, alignItems: "center", alignSelf: "stretch",
  },
});
