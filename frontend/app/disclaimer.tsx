import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import React from "react";
import { Linking, ScrollView, StyleSheet, Text, TouchableOpacity, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useI18n } from "@/src/i18n/I18nContext";
import { useTheme } from "@/src/theme/ThemeContext";

// v8.3.1 — Production backend URL hosting the Play Store legal pages.
// Play Console requires Privacy Policy + Data Deletion URLs to be
// "accessible from within the app", so we deep-link them from Disclaimer.
const LEGAL_BASE_URL = "https://cryptostock-pro.emergent.host";

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
          <Text style={[styles.bannerText, { color: colors.textPrimary }]}>{t("disclaimer_read_carefully")}</Text>
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

        {/* v8.3.1 — Legal links (required for Google Play submission).
             These deep-link to the production backend HTML pages so
             Play Console reviewers can verify "accessible from within
             your app" for both Privacy Policy and Data/Account
             Deletion. Tapping opens the page in the system browser. */}
        <View style={[styles.card, { backgroundColor: colors.surface, borderColor: colors.border, marginTop: 12 }]}>
          <Text style={[styles.contactLabel, { color: colors.textMuted, marginBottom: 8 }]}>
            {t("legal_links_label")}
          </Text>
          <TouchableOpacity
            style={styles.legalRow}
            onPress={() => Linking.openURL(`${LEGAL_BASE_URL}/api/privacy`)}
            testID="legal-privacy-link"
          >
            <Ionicons name="shield-checkmark" size={16} color={colors.accentBlue} />
            <Text style={[styles.legalText, { color: colors.accentBlue }]}>{t("legal_privacy")}</Text>
            <Ionicons name="open-outline" size={14} color={colors.accentBlue} />
          </TouchableOpacity>
          <TouchableOpacity
            style={styles.legalRow}
            onPress={() => Linking.openURL(`${LEGAL_BASE_URL}/api/terms`)}
            testID="legal-terms-link"
          >
            <Ionicons name="document-text" size={16} color={colors.accentBlue} />
            <Text style={[styles.legalText, { color: colors.accentBlue }]}>{t("legal_terms")}</Text>
            <Ionicons name="open-outline" size={14} color={colors.accentBlue} />
          </TouchableOpacity>
          <TouchableOpacity
            style={styles.legalRow}
            onPress={() => Linking.openURL(`${LEGAL_BASE_URL}/api/data-deletion`)}
            testID="legal-data-deletion-link"
          >
            <Ionicons name="trash-bin" size={16} color={colors.accentDown} />
            <Text style={[styles.legalText, { color: colors.accentDown }]}>{t("legal_data_deletion")}</Text>
            <Ionicons name="open-outline" size={14} color={colors.accentDown} />
          </TouchableOpacity>
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
  legalRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingVertical: 10,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: "#33333322",
  },
  legalText: { flex: 1, fontSize: 13, fontWeight: "700" },
});
