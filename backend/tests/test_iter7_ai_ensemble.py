"""Iteration 7 backend tests — 5-model AI ensemble upgrade validation.

Verifies:
  1. POST /api/asset/crypto/{symbol}/analyze returns 5 models with expected labels.
  2. POST /api/asset/stock_id/{symbol}/analyze returns 5 models with expected labels.
  3. Regression: /api/whoami, /api/dashboard, admin generate/verify/cleanup flow.
"""
from __future__ import annotations

import os
import time
import uuid

import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://cryptostock-pro.preview.emergentagent.com").rstrip("/")
ADMIN_TOKEN = "kevin-admin-2026-do-not-share-xyz789"

EXPECTED_LABELS = {
    "Claude Fable 5",
    "Claude Opus 4.8",
    "Claude Sonnet 4.6",
    "GPT-5.5",
    "Gemini 3.1 Pro",
}


@pytest.fixture(scope="module")
def api_client() -> requests.Session:
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json", "X-App-Version": "2.1.6"})
    return s


# ---------- helpers ----------

def _pick_symbol(api_client: requests.Session, market: str) -> str:
    url = f"{BASE_URL}/api/dashboard?market={market}&timeframe=1h&full=true"
    if market == "crypto":
        url += "&sort=premium"
    r = api_client.get(url, timeout=60)
    assert r.status_code == 200, f"dashboard {market} failed: {r.status_code} {r.text[:200]}"
    data = r.json()
    items = data.get("assets") or data.get("items") or []
    assert items, f"no items returned for market={market}: keys={list(data.keys())}"
    return items[0]["symbol"]


# ---------- 1) AI ensemble on crypto ----------

class TestAIEnsembleCrypto:
    def test_analyze_crypto_returns_5_models(self, api_client):
        symbol = _pick_symbol(api_client, "crypto")
        print(f"[crypto] Using symbol: {symbol}")

        t0 = time.time()
        r = api_client.post(
            f"{BASE_URL}/api/asset/crypto/{symbol}/analyze?timeframe=1h",
            json={},
            timeout=120,
        )
        elapsed = time.time() - t0
        print(f"[crypto] analyze took {elapsed:.1f}s, status={r.status_code}")
        assert r.status_code == 200, f"analyze failed: {r.status_code} {r.text[:400]}"

        body = r.json()
        # Top-level shape: {symbol, market, timeframe, price, technical, consensus, models, ...}
        assert "consensus" in body and "models" in body, f"missing consensus/models (keys={list(body.keys())})"
        consensus = body["consensus"]
        for k in ("action", "confidence", "summary"):
            assert k in consensus, f"missing consensus.{k} (keys={list(consensus.keys())})"
        assert consensus["action"] in {"BUY", "SELL", "HOLD"}, f"unexpected action={consensus['action']}"

        models = body["models"]
        assert isinstance(models, list), "models must be a list"
        assert len(models) == 5, f"expected 5 models, got {len(models)}: {[m.get('name') for m in models]}"

        names = {m.get("name") for m in models}
        assert names == EXPECTED_LABELS, f"label mismatch. got={names} expected={EXPECTED_LABELS}"

        ok_count = sum(1 for m in models if m.get("ok"))
        print(f"[crypto] ok_count={ok_count}/5 -> {[(m['name'], m.get('ok'), m.get('error')) for m in models]}")
        # Store for cross-test reporting
        pytest.crypto_models_report = [(m["name"], bool(m.get("ok")), m.get("error")) for m in models]
        assert ok_count >= 4, f"only {ok_count}/5 models returned ok=true; details={pytest.crypto_models_report}"


# ---------- 2) AI ensemble on IDX stock ----------

class TestAIEnsembleStockID:
    def test_analyze_stock_returns_5_models(self, api_client):
        symbol = _pick_symbol(api_client, "stock_id")
        print(f"[stock_id] Using symbol: {symbol}")

        t0 = time.time()
        r = api_client.post(
            f"{BASE_URL}/api/asset/stock_id/{symbol}/analyze?timeframe=1h",
            json={},
            timeout=120,
        )
        elapsed = time.time() - t0
        print(f"[stock_id] analyze took {elapsed:.1f}s, status={r.status_code}")
        assert r.status_code == 200, f"analyze failed: {r.status_code} {r.text[:400]}"

        body = r.json()
        assert "consensus" in body and "models" in body, f"missing consensus/models (keys={list(body.keys())})"
        consensus = body["consensus"]
        assert consensus.get("action") in {"BUY", "SELL", "HOLD"}
        assert "summary" in consensus
        assert "confidence" in consensus

        models = body["models"]
        assert len(models) == 5, f"expected 5 models, got {len(models)}: {[m.get('name') for m in models]}"

        names = {m.get("name") for m in models}
        assert names == EXPECTED_LABELS, f"label mismatch. got={names} expected={EXPECTED_LABELS}"

        ok_count = sum(1 for m in models if m.get("ok"))
        print(f"[stock_id] ok_count={ok_count}/5 -> {[(m['name'], m.get('ok'), m.get('error')) for m in models]}")
        pytest.stock_models_report = [(m["name"], bool(m.get("ok")), m.get("error")) for m in models]
        assert ok_count >= 4, f"only {ok_count}/5 models returned ok=true; details={pytest.stock_models_report}"


# ---------- 3) Regression smoke ----------

class TestRegressionSmoke:
    def test_whoami(self, api_client):
        r = api_client.get(f"{BASE_URL}/api/whoami", timeout=30)
        assert r.status_code == 200
        body = r.json()
        for k in ("backend_origin", "db_name", "codes_count", "admin_tool_url", "server_time"):
            assert k in body, f"missing whoami field {k}"
        assert body["db_name"] == "aitrade_pro"

    def test_dashboard_crypto(self, api_client):
        r = api_client.get(f"{BASE_URL}/api/dashboard?market=crypto&timeframe=1h&full=true", timeout=60)
        assert r.status_code == 200
        body = r.json()
        items = body.get("assets") or body.get("items") or []
        assert isinstance(items, list) and len(items) > 0

    def test_auth_verify_full_flow(self, api_client):
        email = f"TEST_iter7_{uuid.uuid4().hex[:8]}@example.com"

        # Generate code (admin)
        gen = requests.post(
            f"{BASE_URL}/api/admin/generate-code",
            headers={"X-Admin-Token": ADMIN_TOKEN, "Content-Type": "application/json"},
            json={"email": email, "duration": "lifetime"},
            timeout=30,
        )
        assert gen.status_code == 200, f"generate-code failed: {gen.status_code} {gen.text[:300]}"
        code = gen.json().get("code")
        assert code, "no code returned from generate-code"

        try:
            # Verify
            device_id = "test-device-iter7"
            vr = requests.post(
                f"{BASE_URL}/api/auth/verify",
                json={"email": email, "code": code, "device_id": device_id},
                timeout=30,
            )
            assert vr.status_code == 200
            vb = vr.json()
            assert vb.get("ok") is True, f"verify not ok: {vb}"
        finally:
            # Cleanup
            de = requests.delete(
                f"{BASE_URL}/api/admin/users/{email}",
                headers={"X-Admin-Token": ADMIN_TOKEN},
                timeout=30,
            )
            assert de.status_code in (200, 204), f"cleanup failed: {de.status_code} {de.text[:200]}"
