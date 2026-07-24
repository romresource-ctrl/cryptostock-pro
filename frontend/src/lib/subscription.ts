/**
 * Google Play Billing subscription flow for AI Crypto Stock Pro.
 *
 * We use the imperative API of react-native-iap (initConnection,
 * requestSubscription, purchaseUpdatedListener, finishTransaction,
 * getAvailablePurchases) inside a lazy-loaded module so Web and iOS builds
 * never try to import the native Nitro Modules.
 *
 * Flow:
 *   1. `initIap()` — connects to Play Store once per process
 *   2. `fetchSubscription()` — fetches product metadata (price, trial)
 *   3. `purchaseSubscription()` — opens Google Play purchase sheet
 *   4. `setupPurchaseListener()` — global listener, verifies with backend,
 *      finishes transaction, stores entitlement in AsyncStorage
 *   5. `restorePurchases()` — restore for reinstall
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
type IapModule = any; // react-native-iap doesn't ship types for imperative API

let _iap: IapModule | null = null;
let _iapConnected = false;

async function loadIap(): Promise<IapModule | null> {
  if (Platform.OS !== "android") return null;
  if (_iap) return _iap;
  try {
    // Metro will still bundle this into the AAB thanks to the static string.
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
    // react-native-iap 15.x supports both `initConnection()` and the newer
    // `initConnection({})` shape. Passing no-args is universally safe.
    if (typeof iap.initConnection === "function") {
      await iap.initConnection();
    }
    // Optional Android clean-up of stuck pending purchases
    if (typeof iap.flushFailedPurchasesCachedAsPendingAndroid === "function") {
      try {
        await iap.flushFailedPurchasesCachedAsPendingAndroid();
      } catch {
        /* non-fatal */
      }
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
};

export async function fetchSubscription(): Promise<SubProduct | null> {
  const iap = await initIap();
  if (!iap) return null;
  try {
    // 15.x exposes both `getSubscriptions` and `fetchSubscriptions` — try both.
    const fn: any =
      iap.fetchSubscriptions ?? iap.getSubscriptions ?? iap.subscriptions;
    if (typeof fn !== "function") return null;
    const list = await fn({ skus: [SUBSCRIPTION_SKU] });
    if (!Array.isArray(list) || list.length === 0) return null;
    const p = list.find((x: any) => x.productId === SUBSCRIPTION_SKU) ?? list[0];
    return {
      productId: p.productId ?? SUBSCRIPTION_SKU,
      title: p.title ?? p.name ?? null,
      description: p.description ?? null,
      localizedPrice: p.localizedPrice ?? p.price ?? null,
    };
  } catch (e) {
    console.warn("[IAP] fetchSubscription failed:", e);
    return null;
  }
}

// ---- Purchase / Restore ----
export async function purchaseSubscription(): Promise<void> {
  const iap = await initIap();
  if (!iap) throw new Error("Google Play Billing is not available on this device.");
  try {
    // requestSubscription is the imperative call; result comes through the
    // purchaseUpdatedListener. In 15.x the arg shape is { sku }.
    await iap.requestSubscription({ sku: SUBSCRIPTION_SKU });
  } catch (e: any) {
    const msg = e?.message ?? String(e);
    if (msg.toLowerCase().includes("cancel")) return;
    throw e;
  }
}

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

/** Restore a previous purchase (reinstall / new device with same Play account). */
export async function restorePurchases(
  deviceId: string,
  packageName: string,
): Promise<Entitlement | null> {
  const iap = await initIap();
  if (!iap) return null;
  const getAvail: any = iap.getAvailablePurchases ?? iap.availablePurchases;
  if (typeof getAvail !== "function") return null;
  try {
    const purchases = await getAvail();
    if (!Array.isArray(purchases) || purchases.length === 0) return null;
    const p =
      purchases.find((x: any) => x.productId === SUBSCRIPTION_SKU) ?? purchases[0];
    const token = p.purchaseToken ?? p.purchaseTokenAndroid ?? p.transactionReceipt;
    if (!token) return null;
    const ent = await _postVerify(
      String(token),
      String(p.productId ?? SUBSCRIPTION_SKU),
      deviceId,
      packageName,
    );
    // Ack transaction so Play knows we honoured it
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
 * MUST be called once at app startup (root layout) so purchases made from
 * anywhere in the app are captured.
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
          const productId = purchase.productId ?? SUBSCRIPTION_SKU;
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
              await iap.finishTransaction({ purchase, isConsumable: false });
            }
          } catch {
            /* non-fatal — Play will retry ack */
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
