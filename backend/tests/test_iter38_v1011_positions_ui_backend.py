# v10.1.1 — Backend regression: app-version, asi trades (no 'placing'),
# leaderboard (all positive PnL, max 25), dashboard, search.
import os
import pytest
import requests

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
DEVICE_ID = "web:qmeqflw0e2d-mui5ar38"


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


class TestHealthAndVersion:
    """Health: app-version must stay 10.1.1"""

    def test_app_version_10_1_1(self, client):
        r = client.get(f"{BASE_URL}/api/app-version", timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        ver = data.get("latest_version") or data.get("version") or ""
        assert "10.1.1" in str(ver), f"unexpected version payload: {data}"


class TestAsiTrades:
    """ASI trades list: 200, normal statuses, no 'placing'"""

    def test_trades_list_ok(self, client):
        r = client.get(f"{BASE_URL}/api/asi/trades",
                       params={"device_id": DEVICE_ID, "limit": 10}, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        items = data.get("items", data if isinstance(data, list) else [])
        assert isinstance(items, list)
        statuses = {str(t.get("status")) for t in items}
        assert "placing" not in statuses, f"found 'placing' status in {statuses}"

    def test_trades_fields_present(self, client):
        r = client.get(f"{BASE_URL}/api/asi/trades",
                       params={"device_id": DEVICE_ID, "limit": 10}, timeout=30)
        assert r.status_code == 200
        items = r.json().get("items", [])
        assert len(items) > 0, "no seeded trades found for device"
        t0 = items[0]
        for key in ("symbol", "status", "side"):
            assert key in t0, f"missing field {key} in trade item"
        # _id harus string trade-key ("device:orderid"), bukan ObjectId/dict
        if "_id" in t0:
            assert isinstance(t0["_id"], str), f"_id not a string: {t0['_id']!r}"


class TestLeaderboard:
    """Leaderboard: all entries positive PnL, max 25"""

    def test_leaderboard_positive_and_capped(self, client):
        r = client.get(f"{BASE_URL}/api/asi/leaderboard", timeout=30)
        assert r.status_code == 200, r.text
        items = r.json().get("items", [])
        assert len(items) <= 25, f"leaderboard has {len(items)} items (>25)"
        for it in items:
            pnl = it.get("pnl_usdt", it.get("pnl", it.get("total_pnl")))
            assert pnl is not None, f"leaderboard entry missing pnl: {it}"
            assert float(pnl) > 0, f"non-positive PnL entry: {it}"


class TestRegression:
    """Regression: dashboard crypto + search BTC"""

    def test_dashboard_crypto(self, client):
        r = client.get(f"{BASE_URL}/api/dashboard", params={"market": "crypto"}, timeout=60)
        assert r.status_code == 200, r.text[:300]

    def test_search_btc(self, client):
        r = client.get(f"{BASE_URL}/api/search", params={"q": "BTC"}, timeout=30)
        assert r.status_code == 200, r.text[:300]
