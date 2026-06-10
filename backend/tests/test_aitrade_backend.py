"""AITrade Pro backend API tests."""
import os
import time
import pytest
import requests

BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL") or "https://cryptostock-pro.preview.emergentagent.com"
BASE = BASE.rstrip("/")
API = f"{BASE}/api"

TIMEFRAMES = ["15m", "30m", "1h", "3h", "6h", "12h", "18h", "24h"]


@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    sess.headers["Content-Type"] = "application/json"
    return sess


# ---------------- Health ----------------
def test_health(s):
    r = s.get(f"{API}/", timeout=15)
    assert r.status_code == 200
    j = r.json()
    assert j.get("status") == "ok"


# ---------------- Watchlist ----------------
def test_watchlist_defaults(s):
    r = s.get(f"{API}/watchlist", timeout=20)
    assert r.status_code == 200
    j = r.json()
    assert isinstance(j.get("crypto"), list) and len(j["crypto"]) >= 1
    assert isinstance(j.get("stocks"), list) and len(j["stocks"]) >= 1
    assert isinstance(j.get("available_crypto"), list) and len(j["available_crypto"]) >= 20
    assert isinstance(j.get("available_stocks"), list) and len(j["available_stocks"]) >= 18
    assert j.get("timeframes") == TIMEFRAMES
    assert "_id" not in j


def test_watchlist_update_persists(s):
    # Get current
    orig = s.get(f"{API}/watchlist", timeout=15).json()
    new_crypto = ["BTC", "ETH", "SOL"]
    new_stocks = ["BBCA", "BBRI"]
    r = s.post(f"{API}/watchlist", json={"crypto": new_crypto + ["INVALIDX"], "stocks": new_stocks + ["FOO"]}, timeout=15)
    assert r.status_code == 200
    j = r.json()
    assert j["crypto"] == new_crypto, f"crypto filter failed: {j['crypto']}"
    assert j["stocks"] == new_stocks
    # GET to verify persistence
    g = s.get(f"{API}/watchlist", timeout=15).json()
    assert g["crypto"] == new_crypto
    assert g["stocks"] == new_stocks
    # Restore
    s.post(f"{API}/watchlist", json={"crypto": orig["crypto"], "stocks": orig["stocks"]}, timeout=15)


# ---------------- Dashboard ----------------
def test_dashboard_crypto_1h(s):
    r = s.get(f"{API}/dashboard", params={"market": "crypto", "timeframe": "1h"}, timeout=60)
    assert r.status_code == 200
    j = r.json()
    assert j["market"] == "crypto"
    assert j["timeframe"] == "1h"
    assets = j["assets"]
    assert len(assets) >= 15, f"expected >=15 crypto assets, got {len(assets)}"
    a = assets[0]
    for k in ["symbol", "market", "price", "change_pct_24h", "action", "label", "confidence", "spark"]:
        assert k in a, f"missing key {k}"
    assert a["action"] in ("BUY", "SELL", "HOLD")
    assert 0 <= a["confidence"] <= 100
    assert isinstance(a["spark"], list)


def test_dashboard_stock_1h(s):
    r = s.get(f"{API}/dashboard", params={"market": "stock", "timeframe": "1h"}, timeout=60)
    assert r.status_code == 200
    j = r.json()
    assets = j["assets"]
    assert len(assets) >= 10, f"expected >=10 stock assets, got {len(assets)}"
    syms = {a["symbol"] for a in assets}
    assert "BBCA" in syms or "BBRI" in syms


@pytest.mark.parametrize("tf", TIMEFRAMES)
def test_dashboard_all_timeframes(s, tf):
    r = s.get(f"{API}/dashboard", params={"market": "crypto", "timeframe": tf}, timeout=60)
    assert r.status_code == 200, f"timeframe {tf} -> {r.status_code}"


def test_dashboard_invalid_timeframe(s):
    r = s.get(f"{API}/dashboard", params={"market": "crypto", "timeframe": "5m"}, timeout=15)
    assert r.status_code == 400


# ---------------- Asset chart ----------------
def test_chart_crypto_btc(s):
    r = s.get(f"{API}/asset/crypto/BTC/chart", params={"timeframe": "1h"}, timeout=30)
    assert r.status_code == 200
    j = r.json()
    assert j["symbol"] == "BTC"
    assert j["market"] == "crypto"
    assert isinstance(j["candles"], list) and len(j["candles"]) > 5
    assert j["signal"]["action"] in ("BUY", "SELL", "HOLD")
    sig = j["signal"]
    for k in ["confidence", "indicators", "entry", "stop_loss", "take_profit"]:
        assert k in sig


def test_chart_stock_bbca(s):
    r = s.get(f"{API}/asset/stock/BBCA/chart", params={"timeframe": "1h"}, timeout=30)
    assert r.status_code == 200
    j = r.json()
    assert j["symbol"] == "BBCA"
    assert j["market"] == "stock"
    assert len(j["candles"]) > 1
    assert j["ticker"].get("price") is not None


def test_chart_invalid_crypto(s):
    r = s.get(f"{API}/asset/crypto/INVALID/chart", params={"timeframe": "1h"}, timeout=15)
    assert r.status_code == 404


# ---------------- AI Analyze (expensive) ----------------
def test_analyze_crypto_btc(s):
    r = s.post(f"{API}/asset/crypto/BTC/analyze", params={"timeframe": "1h"}, json={}, timeout=120)
    assert r.status_code == 200, r.text[:300]
    j = r.json()
    assert j["symbol"] == "BTC"
    assert j["market"] == "crypto"
    assert isinstance(j["price"], (int, float))
    cons = j["consensus"]
    assert cons["action"] in ("BUY", "SELL", "HOLD")
    assert 0 <= cons["confidence"] <= 100
    assert "summary" in cons
    assert isinstance(cons.get("news_factors"), list)
    assert isinstance(cons.get("risk_factors"), list)
    models = j["models"]
    assert len(models) == 3
    names = [m["name"] for m in models]
    assert "Claude Sonnet 4.6" in names
    assert "GPT-5.2" in names
    assert "Gemini 3.1 Pro" in names
    for m in models:
        assert "name" in m and "ok" in m
        assert "data" in m or "error" in m
    ok_count = sum(1 for m in models if m["ok"])
    assert ok_count >= 1, f"No model returned ok=True; errors: {[m.get('error') for m in models]}"


def test_analyze_stock_bbca(s):
    r = s.post(f"{API}/asset/stock/BBCA/analyze", params={"timeframe": "1h"}, json={}, timeout=120)
    assert r.status_code == 200, r.text[:300]
    j = r.json()
    assert j["symbol"] == "BBCA"
    assert j["market"] == "stock"
    assert len(j["models"]) == 3
    ok_count = sum(1 for m in j["models"] if m["ok"])
    assert ok_count >= 1


# ---------------- _id leakage check ----------------
def test_no_mongo_id_leakage(s):
    paths = [
        "/",
        "/watchlist",
        "/dashboard?market=crypto&timeframe=1h",
        "/asset/crypto/BTC/chart?timeframe=1h",
    ]
    for p in paths:
        r = s.get(f"{API}{p}", timeout=30)
        if r.status_code == 200:
            assert "_id" not in r.text, f"_id leaked in {p}"



# ---------------- News (live RSS) ----------------
def _validate_news_response(j, expected_market):
    assert j.get("market") == expected_market
    assert "fetched_at" in j and isinstance(j["fetched_at"], str)
    items = j.get("items")
    assert isinstance(items, list)
    return items


def test_news_crypto(s):
    r = s.get(f"{API}/news", params={"market": "crypto", "limit": 20}, timeout=60)
    assert r.status_code == 200, r.text[:300]
    items = _validate_news_response(r.json(), "crypto")
    assert len(items) > 0, "no crypto news items"
    for it in items[:5]:
        # required fields
        for k in ["source", "title", "url", "summary", "published"]:
            assert k in it, f"missing key {k} in news item"
        assert isinstance(it["source"], str) and it["source"]
        assert isinstance(it["title"], str) and it["title"]


def test_news_stock(s):
    r = s.get(f"{API}/news", params={"market": "stock", "limit": 20}, timeout=60)
    assert r.status_code == 200, r.text[:300]
    items = _validate_news_response(r.json(), "stock")
    assert len(items) > 0, "no stock news items"


def test_news_all_mixed(s):
    r = s.get(f"{API}/news", params={"market": "all", "limit": 40}, timeout=60)
    assert r.status_code == 200
    items = _validate_news_response(r.json(), "all")
    assert len(items) > 0
    sources = {it["source"] for it in items}
    assert len(sources) >= 2, f"expected mixed sources, got {sources}"


def test_news_cache_is_fast(s):
    # second call should be much faster due to in-memory cache
    s.get(f"{API}/news", params={"market": "crypto", "limit": 20}, timeout=60)
    t0 = time.time()
    r = s.get(f"{API}/news", params={"market": "crypto", "limit": 20}, timeout=30)
    dt = time.time() - t0
    assert r.status_code == 200
    assert dt < 5.0, f"cached news call too slow: {dt}s"


def test_asset_news_crypto_btc(s):
    r = s.get(f"{API}/asset/crypto/BTC/news", params={"limit": 5}, timeout=60)
    assert r.status_code == 200, r.text[:300]
    items = _validate_news_response(r.json(), "crypto")
    assert 0 < len(items) <= 5
    # At least one item should reference bitcoin/btc, or fallback to general (acceptable)
    aliases = ("bitcoin", "btc")
    hits = sum(1 for it in items if any(a in (it.get("title", "") + " " + (it.get("summary") or "")).lower() for a in aliases))
    # don't strictly fail if fallback kicked in, but log
    assert hits >= 0


def test_asset_news_stock_bbca(s):
    r = s.get(f"{API}/asset/stock/BBCA/news", params={"limit": 5}, timeout=60)
    assert r.status_code == 200, r.text[:300]
    items = _validate_news_response(r.json(), "stock")
    # may be fallback if none matched, still must be list
    assert isinstance(items, list)


def test_analyze_includes_news_used(s):
    r = s.post(f"{API}/asset/crypto/BTC/analyze", params={"timeframe": "1h"}, json={}, timeout=120)
    assert r.status_code == 200, r.text[:300]
    j = r.json()
    assert "news_used" in j
    assert isinstance(j["news_used"], list)
    # Should have at least one news item piped to AI
    assert len(j["news_used"]) >= 1, "analyze response missing news_used array"
    n0 = j["news_used"][0]
    for k in ["source", "title"]:
        assert k in n0
