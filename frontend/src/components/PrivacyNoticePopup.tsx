/**
 * v8.12.41 — Post-Subscribe Privacy Notice popup.
 *
 * Renders exactly ONCE per subscription — right after the user completes
 * their first successful payment. Shows a short summary of what data we
 * collect while they use the paid features (chat presence, watchlist,
 * device ID for licence validation, etc.) with a link to the full
 * Privacy Policy hosted on our backend.
 *
 * Storage: acceptance is versioned so a future policy revision (e.g.
 * adding a new data category) will re-prompt subscribers one more time.
 */
import { Ionicons } from "@expo/vector-icons";
import React, { useEffect, useState } from "react";
import {
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

const STORAGE_KEY = "@ai-crypto-stock-pro:privacy-notice-seen";
export const PRIVACY_NOTICE_VERSION = 1;
const LEGAL_BASE_URL = "https://cryptostock-pro.emergent.host";

type Props = {
  /** True when the user's subscription/unlock is active. When it flips
   *  from false → true (i.e. they JUST subscribed) we show the popup. */
  isSubscribed: boolean;
};

export default function PrivacyNoticePopup({ isSubscribed }: Props) {
  const { colors } = useTheme();
  const { t } = useI18n();
  const [visible, setVisible] = useState(false);

  // Watch for the "just subscribed" edge. Show the popup only when we've
  // never shown this version to this user.
  useEffect(() => {
    if (!isSubscribed) return;
    let cancelled = false;
    (async () => {
      try {
        const raw = await AsyncStorage.getItem(STORAGE_KEY);
        const seenVersion = raw ? parseInt(raw, 10) : 0;
        if (!cancelled && seenVersion < PRIVACY_NOTICE_VERSION) {
          setVisible(true);
        }
      } catch {
        /* ignore */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [isSubscribed]);

  const onDismiss = async () => {
    try {
      await AsyncStorage.setItem(STORAGE_KEY, String(PRIVACY_NOTICE_VERSION));
    } catch {
      /* ignore */
    }
    setVisible(false);
  };

  if (!visible) return null;

  return (
    <Modal
      visible={visible}
      transparent
      animationType="fade"
      onRequestClose={onDismiss}
      statusBarTranslucent
    >
      <View style={styles.backdrop}>
        <View
          style={[
            styles.sheet,
            { backgroundColor: colors.surface, borderColor: colors.border },
          ]}
        >
          <View style={styles.headerRow}>
            <View style={[styles.iconBubble, { backgroundColor: "#22C55E22" }]}>
              <Ionicons name="shield-checkmark" size={22} color="#22C55E" />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={[styles.title, { color: colors.textPrimary }]}>
                {t("privacy_notice_title") || "Your Privacy"}
              </Text>
              <Text style={[styles.subtitle, { color: colors.textMuted }]}>
                {t("privacy_notice_subtitle") ||
                  "A quick note about the data we use while you're subscribed."}
              </Text>
            </View>
          </View>

          <ScrollView style={{ maxHeight: 240 }} showsVerticalScrollIndicator={false}>
            {[
              t("privacy_notice_1") ||
                "We store your subscription state + device ID so we can validate premium access.",
              t("privacy_notice_2") ||
                "Chatroom messages are visible to other users. Your device ID is used to show your presence dot.",
              t("privacy_notice_3") ||
                "Watchlist and preferences stay on THIS device (AsyncStorage) — not on our servers.",
              t("privacy_notice_4") ||
                "We never collect wallet addresses, private keys, brokerage credentials, or financial account numbers.",
            ].map((line, i) => (
              <View key={i} style={styles.bulletRow}>
                <Ionicons name="checkmark-circle" size={14} color="#22C55E" />
                <Text style={[styles.bulletText, { color: colors.textPrimary }]}>{line}</Text>
              </View>
            ))}
          </ScrollView>

          <TouchableOpacity
            style={styles.linkRow}
            onPress={() => Linking.openURL(`${LEGAL_BASE_URL}/api/privacy`)}
            testID="privacy-notice-read-full"
          >
            <Ionicons name="open-outline" size={13} color={colors.accentBlue} />
            <Text style={[styles.linkText, { color: colors.accentBlue }]}>
              {t("privacy_notice_read_full") || "Read the full Privacy Policy"}
            </Text>
          </TouchableOpacity>

          <TouchableOpacity
            style={[styles.okBtn, { backgroundColor: "#22C55E" }]}
            onPress={onDismiss}
            testID="privacy-notice-ok"
          >
            <Text style={styles.okBtnText}>
              {t("privacy_notice_ok") || "Got it"}
            </Text>
          </TouchableOpacity>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.55)",
    justifyContent: "center",
    paddingHorizontal: 20,
  },
  sheet: {
    borderWidth: 1,
    borderRadius: 16,
    padding: 18,
    gap: 12,
  },
  headerRow: { flexDirection: "row", alignItems: "center", gap: 12 },
  iconBubble: {
    width: 40,
    height: 40,
    borderRadius: 20,
    alignItems: "center",
    justifyContent: "center",
  },
  title: { fontSize: 16, fontWeight: "900", letterSpacing: 0.3 },
  subtitle: { fontSize: 11.5, fontWeight: "600", marginTop: 2 },
  bulletRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 8,
    paddingVertical: 6,
  },
  bulletText: { flex: 1, fontSize: 12, lineHeight: 17 },
  linkRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingVertical: 6,
  },
  linkText: { fontSize: 12, fontWeight: "700", letterSpacing: 0.3 },
  okBtn: {
    paddingVertical: 12,
    borderRadius: 10,
    alignItems: "center",
    marginTop: Platform.OS === "ios" ? 6 : 4,
  },
  okBtnText: {
    color: "#fff",
    fontSize: 13,
    fontWeight: "900",
    letterSpacing: 0.5,
  },
});
