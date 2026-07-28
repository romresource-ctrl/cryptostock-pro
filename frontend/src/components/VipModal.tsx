import { Ionicons } from "@expo/vector-icons";
import React, { useEffect, useRef, useState } from "react";
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
  SUBSCRIPTION_TIERS,
  SubscriptionTier,
  SUBSCRIPTION_TRIAL_DAYS,
} from "@/src/lib/subscription";
import { useSubscription } from "@/src/lib/subscriptionContext";
import { useTheme } from "@/src/theme/ThemeContext";

type Props = {
  visible: boolean;
  onClose: () => void;
  onLogin?: () => void;
};

const CONTACT_EMAIL = "cryptostockapps@gmail.com";
const GOLD = "#F0B90B";

export default function VipModal({ visible, onClose, onLogin }: Props) {
  const { colors } = useTheme();
  const { t } = useI18n();
  const { subscribe, restore, loading, isPremium, entitlement, product } =
    useSubscription();

  // Selected tier — defaults to the popular 6-month plan.
  const [selectedTier, setSelectedTier] = useState<SubscriptionTier>(
    () => SUBSCRIPTION_TIERS.find((x) => x.popular) ?? SUBSCRIPTION_TIERS[0],
  );

  // Auto-close modal when entitlement becomes active.
  // v8.1.1 — Simpler + more robust logic: whenever the modal is visible
  // AND the user is confirmed premium, schedule a close. Uses a ref to
  // avoid re-scheduling if isPremium flickers. This fires reliably even
  // after backend verify completes 2-3s post-purchase.
  const autoCloseRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (!visible) {
      // Modal was manually closed — cancel any pending auto-close.
      if (autoCloseRef.current) {
        clearTimeout(autoCloseRef.current);
        autoCloseRef.current = null;
      }
      return;
    }
    if (isPremium && !autoCloseRef.current) {
      autoCloseRef.current = setTimeout(() => {
        onClose();
        autoCloseRef.current = null;
      }, 1200);
    }
    return () => {
      // On dep-change (e.g., isPremium flips false→true→false during
      // backend verify race), clear the pending close.
      if (autoCloseRef.current) {
        clearTimeout(autoCloseRef.current);
        autoCloseRef.current = null;
      }
    };
  }, [visible, isPremium, onClose]);

  const openEmail = () =>
    Linking.openURL(`mailto:${CONTACT_EMAIL}`).catch(() => {});

  // Use Play-provided localized price when available, else the fallback USD.
  const priceForTier = (tier: SubscriptionTier): string => {
    const offer = product?.allOffers.find((o) => o.basePlanId === tier.basePlanId);
    return offer?.localizedPrice ?? `$${tier.priceUSD}`;
  };

  const statusLine = (() => {
    if (isPremium) {
      const exp = entitlement?.expiryTime
        ? new Date(entitlement.expiryTime).toLocaleDateString()
        : null;
      return exp ? `Premium active · renews/expires ${exp}` : "Premium active";
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
            <Ionicons name="star" size={26} color={GOLD} />
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

          {/* Tier selector — 2 columns × 2 rows */}
          <View style={styles.tierGrid}>
            {SUBSCRIPTION_TIERS.map((tier) => {
              const isSel = selectedTier.basePlanId === tier.basePlanId;
              return (
                <TouchableOpacity
                  key={tier.basePlanId}
                  onPress={() => setSelectedTier(tier)}
                  disabled={isPremium || loading}
                  activeOpacity={0.85}
                  testID={`vip-tier-${tier.basePlanId}`}
                  style={[
                    styles.tierCard,
                    {
                      backgroundColor: isSel ? GOLD + "22" : colors.surfaceAlt,
                      borderColor: isSel ? GOLD : colors.border,
                      borderWidth: isSel ? 1.5 : 1,
                    },
                  ]}
                >
                  {tier.popular ? (
                    <View style={[styles.popularBadge, { backgroundColor: GOLD }]}>
                      <Text style={styles.popularBadgeText}>BEST</Text>
                    </View>
                  ) : null}
                  <Text style={[styles.tierLabel, { color: colors.textPrimary }]}>
                    {tier.label}
                  </Text>
                  <Text style={[styles.tierPrice, { color: isSel ? GOLD : colors.textPrimary }]}>
                    {priceForTier(tier)}
                  </Text>
                  <Text style={[styles.tierPerMonth, { color: colors.textMuted }]}>
                    {tier.perMonth}
                  </Text>
                  {tier.saveBadge ? (
                    <View style={[styles.saveBadge, { backgroundColor: "#10b98130", borderColor: "#10b981" }]}>
                      <Text style={[styles.saveBadgeText, { color: "#10b981" }]}>
                        {tier.saveBadge}
                      </Text>
                    </View>
                  ) : null}
                </TouchableOpacity>
              );
            })}
          </View>

          {/* Primary CTA — Subscribe */}
          <TouchableOpacity
            onPress={() => subscribe(selectedTier.basePlanId)}
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
                  {isPremium ? "PREMIUM ACTIVE" : `SUBSCRIBE ${selectedTier.label.toUpperCase()}`}
                </Text>
              </>
            )}
          </TouchableOpacity>

          <Text style={[styles.trialHint, { color: colors.textMuted }]}>
            {SUBSCRIPTION_TRIAL_DAYS} days free trial · Cancel anytime via Google Play
          </Text>

          {/* Restore Purchase */}
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

          {/* Admin Login — same size/style as Restore Purchase. Used by
              admins holding an unlock code from the generator; hidden for
              users who are already premium via subscription (no need). */}
          {onLogin && !isPremium ? (
            <TouchableOpacity
              onPress={onLogin}
              disabled={loading}
              style={[styles.restoreBtn, { borderColor: colors.border }]}
              testID="vip-admin-login-button"
            >
              <Ionicons name="key-outline" size={14} color={colors.textMuted} />
              <Text style={[styles.restoreText, { color: colors.textMuted }]}>
                Login Admin
              </Text>
            </TouchableOpacity>
          ) : null}

          {/* Contact */}
          <TouchableOpacity
            onPress={openEmail}
            style={[
              styles.contactRow,
              { backgroundColor: colors.surfaceAlt, borderColor: colors.border },
            ]}
            testID="vip-email-button"
          >
            <Ionicons name="mail" size={14} color={colors.accentBlue} />
            <Text
              style={[styles.contactText, { color: colors.textPrimary }]}
              numberOfLines={1}
            >
              {CONTACT_EMAIL}
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
    padding: 20,
  },
  box: {
    width: "100%",
    maxWidth: 400,
    borderRadius: 16,
    borderWidth: 1.5,
    padding: 18,
    alignItems: "center",
  },
  closeX: { position: "absolute", top: 12, right: 12, zIndex: 1 },
  iconRing: {
    width: 56,
    height: 56,
    borderRadius: 28,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 1.5,
    marginTop: 4,
    marginBottom: 8,
  },
  title: {
    fontSize: 17,
    fontWeight: "800",
    letterSpacing: 0.4,
    textAlign: "center",
  },
  body: {
    fontSize: 12,
    lineHeight: 17,
    textAlign: "center",
    marginTop: 8,
    marginBottom: 4,
  },
  statusLine: {
    fontSize: 10.5,
    textAlign: "center",
    marginBottom: 6,
    fontStyle: "italic",
  },
  // Tier grid
  tierGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    justifyContent: "space-between",
    width: "100%",
    marginTop: 8,
    marginBottom: 4,
    gap: 8,
  },
  tierCard: {
    width: "48%",
    borderRadius: 10,
    paddingHorizontal: 8,
    paddingVertical: 10,
    alignItems: "center",
    position: "relative",
  },
  popularBadge: {
    position: "absolute",
    top: -8,
    right: -6,
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
  },
  popularBadgeText: {
    fontSize: 9,
    color: "#000",
    fontWeight: "900",
    letterSpacing: 0.5,
  },
  tierLabel: { fontSize: 11, fontWeight: "700", letterSpacing: 0.3 },
  tierPrice: {
    fontSize: 17,
    fontWeight: "900",
    marginTop: 4,
    fontVariant: ["tabular-nums"],
  },
  tierPerMonth: {
    fontSize: 9,
    marginTop: 2,
    fontStyle: "italic",
  },
  saveBadge: {
    marginTop: 6,
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
    borderWidth: 0.5,
  },
  saveBadgeText: {
    fontSize: 9,
    fontWeight: "800",
    letterSpacing: 0.3,
  },
  // Buttons
  subscribeBtn: {
    marginTop: 12,
    width: "100%",
    height: 46,
    borderRadius: 10,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
  },
  subscribeText: { fontSize: 12, fontWeight: "900", letterSpacing: 0.6 },
  trialHint: {
    fontSize: 10,
    textAlign: "center",
    marginTop: 4,
    marginBottom: 6,
    fontStyle: "italic",
  },
  restoreBtn: {
    marginTop: 4,
    width: "100%",
    height: 32,
    borderRadius: 8,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    borderWidth: 1,
  },
  restoreText: { fontSize: 10.5, fontWeight: "700", letterSpacing: 0.4 },
  contactRow: {
    marginTop: 8,
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    width: "100%",
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 8,
    borderWidth: 1,
    justifyContent: "center",
  },
  contactText: { fontSize: 11, fontWeight: "600" },
  androidOnly: {
    fontSize: 10,
    textAlign: "center",
    marginTop: 8,
    fontStyle: "italic",
  },
});
