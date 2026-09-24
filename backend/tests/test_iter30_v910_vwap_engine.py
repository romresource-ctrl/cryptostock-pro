"""
v9.1.0 — VWAP Session Engine routing by trader profile.

Covers:
- Profile routing: scalper→SCALPER, day→INTRADAY, swing→SWING (VWAP engine),
  longterm→Confluence (NO vwap_engine key).
- Schema completeness on VWAP path (action/label/confidence/reasons; HOLD →
  entry/sl/tp all null; BUY/SELL → non-null floats with sane R:R ±15%).
- Dashboard batch ↔ asset chart sync for profile=scalper and profile=swing.
- Stock path (BBCA profile=day → INTRADAY, percentage levels near price).
- No-volume fallback (forex EUR/USD zero volume → confluence, no 500).
- Regressions: search TSLA, dashboard stock_us, dashboard crypto longterm,
  subscription/health.
"""
import os
import time

import pytest
import requests

BASE_URL = os.environ.get(
    "EXPO_PUBLIC_BACKEND_URL",
    "https://cryptostock-pro.preview.emergentagent.com",
).rstrip("/")
assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL not set"

CHART = "/api/asset/{market}/{symbol}/chart?timeframe=1h&profile={profile}"


@pytest.fixture(scope="session")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def _get_chart(api, market, symbol, profile, timeframe="1h"):
    r = api.get(
        f"{BASE_URL}/api/asset/{market}/{symbol}/chart",
        params={"timeframe": timeframe, "profile": profile},
        timeout=90,
    )
    return r


# ---------------------------------------------------------------------------
# 1. PROFILE ROUTING — VWAP engine selection
# ---------------------------------------------------------------------------
class TestProfileRouting:
    """scalper→SCALPER, day→INTRADAY, swing→SWING; longterm→no vwap_engine"""

    @pytest.mark.parametrize(
        "profile,engine",
        [("scalper", "SCALPER"), ("day", "INTRADAY"), ("swing", "SWING")],
    )
    def test_vwap_engine_routing(self, api, profile, engine):
        r = _get_chart(api, "crypto", "BTC", profile)
        assert r.status_code == 200, f"{profile}: HTTP {r.status_code}"
        sig = r.json()["signal"]
        ind = sig["indicators"]
        assert ind.get("vwap_engine") == engine, (
            f"profile={profile} expected engine {engine}, got {ind.get('vwap_engine')}"
        )
        # VWAP numeric and near price (within 10%)
        vwap = ind.get("vwap")
        price = ind.get("price")
        assert isinstance(vwap, (int, float)) and vwap > 0, "vwap missing/non-numeric"
        assert isinstance(price, (int, float)) and price > 0
        assert abs(vwap - price) / price < 0.10, f"vwap {vwap} too far from price {price}"
        # price_dev_pct numeric, box levels present
        assert isinstance(ind.get("price_dev_pct"), (int, float)), "price_dev_pct missing"
        assert ind.get("box_high") is not None and ind.get("box_low") is not None
        assert ind["box_high"] >= ind["box_low"], "box_high < box_low"

    def test_longterm_uses_confluence_no_vwap_engine(self, api):
        r = _get_chart(api, "crypto", "BTC", "longterm")
        assert r.status_code == 200
        ind = r.json()["signal"]["indicators"]
        assert "vwap_engine" not in ind, (
            f"longterm must use confluence engine, got vwap_engine={ind.get('vwap_engine')}"
        )

    def test_routing_on_second_symbol(self, api):
        """Sanity: routing works on ETH too (not BTC-specific)."""
        r = _get_chart(api, "crypto", "ETH", "swing")
        assert r.status_code == 200
        assert r.json()["signal"]["indicators"].get("vwap_engine") == "SWING"


# ---------------------------------------------------------------------------
# 2. SCHEMA COMPLETENESS on the VWAP path
# ---------------------------------------------------------------------------
class TestVwapSchema:
    CORE = ("action", "label", "confidence", "reasons")
    LEVELS = ("entry", "stop_loss", "take_profit")

    def _check(self, sig, ctx):
        for k in self.CORE:
            assert k in sig, f"{ctx}: missing key {k}"
        assert sig["action"] in ("BUY", "SELL", "HOLD"), f"{ctx}: bad action {sig['action']}"
        assert isinstance(sig["reasons"], list) and len(sig["reasons"]) > 0
        assert isinstance(sig["confidence"], int)
        if sig["action"] == "HOLD":
            for k in self.LEVELS:
                assert sig.get(k) is None, f"{ctx}: HOLD but {k}={sig.get(k)}"
        else:
            entry, sl, tp = (sig.get(k) for k in self.LEVELS)
            for name, v in (("entry", entry), ("stop_loss", sl), ("take_profit", tp)):
                assert isinstance(v, (int, float)) and v > 0, f"{ctx}: {name} not a positive float"
            risk = abs(entry - sl)
            reward = abs(tp - entry)
            assert risk > 0, f"{ctx}: zero risk entry==sl"
            rr = reward / risk
            assert 0.85 <= rr <= 1.15, f"{ctx}: TP1 R:R={rr:.3f} outside ±15% of 1R"
            # direction sanity
            if sig["action"] == "BUY":
                assert sl < entry < tp, f"{ctx}: BUY levels direction wrong"
            else:
                assert tp < entry < sl, f"{ctx}: SELL levels direction wrong"

    @pytest.mark.parametrize("profile", ["scalper", "day", "swing"])
    def test_chart_schema(self, api, profile):
        r = _get_chart(api, "crypto", "BTC", profile)
        assert r.status_code == 200
        sig = r.json()["signal"]
        assert sig["indicators"].get("vwap_engine") is not None
        self._check(sig, f"BTC/{profile}")

    def test_batch_schema_and_rr(self, api):
        """All BUY/SELL signals on the scalper batch must have sane levels/R:R."""
        r = api.get(
            f"{BASE_URL}/api/dashboard/batch",
            params={"markets": "crypto", "timeframe": "1h", "profile": "scalper"},
            timeout=120,
        )
        assert r.status_code == 200
        assets = r.json()["markets"]["crypto"]["assets"]
        checked = 0
        for a in assets:
            if a["action"] in ("BUY", "SELL"):
                self._check(a, f"batch/{a['symbol']}")
                checked += 1
            else:
                assert a.get("entry") is None and a.get("stop_loss") is None, (
                    f"batch/{a['symbol']}: HOLD with levels"
                )
        assert len(assets) > 0
        print(f"checked {checked} actionable signals in batch")


# ---------------------------------------------------------------------------
# 3. DASHBOARD ↔ DETAIL SYNC
# ---------------------------------------------------------------------------
class TestDashboardDetailSync:
    @pytest.mark.parametrize("profile", ["scalper", "swing"])
    def test_batch_vs_chart_sync(self, api, profile):
        r = api.get(
            f"{BASE_URL}/api/dashboard/batch",
            params={"markets": "crypto", "timeframe": "1h", "profile": profile},
            timeout=120,
        )
        assert r.status_code == 200
        assets = r.json()["markets"]["crypto"]["assets"][:6]
        mismatches = []
        for a in assets:
            sym = a["symbol"]
            rc = _get_chart(api, "crypto", sym, profile)
            assert rc.status_code == 200, f"{sym}: chart HTTP {rc.status_code}"
            cs = rc.json()["signal"]
            for f in ("action", "label", "confidence"):
                if a[f] != cs[f]:
                    mismatches.append(f"{sym}.{f}: batch={a[f]} chart={cs[f]}")
        assert not mismatches, f"profile={profile} sync mismatches: {mismatches}"


# ---------------------------------------------------------------------------
# 4. STOCK PATH (stocklike percentage levels)
# ---------------------------------------------------------------------------
class TestStockPath:
    def test_bbca_day_intraday_engine(self, api):
        r = _get_chart(api, "stock_id", "BBCA", "day")
        assert r.status_code == 200, f"HTTP {r.status_code}"
        sig = r.json()["signal"]
        ind = sig["indicators"]
        assert ind.get("vwap_engine") == "INTRADAY"
        if sig["action"] in ("BUY", "SELL"):
            price = ind["price"]
            entry = sig["entry"]
            # stocklike percentage levels — entry must be near price (<5% away)
            assert abs(entry - price) / price < 0.05, (
                f"entry {entry} too far from price {price}"
            )


# ---------------------------------------------------------------------------
# 5. NO-VOLUME FALLBACK
# ---------------------------------------------------------------------------
class TestNoVolumeFallback:
    def test_forex_zero_volume_falls_back_to_confluence(self, api):
        """EUR/USD from Yahoo has volume=0 → VWAP path returns None →
        confluence engine runs → no vwap_engine, no 500."""
        r = _get_chart(api, "forex", "EUR-USD", "scalper")
        assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:200]}"
        sig = r.json()["signal"]
        assert sig["action"] in ("BUY", "SELL", "HOLD")
        assert sig["indicators"].get("vwap_engine") is None, (
            "zero-volume forex must NOT use VWAP engine"
        )


# ---------------------------------------------------------------------------
# 6. REGRESSIONS
# ---------------------------------------------------------------------------
class TestRegressions:
    def test_search_tsla(self, api):
        r = api.get(f"{BASE_URL}/api/search", params={"q": "TSLA"}, timeout=60)
        assert r.status_code == 200
        hits = r.json().get("hits", [])
        assert any(h["symbol"] == "TSLA" and h["market"] == "stock_us" for h in hits), (
            f"TSLA stock_us hit missing: {[h.get('symbol') for h in hits]}"
        )

    def test_dashboard_stock_us(self, api):
        r = api.get(f"{BASE_URL}/api/dashboard", params={"market": "stock_us"}, timeout=120)
        assert r.status_code == 200
        assert len(r.json().get("assets", [])) > 0

    def test_dashboard_crypto_longterm(self, api):
        r = api.get(
            f"{BASE_URL}/api/dashboard",
            params={"market": "crypto", "profile": "longterm"},
            timeout=120,
        )
        assert r.status_code == 200
        assets = r.json().get("assets", [])
        assert len(assets) > 0
        # longterm → confluence → no vwap_engine on dashboard either
        for a in assets[:5]:
            assert a.get("indicators", {}).get("vwap_engine") is None, (
                f"{a['symbol']}: longterm dashboard should not expose vwap_engine"
            )

    def test_subscription_health(self, api):
        r = api.get(f"{BASE_URL}/api/subscription/health", timeout=30)
        assert r.status_code == 200
