"""Seed synthetic closed trades across 3 days for Iter54 frontend UI test.

Device: TEST-iter54-ui-device
- Day today: 2 real + 1 demo closed; includes AC-15% TP1 trade
- Day today-1: 1 real closed
- Day today-2: 1 demo closed

Usage:
    python backend/tests/seed_iter54_frontend.py seed
    python backend/tests/seed_iter54_frontend.py clean
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import pymongo

TEST_DEV = "TEST-iter54-ui-device"


def connect():
    url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    name = os.environ.get("DB_NAME", "aitrade_pro")
    c = pymongo.MongoClient(url)
    return c, c[name]


def seed():
    _, db = connect()
    now = datetime.now(timezone.utc)
    base_trade = {
        "exchange": "binance", "status": "closed",
        "mode": "semi", "device_id": TEST_DEV,
        "entry_price": 100.0, "closed_price": 110.0, "qty": 1.0,
        "stop_loss": 95.0, "take_profits": [105.0, 110.0, 115.0],
        "leverage": 10, "margin_usdt": 10.0, "risk_pct": 5.0,
    }

    def iso(dt):
        return dt.replace(microsecond=0).isoformat()

    trades = [
        # Today — REAL win, AC-15% hit on TP1 (badge + AC-15% label)
        {
            **base_trade, "_id": f"{TEST_DEV}:ac15-today",
            "symbol": "BTCUSDT", "side": "BUY",
            "testnet": False, "pnl_usdt": 15.0,
            "created_at": iso(now - timedelta(hours=1)),
            "closed_at": iso(now - timedelta(minutes=30)),
            "updated_at": iso(now - timedelta(minutes=30)),
            "close_reason": "TP1", "auto_close_pct": 15,
            "tp_fills": [{"level": "TP1", "price": 110.0, "qty": 1.0, "pnl": 15.0,
                         "at": iso(now - timedelta(minutes=30))}],
            "profile": "scalper",
        },
        # Today — REAL loss
        {
            **base_trade, "_id": f"{TEST_DEV}:sl-today",
            "symbol": "ETHUSDT", "side": "SELL",
            "testnet": False, "pnl_usdt": -12.0,
            "entry_price": 2000, "closed_price": 2020, "stop_loss": 2020,
            "take_profits": [1980, 1960, 1940],
            "created_at": iso(now - timedelta(hours=3)),
            "closed_at": iso(now - timedelta(hours=1)),
            "updated_at": iso(now - timedelta(hours=1)),
            "close_reason": "SL", "auto_close_pct": 0,
            "tp_fills": [], "profile": "day",
        },
        # Today — DEMO win
        {
            **base_trade, "_id": f"{TEST_DEV}:demo-today",
            "symbol": "SOLUSDT", "side": "BUY",
            "testnet": True, "pnl_usdt": 8.0,
            "created_at": iso(now - timedelta(hours=2)),
            "closed_at": iso(now - timedelta(hours=1, minutes=30)),
            "updated_at": iso(now - timedelta(hours=1, minutes=30)),
            "close_reason": "TP2", "auto_close_pct": 0,
            "tp_fills": [{"level": "TP1", "price": 105.0, "qty": 0.33, "pnl": 2.0,
                         "at": iso(now - timedelta(hours=2))}],
            "profile": "swing",
        },
        # Yesterday — REAL win
        {
            **base_trade, "_id": f"{TEST_DEV}:yday-real",
            "symbol": "AVAXUSDT", "side": "BUY",
            "testnet": False, "pnl_usdt": 7.5,
            "created_at": iso(now - timedelta(days=1, hours=4)),
            "closed_at": iso(now - timedelta(days=1, hours=2)),
            "updated_at": iso(now - timedelta(days=1, hours=2)),
            "close_reason": "TP1", "auto_close_pct": 0,
            "tp_fills": [], "profile": "day",
        },
        # 2 days ago — DEMO loss
        {
            **base_trade, "_id": f"{TEST_DEV}:2d-demo",
            "symbol": "ADAUSDT", "side": "SELL",
            "testnet": True, "pnl_usdt": -5.0,
            "created_at": iso(now - timedelta(days=2, hours=5)),
            "closed_at": iso(now - timedelta(days=2, hours=3)),
            "updated_at": iso(now - timedelta(days=2, hours=3)),
            "close_reason": "SL", "auto_close_pct": 0,
            "tp_fills": [], "profile": "scalper",
        },
    ]
    for t in trades:
        db.asi_trades.replace_one({"_id": t["_id"]}, t, upsert=True)
    print(f"Seeded {len(trades)} trades for {TEST_DEV}")


def clean():
    _, db = connect()
    r = db.asi_trades.delete_many({"device_id": TEST_DEV})
    db.asi_bot_config.delete_one({"_id": TEST_DEV})
    print(f"Cleaned {r.deleted_count} docs for {TEST_DEV}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "seed"
    if cmd == "clean":
        clean()
    else:
        seed()
