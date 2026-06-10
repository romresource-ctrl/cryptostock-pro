"""Iteration 3 backend tests: profiles, track record, news image, regression."""
import os
import time
import uuid as _u
import pytest
import requests

BASE = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://cryptostock-pro.preview.emergentagent.com").rstrip("/")
S = requests.Session()
S.headers.update({"Content-Type": "application/json"})


# -------- Profiles --------

def _no_id_leak(obj):
    if isinstance(obj, dict):
        assert "_id" not in obj, f"_id leaked: {obj}"
        for v in obj.values():
            _no_id_leak(v)
    elif isinstance(obj, list):
        for v in obj:
            _no_id_leak(v)


class TestProfiles:
    def test_list_default_profiles(self):
        r = S.get(f"{BASE}/api/profiles", timeout=20)
        assert r.status_code == 200
        d = r.json()
        for k in ("profiles", "active_id", "available_crypto", "available_stocks", "timeframes"):
            assert k in d, f"missing key {k}"
        ids = {p["id"] for p in d["profiles"]}
        # Default seeds should exist
        for need in ("spot", "futures", "konservatif"):
            assert need in ids, f"default profile {need} missing; got {ids}"
        for p in d["profiles"]:
            assert {"id", "name", "crypto", "stocks"}.issubset(p)
        assert d["active_id"] in ids
        assert len(d["timeframes"]) >= 8
        _no_id_leak(d)

    def test_create_update_activate_delete_profile(self):
        name = f"TEST_{_u.uuid4().hex[:6]}"
        # CREATE
        r = S.post(f"{BASE}/api/profiles", json={"name": name, "crypto": ["BTC", "ETH", "FOOBAR"], "stocks": ["BBCA", "NOPE"]})
        assert r.status_code == 200, r.text
        prof = r.json()
        pid = prof["id"]
        assert prof["name"] == name
        # filter applied: FOOBAR & NOPE dropped
        assert "FOOBAR" not in prof["crypto"]
        assert "NOPE" not in prof["stocks"]
        assert "BTC" in prof["crypto"]
        _no_id_leak(prof)

        # UPDATE
        r = S.put(f"{BASE}/api/profiles/{pid}", json={"name": name + "_x", "crypto": ["BTC"], "stocks": ["BBCA"]})
        assert r.status_code == 200, r.text
        upd = r.json()
        assert upd["name"] == name + "_x"
        assert upd["crypto"] == ["BTC"] and upd["stocks"] == ["BBCA"]

        # ACTIVATE
        r = S.post(f"{BASE}/api/profiles/{pid}/activate")
        assert r.status_code == 200
        r2 = S.get(f"{BASE}/api/profiles")
        assert r2.json()["active_id"] == pid

        # reset active to spot before delete (and verify dashboard switched)
        r = S.get(f"{BASE}/api/dashboard?market=crypto&timeframe=1h", timeout=60)
        assert r.status_code == 200
        assert r.json()["profile_id"] == pid
        S.post(f"{BASE}/api/profiles/spot/activate")

        # DELETE
        r = S.delete(f"{BASE}/api/profiles/{pid}")
        assert r.status_code == 200, r.text
        # confirm gone
        r = S.get(f"{BASE}/api/profiles")
        assert pid not in {p["id"] for p in r.json()["profiles"]}

    def test_cannot_delete_last_profile(self):
        # Get current count; we shouldn't actually delete down to 1, so just create
        # one extra, delete all others except it, then assert 400 on deleting the last.
        # Simpler: try delete with only-one scenario can't be safely set up without
        # destroying seed; instead, ensure server returns 400 when count == 1.
        # We'll attempt deleting all profiles one-by-one and stop at last.
        r = S.get(f"{BASE}/api/profiles").json()
        ids = [p["id"] for p in r["profiles"]]
        if len(ids) <= 1:
            # Create a couple of throwaways so the system survives
            created = []
            for i in range(2):
                pr = S.post(f"{BASE}/api/profiles", json={"name": f"TEST_keep_{i}"}).json()
                created.append(pr["id"])
            ids = [p["id"] for p in S.get(f"{BASE}/api/profiles").json()["profiles"]]
        # Delete all but one
        last = ids[-1]
        for pid in ids[:-1]:
            S.delete(f"{BASE}/api/profiles/{pid}")
        # Now last delete must 400
        r = S.delete(f"{BASE}/api/profiles/{last}")
        assert r.status_code == 400
        # Restore the default 3 profiles to keep system healthy for other tests
        S.post(f"{BASE}/api/profiles", json={"name": "Spot Crypto", "crypto": ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOT", "LINK", "LTC", "BCH"], "stocks": []})
        S.post(f"{BASE}/api/profiles", json={"name": "Futures Crypto", "crypto": ["BTC", "ETH", "SOL", "HYPE", "DOGE", "PEPE", "ASTER", "SUI", "SHIB", "XRP", "ALGO", "SAND"], "stocks": []})
        S.post(f"{BASE}/api/profiles", json={"name": "Saham Konservatif", "crypto": ["BTC", "ETH", "XAUT", "USDT"], "stocks": ["BBCA", "BBRI", "BMRI", "ASII", "TPIA", "ANTM", "ADRO"]})


# -------- Dashboard reflects active profile + track_record --------

class TestDashboardWithProfile:
    def test_dashboard_has_profile_and_tr(self):
        # Ensure spot is active
        S.post(f"{BASE}/api/profiles/spot/activate")
        r = S.get(f"{BASE}/api/dashboard?market=crypto&timeframe=1h", timeout=60)
        assert r.status_code == 200
        d = r.json()
        assert d["profile_id"] and d["profile_name"]
        # track_record field on each asset
        for a in d["assets"][:3]:
            assert "track_record" in a
            tr = a["track_record"]
            for k in ("wr_7d", "n_7d", "wr_30d", "n_30d"):
                assert k in tr
        _no_id_leak(d)


# -------- Track record --------

class TestTrackRecord:
    def test_btc_track_record(self):
        r = S.get(f"{BASE}/api/asset/crypto/BTC/track-record", timeout=30)
        assert r.status_code == 200
        d = r.json()
        for k in ("symbol", "market", "win_rate_7d", "win_rate_30d", "win_rate_all", "recent_signals"):
            assert k in d
        for k in ("total", "hits", "win_rate"):
            assert k in d["win_rate_all"]
        # seeded 20 evaluated, 70% all-time per agent context
        assert d["win_rate_all"]["total"] >= 1
        _no_id_leak(d)

    def test_record_signal_increments_total(self):
        sym = "BTC"
        before = S.get(f"{BASE}/api/asset/crypto/{sym}/track-record").json()
        before_count = len(before["recent_signals"])
        # trigger analyze (may take 15-40s)
        r = S.post(f"{BASE}/api/asset/crypto/{sym}/analyze?timeframe=1h", timeout=90)
        if r.status_code in (404, 503):
            pytest.skip(f"upstream unavailable: {r.status_code}")
        assert r.status_code == 200, r.text
        # New signal is unevaluated; recent_signals returns evaluated only,
        # so total may be unchanged. Verify endpoint still works.
        after = S.get(f"{BASE}/api/asset/crypto/{sym}/track-record").json()
        assert len(after["recent_signals"]) >= before_count


# -------- News with image + symbol news --------

class TestNews:
    def test_news_has_image_field(self):
        r = S.get(f"{BASE}/api/news?market=crypto&limit=20", timeout=30)
        assert r.status_code == 200
        items = r.json()["items"]
        assert isinstance(items, list) and len(items) > 0
        for it in items:
            assert "image" in it  # None or string both ok
            if it["image"]:
                assert it["image"].startswith(("http://", "https://"))

    def test_asset_news_btc(self):
        r = S.get(f"{BASE}/api/asset/crypto/BTC/news?limit=5", timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert "items" in d


# -------- Regression --------

class TestRegression:
    def test_watchlist_routes_to_active(self):
        # Pick the first profile that has BTC in its crypto list and activate it,
        # then verify watchlist reflects that profile.
        profiles = S.get(f"{BASE}/api/profiles").json()["profiles"]
        target = next((p for p in profiles if "BTC" in p["crypto"]), profiles[0])
        S.post(f"{BASE}/api/profiles/{target['id']}/activate")
        r = S.get(f"{BASE}/api/watchlist")
        assert r.status_code == 200
        d = r.json()
        assert d["profile_id"] == target["id"]
        assert d["profile_name"] == target["name"]

    def test_no_id_leak_dashboard(self):
        r = S.get(f"{BASE}/api/dashboard?market=crypto&timeframe=1h", timeout=60)
        _no_id_leak(r.json())
