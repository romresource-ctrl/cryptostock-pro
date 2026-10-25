/**
 * v10.2.16 — useBinanceMultiTicker: mark price realtime MULTI simbol
 * lewat SATU koneksi WebSocket combined-stream Binance (`@aggTrade`).
 *
 * Latar: kartu Recent Trades / Running Positions mengandalkan polling
 * backend `/api/asi/prices` tiap 300ms. Bila upstream production
 * terblokir atau request menggantung, harga & PnL kartu membeku
 * (keluhan berulang "kartu tidak berkedip"). Halaman grafik memakai WS
 * langsung dari device dan terbukti LIVE — hook ini membawa sumber yang
 * sama ke kartu posisi. Polling backend TETAP jalan sebagai pelengkap
 * (merge), jadi simbol non-Binance tetap ter-update.
 *
 * Stream: wss://fstream.binance.com/market/stream?streams=btcusdt@aggTrade/...
 * Fallback host sama seperti useBinanceRealtime, plus watchdog 8 detik
 * untuk koneksi silent-dead, reconnect otomatis, dan throttle 150ms per
 * simbol (hemat re-render).
 */
import { useEffect, useRef, useState } from "react";
import { AppState } from "react-native";

/** Normalisasi "BTC/USDT" / "BTCUSDT" / "btc" → "BTC" (kunci map harga). */
function norm(sym: string): string {
  return sym.toUpperCase().replace(/[^A-Z0-9]/g, "").replace(/USDT$/, "");
}

export function useBinanceMultiTicker(symbols: string[]): Record<string, number> {
  const [px, setPx] = useState<Record<string, number>>({});
  const lastEmitRef = useRef<Record<string, number>>({});
  const key = symbols.map(norm).filter(Boolean).sort().join(",");

  useEffect(() => {
    if (!key) {
      setPx({});
      return;
    }
    const streams = key
      .split(",")
      .map((b) => `${b.toLowerCase()}usdt@aggTrade`)
      .join("/");
    // Futures dulu (mark price perp = acuan kartu), lalu spot fallback.
    const urls = [
      `wss://fstream.binance.com/market/stream?streams=${streams}`,
      `wss://data-stream.binance.vision/stream?streams=${streams}`,
      `wss://stream.binance.com:9443/stream?streams=${streams}`,
    ];

    let cancelled = false;
    let ws: WebSocket | null = null;
    let attempt = 0;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let dataWatchdog: ReturnType<typeof setTimeout> | null = null;

    // Rolling inactivity watchdog — dipanggil ulang tiap pesan masuk.
    const armWatchdog = (ms: number) => {
      if (dataWatchdog) clearTimeout(dataWatchdog);
      dataWatchdog = setTimeout(() => {
        try { ws?.close(); } catch { /* ignore */ }
      }, ms);
    };

    const tryConnect = () => {
      if (cancelled) return;
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
      ws.onopen = () => {
        if (cancelled) return;
        // 8 detik tanpa pesan pertama = koneksi silent-dead → tutup
        // paksa supaya fallback host berikutnya dicoba.
        armWatchdog(8000);
      };
      ws.onmessage = (event) => {
        if (cancelled) return;
        // v10.2.16 — ROLLING watchdog: sebelumnya timer hanya menjaga
        // pesan PERTAMA, sehingga koneksi yang mati-menggantung SETELAH
        // beberapa tick (keluhan user: "berkedip 2x lalu statis") tidak
        // pernah terdeteksi. Kini tiap pesan memperbarui timer 30 detik;
        // 30 detik tanpa pesan → socket ditutup → reconnect/host lain.
        armWatchdog(30_000);
        attempt = 0; // v10.3.7 — koneksi sehat → reconnect berikutnya mulai dari futures lagi
        try {
          const msg = JSON.parse(event.data as string);
          // combined-stream membungkus payload: {stream, data}
          const data = msg?.data ?? msg;
          const sym = String(data?.s ?? "");
          const price = Number(data?.p ?? data?.c);
          if (!sym || !Number.isFinite(price)) return;
          const base = norm(sym);
          const now = Date.now();
          if (now - (lastEmitRef.current[base] || 0) < 150) return;
          lastEmitRef.current[base] = now;
          setPx((cur) => (cur[base] === price ? cur : { ...cur, [base]: price }));
        } catch {
          /* frame rusak — abaikan */
        }
      };
      ws.onerror = () => { /* onclose yang melanjutkan fallback */ };
      ws.onclose = () => {
        if (cancelled) return;
        reconnectTimer = setTimeout(tryConnect, 250);
      };
    };
    tryConnect();

    // v10.3.7 — kembali dari background: OS sering membunuh socket diam-diam
    // → paksa reconnect agar harga kartu OPEN langsung jalan lagi.
    const sub = AppState.addEventListener("change", (st) => {
      if (st !== "active" || cancelled) return;
      attempt = 0;
      try { ws?.close(); } catch { /* ignore */ }
    });

    return () => {
      cancelled = true;
      sub.remove();
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (dataWatchdog) clearTimeout(dataWatchdog);
      try { ws?.close(); } catch { /* ignore */ }
    };
  }, [key]);

  return px;
}
