"""AITrade Pro backend.

Endpoints:
  GET    /api/                              health
  GET    /api/profiles                      list profiles + active
  POST   /api/profiles                      create profile {name, crypto?, stocks?}
  PUT    /api/profiles/{id}                 rename + update lists
  DELETE /api/profiles/{id}                 delete profile (cannot delete last)
  POST   /api/profiles/{id}/activate        set active
  GET    /api/watchlist                     active profile's lists + globals (legacy)
  POST   /api/watchlist                     replace active profile's lists (legacy)
  GET    /api/dashboard                     signals batch (market, timeframe) for active profile
  GET    /api/asset/{market}/{symbol}/chart       candles + ticker
  POST   /api/asset/{market}/{symbol}/analyze     AI ensemble (records to signal history)
  GET    /api/asset/{market}/{symbol}/news        symbol-filtered news
  GET    /api/asset/{market}/{symbol}/track-record  win-rate stats
  GET    /api/news                          aggregated news (cache 5min)
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, Header, HTTPException, Query, Request
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field
from starlette.middleware.cors import CORSMiddleware

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

from ai_engine import ensemble_analyze  # noqa: E402
from indicators import compute_signal  # noqa: E402
from market_data import (  # noqa: E402
    CRYPTO_BINANCE_MAP,
    STOCK_YAHOO_MAP,
    TIMEFRAME_MAP,
    get_batch,
    get_crypto_snapshot,
    get_stock_snapshot,
)
from news_feed import get_news, get_news_for_symbol  # noqa: E402
from track_record import (  # noqa: E402
    get_track_record,
    get_track_record_summary,
    record_signal,
)
from subscription_service import (  # noqa: E402
    ENTITLED_STATUSES,
    verify_purchase,
)
from translator import translate_many  # noqa: E402
from unlock_codes import (  # noqa: E402
    DURATION_DAYS,
    DURATION_LABEL,
    delete_code,
    generate_code,
    list_codes,
    reset_device_binding,
    revoke_code,
    verify_code,
)

# v8.3.0 — Emergent-managed push notifications (Firebase relay).
# Registration endpoint + daily scheduler are wired further below.
from push_notifications import (  # noqa: E402
    RegisterPushBody,
    ensure_history_indexes,
    get_history,
    register_push_token,
    save_subscriber,
)
from push_scheduler import build_scheduler  # noqa: E402
from market_brief import (  # noqa: E402
    ensure_ttl_index as ensure_brief_ttl_index,
    generate_and_store_brief,
    get_latest_brief,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")
logger = logging.getLogger("aitrade")

# ---- Dashboard in-memory cache (TTL) ----
# Caches expensive batch snapshots (Binance & Yahoo Finance) and track-record summaries
# to avoid hammering upstream APIs on every dashboard refresh.
import asyncio  # noqa: E402

# v8.0.4: raised to 75s so the 60s dashboard refresh interval always
#         hits the cache.
# v8.0.5: raised to 300s (5 min) — users no longer wait on Yahoo, and
#         stale entries are served instantly while a background task
#         refreshes them (see `_get_snapshots_cached` below).
DASHBOARD_CACHE_TTL = float(os.environ.get("DASHBOARD_CACHE_TTL_SEC", "300"))
# Serve a stale cached response IMMEDIATELY if its age is below this
# hard ceiling. Beyond this, we block on a fresh fetch.
DASHBOARD_STALE_MAX = float(os.environ.get("DASHBOARD_STALE_MAX_SEC", "900"))

# v9.2.4 — Candle-boundary aware cache invalidation.
# BUG KONSISTENSI (laporan user): dashboard menyajikan sinyal dari snapshot
# cache hingga 5-15 menit, sementara halaman detail fetch segar. Tepat saat
# candle 1h TUTUP (mis. 09:00:00), detail langsung menghitung ulang dengan
# candle baru (SUI → HOLD) sedangkan dashboard masih menampilkan sinyal dari
# candle sebelumnya (SUI → LONG) hingga cache kedaluwarsa. Sinyal dihitung
# dari candle TUTUP (_drop_forming_candle), jadi cache WAJIB dibatalkan
# begitu candle baru terbentuk — bukan hanya berdasarkan umur TTL.
_TF_SECONDS: dict[str, int] = {
    "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "3h": 7200, "6h": 21600, "12h": 43200, "18h": 43200,
    "24h": 86400, "7d": 86400, "14d": 86400, "30d": 86400,
}


def _candle_boundary(timeframe: str, now: float | None = None) -> int:
    """Epoch detik dari awal candle timeframe yang sedang berjalan."""
    sec = _TF_SECONDS.get(timeframe, 3600)
    t = int(now if now is not None else time.time())
    return (t // sec) * sec


_snapshot_cache: dict[str, tuple[float, int, list[dict]]] = {}
_snapshot_locks: dict[str, asyncio.Lock] = {}
_snapshot_refresh_inflight: dict[str, bool] = {}
_tr_cache: dict[str, tuple[float, dict]] = {}
_tr_locks: dict[str, asyncio.Lock] = {}


def _cache_key_snap(market: str, symbols: list[str], timeframe: str) -> str:
    return f"{market}|{timeframe}|{','.join(symbols)}"


def _cache_key_tr(market: str, symbols: list[str]) -> str:
    return f"{market}|{','.join(sorted(symbols))}"


async def _get_snapshots_cached(market: str, symbols: list[str], timeframe: str) -> list[dict]:
    """Cached snapshot fetch with stale-while-revalidate semantics.

    Ladder:
      1. Cache fresh (< TTL) → return immediately.
      2. Cache stale but young (< STALE_MAX) → return stale immediately
         AND fire-and-forget a background refresh so the NEXT call sees
         fresh data. This is the key optimisation: users no longer wait
         on Yahoo/Binance.
      3. Cache absent or too old → block on a fresh fetch (same as before).
    """
    key = _cache_key_snap(market, symbols, timeframe)
    now = time.time()
    boundary = _candle_boundary(timeframe, now)
    hit = _snapshot_cache.get(key)
    if hit:
        age = now - hit[0]
        # v9.2.4 — Cache dari periode candle SEBELUMNYA tidak boleh disajikan
        # sama sekali: sinyal berubah saat candle tutup, dan menyajikan cache
        # lama adalah akar desync dashboard-vs-detail yang dilaporkan user.
        if hit[1] == boundary:
            if age < DASHBOARD_CACHE_TTL:
                return hit[2]
            if age < DASHBOARD_STALE_MAX:
                # Stale-while-revalidate (masih candle yang sama → aman).
                if not _snapshot_refresh_inflight.get(key):
                    _snapshot_refresh_inflight[key] = True
                    asyncio.create_task(_refresh_snapshot(key, market, symbols, timeframe))
                return hit[2]
        # Candle baru sudah mulai → paksa fetch segar (blokir sebentar)
        # agar dashboard & detail selalu menghitung dari candle yang sama.
    lock = _snapshot_locks.setdefault(key, asyncio.Lock())
    async with lock:
        hit = _snapshot_cache.get(key)
        if hit and hit[1] == boundary and time.time() - hit[0] < DASHBOARD_CACHE_TTL:
            return hit[2]
        data = await get_batch(market, symbols, timeframe)
        _snapshot_cache[key] = (time.time(), boundary, data)
        return data


async def _refresh_snapshot(key: str, market: str, symbols: list[str], timeframe: str) -> None:
    """Background snapshot refresh — writes result into the cache and
    releases the in-flight flag so a subsequent stale request can trigger
    another refresh."""
    try:
        data = await get_batch(market, symbols, timeframe)
        if data:
            _snapshot_cache[key] = (time.time(), _candle_boundary(timeframe), data)
    except Exception:
        # Swallow — the stale cache continues to serve requests.
        pass
    finally:
        _snapshot_refresh_inflight.pop(key, None)


async def _get_tr_summary_cached(market: str, symbols: list[str]) -> dict:
    key = _cache_key_tr(market, symbols)
    now = time.time()
    hit = _tr_cache.get(key)
    # Track record changes infrequently; cache twice as long.
    if hit and now - hit[0] < DASHBOARD_CACHE_TTL * 2:
        return hit[1]
    lock = _tr_locks.setdefault(key, asyncio.Lock())
    async with lock:
        hit = _tr_cache.get(key)
        if hit and time.time() - hit[0] < DASHBOARD_CACHE_TTL * 2:
            return hit[1]
        data = await get_track_record_summary(db, market, symbols)
        _tr_cache[key] = (time.time(), data)
        return data

mongo_url = os.environ["MONGO_URL"]
# Atlas-friendly connection: longer server-selection window, retry on transient errors.
client = AsyncIOMotorClient(
    mongo_url,
    serverSelectionTimeoutMS=20000,
    connectTimeoutMS=20000,
    socketTimeoutMS=30000,
    retryWrites=True,
    uuidRepresentation="standard",
)
db = client[os.environ["DB_NAME"]]

# Default lists — pulled from the full expanded maps in market_data.py so the
# dashboard "full=true" mode always returns every asset we support.
from market_data import (  # noqa: E402,F811
    CRYPTO_BINANCE_MAP,
    STOCK_YAHOO_MAP,
    ETF_YAHOO_MAP,
    STOCK_US_YAHOO_MAP,
    GOLD_SILVER_YAHOO_MAP,
    COMMODITY_YAHOO_MAP,
    FOREX_YAHOO_MAP,
)

# Top-N presets for FAST dashboard load. When ?full=true is passed, backend
# returns the whole map instead. Reduces initial fetch from 475 to ~200 assets.
_TOP_N = 50

# Per-market default asset counts (v7.0.3 — lightweight dashboard):
#   All markets capped at 50 for fast cold-start.
#   Search endpoint `/api/search` scans the FULL universe (not just these
#   50) so users can still find any symbol they type — even if it's not
#   shown on the dashboard.
DEFAULT_CRYPTO = list(CRYPTO_BINANCE_MAP.keys())[:50]
DEFAULT_STOCKS = list(STOCK_YAHOO_MAP.keys())[:50]
DEFAULT_ETF = list(ETF_YAHOO_MAP.keys())[:50]
DEFAULT_STOCK_US = list(STOCK_US_YAHOO_MAP.keys())[:50]
DEFAULT_GOLD_SILVER = list(GOLD_SILVER_YAHOO_MAP.keys())
DEFAULT_COMMODITY = list(COMMODITY_YAHOO_MAP.keys())
DEFAULT_FOREX = list(FOREX_YAHOO_MAP.keys())

# v8.1.3 — Pre-computed per-region symbol lists for World Stocks.
# When user taps a region chip on the dashboard, we fetch the first ~50
# stocks tagged with that region so the column shows meaningful data
# instead of just the first 50 alphabetical US symbols.
def _build_region_index() -> dict[str, list[str]]:
    from market_data import region_from_yahoo_ticker
    idx: dict[str, list[str]] = {}
    for sym, yahoo in STOCK_US_YAHOO_MAP.items():
        r = region_from_yahoo_ticker(yahoo)
        idx.setdefault(r, []).append(sym)
    return idx

STOCK_US_BY_REGION: dict[str, list[str]] = _build_region_index()

# Full lists — used when ?full=true is requested
FULL_CRYPTO = list(CRYPTO_BINANCE_MAP.keys())
FULL_STOCKS = list(STOCK_YAHOO_MAP.keys())
FULL_ETF = list(ETF_YAHOO_MAP.keys())
FULL_STOCK_US = list(STOCK_US_YAHOO_MAP.keys())
FULL_COMMODITY = list(COMMODITY_YAHOO_MAP.keys())
FULL_FOREX = list(FOREX_YAHOO_MAP.keys())

# Default seed profiles for new installs
DEFAULT_PROFILES = [
    {
        "_id": "spot",
        "name": "Spot Crypto",
        "crypto": ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOT", "LINK", "LTC", "BCH"],
        "stocks": [],
    },
    {
        "_id": "futures",
        "name": "Futures Crypto",
        "crypto": ["BTC", "ETH", "SOL", "HYPE", "DOGE", "PEPE", "ASTER", "SUI", "SHIB", "XRP", "ALGO", "SAND"],
        "stocks": [],
    },
    {
        "_id": "konservatif",
        "name": "Saham Konservatif",
        "crypto": ["BTC", "ETH", "XAUT", "USDT"],
        "stocks": ["BBCA", "BBRI", "BMRI", "ASII", "TPIA", "ANTM", "ADRO"],
    },
]
DEFAULT_ACTIVE_PROFILE = "spot"

TIMEFRAMES = ["15m", "30m", "1h", "3h", "6h", "12h", "18h", "24h"]

app = FastAPI(title="AITrade Pro")
api = APIRouter(prefix="/api")


# v8.12.47 — Lightweight health probe at root. Emergent's K8s ingress
# hits `GET /health` to verify readiness/liveness before routing traffic.
# Without this, the ingress considers the pod unhealthy and returns
# "Connection refused" upstream errors like the one seen in prod logs.
@app.get("/health")
def _root_health() -> dict[str, str]:
    return {"status": "ok"}


# --- App Version Enforcement (RELAXED) ---
# Old APKs (v2.0.x) do NOT call backend for auth (offline SHA-256), and current
# APK v2.1.2 does not yet send X-App-Version header. So we ONLY enforce when
# the header IS present but reports a version LOWER than MIN_APP_VERSION.
# Requests without header are passed through to keep v2.1.2 working. Old APKs
# are effectively neutralized because:
#   1. Their offline SHA-256 codes are absent from unlock_codes DB (migration)
#   2. Attempts to record login hit removed endpoint → auth stays invalid
from fastapi import Request  # noqa: E402,F811
from fastapi.responses import JSONResponse  # noqa: E402

MIN_APP_VERSION = (2, 1, 3)
_ENFORCED_PATH_PREFIXES = ("/api/dashboard", "/api/asset/", "/api/watchlist")


def _parse_version(v: str) -> tuple[int, int, int] | None:
    try:
        parts = v.strip().split(".")
        if len(parts) != 3:
            return None
        return int(parts[0]), int(parts[1]), int(parts[2])
    except Exception:
        return None


@app.middleware("http")
async def enforce_app_version(request: Request, call_next):
    path = request.url.path
    if not path.startswith(_ENFORCED_PATH_PREFIXES):
        return await call_next(request)
    v_header = request.headers.get("x-app-version") or ""
    # No header → pre-2.1.3 APK or web browser → pass through (relaxed)
    if not v_header:
        return await call_next(request)
    v = _parse_version(v_header)
    if v is not None and v < MIN_APP_VERSION:
        return JSONResponse(
            status_code=426,
            content={
                "error": "upgrade_required",
                "message": "Aplikasi CryptoStock Pro versi Anda sudah kadaluarsa. Silakan hubungi admin untuk mendapatkan APK versi terbaru.",
                "message_en": "Your CryptoStock Pro app is outdated. Please contact admin for the latest APK.",
                "min_version": ".".join(map(str, MIN_APP_VERSION)),
                "your_version": v_header,
            },
        )
    return await call_next(request)


# ---------------- Models ----------------

class WatchlistPayload(BaseModel):
    crypto: list[str] = Field(default_factory=list)
    stocks: list[str] = Field(default_factory=list)


class ProfileCreate(BaseModel):
    name: str
    crypto: list[str] = Field(default_factory=list)
    stocks: list[str] = Field(default_factory=list)


class ProfileUpdate(BaseModel):
    name: str | None = None
    crypto: list[str] | None = None
    stocks: list[str] | None = None


class Profile(BaseModel):
    id: str
    name: str
    crypto: list[str]
    stocks: list[str]


class ProfilesResponse(BaseModel):
    profiles: list[Profile]
    active_id: str
    available_crypto: list[str]
    available_stocks: list[str]
    timeframes: list[str]


class WatchlistResponse(BaseModel):
    crypto: list[str]
    stocks: list[str]
    available_crypto: list[str]
    available_stocks: list[str]
    timeframes: list[str]
    profile_id: str
    profile_name: str


class TrackRecordMini(BaseModel):
    wr_7d: float | None = None
    n_7d: int = 0
    wr_30d: float | None = None
    n_30d: int = 0


class AssetSignal(BaseModel):
    symbol: str
    market: str
    price: float | None = None
    change_pct_24h: float | None = None
    high_24h: float | None = None
    low_24h: float | None = None
    volume_24h: float | None = None
    spark: list[float] = Field(default_factory=list)
    action: str
    label: str
    confidence: int
    indicators: dict = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)
    entry: float | None = None
    # v8.1.9 — Entry ZONE (range) so the UI can display "$1915 - $1925"
    # instead of a single point. Both bounds derived from the deep tier
    # ± 0.4 ATR band.
    entry_low: float | None = None
    entry_high: float | None = None
    # v8.1.6 — Alternate entry cycles for the "Entry Levels" card.
    # `entry` (deep) is the safest default; moderate/aggressive give
    # users nearer-price options if they don't want to wait.
    entry_moderate: float | None = None
    entry_aggressive: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    # v9.2.0 — Ladder TP lengkap untuk kartu AI Suggestions.
    take_profit_2: float | None = None
    take_profit_3: float | None = None
    track_record: TrackRecordMini = Field(default_factory=TrackRecordMini)
    is_premium: bool = False
    # v8.1.3 — Region key for World Stocks filter
    region: str | None = None
    # v8.2.2 — Risk/Reward metrics for badge display next to Target Profit.
    # risk_reward: numeric ratio (reward / risk). risk_level: Low/Medium/High.
    risk_reward: float | None = None
    risk_level: str | None = None
    reward_pct: float | None = None
    risk_pct: float | None = None


class DashboardResponse(BaseModel):
    market: str
    timeframe: str
    server_time: str
    assets: list[AssetSignal]
    profile_id: str
    profile_name: str
    premium_count: int = 0
    premium_threshold: dict = Field(default_factory=dict)


class ChartResponse(BaseModel):
    symbol: str
    market: str
    timeframe: str
    ticker: dict
    candles: list[dict]
    signal: dict


class AnalyzeResponse(BaseModel):
    symbol: str
    market: str
    timeframe: str
    price: float | None
    technical: dict
    consensus: dict
    models: list[dict]
    news_used: list[dict] = Field(default_factory=list)
    generated_at: str


class NewsItem(BaseModel):
    source: str
    title: str
    url: str | None = None
    summary: str | None = None
    published: str | None = None
    image: str | None = None


class NewsResponse(BaseModel):
    market: str
    items: list[NewsItem]
    fetched_at: str


# ---------------- Auth tracking ----------------

class LoginRecordPayload(BaseModel):
    email: str
    code: str


class LoggedUser(BaseModel):
    email: str
    unlocked_at: str
    last_seen: str
    login_count: int
    device_id: str | None = None
    device_name: str | None = None
    duration: str | None = None
    expires_at: str | None = None


class LoggedUsersResponse(BaseModel):
    total: int
    users: list[LoggedUser]


def _compute_unlock_code(email: str) -> str:
    import hashlib
    secret = os.environ.get("UNLOCK_SECRET", "")
    normalized = email.strip().lower()
    msg = f"{secret}::{normalized}"
    h = hashlib.sha256(msg.encode()).hexdigest()[:12].upper()
    return f"{h[0:4]}-{h[4:8]}-{h[8:12]}"


# ---------------- Helpers ----------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _ensure_seed() -> None:
    """Seed default profiles + state on first launch.

    Called lazily from `_get_active_profile()` so a slow / unavailable
    database does NOT block app startup (important for serverless /
    Atlas deployments where the first connection may be slow).

    Uses upsert by _id so defaults remain stable.
    """
    try:
        has_any = await db.profiles.count_documents({})
    except Exception as e:
        logger.warning("Mongo not reachable for seed yet: %s", e)
        return
    if not has_any:
        for p in DEFAULT_PROFILES:
            try:
                await db.profiles.update_one(
                    {"_id": p["_id"]},
                    {"$setOnInsert": {**p, "created_at": _now_iso()}},
                    upsert=True,
                )
            except Exception as e:
                logger.warning("Seed profile %s failed: %s", p["_id"], e)
    try:
        state = await db.app_state.find_one({"_id": "active"})
        if not state:
            await db.app_state.replace_one(
                {"_id": "active"},
                {"_id": "active", "profile_id": DEFAULT_ACTIVE_PROFILE},
                upsert=True,
            )
    except Exception as e:
        logger.warning("Seed active state failed: %s", e)


async def _get_active_profile() -> dict:
    await _ensure_seed()
    state = await db.app_state.find_one({"_id": "active"}, {"_id": 0, "profile_id": 1})
    pid = (state or {}).get("profile_id") or DEFAULT_ACTIVE_PROFILE
    prof = await db.profiles.find_one({"_id": pid}, {"_id": 1, "name": 1, "crypto": 1, "stocks": 1})
    if not prof:
        # fallback to any profile
        prof = await db.profiles.find_one({}, {"_id": 1, "name": 1, "crypto": 1, "stocks": 1})
        if prof:
            await db.app_state.replace_one({"_id": "active"}, {"_id": "active", "profile_id": prof["_id"]}, upsert=True)
    if not prof:
        # Shouldn't happen after seed, but be safe
        return {"_id": "default", "name": "Default", "crypto": DEFAULT_CRYPTO.copy(), "stocks": DEFAULT_STOCKS.copy()}
    return prof


def _filter_lists(crypto: list[str], stocks: list[str]) -> tuple[list[str], list[str]]:
    c = [s.upper() for s in (crypto or []) if s.upper() in CRYPTO_BINANCE_MAP]
    s = [t.upper() for t in (stocks or []) if t.upper() in STOCK_YAHOO_MAP]
    return c, s


# v9.2.0 — Cache candle HARIAN (TTL 4 jam) untuk Macro Bias 50 SMA,
# Liquidity Zones & Choke Risk Protection pada mesin VWAP (scalper/day/
# swing). Data harian hanya berubah sekali sehari → cache panjang aman
# dan menjaga dashboard batch tetap cepat.
_DAILY_CACHE: dict[str, tuple[float, list]] = {}
_DAILY_CACHE_TTL = 4 * 3600.0


async def _get_daily_candles(market: str, symbol: str) -> list[dict] | None:
    key = f"{market}|{symbol.upper()}"
    hit = _DAILY_CACHE.get(key)
    if hit and (time.time() - hit[0]) < _DAILY_CACHE_TTL:
        return hit[1]
    try:
        if market == "crypto":
            snap = await get_crypto_snapshot(symbol, "24h")
        else:
            eff = "stock_us" if market == "world_stocks" else market
            snap = await get_stock_snapshot(symbol, "24h", market=eff)
        candles = (snap or {}).get("candles") or []
        _DAILY_CACHE[key] = (time.time(), candles)
        return candles
    except Exception:
        return None


def _build_signal(snapshot: dict, tr: dict | None = None, *, min_conf: int = 85, min_wr: float = 70.0, profile: str | None = None, daily_candles: list | None = None, timeframe: str | None = None) -> AssetSignal:
    market = snapshot["market"]
    candles = snapshot.get("candles", [])
    ticker = snapshot.get("ticker", {}) or {}
    # v9.0.0 — Pass the caller's trader profile so the dashboard computes
    # the SAME signal the detail page shows (single source of truth).
    # v9.1.4 — Anchor level ke harga live ticker (arah tetap candle tutup).
    sig = compute_signal(
        candles, market, profile=profile, live_price=ticker.get("price"),
        daily_candles=daily_candles, timeframe=timeframe,
    )
    spark = [c["close"] for c in candles[-30:]] if candles else []
    tr_mini = TrackRecordMini(**(tr or {}))
    wr = tr_mini.wr_30d
    action_ok = sig["action"] != "HOLD"
    conf_ok = sig["confidence"] >= min_conf
    # v8.7.0 — Restored strict Premium gate (target WR > 70%).
    # Old v8.0.9 logic let signals without a WR sample slip into Premium
    # via `is_premium = action_ok and conf_ok` (WR=None fallback) — this
    # caused the 50% WR degradation. New rule:
    #   • If we have a WR sample → require conf_ok AND wr >= min_wr AND
    #     confidence >= min_conf.
    #   • If we DO NOT have a WR sample → require confidence >= min_conf + 5
    #     (stricter bar to compensate for the unknown WR).
    if wr is None:
        # v9.1.2 — Aset tanpa histori: bar +3 (bukan +5). Bar lama (90-95)
        # praktis tak terjangkau confidence jujur v9 (cap 95, sinyal kuat
        # umumnya 85-90) → kolom premium kosong total.
        is_premium = action_ok and sig["confidence"] >= (min_conf + 3)
    else:
        is_premium = action_ok and conf_ok and wr >= min_wr
    # v8.1.3 — Attach region (japan/china/us/etc.) for World Stocks
    # filter chips on the dashboard.
    from market_data import region_for_symbol
    region = region_for_symbol(market, snapshot["symbol"])

    # v8.2.2 — Compute Risk/Reward + risk level for badge display.
    risk_reward: float | None = None
    risk_level: str | None = None
    reward_pct: float | None = None
    risk_pct: float | None = None
    entry_v = sig.get("entry")
    sl_v = sig.get("stop_loss")
    tp_v = sig.get("take_profit")
    if entry_v and sl_v and tp_v and sig["action"] in ("BUY", "SELL"):
        reward = abs(tp_v - entry_v)
        risk = abs(entry_v - sl_v)
        if risk > 0 and entry_v > 0:
            risk_reward = round(reward / risk, 2)
            reward_pct = round((reward / entry_v) * 100, 2)
            risk_pct = round((risk / entry_v) * 100, 2)
            # Categorize based on confidence + R:R ratio.
            conf = sig.get("confidence") or 0
            if conf >= 85 and risk_reward >= 2.0:
                risk_level = "Low"
            elif conf >= 70 and risk_reward >= 1.0:
                risk_level = "Medium"
            else:
                risk_level = "High"
    elif sig["action"] == "HOLD" and entry_v and sl_v and tp_v:
        # HOLD: show volatility range as a neutral badge (Medium by default)
        reward = abs(tp_v - entry_v)
        risk = abs(entry_v - sl_v)
        if risk > 0 and entry_v > 0:
            risk_reward = round(reward / risk, 2)
            reward_pct = round((reward / entry_v) * 100, 2)
            risk_pct = round((risk / entry_v) * 100, 2)
            risk_level = "Medium"

    return AssetSignal(
        symbol=snapshot["symbol"],
        market=market,
        price=ticker.get("price"),
        change_pct_24h=ticker.get("change_pct_24h"),
        high_24h=ticker.get("high_24h"),
        low_24h=ticker.get("low_24h"),
        volume_24h=ticker.get("volume_24h"),
        spark=spark,
        action=sig["action"],
        label=sig["label"],
        confidence=sig["confidence"],
        indicators=sig["indicators"],
        reasons=sig["reasons"],
        entry=sig["entry"],
        entry_low=sig.get("entry_low"),
        entry_high=sig.get("entry_high"),
        entry_moderate=sig.get("entry_moderate"),
        entry_aggressive=sig.get("entry_aggressive"),
        stop_loss=sig["stop_loss"],
        take_profit=sig["take_profit"],
        take_profit_2=sig.get("take_profit_2"),
        take_profit_3=sig.get("take_profit_3"),
        track_record=tr_mini,
        is_premium=is_premium,
        region=region,
        risk_reward=risk_reward,
        risk_level=risk_level,
        reward_pct=reward_pct,
        risk_pct=risk_pct,
    )


# v9.2.0 — AI Suggestions: daftar aset dengan sinyal AKTIF (BUY/SELL)
# terkuat per kategori market, lengkap dengan Entry/SL/TP1-3. Fitur ini
# PREMIUM-ONLY — divalidasi lewat entitlement device_id di MongoDB.
@api.get("/ai-suggestions")
async def ai_suggestions(
    market: Literal["crypto", "stock_id", "stock_us", "world_stocks", "gold_silver", "commodity", "forex", "etf"] = Query("crypto"),
    timeframe: str = Query("1h"),
    profile: str | None = Query(None),
    device_id: str | None = Query(None),
    limit: int = Query(10, ge=1, le=25),
) -> dict[str, Any]:
    if timeframe not in TIMEFRAME_MAP:
        raise HTTPException(400, f"Invalid timeframe. Use one of {TIMEFRAMES}")

    # ---- Premium gate: subscription Play Billing ATAU unlock code admin ----
    entitled = False
    if device_id:
        row = await db.subscriptions.find_one(
            {"device_id": device_id},
            sort=[("updated_at", -1)],
        )
        if row:
            entitled = row.get("status", "invalid") in ENTITLED_STATUSES
            expiry_iso = row.get("expiry_time")
            if entitled and expiry_iso:
                try:
                    if datetime.fromisoformat(expiry_iso.replace("Z", "+00:00")) <= datetime.now(timezone.utc):
                        entitled = False
                except Exception:
                    pass
        # v9.2.0 — User yang di-unlock admin via kode juga premium.
        if not entitled:
            uc = await db.unlock_codes.find_one({"device_id": device_id})
            if uc and not uc.get("revoked", False):
                exp_iso = uc.get("expires_at")  # None = lifetime
                if not exp_iso:
                    entitled = True
                else:
                    try:
                        entitled = datetime.fromisoformat(exp_iso.replace("Z", "+00:00")) > datetime.now(timezone.utc)
                    except Exception:
                        entitled = False
    if not entitled:
        raise HTTPException(403, "premium_required")

    min_conf, min_wr = _threshold_for_market(market)
    resp = await _build_dashboard_response(
        market=market,
        timeframe=timeframe,
        sort="confidence",
        premium_only=False,
        min_confidence=min_conf,
        min_wr=min_wr,
        # v9.2.1 — full=True: pindai SELURuh universe terkurasi (mis.
        # stock_us 787 ticker, bukan 50 mega-cap saja) agar kategori
        # World Stocks tidak kosong saat mesin VWAP profil aktif.
        full=True,
        profile=profile,
    )
    active = [a for a in resp.assets if a.action in ("BUY", "SELL")]
    active.sort(key=lambda a: -a.confidence)
    picks = active[:limit]

    engine = (
        {"scalper": "VWAP-SCALPER", "day": "VWAP-INTRADAY", "swing": "VWAP-SWING"}.get(profile or "", "CONFLUENCE")
        if profile else "CONFLUENCE"
    )
    return {
        "market": market,
        "timeframe": timeframe,
        "profile": profile,
        "engine": engine,
        "count": len(picks),
        "suggestions": [a.model_dump() for a in picks],
        "server_time": _now_iso(),
    }


def _profile_to_model(p: dict) -> Profile:
    return Profile(id=p["_id"], name=p.get("name", "Untitled"), crypto=p.get("crypto", []), stocks=p.get("stocks", []))


# ---------------- Routes ----------------

@api.get("/")
async def health() -> dict:
    return {"app": "AITrade Pro", "status": "ok", "time": _now_iso()}


# -------- Profiles --------

@api.get("/profiles", response_model=ProfilesResponse)
async def list_profiles() -> ProfilesResponse:
    await _ensure_seed()
    cursor = db.profiles.find({}, {"_id": 1, "name": 1, "crypto": 1, "stocks": 1})
    profiles = [_profile_to_model(p) async for p in cursor]
    state = await db.app_state.find_one({"_id": "active"}, {"_id": 0, "profile_id": 1})
    active_id = (state or {}).get("profile_id") or (profiles[0].id if profiles else "")
    return ProfilesResponse(
        profiles=profiles,
        active_id=active_id,
        available_crypto=list(CRYPTO_BINANCE_MAP.keys()),
        available_stocks=list(STOCK_YAHOO_MAP.keys()),
        timeframes=TIMEFRAMES,
    )


@api.post("/profiles", response_model=Profile)
async def create_profile(payload: ProfileCreate) -> Profile:
    name = payload.name.strip() or "Profil Baru"
    crypto, stocks = _filter_lists(payload.crypto, payload.stocks)
    pid = str(uuid.uuid4())[:8]
    doc = {"_id": pid, "name": name, "crypto": crypto, "stocks": stocks, "created_at": _now_iso()}
    await db.profiles.insert_one(doc)
    return _profile_to_model(doc)


@api.put("/profiles/{profile_id}", response_model=Profile)
async def update_profile(profile_id: str, payload: ProfileUpdate) -> Profile:
    current = await db.profiles.find_one({"_id": profile_id})
    if not current:
        raise HTTPException(404, "Profile not found")
    update: dict = {}
    if payload.name is not None:
        update["name"] = payload.name.strip() or current.get("name", "Untitled")
    if payload.crypto is not None or payload.stocks is not None:
        c = payload.crypto if payload.crypto is not None else current.get("crypto", [])
        s = payload.stocks if payload.stocks is not None else current.get("stocks", [])
        c, s = _filter_lists(c, s)
        update["crypto"] = c
        update["stocks"] = s
    if update:
        await db.profiles.update_one({"_id": profile_id}, {"$set": update})
    doc = await db.profiles.find_one({"_id": profile_id}, {"_id": 1, "name": 1, "crypto": 1, "stocks": 1})
    return _profile_to_model(doc or current)


@api.delete("/profiles/{profile_id}")
async def delete_profile(profile_id: str) -> dict:
    total = await db.profiles.count_documents({})
    if total <= 1:
        raise HTTPException(400, "Tidak bisa menghapus profil terakhir")
    res = await db.profiles.delete_one({"_id": profile_id})
    if res.deleted_count == 0:
        raise HTTPException(404, "Profile not found")
    state = await db.app_state.find_one({"_id": "active"}, {"_id": 0, "profile_id": 1})
    if (state or {}).get("profile_id") == profile_id:
        fallback = await db.profiles.find_one({}, {"_id": 1})
        if fallback:
            await db.app_state.replace_one(
                {"_id": "active"}, {"_id": "active", "profile_id": fallback["_id"]}, upsert=True,
            )
    return {"ok": True, "deleted": profile_id}


@api.post("/profiles/{profile_id}/activate")
async def activate_profile(profile_id: str) -> dict:
    doc = await db.profiles.find_one({"_id": profile_id}, {"_id": 1})
    if not doc:
        raise HTTPException(404, "Profile not found")
    await db.app_state.replace_one(
        {"_id": "active"}, {"_id": "active", "profile_id": profile_id}, upsert=True,
    )
    return {"ok": True, "active_id": profile_id}


# -------- Watchlist (legacy, routes to active profile) --------

@api.get("/watchlist", response_model=WatchlistResponse)
async def get_watchlist() -> WatchlistResponse:
    prof = await _get_active_profile()
    return WatchlistResponse(
        crypto=prof.get("crypto", []),
        stocks=prof.get("stocks", []),
        available_crypto=list(CRYPTO_BINANCE_MAP.keys()),
        available_stocks=list(STOCK_YAHOO_MAP.keys()),
        timeframes=TIMEFRAMES,
        profile_id=prof["_id"],
        profile_name=prof.get("name", "Default"),
    )


@api.post("/watchlist", response_model=WatchlistResponse)
async def update_watchlist(payload: WatchlistPayload) -> WatchlistResponse:
    prof = await _get_active_profile()
    crypto, stocks = _filter_lists(payload.crypto, payload.stocks)
    await db.profiles.update_one(
        {"_id": prof["_id"]},
        {"$set": {"crypto": crypto, "stocks": stocks, "updated_at": _now_iso()}},
    )
    return WatchlistResponse(
        crypto=crypto,
        stocks=stocks,
        available_crypto=list(CRYPTO_BINANCE_MAP.keys()),
        available_stocks=list(STOCK_YAHOO_MAP.keys()),
        timeframes=TIMEFRAMES,
        profile_id=prof["_id"],
        profile_name=prof.get("name", "Default"),
    )


# -------- Dashboard --------

# v8.7.2 — Adaptive premium thresholds per market.
# Rationale: different markets have different noise/volatility profiles.
# The one-size-fits-all 85/70 was too permissive for macro-heavy markets
# (forex/commodity/gold), so we raise the bar there. Callers can still
# override via query params (?min_confidence=&min_wr=).
_MARKET_THRESHOLDS: dict[str, tuple[int, float]] = {
    # market key            (min_conf, min_wr)
    # v9.1.2 — Rekalibrasi ke performa backtest v9 yang JUJUR (WR 55-57%).
    # Gate lama (WR>=72-75%) dikalibrasi untuk formula v1 dan praktis
    # mustahil dicapai → badge premium hilang total. Bar untuk aset tanpa
    # histori juga diturunkan dari +5 ke +3 (lihat _build_signal).
    "crypto":               (85, 55.0),
    "stock_id":             (85, 55.0),
    "stock_us":             (85, 55.0),
    "world_stocks":         (85, 55.0),
    "etf":                  (85, 55.0),
    "gold_silver":          (87, 55.0),
    "commodity":            (87, 55.0),
    "forex":                (85, 55.0),
}


def _threshold_for_market(market: str) -> tuple[int, float]:
    """Return (min_conf, min_wr) tuned for the given market."""
    eff = "stock_id" if market == "stock" else market
    return _MARKET_THRESHOLDS.get(eff, (87, 72.0))


@api.get("/dashboard", response_model=DashboardResponse)
async def dashboard(
    market: Literal["crypto", "stock", "etf", "stock_id", "stock_us", "world_stocks", "gold_silver", "commodity", "forex"] = Query("crypto"),
    timeframe: str = Query("1h"),
    sort: Literal["default", "premium", "confidence", "wr"] = Query("default"),
    premium_only: bool = Query(False),
    min_confidence: int | None = Query(None, ge=0, le=100, description="Override premium threshold (default: adaptive per market)"),
    min_wr: float | None = Query(None, ge=0.0, le=100.0, description="Override WR threshold"),
    full: bool = Query(False),
    region: str | None = Query(None, description="Optional region filter for World Stocks"),
    profile: str | None = Query(None, description="Trader profile (scalper/day/swing/longterm) — keeps dashboard signals identical to the detail page"),
) -> DashboardResponse:
    if timeframe not in TIMEFRAME_MAP:
        raise HTTPException(400, f"Invalid timeframe. Use one of {TIMEFRAMES}")
    default_conf, default_wr = _threshold_for_market(market)
    return await _build_dashboard_response(
        market=market,
        timeframe=timeframe,
        sort=sort,
        premium_only=premium_only,
        min_confidence=min_confidence if min_confidence is not None else default_conf,
        min_wr=min_wr if min_wr is not None else default_wr,
        full=full,
        region=region,
        profile=profile,
    )


async def _build_dashboard_response(
    *,
    market: str,
    timeframe: str,
    sort: str = "default",
    premium_only: bool = False,
    min_confidence: int = 85,
    min_wr: float = 70.0,
    full: bool = False,
    region: str | None = None,
    extras: list[str] | None = None,
    profile: str | None = None,
) -> DashboardResponse:
    # Backward-compat: "stock" -> "stock_id", "world_stocks" -> "stock_us" internally
    eff_market = "stock_id" if market == "stock" else market
    if eff_market == "world_stocks":
        eff_market = "stock_us"

    prof = await _get_active_profile()
    # v8.1.3 — Region-aware picking for stock_us. `region=japan` returns
    # the top-50 tickers tagged as japan; `region=all` or None falls back
    # to the default (first-50 US insertion order).
    if eff_market == "stock_us" and region and region != "all":
        region_syms = STOCK_US_BY_REGION.get(region.lower(), [])
        symbols = region_syms[:50] if not full else region_syms
        profile_id = f"region-{region}"
        profile_name = f"Region: {region.title()}"
    elif full:
        symbols = {
            "crypto": FULL_CRYPTO,
            "stock_id": FULL_STOCKS,
            "etf": FULL_ETF,
            "stock_us": FULL_STOCK_US,
            "gold_silver": DEFAULT_GOLD_SILVER,
            "commodity": FULL_COMMODITY,
            "forex": FULL_FOREX,
        }.get(eff_market, [])
        profile_name = "Semua Aset"
        profile_id = "all"
    else:
        symbols = {
            "crypto": DEFAULT_CRYPTO,
            "stock_id": DEFAULT_STOCKS,
            "etf": DEFAULT_ETF,
            "stock_us": DEFAULT_STOCK_US,
            "gold_silver": DEFAULT_GOLD_SILVER,
            "commodity": DEFAULT_COMMODITY,
            "forex": DEFAULT_FOREX,
        }.get(eff_market, [])
        profile_id = prof["_id"]
        profile_name = prof.get("name", "Default")
    # v8.12.18 — Merge in `extras` (watchlist symbols beyond the default
    # top-50 slice) so favourites like BBCA, BBRI, etc. show up in the
    # dashboard payload and the frontend Watchlist column can resolve
    # them. We look them up against the FULL universe for this market
    # (defence in depth: silently drop anything unknown).
    if extras and not full:
        full_universe = {
            "crypto": FULL_CRYPTO,
            "stock_id": FULL_STOCKS,
            "etf": FULL_ETF,
            "stock_us": FULL_STOCK_US,
            "gold_silver": DEFAULT_GOLD_SILVER,
            "commodity": DEFAULT_COMMODITY,
            "forex": DEFAULT_FOREX,
        }.get(eff_market, [])
        allowed = {s.upper() for s in full_universe}
        seen = {s.upper() for s in symbols}
        for e in extras:
            eu = e.upper()
            if eu in allowed and eu not in seen:
                symbols = [*symbols, eu]
                seen.add(eu)
    if not symbols:
        return DashboardResponse(
            market=market, timeframe=timeframe, server_time=_now_iso(), assets=[],
            profile_id=profile_id, profile_name=profile_name,
            premium_count=0,
            premium_threshold={"min_confidence": min_confidence, "min_wr": min_wr},
        )

    snapshots = await _get_snapshots_cached(eff_market, symbols, timeframe)
    tr_summary = await _get_tr_summary_cached(eff_market, symbols)
    by_sym = {s["symbol"]: s for s in snapshots}
    ordered = [by_sym[s] for s in symbols if s in by_sym]

    # v9.2.0 — Macro Bias 50 SMA harian untuk mesin VWAP (scalper/day/
    # swing). Fetch candle harian paralel (cache 4 jam per simbol).
    daily_map: dict[str, list] = {}
    if profile in ("scalper", "day", "swing"):
        daily_list = await asyncio.gather(
            *(_get_daily_candles(eff_market, s["symbol"]) for s in ordered),
            return_exceptions=True,
        )
        daily_map = {
            s["symbol"]: d
            for s, d in zip(ordered, daily_list)
            if isinstance(d, list) and d
        }

    assets = [
        _build_signal(
            s, tr_summary.get(s["symbol"]),
            min_conf=min_confidence, min_wr=min_wr, profile=profile,
            daily_candles=daily_map.get(s["symbol"]), timeframe=timeframe,
        )
        for s in ordered
    ]

    if premium_only:
        assets = [a for a in assets if a.is_premium]

    if sort == "premium":
        assets.sort(key=lambda a: (not a.is_premium, -a.confidence))
    elif sort == "confidence":
        assets.sort(key=lambda a: -a.confidence)
    elif sort == "wr":
        assets.sort(key=lambda a: -(a.track_record.wr_30d or -1))

    premium_count = sum(1 for a in assets if a.is_premium)

    return DashboardResponse(
        market=market, timeframe=timeframe, server_time=_now_iso(),
        assets=assets,
        profile_id=profile_id, profile_name=profile_name,
        premium_count=premium_count,
        premium_threshold={"min_confidence": min_confidence, "min_wr": min_wr},
    )


# v8.0.4 — Batch dashboard endpoint. Frontend used to fire 8 parallel
# HTTP requests on cold start; even though each is cheap on the server
# they cost ~50ms round-trip on real networks and force React to
# schedule 8 setState updates. `/api/dashboard/batch?markets=a,b,c`
# returns them all inside a single response so the client can perform
# ONE state update.
@api.get("/dashboard/batch")
async def dashboard_batch(
    markets: str = Query("crypto,stock_us,etf,stock_id,gold_silver,commodity,forex"),
    timeframe: str = Query("1h"),
    sort: Literal["default", "premium", "confidence", "wr"] = Query("premium"),
    full: bool = Query(False),
    min_confidence: int | None = Query(None, ge=0, le=100, description="Override (default: adaptive per market)"),
    min_wr: float | None = Query(None, ge=0.0, le=100.0),
    region: str | None = Query(None, description="Regional filter applied to stock_us only"),
    extras: str | None = Query(None, description="Extra symbols to include, format: market:SYMBOL,market:SYMBOL"),
    profile: str | None = Query(None, description="Trader profile (scalper/day/swing/longterm) — keeps batch signals identical to the detail page"),
) -> dict[str, Any]:
    if timeframe not in TIMEFRAME_MAP:
        raise HTTPException(400, f"Invalid timeframe. Use one of {TIMEFRAMES}")
    market_keys = [m.strip() for m in markets.split(",") if m.strip()]
    if not market_keys:
        raise HTTPException(400, "markets query must be non-empty")
    known = {"crypto", "stock", "stock_id", "stock_us", "world_stocks",
             "etf", "gold_silver", "commodity", "forex"}
    market_keys = [m for m in market_keys if m in known][:9]

    # v8.12.18 — Parse extras "market:SYMBOL" pairs into per-market list.
    # Ensures watchlist favourites beyond the default top-50 slice
    # (e.g. BBCA in stock_id) are included in the response.
    extras_by_market: dict[str, list[str]] = {}
    if extras:
        for pair in extras.split(","):
            pair = pair.strip()
            if not pair or ":" not in pair:
                continue
            mk, _, sym = pair.partition(":")
            mk = mk.strip().lower()
            sym = sym.strip().upper()
            if not mk or not sym:
                continue
            # Map legacy alias same way as the builder does.
            eff = "stock_id" if mk == "stock" else ("stock_us" if mk == "world_stocks" else mk)
            extras_by_market.setdefault(eff, []).append(sym)

    def _cfg(m: str) -> tuple[int, float]:
        d_conf, d_wr = _threshold_for_market(m)
        return (
            min_confidence if min_confidence is not None else d_conf,
            min_wr if min_wr is not None else d_wr,
        )

    tasks = []
    for m in market_keys:
        c, w = _cfg(m)
        eff_m = "stock_id" if m == "stock" else ("stock_us" if m == "world_stocks" else m)
        tasks.append(
            _build_dashboard_response(
                market=m,
                timeframe=timeframe,
                sort=sort,
                full=full,
                min_confidence=c,
                min_wr=w,
                # v8.1.3 — Only apply region to stock_us; other markets ignore it.
                region=region if m in ("stock_us", "world_stocks") else None,
                extras=extras_by_market.get(eff_m),
                # v9.0.0 — Trader profile so batch signals match detail page.
                profile=profile,
            )
        )
    results = await asyncio.gather(*tasks, return_exceptions=True)
    out: dict[str, Any] = {}
    for m, r in zip(market_keys, results, strict=False):
        if isinstance(r, Exception):
            out[m] = {"error": str(r)[:200], "assets": [], "premium_count": 0}
        else:
            out[m] = r.model_dump()
    return {"timeframe": timeframe, "markets": out, "server_time": _now_iso()}


# -------- Asset detail --------

@api.get("/asset/{market}/{symbol}/chart", response_model=ChartResponse)
async def asset_chart(
    market: Literal["crypto", "stock", "etf", "stock_id", "stock_us", "world_stocks", "gold_silver", "commodity", "forex"],
    symbol: str,
    timeframe: str = "1h",
    profile: str | None = None,
) -> ChartResponse:
    if timeframe not in TIMEFRAME_MAP:
        raise HTTPException(400, "Invalid timeframe")
    eff_market = "stock_id" if market == "stock" else market
    if eff_market == "world_stocks":
        eff_market = "stock_us"
    # v7.0.5: URL-safe dash decoder — forex/gold-silver symbols contain
    # "/" (EUR/USD, XAU/USD) which breaks path routing. Frontend pushes
    # them as "EUR-USD"; convert back here before pool lookup.
    if eff_market in ("forex", "gold_silver") and "-" in symbol:
        symbol = symbol.replace("-", "/")
    symbol = symbol.upper()
    snap = await (
        get_crypto_snapshot(symbol, timeframe)
        if eff_market == "crypto"
        else get_stock_snapshot(symbol, timeframe, market=eff_market)
    )
    if not snap:
        raise HTTPException(404, "Symbol not found or upstream data unavailable")
    # v8.12.57 — Pass trader profile so v3 formula tunes EMA / RSI /
    # confidence gate per user preference (crypto / forex / gold only).
    # v9.2.0 — Sertakan candle harian (bias 50 SMA) untuk mesin VWAP.
    _daily = None
    if profile in ("scalper", "day", "swing"):
        _daily = await _get_daily_candles(eff_market, symbol)
    sig = compute_signal(
        snap.get("candles", []), eff_market, profile=profile,
        live_price=(snap.get("ticker", {}) or {}).get("price"),
        daily_candles=_daily, timeframe=timeframe,
    )
    # v8.2.2 — Enrich raw signal with risk/reward metrics so the detail
    # page header renders the Risk badge. `compute_signal` returns a
    # plain dict and doesn't go through `_build_signal`, so we compute
    # R:R inline here (mirrors the logic in _build_signal).
    _entry_v = sig.get("entry")
    _sl_v = sig.get("stop_loss")
    _tp_v = sig.get("take_profit")
    if _entry_v and _sl_v and _tp_v and _entry_v > 0:
        _reward = abs(_tp_v - _entry_v)
        _risk = abs(_entry_v - _sl_v)
        if _risk > 0:
            _rr = round(_reward / _risk, 2)
            sig["risk_reward"] = _rr
            sig["reward_pct"] = round((_reward / _entry_v) * 100, 2)
            sig["risk_pct"] = round((_risk / _entry_v) * 100, 2)
            _conf = sig.get("confidence") or 0
            _act = sig.get("action", "HOLD")
            if _act == "HOLD":
                sig["risk_level"] = "Medium"
            elif _conf >= 85 and _rr >= 2.0:
                sig["risk_level"] = "Low"
            elif _conf >= 70 and _rr >= 1.0:
                sig["risk_level"] = "Medium"
            else:
                sig["risk_level"] = "High"
    return ChartResponse(
        symbol=symbol, market=eff_market, timeframe=timeframe,
        ticker=snap.get("ticker", {}) or {},
        candles=snap.get("candles", []),
        signal=sig,
    )


@api.post("/asset/{market}/{symbol}/analyze", response_model=AnalyzeResponse)
async def asset_analyze(
    market: Literal["crypto", "stock", "etf", "stock_id", "stock_us", "world_stocks", "gold_silver", "commodity", "forex"],
    symbol: str,
    timeframe: str = "1h",
    lang: Literal["id", "en", "ru", "cn"] = "en",
    profile: str | None = None,
) -> AnalyzeResponse:
    if timeframe not in TIMEFRAME_MAP:
        raise HTTPException(400, "Invalid timeframe")
    eff_market = "stock_id" if market == "stock" else market
    if eff_market == "world_stocks":
        eff_market = "stock_us"
    # v7.0.5: URL-safe dash decoder — forex/gold-silver symbols contain
    # "/" (EUR/USD, XAU/USD) which breaks path routing. Frontend pushes
    # them as "EUR-USD"; convert back here before pool lookup.
    if eff_market in ("forex", "gold_silver") and "-" in symbol:
        symbol = symbol.replace("-", "/")
    symbol = symbol.upper()
    snap = await (
        get_crypto_snapshot(symbol, timeframe)
        if eff_market == "crypto"
        else get_stock_snapshot(symbol, timeframe, market=eff_market)
    )
    if not snap:
        raise HTTPException(404, "Symbol not found or upstream data unavailable")
    candles = snap.get("candles", [])
    ticker = snap.get("ticker", {}) or {}
    price = ticker.get("price") or (candles[-1]["close"] if candles else None)
    _daily_a = None
    if profile in ("scalper", "day", "swing"):
        _daily_a = await _get_daily_candles(eff_market, symbol)
    technical = compute_signal(
        candles, eff_market, profile=profile, live_price=price,
        daily_candles=_daily_a, timeframe=timeframe,
    )
    if price is None:
        raise HTTPException(503, "Price unavailable")
    news = await get_news_for_symbol(symbol, eff_market, limit=8)
    result = await ensemble_analyze(symbol, eff_market, timeframe, technical, float(price), news=news, lang=lang)
    consensus = result["consensus"]

    # Record signal into history for backtesting
    try:
        prof = await _get_active_profile()
        await record_signal(
            db,
            profile_id=prof["_id"],
            market=eff_market,
            symbol=symbol,
            timeframe=timeframe,
            action=consensus.get("action", "HOLD"),
            label=consensus.get("label", "HOLD"),
            confidence=int(consensus.get("confidence", 0)),
            price_at_signal=float(price),
        )
    except Exception as e:
        logger.warning("Failed to record signal: %s", e)

    # Cache last analysis (always store the Indonesian original)
    await db.analyses.replace_one(
        {"_id": f"{eff_market}-{symbol}-{timeframe}"},
        {
            "_id": f"{eff_market}-{symbol}-{timeframe}",
            "symbol": symbol, "market": eff_market, "timeframe": timeframe,
            "price": float(price), "technical": technical,
            "consensus": consensus, "models": result["models"],
            "news_used": news,
            "generated_at": _now_iso(),
        },
        upsert=True,
    )

    # If EN requested, translate human-readable narrative fields (consensus reasoning,
    # per-model reasoning, news titles/descriptions, news_factors, risk_factors).
    # Ticker symbols / numbers stay intact thanks to translator prompt rules.
    if lang == "en":
        narrative_texts: list[str] = []
        ptrs: list[tuple] = []  # (collection_ref, key_or_index) for write-back

        cons_reason = consensus.get("reasoning") or consensus.get("rationale") or ""
        if cons_reason:
            narrative_texts.append(cons_reason); ptrs.append(("consensus", "reasoning"))
        cons_summary = consensus.get("summary") or ""
        if cons_summary:
            narrative_texts.append(cons_summary); ptrs.append(("consensus", "summary"))
        cons_tfview = consensus.get("timeframe_view") or ""
        if cons_tfview:
            narrative_texts.append(cons_tfview); ptrs.append(("consensus", "timeframe_view"))

        # news_factors and risk_factors arrays
        news_factors = consensus.get("news_factors") or []
        for i, nf in enumerate(news_factors):
            if nf:
                narrative_texts.append(nf); ptrs.append(("news_factor", i))
        risk_factors = consensus.get("risk_factors") or []
        for i, rf in enumerate(risk_factors):
            if rf:
                narrative_texts.append(rf); ptrs.append(("risk_factor", i))

        for idx, m in enumerate(result.get("models", []) or []):
            data = m.get("data") if isinstance(m, dict) else None
            if data:
                r = data.get("reasoning") or data.get("rationale") or ""
                if r:
                    narrative_texts.append(r); ptrs.append(("model", idx))

        n_items = news or []
        news_titles = [i.get("title") or "" for i in n_items]
        news_descs = [i.get("description") or "" for i in n_items]

        translated = await translate_many(db, narrative_texts, "en") if narrative_texts else []
        news_titles_tr, news_descs_tr = await asyncio.gather(
            translate_many(db, news_titles, "en"),
            translate_many(db, news_descs, "en"),
        )

        for (loc, key), val in zip(ptrs, translated):
            if loc == "consensus":
                consensus[key] = val
            elif loc == "news_factor":
                try:
                    consensus["news_factors"][key] = val
                except Exception:
                    pass
            elif loc == "risk_factor":
                try:
                    consensus["risk_factors"][key] = val
                except Exception:
                    pass
            elif loc == "model":
                try:
                    result["models"][key]["data"]["reasoning"] = val
                except Exception:
                    pass
        for i, item in enumerate(n_items):
            item["title"] = news_titles_tr[i] if i < len(news_titles_tr) else item.get("title")
            item["description"] = news_descs_tr[i] if i < len(news_descs_tr) else item.get("description")

    return AnalyzeResponse(
        symbol=symbol, market=eff_market, timeframe=timeframe,
        price=float(price), technical=technical,
        consensus=consensus, models=result["models"],
        news_used=news,
        generated_at=_now_iso(),
    )


@api.get("/asset/{market}/{symbol}/track-record")
async def asset_track_record(
    market: Literal["crypto", "stock", "etf", "stock_id", "stock_us", "world_stocks", "gold_silver", "commodity", "forex"],
    symbol: str,
) -> dict:
    eff_market = "stock_id" if market == "stock" else market
    if eff_market == "world_stocks":
        eff_market = "stock_us"
    # v7.0.5: URL-safe dash decoder — forex/gold-silver symbols contain
    # "/" (EUR/USD, XAU/USD) which breaks path routing. Frontend pushes
    # them as "EUR-USD"; convert back here before pool lookup.
    if eff_market in ("forex", "gold_silver") and "-" in symbol:
        symbol = symbol.replace("-", "/")
    return await get_track_record(db, eff_market, symbol.upper())


# -------- News --------

@api.get("/ai/models")
async def get_ai_models() -> dict[str, Any]:
    """Return the list of AI models currently powering the ensemble analysis.

    Frontend uses this to display an up-to-date hint like
    "Press AI ANALYSIS for consensus from X + Y + Z" — so whenever the
    backend swaps in a newer model (e.g. Sonnet 4.6 → Sonnet 5), the UI
    text updates automatically without a mobile rebuild.
    """
    from ai_engine import MODELS as _AI_MODELS  # local import to avoid circulars
    return {
        "models": [
            {"name": m.get("label"), "provider": m.get("provider")}
            for m in _AI_MODELS
        ],
    }


@api.get("/search")
async def search_assets(
    q: str = Query(..., min_length=1, max_length=32),
    limit: int = Query(30, ge=1, le=60),
    timeframe: str = Query("1h"),
    profile: str | None = Query(None, description="Trader profile — search-hit signals match dashboard/detail"),
) -> dict[str, Any]:
    """Cross-market symbol search — v8.1.3 full-universe edition.

    Scans:
      1. Static maps (all 7 markets: crypto, IDX, ETF, US, gold, commodity, forex)
      2. Live Binance USDT universe (~2000 symbols, auto-loaded at startup)
      3. Live Bitget USDT universe (fallback for tokens not on Binance)
      4. CoinGecko `/search` disambiguation candidates (for ambiguous
         short tickers like CAT, only fetched when local matches are
         weak — always returned as `disambiguation` alongside `hits`).

    Ranking: exact match → prefix match → contains match.
    """
    from market_data import (
        CRYPTO_BINANCE_MAP,
        STOCK_YAHOO_MAP,
        ETF_YAHOO_MAP,
        STOCK_US_YAHOO_MAP,
        STOCK_US_YAHOO_MAP_EXTRA,
        GOLD_SILVER_YAHOO_MAP,
        COMMODITY_YAHOO_MAP,
        FOREX_YAHOO_MAP,
        BINANCE_UNIVERSE,
        BITGET_UNIVERSE,
    )

    query = q.strip().upper()
    if not query:
        return {"hits": [], "disambiguation": []}

    # Static curated maps (already have priority — dashboard/premium data).
    # v9.1.6 — stock_us pool digabung dengan search-only universe
    # (NASDAQ Trader resmi + S&P 500/400/600 superset): BNY, GEV, HONA,
    # dan ~5.200 ticker US lain kini bisa ditemukan via search.
    market_pools: list[tuple[str, list[str]]] = [
        ("crypto", list(CRYPTO_BINANCE_MAP.keys())),
        ("stock_id", list(STOCK_YAHOO_MAP.keys())),
        ("etf", list(ETF_YAHOO_MAP.keys())),
        ("stock_us", list(STOCK_US_YAHOO_MAP.keys()) + list(STOCK_US_YAHOO_MAP_EXTRA.keys())),
        ("gold_silver", list(GOLD_SILVER_YAHOO_MAP.keys())),
        ("commodity", list(COMMODITY_YAHOO_MAP.keys())),
        ("forex", list(FOREX_YAHOO_MAP.keys())),
    ]

    # (market, symbol, rank) — lower rank = better match.
    matches: list[tuple[str, str, int]] = []
    for market, syms in market_pools:
        for sym in syms:
            s = sym.upper()
            if s == query:
                matches.append((market, sym, 0))
            elif s.startswith(query):
                matches.append((market, sym, 1))
            elif query in s:
                matches.append((market, sym, 2))

    # Track already-added crypto symbols to avoid duplicates from universe scan.
    seen_crypto = {m[1].upper() for m in matches if m[0] == "crypto"}

    # v8.1.3 — Scan the LIVE Binance USDT universe. This is where meme
    # tokens like MOODENG, POPCAT, BRETT, CATI, etc. get picked up
    # without any manual map update.
    for base in BINANCE_UNIVERSE.keys():
        if base in seen_crypto:
            continue
        if base == query:
            matches.append(("crypto", base, 0))
            seen_crypto.add(base)
        elif base.startswith(query):
            matches.append(("crypto", base, 1))
            seen_crypto.add(base)
        elif len(query) >= 3 and query in base:
            matches.append(("crypto", base, 2))
            seen_crypto.add(base)

    # v8.1.3 — Bitget spot universe (tokens NOT on Binance).
    for base in BITGET_UNIVERSE.keys():
        if base in seen_crypto:
            continue
        if base == query:
            matches.append(("crypto", base, 0))
            seen_crypto.add(base)
        elif base.startswith(query):
            matches.append(("crypto", base, 1))
            seen_crypto.add(base)
        elif len(query) >= 3 and query in base:
            matches.append(("crypto", base, 2))
            seen_crypto.add(base)

    matches.sort(key=lambda m: (m[2], m[1]))
    matches = matches[:limit]

    # Track whether we already have a strong crypto match BEFORE the
    # safety-net prepend below — used to decide whether to also fetch
    # CoinGecko disambiguation candidates for the user.
    had_exact_crypto_before_safety_net = any(
        m[2] == 0 and m[0] == "crypto" for m in matches
    )

    # v8.1.3 — Safety-net on-demand crypto lookup. Even if the query is
    # NOT in our known universes (Binance mirror is limited to ~470 pairs
    # in some geos; Bitget likewise misses some meme coins), the query
    # itself might still be a valid CoinGecko token. Prepend a synthetic
    # crypto/{query} match and let `get_crypto_snapshot` cascade through
    # Binance → Bitget → CoinGecko to actually fetch OHLCV. If none of
    # them have data, this hit is silently dropped from the response.
    # v8.12.64 — Safety-net crypto lookup must NOT outrank an EXACT
    # match from another market. Previously searching "ABBA" (a real
    # IDX stock) prepended a random CoinGecko token also tickered ABBA
    # above the actual stock. Only fire the safety net when there is
    # no exact ticker match in ANY market.
    had_exact_match_any_market = any(m[2] == 0 for m in matches)
    if not had_exact_match_any_market and len(query) >= 2 and query.isalnum():
        # Only meaningful for symbols that look like a ticker
        # (2+ alphanumeric chars). Prepend so it shows above fuzzy matches
        # when successful.
        matches = [("crypto", query, 0)] + matches
        matches = matches[:limit]

    # v8.1.3 — CoinGecko multi-match ONLY when we did NOT already have a
    # strong crypto match from local universes AND the query looks like a
    # short/ambiguous crypto ticker. This surfaces CAT / OPUS / etc.
    # candidates alongside any static-map hits (e.g. CAT stock).
    disambiguation: list[dict[str, Any]] = []
    if not had_exact_crypto_before_safety_net and len(query) >= 2 and query.isalnum():
        try:
            from market_data import coingecko_multi_search
            disambiguation = await coingecko_multi_search(query, limit=5)
        except Exception:
            disambiguation = []

    if not matches:
        return {"hits": [], "disambiguation": disambiguation, "query": query}

    # Fetch snapshots concurrently.
    from market_data import get_crypto_snapshot, get_stock_snapshot, _yahoo_throttled

    async def fetch_one(market: str, symbol: str):
        try:
            if market == "crypto":
                snap = await get_crypto_snapshot(symbol, timeframe)
            else:
                snap = await _yahoo_throttled(
                    get_stock_snapshot(symbol, timeframe, market)
                )
            if snap:
                snap["market"] = market
                return snap
        except Exception:
            return None
        return None

    results = await asyncio.gather(
        *[fetch_one(m, s) for (m, s, _r) in matches],
        return_exceptions=True,
    )
    hits = [r for r in results if isinstance(r, dict)]

    # Enrich each hit with technical signal + track record.
    symbols_by_market: dict[str, list[str]] = {}
    for h in hits:
        symbols_by_market.setdefault(h["market"], []).append(h["symbol"])
    tr_by_symbol: dict[str, Any] = {}
    for m, syms in symbols_by_market.items():
        tr = await _get_tr_summary_cached(m, syms)
        tr_by_symbol.update(tr)

    signals = [
        _build_signal(h, tr_by_symbol.get(h["symbol"]), profile=profile).model_dump()
        for h in hits
    ]
    for sig, h in zip(signals, hits):
        sig["market"] = h["market"]

    return {
        "hits": signals,
        "disambiguation": disambiguation,
        "query": query,
    }




# v8.12.69 — Latest published Android build. The /app-version endpoint
# serves this so outdated installs get an update prompt. Bump together
# with frontend APP_VERSION / app.json version on every release.
APP_LATEST_VERSION = "9.3.0"


@api.get("/app-version")
async def app_version() -> dict[str, Any]:
    """v8.12.69 — Latest published app version + Play Store link.

    The Android client compares this against its own build version on
    every cold start and nags the user to update when outdated. Bump
    APP_LATEST_VERSION here whenever a new APK/AAB is released.
    """
    return {
        "latest_version": APP_LATEST_VERSION,
        "play_store_url": "https://play.google.com/store/apps/details?id=com.cryptostockapps.aicryptostockpro",
    }


@api.get("/news", response_model=NewsResponse)
async def news_global(
    market: Literal["crypto", "stock", "etf", "stock_id", "stock_us", "world_stocks", "gold_silver", "commodity", "forex", "all"] = Query("all"),
    limit: int = Query(40, ge=1, le=80),
    lang: Literal["id", "en"] = Query("id"),
) -> NewsResponse:
    eff_market = "stock_id" if market == "stock" else market
    if eff_market == "world_stocks":
        eff_market = "stock_us"
    # v7.0.5 / v8.5.3 — URL-safe dash decoder — forex/gold-silver symbols
    # contain "/" (EUR/USD, XAU/USD) which breaks path routing. This block
    # only applies inside symbol-scoped routes; in this global news_global
    # handler `symbol` doesn't exist, so we guard defensively.
    _sym_local = locals().get("symbol")
    if eff_market in ("forex", "gold_silver") and _sym_local and "-" in _sym_local:
        _sym_local = _sym_local.replace("-", "/")  # only mutates the local, not used further in global route
    items = await get_news(eff_market, limit=limit)
    if lang == "en" and items:
        titles = [i.get("title") or "" for i in items]
        descs = [i.get("description") or "" for i in items]
        titles_tr, descs_tr = await asyncio.gather(
            translate_many(db, titles, "en"),
            translate_many(db, descs, "en"),
        )
        for i, item in enumerate(items):
            item["title"] = titles_tr[i]
            item["description"] = descs_tr[i]
    return NewsResponse(market=eff_market, items=[NewsItem(**i) for i in items], fetched_at=_now_iso())


@api.get("/asset/{market}/{symbol}/news", response_model=NewsResponse)
async def news_for_asset(
    market: Literal["crypto", "stock", "etf", "stock_id", "stock_us", "world_stocks", "gold_silver", "commodity", "forex"],
    symbol: str,
    limit: int = Query(10, ge=1, le=30),
    lang: Literal["id", "en"] = Query("id"),
) -> NewsResponse:
    eff_market = "stock_id" if market == "stock" else market
    if eff_market == "world_stocks":
        eff_market = "stock_us"
    # v7.0.5: URL-safe dash decoder — forex/gold-silver symbols contain
    # "/" (EUR/USD, XAU/USD) which breaks path routing. Frontend pushes
    # them as "EUR-USD"; convert back here before pool lookup.
    if eff_market in ("forex", "gold_silver") and "-" in symbol:
        symbol = symbol.replace("-", "/")
    items = await get_news_for_symbol(symbol.upper(), eff_market, limit=limit)
    if lang == "en" and items:
        titles = [i.get("title") or "" for i in items]
        descs = [i.get("description") or "" for i in items]
        titles_tr, descs_tr = await asyncio.gather(
            translate_many(db, titles, "en"),
            translate_many(db, descs, "en"),
        )
        for i, item in enumerate(items):
            item["title"] = titles_tr[i]
            item["description"] = descs_tr[i]
    return NewsResponse(market=eff_market, items=[NewsItem(**i) for i in items], fetched_at=_now_iso())


# -------- Translate --------

class TranslatePayload(BaseModel):
    texts: list[str]
    target_lang: Literal["en", "id"] = "en"


@api.post("/translate")
async def translate_endpoint(payload: TranslatePayload) -> dict:
    """Batch-translate arbitrary texts (cached by content hash)."""
    out = await translate_many(db, payload.texts, payload.target_lang)
    return {"target_lang": payload.target_lang, "items": out}


# -------- App wiring --------

@api.post("/auth/verify")
async def auth_verify(payload: dict) -> dict:
    """Verify an unlock code from the main app.

    Body: { email, code, device_id, device_name? }

    Returns:
      { ok: true, duration, expires_at, device_id } on success
      { ok: false, reason } on failure. Reasons:
        - invalid_code, email_mismatch, revoked, expired, device_mismatch
    """
    email = str(payload.get("email") or "").strip()
    code = str(payload.get("code") or "").strip().upper()
    device_id = str(payload.get("device_id") or "").strip() or None
    device_name = str(payload.get("device_name") or "").strip() or None
    if not email or not code:
        raise HTTPException(400, "Email and code are required")
    if not device_id:
        raise HTTPException(400, "device_id is required for device-bound verification")
    result = await verify_code(db, email, code, device_id, device_name)
    if not result["ok"]:
        return result
    # Mirror to legacy `logged_users` for existing admin views + track counters
    now = _now_iso()
    await db.logged_users.update_one(
        {"_id": email.lower()},
        {
            "$set": {
                "email": email.lower(),
                "last_seen": now,
                "device_id": device_id,
                "device_name": device_name,
                "duration": result.get("duration"),
                "expires_at": result.get("expires_at"),
            },
            "$setOnInsert": {"unlocked_at": now},
            "$inc": {"login_count": 1},
        },
        upsert=True,
    )
    return result


@api.get("/whoami")
async def whoami(request: Request) -> dict:
    """Backend fingerprint — helps users verify their APK & admin tool
    are talking to the SAME backend / database.

    Returns:
      - backend_host: the exact hostname/origin the request landed on
      - db_name: MongoDB database name in use
      - codes_count: number of unlock codes stored in this DB
      - admin_tool_url: exact URL the admin tool should be opened at
    """
    # Prefer the ingress-visible host (respect proxy header if present)
    fwd_host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme or "https"
    backend_origin = f"{scheme}://{fwd_host}" if fwd_host else str(request.base_url).rstrip("/")
    try:
        codes_count = await db.unlock_codes.count_documents({})
    except Exception:
        codes_count = -1
    return {
        "backend_origin": backend_origin,
        "db_name": os.environ.get("DB_NAME", "?"),
        "codes_count": codes_count,
        "admin_tool_url": f"{backend_origin}/api/admin-tool",
        "server_time": _now_iso(),
    }


# ---- Admin: unlock code management ----

def _check_admin(x_admin_token: str | None) -> None:
    expected = os.environ.get("ADMIN_TOKEN", "")
    if not expected or x_admin_token != expected:
        raise HTTPException(403, "Forbidden")


@api.post("/admin/generate-code")
async def admin_generate_code(
    payload: dict,
    x_admin_token: str | None = Header(default=None),
) -> dict:
    """Generate a new unlock code for an email + duration. Admin-only."""
    _check_admin(x_admin_token)
    email = str(payload.get("email") or "").strip()
    duration = str(payload.get("duration") or "monthly").lower()
    if duration not in DURATION_DAYS:
        raise HTTPException(400, f"Invalid duration. Must be one of {list(DURATION_DAYS.keys())}")
    try:
        res = await generate_code(db, email, duration)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {
        **res,
        "duration_label": DURATION_LABEL.get(duration, duration),
    }


@api.get("/admin/codes")
async def admin_list_codes(
    x_admin_token: str | None = Header(default=None),
) -> dict:
    """List all unlock codes with device / expiry status. Admin-only."""
    _check_admin(x_admin_token)
    codes = await list_codes(db)
    # Compute a synthetic status (active/expired/revoked/unused) for each
    now = datetime.now(timezone.utc)
    for c in codes:
        if c.get("revoked"):
            c["status"] = "revoked"
        else:
            exp = c.get("expires_at")
            if exp:
                try:
                    if datetime.fromisoformat(exp) <= now:
                        c["status"] = "expired"
                        continue
                except Exception:
                    pass
            c["status"] = "active" if c.get("device_id") else "unused"
    return {"total": len(codes), "codes": codes}


@api.delete("/admin/codes/{code}")
async def admin_delete_code(
    code: str,
    x_admin_token: str | None = Header(default=None),
) -> dict:
    """Fully delete an unlock code (user must be re-issued a new one)."""
    _check_admin(x_admin_token)
    ok = await delete_code(db, code)
    if not ok:
        raise HTTPException(404, "Code not found")
    return {"ok": True, "code": code.upper()}


@api.post("/admin/codes/{code}/revoke")
async def admin_revoke_code_endpoint(
    code: str,
    x_admin_token: str | None = Header(default=None),
) -> dict:
    """Mark a code as revoked (softer than delete — code stays in history)."""
    _check_admin(x_admin_token)
    ok = await revoke_code(db, code)
    if not ok:
        raise HTTPException(404, "Code not found")
    return {"ok": True, "code": code.upper()}


@api.post("/admin/codes/{code}/reset-device")
async def admin_reset_device(
    code: str,
    x_admin_token: str | None = Header(default=None),
) -> dict:
    """Clear device binding so the code can be re-bound to a new device."""
    _check_admin(x_admin_token)
    ok = await reset_device_binding(db, code)
    if not ok:
        raise HTTPException(404, "Code not found")
    return {"ok": True, "code": code.upper()}


@api.get("/admin/users", response_model=LoggedUsersResponse)
async def admin_list_users(x_admin_token: str | None = Header(default=None)) -> LoggedUsersResponse:
    """List all users who have successfully unlocked the app. Admin-only.

    Combined view: joins `logged_users` with device info from `unlock_codes`.
    """
    _check_admin(x_admin_token)
    docs: list[LoggedUser] = []
    cursor = db.logged_users.find({}).sort("last_seen", -1)
    async for d in cursor:
        docs.append(LoggedUser(
            email=d.get("email", ""),
            unlocked_at=d.get("unlocked_at", ""),
            last_seen=d.get("last_seen", ""),
            login_count=int(d.get("login_count", 1)),
            device_id=d.get("device_id"),
            device_name=d.get("device_name"),
            duration=d.get("duration"),
            expires_at=d.get("expires_at"),
        ))
    return LoggedUsersResponse(total=len(docs), users=docs)


@api.delete("/admin/users/{email}")
async def admin_revoke_user(email: str, x_admin_token: str | None = Header(default=None)) -> dict:
    """Revoke a user — removes them from logged_users AND revokes all their codes."""
    _check_admin(x_admin_token)
    target = email.strip().lower()
    res = await db.logged_users.delete_one({"_id": target})
    # Also revoke every code owned by this email
    await db.unlock_codes.update_many({"email": target}, {"$set": {"revoked": True}})
    if res.deleted_count == 0:
        raise HTTPException(404, "User not found")
    return {"ok": True, "revoked": target}


# ---------------- Google Play Billing Subscription ----------------

class SubscriptionVerifyPayload(BaseModel):
    purchase_token: str
    product_id: str
    package_name: str | None = None
    device_id: str | None = None
    # v8.12.69 — The Play Console base plan the user purchased (e.g.
    # "pro-2m"). Recorded so one-time promos can be enforced
    # server-side (a promo plan may only ever be claimed ONCE per
    # device — reinstalling the app does NOT reset it).
    base_plan_id: str | None = None


class SubscriptionStatusResponse(BaseModel):
    status: str
    entitled: bool
    expiry_time: str | None = None
    product_id: str | None = None
    source: str = "unknown"
    debug: str | None = None


async def _upsert_entitlement(
    *,
    device_id: str | None,
    purchase_token: str,
    product_id: str,
    package_name: str,
    status: str,
    entitled: bool,
    expiry_dt: datetime | None,
    source: str,
    debug: str | None = None,
    base_plan_id: str | None = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "purchase_token": purchase_token,
        "product_id": product_id,
        "package_name": package_name,
        "device_id": device_id,
        "status": status,
        "entitled": entitled,
        "expiry_time": expiry_dt.isoformat() if expiry_dt else None,
        "source": source,
        "updated_at": now,
        "debug": debug,
        "base_plan_id": base_plan_id,
    }
    await db.subscriptions.update_one(
        {"purchase_token": purchase_token, "package_name": package_name},
        {"$set": doc, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )


@api.get("/subscription/debug/latest")
async def subscription_debug_latest(device_id: str | None = None) -> dict[str, Any]:
    """Return the most recent verify attempt for debugging.

    Includes the raw Google Play API error/debug string so we can figure out why
    a purchase was rejected. Safe: does not return the full purchase token to
    client (truncated).
    """
    query: dict[str, Any] = {}
    if device_id:
        query["device_id"] = device_id
    row = await db.subscriptions.find_one(query, sort=[("updated_at", -1)])
    if not row:
        return {"found": False}
    token = row.get("purchase_token", "")
    return {
        "found": True,
        "status": row.get("status"),
        "entitled": row.get("entitled"),
        "expiry_time": row.get("expiry_time"),
        "product_id": row.get("product_id"),
        "package_name": row.get("package_name"),
        "device_id": row.get("device_id"),
        "source": row.get("source"),
        "debug": row.get("debug"),
        "updated_at": row.get("updated_at"),
        "token_prefix": (token[:12] + "…") if token else None,
    }


@api.post("/subscription/verify", response_model=SubscriptionStatusResponse)
async def subscription_verify(payload: SubscriptionVerifyPayload) -> SubscriptionStatusResponse:
    """Verify a Google Play subscription purchase token and persist entitlement.

    - Called by the Android client right after `requestSubscription` succeeds
      AND on restore-purchase (`getAvailablePurchases`).
    - If GOOGLE_PLAY_SERVICE_ACCOUNT_JSON is NOT set on the backend, we return
      status="unverified" and entitled=False. Client must not treat this as
      premium unlock — user should be routed back to paywall.
    """
    token = (payload.purchase_token or "").strip()
    product_id = (payload.product_id or "").strip()
    if not token or not product_id:
        raise HTTPException(400, "purchase_token and product_id are required")

    pkg = (payload.package_name or "com.cryptostockapps.aicryptostockpro").strip()

    result = verify_purchase(token, product_id, pkg)
    status = result["status"]
    entitled = bool(result.get("entitled"))
    expiry_dt = result.get("expiry_time")
    source = result.get("source", "unknown")

    await _upsert_entitlement(
        device_id=payload.device_id,
        purchase_token=token,
        product_id=product_id,
        package_name=pkg,
        status=status,
        entitled=entitled,
        expiry_dt=expiry_dt,
        source=source,
        debug=result.get("debug"),
        base_plan_id=payload.base_plan_id,
    )

    return SubscriptionStatusResponse(
        status=status,
        entitled=entitled,
        expiry_time=expiry_dt.isoformat() if expiry_dt else None,
        product_id=product_id,
        source=source,
        debug=result.get("debug"),
    )


@api.get("/subscription/status", response_model=SubscriptionStatusResponse)
async def subscription_status(device_id: str | None = None) -> SubscriptionStatusResponse:
    """Look up cached entitlement for a device.

    Returns the most-recent entitlement row for the device. If none exists or
    the last-known expiry is in the past, entitled=False.
    Note: This is a **cache** — the authoritative flow is `POST /verify`. Use
    this endpoint on cold-start to quickly gate UI, then re-verify in background.
    """
    if not device_id:
        return SubscriptionStatusResponse(
            status="none", entitled=False, source="none",
        )
    row = await db.subscriptions.find_one(
        {"device_id": device_id},
        sort=[("updated_at", -1)],
    )
    if not row:
        return SubscriptionStatusResponse(status="none", entitled=False, source="none")

    status = row.get("status", "invalid")
    expiry_iso = row.get("expiry_time")
    entitled = status in ENTITLED_STATUSES
    # Belt-and-suspenders: expiry passed → not entitled
    if entitled and expiry_iso:
        try:
            if datetime.fromisoformat(expiry_iso.replace("Z", "+00:00")) <= datetime.now(timezone.utc):
                entitled = False
                status = "expired"
        except Exception:
            pass
    return SubscriptionStatusResponse(
        status=status,
        entitled=entitled,
        expiry_time=expiry_iso,
        product_id=row.get("product_id"),
        source=row.get("source", "cached"),
    )


@api.get("/subscription/promo-claimed")
async def subscription_promo_claimed(device_id: str, base_plan_id: str) -> dict[str, Any]:
    """v8.12.69 — Has this device EVER claimed the given base plan?

    Used to enforce one-time promo plans (e.g. the LIMITED 2-Months
    offer): once any subscription row exists for (device, base plan),
    the promo card is locked in the paywall — even after expiry,
    cancellation, or an app reinstall.
    """
    if not device_id or not base_plan_id:
        return {"claimed": False}
    row = await db.subscriptions.find_one(
        {"device_id": device_id, "base_plan_id": base_plan_id},
    )
    return {"claimed": bool(row)}


# ---- Promo code redemption (one per device) ----
# v8.12.76 — Custom promo codes (Play Console campaign "promo-2026")
# may only be redeemed ONCE per device. Google Play additionally
# restricts each Play account to a single redemption of the custom
# code, so the two layers stack. Reinstalling the app does NOT reset
# the device lock because the record lives server-side.


@api.get("/promo/redeemed")
async def promo_redeemed(device_id: str) -> dict[str, Any]:
    """Has this device already redeemed a promo code?"""
    if not device_id:
        return {"redeemed": False}
    row = await db.promo_redemptions.find_one({"device_id": device_id})
    return {
        "redeemed": bool(row),
        "redeemed_at": row.get("redeemed_at") if row else None,
    }


class PromoRedeemPayload(BaseModel):
    device_id: str
    code: str


@api.post("/promo/redeem")
async def promo_redeem(payload: PromoRedeemPayload) -> dict[str, Any]:
    """Record a promo-code redemption for a device. Idempotent — the
    first record wins; later attempts just report already-redeemed."""
    device_id = (payload.device_id or "").strip()
    code = (payload.code or "").strip().upper()
    if not device_id or not code:
        raise HTTPException(400, "device_id and code are required")
    existing = await db.promo_redemptions.find_one({"device_id": device_id})
    if existing:
        return {
            "ok": True,
            "already": True,
            "redeemed_at": existing.get("redeemed_at"),
        }
    now = datetime.now(timezone.utc).isoformat()
    await db.promo_redemptions.update_one(
        {"device_id": device_id},
        {"$setOnInsert": {"device_id": device_id, "code": code, "redeemed_at": now}},
        upsert=True,
    )
    return {"ok": True, "already": False, "redeemed_at": now}


@api.get("/subscription/health")
async def subscription_health() -> dict[str, Any]:
    """Self-diagnostic endpoint — reports whether backend can talk to Google Play.
    Safe to call publicly; returns no PII, only configuration status.
    """
    import os as _os
    from subscription_service import _CachedClient, _package_name

    sa_env = _os.environ.get("GOOGLE_PLAY_SERVICE_ACCOUNT_JSON", "").strip()
    sa_path_exists = bool(sa_env and _os.path.isfile(sa_env))
    sa_inline_json = bool(sa_env.startswith("{"))
    client = _CachedClient.get()
    return {
        "service_account_env_set": bool(sa_env),
        "service_account_path_exists": sa_path_exists,
        "service_account_inline_json": sa_inline_json,
        "publisher_client_initialised": client is not None,
        "package_name": _package_name(),
    }


# ---------------- Global Chatroom (Premium subscribers only) ----------------

CHAT_RATE_LIMIT_SECONDS = 3
CHAT_MESSAGE_MAX_LENGTH = 500
CHAT_HISTORY_LIMIT = 200
# Auto-expire chat history older than 16 hours (v7.0.5) — new members do
# not see stale conversations. Applied both on read (filter) and on write
# (background purge on every insert to keep the collection lean).
CHAT_HISTORY_TTL_HOURS = 16
# Image data URL (base64) cap: ~700KB string ≈ ~500KB image binary after base64
# overhead. Anything larger is rejected to protect Mongo document limits.
CHAT_IMAGE_MAX_CHARS = 750_000
# v8.1.5 — Audio data URL cap. 60s of AAC/M4A @ 32kbps ≈ ~250KB binary
# ≈ ~340KB base64. Cap at 500KB to allow variance without abuse.
CHAT_AUDIO_MAX_CHARS = 500_000
CHAT_AUDIO_MAX_DURATION_MS = 30_000  # 30 s hard ceiling; client soft-caps at 20 s.
# v8.12.19 — Chatroom presence tracking window (seconds). A device is
# considered "online" if it has polled /chat/messages within this window.
# 90 s = 3 poll cycles at 30 s (or 30 cycles at 3 s) grace period.
PRESENCE_WINDOW_SEC = 90


class ChatReplyInfo(BaseModel):
    """Snapshot of the message being replied to. We denormalise the
    snippet + nickname + optional thumbnail into the reply so that
    subsequent renders don't need a second Mongo lookup, and so that
    reply context survives even if the original message is later purged
    by the 16h TTL sweep."""
    id: str
    nickname: str
    snippet: str = ""          # up to 80 chars of the original text
    has_image: bool = False    # true if original had an attachment
    has_audio: bool = False    # true if original was a voice note


class ChatMessagePayload(BaseModel):
    text: str = ""
    nickname: str
    device_id: str
    # Optional base64 data URL for image attachment (e.g. "data:image/jpeg;base64,...")
    image_data: str | None = None
    # v8.1.5 — Voice note support.
    audio_data: str | None = None          # data:audio/*;base64,...
    audio_duration_ms: int | None = None   # client-reported duration
    # v8.1.5 — Reply context (WhatsApp-style).
    reply_to: ChatReplyInfo | None = None


class ChatMessage(BaseModel):
    id: str
    text: str
    nickname: str
    device_id: str
    created_at: str
    image_data: str | None = None
    audio_data: str | None = None
    audio_duration_ms: int | None = None
    reply_to: ChatReplyInfo | None = None


async def _is_device_entitled(device_id: str) -> bool:
    """Check if a device has an active premium entitlement.

    v8.12.21 — Sources of truth (either grants access):
    1. Google Play subscription (collection: `subscriptions`, `entitled=True`
       and `expiry_time` in the future).
    2. Admin unlock code bound to this device (collection: `unlock_codes`,
       `revoked=False` and `expires_at` in the future OR `duration=lifetime`).

    Prior to v8.12.21 only source (1) was checked, so admins logged in
    with an unlock code (e.g. beta testers) were locked out of chatroom
    posting and Market Brief unlock even though the frontend showed them
    as premium.
    """
    if not device_id:
        return False

    # --- Source 1: Google Play subscriptions ---
    row = await db.subscriptions.find_one(
        {"device_id": device_id}, sort=[("updated_at", -1)]
    )
    if row and row.get("entitled"):
        expiry = row.get("expiry_time")
        if not expiry:
            return True
        try:
            exp_dt = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
            if exp_dt > datetime.now(timezone.utc):
                return True
        except Exception:
            # Fall through to source 2 rather than returning True on a
            # malformed expiry — safer default.
            pass

    # --- Source 2: Admin unlock codes bound to this device ---
    try:
        code_row = await db.unlock_codes.find_one(
            {
                "device_id": device_id,
                "revoked": {"$ne": True},
            },
            sort=[("last_used_at", -1)],
        )
        if code_row:
            expires_at = code_row.get("expires_at")
            if not expires_at:
                # duration == "lifetime"
                return True
            try:
                exp_dt = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
                if exp_dt > datetime.now(timezone.utc):
                    return True
            except Exception:
                pass
    except Exception:
        # DB error — degrade gracefully to False (no access), don't crash
        # the caller. Should be extremely rare given the same DB just
        # served source 1 above.
        pass

    return False


@api.post("/chat/messages", response_model=ChatMessage)
async def chat_send_message(payload: ChatMessagePayload) -> ChatMessage:
    """Send a message to the global chatroom. Only premium subscribers can post."""
    text = (payload.text or "").strip()
    nickname = (payload.nickname or "").strip()
    device_id = (payload.device_id or "").strip()
    image_data = (payload.image_data or "").strip() or None
    audio_data = (payload.audio_data or "").strip() or None
    audio_duration_ms = payload.audio_duration_ms

    if not nickname or not device_id:
        raise HTTPException(400, "nickname and device_id are required")
    if not text and not image_data and not audio_data:
        raise HTTPException(400, "Message text, image, or audio is required")
    if len(text) > CHAT_MESSAGE_MAX_LENGTH:
        raise HTTPException(400, f"Message too long (max {CHAT_MESSAGE_MAX_LENGTH})")
    if len(nickname) > 20:
        raise HTTPException(400, "Nickname too long (max 20)")
    if image_data is not None:
        if not image_data.startswith("data:image/"):
            raise HTTPException(400, "image_data must be a data URL (data:image/...)")
        if len(image_data) > CHAT_IMAGE_MAX_CHARS:
            raise HTTPException(
                400,
                f"Image too large (max ~{CHAT_IMAGE_MAX_CHARS // 1024}KB after base64).",
            )
    if audio_data is not None:
        if not audio_data.startswith("data:audio/"):
            raise HTTPException(400, "audio_data must be a data URL (data:audio/...)")
        if len(audio_data) > CHAT_AUDIO_MAX_CHARS:
            raise HTTPException(
                400,
                f"Audio too large (max ~{CHAT_AUDIO_MAX_CHARS // 1024}KB after base64).",
            )
        if audio_duration_ms is None or audio_duration_ms <= 0:
            audio_duration_ms = 0
        if audio_duration_ms > CHAT_AUDIO_MAX_DURATION_MS:
            raise HTTPException(400, f"Voice note too long (max {CHAT_AUDIO_MAX_DURATION_MS // 1000}s).")

    # Entitlement check
    if not await _is_device_entitled(device_id):
        raise HTTPException(403, "Only premium subscribers can post in the chatroom.")

    # Rate limit
    last = await db.chat_messages.find_one(
        {"device_id": device_id}, sort=[("created_at", -1)]
    )
    if last:
        try:
            last_dt = datetime.fromisoformat(last["created_at"].replace("Z", "+00:00"))
            elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds()
            if elapsed < CHAT_RATE_LIMIT_SECONDS:
                raise HTTPException(
                    429,
                    f"Please wait {int(CHAT_RATE_LIMIT_SECONDS - elapsed) + 1}s before sending another message.",
                )
        except HTTPException:
            raise
        except Exception:
            pass

    now = datetime.now(timezone.utc)
    msg: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "text": text,
        "nickname": nickname[:20],
        "device_id": device_id,
        "created_at": now.isoformat(),
        "image_data": image_data,
        "audio_data": audio_data,
        "audio_duration_ms": audio_duration_ms,
        "reply_to": payload.reply_to.model_dump() if payload.reply_to else None,
    }
    await db.chat_messages.insert_one(dict(msg))
    return ChatMessage(**msg)


@api.get("/chat/messages")
async def chat_get_messages(
    after: str | None = None,
    limit: int = Query(100, ge=1, le=CHAT_HISTORY_LIMIT),
    device_id: str | None = Query(None, description="Optional presence heartbeat"),
) -> dict[str, Any]:
    """Get recent chat messages. Pass `after` (ISO timestamp) to fetch only new ones.

    Messages older than CHAT_HISTORY_TTL_HOURS (16h) are hidden from
    everyone so new members do not see stale conversations.

    v8.12.19 — When `device_id` is supplied we treat this poll as a
    presence heartbeat: upsert into `chat_presence` and return the number
    of distinct devices seen within the last PRESENCE_WINDOW_SEC seconds
    as `online`. Missing / empty `device_id` skips presence and returns
    `online: 0`.
    """
    from datetime import timedelta

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=CHAT_HISTORY_TTL_HOURS)).isoformat()
    query: dict[str, Any] = {"created_at": {"$gte": cutoff}}
    if after:
        # Combine with cutoff — take the later of the two.
        query["created_at"] = {"$gt": max(after, cutoff)}
    # Opportunistic cleanup: delete anything older than the cutoff so the
    # collection stays small. Runs on every read but is a no-op most of
    # the time (Mongo returns 0 deleted quickly).
    try:
        await db.chat_messages.delete_many({"created_at": {"$lt": cutoff}})
    except Exception:
        pass
    cursor = db.chat_messages.find(query, projection={"_id": False}).sort(
        "created_at", -1
    ).limit(limit)
    rows = await cursor.to_list(length=limit)
    rows.reverse()  # oldest first for client convenience

    # v8.12.19 — Presence tracking. TTL index on `chat_presence.last_seen`
    # (created in _bootstrap_indexes) auto-expires stale rows after
    # PRESENCE_WINDOW_SEC*2, so counting active rows is O(index).
    online = 0
    try:
        now = datetime.now(timezone.utc)
        if device_id:
            did = device_id.strip()[:80]
            if did:
                await db.chat_presence.update_one(
                    {"device_id": did},
                    {"$set": {"device_id": did, "last_seen": now}},
                    upsert=True,
                )
        # Count distinct devices seen within the sliding window (default 90s).
        window_start = now - timedelta(seconds=PRESENCE_WINDOW_SEC)
        online = await db.chat_presence.count_documents({"last_seen": {"$gte": window_start}})
    except Exception:
        pass

    return {"messages": rows, "server_time": _now_iso(), "online": online}


@api.get("/chat/online")
async def chat_online(device_id: str | None = None) -> dict[str, Any]:
    """v8.12.36 — Lightweight presence-only endpoint for the dashboard
    Chatroom badge. Returns the number of distinct devices seen within
    the last PRESENCE_WINDOW_SEC seconds, WITHOUT loading any messages.

    Also acts as a presence heartbeat when `device_id` is supplied so the
    caller stays "online" while the badge polls. Cheap: single index
    count + one upsert.
    """
    from datetime import timedelta

    online = 0
    try:
        now = datetime.now(timezone.utc)
        if device_id:
            did = device_id.strip()[:80]
            if did:
                await db.chat_presence.update_one(
                    {"device_id": did},
                    {"$set": {"device_id": did, "last_seen": now}},
                    upsert=True,
                )
        window_start = now - timedelta(seconds=PRESENCE_WINDOW_SEC)
        online = await db.chat_presence.count_documents({"last_seen": {"$gte": window_start}})
    except Exception:
        pass
    return {"online": online, "server_time": _now_iso()}




# ------------------------- Push notifications -------------------------
# v8.3.0 — Frontend calls POST /api/register-push after the user grants
# notification permission. We forward the {user_id, platform, token} to the
# Emergent push relay AND store the {user_id, language} pair locally so the
# scheduler can group recipients by language cohort.


@api.post("/register-push", status_code=201)
async def register_push(body: RegisterPushBody) -> dict[str, str]:
    # Relay to Emergent (upserts device_token there). Failure surfaces as
    # 502/500 automatically.
    await register_push_token(body.user_id, body.platform, body.device_token)
    # Persist language cohort locally (no device_token stored — that lives
    # in the relay per playbook).
    await save_subscriber(db, body.user_id, body.language or "en", body.platform)
    return {"status": "registered"}


# v8.3.5 — Return the last-24h Market Brief history for the caller's
# language cohort. Consumed by the /market-brief page on the frontend.
# Docs auto-expire via the TTL index on `sent_at` (24h), so today's brief
# naturally replaces yesterday's without any manual pruning.
@api.get("/push/history")
async def push_history_endpoint(
    language: str = Query("en", description="One of: id / en / ru / cn"),
    limit: int = Query(20, ge=1, le=50),
) -> dict[str, Any]:
    lang = (language or "en").lower()
    if lang not in ("id", "en", "ru", "cn"):
        lang = "en"
    items = await get_history(db, lang, limit=limit)
    # Coerce datetime -> ISO string for JSON serialization.
    for it in items:
        ts = it.get("sent_at")
        if hasattr(ts, "isoformat"):
            it["sent_at"] = ts.isoformat()
    return {"language": lang, "count": len(items), "items": items}


# ---------------------- Market Brief (v8.7.1) --------------------------
#
# AI-generated narrative recap of the last session. Powered by Claude
# Sonnet 4.6 via the Emergent LLM Key. Runs 2x/day (06:00 & 18:00 WIB).
# Frontend consumes the latest brief in the caller's language via
# GET /api/market-brief?lang=id.

@api.get("/market-brief")
async def market_brief_endpoint(
    lang: str = Query("en", description="One of: id / en / ru / cn"),
    device_id: str = Query("", description="Optional device_id for premium gating"),
) -> dict[str, Any]:
    lang_key = (lang or "en").lower()
    if lang_key not in ("id", "en", "ru", "cn"):
        lang_key = "en"
    brief = await get_latest_brief(db, lang_key)
    if not brief:
        return {"available": False, "lang": lang_key, "brief": None, "is_premium": False}

    # v8.7.2 — Premium gating.
    # FREE tier gets: sentiment, sentiment_score, summary, top_headlines,
    #                 warning_zones (general market info + risk awareness).
    # PREMIUM tier ADDITIONALLY gets: sections (per-market actionable analysis)
    #                                 and top_movers (which include buy/sell
    #                                 rationale notes). Everything else stays
    #                                 identical so the shape is stable.
    is_premium = await _is_device_entitled(device_id.strip()) if device_id else False
    if not is_premium:
        brief = dict(brief)  # shallow copy so we don't mutate the cached doc
        brief["sections"] = {}      # locked → frontend renders paywall card
        brief["top_movers"] = []    # locked
        brief["premium_locked"] = True
    else:
        brief["premium_locked"] = False

    return {
        "available": True,
        "lang": lang_key,
        "brief": brief,
        "is_premium": is_premium,
    }


@api.post("/admin/reset-wr-history", include_in_schema=False)
async def admin_reset_wr_history(admin_token: str = Query(..., description="Admin bypass")) -> dict[str, Any]:
    """Nuke the signals collection so the WR track record starts fresh.

    Used AFTER shipping a tightened AI formula. Idempotent — the same call
    twice just deletes nothing the second time. Guarded by the admin token.
    """
    if admin_token != os.environ.get("ADMIN_UNLOCK_TOKEN", ""):
        raise HTTPException(status_code=403, detail="forbidden")
    result = await db.signals.delete_many({})
    marker = "v8.7.3-manual"
    await db.app_meta.replace_one(
        {"_id": "wr_reset_marker"},
        {"_id": "wr_reset_marker", "version": marker, "at": datetime.now(timezone.utc)},
        upsert=True,
    )
    return {"ok": True, "deleted": result.deleted_count, "marker": marker}


# v8.7.3 — Auto-reset marker: bump this string whenever we ship a formula
# change that requires wiping the historic WR track record. On startup,
# if the persisted marker < WR_RESET_TARGET, the signals collection is
# dropped ONCE and the marker is updated. Safe to redeploy repeatedly.
WR_RESET_TARGET = "v8.7.3"


async def _wr_reset_on_version_bump() -> None:
    """Wipe signals collection ONCE per WR_RESET_TARGET bump.

    v8.12.47 — No longer wired to startup. Callable ONLY via
    `POST /api/admin/startup-migrations` with a valid X-Admin-Token.
    """
    try:
        marker_doc = await db.app_meta.find_one({"_id": "wr_reset_marker"})
        cur = (marker_doc or {}).get("version", "")
        if cur == WR_RESET_TARGET:
            logger.info("wr-reset: already at %s, skip", WR_RESET_TARGET)
            return
        deleted = await db.signals.delete_many({})
        await db.app_meta.replace_one(
            {"_id": "wr_reset_marker"},
            {"_id": "wr_reset_marker", "version": WR_RESET_TARGET, "at": datetime.now(timezone.utc)},
            upsert=True,
        )
        logger.info(
            "wr-reset: wiped %d stale signals (bumped marker %s → %s)",
            deleted.deleted_count, cur or "<none>", WR_RESET_TARGET,
        )
    except Exception as e:
        logger.warning("wr-reset failed: %s", e)
async def market_brief_generate(admin_token: str = Query(..., description="Admin bypass")) -> dict[str, Any]:
    """Manual trigger — used by the admin/cron warmup to regenerate a brief
    off-schedule. Guarded by the admin token so it can't be abused.
    """
    if admin_token != os.environ.get("ADMIN_UNLOCK_TOKEN", ""):
        raise HTTPException(status_code=403, detail="forbidden")
    doc = await generate_and_store_brief(
        db, _brief_dashboard_batch_fetch, _brief_news_fetch,
    )
    return {"ok": bool(doc), "id": doc.get("_id") if doc else None}


# v9.3.0 — ASI-Bot (Artificial Super Intelligence Bot) Phase 1:
# Credential management (AES-256-GCM encrypted exchange API keys).
# Register BEFORE include_router so sub-routes are picked up.
from asi_bot.routes import register as _register_asi_bot  # noqa: E402
from asi_bot.scheduler import ASIScheduler  # noqa: E402
_register_asi_bot(api, db)
_asi_scheduler_state: dict[str, Any] = {"scheduler": None}

app.include_router(api)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


# --- Admin-only static admin HTML (served under /api/admin-tool for ingress-friendly route) ---
from fastapi.responses import FileResponse, HTMLResponse  # noqa: E402


@app.get("/api/admin-tool", include_in_schema=False)
async def admin_tool_html() -> HTMLResponse:
    """Serve the standalone Unlock Code Generator web page.

    Access via https://<backend>/api/admin-tool from a browser. Do NOT share
    the URL. The page still calls protected /api/admin/* endpoints with the
    admin token embedded.
    """
    try:
        path = os.path.join(os.path.dirname(__file__), "static", "admin.html")
        with open(path, "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    except Exception:
        return HTMLResponse("<h1>Admin tool not deployed</h1>", status_code=404)


@app.api_route("/api/privacy", methods=["GET", "HEAD"], include_in_schema=False)
async def privacy_policy_html() -> HTMLResponse:
    """PUBLIC Privacy Policy page — required by Google Play Console for store
    submission. Google reviewers must be able to open this URL without login.

    v8.3.1 — Also accepts HEAD requests. Google Play Console (and other
    URL validators) issue HEAD to check reachability; a 405 there was
    surfacing as "page not found" in the pre-review checklist.
    """
    try:
        path = os.path.join(os.path.dirname(__file__), "static", "privacy.html")
        with open(path, "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    except Exception:
        return HTMLResponse("<h1>Privacy policy not deployed</h1>", status_code=404)


@app.api_route("/api/terms", methods=["GET", "HEAD"], include_in_schema=False)
async def terms_html() -> HTMLResponse:
    """PUBLIC Terms of Service page — required for Play Console subscription apps."""
    try:
        path = os.path.join(os.path.dirname(__file__), "static", "terms.html")
        with open(path, "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    except Exception:
        return HTMLResponse("<h1>Terms of service not deployed</h1>", status_code=404)


@app.api_route("/api/data-deletion", methods=["GET", "HEAD"], include_in_schema=False)
async def data_deletion_html() -> HTMLResponse:
    """PUBLIC Account/Data Deletion Request page — required by Google Play Console
    Data Safety section (users must have a URL to request account deletion).

    v8.3.1 — Also accepts HEAD requests (see privacy_policy_html).
    """
    try:
        path = os.path.join(os.path.dirname(__file__), "static", "data-deletion.html")
        with open(path, "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    except Exception:
        return HTMLResponse("<h1>Data deletion page not deployed</h1>", status_code=404)


@app.get("/api/store-assets/{filename}", include_in_schema=False)
async def store_asset(filename: str) -> FileResponse:
    """Serve Play Store submission assets (feature graphic, screenshots).
    Admin/dev only — link the specific URL to download.
    """
    # sanitize
    if "/" in filename or ".." in filename or not (filename.endswith(".png") or filename.endswith(".jpg")):
        return HTMLResponse("<h1>Invalid asset</h1>", status_code=400)
    path = os.path.join(os.path.dirname(__file__), "static", "store-assets", filename)
    if not os.path.exists(path):
        return HTMLResponse(f"<h1>Not found: {filename}</h1>", status_code=404)
    media = "image/jpeg" if filename.endswith(".jpg") else "image/png"
    return FileResponse(path, media_type=media, filename=filename)


@app.get("/api/admin-source.zip", include_in_schema=False)
async def admin_source_zip() -> FileResponse:
    """Download the admin-app source ZIP (for offline APK build via EAS Cloud).

    Contains the entire /app/admin-app source tree minus node_modules. Extract
    and follow admin-app/BUILD_APK.md instructions.
    """
    path = os.path.join(os.path.dirname(__file__), "static", "CryptoStock-Admin-Source.zip")
    return FileResponse(
        path,
        media_type="application/zip",
        filename="CryptoStock-Admin-Source.zip",
    )


@app.get("/api/app-source.zip", include_in_schema=False)
async def app_source_zip() -> FileResponse:
    """Download the MAIN APP source ZIP for building CryptoStock Pro APK (v2.1.3+)."""
    path = os.path.join(os.path.dirname(__file__), "static", "CryptoStock-App-Source.zip")
    return FileResponse(path, media_type="application/zip", filename="CryptoStock-App-Source.zip")


@app.get("/api/build-main-guide", include_in_schema=False)
async def build_main_guide() -> FileResponse:
    """Markdown build guide for main app APK."""
    path = os.path.join(os.path.dirname(__file__), "static", "BUILD_MAIN_APK.md")
    return FileResponse(path, media_type="text/markdown", filename="BUILD_MAIN_APK.md")


# NOTE: no @app.on_event("startup") MongoDB seed — kept lazy so the API can
# accept traffic immediately even while the Atlas connection is warming up.
# Seeding happens on first /api/profiles or /api/dashboard call.
#
# v7.0.9 — Index bootstrap runs in the background on startup so it does not
# block the health check. We create a TTL index on chat_messages.created_at
# so Mongo automatically deletes any document older than 16 hours (matches
# the CHAT_HISTORY_TTL_HOURS filter used at read time). Idempotent — if the
# index already exists with the same spec, Mongo is a no-op.


async def _bootstrap_indexes() -> None:
    """Create supporting indexes. Runs once on startup, non-blocking."""
    try:
        await db.chat_messages.create_index("created_at")
        # v8.0.9 — indexes on the signals collection so track-record
        # aggregation stays fast even after thousands of writes.
        await db.signals.create_index([("market", 1), ("symbol", 1), ("created_at", -1)])
        await db.signals.create_index("created_at")
        # v8.12.19 — Chatroom presence collection. Unique per device_id
        # (upserts on heartbeat), with a TTL that auto-purges rows once
        # their `last_seen` is older than PRESENCE_WINDOW_SEC * 2 seconds
        # so we don't count ghosts.
        try:
            await db.chat_presence.create_index("device_id", unique=True)
        except Exception:
            # Index may already exist with a different spec — ignore.
            pass
        try:
            await db.chat_presence.create_index(
                "last_seen", expireAfterSeconds=PRESENCE_WINDOW_SEC * 2
            )
        except Exception:
            pass
    except Exception:
        pass


async def _load_universe_refresh_loop() -> None:
    """v8.1.3 — On startup, load Binance + Bitget universes IMMEDIATELY,
    then refresh every 6h. Search relies on these being populated
    early — but even if the first load is slow, the endpoint gracefully
    falls back to the static maps."""
    try:
        from market_data import _load_binance_universe, _load_bitget_universe
        # First load — parallel, non-blocking with respect to other startup work.
        await asyncio.gather(
            _load_binance_universe(force=True),
            _load_bitget_universe(force=True),
            return_exceptions=True,
        )
        # Periodic refresh loop (6h).
        while True:
            await asyncio.sleep(6 * 3600)
            try:
                await asyncio.gather(
                    _load_binance_universe(force=True),
                    _load_bitget_universe(force=True),
                    return_exceptions=True,
                )
            except Exception:
                # Never let the refresh loop die.
                await asyncio.sleep(60)
    except Exception:
        pass


async def _bootstrap_signals_seed() -> None:
    """v8.0.9 — Seed the `signals` collection so newly-deployed instances
    do not have an empty win-rate history (which used to demote every
    asset from Premium). We write ONE synthetic snapshot per tracked
    symbol per market at startup, using the local rule-based
    `compute_signal` output (no AI cost). Real user Analyze calls
    keep writing over top of this baseline afterwards.

    Runs delayed by 20s so it does not fight cold-start dashboard load
    for upstream Yahoo/Binance connections."""
    try:
        await asyncio.sleep(20)
        # If we already have recent signals, skip — no need to spam Mongo.
        recent = await db.signals.count_documents({}, limit=1)
        if recent > 0:
            # Only re-seed on fully empty deployments.
            return

        # Import lazily to avoid a circular import at module load.
        from indicators import compute_signal
        from market_data import get_batch as md_get_batch

        prof = await _get_active_profile()
        profile_id = prof["_id"]
        market_symbols: dict[str, list[str]] = {
            "crypto": DEFAULT_CRYPTO,
            "stock_id": DEFAULT_STOCKS,
            "etf": DEFAULT_ETF,
            "stock_us": DEFAULT_STOCK_US,
            "gold_silver": DEFAULT_GOLD_SILVER,
            "commodity": DEFAULT_COMMODITY,
            "forex": DEFAULT_FOREX,
        }
        for market, symbols in market_symbols.items():
            if not symbols:
                continue
            try:
                snaps = await md_get_batch(market, symbols, "1h")
            except Exception:
                continue
            for s in snaps:
                candles = s.get("candles") or []
                ticker = s.get("ticker") or {}
                price = ticker.get("price")
                if not candles or price is None:
                    continue
                sig = compute_signal(candles, market)
                try:
                    await record_signal(
                        db,
                        profile_id=profile_id,
                        market=market,
                        symbol=s["symbol"],
                        timeframe="1h",
                        action=sig.get("action", "HOLD"),
                        label=sig.get("label", "HOLD"),
                        confidence=int(sig.get("confidence", 0)),
                        price_at_signal=float(price),
                    )
                except Exception:
                    continue
    except Exception:
        # Never crash startup on seed failure.
        pass


@app.on_event("startup")
async def _startup_bootstrap() -> None:
    # Schedule in the background — do not await, so cold-start latency
    # stays low. Any failure is swallowed inside `_bootstrap_indexes`.
    asyncio.create_task(_bootstrap_indexes())
    # v8.0.9 — Seed signals so the WR-based Premium ranking has data on
    # fresh deploys.
    asyncio.create_task(_bootstrap_signals_seed())
    # v8.1.3 — Load Binance + Bitget spot universes into memory so
    # /api/search can match ANY listed pair (MOODENG, POPCAT, CAT, etc.)
    # without waiting on hard-coded map updates. Non-blocking. Refreshes
    # itself every 6 hours in _load_universe_refresh_loop.
    asyncio.create_task(_load_universe_refresh_loop())
    # v8.3.0 — Start daily push notification scheduler (7 slots, WIB).
    _start_push_scheduler()
    # v8.12.47 — Destructive startup migrations removed to satisfy
    # deployment safety policy (no auto-deletion on boot). The TTL
    # indexes on push_history + market_briefs already exist in prod
    # MongoDB from previous deploys and remain functional. To (re)create
    # them or run the WR reset, use the dedicated admin endpoints:
    #   POST /api/admin/startup-migrations  (X-Admin-Token required)
    _start_market_brief_scheduler()
    # Warm-start: if no brief exists yet (fresh deploy or 48h TTL evicted
    # everything), generate one in the background so the News tab isn't
    # empty for first-time users.
    asyncio.create_task(_brief_warm_start())
    # v9.4.0 — ASI-Bot scheduler: soft-bracket watcher, open-PnL refresh,
    # and Full-Auto scanner. Safe to start even if no users have keys yet.
    _start_asi_scheduler()


# --------------- Push scheduler wiring (v8.3.0) ---------------
# Kept as module-level state so `_shutdown` can stop it cleanly.

_push_scheduler_state: dict[str, object] = {"scheduler": None}


async def _scheduler_dashboard_fetch(market: str) -> list[dict[str, object]]:
    """Return dashboard rows for a market — used by the push scheduler
    to pick the top BUY/LONG signal of the day.
    """
    try:
        # Reuse the same builder that /api/dashboard/batch uses. `full=True`
        # so we don't filter to only Premium — the scheduler still wants
        # coverage when Premium is empty.
        resp = await _build_dashboard_response(
            market=market,
            timeframe="1h",
            sort="confidence",
            full=True,
            min_confidence=0,
            min_wr=0.0,
            region=None,
        )
        return [a.model_dump() for a in resp.assets]
    except Exception as e:
        logger.warning("scheduler dashboard fetch failed for %s: %s", market, e)
        return []


async def _scheduler_news_fetch(market: str) -> list[dict[str, object]]:
    try:
        items = await get_news(market, limit=3)
        return [i.model_dump() if hasattr(i, "model_dump") else dict(i) for i in items]
    except Exception as e:
        logger.warning("scheduler news fetch failed for %s: %s", market, e)
        return []


def _start_push_scheduler() -> None:
    if _push_scheduler_state.get("scheduler"):
        return
    try:
        sched = build_scheduler(
            db=db,
            get_dashboard=_scheduler_dashboard_fetch,
            get_news=_scheduler_news_fetch,
        )
        sched.start()
        _push_scheduler_state["scheduler"] = sched
        logger.info("push scheduler started with %d jobs", len(sched.get_jobs()))
    except Exception as e:
        # Never crash the app because the scheduler couldn't start.
        logger.exception("failed to start push scheduler: %s", e)


# --------------- ASI-Bot scheduler (v9.4.0) ---------------

async def _asi_signal_fetcher(market: str, symbol: str) -> dict[str, Any] | None:
    """Return a dashboard-grade signal for Full-Auto execution.

    Pulls from the SAME pipeline used by /api/dashboard so Full-Auto
    stays in-sync with what users see on screen.
    """
    try:
        resp = await _build_dashboard_response(
            market=market, timeframe="1h", sort="confidence",
            full=True, min_confidence=70, min_wr=70.0, region=None,
        )
        for a in resp.assets:
            if a.symbol.upper() != symbol.upper():
                continue
            d = a.model_dump()
            action = (d.get("action") or "").upper()
            side = "BUY" if action in ("BUY", "LONG") else (
                "SELL" if action in ("SELL", "SHORT") else None
            )
            if not side:
                return None
            entry = d.get("entry") or d.get("price")
            sl = d.get("stop_loss")
            tps = [t for t in (d.get("take_profit"), d.get("take_profit_2"),
                                d.get("take_profit_3")) if t]
            if not (entry and sl and tps):
                return None
            return {
                "side": side, "entry": entry, "stop_loss": sl,
                "take_profits": tps,
                "confidence": int(d.get("confidence") or 0),
            }
        return None
    except Exception as e:  # noqa: BLE001
        logger.debug("asi signal fetch %s/%s failed: %s", market, symbol, e)
        return None


def _start_asi_scheduler() -> None:
    if _asi_scheduler_state.get("scheduler"):
        return
    try:
        sch = ASIScheduler(db=db, signal_fetcher=_asi_signal_fetcher)
        sch.start()
        _asi_scheduler_state["scheduler"] = sch
        logger.info("ASI-Bot scheduler started")
    except Exception as e:
        logger.exception("failed to start ASI scheduler: %s", e)


@app.on_event("shutdown")
async def _shutdown() -> None:
    # Stop push scheduler first so its jobs don't try to talk to a closed
    # Mongo/HTTP client during teardown.
    sched = _push_scheduler_state.get("scheduler")
    if sched is not None:
        try:
            sched.shutdown(wait=False)  # type: ignore[union-attr]
        except Exception:
            pass
    # v8.7.1 — Also stop the Market Brief scheduler.
    bsched = _brief_scheduler_state.get("scheduler")
    if bsched is not None:
        try:
            bsched.shutdown(wait=False)  # type: ignore[union-attr]
        except Exception:
            pass
    # v9.4.0 — Stop ASI-Bot scheduler.
    asi_sch = _asi_scheduler_state.get("scheduler")
    if asi_sch is not None:
        try:
            await asi_sch.stop()  # type: ignore[union-attr]
        except Exception:
            pass
    from market_data import close_http_client
    await close_http_client()
    client.close()


# --------------- Market Brief scheduler (v8.7.1) ---------------

_brief_scheduler_state: dict[str, object] = {"scheduler": None}


async def _brief_dashboard_batch_fetch(markets: list[str]) -> dict[str, Any]:
    """Return a `{market: {assets, premium_count}}` dict for the brief
    LLM prompt. Uses the same builder as /api/dashboard/batch.
    """
    out: dict[str, Any] = {}
    for m in markets:
        try:
            resp = await _build_dashboard_response(
                market=m,
                timeframe="1h",
                sort="confidence",
                full=False,
                min_confidence=85,
                min_wr=70.0,
                region=None,
            )
            out[m] = {
                "assets": [a.model_dump() for a in resp.assets[:20]],
                "premium_count": resp.premium_count,
            }
        except Exception as e:
            logger.warning("brief dashboard fetch failed for %s: %s", m, e)
            out[m] = {"assets": [], "premium_count": 0}
    return out


async def _brief_news_fetch(market_key: str = "all") -> list[dict[str, Any]]:
    """Return top news across all markets for the brief LLM prompt."""
    try:
        items = await get_news(market_key, limit=10)
        return [i.model_dump() if hasattr(i, "model_dump") else dict(i) for i in items]
    except Exception as e:
        logger.warning("brief news fetch failed: %s", e)
        return []


async def _brief_run_job() -> None:
    """Scheduled cron job: generate & persist a Market Brief."""
    try:
        await generate_and_store_brief(db, _brief_dashboard_batch_fetch, _brief_news_fetch)
    except Exception as e:
        logger.exception("scheduled market brief generation failed: %s", e)


async def _brief_warm_start() -> None:
    """Generate an initial brief if none exists (first deploy / TTL wipe).

    Wait 30s so heavy startup tasks (index build, universe load) settle.
    """
    try:
        await asyncio.sleep(30)
        existing = await db.market_briefs.find_one(sort=[("generated_at", -1)])
        if existing:
            logger.info("brief warm-start skipped: existing brief %s", existing.get("_id"))
            return
        logger.info("brief warm-start: no existing brief, generating one now")
        await _brief_run_job()
    except Exception as e:
        logger.warning("brief warm-start failed: %s", e)


def _start_market_brief_scheduler() -> None:
    if _brief_scheduler_state.get("scheduler"):
        return
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger
        import pytz
        wib = pytz.timezone("Asia/Jakarta")
        sched = AsyncIOScheduler(timezone=wib)
        # Morning brief — 06:00 WIB (right after US close, pre-Asia session)
        sched.add_job(
            _brief_run_job,
            trigger=CronTrigger(hour=6, minute=0, timezone=wib),
            id="market_brief_morning",
            max_instances=1, coalesce=True, misfire_grace_time=1800,
            replace_existing=True,
        )
        # Evening brief — 18:00 WIB (post-EU open, mid US-day)
        sched.add_job(
            _brief_run_job,
            trigger=CronTrigger(hour=18, minute=0, timezone=wib),
            id="market_brief_evening",
            max_instances=1, coalesce=True, misfire_grace_time=1800,
            replace_existing=True,
        )
        sched.start()
        _brief_scheduler_state["scheduler"] = sched
        logger.info("market brief scheduler started with %d jobs", len(sched.get_jobs()))
    except Exception as e:
        logger.exception("failed to start market brief scheduler: %s", e)
