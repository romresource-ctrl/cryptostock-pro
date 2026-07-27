/**
 * usePremiumAccess — single source of truth for "does this user have
 * access to premium features right now?"
 *
 * Consolidates the two independent access gates:
 *   - `isPremium`   from Google Play Billing (react-native-iap)
 *   - `isUnlocked`  from legacy admin unlock-code flow
 *
 * Any component that needs to gate premium UI should call this hook
 * instead of duplicating the OR expression. That way, if we ever add
 * a third source (referral code, promo, etc.), we change one file.
 *
 * `__DEV__` bypass: in Expo dev builds and web preview the paywall is
 * lifted so screens are testable. React Native replaces `__DEV__` with
 * a hard-coded `false` in release builds, so this has ZERO effect on
 * production Android AAB/APK — Google Play users still hit the paywall
 * as designed.
 */
import { useAuth } from "@/src/auth/AuthContext";
import { useSubscription } from "@/src/lib/subscriptionContext";

export interface PremiumAccessState {
  /** True when the app can show premium features (any source). */
  hasAccess: boolean;
  /** True when at least one entitlement source is a paying subscription. */
  isPremium: boolean;
  /** True when the legacy admin unlock-code flow granted access. */
  isUnlocked: boolean;
  /** True once BOTH auth + subscription contexts finished cold-start sync. */
  loaded: boolean;
}

export function usePremiumAccess(): PremiumAccessState {
  const { isPremium, loaded: subLoaded } = useSubscription();
  const { isUnlocked, loaded: authLoaded } = useAuth();
  const loaded = authLoaded && subLoaded;
  const hasAccess = __DEV__ || isPremium || isUnlocked;
  return { hasAccess, isPremium, isUnlocked, loaded };
}
