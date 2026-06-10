"""Live RSS news feed aggregator.

Fetches multiple public RSS sources concurrently (no API key needed),
parses with feedparser, and exposes:
  - get_news(market) -> list[NewsItem]   (cached ~15min)
  - get_news_for_symbol(symbol, market) -> filtered list

The result is also fed into the AI ensemble prompt as real-time context.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import feedparser
import httpx

log = logging.getLogger("aitrade.news")

CRYPTO_FEEDS: list[tuple[str, str]] = [
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("CoinTelegraph", "https://cointelegraph.com/rss"),
    ("Decrypt", "https://decrypt.co/feed"),
    ("CryptoPanic", "https://cryptopanic.com/news/rss/"),
    ("Bitcoin Magazine", "https://bitcoinmagazine.com/.rss/full/"),
]

STOCK_FEEDS: list[tuple[str, str]] = [
    ("Bisnis.com Market", "https://market.bisnis.com/rss"),
    ("Kontan Investasi", "https://investasi.kontan.co.id/rss"),
    ("CNBC Indonesia Market", "https://www.cnbcindonesia.com/market/rss"),
    ("Investing.com Indonesia", "https://id.investing.com/rss/news.rss"),
]

GLOBAL_FEEDS: list[tuple[str, str]] = [
    ("Yahoo Finance Top", "https://finance.yahoo.com/news/rssindex"),
]

_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_CACHE_TTL_SEC = 300  # 5 min (aggressive refresh)


def _extract_image(entry: Any) -> str | None:
    """Best-effort RSS image extraction across multiple feed conventions."""
    get = (lambda k: entry.get(k)) if isinstance(entry, dict) else (lambda k: getattr(entry, k, None))
    # media:content / media:thumbnail
    for key in ("media_content", "media_thumbnail"):
        media = get(key)
        if isinstance(media, list) and media:
            for m in media:
                url = (m or {}).get("url") if isinstance(m, dict) else None
                if url and isinstance(url, str) and url.startswith(("http://", "https://")):
                    return url
    # enclosures
    enc = get("enclosures")
    if isinstance(enc, list):
        for e in enc:
            d = e if isinstance(e, dict) else {}
            t = (d.get("type") or "").lower()
            url = d.get("href") or d.get("url")
            if url and (t.startswith("image/") or any(url.lower().endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"))):
                return url
    # image
    img = get("image")
    if isinstance(img, dict):
        url = img.get("href") or img.get("url")
        if url:
            return url
    # Look inside summary/description for first <img src>
    for key in ("summary", "description", "content"):
        body = get(key)
        if isinstance(body, list) and body:
            body = body[0].get("value", "") if isinstance(body[0], dict) else str(body[0])
        if isinstance(body, str) and body:
            m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', body, re.IGNORECASE)
            if m:
                u = m.group(1)
                if u.startswith(("http://", "https://")):
                    return u
    return None


def _clean_html(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"&nbsp;", " ", s)
    s = re.sub(r"&amp;", "&", s)
    s = re.sub(r"&quot;", '"', s)
    s = re.sub(r"&#39;|&apos;", "'", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _parse_date(entry: Any) -> str | None:
    for attr in ("published", "updated", "pubDate"):
        v = entry.get(attr) if isinstance(entry, dict) else getattr(entry, attr, None)
        if v:
            try:
                dt = parsedate_to_datetime(v)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc).isoformat()
            except Exception:
                pass
    return None


async def _fetch_one(client: httpx.AsyncClient, source: str, url: str) -> list[dict[str, Any]]:
    try:
        r = await client.get(url, timeout=8.0, headers={"User-Agent": "Mozilla/5.0 AITradePro/1.0"})
        if r.status_code != 200:
            return []
        # feedparser is sync — run in thread
        parsed = await asyncio.to_thread(feedparser.parse, r.text)
        items: list[dict[str, Any]] = []
        for e in parsed.entries[:15]:
            title = _clean_html(e.get("title", "")) if isinstance(e, dict) else _clean_html(getattr(e, "title", ""))
            link = e.get("link", "") if isinstance(e, dict) else getattr(e, "link", "")
            summary = (
                e.get("summary", "") if isinstance(e, dict) else getattr(e, "summary", "")
            ) or (
                e.get("description", "") if isinstance(e, dict) else getattr(e, "description", "")
            )
            if not title:
                continue
            items.append({
                "source": source,
                "title": title,
                "url": link,
                "summary": _clean_html(summary)[:280],
                "published": _parse_date(e),
                "image": _extract_image(e),
            })
        return items
    except Exception as ex:
        log.warning("RSS fetch failed for %s: %s", source, ex)
        return []


async def _fetch_feeds(feeds: list[tuple[str, str]]) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(follow_redirects=True) as client:
        tasks = [_fetch_one(client, src, url) for src, url in feeds]
        results = await asyncio.gather(*tasks, return_exceptions=False)
    flat: list[dict[str, Any]] = []
    for r in results:
        flat.extend(r)
    # Sort newest first
    flat.sort(key=lambda x: x.get("published") or "", reverse=True)
    return flat


async def get_news(market: str = "all", limit: int = 40) -> list[dict[str, Any]]:
    """Return cached aggregated news. market in {crypto, stock, all}."""
    cache_key = f"news:{market}"
    now = time.time()
    cached = _CACHE.get(cache_key)
    if cached and (now - cached[0]) < _CACHE_TTL_SEC:
        return cached[1][:limit]

    if market == "crypto":
        feeds = CRYPTO_FEEDS + GLOBAL_FEEDS
    elif market == "stock":
        feeds = STOCK_FEEDS + GLOBAL_FEEDS
    else:
        feeds = CRYPTO_FEEDS + STOCK_FEEDS + GLOBAL_FEEDS

    items = await _fetch_feeds(feeds)
    _CACHE[cache_key] = (now, items)
    return items[:limit]


# Symbol aliases for headline filtering
_CRYPTO_ALIASES: dict[str, list[str]] = {
    "BTC": ["bitcoin", "btc"],
    "ETH": ["ethereum", "eth"],
    "BNB": ["bnb", "binance coin"],
    "XRP": ["xrp", "ripple"],
    "SOL": ["solana", "sol"],
    "DOGE": ["dogecoin", "doge"],
    "PEPE": ["pepe"],
    "SUI": ["sui"],
    "ADA": ["cardano", "ada"],
    "TRX": ["tron", "trx"],
    "LTC": ["litecoin", "ltc"],
    "LINK": ["chainlink", "link"],
    "HBAR": ["hedera", "hbar"],
    "SHIB": ["shiba", "shib"],
    "DOT": ["polkadot", "dot"],
    "BCH": ["bitcoin cash", "bch"],
    "SAND": ["sandbox", "sand"],
    "ALGO": ["algorand", "algo"],
    "XAUT": ["tether gold", "xaut", "paxg"],
    "USDT": ["tether", "usdt", "stablecoin"],
    "HYPE": ["hyperliquid", "hype"],
    "ASTER": ["aster"],
}
_STOCK_ALIASES: dict[str, list[str]] = {
    "BBCA": ["bca", "bank central asia", "bbca"],
    "BBRI": ["bri", "bank rakyat", "bbri"],
    "BMRI": ["bank mandiri", "mandiri", "bmri"],
    "TPIA": ["chandra asri", "tpia"],
    "ADRO": ["adaro", "adro"],
    "DEWA": ["darma henwa", "dewa"],
    "ASII": ["astra international", "astra", "asii"],
    "EMTK": ["elang mahkota", "emtek", "emtk"],
    "ADMR": ["adaro minerals", "admr"],
    "BRMS": ["bumi resources minerals", "brms"],
    "PANI": ["pantai indah kapuk", "pani"],
    "CBRE": ["cibadak", "cbre"],
    "RAJA": ["rukun raharja", "raja"],
    "PTRO": ["petrosea", "ptro"],
    "INET": ["mnc digital", "inet"],
    "ANTM": ["aneka tambang", "antam", "antm"],
    "MBMA": ["merdeka battery", "mbma"],
    "MDKA": ["merdeka copper gold", "mdka"],
}


async def get_news_for_symbol(symbol: str, market: str, limit: int = 8) -> list[dict[str, Any]]:
    """Return news whose title/summary contains any of the symbol's aliases."""
    aliases = (_CRYPTO_ALIASES if market == "crypto" else _STOCK_ALIASES).get(symbol.upper(), [symbol.lower()])
    all_items = await get_news(market, limit=80)
    matches: list[dict[str, Any]] = []
    seen: set[str] = set()
    for it in all_items:
        text = f"{it.get('title','')} {it.get('summary','')}".lower()
        if any(a in text for a in aliases):
            key = it.get("title", "")[:120]
            if key in seen:
                continue
            seen.add(key)
            matches.append(it)
            if len(matches) >= limit:
                break
    # Fallback: include top macro/global headlines if no symbol-specific hits
    if not matches:
        matches = all_items[:limit]
    return matches
