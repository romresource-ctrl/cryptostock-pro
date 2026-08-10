import React, { useEffect, useState } from "react";
import { Animated, StyleSheet, Text, View } from "react-native";
import { Gesture, GestureDetector } from "react-native-gesture-handler";
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
  /** v8.6.12 — Override for the "live close" value that drives the
      dashed line, right-edge tag and pulsing dot. When provided (from
      the parent's Binance ticker WS), this keeps the header price and
      chart live-line in perfect lock-step — otherwise the chart uses
      the last candle's close which lags a beat behind the ticker. */
  livePrice?: number | null;
  /** v8.7.8 — Small blinking pill drawn at the LEFT edge of the live-price
      line, tracks vertically with the price (so it looks like a moving
      badge riding the ticker). Passed as-is from `usePriceZoneAlert()`.
      Supports laddered zones: entry, tp1/tp2/tp3, buy3/buy2/buy1, sl.
      When "idle" nothing is drawn. */
  alertZone?:
    | "idle" | "entry"
    | "tp1" | "tp2" | "tp3"
    | "buy3" | "buy2" | "buy1"
    | "sl";
  /** v8.7.7 — signal direction (BUY / SELL / HOLD) used only to colour
      the ENTRY badge (BUY = green, SELL = red). */
  signalAction?: string;
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
  livePrice = null,
  alertZone = "idle",
  signalAction,
}: Props) {
  const { colors } = useTheme();

  // v8.6.14 — Zoomable window via pinch. `visibleCount` was hardcoded
  // 120 in v8.6.13; now it's stateful so `Gesture.Pinch()` can shrink
  // (zoom in / see more detail per candle) or grow (zoom out / see
  // longer history) the visible window at runtime.
  const DEFAULT_VISIBLE = 120;
  const MIN_VISIBLE = 20;   // most zoomed-in
  const MAX_VISIBLE = 300;  // most zoomed-out (max candles the SVG will render)
  const [visibleCount, setVisibleCount] = useState<number>(DEFAULT_VISIBLE);
  // Panning state. `endIndex` is the array-index of the right-most
  // visible candle. Default = latest bar. Users can drag horizontally
  // (Gesture.Pan) to inspect history; the chart AUTO-ADVANCES to the
  // newest candle ONLY IF endIndex was pinned to the latest before an
  // append. If the user has scrolled back, we freeze the view so they
  // can inspect the past without being yanked forward.
  const [endIndex, setEndIndex] = useState<number>(candles.length - 1);
  // `panStartEndIndex` and `isPanningRef` from v8.6.13 were removed —
  // the new UI-thread Gesture.Pan (v8.6.14) uses `endIndexRef` +
  // per-gesture closures instead.

  // Auto-advance: when a new bar arrives (candles.length increases), bump
  // endIndex ONLY when the user was already viewing the newest bar.
  const prevLenRef = React.useRef<number>(candles.length);
  React.useEffect(() => {
    const prev = prevLenRef.current;
    const curr = candles.length;
    if (curr > prev) {
      // A new bar was appended. Pinned-to-right if endIndex was at the
      // previous last index.
      if (endIndex >= prev - 1) {
        setEndIndex(curr - 1);
      }
    } else if (curr < prev) {
      // Data reset / timeframe change — snap to latest.
      setEndIndex(curr - 1);
    }
    prevLenRef.current = curr;
  }, [candles.length, endIndex]);

  // If the incoming `candles` array is smaller than our recorded index
  // (e.g. after a timeframe switch that returns fewer bars), clamp.
  const clampedEnd = Math.min(endIndex, Math.max(0, candles.length - 1));

  // Hooks must run before any early return.
  const [cursorX, setCursorX] = useState<number | null>(null);

  // v8.7.18 — Hide the live-price OVERLAYS (right-edge SVG price tag
  // and the pulsing halo) for the first 300ms after mount so they
  // don't paint at full saturation on the very first frame (green
  // flicker). Chart data, gestures, live-price sync are untouched —
  // this is a display-only opacity gate applied via `overlayOpacity`.
  const [overlayOpacity, setOverlayOpacity] = useState(0);
  useEffect(() => {
    const t = setTimeout(() => setOverlayOpacity(1), 300);
    return () => clearTimeout(t);
  }, []);
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

  // v8.6.17 — Unified gesture stack, ALL via react-native-gesture-handler:
  //   • Gesture.Pan()   → horizontal slide to inspect history
  //   • Gesture.Pinch() → zoom in/out to change candles-per-viewport
  //   • Gesture.Tap()   → tap-to-place-crosshair (replaces the old
  //                       PanResponder that ran in parallel)
  // All three are composed inside a single `Gesture.Simultaneous` so
  // exactly ONE gesture system is attached to the chart view, avoiding
  // race conditions where PanResponder + RNGH would fight for touches.
  // The tap also drives `setCursorX` on a longer hold (Tap.numberOfTaps
  // 1 with maxDuration long-enough for read-off) — pan/pinch still win
  // for any real drag/scale.

  // Refs used by UI-thread gesture callbacks so they always see the
  // latest committed state without re-registering the gesture handler.
  const endIndexRef = React.useRef<number>(endIndex);
  React.useEffect(() => { endIndexRef.current = endIndex; }, [endIndex]);
  const visibleCountRef = React.useRef<number>(visibleCount);
  React.useEffect(() => { visibleCountRef.current = visibleCount; }, [visibleCount]);

  const candlesLen = candles.length;
  const applyPan = React.useCallback(
    (translationX: number, startEnd: number) => {
      const chartWidthPx = width - 56;
      const stepPx = Math.max(1, chartWidthPx / visibleCountRef.current);
      const deltaCandles = Math.round(-translationX / stepPx);
      const target = startEnd + deltaCandles;
      const minEnd = Math.max(0, Math.min(visibleCountRef.current - 1, candlesLen - 1));
      const maxEnd = candlesLen - 1;
      setEndIndex(Math.min(maxEnd, Math.max(minEnd, target)));
    },
    [width, candlesLen],
  );

  const applyPinch = React.useCallback(
    (scale: number, startVisible: number) => {
      // Pinch OUT (scale > 1) → zoom IN → fewer candles visible.
      // Pinch IN  (scale < 1) → zoom OUT → more candles visible.
      const next = Math.round(startVisible / Math.max(0.1, scale));
      const clamped = Math.min(MAX_VISIBLE, Math.max(MIN_VISIBLE, next));
      setVisibleCount(clamped);
    },
    [],
  );

  const chartGesture = React.useMemo(() => {
    const panStart = { end: candles.length - 1 };
    const pinchStart = { visible: DEFAULT_VISIBLE };
    // v8.6.15 — Gesture callbacks run on the JS thread (no `"worklet"`
    // directive, no `runOnJS`) so we don't require the Reanimated
    // Babel plugin to touch this file. Pan/pinch latency is 1-2 frames
    // — imperceptible for chart panning at 60fps.
    const pan = Gesture.Pan()
      // Activate only after 10px horizontal movement — leaves smaller
      // gestures free for the crosshair Tap gesture in the same stack.
      .activeOffsetX([-10, 10])
      // If the finger travels vertically first, fail this gesture so
      // the parent ScrollView can scroll the page.
      .failOffsetY([-15, 15])
      // `.runOnJS(true)` = handler bodies stay on JS thread. Safe
      // because we don't use any Reanimated shared values here.
      .runOnJS(true)
      .onStart(() => {
        panStart.end = endIndexRef.current;
      })
      .onUpdate((e) => {
        applyPan(e.translationX, panStart.end);
      });

    const pinch = Gesture.Pinch()
      .runOnJS(true)
      .onStart(() => {
        pinchStart.visible = visibleCountRef.current;
      })
      .onUpdate((e) => {
        applyPinch(e.scale, pinchStart.visible);
      });

    // v8.6.17 — Crosshair tap. Fires on a quick tap → shows crosshair
    // at the touch X for ~1.2s then auto-hides (setTimeout scheduled
    // in onEnd). Pan wins over Tap for any real horizontal drag; Pinch
    // wins for two-finger gestures. Tap only fires when neither of
    // the other gestures activates (Race semantics of the Simultaneous
    // composition + Tap's short activation window).
    const tap = Gesture.Tap()
      .maxDuration(250)
      .runOnJS(true)
      .onEnd((e) => {
        setCursorX(e.x);
        // Auto-hide crosshair after 1.2s so it doesn't linger.
        setTimeout(() => setCursorX(null), 1200);
      });

    return Gesture.Simultaneous(pan, pinch, tap);
  }, [applyPan, applyPinch, candles.length]);

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

  // v8.6.14 — Panning + pinch-zoom aware slice.
  const startIdx = Math.max(0, clampedEnd - visibleCount + 1);
  const endIdx = Math.max(0, clampedEnd) + 1;
  const rawDisplayed = candles.slice(startIdx, endIdx);

  // v8.6.17 — Live-tick candle mutation. When `isLive` + `livePrice` are
  // both truthy, override the last visible candle's `close/high/low`
  // with the live price so the body/wick redraw on every ticker frame.
  //   - close   = livePrice (drives the body top/bottom on falling ticks)
  //   - high    = max(candle.high, livePrice)  (wick grows if price
  //               exceeds current bar high)
  //   - low     = min(candle.low,  livePrice)  (wick grows if price
  //               drops below current bar low)
  // This is applied ONLY to the last candle so historical bars remain
  // immutable. The mutation also feeds into the Y-axis range
  // calculation below, so the scale auto-expands if the live price
  // wanders outside the pre-existing highs/lows.
  const displayed =
    isLive &&
    typeof livePrice === "number" &&
    Number.isFinite(livePrice) &&
    rawDisplayed.length > 0
      ? (() => {
          const arr = rawDisplayed.slice();
          const lc = arr[arr.length - 1];
          arr[arr.length - 1] = {
            ...lc,
            close: livePrice,
            high: Math.max(lc.high, livePrice),
            low: Math.min(lc.low, livePrice),
          } as (typeof lc);
          return arr;
        })()
      : rawDisplayed;

  const highs = displayed.map((c) => c.high);
  const lows = displayed.map((c) => c.low);
  // v8.6.17 — Ensure the live price ALWAYS lands inside the visible
  // range even before the last-candle mutation propagates through React
  // state. Guarantees the dashed live-line + right-tag never render off-
  // screen when the market suddenly spikes/dumps past the previous
  // candle extremes.
  const liveP =
    isLive && typeof livePrice === "number" && Number.isFinite(livePrice)
      ? livePrice
      : null;
  const priceMax = Math.max(...highs, liveP ?? -Infinity);
  const priceMin = Math.min(...lows, liveP ?? Infinity);
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
  // Hooks (`cursorX`, gesture memos) are declared at the top of this
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
    <GestureDetector gesture={chartGesture}>
    <View style={{ width, height }} testID="candlestick-chart">
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
        // v8.6.12 — Prefer the ticker WS price (updates every ~200ms)
        // over the kline WS close (updates every 1-2s and rounds to
        // whole units on the wire). Falls back to candle close when no
        // ticker price has arrived yet.
        const liveClose =
          typeof livePrice === "number" && Number.isFinite(livePrice)
            ? livePrice
            : lastCandle.close;
        const lastY = priceToY(liveClose);
        const isUp = liveClose >= lastCandle.open;
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
              y={lastY - 11}
              width={rightPad - 2}
              height={22}
              fill={liveColor}
              rx={3}
              opacity={overlayOpacity}
            />
            <SvgText
              x={chartW + 4}
              y={lastY + 5}
              fontSize={11}
              fontWeight="900"
              fill="#000"
              opacity={overlayOpacity}
            >
              {formatPriceLabel(liveClose)}
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
      // v8.6.12 — Dot Y must match the same live-close used by the
      // dashed line + right-edge tag above; otherwise the dot appears
      // to hover a fraction of a pixel away from its own price line.
      const liveCloseDot =
        typeof livePrice === "number" && Number.isFinite(livePrice)
          ? livePrice
          : lastCandle.close;
      const lastY = priceToY(liveCloseDot);
      const isUp = lastCandle.close >= lastCandle.open;
      const liveColor = isUp ? upColor : downColor;
      const dotSize = 16;
      return (
        <View
          pointerEvents="none"
          style={{
            position: "absolute",
            left: lastX - dotSize / 2,
            top: lastY - dotSize / 2,
            width: dotSize,
            height: dotSize,
            opacity: overlayOpacity,
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
                { scale: pulseAnim.interpolate({ inputRange: [0, 1], outputRange: [1, 4.5] }) },
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

    {/* v8.7.9 — Alert pill (ENTRY / TP HIT / SL HIT) riding the live-price
        line at the LEFT edge. Same vertical Y as the right-edge tag so
        it visually "hangs" off the same horizontal price line. Small so
        it doesn't dominate the chart. The specific ladder level (BUY-1/2/3
        or TP-1/2/3) is rendered separately as a top-left badge overlay
        from [symbol].tsx. */}
    {isLive && candles.length > 0 && alertZone !== "idle" ? (() => {
      const lastCandle = displayed[displayed.length - 1];
      const liveClose =
        typeof livePrice === "number" && Number.isFinite(livePrice)
          ? livePrice
          : lastCandle.close;
      const lastY = priceToY(liveClose);
      // Map ladder → primary 3-state pill
      const isSl = alertZone === "sl";
      const isTp = alertZone === "tp1" || alertZone === "tp2" || alertZone === "tp3";
      const isEntry =
        alertZone === "entry" ||
        alertZone === "buy3" || alertZone === "buy2" || alertZone === "buy1";
      if (!isSl && !isTp && !isEntry) return null;
      const label = isSl ? "SL HIT" : isTp ? "TP HIT" : "ENTRY";
      const bg = isSl
        ? downColor
        : isTp
          ? "#f5c518"
          : (signalAction === "SELL" ? downColor : upColor);
      const fg = isSl ? "#fff" : "#000";
      return (
        <AlertPill
          top={lastY - 10}
          bg={bg}
          fg={fg}
          label={label}
        />
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
    </GestureDetector>
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
  // v8.6.12 — Aligned with formatPrice(): exactly 2 decimals for
  // regular prices; extra precision preserved only for sub-cent tokens
  // so SHIB/PEPE-style entries don't collapse into "0.00".
  const abs = Math.abs(p);
  if (abs >= 0.01) return p.toFixed(2);
  if (abs >= 0.0001) return p.toFixed(6);
  return p.toFixed(8);
}

/**
 * Small blinking "ENTRY / TP HIT / SL HIT" pill overlaid on the left
 * edge of the live-price line. Uses opacity animation loop (400ms fade)
 * with native driver so it stays smooth even while candles tick.
 */
function AlertPill({ top, bg, fg, label }: { top: number; bg: string; fg: string; label: string }) {
  const opacity = React.useRef(new Animated.Value(1)).current;
  React.useEffect(() => {
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(opacity, { toValue: 0.25, duration: 400, useNativeDriver: true }),
        Animated.timing(opacity, { toValue: 1, duration: 400, useNativeDriver: true }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [opacity]);
  return (
    <Animated.View
      pointerEvents="none"
      style={{
        position: "absolute",
        left: 2,
        top,
        backgroundColor: bg,
        borderRadius: 3,
        paddingHorizontal: 5,
        paddingVertical: 1,
        opacity,
      }}
      testID={`chart-alert-pill-${label.toLowerCase().replace(/\s+/g, "-")}`}
    >
      <Text style={{ color: fg, fontSize: 9, fontWeight: "900", letterSpacing: 0.4 }}>
        {label}
      </Text>
    </Animated.View>
  );
}
