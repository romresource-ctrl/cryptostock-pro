"""
Iteration 26 — v8.12.1 signal payload tests.

Verifies:
 1. /api/asset/crypto/{SYMBOL}/chart returns a signal dict with the new
    3-tier entry ladder (deep/moderate/aggressive) each exposing low/high,
    plus take_profit_2 / take_profit_3 / regime.
 2. Applies to BTC, ETH, SOL, XRP, DOGE across 1h and 4h.
 3. Non-crypto (stock_us AAPL) still returns entry_moderate/aggressive
    low/high with regime == "UNKNOWN".
 4. /api/dashboard schema still exposes AssetSignal fields.
"""

import os
import pytest
import requests

BASE_URL = (os.environ.get("preview_endpoint") or os.environ.get("EXPO_BACKEND_URL") or "").rstrip("/")

if not BASE_URL:
    raise RuntimeError("preview_endpoint / EXPO_BACKEND_URL env var missing – cannot run backend tests")

REQUIRED_SIGNAL_KEYS = [
    "entry", "entry_low", "entry_high",
    "entry_moderate", "entry_moderate_low", "entry_moderate_high",
    "entry_aggressive", "entry_aggressive_low", "entry_aggressive_high",
    "take_profit", "take_profit_2", "take_profit_3",
    "stop_loss", "regime", "action", "confidence", "label",
]

VALID_CRYPTO_REGIMES = {"BULL", "BEAR", "BEAR_CAPITULATION", "SIDEWAYS", "UNKNOWN"}


@pytest.fixture(scope="module")
def api_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def _fetch_chart(api_client, market: str, symbol: str, timeframe: str) -> dict:
    url = f"{BASE_URL}/api/asset/{market}/{symbol}/chart?timeframe={timeframe}"
    r = api_client.get(url, timeout=45)
    assert r.status_code == 200, f"GET {url} => {r.status_code} : {r.text[:300]}"
    body = r.json()
    assert "signal" in body and isinstance(body["signal"], dict), f"missing signal in {url}"
    return body


# -----------------------------------------------------------------------------
# 1) BTC on 1h — full field set required
# -----------------------------------------------------------------------------
class TestBTCSignalPayload:

    def test_btc_1h_has_all_new_keys(self, api_client):
        body = _fetch_chart(api_client, "crypto", "BTC", "1h")
        sig = body["signal"]
        missing = [k for k in REQUIRED_SIGNAL_KEYS if k not in sig]
        assert not missing, f"BTC/1h missing keys: {missing}. Got keys={sorted(sig.keys())}"

    def test_btc_1h_regime_is_valid(self, api_client):
        sig = _fetch_chart(api_client, "crypto", "BTC", "1h")["signal"]
        assert sig["regime"] in VALID_CRYPTO_REGIMES, f"regime={sig['regime']!r} not in {VALID_CRYPTO_REGIMES}"

    def test_btc_1h_numeric_types(self, api_client):
        sig = _fetch_chart(api_client, "crypto", "BTC", "1h")["signal"]
        # Every required key must be number or None (never missing / string)
        for k in ["entry", "entry_low", "entry_high",
                  "entry_moderate", "entry_moderate_low", "entry_moderate_high",
                  "entry_aggressive", "entry_aggressive_low", "entry_aggressive_high",
                  "take_profit", "take_profit_2", "take_profit_3", "stop_loss"]:
            v = sig.get(k)
            assert v is None or isinstance(v, (int, float)), f"{k} must be number|null, got {type(v).__name__} => {v!r}"


# -----------------------------------------------------------------------------
# 2) BTC/ETH/SOL/XRP/DOGE × 1h,4h — full field set required
# -----------------------------------------------------------------------------
CRYPTO_SYMBOLS = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
# NOTE: Review requested 1h + 4h, but backend TIMEFRAME_MAP
# (backend/market_data.py:627) does NOT include "4h" — supported longer
# TFs are 3h / 6h / 12h / 24h. Using 6h as the closest supported bucket
# so the v8.12.1 payload can still be validated on a non-1h chart.
CRYPTO_TFS = ["1h", "6h"]


@pytest.mark.parametrize("symbol", CRYPTO_SYMBOLS)
@pytest.mark.parametrize("tf", CRYPTO_TFS)
class TestCryptoMatrix:

    def test_has_all_required_keys(self, api_client, symbol, tf):
        sig = _fetch_chart(api_client, "crypto", symbol, tf)["signal"]
        missing = [k for k in REQUIRED_SIGNAL_KEYS if k not in sig]
        assert not missing, f"{symbol}/{tf} missing keys: {missing}"

    def test_regime_valid(self, api_client, symbol, tf):
        sig = _fetch_chart(api_client, "crypto", symbol, tf)["signal"]
        assert sig["regime"] in VALID_CRYPTO_REGIMES, f"{symbol}/{tf} regime={sig['regime']!r}"

    def test_tier_ladder_when_buy_or_sell(self, api_client, symbol, tf):
        """When action in {BUY, SELL}: 3-tier ladder must be distinct and
        take_profit_2 / take_profit_3 must be non-null & monotonically further
        from entry than take_profit. HOLD is expected to have TP2/TP3 = null.
        """
        sig = _fetch_chart(api_client, "crypto", symbol, tf)["signal"]
        action = sig["action"]

        if action not in ("BUY", "SELL"):
            pytest.skip(f"{symbol}/{tf} action={action} — ladder assertions only apply to BUY/SELL")

        entry_deep = sig["entry_low"]        # low bound of tier1
        entry_mod = sig["entry_moderate_low"]
        entry_agg = sig["entry_aggressive_low"]

        assert entry_deep is not None and entry_mod is not None and entry_agg is not None, \
            f"{symbol}/{tf} tier lows must be numeric for {action}"

        if action == "BUY":
            # BUY: deep is furthest below price, moderate ≈ price, aggressive slightly above
            assert entry_deep < entry_mod <= entry_agg, \
                f"{symbol}/{tf} BUY ladder failed: deep={entry_deep} mod={entry_mod} agg={entry_agg}"
        else:  # SELL
            assert entry_deep > entry_mod >= entry_agg, \
                f"{symbol}/{tf} SELL ladder failed: deep={entry_deep} mod={entry_mod} agg={entry_agg}"

        # TP ladder
        entry = sig["entry"]
        tp1 = sig["take_profit"]
        tp2 = sig["take_profit_2"]
        tp3 = sig["take_profit_3"]
        assert tp2 is not None and tp3 is not None, \
            f"{symbol}/{tf} TP2/TP3 must be non-null when action={action} (got tp2={tp2} tp3={tp3})"

        d1 = abs(tp1 - entry)
        d2 = abs(tp2 - entry)
        d3 = abs(tp3 - entry)
        assert d1 < d2 < d3, f"{symbol}/{tf} TP ladder not monotonic: d1={d1} d2={d2} d3={d3}"

    def test_hold_tp2_tp3_allowed_null(self, api_client, symbol, tf):
        """No regression: for HOLD, tp2/tp3 = None is OK (not a failure)."""
        sig = _fetch_chart(api_client, "crypto", symbol, tf)["signal"]
        if sig["action"] != "HOLD":
            pytest.skip(f"{symbol}/{tf} action={sig['action']} — only for HOLD")
        # We simply assert the fields *exist* (even if null).
        assert "take_profit_2" in sig and "take_profit_3" in sig


# -----------------------------------------------------------------------------
# 3) Non-crypto sanity — AAPL stock_us / 1d
# -----------------------------------------------------------------------------
class TestStockUSSanity:

    def test_aapl_signal_has_tier_ranges_and_unknown_regime(self, api_client):
        # NOTE: Review requested "1d" but backend TIMEFRAME_MAP does NOT
        # include "1d" — supported daily bucket is "24h". Using 24h.
        body = _fetch_chart(api_client, "stock_us", "AAPL", "24h")
        sig = body["signal"]

        for k in ["entry_moderate_low", "entry_moderate_high",
                  "entry_aggressive_low", "entry_aggressive_high"]:
            assert k in sig, f"AAPL/1d missing {k}"
            assert sig[k] is None or isinstance(sig[k], (int, float)), \
                f"AAPL/1d {k} must be number|null, got {sig[k]!r}"

        assert sig.get("regime") == "UNKNOWN", f"AAPL/1d regime expected UNKNOWN, got {sig.get('regime')!r}"


# -----------------------------------------------------------------------------
# 4) /api/dashboard schema regression — must still return AssetSignal fields
# -----------------------------------------------------------------------------
class TestDashboardSchema:

    def test_dashboard_crypto_1h_has_asset_signal_fields(self, api_client):
        url = f"{BASE_URL}/api/dashboard?market=crypto&timeframe=1h"
        r = api_client.get(url, timeout=45)
        assert r.status_code == 200, f"{url} => {r.status_code} : {r.text[:300]}"
        body = r.json()
        assert "assets" in body and isinstance(body["assets"], list) and body["assets"], \
            "dashboard.assets must be a non-empty list"

        # Check the first few assets have the mandated AssetSignal fields.
        required = ["symbol", "market", "action", "confidence",
                    "entry_low", "entry_high", "entry_moderate", "entry_aggressive",
                    "is_premium"]

        for a in body["assets"][:5]:
            missing = [k for k in required if k not in a]
            assert not missing, f"asset {a.get('symbol')!r} missing {missing}"
            assert isinstance(a["is_premium"], bool)
            assert isinstance(a["confidence"], int)
            assert a["action"] in ("BUY", "SELL", "HOLD"), f"unexpected action {a['action']!r}"
