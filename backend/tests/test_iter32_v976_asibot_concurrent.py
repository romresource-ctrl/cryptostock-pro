"""v9.7.6 — ASI-Bot concurrent Semi+Full state, mode badge, manual close.

Test scope (from review request):
  (1) POST/GET /api/asi/bot accepts & returns semi_enabled & full_enabled
      independently (both true / both false / one of each).
  (2) GET /api/asi/trades returns `_id` as string per item (so the UI can
      call POST /api/asi/trades/{id}/close).
  (3) POST /api/asi/trades/{id}/close error branches:
        - 404 for non-existent trade.
        - already-closed trade → {ok:true, already_closed:true}.
        - open trade with no credential → 400 "credential missing".
  (4) POST /api/asi/trades/close-all regression — empty & no-cred paths.
  (5) /api/asi/egress-ip & /api/asi/server-ip regression.

NOTE: We DO NOT exercise real exchange calls — we exercise schema &
error branches. Real credential + Binance testnet is out of scope.
"""
from __future__ import annotations

import os
import uuid
from urllib.parse import urlencode

import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient

BASE_URL = os.environ.get("EXPO_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"
MONGO_URL = os.environ.get("MONGO_URL") or "mongodb://localhost:27017"
# Match the backend's live DB. If backend/.env defines DB_NAME, honor it.
DB_NAME = os.environ.get("DB_NAME") or "aitrade_pro"

DEVICE_ID = f"t1-9767-{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="module")
def api_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    yield s
    s.close()


# --- (5) regression smoke -------------------------------------------------
def test_egress_ip(api_client):
    r = api_client.get(f"{API}/asi/egress-ip", timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "ok" in data


def test_server_ip(api_client):
    r = api_client.get(f"{API}/asi/server-ip", timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "ip" in data and isinstance(data["ip"], str)


# --- (1) BotConfig semi/full independence --------------------------------
def _save_bot(api_client, **overrides):
    body = {
        "enabled": False,
        "exchange": "binance",
        "mode": "semi",
        "max_trades_per_day": 5,
        "risk_pct": 5.0,
        "leverage": 10,
        "whitelist": [],
        "min_confidence": 75,
        "daily_loss_limit_usdt": 0.0,
        "semi_enabled": False,
        "full_enabled": False,
        "tp_count": 3,
        "trailing_callback_rate": 2.0,
    }
    body.update(overrides)
    return api_client.post(
        f"{API}/asi/bot?device_id={DEVICE_ID}", json=body, timeout=10,
    )


def _get_bot(api_client):
    return api_client.get(f"{API}/asi/bot?device_id={DEVICE_ID}", timeout=10)


def test_bot_both_disabled(api_client):
    r = _save_bot(api_client, semi_enabled=False, full_enabled=False)
    assert r.status_code == 200, r.text
    g = _get_bot(api_client).json()
    assert g["semi_enabled"] is False
    assert g["full_enabled"] is False
    assert g["exists"] is True


def test_bot_only_semi(api_client):
    r = _save_bot(api_client, semi_enabled=True, full_enabled=False, mode="semi", enabled=True)
    assert r.status_code == 200, r.text
    g = _get_bot(api_client).json()
    assert g["semi_enabled"] is True
    assert g["full_enabled"] is False


def test_bot_only_full(api_client):
    r = _save_bot(api_client, semi_enabled=False, full_enabled=True, mode="full", enabled=True)
    assert r.status_code == 200, r.text
    g = _get_bot(api_client).json()
    assert g["semi_enabled"] is False
    assert g["full_enabled"] is True


def test_bot_both_enabled_concurrently(api_client):
    """Core v9.7.6 requirement: semi AND full both True simultaneously."""
    r = _save_bot(api_client, semi_enabled=True, full_enabled=True, enabled=True, mode="full")
    assert r.status_code == 200, r.text
    g = _get_bot(api_client).json()
    assert g["semi_enabled"] is True
    assert g["full_enabled"] is True
    # Reset to clean state.
    _save_bot(api_client, semi_enabled=False, full_enabled=False)


# --- (2) GET /trades returns _id as string --------------------------------
@pytest.mark.asyncio
async def test_list_trades_includes_string_id(api_client):
    """Seed a trade directly via Mongo, then GET /trades and assert _id string."""
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]
    seeded_id = f"{DEVICE_ID}:seed-{uuid.uuid4().hex[:6]}"
    doc = {
        "_id": seeded_id,
        "device_id": DEVICE_ID,
        "exchange": "binance",
        "symbol": "BTCUSDT",
        "side": "BUY",
        "qty": 0.001,
        "entry_price": 50000.0,
        "stop_loss": 49000.0,
        "take_profits": [51000.0, 52000.0, 53000.0],
        "leverage": 10,
        "margin_usdt": 5.0,
        "status": "open",
        "mode": "semi",
        "pnl_usdt": 0.0,
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    await db.asi_trades.replace_one({"_id": seeded_id}, doc, upsert=True)
    try:
        r = api_client.get(f"{API}/asi/trades?device_id={DEVICE_ID}", timeout=10)
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        assert len(items) >= 1
        match = [x for x in items if x.get("_id") == seeded_id]
        assert match, f"seeded trade missing from list. items={items}"
        assert isinstance(match[0]["_id"], str)
        assert match[0]["mode"] == "semi"
    finally:
        await db.asi_trades.delete_one({"_id": seeded_id})
        client.close()


# --- (3) manual close error branches --------------------------------------
def test_close_nonexistent_returns_404(api_client):
    bogus = f"{DEVICE_ID}:does-not-exist-{uuid.uuid4().hex[:6]}"
    r = api_client.post(
        f"{API}/asi/trades/{bogus}/close?device_id={DEVICE_ID}", timeout=10,
    )
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_close_already_closed_returns_ok(api_client):
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]
    tid = f"{DEVICE_ID}:closed-{uuid.uuid4().hex[:6]}"
    await db.asi_trades.replace_one(
        {"_id": tid},
        {
            "_id": tid, "device_id": DEVICE_ID, "exchange": "binance",
            "symbol": "ETHUSDT", "side": "SELL", "status": "closed",
            "qty": 0.01, "entry_price": 3000.0, "mode": "semi",
            "created_at": "2026-01-01T00:00:00+00:00",
        },
        upsert=True,
    )
    try:
        r = api_client.post(
            f"{API}/asi/trades/{tid}/close?device_id={DEVICE_ID}", timeout=10,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True
        assert body.get("already_closed") is True
    finally:
        await db.asi_trades.delete_one({"_id": tid})
        client.close()


@pytest.mark.asyncio
async def test_close_open_without_credential_returns_400(api_client):
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]
    tid = f"{DEVICE_ID}:open-{uuid.uuid4().hex[:6]}"
    await db.asi_trades.replace_one(
        {"_id": tid},
        {
            "_id": tid, "device_id": DEVICE_ID, "exchange": "binance",
            "symbol": "BTCUSDT", "side": "BUY", "status": "open",
            "qty": 0.001, "entry_price": 50000.0, "mode": "full",
            "created_at": "2026-01-01T00:00:00+00:00",
        },
        upsert=True,
    )
    # Ensure NO credential for this device/binance:
    await db.asi_credentials.delete_one({"_id": f"{DEVICE_ID}:binance"})
    try:
        r = api_client.post(
            f"{API}/asi/trades/{tid}/close?device_id={DEVICE_ID}", timeout=10,
        )
        assert r.status_code == 400, r.text
        detail = r.json().get("detail", "")
        assert "credential missing" in str(detail).lower()
    finally:
        await db.asi_trades.delete_one({"_id": tid})
        client.close()


# --- (4) close-all regression --------------------------------------------
def test_close_all_empty(api_client):
    unique_dev = f"nothing-{uuid.uuid4().hex[:6]}"
    r = api_client.post(
        f"{API}/asi/trades/close-all?device_id={unique_dev}", timeout=10,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("closed") == 0
    assert body.get("errors") == []
