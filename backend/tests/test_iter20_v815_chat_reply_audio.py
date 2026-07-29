"""
v8.1.5 Backend Tests — Chat reply + voice notes
Focus: POST/GET /api/chat/messages new fields (reply_to, audio_data, audio_duration_ms)
       + regression on /api/dashboard, /api/search, /api/subscription/health

Premium entitlement is expected NOT to be present in the test DB, so premium-gated
POSTs are expected to return 403. Per review-request note, 403 is treated as SUCCESS
for premium-gated tests. We also attempt a mock-entitlement success path.
"""
import os
import uuid
import time
import base64
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # fallback to EXPO_BACKEND_URL if defined (naming convention)
    BASE_URL = os.environ.get("EXPO_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL must be set"

API = f"{BASE_URL}/api"
TIMEOUT = 30


# ---------- helpers ----------
def _tiny_audio_data_url() -> str:
    # a minimal ~40 byte payload; content doesn't need to be a real m4a for schema checks
    blob = base64.b64encode(b"\x00" * 64).decode()
    return f"data:audio/m4a;base64,{blob}"


def _tiny_image_data_url() -> str:
    blob = base64.b64encode(b"\x00" * 32).decode()
    return f"data:image/png;base64,{blob}"


def _payload(**overrides):
    p = {
        "text": "hello",
        "nickname": "tester",
        "device_id": f"TEST_{uuid.uuid4().hex[:12]}",
    }
    p.update(overrides)
    return p


@pytest.fixture(scope="module")
def s():
    return requests.Session()


# =================================================================
# Chat POST — new fields, validation, entitlement
# =================================================================
class TestChatPostValidation:
    """Verify size/shape validation runs BEFORE the entitlement (403) check."""

    def test_missing_text_image_audio_returns_400(self, s):
        # empty text, no image, no audio, no reply_to -> 400
        r = s.post(f"{API}/chat/messages", json=_payload(text=""), timeout=TIMEOUT)
        assert r.status_code == 400, r.text
        # Error message should be clear
        detail = (r.json().get("detail") or "").lower()
        assert "text" in detail and ("image" in detail or "audio" in detail), r.text

    def test_reply_to_only_no_text_returns_400(self, s):
        # reply_to is metadata not content; empty text + no image + no audio => 400
        rt = {
            "id": str(uuid.uuid4()),
            "nickname": "someone",
            "snippet": "prior msg",
            "has_image": False,
            "has_audio": False,
        }
        r = s.post(f"{API}/chat/messages", json=_payload(text="", reply_to=rt), timeout=TIMEOUT)
        assert r.status_code == 400, r.text

    def test_audio_not_data_url_returns_400(self, s):
        # bad audio scheme
        r = s.post(
            f"{API}/chat/messages",
            json=_payload(audio_data="https://example.com/foo.m4a", audio_duration_ms=1500),
            timeout=TIMEOUT,
        )
        assert r.status_code == 400, r.text
        assert "data url" in (r.json().get("detail") or "").lower(), r.text

    def test_audio_wrong_mime_returns_400(self, s):
        # image mime under audio field
        r = s.post(
            f"{API}/chat/messages",
            json=_payload(audio_data="data:image/png;base64,AAAA", audio_duration_ms=1500),
            timeout=TIMEOUT,
        )
        assert r.status_code == 400, r.text

    def test_audio_duration_over_hard_cap_returns_400(self, s):
        r = s.post(
            f"{API}/chat/messages",
            json=_payload(audio_data=_tiny_audio_data_url(), audio_duration_ms=30001),
            timeout=TIMEOUT,
        )
        assert r.status_code == 400, r.text
        assert "voice note too long" in (r.json().get("detail") or "").lower(), r.text

    def test_audio_duration_exactly_30000_ok_shape(self, s):
        # exactly 30_000 should not trip the 30s hard-cap check (uses >)
        # entitlement then returns 403 (no premium in test DB) — treat as success
        r = s.post(
            f"{API}/chat/messages",
            json=_payload(audio_data=_tiny_audio_data_url(), audio_duration_ms=30000),
            timeout=TIMEOUT,
        )
        assert r.status_code in (200, 403), r.text

    def test_audio_data_too_large_returns_400(self, s):
        # > 500_000 chars
        big = "data:audio/m4a;base64," + ("A" * 500_001)
        r = s.post(
            f"{API}/chat/messages",
            json=_payload(audio_data=big, audio_duration_ms=1500),
            timeout=TIMEOUT,
        )
        assert r.status_code == 400, r.text
        assert "audio too large" in (r.json().get("detail") or "").lower(), r.text

    def test_missing_nickname_returns_400(self, s):
        r = s.post(f"{API}/chat/messages", json=_payload(nickname=""), timeout=TIMEOUT)
        assert r.status_code == 400, r.text


class TestChatPostEntitlement:
    """Without a premium subscription seed, all posts must 403."""

    def test_text_only_no_premium_returns_403(self, s):
        r = s.post(f"{API}/chat/messages", json=_payload(text="hello world"), timeout=TIMEOUT)
        assert r.status_code == 403, r.text
        assert "premium" in (r.json().get("detail") or "").lower(), r.text

    def test_image_only_no_premium_returns_403(self, s):
        r = s.post(
            f"{API}/chat/messages",
            json=_payload(text="", image_data=_tiny_image_data_url()),
            timeout=TIMEOUT,
        )
        assert r.status_code == 403, r.text

    def test_valid_audio_no_premium_returns_403(self, s):
        # valid audio (data URL + duration <= 30s) but no entitlement -> 403
        r = s.post(
            f"{API}/chat/messages",
            json=_payload(text="", audio_data=_tiny_audio_data_url(), audio_duration_ms=5000),
            timeout=TIMEOUT,
        )
        assert r.status_code == 403, r.text

    def test_valid_reply_to_no_premium_returns_403(self, s):
        rt = {
            "id": str(uuid.uuid4()),
            "nickname": "peer",
            "snippet": "prior message text",
            "has_image": False,
            "has_audio": False,
        }
        r = s.post(
            f"{API}/chat/messages",
            json=_payload(text="answering", reply_to=rt),
            timeout=TIMEOUT,
        )
        assert r.status_code == 403, r.text

    def test_reply_to_with_has_audio_no_premium_returns_403(self, s):
        # reply to a voice note
        rt = {
            "id": str(uuid.uuid4()),
            "nickname": "peer",
            "snippet": "",
            "has_image": False,
            "has_audio": True,
        }
        r = s.post(
            f"{API}/chat/messages",
            json=_payload(text="re: your voice note", reply_to=rt),
            timeout=TIMEOUT,
        )
        assert r.status_code == 403, r.text

    def test_reply_to_with_audio_reply_no_premium_returns_403(self, s):
        # combine reply_to + audio_data (both new features)
        rt = {
            "id": str(uuid.uuid4()),
            "nickname": "peer",
            "snippet": "hey",
            "has_image": False,
            "has_audio": False,
        }
        r = s.post(
            f"{API}/chat/messages",
            json=_payload(
                text="",
                audio_data=_tiny_audio_data_url(),
                audio_duration_ms=8000,
                reply_to=rt,
            ),
            timeout=TIMEOUT,
        )
        assert r.status_code == 403, r.text


class TestChatPostBackwardCompat:
    """Existing image-only + text payload contracts still return 403 (unchanged)."""

    def test_text_only_backward_compat_shape(self, s):
        r = s.post(
            f"{API}/chat/messages",
            json={"text": "hi", "nickname": "u", "device_id": f"TEST_{uuid.uuid4().hex[:8]}"},
            timeout=TIMEOUT,
        )
        assert r.status_code == 403, r.text  # entitlement gate, contract preserved

    def test_text_plus_image_backward_compat_shape(self, s):
        r = s.post(
            f"{API}/chat/messages",
            json={
                "text": "look",
                "nickname": "u",
                "device_id": f"TEST_{uuid.uuid4().hex[:8]}",
                "image_data": _tiny_image_data_url(),
            },
            timeout=TIMEOUT,
        )
        assert r.status_code == 403, r.text


# =================================================================
# Premium seeded path — insert entitlement directly in Mongo & verify success shape
# =================================================================
@pytest.fixture(scope="module")
def premium_device_id():
    """Seed a premium subscription row and yield the device_id. Cleans up after."""
    try:
        from pymongo import MongoClient
    except Exception:
        pytest.skip("pymongo not available")
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("DB_NAME", "aitrade_pro")
    client = MongoClient(mongo_url, serverSelectionTimeoutMS=3000)
    try:
        client.admin.command("ping")
    except Exception:
        pytest.skip("MongoDB not reachable from tests")
    db = client[db_name]
    dev = f"TEST_PREMIUM_{uuid.uuid4().hex[:12]}"
    # Insert an entitled row (no expiry_time, or a far-future one).
    from datetime import datetime, timezone, timedelta
    far_future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat().replace("+00:00", "Z")
    db.subscriptions.insert_one({
        "device_id": dev,
        "entitled": True,
        "expiry_time": far_future,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": "TEST_SEED_iter20",
    })
    yield dev
    # cleanup
    try:
        db.subscriptions.delete_many({"device_id": dev})
        db.chat_messages.delete_many({"device_id": dev})
    except Exception:
        pass
    client.close()


class TestChatPremiumSuccessPath:
    """With an entitled device seeded, verify new fields round-trip through POST + GET."""

    def test_post_with_audio_and_reply_returns_full_shape(self, s, premium_device_id):
        rt = {
            "id": str(uuid.uuid4()),
            "nickname": "alice",
            "snippet": "original text",
            "has_image": False,
            "has_audio": False,
        }
        payload = {
            "text": "TEST reply w/ voice",
            "nickname": "bob_TEST",
            "device_id": premium_device_id,
            "audio_data": _tiny_audio_data_url(),
            "audio_duration_ms": 4200,
            "reply_to": rt,
        }
        r = s.post(f"{API}/chat/messages", json=payload, timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        body = r.json()
        # Shape checks
        for k in ("id", "text", "nickname", "device_id", "created_at",
                 "image_data", "audio_data", "audio_duration_ms", "reply_to"):
            assert k in body, f"missing key {k} in {body.keys()}"
        assert body["audio_duration_ms"] == 4200
        assert body["audio_data"].startswith("data:audio/")
        assert body["image_data"] is None
        assert body["reply_to"]["id"] == rt["id"]
        assert body["reply_to"]["nickname"] == "alice"
        assert body["reply_to"]["has_image"] is False
        assert body["reply_to"]["has_audio"] is False

    def test_get_messages_returns_new_fields(self, s, premium_device_id):
        # send a text-only after a short wait to bypass rate limit (3s)
        time.sleep(4)
        payload = {
            "text": "TEST plain text",
            "nickname": "bob_TEST",
            "device_id": premium_device_id,
        }
        r = s.post(f"{API}/chat/messages", json=payload, timeout=TIMEOUT)
        assert r.status_code == 200, r.text

        # GET
        rg = s.get(f"{API}/chat/messages", timeout=TIMEOUT)
        assert rg.status_code == 200, rg.text
        data = rg.json()
        assert "messages" in data and "server_time" in data
        msgs = data["messages"]
        assert isinstance(msgs, list)
        # find our seeded ones
        ours = [m for m in msgs if m.get("device_id") == premium_device_id]
        assert len(ours) >= 1, f"expected >=1 own msg, got {len(ours)}"
        # every message must have all new optional fields (None or value)
        for m in msgs:
            assert "audio_data" in m
            assert "audio_duration_ms" in m
            assert "reply_to" in m
            # ensure no leaked mongo _id
            assert "_id" not in m
        # at least one of ours has audio+reply_to populated (from previous test)
        with_audio = [m for m in ours if m.get("audio_data")]
        assert with_audio, "expected the audio+reply message from previous test to be present"
        first = with_audio[0]
        assert first["audio_duration_ms"] == 4200
        assert first["reply_to"] is not None
        assert first["reply_to"]["nickname"] == "alice"


# =================================================================
# Regression — dashboard, search, subscription/health
# =================================================================
class TestRegressionEndpoints:

    def test_dashboard_crypto(self, s):
        r = s.get(f"{API}/dashboard", params={"market": "crypto"}, timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "assets" in data
        assert isinstance(data["assets"], list) and len(data["assets"]) > 0

    def test_dashboard_stock_us(self, s):
        r = s.get(f"{API}/dashboard", params={"market": "stock_us"}, timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "assets" in data
        assert isinstance(data["assets"], list)

    def test_search_btc(self, s):
        r = s.get(f"{API}/search", params={"q": "BTC"}, timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "hits" in data and "query" in data
        assert any("BTC" in (h.get("symbol") or "").upper() for h in data["hits"]), data

    def test_search_shape_contract(self, s):
        r = s.get(f"{API}/search", params={"q": "AAPL"}, timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        data = r.json()
        assert set(data.keys()) >= {"hits", "query", "disambiguation"}

    def test_subscription_health(self, s):
        r = s.get(f"{API}/subscription/health", timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        data = r.json()
        # tolerate iter19 shape drift (5 keys including package_name)
        assert isinstance(data, dict) and len(data) >= 2
        # ensure no secrets leak
        text = str(data).lower()
        for banned in ("private_key", "client_email", "-----begin", "service_account.json"):
            assert banned not in text, f"leaked '{banned}' in {data}"

    def test_get_chat_messages_public(self, s):
        r = s.get(f"{API}/chat/messages", timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "messages" in data
        assert "server_time" in data
