"""Market data adapters for crypto (Binance) and Indonesian stocks (Yahoo Finance).

All functions return native Python types; no MongoDB.
"""
from __future__ import annotations

import asyncio
from typing import Any

import httpx

# Crypto symbol -> Binance trading pair (USDT-quoted spot)
CRYPTO_BINANCE_MAP: dict[str, str] = {
    "BTC": "BTCUSDT", "ETH": "ETHUSDT", "HYPE": "HYPEUSDT",
    "USDT": "USDCUSDT",  # stablecoin; show vs USDC
    "ASTER": "ASTERUSDT", "BNB": "BNBUSDT", "XRP": "XRPUSDT",
    "SOL": "SOLUSDT", "DOGE": "DOGEUSDT", "PEPE": "PEPEUSDT",
    "SUI": "SUIUSDT", "ADA": "ADAUSDT", "TRX": "TRXUSDT",
    "LTC": "LTCUSDT", "LINK": "LINKUSDT", "HBAR": "HBARUSDT",
    "SHIB": "SHIBUSDT", "DOT": "DOTUSDT", "BCH": "BCHUSDT",
    "SAND": "SANDUSDT", "ALGO": "ALGOUSDT", "XAUT": "PAXGUSDT",  # XAUT thin liquidity; PAXG proxy for tokenized gold
}

# IDX ticker -> Yahoo Finance symbol
STOCK_YAHOO_MAP: dict[str, str] = {
    "BBCA": "BBCA.JK", "BBRI": "BBRI.JK", "BMRI": "BMRI.JK",
    "TPIA": "TPIA.JK", "ADRO": "ADRO.JK", "DEWA": "DEWA.JK",
    "ASII": "ASII.JK", "EMTK": "EMTK.JK", "ADMR": "ADMR.JK",
    "BRMS": "BRMS.JK", "PANI": "PANI.JK", "CBRE": "CBRE.JK",
    "RAJA": "RAJA.JK", "PTRO": "PTRO.JK", "INET": "INET.JK",
    "ANTM": "ANTM.JK", "MBMA": "MBMA.JK", "MDKA": "MDKA.JK",
}

# Map app timeframe -> (binance_interval, yahoo_range, yahoo_interval, candles_needed)
TIMEFRAME_MAP: dict[str, dict[str, Any]] = {
    "15m": {"binance": "15m", "yahoo_range": "5d", "yahoo_interval": "15m", "limit": 100},
    "30m": {"binance": "30m", "yahoo_range": "5d", "yahoo_interval": "30m", "limit": 100},
    "1h":  {"binance": "1h",  "yahoo_range": "1mo", "yahoo_interval": "60m", "limit": 100},
    "3h":  {"binance": "2h",  "yahoo_range": "1mo", "yahoo_interval": "60m", "limit": 100},
    "6h":  {"binance": "6h",  "yahoo_range": "3mo", "yahoo_interval": "1d", "limit": 100},
    "12h": {"binance": "12h", "yahoo_range": "3mo", "yahoo_interval": "1d", "limit": 100},
    "18h": {"binance": "12h", "yahoo_range": "6mo", "yahoo_interval": "1d", "limit": 100},
    "24h": {"binance": "1d",  "yahoo_range": "6mo", "yahoo_interval": "1d", "limit": 100},
}

BINANCE_BASE = "https://data-api.binance.vision"
YAHOO_BASE = "https://query1.finance.yahoo.com"


async def _fetch_binance_klines(client: httpx.AsyncClient, symbol: str, interval: str, limit: int) -> list[dict[str, float]]:
    pair = CRYPTO_BINANCE_MAP.get(symbol)
    if not pair:
        return []
    try:
        r = await client.get(
            f"{BINANCE_BASE}/api/v3/klines",
            params={"symbol": pair, "interval": interval, "limit": limit},
            timeout=10.0,
        )
        r.raise_for_status()
        raw = r.json()
        return [
            {
                "t": int(k[0]),
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
            }
            for k in raw
        ]
    except Exception:
        return []


async def _fetch_binance_ticker(client: httpx.AsyncClient, symbol: str) -> dict[str, float] | None:
    pair = CRYPTO_BINANCE_MAP.get(symbol)
    if not pair:
        return None
    try:
        r = await client.get(
            f"{BINANCE_BASE}/api/v3/ticker/24hr",
            params={"symbol": pair},
            timeout=8.0,
        )
        r.raise_for_status()
        d = r.json()
        return {
            "price": float(d["lastPrice"]),
            "change_pct_24h": float(d["priceChangePercent"]),
            "volume_24h": float(d["quoteVolume"]),
            "high_24h": float(d["highPrice"]),
            "low_24h": float(d["lowPrice"]),
        }
    except Exception:
        return None


async def _fetch_yahoo_chart(client: httpx.AsyncClient, symbol: str, range_: str, interval: str) -> dict[str, Any] | None:
    yahoo_sym = STOCK_YAHOO_MAP.get(symbol)
    if not yahoo_sym:
        return None
    try:
        r = await client.get(
            f"{YAHOO_BASE}/v8/finance/chart/{yahoo_sym}",
            params={"range": range_, "interval": interval, "includePrePost": "false"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10.0,
        )
        r.raise_for_status()
        data = r.json()
        result = data["chart"]["result"][0]
        meta = result.get("meta", {})
        ts = result.get("timestamp", []) or []
        quote = (result.get("indicators", {}).get("quote") or [{}])[0]
        opens = quote.get("open") or []
        highs = quote.get("high") or []
        lows = quote.get("low") or []
        closes = quote.get("close") or []
        volumes = quote.get("volume") or []
        candles: list[dict[str, float]] = []
        for i, t in enumerate(ts):
            o, hi, lo, c, v = opens[i], highs[i], lows[i], closes[i], volumes[i]
            if None in (o, hi, lo, c):
                continue
            candles.append({
                "t": int(t) * 1000,
                "open": float(o), "high": float(hi), "low": float(lo),
                "close": float(c), "volume": float(v or 0),
            })
        last = candles[-1] if candles else None
        prev_close = float(meta.get("chartPreviousClose") or (candles[-2]["close"] if len(candles) >= 2 else (last["close"] if last else 0)))
        price = float(meta.get("regularMarketPrice") or (last["close"] if last else 0))
        change_pct = ((price - prev_close) / prev_close * 100.0) if prev_close else 0.0
        return {
            "candles": candles,
            "ticker": {
                "price": price,
                "change_pct_24h": change_pct,
                "volume_24h": float(meta.get("regularMarketVolume") or 0),
                "high_24h": float(meta.get("regularMarketDayHigh") or (last["high"] if last else 0)),
                "low_24h": float(meta.get("regularMarketDayLow") or (last["low"] if last else 0)),
            },
        }
    except Exception:
        return None


async def get_crypto_snapshot(symbol: str, timeframe: str) -> dict[str, Any] | None:
    tf = TIMEFRAME_MAP.get(timeframe, TIMEFRAME_MAP["1h"])
    async with httpx.AsyncClient() as client:
        ticker, klines = await asyncio.gather(
            _fetch_binance_ticker(client, symbol),
            _fetch_binance_klines(client, symbol, tf["binance"], tf["limit"]),
        )
    if not ticker and not klines:
        return None
    return {"symbol": symbol, "market": "crypto", "ticker": ticker or {}, "candles": klines}


async def get_stock_snapshot(symbol: str, timeframe: str) -> dict[str, Any] | None:
    tf = TIMEFRAME_MAP.get(timeframe, TIMEFRAME_MAP["1h"])
    async with httpx.AsyncClient() as client:
        data = await _fetch_yahoo_chart(client, symbol, tf["yahoo_range"], tf["yahoo_interval"])
    if not data:
        return None
    return {"symbol": symbol, "market": "stock", "ticker": data["ticker"], "candles": data["candles"]}


async def get_batch(market: str, symbols: list[str], timeframe: str) -> list[dict[str, Any]]:
    """Fetch many symbols concurrently. Returns only successful results."""
    if market == "crypto":
        fetcher = get_crypto_snapshot
    else:
        fetcher = get_stock_snapshot
    results = await asyncio.gather(*[fetcher(s, timeframe) for s in symbols], return_exceptions=True)
    out: list[dict[str, Any]] = []
    for r in results:
        if isinstance(r, dict):
            out.append(r)
    return out
