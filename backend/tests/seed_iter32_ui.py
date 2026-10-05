"""Seed ASI-Bot UI test data for device web:t1976-ui976 (iteration 32)."""
import asyncio
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

from motor.motor_asyncio import AsyncIOMotorClient
from asi_bot.crypto import encrypt, mask

DEVICE = "web:t1976-ui976"
NOW = datetime.now(timezone.utc).isoformat()


async def main():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ.get("DB_NAME", "aitrade_pro")]

    # 1) Credential (dummy keys, properly encrypted so close_position can
    #    build a client; exchange call itself will fail -> tests error path)
    await db.asi_credentials.replace_one(
        {"_id": f"{DEVICE}:binance"},
        {
            "_id": f"{DEVICE}:binance", "device_id": DEVICE,
            "exchange": "binance", "testnet": True,
            "api_key_enc": encrypt("TESTDUMMYAPIKEY1234567890"),
            "api_secret_enc": encrypt("TESTDUMMYSECRET1234567890"),
            "password_enc": None,
            "api_key_mask": mask("TESTDUMMYAPIKEY1234567890"),
            "handle": "TST", "created_at": NOW, "updated_at": NOW,
        },
        upsert=True,
    )

    # 2) Trades: open semi, open full, closed full
    trades = [
        {"_id": f"{DEVICE}:seed-open-semi-1", "symbol": "BTCUSDT", "side": "BUY",
         "status": "open", "mode": "semi", "entry_price": 50000.0, "qty": 0.001,
         "leverage": 10, "margin_usdt": 5.0, "pnl_usdt": 12.5,
         "stop_loss": 49000.0, "take_profits": [51000.0], "ccxt_symbol": "BTC/USDT:USDT",
         "bracket_type": "hard", "created_at": "2026-01-20T10:00:00+00:00"},
        {"_id": f"{DEVICE}:seed-open-full-1", "symbol": "ETHUSDT", "side": "SELL",
         "status": "open", "mode": "full", "entry_price": 3000.0, "qty": 0.01,
         "leverage": 10, "margin_usdt": 3.0, "pnl_usdt": -4.2,
         "stop_loss": 3100.0, "take_profits": [2900.0], "ccxt_symbol": "ETH/USDT:USDT",
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

    # 3) Bot config: both disabled, binance, semi mode
    await db.asi_bot_config.replace_one(
        {"_id": DEVICE},
        {"_id": DEVICE, "device_id": DEVICE, "enabled": False, "exchange": "binance",
         "mode": "semi", "max_trades_per_day": 5, "risk_pct": 5.0, "leverage": 10,
         "whitelist": [], "profile": "confluence", "min_confidence": 75,
         "daily_loss_limit_usdt": 0.0, "semi_enabled": False, "full_enabled": False,
         "tp_count": 3, "trailing_callback_rate": 2.0, "updated_at": NOW},
        upsert=True,
    )
    print("SEED OK for", DEVICE)
    client.close()


asyncio.run(main())
