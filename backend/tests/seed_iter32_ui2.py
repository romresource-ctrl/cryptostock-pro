"""Seed OPEN trades for device web:t1976-ui977 (NO credential on purpose,
so the scheduler PnL loop skips them and they stay open for UI testing)."""
import asyncio
import os
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
from motor.motor_asyncio import AsyncIOMotorClient

DEVICE = "web:t1976-ui977"
NOW = datetime.now(timezone.utc).isoformat()


async def main():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ.get("DB_NAME", "aitrade_pro")]
    await db.asi_credentials.delete_many({"device_id": DEVICE})  # ensure none

    trades = [
        {"_id": f"{DEVICE}:seed-open-semi-1", "symbol": "BTCUSDT", "side": "BUY",
         "status": "open", "mode": "semi", "entry_price": 50000.0, "qty": 0.001,
         "leverage": 10, "margin_usdt": 5.0, "pnl_usdt": 12.5,
         "stop_loss": 1.0, "take_profits": [999999.0], "ccxt_symbol": "BTC/USDT:USDT",
         "bracket_type": "hard", "created_at": "2026-01-20T10:00:00+00:00"},
        {"_id": f"{DEVICE}:seed-open-full-1", "symbol": "ETHUSDT", "side": "SELL",
         "status": "open", "mode": "full", "entry_price": 3000.0, "qty": 0.01,
         "leverage": 10, "margin_usdt": 3.0, "pnl_usdt": -4.2,
         "stop_loss": 999999.0, "take_profits": [1.0], "ccxt_symbol": "ETH/USDT:USDT",
         "bracket_type": "hard", "created_at": "2026-01-20T09:00:00+00:00"},
        {"_id": f"{DEVICE}:seed-closed-1", "symbol": "SOLUSDT", "side": "BUY",
         "status": "closed", "mode": "full", "entry_price": 150.0, "qty": 0.1,
         "leverage": 10, "margin_usdt": 1.5, "pnl_usdt": 8.75,
         "stop_loss": 145.0, "take_profits": [160.0], "close_reason": "TP",
         "closed_at": "2026-01-19T08:00:00+00:00", "created_at": "2026-01-19T07:00:00+00:00"},
    ]
    for t in trades:
        t.update({"device_id": DEVICE, "exchange": "binance", "testnet": True,
                  "risk_pct": 5.0, "updated_at": NOW})
        await db.asi_trades.replace_one({"_id": t["_id"]}, t, upsert=True)
    print("SEED OK for", DEVICE)
    client.close()


asyncio.run(main())
