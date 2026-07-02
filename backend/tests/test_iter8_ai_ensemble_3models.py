"""Iteration 8 backend tests — 3-model AI ensemble (cost reduction).

Verifies:
  1. POST /api/asset/crypto/{symbol}/analyze returns EXACTLY 3 models with expected labels.
  2. GPT-5.5 and Gemini 3.1 Pro have been REMOVED.
  3. At least 2/3 models return ok=true.
  4. Regression: /api/whoami and /api/dashboard still return 200.
"""
from __future__ import annotations

import os
import time

import pytest
import requests

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
ADMIN_TOKEN = "kevin-admin-2026-do-not-share-xyz789"

EXPECTED_LABELS = {
    "Claude Fable 5",
    "Claude Opus 4.8",
    "Claude Sonnet 4.6",
}
FORBIDDEN_LABELS = {"GPT-5.5", "Gemini 3.1 Pro"}


@pytest.fixture(scope="module")
def api_client() -> requests.Session:
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json", "X-App-Version": "2.1.8"})
    return s


def _pick_symbol(api_client: requests.Session, market: str) -> str:
    url = f"{BASE_URL}/api/dashboard?market={market}&timeframe=1h&full=true"
    r = api_client.get(url, timeout=60)
    assert r.status_code == 200, f"dashboard failed: {r.status_code} {r.text[:200]}"
    data = r.json()
    items = data.get("assets") or data.get("items") or []
    assert items, f"no items for market={market}"
    # Prefer common symbols
    preferred = {"BNBUSDT", "BTCUSDT", "ETHUSDT"}
    for it in items:
        if it.get("symbol") in preferred:
            return it["symbol"]
    return items[0]["symbol"]


class TestAIEnsembleCrypto3Models:
    def test_analyze_crypto_returns_exactly_3_models(self, api_client):
        symbol = _pick_symbol(api_client, "crypto")
        print(f"[crypto] Using symbol: {symbol}")

        t0 = time.time()
        r = api_client.post(
            f"{BASE_URL}/api/asset/crypto/{symbol}/analyze?timeframe=1h",
            json={},
            timeout=120,
        )
        elapsed = time.time() - t0
        print(f"[crypto] analyze took {elapsed:.1f}s status={r.status_code}")
        assert r.status_code == 200, f"analyze failed: {r.status_code} {r.text[:400]}"

        body = r.json()
        assert "consensus" in body and "models" in body, f"missing keys={list(body.keys())}"

        models = body["models"]
        assert isinstance(models, list), "models must be list"
        # EXACT count check
        assert len(models) == 3, (
            f"expected EXACTLY 3 models, got {len(models)}: "
            f"{[m.get('name') for m in models]}"
        )

        names = {m.get("name") for m in models}
        # Label match
        assert names == EXPECTED_LABELS, (
            f"label mismatch. got={names} expected={EXPECTED_LABELS}"
        )
        # No forbidden labels
        overlap = names & FORBIDDEN_LABELS
        assert not overlap, f"forbidden labels present: {overlap}"

        # ok count
        details = [(m["name"], bool(m.get("ok")), m.get("error")) for m in models]
        ok_count = sum(1 for m in models if m.get("ok"))
        print(f"[crypto] ok_count={ok_count}/3 -> {details}")
        assert ok_count >= 2, f"only {ok_count}/3 ok=true; details={details}"

        # Consensus sanity
        consensus = body["consensus"]
        assert consensus.get("action") in {"BUY", "SELL", "HOLD"}
        assert "confidence" in consensus
        assert "summary" in consensus


class TestRegressionSmoke:
    def test_whoami(self, api_client):
        r = api_client.get(f"{BASE_URL}/api/whoami", timeout=30)
        assert r.status_code == 200
        body = r.json()
        for k in ("backend_origin", "db_name", "codes_count", "admin_tool_url", "server_time"):
            assert k in body, f"missing whoami field {k}"
        assert body["db_name"] == "aitrade_pro"

    def test_dashboard_crypto(self, api_client):
        r = api_client.get(f"{BASE_URL}/api/dashboard?market=crypto", timeout=60)
        assert r.status_code == 200
        body = r.json()
        items = body.get("assets") or body.get("items") or []
        assert isinstance(items, list) and len(items) > 0
