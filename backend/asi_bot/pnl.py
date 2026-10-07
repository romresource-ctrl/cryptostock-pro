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
    """v9.4.0 — Return traders that are CURRENTLY in open positions.

    v9.7.7 — Hanya tampilkan trader yang SEDANG PROFIT (hijau) dan diurutkan
    dari UNREALIZED PnL % terbesar (bukan $). Trader loss (merah) dan
    break-even disembunyikan — leaderboard khusus "who's crushing it right now".

    v9.9.7 — DEMO & REAL sama-sama ditampilkan (keputusan user: strategi bot
    identik, hanya beda uang asli/non-asli). Group per (device, testnet)
    supaya entry demo & real trader yang sama tampil terpisah dengan badge.
    Maks 25 entri — nilai kecil tergeser keluar oleh % dan $ terbesar.
    """
    pipeline = [
        {"$match": {"status": "open"}},
        {"$sort": {"updated_at": -1}},
        {"$group": {
            # v9.9.7 — pisahkan demo vs real per trader (badge DEMO di UI)
            "_id": {"device": "$device_id", "testnet": {"$eq": ["$testnet", True]}},
            "unrealized_usdt": {"$sum": "$pnl_usdt"},
            "margin_usdt": {"$sum": {"$ifNull": ["$margin_usdt", 0]}},
            # Fallback margin from notional/leverage for older records.
            "notional_margin": {"$sum": {
                "$divide": [
                    {"$multiply": [
                        {"$ifNull": ["$entry_price", 0]},
                        {"$ifNull": ["$qty", 0]},
                    ]},
                    {"$max": [{"$ifNull": ["$leverage", 1]}, 1]},
                ],
            }},
            "open_count": {"$sum": 1},
            "latest": {"$first": "$$ROOT"},
            # v10.0.3 — Kumpulkan SEMUA posisi open trader (bukan hanya 1
            # terbaru) supaya leaderboard menampilkan tiap posisi sebagai
            # kartu terpisah (permintaan user: 2 open pos = 2 kartu).
            "all_trades": {"$push": "$$ROOT"},
        }},
        # v9.7.7 — hanya posisi profit sebelum sorting
        {"$match": {"unrealized_usdt": {"$gt": 0}}},
    ]
    # Grab a wider pool (3x limit) so after %-sort we still have ≥ `limit`.
    rows = await db.asi_trades.aggregate(pipeline).to_list(limit * 3)
    enriched: list[dict[str, Any]] = []
    for r in rows:
        device_id = r["_id"]["device"]
        is_demo = bool(r["_id"]["testnet"])
        unrealized = round(r.get("unrealized_usdt") or 0.0, 2)
        margin = (r.get("margin_usdt") or 0.0) or (r.get("notional_margin") or 0.0)
        unrealized_pct = round(unrealized / margin * 100.0, 2) if margin > 0 else 0.0
        if unrealized_pct <= 0:
            continue
        cred = await db.asi_credentials.find_one({"device_id": device_id}, {"handle": 1})
        handle = (cred or {}).get("handle") or "***"
        # Realised 30-day Win Rate for extra context (demo & real digabung —
        # strategi bot identik menurut keputusan user v9.9.7).
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
        enriched.append({
            "handle": handle,
            "testnet": is_demo,
            "unrealized_usdt": unrealized,
            "unrealized_pct": unrealized_pct,
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
            # v10.0.3 — semua posisi open, diurutkan dari PnL terbesar.
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
                for x in sorted(
                    r.get("all_trades") or [],
                    key=lambda y: y.get("pnl_usdt") or 0, reverse=True,
                )
            ],
        })
    # v9.7.7 — sort by percentage desc, assign rank, trim to limit
    enriched.sort(key=lambda x: x["unrealized_pct"], reverse=True)
    out: list[dict[str, Any]] = []
    for i, row in enumerate(enriched[:limit]):
        out.append({"rank": i + 1, **row})
    return out
