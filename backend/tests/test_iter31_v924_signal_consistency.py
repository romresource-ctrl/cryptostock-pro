"""v9.2.4 — Iteration 31: end-to-end signal consistency regression.

Covers:
  - Dashboard vs detail chart consistency (label/confidence/levels) at TF 1h
    for crypto assets (the original user complaint: dashboard LONG vs
    detail SIDEWAYS).
  - /api/ai-suggestions premium gating (403 without entitlement,
    200 with premium device id) and engine routing per profile.
  - KNOWN ISSUE documented: commodity/WTI dashboard (Yahoo spark batch)
    vs chart (Yahoo v8 chart) Entry/SL/TP drift while label/conf match.

Run: pytest /app/backend/tests/test_iter31_v924_signal_consistency.py -v
"""
import os

import pytest
import requests

# Resolve public base URL from frontend/.env (no hardcoded defaults)
_env: dict[str, str] = {}
with open("/app/frontend/.env") as fh:
    for line in fh:
        if "=" in line:
            k, v = line.strip().split("=", 1)
            _env[k] = v
BASE_URL = (_env.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_PUBLIC_BACKEND_URL")).rstrip("/")
PREMIUM_DEVICE = "web:aitest-e2e-001"  # lifetime unlock_codes row (not revoked)


@pytest.fixture(scope="module")
def api() -> requests.Session:
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def _dash_asset(api: requests.Session, market: str, symbol: str, profile: str | None = None) -> dict:
    q = f"&profile={profile}" if profile else ""
    r = api.get(f"{BASE_URL}/api/dashboard?market={market}&timeframe=1h{q}", timeout=120)
    assert r.status_code == 200, f"dashboard {market} -> {r.status_code}"
    hit = next((a for a in r.json()["assets"] if a["symbol"].upper() == symbol.replace("-", "/").upper()), None)
    assert hit, f"{symbol} not in dashboard {market}"
    return hit


def _chart_signal(api: requests.Session, market: str, symbol: str, profile: str | None = None) -> dict:
    q = f"&profile={profile}" if profile else ""
    r = api.get(f"{BASE_URL}/api/asset/{market}/{symbol}/chart?timeframe=1h{q}", timeout=120)
    assert r.status_code == 200, f"chart {market}/{symbol} -> {r.status_code}"
    return r.json()["signal"]


class TestDashboardVsDetailConsistency:
    """Core user complaint: dashboard card signal must equal detail-page signal (TF 1h)."""

    @pytest.mark.parametrize("symbol", ["BTC", "ETH", "SUI"])
    def test_crypto_label_conf_levels_match(self, api, symbol):
        dash = _dash_asset(api, "crypto", symbol)
        sig = _chart_signal(api, "crypto", symbol)
        assert dash["label"] == sig["label"], f"{symbol} label {dash['label']} vs {sig['label']}"
        assert dash["action"] == sig["action"]
        assert dash["confidence"] == sig["confidence"]
        for k in ("entry", "stop_loss", "take_profit"):
            assert dash[k] == sig[k], f"{symbol} {k}: dash={dash[k]} chart={sig[k]}"

    @pytest.mark.parametrize("profile", ["scalper", "day", "swing"])
    def test_crypto_profile_consistency(self, api, profile):
        dash = _dash_asset(api, "crypto", "BTC", profile)
        sig = _chart_signal(api, "crypto", "BTC", profile)
        assert dash["label"] == sig["label"]
        assert dash["confidence"] == sig["confidence"]
        assert dash["entry"] == sig["entry"] and dash["stop_loss"] == sig["stop_loss"]

    def test_commodity_wti_label_conf_match(self, api):
        """WTI: label/confidence MUST match (direction consistency)."""
        dash = _dash_asset(api, "commodity", "WTI")
        sig = _chart_signal(api, "commodity", "WTI")
        assert dash["label"] == sig["label"]
        assert dash["confidence"] == sig["confidence"]

    def test_commodity_wti_levels_exact_match(self, api):
        """KNOWN DRIFT: dashboard uses Yahoo spark batch, chart uses Yahoo v8
        chart — last price differs (89.97 vs 89.88 observed) so ATR-derived
        Entry/SL/TP differ (~0.1%). This test encodes the DESIRED behavior
        and currently FAILS until both paths share one snapshot source."""
        dash = _dash_asset(api, "commodity", "WTI")
        sig = _chart_signal(api, "commodity", "WTI")
        for k in ("entry", "stop_loss", "take_profit"):
            assert dash[k] == sig[k], f"WTI {k}: dash={dash[k]} chart={sig[k]}"


class TestAISuggestionsGating:
    """Premium gate + engine routing for /api/ai-suggestions."""

    def test_forbidden_without_device(self, api):
        r = api.get(f"{BASE_URL}/api/ai-suggestions?market=crypto&timeframe=1h&profile=scalper", timeout=60)
        assert r.status_code == 403

    def test_forbidden_with_unknown_device(self, api):
        r = api.get(f"{BASE_URL}/api/ai-suggestions?market=crypto&timeframe=1h&profile=scalper&device_id=web:nonexistent-xyz", timeout=60)
        assert r.status_code == 403

    def test_premium_device_ok_and_engine(self, api):
        r = api.get(
            f"{BASE_URL}/api/ai-suggestions?market=stock_us&timeframe=1h&profile=scalper&device_id={PREMIUM_DEVICE}",
            timeout=180,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["engine"] == "VWAP-SCALPER"
        assert isinstance(body["suggestions"], list)

    def test_confluence_engine_without_profile(self, api):
        r = api.get(
            f"{BASE_URL}/api/ai-suggestions?market=crypto&timeframe=1h&device_id={PREMIUM_DEVICE}",
            timeout=180,
        )
        assert r.status_code == 200
        assert r.json()["engine"] == "CONFLUENCE"
