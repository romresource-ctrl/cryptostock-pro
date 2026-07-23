"""Iteration 9 backend tests — v3.0.1 verification.

Covers:
- New markets: gold_silver, commodity, forex, world_stocks (+ regression).
- New crypto timeframes: 1m, 5m, 7d, 30d (+ regression 1h).
- /api/whoami (5 fields).
- Full auth flow: generate-code (lifetime) -> verify -> DELETE cleanup.
"""
from __future__ import annotations

import os
import time
import uuid

import pytest
import requests

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
ADMIN_TOKEN = "kevin-admin-2026-do-not-share-xyz789"


@pytest.fixture(scope="module")
def api_client() -> requests.Session:
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def _get_dashboard(client: requests.Session, market: str, tf: str = "1h"):
    url = f"{BASE_URL}/api/dashboard?market={market}&timeframe={tf}&full=true"
    r = client.get(url, timeout=90)
    return r


# ---------- New markets ----------
class TestNewMarkets:
    def test_gold_silver(self, api_client):
        r = _get_dashboard(api_client, "gold_silver")
        assert r.status_code == 200, r.text[:300]
        assets = r.json().get("assets") or []
        assert len(assets) >= 3, f"expected >=3 gold/silver assets, got {len(assets)}"
        symbols = {a["symbol"] for a in assets}
        expected_pool = {"XAU/USD", "XAG/USD", "XPT/USD", "XPD/USD"}
        assert symbols & expected_pool, f"no expected symbol among {symbols}"
        for a in assets:
            assert a.get("price", 0) > 0, f"{a['symbol']} price not > 0: {a.get('price')}"
        print(f"[gold_silver] {len(assets)} assets: {symbols}")

    def test_commodity(self, api_client):
        r = _get_dashboard(api_client, "commodity")
        assert r.status_code == 200, r.text[:300]
        assets = r.json().get("assets") or []
        symbols = {a["symbol"] for a in assets}
        assert "WTI" in symbols, f"WTI missing; got {symbols}"
        assert "BRENT" in symbols, f"BRENT missing; got {symbols}"
        for a in assets:
            if a["symbol"] in ("WTI", "BRENT"):
                assert a.get("price", 0) > 0
        print(f"[commodity] symbols={symbols}")

    def test_forex(self, api_client):
        r = _get_dashboard(api_client, "forex")
        assert r.status_code == 200, r.text[:300]
        assets = r.json().get("assets") or []
        assert len(assets) >= 6, f"expected >=6 forex pairs, got {len(assets)}"
        by_sym = {a["symbol"]: a for a in assets}
        if "EUR/USD" in by_sym:
            p = by_sym["EUR/USD"].get("price", 0)
            assert 0.8 < p < 2.0, f"EUR/USD price out of realistic band: {p}"
        print(f"[forex] {len(assets)} pairs, EUR/USD={by_sym.get('EUR/USD', {}).get('price')}")

    def test_world_stocks(self, api_client):
        r = _get_dashboard(api_client, "world_stocks")
        assert r.status_code == 200, r.text[:300]
        assets = r.json().get("assets") or []
        assert len(assets) >= 30, f"expected >=30 world_stocks, got {len(assets)}"
        symbols = {a["symbol"] for a in assets}
        indices = {"US30", "NAS100", "SPX500", "JP225", "HK50", "GER40", "UK100", "IDX30"}
        assert symbols & indices, f"no expected index symbol in {sorted(symbols)[:20]}"
        print(f"[world_stocks] {len(assets)} items; indices present={symbols & indices}")


# ---------- New crypto timeframes ----------
class TestNewTimeframes:
    @pytest.mark.parametrize("tf", ["5m", "1m", "7d", "30d"])
    def test_crypto_new_timeframes(self, api_client, tf):
        r = _get_dashboard(api_client, "crypto", tf=tf)
        assert r.status_code == 200, f"tf={tf} failed: {r.status_code} {r.text[:300]}"
        assets = r.json().get("assets") or []
        assert len(assets) > 0, f"tf={tf} empty assets"


# ---------- Regression on old markets/TFs ----------
class TestRegressionMarkets:
    @pytest.mark.parametrize("market", ["crypto", "stock_id", "etf", "stock_us"])
    def test_regression_markets(self, api_client, market):
        r = _get_dashboard(api_client, market, tf="1h")
        assert r.status_code == 200, f"{market} failed: {r.status_code} {r.text[:300]}"
        assets = r.json().get("assets") or []
        assert isinstance(assets, list) and len(assets) > 0, f"{market} empty assets"


# ---------- whoami ----------
class TestWhoami:
    def test_whoami_five_fields(self, api_client):
        r = api_client.get(f"{BASE_URL}/api/whoami", timeout=30)
        assert r.status_code == 200
        body = r.json()
        for k in ("backend_origin", "db_name", "codes_count", "admin_tool_url", "server_time"):
            assert k in body, f"missing field {k}; body={body}"


# ---------- Full auth flow ----------
class TestAuthFlow:
    def test_generate_verify_and_cleanup(self, api_client):
        email = f"TEST_iter9_{uuid.uuid4().hex[:8]}@example.com"
        admin_headers = {"X-Admin-Token": ADMIN_TOKEN}

        # 1) generate-code (lifetime)
        r = api_client.post(
            f"{BASE_URL}/api/admin/generate-code",
            json={"email": email, "duration": "lifetime"},
            headers=admin_headers,
            timeout=30,
        )
        assert r.status_code == 200, f"generate-code failed: {r.status_code} {r.text[:400]}"
        gen = r.json()
        code = gen.get("code") or gen.get("unlock_code")
        assert code, f"no code in response: {gen}"
        print(f"[auth] generated code={code} for {email}")

        # 2) verify
        r2 = api_client.post(
            f"{BASE_URL}/api/auth/verify",
            json={"email": email, "code": code, "device_id": "test-device-iter9",
                  "device_name": "pytest-iter9"},
            timeout=30,
        )
        assert r2.status_code == 200, f"verify failed: {r2.status_code} {r2.text[:300]}"
        v = r2.json()
        assert v.get("ok") is True or v.get("valid") is True or v.get("success") is True, (
            f"verify not ok: {v}"
        )

        # 3) cleanup — DELETE
        r3 = api_client.delete(
            f"{BASE_URL}/api/admin/users/{email}",
            headers=admin_headers,
            timeout=30,
        )
        assert r3.status_code in (200, 204), f"delete failed: {r3.status_code} {r3.text[:300]}"
