"""v8.7.2 — Adaptive premium thresholds per market + Market Brief premium gating
+ WR history reset verification.

Covers:
  1. GET /api/dashboard?market={m} → premium_threshold varies per market.
     - crypto → 87 / 72.0
     - stock_us / world_stocks / stock_id / etf / forex → 88 / 75.0
     - gold_silver / commodity → 90 / 75.0
  2. GET /api/dashboard/batch?markets=... → each market carries adaptive
     threshold in its response entry.
  3. GET /api/asset/crypto/BTC/track-record → win_rate_all.total is 0 (or
     tiny; live signals may have accumulated) after the manual wipe.
  4. GET /api/market-brief (no device_id, bogus device_id) → free tier
     locked shape: sections={}, top_movers=[], premium_locked=True,
     is_premium=False. Free info (summary, sentiment, warning_zones,
     top_headlines) still populated.
  5. Translation gating unaffected: lang=id free tier still returns
     translated summary + warning_zones.
  6. Regression: /api/asset/crypto/BTC/analyze, /api/push/history?language=en,
     /api/dashboard?market=crypto&min_confidence=80&min_wr=65 override.
"""
from __future__ import annotations

import os
import time

import pytest
import requests

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")

# Adaptive threshold table copied from server.py `_MARKET_THRESHOLDS`.
EXPECTED_THRESHOLDS: dict[str, tuple[int, float]] = {
    "crypto":               (87, 72.0),
    "stock_us":             (88, 75.0),
    "world_stocks":         (88, 75.0),
    "stock_id":             (88, 75.0),
    "etf":                  (88, 75.0),
    "forex":                (88, 75.0),
    "gold_silver":          (90, 75.0),
    "commodity":            (90, 75.0),
}


@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ---------- 1. Adaptive premium threshold per market ----------


class TestAdaptivePremiumThresholds:
    """Every market must expose the market-specific default threshold."""

    @pytest.mark.parametrize("market,exp_conf,exp_wr", [
        ("crypto",       87, 72.0),
        ("stock_us",     88, 75.0),
        ("world_stocks", 88, 75.0),
        ("stock_id",     88, 75.0),
        ("etf",          88, 75.0),
        ("forex",        88, 75.0),
        ("gold_silver",  90, 75.0),
        ("commodity",    90, 75.0),
    ])
    def test_dashboard_returns_expected_default_threshold(
        self, api, market, exp_conf, exp_wr
    ):
        r = api.get(
            f"{BASE_URL}/api/dashboard",
            params={"market": market, "timeframe": "1h"},
            timeout=60,
        )
        assert r.status_code == 200, f"{market}: HTTP {r.status_code} — {r.text[:200]}"
        j = r.json()
        pt = j.get("premium_threshold")
        assert isinstance(pt, dict), f"{market}: premium_threshold missing/invalid: {pt}"
        assert pt.get("min_confidence") == exp_conf, (
            f"{market}: expected min_confidence={exp_conf}, got {pt.get('min_confidence')}"
        )
        assert pt.get("min_wr") == exp_wr, (
            f"{market}: expected min_wr={exp_wr}, got {pt.get('min_wr')}"
        )

    def test_dashboard_override_is_honored(self, api):
        """?min_confidence=80&min_wr=65 must override adaptive defaults."""
        r = api.get(
            f"{BASE_URL}/api/dashboard",
            params={"market": "crypto", "min_confidence": 80, "min_wr": 65},
            timeout=60,
        )
        assert r.status_code == 200
        pt = r.json()["premium_threshold"]
        assert pt["min_confidence"] == 80, pt
        assert pt["min_wr"] == 65.0, pt

    def test_dashboard_partial_override_only_confidence(self, api):
        """?min_confidence=95 alone — WR should still fall back to adaptive default."""
        r = api.get(
            f"{BASE_URL}/api/dashboard",
            params={"market": "gold_silver", "min_confidence": 95},
            timeout=60,
        )
        assert r.status_code == 200
        pt = r.json()["premium_threshold"]
        assert pt["min_confidence"] == 95, pt
        # WR should retain gold_silver's adaptive 75.0 (not the old 70.0 fallback).
        assert pt["min_wr"] == 75.0, pt


# ---------- 2. Batch dashboard adaptive ----------


class TestBatchDashboardAdaptive:

    def test_batch_returns_adaptive_threshold_per_market(self, api):
        markets = "crypto,stock_us,forex,gold_silver"
        r = api.get(
            f"{BASE_URL}/api/dashboard/batch",
            params={"markets": markets, "timeframe": "1h"},
            timeout=90,
        )
        assert r.status_code == 200, r.text[:300]
        j = r.json()
        m_map = j.get("markets") or {}
        assert set(m_map.keys()) >= {"crypto", "stock_us", "forex", "gold_silver"}, m_map.keys()
        for mkt in ("crypto", "stock_us", "forex", "gold_silver"):
            entry = m_map[mkt]
            pt = entry.get("premium_threshold")
            exp_conf, exp_wr = EXPECTED_THRESHOLDS[mkt]
            assert pt and pt.get("min_confidence") == exp_conf and pt.get("min_wr") == exp_wr, (
                f"batch[{mkt}] premium_threshold mismatch: {pt}"
            )

    def test_batch_covers_all_eight_markets(self, api):
        markets_all = ",".join([
            "crypto", "stock_us", "world_stocks", "stock_id",
            "etf", "forex", "gold_silver", "commodity",
        ])
        r = api.get(
            f"{BASE_URL}/api/dashboard/batch",
            params={"markets": markets_all, "timeframe": "1h"},
            timeout=120,
        )
        assert r.status_code == 200
        m_map = r.json().get("markets") or {}
        for mkt, (exp_conf, exp_wr) in EXPECTED_THRESHOLDS.items():
            assert mkt in m_map, f"missing market {mkt} in batch response"
            pt = m_map[mkt].get("premium_threshold") or {}
            assert pt.get("min_confidence") == exp_conf, f"{mkt}: {pt}"
            assert pt.get("min_wr") == exp_wr, f"{mkt}: {pt}"


# ---------- 3. WR history reset verification ----------


class TestWRReset:
    """After the manual signals wipe, BTC track-record.win_rate_all.total should be 0
    (or a small number if new signals have been recorded post-reset)."""

    def test_btc_track_record_wr_all_reset(self, api):
        r = api.get(f"{BASE_URL}/api/asset/crypto/BTC/track-record", timeout=30)
        assert r.status_code == 200
        j = r.json()
        wr_all = j.get("win_rate_all")
        assert isinstance(wr_all, dict), f"win_rate_all missing/invalid: {wr_all}"
        total = wr_all.get("total")
        assert isinstance(total, int), f"total should be int, got {total!r}"
        # Previously accumulated ~48+ signals. After wipe: 0 or <5 fresh ones.
        assert total < 5, f"expected wipe (<5 evaluated), got total={total}. wr_all={wr_all}"

    def test_btc_history_all_is_recent_or_empty(self, api):
        r = api.get(f"{BASE_URL}/api/asset/crypto/BTC/track-record", timeout=30)
        j = r.json()
        history_all = j.get("history_all")
        assert isinstance(history_all, list), f"history_all should be list, got {history_all!r}"
        # Should be small (post-wipe): allow empty, or fresh entries after 2026-01.
        assert len(history_all) < 20, (
            f"expected <20 history items after wipe, got {len(history_all)}"
        )
        for item in history_all:
            created_at = item.get("created_at")
            assert created_at, f"item missing created_at: {item}"
            # Any surviving items must be from 2026 (post-wipe era).
            assert created_at >= "2026-01", (
                f"found pre-wipe signal (created_at={created_at}): {item}"
            )


# ---------- 4-5. Market Brief FREE gating (no / bogus device_id) ----------


REQUIRED_FREE_INFO_KEYS = {"summary", "sentiment", "warning_zones", "top_headlines"}


class TestMarketBriefFreeTierGating:
    """No device_id, or bogus device_id → free tier: locked sections+top_movers."""

    def _fetch_free(self, api, params):
        r = api.get(f"{BASE_URL}/api/market-brief", params=params, timeout=30)
        assert r.status_code == 200, r.text
        return r.json()

    def test_no_device_id_returns_free_tier(self, api):
        j = self._fetch_free(api, {"lang": "en"})
        assert j["is_premium"] is False, j
        assert j["available"] is True, j
        b = j["brief"]
        assert b.get("premium_locked") is True, f"premium_locked should be True: {b.get('premium_locked')}"
        assert b.get("sections") == {}, f"sections should be empty dict: {b.get('sections')!r}"
        assert b.get("top_movers") == [], f"top_movers should be empty list: {b.get('top_movers')!r}"

    def test_no_device_id_still_returns_free_info(self, api):
        j = self._fetch_free(api, {"lang": "en"})
        b = j["brief"]
        assert isinstance(b.get("summary"), str) and len(b["summary"]) > 20, (
            f"free summary should be non-empty: {b.get('summary')!r}"
        )
        assert b.get("sentiment") in {"bullish", "bearish", "mixed", "neutral"}, b.get("sentiment")
        wz = b.get("warning_zones")
        assert isinstance(wz, list) and len(wz) >= 1, f"warning_zones: {wz!r}"
        for w in wz:
            assert isinstance(w, str) and w, w
        th = b.get("top_headlines")
        assert isinstance(th, list) and len(th) >= 1, f"top_headlines: {th!r}"

    def test_bogus_device_id_still_free_tier(self, api):
        j = self._fetch_free(api, {"lang": "en", "device_id": "notarealone123"})
        assert j["is_premium"] is False, j
        b = j["brief"]
        assert b["premium_locked"] is True, b
        assert b["sections"] == {}, b["sections"]
        assert b["top_movers"] == [], b["top_movers"]

    def test_free_tier_response_envelope_intact(self, api):
        """Overall shape validity: keys `available`, `lang`, `brief`, `is_premium`."""
        j = self._fetch_free(api, {"lang": "en"})
        assert set(j.keys()) >= {"available", "lang", "brief", "is_premium"}, j.keys()
        assert j["lang"] == "en"


# ---------- 7. Translation gating unaffected ----------


class TestMarketBriefTranslationsFreeTier:
    """Free tier still gets the translated summary + warning_zones in ID."""

    def test_id_free_tier_has_translated_summary(self, api):
        # Prime EN then ID (translation may need a moment on first call).
        api.get(f"{BASE_URL}/api/market-brief", params={"lang": "en"}, timeout=30)
        r_id = api.get(f"{BASE_URL}/api/market-brief", params={"lang": "id"}, timeout=60)
        assert r_id.status_code == 200
        j_id = r_id.json()
        assert j_id["lang"] == "id"
        assert j_id["is_premium"] is False
        b_id = j_id["brief"]
        assert b_id["premium_locked"] is True
        # Sections + top_movers still locked for free tier
        assert b_id["sections"] == {}, b_id["sections"]
        assert b_id["top_movers"] == [], b_id["top_movers"]
        # But translated general info remains
        assert isinstance(b_id["summary"], str) and len(b_id["summary"]) > 20
        # Verify translation actually happened (differs from EN)
        r_en = api.get(f"{BASE_URL}/api/market-brief", params={"lang": "en"}, timeout=30)
        b_en = r_en.json()["brief"]
        assert b_id["summary"] != b_en["summary"], "ID summary looks identical to EN"

    def test_id_free_tier_has_translated_warning_zones(self, api):
        r = api.get(f"{BASE_URL}/api/market-brief", params={"lang": "id"}, timeout=60)
        wz = r.json()["brief"]["warning_zones"]
        assert isinstance(wz, list) and len(wz) >= 1, wz
        for w in wz:
            assert isinstance(w, str) and w, w


# ---------- 8. Regression ----------


class TestRegression:

    def test_analyze_btc_still_works(self, api):
        # /analyze is a POST endpoint (AI ensemble; ~15s).
        r = api.post(f"{BASE_URL}/api/asset/crypto/BTC/analyze",
                     params={"timeframe": "1h"}, timeout=120)
        assert r.status_code == 200, r.text[:300]
        j = r.json()
        # Loose contract: must contain technical or consensus-ish payload
        # Common keys observed in prior iterations
        assert isinstance(j, dict) and j, "empty response"

    def test_push_history_en_regression(self, api):
        r = api.get(f"{BASE_URL}/api/push/history", params={"language": "en"}, timeout=30)
        assert r.status_code == 200
        j = r.json()
        # Contract preserved: dict with items/history
        assert isinstance(j, dict)

    def test_dashboard_override_regression(self, api):
        r = api.get(
            f"{BASE_URL}/api/dashboard",
            params={"market": "crypto", "min_confidence": 80, "min_wr": 65},
            timeout=60,
        )
        assert r.status_code == 200
        j = r.json()
        pt = j["premium_threshold"]
        assert pt["min_confidence"] == 80 and pt["min_wr"] == 65.0, pt
        assert isinstance(j["assets"], list)
