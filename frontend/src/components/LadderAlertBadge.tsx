/**
 * LadderAlertBadge — v8.12.1
 *
 * Blinking popup badge rendered inline next to the Candlestick / Line
 * toggle buttons (per user spec — should NOT overlap the chart body).
 * Shows the SPECIFIC laddered level the live ticker just crossed:
 *
 *   • Entry tiers (deep / moderate / aggressive):
 *       - BUY  side → "LONG 1", "LONG 2", "LONG 3"
 *       - SELL side → "SHORT 1", "SHORT 2", "SHORT 3"
 *       - Non-crypto BUY  → "BUY 1", "BUY 2", "BUY 3"
 *       - Non-crypto SELL → "SELL 1", "SELL 2", "SELL 3"
 *   • Take-profit ladder → "TP 1", "TP 2", "TP 3"
 *
 * The primary ENTRY / TP HIT / SL HIT / HOLD pill lives on the price-line
 * at the LEFT edge (inside CandlestickChart). This badge is intentionally
 * a separate overlay so both can be shown simultaneously when relevant.
 * Beep is handled by the shared `usePriceZoneAlert` hook, not here.
 */
import React, { useEffect, useRef } from "react";
import { Animated, StyleSheet, Text } from "react-native";
import type { AlertZone } from "@/src/hooks/usePriceZoneAlert";

interface Props {
  zone: AlertZone;
  /** Signal side determines whether entry-tier badges read
   *  "LONG/SHORT" (crypto) or "BUY/SELL" (stocks / others). */
  signalAction?: string | null;
  /** Backend label — "LONG"/"SHORT" for crypto, "BUY"/"SELL" otherwise.
   *  Used to derive the correct verb prefix. */
  signalLabel?: string | null;
}

type Meta = { label: string; bg: string; fg: string };

const TP_META: Record<"tp1" | "tp2" | "tp3", Meta> = {
  tp3: { label: "🚀 TP 3", bg: "#00d4aa", fg: "#000" },
  tp2: { label: "✨ TP 2", bg: "#22c55e", fg: "#000" },
  tp1: { label: "🎯 TP 1", bg: "#f5c518", fg: "#000" },
};

function entryMeta(zone: "entry1" | "entry2" | "entry3",
                   action: string,
                   label: string): Meta {
  const isSell = action === "SELL" || label === "SHORT";
  const isCrypto = label === "LONG" || label === "SHORT";
  const verb = isSell
    ? (isCrypto ? "SHORT" : "SELL")
    : (isCrypto ? "LONG" : "BUY");
  const n = zone === "entry1" ? "1" : zone === "entry2" ? "2" : "3";
  const buyBg: Record<string, string> = { "1": "#22c55e", "2": "#3b82f6", "3": "#60a5fa" };
  const sellBg: Record<string, string> = { "1": "#ef4444", "2": "#f97316", "3": "#f472b6" };
  return {
    label: `${verb} ${n}`,
    bg: (isSell ? sellBg : buyBg)[n],
    fg: "#fff",
  };
}

function metaForZone(zone: AlertZone, action: string, label: string): Meta | null {
  if (zone === "tp1" || zone === "tp2" || zone === "tp3") return TP_META[zone];
  if (zone === "entry1" || zone === "entry2" || zone === "entry3") {
    return entryMeta(zone, action, label);
  }
  return null;
}

const LadderAlertBadge: React.FC<Props> = ({ zone, signalAction, signalLabel }) => {
  // Fade in 0→1 in 200ms then blink softly — prevents first-frame flicker
  // when the badge mounts.
  const opacity = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    if (zone === "idle" || zone === "sl" || zone === "hold") {
      opacity.setValue(0);
      return;
    }
    const fadeIn = Animated.timing(opacity, {
      toValue: 1, duration: 200, useNativeDriver: true,
    });
    const blink = Animated.loop(
      Animated.sequence([
        Animated.timing(opacity, { toValue: 0.35, duration: 500, useNativeDriver: true }),
        Animated.timing(opacity, { toValue: 1, duration: 500, useNativeDriver: true }),
      ]),
    );
    fadeIn.start(({ finished }) => {
      if (finished) blink.start();
    });
    return () => {
      fadeIn.stop();
      blink.stop();
    };
  }, [zone, opacity]);

  if (zone === "idle" || zone === "sl" || zone === "hold") return null;
  const action = String(signalAction || "").toUpperCase();
  const label = String(signalLabel || "").toUpperCase();
  const meta = metaForZone(zone, action, label);
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
    fontSize: 11,
    fontWeight: "800",
    letterSpacing: 0.6,
  },
});

export default LadderAlertBadge;
