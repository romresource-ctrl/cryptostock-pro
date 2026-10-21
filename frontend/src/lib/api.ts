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
  // v9.2.0 — Ladder TP lengkap (dipakai kartu AI Suggestions).
  take_profit_2?: number | null;
  take_profit_3?: number | null;
  track_record: TrackRecordMini;
  is_premium: boolean;
  // v8.1.3 — Region key from Yahoo suffix (us/europe/japan/china/…).
  region?: string | null;
  // v8.2.2 — Risk/Reward metrics for badge display.
  risk_reward?: number | null;
  risk_level?: "Low" | "Medium" | "High" | null;
  reward_pct?: number | null;
  risk_pct?: number | null;
  // v9.8.3 — Flag dari backend: false bila simbol TIDAK tradable sebagai
  // USDT perpetual di Binance Futures (mis. aset delisted seperti OCEAN).
  // undefined = belum dicek (anggap tradable).
  futures_tradable?: boolean;
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

async function get<T>(path: string, timeoutMs?: number): Promise<T> {
  // v10.2.16 — Timeout opsional: tanpa ini fetch yang menggantung
  // (jaringan lambat / backend sibuk memindai universe penuh) membuat
  // UI skeleton selamanya — kasus user: AI Suggestions "stuck" saat
  // menampilkan aset hasil filter formula.
  const ctrl = timeoutMs ? new AbortController() : null;
  const timer = ctrl ? setTimeout(() => ctrl.abort(), timeoutMs) : null;
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      headers: COMMON_HEADERS,
      signal: ctrl?.signal,
    });
  } catch (e) {
    if (ctrl?.signal.aborted) throw new Error(`Timeout ${timeoutMs}ms on ${path}`);
    throw e;
  } finally {
    if (timer) clearTimeout(timer);
  }
  // v10.2.16 — Auto-retry 1x setelah 3 detik untuk error server 5xx
  // (mis. 502 Bad Gateway saat backend restart / proxy gangguan sesaat).
  // Keputusan user: gangguan sesaat tidak boleh langsung melempar error
  // ke UI. Bila retry tetap gagal, caller menampilkan pesan + tombol
  // Retry (bukan crash).
  if (res.status >= 500) {
    console.warn(`[api] HTTP ${res.status} pada ${path} — retry otomatis dalam 3 detik`);
    await new Promise((r) => setTimeout(r, 3000));
    res = await fetch(`${API_BASE}${path}`, { headers: COMMON_HEADERS });
  }
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
    // v9.6.9 — Preserve structured error body so callers can read
    // {code, message} and localize per-user. FastAPI wraps HTTPException
    // in {detail: ...}; some endpoints throw plain strings.
    let parsed: any = null;
    try { parsed = txt ? JSON.parse(txt) : null; } catch {}
    const detail = parsed?.detail ?? parsed;
    const errMsg = (detail && typeof detail === "object" ? detail.message : detail) || `HTTP ${res.status}`;
    const err: Error & { code?: string; detail?: any; status?: number } = new Error(String(errMsg));
    err.status = res.status;
    err.detail = (detail && typeof detail === "object") ? detail : undefined;
    err.code = (detail && typeof detail === "object") ? detail.code : undefined;
    throw err;
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
      // v10.2.16 — Timeout fetch chart DIHAPUS (keputusan user): kecepatan
      // dijamin oleh prefetch+chartCache (list trade mem-prefetch semua
      // kartu di background) + pageCache; bukan oleh batas waktu.
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

  // v9.2.0 — AI Suggestions (PREMIUM): aset dengan sinyal aktif terkuat
  // per kategori market, lengkap Entry/SL/TP1-3. Backend gate via
  // device_id entitlement (403 bila non-premium).
  aiSuggestions: (
    market: Market,
    timeframe: Timeframe = "1h",
    profile?: string,
    deviceId?: string,
  ) => {
    const params = new URLSearchParams({ market, timeframe });
    if (profile) params.append("profile", profile);
    if (deviceId) params.append("device_id", deviceId);
    return get<{
      market: Market;
      timeframe: string;
      profile: string | null;
      engine: string;
      count: number;
      suggestions: AssetSignal[];
      server_time: string;
    }>(`/ai-suggestions?${params.toString()}`, 45_000);
  },
  search: (q: string, timeframe: string = "1h", profile?: string) =>
    get<{
      hits: AssetSignal[];
      query: string;
      disambiguation?: { id: string; symbol: string; name: string; market_cap_rank: number | null; thumb: string | null }[];
    }>(
      `/search?q=${encodeURIComponent(q)}&timeframe=${encodeURIComponent(timeframe)}${profile ? `&profile=${encodeURIComponent(profile)}` : ""}`,
    ),

  // ===== v9.3.0 ASI-Bot (Phase 2-4) =====
  asi: {
    listCredentials: (deviceId: string) =>
      get<{ items: AsiCredential[]; supported_exchanges: { id: string; display: string }[] }>(
        `/asi/credentials?device_id=${encodeURIComponent(deviceId)}`,
      ),
    saveCredential: (deviceId: string, body: AsiSaveCredentialBody) =>
      send<AsiCredentialSaveResp>(
        `/asi/credentials?device_id=${encodeURIComponent(deviceId)}`,
        "POST", body,
      ),
    deleteCredential: (deviceId: string, exchange: string) =>
      send<{ deleted: number }>(
        `/asi/credentials/${exchange}?device_id=${encodeURIComponent(deviceId)}`,
        "DELETE",
      ),
    testCredential: (deviceId: string, exchange: string) =>
      send<{ ok: boolean; message?: string }>(
        `/asi/credentials/${exchange}/test?device_id=${encodeURIComponent(deviceId)}`,
        "POST",
      ),
    whitelist: () => get<{ top_100: string[]; count: number }>(`/asi/whitelist`),
    previewTrade: (deviceId: string, body: AsiTradeBody) =>
      send<AsiPreview>(
        `/asi/trades/preview?device_id=${encodeURIComponent(deviceId)}`, "POST", body,
      ),
    executeTrade: (deviceId: string, body: AsiTradeBody) =>
      send<AsiTradeResp>(
        `/asi/trades/execute?device_id=${encodeURIComponent(deviceId)}`, "POST", body,
      ),
    listTrades: (deviceId: string, limit: number = 20) =>
      get<{ items: AsiTradeResp[] }>(
        `/asi/trades?device_id=${encodeURIComponent(deviceId)}&limit=${limit}`,
      ),
    closeAllTrades: (deviceId: string) =>
      send<{ ok: boolean; closed: number; errors: { symbol: string; error: string }[] }>(
        `/asi/trades/close-all?device_id=${encodeURIComponent(deviceId)}`, "POST",
      ),
    closeTrade: (deviceId: string, tradeId: string) =>
      send<{ ok: boolean; already_closed?: boolean }>(
        `/asi/trades/${encodeURIComponent(tradeId)}/close?device_id=${encodeURIComponent(deviceId)}`,
        "POST",
      ),
    // v9.9.13 — Hapus kartu history (closed/expired/cancelled saja).
    deleteTrade: (deviceId: string, tradeId: string) =>
      send<{ ok: boolean }>(
        `/asi/trades/${encodeURIComponent(tradeId)}?device_id=${encodeURIComponent(deviceId)}`,
        "DELETE",
      ),
    closeTradeBySymbol: (deviceId: string, symbol: string, exchange: string) =>
      send<{ ok: boolean; closed: number; symbol: string; note?: string | null }>(
        `/asi/trades/close-by-symbol?device_id=${encodeURIComponent(deviceId)}` +
        `&symbol=${encodeURIComponent(symbol)}&exchange=${encodeURIComponent(exchange)}`,
        "POST",
      ),
    repairBrackets: (deviceId: string, exchange: string = "binance") =>
      send<{ ok: boolean; repaired: number; total: number;
             results: { ok: boolean; symbol?: string; errors?: string[] }[] }>(
        `/asi/trades/repair-brackets?device_id=${encodeURIComponent(deviceId)}&exchange=${encodeURIComponent(exchange)}`,
        "POST",
      ),
    // v9.9.9 — harga live Binance Futures via backend (untuk copy trade
    // entry pada harga pasar saat ini).
    price: (symbol: string) =>
      get<{ symbol: string; price: number }>(
        `/asi/price?symbol=${encodeURIComponent(symbol)}`,
      ),
    // v9.9.13 — Batch harga live untuk mark price realtime Recent Trades.
    // v10.2.16 — Timeout 5s: polling 300ms tidak menunggu, tapi request
    // yang menggantung permanen tidak boleh menumpuk tak berujung.
    prices: (symbols: string[]) =>
      get<{ prices: Record<string, number> }>(
        `/asi/prices?symbols=${encodeURIComponent(symbols.join(","))}`,
        5_000,
      ),
    // v10.2.7 — Scan debug: alasan scanner mengeksekusi / me-skip device ini.
    scanDebug: (deviceId: string) =>
      get<{
        last_scan_at?: string | null;
        devices_scanned: number;
        device_in_scanner: boolean;
        report: {
          scanned: boolean;
          skip_reason?: string | null;
          signals: number;
          placed: number;
          rejects: Record<string, number>;
        } | null;
        config: Record<string, any> | null;
      }>(`/asi/scan-debug?device_id=${encodeURIComponent(deviceId)}`),
    // v9.9.9 — saldo USDT available untuk jaringan aktif (demo/real).
    balance: (deviceId: string, exchange: string = "binance") =>
      get<{ ok: boolean;
             demo: { connected: boolean; available_usdt: number | null };
             real: { connected: boolean; available_usdt: number | null } }>(
        `/asi/balance?device_id=${encodeURIComponent(deviceId)}&exchange=${encodeURIComponent(exchange)}`,
      ),
    pnl: (deviceId: string) =>
      get<AsiPnl>(`/asi/pnl?device_id=${encodeURIComponent(deviceId)}`),
    leaderboard: (periodDays = 7) =>
      get<{ items: AsiLeaderRow[]; period_days: number }>(
        `/asi/leaderboard?period_days=${periodDays}`,
      ),
    leaderboardLive: () =>
      get<{ items: AsiLiveRow[] }>(`/asi/leaderboard/live`),
    getBot: (deviceId: string) =>
      get<AsiBotConfig & { exists: boolean }>(
        `/asi/bot?device_id=${encodeURIComponent(deviceId)}`,
      ),
    saveBot: (deviceId: string, body: AsiBotConfig) =>
      send<{ ok: boolean } & AsiBotConfig>(
        `/asi/bot?device_id=${encodeURIComponent(deviceId)}`, "POST", body,
      ),
    serverIp: () => get<{ ip: string; instructions: string }>("/asi/server-ip"),
  },
};

export type AsiCredential = {
  device_id: string; exchange: string; display: string;
  testnet: boolean; api_key_mask: string; handle: string;
  created_at: string; updated_at: string;
};
export type AsiSaveCredentialBody = {
  exchange: "binance" | "bybit" | "okx" | "bitget";
  api_key: string; api_secret: string; password?: string | null;
  testnet: boolean; email?: string | null;
};
export type AsiCredentialSaveResp = {
  ok: boolean; exchange: string; display: string; testnet: boolean;
  api_key_mask: string; handle: string; message: string;
};
export type AsiTradeBody = {
  exchange: "binance" | "bybit" | "okx" | "bitget";
  symbol: string; side: "BUY" | "SELL";
  entry: number; stop_loss: number; take_profits: number[];
  risk_pct: number; leverage: number;
  mode?: "semi" | "full";
  // v9.6.0 — TP strategy & trailing stop
  tp_count?: 1 | 2 | 3;
  // v10.2.36 — Auto-Close Profit ROI % dari margin (0 = off)
  auto_close_pct?: 0 | 10 | 15 | 20 | 25 | 50 | 100;
  margin_usdt?: number;
  trailing_callback_rate?: number;
  // v9.9.0 — Margin mode wajib dipilih user sebelum eksekusi
  margin_mode?: "isolated" | "cross";
  // v9.9.5 — Network (undefined → backend pakai active_testnet config)
  testnet?: boolean;
  // v9.9.13 — Profil formula saat eksekusi (label di kartu history)
  profile?: string | null;
  // Tag singkat modul pemicu (mis. "John Wick Candle Stick")
  formula_tag?: string | null;
  // v10.0.1 — Tipe eksekusi: limit (moderate) / market (instan)
  entry_mode?: "limit" | "market";
};
export type AsiPreview = {
  ok: boolean; balance_usdt: number; margin_usdt: number;
  size_usdt: number; qty: number; leverage: number; risk_pct: number;
  est_loss_usdt: number;
  tp_estimations: { tp: number; qty_share: number; est_profit_usdt: number }[];
  message?: string;
  // v9.8.3 — machine-readable error code untuk lokalisasi frontend
  reason?: "not_listed" | "market_inactive" | "min_notional" | string;
  // v9.8.8 — detail utk reason=min_notional
  min_notional?: number;
};
export type AsiTradeResp = {
  ok?: boolean; exchange: string; testnet: boolean; symbol: string;
  side: "BUY" | "SELL"; entry_price: number; stop_loss: number;
  take_profits: number[]; qty: number; leverage: number; risk_pct: number;
  status: "open" | "closed"; pnl_usdt: number; created_at: string;
  entry_order_id?: string | null;
  // v9.7.4 — enriched fields for the Recent Trades panel
  margin_usdt?: number | null;
  mark_price?: number | null;
  formula_tag?: string | null;
  bracket_type?: string | null;
  close_reason?: string | null;
  closed_at?: string | null;
  // v9.9.9 — harga close aktual (fill terakhir) untuk history detail
  closed_price?: number | null;
  exit_price?: number | null;  // legacy soft-close field
  // v9.9.0 — alasan bracket native gagal (ditampilkan saat tap badge ⚠️)
  soft_bracket_reason?: string | null;
  margin_mode?: string | null;
  // v9.9.2 — actual margin mode read from Binance positionRisk (bisa
  // berbeda dari margin_mode yang diminta kalau posisi sudah terbuka
  // di mode berbeda). UI pakai field ini (bukan margin_mode request).
  actual_margin_mode?: string | null;
  // v9.9.3 — leverage AKTUAL dibaca dari positionRisk (bisa beda dari
  // leverage request bila Binance menolak karena tier notional). UI pakai
  // ini, fallback ke leverage lama untuk trade pre-v9.9.3.
  actual_leverage?: number | null;
  // v9.9.4 — layering (averaging): true bila ini eksekusi ke-2+ simbol
  // yang sama; layer_count = total layer pada posisi gabungan.
  layered?: boolean;
  layer_count?: number;
  // v9.9.2 — hasil verifikasi bracket aktif di openAlgoOrders. True =
  // SL+TP masih live di exchange. False = sudah tidak ada (kemungkinan
  // user cancel manual di Binance app) → tampilkan tombol REPAIR.
  bracket_live?: boolean | null;
  bracket_verified_at?: string | null;
  // v9.7.6 — mode badge (SEMI / FULL) + stable id for manual close
  mode?: "semi" | "full" | null;
  _id?: string | null;
};
export type AsiPnl = Record<"daily" | "weekly" | "monthly", {
  pnl_usdt: number; pnl_pct: number; trades: number; wins: number; losses: number;
}> & {
  // v9.9.5 — ringkasan DEMO (testnet) terpisah; tidak masuk PnL real.
  demo?: { pnl_usdt: number; trades: number; wins: number; losses: number };
};
export type AsiLeaderRow = {
  rank: number; handle: string; pnl_usdt: number; trades: number; wr: number;
  // v9.9.7 — badge DEMO/REAL di leaderboard periode
  testnet?: boolean;
};
// v10.0.5 — Satu entri leaderboard = SATU posisi (open/closed), bukan trader.
export type AsiLiveRow = {
  rank: number;
  handle: string;
  testnet?: boolean;
  status?: "open" | "closed" | string;
  symbol: string | null;
  side: "BUY" | "SELL" | null;
  entry_price: number | null;
  stop_loss: number | null;
  take_profits: number[] | null;
  leverage: number | null;
  exchange: string | null;
  // v10.0.5 — badge seperti Recent Trades: mode bot & cara entry
  mode?: "semi" | "full" | string | null;
  entry_mode?: "market" | "limit" | string | null;
  created_at: string | null;
  closed_at?: string | null;
  closed_price?: number | null;
  close_reason?: string | null;
  pnl_usdt: number;
  pnl_pct?: number;
  wr30d?: number;
  trades30d?: number;
  // v10.0.13 — Dibutuhkan utk hitung PnL realtime di leaderboard dari
  // mark price Futures Perp + tampilan status/harga partial TP.
  qty?: number | null;
  margin_usdt?: number | null;
  tp_fills?: Array<{ level: string; price: number | null; qty: number; pnl: number | null; at: string }> | null;
};
export type AsiBotConfig = {
  enabled: boolean;
  exchange: "binance" | "bybit" | "okx" | "bitget";
  mode: "semi" | "full";
  max_trades_per_day: number;
  risk_pct: number;
  leverage: number;
  whitelist: string[];
  profile?: "confluence" | "scalper" | "day" | "swing" | "longterm" | null;
  min_confidence?: number;
  daily_loss_limit_usdt?: number;
  // v9.6.0 — TP flexibility & trailing stop
  tp_count?: 1 | 2 | 3;
  auto_close_pct?: 0 | 10 | 15 | 20 | 25 | 50 | 100;
  margin_usdt?: number;
  trailing_callback_rate?: number;
  // v9.7.6 — independent Semi/Full enable flags
  semi_enabled?: boolean;
  full_enabled?: boolean;
  // v9.7.7 — persistent disclaimer acknowledgement
  disclaimer_ack?: boolean;
  // v9.9.0 — default margin mode bot
  margin_mode?: "isolated" | "cross";
  // v10.0.1 — tipe eksekusi entry bot (limit moderate / market instan)
  entry_mode?: "limit" | "market";
  // v9.9.5 — network aktif (testnet/mainnet). Credential per jaringan
  // disimpan di slot terpisah; switching tidak meminta API key ulang.
  active_testnet?: boolean;
  // v10.0.14 — Sumber sinyal:
  //   "asi_bot"   → formula internal (Confluence v9 / VWAP engines)
  //   "cloud_pro" → sinyal eksternal "Cloud Pro Engine" via webhook
  //   "hybrid"    → terima dari keduanya
  signal_source?: "asi_bot" | "cloud_pro" | "hybrid";
  auto_disabled_reason?: string | null;
  auto_disabled_at?: string | null;
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
