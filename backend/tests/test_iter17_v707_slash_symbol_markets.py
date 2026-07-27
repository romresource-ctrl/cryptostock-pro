"""
Iteration 17 — v7.0.7 slash-symbol + market-whitelist regression tests.

Covers:
 - Dashboard 8 markets (previously crashed 500 for forex / gold_silver)
 - Asset detail chart / track-record / news for commodity, forex, gold_silver, world_stocks
   (slash-encoded EUR-USD / XAU-USD / XAG-USD → backend must decode to EUR/USD etc.)
 - Analyze endpoint slash-encoding
 - Search returns correct market segment (CORN → commodity, EUR → forex, XAU → gold_silver)
 - Chat retention (POST rejected 403 without entitlement, GET returns messages array with 16h retention)
 - GET /api/ai/models returns 3 models
 - GET /api/subscription/health has publisher_client_initialised
"""

import os
import time
import pytest
import requests
from datetime import datetime, timezone, timedelta

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    BASE_URL = os.environ.get("EXPO_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL must be set"

API = f"{BASE_URL}/api"


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ---------- Dashboard for all 8 markets ----------
DASHBOARD_MARKETS = ["crypto", "etf", "stock_id", "stock_us", "world_stocks", "gold_silver", "commodity", "forex"]


@pytest.mark.parametrize("market", DASHBOARD_MARKETS)
def test_dashboard_market_returns_200_with_assets(client, market):
    r = client.get(f"{API}/dashboard", params={"market": market, "timeframe": "1h"}, timeout=45)
    assert r.status_code == 200, f"{market}: {r.status_code} — {r.text[:300]}"
    body = r.json()
    assert "assets" in body, f"{market}: no assets key — {body}"
    assert isinstance(body["assets"], list), f"{market}: assets not a list"
    assert len(body["assets"]) > 0, f"{market}: assets list empty"


# ---------- Asset detail chart endpoints ----------
CHART_CASES = [
    ("commodity", "CORN"),
    ("commodity", "BRENT"),
    ("forex", "EUR-USD"),
    ("forex", "GBP-USD"),
    ("gold_silver", "XAU-USD"),
    ("gold_silver", "XAG-USD"),
    ("world_stocks", "AAPL"),
    ("crypto", "BTC"),
]


@pytest.mark.parametrize("market,symbol", CHART_CASES)
def test_asset_chart_returns_200(client, market, symbol):
    r = client.get(f"{API}/asset/{market}/{symbol}/chart", params={"timeframe": "1h"}, timeout=45)
    assert r.status_code == 200, f"{market}/{symbol}: {r.status_code} — {r.text[:300]}"
    body = r.json()
    # Loose contract: must have some form of candle data
    assert isinstance(body, dict), f"{market}/{symbol}: body not dict"
    # At least one recognised key
    keys = set(body.keys())
    assert keys & {"candles", "chart", "data", "ohlc", "series", "prices"}, (
        f"{market}/{symbol}: unrecognised chart body keys={list(keys)[:8]}"
    )


@pytest.mark.parametrize("market,symbol", CHART_CASES)
def test_asset_track_record_returns_200(client, market, symbol):
    r = client.get(f"{API}/asset/{market}/{symbol}/track-record", timeout=45)
    assert r.status_code == 200, f"{market}/{symbol}: {r.status_code} — {r.text[:300]}"
    body = r.json()
    assert isinstance(body, dict), f"{market}/{symbol}: body not dict"


@pytest.mark.parametrize("market,symbol", CHART_CASES)
def test_asset_news_returns_200(client, market, symbol):
    r = client.get(f"{API}/asset/{market}/{symbol}/news", timeout=45)
    assert r.status_code == 200, f"{market}/{symbol}: {r.status_code} — {r.text[:300]}"
    body = r.json()
    assert isinstance(body, (dict, list)), f"{market}/{symbol}: unexpected body type"


# ---------- Analyze endpoint (slash-encoded) ----------
@pytest.mark.parametrize("market,symbol", [
    ("commodity", "CORN"),
    ("forex", "EUR-USD"),
])
def test_asset_analyze_no_500(client, market, symbol):
    r = client.post(f"{API}/asset/{market}/{symbol}/analyze", params={"timeframe": "1h", "lang": "id"}, timeout=90)
    # 200 preferred; 4xx allowed (e.g. entitlement); 5xx NOT allowed
    assert r.status_code < 500, f"{market}/{symbol} analyze crashed: {r.status_code} — {r.text[:500]}"
    if r.status_code == 200:
        body = r.json()
        assert isinstance(body, dict)


# ---------- Search: market segment must be preserved ----------
def test_search_corn_returns_commodity(client):
    r = client.get(f"{API}/search", params={"q": "CORN"}, timeout=30)
    assert r.status_code == 200, f"search CORN: {r.status_code} — {r.text[:300]}"
    body = r.json()
    hits = body.get("hits") or body.get("results") or []
    assert len(hits) > 0, f"search CORN empty — {body}"
    assert hits[0].get("market") == "commodity", (
        f"search CORN first hit market={hits[0].get('market')} (expected 'commodity') — {hits[0]}"
    )


def test_search_eur_has_forex_hit(client):
    r = client.get(f"{API}/search", params={"q": "EUR"}, timeout=30)
    assert r.status_code == 200
    hits = r.json().get("hits") or r.json().get("results") or []
    assert any(h.get("market") == "forex" for h in hits), (
        f"no forex hit for EUR — markets={[h.get('market') for h in hits[:10]]}"
    )


def test_search_xau_has_gold_silver_hit(client):
    r = client.get(f"{API}/search", params={"q": "XAU"}, timeout=30)
    assert r.status_code == 200
    hits = r.json().get("hits") or r.json().get("results") or []
    assert any(h.get("market") == "gold_silver" for h in hits), (
        f"no gold_silver hit for XAU — markets={[h.get('market') for h in hits[:10]]}"
    )


# ---------- Chat retention ----------
def test_chat_post_without_entitlement_403(client):
    payload = {"nickname": "TESTuser", "device_id": f"TEST_nopremium_{int(time.time())}", "text": "hello"}
    r = client.post(f"{API}/chat/messages", json=payload, timeout=20)
    # Expected 403 per problem statement; 401 also acceptable
    assert r.status_code in (401, 403), f"expected 401/403 got {r.status_code} — {r.text[:300]}"


def test_chat_get_messages_returns_200_with_16h_retention(client):
    r = client.get(f"{API}/chat/messages", params={"limit": 100}, timeout=20)
    assert r.status_code == 200, f"GET chat: {r.status_code} — {r.text[:300]}"
    body = r.json()
    assert "messages" in body, f"no messages key — {body}"
    msgs = body["messages"]
    assert isinstance(msgs, list)
    if msgs:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=16, minutes=5)  # small grace
        for m in msgs:
            ts = m.get("created_at") or m.get("timestamp")
            assert ts, f"message missing created_at: {m}"
            # ISO 8601 parse
            try:
                dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            except Exception as e:
                pytest.fail(f"cannot parse created_at={ts}: {e}")
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            assert dt >= cutoff, f"message older than 16h: {ts}"


# ---------- AI models ----------
def test_ai_models_returns_three(client):
    r = client.get(f"{API}/ai/models", timeout=15)
    assert r.status_code == 200, f"{r.status_code} — {r.text[:300]}"
    body = r.json()
    models = body.get("models") or body if isinstance(body, list) else body.get("models", [])
    assert isinstance(models, list)
    assert len(models) == 3, f"expected 3 models, got {len(models)}: {models}"


# ---------- Subscription health ----------
def test_subscription_health_has_publisher_client_initialised(client):
    r = client.get(f"{API}/subscription/health", timeout=15)
    assert r.status_code == 200, f"{r.status_code} — {r.text[:300]}"
    body = r.json()
    assert "publisher_client_initialised" in body, f"missing key — {body}"
