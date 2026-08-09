/**
 * useBinanceKline — subscribe to Binance's public kline (candlestick)
 * WebSocket for a single spot pair + timeframe.  The hook emits the
 * currently-forming candle (the last row on the chart) on every trade
 * tick, so the parent can *patch* its REST candle array in place and
 * make the chart feel live.
 *
 * Reference:
 *   wss://stream.binance.com:9443/ws/<pair>@kline_<interval>
 *   Payload: { k: { t: openTime, o, h, l, c, v, x: isClosed, ... } }
 *
 * Binance intervals: 1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 8h, 12h,
 *   1d, 3d, 1w, 1M.  We map the app's TIMEFRAMES onto the closest match
 *   (e.g. app "3h" → Binance "2h", "18h" → "12h").
 */
import { useEffect, useState } from "react";

const STABLECOIN_SYMBOLS = new Set([
  "USDT", "USDC", "BUSD", "DAI", "TUSD", "FDUSD", "USDP", "USDS",
]);

// App timeframe → Binance interval string.  Binance doesn't support every
// app timeframe (e.g. 3h/18h), so we fall back to the closest one so the
// chart still updates roughly in sync.
const TF_MAP: Record<string, string> = {
  "1m": "1m",
  "3m": "3m",
  "5m": "5m",
  "15m": "15m",
  "30m": "30m",
  "1h": "1h",
  "3h": "2h",  // no 3h — 2h is closest
  "6h": "6h",
  "12h": "12h",
  "18h": "12h", // no 18h
  "24h": "1d",
  "7d": "1w",
  "14d": "1w",
  "30d": "1M",
};

export type LiveKline = {
  t: number;      // open time (seconds — matches REST format)
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  isClosed: boolean;
  updatedAt: number;
};

export function useBinanceKline(
  symbol: string | null | undefined,
  market: string,
  timeframe: string,
): LiveKline | null {
  const [kline, setKline] = useState<LiveKline | null>(null);

  useEffect(() => {
    if (market !== "crypto" || !symbol) {
      setKline(null);
      return;
    }
    const upper = symbol.toUpperCase();
    if (STABLECOIN_SYMBOLS.has(upper)) {
      setKline(null);
      return;
    }
    const bInterval = TF_MAP[timeframe] || "1h";
    const streamPath = `${upper.toLowerCase()}usdt@kline_${bInterval}`;
    // v8.6.7 — Lead with `data-stream.binance.vision` (Binance's public
    // read-only mirror hosted on Cloudflare — allowed from most regions
    // including preview pods). Fallback to main + US mirror if it drops.
    const urls = [
      `wss://data-stream.binance.vision/ws/${streamPath}`,
      `wss://stream.binance.com:9443/ws/${streamPath}`,
      `wss://stream.binance.us:9443/ws/${streamPath}`,
    ];

    let cancelled = false;
    let ws: WebSocket | null = null;
    let attempt = 0;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    const tryConnect = () => {
      if (cancelled) return;
      // v8.6.7 — Reconnect loop: once we've tried every URL, wait a
      // short backoff and start over from index 0. This means candle
      // ticking automatically recovers after a dropped/idle-out
      // connection instead of freezing until the user backgrounds and
      // reopens the app.
      if (attempt >= urls.length) {
        attempt = 0;
        reconnectTimer = setTimeout(tryConnect, 1500);
        return;
      }
      const url = urls[attempt++];
      try {
        ws = new WebSocket(url);
      } catch {
        tryConnect();
        return;
      }
      ws.onmessage = (event) => {
        if (cancelled) return;
        try {
          const data = JSON.parse(event.data as string);
          const k = data?.k;
          if (!k) return;
          const open = Number(k.o);
          const high = Number(k.h);
          const low = Number(k.l);
          const close = Number(k.c);
          const vol = Number(k.v);
          const t = Number(k.t);
          if (!Number.isFinite(close) || !Number.isFinite(t)) return;
          setKline({
            // REST candles use seconds; kline `t` is ms since epoch.
            t: Math.floor(t / 1000),
            open,
            high,
            low,
            close,
            volume: Number.isFinite(vol) ? vol : 0,
            isClosed: Boolean(k.x),
            updatedAt: Date.now(),
          });
        } catch {
          /* malformed frame */
        }
      };
      ws.onclose = () => {
        if (cancelled) return;
        // Advance to the next URL immediately; if all URLs are
        // exhausted, tryConnect() will wrap around after backoff.
        reconnectTimer = setTimeout(tryConnect, 250);
      };
      ws.onerror = () => {
        /* wait for close → fallback URL */
      };
    };
    tryConnect();

    return () => {
      cancelled = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      try {
        ws?.close();
      } catch {
        /* ignore */
      }
    };
  }, [symbol, market, timeframe]);

  return kline;
}

/**
 * Patch a REST candles array with the current live kline. If the live
 * kline is for the same open-time as the last REST candle, we replace it
 * in place. Otherwise (new candle after last close), we append.
 * Callers pass the result straight to the chart component.
 *
 * v8.6.9 — Timestamp-unit fix. REST candles use `t` in milliseconds
 * (from `/api/chart/*`) but WS klines store `t` in seconds (see the
 * `Math.floor(t / 1000)` inside setKline above). The old code compared
 * these directly → the delta was always ~1e12, never < 60, so the
 * "same candle" branch never fired and the chart looked static. We now
 * normalize `last.t` to seconds JUST for the comparison, and preserve
 * the REST millisecond format on the patched candle so the SVG X-axis
 * renderer keeps working unchanged.
 *
 * v8.6.13 — Made new-bar append explicit and interval-safe. The old
 * heuristic `Math.abs(lastTs - live.t) < 60` was a 1-minute window that
 * happened to work but had ambiguous edges. We now use strict equality
 * for "same candle" and `live.t > lastTs` for the append case, so a
 * 1-minute chart cleanly rolls over the instant the minute crosses.
 * The returned array is ALWAYS a fresh reference when we append or
 * replace, so React sees a new prop and re-renders — no more staying
 * frozen after a minute change.
 */
export function patchCandlesWithLive<C extends { t: number }>(
  candles: C[],
  live: LiveKline | null,
): C[] {
  if (!live || !candles || candles.length === 0) return candles;
  const last = candles[candles.length - 1];

  // Normalize REST `t` to seconds ONLY for the comparison. Any value
  // greater than 1e12 must be in ms (year > 33,000 in seconds would hit
  // that ceiling — safe heuristic). Values ≤ 1e12 are already seconds.
  const lastTs = last.t > 1e12 ? Math.floor(last.t / 1000) : last.t;

  // Rebuild `t` in the *same unit as the input candles* so downstream
  // renderers (SVG X-axis, tooltip time formatter) stay consistent.
  const patchedT = last.t > 1e12 ? live.t * 1000 : live.t;

  const patched: C = {
    ...last,
    t: patchedT as never,
    open: live.open as never,
    high: live.high as never,
    low: live.low as never,
    close: live.close as never,
    volume: live.volume as never,
  };

  if (lastTs === live.t) {
    // Same candle open-time — replace last bar in place.
    // Fresh array reference guarantees React re-renders the chart.
    const copy = candles.slice(0, -1);
    copy.push(patched);
    return copy;
  }
  if (live.t > lastTs) {
    // A brand-new bar just opened — append. The dedicated "new candle"
    // object uses `patchedT` (already in the input's time unit) and the
    // WS OHLCV so the chart immediately shows the fresh bar on the
    // right edge. The oldest bar rolls off naturally once the caller
    // slices to a fixed visible window (v8.6.13 in CandlestickChart).
    const nextBar: C = {
      ...last,
      t: patchedT as never,
      open: live.open as never,
      high: live.high as never,
      low: live.low as never,
      close: live.close as never,
      volume: live.volume as never,
    };
    return [...candles, nextBar];
  }
  // Older kline — ignore (out-of-order retransmission).
  return candles;
}
