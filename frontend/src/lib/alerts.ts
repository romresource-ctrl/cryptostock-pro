/**
 * useAlerts — client-side price alert store (AsyncStorage-backed).
 *
 * Data model per alert:
 *   { id, market, symbol, direction: 'above' | 'below',
 *     target: number, enabled: boolean, createdAt, triggeredAt? }
 *
 * The engine (see `useAlertEngine.ts`) evaluates every alert against the
 * live dashboard prices every refresh cycle and fires a local notification
 * when a target is crossed.  Once triggered, an alert self-disables (one-
 * shot) to avoid spam, but stays in the list with `triggeredAt` set so
 * the user can inspect the history.
 */
import AsyncStorage from "@react-native-async-storage/async-storage";
import { useCallback, useEffect, useState } from "react";

const STORAGE_KEY = "dashboard:alerts";

export type AlertRow = {
  id: string;
  market: string;
  symbol: string;
  direction: "above" | "below";
  target: number;
  enabled: boolean;
  createdAt: number;
  triggeredAt?: number;
  note?: string;
};

const listeners = new Set<() => void>();
let cache: AlertRow[] = [];
let hydrated = false;

async function hydrate() {
  if (hydrated) return;
  try {
    const raw = await AsyncStorage.getItem(STORAGE_KEY);
    if (raw) {
      const arr = JSON.parse(raw);
      if (Array.isArray(arr)) cache = arr.filter((x) => x && x.id);
    }
  } catch {
    /* ignore */
  } finally {
    hydrated = true;
    listeners.forEach((fn) => fn());
  }
}

async function persist() {
  try {
    await AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(cache));
  } catch {
    /* silent */
  }
}

function makeId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function notify() {
  listeners.forEach((fn) => fn());
}

export function useAlerts() {
  const [snapshot, setSnapshot] = useState<AlertRow[]>(cache);
  const [ready, setReady] = useState<boolean>(hydrated);

  useEffect(() => {
    void hydrate();
    const cb = () => {
      setSnapshot([...cache]);
      setReady(true);
    };
    listeners.add(cb);
    if (hydrated) cb();
    return () => {
      listeners.delete(cb);
    };
  }, []);

  const add = useCallback(
    (row: Omit<AlertRow, "id" | "createdAt" | "enabled" | "triggeredAt">) => {
      const full: AlertRow = {
        id: makeId(),
        createdAt: Date.now(),
        enabled: true,
        ...row,
      };
      cache = [...cache, full];
      void persist();
      notify();
      return full;
    },
    [],
  );

  const update = useCallback((id: string, patch: Partial<AlertRow>) => {
    cache = cache.map((a) => (a.id === id ? { ...a, ...patch } : a));
    void persist();
    notify();
  }, []);

  const remove = useCallback((id: string) => {
    cache = cache.filter((a) => a.id !== id);
    void persist();
    notify();
  }, []);

  const clear = useCallback(() => {
    cache = [];
    void persist();
    notify();
  }, []);

  return {
    alerts: snapshot,
    ready,
    add,
    update,
    remove,
    clear,
  };
}

// Direct (non-hook) accessors for the alert engine.
export function getAlertsSync(): AlertRow[] {
  return cache;
}
export function markAlertTriggered(id: string) {
  cache = cache.map((a) =>
    a.id === id ? { ...a, enabled: false, triggeredAt: Date.now() } : a,
  );
  void persist();
  notify();
}
