/**
 * useBinanceRealtime — subscribe to Binance's public ticker WebSocket
 * (24-hr rolling stats) for a single spot pair.  Emits a live price and
 * 24h change % as they tick in — typically every 100-200ms.
 *
 * Only used for crypto assets on the detail page.  Falls back to the
 * REST snapshot (already fetched by the parent) when:
 *   • Symbol isn't tradable on Binance (e.g. WLD-USD).
 *   • Web preview blocks WebSocket connections.
 *   • Any error happens during the handshake.
 *
 * Reference: https://binance-docs.github.io/apidocs/spot/en/#individual-symbol-ticker-streams
 *   Stream: <symbol>usdt@ticker → payload includes `c` (close), `P` (24h %).
 */
import { useEffect, useRef, useState } from "react";

// Some tickers on Binance use USDC or BUSD quote instead of USDT — most
// popular assets are USDT-quoted, so we default there and let the caller
// override for edge-cases.
const DEFAULT_QUOTE = "usdt";

// Stablecoins have no meaningful "24h change %" — Binance sometimes even
// returns 0.00% which the UI would render as a flat green.  We short-
// circuit for them so the caller keeps its REST snapshot instead.
const STABLECOIN_SYMBOLS = new Set([
  "USDT", "USDC", "BUSD", "DAI", "TUSD", "FDUSD", "USDP", "USDS",
]);

export type RealtimeTick = {
  /** Last-traded price ("c" field). */
  price: number;
  /** 24-hour rolling change percent ("P" field). */
  changePct: number;
  /** True while the WebSocket handshake is complete and receiving messages. */
  connected: boolean;
  /** Ms since epoch of last received tick. */
  updatedAt: number | null;
};

const IDLE: RealtimeTick = {
  price: NaN,
  changePct: NaN,
  connected: false,
  updatedAt: null,
};

export function useBinanceRealtime(
  symbol: string | null | undefined,
  market: string,
  quote: string = DEFAULT_QUOTE,
): RealtimeTick {
  const [tick, setTick] = useState<RealtimeTick>(IDLE);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    // Not applicable for anything that isn't crypto, or when we have no symbol.
    if (market !== "crypto" || !symbol) {
      setTick(IDLE);
      return;
    }
    const upper = symbol.toUpperCase();
    if (STABLECOIN_SYMBOLS.has(upper)) {
      // Stablecoins hover near $1 permanently — keep the REST snapshot instead.
      setTick(IDLE);
      return;
    }

    // v10.1.7 — Pakai stream `@aggTrade` (aggregate trade) BUKAN `@ticker`.
    // Binance `@ticker` (24hrTicker) HANYA update setiap ~1 detik BY DESIGN
    // sehingga harga terasa lambat. `@aggTrade` fired SETIAP trade agregat
    // (bisa 5-50 update/detik untuk pair liquid) sehingga mark price
    // benar-benar "berkedip" real-time. Field: p=price, q=qty.
    // Kita throttle ke 100ms agar tidak re-render >10x/detik (hemat CPU).
    const streamPath = `${upper.toLowerCase()}${quote}@aggTrade`;
    // v10.0.13 — Prioritaskan Binance FUTURES (fstream) sebagai sumber WS
    // utama supaya harga realtime = perp mark/last (bukan spot). Ini juga
    // yang membuat hook useDipTopAlert kembali terpicu — beberapa simbol
    // (contoh: PENGU, WIF versi lama) tidak ada di spot tapi ada di
    // perpetual futures, sehingga WS spot gagal konek dan dip/top tidak
    // pernah menerima tick. Spot tetap sebagai fallback terakhir.
    const urls = [
      `wss://fstream.binance.com/ws/${streamPath}`,
      `wss://data-stream.binance.vision/ws/${streamPath}`,
      `wss://stream.binance.com:9443/ws/${streamPath}`,
      `wss://stream.binance.us:9443/ws/${streamPath}`,
    ];

    let cancelled = false;
    let ws: WebSocket | null = null;
    let attempt = 0;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let lastEmit = 0;

    const tryConnect = () => {
      if (cancelled) return;
      // v8.6.7 — Reconnect loop: after every URL has been tried we wrap
      // back to attempt 0 with a short backoff so the LIVE badge / price
      // ticker recovers automatically after a dropped or idle-out socket.
      if (attempt >= urls.length) {
        attempt = 0;
        reconnectTimer = setTimeout(tryConnect, 1500);
        return;
      }
      const url = urls[attempt++];
      try {
        ws = new WebSocket(url);
        wsRef.current = ws;
      } catch {
        tryConnect();
        return;
      }

      ws.onopen = () => {
        if (cancelled) return;
        setTick((prev) => ({ ...prev, connected: true }));
      };
      ws.onmessage = (event) => {
        if (cancelled) return;
        try {
          const data = JSON.parse(event.data as string);
          // v10.1.7 — aggTrade payload: {e,s,p,q}. Dulu @ticker pakai
          // {c, P}. Kita parse keduanya agar tetap kompatibel jika
          // ada fallback stream.
          const price = Number(data?.p ?? data?.c);
          const changePct = Number(data?.P);
          if (!Number.isFinite(price)) return;
          // Throttle 100ms: drop tick yang datang lebih cepat dari
          // interval — menghindari React re-render berlebihan.
          const now = Date.now();
          if (now - lastEmit < 100) return;
          lastEmit = now;
          setTick({
            price,
            changePct: Number.isFinite(changePct) ? changePct : NaN,
            connected: true,
            updatedAt: now,
          });
        } catch {
          /* malformed frame — ignore */
        }
      };
      ws.onerror = () => {
        // If the primary rejects (e.g. HTTP 451 in restricted regions), we
        // wait for onclose to fire and then advance to the fallback URL.
      };
      ws.onclose = () => {
        if (cancelled) return;
        setTick((prev) => ({ ...prev, connected: false }));
        // Always retry — either the next URL in the list, or (when the
        // list is exhausted) wrap around after backoff inside tryConnect.
        reconnectTimer = setTimeout(tryConnect, 250);
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
      wsRef.current = null;
    };
  }, [symbol, market, quote]);

  return tick;
}
