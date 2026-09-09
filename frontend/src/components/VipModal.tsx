import { Ionicons } from "@expo/vector-icons";
import React, { useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Linking,
  Modal,
  Platform,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from "react-native";

import { useI18n } from "@/src/i18n/I18nContext";
import { getDeviceId } from "@/src/lib/deviceId";
import {
  SUBSCRIPTION_TIERS,
  SubscriptionTier,
  SUBSCRIPTION_TRIAL_DAYS,
  checkPromoClaimed,
} from "@/src/lib/subscription";
import { useSubscription } from "@/src/lib/subscriptionContext";
import { useTheme } from "@/src/theme/ThemeContext";

type Props = {
  visible: boolean;
  onClose: () => void;
};

const CONTACT_EMAIL = "cryptostockapps@gmail.com";
const GOLD = "#F0B90B";

export default function VipModal({ visible, onClose }: Props) {
  const { colors } = useTheme();
  const { t } = useI18n();
  const { subscribe, restore, loading, isPremium, entitlement, product } =
    useSubscription();

  // v8.12.75 — Promo code sheet state. Redeeming a Google Play promo
  // code happens on the Play Store side; we only need the code text.
  const [promoOpen, setPromoOpen] = useState(false);
  const [promoCode, setPromoCode] = useState("");

  const redeemPromo = () => {
    const code = promoCode.trim();
    if (!code) return;
    // Play Store redemption page with the code pre-filled. On Android
    // this opens the Play Store app directly on the redeem screen.
    Linking.openURL(
      `https://play.google.com/store/redeem?code=${encodeURIComponent(code)}`,
    ).catch(() => {});
    setPromoOpen(false);
    setPromoCode("");
  };

  // Selected tier — v8.12.69: defaults to the 3-Months plan to match
  // the approved paywall design (3 Months highlighted with gold frame
  // and the CTA reading "SUBSCRIBE 3 MONTHS" on first open).
  const [selectedTier, setSelectedTier] = useState<SubscriptionTier>(
    () => SUBSCRIPTION_TIERS.find((x) => x.id === "pro-3m") ?? SUBSCRIPTION_TIERS[0],
  );

  // v8.12.69/72 — One-time "new subscriber" plan enforcement.
  // The 1-Week (pro-1w) and the LIMITED 2-Months (prepaid-2m) plans are
  // MUTUALLY EXCLUSIVE first-subscriber offers:
  //   • Ever bought 1 Week      → 2-Months promo locks forever.
  //   • Ever bought 2-Months    → 1-Week plan locks forever.
  // Records live on the backend (per device), so reinstalling the app
  // does NOT unlock them again. Truly new subscribers may pick ONE.
  const [promo2mClaimed, setPromo2mClaimed] = useState(false);
  const [week1Claimed, setWeek1Claimed] = useState(false);
  useEffect(() => {
    if (!visible) return;
    let alive = true;
    (async () => {
      const id = await getDeviceId().catch(() => "");
      // v8.12.71 — Check prepaid-2m + legacy pro-2m; v8.12.72 — and pro-1w.
      const c2m = id
        ? (await checkPromoClaimed(id, "prepaid-2m")) ||
          (await checkPromoClaimed(id, "pro-2m"))
        : false;
      const c1w = id ? await checkPromoClaimed(id, "pro-1w") : false;
      if (!alive) return;
      setPromo2mClaimed(c2m);
      setWeek1Claimed(c1w);
      if (c2m || c1w) {
        // If the currently-selected card just got locked, fall back to 3 Months.
        setSelectedTier((cur) => {
          const nowLocked =
            (cur.id === "prepaid-2m" && (c2m || c1w)) ||
            (cur.id === "pro-1w" && (c1w || c2m));
          return nowLocked
            ? SUBSCRIPTION_TIERS.find((x) => x.id === "pro-3m") ?? cur
            : cur;
        });
      }
    })();
    return () => {
      alive = false;
    };
  }, [visible]);

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
    // v8.12.65 — Promo tiers (e.g. september-promo-2for1) must match
    // BOTH basePlanId + offerId, otherwise the 1-Month offer would be
    // picked for the 2-Months promo card (they share base plan pro-1m).
    const offer = product?.allOffers.find((o) =>
      tier.offerId
        ? o.basePlanId === tier.basePlanId && o.offerId === tier.offerId
        : o.basePlanId === tier.basePlanId,
    );
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

          {/* Tier selector — 2 columns × 3 rows (incl. LIMITED promo) */}
          <View style={styles.tierGrid}>
            {SUBSCRIPTION_TIERS.map((tier) => {
              const isSel = selectedTier.id === tier.id;
              // v8.12.72/73 — Lock rules for the two first-subscriber
              // plans (both are strictly ONE-TIME per device):
              //   • 2-Months promo locks after EITHER plan was ever used.
              //   • 1-Week locks after it was used itself, OR after the
              //     2-Months promo was used. Past 1-Week subscribers must
              //     continue with 1m/3m/6m/12m — no 1-Week re-subscribe.
              const locked =
                (tier.id === "prepaid-2m" && (promo2mClaimed || week1Claimed)) ||
                (tier.id === "pro-1w" && (week1Claimed || promo2mClaimed));
              return (
                <TouchableOpacity
                  key={tier.id}
                  onPress={() => !locked && setSelectedTier(tier)}
                  disabled={isPremium || loading || locked}
                  activeOpacity={0.85}
                  testID={`vip-tier-${tier.id}`}
                  style={[
                    styles.tierCard,
                    {
                      backgroundColor: isSel ? GOLD + "22" : colors.surfaceAlt,
                      // v8.12.65 — LIMITED promo card keeps a gold frame
                      // even when not selected, so the eye is drawn to
                      // the time-boxed offer (matches the approved
                      // paywall design). Locked (claimed) cards lose it.
                      borderColor: !locked && (isSel || tier.limited) ? GOLD : colors.border,
                      borderWidth: !locked && (isSel || tier.limited) ? 1.5 : 1,
                      opacity: locked ? 0.5 : 1,
                    },
                  ]}
                >
                  {tier.popular ? (
                    <View style={[styles.popularBadge, { backgroundColor: GOLD }]}>
                      <Text style={styles.popularBadgeText}>BEST</Text>
                    </View>
                  ) : null}
                  {/* v8.12.49 — STARTER ribbon on the 1-Week tier. Sits on
                      the top-LEFT (mirrors the BEST badge on top-right)
                      so newcomers see it before scanning prices. */}
                  {tier.starter ? (
                    <View style={[styles.starterBadge, { backgroundColor: "#3B82F6" }]}>
                      <Text style={styles.starterBadgeText}>STARTER</Text>
                    </View>
                  ) : null}
                  {/* v8.12.65 — LIMITED ribbon (red) for time-boxed
                      promos like the September 2-for-1 offer. */}
                  {tier.limited ? (
                    <View style={[styles.starterBadge, { backgroundColor: "#EF4444" }]}>
                      <Text style={styles.starterBadgeText}>LIMITED</Text>
                    </View>
                  ) : null}
                  <Text style={[styles.tierLabel, { color: colors.textPrimary }]}>
                    {tier.label}
                  </Text>
                  <Text style={[styles.tierPrice, { color: isSel ? GOLD : colors.textPrimary }]}>
                    {priceForTier(tier)}
                  </Text>
                  {/* v8.12.65 — Per-month row and Save badge sit on the
                      SAME line (per the approved paywall design): the
                      italic per-month note is directly followed by the
                      green Save pill. */}
                  <View style={styles.perMonthRow}>
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
                  </View>
                  {tier.footNote ? (
                    <Text
                      style={[
                        styles.footNote,
                        { color: colors.textMuted },
                      ]}
                    >
                      {locked
                        ? (tier.id === "prepaid-2m" && promo2mClaimed) ||
                          (tier.id === "pro-1w" && week1Claimed)
                          ? "ALREADY CLAIMED"
                          : "NOT AVAILABLE"
                        : tier.footNote}
                    </Text>
                  ) : null}
                </TouchableOpacity>
              );
            })}
          </View>

          {/* Primary CTA — Subscribe */}
          <TouchableOpacity
            onPress={() => subscribe(selectedTier.basePlanId, selectedTier.offerId)}
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
            {/* v8.12.50 — Only mention the free trial when the currently
                selected tier is eligible (1 Month and longer). The
                1-Week Starter plan intentionally has no free trial.
                v8.12.65 — LIMITED promo tiers get their own hint: the
                discounted months replace the free trial. */}
            {selectedTier.limited
              ? `Limited time offer · ${selectedTier.perMonth} for the first 2 months · Cancel anytime via Google Play`
              : selectedTier.trialEligible !== false
                ? `${SUBSCRIPTION_TRIAL_DAYS} days free trial. Cancel anytime via Google Play`
                : `No free trial on this plan · Cancel anytime via Google Play`}
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

          {/* v8.12.75 — PROMO CODE button (replaces Login Admin — the
              key icon on the dashboard header already covers admin
              login). Opens a small input sheet; Redeem deep-links to
              the Play Store redeem page with the code pre-filled so
              Google Play applies the promo (campaign "promo-3m": 7-day
              free trial, one-time codes, 9 Sep – 31 Dec 2026). */}
          <TouchableOpacity
            onPress={() => setPromoOpen(true)}
            disabled={loading}
            style={[styles.restoreBtn, { borderColor: GOLD }]}
            testID="vip-promo-code-button"
          >
            <Ionicons name="pricetag-outline" size={14} color={GOLD} />
            <Text style={[styles.restoreText, { color: GOLD }]}>
              INPUT PROMO CODE
            </Text>
          </TouchableOpacity>

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

        {/* v8.12.75 — Promo code input sheet. Campaign "promo-2026"
            (Play Console: 7-day free trial, CUSTOM codes, 9 Sep –
            31 Dec 2026). The user types/pastes the code here, then we
            deep-link to the Play Store redeem page with the code
            pre-filled — Google Play applies the free trial itself. */}
        <Modal
          visible={promoOpen}
          transparent
          animationType="fade"
          onRequestClose={() => setPromoOpen(false)}
        >
          <View style={[styles.overlay, { backgroundColor: colors.overlay }]}>
            <View
              style={[
                styles.promoBox,
                { backgroundColor: colors.surface, borderColor: GOLD },
              ]}
            >
              <Text style={[styles.promoTitle, { color: GOLD }]}>
                Promo Code
              </Text>
              <Text style={[styles.promoHint, { color: colors.textMuted }]}>
                Enter your code, then confirm on the Google Play redeem page to activate your free trial.
              </Text>
              <TextInput
                value={promoCode}
                onChangeText={setPromoCode}
                placeholder="Enter your promo code"
                placeholderTextColor={colors.textMuted}
                autoCapitalize="characters"
                autoCorrect={false}
                autoFocus
                testID="promo-code-input"
                style={[
                  styles.promoInput,
                  {
                    backgroundColor: colors.surfaceAlt,
                    borderColor: colors.border,
                    color: colors.textPrimary,
                  },
                ]}
              />
              <TouchableOpacity
                onPress={redeemPromo}
                disabled={!promoCode.trim()}
                style={[
                  styles.promoRedeemBtn,
                  { backgroundColor: GOLD, opacity: promoCode.trim() ? 1 : 0.5 },
                ]}
                testID="promo-redeem-button"
              >
                <Ionicons name="logo-google-playstore" size={15} color="#000" />
                <Text style={styles.promoRedeemText}>REDEEM ON PLAY STORE</Text>
              </TouchableOpacity>
              <TouchableOpacity
                onPress={() => {
                  setPromoOpen(false);
                  setPromoCode("");
                }}
                style={styles.promoCancelBtn}
                testID="promo-cancel-button"
              >
                <Text style={[styles.promoCancelText, { color: colors.textMuted }]}>
                  Cancel
                </Text>
              </TouchableOpacity>
            </View>
          </View>
        </Modal>
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
  // v8.12.49 — STARTER ribbon (top-left of the 1-Week tier).
  starterBadge: {
    position: "absolute",
    top: -8,
    left: -6,
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
  },
  starterBadgeText: {
    fontSize: 9,
    color: "#fff",
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
    fontStyle: "italic",
  },
  // v8.12.65 — Per-month note + Save badge on one line (approved design).
  perMonthRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    marginTop: 2,
  },
  // v8.12.65 — Foot line inside the card: "NO FREE TRIAL" /
  // "14-D FREE TRIAL" / "Limited Time Offer".
  footNote: {
    fontSize: 9,
    fontWeight: "700",
    letterSpacing: 0.3,
    marginTop: 4,
  },
  saveBadge: {
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
  // v8.12.75 — Promo code sheet
  promoBox: {
    width: "100%",
    maxWidth: 320,
    borderRadius: 14,
    borderWidth: 1.5,
    padding: 18,
    alignItems: "center",
  },
  promoTitle: { fontSize: 15, fontWeight: "900", letterSpacing: 0.4 },
  promoHint: {
    fontSize: 11,
    lineHeight: 16,
    textAlign: "center",
    marginTop: 6,
    marginBottom: 12,
  },
  promoInput: {
    width: "100%",
    height: 44,
    borderRadius: 10,
    borderWidth: 1,
    paddingHorizontal: 12,
    fontSize: 14,
    fontWeight: "700",
    letterSpacing: 1,
    textAlign: "center",
  },
  promoRedeemBtn: {
    marginTop: 12,
    width: "100%",
    height: 42,
    borderRadius: 10,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
  },
  promoRedeemText: { color: "#000", fontSize: 12, fontWeight: "900", letterSpacing: 0.5 },
  promoCancelBtn: { marginTop: 10, paddingVertical: 4 },
  promoCancelText: { fontSize: 12, fontWeight: "700" },
  androidOnly: {
    fontSize: 10,
    textAlign: "center",
    marginTop: 8,
    fontStyle: "italic",
  },
});
