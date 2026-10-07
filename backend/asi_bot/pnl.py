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
    """v10.0.5 — RANK PER POSISI (bukan per trader): setiap posisi open
    maupun closed (24 jam terakhir) menjadi SATU entri leaderboard dengan
    PnL masing-masing — tidak digabung per trader/aset. Nama trader yang
    sama bisa muncul di beberapa rank bila punya banyak posisi profit.
    Hanya posisi ber-PnL positif; EXECUTE hanya untuk status open."""
    since = _iso_days_ago(1)
    cursor = db.asi_trades.find(
        {
            "$or": [
                {"status": "open"},
                {"status": "closed", "closed_at": {"$gte": since}},
                {"status": "closed", "created_at": {"$gte": since}},
            ],
            "pnl_usdt": {"$gt": 0},
        },
        {
            "device_id": 1, "testnet": 1, "status": 1,
            "symbol": 1, "side": 1, "entry_price": 1, "stop_loss": 1,
            "take_profits": 1, "leverage": 1, "exchange": 1, "qty": 1,
            "margin_usdt": 1, "pnl_usdt": 1,
            "mode": 1, "entry_mode": 1,
            "created_at": 1, "closed_at": 1, "closed_price": 1,
            "close_reason": 1,
        },
    ).sort("pnl_usdt", -1).limit(limit)
    trades = await cursor.to_list(limit)

    # Cache handle & statistik 30 hari per device (trader bisa muncul 2+ rank).
    handle_cache: dict[str, str] = {}
    stats_cache: dict[str, tuple[float, int]] = {}

    async def _handle(device_id: str) -> str:
        if device_id not in handle_cache:
            cred = await db.asi_credentials.find_one(
                {"device_id": device_id}, {"handle": 1})
            handle_cache[device_id] = (cred or {}).get("handle") or "***"
        return handle_cache[device_id]

    async def _stats30(device_id: str) -> tuple[float, int]:
        if device_id not in stats_cache:
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
            stats_cache[device_id] = (wr30, tr30)
        return stats_cache[device_id]

    out: list[dict[str, Any]] = []
    for i, tr in enumerate(trades):
        device_id = tr.get("device_id") or ""
        pnl = round(tr.get("pnl_usdt") or 0.0, 2)
        margin = tr.get("margin_usdt") or 0.0
        if margin <= 0:
            entry = tr.get("entry_price") or 0.0
            qty = tr.get("qty") or 0.0
            lev = max(tr.get("leverage") or 1, 1)
            margin = (entry * qty / lev) if entry and qty else 0.0
        pnl_pct = round(pnl / margin * 100.0, 2) if margin > 0 else 0.0
        wr30, tr30 = await _stats30(device_id)
        is_open = tr.get("status") == "open"
        # v10.0.5 — COMPAT: aplikasi lama (<=10.0.4) membaca field grup
        # per-trader (unrealized_usdt/total_profit_usdt/open_trades/dst).
        # Set unrealized_usdt = pnl (BUKAN 0) agar app lama menampilkan
        # angka PnL yang bermakna; set open_count = 1 supaya pill
        # "0 OPEN POS" tidak muncul. pnl SELALU > 0 (sudah difilter).
        pos_payload = {
            "symbol": tr.get("symbol"),
            "side": tr.get("side"),
            "entry_price": tr.get("entry_price"),
            "stop_loss": tr.get("stop_loss"),
            "take_profits": tr.get("take_profits"),
            "leverage": tr.get("leverage"),
            "exchange": tr.get("exchange"),
            "created_at": tr.get("created_at"),
            "pnl_usdt": pnl,
            "closed_at": tr.get("closed_at"),
            "closed_price": tr.get("closed_price"),
            "close_reason": tr.get("close_reason"),
        }
        out.append({
            "rank": i + 1,
            "handle": await _handle(device_id),
            "testnet": bool(tr.get("testnet")),
            "status": tr.get("status"),
            "symbol": tr.get("symbol"),
            "side": tr.get("side"),
            "entry_price": tr.get("entry_price"),
            "stop_loss": tr.get("stop_loss"),
            "take_profits": tr.get("take_profits"),
            "leverage": tr.get("leverage"),
            "exchange": tr.get("exchange"),
            "mode": tr.get("mode"),
            "entry_mode": tr.get("entry_mode"),
            "created_at": tr.get("created_at"),
            "closed_at": tr.get("closed_at"),
            "closed_price": tr.get("closed_price"),
            "close_reason": tr.get("close_reason"),
            "pnl_usdt": pnl,
            "pnl_pct": pnl_pct,
            "wr30d": wr30,
            "trades30d": tr30,
            # ---- field kompatibilitas untuk app versi lama ----
            # unrealized/total diisi pnl aktual (positif) supaya app lama
            # tidak menampilkan "+$0.00"; open_count=1 agar pill "0 OPEN
            # POS" tidak muncul.
            "unrealized_usdt": pnl,
            "unrealized_pct": pnl_pct,
            "realized_usdt": 0.0 if is_open else pnl,
            "total_profit_usdt": pnl,
            "open_count": 1,
            "closed_count": 0 if is_open else 1,
            "latest_trade": pos_payload,
            "open_trades": [pos_payload] if is_open else [],
            "closed_trades": [] if is_open else [pos_payload],
        })
    return out
