import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Alert, AppState, Platform } from "react-native";

import { getDeviceId } from "@/src/lib/deviceId";
import {
  clearEntitlement,
  Entitlement,
  fetchSubscription,
  initIap,
  isEntitled,
  loadEntitlement,
  purchaseSubscription,
  restorePurchases,
  SubProduct,
  setupPurchaseListener,
  SUBSCRIPTION_SKU,
  syncEntitlementFromBackend,
} from "@/src/lib/subscription";

const ANDROID_PACKAGE = "com.cryptostockapps.aicryptostockpro";

type SubscriptionState = {
  loaded: boolean;
  isPremium: boolean;
  entitlement: Entitlement | null;
  product: SubProduct | null;
  loading: boolean;
  connected: boolean;
  subscribe: (basePlanId?: string, offerId?: string) => Promise<void>;
  restore: () => Promise<void>;
  refresh: () => Promise<void>;
};

const SubscriptionContext = createContext<SubscriptionState | undefined>(undefined);

export function SubscriptionProvider({ children }: { children: React.ReactNode }) {
  const [loaded, setLoaded] = useState(false);
  const [entitlement, setEntitlement] = useState<Entitlement | null>(null);
  const [product, setProduct] = useState<SubProduct | null>(null);
  const [loading, setLoading] = useState(false);
  const [connected, setConnected] = useState(false);
  const deviceIdRef = useRef<string>("");

  /**
   * Apply a backend sync result to local state — but only if it doesn't
   * downgrade a still-valid entitlement. Rules:
   *   • synced is null/undefined  → ignore (network failed, keep local).
   *   • synced.entitled == true   → always apply (may extend expiry).
   *   • synced.entitled == false  → apply ONLY if local is also expired /
   *     unentitled. If local is still active and unexpired, keep local
   *     (this prevents transient backend blips from kicking premium users
   *     out of asset detail screens mid-session).
   */
  const applySync = useCallback(
    (synced: Entitlement | null) => {
      if (!synced) return;
      // Use functional setState to safely capture the LATEST entitlement,
      // avoiding stale closures inside intervals / listeners.
      setEntitlement((prev) => {
        if (synced.entitled) return synced;
        // Backend says not entitled. Only trust it if local also thinks so.
        if (!prev || !isEntitled(prev)) return synced;
        return prev; // keep still-valid local entitlement
      });
    },
    [],
  );

  // ---- Bootstrap: load cached entitlement + sync backend + init IAP + wire listener ----
  useEffect(() => {
    let cleanup: (() => void) | null = null;
    (async () => {
      const cached = await loadEntitlement();
      if (cached) setEntitlement(cached);

      const deviceId = await getDeviceId();
      deviceIdRef.current = deviceId;

      // Backend is source of truth for RENEWING entitlement (extending
      // expiry, catching a new purchase). But we must NOT downgrade a
      // still-valid local entitlement just because a single request came
      // back with entitled=false (e.g. transient backend hiccup, service
      // account key propagation lag). Doing so caused users to be kicked
      // out of asset detail screens mid-session. See `applySync` below.
      try {
        const synced = await Promise.race([
          syncEntitlementFromBackend(deviceId),
          new Promise<null>((r) => setTimeout(() => r(null), 2500)),
        ]);
        applySync(synced);
      } catch {
        /* ignore — trust local cache */
      }

      if (Platform.OS === "android") {
        // v10.2.16 — initConnection Play Billing bisa menggantung di
        // sebagian perangkat (Play Services lambat/absen) → subLoaded
        // tak pernah true → accessLoaded false selamanya → halaman
        // grafik aset spinner tanpa selesai. Batasi 6 detik.
        const iap = await Promise.race([
          initIap(),
          new Promise<null>((r) => setTimeout(() => r(null), 6000)),
        ]);
        setConnected(!!iap);
        if (iap) {
          // Fetch product metadata in background
          fetchSubscription()
            .then((p) => {
              if (p) setProduct(p);
            })
            .catch(() => {});

          // Attach global purchase listener
          cleanup = setupPurchaseListener({
            deviceId,
            packageName: ANDROID_PACKAGE,
            onSuccess: (ent) => {
              setEntitlement(ent);
              if (ent.entitled) {
                Alert.alert(
                  "Subscription Active",
                  "Thank you! Your premium access is now active.",
                );
              }
            },
            onError: (msg) => {
              Alert.alert("Subscription", `Purchase issue: ${msg}`);
            },
            onCancel: () => {
              /* silent */
            },
          });
        }
      }
      setLoaded(true);
    })();

    return () => {
      if (cleanup) cleanup();
    };
  }, []);

  const subscribe = useCallback(async (basePlanId?: string, offerId?: string) => {
    if (Platform.OS !== "android") {
      Alert.alert(
        "Android Only",
        "Please install AI Crypstock Pro from Google Play on your Android device to subscribe.",
      );
      return;
    }
    setLoading(true);
    try {
      await purchaseSubscription(basePlanId, offerId);
      // Success is handled by the global purchaseUpdatedListener
    } catch (e: any) {
      const raw = String(e?.message ?? e ?? "");
      const lower = raw.toLowerCase();

      // "Something went wrong on our end" and similar generic Google Play
      // errors are almost always caused by test-environment state on the
      // device, NOT by a bug in our code. Give the user actionable
      // troubleshooting steps rather than a cryptic error string.
      const isGooglePlayGenericError =
        lower.includes("something went wrong") ||
        lower.includes("try again") ||
        lower.includes("play services") ||
        lower.includes("unavailable") ||
        e?.code === "E_UNKNOWN" ||
        e?.code === "E_SERVICE_ERROR";

      if (isGooglePlayGenericError) {
        // v8.12.66 — Surface the RAW Play error code/message in the dialog.
        // Promo offers with eligibility rules (e.g. "Never had any
        // subscription") fail with this same generic error on accounts
        // that are INELIGIBLE (any past purchase — including license-
        // tester purchases — counts as "had a subscription"). Without
        // the raw detail there is no way to tell propagation delay from
        // ineligibility.
        const detail = raw ? `\n\nDetail: ${raw.slice(0, 180)}` : "";
        Alert.alert(
          "Google Play Issue",
          "Google Play could not process this request right now.\n\n" +
            "This is usually caused by:\n" +
            "• Play Store cache — clear it in Settings → Apps → Google Play Store → Storage → Clear cache.\n" +
            "• A previous test subscription still active — open Play Store → Payments & subscriptions → Subscriptions and cancel any AI Crypto Stock Pro entry.\n" +
            "• Recent Play Console change still propagating — wait 15–60 min and retry.\n" +
            "• LIMITED promo eligibility — the 2-Months promo is only for accounts that have NEVER had any subscription (past test purchases count). Test it with a fresh Google account.\n\n" +
            "Real (production) users will not see this issue." +
            detail,
          [{ text: "OK" }],
        );
      // v8.12.67 — Our OWN tagged errors get a SPECIFIC dialog so the
      // real cause (promo offer not visible / wrong ID / wrong base
      // plan in Play Console) is never hidden behind a generic message.
      } else if (e?.code === "APP_PROMO_NOT_FOUND") {
        Alert.alert(
          "Promo Not Available",
          "The LIMITED promo offer could not be found on this device.\n\n" +
            "Please check in Play Console:\n" +
            "1. Offer ID is exactly \"september-promo-2for1\".\n" +
            "2. The offer is ACTIVE on base plan \"pro-1m\" (1 Month).\n" +
            "3. Wait 15–60 min after activation for Google to sync.\n\n" +
            "If all of the above is correct, the account may not meet the promo eligibility rules.",
          [{ text: "OK" }],
        );
      } else if (
        // v8.0.3: only show "Already Subscribed" when our own local guard
        // fired (marker code above). Native Play errors that happen to
        // contain the word "subscribed" now flow through to the generic
        // handler further down so users on EXPIRED accounts are not
        // misdirected into cancelling a subscription they no longer have.
        e?.code === "APP_ACTIVE_SUB_GUARD"
      ) {
        Alert.alert(
          "Already Subscribed",
          raw,
          [{ text: "OK" }],
        );
      } else if (
        lower.includes("invalid argument") ||
        lower.includes("invalid arguments")
      ) {
        Alert.alert(
          "Purchase Issue",
          "Google Play rejected this purchase.\n\n" +
            "Most likely you already have an active or recently-cancelled subscription. Please:\n" +
            "1. Open Play Store → profile → Payments & subscriptions → Subscriptions.\n" +
            "2. Cancel any existing AI Crypto Stock Pro plan.\n" +
            "3. Wait 2–5 minutes for Google to sync.\n" +
            "4. Try again.",
        );
      } else if (
        lower.includes("not active") ||
        lower.includes("basePlan") ||
        lower.includes("base plan")
      ) {
        Alert.alert(
          "Plan Not Available",
          "This subscription plan is not yet active in Google Play Console. " +
            "Please try a different plan or contact support.",
        );
      } else {
        Alert.alert("Subscription", `Could not start purchase: ${raw}`);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  const restore = useCallback(async () => {
    if (Platform.OS !== "android") return;
    setLoading(true);
    try {
      const deviceId = deviceIdRef.current || (await getDeviceId());
      const ent = await restorePurchases(deviceId, ANDROID_PACKAGE);
      if (ent) {
        setEntitlement(ent);
        if (ent.entitled) {
          Alert.alert("Restored", "Your subscription has been restored.");
        } else {
          Alert.alert(
            "Restore",
            `No active subscription found (status: ${ent.status}).`,
          );
        }
      } else {
        Alert.alert(
          "Restore",
          "No previous purchase was found for this Google account.",
        );
      }
    } catch (e: any) {
      Alert.alert("Restore", `Failed: ${e?.message ?? e}`);
    } finally {
      setLoading(false);
    }
  }, []);

  const refresh = useCallback(async () => {
    const cached = await loadEntitlement();
    setEntitlement(cached);
  }, []);

  // ---- Auto-lock on expiry (issue #2, #3) ----
  // Every 30s, force a re-check of isEntitled by bumping a tick counter. This
  // ensures `isPremium` transitions from true → false the moment expiryTime
  // passes, without requiring the app to be restarted.
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick((x) => x + 1), 30_000);
    return () => clearInterval(id);
  }, []);
  // Also re-check on app-foreground (background→active) so users returning
  // from a long absence see the correct locked state immediately.
  useEffect(() => {
    const sub = AppState.addEventListener("change", (state) => {
      if (state === "active") {
        setTick((x) => x + 1);
        // Also refresh entitlement from backend (source of truth).
        (async () => {
          const deviceId = deviceIdRef.current || (await getDeviceId());
          try {
            const synced = await syncEntitlementFromBackend(deviceId);
            applySync(synced);
          } catch {
            /* ignore */
          }
        })();
      }
    });
    return () => sub.remove();
  }, []);
  // Backend re-sync every 2 min so expired subscriptions get locked without
  // requiring app restart / background transition.
  useEffect(() => {
    const id = setInterval(async () => {
      const deviceId = deviceIdRef.current || (await getDeviceId());
      try {
        const synced = await syncEntitlementFromBackend(deviceId);
        applySync(synced);
      } catch {
        /* silent */
      }
    }, 2 * 60_000);
    return () => clearInterval(id);
  }, []);
  // Trigger re-fetch of getAvailablePurchases in background occasionally in
  // case the user cancelled from Play Store settings while offline.
  useEffect(() => {
    if (!connected || Platform.OS !== "android") return;
    const id = setInterval(async () => {
      try {
        const deviceId = deviceIdRef.current || (await getDeviceId());
        const ent = await restorePurchases(deviceId, ANDROID_PACKAGE);
        // v8.1.1 — Use applySync guard here too. Directly assigning the
        // result caused Bug #5 (user briefly kicked out of premium when
        // `restorePurchases` returned `entitled:false` due to a slow
        // Play Store ack or transient network issue). applySync only
        // downgrades to `not entitled` when the local cache also agrees.
        applySync(ent);
      } catch {
        /* silent */
      }
    }, 5 * 60_000); // every 5 minutes
    return () => clearInterval(id);
  }, [connected, applySync]);

  const value = useMemo<SubscriptionState>(
    () => ({
      loaded,
      isPremium: isEntitled(entitlement),
      entitlement,
      product,
      loading,
      connected,
      subscribe,
      restore,
      refresh,
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [loaded, entitlement, product, loading, connected, subscribe, restore, refresh, tick],
  );

  return (
    <SubscriptionContext.Provider value={value}>
      {children}
    </SubscriptionContext.Provider>
  );
}

export function useSubscription(): SubscriptionState {
  const ctx = useContext(SubscriptionContext);
  if (!ctx) {
    throw new Error("useSubscription must be used within SubscriptionProvider");
  }
  return ctx;
}

// Convenience helper — clears local cache (does NOT cancel Play subscription)
export async function localClearSubscription(): Promise<void> {
  await clearEntitlement();
}

export { SUBSCRIPTION_SKU };
