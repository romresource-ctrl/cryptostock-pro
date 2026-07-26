"""
Iteration 16 — AI Crypto Stock Pro v5.0.4 backend regression.

Focus:
  * POST /api/chat/messages validation (image_data, non-premium gate)
  * GET  /api/chat/messages
  * GET  /api/subscription/status  (fresh device → status=none, entitled=false)
  * GET  /api/subscription/health  (publisher_client_initialised)
  * Regression: /api/dashboard 7 markets, /api/analyze reachable
"""

import os
import uuid
import time
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/") or \
           "https://cryptostock-pro.preview.emergentagent.com"
API = f"{BASE_URL}/api"


@pytest.fixture(scope="module")
def api_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ---------------- Subscription endpoints ----------------

class TestSubscriptionEndpoints:
    def test_status_fresh_device(self, api_client):
        fresh = f"fresh-{uuid.uuid4().hex[:12]}"
        r = api_client.get(f"{API}/subscription/status", params={"device_id": fresh}, timeout=30)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j.get("status") == "none"
        assert j.get("entitled") is False
        # source is either "none" (no row) or "cached"
        assert j.get("source") in ("none", "cached", None)

    def test_status_no_device_id(self, api_client):
        r = api_client.get(f"{API}/subscription/status", timeout=30)
        assert r.status_code == 200
        j = r.json()
        assert j.get("status") == "none"
        assert j.get("entitled") is False

    def test_health_publisher_initialised(self, api_client):
        r = api_client.get(f"{API}/subscription/health", timeout=30)
        assert r.status_code == 200, r.text
        j = r.json()
        assert "publisher_client_initialised" in j
        assert j["publisher_client_initialised"] is True, \
            f"Publisher client not initialised: {j}"
        assert j.get("service_account_env_set") is True


# ---------------- Chat POST validation ----------------

class TestChatMessagePostValidation:
    """v5.0.4: text is optional if image_data provided; image_data must be data URL and <=750KB chars."""

    def test_non_premium_forbidden(self, api_client):
        dev = f"nonprem-{uuid.uuid4().hex[:12]}"
        r = api_client.post(
            f"{API}/chat/messages",
            json={"text": "hello world", "nickname": "Tester1", "device_id": dev},
            timeout=30,
        )
        assert r.status_code == 403, r.text
        assert "premium" in r.text.lower()

    def test_missing_nickname_or_device(self, api_client):
        r = api_client.post(
            f"{API}/chat/messages",
            json={"text": "hi", "nickname": "", "device_id": "abc"},
            timeout=30,
        )
        assert r.status_code == 400

    def test_empty_text_and_no_image(self, api_client):
        dev = f"nonprem-{uuid.uuid4().hex[:12]}"
        r = api_client.post(
            f"{API}/chat/messages",
            json={"text": "", "nickname": "Tester", "device_id": dev},
            timeout=30,
        )
        # v5.0.4 spec: 400 "Message text or image is required"
        assert r.status_code == 400, r.text
        assert "text or image" in r.text.lower()

    def test_image_data_not_data_url(self, api_client):
        dev = f"nonprem-{uuid.uuid4().hex[:12]}"
        r = api_client.post(
            f"{API}/chat/messages",
            json={
                "text": "",
                "nickname": "Tester",
                "device_id": dev,
                "image_data": "https://example.com/img.jpg",
            },
            timeout=30,
        )
        assert r.status_code == 400, r.text
        assert "data url" in r.text.lower() or "data:image" in r.text.lower()

    def test_image_data_too_large(self, api_client):
        dev = f"nonprem-{uuid.uuid4().hex[:12]}"
        big = "data:image/jpeg;base64," + ("A" * 800_000)
        r = api_client.post(
            f"{API}/chat/messages",
            json={
                "text": "",
                "nickname": "Tester",
                "device_id": dev,
                "image_data": big,
            },
            timeout=60,
        )
        assert r.status_code == 400, r.text[:200]
        assert "too large" in r.text.lower()

    def test_valid_image_data_url_still_403_for_non_premium(self, api_client):
        """Confirms that the data-URL validator runs BEFORE the entitlement gate is the only remaining check.
        Actually the current server checks nickname/device → text-or-image → image validators → entitlement.
        So a well-formed image + non-premium device should return 403."""
        dev = f"nonprem-{uuid.uuid4().hex[:12]}"
        r = api_client.post(
            f"{API}/chat/messages",
            json={
                "text": "",
                "nickname": "Tester",
                "device_id": dev,
                "image_data": "data:image/jpeg;base64,AAAA",
            },
            timeout=30,
        )
        assert r.status_code == 403, r.text
        assert "premium" in r.text.lower()


# ---------------- Chat happy path (entitled device via direct Mongo insert) ----------------

class TestChatHappyPath:
    """Insert a temporary premium entitlement row so we can exercise POST success."""

    @pytest.fixture(scope="class")
    def entitled_device(self):
        # Use Mongo directly to seed an "active" entitlement — this is the only
        # way to test the happy path without a real Google Play token.
        try:
            from pymongo import MongoClient
        except ImportError:
            pytest.skip("pymongo not installed")

        mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
        db_name = os.environ.get("DB_NAME", "aitrade_pro")
        client = MongoClient(mongo_url)
        db = client[db_name]
        device_id = f"TEST_premium_{uuid.uuid4().hex[:12]}"
        from datetime import datetime, timedelta, timezone
        future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        db.subscriptions.insert_one({
            "device_id": device_id,
            "purchase_token": f"TEST_token_{uuid.uuid4().hex}",
            "product_id": "ai_cryptostockpro_monthly",
            "package_name": "com.cryptostockapps.aicryptostockpro",
            "status": "active",
            "entitled": True,
            "expiry_time": future,
            "source": "test-seed",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        yield device_id
        # cleanup
        db.subscriptions.delete_many({"device_id": device_id})
        db.chat_messages.delete_many({"device_id": device_id})
        client.close()

    def test_post_text_only_success(self, api_client, entitled_device):
        r = api_client.post(
            f"{API}/chat/messages",
            json={
                "text": f"TEST_v504 hello {uuid.uuid4().hex[:6]}",
                "nickname": "TEST_Bot",
                "device_id": entitled_device,
            },
            timeout=30,
        )
        assert r.status_code == 200, r.text
        j = r.json()
        assert j.get("text", "").startswith("TEST_v504 hello")
        assert j.get("nickname") == "TEST_Bot"
        assert j.get("image_data") is None
        assert "id" in j and "created_at" in j

    def test_post_image_only_success(self, api_client, entitled_device):
        # Wait past rate limit (3s)
        time.sleep(3.2)
        img = "data:image/png;base64," + "iVBORw0KGgoAAAANSUhEUg"  # dummy but valid prefix
        r = api_client.post(
            f"{API}/chat/messages",
            json={
                "text": "",
                "nickname": "TEST_Bot",
                "device_id": entitled_device,
                "image_data": img,
            },
            timeout=30,
        )
        assert r.status_code == 200, r.text
        j = r.json()
        assert j.get("image_data") == img
        assert j.get("text") == ""


# ---------------- Chat GET ----------------

class TestChatGet:
    def test_get_messages_returns_list(self, api_client):
        r = api_client.get(f"{API}/chat/messages?limit=50", timeout=30)
        assert r.status_code == 200, r.text
        j = r.json()
        assert isinstance(j.get("messages"), list)
        assert "server_time" in j
        # image_data field should be present (or None) on each message shape
        for m in j["messages"][:5]:
            assert "id" in m and "text" in m and "created_at" in m
            # image_data is optional; ensure key exists OR value is missing (both OK)
            # (backend returns projection with _id excluded)


# ---------------- Regression: dashboard & analyze ----------------

class TestRegression:
    def test_dashboard_returns_seven_markets(self, api_client):
        markets = ["crypto", "stock_id", "etf", "stock_us", "gold_silver", "commodity", "forex"]
        for m in markets:
            r = api_client.get(f"{API}/dashboard", params={"market": m}, timeout=90)
            assert r.status_code == 200, f"{m}: {r.status_code} {r.text[:200]}"
            j = r.json()
            assert j.get("market") == m, f"{m}: response market={j.get('market')}"
            assert isinstance(j.get("assets"), list), f"{m}: no assets list"
            assert len(j["assets"]) > 0, f"{m}: empty assets list"

    def test_analyze_endpoint_reachable(self, api_client):
        # Simple sanity — should return 200 or 4xx (not 5xx)
        r = api_client.get(f"{API}/analyze/crypto/BTC", timeout=90)
        assert r.status_code < 500, f"analyze endpoint 5xx: {r.status_code} {r.text[:200]}"
