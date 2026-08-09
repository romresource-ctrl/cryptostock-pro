/**
 * PriceAlertOverlay — v8.7.5
 *
 * Real-time alert that fires when the live ticker price enters:
 *   • ENTRY zone   → shows blinking "ENTRY!"  (accentBlue) badge + beep
 *   • TP HIT zone  → shows blinking "TP HIT!" (accentUp / accentDown) + beep
 *
 * Uses the EXISTING signal-provided entry_low / entry_high band (from
 * indicators.py — do NOT recompute a new band here). TP uses ±0.15% around
 * the take_profit level so it fires briefly as price crosses.
 *
 * A single beep plays the first time price ENTERS a zone; sound is silenced
 * while price stays inside, and re-armed once it exits. The badge auto-hides
 * as soon as price leaves the zone.
 */
import React, { useEffect, useRef, useState } from "react";
import { Animated, Platform, StyleSheet, Text, View } from "react-native";
import { useAudioPlayer } from "expo-audio";

import { useTheme } from "@/src/theme/ThemeContext";

type Side = "BUY" | "SELL" | "HOLD" | string;

interface Props {
  livePrice: number | null | undefined;
  entryLow: number | null | undefined;
  entryHigh: number | null | undefined;
  takeProfit: number | null | undefined;
  stopLoss: number | null | undefined;
  action: Side;
}

// Public-domain "beep" WAV. Emergent CDN copy so it works offline-in-container.
// Falls back to Web Audio API on web (see below) so we never crash if the
// asset is unreachable.
const BEEP_URL =
  "https://customer-assets.emergentagent.com/job_swift-market/artifacts/uwx4jcxr_beep.mp3";
const TP_BAND_PCT = 0.0015; // ±0.15% around take_profit
const SL_BAND_PCT = 0.0015; // ±0.15% around stop_loss

function inRange(px: number, low: number, high: number): boolean {
  return px >= low && px <= high;
}

const PriceAlertOverlay: React.FC<Props> = ({
  livePrice,
  entryLow,
  entryHigh,
  takeProfit,
  stopLoss,
  action,
}) => {
  const { colors } = useTheme();
  const [state, setState] = useState<"idle" | "entry" | "tp" | "sl">("idle");
  const blinkAnim = useRef(new Animated.Value(1)).current;
  const armedRef = useRef<{ entry: boolean; tp: boolean; sl: boolean }>({
    entry: true, tp: true, sl: true,
  });
  const player = useAudioPlayer({ uri: BEEP_URL });

  // Determine current zone based on live price
  useEffect(() => {
    if (livePrice == null || !Number.isFinite(livePrice)) {
      setState("idle");
      return;
    }
    let nextState: "idle" | "entry" | "tp" | "sl" = "idle";

    // SL zone — HIGHEST priority (loss alert is most urgent)
    if (stopLoss != null && Number.isFinite(stopLoss)) {
      const slLow = stopLoss * (1 - SL_BAND_PCT);
      const slHigh = stopLoss * (1 + SL_BAND_PCT);
      if (inRange(livePrice, slLow, slHigh)) nextState = "sl";
    }

    // TP zone
    if (nextState === "idle" && takeProfit != null && Number.isFinite(takeProfit)) {
      const tpLow = takeProfit * (1 - TP_BAND_PCT);
      const tpHigh = takeProfit * (1 + TP_BAND_PCT);
      if (inRange(livePrice, tpLow, tpHigh)) nextState = "tp";
    }

    // Entry zone — uses signal's own entry_low / entry_high band
    if (
      nextState === "idle" &&
      entryLow != null &&
      entryHigh != null &&
      Number.isFinite(entryLow) &&
      Number.isFinite(entryHigh)
    ) {
      if (inRange(livePrice, entryLow, entryHigh)) nextState = "entry";
    }

    setState((prev) => {
      if (prev === nextState) return prev;
      // Play beep on FIRST entry to a zone (armed → disarm), re-arm on exit.
      if (nextState === "entry" && armedRef.current.entry) {
        armedRef.current.entry = false;
        _playBeep(player);
      } else if (nextState === "tp" && armedRef.current.tp) {
        armedRef.current.tp = false;
        _playBeep(player);
      } else if (nextState === "sl" && armedRef.current.sl) {
        armedRef.current.sl = false;
        _playBeep(player);
      }
      if (nextState === "idle") {
        // Re-arm all zones when we leave any zone
        armedRef.current = { entry: true, tp: true, sl: true };
      } else {
        // Re-arm the OTHER zones when we jump between them
        if (nextState !== "entry") armedRef.current.entry = true;
        if (nextState !== "tp") armedRef.current.tp = true;
        if (nextState !== "sl") armedRef.current.sl = true;
      }
      return nextState;
    });
  }, [livePrice, entryLow, entryHigh, takeProfit, stopLoss, player]);

  // Blink animation loop
  useEffect(() => {
    if (state === "idle") {
      blinkAnim.setValue(1);
      return;
    }
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(blinkAnim, { toValue: 0.25, duration: 400, useNativeDriver: true }),
        Animated.timing(blinkAnim, { toValue: 1, duration: 400, useNativeDriver: true }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [state, blinkAnim]);

  if (state === "idle") return null;

  const isSl = state === "sl";
  const isTp = state === "tp";
  const label = isSl ? "🛑 SL HIT!" : isTp ? "🎯 TP HIT!" : "🚀 ENTRY!";
  // Colour hint: SL always red, TP always gold, Entry follows signal side.
  const bg = isSl
    ? colors.accentDown
    : isTp
      ? "#f5c518"
      : action === "SELL"
        ? colors.accentDown
        : colors.accentUp;
  const fg = isSl ? "#fff" : "#000";

  return (
    <View pointerEvents="none" style={styles.container} testID={`price-alert-${state}`}>
      <Animated.View style={[styles.pill, { backgroundColor: bg, opacity: blinkAnim }]}>
        <Text style={[styles.text, { color: fg }]}>{label}</Text>
      </Animated.View>
    </View>
  );
};

async function _playBeep(player: ReturnType<typeof useAudioPlayer>) {
  try {
    // expo-audio: seekTo(0) + play() replays reliably each time
    if (typeof player?.seekTo === "function") {
      await player.seekTo(0);
    }
    player?.play?.();
  } catch {
    // Web fallback: Web Audio API oscillator beep (native platforms will
    // never reach here because expo-audio's promise won't reject to catch).
    if (Platform.OS === "web" && typeof window !== "undefined") {
      try {
        const AC: any = (window as any).AudioContext || (window as any).webkitAudioContext;
        if (!AC) return;
        const ctx = new AC();
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.frequency.value = 880; // A5
        osc.type = "sine";
        gain.gain.setValueAtTime(0.15, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.25);
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.start();
        osc.stop(ctx.currentTime + 0.25);
      } catch {
        /* ignore */
      }
    }
  }
}

const styles = StyleSheet.create({
  container: {
    position: "absolute",
    top: 8,
    right: 8,
    zIndex: 20,
    alignItems: "flex-end",
  },
  pill: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 8,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.35,
    shadowRadius: 4,
    elevation: 6,
  },
  text: {
    fontSize: 13,
    fontWeight: "800",
    letterSpacing: 0.8,
  },
});

export default PriceAlertOverlay;
