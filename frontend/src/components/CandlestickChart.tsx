import React from "react";
import { View } from "react-native";
import Svg, { Line, Rect, Text as SvgText } from "react-native-svg";

import { useTheme } from "@/src/theme/ThemeContext";

type Candle = {
  t: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
};

type Props = {
  candles: Candle[];
  width: number;
  height: number;
  showVolume?: boolean;
  showGrid?: boolean;
  currency?: string;
};

/**
 * Real-time candlestick (OHLC) chart with volume overlay.
 * Pure react-native-svg — no external chart library dependency.
 *
 * Green candle = close >= open (bullish)
 * Red candle   = close <  open (bearish)
 * Wick = high↔low, Body = open↔close
 */
export default function CandlestickChart({
  candles,
  width,
  height,
  showVolume = true,
  showGrid = true,
  currency: _currency,
}: Props) {
  const { colors } = useTheme();

  if (!candles || candles.length < 2) {
    return (
      <View style={{ width, height, backgroundColor: colors.surface }} />
    );
  }

  // Layout: reserve bottom band for volume, right band for price labels
  const rightPad = 56;
  const volumeH = showVolume ? Math.max(24, height * 0.18) : 0;
  const chartH = height - volumeH - 4;
  const chartW = width - rightPad;

  // Cap candles to keep rendering fast on low-end phones
  const MAX_CANDLES = 120;
  const displayed =
    candles.length > MAX_CANDLES
      ? candles.slice(candles.length - MAX_CANDLES)
      : candles;

  const highs = displayed.map((c) => c.high);
  const lows = displayed.map((c) => c.low);
  const priceMax = Math.max(...highs);
  const priceMin = Math.min(...lows);
  const priceRange = priceMax - priceMin || Math.abs(priceMax) * 0.01 || 1;
  // Add 3% headroom
  const priceHi = priceMax + priceRange * 0.03;
  const priceLo = priceMin - priceRange * 0.03;
  const priceSpan = priceHi - priceLo || 1;

  const priceToY = (p: number) => ((priceHi - p) / priceSpan) * chartH;

  const candleGap = 1.5;
  const candleWidth = Math.max(
    2,
    chartW / displayed.length - candleGap,
  );
  const step = chartW / displayed.length;

  const upColor = colors.accentUp || "#10b981";
  const downColor = colors.accentDown || "#ef4444";

  // Horizontal grid lines + price labels (4 rows)
  const rows = [0, 0.25, 0.5, 0.75, 1];
  const gridEls = showGrid
    ? rows.map((p, i) => {
        const y = p * chartH;
        const priceAtRow = priceHi - p * priceSpan;
        return (
          <React.Fragment key={`grid-${i}`}>
            <Line
              x1={0}
              x2={chartW}
              y1={y}
              y2={y}
              stroke={colors.border}
              strokeWidth={0.5}
              strokeDasharray="3 4"
              opacity={0.55}
            />
            <SvgText
              x={chartW + 4}
              y={Math.min(Math.max(y + 3, 9), chartH - 2)}
              fontSize={9}
              fill={colors.textMuted}
            >
              {formatPriceLabel(priceAtRow)}
            </SvgText>
          </React.Fragment>
        );
      })
    : null;

  // Volume scale
  const volumes = displayed.map((c) => c.volume ?? 0);
  const volMax = Math.max(...volumes, 1);

  return (
    <Svg width={width} height={height}>
      {gridEls}
      {displayed.map((c, i) => {
        const x = i * step + candleGap / 2;
        const bodyX = x;
        const bodyW = candleWidth;
        const isUp = c.close >= c.open;
        const color = isUp ? upColor : downColor;
        const bodyTop = priceToY(Math.max(c.open, c.close));
        const bodyBot = priceToY(Math.min(c.open, c.close));
        const bodyH = Math.max(1, bodyBot - bodyTop);
        const wickX = bodyX + bodyW / 2;
        const wickTop = priceToY(c.high);
        const wickBot = priceToY(c.low);

        // Volume bar (bottom band)
        const vol = c.volume ?? 0;
        const vh = showVolume ? (vol / volMax) * (volumeH - 4) : 0;
        const volY = chartH + 4 + (volumeH - 4 - vh);

        return (
          <React.Fragment key={`c-${i}`}>
            {/* Wick */}
            <Line
              x1={wickX}
              x2={wickX}
              y1={wickTop}
              y2={wickBot}
              stroke={color}
              strokeWidth={1}
            />
            {/* Body */}
            <Rect
              x={bodyX}
              y={bodyTop}
              width={bodyW}
              height={bodyH}
              fill={color}
              rx={0.5}
            />
            {/* Volume */}
            {showVolume && vh > 0 ? (
              <Rect
                x={bodyX}
                y={volY}
                width={bodyW}
                height={vh}
                fill={color}
                opacity={0.35}
              />
            ) : null}
          </React.Fragment>
        );
      })}

      {/* Volume label */}
      {showVolume ? (
        <SvgText
          x={chartW + 4}
          y={chartH + volumeH - 4}
          fontSize={8}
          fill={colors.textMuted}
        >
          Vol
        </SvgText>
      ) : null}

      {/* Swing high/low price labels (issue #5) — pivot-detected local extrema */}
      {(() => {
        // Detect swing highs & lows using a 3-bar window on each side.
        const win = Math.max(2, Math.floor(displayed.length / 30));
        const highs: { i: number; price: number }[] = [];
        const lows: { i: number; price: number }[] = [];
        for (let i = win; i < displayed.length - win; i++) {
          const h = displayed[i].high;
          const l = displayed[i].low;
          let isHigh = true;
          let isLow = true;
          for (let k = 1; k <= win; k++) {
            if (displayed[i - k].high >= h || displayed[i + k].high >= h) {
              isHigh = false;
              break;
            }
          }
          for (let k = 1; k <= win; k++) {
            if (displayed[i - k].low <= l || displayed[i + k].low <= l) {
              isLow = false;
              break;
            }
          }
          if (isHigh) highs.push({ i, price: h });
          if (isLow) lows.push({ i, price: l });
        }
        // Cap labels to avoid overdraw
        const maxLabels = 5;
        const pickTop = (arr: { i: number; price: number }[], top: boolean) => {
          const sorted = arr
            .slice()
            .sort((a, b) => (top ? b.price - a.price : a.price - b.price));
          return sorted.slice(0, maxLabels);
        };
        const nodes = [
          ...pickTop(highs, true).map((p) => ({ ...p, isHigh: true })),
          ...pickTop(lows, false).map((p) => ({ ...p, isHigh: false })),
        ];
        return nodes.map((n, idx) => {
          const x = n.i * step + candleGap / 2 + candleWidth / 2;
          const y = priceToY(n.price);
          const yLabel = n.isHigh ? Math.max(y - 6, 8) : Math.min(y + 12, chartH - 2);
          const color = n.isHigh ? upColor : downColor;
          return (
            <SvgText
              key={`sw-${idx}`}
              x={x}
              y={yLabel}
              fontSize={8.5}
              fontWeight="700"
              fill={color}
              textAnchor="middle"
              stroke={colors.background}
              strokeWidth={0.4}
              paintOrder="stroke"
            >
              {formatPriceLabel(n.price)}
            </SvgText>
          );
        });
      })()}
    </Svg>
  );
}

function formatPriceLabel(p: number): string {
  const abs = Math.abs(p);
  if (abs >= 1000) return p.toFixed(0);
  if (abs >= 10) return p.toFixed(2);
  if (abs >= 1) return p.toFixed(3);
  if (abs >= 0.01) return p.toFixed(4);
  return p.toFixed(6);
}
