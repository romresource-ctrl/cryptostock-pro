"""v10.3.1 — Daily Loss Limit harus mematikan full_enabled (Full-Auto)."""
import asyncio
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv  # noqa: E402

load_dotenv("/app/backend/.env")
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402
from asi_bot.scheduler import _enforce_daily_loss_limit  # noqa: E402

DEV = "TEST-iter62-dll"


def _run(pnl: float) -> dict:
    async def go():
        db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
        now = datetime.now(timezone.utc).isoformat()
        await db.asi_bot_config.delete_many({"device_id": DEV})
        await db.asi_trades.delete_many({"device_id": DEV})
        await db.asi_bot_config.insert_one({"_id": DEV, "device_id": DEV, "enabled": True,
                                            "full_enabled": True, "mode": "full",
                                            "daily_loss_limit_usdt": 50})
        await db.asi_trades.insert_one({"_id": DEV + "-t", "device_id": DEV, "status": "closed",
                                        "pnl_usdt": pnl, "closed_at": now, "updated_at": now,
                                        "created_at": now, "symbol": "XRP", "side": "BUY"})
        try:
            await _enforce_daily_loss_limit(db)
            return await db.asi_bot_config.find_one({"_id": DEV})
        finally:
            await db.asi_bot_config.delete_many({"device_id": DEV})
            await db.asi_trades.delete_many({"device_id": DEV})
    return asyncio.run(go())


def test_loss_limit_stops_full_auto():
    cfg = _run(-60)
    assert cfg["full_enabled"] is False and cfg["enabled"] is False
    assert "Daily loss limit" in cfg["auto_disabled_reason"]


def test_below_limit_keeps_running():
    cfg = _run(-20)
    assert cfg["full_enabled"] is True


from asi_bot.scheduler import _enforce_daily_profit_limit  # noqa: E402


def _run_profit(pnl: float, legacy: bool = False) -> dict:
    async def go():
        db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
        now = datetime.now(timezone.utc).isoformat()
        await db.asi_bot_config.delete_many({"device_id": DEV})
        await db.asi_trades.delete_many({"device_id": DEV})
        cfg = {"_id": DEV, "device_id": DEV, "enabled": True, "mode": "full",
               "daily_profit_limit_usdt": 50}
        if not legacy:
            cfg["full_enabled"] = True
        await db.asi_bot_config.insert_one(cfg)
        await db.asi_trades.insert_one({"_id": DEV + "-t", "device_id": DEV, "status": "closed",
                                        "pnl_usdt": pnl, "closed_at": now, "updated_at": now,
                                        "created_at": now, "symbol": "XRP", "side": "BUY"})
        try:
            await _enforce_daily_profit_limit(db)
            return await db.asi_bot_config.find_one({"_id": DEV})
        finally:
            await db.asi_bot_config.delete_many({"device_id": DEV})
            await db.asi_trades.delete_many({"device_id": DEV})
    return asyncio.run(go())


def test_profit_target_stops_full_auto():
    cfg = _run_profit(60)
    assert cfg["full_enabled"] is False and cfg["enabled"] is False
    assert "Daily profit target" in cfg["auto_disabled_reason"]


def test_profit_target_stops_legacy_full_config():
    cfg = _run_profit(50, legacy=True)  # tepat = target
    assert cfg["enabled"] is False and cfg["full_enabled"] is False


def test_profit_below_target_keeps_running():
    cfg = _run_profit(49.9)
    assert cfg["full_enabled"] is True
