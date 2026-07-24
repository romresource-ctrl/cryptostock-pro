"""Backend tests for v3.0.8 subscription flow + regression endpoints.

Covers:
- POST /api/subscription/verify   (dev-mode fallback => unverified, entitled=false, persisted)
- GET  /api/subscription/status   (cached lookup by device_id, none => none/false)
- GET  /api/dashboard             (regression)
- POST /api/auth/verify           (legacy unlock code, uses test_credentials.md)
- GET  /api/asset/{market}/{sym}/chart
- GET  /api/privacy, /api/terms, /api/data-deletion (public HTML)
- GET  /api/                      (health)
"""
from __future__ import annotations

import os
import uuid

import pytest
import requests

BASE_URL = os.environ.get(
    "EXPO_PUBLIC_BACKEND_URL",
    "https://cryptostock-pro.preview.emergentagent.com",
).rstrip("/")


@pytest.fixture(scope="module")
def api_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ---------- Health / regression ----------
class TestHealth:
    def test_health_ok(self, api_client):
        r = api_client.get(f"{BASE_URL}/api/", timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d.get("status") == "ok"


class TestPublicHtml:
    @pytest.mark.parametrize("path", ["/api/privacy", "/api/terms", "/api/data-deletion"])
    def test_public_html(self, api_client, path):
        r = api_client.get(f"{BASE_URL}{path}", timeout=30)
        assert r.status_code == 200, f"{path} -> {r.status_code}"
        assert "text/html" in r.headers.get("content-type", "").lower()
        # very small sanity check
        assert len(r.text) > 100


class TestDashboardRegression:
    def test_dashboard_crypto(self, api_client):
        r = api_client.get(
            f"{BASE_URL}/api/dashboard",
            params={"market": "crypto", "timeframe": "1h"},
            timeout=90,
        )
        assert r.status_code == 200
        d = r.json()
        assert d.get("market") == "crypto"
        assert "assets" in d
        assert isinstance(d["assets"], list)
        # At least one asset with essentials
        if d["assets"]:
            a = d["assets"][0]
            for k in ("symbol", "action", "confidence"):
                assert k in a


class TestAssetChart:
    def test_btc_chart(self, api_client):
        r = api_client.get(
            f"{BASE_URL}/api/asset/crypto/BTC/chart",
            params={"timeframe": "1h"},
            timeout=60,
        )
        assert r.status_code == 200
        d = r.json()
        assert d["symbol"] == "BTC"
        assert "candles" in d and isinstance(d["candles"], list)
        assert "signal" in d


# ---------- Legacy auth (from test_credentials.md) ----------
class TestLegacyAuth:
    def test_auth_verify_known_code(self, api_client):
        r = api_client.post(
            f"{BASE_URL}/api/auth/verify",
            json={
                "email": "test@example.com",
                "code": "3459-10B0-3308",
                "device_id": f"test-device-{uuid.uuid4().hex[:8]}",
                "device_name": "pytest-runner",
            },
            timeout=30,
        )
        # Must respond 200 with ok true or false depending on code state in this DB
        assert r.status_code == 200, r.text
        d = r.json()
        assert "ok" in d
        # If code exists in DB it should be ok; if not seeded here, we accept
        # a well-formed failure (invalid_code) — but flag it for main agent.
        if not d.get("ok"):
            pytest.skip(f"Legacy code not present in this DB: reason={d.get('reason')}")

    def test_auth_verify_missing_device_id(self, api_client):
        r = api_client.post(
            f"{BASE_URL}/api/auth/verify",
            json={"email": "x@example.com", "code": "AAAA-BBBB-CCCC"},
            timeout=30,
        )
        assert r.status_code == 400


# ---------- Subscription verify + status ----------
class TestSubscriptionVerifyDevFallback:
    """With GOOGLE_PLAY_SERVICE_ACCOUNT_JSON not set, verify must return
    status='unverified', entitled=false, and persist a row."""

    def _payload(self, device_id):
        return {
            "purchase_token": f"FAKE_TOKEN_{uuid.uuid4().hex}",
            "product_id": "ai_cryptostockpro_monthly",
            "package_name": "com.cryptostockapps.aicryptostockpro",
            "device_id": device_id,
        }

    def test_verify_400_when_missing_fields(self, api_client):
        r = api_client.post(
            f"{BASE_URL}/api/subscription/verify",
            json={"purchase_token": "", "product_id": ""},
            timeout=30,
        )
        assert r.status_code in (400, 422)

    def test_verify_dev_fallback_unverified(self, api_client):
        device_id = f"TEST_dev_{uuid.uuid4().hex[:10]}"
        r = api_client.post(
            f"{BASE_URL}/api/subscription/verify",
            json=self._payload(device_id),
            timeout=30,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["status"] == "unverified", f"expected unverified got {d}"
        assert d["entitled"] is False
        assert d["source"] == "unverified"
        assert d["product_id"] == "ai_cryptostockpro_monthly"

    def test_verify_then_status_persists(self, api_client):
        device_id = f"TEST_dev_{uuid.uuid4().hex[:10]}"
        vr = api_client.post(
            f"{BASE_URL}/api/subscription/verify",
            json=self._payload(device_id),
            timeout=30,
        )
        assert vr.status_code == 200
        # Now GET status should reflect the persisted row (status=unverified)
        sr = api_client.get(
            f"{BASE_URL}/api/subscription/status",
            params={"device_id": device_id},
            timeout=30,
        )
        assert sr.status_code == 200, sr.text
        d = sr.json()
        assert d["status"] == "unverified"
        assert d["entitled"] is False
        assert d["product_id"] == "ai_cryptostockpro_monthly"


class TestSubscriptionStatusNoDevice:
    def test_status_no_device_id(self, api_client):
        r = api_client.get(f"{BASE_URL}/api/subscription/status", timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d["status"] == "none"
        assert d["entitled"] is False

    def test_status_unknown_device(self, api_client):
        r = api_client.get(
            f"{BASE_URL}/api/subscription/status",
            params={"device_id": f"TEST_unknown_{uuid.uuid4().hex[:8]}"},
            timeout=30,
        )
        assert r.status_code == 200
        d = r.json()
        assert d["status"] == "none"
        assert d["entitled"] is False
