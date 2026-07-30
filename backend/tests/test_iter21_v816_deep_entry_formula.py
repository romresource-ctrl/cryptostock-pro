"""v8.1.6 backend regression tests for the swing-based deep-entry formula.

Scope (from review request):
- Dashboard endpoints expose new entry / entry_moderate / entry_aggressive /
  stop_loss / take_profit fields.
- Per-asset analyze endpoint returns:
    * `technical` block with new fields (entry_moderate, entry_aggressive,
      _all_levels, indicators.avg_peak, indicators.avg_valley,
      indicators.peaks_found, indicators.valleys_found).
    * `consensus` block with entry_bias + bias_votes.
- Formula math sanity:
    * For BUY signals, entry < current price (avoid falling knife).
    * For SELL signals, entry > current price.
    * TP (LONG) ≈ indicators.avg_peak, TP (SHORT) ≈ indicators.avg_valley.
    * SL is within 0.5–1 ATR of chosen entry (tighter stop).
- AI consensus.entry_bias ∈ {"deep", "moderate", "aggressive"}.
- consensus.summary length regression (soft check).
- Non-crypto (stock_us AAPL) analyze also uses the new formula.
- Search / dashboard batch / chat / subscription regression stays green.

Uses public URL from EXPO_PUBLIC_BACKEND_URL (fallback EXPO_BACKEND_URL).
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
    pytest.skip("EXPO_PUBLIC_BACKEND_URL not set", allow_module_level=True)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def api_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def btc_analyze(api_client):
    """One shared BTC analyze call (AI ensemble is expensive)."""
    url = f"{BASE_URL}/api/asset/crypto/BTC/analyze?timeframe=1h&lang=en"
    resp = api_client.post(url, timeout=120)
    assert resp.status_code == 200, f"BTC analyze failed: {resp.status_code} {resp.text[:400]}"
    return resp.json()


@pytest.fixture(scope="module")
def eth_analyze(api_client):
    url = f"{BASE_URL}/api/asset/crypto/ETH/analyze?timeframe=1h&lang=en"
    resp = api_client.post(url, timeout=120)
    assert resp.status_code == 200, f"ETH analyze failed: {resp.status_code} {resp.text[:400]}"
    return resp.json()


@pytest.fixture(scope="module")
def aapl_analyze(api_client):
    url = f"{BASE_URL}/api/asset/stock_us/AAPL/analyze?timeframe=1h&lang=en"
    resp = api_client.post(url, timeout=120)
    assert resp.status_code == 200, f"AAPL analyze failed: {resp.status_code} {resp.text[:400]}"
    return resp.json()


# ---------------------------------------------------------------------------
# 1) Dashboard: new fields exposed for every asset
# ---------------------------------------------------------------------------


class TestDashboardDeepEntry:
    def test_dashboard_crypto_has_legacy_signal_fields(self, api_client):
        """Backward-compat: legacy entry/SL/TP fields still populated."""
        url = f"{BASE_URL}/api/dashboard?market=crypto&timeframe=1h"
        r = api_client.get(url, timeout=90)
        assert r.status_code == 200, r.text[:400]
        body = r.json()
        assets = body.get("assets") or []
        assert len(assets) > 0, "no assets in dashboard"
        for a in assets:
            for k in ("entry", "stop_loss", "take_profit"):
                assert k in a, f"asset {a.get('symbol')} missing legacy field {k}"

    def test_dashboard_crypto_exposes_new_moderate_aggressive_fields(self, api_client):
        """v8.1.6 spec: each dashboard asset should surface the new
        entry_moderate and entry_aggressive fields so the frontend can
        render a 3-tier entry card without a second analyze round-trip.

        Currently AssetSignal Pydantic model (server.py:355+) does NOT
        include these — this test documents the gap.
        """
        url = f"{BASE_URL}/api/dashboard?market=crypto&timeframe=1h"
        r = api_client.get(url, timeout=90)
        assert r.status_code == 200, r.text[:400]
        assets = r.json().get("assets") or []
        assert assets, "no assets"
        first = assets[0]
        missing = [k for k in ("entry_moderate", "entry_aggressive") if k not in first]
        assert not missing, (
            f"dashboard asset missing new v8.1.6 fields: {missing}. "
            f"AssetSignal Pydantic model needs to expose them. Got keys: {sorted(first.keys())}"
        )

    def test_dashboard_batch_crypto_and_stock_us(self, api_client):
        url = f"{BASE_URL}/api/dashboard/batch?markets=crypto,stock_us&timeframe=1h"
        r = api_client.get(url, timeout=120)
        assert r.status_code == 200, r.text[:400]
        body = r.json()
        # Batch returns {"markets": {"crypto": {...}, "stock_us": {...}}, ...}
        markets = body.get("markets") or {}
        assert "crypto" in markets and "stock_us" in markets, body
        for m in ("crypto", "stock_us"):
            block = markets[m]
            assets = block.get("assets") if isinstance(block, dict) else None
            assert assets, f"{m} has no assets"
            # New field presence on at least first asset.
            first = assets[0]
            assert "entry" in first
            assert "stop_loss" in first
            assert "take_profit" in first


# ---------------------------------------------------------------------------
# 2) Per-asset analyze — new technical + consensus fields
# ---------------------------------------------------------------------------


class TestAnalyzeShape:
    def test_btc_analyze_technical_new_fields(self, btc_analyze):
        assert "technical" in btc_analyze, btc_analyze.keys()
        t = btc_analyze["technical"]

        # Required new top-level fields on the technical block.
        for k in ("entry", "entry_moderate", "entry_aggressive",
                  "stop_loss", "take_profit", "_all_levels"):
            assert k in t, f"technical missing {k}. got keys={list(t.keys())}"

        # _all_levels must have BUY + SELL sub-dicts.
        lvl = t["_all_levels"]
        assert isinstance(lvl, dict) and "BUY" in lvl and "SELL" in lvl
        for side in ("BUY", "SELL"):
            side_lvl = lvl[side]
            for key in ("entry", "entry_moderate", "entry_aggressive",
                        "stop_loss", "take_profit"):
                assert key in side_lvl, (
                    f"_all_levels[{side}] missing {key}, got {list(side_lvl.keys())}"
                )

        # Indicator sub-block gains 4 new swing metrics.
        ind = t.get("indicators") or {}
        for k in ("avg_peak", "avg_valley", "peaks_found", "valleys_found"):
            assert k in ind, f"indicators missing {k}, got {list(ind.keys())}"

    def test_btc_analyze_consensus_new_fields(self, btc_analyze):
        assert "consensus" in btc_analyze
        c = btc_analyze["consensus"]
        assert "entry_bias" in c, f"consensus missing entry_bias, got {list(c.keys())}"
        # bias_votes is optional if all 3 AIs failed, but should be present
        # whenever the aggregate path ran (which it does when any AI succeeds).
        # In fallback path (no valid AI) the consensus dict is different, so we
        # allow missing bias_votes only in that fallback case.
        if any(m.get("ok") for m in btc_analyze.get("models", [])):
            assert "bias_votes" in c, f"consensus missing bias_votes, got {list(c.keys())}"
            assert isinstance(c["bias_votes"], dict)
            # All three bias buckets present.
            for k in ("deep", "moderate", "aggressive"):
                assert k in c["bias_votes"], c["bias_votes"]

    def test_consensus_entry_bias_valid_value(self, btc_analyze):
        c = btc_analyze["consensus"]
        assert c.get("entry_bias") in ("deep", "moderate", "aggressive"), (
            f"entry_bias must be deep/moderate/aggressive, got {c.get('entry_bias')!r}"
        )


# ---------------------------------------------------------------------------
# 3) Formula math sanity — BUY entry < price, SELL entry > price, TP anchor, SL tight
# ---------------------------------------------------------------------------


def _price_of(payload: dict) -> float:
    # Server includes top-level `price` on analyze response.
    p = payload.get("price")
    if p is None:
        p = (payload.get("technical") or {}).get("indicators", {}).get("price")
    assert p is not None, "no price found in analyze payload"
    return float(p)


class TestFormulaMath:
    def test_eth_buy_entry_below_price_and_sell_above(self, eth_analyze):
        """For a BUY signal entry must be < price (below recent valleys);
        for SELL entry must be > price (above recent peaks). This is the
        core user-requested behaviour of the deep-entry formula.
        """
        t = eth_analyze["technical"]
        price = _price_of(eth_analyze)
        atr = (t.get("indicators") or {}).get("atr") or 0.0

        # Use the deterministic _all_levels map — this is what the frontend
        # will render regardless of AI vote.
        buy_lvl = t["_all_levels"]["BUY"]
        sell_lvl = t["_all_levels"]["SELL"]

        # BUY entry: must be below current price. Allow tiny numeric noise
        # equal to 5% of ATR (fallback path may sit at price*0.95 which is
        # still < price).
        eps = max(atr * 0.05, price * 1e-6)
        assert buy_lvl["entry"] < price + eps, (
            f"BUY entry {buy_lvl['entry']} not below price {price} (ATR={atr})"
        )
        # SELL entry: above price.
        assert sell_lvl["entry"] > price - eps, (
            f"SELL entry {sell_lvl['entry']} not above price {price} (ATR={atr})"
        )

    def test_eth_tp_matches_avg_peak_valley(self, eth_analyze):
        """TP (LONG) ≈ indicators.avg_peak, TP (SHORT) ≈ indicators.avg_valley.

        The formula caps TP at (entry ± 1 ATR) so in thin-history fallback
        the TP may drift from avg_peak by up to 1 ATR — we allow that
        tolerance (either exact match to avg or within 1.5*ATR from it).
        """
        t = eth_analyze["technical"]
        ind = t["indicators"]
        atr = float(ind.get("atr") or 0.0)
        buy_tp = float(t["_all_levels"]["BUY"]["take_profit"])
        sell_tp = float(t["_all_levels"]["SELL"]["take_profit"])
        avg_peak = float(ind["avg_peak"])
        avg_valley = float(ind["avg_valley"])

        tol_long = max(atr * 1.5, avg_peak * 0.01)
        tol_short = max(atr * 1.5, avg_valley * 0.01)
        assert abs(buy_tp - avg_peak) <= tol_long, (
            f"BUY TP {buy_tp} not near avg_peak {avg_peak} (tol {tol_long}, ATR {atr})"
        )
        assert abs(sell_tp - avg_valley) <= tol_short, (
            f"SELL TP {sell_tp} not near avg_valley {avg_valley} (tol {tol_short}, ATR {atr})"
        )

    def test_eth_sl_within_tight_atr_of_entry(self, eth_analyze):
        """User asked for 'SL 0.5 ATR tighter'. The default (deep) SL is
        placed 0.5*ATR away from the deep entry. We verify |entry - SL|
        is within [0.3, 1.2] * ATR (allow tolerance for rounding / ATR≈0
        edge cases).
        """
        t = eth_analyze["technical"]
        atr = float((t.get("indicators") or {}).get("atr") or 0.0)
        if atr <= 0:
            pytest.skip("ATR is 0 — SL distance check not meaningful")

        for side in ("BUY", "SELL"):
            side_lvl = t["_all_levels"][side]
            dist = abs(float(side_lvl["entry"]) - float(side_lvl["stop_loss"]))
            ratio = dist / atr
            assert 0.3 <= ratio <= 1.2, (
                f"{side} SL distance {dist} = {ratio:.2f}*ATR, expected ~0.5"
            )


# ---------------------------------------------------------------------------
# 4) AI summary soft length check
# ---------------------------------------------------------------------------


class TestAiSummary:
    def test_consensus_summary_length_soft(self, btc_analyze):
        c = btc_analyze["consensus"]
        summary = str(c.get("summary") or "")
        # Soft — just log if outside typical range.
        length = len(summary)
        # Allow 0 (fallback), or 30..600 typical. Fail only if wildly long.
        assert length < 900, (
            f"consensus.summary too long ({length} chars); v8.1.6 asked for shorter."
        )


# ---------------------------------------------------------------------------
# 5) Regression: AAPL non-crypto path still populates new fields
# ---------------------------------------------------------------------------


class TestNonCryptoRegression:
    def test_aapl_analyze_has_new_technical_fields(self, aapl_analyze):
        t = aapl_analyze["technical"]
        for k in ("entry_moderate", "entry_aggressive", "_all_levels"):
            assert k in t, f"AAPL technical missing {k}"
        ind = t["indicators"]
        for k in ("avg_peak", "avg_valley", "peaks_found", "valleys_found"):
            assert k in ind, f"AAPL indicators missing {k}"

    def test_aapl_consensus_entry_bias(self, aapl_analyze):
        c = aapl_analyze["consensus"]
        # If any model succeeded, entry_bias must be one of the three.
        if any(m.get("ok") for m in aapl_analyze.get("models", [])):
            assert c.get("entry_bias") in ("deep", "moderate", "aggressive"), c


# ---------------------------------------------------------------------------
# 6) Regression: /api/search still returns entry/SL/TP populated
# ---------------------------------------------------------------------------


class TestSearchRegression:
    def test_search_btc_hits_have_signal_fields(self, api_client):
        url = f"{BASE_URL}/api/search?q=BTC"
        r = api_client.get(url, timeout=60)
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        hits = body.get("hits") or []
        assert len(hits) > 0, "search returned no hits for BTC"
        # At least one hit should have entry/SL/TP.
        with_signals = [
            h for h in hits
            if h.get("entry") is not None
            and h.get("stop_loss") is not None
            and h.get("take_profit") is not None
        ]
        assert with_signals, (
            "no BTC search hits populated entry/SL/TP — dashboard cards will be empty"
        )


# ---------------------------------------------------------------------------
# 7) Regression: chat validation still works + subscription health
# ---------------------------------------------------------------------------


class TestPreviousIterationRegression:
    def test_chat_send_empty_returns_validation_error(self, api_client):
        url = f"{BASE_URL}/api/chat/messages"
        r = api_client.post(url, json={"nickname": "TEST_iter21", "text": ""}, timeout=30)
        # 400 (custom text-required), 403 (entitlement), 422 (FastAPI missing device_id)
        # are all acceptable — the request must not succeed.
        assert r.status_code in (400, 403, 422), (
            f"expected validation error, got {r.status_code}: {r.text[:200]}"
        )

    def test_chat_send_missing_nickname_returns_validation_error(self, api_client):
        url = f"{BASE_URL}/api/chat/messages"
        r = api_client.post(url, json={"text": "hi"}, timeout=30)
        # FastAPI Pydantic emits 422 when required nickname/device_id fields
        # are missing; older code emitted 400. Either is a valid rejection.
        assert r.status_code in (400, 422), r.text[:200]

    def test_subscription_health_ok(self, api_client):
        url = f"{BASE_URL}/api/subscription/health"
        r = api_client.get(url, timeout=30)
        assert r.status_code == 200, r.text[:200]
        # Should not leak service-account PII.
        body_text = r.text
        for secret_marker in ("private_key", "BEGIN PRIVATE KEY", "client_email", "service-account.json"):
            assert secret_marker not in body_text, (
                f"subscription/health leaked secret marker: {secret_marker}"
            )


# ---------------------------------------------------------------------------
# Sanity: warm-up ping (runs first).
# ---------------------------------------------------------------------------


def test_zzz_warmup_and_report(api_client):
    """Diagnostic — prints key computed levels for the reviewer to eyeball."""
    r = api_client.post(
        f"{BASE_URL}/api/asset/crypto/BTC/analyze?timeframe=1h&lang=en", timeout=120
    )
    assert r.status_code == 200
    body = r.json()
    t = body["technical"]
    c = body["consensus"]
    ind = t["indicators"]
    print("\n--- v8.1.6 DIAG ---")
    print(f"price={body.get('price')} atr={ind.get('atr')} rsi={ind.get('rsi')}")
    print(f"action={t.get('action')} label={t.get('label')} conf={t.get('confidence')}")
    print(
        f"peaks_found={ind.get('peaks_found')} valleys_found={ind.get('valleys_found')} "
        f"avg_peak={ind.get('avg_peak')} avg_valley={ind.get('avg_valley')}"
    )
    print(f"entry={t.get('entry')} entry_mod={t.get('entry_moderate')} entry_agg={t.get('entry_aggressive')}")
    print(f"SL={t.get('stop_loss')} TP={t.get('take_profit')}")
    print(f"consensus.action={c.get('action')} bias={c.get('entry_bias')} votes={c.get('bias_votes')}")
    print(f"consensus.summary_len={len(str(c.get('summary') or ''))}")
    print("---")
    time.sleep(0.1)
