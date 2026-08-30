/**
 * v8.12.41 — First-Launch Disclaimer Modal.
 *
 * Blocking full-screen modal that renders on the FIRST run of the app.
 * The user must tick the "I understand" checkbox and tap "Agree" before
 * the app becomes interactive. This satisfies Google Play + App Store
 * finance-app review guidelines that require an up-front risk warning.
 *
 * Storage: acceptance is persisted in AsyncStorage under a versioned
 * key. Bumping the version (see DISCLAIMER_VERSION) forces the modal to
 * reappear so any future policy update is re-accepted before the user
 * can continue using the app.
 *
 * Decline path:
 *   - Android → BackHandler.exitApp() (returns them to launcher).
 *   - iOS     → informational Alert; users must swipe up to exit
 *               (Apple forbids programmatic exit).
 */
import { Ionicons } from "@expo/vector-icons";
import React, { useEffect, useState } from "react";
import {
  Alert,
  BackHandler,
  Linking,
  Modal,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";

import { useI18n } from "@/src/i18n/I18nContext";
import { useTheme } from "@/src/theme/ThemeContext";

const STORAGE_KEY = "@ai-crypto-stock-pro:disclaimer-accepted";
export const DISCLAIMER_VERSION = 1; // Bump on any policy change to re-prompt.
const LEGAL_BASE_URL = "https://cryptostock-pro.emergent.host";

export default function DisclaimerModal() {
  const { colors } = useTheme();
  const { t, lang } = useI18n();

  const [ready, setReady] = useState(false);
  const [visible, setVisible] = useState(false);
  const [agreed, setAgreed] = useState(false);

  // Check acceptance on mount.
  useEffect(() => {
    (async () => {
      try {
        const raw = await AsyncStorage.getItem(STORAGE_KEY);
        const acceptedVersion = raw ? parseInt(raw, 10) : 0;
        if (acceptedVersion < DISCLAIMER_VERSION) {
          setVisible(true);
        }
      } catch {
        // If storage is broken, err on the side of showing the modal.
        setVisible(true);
      } finally {
        setReady(true);
      }
    })();
  }, []);

  const onAgree = async () => {
    if (!agreed) return;
    try {
      await AsyncStorage.setItem(STORAGE_KEY, String(DISCLAIMER_VERSION));
    } catch {
      /* ignore */
    }
    setVisible(false);
  };

  const onDecline = () => {
    if (Platform.OS === "android") {
      BackHandler.exitApp();
    } else {
      Alert.alert(
        lang === "id" ? "Diperlukan persetujuan" : "Consent required",
        lang === "id"
          ? "Anda harus menyetujui disclaimer untuk melanjutkan. Silakan tutup aplikasi jika tidak setuju."
          : "You must agree to the disclaimer to continue. Please close the app if you disagree.",
      );
    }
  };

  if (!ready) return null;

  return (
    <Modal
      visible={visible}
      transparent={false}
      animationType="fade"
      statusBarTranslucent
      onRequestClose={() => {
        // Ignore Android back button — user must explicitly agree or exit.
      }}
    >
      <View style={[styles.root, { backgroundColor: colors.background }]}>
        <ScrollView
          contentContainerStyle={styles.scroll}
          showsVerticalScrollIndicator={false}
        >
          {/* Warning header */}
          <View style={styles.headerRow}>
            <Ionicons name="warning" size={32} color="#EF4444" />
            <Text style={[styles.headerTitle, { color: colors.textPrimary }]}>
              {t("disclaimer_first_title") || "Important Disclaimer"}
            </Text>
          </View>

          {/* Body */}
          <View style={[styles.card, { backgroundColor: colors.surface, borderColor: colors.border }]}>
            <Text style={[styles.body, { color: colors.textPrimary }]}>
              {t("disclaimer_first_body") ||
                "AI Crypto Stock Pro provides trading signals and market analytics for EDUCATIONAL purposes only. It is NOT financial advice. Trading involves substantial risk, including possible loss of all invested capital. Past performance does not guarantee future results. You are solely responsible for your investment decisions."}
            </Text>
          </View>

          {/* Bullets */}
          <View style={styles.bullets}>
            {[
              t("disclaimer_bullet_1") || "Not financial advice — for education only",
              t("disclaimer_bullet_2") || "Trading carries risk of losing your capital",
              t("disclaimer_bullet_3") || "AI signals may be wrong — always DYOR",
              t("disclaimer_bullet_4") || "We are not registered investment advisors",
            ].map((line, i) => (
              <View key={i} style={styles.bulletRow}>
                <Ionicons name="checkmark-circle" size={16} color="#EF4444" />
                <Text style={[styles.bulletText, { color: colors.textPrimary }]}>{line}</Text>
              </View>
            ))}
          </View>

          {/* Legal quick links */}
          <View style={[styles.linksCard, { backgroundColor: colors.surfaceAlt, borderColor: colors.border }]}>
            <TouchableOpacity
              style={styles.linkRow}
              onPress={() => Linking.openURL(`${LEGAL_BASE_URL}/api/privacy`)}
              testID="disclaimer-privacy-link"
            >
              <Ionicons name="shield-checkmark" size={14} color={colors.accentBlue} />
              <Text style={[styles.linkText, { color: colors.accentBlue }]}>
                {t("legal_privacy") || "Privacy Policy"}
              </Text>
              <Ionicons name="open-outline" size={12} color={colors.accentBlue} />
            </TouchableOpacity>
            <TouchableOpacity
              style={styles.linkRow}
              onPress={() => Linking.openURL(`${LEGAL_BASE_URL}/api/terms`)}
              testID="disclaimer-terms-link"
            >
              <Ionicons name="document-text" size={14} color={colors.accentBlue} />
              <Text style={[styles.linkText, { color: colors.accentBlue }]}>
                {t("legal_terms") || "Terms of Use"}
              </Text>
              <Ionicons name="open-outline" size={12} color={colors.accentBlue} />
            </TouchableOpacity>
          </View>
        </ScrollView>

        {/* Sticky footer with checkbox + buttons */}
        <View style={[styles.footer, { backgroundColor: colors.surface, borderTopColor: colors.border }]}>
          <TouchableOpacity
            style={styles.checkboxRow}
            onPress={() => setAgreed((v) => !v)}
            activeOpacity={0.7}
            testID="disclaimer-checkbox"
          >
            <View
              style={[
                styles.checkbox,
                { borderColor: agreed ? "#22C55E" : colors.border, backgroundColor: agreed ? "#22C55E" : "transparent" },
              ]}
            >
              {agreed ? <Ionicons name="checkmark" size={14} color="#fff" /> : null}
            </View>
            <Text style={[styles.checkboxText, { color: colors.textPrimary }]}>
              {t("disclaimer_checkbox") ||
                "I have read and understood — this is not financial advice"}
            </Text>
          </TouchableOpacity>
          <View style={styles.btnRow}>
            <TouchableOpacity
              style={[styles.btnDecline, { borderColor: colors.border }]}
              onPress={onDecline}
              testID="disclaimer-decline"
            >
              <Text style={[styles.btnDeclineText, { color: colors.textSecondary }]}>
                {t("disclaimer_decline") || "Decline"}
              </Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[
                styles.btnAgree,
                { backgroundColor: agreed ? "#22C55E" : colors.border, opacity: agreed ? 1 : 0.55 },
              ]}
              disabled={!agreed}
              onPress={onAgree}
              testID="disclaimer-agree"
            >
              <Text style={styles.btnAgreeText}>{t("disclaimer_agree") || "I Agree"}</Text>
            </TouchableOpacity>
          </View>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  scroll: { paddingHorizontal: 20, paddingTop: 40, paddingBottom: 20 },
  headerRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    marginBottom: 16,
  },
  headerTitle: {
    flex: 1,
    fontSize: 20,
    fontWeight: "900",
    letterSpacing: 0.4,
  },
  card: {
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    marginBottom: 14,
  },
  body: {
    fontSize: 13,
    lineHeight: 20,
    textAlign: "justify",
  },
  bullets: { gap: 8, marginBottom: 14 },
  bulletRow: { flexDirection: "row", alignItems: "flex-start", gap: 8 },
  bulletText: { flex: 1, fontSize: 12.5, lineHeight: 18, fontWeight: "600" },
  linksCard: {
    borderWidth: 1,
    borderRadius: 12,
    padding: 4,
  },
  linkRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingVertical: 10,
    paddingHorizontal: 10,
  },
  linkText: { flex: 1, fontSize: 12.5, fontWeight: "700" },
  footer: {
    borderTopWidth: 1,
    paddingHorizontal: 16,
    paddingTop: 12,
    paddingBottom: Platform.OS === "ios" ? 34 : 16,
    gap: 12,
  },
  checkboxRow: { flexDirection: "row", alignItems: "flex-start", gap: 10 },
  checkbox: {
    width: 20,
    height: 20,
    borderRadius: 6,
    borderWidth: 2,
    alignItems: "center",
    justifyContent: "center",
    marginTop: 1,
  },
  checkboxText: { flex: 1, fontSize: 12.5, lineHeight: 18, fontWeight: "700" },
  btnRow: { flexDirection: "row", gap: 10 },
  btnDecline: {
    flex: 1,
    borderWidth: 1,
    paddingVertical: 12,
    borderRadius: 10,
    alignItems: "center",
  },
  btnDeclineText: { fontSize: 13, fontWeight: "700", letterSpacing: 0.3 },
  btnAgree: {
    flex: 1.5,
    paddingVertical: 12,
    borderRadius: 10,
    alignItems: "center",
  },
  btnAgreeText: { color: "#fff", fontSize: 13, fontWeight: "900", letterSpacing: 0.4 },
});
