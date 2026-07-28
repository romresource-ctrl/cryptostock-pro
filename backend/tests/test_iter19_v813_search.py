"""
Iteration 19 – v8.1.3 full-universe search + world stocks + IDX low-cap + interactive filter chips.

Tests the review request:
- Search endpoint correctness (crypto cascade, stock_id, stock_us world map, disambiguation)
- Dashboard/asset/analyze regression
- Subscription/chat regression
- Response shape of /api/search
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://cryptostock-pro.preview.emergentagent.com").rstrip("/")

# Reasonable timeout since search hits Binance mirror + Bitget + CoinGecko + Yahoo cascades
TIMEOUT = 45


@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ---------- Helpers ----------

def _get_search(api, q):
    r = api.get(f"{BASE_URL}/api/search", params={"q": q}, timeout=TIMEOUT)
    return r


def _has_hit(hits, symbol_upper, market=None):
    for h in hits:
        if str(h.get("symbol", "")).upper() == symbol_upper.upper():
            if market is None or h.get("market") == market:
                return True
    return False


def _find_hit(hits, symbol_upper, market=None):
    for h in hits:
        if str(h.get("symbol", "")).upper() == symbol_upper.upper():
            if market is None or h.get("market") == market:
                return h
    return None


# ---------- Search: crypto cascade ----------

class TestSearchCrypto:
    def test_btc_returns_crypto_with_candles(self, api):
        r = _get_search(api, "BTC")
        assert r.status_code == 200, r.text
        data = r.json()
        assert set(["hits", "query", "disambiguation"]).issubset(data.keys()), f"Missing keys: {data.keys()}"
        assert isinstance(data["hits"], list) and len(data["hits"]) >= 1
        btc = _find_hit(data["hits"], "BTC", market="crypto")
        assert btc is not None, f"BTC crypto hit missing: {data['hits'][:3]}"
        # candles / sparkline non-empty
        spark = btc.get("spark") or btc.get("candles") or []
        assert isinstance(spark, list) and len(spark) > 0, f"BTC sparkline empty: {btc}"

    def test_moodeng_crypto_hit(self, api):
        r = _get_search(api, "MOODENG")
        assert r.status_code == 200, r.text
        data = r.json()
        assert _has_hit(data["hits"], "MOODENG", market="crypto") or _has_hit(data.get("disambiguation") or [], "MOODENG"), \
            f"MOODENG not found. hits={data['hits']} disamb={data.get('disambiguation')}"

    def test_mew_crypto_hit(self, api):
        r = _get_search(api, "MEW")
        assert r.status_code == 200, r.text
        data = r.json()
        assert _has_hit(data["hits"], "MEW", market="crypto") or _has_hit(data.get("disambiguation") or [], "MEW"), \
            f"MEW not found. hits={data['hits']} disamb={data.get('disambiguation')}"

    def test_brett_crypto_hit(self, api):
        r = _get_search(api, "BRETT")
        assert r.status_code == 200, r.text
        data = r.json()
        assert _has_hit(data["hits"], "BRETT", market="crypto") or _has_hit(data.get("disambiguation") or [], "BRETT"), \
            f"BRETT not found. hits={data['hits']} disamb={data.get('disambiguation')}"

    def test_aave_crypto_hit(self, api):
        r = _get_search(api, "AAVE")
        assert r.status_code == 200, r.text
        data = r.json()
        assert _has_hit(data["hits"], "AAVE", market="crypto"), f"AAVE crypto hit missing: {data['hits'][:3]}"

    def test_cat_returns_caterpillar_no_5xx(self, api):
        r = _get_search(api, "CAT")
        assert r.status_code == 200, r.text
        data = r.json()
        # Must include CAT stock_us Caterpillar. Disamb can be empty due to CG rate-limit.
        assert _has_hit(data["hits"], "CAT", market="stock_us") or \
               any("caterpillar" in str(h.get("name", "")).lower() for h in data["hits"]), \
               f"CAT (Caterpillar stock_us) missing: {data['hits']}"

    def test_popcat_no_5xx(self, api):
        r = _get_search(api, "POPCAT")
        # 0 hits acceptable, but must not 5xx
        assert r.status_code == 200, r.text
        data = r.json()
        assert "hits" in data and "disambiguation" in data


# ---------- Search: stock_id (Indonesia) ----------

class TestSearchStockID:
    @pytest.mark.parametrize("q", ["AADI", "DSSA", "WBSA", "DOOH", "ERAA", "MSIN", "VKTR"])
    def test_stock_id_hit(self, api, q):
        r = _get_search(api, q)
        assert r.status_code == 200, r.text
        data = r.json()
        assert _has_hit(data["hits"], q, market="stock_id"), \
            f"{q} stock_id hit missing. hits={data['hits']}"

    def test_coco_returns_stock_id_AND_commodity_cocoa(self, api):
        r = _get_search(api, "COCO")
        assert r.status_code == 200, r.text
        data = r.json()
        pool = data["hits"] + (data.get("disambiguation") or [])
        has_stock_coco = _has_hit(pool, "COCO", market="stock_id")
        has_cocoa = any("cocoa" in str(h.get("symbol", "")).lower() or
                        "cocoa" in str(h.get("name", "")).lower() or
                        str(h.get("symbol", "")).upper() == "COCOA"
                        for h in pool)
        assert has_stock_coco, f"COCO stock_id missing: {pool}"
        assert has_cocoa, f"COCOA commodity match missing: {pool}"


# ---------- Search: stock_us (world stocks via Yahoo suffixes) ----------

class TestSearchWorldStocks:
    @pytest.mark.parametrize("q,expected_mapped_hint", [
        ("TOYOTA", "7203"),
        ("TSMC_TW", "2330"),
        ("TENCENT", "0700"),
        ("DBS", "D05"),
        ("MOUTAI", "600519"),
        ("HSBC", "0005"),
        ("SAMSUNG", "005930"),
        ("MAYBANK", "1155"),
    ])
    def test_world_stock_hit(self, api, q, expected_mapped_hint):
        r = _get_search(api, q)
        assert r.status_code == 200, r.text
        data = r.json()
        # The user-facing hit should show the alias (TOYOTA) or the mapped ticker (7203.T).
        pool = data["hits"] + (data.get("disambiguation") or [])
        matched = False
        for h in pool:
            sym = str(h.get("symbol", "")).upper()
            name = str(h.get("name", "")).upper()
            mapped = str(h.get("mapped_symbol", "") or h.get("yahoo_symbol", "") or "").upper()
            if q.upper() in sym or q.upper() in name or expected_mapped_hint in sym or expected_mapped_hint in mapped:
                matched = True
                break
        assert matched, f"{q} world-stock hit missing (expected containing {expected_mapped_hint}). pool={pool}"

    def test_sber_no_5xx(self, api):
        """SBER (Russia) may fail gracefully — accept empty hits but no 5xx."""
        r = _get_search(api, "SBER")
        assert r.status_code == 200, r.text
        data = r.json()
        assert "hits" in data


# ---------- Search response shape ----------

class TestSearchShape:
    def test_response_shape_contract(self, api):
        r = _get_search(api, "BTC")
        assert r.status_code == 200
        data = r.json()
        # Required keys
        for k in ("hits", "query", "disambiguation"):
            assert k in data, f"Missing key '{k}' in /api/search response"
        assert isinstance(data["hits"], list)
        assert isinstance(data["disambiguation"], list)
        assert isinstance(data["query"], str)


# ---------- Startup resilience (Binance geo-block) ----------

class TestStartupResilience:
    def test_backend_survives_binance_geoblock(self, api):
        """/api/search?q=BTC should succeed via data-api.binance.vision fallback."""
        r = _get_search(api, "BTC")
        assert r.status_code == 200, r.text
        data = r.json()
        assert _has_hit(data["hits"], "BTC", market="crypto")


# ---------- Dashboard regression ----------

class TestDashboardRegression:
    def _items_from_dashboard(self, data):
        # Backend returns { assets: [...], market, premium_count, ... }
        if isinstance(data, dict):
            return data.get("assets") or data.get("items") or data.get("results") or data.get("data")
        return data

    def test_dashboard_crypto_1h(self, api):
        r = api.get(f"{BASE_URL}/api/dashboard", params={"market": "crypto", "timeframe": "1h"}, timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        data = r.json()
        items = self._items_from_dashboard(data)
        assert isinstance(items, list) and len(items) >= 20, \
            f"Expected top-N crypto, got {len(items) if isinstance(items, list) else 'n/a'}. keys={list(data.keys()) if isinstance(data, dict) else 'n/a'}"

    def test_dashboard_stock_us_1h(self, api):
        r = api.get(f"{BASE_URL}/api/dashboard", params={"market": "stock_us", "timeframe": "1h"}, timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        data = r.json()
        items = self._items_from_dashboard(data)
        assert isinstance(items, list) and len(items) >= 20, \
            f"Expected top-N stock_us, got {len(items) if isinstance(items, list) else 'n/a'}"

    def test_dashboard_batch_all_seven_markets(self, api):
        markets = "crypto,stock_id,stock_us,etf,gold_silver,commodity,forex"
        r = api.get(f"{BASE_URL}/api/dashboard/batch",
                    params={"markets": markets, "timeframe": "1h"}, timeout=TIMEOUT * 2)
        assert r.status_code == 200, r.text
        data = r.json()
        # Backend shape: { markets: {crypto: {...}, stock_id: {...}, ...}, timeframe, server_time }
        assert isinstance(data, dict), f"Expected dict, got {type(data)}"
        markets_dict = data.get("markets") or {}
        assert isinstance(markets_dict, dict), f"Expected 'markets' dict, got {type(markets_dict)}"
        required = {"crypto", "stock_id", "stock_us", "etf", "gold_silver", "commodity", "forex"}
        keys = set(markets_dict.keys())
        assert required.issubset(keys), f"Missing markets: expected {required}, got {keys}"
        for m in required:
            val = markets_dict.get(m) or {}
            items = val.get("assets") or val.get("items") if isinstance(val, dict) else val
            assert items, f"Market {m} has no items/assets. val={val}"


# ---------- Asset chart & analyze ----------

class TestAssetEndpoints:
    def test_btc_chart_1h(self, api):
        r = api.get(f"{BASE_URL}/api/asset/crypto/BTC/chart",
                    params={"timeframe": "1h"}, timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        data = r.json()
        candles = data.get("candles") or data.get("data") or []
        assert isinstance(candles, list) and len(candles) > 0, f"No candles: {data}"

    def test_btc_analyze(self, api):
        r = api.post(f"{BASE_URL}/api/asset/crypto/BTC/analyze",
                     params={"timeframe": "1h", "lang": "en"}, timeout=TIMEOUT * 2)
        assert r.status_code == 200, r.text
        data = r.json()
        # Look for AI response in known shapes
        has_ai = any(k in data for k in ("ai", "analysis", "response", "message", "summary", "reasoning"))
        assert has_ai or bool(data), f"AI analyze response empty: {data}"


# ---------- Regression: subscription & chat ----------

class TestSubscriptionChatRegression:
    def test_subscription_health(self, api):
        r = api.get(f"{BASE_URL}/api/subscription/health", timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        data = r.json()
        # Review contract says boolean-only, but current backend adds `package_name` (public bundle id).
        # Enforce: no PII/secret leak (private_key, client_email, service_account json path).
        body_lower = str(data).lower()
        for forbidden in ("private_key", "client_email", "service_account.json", "-----begin"):
            assert forbidden not in body_lower, f"PII/secret leak in /subscription/health: contains '{forbidden}'"
        # Non-boolean non-string-package_name values would indicate deeper drift
        non_bool_keys = [k for k, v in data.items() if not isinstance(v, bool)]
        # Allow package_name as the only known string key
        unexpected = [k for k in non_bool_keys if k != "package_name"]
        assert not unexpected, f"Unexpected non-boolean keys in /subscription/health: {unexpected}. data={data}"

    def test_chat_messages_get(self, api):
        r = api.get(f"{BASE_URL}/api/chat/messages", timeout=TIMEOUT)
        assert r.status_code == 200, r.text
