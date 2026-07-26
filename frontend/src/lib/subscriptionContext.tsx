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
} from "@/src/lib/subscription";

const ANDROID_PACKAGE = "com.cryptostockapps.aicryptostockpro";

type SubscriptionState = {
  loaded: boolean;
  isPremium: boolean;
  entitlement: Entitlement | null;
  product: SubProduct | null;
  loading: boolean;
  connected: boolean;
  subscribe: (basePlanId?: string) => Promise<void>;
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

  // ---- Bootstrap: load cached entitlement + init IAP + wire listener ----
  useEffect(() => {
    let cleanup: (() => void) | null = null;
    (async () => {
      const cached = await loadEntitlement();
      if (cached) setEntitlement(cached);

      const deviceId = await getDeviceId();
      deviceIdRef.current = deviceId;

      if (Platform.OS === "android") {
        const iap = await initIap();
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

  const subscribe = useCallback(async (basePlanId?: string) => {
    if (Platform.OS !== "android") {
      Alert.alert(
        "Android Only",
        "Please install AI Crypstock Pro from Google Play on your Android device to subscribe.",
      );
      return;
    }
    setLoading(true);
    try {
      await purchaseSubscription(basePlanId);
      // Success is handled by the global purchaseUpdatedListener
    } catch (e: any) {
      Alert.alert("Subscription", `Could not start purchase: ${e?.message ?? e}`);
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
      if (state === "active") setTick((x) => x + 1);
    });
    return () => sub.remove();
  }, []);
  // Trigger re-fetch of getAvailablePurchases in background occasionally in
  // case the user cancelled from Play Store settings while offline.
  useEffect(() => {
    if (!connected || Platform.OS !== "android") return;
    const id = setInterval(async () => {
      try {
        const deviceId = deviceIdRef.current || (await getDeviceId());
        const ent = await restorePurchases(deviceId, ANDROID_PACKAGE);
        if (ent) setEntitlement(ent);
      } catch {
        /* silent */
      }
    }, 5 * 60_000); // every 5 minutes
    return () => clearInterval(id);
  }, [connected]);

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
