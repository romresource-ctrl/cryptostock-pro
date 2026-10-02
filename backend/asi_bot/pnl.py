"""ASI-Bot — PnL aggregation + Top-10 leaderboard (Phase 4)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


def _iso_days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


async def pnl_summary(db: Any, device_id: str) -> dict[str, Any]:
    """Return dict with daily/weekly/monthly PnL in USDT + %."""
    out: dict[str, Any] = {}
    for key, days in (("daily", 1), ("weekly", 7), ("monthly", 30)):
        pipeline = [
            {"$match": {"device_id": device_id, "created_at": {"$gte": _iso_days_ago(days)}}},
            {"$group": {
                "_id": None,
                "pnl_usdt": {"$sum": "$pnl_usdt"},
                "margin_usdt": {"$sum": "$margin_usdt"},
                "trades": {"$sum": 1},
                "wins": {"$sum": {"$cond": [{"$gt": ["$pnl_usdt", 0]}, 1, 0]}},
                "losses": {"$sum": {"$cond": [{"$lt": ["$pnl_usdt", 0]}, 1, 0]}},
            }},
        ]
        agg = await db.asi_trades.aggregate(pipeline).to_list(1)
        row = agg[0] if agg else {}
        pnl = round(row.get("pnl_usdt") or 0.0, 2)
        margin = row.get("margin_usdt") or 0.0
        pct = round((pnl / margin * 100.0), 2) if margin > 0 else 0.0
        out[key] = {
            "pnl_usdt": pnl, "pnl_pct": pct,
            "trades": row.get("trades", 0),
            "wins": row.get("wins", 0), "losses": row.get("losses", 0),
        }
    return out


async def leaderboard(db: Any, period_days: int = 7, limit: int = 10) -> list[dict[str, Any]]:
    pipeline = [
        {"$match": {"created_at": {"$gte": _iso_days_ago(period_days)}}},
        {"$group": {
            "_id": "$device_id",
            "pnl_usdt": {"$sum": "$pnl_usdt"},
            "trades": {"$sum": 1},
            "wins": {"$sum": {"$cond": [{"$gt": ["$pnl_usdt", 0]}, 1, 0]}},
            "losses": {"$sum": {"$cond": [{"$lt": ["$pnl_usdt", 0]}, 1, 0]}},
        }},
        {"$sort": {"pnl_usdt": -1}},
        {"$limit": limit},
    ]
    rows = await db.asi_trades.aggregate(pipeline).to_list(limit)
    out = []
    for i, r in enumerate(rows):
        cred = await db.asi_credentials.find_one({"device_id": r["_id"]}, {"handle": 1})
        handle = (cred or {}).get("handle") or "***"
        trades = r.get("trades", 0)
        wins = r.get("wins", 0)
        wr = round(wins / trades * 100, 1) if trades else 0.0
        out.append({
            "rank": i + 1, "handle": handle,
            "pnl_usdt": round(r.get("pnl_usdt") or 0.0, 2),
            "trades": trades, "wr": wr,
        })
    return out


async def live_leaderboard(db: Any, limit: int = 10) -> list[dict[str, Any]]:
    """v9.4.0 — Return traders that are CURRENTLY in open positions.

    Ranked by UNREALIZED PnL (desc). Traders whose last open trade just
    closed will fall off the list automatically — fully live.
    Each row includes the open trade snapshot so the UI can show what's
    being traded (symbol, side, entry) and the user can preview a copy.
    """
    pipeline = [
        {"$match": {"status": "open"}},
        {"$sort": {"updated_at": -1}},
        {"$group": {
            "_id": "$device_id",
            "unrealized_usdt": {"$sum": "$pnl_usdt"},
            "open_count": {"$sum": 1},
            "latest": {"$first": "$$ROOT"},
        }},
        {"$sort": {"unrealized_usdt": -1}},
        {"$limit": limit},
    ]
    rows = await db.asi_trades.aggregate(pipeline).to_list(limit)
    out = []
    for i, r in enumerate(rows):
        device_id = r["_id"]
        cred = await db.asi_credentials.find_one({"device_id": device_id}, {"handle": 1})
        handle = (cred or {}).get("handle") or "***"
        # Realised 30-day Win Rate for extra context.
        hist = await db.asi_trades.aggregate([
            {"$match": {
                "device_id": device_id, "status": "closed",
                "created_at": {"$gte": _iso_days_ago(30)},
            }},
            {"$group": {
                "_id": None,
                "trades": {"$sum": 1},
                "wins": {"$sum": {"$cond": [{"$gt": ["$pnl_usdt", 0]}, 1, 0]}},
            }},
        ]).to_list(1)
        h = hist[0] if hist else {}
        tr30 = int(h.get("trades") or 0)
        wr30 = round((h.get("wins") or 0) / tr30 * 100, 1) if tr30 else 0.0
        latest = r.get("latest") or {}
        out.append({
            "rank": i + 1,
            "handle": handle,
            "unrealized_usdt": round(r.get("unrealized_usdt") or 0.0, 2),
            "open_count": int(r.get("open_count") or 0),
            "wr30d": wr30,
            "trades30d": tr30,
            "latest_trade": {
                "symbol": latest.get("symbol"),
                "side": latest.get("side"),
                "entry_price": latest.get("entry_price"),
                "stop_loss": latest.get("stop_loss"),
                "take_profits": latest.get("take_profits"),
                "leverage": latest.get("leverage"),
                "exchange": latest.get("exchange"),
                "created_at": latest.get("created_at"),
            },
        })
    return out
