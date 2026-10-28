# v10.6.1 — Leaderboard live: parameter badge fields (read-only GET, no orders)
import os
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", os.environ.get("EXPO_BACKEND_URL", "")).rstrip("/")


@pytest.fixture(scope="module")
def live_items():
    if not BASE_URL:
        pytest.skip("EXPO_PUBLIC_BACKEND_URL not set")
    r = requests.get(f"{BASE_URL}/api/asi/leaderboard/live", timeout=30)
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data.get("items"), list)
    return data["items"]


# Leaderboard live — every row carries badge fields
def test_badge_fields_present(live_items):
    if not live_items:
        pytest.skip("leaderboard empty")
    for it in live_items:
        for k in ("auto_close_pct", "margin_mode", "formula_tag", "tp_count"):
            assert k in it, f"rank {it.get('rank')} missing {k}"


# Leaderboard live — field value types/domains
def test_badge_field_values(live_items):
    if not live_items:
        pytest.skip("leaderboard empty")
    for it in live_items:
        if it.get("margin_mode") is not None:
            assert str(it["margin_mode"]).lower() in ("isolated", "cross")
        if it.get("auto_close_pct") is not None:
            assert 0 <= float(it["auto_close_pct"]) <= 100
        if it.get("tp_count") is not None:
            assert int(it["tp_count"]) in (1, 2, 3)
        assert it.get("status") in ("open", "closed", "pending_entry")
        assert it.get("side") in ("BUY", "SELL")
        assert "_id" not in it
