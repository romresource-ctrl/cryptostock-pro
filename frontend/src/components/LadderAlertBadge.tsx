/**
 * LadderAlertBadge — v8.7.9
 *
 * Blinking popup badge rendered at the TOP-LEFT corner of the candlestick
 * chart area (per user spec — see the hand-drawn rectangle in the ETH
 * screenshot). Shows the SPECIFIC laddered level the live ticker just
 * crossed:
 *
 *   • TP-1 / TP-2 / TP-3  — as price rises through the profit ladder
 *   • BUY 3 / BUY 2 / BUY 1 — as price dips through the value ladder
 *
 * The primary ENTRY / TP HIT / SL HIT badge lives on the price-line at
 * the LEFT edge (inside CandlestickChart). This badge is intentionally
 * a separate overlay so both can be shown simultaneously when relevant.
 * Beep is handled by the shared `usePriceZoneAlert` hook, not here.
 */
import React, { useEffect, useRef } from "react";
import { Animated, StyleSheet, Text } from "react-native";
import type { AlertZone } from "@/src/hooks/usePriceZoneAlert";

interface Props {
  zone: AlertZone;
}

const META: Record<
  Exclude<AlertZone, "idle" | "entry" | "sl">,
  { label: string; bg: string; fg: string }
> = {
  tp3:  { label: "🚀 TP-3",  bg: "#00d4aa", fg: "#000" },
  tp2:  { label: "✨ TP-2",  bg: "#22c55e", fg: "#000" },
  tp1:  { label: "🎯 TP-1",  bg: "#f5c518", fg: "#000" },
  buy3: { label: "💧 BUY 3", bg: "#60a5fa", fg: "#000" },
  buy2: { label: "💧 BUY 2", bg: "#3b82f6", fg: "#fff" },
  buy1: { label: "💎 BUY 1", bg: "#1d4ed8", fg: "#fff" },
};

const LadderAlertBadge: React.FC<Props> = ({ zone }) => {
  const opacity = useRef(new Animated.Value(1)).current;
  useEffect(() => {
    if (zone === "idle" || zone === "entry" || zone === "sl") {
      opacity.setValue(1);
      return;
    }
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(opacity, { toValue: 0.3, duration: 400, useNativeDriver: true }),
        Animated.timing(opacity, { toValue: 1, duration: 400, useNativeDriver: true }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [zone, opacity]);

  if (zone === "idle" || zone === "entry" || zone === "sl") return null;
  const meta = META[zone];
  if (!meta) return null;

  return (
    <Animated.View
      pointerEvents="none"
      style={[styles.badge, { backgroundColor: meta.bg, opacity }]}
      testID={`ladder-alert-${zone}`}
    >
      <Text style={[styles.text, { color: meta.fg }]}>{meta.label}</Text>
    </Animated.View>
  );
};

const styles = StyleSheet.create({
  badge: {
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: 6,
    alignSelf: "center",
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.35,
    shadowRadius: 3,
    elevation: 5,
  },
  text: {
    fontSize: 12,
    fontWeight: "800",
    letterSpacing: 0.6,
  },
});

export default LadderAlertBadge;
