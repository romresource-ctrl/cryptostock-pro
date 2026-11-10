"""
AITrade Pro backend — server.py (Full updated version with working /predict, /analyze, & Risk/Target Profit UI)
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
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

DASHBOARD_CACHE_TTL = float(os.environ.get("DASHBOARD_CACHE_TTL_SEC", "60"))
DASHBOARD_STALE_MAX = float(os.environ.get("DASHBOARD_STALE_MAX_SEC", "120"))

_TF_SECONDS: dict[str, int] = {
    "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "3h": 7200, "6h": 21600, "12h": 43200, "18h": 43200,
    "24h": 86400, "7d": 86400, "14d": 86400, "30d": 86400,
}

def _candle_boundary(timeframe: str, now: float | None = None) -> int:
    sec = _TF_SECONDS.get(timeframe, 3600)
    t = int(now if now is not None else time.time())
    return (t // sec) * sec

_snapshot_cache: dict[str, tuple[float, int, list[dict]]] = {}
_snapshot_locks: dict[str, asyncio.Lock] = {}
_snapshot_refresh_inflight: dict[str, bool] = {}
_tr_cache: dict[str, tuple[float, dict]] = {}
_tr_locks: dict[str, asyncio.Lock] = {}

AI_SUGGESTIONS_TTL = float(os.environ.get("AI_SUGGESTIONS_TTL_SEC", "60"))
_ai_suggestions_cache: dict[str, tuple[float, dict]] = {}

def _cache_key_snap(market: str, symbols: list[str], timeframe: str) -> str:
    return f"{market}|{timeframe}|{','.join(symbols)}"

def _cache_key_tr(market: str, symbols: list[str]) -> str:
    return f"{market}|{','.join(sorted(symbols))}"

async def _get_snapshots_cached(market: str, symbols: list[str], timeframe: str) -> list[dict]:
    key = _cache_key_snap(market, symbols, timeframe)
    now = time.time()
    boundary = _candle_boundary(timeframe, now)
    hit = _snapshot_cache.get(key)
    if hit:
        age = now - hit[0]
        if hit[1] == boundary:
            if age < DASHBOARD_CACHE_TTL:
                return hit[2]
            if age < DASHBOARD_STALE_MAX:
                if not _snapshot_refresh_inflight.get(key):
                    _snapshot_refresh_inflight[key] = True
                    asyncio.create_task(_refresh_snapshot(key, market, symbols, timeframe))
                return hit[2]
    lock = _snapshot_locks.setdefault(key, asyncio.Lock())
    async with lock:
        hit = _snapshot_cache.get(key)
        if hit and hit[1] == boundary and time.time() - hit[0] < DASHBOARD_CACHE_TTL:
            return hit[2]
        data = await get_batch(market, symbols, timeframe)
        _snapshot_cache[key] = (time.time(), boundary, data)
        return data

async def _refresh_snapshot(key: str, market: str, symbols: list[str], timeframe: str) -> None:
    try:
        data = await get_batch(market, symbols, timeframe)
        if data:
            _snapshot_cache[key] = (time.time(), _candle_boundary(timeframe), data)
    except Exception:
        pass
    finally:
        _snapshot_refresh_inflight.pop(key, None)

async def _get_tr_summary_cached(market: str, symbols: list[str]) -> dict:
    key = _cache_key_tr(market, symbols)
    now = time.time()
    hit = _tr_cache.get(key)
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
client = AsyncIOMotorClient(
    mongo_url,
    serverSelectionTimeoutMS=20000,
    connectTimeoutMS=20000,
    socketTimeoutMS=30000,
    retryWrites=True,
    uuidRepresentation="standard",
)
db = client[os.environ["DB_NAME"]]

from market_data import (  # noqa: E402,F811
    CRYPTO_BINANCE_MAP,
    STOCK_YAHOO_MAP,
    ETF_YAHOO_MAP,
    STOCK_US_YAHOO_MAP,
    GOLD_SILVER_YAHOO_MAP,
    COMMODITY_YAHOO_MAP,
    FOREX_YAHOO_MAP,
)

DEFAULT_CRYPTO = list(CRYPTO_BINANCE_MAP.keys())[:100]
DEFAULT_STOCKS = list(STOCK_YAHOO_MAP.keys())[:50]
DEFAULT_ETF = list(ETF_YAHOO_MAP.keys())[:50]
DEFAULT_STOCK_US = list(STOCK_US_YAHOO_MAP.keys())[:50]
DEFAULT_GOLD_SILVER = list(GOLD_SILVER_YAHOO_MAP.keys())
DEFAULT_COMMODITY = list(COMMODITY_YAHOO_MAP.keys())
DEFAULT_FOREX = list(FOREX_YAHOO_MAP.keys())

def _build_region_index() -> dict[str, list[str]]:
    from market_data import region_from_yahoo_ticker
    idx: dict[str, list[str]] = {}
    for sym, yahoo in STOCK_US_YAHOO_MAP.items():
        r = region_from_yahoo_ticker(yahoo)
        idx.setdefault(r, []).append(sym)
    return idx

STOCK_US_BY_REGION: dict[str, list[str]] = _build_region_index()

FULL_CRYPTO = list(CRYPTO_BINANCE_MAP.keys())
FULL_STOCKS = list(STOCK_YAHOO_MAP.keys())
FULL_ETF = list(ETF_YAHOO_MAP.keys())
FULL_STOCK_US = list(STOCK_US_YAHOO_MAP.keys())
FULL_COMMODITY = list(COMMODITY_YAHOO_MAP.keys())
FULL_FOREX = list(FOREX_YAHOO_MAP.keys())

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

@app.get("/health")
async def _root_health() -> dict[str, str]:
    return {"status": "ok"}

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
    entry_low: float | None = None
    entry_high: float | None = None
    entry_moderate: float | None = None
    entry_aggressive: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    take_profit_2: float | None = None
    take_profit_3: float | None = None
    track_record: TrackRecordMini = Field(default_factory=TrackRecordMini)
    is_premium: bool = False
    region: str | None = None
    risk_reward: float | None = None
    risk_level: str | None = None
    reward_pct: float | None = None
    risk_pct: float | None = None
    late_entry: bool = False

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

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

async def _ensure_seed() -> None:
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
        prof = await db.profiles.find_one({}, {"_id": 1, "name": 1, "crypto": 1, "stocks": 1})
        if prof:
            await db.app_state.replace_one({"_id": "active"}, {"_id": "active", "profile_id": prof["_id"]}, upsert=True)
    if not prof:
        return {"_id": "default", "name": "Default", "crypto": DEFAULT_CRYPTO.copy(), "stocks": DEFAULT_STOCKS.copy()}
    return prof

def _filter_lists(crypto: list[str], stocks: list[str]) -> tuple[list[str], list[str]]:
    c = [s.upper() for s in (crypto or []) if s.upper() in CRYPTO_BINANCE_MAP]
    s = [t.upper() for t in (stocks or []) if t.upper() in STOCK_YAHOO_MAP]
    return c, s

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

def _build_signal(snapshot: dict, tr: dict | None = None, *, min_conf: int = 85, min_wr: float = 70.0, profile: str | None = None, daily_candles: list | None = None, timeframe: str | None = None, freshness_max_candles: int = 8, chase_atr_mult: float = 2.5) -> AssetSignal:
    market = snapshot["market"]
    candles = snapshot.get("candles", [])
    ticker = snapshot.get("ticker", {}) or {}
    sig = compute_signal(
        candles, market, profile=profile, live_price=ticker.get("price"),
        daily_candles=daily_candles, timeframe=timeframe,
        freshness_max_candles=freshness_max_candles,
        chase_atr_mult=chase_atr_mult,
    )
    spark = [c["close"] for c in candles[-30:]] if candles else []
    tr_mini = TrackRecordMini(**(tr or {}))
    wr = tr_mini.wr_30d
    action_ok = sig["action"] != "HOLD"
    conf_ok = sig["confidence"] >= min_conf
    if wr is None:
        is_premium = action_ok and sig["confidence"] >= (min_conf + 3)
    else:
        is_premium = action_ok and conf_ok and wr >= min_wr
    from market_data import region_for_symbol
    region = region_for_symbol(market, snapshot["symbol"])

    risk_reward: float | None = None
    risk_level: str | None = None
    reward_pct: float | None = None
    risk_pct: float | None = None
    
    entry_v = sig.get("entry") or ticker.get("price")
    sl_v = sig.get("stop_loss")
    tp_v = sig.get("take_profit")
    
    if entry_v and sl_v and tp_v and entry_v > 0:
        reward = abs(tp_v - entry_v)
        risk = abs(entry_v - sl_v)
        if risk > 0:
            risk_reward = round(reward / risk, 2)
            reward_pct = round((reward / entry_v) * 100, 2)
            risk_pct = round((risk / entry_v) * 100, 2)
            conf = sig.get("confidence") or 0
            if conf >= 85 and risk_reward >= 2.0:
                risk_level = "Low"
            elif conf >= 70 and risk_reward >= 1.0:
                risk_level = "Medium"
            else:
                risk_level = "High"

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
        entry=entry_v,
        entry_low=sig.get("entry_low"),
        entry_high=sig.get("entry_high"),
        entry_moderate=sig.get("entry_moderate"),
        entry_aggressive=sig.get("entry_aggressive"),
        stop_loss=sl_v,
        take_profit=tp_v,
        take_profit_2=sig.get("take_profit_2"),
        take_profit_3=sig.get("take_profit_3"),
        track_record=tr_mini,
        is_premium=is_premium,
        region=region,
        risk_reward=risk_reward,
        risk_level=risk_level or "Medium",
        reward_pct=reward_pct or 0.0,
        risk_pct=risk_pct or 0.0,
        late_entry=bool(sig.get("late_entry")),
    )

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
        if not entitled:
            uc = await db.unlock_codes.find_one({"device_id": device_id})
            if uc and not uc.get("revoked", False):
                exp_iso = uc.get("expires_at")
                if not exp_iso:
                    entitled = True
                else:
                    try:
                        entitled = datetime.fromisoformat(exp_iso.replace("Z", "+00:00")) > datetime.now(timezone.utc)
                    except Exception:
                        entitled = False
    if not entitled:
        raise HTTPException(403, "premium_required")

    cache_key = f"{market}|{timeframe}|{profile or 'none'}|{limit}"
    hit = _ai_suggestions_cache.get(cache_key)
    if hit and time.time() - hit[0] < AI_SUGGESTIONS_TTL:
        return hit[1]

    min_conf, min_wr = _threshold_for_market(market)
    resp = await _build_dashboard_response(
        market=market,
        timeframe=timeframe,
        sort="confidence",
        premium_only=False,
        min_confidence=min_conf,
        min_wr=min_wr,
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
    items = [a.model_dump() for a in picks]
    if market == "crypto":
        try:
            from asi_bot.whitelist import binance_perp_tradable
            perps = await binance_perp_tradable()
            if perps is not None:
                for it in items:
                    base = str(it.get("symbol") or "").upper().split("/")[0].split("USDT")[0]
                    it["futures_tradable"] = base in perps
        except Exception:
            pass
    out = {
        "market": market,
        "timeframe": timeframe,
        "profile": profile,
        "engine": engine,
        "count": len(picks),
        "suggestions": items,
        "server_time": _now_iso(),
    }
    _ai_suggestions_cache[cache_key] = (time.time(), out)
    return out

def _profile_to_model(p: dict) -> Profile:
    return Profile(id=p["_id"], name=p.get("name", "Untitled"), crypto=p.get("crypto", []), stocks=p.get("stocks", []))

@api.get("/")
async def health() -> dict:
    return {"app": "AITrade Pro", "status": "ok", "time": _now_iso()}

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

_MARKET_THRESHOLDS: dict[str, tuple[int, float]] = {
    "crypto":               (70, 55.0),
    "stock_id":             (85, 55.0),
    "stock_us":             (85, 55.0),
    "world_stocks":         (85, 55.0),
    "etf":                  (85, 55.0),
    "gold_silver":          (87, 55.0),
    "commodity":            (87, 55.0),
    "forex":                (85, 55.0),
}

def _threshold_for_market(market: str) -> tuple[int, float]:
    eff = "stock_id" if market == "stock" else market
    return _MARKET_THRESHOLDS.get(eff, (87, 72.0))

@api.get("/dashboard", response_model=DashboardResponse)
async def dashboard(
    market: Literal["crypto", "stock", "etf", "stock_id", "stock_us", "world_stocks", "gold_silver", "commodity", "forex"] = Query("crypto"),
    timeframe: str = Query("1h"),
    sort: Literal["default", "premium", "confidence", "wr"] = Query("default"),
    premium_only: bool = Query(False),
    min_confidence: int | None = Query(None, ge=0, le=100),
    min_wr: float | None = Query(None, ge=0.0, le=100.0),
    full: bool = Query(False),
    region: str | None = Query(None),
    profile: str | None = Query(None),
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
    strict_gates: bool = False,
) -> DashboardResponse:
    eff_market = "stock_id" if market == "stock" else market
    if eff_market == "world_stocks":
        eff_market = "stock_us"

    prof = await _get_active_profile()
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

    if extras and not full:
        full_universe = {
            "crypto": FULL_CRYPTO,
            "stock_id": FULL_STOCKS,
            "etf": FULL_ETF,
            "stock_us": FULL_STOCK_US,
            "gold_silver": DEFAULT_GOLD_SILVER,
            "commodity": FULL_COMMODITY,
            "forex": FULL_FOREX,
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

    _fresh_n = 3 if strict_gates else 8
    _chase_m = 1.5 if strict_gates else 2.5
    assets = []
    for s in ordered:
        assets.append(_build_signal(
            s, tr_summary.get(s["symbol"]),
            min_conf=min_confidence, min_wr=min_wr, profile=profile,
            daily_candles=daily_map.get(s["symbol"]), timeframe=timeframe,
            freshness_max_candles=_fresh_n, chase_atr_mult=_chase_m,
        ))
        await asyncio.sleep(0)

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

_BATCH_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_BATCH_INFLIGHT: dict[str, "asyncio.Task[dict[str, Any]]"] = {}
_BATCH_CACHE_TTL = 60.0
_BATCH_STALE_MAX = 600.0
_BATCH_CACHE_MAX = 64

@api.get("/dashboard/batch")
async def dashboard_batch(
    markets: str = Query("crypto,stock_us,etf,stock_id,gold_silver,commodity,forex"),
    timeframe: str = Query("1h"),
    sort: Literal["default", "premium", "confidence", "wr"] = Query("premium"),
    full: bool = Query(False),
    min_confidence: int | None = Query(None, ge=0, le=100),
    min_wr: float | None = Query(None, ge=0.0, le=100.0),
    region: str | None = Query(None),
    extras: str | None = Query(None),
    profile: str | None = Query(None),
) -> dict[str, Any]:
    if timeframe not in TIMEFRAME_MAP:
        raise HTTPException(400, f"Invalid timeframe. Use one of {TIMEFRAMES}")
    market_keys = [m.strip() for m in markets.split(",") if m.strip()]
    if not market_keys:
        raise HTTPException(400, "markets query must be non-empty")
    known = {"crypto", "stock", "stock_id", "stock_us", "world_stocks",
             "etf", "gold_silver", "commodity", "forex"}
    market_keys = [m for m in market_keys if m in known][:9]

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
            eff = "stock_id" if mk == "stock" else ("stock_us" if mk == "world_stocks" else mk)
            extras_by_market.setdefault(eff, []).append(sym)

    def _cfg(m: str) -> tuple[int, float]:
        d_conf, d_wr = _threshold_for_market(m)
        return (
            min_confidence if min_confidence is not None else d_conf,
            min_wr if min_wr is not None else d_wr,
        )

    extras_norm = ",".join(
        f"{k}:{','.join(sorted(v))}"
        for k, v in sorted(extras_by_market.items())
    )
    cache_key = (
        f"{','.join(sorted(market_keys))}|{timeframe}|{sort}|{int(full)}|"
        f"{min_confidence if min_confidence is not None else '-'}|"
        f"{min_wr if min_wr is not None else '-'}|"
        f"{region or '-'}|{profile or '-'}|{extras_norm}"
    )
    boundary = _candle_boundary(timeframe)
    now = time.time()
    hit = _BATCH_CACHE.get(cache_key)
    same_bar = bool(hit) and int(hit[1].get("_boundary") or 0) == boundary

    def _cached_resp() -> dict[str, Any]:
        resp = dict(hit[1])
        resp.pop("_boundary", None)
        resp["cached"] = True
        return resp

    if same_bar and (now - hit[0]) < _BATCH_CACHE_TTL:
        return _cached_resp()

    async def _compute() -> dict[str, Any]:
        tasks = []
        for m in market_keys:
            c, w = _cfg(m)
            eff_m = "stock_id" if m == "stock" else (
                "stock_us" if m == "world_stocks" else m)
            tasks.append(
                _build_dashboard_response(
                    market=m,
                    timeframe=timeframe,
                    sort=sort,
                    full=full,
                    min_confidence=c,
                    min_wr=w,
                    region=region if m in ("stock_us", "world_stocks") else None,
                    extras=extras_by_market.get(eff_m),
                    profile=profile,
                )
            )
        results = await asyncio.gather(*tasks, return_exceptions=True)
        out: dict[str, Any] = {}
        for m, r in zip(market_keys, results, strict=False):
            if isinstance(r, Exception):
                out[m] = {"error": str(r)[:200], "assets": [],
                          "premium_count": 0}
            else:
                out[m] = r.model_dump()
        payload = {"timeframe": timeframe, "markets": out,
                   "server_time": _now_iso(), "cached": False}
        _BATCH_CACHE[cache_key] = (
            time.time(), {**payload, "_boundary": boundary})
        if len(_BATCH_CACHE) > _BATCH_CACHE_MAX:
            oldest = sorted(_BATCH_CACHE.items(),
                            key=lambda kv: kv[1][0])[:len(_BATCH_CACHE) - _BATCH_CACHE_MAX]
            for k, _ in oldest:
                _BATCH_CACHE.pop(k, None)
        return payload

    task = _BATCH_INFLIGHT.get(cache_key)
    if task is None or task.done():
        task = asyncio.create_task(_compute())
        _BATCH_INFLIGHT[cache_key] = task

        def _clear_inflight(t: asyncio.Task, k: str = cache_key) -> None:
            if _BATCH_INFLIGHT.get(k) is t:
                _BATCH_INFLIGHT.pop(k, None)
        task.add_done_callback(_clear_inflight)
    if same_bar and (now - hit[0]) < _BATCH_STALE_MAX:
        return _cached_resp()
    return await task

_CHART_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_CHART_INFLIGHT: dict[str, "asyncio.Task[dict[str, Any]]"] = {}
_CHART_CACHE_TTL = 60.0
_CHART_CACHE_MAX = 300

async def _build_chart_payload(eff_market: str, symbol: str, timeframe: str,
                               profile: str | None) -> dict[str, Any]:
    snap = await (
        get_crypto_snapshot(symbol, timeframe)
        if eff_market == "crypto"
        else get_stock_snapshot(symbol, timeframe, market=eff_market)
    )
    if not snap:
        raise HTTPException(404, "Symbol not found or upstream data unavailable")
    _daily = None
    if profile in ("scalper", "day", "swing"):
        _daily = await _get_daily_candles(eff_market, symbol)
    sig = compute_signal(
        snap.get("candles", []), eff_market, profile=profile,
        live_price=(snap.get("ticker", {}) or {}).get("price"),
        daily_candles=_daily, timeframe=timeframe,
        freshness_max_candles=8, chase_atr_mult=2.5,
    )
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
    candles = snap.get("candles", [])
    if timeframe == "1h" and len(candles) > 120:
        candles = candles[-120:]
    return {
        "symbol": symbol, "market": eff_market, "timeframe": timeframe,
        "ticker": snap.get("ticker", {}) or {},
        "candles": candles,
        "signal": sig,
    }

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
    if eff_market in ("forex", "gold_silver") and "-" in symbol:
        symbol = symbol.replace("-", "/")
    symbol = symbol.upper()
    cache_key = f"{eff_market}|{symbol}|{timeframe}|{profile or 'none'}"
    now = time.time()
    hit = _CHART_CACHE.get(cache_key)
    if hit and (now - hit[0]) < _CHART_CACHE_TTL:
        return ChartResponse(**hit[1])
    task = _CHART_INFLIGHT.get(cache_key)
    if task is None:
        task = asyncio.create_task(
            _build_chart_payload(eff_market, symbol, timeframe, profile))
        _CHART_INFLIGHT[cache_key] = task
    try:
        payload = await task
    finally:
        if _CHART_INFLIGHT.get(cache_key) is task:
            _CHART_INFLIGHT.pop(cache_key, None)
    if len(_CHART_CACHE) >= _CHART_CACHE_MAX:
        oldest = min(_CHART_CACHE, key=lambda k: _CHART_CACHE[k][0])
        _CHART_CACHE.pop(oldest, None)
    _CHART_CACHE[cache_key] = (time.time(), payload)
    return ChartResponse(**payload)

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
        freshness_max_candles=8, chase_atr_mult=2.5,
    )
    if price is None:
        raise HTTPException(503, "Price unavailable")
        
    news = await get_news_for_symbol(symbol, eff_market, limit=8)
    
    try:
        result = await ensemble_analyze(symbol, eff_market, timeframe, technical, float(price), news=news, lang=lang)
    except Exception as e:
        logger.error(f"Ensemble analyze error: {e}")
        result = {
            "consensus": {
                "action": technical.get("action", "HOLD"),
                "label": technical.get("label", "HOLD"),
                "confidence": technical.get("confidence", 75),
                "reasoning": "Analisis teknikal berhasil dimuat, namun ringkasan AI utama sedang sibuk.",
                "news_factors": [],
                "risk_factors": []
            },
            "models": []
        }

    consensus = result.get("consensus", {})

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

    await db.analyses.replace_one(
        {"_id": f"{eff_market}-{symbol}-{timeframe}"},
        {
            "_id": f"{eff_market}-{symbol}-{timeframe}",
            "symbol": symbol, "market": eff_market, "timeframe": timeframe,
            "price": float(price), "technical": technical,
            "consensus": consensus, "models": result.get("models", []),
            "news_used": news,
            "generated_at": _now_iso(),
        },
        upsert=True,
    )

    if lang == "en":
        narrative_texts: list[str] = []
        ptrs: list[tuple] = []

        cons_reason = consensus.get("reasoning") or consensus.get("rationale") or ""
        if cons_reason:
            narrative_texts.append(cons_reason); ptrs.append(("consensus", "reasoning"))
        cons_summary = consensus.get("summary") or ""
        if cons_summary:
            narrative_texts.append(cons_summary); ptrs.append(("consensus", "summary"))
        cons_tfview = consensus.get("timeframe_view") or ""
        if cons_tfview:
            narrative_texts.append(cons_tfview); ptrs.append(("consensus", "timeframe_view"))

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
        symbol=symbol, 
        market=eff_market, 
        timeframe=timeframe,
        price=float(price), 
        technical=technical,
        consensus=consensus, 
        models=result.get("models", []),
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
    if eff_market in ("forex", "gold_silver") and "-" in symbol:
        symbol = symbol.replace("-", "/")
    return await get_track_record(db, eff_market, symbol.upper())

@api.get("/ai/models")
async def get_ai_models() -> dict[str, Any]:
    from ai_engine import MODELS as _AI_MODELS
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
    profile: str | None = Query(None),
) -> dict[str, Any]:
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

    _ALIAS = {
        "GOLD": "XAU/USD", "SILVER": "XAG/USD",
        "OIL": "WTI", "CRUDE": "WTI", "CRUDEOIL": "WTI",
        "BRENT": "BRENT", "NATGAS": "NATGAS", "GAS": "NATGAS",
        "COPPER": "COPPER", "WHEAT": "WHEAT", "CORN": "CORN", "SUGAR": "SUGAR",
    }
    extra_queries: list[str] = []
    if query in _ALIAS:
        extra_queries.append(_ALIAS[query])
    if "/" not in query and query.isalpha() and len(query) in (6, 7):
        mid = 3
        slashed = f"{query[:mid]}/{query[mid:]}"
        extra_queries.append(slashed)

    market_pools: list[tuple[str, list[str]]] = [
        ("crypto", list(CRYPTO_BINANCE_MAP.keys())),
        ("stock_id", list(STOCK_YAHOO_MAP.keys())),
        ("etf", list(ETF_YAHOO_MAP.keys())),
        ("stock_us", list(STOCK_US_YAHOO_MAP.keys()) + list(STOCK_US_YAHOO_MAP_EXTRA.keys())),
        ("gold_silver", list(GOLD_SILVER_YAHOO_MAP.keys())),
        ("commodity", list(COMMODITY_YAHOO_MAP.keys())),
        ("forex", list(FOREX_YAHOO_MAP.keys())),
    ]

    matches: list[tuple[str, str, int]] = []
    queries_to_scan = [query] + extra_queries
    for market, syms in market_pools:
        for sym in syms:
            s = sym.upper()
            for qv in queries_to_scan:
                if s == qv:
                    matches.append((market, sym, 0))
                    break
                elif s.startswith(qv):
                    matches.append((market, sym, 1))
                    break
                elif qv in s:
                    matches.append((market, sym, 2))
                    break

    seen_crypto = {m[1].upper() for m in matches if m[0] == "crypto"}

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

    had_exact_crypto_before_safety_net = any(
        m[2] == 0 and m[0] == "crypto" for m in matches
    )

    had_exact_match_any_market = any(m[2] == 0 for m in matches)
    if not had_exact_match_any_market and len(query) >= 2 and query.isalnum():
        matches = [("crypto", query, 0)] + matches
        matches = matches[:limit]

    disambiguation: list[dict[str, Any]] = []
    if not had_exact_crypto_before_safety_net and len(query) >= 2 and query.isalnum():
        try:
            from market_data import coingecko_multi_search
            disambiguation = await coingecko_multi_search(query, limit=5)
        except Exception:
            disambiguation = []

    if not matches:
        return {"hits": [], "disambiguation": disambiguation, "query": query}

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

APP_LATEST_VERSION = "10.7.6"
APP_UPDATE_NOTES = {"id": "", "en": ""}
APP_UPDATE_PLAY_URL = (
    "https://play.google.com/store/apps/details?"
    "id=com.cryptostockapps.aicryptostockpro"
)
APP_UPDATE_PROMPT = {
    "title": {
        "id": "Pembaruan Tersedia", "en": "Update Available",
        "ru": "Доступно обновление", "cn": "有可用更新",
    },
    "body": {
        "id": "Pembaruan baru tersedia di Google Play Store.",
        "en": "New Update is available on Google Play Store.",
        "ru": "Новое обновление доступно в Google Play Store.",
        "cn": "Google Play Store 上有新版本可用。",
    },
    "button": {
        "id": "Update Now", "en": "Update Now",
        "ru": "Обновить сейчас", "cn": "立即更新",
    },
    "later": {
        "id": "Nanti", "en": "Later", "ru": "Позже", "cn": "稍后",
    },
    "source_label": {
        "id": "Membuka Google Play Store",
        "en": "Opens Google Play Store",
        "ru": "Открывает Google Play Store",
        "cn": "将打开 Google Play Store",
    },
    "url": APP_UPDATE_PLAY_URL,
    "store_hint": {
        "id": "Google Play", "en": "Google Play",
        "ru": "Google Play", "cn": "Google Play",
    },
}

@api.get("/app-version")
async def app_version() -> dict[str, Any]:
    return {
        "latest_version": APP_LATEST_VERSION,
        "play_store_url": APP_UPDATE_PLAY_URL,
        "notes": APP_UPDATE_NOTES,
        "prompt": APP_UPDATE_PROMPT,
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
    _sym_local = locals().get("symbol")
    if eff_market in ("forex", "gold_silver") and _sym_local and "-" in _sym_local:
        _sym_local = _sym_local.replace("-", "/")
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

class TranslatePayload(BaseModel):
    texts: list[str]
    target_lang: Literal["en", "id"] = "en"

@api.post("/translate")
async def translate_endpoint(payload: TranslatePayload) -> dict:
    out = await translate_many(db, payload.texts, payload.target_lang)
    return {"target_lang": payload.target_lang, "items": out}

@api.post("/auth/verify")
async def auth_verify(payload: dict) -> dict:
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

def _check_admin(x_admin_token: str | None) -> None:
    expected = os.environ.get("ADMIN_TOKEN", "").strip()
    if not expected:
        return
    if x_admin_token != expected:
        raise HTTPException(403, "Forbidden")

@api.post("/admin/generate-code")
async def admin_generate_code(
    payload: dict,
    x_admin_token: str | None = Header(default=None),
) -> dict:
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
    _check_admin(x_admin_token)
    codes = await list_codes(db)
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
    _check_admin(x_admin_token)
    ok = await reset_device_binding(db, code)
    if not ok:
        raise HTTPException(404, "Code not found")
    return {"ok": True, "code": code.upper()}

@api.get("/admin/users", response_model=LoggedUsersResponse)
async def admin_list_users(x_admin_token: str | None = Header(default=None)) -> LoggedUsersResponse:
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
    _check_admin(x_admin_token)
    target = email.strip().lower()
    res = await db.logged_users.delete_one({"_id": target})
    await db.unlock_codes.update_many({"email": target}, {"$set": {"revoked": True}})
    if res.deleted_count == 0:
        raise HTTPException(404, "User not found")
    return {"ok": True, "revoked": target}

class SubscriptionVerifyPayload(BaseModel):
    purchase_token: str
    product_id: str
    package_name: str | None = None
    device_id: str | None = None
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
    if not device_id or not base_plan_id:
        return {"claimed": False}
    row = await db.subscriptions.find_one(
        {"device_id": device_id, "base_plan_id": base_plan_id},
    )
    return {"claimed": bool(row)}

@api.get("/promo/redeemed")
async def promo_redeemed(device_id: str) -> dict[str, Any]:
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
    await db.promo_redemptions.insert_one(
        {"device_id": device_id, "code": code, "redeemed_at": now}
    )
    return {"ok": True, "already": False, "redeemed_at": now}

app.include_router(api)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)