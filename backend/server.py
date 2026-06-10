"""AITrade Pro backend.

Endpoints:
  GET  /api/                       health
  GET  /api/watchlist              get default watchlist (crypto + stock)
  POST /api/watchlist              update watchlist (full replace)
  GET  /api/dashboard              dashboard signals batch (market, timeframe)
  GET  /api/asset/{market}/{symbol}/chart    candles + ticker
  POST /api/asset/{market}/{symbol}/analyze  AI ensemble deep analysis
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, HTTPException, Query
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")
logger = logging.getLogger("aitrade")

mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

DEFAULT_CRYPTO = ["BTC", "ETH", "HYPE", "USDT", "ASTER", "BNB", "XRP", "SOL", "DOGE", "PEPE",
                  "SUI", "ADA", "TRX", "LTC", "LINK", "HBAR", "SHIB", "DOT", "BCH", "SAND", "ALGO", "XAUT"]
DEFAULT_STOCKS = ["BBCA", "BBRI", "BMRI", "TPIA", "ADRO", "DEWA", "ASII", "EMTK", "ADMR",
                  "BRMS", "PANI", "CBRE", "RAJA", "PTRO", "INET", "ANTM", "MBMA", "MDKA"]

WATCHLIST_ID = "default"  # No-login app: single shared watchlist
TIMEFRAMES = ["15m", "30m", "1h", "3h", "6h", "12h", "18h", "24h"]

app = FastAPI(title="AITrade Pro")
api = APIRouter(prefix="/api")


# ---------------- Models ----------------

class WatchlistPayload(BaseModel):
    crypto: list[str] = Field(default_factory=list)
    stocks: list[str] = Field(default_factory=list)


class WatchlistResponse(BaseModel):
    crypto: list[str]
    stocks: list[str]
    available_crypto: list[str]
    available_stocks: list[str]
    timeframes: list[str]


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


class DashboardResponse(BaseModel):
    market: str
    timeframe: str
    server_time: str
    assets: list[AssetSignal]


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


class NewsResponse(BaseModel):
    market: str
    items: list[NewsItem]
    fetched_at: str


# ---------------- Helpers ----------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _get_or_init_watchlist() -> dict:
    doc = await db.watchlist.find_one({"_id": WATCHLIST_ID}, {"_id": 0, "crypto": 1, "stocks": 1})
    if not doc:
        doc = {"crypto": DEFAULT_CRYPTO.copy(), "stocks": DEFAULT_STOCKS.copy()}
        await db.watchlist.replace_one(
            {"_id": WATCHLIST_ID},
            {"_id": WATCHLIST_ID, **doc, "updated_at": _now_iso()},
            upsert=True,
        )
    return doc


def _build_signal(snapshot: dict) -> AssetSignal:
    market = snapshot["market"]
    candles = snapshot.get("candles", [])
    ticker = snapshot.get("ticker", {}) or {}
    sig = compute_signal(candles, market)
    spark = [c["close"] for c in candles[-30:]] if candles else []
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
    )


# ---------------- Routes ----------------

@api.get("/")
async def health() -> dict:
    return {"app": "AITrade Pro", "status": "ok", "time": _now_iso()}


@api.get("/watchlist", response_model=WatchlistResponse)
async def get_watchlist() -> WatchlistResponse:
    doc = await _get_or_init_watchlist()
    return WatchlistResponse(
        crypto=doc.get("crypto", []),
        stocks=doc.get("stocks", []),
        available_crypto=list(CRYPTO_BINANCE_MAP.keys()),
        available_stocks=list(STOCK_YAHOO_MAP.keys()),
        timeframes=TIMEFRAMES,
    )


@api.post("/watchlist", response_model=WatchlistResponse)
async def update_watchlist(payload: WatchlistPayload) -> WatchlistResponse:
    crypto = [s.upper() for s in payload.crypto if s.upper() in CRYPTO_BINANCE_MAP]
    stocks = [s.upper() for s in payload.stocks if s.upper() in STOCK_YAHOO_MAP]
    await db.watchlist.replace_one(
        {"_id": WATCHLIST_ID},
        {"_id": WATCHLIST_ID, "crypto": crypto, "stocks": stocks, "updated_at": _now_iso()},
        upsert=True,
    )
    return WatchlistResponse(
        crypto=crypto,
        stocks=stocks,
        available_crypto=list(CRYPTO_BINANCE_MAP.keys()),
        available_stocks=list(STOCK_YAHOO_MAP.keys()),
        timeframes=TIMEFRAMES,
    )


@api.get("/dashboard", response_model=DashboardResponse)
async def dashboard(
    market: Literal["crypto", "stock"] = Query("crypto"),
    timeframe: str = Query("1h"),
) -> DashboardResponse:
    if timeframe not in TIMEFRAME_MAP:
        raise HTTPException(400, f"Invalid timeframe. Use one of {TIMEFRAMES}")

    doc = await _get_or_init_watchlist()
    symbols = doc.get("crypto") if market == "crypto" else doc.get("stocks")
    symbols = symbols or (DEFAULT_CRYPTO if market == "crypto" else DEFAULT_STOCKS)

    snapshots = await get_batch(market, symbols, timeframe)
    # Keep order matching watchlist
    by_sym = {s["symbol"]: s for s in snapshots}
    ordered = [by_sym[s] for s in symbols if s in by_sym]
    assets = [_build_signal(s) for s in ordered]
    return DashboardResponse(
        market=market, timeframe=timeframe, server_time=_now_iso(), assets=assets
    )


@api.get("/asset/{market}/{symbol}/chart", response_model=ChartResponse)
async def asset_chart(market: Literal["crypto", "stock"], symbol: str, timeframe: str = "1h") -> ChartResponse:
    if timeframe not in TIMEFRAME_MAP:
        raise HTTPException(400, "Invalid timeframe")
    symbol = symbol.upper()
    snap = await (get_crypto_snapshot(symbol, timeframe) if market == "crypto"
                  else get_stock_snapshot(symbol, timeframe))
    if not snap:
        raise HTTPException(404, "Symbol not found or upstream data unavailable")
    sig = compute_signal(snap.get("candles", []), market)
    return ChartResponse(
        symbol=symbol, market=market, timeframe=timeframe,
        ticker=snap.get("ticker", {}) or {},
        candles=snap.get("candles", []),
        signal=sig,
    )


@api.post("/asset/{market}/{symbol}/analyze", response_model=AnalyzeResponse)
async def asset_analyze(market: Literal["crypto", "stock"], symbol: str, timeframe: str = "1h") -> AnalyzeResponse:
    if timeframe not in TIMEFRAME_MAP:
        raise HTTPException(400, "Invalid timeframe")
    symbol = symbol.upper()
    snap = await (get_crypto_snapshot(symbol, timeframe) if market == "crypto"
                  else get_stock_snapshot(symbol, timeframe))
    if not snap:
        raise HTTPException(404, "Symbol not found or upstream data unavailable")
    candles = snap.get("candles", [])
    ticker = snap.get("ticker", {}) or {}
    price = ticker.get("price") or (candles[-1]["close"] if candles else None)
    technical = compute_signal(candles, market)
    if price is None:
        raise HTTPException(503, "Price unavailable")
    # Fetch real-time news headlines for this symbol/market
    news = await get_news_for_symbol(symbol, market, limit=8)
    result = await ensemble_analyze(symbol, market, timeframe, technical, float(price), news=news)
    # Cache last analysis
    await db.analyses.replace_one(
        {"_id": f"{market}-{symbol}-{timeframe}"},
        {
            "_id": f"{market}-{symbol}-{timeframe}",
            "symbol": symbol, "market": market, "timeframe": timeframe,
            "price": float(price), "technical": technical,
            "consensus": result["consensus"], "models": result["models"],
            "news_used": news,
            "generated_at": _now_iso(),
        },
        upsert=True,
    )
    return AnalyzeResponse(
        symbol=symbol, market=market, timeframe=timeframe,
        price=float(price), technical=technical,
        consensus=result["consensus"], models=result["models"],
        news_used=news,
        generated_at=_now_iso(),
    )


@api.get("/news", response_model=NewsResponse)
async def news_global(market: Literal["crypto", "stock", "all"] = Query("all"), limit: int = Query(40, ge=1, le=80)) -> NewsResponse:
    items = await get_news(market, limit=limit)
    return NewsResponse(market=market, items=[NewsItem(**i) for i in items], fetched_at=_now_iso())


@api.get("/asset/{market}/{symbol}/news", response_model=NewsResponse)
async def news_for_asset(market: Literal["crypto", "stock"], symbol: str, limit: int = Query(10, ge=1, le=30)) -> NewsResponse:
    items = await get_news_for_symbol(symbol.upper(), market, limit=limit)
    return NewsResponse(market=market, items=[NewsItem(**i) for i in items], fetched_at=_now_iso())


app.include_router(api)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


@app.on_event("shutdown")
async def _shutdown() -> None:
    client.close()
