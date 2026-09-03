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
    """Insert a new signal row into the `signals` collection.

    v8.12.29 — Skip HOLD signals: they aren't real trades so they
    should never enter the win-rate stats. Prior versions were writing
    them and later filtering — which still polluted the "18 signals
    historis" count on the frontend.
    """
    if action.upper() == "HOLD":
        return
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


# v8.7.0 — 3-way outcome classification for the WR history popup.
#   WIN   : signal target was hit (as before).
#   LOSS  : price moved against the signal by >= HIT_THRESHOLD (i.e. SL zone).
#   BE    : price stayed within ±HIT_THRESHOLD (break-even / chop).
def _classify_outcome(action: str, pct_change: float) -> str:
    a = action.upper()
    if a == "BUY":
        if pct_change >= HIT_THRESHOLD_PCT:
            return "WIN"
        if pct_change <= -HIT_THRESHOLD_PCT:
            return "LOSS"
        return "BE"
    if a == "SELL":
        if pct_change <= -HIT_THRESHOLD_PCT:
            return "WIN"
        if pct_change >= HIT_THRESHOLD_PCT:
            return "LOSS"
        return "BE"
    # HOLD: WIN when it stayed flat, LOSS if it broke out either way.
    if abs(pct_change) < HIT_THRESHOLD_PCT:
        return "WIN"
    return "LOSS"


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
        outcome = _classify_outcome(doc.get("action", "HOLD"), pct)
        await db.signals.update_one(
            {"_id": doc["_id"]},
            {"$set": {
                "evaluated": True,
                "evaluation": {
                    "price_after": cur,
                    "pct_change": round(pct, 4),
                    "hit": bool(hit),
                    "outcome": outcome,
                    "evaluated_at": now,
                },
            }},
        )
        evaluated += 1
    return evaluated


async def get_track_record(
    db: AsyncIOMotorDatabase, market: str, symbol: str,
    *, history_limit: int = 500,
) -> dict[str, Any]:
    """Return win-rate stats + full history for one symbol.

    v8.7.0 — Returns:
      * win_rate_7d / 30d / all buckets (with wins/losses/be counts)
      * full `history` list (up to `history_limit`) with per-signal outcome
        (WIN/LOSS/BE), created_at, timeframe, action, price, pct_change.
        Frontend consumes this to render the tappable WR history popup.
    """
    await evaluate_pending(db, market=market, symbol=symbol)
    now = _now()
    cutoff_7d = now - timedelta(days=7)
    cutoff_30d = now - timedelta(days=30)

    docs: list[dict[str, Any]] = []
    cursor = db.signals.find(
        {
            "market": market,
            "symbol": symbol.upper(),
            "evaluated": True,
            # v8.12.29 — Exclude HOLD signals from track record.
            # HOLD = "no trade" → it never had a real entry/SL/TP, so
            # measuring "did the price move up or down after HOLD" is
            # meaningless. Users complained that HOLD signals were
            # being labelled WIN/LOSS/SL/BE in the history modal.
            "action": {"$in": ["BUY", "SELL"]},
        },
        {"_id": 0, "action": 1, "label": 1, "confidence": 1, "evaluation": 1, "created_at": 1, "timeframe": 1, "price_at_signal": 1},
    ).sort("created_at", -1).limit(history_limit)
    async for d in cursor:
        docs.append(d)

    def _outcome_of(x: dict[str, Any]) -> str:
        ev = x.get("evaluation") or {}
        o = ev.get("outcome")
        if o in ("WIN", "LOSS", "BE"):
            return o
        # Legacy rows without `outcome` — derive from `hit`.
        return "WIN" if ev.get("hit") else "LOSS"

    def _wr(items: list[dict[str, Any]]) -> dict[str, Any]:
        total = len(items)
        wins = sum(1 for x in items if _outcome_of(x) == "WIN")
        losses = sum(1 for x in items if _outcome_of(x) == "LOSS")
        be = sum(1 for x in items if _outcome_of(x) == "BE")
        # v8.12.27 — WR now excludes break-even from the denominator
        # (industry-standard trader definition). Old formula was
        # wins / total which caused chop periods to drag WR down
        # toward 50 % even when the loss ratio was actually much
        # lower. Users saw this as "AI performance dropping" when
        # in reality market was sideways.
        decisive = wins + losses
        if decisive > 0:
            wr = round(wins / decisive * 100.0, 1)
        elif be > 0:
            # v8.12.31 — When every evaluated trade closed at break-even
            # (market chop), the "wins/(wins+losses)" formula divides by
            # zero. Return 50 (neutral) instead of None so the UI shows a
            # meaningful placeholder instead of "—/N hit" which looked
            # like the metric was broken.
            wr = 50.0
        else:
            wr = None
        return {
            "total": total,
            "hits": wins,       # kept for backward compat with older UI
            "wins": wins,
            "losses": losses,
            "break_even": be,
            "win_rate": wr,
        }

    def _serialise(d: dict[str, Any]) -> dict[str, Any]:
        created = d.get("created_at")
        if isinstance(created, datetime):
            iso = (
                created.replace(tzinfo=timezone.utc) if created.tzinfo is None else created
            ).isoformat()
        else:
            iso = str(created)
        ev = d.get("evaluation") or {}
        return {
            "action": d.get("action"),
            "label": d.get("label"),
            "confidence": d.get("confidence"),
            "timeframe": d.get("timeframe"),
            "price_at_signal": d.get("price_at_signal"),
            "created_at": iso,
            "outcome": _outcome_of(d),
            "pct_change": ev.get("pct_change"),
            "price_after": ev.get("price_after"),
            "evaluation": ev,  # keep raw for backward compat
        }

    history_all = [_serialise(d) for d in docs]
    recent = history_all[:8]  # backward compat field

    in_7d = [d for d in docs if _to_dt(d.get("created_at")) >= cutoff_7d]
    in_30d = [d for d in docs if _to_dt(d.get("created_at")) >= cutoff_30d]
    history_7d = [_serialise(d) for d in in_7d]
    history_30d = [_serialise(d) for d in in_30d]

    return {
        "symbol": symbol.upper(),
        "market": market,
        "win_rate_7d": _wr(in_7d),
        "win_rate_30d": _wr(in_30d),
        "win_rate_all": _wr(docs),
        "recent_signals": recent,        # legacy field (top 8)
        "history_7d": history_7d,        # v8.7.0 — full 7d history for popup
        "history_30d": history_30d,      # v8.7.0 — full 30d history for popup
        "history_all": history_all,      # v8.7.0 — full history for popup
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
            # v8.12.29 — Exclude HOLD signals (same reason as detail view).
            "action": {"$in": ["BUY", "SELL"]},
            "created_at": {"$gte": cutoff_30d},
        }},
        {"$project": {
            "symbol": 1,
            "created_at": 1,
            "hit": "$evaluation.hit",
            # v8.12.61 — Also project outcome so we can exclude Break-Even
            # from the denominator (same rule as get_track_record()). This
            # keeps dashboard WR = detail-page WR = "wins / (wins + losses)".
            "outcome": "$evaluation.outcome",
        }},
    ]
    # v8.12.61 — Accumulate per bucket both a "wins" list and a "losses"
    # list, then compute WR = wins / (wins + losses). This matches the
    # detail page formula and removes the mismatch users noticed
    # (dashboard 34% vs detail 75% for ETH, dashboard 7% vs detail 56%
    # for BTC).
    by_symbol: dict[str, dict[str, dict[str, int]]] = {
        s: {"d7": {"wins": 0, "losses": 0, "be": 0}, "d30": {"wins": 0, "losses": 0, "be": 0}}
        for s in syms
    }
    async for d in db.signals.aggregate(pipeline):
        s = d["symbol"]
        if s not in by_symbol:
            continue
        created = d.get("created_at")
        if isinstance(created, datetime):
            created = created.replace(tzinfo=timezone.utc) if created.tzinfo is None else created
            outcome = d.get("outcome")
            if outcome not in ("WIN", "LOSS", "BE"):
                outcome = "WIN" if d.get("hit") else "LOSS"
            key = "wins" if outcome == "WIN" else ("losses" if outcome == "LOSS" else "be")
            if created >= cutoff_7d:
                by_symbol[s]["d7"][key] += 1
            if created >= cutoff_30d:
                by_symbol[s]["d30"][key] += 1

    def _wr_pct(bucket: dict[str, int]) -> tuple[float | None, int]:
        wins = bucket["wins"]
        losses = bucket["losses"]
        be = bucket["be"]
        decisive = wins + losses
        total = wins + losses + be
        if decisive > 0:
            return round(wins / decisive * 100.0, 1), total
        if be > 0:
            return 50.0, total  # every trade broke even → neutral
        return None, total

    out: dict[str, dict[str, Any]] = {}
    for s, buckets in by_symbol.items():
        wr7, n7 = _wr_pct(buckets["d7"])
        wr30, n30 = _wr_pct(buckets["d30"])
        out[s] = {
            "wr_7d": wr7,
            "n_7d": n7,
            "wr_30d": wr30,
            "n_30d": n30,
        }
    return out
