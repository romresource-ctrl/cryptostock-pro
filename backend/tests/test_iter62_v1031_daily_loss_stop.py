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
                                            "full_enabled": True, "mode": "full", "active_testnet": False,
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
        cfg = {"_id": DEV, "device_id": DEV, "enabled": True, "mode": "full", "active_testnet": False,
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


from datetime import timedelta  # noqa: E402
from asi_bot.scheduler import (_auto_resume_daily_limits, _local_day,  # noqa: E402
                               _local_day_start_utc)


def test_local_day_start_wib():
    now = datetime(2026, 10, 22, 18, 30, tzinfo=timezone.utc)  # 01:30 WIB 23/10
    assert _local_day(420, now) == "2026-10-23"
    assert _local_day_start_utc(420, now) == datetime(2026, 10, 22, 17, 0, tzinfo=timezone.utc)


def _resume(day: str, kind: str = "daily_limit") -> dict:
    async def go():
        db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
        await db.asi_bot_config.delete_many({"device_id": DEV})
        await db.asi_bot_config.insert_one({"_id": DEV, "device_id": DEV, "enabled": False,
                                            "full_enabled": False, "tz_offset_min": 420,
                                            "auto_disabled_kind": kind, "auto_disabled_day": day,
                                            "auto_disabled_reason": "x"})
        try:
            await _auto_resume_daily_limits(db)
            return await db.asi_bot_config.find_one({"_id": DEV})
        finally:
            await db.asi_bot_config.delete_many({"device_id": DEV})
    return asyncio.run(go())


def test_resume_after_midnight():
    yday = (datetime.now(timezone.utc) + timedelta(minutes=420) - timedelta(days=1)).strftime("%Y-%m-%d")
    cfg = _resume(yday)
    assert cfg["full_enabled"] is True and "auto_disabled_reason" not in cfg


def test_no_resume_same_day():
    cfg = _resume(_local_day(420))
    assert cfg["full_enabled"] is False


def test_profit_stop_marks_day_and_demo_counts():
    async def go():
        db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
        now = datetime.now(timezone.utc).isoformat()
        await db.asi_bot_config.delete_many({"device_id": DEV})
        await db.asi_trades.delete_many({"device_id": DEV})
        await db.asi_bot_config.insert_one({"_id": DEV, "device_id": DEV, "enabled": True,
                                            "full_enabled": True, "active_testnet": True,
                                            "tz_offset_min": 420, "daily_profit_limit_usdt": 50})
        await db.asi_trades.insert_one({"_id": DEV + "-t", "device_id": DEV, "status": "closed",
                                        "testnet": True, "pnl_usdt": 70, "closed_at": now})
        try:
            await _enforce_daily_profit_limit(db)
            return await db.asi_bot_config.find_one({"_id": DEV})
        finally:
            await db.asi_bot_config.delete_many({"device_id": DEV})
            await db.asi_trades.delete_many({"device_id": DEV})
    cfg = asyncio.run(go())
    assert cfg["full_enabled"] is False
    assert cfg["auto_disabled_kind"] == "daily_limit" and cfg["auto_disabled_day"] == _local_day(420)
