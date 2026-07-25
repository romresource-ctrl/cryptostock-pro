import { Ionicons } from "@expo/vector-icons";
import React, { useEffect, useRef } from "react";
import {
  ActivityIndicator,
  Linking,
  Modal,
  Platform,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from "react-native";

import { useI18n } from "@/src/i18n/I18nContext";
import {
  SUBSCRIPTION_PRICE,
  SUBSCRIPTION_TRIAL_DAYS,
} from "@/src/lib/subscription";
import { useSubscription } from "@/src/lib/subscriptionContext";
import { useTheme } from "@/src/theme/ThemeContext";

type Props = {
  visible: boolean;
  onClose: () => void;
  // Kept for backwards-compat with existing callers but no longer wired to any
  // public UI — subscription is now the only public unlock flow.
  onLogin?: () => void;
};

const CONTACT_EMAIL = "cryptostockapps@gmail.com";
const GOLD = "#F0B90B";

export default function VipModal({ visible, onClose }: Props) {
  const { colors } = useTheme();
  const { t } = useI18n();
  const { subscribe, restore, loading, isPremium, entitlement, product } =
    useSubscription();

  // Auto-close modal when entitlement becomes active (issue #1, #4).
  // We track visible edge so we only close once per open cycle.
  const wasPremiumRef = useRef(isPremium);
  useEffect(() => {
    if (visible && isPremium && !wasPremiumRef.current) {
      const t = setTimeout(() => onClose(), 900);
      wasPremiumRef.current = true;
      return () => clearTimeout(t);
    }
    if (!visible) wasPremiumRef.current = isPremium;
  }, [visible, isPremium, onClose]);

  const openEmail = () =>
    Linking.openURL(`mailto:${CONTACT_EMAIL}`).catch(() => {});

  const displayPrice = product?.localizedPrice ?? SUBSCRIPTION_PRICE;

  const statusLine = (() => {
    if (isPremium) {
      const exp = entitlement?.expiryTime
        ? new Date(entitlement.expiryTime).toLocaleDateString()
        : null;
      return exp
        ? `Premium active · renews/expires ${exp}`
        : "Premium active";
    }
    if (!entitlement || entitlement.status === "none") return null;
    const nice: Record<string, string> = {
      pending: "Payment pending — please wait…",
      on_hold: "On hold — payment issue detected",
      paused: "Subscription paused",
      canceled: "Canceled (access until expiry)",
      expired: "Subscription expired",
      invalid: "No valid subscription",
      unverified: "Verification unavailable — please try again",
    };
    return nice[entitlement.status] ?? null;
  })();

  return (
    <Modal
      visible={visible}
      transparent
      animationType="fade"
      onRequestClose={onClose}
    >
      <View style={[styles.overlay, { backgroundColor: colors.overlay }]}>
        <View
          style={[
            styles.box,
            { backgroundColor: colors.surface, borderColor: GOLD },
          ]}
        >
          <TouchableOpacity
            onPress={onClose}
            testID="vip-close-button"
            style={styles.closeX}
            hitSlop={10}
          >
            <Ionicons name="close" size={22} color={colors.textMuted} />
          </TouchableOpacity>

          <View
            style={[
              styles.iconRing,
              { borderColor: GOLD, backgroundColor: GOLD + "22" },
            ]}
          >
            <Ionicons name="star" size={28} color={GOLD} />
          </View>

          <Text style={[styles.title, { color: GOLD }]}>{t("vip_title")}</Text>
          <Text style={[styles.body, { color: colors.textPrimary }]}>
            {t("vip_body")}
          </Text>

          {statusLine ? (
            <Text style={[styles.statusLine, { color: colors.textMuted }]}>
              {statusLine}
            </Text>
          ) : null}

          <Text style={[styles.contactLabel, { color: colors.textMuted }]}>
            {t("vip_contact_label")}
          </Text>
          <TouchableOpacity
            onPress={openEmail}
            style={[
              styles.contactRow,
              { backgroundColor: colors.surfaceAlt, borderColor: colors.border },
            ]}
            testID="vip-email-button"
          >
            <Ionicons name="mail" size={18} color={colors.accentBlue} />
            <Text
              style={[styles.contactText, { color: colors.textPrimary }]}
              numberOfLines={1}
            >
              {CONTACT_EMAIL}
            </Text>
            <Ionicons name="open-outline" size={14} color={colors.textMuted} />
          </TouchableOpacity>

          {/* Primary CTA — Subscribe (Google Play Billing) */}
          <TouchableOpacity
            onPress={subscribe}
            disabled={loading || isPremium}
            style={[
              styles.subscribeBtn,
              {
                backgroundColor: isPremium ? colors.surfaceAlt : GOLD,
                opacity: loading ? 0.7 : 1,
              },
            ]}
            testID="vip-subscribe-button"
          >
            {loading ? (
              <ActivityIndicator size="small" color="#000" />
            ) : (
              <>
                <Ionicons
                  name="star"
                  size={16}
                  color={isPremium ? colors.textMuted : "#000"}
                />
                <Text
                  style={[
                    styles.subscribeText,
                    { color: isPremium ? colors.textMuted : "#000" },
                  ]}
                >
                  {isPremium
                    ? "PREMIUM ACTIVE"
                    : `SUBSCRIBE ${displayPrice}/MONTH`}
                </Text>
              </>
            )}
          </TouchableOpacity>

          <Text style={[styles.trialHint, { color: colors.textMuted }]}>
            {SUBSCRIPTION_TRIAL_DAYS} days free trial · Cancel anytime via Google Play
          </Text>

          {/* Secondary CTA — Restore purchases (reinstall / new device) */}
          <TouchableOpacity
            onPress={restore}
            disabled={loading}
            style={[styles.restoreBtn, { borderColor: colors.border }]}
            testID="vip-restore-button"
          >
            <Ionicons name="refresh" size={14} color={colors.textMuted} />
            <Text style={[styles.restoreText, { color: colors.textMuted }]}>
              Restore Purchase
            </Text>
          </TouchableOpacity>

          {Platform.OS !== "android" ? (
            <Text style={[styles.androidOnly, { color: colors.textMuted }]}>
              Subscription is only available in the Android app on Google Play.
            </Text>
          ) : null}
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: 24,
  },
  box: {
    width: "100%",
    maxWidth: 380,
    borderRadius: 16,
    borderWidth: 1.5,
    padding: 20,
    alignItems: "center",
  },
  closeX: { position: "absolute", top: 12, right: 12, zIndex: 1 },
  iconRing: {
    width: 64,
    height: 64,
    borderRadius: 32,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 1.5,
    marginTop: 6,
    marginBottom: 12,
  },
  title: {
    fontSize: 18,
    fontWeight: "800",
    letterSpacing: 0.4,
    textAlign: "center",
  },
  body: {
    fontSize: 13,
    lineHeight: 19,
    textAlign: "center",
    marginTop: 10,
    marginBottom: 6,
  },
  statusLine: {
    fontSize: 11,
    textAlign: "center",
    marginBottom: 8,
    fontStyle: "italic",
  },
  contactLabel: {
    fontSize: 10,
    letterSpacing: 0.6,
    alignSelf: "stretch",
    marginBottom: 6,
    marginTop: 4,
  },
  contactRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    width: "100%",
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderRadius: 10,
    borderWidth: 1,
    marginBottom: 8,
  },
  contactText: { fontSize: 13, fontWeight: "600", flex: 1 },
  subscribeBtn: {
    marginTop: 8,
    width: "100%",
    height: 48,
    borderRadius: 10,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
  },
  subscribeText: { fontSize: 13, fontWeight: "900", letterSpacing: 0.6 },
  trialHint: {
    fontSize: 10,
    textAlign: "center",
    marginTop: 4,
    marginBottom: 8,
    fontStyle: "italic",
  },
  restoreBtn: {
    marginTop: 4,
    width: "100%",
    height: 36,
    borderRadius: 8,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    borderWidth: 1,
  },
  restoreText: { fontSize: 11, fontWeight: "700", letterSpacing: 0.4 },
  androidOnly: {
    fontSize: 10,
    textAlign: "center",
    marginTop: 8,
    fontStyle: "italic",
  },
});
