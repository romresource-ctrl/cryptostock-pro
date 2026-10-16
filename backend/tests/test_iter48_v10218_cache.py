"""v10.2.18 — Server-side cache tests.

Covers:
  - /api/dashboard/batch 60s cache + distinct keys per profile/markets
  - /api/asi/leaderboard & /live cache + limit <= 25
  - Regression: /health, /api/asi/scan-debug fields v10.2.17
"""
import os
import time

import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL") \
    or "https://cryptostock-pro.preview.emergentagent.com"
BASE_URL = BASE_URL.rstrip("/")


@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ---------- Regression ----------
class TestRegression:
    def test_health(self, api):
        r = api.get(f"{BASE_URL}/health", timeout=15)
        assert r.status_code == 200, r.text
        assert r.json().get("status") == "ok"

    def test_api_root(self, api):
        r = api.get(f"{BASE_URL}/api/", timeout=15)
        assert r.status_code == 200
        assert r.json().get("status") == "ok"

    def test_scan_debug_has_v10217_fields(self, api):
        r = api.get(f"{BASE_URL}/api/asi/scan-debug",
                    params={"device_id": "test-judge-device-001"},
                    timeout=20)
        assert r.status_code == 200, r.text
        j = r.json()
        # v10.2.17 BUY gates fields must be present (may be None if no scan yet)
        for k in ("btc_base_regime_4h", "btc_trend_up_streak", "buy_gates"):
            assert k in j, f"missing field {k} in scan-debug: {j.keys()}"


# ---------- /api/dashboard/batch ----------
class TestDashboardBatchCache:
    def test_batch_cache_second_call_cached(self, api):
        params = {"markets": "crypto,forex", "timeframe": "1h"}
        t0 = time.time()
        r1 = api.get(f"{BASE_URL}/api/dashboard/batch",
                     params=params, timeout=90)
        dur1 = time.time() - t0
        assert r1.status_code == 200, r1.text
        j1 = r1.json()
        # First call may or may not be cached depending on earlier calls;
        # just assert shape.
        assert "markets" in j1
        assert "cached" in j1

        t0 = time.time()
        r2 = api.get(f"{BASE_URL}/api/dashboard/batch",
                     params=params, timeout=30)
        dur2 = time.time() - t0
        assert r2.status_code == 200
        j2 = r2.json()
        assert j2.get("cached") is True, \
            f"expected cached:true on 2nd identical call (dur1={dur1:.2f}s, dur2={dur2:.2f}s)"
        # Cached response should be faster
        assert dur2 < max(dur1, 2.0), \
            f"cached call not faster: dur1={dur1:.2f}s dur2={dur2:.2f}s"

    def test_batch_different_profile_distinct_cache_key(self, api):
        base_params = {"markets": "crypto", "timeframe": "1h"}
        # Warm cache for no-profile
        api.get(f"{BASE_URL}/api/dashboard/batch",
                params=base_params, timeout=90)
        # Now call with scalper profile → should NOT be cached hit
        r = api.get(f"{BASE_URL}/api/dashboard/batch",
                    params={**base_params, "profile": "scalper"}, timeout=90)
        assert r.status_code == 200, r.text
        assert r.json().get("cached") is False, \
            "profile should produce distinct cache key → cached:false expected"

    def test_batch_different_markets_distinct_cache_key(self, api):
        api.get(f"{BASE_URL}/api/dashboard/batch",
                params={"markets": "crypto"}, timeout=90)
        r = api.get(f"{BASE_URL}/api/dashboard/batch",
                    params={"markets": "crypto,etf"}, timeout=90)
        assert r.status_code == 200
        assert r.json().get("cached") is False, \
            "different markets → cached:false expected"


# ---------- /api/asi/leaderboard ----------
class TestLeaderboardCache:
    def test_leaderboard_7d_cache(self, api):
        r1 = api.get(f"{BASE_URL}/api/asi/leaderboard",
                     params={"period_days": 7}, timeout=30)
        assert r1.status_code == 200, r1.text
        j1 = r1.json()
        assert "items" in j1
        assert isinstance(j1["items"], list)
        assert len(j1["items"]) <= 25
        # 2nd call must be cached
        r2 = api.get(f"{BASE_URL}/api/asi/leaderboard",
                     params={"period_days": 7}, timeout=15)
        assert r2.status_code == 200
        j2 = r2.json()
        assert j2.get("cached") is True, "2nd leaderboard call must be cached"
        assert len(j2["items"]) <= 25

    def test_leaderboard_live_cache(self, api):
        r1 = api.get(f"{BASE_URL}/api/asi/leaderboard/live", timeout=30)
        assert r1.status_code == 200, r1.text
        j1 = r1.json()
        assert "items" in j1
        assert len(j1["items"]) <= 25
        r2 = api.get(f"{BASE_URL}/api/asi/leaderboard/live", timeout=15)
        assert r2.status_code == 200
        j2 = r2.json()
        assert j2.get("cached") is True, "2nd live-leaderboard call must be cached"
        assert len(j2["items"]) <= 25
