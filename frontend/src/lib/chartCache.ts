/**
 * v10.2.9 — Chart prefetch cache (in-memory).
 *
 * Masalah: tap kartu di Running Positions / Recent Trades membuka
 * halaman grafik yang baru mulai fetch SETELAH navigasi selesai →
 * terasa lambat (spinner 1-3 detik di jaringan HP).
 *
 * Solusi: saat kartu ditekan, fetch chart LANGSUNG dimulai sebelum
 * router.push; halaman detail mengambil promise yang sudah berjalan
 * (atau data yang sudah selesai) → chart tampil hampir instan.
 *
 * Cache single-use dengan TTL 60 detik. Miss = fallback fetch normal,
 * tidak ada risiko data basi berkepanjangan.
 */
import { api, type ChartResponse, type Market, type Timeframe } from "./api";

type Entry = { at: number; promise: Promise<ChartResponse | null> };
const cache = new Map<string, Entry>();
const TTL_MS = 90_000;
const MAX_ENTRIES = 60;

function keyOf(market: Market, symbol: string, tf: Timeframe, profile?: string): string {
  return `${market}|${symbol.toUpperCase()}|${tf}|${profile || "none"}`;
}

/** Tembak fetch chart di background (fire-and-forget). Dipanggil tepat
 * sebelum router.push ke halaman detail aset. */
export function prefetchChart(
  market: Market, symbol: string, tf: Timeframe = "1h", profile?: string,
): void {
  try {
    const k = keyOf(market, symbol, tf, profile);
    const existing = cache.get(k);
    if (existing && Date.now() - existing.at < TTL_MS) return; // masih segar
    if (cache.size >= MAX_ENTRIES) {
      // Buang entri tertua supaya memori tidak tumbuh.
      let oldestKey: string | null = null;
      let oldestAt = Infinity;
      cache.forEach((v, k2) => {
        if (v.at < oldestAt) { oldestAt = v.at; oldestKey = k2; }
      });
      if (oldestKey) cache.delete(oldestKey);
    }
    // v10.2.16 — Promise prefetch TIDAK BOLEH reject tanpa handler:
    // rejection yang belum di-await (network error / "Failed to fetch")
    // memicu red-screen "Uncaught Error" (dev) / unhandled rejection di
    // HP. Bungkus dengan catch → log + null, sehingga kegagalan jaringan
    // diperlakukan sebagai cache-miss: halaman detail jatuh ke fetch
    // normal yang punya skeleton + retry, tanpa crash.
    cache.set(k, {
      at: Date.now(),
      promise: api.chart(market, symbol, tf, profile).catch((err) => {
        console.warn(`[chartCache] prefetch ${symbol} gagal (diabaikan):`, err);
        return null;
      }),
    });
  } catch {
    /* prefetch gagal → halaman fetch normal */
  }
}

/** Ambil hasil prefetch bila ada & segar. Single-use: entri dihapus
 * setelah diambil supaya navigasi berikutnya selalu fetch data baru. */
export async function getPrefetchedChart(
  market: Market, symbol: string, tf: Timeframe, profile?: string,
): Promise<ChartResponse | null> {
  const k = keyOf(market, symbol, tf, profile);
  const e = cache.get(k);
  if (!e || Date.now() - e.at >= TTL_MS) return null;
  cache.delete(k);
  try {
    return await e.promise;
  } catch {
    return null;
  }
}
