/**
 * Backend API client for KevinAI Pro.
 */
const RAW = process.env.EXPO_PUBLIC_BACKEND_URL ?? "";
export const API_BASE = `${RAW.replace(/\/+$/, "")}/api`;

export type Market = "crypto" | "etf" | "stock_id" | "stock_us" | "world_stocks" | "gold_silver" | "commodity" | "forex";
export type Timeframe = "1m" | "3m" | "5m" | "15m" | "30m" | "1h" | "3h" | "6h" | "12h" | "18h" | "24h" | "7d" | "14d" | "30d";

export interface TrackRecordMini {
  wr_7d: number | null;
  n_7d: number;
  wr_30d: number | null;
  n_30d: number;
}

export interface AssetSignal {
  symbol: string;
  market: Market;
  price: number | null;
  change_pct_24h: number | null;
  high_24h: number | null;
  low_24h: number | null;
  volume_24h: number | null;
  spark: number[];
  action: "BUY" | "SELL" | "HOLD";
  label: string;
  confidence: number;
  indicators: Record<string, number | null>;
  reasons: string[];
  entry: number | null;
  // v8.1.9 — Entry zone (range) for display as "$1915 - $1925".
  entry_low?: number | null;
  entry_high?: number | null;
  // v8.1.6 — Alternate entry cycles (moderate / aggressive tiers).
  entry_moderate?: number | null;
  entry_aggressive?: number | null;
  stop_loss: number | null;
  take_profit: number | null;
  track_record: TrackRecordMini;
  is_premium: boolean;
  // v8.1.3 — Region key from Yahoo suffix (us/europe/japan/china/…).
  region?: string | null;
  // v8.2.2 — Risk/Reward metrics for badge display.
  risk_reward?: number | null;
  risk_level?: "Low" | "Medium" | "High" | null;
  reward_pct?: number | null;
  risk_pct?: number | null;
}

export type DashboardSort = "default" | "premium" | "confidence" | "wr";

export interface DashboardResponse {
  market: Market;
  timeframe: Timeframe;
  server_time: string;
  assets: AssetSignal[];
  profile_id: string;
  profile_name: string;
  premium_count: number;
  premium_threshold: { min_confidence: number; min_wr: number };
}

export interface Profile {
  id: string;
  name: string;
  crypto: string[];
  stocks: string[];
}

export interface ProfilesResponse {
  profiles: Profile[];
  active_id: string;
  available_crypto: string[];
  available_stocks: string[];
  timeframes: Timeframe[];
}

export interface WatchlistResponse {
  crypto: string[];
  stocks: string[];
  available_crypto: string[];
  available_stocks: string[];
  timeframes: Timeframe[];
  profile_id: string;
  profile_name: string;
}

export interface ChartResponse {
  symbol: string;
  market: Market;
  timeframe: Timeframe;
  ticker: {
    price?: number;
    change_pct_24h?: number;
    high_24h?: number;
    low_24h?: number;
    volume_24h?: number;
  };
  candles: { t: number; open: number; high: number; low: number; close: number; volume: number }[];
  signal: {
    action: string;
    label: string;
    confidence: number;
    indicators: Record<string, number | null>;
    reasons: string[];
    entry: number | null;
    entry_low?: number | null;
    entry_high?: number | null;
    entry_moderate?: number | null;
    entry_aggressive?: number | null;
    stop_loss: number | null;
    take_profit: number | null;
    // v8.2.2 — Risk/Reward badge fields
    risk_reward?: number | null;
    risk_level?: "Low" | "Medium" | "High" | null;
    reward_pct?: number | null;
    risk_pct?: number | null;
  };
}

export interface ModelResult {
  name: string;
  ok: boolean;
  data: {
    action?: string;
    label?: string;
    confidence?: number;
    summary?: string;
    entry?: number;
    stop_loss?: number;
    take_profit?: number;
    timeframe_view?: string;
    news_factors?: string[];
    risk_factors?: string[];
  } | null;
  error?: string;
}

export interface NewsItem {
  source: string;
  title: string;
  url: string | null;
  summary: string | null;
  published: string | null;
  image: string | null;
}

export interface NewsResponse {
  market: Market | "all";
  items: NewsItem[];
  fetched_at: string;
}

export interface AnalyzeResponse {
  symbol: string;
  market: Market;
  timeframe: Timeframe;
  price: number;
  technical: ChartResponse["signal"];
  consensus: {
    action: string;
    label: string;
    confidence: number;
    summary: string;
    entry: number | null;
    entry_low?: number | null;
    entry_high?: number | null;
    stop_loss: number | null;
    take_profit: number | null;
    timeframe_view: string;
    // v8.1.7 — Additional AI insight
    macro_context?: string;
    entry_bias?: "deep" | "moderate" | "aggressive";
    news_factors: string[];
    risk_factors: string[];
    votes?: Record<string, number>;
    bias_votes?: Record<string, number>;
  };
  models: ModelResult[];
  news_used: NewsItem[];
  generated_at: string;
}

export interface TrackRecordWrBucket {
  total: number;
  hits: number;      // legacy alias (= wins)
  wins?: number;
  losses?: number;
  break_even?: number;
  win_rate: number | null;
}

export interface TrackRecordHistoryItem {
  action: string;
  label: string;
  confidence: number;
  timeframe: string;
  price_at_signal: number;
  created_at: string;
  outcome?: "WIN" | "LOSS" | "BE";
  pct_change?: number;
  price_after?: number;
  evaluation?: { pct_change: number; hit: boolean; price_after: number; outcome?: string };
}

export interface TrackRecordResponse {
  symbol: string;
  market: Market;
  win_rate_7d: TrackRecordWrBucket;
  win_rate_30d: TrackRecordWrBucket;
  win_rate_all: TrackRecordWrBucket;
  recent_signals: TrackRecordHistoryItem[];
  history_7d?: TrackRecordHistoryItem[];
  history_30d?: TrackRecordHistoryItem[];
  history_all?: TrackRecordHistoryItem[];
}

import { APP_VERSION } from "./version";

const COMMON_HEADERS: Record<string, string> = {
  "X-App-Version": APP_VERSION,
};

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { headers: COMMON_HEADERS });
  if (res.status === 426) {
    const err: Error & { code?: string } = new Error("Aplikasi Anda sudah kadaluarsa. Silakan install APK versi terbaru dari admin.");
    err.code = "upgrade_required";
    throw err;
  }
  if (!res.ok) throw new Error(`HTTP ${res.status} on ${path}`);
  return (await res.json()) as T;
}
async function send<T>(path: string, method: "POST" | "PUT" | "DELETE", body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: body ? { "Content-Type": "application/json", ...COMMON_HEADERS } : COMMON_HEADERS,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 426) {
    const err: Error & { code?: string } = new Error("Aplikasi Anda sudah kadaluarsa. Silakan install APK versi terbaru dari admin.");
    err.code = "upgrade_required";
    throw err;
  }
  if (!res.ok) {
    const txt = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status} on ${path}: ${txt.slice(0, 120)}`);
  }
  return (await res.json()) as T;
}

export const api = {
  dashboard: (
    market: Market,
    timeframe: Timeframe,
    opts: { sort?: DashboardSort; premiumOnly?: boolean; full?: boolean; profile?: string } = {},
  ) => {
    const params = new URLSearchParams({ market, timeframe });
    if (opts.sort) params.append("sort", opts.sort);
    if (opts.premiumOnly) params.append("premium_only", "true");
    if (opts.full) params.append("full", "true");
    if (opts.profile) params.append("profile", opts.profile);
    return get<DashboardResponse>(`/dashboard?${params.toString()}`);
  },
  // v8.0.4 — Batch dashboard fetch. Instead of firing N parallel HTTP
  // requests, hand the backend a comma-separated market list and let it
  // do the fan-out server-side (one response, one setState).
  dashboardBatch: (
    markets: Market[],
    timeframe: Timeframe,
    opts: { sort?: DashboardSort; full?: boolean; region?: string; extras?: string[]; profile?: string } = {},
  ) => {
    const params = new URLSearchParams({
      markets: markets.join(","),
      timeframe,
    });
    if (opts.sort) params.append("sort", opts.sort);
    if (opts.full) params.append("full", "true");
    if (opts.region && opts.region !== "all") params.append("region", opts.region);
    // v9.0.0 — Trader profile so dashboard signals match the detail page.
    if (opts.profile) params.append("profile", opts.profile);
    // v8.12.18 — Ship watchlist entries as extras so the backend
    // includes symbols beyond the default top-50 slice (e.g. BBCA at
    // index 51 in stock_id). Format: `market:SYMBOL,market:SYMBOL`.
    if (opts.extras && opts.extras.length > 0) {
      params.append("extras", opts.extras.join(","));
    }
    return get<{
      timeframe: Timeframe;
      server_time: string;
      markets: Record<string, DashboardResponse & { error?: string }>;
    }>(`/dashboard/batch?${params.toString()}`);
  },
  watchlist: () => get<WatchlistResponse>("/watchlist"),
  updateWatchlist: (payload: { crypto: string[]; stocks: string[] }) =>
    send<WatchlistResponse>("/watchlist", "POST", payload),

  profiles: () => get<ProfilesResponse>("/profiles"),
  createProfile: (payload: { name: string; crypto?: string[]; stocks?: string[] }) =>
    send<Profile>("/profiles", "POST", payload),
  updateProfile: (id: string, payload: { name?: string; crypto?: string[]; stocks?: string[] }) =>
    send<Profile>(`/profiles/${id}`, "PUT", payload),
  deleteProfile: (id: string) => send<{ ok: boolean }>(`/profiles/${id}`, "DELETE"),
  activateProfile: (id: string) => send<{ ok: boolean; active_id: string }>(`/profiles/${id}/activate`, "POST"),

  chart: (market: Market, symbol: string, timeframe: Timeframe, profile?: string) =>
    get<ChartResponse>(
      `/asset/${market}/${symbol}/chart?timeframe=${timeframe}${profile ? `&profile=${encodeURIComponent(profile)}` : ""}`,
    ),
  analyze: (market: Market, symbol: string, timeframe: Timeframe, lang: "id" | "en" | "ru" | "cn" = "en", profile?: string) =>
    send<AnalyzeResponse>(
      `/asset/${market}/${symbol}/analyze?timeframe=${timeframe}&lang=${lang}${profile ? `&profile=${encodeURIComponent(profile)}` : ""}`,
      "POST",
    ),
  trackRecord: (market: Market, symbol: string) =>
    get<TrackRecordResponse>(`/asset/${market}/${symbol}/track-record`),

  news: (market: Market | "all", limit = 40, lang: "id" | "en" = "id") =>
    get<NewsResponse>(`/news?market=${market}&limit=${limit}&lang=${lang}`),
  newsForAsset: (market: Market, symbol: string, limit = 10, lang: "id" | "en" = "id") =>
    get<NewsResponse>(`/asset/${market}/${symbol}/news?limit=${limit}&lang=${lang}`),

  translate: (texts: string[], target_lang: "en" | "id" = "en") =>
    send<{ target_lang: string; items: string[] }>(`/translate`, "POST", { texts, target_lang }),

  aiModels: () =>
    get<{ models: { name: string; provider: string }[] }>(`/ai/models`),

  search: (q: string, timeframe: string = "1h", profile?: string) =>
    get<{
      hits: AssetSignal[];
      query: string;
      disambiguation?: { id: string; symbol: string; name: string; market_cap_rank: number | null; thumb: string | null }[];
    }>(
      `/search?q=${encodeURIComponent(q)}&timeframe=${encodeURIComponent(timeframe)}${profile ? `&profile=${encodeURIComponent(profile)}` : ""}`,
    ),
};

export const TIMEFRAMES: Timeframe[] = ["1m", "3m", "5m", "15m", "30m", "1h", "3h", "6h", "12h", "18h", "24h", "7d", "14d", "30d"];

export function formatPrice(v: number | null | undefined, market: Market): string {
  if (v === null || v === undefined || isNaN(v)) return "—";
  if (market === "stock_id") {
    return v.toLocaleString("id-ID", { minimumFractionDigits: 0, maximumFractionDigits: 0 });
  }
  // v8.12.62 — Refined adaptive precision. The previous rule collapsed
  // 1-100 range to 2 decimals, hiding real precision for coins like
  // DOT (1.0315 → 1.03), OP (2.1234 → 2.12), ATOM, SOL below $100, etc.
  // New rule mirrors Binance display exactly:
  //   v >= 100        → 2 decimals   ("77,868.18", "150.32")
  //   1 ≤ v < 100     → 4 decimals   ("1.0315", "12.5432", "88.4321")
  //   0.01 ≤ v < 1    → 5 decimals   ("0.03892", "0.12272")
  //   0.0001 ≤ v      → 6 decimals   ("0.001234")
  //   0.00000001 ≤    → 8 decimals   ("0.00000123")
  //   below           → toFixed(10) trim (SHIB-tier)
  const abs = Math.abs(v);
  let decimals: number;
  if (abs >= 100) decimals = 2;
  else if (abs >= 1) decimals = 4;
  else if (abs >= 0.01) decimals = 5;
  else if (abs >= 0.0001) decimals = 6;
  else if (abs >= 0.00000001) decimals = 8;
  else return v.toFixed(10).replace(/0+$/, "").replace(/\.$/, "");
  return v.toLocaleString("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

export function formatPct(v: number | null | undefined): string {
  if (v === null || v === undefined || isNaN(v)) return "—";
  const sign = v >= 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}%`;
}
