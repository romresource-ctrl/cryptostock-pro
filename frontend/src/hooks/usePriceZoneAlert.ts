/**
 * usePriceZoneAlert — v8.7.7
 *
 * Watches the live ticker price against the AI signal's own entry_low /
 * entry_high band, take_profit (±0.15%) and stop_loss (±0.15%) levels.
 * Returns the current alert zone ("entry" | "tp" | "sl" | "idle") and
 * plays a single beep the first time the price enters a zone (re-armed
 * once it exits). Do NOT recompute the entry band here — reuse whatever
 * the backend indicator already produced.
 */
import { useEffect, useRef, useState } from "react";
import { Platform } from "react-native";
import { useAudioPlayer } from "expo-audio";

export type AlertZone = "idle" | "entry" | "tp" | "sl";

const BEEP_URL =
  "https://customer-assets.emergentagent.com/job_swift-market/artifacts/uwx4jcxr_beep.mp3";
const TP_BAND_PCT = 0.0015; // ±0.15%
const SL_BAND_PCT = 0.0015;

interface Args {
  livePrice: number | null | undefined;
  entryLow: number | null | undefined;
  entryHigh: number | null | undefined;
  takeProfit: number | null | undefined;
  stopLoss: number | null | undefined;
}

function inRange(px: number, lo: number, hi: number): boolean {
  return px >= lo && px <= hi;
}

export function usePriceZoneAlert({
  livePrice, entryLow, entryHigh, takeProfit, stopLoss,
}: Args): AlertZone {
  const [zone, setZone] = useState<AlertZone>("idle");
  const armedRef = useRef<{ entry: boolean; tp: boolean; sl: boolean }>({
    entry: true, tp: true, sl: true,
  });
  const player = useAudioPlayer({ uri: BEEP_URL });

  useEffect(() => {
    if (livePrice == null || !Number.isFinite(livePrice)) {
      setZone("idle");
      return;
    }
    let next: AlertZone = "idle";

    if (stopLoss != null && Number.isFinite(stopLoss)) {
      const lo = stopLoss * (1 - SL_BAND_PCT);
      const hi = stopLoss * (1 + SL_BAND_PCT);
      if (inRange(livePrice, lo, hi)) next = "sl";
    }
    if (next === "idle" && takeProfit != null && Number.isFinite(takeProfit)) {
      const lo = takeProfit * (1 - TP_BAND_PCT);
      const hi = takeProfit * (1 + TP_BAND_PCT);
      if (inRange(livePrice, lo, hi)) next = "tp";
    }
    if (
      next === "idle" &&
      entryLow != null && entryHigh != null &&
      Number.isFinite(entryLow) && Number.isFinite(entryHigh)
    ) {
      if (inRange(livePrice, entryLow, entryHigh)) next = "entry";
    }

    setZone((prev) => {
      if (prev === next) return prev;
      if (next === "entry" && armedRef.current.entry) {
        armedRef.current.entry = false;
        _playBeep(player);
      } else if (next === "tp" && armedRef.current.tp) {
        armedRef.current.tp = false;
        _playBeep(player);
      } else if (next === "sl" && armedRef.current.sl) {
        armedRef.current.sl = false;
        _playBeep(player);
      }
      if (next === "idle") {
        armedRef.current = { entry: true, tp: true, sl: true };
      } else {
        if (next !== "entry") armedRef.current.entry = true;
        if (next !== "tp") armedRef.current.tp = true;
        if (next !== "sl") armedRef.current.sl = true;
      }
      return next;
    });
  }, [livePrice, entryLow, entryHigh, takeProfit, stopLoss, player]);

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
