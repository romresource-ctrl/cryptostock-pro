"""
Iteration 18 — v7.0.9 stability/polish regression tests.

Scope (per review_request):
 - REGRESSION: dashboard 8 markets 200 + populated assets[] (no forex/gold_silver 500).
 - REGRESSION: /api/asset/{market}/{symbol}/{chart,analyze,track-record,news} for
   commodity/CORN, forex/EUR-USD, gold_silver/XAU-USD, crypto/BTC → 200 with slash decode.
 - REGRESSION: search returns correct market for CORN / EUR / XAU.
 - NEW: /api/chat/messages GET → 200 items within last 16h.
 - NEW: pymongo verifies chat_messages has created_at_1 index (bootstrap task ran).
 - NEW: cache verify — 3 back-to-back /asset/commodity/CORN/chart calls; correctness
   check (all three return candles with the SAME latest timestamp within 60s TTL).
 - PRESERVE: /api/subscription/health has boolean 'service_account_env_set' &
   'publisher_client_initialised' AND does NOT leak private_key/JSON path/PII.
 - PRESERVE: /api/subscription/status?device_id=fresh-... → {status:'none', entitled:false}.
 - PRESERVE: POST /api/subscription/verify with fake token → 200/400 but entitled != true.
 - PRESERVE: /api/ai/models → 3 models.
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


# ---------------- Dashboard: 8 markets ----------------
DASHBOARD_MARKETS = [
    "crypto", "etf", "stock_id", "stock_us",
    "world_stocks", "gold_silver", "commodity", "forex",
]


@pytest.mark.parametrize("market", DASHBOARD_MARKETS)
def test_dashboard_market_200_populated(client, market):
    r = client.get(f"{API}/dashboard", params={"market": market, "timeframe": "1h"}, timeout=45)
    assert r.status_code == 200, f"{market}: {r.status_code} — {r.text[:300]}"
    body = r.json()
    assert isinstance(body.get("assets"), list) and len(body["assets"]) > 0, (
        f"{market}: assets empty/missing — {body}"
    )


# ---------------- Asset detail suite for the four key symbols ----------------
KEY_CASES = [
    ("commodity", "CORN"),
    ("forex", "EUR-USD"),
    ("gold_silver", "XAU-USD"),
    ("crypto", "BTC"),
]


@pytest.mark.parametrize("market,symbol", KEY_CASES)
def test_asset_chart_200(client, market, symbol):
    r = client.get(f"{API}/asset/{market}/{symbol}/chart", params={"timeframe": "1h"}, timeout=45)
    assert r.status_code == 200, f"{market}/{symbol}: {r.status_code} — {r.text[:300]}"
    body = r.json()
    assert isinstance(body, dict)
    keys = set(body.keys())
    assert keys & {"candles", "chart", "data", "ohlc", "series", "prices"}, (
        f"{market}/{symbol}: unrecognised chart keys={list(keys)[:8]}"
    )


@pytest.mark.parametrize("market,symbol", KEY_CASES)
def test_asset_track_record_200(client, market, symbol):
    r = client.get(f"{API}/asset/{market}/{symbol}/track-record", timeout=45)
    assert r.status_code == 200, f"{market}/{symbol}: {r.status_code} — {r.text[:300]}"


@pytest.mark.parametrize("market,symbol", KEY_CASES)
def test_asset_news_200(client, market, symbol):
    r = client.get(f"{API}/asset/{market}/{symbol}/news", timeout=45)
    assert r.status_code == 200, f"{market}/{symbol}: {r.status_code} — {r.text[:300]}"


@pytest.mark.parametrize("market,symbol", KEY_CASES)
def test_asset_analyze_no_500(client, market, symbol):
    r = client.post(f"{API}/asset/{market}/{symbol}/analyze",
                    params={"timeframe": "1h", "lang": "id"}, timeout=90)
    assert r.status_code < 500, f"{market}/{symbol} analyze crashed: {r.status_code} — {r.text[:500]}"


# ---------------- Search cross-market ----------------
def test_search_corn_first_hit_commodity(client):
    # Small retry loop for Yahoo cold-start flakiness noted in iter17.
    last_body = None
    for _ in range(3):
        r = client.get(f"{API}/search", params={"q": "CORN"}, timeout=30)
        assert r.status_code == 200
        body = r.json()
        hits = body.get("hits") or body.get("results") or []
        if hits and hits[0].get("market") == "commodity":
            return
        last_body = body
        time.sleep(1)
    pytest.fail(f"search CORN never returned commodity as first hit: {last_body}")


def test_search_eur_has_forex_hit(client):
    r = client.get(f"{API}/search", params={"q": "EUR"}, timeout=30)
    assert r.status_code == 200
    hits = r.json().get("hits") or r.json().get("results") or []
    assert any(h.get("market") == "forex" for h in hits), (
        f"no forex hit for EUR — {[h.get('market') for h in hits[:10]]}"
    )


def test_search_xau_has_gold_silver_hit(client):
    r = client.get(f"{API}/search", params={"q": "XAU"}, timeout=30)
    assert r.status_code == 200
    hits = r.json().get("hits") or r.json().get("results") or []
    assert any(h.get("market") == "gold_silver" for h in hits), (
        f"no gold_silver hit for XAU — {[h.get('market') for h in hits[:10]]}"
    )


# ---------------- Chat retention + Mongo index ----------------
def test_chat_get_messages_within_16h(client):
    r = client.get(f"{API}/chat/messages", params={"limit": 100}, timeout=20)
    assert r.status_code == 200, f"{r.status_code} — {r.text[:300]}"
    body = r.json()
    assert isinstance(body.get("messages"), list), f"no messages key — {body}"
    cutoff = datetime.now(timezone.utc) - timedelta(hours=16, minutes=5)
    for m in body["messages"]:
        ts = m.get("created_at") or m.get("timestamp")
        assert ts, f"message missing created_at: {m}"
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        assert dt >= cutoff, f"message older than 16h: {ts}"


def test_chat_messages_has_created_at_index():
    """NEW iter18: startup bootstrap must create created_at_1 index."""
    from pymongo import MongoClient
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("DB_NAME", "aitrade_pro")
    c = MongoClient(mongo_url)
    idxs = list(c[db_name].chat_messages.list_indexes())
    names = {i.get("name") for i in idxs}
    assert "created_at_1" in names, f"created_at_1 index missing — got {names}"


# ---------------- Cache verify: 3 back-to-back /asset/commodity/CORN/chart ----------------
def _latest_candle_ts(body: dict):
    for k in ("candles", "chart", "data", "ohlc", "series", "prices"):
        arr = body.get(k)
        if isinstance(arr, list) and arr:
            last = arr[-1]
            if isinstance(last, dict):
                return last.get("t") or last.get("time") or last.get("timestamp") or last.get("date")
            if isinstance(last, (list, tuple)) and last:
                return last[0]
    return None


def test_asset_chart_cache_correctness(client):
    url = f"{API}/asset/commodity/CORN/chart"
    params = {"timeframe": "1h"}
    latest_ts = []
    timings = []
    for _ in range(3):
        t0 = time.time()
        r = client.get(url, params=params, timeout=45)
        timings.append(time.time() - t0)
        assert r.status_code == 200, f"cache test: {r.status_code} — {r.text[:300]}"
        body = r.json()
        latest_ts.append(_latest_candle_ts(body))
    # All three must have same latest candle timestamp (cache should not mutate correctness)
    assert latest_ts[0] is not None, f"no latest candle ts extracted; body keys={list(body.keys())[:8]}"
    assert latest_ts[0] == latest_ts[1] == latest_ts[2], (
        f"cache correctness broken: latest_ts={latest_ts}"
    )
    # Non-strict perf: 2nd/3rd call typically < 1st, but do NOT fail if not — problem statement
    # says "any HTTP 200 is acceptable". Just log.
    print(f"[cache-timings] cold={timings[0]:.2f}s warm1={timings[1]:.2f}s warm2={timings[2]:.2f}s")


# ---------------- Subscription: health, status, verify ----------------
def test_subscription_health_shape(client):
    r = client.get(f"{API}/subscription/health", timeout=15)
    assert r.status_code == 200, f"{r.status_code} — {r.text[:300]}"
    body = r.json()
    # Boolean fields required
    assert "service_account_env_set" in body, f"missing key — {body}"
    assert "publisher_client_initialised" in body, f"missing key — {body}"
    assert isinstance(body["service_account_env_set"], bool)
    assert isinstance(body["publisher_client_initialised"], bool)
    # No PII / secrets
    raw = r.text.lower()
    for forbidden in ("private_key", "-----begin", "client_email", ".json", "service-account"):
        assert forbidden not in raw, f"subscription/health leaked '{forbidden}' — body={raw[:400]}"


def test_subscription_status_fresh_device(client):
    device_id = f"fresh-device-abc123-{int(time.time())}"
    r = client.get(f"{API}/subscription/status", params={"device_id": device_id}, timeout=15)
    assert r.status_code == 200, f"{r.status_code} — {r.text[:300]}"
    body = r.json()
    assert body.get("status") == "none", f"status={body.get('status')} — {body}"
    assert body.get("entitled") is False, f"entitled={body.get('entitled')} — {body}"


def test_subscription_verify_fake_token_not_entitled(client):
    payload = {
        "device_id": f"TEST_iter18_fake_{int(time.time())}",
        "purchase_token": "TEST_FAKE_TOKEN_ITER18",
        "product_id": "premium_1month",
    }
    r = client.post(f"{API}/subscription/verify", json=payload, timeout=30)
    # 200 (rejected via body) or 400 (invalid) both acceptable. Must NOT be entitled=true.
    assert r.status_code in (200, 400, 401, 403, 422), f"{r.status_code} — {r.text[:300]}"
    if r.status_code == 200:
        body = r.json()
        assert body.get("entitled") is not True, f"fake token entitled! — {body}"


# ---------------- AI models ----------------
def test_ai_models_returns_three(client):
    r = client.get(f"{API}/ai/models", timeout=15)
    assert r.status_code == 200
    body = r.json()
    models = body if isinstance(body, list) else body.get("models", [])
    assert isinstance(models, list)
    assert len(models) == 3, f"expected 3 models, got {len(models)}: {models}"
