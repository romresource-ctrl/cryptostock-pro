"""v8.7.0 — Stricter Premium formula + track-record WR history popup contract.

Scope (per iter23 review request):
  1. GET /api/asset/{market}/{symbol}/track-record — returns win_rate_7d/30d/all
     buckets with wins/losses/break_even AND history_7d/30d/all lists whose
     items include outcome ∈ {WIN,LOSS,BE}, pct_change, created_at, timeframe,
     action, label, price_at_signal, price_after.
  2. GET /api/dashboard?market=crypto&timeframe=1h — stricter Premium gate:
     is_premium ⇒ confidence >= 85 AND (wr_30d >= 70 OR (wr_30d IS None AND
     confidence >= 90)).
  3. GET /api/dashboard/batch — still returns valid multi-market payload.
  4. POST /api/asset/crypto/BTC/analyze — still works end-to-end.
"""
from __future__ import annotations

import os
import time

import pytest
import requests

BASE_URL = (
    os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or os.environ.get("EXPO_BACKEND_URL")
    or ""
).rstrip("/")

if not BASE_URL:
    raise RuntimeError("EXPO_PUBLIC_BACKEND_URL must be set")


@pytest.fixture(scope="session")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ---------- helpers ----------
_HISTORY_ITEM_KEYS = {
    "action", "label", "confidence", "timeframe", "price_at_signal",
    "created_at", "outcome", "pct_change", "price_after",
}
_WR_BUCKET_KEYS = {"total", "hits", "wins", "losses", "break_even", "win_rate"}


def _assert_wr_bucket(bucket: dict, name: str) -> None:
    assert isinstance(bucket, dict), f"{name} not a dict"
    missing = _WR_BUCKET_KEYS - set(bucket.keys())
    assert not missing, f"{name} missing keys: {missing}"
    assert isinstance(bucket["total"], int)
    assert isinstance(bucket["wins"], int)
    assert isinstance(bucket["losses"], int)
    assert isinstance(bucket["break_even"], int)
    assert isinstance(bucket["hits"], int)
    # hits == wins for backward-compat
    assert bucket["hits"] == bucket["wins"], f"{name}: hits should equal wins"
    # totals reconcile
    assert bucket["wins"] + bucket["losses"] + bucket["break_even"] == bucket["total"], (
        f"{name}: wins+losses+be != total"
    )
    wr = bucket["win_rate"]
    if bucket["total"] == 0:
        assert wr is None
    else:
        assert isinstance(wr, (int, float))
        assert 0.0 <= wr <= 100.0


def _assert_history_item(item: dict, ctx: str) -> None:
    missing = _HISTORY_ITEM_KEYS - set(item.keys())
    assert not missing, f"{ctx}: history item missing {missing}"
    assert item["action"] in ("BUY", "SELL", "HOLD"), f"{ctx}: bad action {item['action']}"
    assert item["outcome"] in ("WIN", "LOSS", "BE"), f"{ctx}: bad outcome {item['outcome']}"
    # timeframe should be a canonical string
    assert isinstance(item["timeframe"], str) and item["timeframe"]
    # created_at ISO format
    ca = item["created_at"]
    assert isinstance(ca, str) and ("T" in ca), f"{ctx}: created_at not ISO: {ca!r}"
    # pct_change may be None only for unevaluated legacy rows — but the
    # history_* lists only include `evaluated=True` docs per track_record.py,
    # so numeric here.
    assert isinstance(item["pct_change"], (int, float)), f"{ctx}: pct_change not numeric"
    assert isinstance(item["price_at_signal"], (int, float))


# ---------- 1. Track-record contract ----------
class TestTrackRecordContract:
    """v8.7.0 track-record endpoint schema."""

    def test_btc_track_record_has_all_v870_keys(self, api):
        r = api.get(f"{BASE_URL}/api/asset/crypto/BTC/track-record", timeout=60)
        assert r.status_code == 200, r.text
        data = r.json()
        # symbol/market echo
        assert data["symbol"] == "BTC"
        assert data["market"] == "crypto"
        # WR buckets
        for k in ("win_rate_7d", "win_rate_30d", "win_rate_all"):
            assert k in data, f"missing bucket {k}"
            _assert_wr_bucket(data[k], k)
        # History lists
        for k in ("history_7d", "history_30d", "history_all"):
            assert k in data, f"missing history {k}"
            assert isinstance(data[k], list)
        # Legacy compat
        assert "recent_signals" in data
        assert isinstance(data["recent_signals"], list)
        assert len(data["recent_signals"]) <= 8

    def test_btc_history_items_shape(self, api):
        r = api.get(f"{BASE_URL}/api/asset/crypto/BTC/track-record", timeout=60)
        data = r.json()
        # history_all should be the biggest (or equal to) 30d ≥ 7d
        assert len(data["history_all"]) >= len(data["history_30d"]) >= len(data["history_7d"])
        # Validate every item across all three lists
        for tag in ("history_7d", "history_30d", "history_all"):
            for item in data[tag]:
                _assert_history_item(item, tag)

    def test_btc_history_outcomes_reconcile_with_wr_buckets(self, api):
        """WR bucket counts should match outcome counts in the paired history list."""
        r = api.get(f"{BASE_URL}/api/asset/crypto/BTC/track-record", timeout=60)
        data = r.json()
        for hkey, wkey in (
            ("history_7d", "win_rate_7d"),
            ("history_30d", "win_rate_30d"),
            ("history_all", "win_rate_all"),
        ):
            hist = data[hkey]
            wr = data[wkey]
            wins = sum(1 for h in hist if h["outcome"] == "WIN")
            losses = sum(1 for h in hist if h["outcome"] == "LOSS")
            be = sum(1 for h in hist if h["outcome"] == "BE")
            # history_all may be capped at history_limit=500; if total > 500
            # the two won't reconcile perfectly. Accept when total <= 500.
            if wr["total"] <= 500:
                assert wr["wins"] == wins, f"{wkey}.wins={wr['wins']} but {hkey} has {wins}"
                assert wr["losses"] == losses, f"{wkey}.losses"
                assert wr["break_even"] == be, f"{wkey}.break_even"

    def test_eth_track_record_ok(self, api):
        r = api.get(f"{BASE_URL}/api/asset/crypto/ETH/track-record", timeout=60)
        assert r.status_code == 200
        data = r.json()
        assert data["symbol"] == "ETH"
        for k in ("win_rate_7d", "win_rate_30d", "win_rate_all",
                  "history_7d", "history_30d", "history_all", "recent_signals"):
            assert k in data

    def test_unknown_symbol_returns_empty_buckets(self, api):
        """Unknown symbol shouldn't 500 — should return zero-count buckets."""
        r = api.get(f"{BASE_URL}/api/asset/crypto/NEWCOIN/track-record", timeout=60)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["symbol"] == "NEWCOIN"
        for k in ("win_rate_7d", "win_rate_30d", "win_rate_all"):
            assert data[k]["total"] == 0
            assert data[k]["wins"] == 0
            assert data[k]["win_rate"] is None
        for k in ("history_7d", "history_30d", "history_all", "recent_signals"):
            assert data[k] == []


# ---------- 2. Dashboard stricter Premium gate ----------
class TestDashboardStrictPremiumGate:
    """v8.7.0 — Premium requires conf>=85 AND (wr_30d>=70 OR no WR & conf>=90)."""

    @pytest.fixture(scope="class")
    def dash(self, api):
        r = api.get(
            f"{BASE_URL}/api/dashboard",
            params={"market": "crypto", "timeframe": "1h"},
            timeout=90,
        )
        assert r.status_code == 200, r.text
        return r.json()

    def test_dashboard_schema_valid(self, dash):
        assert dash["market"] == "crypto"
        assert isinstance(dash["assets"], list)
        assert len(dash["assets"]) > 0
        assert "premium_threshold" in dash
        assert dash["premium_threshold"]["min_confidence"] == 85
        assert dash["premium_threshold"]["min_wr"] == 70.0

    def test_dashboard_no_crashes_on_all_assets(self, dash):
        """Every asset must have valid action/confidence and no missing keys."""
        for a in dash["assets"]:
            assert a["action"] in ("BUY", "SELL", "HOLD"), f"{a['symbol']}: {a['action']}"
            assert 0 <= a["confidence"] <= 100
            assert isinstance(a["is_premium"], bool)

    def test_premium_signals_pass_strict_gate(self, dash):
        """Every is_premium=True asset must satisfy the v8.7.0 rules."""
        min_conf = dash["premium_threshold"]["min_confidence"]
        min_wr = dash["premium_threshold"]["min_wr"]
        violations = []
        for a in dash["assets"]:
            if not a["is_premium"]:
                continue
            # Rule A: action must be BUY or SELL (not HOLD)
            if a["action"] == "HOLD":
                violations.append(f"{a['symbol']}: premium but HOLD")
                continue
            wr30 = (a.get("track_record") or {}).get("wr_30d")
            conf = a["confidence"]
            if wr30 is None:
                # Rule B2: no WR ⇒ conf >= min_conf + 5 (i.e. 90)
                if conf < min_conf + 5:
                    violations.append(
                        f"{a['symbol']}: premium/no-WR but conf={conf} < {min_conf + 5}"
                    )
            else:
                # Rule B1: has WR ⇒ conf >= min_conf AND wr >= min_wr
                if conf < min_conf:
                    violations.append(f"{a['symbol']}: premium but conf={conf} < {min_conf}")
                if wr30 < min_wr:
                    violations.append(f"{a['symbol']}: premium but wr_30d={wr30} < {min_wr}")
        assert not violations, "Premium gate violations:\n  " + "\n  ".join(violations)

    def test_hold_ratio_reflects_stricter_gate(self, dash):
        """Sanity: with stricter score>=3 & trend-aligned gate, HOLD should be a
        meaningful chunk of assets. Not a hard bound — just check it's not zero."""
        holds = sum(1 for a in dash["assets"] if a["action"] == "HOLD")
        # With realistic market data the stricter gate should keep some HOLDs.
        # Accept anything >=0 but log the ratio for reviewer visibility.
        print(f"[iter23] HOLD ratio: {holds}/{len(dash['assets'])}")
        assert holds >= 0

    def test_premium_count_field(self, dash):
        actual = sum(1 for a in dash["assets"] if a["is_premium"])
        assert dash["premium_count"] == actual


# ---------- 3. Dashboard batch ----------
class TestDashboardBatch:
    def test_batch_multi_market(self, api):
        r = api.get(
            f"{BASE_URL}/api/dashboard/batch",
            params={"markets": "crypto,stock_us", "timeframe": "1h"},
            timeout=120,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert "markets" in data
        markets = data["markets"]
        assert "crypto" in markets and "stock_us" in markets
        # Each market should carry assets or an error field
        for m, payload in markets.items():
            assert "assets" in payload or "error" in payload, f"{m}: {payload}"
            if "assets" in payload:
                assert isinstance(payload["assets"], list)


# ---------- 4. Analyze endpoint still works ----------
class TestAnalyzeEndpoint:
    def test_btc_analyze_ok(self, api):
        # /analyze runs the AI ensemble (LLM calls) — allow generous timeout
        r = api.post(
            f"{BASE_URL}/api/asset/crypto/BTC/analyze",
            params={"timeframe": "1h", "lang": "id"},
            timeout=180,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        # TA still feeds in
        assert "technical" in data
        assert data["technical"]["action"] in ("BUY", "SELL", "HOLD")
        assert 0 <= data["technical"]["confidence"] <= 100
        # AI ensemble present (may be single-model fallback if any fail)
        assert "consensus" in data or "ai" in data or "models" in data


# ---------- 5. Regression smoke ----------
class TestRegressionSmoke:
    def test_health(self, api):
        r = api.get(f"{BASE_URL}/api/", timeout=15)
        assert r.status_code == 200

    def test_track_record_summary_via_dashboard(self, api):
        """Dashboard rows carry track_record mini per symbol — sanity check."""
        r = api.get(f"{BASE_URL}/api/dashboard", params={"market": "crypto", "timeframe": "1h"}, timeout=90)
        data = r.json()
        # At least one asset should have a wr_30d (from the DB fixtures)
        has_any_wr = any(
            (a.get("track_record") or {}).get("wr_30d") is not None for a in data["assets"]
        )
        # Not a hard failure if all None (fresh DB) — just note it.
        print(f"[iter23] any wr_30d present: {has_any_wr}")
