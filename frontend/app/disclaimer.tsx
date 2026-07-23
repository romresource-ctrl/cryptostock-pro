import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import React from "react";
import { ScrollView, StyleSheet, Text, TouchableOpacity, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useI18n } from "@/src/i18n/I18nContext";
import { useTheme } from "@/src/theme/ThemeContext";

export default function DisclaimerPage() {
  const router = useRouter();
  const { colors } = useTheme();
  const { t } = useI18n();

  return (
    <SafeAreaView style={[styles.root, { backgroundColor: colors.background }]} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} hitSlop={12} style={styles.backBtn}>
          <Ionicons name="chevron-back" size={22} color={colors.textPrimary} />
          <Text style={[styles.backText, { color: colors.textPrimary }]}>{t("back")}</Text>
        </TouchableOpacity>
        <Text style={[styles.title, { color: colors.textPrimary }]}>{t("disclaimer_title")}</Text>
        <View style={{ width: 60 }} />
      </View>

      <ScrollView
        style={{ flex: 1 }}
        contentContainerStyle={styles.scrollContent}
        showsVerticalScrollIndicator={false}
      >
        {/* Warning banner */}
        <View style={[styles.banner, { borderColor: colors.accentDown, backgroundColor: colors.accentDown + "18" }]}>
          <Ionicons name="warning" size={20} color={colors.accentDown} />
          <Text style={[styles.bannerText, { color: colors.textPrimary }]}>⚠️ HARAP BACA DENGAN SEKSAMA</Text>
        </View>

        {/* Main disclaimer body */}
        <View style={[styles.card, { backgroundColor: colors.surface, borderColor: colors.border }]}>
          <Text style={[styles.body, { color: colors.textPrimary }]}>{t("disclaimer_body")}</Text>
        </View>

        {/* Contact / Support */}
        <View style={[styles.card, { backgroundColor: colors.surface, borderColor: colors.border, marginTop: 12 }]}>
          <View style={styles.contactRow}>
            <Ionicons name="mail" size={16} color={colors.accentBlue} />
            <Text style={[styles.contactLabel, { color: colors.textMuted }]}>Support</Text>
          </View>
          <Text style={[styles.contactValue, { color: colors.textPrimary }]} selectable>
            cryptostockapps@gmail.com
          </Text>
        </View>

        <View style={{ height: 40 }} />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 12,
    paddingVertical: 12,
  },
  backBtn: { flexDirection: "row", alignItems: "center", gap: 4, width: 60 },
  backText: { fontSize: 13, fontWeight: "600" },
  title: { fontSize: 15, fontWeight: "800", letterSpacing: 0.4 },
  scrollContent: { paddingHorizontal: 12, paddingTop: 4, paddingBottom: 20 },
  banner: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    borderWidth: 1.5,
    borderRadius: 10,
    padding: 12,
    marginBottom: 12,
  },
  bannerText: { fontSize: 12, fontWeight: "800", letterSpacing: 0.4 },
  card: {
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
  },
  body: { fontSize: 12.5, lineHeight: 19, textAlign: "justify" },
  contactRow: { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 4 },
  contactLabel: { fontSize: 11, fontWeight: "600", letterSpacing: 0.4 },
  contactValue: { fontSize: 13, fontWeight: "800" },
});
