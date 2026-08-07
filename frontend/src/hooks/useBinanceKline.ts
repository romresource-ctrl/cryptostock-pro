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
    const urls = [
      `wss://stream.binance.com:9443/ws/${streamPath}`,
      `wss://stream.binance.us:9443/ws/${streamPath}`,
    ];

    let cancelled = false;
    let ws: WebSocket | null = null;
    let attempt = 0;

    const tryConnect = () => {
      if (cancelled || attempt >= urls.length) return;
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
        if (attempt < urls.length) setTimeout(tryConnect, 250);
      };
      ws.onerror = () => {
        /* wait for close → fallback URL */
      };
    };
    tryConnect();

    return () => {
      cancelled = true;
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
 * Patch a REST candles array with the current live kline.  If the live
 * kline is for the same open-time as the last REST candle, we replace it
 * in place.  Otherwise (new candle after last close), we append.
 * Callers pass the result straight to the chart component.
 */
export function patchCandlesWithLive<C extends { t: number }>(
  candles: C[],
  live: LiveKline | null,
): C[] {
  if (!live || !candles || candles.length === 0) return candles;
  const last = candles[candles.length - 1];
  const patched: C = {
    ...last,
    t: live.t,
    open: (live.open as any),
    high: (live.high as any),
    low: (live.low as any),
    close: (live.close as any),
    volume: (live.volume as any),
  };
  if (Math.abs(last.t - live.t) < 60) {
    // Same candle — replace in place.
    const copy = candles.slice(0, -1);
    copy.push(patched);
    return copy;
  }
  if (live.t > last.t) {
    // A new bar just opened — append.
    return [...candles, patched];
  }
  // Older kline — ignore (out-of-order retransmission).
  return candles;
}
