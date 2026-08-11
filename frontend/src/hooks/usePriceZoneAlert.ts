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
  | "entry1" | "entry2" | "entry3"
  | "tp1" | "tp2" | "tp3"
  | "sl"
  | "hold";

const BEEP_URL =
  "https://customer-assets.emergentagent.com/job_swift-market/artifacts/uwx4jcxr_beep.mp3";
const BAND_PCT = 0.0015; // ±0.15%

interface Args {
  livePrice: number | null | undefined;
  entryLow: number | null | undefined;
  entryHigh: number | null | undefined;
  /** v8.8.1 — 3-tier entry ranges (deep=1, moderate=2, aggressive=3). */
  entryModerateLow?: number | null;
  entryModerateHigh?: number | null;
  entryAggressiveLow?: number | null;
  entryAggressiveHigh?: number | null;
  takeProfit: number | null | undefined;
  takeProfit2?: number | null | undefined;
  takeProfit3?: number | null | undefined;
  stopLoss: number | null | undefined;
  action?: string | null;
  confidence?: number | null;
  isPremium?: boolean | null;
}

interface Levels {
  entry1Low: number | null; entry1High: number | null;
  entry2Low: number | null; entry2High: number | null;
  entry3Low: number | null; entry3High: number | null;
  tp1: number | null; tp2: number | null; tp3: number | null;
  sl: number | null;
}

function inRange(px: number, lo: number, hi: number): boolean {
  return px >= lo && px <= hi;
}

function pctBand(target: number): [number, number] {
  return [target * (1 - BAND_PCT), target * (1 + BAND_PCT)];
}

export function usePriceZoneAlert({
  livePrice, entryLow, entryHigh, takeProfit, takeProfit2, takeProfit3, stopLoss,
  entryModerateLow, entryModerateHigh, entryAggressiveLow, entryAggressiveHigh,
  action, confidence, isPremium,
}: Args): AlertZone {
  const player = useAudioPlayer({ uri: BEEP_URL });

  // v8.12.1 — Gate rules split by action:
  //   • BUY/SELL: require confidence ≥ 85 + is_premium ≠ false. Fires
  //     any of entry1/2/3, tp1/2/3, sl.
  //   • HOLD: always allowed to render the "HOLD" pill (no confidence
  //     floor — HOLD is informational, not actionable). Only zone="hold"
  //     can be committed for HOLD signals.
  //   • Any other (empty/null): no alert.
  const gateMode = useMemo<"actionable" | "hold" | "off">(() => {
    const act = String(action || "").toUpperCase();
    if (act === "HOLD") return "hold";
    if (act !== "BUY" && act !== "SELL") return "off";
    if (confidence != null && Number.isFinite(confidence) && confidence < 85) return "off";
    if (isPremium === false) return "off";
    return "actionable";
  }, [action, confidence, isPremium]);
  const gateOk = gateMode !== "off";

  // Compute ladder levels once per signal input change
  const levels: Levels = useMemo(() => {
    const num = (x: unknown): number | null =>
      Number.isFinite(x as number) ? (x as number) : null;
    const e1Low = num(entryLow);
    const e1High = num(entryHigh);
    const e2Low = num(entryModerateLow) ?? e1Low;
    const e2High = num(entryModerateHigh) ?? e1High;
    const e3Low = num(entryAggressiveLow) ?? e1Low;
    const e3High = num(entryAggressiveHigh) ?? e1High;
    const tp = num(takeProfit);
    const sl = num(stopLoss);
    const bTp2 = num(takeProfit2);
    const bTp3 = num(takeProfit3);

    let tp1 = tp;
    let tp2: number | null = bTp2;
    let tp3: number | null = bTp3;
    if ((tp2 == null || tp3 == null) && tp != null && e1High != null && tp > e1High) {
      const step = tp - e1High;
      tp2 = tp2 ?? e1High + step * 1.7;
      tp3 = tp3 ?? e1High + step * 2.5;
    }
    return {
      entry1Low: e1Low, entry1High: e1High,
      entry2Low: e2Low, entry2High: e2High,
      entry3Low: e3Low, entry3High: e3High,
      tp1, tp2, tp3, sl,
    };
  }, [entryLow, entryHigh, entryModerateLow, entryModerateHigh,
      entryAggressiveLow, entryAggressiveHigh,
      takeProfit, takeProfit2, takeProfit3, stopLoss]);

  const [zone, setZone] = useState<AlertZone>("idle");
  // v8.7.22 — 700ms stability gate: a candidate zone must persist for
  // at least 700ms before it commits and paints on the UI. Prevents
  // the price from momentarily grazing a zone during initial WS
  // handshake / mount from firing a false alert. Idle commits
  // immediately (no wait) so alerts can DISAPPEAR fast.
  const settleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingRef = useRef<{ zone: AlertZone } | null>(null);
  const commitTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const armedRef = useRef<Record<AlertZone, boolean>>({
    idle: true,
    entry1: true, entry2: true, entry3: true,
    tp1: true, tp2: true, tp3: true,
    sl: true,
    hold: true,
  });

  // Reset stability state whenever the gate flips off (signal changes)
  useEffect(() => {
    if (!gateOk) {
      pendingRef.current = null;
      if (commitTimerRef.current) {
        clearTimeout(commitTimerRef.current);
        commitTimerRef.current = null;
      }
      if (settleTimerRef.current) {
        clearTimeout(settleTimerRef.current);
        settleTimerRef.current = null;
      }
    }
  }, [gateOk]);

  useEffect(() => {
    // Gate: no actionable signal → no alert at all
    if (!gateOk) {
      setZone("idle");
      pendingRef.current = null;
      if (commitTimerRef.current) {
        clearTimeout(commitTimerRef.current);
        commitTimerRef.current = null;
      }
      return;
    }
    if (livePrice == null || !Number.isFinite(livePrice)) {
      setZone("idle");
      pendingRef.current = null;
      return;
    }
    const px = livePrice as number;
    let next: AlertZone = "idle";

    // v8.12.1 — HOLD mode: only the "hold" zone is emitted. No entry/TP/SL
    // pills fire when the underlying signal is HOLD (they'd be misleading
    // — HOLD has no valid entry ladder).
    if (gateMode === "hold") {
      next = "hold";
    } else {
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
    // v8.8.1 — 3-tier entry zones (deep = ENTRY-1, moderate = ENTRY-2,
    // aggressive = ENTRY-3). Each uses its own low..high range from
    // backend indicators.py.
    const inBand = (lo: number | null, hi: number | null) =>
      lo != null && hi != null && px >= Math.min(lo, hi) && px <= Math.max(lo, hi);
    if (next === "idle" && inBand(levels.entry1Low, levels.entry1High)) next = "entry1";
    if (next === "idle" && inBand(levels.entry2Low, levels.entry2High)) next = "entry2";
    if (next === "idle" && inBand(levels.entry3Low, levels.entry3High)) next = "entry3";
    }
    // v8.12.1 — Down-side/dip-buy zones removed; entry1/2/3 already cover
    // the 3-tier entry ladder (deep/moderate/aggressive) uniformly.

    // v8.7.22 — Stability commit: only setZone(next) if the candidate
    // has been the same for ≥700ms. Idle commits immediately so alerts
    // clear fast. Each new candidate resets the 700ms timer.
    const commitZone = (committed: AlertZone) => {
      setZone((prev) => {
        if (prev === committed) return prev;
        if (committed !== "idle" && armedRef.current[committed]) {
          armedRef.current[committed] = false;
          _playBeep(player);
        }
        if (committed === "idle") {
          (Object.keys(armedRef.current) as AlertZone[]).forEach((k) => {
            armedRef.current[k] = true;
          });
        } else {
          (Object.keys(armedRef.current) as AlertZone[]).forEach((k) => {
            if (k !== committed) armedRef.current[k] = true;
          });
        }
        return committed;
      });
    };

    if (pendingRef.current?.zone === next) {
      // Same candidate as last tick — timer already scheduled (or already
      // committed). Nothing to do.
      return;
    }
    // New candidate: cancel any pending commit, restart the 700ms timer
    if (commitTimerRef.current) {
      clearTimeout(commitTimerRef.current);
      commitTimerRef.current = null;
    }
    pendingRef.current = { zone: next };
    if (next === "idle") {
      commitZone("idle");
    } else {
      commitTimerRef.current = setTimeout(() => {
        commitZone(next);
        commitTimerRef.current = null;
      }, 700);
    }
  }, [livePrice, levels, player, gateOk, gateMode]);

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
