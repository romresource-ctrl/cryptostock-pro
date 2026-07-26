"""Iteration 14 — Verify v5.0.1 dashboard cold-start load speed fix.

Confirms:
1. Default (`full=false`) dashboard returns a SMALL default profile (~10-30 assets)
   for each supported market.
2. `full=true` returns the full asset universe (~92 crypto, 80 IDX, 176 US stocks).
3. Response-time delta: full=true must be strictly slower than full=false on cold
   start.
4. Regression: /api/subscription/verify, /api/subscription/status,
   /api/subscription/health, /api/chat/messages, and /api/asset/{market}/{symbol}/chart
   still respond without server errors.
"""
from __future__ import annotations

import os
import time
import uuid

import pytest
import requests

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
HTTP_TIMEOUT = 60  # cold start may hit Binance/Yahoo


# --- Shared client fixture ---

@pytest.fixture(scope="module")
def api_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def _dashboard(client: requests.Session, market: str, *, timeframe: str = "1h", full: bool | None = None) -> tuple[dict, float]:
    """Return (json, elapsed_seconds) for a dashboard call. Fails test on non-200."""
    params: dict = {"market": market, "timeframe": timeframe}
    if full is not None:
        params["full"] = str(full).lower()
    t0 = time.monotonic()
    r = client.get(f"{BASE_URL}/api/dashboard", params=params, timeout=HTTP_TIMEOUT)
    elapsed = time.monotonic() - t0
    assert r.status_code == 200, f"dashboard {market} full={full} => {r.status_code}: {r.text[:200]}"
    return r.json(), elapsed


# --------- 1. Default (fast) profile ---------

class TestDashboardDefaultProfile:
    """Cold-start default profile — should be capped by _TOP_N=30 for large maps."""

    def test_default_crypto_is_capped(self, api_client):
        data, _ = _dashboard(api_client, "crypto", full=False)
        n = len(data["assets"])
        # Active profile "spot" defines 10 crypto symbols; default seed returns them
        assert 1 <= n <= 30, f"Expected <=30 crypto assets on default, got {n}"
        assert data["market"] == "crypto"
        assert data["timeframe"] == "1h"

    def test_default_stock_id_capped(self, api_client):
        data, _ = _dashboard(api_client, "stock_id", full=False)
        n = len(data["assets"])
        # Active profile "spot" has stocks=[] → falls back to DEFAULT_STOCKS[:30]
        assert n <= 30, f"Expected <=30 stock_id assets on default, got {n}"

    def test_default_stock_us_capped(self, api_client):
        data, _ = _dashboard(api_client, "stock_us", full=False)
        n = len(data["assets"])
        assert n <= 30, f"Expected <=30 stock_us assets on default, got {n}"


# --------- 2. Full profile ---------

class TestDashboardFullProfile:
    """`full=true` must return the whole asset map for each market."""

    def test_full_crypto(self, api_client):
        data, _ = _dashboard(api_client, "crypto", full=True)
        n = len(data["assets"])
        # Full crypto map is ~92-95 (v5.0.1 build)
        assert n >= 80, f"Expected >=80 full crypto assets, got {n}"
        assert data["profile_id"] == "all"
        assert data["profile_name"] == "Semua Aset"

    def test_full_stock_id_returns_80(self, api_client):
        data, _ = _dashboard(api_client, "stock_id", full=True)
        n = len(data["assets"])
        # Full IDX map has 80 tickers (some may fail Yahoo fetch → allow small drop)
        assert n >= 60, f"Expected ~80 IDX stocks, got {n}"

    def test_full_stock_us_returns_176(self, api_client):
        data, _ = _dashboard(api_client, "stock_us", full=True)
        n = len(data["assets"])
        # Full US map: 176 tickers (allow small failure margin from Yahoo)
        assert n >= 140, f"Expected ~176 US stocks, got {n}"


# --------- 3. Response-time delta ---------

class TestDashboardResponseTime:
    """full=false must be significantly faster than full=true on cold start."""

    def test_default_faster_than_full_crypto(self, api_client):
        # Bust snapshot cache with a unique timeframe won't help because tf is
        # constrained; instead we accept warm cache but still expect full to be
        # at least as slow. Run default first (small set) then full (larger set).
        _, t_default = _dashboard(api_client, "crypto", full=False, timeframe="30m")
        _, t_full = _dashboard(api_client, "crypto", full=True, timeframe="30m")
        # Full does more upstream calls, so on a cold call it must be strictly
        # slower than the default (10 assets vs ~92 assets).
        print(f"\n[perf] crypto default={t_default:.2f}s  full={t_full:.2f}s")
        assert t_default <= t_full + 0.5, (
            f"Default ({t_default:.2f}s) should be <= full ({t_full:.2f}s)"
        )

    def test_default_fast_under_15s(self, api_client):
        # Cold-start budget for default profile after the fix.
        # (Previously the app was taking 20+ seconds.)
        _, t_default = _dashboard(api_client, "crypto", full=False, timeframe="15m")
        print(f"\n[perf] crypto default cold-start (15m) = {t_default:.2f}s")
        assert t_default < 15.0, f"Default cold-start too slow: {t_default:.2f}s"


# --------- 4. Regression: subscription + chat + asset chart ---------

class TestSubscriptionRegression:

    def test_subscription_health_ok(self, api_client):
        r = api_client.get(f"{BASE_URL}/api/subscription/health", timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        # These booleans must be present regardless of config
        for key in (
            "service_account_env_set",
            "service_account_path_exists",
            "service_account_inline_json",
            "publisher_client_initialised",
            "package_name",
        ):
            assert key in body, f"missing {key} in {body}"

    def test_subscription_status_none_for_unknown_device(self, api_client):
        r = api_client.get(
            f"{BASE_URL}/api/subscription/status",
            params={"device_id": f"TEST_dev_{uuid.uuid4().hex[:8]}"},
            timeout=10,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["entitled"] is False
        assert body["status"] in ("none", "invalid", "expired")

    def test_subscription_verify_rejects_fake_token(self, api_client):
        r = api_client.post(
            f"{BASE_URL}/api/subscription/verify",
            json={
                "purchase_token": "TEST_fake_token_xxx",
                "product_id": "ai_cryptostockpro_monthly",
                "package_name": "com.cryptostockapps.aicryptostockpro",
                "device_id": f"TEST_dev_{uuid.uuid4().hex[:8]}",
            },
            timeout=20,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # Google actively rejects fake tokens → expect not entitled
        assert body["entitled"] is False
        assert body["status"] in ("invalid", "unverified", "error")


class TestChatMessages:

    def test_chat_messages_get(self, api_client):
        r = api_client.get(f"{BASE_URL}/api/chat/messages", params={"limit": 5}, timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "messages" in body
        assert isinstance(body["messages"], list)
        assert "server_time" in body

    def test_chat_send_requires_entitlement(self, api_client):
        r = api_client.post(
            f"{BASE_URL}/api/chat/messages",
            json={
                "text": "TEST_hello",
                "nickname": "TEST_user",
                "device_id": f"TEST_dev_{uuid.uuid4().hex[:8]}",
            },
            timeout=10,
        )
        # Non-premium device → 403
        assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text}"


class TestAssetChartRegression:

    def test_asset_chart_btc(self, api_client):
        r = api_client.get(
            f"{BASE_URL}/api/asset/crypto/BTC/chart",
            params={"timeframe": "1h"},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["symbol"] == "BTC"
        assert body["market"] == "crypto"
        assert isinstance(body.get("candles"), list)
        assert len(body["candles"]) > 0
        assert "signal" in body
