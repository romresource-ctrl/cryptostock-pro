"""Iteration 4 backend tests: Premium Signals.

Verifies:
- /api/dashboard returns is_premium per asset + premium_count + premium_threshold
- spot profile yields at least 1 premium crypto (with default 85/70 threshold)
- sort=premium / confidence / wr / default order behavior
- premium_only=true filters list
- invalid sort -> 422
- min_confidence / min_wr customizable
- Regression: /api/profiles /api/watchlist /api/asset/.../track-record /api/news still 200
- No _id leak in responses
"""
from __future__ import annotations

import json
import os

import pytest
import requests

BASE = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/") if os.environ.get(
    "EXPO_PUBLIC_BACKEND_URL"
) else "https://cryptostock-pro.preview.emergentagent.com"
API = f"{BASE}/api"


@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    return sess


@pytest.fixture(scope="module", autouse=True)
def ensure_spot_active(s):
    # activate spot profile
    r = s.post(f"{API}/profiles/spot/activate", timeout=20)
    # If spot doesn't exist anymore (e.g. recreated as uuid), fall back to first
    if r.status_code != 200:
        profs = s.get(f"{API}/profiles", timeout=20).json()
        spot = next((p for p in profs["profiles"] if p["name"] == "Spot Crypto"), None) or profs["profiles"][0]
        s.post(f"{API}/profiles/{spot['id']}/activate", timeout=20)
    yield


def _no_id_leak(obj):
    """Recursively assert no '_id' key in any dict."""
    if isinstance(obj, dict):
        assert "_id" not in obj, f"_id leak: {list(obj.keys())}"
        for v in obj.values():
            _no_id_leak(v)
    elif isinstance(obj, list):
        for v in obj:
            _no_id_leak(v)


# ---------------- Dashboard premium fields ----------------

class TestDashboardPremium:
    def test_dashboard_returns_premium_fields(self, s):
        r = s.get(f"{API}/dashboard", params={"market": "crypto", "timeframe": "1h"}, timeout=60)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "premium_count" in d
        assert isinstance(d["premium_count"], int)
        assert "premium_threshold" in d
        assert d["premium_threshold"]["min_confidence"] == 85
        assert d["premium_threshold"]["min_wr"] == 70.0
        assert d["assets"], "expected assets present for spot profile"
        for a in d["assets"]:
            assert "is_premium" in a
            assert isinstance(a["is_premium"], bool)
        _no_id_leak(d)

    def test_spot_has_at_least_one_premium(self, s):
        r = s.get(f"{API}/dashboard", params={"market": "crypto", "timeframe": "1h"}, timeout=60)
        d = r.json()
        prem = [a for a in d["assets"] if a["is_premium"]]
        assert d["premium_count"] == len(prem)
        assert d["premium_count"] >= 1, (
            f"expected >=1 premium on spot profile, got 0. assets sample: "
            f"{json.dumps([{'s': a['symbol'], 'c': a['confidence'], 'a': a['action'], 'wr': a['track_record']['wr_30d']} for a in d['assets']])[:600]}"
        )

    def test_sort_premium_first(self, s):
        r = s.get(f"{API}/dashboard", params={"market": "crypto", "timeframe": "1h", "sort": "premium"}, timeout=60)
        d = r.json()
        if d["premium_count"] == 0:
            pytest.skip("no premium present")
        first_n = d["assets"][: d["premium_count"]]
        assert all(a["is_premium"] for a in first_n), [a["symbol"] for a in first_n]

    def test_sort_confidence_desc(self, s):
        r = s.get(f"{API}/dashboard", params={"market": "crypto", "timeframe": "1h", "sort": "confidence"}, timeout=60)
        confs = [a["confidence"] for a in r.json()["assets"]]
        assert confs == sorted(confs, reverse=True), confs

    def test_sort_wr_desc_nulls_last(self, s):
        r = s.get(f"{API}/dashboard", params={"market": "crypto", "timeframe": "1h", "sort": "wr"}, timeout=60)
        wrs = [a["track_record"]["wr_30d"] for a in r.json()["assets"]]
        # Non-null first sorted desc; None at the end
        keyed = [(w if w is not None else -1) for w in wrs]
        assert keyed == sorted(keyed, reverse=True), wrs

    def test_premium_only_filter(self, s):
        r = s.get(
            f"{API}/dashboard",
            params={"market": "crypto", "timeframe": "1h", "premium_only": "true"},
            timeout=60,
        )
        d = r.json()
        assert all(a["is_premium"] for a in d["assets"])
        assert d["premium_count"] == len(d["assets"])

    def test_invalid_sort_422(self, s):
        r = s.get(f"{API}/dashboard", params={"market": "crypto", "timeframe": "1h", "sort": "lol"}, timeout=30)
        assert r.status_code == 422, r.status_code

    def test_min_wr_relaxed_increases_premium(self, s):
        d1 = s.get(f"{API}/dashboard", params={"market": "crypto", "timeframe": "1h"}, timeout=60).json()
        d2 = s.get(
            f"{API}/dashboard",
            params={"market": "crypto", "timeframe": "1h", "min_wr": 50},
            timeout=60,
        ).json()
        assert d2["premium_threshold"]["min_wr"] == 50.0
        assert d2["premium_count"] >= d1["premium_count"], (d1["premium_count"], d2["premium_count"])


# ---------------- Regression ----------------

class TestRegression:
    def test_profiles(self, s):
        r = s.get(f"{API}/profiles", timeout=20)
        assert r.status_code == 200
        _no_id_leak(r.json())

    def test_watchlist(self, s):
        r = s.get(f"{API}/watchlist", timeout=20)
        assert r.status_code == 200
        _no_id_leak(r.json())

    def test_track_record(self, s):
        r = s.get(f"{API}/asset/crypto/BTC/track-record", timeout=30)
        assert r.status_code == 200
        _no_id_leak(r.json())

    def test_news(self, s):
        r = s.get(f"{API}/news", params={"market": "crypto", "limit": 10}, timeout=60)
        assert r.status_code == 200
        _no_id_leak(r.json())
