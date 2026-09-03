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
 */
import { useCallback, useEffect, useState } from "react";
import AsyncStorage from "@react-native-async-storage/async-storage";

export type TraderProfile = "scalper" | "day" | "swing" | "longterm";

const STORAGE_KEY = "@ai-crypto-stock-pro:trader-profile:v1";

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
    description: "Fast entries · small wins · EMA 5/13",
    color: "#EF4444",
  },
  day: {
    emoji: "⚡",
    label: "Day Trader",
    timeframe: "1h–4h",
    description: "Balanced · standard v3 · EMA 20/50",
    color: "#F0B90B",
  },
  swing: {
    emoji: "📈",
    label: "Swing",
    timeframe: "4h–24h",
    description: "Selective · MTF confirmed · SL 2×ATR",
    color: "#22C55E",
  },
  longterm: {
    emoji: "🐢",
    label: "Long-term",
    timeframe: "1D+",
    description: "High conviction · EMA 50/200 · SL 3×ATR",
    color: "#3B82F6",
  },
};

export const PROFILE_ORDER: TraderProfile[] = ["scalper", "day", "swing", "longterm"];

export function useTraderProfile(): {
  profile: TraderProfile;
  setProfile: (p: TraderProfile) => void;
  loaded: boolean;
} {
  const [profile, setProfileState] = useState<TraderProfile>("day");
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const raw = await AsyncStorage.getItem(STORAGE_KEY);
        if (raw && (PROFILE_ORDER as string[]).includes(raw)) {
          setProfileState(raw as TraderProfile);
        }
      } catch {
        /* ignore */
      } finally {
        setLoaded(true);
      }
    })();
  }, []);

  const setProfile = useCallback((p: TraderProfile) => {
    setProfileState(p);
    AsyncStorage.setItem(STORAGE_KEY, p).catch(() => {
      /* ignore */
    });
  }, []);

  return { profile, setProfile, loaded };
}
