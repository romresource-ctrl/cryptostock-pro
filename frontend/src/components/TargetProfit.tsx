import { Ionicons } from "@expo/vector-icons";
import React, { useMemo } from "react";
import { StyleSheet, Text, View } from "react-native";

import { formatPrice } from "@/src/lib/api";
import { useTheme } from "@/src/theme/ThemeContext";

type Candle = { high: number; low: number; close: number };

type Props = {
  action: string; // "BUY" | "SELL" | "HOLD"
  entryPrice: number;
  candles: Candle[];
  confidence?: number;
  label?: string;
  translations?: {
    title?: string;
    entry?: string;
    stopLoss?: string;
    tp1?: string;
    tp2?: string;
    tp3?: string;
    riskReward?: string;
    hold_msg?: string;
  };
};

/**
 * Calculates Target Profit / Stop Loss levels using ATR (Average True Range)
 * derived from the recent candles. Standard risk management ratios:
 *   - Stop Loss: 1× ATR from entry (opposite direction of trade)
 *   - Take Profit 1: 1.5× ATR   (Risk:Reward ≈ 1.5)
 *   - Take Profit 2: 2.5× ATR   (Risk:Reward ≈ 2.5)
 *   - Take Profit 3: 4.0× ATR   (Risk:Reward ≈ 4.0)
 *
 * Only shown for BUY/SELL actions. HOLD shows a neutral message.
 */
function computeATR(candles: Candle[], period = 14): number {
  if (!candles || candles.length < 2) return 0;
  const sample = candles.slice(-period - 1);
  const trs: number[] = [];
  for (let i = 1; i < sample.length; i++) {
    const c = sample[i];
    const prev = sample[i - 1];
    const tr = Math.max(
      c.high - c.low,
      Math.abs(c.high - prev.close),
      Math.abs(c.low - prev.close),
    );
    trs.push(tr);
  }
  if (trs.length === 0) return 0;
  return trs.reduce((s, v) => s + v, 0) / trs.length;
}

export default function TargetProfit({
  action,
  entryPrice,
  candles,
  confidence = 0,
  label,
  translations,
}: Props) {
  const { colors } = useTheme();

  const t = {
    title: translations?.title ?? "Target Profit & Stop Loss",
    entry: translations?.entry ?? "Entry",
    stopLoss: translations?.stopLoss ?? "Stop Loss",
    tp1: translations?.tp1 ?? "Target 1",
    tp2: translations?.tp2 ?? "Target 2",
    tp3: translations?.tp3 ?? "Target 3",
    riskReward: translations?.riskReward ?? "Risk : Reward",
    hold_msg:
      translations?.hold_msg ??
      "No clear entry. Wait for the next signal before opening a position.",
  };

  const levels = useMemo(() => {
    const atr = computeATR(candles, 14) || entryPrice * 0.01;
    const isBuy = action === "BUY";
    const isSell = action === "SELL";
    if (!isBuy && !isSell) return null;
    const dir = isBuy ? 1 : -1;
    // Scale ATR distance by confidence (higher conf → wider TP3)
    const confBoost = 1 + Math.min(Math.max(confidence, 0), 100) / 200; // 1.0 – 1.5
    const sl = entryPrice - dir * atr;
    const tp1 = entryPrice + dir * atr * 1.5;
    const tp2 = entryPrice + dir * atr * 2.5;
    const tp3 = entryPrice + dir * atr * 4.0 * confBoost;
    const riskPerUnit = Math.abs(entryPrice - sl) || 1;
    const rewardPerUnit = Math.abs(tp2 - entryPrice);
    const rr = rewardPerUnit / riskPerUnit;
    return { atr, sl, tp1, tp2, tp3, rr, isBuy };
  }, [action, entryPrice, candles, confidence]);

  if (!levels) {
    return (
      <View
        style={[
          styles.card,
          { backgroundColor: colors.surface, borderColor: colors.border },
        ]}
      >
        <View style={styles.headerRow}>
          <Ionicons name="pause-circle" size={16} color={colors.accentHold} />
          <Text style={[styles.title, { color: colors.textPrimary }]}>{t.title}</Text>
        </View>
        <Text style={[styles.holdMsg, { color: colors.textMuted }]}>
          {t.hold_msg}
        </Text>
      </View>
    );
  }

  const dirColor = levels.isBuy ? colors.accentUp : colors.accentDown;
  const oppColor = levels.isBuy ? colors.accentDown : colors.accentUp;

  const rows = [
    { label: t.tp3, value: levels.tp3, color: dirColor, weight: "3" },
    { label: t.tp2, value: levels.tp2, color: dirColor, weight: "2" },
    { label: t.tp1, value: levels.tp1, color: dirColor, weight: "1" },
    { label: t.entry, value: entryPrice, color: colors.textPrimary, weight: "•" },
    { label: t.stopLoss, value: levels.sl, color: oppColor, weight: "SL" },
  ];

  return (
    <View
      style={[
        styles.card,
        { backgroundColor: colors.surface, borderColor: colors.border },
      ]}
    >
      <View style={styles.headerRow}>
        <Ionicons
          name={levels.isBuy ? "trending-up" : "trending-down"}
          size={16}
          color={dirColor}
        />
        <Text style={[styles.title, { color: colors.textPrimary }]}>
          {t.title}
        </Text>
        {label ? (
          <View
            style={[styles.badge, { backgroundColor: dirColor + "26" }]}
          >
            <Text style={[styles.badgeText, { color: dirColor }]}>{label}</Text>
          </View>
        ) : null}
      </View>

      {rows.map((r, i) => (
        <View
          key={i}
          style={[
            styles.row,
            i === rows.length - 1 ? null : { borderBottomWidth: 0.5, borderBottomColor: colors.border },
          ]}
        >
          <View style={[styles.dot, { backgroundColor: r.color }]}>
            <Text style={styles.dotText}>{r.weight}</Text>
          </View>
          <Text style={[styles.rowLabel, { color: colors.textPrimary }]}>{r.label}</Text>
          <Text style={[styles.rowValue, { color: r.color }]}>
            {formatPrice(r.value)}
          </Text>
        </View>
      ))}

      <View style={[styles.footer, { borderTopColor: colors.border }]}>
        <Text style={[styles.footerLabel, { color: colors.textMuted }]}>
          {t.riskReward}
        </Text>
        <Text
          style={[
            styles.footerValue,
            { color: levels.rr >= 2 ? colors.accentUp : colors.accentHold },
          ]}
        >
          1 : {levels.rr.toFixed(2)}
        </Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    borderRadius: 12,
    borderWidth: 1,
    padding: 14,
    marginTop: 12,
  },
  headerRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    marginBottom: 10,
  },
  title: { fontSize: 13, fontWeight: "800", flex: 1 },
  badge: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 6,
  },
  badgeText: { fontSize: 10, fontWeight: "800", letterSpacing: 0.4 },
  row: {
    flexDirection: "row",
    alignItems: "center",
    paddingVertical: 8,
    gap: 10,
  },
  dot: {
    width: 22,
    height: 22,
    borderRadius: 11,
    alignItems: "center",
    justifyContent: "center",
  },
  dotText: {
    fontSize: 10,
    fontWeight: "900",
    color: "#fff",
  },
  rowLabel: { fontSize: 12, fontWeight: "600", flex: 1 },
  rowValue: { fontSize: 13, fontWeight: "800", fontVariant: ["tabular-nums"] },
  footer: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    borderTopWidth: 0.5,
    paddingTop: 10,
    marginTop: 4,
  },
  footerLabel: { fontSize: 11, fontWeight: "600" },
  footerValue: { fontSize: 13, fontWeight: "900" },
  holdMsg: {
    fontSize: 12,
    lineHeight: 18,
    fontStyle: "italic",
  },
});
