/**
 * usePriceZoneAlert — v8.7.8
 *
 * Laddered zone-alert hook. Watches live ticker price against multiple
 * levels derived from the AI signal:
 *
 *   Upside ladder (bullish continuation):
 *     • TP-1  = take_profit                             (original TP)
 *     • TP-2  = entry_high + reward × 1.75              (extended target)
 *     • TP-3  = entry_high + reward × 2.5               (max profit target)
 *
 *   Downside ladder (buy-the-dip):
 *     • BUY-3 = entry_low                              (first dip below entry)
 *     • BUY-2 = entry_low − risk × 0.35                (deeper dip)
 *     • BUY-1 = entry_low − risk × 0.70                (bottom / max value)
 *
 *   Terminal zones:
 *     • ENTRY = original entry_low..entry_high band
 *     • SL    = stop_loss ±0.15%
 *
 * A single beep plays the first time price enters ANY new level; each
 * level re-arms once price exits. All bands are ±0.15% around the target
 * unless the level is already a range (ENTRY). Do NOT recompute the base
 * entry / TP / SL — use the backend's own numbers.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { Platform } from "react-native";
import { useAudioPlayer } from "expo-audio";

export type AlertZone =
  | "idle"
  | "entry"
  | "tp1" | "tp2" | "tp3"
  | "buy3" | "buy2" | "buy1"
  | "sl";

const BEEP_URL =
  "https://customer-assets.emergentagent.com/job_swift-market/artifacts/uwx4jcxr_beep.mp3";
const BAND_PCT = 0.0015; // ±0.15%

interface Args {
  livePrice: number | null | undefined;
  entryLow: number | null | undefined;
  entryHigh: number | null | undefined;
  takeProfit: number | null | undefined;
  stopLoss: number | null | undefined;
  /** v8.7.12 — Gate: alerts only fire when the underlying signal is
   *  ACTIONABLE. Otherwise HOLD/low-conf signals spam ENTRY/BUY/TP badges
   *  from arbitrary entry ranges the backend still returns. */
  action?: string | null;
  confidence?: number | null;
  isPremium?: boolean | null;
}

interface Levels {
  entryLow: number | null;
  entryHigh: number | null;
  tp1: number | null;
  tp2: number | null;
  tp3: number | null;
  buy3: number | null;
  buy2: number | null;
  buy1: number | null;
  sl: number | null;
}

function inRange(px: number, lo: number, hi: number): boolean {
  return px >= lo && px <= hi;
}

function pctBand(target: number): [number, number] {
  return [target * (1 - BAND_PCT), target * (1 + BAND_PCT)];
}

export function usePriceZoneAlert({
  livePrice, entryLow, entryHigh, takeProfit, stopLoss,
  action, confidence, isPremium,
}: Args): AlertZone {
  const player = useAudioPlayer({ uri: BEEP_URL });

  // v8.7.12 — Gate alerts to Premium-quality actionable signals only.
  // Rules (ALL must hold):
  //   • action is BUY or SELL (never HOLD)
  //   • confidence >= 85 (matches _MARKET_THRESHOLDS min_conf floor)
  //   • is_premium flag from backend, when available, must be true
  // This prevents the ENTRY / BUY-3 / TP badges from spamming when the
  // backend returns wide, arbitrary entry ranges around a HOLD signal.
  const gateOk = useMemo(() => {
    const act = String(action || "").toUpperCase();
    if (act !== "BUY" && act !== "SELL") return false;
    if (confidence != null && Number.isFinite(confidence) && confidence < 85) return false;
    if (isPremium === false) return false; // explicit false disables; null/undefined stays permissive
    return true;
  }, [action, confidence, isPremium]);

  // Compute ladder levels once per signal input change
  const levels: Levels = useMemo(() => {
    const eLow = Number.isFinite(entryLow as number) ? (entryLow as number) : null;
    const eHigh = Number.isFinite(entryHigh as number) ? (entryHigh as number) : null;
    const tp = Number.isFinite(takeProfit as number) ? (takeProfit as number) : null;
    const sl = Number.isFinite(stopLoss as number) ? (stopLoss as number) : null;
    const px = Number.isFinite(livePrice as number) ? (livePrice as number) : null;

    let tp1: number | null = tp;
    let tp2: number | null = null;
    let tp3: number | null = null;
    if (tp != null) {
      // v8.7.14 — Ladder step = distance from CURRENT PRICE to TP1 (not
      // entry_high). When the signal parks entry deep below price (dip
      // buy zone), entry_high−TP1 is huge and inflates TP-2/TP-3. Using
      // price as the reference gives realistic +$7 / +$15 steps.
      // Falls back to entry_high-based step only if livePrice missing.
      const anchor = px ?? eHigh;
      if (anchor != null && tp > anchor) {
        const step = tp - anchor;
        tp2 = tp + step * 1.15;
        tp3 = tp + step * 2.5;
      }
    }

    let buy3: number | null = eLow;
    let buy2: number | null = null;
    let buy1: number | null = null;
    if (eLow != null && sl != null && eLow > sl) {
      const risk = eLow - sl;
      buy2 = eLow - risk * 0.35;
      buy1 = eLow - risk * 0.70;
    }

    return { entryLow: eLow, entryHigh: eHigh, tp1, tp2, tp3, buy3, buy2, buy1, sl };
  }, [entryLow, entryHigh, takeProfit, stopLoss, livePrice]);

  const [zone, setZone] = useState<AlertZone>("idle");
  const armedRef = useRef<Record<AlertZone, boolean>>({
    idle: true,
    entry: true,
    tp1: true, tp2: true, tp3: true,
    buy3: true, buy2: true, buy1: true,
    sl: true,
  });

  useEffect(() => {
    // Gate: no actionable signal → no alert at all
    if (!gateOk) {
      setZone("idle");
      return;
    }
    if (livePrice == null || !Number.isFinite(livePrice)) {
      setZone("idle");
      return;
    }
    const px = livePrice as number;
    let next: AlertZone = "idle";

    // Priority: SL > TP-3 > TP-2 > TP-1 > ENTRY > BUY-3 > BUY-2 > BUY-1
    // (highest / most-actionable level wins if two overlap)
    const check = (target: number | null, tag: AlertZone) => {
      if (next !== "idle" || target == null) return;
      const [lo, hi] = pctBand(target);
      if (inRange(px, lo, hi)) next = tag;
    };

    // Terminal loss
    check(levels.sl, "sl");
    // Upside ladder — highest first
    check(levels.tp3, "tp3");
    check(levels.tp2, "tp2");
    check(levels.tp1, "tp1");
    // Original entry band (uses actual entry_low..entry_high, no ± band)
    if (
      next === "idle" &&
      levels.entryLow != null && levels.entryHigh != null &&
      inRange(px, levels.entryLow, levels.entryHigh)
    ) {
      next = "entry";
    }
    // Downside ladder — nearest dip first
    check(levels.buy3, "buy3");
    check(levels.buy2, "buy2");
    check(levels.buy1, "buy1");

    setZone((prev) => {
      if (prev === next) return prev;
      if (next !== "idle" && armedRef.current[next]) {
        armedRef.current[next] = false;
        _playBeep(player);
      }
      if (next === "idle") {
        // Re-arm ALL levels once we leave any zone
        (Object.keys(armedRef.current) as AlertZone[]).forEach((k) => {
          armedRef.current[k] = true;
        });
      } else {
        // Re-arm all OTHER levels
        (Object.keys(armedRef.current) as AlertZone[]).forEach((k) => {
          if (k !== next) armedRef.current[k] = true;
        });
      }
      return next;
    });
  }, [livePrice, levels, player, gateOk]);

  return zone;
}

async function _playBeep(player: ReturnType<typeof useAudioPlayer>) {
  try {
    if (typeof player?.seekTo === "function") await player.seekTo(0);
    player?.play?.();
  } catch {
    if (Platform.OS === "web" && typeof window !== "undefined") {
      try {
        const AC: any = (window as any).AudioContext || (window as any).webkitAudioContext;
        if (!AC) return;
        const ctx = new AC();
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.frequency.value = 880;
        osc.type = "sine";
        gain.gain.setValueAtTime(0.15, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.25);
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.start();
        osc.stop(ctx.currentTime + 0.25);
      } catch { /* ignore */ }
    }
  }
}
