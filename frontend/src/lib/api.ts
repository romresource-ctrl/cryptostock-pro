/**
 * Backend API client for AITrade Pro.
 *
 * Reads EXPO_PUBLIC_BACKEND_URL from env and appends /api prefix.
 */
const RAW = process.env.EXPO_PUBLIC_BACKEND_URL ?? "";
export const API_BASE = `${RAW.replace(/\/+$/, "")}/api`;

export type Market = "crypto" | "stock";

export type Timeframe = "15m" | "30m" | "1h" | "3h" | "6h" | "12h" | "18h" | "24h";

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
}

export interface DashboardResponse {
  market: Market;
  timeframe: Timeframe;
  server_time: string;
  assets: AssetSignal[];
}

export interface WatchlistResponse {
  crypto: string[];
  stocks: string[];
  available_crypto: string[];
  available_stocks: string[];
  timeframes: Timeframe[];
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
  generated_at: string;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`HTTP ${res.status} on ${path}`);
  return (await res.json()) as T;
}
async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status} on ${path}`);
  return (await res.json()) as T;
}

export const api = {
  dashboard: (market: Market, timeframe: Timeframe) =>
    get<DashboardResponse>(`/dashboard?market=${market}&timeframe=${timeframe}`),
  watchlist: () => get<WatchlistResponse>("/watchlist"),
  updateWatchlist: (payload: { crypto: string[]; stocks: string[] }) =>
    post<WatchlistResponse>("/watchlist", payload),
  chart: (market: Market, symbol: string, timeframe: Timeframe) =>
    get<ChartResponse>(`/asset/${market}/${symbol}/chart?timeframe=${timeframe}`),
  analyze: (market: Market, symbol: string, timeframe: Timeframe) =>
    post<AnalyzeResponse>(`/asset/${market}/${symbol}/analyze?timeframe=${timeframe}`, {}),
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
