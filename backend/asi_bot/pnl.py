"""ASI-Bot — PnL aggregation + Top-10 leaderboard (Phase 4)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


def _iso_days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


async def pnl_summary(db: Any, device_id: str) -> dict[str, Any]:
    """Return dict with daily/weekly/monthly PnL in USDT + %.

    v9.9.5 — PnL utama HANYA trade mainnet (real). Trade testnet (demo)
    dipisah ke key `demo` agar tidak mengurangi/menambah PnL real user.
    """
    out: dict[str, Any] = {}
    for key, days in (("daily", 1), ("weekly", 7), ("monthly", 30)):
        pipeline = [
            {"$match": {
                "device_id": device_id,
                "created_at": {"$gte": _iso_days_ago(days)},
                "testnet": {"$ne": True},  # hanya REAL
            }},
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
    # Demo (testnet) ringkasan terpisah — informatif, tidak masuk PnL real.
    demo_pipeline = [
        {"$match": {"device_id": device_id, "testnet": True}},
        {"$group": {
            "_id": None,
            "pnl_usdt": {"$sum": "$pnl_usdt"},
            "trades": {"$sum": 1},
            "wins": {"$sum": {"$cond": [{"$gt": ["$pnl_usdt", 0]}, 1, 0]}},
            "losses": {"$sum": {"$cond": [{"$lt": ["$pnl_usdt", 0]}, 1, 0]}},
        }},
    ]
    dagg = await db.asi_trades.aggregate(demo_pipeline).to_list(1)
    drow = dagg[0] if dagg else {}
    out["demo"] = {
        "pnl_usdt": round(drow.get("pnl_usdt") or 0.0, 2),
        "trades": drow.get("trades", 0),
        "wins": drow.get("wins", 0), "losses": drow.get("losses", 0),
    }
    return out


async def leaderboard(db: Any, period_days: int = 7, limit: int = 25) -> list[dict[str, Any]]:
    # v9.9.7 — DEMO & REAL sama-sama tampil (keputusan user), dipisah per
    # jaringan supaya badge DEMO akurat. Maks 25 — nilai kecil tergeser.
    pipeline = [
        {"$match": {"created_at": {"$gte": _iso_days_ago(period_days)}}},
        {"$group": {
            "_id": {"device": "$device_id", "testnet": {"$eq": ["$testnet", True]}},
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
        cred = await db.asi_credentials.find_one(
            {"device_id": r["_id"]["device"]}, {"handle": 1})
        handle = (cred or {}).get("handle") or "***"
        trades = r.get("trades", 0)
        wins = r.get("wins", 0)
        wr = round(wins / trades * 100, 1) if trades else 0.0
        out.append({
            "rank": i + 1, "handle": handle,
            "testnet": bool(r["_id"]["testnet"]),
            "pnl_usdt": round(r.get("pnl_usdt") or 0.0, 2),
            "trades": trades, "wr": wr,
        })
    return out


async def live_leaderboard(db: Any, limit: int = 25) -> list[dict[str, Any]]:
    """v10.0.3 — Top 25 trader berdasarkan TOTAL PROFIT 24 jam terakhir:
    unrealized (posisi open) + realized (posisi closed). Trader yang masih
    online (punya posisi open) bisa langsung di-copy via kartu posisi;
    trader yang sudah selesai hari ini tetap tampil (tanpa kartu posisi)
    sampai digantikan rank yang lebih tinggi. Hanya profit positif."""
    since = _iso_days_ago(1)
    # Agregat total profit per (device, testnet) dari open + closed 24h.
    pipeline = [
        {"$match": {
            "$or": [
                {"status": "open"},
                {"status": "closed", "closed_at": {"$gte": since}},
                {"status": "closed", "created_at": {"$gte": since}},
            ],
        }},
        {"$sort": {"updated_at": -1}},
        {"$group": {
            "_id": {"device": "$device_id", "testnet": {"$eq": ["$testnet", True]}},
            "unrealized_usdt": {"$sum": {
                "$cond": [{"$eq": ["$status", "open"]}, {"$ifNull": ["$pnl_usdt", 0]}, 0],
            }},
            "realized_usdt": {"$sum": {
                "$cond": [{"$eq": ["$status", "closed"]}, {"$ifNull": ["$pnl_usdt", 0]}, 0],
            }},
            "margin_usdt": {"$sum": {
                "$cond": [{"$eq": ["$status", "open"]}, {"$ifNull": ["$margin_usdt", 0]}, 0],
            }},
            "notional_margin": {"$sum": {"$cond": [
                {"$eq": ["$status", "open"]},
                {"$divide": [
                    {"$multiply": [
                        {"$ifNull": ["$entry_price", 0]},
                        {"$ifNull": ["$qty", 0]},
                    ]},
                    {"$max": [{"$ifNull": ["$leverage", 1]}, 1]},
                ]},
                0,
            ]}},
            "open_count": {"$sum": {"$cond": [{"$eq": ["$status", "open"]}, 1, 0]}},
            "closed_count": {"$sum": {"$cond": [{"$eq": ["$status", "closed"]}, 1, 0]}},
            "latest": {"$first": "$$ROOT"},
            "open_trades": {"$push": {
                "$cond": [{"$eq": ["$status", "open"]}, "$$ROOT", "$$REMOVE"],
            }},
        }},
    ]
    rows = await db.asi_trades.aggregate(pipeline).to_list(limit * 3)
    enriched: list[dict[str, Any]] = []
    for r in rows:
        device_id = r["_id"]["device"]
        is_demo = bool(r["_id"]["testnet"])
        unreal = round(r.get("unrealized_usdt") or 0.0, 2)
        realized = round(r.get("realized_usdt") or 0.0, 2)
        total = round(unreal + realized, 2)
        if total <= 0:
            continue
        margin = (r.get("margin_usdt") or 0.0) or (r.get("notional_margin") or 0.0)
        unreal_pct = round(unreal / margin * 100.0, 2) if margin > 0 else 0.0
        cred = await db.asi_credentials.find_one({"device_id": device_id}, {"handle": 1})
        handle = (cred or {}).get("handle") or "***"
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
        open_trades_sorted = sorted(
            (r.get("open_trades") or []),
            key=lambda y: y.get("pnl_usdt") or 0, reverse=True,
        )
        enriched.append({
            "handle": handle,
            "testnet": is_demo,
            # Backward-compat: unrealized_usdt tetap tersedia (UI lama).
            "unrealized_usdt": unreal,
            "unrealized_pct": unreal_pct,
            "realized_usdt": realized,
            "total_profit_usdt": total,
            "open_count": int(r.get("open_count") or 0),
            "closed_count": int(r.get("closed_count") or 0),
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
            "open_trades": [
                {
                    "symbol": x.get("symbol"),
                    "side": x.get("side"),
                    "entry_price": x.get("entry_price"),
                    "stop_loss": x.get("stop_loss"),
                    "take_profits": x.get("take_profits"),
                    "leverage": x.get("leverage"),
                    "exchange": x.get("exchange"),
                    "created_at": x.get("created_at"),
                    "pnl_usdt": x.get("pnl_usdt"),
                }
                for x in open_trades_sorted
            ],
        })
    # v10.0.3 — Rank berdasarkan TOTAL PROFIT $ (realized + unrealized 24h).
    enriched.sort(key=lambda x: x["total_profit_usdt"], reverse=True)
    out: list[dict[str, Any]] = []
    for i, row in enumerate(enriched[:limit]):
        out.append({"rank": i + 1, **row})
    return out
