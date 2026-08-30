"""
Backend tests for v8.12.36 features:
  - GET /api/chat/online — new lightweight presence-only endpoint used by the
    dashboard CHATROOM badge (polled every 20s).
  - Regression: /api/search still works for TRUMP, BTC, AAPL — no 500s from
    the recent search-crash hotfix + voice search UI addition.
"""
import os
import time

import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    BASE_URL = "https://cryptostock-pro.preview.emergentagent.com"


@pytest.fixture(scope="module")
def api_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# --------------------- /api/chat/online ---------------------

class TestChatOnline:
    def test_no_params_returns_online_and_server_time(self, api_client):
        r = api_client.get(f"{BASE_URL}/api/chat/online", timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        assert "online" in j, f"Missing 'online' in {j}"
        assert "server_time" in j, f"Missing 'server_time' in {j}"
        assert isinstance(j["online"], int)
        assert j["online"] >= 0
        # ISO-8601-ish server_time (naïve check)
        assert "T" in j["server_time"]

    def test_single_device_upsert_included(self, api_client):
        did = "TEST_device_A_iter28"
        r = api_client.get(
            f"{BASE_URL}/api/chat/online",
            params={"device_id": did},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        j = r.json()
        assert isinstance(j["online"], int)
        assert j["online"] >= 1, (
            f"After heartbeat for {did!r}, online count should include this device — got {j}"
        )

    def test_two_distinct_devices_increment(self, api_client):
        # Fresh unique ids so we don't collide with parallel runs.
        stamp = int(time.time())
        a = f"TEST_iter28_A_{stamp}"
        b = f"TEST_iter28_B_{stamp}"

        r1 = api_client.get(f"{BASE_URL}/api/chat/online", params={"device_id": a}, timeout=15)
        assert r1.status_code == 200
        c1 = r1.json()["online"]

        r2 = api_client.get(f"{BASE_URL}/api/chat/online", params={"device_id": b}, timeout=15)
        assert r2.status_code == 200
        c2 = r2.json()["online"]

        # Second call must see at least both devices we just registered.
        assert c2 >= 2, f"Expected >=2 online after two devices, got {c2} (first={c1})"
        # And the second count is never LESS than the first (both are inside
        # the presence window, so B was added).
        assert c2 >= c1, f"Count should not decrease: first={c1}, second={c2}"

    def test_empty_device_id_is_ignored_gracefully(self, api_client):
        # device_id="" or whitespace-only should NOT crash and should not upsert.
        r = api_client.get(f"{BASE_URL}/api/chat/online", params={"device_id": ""}, timeout=15)
        assert r.status_code == 200
        j = r.json()
        assert "online" in j and isinstance(j["online"], int)


# --------------------- /api/search regression ---------------------

class TestSearchRegression:
    @pytest.mark.parametrize("q", ["TRUMP", "BTC", "AAPL"])
    def test_search_ticker(self, api_client, q):
        r = api_client.get(f"{BASE_URL}/api/search", params={"q": q}, timeout=30)
        assert r.status_code == 200, f"/api/search?q={q} failed: {r.status_code} {r.text[:200]}"
        j = r.json()
        # The endpoint is expected to return either a list or a dict with a
        # results list — be permissive but check we got JSON with content.
        if isinstance(j, dict):
            # common shape: {"results": [...]} or {"hits": [...]}
            hits = j.get("results") or j.get("hits") or j.get("data") or []
        else:
            hits = j
        assert isinstance(hits, list), f"Search {q}: unexpected shape {type(j)}"
        # We don't force a minimum hit count (SIDO-style symbols may 0-hit for
        # some queries), but ensure no 500 and JSON parseable.

    def test_search_no_500_on_gibberish(self, api_client):
        r = api_client.get(f"{BASE_URL}/api/search", params={"q": "ZZZZZZQ"}, timeout=15)
        assert r.status_code == 200, r.text
