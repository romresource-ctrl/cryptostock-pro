"""
v9.8.0 — Backend verification for three UI bugs fixed by main agent.

Bug 1 — AI Suggestions crypto cards had no EXECUTE SEMI-AUTO (frontend filter
        looked at `take_profits` plural; backend sends singular take_profit +
        take_profit_2 + take_profit_3). → Verify backend fields exist.

Bug 2 — PICK A SIGNAL always alerted "No signal for CONFLUENCE" regardless of
        trader profile. The fix wires useTraderProfile → aiSuggestions call;
        the backend must accept scalper / day / swing / confluence and return
        a distinct engine for each.

Bug 3 — "need_connect" alert raced the creds fetch. Pure frontend; we only
        regression-check /api/asi/bot persistence of the `profile` field so
        the Full-Auto scheduler sees the user's choice.

Regression — close trade 404, GET /trades returns _id as string,
             leaderboard/live sorted by unrealized_pct DESC.
"""
import os
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get("EXPO_BACKEND_URL") or os.environ.get("EXPO_PUBLIC_BACKEND_URL") \
    or "https://cryptostock-pro.preview.emergentagent.com"
BASE_URL = BASE_URL.rstrip("/")

# device bound to lifetime unlock → premium /api/ai-suggestions access
PREMIUM_DEVICE = "test-judge-device-001"


@pytest.fixture(scope="module")
def api_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    yield s
    s.close()


# ---------- Bug 1 + Bug 2: /api/ai-suggestions engine routing + TP fields ----------
class TestAiSuggestionsEngineRouting:
    """GET /api/ai-suggestions must branch on `profile` and expose singular TP fields."""

    @pytest.mark.parametrize("profile,expected_engine", [
        ("scalper", "VWAP-SCALPER"),
        ("day", "VWAP-INTRADAY"),  # NOTE: review request wrote "VWAP-DAY" — backend label is VWAP-INTRADAY
        ("swing", "VWAP-SWING"),
        ("confluence", "CONFLUENCE"),
    ])
    def test_engine_label_matches_profile(self, api_client, profile, expected_engine):
        r = api_client.get(
            f"{BASE_URL}/api/ai-suggestions",
            params={"market": "crypto", "profile": profile, "device_id": PREMIUM_DEVICE, "limit": 5},
            timeout=60,
        )
        assert r.status_code == 200, f"status={r.status_code} body={r.text[:300]}"
        data = r.json()
        assert data["engine"] == expected_engine, \
            f"profile={profile} got engine={data['engine']} expected {expected_engine}"
        assert data["profile"] == profile

    def test_no_profile_defaults_to_confluence(self, api_client):
        r = api_client.get(
            f"{BASE_URL}/api/ai-suggestions",
            params={"market": "crypto", "device_id": PREMIUM_DEVICE, "limit": 3},
            timeout=60,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["engine"] == "CONFLUENCE"
        assert data["profile"] in (None, "")

    def test_scalper_signals_have_singular_tp_fields(self, api_client):
        """Bug 1 root cause: backend sends take_profit, take_profit_2, take_profit_3 (singular)."""
        r = api_client.get(
            f"{BASE_URL}/api/ai-suggestions",
            params={"market": "crypto", "profile": "scalper", "device_id": PREMIUM_DEVICE, "limit": 5},
            timeout=60,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["engine"] == "VWAP-SCALPER"
        suggestions = data.get("suggestions", [])
        if not suggestions:
            pytest.skip("No active scalper signals right now")
        buy_sell = [s for s in suggestions if s.get("action") in ("BUY", "SELL")]
        assert buy_sell, "Expected at least one BUY/SELL signal in scalper feed"
        top = buy_sell[0]
        # The exact fields the frontend normalises into take_profits[]
        assert "take_profit" in top and isinstance(top["take_profit"], (int, float))
        assert "take_profit_2" in top and isinstance(top["take_profit_2"], (int, float))
        assert "take_profit_3" in top and isinstance(top["take_profit_3"], (int, float))
        assert "entry" in top and "stop_loss" in top
        # And NO plural key (which was the frontend's broken expectation)
        assert "take_profits" not in top, \
            "Backend started sending take_profits plural — frontend normaliser becomes redundant (not a bug, just FYI)"

    def test_day_profile_returns_non_confluence_engine(self, api_client):
        """Bug 2 regression: profile=day must NOT fall back to CONFLUENCE."""
        r = api_client.get(
            f"{BASE_URL}/api/ai-suggestions",
            params={"market": "crypto", "profile": "day", "device_id": PREMIUM_DEVICE, "limit": 1},
            timeout=60,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["engine"] != "CONFLUENCE", \
            "profile=day returned CONFLUENCE — bug 2 regression (useTraderProfile wiring)"
        assert "VWAP" in data["engine"]


# ---------- Bug 2 (persistence): /api/asi/bot persists profile ----------
class TestAsiBotProfilePersistence:
    """POST /api/asi/bot must round-trip profile=scalper/day/swing (not force confluence)."""

    @pytest.fixture(scope="class")
    def test_device(self):
        return f"test-980-{uuid.uuid4().hex[:10]}"

    def _get_bot(self, api_client, device_id):
        return api_client.get(f"{BASE_URL}/api/asi/bot", params={"device_id": device_id}, timeout=30)

    def _set_bot(self, api_client, device_id, payload):
        return api_client.post(f"{BASE_URL}/api/asi/bot",
                               params={"device_id": device_id}, json=payload, timeout=30)

    @pytest.mark.parametrize("profile", ["scalper", "day", "swing", "confluence"])
    def test_profile_round_trip(self, api_client, test_device, profile):
        payload = {
            "enabled": False, "exchange": "binance", "mode": "semi",
            "max_trades_per_day": 5, "risk_pct": 5, "leverage": 10,
            "whitelist": [], "profile": profile,
            "min_confidence": 75, "daily_loss_limit_usdt": 0,
            "tp_count": 3, "trailing_callback_rate": 2,
            "semi_enabled": False, "full_enabled": False,
            "disclaimer_ack": False,
        }
        r = self._set_bot(api_client, test_device, payload)
        assert r.status_code == 200, f"POST /asi/bot failed: {r.status_code} {r.text[:300]}"
        got = self._get_bot(api_client, test_device)
        assert got.status_code == 200
        body = got.json()
        assert body.get("exists") is True
        assert body.get("profile") == profile, \
            f"profile not persisted: sent {profile} got {body.get('profile')}"


# ---------- Regression: close trade, trades list, leaderboard ----------
class TestRegressionAsiEndpoints:
    def test_close_unknown_trade_returns_404(self, api_client):
        device = f"test-980-{uuid.uuid4().hex[:8]}"
        unknown_tid = "0" * 24
        r = api_client.post(
            f"{BASE_URL}/api/asi/trades/{unknown_tid}/close",
            params={"device_id": device}, timeout=30,
        )
        assert r.status_code == 404, f"expected 404, got {r.status_code} {r.text[:200]}"

    def test_list_trades_shape_and_id(self, api_client):
        device = f"test-980-{uuid.uuid4().hex[:8]}"
        r = api_client.get(f"{BASE_URL}/api/asi/trades",
                           params={"device_id": device}, timeout=30)
        assert r.status_code == 200
        body = r.json()
        assert "items" in body and isinstance(body["items"], list)
        for it in body["items"][:5]:
            if "_id" in it:
                assert isinstance(it["_id"], str), "_id should be serialised as string"

    def test_leaderboard_live_sorted_desc(self, api_client):
        r = api_client.get(f"{BASE_URL}/api/asi/leaderboard/live", timeout=30)
        assert r.status_code == 200
        body = r.json()
        items = body.get("items", [])
        if len(items) < 2:
            pytest.skip("Not enough live leaderboard rows to assert sort order")
        pcts = [it.get("unrealized_pct", 0) for it in items]
        assert pcts == sorted(pcts, reverse=True), \
            f"leaderboard not sorted desc by unrealized_pct: {pcts}"
        # Profit-only invariant from iter_33
        assert all(p > 0 for p in pcts), "All live leaderboard entries must be positive %"
        # Rank starts at 1
        if "rank" in items[0]:
            assert items[0]["rank"] == 1
