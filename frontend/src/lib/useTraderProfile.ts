/**
 * v8.12.57 — Trader Profile hook.
 * v9.3.0 — TOGGLE behaviour: tapping the active profile again UNSELECTS
 * it (explicit=false → apiProfile=null) and the backend falls back to
 * the default Confluence v9.0 engine. The VWAP Session engines only run
 * when the user has explicitly chosen scalper / day / swing.
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
import { api } from "./api";
import { getDeviceId } from "./deviceId";

export type TraderProfile = "scalper" | "day" | "swing" | "longterm";

const STORAGE_KEY = "@ai-crypto-stock-pro:trader-profile:v1";

// v10.1.1 — Sinkron GLOBAL ke bot config: setiap kali user ganti Trader
// Profile di MANA PUN (dashboard header, modal picker, dsb) langsung
// panggil backend untuk update field bot.profile. Sebelumnya sync hanya
// terjadi saat user membuka layar ASI-Bot — menyebabkan Full-Auto scanner
// terus memakai profile lama (mis. tetap "scalper" walau user ganti ke
// "day" di header), sehingga sinyal profile baru tidak pernah dieksekusi.
async function _syncProfileToBot(apiProfile: TraderProfile | null): Promise<void> {
  try {
    const deviceId = await getDeviceId();
    if (!deviceId) return;
    const current = await api.asi.getBot(deviceId).catch(() => null);
    if (!current) return;
    const targetBackend = apiProfile; // null → confluence default
    if ((current.profile ?? null) === targetBackend) return;
    await api.asi.saveBot(deviceId, { ...current, profile: targetBackend as any });
  } catch {
    /* fire-and-forget: UI tetap pakai pilihan user walau sync gagal */
  }
}

// ---- Shared module-level store (single source of truth) ----
let _profile: TraderProfile = "day";
let _explicit = false;  // true hanya jika user pernah memilih secara eksplisit
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

function _getExplicit(): boolean {
  return _explicit;
}

async function _ensureInit(): Promise<void> {
  if (_initStarted) return;
  _initStarted = true;
  try {
    const raw = await AsyncStorage.getItem(STORAGE_KEY);
    if (raw && (PROFILE_ORDER as string[]).includes(raw)) {
      _profile = raw as TraderProfile;
      _explicit = true;  // tersimpan di storage = user pernah memilih
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
    // v10.0.11 — Label UI "Intraday" (dulu "Day Trader") per permintaan
    // user. Mapping backend tetap `day` → tidak mengubah formula.
    label: "Intraday",
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
    emoji: "🧠",
    // v10.0.11 — Label UI "Confluence v9" (dulu "Long-term"). Backend
    // profile `longterm` memakai engine Confluence default (sama dengan
    // profile=null). Rename murni di UI untuk kejelasan user.
    label: "Confluence v9",
    timeframe: "Multi-TF",
    description: "Confluence EMA 50/100/200 — mesin default v9",
    color: "#3B82F6",
  },
};

export const PROFILE_ORDER: TraderProfile[] = ["scalper", "day", "swing", "longterm"];

export function useTraderProfile(): {
  profile: TraderProfile;
  setProfile: (p: TraderProfile) => void;
  loaded: boolean;
  explicit: boolean;
  apiProfile: TraderProfile | null;
} {
  // One shared store — every component re-renders together on change.
  useEffect(() => {
    _ensureInit();
  }, []);
  const profile = useSyncExternalStore(_subscribe, _getProfile, _getProfile);
  const loaded = useSyncExternalStore(_subscribe, _getLoaded, _getLoaded);
  const explicit = useSyncExternalStore(_subscribe, _getExplicit, _getExplicit);

  const setProfile = (p: TraderProfile) => {
    // v9.3.0 — Toggle: ketuk profil yang sedang aktif = LEPAS pilihan,
    // sinyal kembali ke mesin Confluence v9.0 (default tanpa profil).
    if (_explicit && p === _profile) {
      _explicit = false;
      _notify();
      AsyncStorage.removeItem(STORAGE_KEY).catch(() => {
        /* ignore */
      });
      // v10.1.1 — Lepas profile = sync bot ke null (default Confluence
      // longgar gate 5), bukan ke "longterm"/legacy.
      _syncProfileToBot(null);
      return;
    }
    _profile = p;
    _explicit = true;
    _notify();
    AsyncStorage.setItem(STORAGE_KEY, p).catch(() => {
      /* ignore */
    });
    // v10.1.1 — Push ke bot config SEGERA supaya Full-Auto scanner
    // berikutnya (≤90 detik) sudah memakai profile baru.
    _syncProfileToBot(p);
  };

  return {
    profile,
    setProfile,
    loaded,
    explicit,
    // null → jangan kirim ?profile= ke backend (Confluence v9.0 default).
    apiProfile: explicit ? profile : null,
  };
}
