/**
 * useDipTopAlert — v8.13.0
 *
 * Micro-swing detector for crypto live tickers. Buffers the last
 * `windowMs` of livePrice samples and emits one of:
 *
 *   • "dip1" / "dip2" / "dip3" — price has dropped 0.5% / 1.2% / 2.5%
 *     from the highest point in the buffer (peak → valley move).
 *   • "top1" / "top2" / "top3" — price has risen 0.5% / 1.2% / 2.5%
 *     from the lowest point in the buffer (valley → peak move).
 *   • "idle" — no significant instant move.
 *
 * The tier progression is designed for "buy the dip" / "sell the top"
 * micro-scalping signals. Only fires when the direction is monotonic
 * (max/min occurred BEFORE the current live tick), so a slow trend
 * doesn't trigger.
 *
 * Stability: uses a state machine that only emits a HIGHER tier once
 * per wave (tier only ratchets up, never down). Resets to idle when
 * the drawdown/rally shrinks below tier-1 threshold, allowing the
 * next wave to trigger fresh.
 */
import { useEffect, useRef, useState } from "react";
import { Platform } from "react-native";
import { useAudioPlayer } from "expo-audio";

export type DipTopZone =
  | "idle"
  | "dip1" | "dip2" | "dip3"
  | "top1" | "top2" | "top3";

const BEEP_URL =
  "https://customer-assets.emergentagent.com/job_swift-market/artifacts/uwx4jcxr_beep.mp3";

interface Args {
  livePrice: number | null | undefined;
  /** Look-back window in milliseconds (default 60s) */
  windowMs?: number;
  /** Drop thresholds (fraction 0.005 = 0.5%) */
  dipT1?: number;
  dipT2?: number;
  dipT3?: number;
  /** Rise thresholds */
  topT1?: number;
  topT2?: number;
  topT3?: number;
  /** Minimum samples before we start emitting (avoid noise on first ticks) */
  minSamples?: number;
}

interface Sample { t: number; p: number }

export function useDipTopAlert({
  livePrice,
  windowMs = 60_000,
  dipT1 = 0.005,
  dipT2 = 0.012,
  dipT3 = 0.025,
  topT1 = 0.005,
  topT2 = 0.012,
  topT3 = 0.025,
  minSamples = 5,
}: Args): DipTopZone {
  const bufferRef = useRef<Sample[]>([]);
  const [zone, setZone] = useState<DipTopZone>("idle");
  const player = useAudioPlayer({ uri: BEEP_URL });
  // v8.13.1 — arm/re-arm map so each tier beeps at most once per wave.
  // Tiers are re-armed only when zone returns to "idle" (i.e. the
  // swing recovers below tier-1 threshold), preventing beep spam
  // while the price hovers around a tier's edge.
  const armedRef = useRef<Record<DipTopZone, boolean>>({
    idle: true,
    dip1: true, dip2: true, dip3: true,
    top1: true, top2: true, top3: true,
  });

  useEffect(() => {
    if (livePrice == null || !Number.isFinite(livePrice)) return;
    const now = Date.now();
    const buf = bufferRef.current;
    buf.push({ t: now, p: livePrice });
    // Trim old samples outside the window
    while (buf.length > 0 && now - buf[0].t > windowMs) buf.shift();
    if (buf.length < minSamples) {
      if (zone !== "idle") setZone("idle");
      return;
    }

    // Locate peak & trough within the window
    let maxP = buf[0].p;
    let minP = buf[0].p;
    let maxIdx = 0;
    let minIdx = 0;
    for (let i = 1; i < buf.length; i++) {
      if (buf[i].p > maxP) { maxP = buf[i].p; maxIdx = i; }
      if (buf[i].p < minP) { minP = buf[i].p; minIdx = i; }
    }
    const lastIdx = buf.length - 1;

    // Drawdown from peak, only if peak was BEFORE current sample
    // (otherwise it's a live new-high, not a dip).
    const drawdown = maxIdx < lastIdx && maxP > 0
      ? (maxP - livePrice) / maxP
      : 0;
    // Rally from trough, only if trough was BEFORE current sample.
    const rally = minIdx < lastIdx && minP > 0
      ? (livePrice - minP) / minP
      : 0;

    let next: DipTopZone = "idle";
    // Whichever move is bigger wins the frame (typically only one at a time)
    if (drawdown >= dipT1 && drawdown >= rally) {
      if (drawdown >= dipT3) next = "dip3";
      else if (drawdown >= dipT2) next = "dip2";
      else next = "dip1";
    } else if (rally >= topT1) {
      if (rally >= topT3) next = "top3";
      else if (rally >= topT2) next = "top2";
      else next = "top1";
    }

    if (next !== zone) {
      // v8.13.1 — Beep once when a NEW tier commits. Re-arm all tiers
      // on return to idle so the next micro-swing can fire fresh.
      if (next === "idle") {
        (Object.keys(armedRef.current) as DipTopZone[]).forEach((k) => {
          armedRef.current[k] = true;
        });
      } else if (armedRef.current[next]) {
        armedRef.current[next] = false;
        _playBeep(player);
      }
      setZone(next);
    }
  }, [livePrice, windowMs, dipT1, dipT2, dipT3, topT1, topT2, topT3, minSamples, zone, player]);

  // Clear buffer if livePrice goes null (symbol change / disconnect)
  useEffect(() => {
    if (livePrice == null) {
      bufferRef.current = [];
      if (zone !== "idle") setZone("idle");
    }
  }, [livePrice, zone]);

  return zone;
}


// v8.13.1 / v8.12.12 — Shared beep helper. Uses the expo-audio player
// bound to BEEP_URL, with a Web Audio API fallback (880Hz sine, 250ms)
// for the web preview where the remote mp3 may be blocked by ORB.
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
        // Distinct pitch from usePriceZoneAlert (880Hz) so dip/top
        // beep is audibly different from entry/TP beep — 660Hz.
        osc.frequency.value = 660;
        osc.type = "triangle";
        gain.gain.setValueAtTime(0.15, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.28);
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.start();
        osc.stop(ctx.currentTime + 0.28);
      } catch { /* ignore */ }
    }
  }
}
