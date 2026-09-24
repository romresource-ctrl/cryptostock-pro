# v9.2.0 — Master All-in-One Trading Engine (VWAP + John Wick + Power of Tower)
# Tests: VWAP engine routing by profile, indicator fields, HOLD/BUY-SELL level rules,
# dashboard/batch vs chart sync, and regressions (search TSLA, stock_id dashboard, BBCA chart).
import os

import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    pytest.skip("EXPO_PUBLIC_BACKEND_URL not set", allow_module_level=True)

API = f"{BASE_URL}/api"


@pytest.fixture
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ---------------- VWAP engine routing + schema ----------------

VWAP_PROFILES = [("scalper", "SCALPER"), ("day", "INTRADAY"), ("swing", "SWING")]


@pytest.mark.parametrize("profile,engine", VWAP_PROFILES)
def test_chart_vwap_engine_schema(client, profile, engine):
    r = client.get(f"{API}/asset/crypto/BTC/chart", params={"timeframe": "1h", "profile": profile}, timeout=60)
    assert r.status_code == 200, f"{profile} chart status={r.status_code} body={r.text[:300]}"
    data = r.json()
    sig = data.get("signal") or data
    ind = sig.get("indicators") or {}
    assert ind.get("vwap_engine") == engine, f"expected vwap_engine={engine}, got {ind.get('vwap_engine')}"
    assert isinstance(ind.get("vwap"), (int, float)), f"vwap not float: {ind.get('vwap')!r}"
    assert isinstance(ind.get("price_dev_pct"), (int, float)), f"price_dev_pct not float: {ind.get('price_dev_pct')!r}"
    assert isinstance(ind.get("box_high"), (int, float)), "box_high missing/not float"
    assert isinstance(ind.get("box_low"), (int, float)), "box_low missing/not float"
    assert isinstance(ind.get("john_wick"), bool), f"john_wick not bool: {ind.get('john_wick')!r}"
    assert isinstance(ind.get("power_of_tower"), bool), f"power_of_tower not bool: {ind.get('power_of_tower')!r}"
    # Level rule: HOLD → entry/sl/tp all null; BUY/SELL → all non-null
    action = sig.get("action")
    if action == "HOLD":
        assert sig.get("entry") is None, f"HOLD entry must be null, got {sig.get('entry')}"
        assert sig.get("stop_loss") is None, f"HOLD stop_loss must be null, got {sig.get('stop_loss')}"
        assert sig.get("take_profit") is None, f"HOLD take_profit must be null, got {sig.get('take_profit')}"
    else:
        assert action in ("BUY", "SELL"), f"unexpected action {action}"
        assert sig.get("entry") is not None, f"{action} entry null"
        assert sig.get("stop_loss") is not None, f"{action} stop_loss null"
        assert sig.get("take_profit") is not None, f"{action} take_profit null"


def test_longterm_no_vwap_engine(client):
    r = client.get(f"{API}/asset/crypto/BTC/chart", params={"timeframe": "1h", "profile": "longterm"}, timeout=60)
    assert r.status_code == 200
    data = r.json()
    sig = data.get("signal") or data
    ind = sig.get("indicators") or {}
    assert "vwap_engine" not in ind, f"longterm should use Confluence path, found vwap_engine={ind.get('vwap_engine')}"


# ---------------- Dashboard/batch vs chart sync (profile=day) ----------------

SYNC_SYMBOLS = ["BTC", "ETH", "SOL"]


def test_batch_vs_chart_sync(client):
    r = client.get(f"{API}/dashboard/batch", params={"markets": "crypto", "profile": "day"}, timeout=120)
    assert r.status_code == 200, f"batch status={r.status_code}"
    batch = r.json()
    assets = (batch.get("markets") or {}).get("crypto", {}).get("assets") or []
    by_sym = {a.get("symbol"): a for a in assets}
    for sym in SYNC_SYMBOLS:
        assert sym in by_sym, f"{sym} missing from batch crypto assets: {list(by_sym)[:10]}"
        b = by_sym[sym]
        rc = client.get(f"{API}/asset/crypto/{sym}/chart", params={"profile": "day"}, timeout=60)
        assert rc.status_code == 200, f"{sym} chart status={rc.status_code}"
        sig = rc.json().get("signal") or rc.json()
        for field in ("action", "label", "confidence"):
            assert b.get(field) == sig.get(field), (
                f"{sym} mismatch {field}: batch={b.get(field)!r} chart={sig.get(field)!r}"
            )


# ---------------- Regressions ----------------

def test_search_tsla_regression(client):
    r = client.get(f"{API}/search", params={"q": "TSLA"}, timeout=60)
    assert r.status_code == 200, f"search status={r.status_code}"
    hits = r.json()
    results = hits.get("hits", hits.get("results", hits)) if isinstance(hits, dict) else hits
    markets = [h.get("market") for h in results if isinstance(h, dict)]
    syms = [h.get("symbol") for h in results if isinstance(h, dict)]
    assert "stock_us" in markets, f"no stock_us hit for TSLA: {results[:5]}"
    assert any("TSLA" in (s or "") for s in syms), f"no TSLA symbol hit: {syms[:10]}"


def test_dashboard_stock_id(client):
    r = client.get(f"{API}/dashboard", params={"market": "stock_id"}, timeout=120)
    assert r.status_code == 200, f"status={r.status_code}"
    data = r.json()
    assets = data.get("assets") or data.get("signals") or []
    assert len(assets) > 0, "stock_id dashboard returned no assets"


def test_bbca_chart_intraday(client):
    r = client.get(f"{API}/asset/stock_id/BBCA/chart", params={"profile": "day"}, timeout=60)
    assert r.status_code == 200, f"status={r.status_code} body={r.text[:300]}"
    data = r.json()
    sig = data.get("signal") or data
    ind = sig.get("indicators") or {}
    assert ind.get("vwap_engine") == "INTRADAY", f"expected INTRADAY, got {ind.get('vwap_engine')}"
    price = ind.get("price")
    # Sane percentage levels: entry/sl/tp within ±20% of price when present
    for field in ("entry", "stop_loss", "take_profit"):
        v = sig.get(field)
        if v is not None and price:
            assert 0.8 * price <= v <= 1.2 * price, f"{field}={v} not within ±20% of price={price}"
