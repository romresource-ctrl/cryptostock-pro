/**
 * useWatchlist — AsyncStorage-backed favorites list for the dashboard.
 *
 * Data model: array of `${market}:${symbol}` keys, e.g. "crypto:BTC",
 * "stock_us:AAPL".  Keying by market prevents accidental collisions
 * between e.g. crypto "APT" and stock "APT" (both real).
 *
 * The hook returns a stable `toggle()` callback plus a `has()` checker,
 * matching the shape callers already use for `useSubscription()`.  A
 * cross-tab in-memory notifier keeps every mounted consumer in sync
 * without needing a full React context.
 */
import AsyncStorage from "@react-native-async-storage/async-storage";
import { useCallback, useEffect, useState } from "react";

const STORAGE_KEY = "dashboard:watchlist";

// Cheap pub/sub so multiple components stay synced without a context.
const listeners = new Set<() => void>();
let cache: Set<string> = new Set();
let hydrated = false;

async function hydrate() {
  if (hydrated) return;
  try {
    const raw = await AsyncStorage.getItem(STORAGE_KEY);
    if (raw) {
      const arr = JSON.parse(raw) as string[];
      cache = new Set(arr.filter((x) => typeof x === "string"));
    }
  } catch {
    /* ignore — start empty */
  } finally {
    hydrated = true;
    listeners.forEach((cb) => cb());
  }
}

async function persist() {
  try {
    await AsyncStorage.setItem(STORAGE_KEY, JSON.stringify([...cache]));
  } catch {
    /* silent */
  }
}

export type WatchlistEntry = { market: string; symbol: string };

function keyOf(market: string, symbol: string): string {
  return `${market}:${symbol.toUpperCase()}`;
}

export function parseEntry(key: string): WatchlistEntry | null {
  const idx = key.indexOf(":");
  if (idx <= 0) return null;
  return { market: key.slice(0, idx), symbol: key.slice(idx + 1) };
}

export function useWatchlist() {
  const [snapshot, setSnapshot] = useState<Set<string>>(cache);
  const [ready, setReady] = useState<boolean>(hydrated);

  useEffect(() => {
    void hydrate();
    const cb = () => {
      // Replace the ref so React re-renders (Set identity check).
      setSnapshot(new Set(cache));
      setReady(true);
    };
    listeners.add(cb);
    if (hydrated) cb();
    return () => {
      listeners.delete(cb);
    };
  }, []);

  const has = useCallback(
    (market: string, symbol: string) => snapshot.has(keyOf(market, symbol)),
    [snapshot],
  );

  const toggle = useCallback((market: string, symbol: string) => {
    const k = keyOf(market, symbol);
    if (cache.has(k)) cache.delete(k);
    else cache.add(k);
    void persist();
    listeners.forEach((fn) => fn());
  }, []);

  const clear = useCallback(() => {
    cache = new Set();
    void persist();
    listeners.forEach((fn) => fn());
  }, []);

  return {
    entries: [...snapshot].map(parseEntry).filter(Boolean) as WatchlistEntry[],
    size: snapshot.size,
    ready,
    has,
    toggle,
    clear,
  };
}
