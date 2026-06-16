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
from fastapi import APIRouter, FastAPI, Header, HTTPException, Query
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

DEFAULT_CRYPTO = ["BTC", "ETH", "HYPE", "AVAX", "USDT", "ASTER", "BNB", "XRP", "SOL", "DOGE", "PEPE",
                  "SUI", "ADA", "TRX", "LTC", "LINK", "HBAR", "SHIB", "DOT", "BCH", "SAND", "ALGO", "XAUT"]
DEFAULT_STOCKS = ["BBCA", "BBRI", "BMRI", "TPIA", "ADRO", "DEWA", "ASII", "EMTK", "ADMR",
                  "BRMS", "PANI", "CBRE", "RAJA", "PTRO", "INET", "ANTM", "MBMA", "MDKA",
                  "TLKM", "AMMN", "PGEO", "SIDO", "UNVR"]
DEFAULT_ETF = ["QQQ", "VOO", "VTI", "ARKK", "SMH", "TLT", "IBIT", "FBTC", "ARKB", "BITO",
               "ETHE", "ETHA", "SCHD", "VYM", "INDA", "EWJ", "XLF", "XLE", "XBI", "EIDO", "BND", "LQD"]
DEFAULT_STOCK_US = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "TSLA", "META", "AMD", "ASML",
                    "TSMC", "ARM", "PLTR", "SNOW", "CRWD", "ADBE", "AVGO", "ANET", "DELL",
                    "MSTR", "BABA", "TCEHY", "PDD", "BIDU", "JD", "SHOP", "NU", "AZN", "SPCX"]

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
    is_premium = (
        sig["action"] != "HOLD"
        and sig["confidence"] >= min_conf
        and wr is not None
        and wr >= min_wr
    )
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
    market: Literal["crypto", "stock", "etf", "stock_id", "stock_us"] = Query("crypto"),
    timeframe: str = Query("1h"),
    sort: Literal["default", "premium", "confidence", "wr"] = Query("default"),
    premium_only: bool = Query(False),
    min_confidence: int = Query(85, ge=0, le=100),
    min_wr: float = Query(70.0, ge=0.0, le=100.0),
    full: bool = Query(False),
) -> DashboardResponse:
    if timeframe not in TIMEFRAME_MAP:
        raise HTTPException(400, f"Invalid timeframe. Use one of {TIMEFRAMES}")
    # Backward-compat: "stock" -> "stock_id"
    eff_market = "stock_id" if market == "stock" else market

    prof = await _get_active_profile()
    if full:
        symbols = {
            "crypto": DEFAULT_CRYPTO,
            "stock_id": DEFAULT_STOCKS,
            "etf": DEFAULT_ETF,
            "stock_us": DEFAULT_STOCK_US,
        }.get(eff_market, [])
        profile_name = "Semua Aset"
        profile_id = "all"
    else:
        symbols = prof.get("crypto") if eff_market == "crypto" else prof.get("stocks")
        symbols = symbols or []
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
    market: Literal["crypto", "stock", "etf", "stock_id", "stock_us"],
    symbol: str,
    timeframe: str = "1h",
) -> ChartResponse:
    if timeframe not in TIMEFRAME_MAP:
        raise HTTPException(400, "Invalid timeframe")
    eff_market = "stock_id" if market == "stock" else market
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
    market: Literal["crypto", "stock", "etf", "stock_id", "stock_us"],
    symbol: str,
    timeframe: str = "1h",
) -> AnalyzeResponse:
    if timeframe not in TIMEFRAME_MAP:
        raise HTTPException(400, "Invalid timeframe")
    eff_market = "stock_id" if market == "stock" else market
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

    # Cache last analysis
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
    return AnalyzeResponse(
        symbol=symbol, market=eff_market, timeframe=timeframe,
        price=float(price), technical=technical,
        consensus=consensus, models=result["models"],
        news_used=news,
        generated_at=_now_iso(),
    )


@api.get("/asset/{market}/{symbol}/track-record")
async def asset_track_record(
    market: Literal["crypto", "stock", "etf", "stock_id", "stock_us"],
    symbol: str,
) -> dict:
    eff_market = "stock_id" if market == "stock" else market
    return await get_track_record(db, eff_market, symbol.upper())


# -------- News --------

@api.get("/news", response_model=NewsResponse)
async def news_global(
    market: Literal["crypto", "stock", "etf", "stock_id", "stock_us", "all"] = Query("all"),
    limit: int = Query(40, ge=1, le=80),
) -> NewsResponse:
    eff_market = "stock_id" if market == "stock" else market
    items = await get_news(eff_market, limit=limit)
    return NewsResponse(market=eff_market, items=[NewsItem(**i) for i in items], fetched_at=_now_iso())


@api.get("/asset/{market}/{symbol}/news", response_model=NewsResponse)
async def news_for_asset(
    market: Literal["crypto", "stock", "etf", "stock_id", "stock_us"],
    symbol: str,
    limit: int = Query(10, ge=1, le=30),
) -> NewsResponse:
    eff_market = "stock_id" if market == "stock" else market
    items = await get_news_for_symbol(symbol.upper(), eff_market, limit=limit)
    return NewsResponse(market=eff_market, items=[NewsItem(**i) for i in items], fetched_at=_now_iso())


# -------- App wiring --------

@api.post("/auth/record-login")
async def record_login(payload: LoginRecordPayload) -> dict:
    """Called by the main app after a successful unlock.

    The server re-verifies the unlock code so spam / forged calls can't
    pollute the `logged_users` collection.
    """
    email = payload.email.strip().lower()
    code = payload.code.strip().upper()
    expected = _compute_unlock_code(email)
    if not email or not expected or expected != code:
        raise HTTPException(401, "Invalid email or unlock code")
    now = _now_iso()
    res = await db.logged_users.find_one({"_id": email}, {"_id": 0, "login_count": 1})
    if res:
        await db.logged_users.update_one(
            {"_id": email},
            {"$set": {"last_seen": now}, "$inc": {"login_count": 1}},
        )
    else:
        await db.logged_users.insert_one({
            "_id": email,
            "email": email,
            "unlocked_at": now,
            "last_seen": now,
            "login_count": 1,
        })
    return {"ok": True}


@api.get("/admin/users", response_model=LoggedUsersResponse)
async def admin_list_users(x_admin_token: str | None = Header(default=None)) -> LoggedUsersResponse:
    """List all users who have successfully unlocked the app. Admin-only."""
    expected = os.environ.get("ADMIN_TOKEN", "")
    if not expected or x_admin_token != expected:
        raise HTTPException(403, "Forbidden")
    docs: list[LoggedUser] = []
    cursor = db.logged_users.find(
        {},
        {"_id": 0, "email": 1, "unlocked_at": 1, "last_seen": 1, "login_count": 1},
    ).sort("last_seen", -1)
    async for d in cursor:
        docs.append(LoggedUser(
            email=d.get("email", ""),
            unlocked_at=d.get("unlocked_at", ""),
            last_seen=d.get("last_seen", ""),
            login_count=int(d.get("login_count", 1)),
        ))
    return LoggedUsersResponse(total=len(docs), users=docs)


@api.delete("/admin/users/{email}")
async def admin_revoke_user(email: str, x_admin_token: str | None = Header(default=None)) -> dict:
    """Revoke a user — removes them from the logged_users collection.

    NOTE: This does NOT prevent re-login with the same code. To permanently
    revoke an account you must also rotate UNLOCK_SECRET, which invalidates
    all codes globally.
    """
    expected = os.environ.get("ADMIN_TOKEN", "")
    if not expected or x_admin_token != expected:
        raise HTTPException(403, "Forbidden")
    target = email.strip().lower()
    res = await db.logged_users.delete_one({"_id": target})
    if res.deleted_count == 0:
        raise HTTPException(404, "User not found")
    return {"ok": True, "revoked": target}


app.include_router(api)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


# NOTE: no @app.on_event("startup") MongoDB seed — kept lazy so the API can
# accept traffic immediately even while the Atlas connection is warming up.
# Seeding happens on first /api/profiles or /api/dashboard call.


@app.on_event("shutdown")
async def _shutdown() -> None:
    client.close()
