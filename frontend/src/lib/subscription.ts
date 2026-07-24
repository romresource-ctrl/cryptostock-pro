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
export const SUBSCRIPTION_BASE_PLAN_ID = "monthly";
export const SUBSCRIPTION_OFFER_ID = "freetrial3days";
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
export type SubProduct = {
  productId: string;
  title: string | null;
  description: string | null;
  localizedPrice: string | null;
  // Android offer token (from Play Console base plan / offer).
  // We need this to trigger requestPurchase for subscriptions in v15.x.
  offerToken: string | null;
  offerId: string | null;
  basePlanId: string | null;
};

// Cache last-fetched product so purchase button doesn't need to re-fetch.
let _cachedProduct: SubProduct | null = null;

/**
 * Extract the best offer for our subscription:
 * 1. Prefer offer with offerId matching SUBSCRIPTION_OFFER_ID (3-day free trial)
 * 2. Fall back to first offer for base plan `monthly`
 * 3. Fall back to first available offer
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
  const preferred =
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
    };
    _cachedProduct = prod;
    return prod;
  } catch (e) {
    console.warn("[IAP] fetchSubscription failed:", e);
    return null;
  }
}

// ---- Purchase ----
export async function purchaseSubscription(): Promise<void> {
  const iap = await initIap();
  if (!iap) throw new Error("Google Play Billing is not available on this device.");

  // Make sure we have an offer token before calling requestPurchase (Android v15
  // requires subscriptionOffers[] with offerToken).
  let product = _cachedProduct;
  if (!product?.offerToken) {
    product = await fetchSubscription();
  }
  if (!product) {
    throw new Error(
      "Subscription product is not available yet. Please check that the subscription is Active in Play Console and try again in a few minutes.",
    );
  }
  if (!product.offerToken) {
    throw new Error(
      "This subscription has no offers configured. Please open Play Console → Monetize → Subscriptions and make sure your base plan and offer are Active.",
    );
  }

  try {
    await iap.requestPurchase({
      type: "subs",
      request: {
        android: {
          skus: [SUBSCRIPTION_SKU],
          subscriptionOffers: [
            { sku: SUBSCRIPTION_SKU, offerToken: product.offerToken },
          ],
        },
      },
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
