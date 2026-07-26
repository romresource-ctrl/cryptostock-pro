/**
 * Google Play Billing subscription flow for AI Crypto Stock Pro.
 *
 * Uses react-native-iap v15.x (Nitro-based) imperative API:
 *   - fetchProducts({ skus, type: 'subs' })    → returns ProductSubscriptionAndroid[]
 *   - requestPurchase({ type: 'subs', request: { android: { skus, subscriptionOffers } } })
 *   - purchaseUpdatedListener / purchaseErrorListener
 *   - finishTransaction({ purchase, isConsumable: false })
 *   - getAvailablePurchases()  → active entitlements for restore
 *
 * The module is lazy-loaded so Web/iOS builds don't try to import Nitro modules.
 */
import { Platform } from "react-native";

import { storage } from "@/src/utils/storage";

// ==== Product config — MUST match Play Console Product ID ====
export const SUBSCRIPTION_SKU = "ai_cryptostockpro_monthly";

// Tier catalog — 4 subscription options (durations & prices).
// Each maps to a Base Plan ID in Play Console.
export type SubscriptionTier = {
  basePlanId: string;
  months: number;
  priceUSD: number;
  label: string;      // Short label shown in the paywall
  perMonth: string;   // Effective per-month cost
  saveBadge?: string; // "Save X%" badge — optional
  popular?: boolean;  // Recommended tier
};

export const SUBSCRIPTION_TIERS: SubscriptionTier[] = [
  {
    basePlanId: "pro-1m",
    months: 1,
    priceUSD: 20,
    label: "1 Month",
    perMonth: "$20/mo",
  },
  {
    basePlanId: "pro-3m",
    months: 3,
    priceUSD: 50,
    label: "3 Months",
    perMonth: "$16.67/mo",
    saveBadge: "Save 17%",
  },
  {
    basePlanId: "pro-6m",
    months: 6,
    priceUSD: 100,
    label: "6 Months",
    perMonth: "$16.67/mo",
    saveBadge: "Save 17%",
    popular: true,
  },
  {
    basePlanId: "pro-1y",
    months: 12,
    priceUSD: 180,
    label: "12 Months",
    perMonth: "$15/mo",
    saveBadge: "Save 25%",
  },
];

// Legacy exports (kept for backward compatibility) — points to the default 1-month tier
export const SUBSCRIPTION_BASE_PLAN_ID = "pro-1m";
export const SUBSCRIPTION_OFFER_ID = "freetrial-3days";
export const SUBSCRIPTION_PRICE = "$20.00";
export const SUBSCRIPTION_TRIAL_DAYS = 3;

const ENTITLEMENT_KEY = "aicrypstockpro.entitlement";

export type SubStatus =
  | "none"
  | "active"
  | "grace_period"
  | "on_hold"
  | "paused"
  | "canceled"
  | "expired"
  | "pending"
  | "unverified"
  | "invalid";

export type Entitlement = {
  status: SubStatus;
  entitled: boolean;
  expiryTime: string | null;
  productId: string | null;
  purchaseToken: string | null;
  source: string;
  updatedAt: string;
};

const ENTITLED_STATUSES: SubStatus[] = ["active", "grace_period"];

export function isEntitled(ent: Entitlement | null): boolean {
  if (!ent) return false;
  if (!ENTITLED_STATUSES.includes(ent.status)) return false;
  if (ent.expiryTime) {
    const t = Date.parse(ent.expiryTime);
    if (!Number.isNaN(t) && t <= Date.now()) return false;
  }
  return ent.entitled;
}

function backendBase(): string {
  const RAW = process.env.EXPO_PUBLIC_BACKEND_URL ?? "";
  return `${RAW.replace(/\/+$/, "")}/api`;
}

// ---- Lazy-loaded native module (Android only) ----
type IapModule = any; // v15 does export types but we treat imperative funcs as any for lazy shape

let _iap: IapModule | null = null;
let _iapConnected = false;

async function loadIap(): Promise<IapModule | null> {
  if (Platform.OS !== "android") return null;
  if (_iap) return _iap;
  try {
    const mod = await import("react-native-iap");
    _iap = mod;
    return mod;
  } catch (e) {
    console.warn("[IAP] load failed:", e);
    return null;
  }
}

export async function initIap(): Promise<IapModule | null> {
  const iap = await loadIap();
  if (!iap) return null;
  if (_iapConnected) return iap;
  try {
    if (typeof iap.initConnection === "function") {
      await iap.initConnection();
    }
    _iapConnected = true;
    return iap;
  } catch (e) {
    console.warn("[IAP] initConnection failed:", e);
    return null;
  }
}

export async function endIap(): Promise<void> {
  if (!_iap || !_iapConnected) return;
  try {
    if (typeof _iap.endConnection === "function") {
      await _iap.endConnection();
    }
  } catch {
    /* ignore */
  }
  _iapConnected = false;
}

// ---- Product fetch ----
export type SubOffer = {
  offerToken: string;
  offerId: string | null;
  basePlanId: string | null;
  localizedPrice: string | null;
  isFreeTrial: boolean;
};

export type SubProduct = {
  productId: string;
  title: string | null;
  description: string | null;
  localizedPrice: string | null;
  // Legacy fields used by 1-tier flow (freetrial-3days offer of pro-1m)
  offerToken: string | null;
  offerId: string | null;
  basePlanId: string | null;
  // Full offer catalog — used by 4-tier paywall
  allOffers: SubOffer[];
};

// Cache last-fetched product so purchase button doesn't need to re-fetch.
let _cachedProduct: SubProduct | null = null;

function _extractAllOffers(product: any): SubOffer[] {
  const details: any[] = product?.subscriptionOfferDetailsAndroid ?? [];
  const list: SubOffer[] = [];
  for (const d of details) {
    if (!d?.offerToken) continue;
    const phases: any[] =
      d?.pricingPhases?.pricingPhaseList ??
      d?.pricingPhases ??
      [];
    const isFreeTrial = phases.some((ph: any) => {
      const p = ph?.priceAmountMicros ?? ph?.priceAmount ?? ph?.formattedPrice;
      return p === 0 || p === "0" || p === "0.0";
    });
    // Localized recurring price = last phase (post-trial)
    const nonFree = phases.filter((ph: any) => {
      const p = ph?.priceAmountMicros ?? ph?.priceAmount ?? ph?.formattedPrice;
      return !(p === 0 || p === "0" || p === "0.0");
    });
    const lastPhase = nonFree[nonFree.length - 1] ?? phases[phases.length - 1];
    const localizedPrice =
      lastPhase?.formattedPrice ??
      lastPhase?.priceAmount ??
      null;
    list.push({
      offerToken: String(d.offerToken),
      offerId: d.offerId ?? null,
      basePlanId: d.basePlanId ?? null,
      localizedPrice: localizedPrice ? String(localizedPrice) : null,
      isFreeTrial,
    });
  }
  return list;
}

/**
 * Extract the best offer for our subscription:
 * 1. Prefer any offer whose pricingPhases contains a free/trial phase
 *    (price=0 or paymentMode='FreeTrial'). This makes us always show trial
 *    even when Play Console offer IDs don't match.
 * 2. Fall back to offer with offerId === SUBSCRIPTION_OFFER_ID
 * 3. Fall back to base plan `SUBSCRIPTION_BASE_PLAN_ID`
 * 4. Fall back to first available offer
 */
function pickOfferAndroid(product: any): {
  offerToken: string | null;
  offerId: string | null;
  basePlanId: string | null;
} {
  const details: any[] = product?.subscriptionOfferDetailsAndroid ?? [];
  if (!details || details.length === 0) {
    return { offerToken: null, offerId: null, basePlanId: null };
  }
  const hasFreePhase = (d: any): boolean => {
    const phases: any[] =
      d?.pricingPhases?.pricingPhaseList ??
      d?.pricingPhases ??
      [];
    if (!Array.isArray(phases)) return false;
    return phases.some((ph: any) => {
      const price = ph?.priceAmountMicros ?? ph?.priceAmount ?? ph?.formattedPrice;
      const mode = String(ph?.paymentMode ?? ph?.recurrenceMode ?? "").toLowerCase();
      if (mode.includes("free") || mode.includes("trial")) return true;
      if (price === 0 || price === "0" || price === "0.0") return true;
      if (typeof price === "string" && /^\D*0(\.0+)?\D*$/.test(price)) return true;
      return false;
    });
  };
  const preferred =
    details.find((d) => hasFreePhase(d)) ??
    details.find((d) => d.offerId === SUBSCRIPTION_OFFER_ID) ??
    details.find((d) => d.basePlanId === SUBSCRIPTION_BASE_PLAN_ID) ??
    details[0];
  return {
    offerToken: preferred?.offerToken ?? null,
    offerId: preferred?.offerId ?? null,
    basePlanId: preferred?.basePlanId ?? null,
  };
}

export async function fetchSubscription(): Promise<SubProduct | null> {
  const iap = await initIap();
  if (!iap) return null;
  try {
    if (typeof iap.fetchProducts !== "function") {
      console.warn("[IAP] fetchProducts is not available");
      return null;
    }
    const list = await iap.fetchProducts({
      skus: [SUBSCRIPTION_SKU],
      type: "subs",
    });
    if (!Array.isArray(list) || list.length === 0) return null;
    const p = list.find((x: any) => x.id === SUBSCRIPTION_SKU) ?? list[0];
    const offer = pickOfferAndroid(p);
    const allOffers = _extractAllOffers(p);
    const displayPrice: string | null =
      p.displayPrice ??
      p.subscriptionOffers?.[0]?.displayPrice ??
      null;
    const prod: SubProduct = {
      productId: p.id ?? SUBSCRIPTION_SKU,
      title: p.title ?? p.nameAndroid ?? p.displayName ?? null,
      description: p.description ?? null,
      localizedPrice: displayPrice,
      offerToken: offer.offerToken,
      offerId: offer.offerId,
      basePlanId: offer.basePlanId,
      allOffers,
    };
    _cachedProduct = prod;
    return prod;
  } catch (e) {
    console.warn("[IAP] fetchSubscription failed:", e);
    return null;
  }
}

// ---- Purchase ----
export async function purchaseSubscription(basePlanId?: string): Promise<void> {
  const iap = await initIap();
  if (!iap) throw new Error("Google Play Billing is not available on this device.");

  let product = _cachedProduct;
  if (!product || product.allOffers.length === 0) {
    product = await fetchSubscription();
  }
  if (!product) {
    throw new Error(
      "Subscription product is not available yet. Please try again in a few minutes.",
    );
  }

  // Pick target offer
  let offerToken: string | null = null;
  if (basePlanId) {
    const freeMatch = product.allOffers.find(
      (o) => o.basePlanId === basePlanId && o.isFreeTrial,
    );
    const anyMatch = product.allOffers.find((o) => o.basePlanId === basePlanId);
    offerToken = (freeMatch ?? anyMatch)?.offerToken ?? null;
  } else {
    offerToken = product.offerToken;
  }
  if (!offerToken) {
    throw new Error(
      basePlanId
        ? `The "${basePlanId}" plan is not active in Play Console yet. Please try again in a few minutes.`
        : "This subscription has no offers configured.",
    );
  }

  // Detect existing subscription so we can UPGRADE instead of erroring out.
  // Google Play Billing 8.1+ requires the replacement mode as an INTEGER
  // (not a string) and only accepts specific field names on the Nitro
  // request. Extra / mis-named fields make the native side throw
  // "Cannot convert [object Object] to any type in variant<...>".
  let oldPurchaseToken: string | null = null;
  try {
    const getAvail: any = iap.getAvailablePurchases;
    if (typeof getAvail === "function") {
      const active: any[] = await getAvail();
      if (Array.isArray(active) && active.length > 0) {
        const same = active.find(
          (p: any) => (p.productId ?? p.id) === SUBSCRIPTION_SKU,
        );
        if (same) {
          oldPurchaseToken =
            same.purchaseToken ??
            same.purchaseTokenAndroid ??
            same.transactionReceipt ??
            null;
        }
      }
    }
  } catch {
    /* ignore — treat as new purchase */
  }

  // Build request that matches `RequestSubscriptionAndroidProps` in
  // react-native-iap v15 (Nitro). Only whitelisted fields are allowed:
  //   skus, subscriptionOffers, purchaseToken, replacementMode (integer),
  //   obfuscatedAccountId, obfuscatedProfileId, isOfferPersonalized,
  //   originalExternalTransactionId, developerBillingOption,
  //   subscriptionProductReplacementParams
  // Google Play Billing replacement mode integers:
  //   1 = WITH_TIME_PRORATION   (default — new plan starts NOW, remaining
  //                              time is credited pro-rata)
  //   2 = CHARGE_PRORATED_PRICE
  //   3 = WITHOUT_PRORATION
  //   5 = CHARGE_FULL_PRICE
  //   6 = DEFERRED              (new plan queues, starts after old expires)
  // For consumer clarity ("subscribe = get full new period immediately") we
  // use WITH_TIME_PRORATION when upgrading between our tiers, which is the
  // default Google Play behavior.
  const androidReq: any = {
    skus: [SUBSCRIPTION_SKU],
    subscriptionOffers: [{ sku: SUBSCRIPTION_SKU, offerToken }],
  };
  if (oldPurchaseToken) {
    androidReq.purchaseToken = oldPurchaseToken;
    androidReq.replacementMode = 1; // WITH_TIME_PRORATION (integer!)
  }

  try {
    await iap.requestPurchase({
      type: "subs",
      // Use `google:` (preferred in Nitro spec). `android:` is deprecated
      // and passing both variants causes the native converter to reject
      // the payload.
      request: { google: androidReq },
    });
  } catch (e: any) {
    const msg = String(e?.message ?? e ?? "");
    if (
      msg.toLowerCase().includes("cancel") ||
      e?.code === "E_USER_CANCELLED"
    ) {
      return;
    }
    throw e;
  }
}

// ---- Backend verify ----
async function _postVerify(
  purchaseToken: string,
  productId: string,
  deviceId: string,
  packageName: string,
): Promise<Entitlement> {
  const res = await fetch(`${backendBase()}/subscription/verify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      purchase_token: purchaseToken,
      product_id: productId,
      device_id: deviceId,
      package_name: packageName,
    }),
  });
  if (!res.ok) throw new Error(`verify failed: HTTP ${res.status}`);
  const data = await res.json();
  const ent: Entitlement = {
    status: (data.status ?? "invalid") as SubStatus,
    entitled: Boolean(data.entitled),
    expiryTime: data.expiry_time ?? null,
    productId: data.product_id ?? productId,
    purchaseToken,
    source: data.source ?? "unknown",
    updatedAt: new Date().toISOString(),
  };
  await storage.setItem(ENTITLEMENT_KEY, ent);
  return ent;
}

// ---- Restore ----
export async function restorePurchases(
  deviceId: string,
  packageName: string,
): Promise<Entitlement | null> {
  const iap = await initIap();
  if (!iap) return null;
  // In v15 both restorePurchases (mutation) + getAvailablePurchases (query) exist.
  // The reliable pattern is: call restorePurchases (no-op on Android but harmless),
  // then read active purchases via getAvailablePurchases.
  try {
    if (typeof iap.restorePurchases === "function") {
      try {
        await iap.restorePurchases();
      } catch {
        /* ignore — Android returns immediately */
      }
    }
    if (typeof iap.getAvailablePurchases !== "function") return null;
    const purchases = await iap.getAvailablePurchases();
    if (!Array.isArray(purchases) || purchases.length === 0) return null;
    const p =
      purchases.find((x: any) => {
        const pid = x.productId ?? x.id ?? "";
        return pid === SUBSCRIPTION_SKU;
      }) ?? purchases[0];
    const token =
      p.purchaseToken ??
      p.purchaseTokenAndroid ??
      p.transactionReceipt ??
      null;
    if (!token) return null;
    const ent = await _postVerify(
      String(token),
      String(p.productId ?? p.id ?? SUBSCRIPTION_SKU),
      deviceId,
      packageName,
    );
    try {
      if (typeof iap.finishTransaction === "function") {
        await iap.finishTransaction({ purchase: p, isConsumable: false });
      }
    } catch {
      /* non-fatal */
    }
    return ent;
  } catch (e) {
    console.warn("[IAP] restorePurchases failed:", e);
    return null;
  }
}

// ---- Global purchase listener ----
type PurchaseHandlers = {
  onSuccess: (ent: Entitlement) => void;
  onError: (msg: string) => void;
  onCancel?: () => void;
  deviceId: string;
  packageName: string;
};

/**
 * Attach global purchase listeners. Returns a cleanup function.
 * MUST be called once at app startup (root layout).
 */
export function setupPurchaseListener(handlers: PurchaseHandlers): () => void {
  let disposed = false;
  let sub1: any = null;
  let sub2: any = null;

  (async () => {
    const iap = await initIap();
    if (!iap || disposed) return;

    if (typeof iap.purchaseUpdatedListener === "function") {
      sub1 = iap.purchaseUpdatedListener(async (purchase: any) => {
        try {
          const token =
            purchase.purchaseToken ??
            purchase.purchaseTokenAndroid ??
            purchase.transactionReceipt;
          const productId =
            purchase.productId ?? purchase.id ?? SUBSCRIPTION_SKU;
          if (!token) {
            handlers.onError("Purchase token missing from Play response.");
            return;
          }
          const ent = await _postVerify(
            String(token),
            String(productId),
            handlers.deviceId,
            handlers.packageName,
          );
          try {
            if (typeof iap.finishTransaction === "function") {
              await iap.finishTransaction({
                purchase,
                isConsumable: false,
              });
            }
          } catch {
            /* Play will retry ack */
          }
          handlers.onSuccess(ent);
        } catch (e: any) {
          handlers.onError(e?.message ?? String(e));
        }
      });
    }

    if (typeof iap.purchaseErrorListener === "function") {
      sub2 = iap.purchaseErrorListener((err: any) => {
        const msg = String(err?.message ?? err ?? "");
        if (
          msg.toLowerCase().includes("cancel") ||
          err?.code === "E_USER_CANCELLED"
        ) {
          handlers.onCancel?.();
          return;
        }
        handlers.onError(msg || "Purchase failed.");
      });
    }
  })();

  return () => {
    disposed = true;
    try {
      sub1?.remove?.();
    } catch {
      /* ignore */
    }
    try {
      sub2?.remove?.();
    } catch {
      /* ignore */
    }
  };
}

// ---- Entitlement storage ----
export async function loadEntitlement(): Promise<Entitlement | null> {
  return await storage.getItem<Entitlement | null>(ENTITLEMENT_KEY, null);
}

export async function clearEntitlement(): Promise<void> {
  await storage.removeItem(ENTITLEMENT_KEY);
}

/**
 * Backend-first entitlement sync: asks the server for the freshest known
 * status for this device. This is the source of truth for premium access —
 * local cache can be stale (e.g. Google Play cancelled the subscription
 * while the app was closed). Falls back silently on network error.
 */
export async function syncEntitlementFromBackend(
  deviceId: string,
): Promise<Entitlement | null> {
  if (!deviceId) return null;
  try {
    const res = await fetch(
      `${backendBase()}/subscription/status?device_id=${encodeURIComponent(deviceId)}`,
    );
    if (!res.ok) return null;
    const data = await res.json();
    const ent: Entitlement = {
      status: (data.status ?? "none") as SubStatus,
      entitled: Boolean(data.entitled),
      expiryTime: data.expiry_time ?? null,
      productId: data.product_id ?? null,
      purchaseToken: null,
      source: data.source ?? "backend",
      updatedAt: new Date().toISOString(),
    };
    // Persist only if we have a meaningful entitlement — avoid overwriting a
    // richer local cache (with purchaseToken) with a bare "none".
    if (ent.entitled || ent.status !== "none") {
      await storage.setItem(ENTITLEMENT_KEY, ent);
    }
    return ent;
  } catch {
    return null;
  }
}
