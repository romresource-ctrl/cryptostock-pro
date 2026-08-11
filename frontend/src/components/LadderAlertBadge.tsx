/**
 * LadderAlertBadge — v8.13.0
 *
 * Blinking popup badge rendered inline next to the Candlestick / Line
 * toggle buttons (per user spec — should NOT overlap the chart body).
 * Shows either:
 *
 *   • Entry / TP tiers (from usePriceZoneAlert):
 *       - BUY  side → "LONG 1 / 2 / 3" (crypto) or "BUY 1 / 2 / 3"
 *       - SELL side → "SHORT 1 / 2 / 3" (crypto) or "SELL 1 / 2 / 3"
 *       - Take-profit ladder → "TP 1 / 2 / 3"
 *
 *   • Micro-swing tiers (from useDipTopAlert) — v8.13.0:
 *       - "DIP 1 / 2 / 3" — price dropped 0.5% / 1.2% / 2.5% from
 *         the recent peak (blue palette).
 *       - "TOP 1 / 2 / 3" — price rose 0.5% / 1.2% / 2.5% from the
 *         recent trough (orange palette).
 *
 * When BOTH zones are active, entry/TP wins over dip/top since it is
 * the higher-priority actionable signal.
 */
import React, { useEffect, useRef } from "react";
import { Animated, StyleSheet, Text, View } from "react-native";
import type { AlertZone } from "@/src/hooks/usePriceZoneAlert";
import type { DipTopZone } from "@/src/hooks/useDipTopAlert";

interface Props {
  zone: AlertZone;
  /** Signal side determines whether entry-tier badges read
   *  "LONG/SHORT" (crypto) or "BUY/SELL" (stocks / others). */
  signalAction?: string | null;
  /** Backend label — "LONG"/"SHORT" for crypto, "BUY"/"SELL" otherwise.
   *  Used to derive the correct verb prefix. */
  signalLabel?: string | null;
  /** v8.13.0 — Independent micro-swing zone (buy-the-dip / sell-the-top).
   *  Rendered as a SECOND badge to the right of the entry/TP badge
   *  when both are active. */
  dipTopZone?: DipTopZone;
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

// v8.13.0 — Palette for micro-swing dip/top tiers.
// DIP: cool blue (entry into value) → deeper = more saturated.
// TOP: warm orange (take profit / exit at high) → higher = more saturated.
const DIP_META: Record<"dip1" | "dip2" | "dip3", Meta> = {
  dip1: { label: "💧 DIP 1", bg: "#38bdf8", fg: "#000" },
  dip2: { label: "🌊 DIP 2", bg: "#0ea5e9", fg: "#fff" },
  dip3: { label: "💎 DIP 3", bg: "#0369a1", fg: "#fff" },
};
const TOP_META: Record<"top1" | "top2" | "top3", Meta> = {
  top1: { label: "📈 TOP 1", bg: "#fbbf24", fg: "#000" },
  top2: { label: "🚀 TOP 2", bg: "#f97316", fg: "#fff" },
  top3: { label: "🔥 TOP 3", bg: "#c2410c", fg: "#fff" },
};

function dipTopMeta(zone: DipTopZone): Meta | null {
  if (zone === "dip1" || zone === "dip2" || zone === "dip3") return DIP_META[zone];
  if (zone === "top1" || zone === "top2" || zone === "top3") return TOP_META[zone];
  return null;
}

const LadderAlertBadge: React.FC<Props> = ({ zone, signalAction, signalLabel, dipTopZone = "idle" }) => {
  // Fade in 0→1 in 200ms then blink softly — prevents first-frame flicker
  // when the badge mounts.
  const opacity = useRef(new Animated.Value(0)).current;
  const dipOpacity = useRef(new Animated.Value(0)).current;

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

  // v8.13.0 — Independent blink loop for the dip/top badge.
  useEffect(() => {
    if (dipTopZone === "idle") {
      dipOpacity.setValue(0);
      return;
    }
    const fadeIn = Animated.timing(dipOpacity, {
      toValue: 1, duration: 200, useNativeDriver: true,
    });
    const blink = Animated.loop(
      Animated.sequence([
        Animated.timing(dipOpacity, { toValue: 0.4, duration: 450, useNativeDriver: true }),
        Animated.timing(dipOpacity, { toValue: 1, duration: 450, useNativeDriver: true }),
      ]),
    );
    fadeIn.start(({ finished }) => {
      if (finished) blink.start();
    });
    return () => {
      fadeIn.stop();
      blink.stop();
    };
  }, [dipTopZone, dipOpacity]);

  const action = String(signalAction || "").toUpperCase();
  const label = String(signalLabel || "").toUpperCase();
  const primaryMeta =
    zone === "idle" || zone === "sl" || zone === "hold"
      ? null
      : metaForZone(zone, action, label);
  const secondaryMeta = dipTopZone === "idle" ? null : dipTopMeta(dipTopZone);

  if (!primaryMeta && !secondaryMeta) return null;

  return (
    <View style={styles.row} pointerEvents="none">
      {primaryMeta ? (
        <Animated.View
          style={[styles.badge, { backgroundColor: primaryMeta.bg, opacity }]}
          testID={`ladder-alert-${zone}`}
        >
          <Text style={[styles.text, { color: primaryMeta.fg }]}>{primaryMeta.label}</Text>
        </Animated.View>
      ) : null}
      {secondaryMeta ? (
        <Animated.View
          style={[styles.badge, { backgroundColor: secondaryMeta.bg, opacity: dipOpacity }]}
          testID={`diptop-alert-${dipTopZone}`}
        >
          <Text style={[styles.text, { color: secondaryMeta.fg }]}>{secondaryMeta.label}</Text>
        </Animated.View>
      ) : null}
    </View>
  );
};

const styles = StyleSheet.create({
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    flexWrap: "wrap",
  },
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
