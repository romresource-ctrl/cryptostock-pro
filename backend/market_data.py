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
    "AVAX": "AVAXUSDT",
    "USDT": "USDCUSDT",
    "ASTER": "ASTERUSDT", "BNB": "BNBUSDT", "XRP": "XRPUSDT",
    "SOL": "SOLUSDT", "DOGE": "DOGEUSDT", "PEPE": "PEPEUSDT",
    "SUI": "SUIUSDT", "ADA": "ADAUSDT", "TRX": "TRXUSDT",
    "LTC": "LTCUSDT", "LINK": "LINKUSDT", "HBAR": "HBARUSDT",
    "SHIB": "SHIBUSDT", "DOT": "DOTUSDT", "BCH": "BCHUSDT",
    "SAND": "SANDUSDT", "ALGO": "ALGOUSDT", "XAUT": "PAXGUSDT",
}

# IDX (Indonesia) stocks -> Yahoo Finance with .JK suffix
STOCK_YAHOO_MAP: dict[str, str] = {
    "BBCA": "BBCA.JK", "BBRI": "BBRI.JK", "BMRI": "BMRI.JK",
    "TPIA": "TPIA.JK", "ADRO": "ADRO.JK", "DEWA": "DEWA.JK",
    "ASII": "ASII.JK", "EMTK": "EMTK.JK", "ADMR": "ADMR.JK",
    "BRMS": "BRMS.JK", "PANI": "PANI.JK", "CBRE": "CBRE.JK",
    "RAJA": "RAJA.JK", "PTRO": "PTRO.JK", "INET": "INET.JK",
    "ANTM": "ANTM.JK", "MBMA": "MBMA.JK", "MDKA": "MDKA.JK",
    "TLKM": "TLKM.JK", "AMMN": "AMMN.JK", "PGEO": "PGEO.JK",
    "SIDO": "SIDO.JK", "UNVR": "UNVR.JK",
}

# ETFs -> Yahoo Finance (no suffix, listed in USD)
ETF_YAHOO_MAP: dict[str, str] = {
    "QQQ": "QQQ", "VOO": "VOO", "VTI": "VTI", "ARKK": "ARKK",
    "SMH": "SMH", "TLT": "TLT", "IBIT": "IBIT", "FBTC": "FBTC",
    "ARKB": "ARKB", "BITO": "BITO", "ETHE": "ETHE", "ETHA": "ETHA",
    "SCHD": "SCHD", "VYM": "VYM", "INDA": "INDA", "EWJ": "EWJ",
    "XLF": "XLF", "XLE": "XLE", "XBI": "XBI", "EIDO": "EIDO",
    "BND": "BND", "LQD": "LQD",
}

# US stocks -> Yahoo Finance (renamed to "world_stocks" market — kept map name for backward compat)
STOCK_US_YAHOO_MAP: dict[str, str] = {
    "AAPL": "AAPL", "MSFT": "MSFT", "NVDA": "NVDA", "GOOGL": "GOOGL",
    "AMZN": "AMZN", "TSLA": "TSLA", "META": "META", "SPCX": "SPCX",
    "AMD": "AMD", "ASML": "ASML", "TSMC": "TSM", "ARM": "ARM",
    "PLTR": "PLTR", "SNOW": "SNOW", "CRWD": "CRWD", "ADBE": "ADBE",
    "AVGO": "AVGO", "ANET": "ANET", "DELL": "DELL", "MSTR": "MSTR",
    "BABA": "BABA", "TCEHY": "TCEHY", "PDD": "PDD", "BIDU": "BIDU",
    "JD": "JD", "SHOP": "SHOP", "NU": "NU", "AZN": "AZN",
    # Indices (world stock indices, tickers Yahoo)
    "US30": "^DJI", "NAS100": "^IXIC", "SPX500": "^GSPC",
    "JP225": "^N225", "HK50": "^HSI", "GER40": "^GDAXI",
    "UK100": "^FTSE", "IDX30": "^JKSE",
    # Extra world stocks per v3.0.1 request
    "HOOD": "HOOD", "COIN": "COIN", "INTC": "INTC", "SPY": "SPY",
    "MU": "MU", "QCOM": "QCOM", "ORCL": "ORCL", "DIS": "DIS",
    "UBER": "UBER", "CSCO": "CSCO", "HD": "HD", "SOXL": "SOXL",
    "MRVL": "MRVL", "WMT": "WMT", "JPM": "JPM", "V": "V",
    "BRK-B": "BRK-B", "IBM": "IBM", "NOW": "NOW", "CRM": "CRM",
    "AMAT": "AMAT", "NFLX": "NFLX", "COST": "COST", "EBAY": "EBAY",
    "ZM": "ZM", "DKNG": "DKNG", "RIVN": "RIVN", "GME": "GME",
    "TQQQ": "TQQQ", "SQQQ": "SQQQ", "CAT": "CAT", "TXN": "TXN",
    "SMCI": "SMCI", "LRCX": "LRCX", "KLAC": "KLAC", "SONY": "SONY",
    "LLY": "LLY", "NVO": "NVO", "PYPL": "PYPL", "RKLB": "RKLB",
}

# Gold / Silver / Precious metals -> Yahoo Finance FX/commodity symbols
GOLD_SILVER_YAHOO_MAP: dict[str, str] = {
    "XAU/USD": "GC=F",   # Gold futures (proxy for spot)
    "XAG/USD": "SI=F",   # Silver futures
    "XPT/USD": "PL=F",   # Platinum
    "XPD/USD": "PA=F",   # Palladium
}

# Commodities -> Yahoo Finance futures symbols
COMMODITY_YAHOO_MAP: dict[str, str] = {
    "WTI":     "CL=F",   # WTI Crude Oil
    "BRENT":   "BZ=F",   # Brent Crude Oil
    "NATGAS":  "NG=F",   # Natural Gas
    "CORN":    "ZC=F",   # Corn
    "COFFEE":  "KC=F",   # Coffee Beans
    "SUGAR":   "SB=F",   # Sugar
    "COPPER":  "HG=F",   # Copper
    "WHEAT":   "ZW=F",   # Wheat
}

# Forex -> Yahoo Finance FX symbols (XXX=X or XXXYYY=X)
FOREX_YAHOO_MAP: dict[str, str] = {
    "EUR/USD": "EURUSD=X",
    "GBP/USD": "GBPUSD=X",
    "USD/JPY": "JPY=X",
    "AUD/USD": "AUDUSD=X",
    "EUR/GBP": "EURGBP=X",
    "EUR/JPY": "EURJPY=X",
    "USD/IDR": "IDR=X",
    "USD/TRY": "TRY=X",
    "USD/ZAR": "ZAR=X",
    "USD/CNY": "CNY=X",
    "USD/RUB": "RUB=X",
    "NZD/USD": "NZDUSD=X",
}

# Map app timeframe -> (binance_interval, yahoo_range, yahoo_interval, candles_needed)
TIMEFRAME_MAP: dict[str, dict[str, Any]] = {
    "1m":  {"binance": "1m",  "yahoo_range": "1d",  "yahoo_interval": "1m",  "limit": 100},
    "3m":  {"binance": "3m",  "yahoo_range": "1d",  "yahoo_interval": "5m",  "limit": 100},
    "5m":  {"binance": "5m",  "yahoo_range": "1d",  "yahoo_interval": "5m",  "limit": 100},
    "15m": {"binance": "15m", "yahoo_range": "5d",  "yahoo_interval": "15m", "limit": 100},
    "30m": {"binance": "30m", "yahoo_range": "5d",  "yahoo_interval": "30m", "limit": 100},
    "1h":  {"binance": "1h",  "yahoo_range": "1mo", "yahoo_interval": "60m", "limit": 100},
    "3h":  {"binance": "2h",  "yahoo_range": "1mo", "yahoo_interval": "60m", "limit": 100},
    "6h":  {"binance": "6h",  "yahoo_range": "3mo", "yahoo_interval": "1d",  "limit": 100},
    "12h": {"binance": "12h", "yahoo_range": "3mo", "yahoo_interval": "1d",  "limit": 100},
    "18h": {"binance": "12h", "yahoo_range": "6mo", "yahoo_interval": "1d",  "limit": 100},
    "24h": {"binance": "1d",  "yahoo_range": "6mo", "yahoo_interval": "1d",  "limit": 100},
    "7d":  {"binance": "1d",  "yahoo_range": "1y",  "yahoo_interval": "1wk", "limit": 100},
    "14d": {"binance": "1d",  "yahoo_range": "2y",  "yahoo_interval": "1wk", "limit": 100},
    "30d": {"binance": "1d",  "yahoo_range": "5y",  "yahoo_interval": "1mo", "limit": 100},
}

BINANCE_BASE = "https://data-api.binance.vision"
YAHOO_BASE = "https://query1.finance.yahoo.com"
OKX_BASE = "https://www.okx.com"

# Symbols that should be fetched from OKX instead of Binance
# (e.g. HYPE / Hyperliquid is not listed on Binance spot API).
CRYPTO_OKX_MAP: dict[str, str] = {
    "HYPE": "HYPE-USDT",
}

# OKX timeframe mapping (OKX uses uppercase H/D, lowercase m for minutes)
OKX_BAR_MAP: dict[str, str] = {
    "15m": "15m", "30m": "30m", "1h": "1H", "2h": "2H", "6h": "6H",
    "12h": "12H", "1d": "1D",
}


async def _fetch_okx_klines(client: httpx.AsyncClient, symbol: str, interval: str, limit: int) -> list[dict[str, float]]:
    pair = CRYPTO_OKX_MAP.get(symbol)
    if not pair:
        return []
    bar = OKX_BAR_MAP.get(interval, "1H")
    try:
        r = await client.get(
            f"{OKX_BASE}/api/v5/market/candles",
            params={"instId": pair, "bar": bar, "limit": str(min(limit, 300))},
            timeout=10.0,
        )
        r.raise_for_status()
        data = r.json()
        rows = data.get("data") or []
        # OKX returns newest-first; reverse to oldest-first for charting parity with Binance.
        rows = list(reversed(rows))
        return [
            {
                "t": int(k[0]),
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
            }
            for k in rows
        ]
    except Exception:
        return []


async def _fetch_okx_ticker(client: httpx.AsyncClient, symbol: str) -> dict[str, float] | None:
    pair = CRYPTO_OKX_MAP.get(symbol)
    if not pair:
        return None
    try:
        r = await client.get(
            f"{OKX_BASE}/api/v5/market/ticker",
            params={"instId": pair},
            timeout=8.0,
        )
        r.raise_for_status()
        d = (r.json().get("data") or [None])[0]
        if not d:
            return None
        last = float(d["last"])
        open24 = float(d.get("open24h") or last)
        change_pct = ((last - open24) / open24 * 100.0) if open24 else 0.0
        return {
            "price": last,
            "change_pct_24h": change_pct,
            "volume_24h": float(d.get("volCcy24h") or 0.0),
            "high_24h": float(d.get("high24h") or 0.0),
            "low_24h": float(d.get("low24h") or 0.0),
        }
    except Exception:
        return None


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
    # Route to OKX for symbols not listed on Binance public API
    if symbol in CRYPTO_OKX_MAP:
        async with httpx.AsyncClient() as client:
            ticker, klines = await asyncio.gather(
                _fetch_okx_ticker(client, symbol),
                _fetch_okx_klines(client, symbol, tf["binance"], tf["limit"]),
            )
        if not ticker and not klines:
            return None
        return {"symbol": symbol, "market": "crypto", "ticker": ticker or {}, "candles": klines}
    async with httpx.AsyncClient() as client:
        ticker, klines = await asyncio.gather(
            _fetch_binance_ticker(client, symbol),
            _fetch_binance_klines(client, symbol, tf["binance"], tf["limit"]),
        )
    if not ticker and not klines:
        return None
    return {"symbol": symbol, "market": "crypto", "ticker": ticker or {}, "candles": klines}


async def get_stock_snapshot(symbol: str, timeframe: str, market: str = "stock_id") -> dict[str, Any] | None:
    tf = TIMEFRAME_MAP.get(timeframe, TIMEFRAME_MAP["1h"])
    if market == "stock_id":
        sym_map = STOCK_YAHOO_MAP
    elif market == "etf":
        sym_map = ETF_YAHOO_MAP
    elif market in ("stock_us", "world_stocks"):
        sym_map = STOCK_US_YAHOO_MAP
    elif market == "gold_silver":
        sym_map = GOLD_SILVER_YAHOO_MAP
    elif market == "commodity":
        sym_map = COMMODITY_YAHOO_MAP
    elif market == "forex":
        sym_map = FOREX_YAHOO_MAP
    else:
        sym_map = STOCK_YAHOO_MAP
    yahoo_sym = sym_map.get(symbol)
    if not yahoo_sym:
        return None
    async with httpx.AsyncClient() as client:
        data = await _fetch_yahoo_chart_by_symbol(client, yahoo_sym, tf["yahoo_range"], tf["yahoo_interval"])
    if not data:
        return None
    return {"symbol": symbol, "market": market, "ticker": data["ticker"], "candles": data["candles"]}


async def _fetch_yahoo_chart_by_symbol(client: httpx.AsyncClient, yahoo_sym: str, range_: str, interval: str) -> dict[str, Any] | None:
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
                "t": int(t) * 1000, "open": float(o), "high": float(hi),
                "low": float(lo), "close": float(c), "volume": float(v or 0),
            })
        last = candles[-1] if candles else None
        prev_close = float(meta.get("chartPreviousClose") or (candles[-2]["close"] if len(candles) >= 2 else (last["close"] if last else 0)))
        price = float(meta.get("regularMarketPrice") or (last["close"] if last else 0))
        change_pct = ((price - prev_close) / prev_close * 100.0) if prev_close else 0.0
        return {
            "candles": candles,
            "ticker": {
                "price": price, "change_pct_24h": change_pct,
                "volume_24h": float(meta.get("regularMarketVolume") or 0),
                "high_24h": float(meta.get("regularMarketDayHigh") or (last["high"] if last else 0)),
                "low_24h": float(meta.get("regularMarketDayLow") or (last["low"] if last else 0)),
            },
        }
    except Exception:
        return None


async def get_batch(market: str, symbols: list[str], timeframe: str) -> list[dict[str, Any]]:
    """Fetch many symbols concurrently. Returns only successful results."""
    if market == "crypto":
        results = await asyncio.gather(*[get_crypto_snapshot(s, timeframe) for s in symbols], return_exceptions=True)
    else:
        results = await asyncio.gather(*[get_stock_snapshot(s, timeframe, market) for s in symbols], return_exceptions=True)
    out: list[dict[str, Any]] = []
    for r in results:
        if isinstance(r, dict):
            out.append(r)
    return out
