/**
 * v10.2.15 — In-Memory + Persistent Dashboard Profile Cache & Prefetcher.
 *
 * Keluhan user: saat berpindah trader profile di dashboard, tampilan
 * loading sangat lambat sebelum konten muncul.
 *
 * Solusi:
 * 1. Simpan hasil dashboardBatch per-profil di in-memory Map & AsyncStorage.
 * 2. Saat switch profile: jika cache ada, render data seketika (0ms delay),
 *    lalu revalidasi di background (stale-while-revalidate).
 * 3. Jika belum di cache: segera tampilkan skeleton loading responsif.
 * 4. Saat membuka modal Trader Profile atau idle: otomatis prefetch
 *    profil-profil lainnya di background sehingga saat dipilih, datanya
 *    sudah siap instan.
 */
import { api, type AssetSignal, type Market, type Timeframe } from "./api";
import { readPageCache, writePageCache } from "./pageCache";

export type Category = Market;

export type DashboardCachePayload = {
  data: Record<Category, AssetSignal[]>;
  premiumCount: number;
  at: number;
};

// In-memory cache map: key -> DashboardCachePayload
const memoryCache = new Map<string, DashboardCachePayload>();
const inFlightRequests = new Map<string, Promise<DashboardCachePayload | null>>();

export const ALL_CATEGORIES: Category[] = [
  "crypto",
  "etf",
  "stock_id",
  "stock_us",
  "world_stocks",
  "gold_silver",
  "commodity",
  "forex",
];

export function buildDashboardCacheKey(
  profile?: string | null,
  timeframe: Timeframe = "1h",
  region: string = "all"
): string {
  return `dash:${profile || "default"}:${timeframe}:${region}`;
}

/** Synchronous read from in-memory cache */
export function getSyncDashboardCache(
  profile?: string | null,
  timeframe: Timeframe = "1h",
  region: string = "all"
): DashboardCachePayload | null {
  const key = buildDashboardCacheKey(profile, timeframe, region);
  return memoryCache.get(key) ?? null;
}

/** Set cache in memory and write to disk asynchronously */
export function setDashboardCache(
  profile: string | null | undefined,
  timeframe: Timeframe,
  region: string,
  data: Record<Category, AssetSignal[]>,
  premiumCount: number
): void {
  const key = buildDashboardCacheKey(profile, timeframe, region);
  const payload: DashboardCachePayload = {
    data,
    premiumCount,
    at: Date.now(),
  };
  memoryCache.set(key, payload);
  writePageCache(key, payload);
}

/** Async read from AsyncStorage if memory cache misses on cold boot */
export async function loadPersistentDashboardCache(
  profile?: string | null,
  timeframe: Timeframe = "1h",
  region: string = "all"
): Promise<DashboardCachePayload | null> {
  const key = buildDashboardCacheKey(profile, timeframe, region);
  const mem = memoryCache.get(key);
  if (mem) return mem;
  const disk = await readPageCache<DashboardCachePayload>(key);
  if (disk && disk.data) {
    memoryCache.set(key, disk);
    return disk;
  }
  return null;
}

/** Prefetch a specific profile in the background */
export async function prefetchDashboardProfile(
  profile?: string | null,
  timeframe: Timeframe = "1h",
  region: string = "all",
  hasAccess: boolean = true,
  extras: string[] = []
): Promise<DashboardCachePayload | null> {
  const key = buildDashboardCacheKey(profile, timeframe, region);
  const existing = memoryCache.get(key);
  // If cached within last 45s, skip network call
  if (existing && Date.now() - existing.at < 45_000) {
    return existing;
  }

  // Deduplicate in-flight requests
  const existingPromise = inFlightRequests.get(key);
  if (existingPromise) {
    return existingPromise;
  }

  const promise = (async () => {
    try {
      const res = await api.dashboardBatch(ALL_CATEGORIES as Market[], timeframe, {
        sort: "premium",
        full: false,
        region: region as any,
        extras,
        profile: hasAccess ? (profile ?? undefined) : undefined,
      });

      const nextData: Record<Category, AssetSignal[]> = {
        crypto: [],
        etf: [],
        stock_id: [],
        stock_us: [],
        world_stocks: [],
        gold_silver: [],
        commodity: [],
        forex: [],
      };

      ALL_CATEGORIES.forEach((k) => {
        const m = res.markets?.[k];
        if (m && Array.isArray(m.assets)) {
          nextData[k] = m.assets;
        }
      });

      let pCount = 0;
      Object.values(res.markets || {}).forEach((m) => {
        pCount += m?.premium_count ?? 0;
      });

      const payload: DashboardCachePayload = {
        data: nextData,
        premiumCount: pCount,
        at: Date.now(),
      };

      memoryCache.set(key, payload);
      writePageCache(key, payload);
      return payload;
    } catch {
      return null;
    } finally {
      inFlightRequests.delete(key);
    }
  })();

  inFlightRequests.set(key, promise);
  return promise;
}

/** Prefetch all popular profiles in the background (fire-and-forget) */
export function prefetchAllProfiles(
  currentProfile?: string | null,
  timeframe: Timeframe = "1h",
  region: string = "all",
  hasAccess: boolean = true,
  extras: string[] = []
): void {
  if (!hasAccess) return;
  // v10.2.16 — Sertakan "longterm" (Confluence v9): sebelumnya profil
  // ini TIDAK pernah di-prefetch sehingga selalu cold-fetch saat dipilih
  // (keluhan: ganti ke profil apa pun lambat).
  const profilesToPrefetch = ["day", "scalper", "swing", "longterm", null].filter(
    (p) => (p ?? null) !== (currentProfile ?? null)
  );

  // Stagger requests slightly to prevent network congestion
  profilesToPrefetch.forEach((p, idx) => {
    setTimeout(() => {
      prefetchDashboardProfile(p, timeframe, region, hasAccess, extras).catch(() => {});
    }, (idx + 1) * 350);
  });
}
