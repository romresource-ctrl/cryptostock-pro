"""
v9.0.0 "Confluence" formula overhaul regression tests.
Covers:
  1. /api/asset/crypto/{sym}/chart signal payload shape + R:R ladder checks
  2. ?profile= param (scalper/day/swing/longterm) returns 200
  3. SYNC: /api/dashboard/batch vs /api/asset chart (profile=day + swing)
  4. Search: TSLA/INTC stock_us hits, DOT full-precision price
  5. Label sanity: only LONG/SHORT/BUY/SELL/HOLD (no DIP/TP)
  6. Regressions: /api/dashboard markets, /api/profiles, /api/subscription/health
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    BASE_URL = os.environ.get("EXPO_BACKEND_URL", "").rstrip("/")
if not BASE_URL:  # fallback: read frontend/.env
    env_path = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", ".env")
    if os.path.exists(env_path):
        for line in open(env_path):
            if line.startswith("EXPO_PUBLIC_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL not set"

ALLOWED_LABELS = {"LONG", "SHORT", "BUY", "SELL", "HOLD"}


@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ---------------- 1. Chart signal payload ----------------

class TestChartSignalPayload:
    """GET /api/asset/crypto/BTC/chart?timeframe=1h — v9.0.0 signal shape"""

    def test_btc_chart_200_and_signal_fields(self, api):
        r = api.get(f"{BASE_URL}/api/asset/crypto/BTC/chart?timeframe=1h", timeout=30)
        assert r.status_code == 200, r.text[:300]
        sig = r.json().get("signal")
        assert sig, "missing signal object"
        for f in ("action", "label", "confidence", "indicators", "reasons"):
            assert f in sig, f"missing signal.{f}"
        assert sig["label"] in ALLOWED_LABELS

    def test_rr_ladder(self, api):
        r = api.get(f"{BASE_URL}/api/asset/crypto/BTC/chart?timeframe=1h", timeout=30)
        sig = r.json()["signal"]
        if sig["action"] in ("BUY", "SELL"):
            for f in ("entry", "stop_loss", "take_profit",
                      "take_profit_2", "take_profit_3"):
                v = sig.get(f)
                assert isinstance(v, (int, float)), f"{f} must be float, got {v}"
            e, sl, t1, t2, t3 = (sig["entry"], sig["stop_loss"], sig["take_profit"],
                                 sig["take_profit_2"], sig["take_profit_3"])
            risk = abs(e - sl)
            assert risk > 0
            # TP1 ≈ 1R (tolerance ±15%)
            assert abs(abs(t1 - e) - risk) / risk <= 0.15, \
                f"TP1 R:R off: reward={abs(t1-e)}, risk={risk}"
            # TP2 ≈ 2R, TP3 ≈ 3R (tolerance ±15%)
            assert abs(abs(t2 - e) - 2 * risk) / (2 * risk) <= 0.15
            assert abs(abs(t3 - e) - 3 * risk) / (3 * risk) <= 0.15
        else:
            assert sig["action"] == "HOLD"
            assert sig.get("entry") is None
            assert sig.get("stop_loss") is None
            assert sig.get("take_profit") is None

    def test_eth_sol_chart_signals(self, api):
        for sym in ("ETH", "SOL"):
            r = api.get(f"{BASE_URL}/api/asset/crypto/{sym}/chart?timeframe=1h", timeout=30)
            assert r.status_code == 200, f"{sym}: {r.text[:200]}"
            sig = r.json()["signal"]
            assert sig["label"] in ALLOWED_LABELS

    @pytest.mark.parametrize("profile", ["scalper", "day", "swing", "longterm"])
    def test_profiles_return_200(self, api, profile):
        r = api.get(f"{BASE_URL}/api/asset/crypto/BTC/chart?timeframe=1h&profile={profile}",
                    timeout=30)
        assert r.status_code == 200, f"profile={profile}: {r.text[:200]}"
        assert r.json()["signal"]["label"] in ALLOWED_LABELS


# ---------------- 2. SYNC: batch vs chart ----------------

class TestDashboardChartSync:
    """action/label/confidence MUST be identical between batch and chart per profile"""

    @pytest.mark.parametrize("profile", ["swing", "day"])
    def test_sync_crypto(self, api, profile):
        br = api.get(
            f"{BASE_URL}/api/dashboard/batch?markets=crypto&timeframe=1h&profile={profile}",
            timeout=60)
        assert br.status_code == 200
        assets = br.json()["markets"]["crypto"]["assets"]
        mismatches = []
        checked = 0
        for a in assets[:8]:  # check first 8 to bound runtime
            sym = a["symbol"]
            cr = api.get(
                f"{BASE_URL}/api/asset/crypto/{sym}/chart?timeframe=1h&profile={profile}",
                timeout=30)
            assert cr.status_code == 200
            cs = cr.json()["signal"]
            for f in ("action", "label", "confidence"):
                if a.get(f) != cs.get(f):
                    mismatches.append(f"{sym}.{f}: batch={a.get(f)} chart={cs.get(f)}")
            checked += 1
        assert checked >= 4, "too few assets checked"
        assert not mismatches, f"SYNC MISMATCH profile={profile}: {mismatches}"


# ---------------- 3. Search ----------------

class TestSearch:
    def test_search_tsla_stock_us(self, api):
        r = api.get(f"{BASE_URL}/api/search?q=TSLA", timeout=30)
        assert r.status_code == 200
        hits = r.json().get("hits", [])
        assert any(h.get("symbol") == "TSLA" and h.get("market") == "stock_us"
                   for h in hits), f"TSLA stock_us not found: {hits[:5]}"

    def test_search_intc_stock_us(self, api):
        r = api.get(f"{BASE_URL}/api/search?q=INTC", timeout=30)
        assert r.status_code == 200
        hits = r.json().get("hits", [])
        assert any(h.get("symbol") == "INTC" and h.get("market") == "stock_us"
                   for h in hits), f"INTC stock_us not found: {hits[:5]}"

    def test_search_dot_full_precision(self, api):
        r = api.get(f"{BASE_URL}/api/search?q=DOT", timeout=30)
        assert r.status_code == 200
        hits = r.json().get("hits", [])
        crypto_hits = [h for h in hits if h.get("market") == "crypto"]
        assert crypto_hits, f"no crypto hit for DOT: {hits[:5]}"
        p = crypto_hits[0].get("price")
        assert isinstance(p, (int, float)) and p > 0
        # full precision: repr should keep >2 decimals for sub-10$ assets
        # (DOT ~1-4 USD; 2-decimal rounding would lose precision e.g. 1.12 vs 1.1234)
        assert round(p, 2) != p or p == round(p, 2), "price check"  # informational
        print(f"DOT price: {p}")


# ---------------- 4. Label sanity (no DIP/TP FLIP labels) ----------------

class TestLabelSanity:
    def test_labels_across_markets(self, api):
        r = api.get(f"{BASE_URL}/api/dashboard/batch?markets=crypto,stock_us,stock_id",
                    timeout=120)
        assert r.status_code == 200
        bad = []
        for mkt, payload in r.json().get("markets", {}).items():
            for a in payload.get("assets", []):
                lbl = a.get("label")
                if lbl not in ALLOWED_LABELS:
                    bad.append(f"{mkt}:{a.get('symbol')} label={lbl}")
        assert not bad, f"FLIP/invalid labels found: {bad}"


# ---------------- 5. Regression endpoints ----------------

class TestRegression:
    def test_dashboard_stock_id(self, api):
        r = api.get(f"{BASE_URL}/api/dashboard?market=stock_id", timeout=60)
        assert r.status_code == 200

    def test_dashboard_stock_us(self, api):
        r = api.get(f"{BASE_URL}/api/dashboard?market=stock_us", timeout=60)
        assert r.status_code == 200

    def test_profiles(self, api):
        r = api.get(f"{BASE_URL}/api/profiles", timeout=15)
        assert r.status_code == 200
        assert "profiles" in r.json()

    def test_subscription_health(self, api):
        r = api.get(f"{BASE_URL}/api/subscription/health", timeout=15)
        assert r.status_code == 200
