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
from typing import Literal

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

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")
logger = logging.getLogger("aitrade")

# ---- Dashboard in-memory cache (TTL) ----
# Caches expensive batch snapshots (Binance & Yahoo Finance) and track-record summaries
# to avoid hammering upstream APIs on every dashboard refresh.
import asyncio  # noqa: E402

DASHBOARD_CACHE_TTL = float(os.environ.get("DASHBOARD_CACHE_TTL_SEC", "45"))
_snapshot_cache: dict[str, tuple[float, list[dict]]] = {}
_snapshot_locks: dict[str, asyncio.Lock] = {}
_tr_cache: dict[str, tuple[float, dict]] = {}
_tr_locks: dict[str, asyncio.Lock] = {}


def _cache_key_snap(market: str, symbols: list[str], timeframe: str) -> str:
    return f"{market}|{timeframe}|{','.join(symbols)}"


def _cache_key_tr(market: str, symbols: list[str]) -> str:
    return f"{market}|{','.join(sorted(symbols))}"


async def _get_snapshots_cached(market: str, symbols: list[str], timeframe: str) -> list[dict]:
    key = _cache_key_snap(market, symbols, timeframe)
    now = time.time()
    hit = _snapshot_cache.get(key)
    if hit and now - hit[0] < DASHBOARD_CACHE_TTL:
        return hit[1]
    lock = _snapshot_locks.setdefault(key, asyncio.Lock())
    async with lock:
        hit = _snapshot_cache.get(key)
        if hit and time.time() - hit[0] < DASHBOARD_CACHE_TTL:
            return hit[1]
        data = await get_batch(market, symbols, timeframe)
        _snapshot_cache[key] = (time.time(), data)
        return data


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
from market_data import (  # noqa: E402
    CRYPTO_BINANCE_MAP,
    STOCK_YAHOO_MAP,
    ETF_YAHOO_MAP,
    STOCK_US_YAHOO_MAP,
    GOLD_SILVER_YAHOO_MAP,
    COMMODITY_YAHOO_MAP,
    FOREX_YAHOO_MAP,
)

DEFAULT_CRYPTO = list(CRYPTO_BINANCE_MAP.keys())
DEFAULT_STOCKS = list(STOCK_YAHOO_MAP.keys())
DEFAULT_ETF = list(ETF_YAHOO_MAP.keys())
DEFAULT_STOCK_US = list(STOCK_US_YAHOO_MAP.keys())
DEFAULT_GOLD_SILVER = list(GOLD_SILVER_YAHOO_MAP.keys())
DEFAULT_COMMODITY = list(COMMODITY_YAHOO_MAP.keys())
DEFAULT_FOREX = list(FOREX_YAHOO_MAP.keys())

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


# --- App Version Enforcement (RELAXED) ---
# Old APKs (v2.0.x) do NOT call backend for auth (offline SHA-256), and current
# APK v2.1.2 does not yet send X-App-Version header. So we ONLY enforce when
# the header IS present but reports a version LOWER than MIN_APP_VERSION.
# Requests without header are passed through to keep v2.1.2 working. Old APKs
# are effectively neutralized because:
#   1. Their offline SHA-256 codes are absent from unlock_codes DB (migration)
#   2. Attempts to record login hit removed endpoint → auth stays invalid
from fastapi import Request  # noqa: E402
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
    stop_loss: float | None = None
    take_profit: float | None = None
    track_record: TrackRecordMini = Field(default_factory=TrackRecordMini)
    is_premium: bool = False


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


def _build_signal(snapshot: dict, tr: dict | None = None, *, min_conf: int = 85, min_wr: float = 70.0) -> AssetSignal:
    market = snapshot["market"]
    candles = snapshot.get("candles", [])
    ticker = snapshot.get("ticker", {}) or {}
    sig = compute_signal(candles, market)
    spark = [c["close"] for c in candles[-30:]] if candles else []
    tr_mini = TrackRecordMini(**(tr or {}))
    wr = tr_mini.wr_30d
    action_ok = sig["action"] != "HOLD"
    conf_ok = sig["confidence"] >= min_conf
    # Primary: action OK, confidence OK, AND historical WR >= threshold
    # Fallback (for markets without enough recorded history yet): allow premium
    # when confidence is very high (>= 90) even if WR is unavailable.
    if wr is None:
        is_premium = action_ok and sig["confidence"] >= max(min_conf, 90)
    else:
        is_premium = action_ok and conf_ok and wr >= min_wr
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
        stop_loss=sig["stop_loss"],
        take_profit=sig["take_profit"],
        track_record=tr_mini,
        is_premium=is_premium,
    )


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

@api.get("/dashboard", response_model=DashboardResponse)
async def dashboard(
    market: Literal["crypto", "stock", "etf", "stock_id", "stock_us", "world_stocks", "gold_silver", "commodity", "forex"] = Query("crypto"),
    timeframe: str = Query("1h"),
    sort: Literal["default", "premium", "confidence", "wr"] = Query("default"),
    premium_only: bool = Query(False),
    min_confidence: int = Query(85, ge=0, le=100),
    min_wr: float = Query(70.0, ge=0.0, le=100.0),
    full: bool = Query(False),
) -> DashboardResponse:
    if timeframe not in TIMEFRAME_MAP:
        raise HTTPException(400, f"Invalid timeframe. Use one of {TIMEFRAMES}")
    # Backward-compat: "stock" -> "stock_id", "world_stocks" -> "stock_us" internally
    eff_market = "stock_id" if market == "stock" else market
    if eff_market == "world_stocks":
        eff_market = "stock_us"

    prof = await _get_active_profile()
    if full:
        symbols = {
            "crypto": DEFAULT_CRYPTO,
            "stock_id": DEFAULT_STOCKS,
            "etf": DEFAULT_ETF,
            "stock_us": DEFAULT_STOCK_US,
            "gold_silver": DEFAULT_GOLD_SILVER,
            "commodity": DEFAULT_COMMODITY,
            "forex": DEFAULT_FOREX,
        }.get(eff_market, [])
        profile_name = "Semua Aset"
        profile_id = "all"
    else:
        symbols = prof.get("crypto") if eff_market == "crypto" else prof.get("stocks")
        symbols = symbols or []
        # For new asset categories (gold, commodity, forex, etf, us stocks) always show defaults
        if not symbols and eff_market in ("etf", "stock_us", "gold_silver", "commodity", "forex"):
            symbols = {
                "etf": DEFAULT_ETF, "stock_us": DEFAULT_STOCK_US,
                "gold_silver": DEFAULT_GOLD_SILVER, "commodity": DEFAULT_COMMODITY,
                "forex": DEFAULT_FOREX,
            }[eff_market]
        profile_id = prof["_id"]
        profile_name = prof.get("name", "Default")
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
    assets = [
        _build_signal(s, tr_summary.get(s["symbol"]), min_conf=min_confidence, min_wr=min_wr)
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


# -------- Asset detail --------

@api.get("/asset/{market}/{symbol}/chart", response_model=ChartResponse)
async def asset_chart(
    market: Literal["crypto", "stock", "etf", "stock_id", "stock_us", "world_stocks", "gold_silver", "commodity", "forex"],
    symbol: str,
    timeframe: str = "1h",
) -> ChartResponse:
    if timeframe not in TIMEFRAME_MAP:
        raise HTTPException(400, "Invalid timeframe")
    eff_market = "stock_id" if market == "stock" else market
    if eff_market == "world_stocks":
        eff_market = "stock_us"
    symbol = symbol.upper()
    snap = await (
        get_crypto_snapshot(symbol, timeframe)
        if eff_market == "crypto"
        else get_stock_snapshot(symbol, timeframe, market=eff_market)
    )
    if not snap:
        raise HTTPException(404, "Symbol not found or upstream data unavailable")
    sig = compute_signal(snap.get("candles", []), eff_market)
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
    lang: Literal["id", "en"] = "id",
) -> AnalyzeResponse:
    if timeframe not in TIMEFRAME_MAP:
        raise HTTPException(400, "Invalid timeframe")
    eff_market = "stock_id" if market == "stock" else market
    if eff_market == "world_stocks":
        eff_market = "stock_us"
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
    technical = compute_signal(candles, eff_market)
    if price is None:
        raise HTTPException(503, "Price unavailable")
    news = await get_news_for_symbol(symbol, eff_market, limit=8)
    result = await ensemble_analyze(symbol, eff_market, timeframe, technical, float(price), news=news)
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
    return await get_track_record(db, eff_market, symbol.upper())


# -------- News --------

@api.get("/news", response_model=NewsResponse)
async def news_global(
    market: Literal["crypto", "stock", "etf", "stock_id", "stock_us", "world_stocks", "gold_silver", "commodity", "forex", "all"] = Query("all"),
    limit: int = Query(40, ge=1, le=80),
    lang: Literal["id", "en"] = Query("id"),
) -> NewsResponse:
    eff_market = "stock_id" if market == "stock" else market
    if eff_market == "world_stocks":
        eff_market = "stock_us"
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


@app.get("/api/privacy", include_in_schema=False)
async def privacy_policy_html() -> HTMLResponse:
    """PUBLIC Privacy Policy page — required by Google Play Console for store
    submission. Google reviewers must be able to open this URL without login.
    """
    try:
        path = os.path.join(os.path.dirname(__file__), "static", "privacy.html")
        with open(path, "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    except Exception:
        return HTMLResponse("<h1>Privacy policy not deployed</h1>", status_code=404)


@app.get("/api/terms", include_in_schema=False)
async def terms_html() -> HTMLResponse:
    """PUBLIC Terms of Service page — required for Play Console subscription apps."""
    try:
        path = os.path.join(os.path.dirname(__file__), "static", "terms.html")
        with open(path, "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    except Exception:
        return HTMLResponse("<h1>Terms of service not deployed</h1>", status_code=404)


@app.get("/api/data-deletion", include_in_schema=False)
async def data_deletion_html() -> HTMLResponse:
    """PUBLIC Account/Data Deletion Request page — required by Google Play Console
    Data Safety section (users must have a URL to request account deletion).
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


@app.on_event("shutdown")
async def _shutdown() -> None:
    client.close()
