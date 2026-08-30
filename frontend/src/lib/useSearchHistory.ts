/**
 * v8.12.38 — Recent Search History.
 *
 * Persists the last 5 asset symbols the user has searched into AsyncStorage
 * so they can retap them without retyping. Used by the dashboard search bar
 * to render clickable "recent" chips right underneath the input whenever
 * the current query is empty.
 *
 * Contract:
 *   - `push(symbol)` — call once the user finishes searching (we call it
 *     when the user actually taps a result card so we only remember the
 *     symbols they cared about, not every random keystroke).
 *   - `history` — current ordered list, most-recent first.
 *   - `clear()` — wipe.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import AsyncStorage from "@react-native-async-storage/async-storage";

const STORAGE_KEY = "@ai-crypto-stock-pro:search-history:v1";
const MAX_ITEMS = 5;

export function useSearchHistory(): {
  history: string[];
  push: (symbol: string) => void;
  clear: () => void;
} {
  const [history, setHistory] = useState<string[]>([]);
  const loadedRef = useRef(false);

  // Load once on mount.
  useEffect(() => {
    (async () => {
      try {
        const raw = await AsyncStorage.getItem(STORAGE_KEY);
        if (raw) {
          const arr = JSON.parse(raw);
          if (Array.isArray(arr)) {
            setHistory(arr.filter((x) => typeof x === "string").slice(0, MAX_ITEMS));
          }
        }
      } catch {
        /* ignore */
      } finally {
        loadedRef.current = true;
      }
    })();
  }, []);

  const persist = useCallback(async (list: string[]) => {
    try {
      await AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(list));
    } catch {
      /* ignore */
    }
  }, []);

  const push = useCallback(
    (symbolRaw: string) => {
      const sym = (symbolRaw || "").trim().toUpperCase();
      if (!sym) return;
      setHistory((prev) => {
        const next = [sym, ...prev.filter((s) => s !== sym)].slice(0, MAX_ITEMS);
        void persist(next);
        return next;
      });
    },
    [persist],
  );

  const clear = useCallback(() => {
    setHistory([]);
    void persist([]);
  }, [persist]);

  return { history, push, clear };
}
