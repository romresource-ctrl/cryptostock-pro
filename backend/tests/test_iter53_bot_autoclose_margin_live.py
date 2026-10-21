"""Live sanity test for /api/asi/bot persistence of auto_close_pct & margin_usdt.
Runs against EXPO_BACKEND_URL (public preview). Non-destructive: uses a
scratch device_id prefixed with TEST_."""
from __future__ import annotations

import os
import time
import pytest
import requests

BASE_URL = os.environ.get("EXPO_BACKEND_URL", "").rstrip("/")
DEVICE_ID = f"TEST_iter53_{int(time.time())}"


@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def _base_payload(**over):
    body = {
        "enabled": False,
        "exchange": "binance",
        "mode": "semi",
        "max_trades_per_day": 5,
        "risk_pct": 5.0,
        "leverage": 10,
        "whitelist": [],
        "profile": "scalper",
        "min_confidence": 75,
        "daily_loss_limit_usdt": 0.0,
        "semi_enabled": False,
        "full_enabled": False,
        "tp_count": 3,
        "auto_close_pct": 0,
        "margin_usdt": 0.0,
        "trailing_callback_rate": 0.0,
        "margin_mode": "isolated",
        "active_testnet": True,
        "entry_mode": "limit",
        "disclaimer_ack": False,
        "signal_source": "asi_bot",
    }
    body.update(over)
    return body


def test_save_bot_with_autoclose_and_margin(api):
    r = api.post(f"{BASE_URL}/api/asi/bot?device_id={DEVICE_ID}",
                 json=_base_payload(auto_close_pct=25, margin_usdt=50.0))
    assert r.status_code == 200, r.text
    assert r.json()["auto_close_pct"] == 25
    assert r.json()["margin_usdt"] == 50.0


def test_get_bot_returns_persisted(api):
    r = api.get(f"{BASE_URL}/api/asi/bot?device_id={DEVICE_ID}")
    assert r.status_code == 200
    j = r.json()
    assert j["auto_close_pct"] == 25
    assert j["margin_usdt"] == 50.0
    assert j["exists"] is True


@pytest.mark.parametrize("pct", [0, 10, 15, 20, 25, 50, 100])
def test_autoclose_valid_values(api, pct):
    r = api.post(f"{BASE_URL}/api/asi/bot?device_id={DEVICE_ID}",
                 json=_base_payload(auto_close_pct=pct))
    assert r.status_code == 200, (pct, r.text)
    assert r.json()["auto_close_pct"] == pct


@pytest.mark.parametrize("bad_pct", [30, 5, 200, -10])
def test_autoclose_invalid_rejected(api, bad_pct):
    r = api.post(f"{BASE_URL}/api/asi/bot?device_id={DEVICE_ID}",
                 json=_base_payload(auto_close_pct=bad_pct))
    assert r.status_code == 422, (bad_pct, r.status_code, r.text[:300])


def test_margin_usdt_negative_rejected(api):
    r = api.post(f"{BASE_URL}/api/asi/bot?device_id={DEVICE_ID}",
                 json=_base_payload(margin_usdt=-5.0))
    assert r.status_code == 422, r.text


def test_margin_usdt_zero_and_positive_ok(api):
    for m in (0.0, 10.5, 1000.0):
        r = api.post(f"{BASE_URL}/api/asi/bot?device_id={DEVICE_ID}",
                     json=_base_payload(margin_usdt=m))
        assert r.status_code == 200, (m, r.text)
        assert r.json()["margin_usdt"] == m
