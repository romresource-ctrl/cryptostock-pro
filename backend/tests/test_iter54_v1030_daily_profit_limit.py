"""Iter54 — ASI-Bot v10.3.0 backend tests.

Scope (from main agent review_request):
  1. GET /api/app-version returns 10.3.0
  2. POST/GET /api/asi/bot persists daily_profit_limit_usdt (>=0; negative → 422)
  3. scheduler._enforce_daily_profit_limit disables Full-Auto when
     realized PnL today >= limit; stays enabled when below limit.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://cryptostock-pro.preview.emergentagent.com").rstrip("/")

# Dedicated TEST device_id — isolated from real devices
TEST_DEVICE_ID = "TEST-iter54-dpl-device-001"
PREMIUM_DEVICE = "test-judge-device-001"
UNLOCK_CODE = "C924-337C-D665"


@pytest.fixture(scope="module")
def api_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    yield s
    s.close()


# ─────────────────────────────────────────────────────────────────────────────
# 1. App version
# ─────────────────────────────────────────────────────────────────────────────
class TestAppVersion:
    def test_app_version_is_10_3_0(self, api_client):
        r = api_client.get(f"{BASE_URL}/api/app-version", timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        # Field names historically: latest_version / version / android_latest.
        version_val = (
            data.get("latest_version")
            or data.get("version")
            or data.get("android_latest")
            or data.get("latest")
        )
        assert version_val == "10.4.1", f"Expected 10.3.0, got {version_val} | body={data}"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Bot config endpoint — daily_profit_limit_usdt field
# ─────────────────────────────────────────────────────────────────────────────
class TestDailyProfitLimitPersistence:
    _VALID_BOT_PAYLOAD = {
        "enabled": False,
        "exchange": "binance",
        "mode": "semi",
        "max_trades_per_day": 5,
        "risk_pct": 5.0,
        "leverage": 10,
        "whitelist": [],
        "profile": None,
        "min_confidence": 75,
        "daily_loss_limit_usdt": 100.0,
        "daily_profit_limit_usdt": 50.0,
        "semi_enabled": False,
        "full_enabled": False,
        "tp_count": 3,
        "auto_close_pct": 0,
        "margin_usdt": 0.0,
        "trailing_callback_rate": 2.0,
        "entry_mode": "limit",
        "disclaimer_ack": True,
        "margin_mode": "isolated",
        "active_testnet": True,
        "signal_source": "asi_bot",
    }

    def test_post_bot_accepts_daily_profit_limit_and_persists(self, api_client):
        url = f"{BASE_URL}/api/asi/bot"
        r = api_client.post(url, params={"device_id": TEST_DEVICE_ID},
                            json=self._VALID_BOT_PAYLOAD, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True
        assert body.get("daily_profit_limit_usdt") == 50.0

        # GET to verify persistence
        r2 = api_client.get(url, params={"device_id": TEST_DEVICE_ID}, timeout=15)
        assert r2.status_code == 200, r2.text
        got = r2.json()
        assert got.get("exists") is True
        assert got.get("daily_profit_limit_usdt") == 50.0, got

    def test_post_bot_rejects_negative_daily_profit_limit(self, api_client):
        payload = dict(self._VALID_BOT_PAYLOAD)
        payload["daily_profit_limit_usdt"] = -1
        r = api_client.post(f"{BASE_URL}/api/asi/bot",
                            params={"device_id": TEST_DEVICE_ID},
                            json=payload, timeout=15)
        assert r.status_code == 422, f"Expected 422 for negative, got {r.status_code} | {r.text}"

    def test_post_bot_accepts_zero_daily_profit_limit(self, api_client):
        payload = dict(self._VALID_BOT_PAYLOAD)
        payload["daily_profit_limit_usdt"] = 0
        r = api_client.post(f"{BASE_URL}/api/asi/bot",
                            params={"device_id": TEST_DEVICE_ID},
                            json=payload, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json().get("daily_profit_limit_usdt") == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# 3. scheduler._enforce_daily_profit_limit — direct Mongo call
# ─────────────────────────────────────────────────────────────────────────────
def _make_db():
    """Create a fresh motor client bound to the CURRENT event loop."""
    import sys
    sys.path.insert(0, "/app/backend")
    from motor.motor_asyncio import AsyncIOMotorClient
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("DB_NAME", "aitrade_pro")
    client = AsyncIOMotorClient(mongo_url)
    return client, client[db_name]


class TestEnforceDailyProfitLimit:
    """Call scheduler function directly against local Mongo."""

    def test_disables_bot_when_profit_above_limit(self):
        import sys
        sys.path.insert(0, "/app/backend")
        from asi_bot.scheduler import _enforce_daily_profit_limit

        test_dev = "TEST-iter54-dpl-above-999"
        now = datetime.now(timezone.utc).isoformat()

        async def _flow():
            client, db = _make_db()
            # Seed config: full_enabled True, limit $50
            await db.asi_bot_config.replace_one(
                {"_id": test_dev},
                {"_id": test_dev, "device_id": test_dev,
                 "full_enabled": True, "enabled": True,
                 "daily_profit_limit_usdt": 50.0,
                 "daily_loss_limit_usdt": 0.0,
                 "exchange": "binance", "active_testnet": False,
                 "updated_at": now},
                upsert=True,
            )
            # Seed synthetic REAL (testnet False) closed trade today pnl=60
            trade_id = f"TEST_iter54_above:{test_dev}:1"
            await db.asi_trades.replace_one(
                {"_id": trade_id},
                {"_id": trade_id, "device_id": test_dev,
                 "status": "closed", "pnl_usdt": 60.0,
                 "closed_at": now, "created_at": now,
                 "testnet": False, "exchange": "binance",
                 "symbol": "TESTCOIN", "side": "BUY",
                 "qty": 1.0, "entry_price": 1.0},
                upsert=True,
            )
            try:
                await _enforce_daily_profit_limit(db)
                cfg = await db.asi_bot_config.find_one({"_id": test_dev})
                assert cfg is not None
                assert cfg.get("full_enabled") is False, \
                    f"Expected full_enabled False, got {cfg.get('full_enabled')}"
                reason = cfg.get("auto_disabled_reason") or ""
                assert "profit" in reason.lower() or "target" in reason.lower(), \
                    f"Expected profit-target reason, got {reason!r}"
                assert cfg.get("auto_disabled_at")
            finally:
                await db.asi_bot_config.delete_one({"_id": test_dev})
                await db.asi_trades.delete_one({"_id": trade_id})
                client.close()

        asyncio.run(_flow())

    def test_keeps_bot_enabled_when_profit_below_limit(self):
        import sys
        sys.path.insert(0, "/app/backend")
        from asi_bot.scheduler import _enforce_daily_profit_limit

        test_dev = "TEST-iter54-dpl-below-888"
        now = datetime.now(timezone.utc).isoformat()

        async def _flow():
            client, db = _make_db()
            await db.asi_bot_config.replace_one(
                {"_id": test_dev},
                {"_id": test_dev, "device_id": test_dev,
                 "full_enabled": True, "enabled": True,
                 "daily_profit_limit_usdt": 50.0,
                 "daily_loss_limit_usdt": 0.0,
                 "exchange": "binance", "active_testnet": False,
                 "updated_at": now},
                upsert=True,
            )
            trade_id = f"TEST_iter54_below:{test_dev}:1"
            await db.asi_trades.replace_one(
                {"_id": trade_id},
                {"_id": trade_id, "device_id": test_dev,
                 "status": "closed", "pnl_usdt": 30.0,
                 "closed_at": now, "created_at": now,
                 "testnet": False, "exchange": "binance",
                 "symbol": "TESTCOIN", "side": "BUY",
                 "qty": 1.0, "entry_price": 1.0},
                upsert=True,
            )
            try:
                await _enforce_daily_profit_limit(db)
                cfg = await db.asi_bot_config.find_one({"_id": test_dev})
                assert cfg is not None
                assert cfg.get("full_enabled") is True, \
                    f"Expected full_enabled True (profit 30 < limit 50), got {cfg.get('full_enabled')}"
                assert not cfg.get("auto_disabled_reason")
            finally:
                await db.asi_bot_config.delete_one({"_id": test_dev})
                await db.asi_trades.delete_one({"_id": trade_id})
                client.close()

        asyncio.run(_flow())


def teardown_module(_module):
    # Cleanup test bot config via API
    try:
        import pymongo
        client = pymongo.MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
        db = client[os.environ.get("DB_NAME", "aitrade_pro")]
        db.asi_bot_config.delete_one({"_id": TEST_DEVICE_ID})
        client.close()
    except Exception:
        pass
