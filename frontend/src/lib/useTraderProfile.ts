/**
 * v8.12.57 — Trader Profile hook.
 *
 * Persists the user's Trader Profile choice (scalper / day / swing /
 * longterm) in AsyncStorage. The current profile is passed to every
 * signal-generating endpoint (crypto / forex / gold_silver only) so
 * the backend can tune EMA windows, RSI period, and confidence gate
 * per the user's trading horizon.
 *
 * Default: "day" (matches the legacy v8.x behaviour so any pre-v3
 * install keeps their existing signals until they explicitly switch).
 *
 * v8.12.74 — CRITICAL FIX: the hook used to keep a PRIVATE useState
 * per call site. The dashboard header and the picker modal each owned
 * a separate copy, so picking a profile in the modal never updated the
 * header icon (it stayed ⚡ "day" until the next app restart). The
 * state is now a single MODULE-LEVEL store shared by every component
 * via useSyncExternalStore — any change propagates instantly.
 */
import { useEffect, useSyncExternalStore } from "react";
import AsyncStorage from "@react-native-async-storage/async-storage";

export type TraderProfile = "scalper" | "day" | "swing" | "longterm";

const STORAGE_KEY = "@ai-crypto-stock-pro:trader-profile:v1";

// ---- Shared module-level store (single source of truth) ----
let _profile: TraderProfile = "day";
let _loaded = false;
let _initStarted = false;
const _listeners = new Set<() => void>();

function _notify() {
  _listeners.forEach((l) => l());
}

function _subscribe(listener: () => void): () => void {
  _listeners.add(listener);
  return () => {
    _listeners.delete(listener);
  };
}

function _getProfile(): TraderProfile {
  return _profile;
}

function _getLoaded(): boolean {
  return _loaded;
}

async function _ensureInit(): Promise<void> {
  if (_initStarted) return;
  _initStarted = true;
  try {
    const raw = await AsyncStorage.getItem(STORAGE_KEY);
    if (raw && (PROFILE_ORDER as string[]).includes(raw)) {
      _profile = raw as TraderProfile;
    }
  } catch {
    /* ignore */
  } finally {
    _loaded = true;
    _notify();
  }
}

export const PROFILE_META: Record<
  TraderProfile,
  {
    emoji: string;
    label: string;
    timeframe: string;
    description: string;
    color: string;
  }
> = {
  scalper: {
    emoji: "🏃",
    label: "Scalper",
    timeframe: "5m–15m",
    description: "VWAP deviasi + breakout box-10 · entry kilat",
    color: "#EF4444",
  },
  day: {
    emoji: "⚡",
    label: "Day Trader",
    timeframe: "1h–4h",
    description: "VWAP reclaim/rejection + box-20 · intraday",
    color: "#F0B90B",
  },
  swing: {
    emoji: "📈",
    label: "Swing",
    timeframe: "4h–24h",
    description: "VWAP + breakout box-50 + reversal · multi-hari",
    color: "#22C55E",
  },
  longterm: {
    emoji: "🐢",
    label: "Long-term",
    timeframe: "1D+",
    description: "Confluence EMA 50/100/200 · position hold",
    color: "#3B82F6",
  },
};

export const PROFILE_ORDER: TraderProfile[] = ["scalper", "day", "swing", "longterm"];

export function useTraderProfile(): {
  profile: TraderProfile;
  setProfile: (p: TraderProfile) => void;
  loaded: boolean;
} {
  // One shared store — every component re-renders together on change.
  useEffect(() => {
    _ensureInit();
  }, []);
  const profile = useSyncExternalStore(_subscribe, _getProfile, _getProfile);
  const loaded = useSyncExternalStore(_subscribe, _getLoaded, _getLoaded);

  const setProfile = (p: TraderProfile) => {
    if (p === _profile) return;
    _profile = p;
    _notify();
    AsyncStorage.setItem(STORAGE_KEY, p).catch(() => {
      /* ignore */
    });
  };

  return { profile, setProfile, loaded };
}
