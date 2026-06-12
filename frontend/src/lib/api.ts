/**
 * Backend API client for KevinAI Pro.
 */
const RAW = process.env.EXPO_PUBLIC_BACKEND_URL ?? "";
export const API_BASE = `${RAW.replace(/\/+$/, "")}/api`;

export type Market = "crypto" | "stock";
export type Timeframe = "15m" | "30m" | "1h" | "3h" | "6h" | "12h" | "18h" | "24h";

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
  stop_loss: number | null;
  take_profit: number | null;
  track_record: TrackRecordMini;
  is_premium: boolean;
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
    stop_loss: number | null;
    take_profit: number | null;
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
    stop_loss: number | null;
    take_profit: number | null;
    timeframe_view: string;
    news_factors: string[];
    risk_factors: string[];
    votes?: Record<string, number>;
  };
  models: ModelResult[];
  news_used: NewsItem[];
  generated_at: string;
}

export interface TrackRecordResponse {
  symbol: string;
  market: Market;
  win_rate_7d: { total: number; hits: number; win_rate: number | null };
  win_rate_30d: { total: number; hits: number; win_rate: number | null };
  win_rate_all: { total: number; hits: number; win_rate: number | null };
  recent_signals: {
    action: string;
    label: string;
    confidence: number;
    timeframe: string;
    price_at_signal: number;
    created_at: string;
    evaluation: { pct_change: number; hit: boolean; price_after: number };
  }[];
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`HTTP ${res.status} on ${path}`);
  return (await res.json()) as T;
}
async function send<T>(path: string, method: "POST" | "PUT" | "DELETE", body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
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
    opts: { sort?: DashboardSort; premiumOnly?: boolean; full?: boolean } = {},
  ) => {
    const params = new URLSearchParams({ market, timeframe });
    if (opts.sort) params.append("sort", opts.sort);
    if (opts.premiumOnly) params.append("premium_only", "true");
    if (opts.full) params.append("full", "true");
    return get<DashboardResponse>(`/dashboard?${params.toString()}`);
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

  chart: (market: Market, symbol: string, timeframe: Timeframe) =>
    get<ChartResponse>(`/asset/${market}/${symbol}/chart?timeframe=${timeframe}`),
  analyze: (market: Market, symbol: string, timeframe: Timeframe) =>
    send<AnalyzeResponse>(`/asset/${market}/${symbol}/analyze?timeframe=${timeframe}`, "POST"),
  trackRecord: (market: Market, symbol: string) =>
    get<TrackRecordResponse>(`/asset/${market}/${symbol}/track-record`),

  news: (market: Market | "all", limit = 40) =>
    get<NewsResponse>(`/news?market=${market}&limit=${limit}`),
  newsForAsset: (market: Market, symbol: string, limit = 10) =>
    get<NewsResponse>(`/asset/${market}/${symbol}/news?limit=${limit}`),
};

export const TIMEFRAMES: Timeframe[] = ["15m", "30m", "1h", "3h", "6h", "12h", "18h", "24h"];

export function formatPrice(v: number | null | undefined, market: Market): string {
  if (v === null || v === undefined || isNaN(v)) return "—";
  if (market === "stock") {
    return v.toLocaleString("id-ID", { minimumFractionDigits: 0, maximumFractionDigits: 0 });
  }
  if (v >= 1000) return v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  if (v >= 1) return v.toFixed(3);
  if (v >= 0.01) return v.toFixed(4);
  if (v >= 0.0001) return v.toFixed(6);
  return v.toExponential(3);
}

export function formatPct(v: number | null | undefined): string {
  if (v === null || v === undefined || isNaN(v)) return "—";
  const sign = v >= 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}%`;
}
