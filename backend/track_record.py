"""AI signal history & track record.

Every `/analyze` call appends a record. We lazily evaluate signals once the
expected horizon (a few candles forward) has passed by comparing the current
price with the price at signal time.

A signal is "hit" if:
  - BUY  : pct_change >= +1.0%
  - SELL : pct_change <= -1.0%
  - HOLD : abs(pct_change) <  1.0%
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from market_data import get_crypto_snapshot, get_stock_snapshot

log = logging.getLogger("aitrade.track")

# Minimum minutes between signal creation and evaluation per timeframe
EVAL_WAIT_MINUTES: dict[str, int] = {
    "15m": 90,    # ~6 candles
    "30m": 150,   # ~5 candles
    "1h": 240,    # ~4 candles
    "3h": 720,    # ~4 candles
    "6h": 1440,   # 24h = 4 candles
    "12h": 2160,  # 36h = 3 candles
    "18h": 3240,  # 54h
    "24h": 4320,  # 72h = 3 candles
}

HIT_THRESHOLD_PCT = 1.0


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def record_signal(
    db: AsyncIOMotorDatabase,
    *,
    profile_id: str,
    market: str,
    symbol: str,
    timeframe: str,
    action: str,
    label: str,
    confidence: int,
    price_at_signal: float,
) -> None:
    """Insert a new signal row into the `signals` collection."""
    await db.signals.insert_one({
        "_id": str(uuid.uuid4()),
        "profile_id": profile_id,
        "market": market,
        "symbol": symbol.upper(),
        "timeframe": timeframe,
        "action": action,
        "label": label,
        "confidence": int(confidence),
        "price_at_signal": float(price_at_signal),
        "created_at": _now(),
        "evaluated": False,
        "evaluation": None,
    })


def _is_hit(action: str, pct_change: float) -> bool:
    a = action.upper()
    if a == "BUY":
        return pct_change >= HIT_THRESHOLD_PCT
    if a == "SELL":
        return pct_change <= -HIT_THRESHOLD_PCT
    return abs(pct_change) < HIT_THRESHOLD_PCT


async def _fetch_current_price(market: str, symbol: str) -> float | None:
    snap = await (
        get_crypto_snapshot(symbol, "1h") if market == "crypto"
        else get_stock_snapshot(symbol, "1h")
    )
    if not snap:
        return None
    t = snap.get("ticker") or {}
    p = t.get("price")
    if p is None:
        candles = snap.get("candles") or []
        if candles:
            p = candles[-1]["close"]
    return float(p) if p is not None else None


async def evaluate_pending(db: AsyncIOMotorDatabase, market: str | None = None, symbol: str | None = None) -> int:
    """Find pending signals whose evaluation horizon has passed, fetch the
    current price, mark hit/miss.

    Returns count evaluated.
    """
    now = _now()
    query: dict[str, Any] = {"evaluated": False}
    if market:
        query["market"] = market
    if symbol:
        query["symbol"] = symbol.upper()

    cursor = db.signals.find(query)
    # Group by (market, symbol) to dedupe network calls
    pending: list[dict[str, Any]] = []
    async for doc in cursor:
        tf = doc.get("timeframe", "1h")
        wait = EVAL_WAIT_MINUTES.get(tf, 240)
        created = doc.get("created_at")
        if not isinstance(created, datetime):
            continue
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if (now - created) < timedelta(minutes=wait):
            continue
        pending.append(doc)

    if not pending:
        return 0

    # Fetch current price once per (market, symbol)
    price_cache: dict[tuple[str, str], float | None] = {}
    evaluated = 0
    for doc in pending:
        key = (doc["market"], doc["symbol"])
        if key not in price_cache:
            price_cache[key] = await _fetch_current_price(*key)
        cur = price_cache[key]
        if cur is None:
            continue
        p0 = float(doc.get("price_at_signal") or 0)
        if p0 <= 0:
            continue
        pct = (cur - p0) / p0 * 100.0
        hit = _is_hit(doc.get("action", "HOLD"), pct)
        await db.signals.update_one(
            {"_id": doc["_id"]},
            {"$set": {
                "evaluated": True,
                "evaluation": {
                    "price_after": cur,
                    "pct_change": round(pct, 4),
                    "hit": bool(hit),
                    "evaluated_at": now,
                },
            }},
        )
        evaluated += 1
    return evaluated


async def get_track_record(
    db: AsyncIOMotorDatabase, market: str, symbol: str,
) -> dict[str, Any]:
    """Return win-rate stats for one symbol."""
    await evaluate_pending(db, market=market, symbol=symbol)
    now = _now()
    cutoff_7d = now - timedelta(days=7)
    cutoff_30d = now - timedelta(days=30)

    docs: list[dict[str, Any]] = []
    cursor = db.signals.find(
        {"market": market, "symbol": symbol.upper(), "evaluated": True},
        {"_id": 0, "action": 1, "label": 1, "confidence": 1, "evaluation": 1, "created_at": 1, "timeframe": 1, "price_at_signal": 1},
    ).sort("created_at", -1).limit(120)
    async for d in cursor:
        docs.append(d)

    def _wr(items: list[dict[str, Any]]) -> dict[str, Any]:
        total = len(items)
        hits = sum(1 for x in items if (x.get("evaluation") or {}).get("hit"))
        return {
            "total": total,
            "hits": hits,
            "win_rate": round(hits / total * 100.0, 1) if total else None,
        }

    recent: list[dict[str, Any]] = []
    for d in docs[:8]:
        created = d.get("created_at")
        if isinstance(created, datetime):
            d["created_at"] = (
                created.replace(tzinfo=timezone.utc) if created.tzinfo is None else created
            ).isoformat()
        recent.append(d)

    in_7d = [d for d in docs if _to_dt(d.get("created_at")) >= cutoff_7d]
    in_30d = [d for d in docs if _to_dt(d.get("created_at")) >= cutoff_30d]

    return {
        "symbol": symbol.upper(),
        "market": market,
        "win_rate_7d": _wr(in_7d),
        "win_rate_30d": _wr(in_30d),
        "win_rate_all": _wr(docs),
        "recent_signals": recent,
    }


def _to_dt(v: Any) -> datetime:
    if isinstance(v, datetime):
        return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        except Exception:
            pass
    return datetime(1970, 1, 1, tzinfo=timezone.utc)


async def get_track_record_summary(
    db: AsyncIOMotorDatabase, market: str, symbols: list[str],
) -> dict[str, dict[str, Any]]:
    """Return per-symbol win-rate summary for many symbols (no fresh eval).
    Used by dashboard so it's fast.
    """
    if not symbols:
        return {}
    syms = [s.upper() for s in symbols]
    now = _now()
    cutoff_30d = now - timedelta(days=30)
    cutoff_7d = now - timedelta(days=7)
    pipeline = [
        {"$match": {
            "market": market,
            "symbol": {"$in": syms},
            "evaluated": True,
            "created_at": {"$gte": cutoff_30d},
        }},
        {"$project": {
            "symbol": 1,
            "created_at": 1,
            "hit": "$evaluation.hit",
        }},
    ]
    by_symbol: dict[str, dict[str, list[int]]] = {s: {"d7": [], "d30": []} for s in syms}
    async for d in db.signals.aggregate(pipeline):
        s = d["symbol"]
        if s not in by_symbol:
            continue
        created = d.get("created_at")
        if isinstance(created, datetime):
            created = created.replace(tzinfo=timezone.utc) if created.tzinfo is None else created
            hit_int = 1 if d.get("hit") else 0
            if created >= cutoff_7d:
                by_symbol[s]["d7"].append(hit_int)
            if created >= cutoff_30d:
                by_symbol[s]["d30"].append(hit_int)

    out: dict[str, dict[str, Any]] = {}
    for s, buckets in by_symbol.items():
        d7 = buckets["d7"]
        d30 = buckets["d30"]
        out[s] = {
            "wr_7d": round(sum(d7) / len(d7) * 100.0, 1) if d7 else None,
            "n_7d": len(d7),
            "wr_30d": round(sum(d30) / len(d30) * 100.0, 1) if d30 else None,
            "n_30d": len(d30),
        }
    return out
