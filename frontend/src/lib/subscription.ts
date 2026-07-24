/**
 * Google Play Billing scaffolding for AI Crypstock Pro subscription.
 *
 * Import path only — actual purchase flow lives in `useSubscription` hook (v3.1.x).
 * This file exists so Metro bundles react-native-iap into the AAB, which is what
 * satisfies Play Console's "Billing Library v6.0.1+" requirement.
 */
import { Platform } from "react-native";

// Subscription Product ID configured in Play Console → Monetize → Subscriptions
export const SUBSCRIPTION_SKU = "ai_cryptostockpro_monthly";
export const SUBSCRIPTION_BASE_PLAN_ID = "monthly-autorenew";
export const SUBSCRIPTION_OFFER_ID = "free-trial-3d";

// Lazy import — only on Android, and only when actually used to trigger purchase.
// Web preview must not try to import (would crash Metro).
export async function loadIap() {
  if (Platform.OS !== "android") return null;
  try {
    const iap = await import("react-native-iap");
    return iap;
  } catch (e) {
    console.warn("[IAP] load failed:", e);
    return null;
  }
}

// Placeholder — full flow will be wired in v3.1.x (init connection, fetch product,
// requestSubscription, purchaseUpdatedListener, server-side receipt verify).
export const SUBSCRIPTION_PRICE = "$20.00";
export const SUBSCRIPTION_TRIAL_DAYS = 3;
