"""Iteration 15 — v5.0.3 backend verification.

Verifies the fix in server.py:660 where the empty-symbol fallback dict now
covers ALL 7 markets (crypto, stock_id, etf, stock_us, gold_silver, commodity,
forex). Previously only 5 markets had a fallback, causing empty columns when
the active profile had empty lists.

Also regressions on /api/subscription/{verify,health} and /api/chat/messages.
"""
from __future__ import annotations

import os

import pytest
import requests

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")


@pytest.fixture(scope="module")
def api_client() -> requests.Session:
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ---- Seven-market default (full=false) fallback verification ----
# Expected mins per review_request: crypto>=10, stock_id>=20, etf>=20,
# stock_us>=20, gold_silver>=3, commodity>=15, forex>=20
MARKET_MINIMUMS = {
    "crypto": 10,
    "stock_id": 20,
    "etf": 20,
    "stock_us": 20,
    "gold_silver": 3,
    "commodity": 15,
    "forex": 20,
}


class TestSevenMarketDefaultFallback:
    """v5.0.3 fix: every market must return non-empty assets on default full=false."""

    @pytest.mark.parametrize("market,min_count", list(MARKET_MINIMUMS.items()))
    def test_market_default_non_empty(self, api_client, market, min_count):
        url = f"{BASE_URL}/api/dashboard?market={market}&timeframe=1h&full=false"
        r = api_client.get(url, timeout=90)
        assert r.status_code == 200, f"{market}: {r.status_code} {r.text[:200]}"
        body = r.json()
        assets = body.get("assets") or []
        assert isinstance(assets, list)
        assert len(assets) >= min_count, (
            f"{market}: expected >= {min_count} assets, got {len(assets)}"
        )
        # Sanity: each asset has a symbol and price
        for a in assets[:3]:
            assert a.get("symbol"), f"{market}: missing symbol in {a}"
            # Some upstream flakes may return 0 for illiquid tickers; we only
            # require the shape here.
            assert "price" in a, f"{market}: missing price in {a}"
        print(f"[{market}] default returned {len(assets)} assets (>= {min_count})")


# ---- Regression: subscription endpoints ----
class TestSubscriptionRegression:
    def test_subscription_health(self, api_client):
        r = api_client.get(f"{BASE_URL}/api/subscription/health", timeout=15)
        assert r.status_code == 200, r.text[:200]
        body = r.json()
        # Just verify it's a dict/object with something
        assert isinstance(body, dict)

    def test_subscription_verify_invalid_token(self, api_client):
        # A garbage token should return 200 with entitled=false OR 4xx — either
        # is acceptable, we just want no 5xx crash.
        r = api_client.post(
            f"{BASE_URL}/api/subscription/verify",
            json={
                "device_id": "TEST_iter15_device",
                "purchase_token": "TEST_FAKE_TOKEN",
                "product_id": "premium_monthly",
            },
            timeout=30,
        )
        assert r.status_code < 500, f"5xx on verify: {r.status_code} {r.text[:200]}"
        if r.status_code == 200:
            body = r.json()
            # entitled should be falsy for garbage token
            assert body.get("entitled") in (False, None), (
                f"fake token unexpectedly entitled: {body}"
            )


# ---- Regression: chat messages ----
class TestChatMessagesRegression:
    def test_chat_messages_get(self, api_client):
        r = api_client.get(f"{BASE_URL}/api/chat/messages?limit=10", timeout=15)
        assert r.status_code == 200, r.text[:200]
        body = r.json()
        assert "messages" in body
        assert isinstance(body["messages"], list)

    def test_chat_messages_post_non_premium_forbidden(self, api_client):
        # Non-premium device_id should be rejected (403 or similar).
        r = api_client.post(
            f"{BASE_URL}/api/chat/messages",
            json={
                "text": "TEST_iter15 hello",
                "nickname": "TEST_it15",
                "device_id": "TEST_iter15_nonpremium_device",
            },
            timeout=15,
        )
        assert r.status_code in (401, 402, 403), (
            f"expected 4xx for non-premium, got {r.status_code} {r.text[:200]}"
        )
