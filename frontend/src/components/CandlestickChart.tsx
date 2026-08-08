import React, { useState } from "react";
import { Animated, PanResponder, StyleSheet, Text, View } from "react-native";
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
  /** v8.6.5 — When true, draw a pulsing horizontal line at last close
      + animated dot at the tip so users can *see* the market breathing
      even for sub-cent price moves. */
  isLive?: boolean;
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
  isLive = false,
}: Props) {
  const { colors } = useTheme();
  // Hooks must run before any early return.
  const [cursorX, setCursorX] = useState<number | null>(null);
  // v8.6.5 — Pulse animation for the live-price dot. useNativeDriver keeps
  // this off the JS thread so it never stutters even during heavy renders.
  const pulseAnim = React.useRef(new Animated.Value(0)).current;
  React.useEffect(() => {
    if (!isLive) {
      pulseAnim.setValue(0);
      return;
    }
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(pulseAnim, { toValue: 1, duration: 900, useNativeDriver: true }),
        Animated.timing(pulseAnim, { toValue: 0, duration: 900, useNativeDriver: true }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [isLive, pulseAnim]);
  const panResponder = React.useMemo(
    () =>
      PanResponder.create({
        onStartShouldSetPanResponder: () => true,
        onMoveShouldSetPanResponder: () => true,
        onPanResponderGrant: (evt) => setCursorX(evt.nativeEvent.locationX),
        onPanResponderMove: (evt) => setCursorX(evt.nativeEvent.locationX),
        onPanResponderRelease: () => setCursorX(null),
        onPanResponderTerminate: () => setCursorX(null),
      }),
    [],
  );

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

  // ---------------------------------------------------------------------
  // v8.5.0 — Interactive crosshair (touch & drag to inspect a candle).
  // Hooks (`cursorX`, `panResponder`) are declared at the top of this
  // component; here we just compute the hovered candle from the current
  // cursor position.
  // ---------------------------------------------------------------------
  let hover: { candle: Candle; x: number; y: number; index: number } | null = null;
  if (cursorX != null) {
    const clamped = Math.max(0, Math.min(cursorX, chartW - 1));
    const idx = Math.min(displayed.length - 1, Math.max(0, Math.floor(clamped / step)));
    const c = displayed[idx];
    hover = {
      candle: c,
      index: idx,
      x: idx * step + candleGap / 2 + candleWidth / 2,
      y: priceToY(c.close),
    };
  }
  const fmtTime = (t: number): string => {
    if (!Number.isFinite(t)) return "";
    try {
      const d = new Date(t < 1e12 ? t * 1000 : t);
      const hh = String(d.getHours()).padStart(2, "0");
      const mm = String(d.getMinutes()).padStart(2, "0");
      const dd = String(d.getDate()).padStart(2, "0");
      const mo = String(d.getMonth() + 1).padStart(2, "0");
      return `${dd}/${mo} ${hh}:${mm}`;
    } catch {
      return "";
    }
  };

  return (
    <View style={{ width, height }} {...panResponder.panHandlers} testID="candlestick-chart">
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
        // Detect swing highs & lows using a 2-bar window on each side (denser labels).
        const win = 2;
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
        // Show up to 12 highs + 12 lows for good coverage without overdraw.
        // Prefer larger-magnitude pivots when we have too many.
        const maxLabels = 12;
        const pickTop = (arr: { i: number; price: number }[], top: boolean) => {
          if (arr.length <= maxLabels) return arr;
          const sorted = arr
            .slice()
            .sort((a, b) => (top ? b.price - a.price : a.price - b.price));
          return sorted.slice(0, maxLabels);
        };
        const nodes: { i: number; price: number; isHigh: boolean }[] = [
          ...pickTop(highs, true).map((p) => ({ ...p, isHigh: true })),
          ...pickTop(lows, false).map((p) => ({ ...p, isHigh: false })),
        ];
        // Avoid overlapping labels: sort by x, then skip any node closer than ~28px to the previous.
        nodes.sort((a, b) => a.i - b.i);
        const minPx = 26;
        let lastX = -Infinity;
        const filtered: typeof nodes = [];
        for (const n of nodes) {
          const x = n.i * step;
          if (x - lastX >= minPx || filtered.length === 0) {
            filtered.push(n);
            lastX = x;
          }
        }
        return filtered.map((n, idx) => {
          const x = n.i * step + candleGap / 2 + candleWidth / 2;
          const y = priceToY(n.price);
          const yLabel = n.isHigh ? Math.max(y - 6, 9) : Math.min(y + 12, chartH - 2);
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
              strokeWidth={0.6}
            >
              {formatPriceLabel(n.price)}
            </SvgText>
          );
        });
      })()}

      {/* v8.6.5 — Live-price line + pulsing dot. Renders whenever
          `isLive` is true (parent controls this via Binance WS connect
          state). The horizontal dashed line + right-edge price tag are
          drawn inside SVG. The pulsing dot animation is a sibling
          <Animated.View> laid on top of the SVG because SVG elements
          can't be animated with useNativeDriver on RN. */}
      {isLive && candles.length > 0 ? (() => {
        const lastCandle = displayed[displayed.length - 1];
        const lastY = priceToY(lastCandle.close);
        const isUp = lastCandle.close >= lastCandle.open;
        const liveColor = isUp ? upColor : downColor;
        return (
          <>
            <Line
              x1={0}
              x2={chartW}
              y1={lastY}
              y2={lastY}
              stroke={liveColor}
              strokeWidth={1}
              strokeDasharray="4 3"
              opacity={0.9}
            />
            <Rect
              x={chartW}
              y={lastY - 8}
              width={rightPad - 2}
              height={16}
              fill={liveColor}
              rx={2}
            />
            <SvgText
              x={chartW + 4}
              y={lastY + 4}
              fontSize={9.5}
              fontWeight="800"
              fill="#000"
            >
              {formatPriceLabel(lastCandle.close)}
            </SvgText>
          </>
        );
      })() : null}

      {/* v8.5.0 — Crosshair overlay (rendered last so it sits above candles). */}
      {hover ? (
        <>
          <Line
            x1={hover.x}
            x2={hover.x}
            y1={0}
            y2={chartH + (showVolume ? volumeH : 0)}
            stroke={colors.textMuted}
            strokeWidth={1}
            strokeDasharray="3 3"
            opacity={0.85}
          />
          <Line
            x1={0}
            x2={chartW}
            y1={hover.y}
            y2={hover.y}
            stroke={colors.textMuted}
            strokeWidth={1}
            strokeDasharray="3 3"
            opacity={0.85}
          />
          <Rect
            x={chartW}
            y={hover.y - 8}
            width={rightPad - 2}
            height={16}
            fill={colors.surfaceAlt || "#1E2329"}
            stroke={colors.border}
            strokeWidth={0.5}
            rx={2}
          />
          <SvgText
            x={chartW + 4}
            y={hover.y + 4}
            fontSize={9.5}
            fontWeight="700"
            fill={colors.textPrimary}
          >
            {formatPriceLabel(hover.candle.close)}
          </SvgText>
        </>
      ) : null}
    </Svg>
    {/* v8.6.5 — Pulsing live-price dot overlaid on top of the SVG at
        the right edge of the last candle. Animated at 60fps via
        useNativeDriver so it visibly "breathes" even when the WS
        price itself doesn't change every tick. */}
    {isLive && candles.length > 0 ? (() => {
      const lastCandle = displayed[displayed.length - 1];
      const lastX = (displayed.length - 1) * step + candleGap / 2 + candleWidth / 2;
      const lastY = priceToY(lastCandle.close);
      const isUp = lastCandle.close >= lastCandle.open;
      const liveColor = isUp ? upColor : downColor;
      const dotSize = 10;
      return (
        <View
          pointerEvents="none"
          style={{
            position: "absolute",
            left: lastX - dotSize / 2,
            top: lastY - dotSize / 2,
            width: dotSize,
            height: dotSize,
          }}
        >
          {/* Outer pulsing halo — scales 1→2.4 and fades 0.55→0 */}
          <Animated.View
            style={{
              position: "absolute",
              left: 0,
              top: 0,
              width: dotSize,
              height: dotSize,
              borderRadius: dotSize / 2,
              backgroundColor: liveColor,
              opacity: pulseAnim.interpolate({ inputRange: [0, 1], outputRange: [0.55, 0] }),
              transform: [
                { scale: pulseAnim.interpolate({ inputRange: [0, 1], outputRange: [1, 2.4] }) },
              ],
            }}
          />
          {/* Solid inner dot */}
          <View
            style={{
              position: "absolute",
              left: dotSize * 0.25,
              top: dotSize * 0.25,
              width: dotSize * 0.5,
              height: dotSize * 0.5,
              borderRadius: (dotSize * 0.5) / 2,
              backgroundColor: liveColor,
            }}
          />
        </View>
      );
    })() : null}
    {/* Floating OHLC tooltip — pinned to top of chart, offset to avoid finger. */}
    {hover ? (
      <View
        style={[
          styles.tooltip,
          {
            backgroundColor: (colors.surfaceAlt || "#1E2329") + "F2",
            borderColor: colors.border,
            left: Math.min(Math.max(4, hover.x - 82), width - 168),
            pointerEvents: "none" as const,
          },
        ]}
      >
        <Text style={[styles.tooltipTime, { color: colors.textMuted }]}>
          {fmtTime(hover.candle.t)}
        </Text>
        <View style={styles.tooltipRow}>
          <Text style={[styles.tooltipLabel, { color: colors.textMuted }]}>O</Text>
          <Text style={[styles.tooltipVal, { color: colors.textPrimary }]}>
            {formatPriceLabel(hover.candle.open)}
          </Text>
          <Text style={[styles.tooltipLabel, { color: colors.textMuted }]}>H</Text>
          <Text style={[styles.tooltipVal, { color: colors.accentUp }]}>
            {formatPriceLabel(hover.candle.high)}
          </Text>
        </View>
        <View style={styles.tooltipRow}>
          <Text style={[styles.tooltipLabel, { color: colors.textMuted }]}>L</Text>
          <Text style={[styles.tooltipVal, { color: colors.accentDown }]}>
            {formatPriceLabel(hover.candle.low)}
          </Text>
          <Text style={[styles.tooltipLabel, { color: colors.textMuted }]}>C</Text>
          <Text
            style={[
              styles.tooltipVal,
              {
                color:
                  hover.candle.close >= hover.candle.open
                    ? colors.accentUp
                    : colors.accentDown,
              },
            ]}
          >
            {formatPriceLabel(hover.candle.close)}
          </Text>
        </View>
      </View>
    ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  tooltip: {
    position: "absolute",
    top: 4,
    minWidth: 152,
    paddingHorizontal: 8,
    paddingVertical: 5,
    borderRadius: 6,
    borderWidth: 1,
  },
  tooltipRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    marginTop: 2,
  },
  tooltipTime: { fontSize: 10, fontWeight: "600" },
  tooltipLabel: { fontSize: 9.5, fontWeight: "700", width: 10 },
  tooltipVal: { fontSize: 10.5, fontWeight: "800", flex: 1 },
});

function formatPriceLabel(p: number): string {
  const abs = Math.abs(p);
  if (abs >= 1000) return p.toFixed(0);
  if (abs >= 10) return p.toFixed(2);
  if (abs >= 1) return p.toFixed(3);
  if (abs >= 0.01) return p.toFixed(4);
  return p.toFixed(6);
}
