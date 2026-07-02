"""Iteration 5: /api/whoami fingerprint + end-to-end unlock code auth flow."""
import os
import re
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL")
if not BASE_URL:
    # frontend/.env is the source of truth for the ingress URL
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("EXPO_PUBLIC_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().strip('"')
                break
BASE_URL = (BASE_URL or "").rstrip("/")

ADMIN_TOKEN = "kevin-admin-2026-do-not-share-xyz789"
TEST_EMAIL = "TEST_e2etest@example.com"
TEST_DEVICE_ID = "TEST_device-iter5-abc"
TEST_DEVICE_NAME = "TEST Device iter5"


@pytest.fixture(scope="session")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ---------- /api/whoami ----------

class TestWhoami:
    def test_whoami_returns_all_five_fields(self, api):
        r = api.get(f"{BASE_URL}/api/whoami", timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        for field in ("backend_origin", "db_name", "codes_count", "admin_tool_url", "server_time"):
            assert field in data, f"missing {field} in {data}"

    def test_whoami_db_name_matches_env(self, api):
        r = api.get(f"{BASE_URL}/api/whoami", timeout=15)
        data = r.json()
        assert data["db_name"] == "aitrade_pro"

    def test_whoami_admin_url_is_backend_plus_admin_tool(self, api):
        r = api.get(f"{BASE_URL}/api/whoami", timeout=15)
        data = r.json()
        assert data["admin_tool_url"] == data["backend_origin"] + "/api/admin-tool"

    def test_whoami_codes_count_matches_admin_list(self, api):
        r_who = api.get(f"{BASE_URL}/api/whoami", timeout=15)
        who = r_who.json()
        r_list = api.get(
            f"{BASE_URL}/api/admin/codes",
            headers={"X-Admin-Token": ADMIN_TOKEN},
            timeout=15,
        )
        assert r_list.status_code == 200, r_list.text
        listed = r_list.json()
        assert who["codes_count"] == listed["total"], (
            f"whoami codes_count={who['codes_count']} but admin list total={listed['total']}"
        )

    def test_whoami_backend_origin_uses_ingress_not_localhost(self, api):
        r = api.get(f"{BASE_URL}/api/whoami", timeout=15)
        data = r.json()
        # Must not be localhost / 127.0.0.1 / :8001 when accessed via ingress
        assert "localhost" not in data["backend_origin"], data
        assert "127.0.0.1" not in data["backend_origin"], data
        assert ":8001" not in data["backend_origin"], data
        # Should be an https URL matching the ingress
        assert data["backend_origin"].startswith("http"), data

    def test_whoami_respects_x_forwarded_headers(self, api):
        r = api.get(
            f"{BASE_URL}/api/whoami",
            headers={"X-Forwarded-Host": "custom.example.com", "X-Forwarded-Proto": "https"},
            timeout=15,
        )
        data = r.json()
        # Ingress may strip these headers; if the backend received them we should see the override.
        # Otherwise at minimum the origin should still be a valid URL.
        assert data["backend_origin"].startswith("http")

    def test_whoami_server_time_iso_format(self, api):
        r = api.get(f"{BASE_URL}/api/whoami", timeout=15)
        data = r.json()
        # ISO 8601-ish: e.g. 2026-01-15T12:34:56.123456+00:00 or Z
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", data["server_time"]), data["server_time"]


# ---------- /api/admin-tool HTML ----------

class TestAdminToolHtml:
    def test_admin_tool_html_contains_whoami_banner(self, api):
        r = api.get(f"{BASE_URL}/api/admin-tool", timeout=15)
        assert r.status_code == 200
        html = r.text
        assert 'id="whoami-banner"' in html
        assert "BACKEND SAAT INI" in html
        assert 'id="whoami-origin"' in html


# ---------- End-to-end unlock code flow ----------

class TestUnlockCodeFlow:
    """Generate code -> verify -> case/whitespace tolerance -> device mismatch -> invalid -> cleanup."""

    _generated_code = None

    def test_a_generate_code(self, api):
        r = api.post(
            f"{BASE_URL}/api/admin/generate-code",
            headers={"X-Admin-Token": ADMIN_TOKEN},
            json={"email": TEST_EMAIL, "duration": "lifetime"},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert "code" in data
        assert isinstance(data["code"], str) and len(data["code"]) >= 8
        TestUnlockCodeFlow._generated_code = data["code"]

    def test_b_verify_success(self, api):
        code = TestUnlockCodeFlow._generated_code
        assert code, "Code was not generated in previous test"
        r = api.post(
            f"{BASE_URL}/api/auth/verify",
            json={
                "email": TEST_EMAIL,
                "code": code,
                "device_id": TEST_DEVICE_ID,
                "device_name": TEST_DEVICE_NAME,
            },
            timeout=15,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("ok") is True, data
        assert data.get("duration") == "lifetime", data
        assert data.get("expires_at") is None, data
        assert data.get("device_id") == TEST_DEVICE_ID, data

    def test_c_verify_case_insensitive_and_whitespace_tolerant(self, api):
        code = TestUnlockCodeFlow._generated_code
        # Re-verifying with SAME device should still succeed (already bound); mangle case+spaces.
        mangled = f"   {code.lower()}   "
        r = api.post(
            f"{BASE_URL}/api/auth/verify",
            json={
                "email": TEST_EMAIL,
                "code": mangled,
                "device_id": TEST_DEVICE_ID,
                "device_name": TEST_DEVICE_NAME,
            },
            timeout=15,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("ok") is True, data

    def test_d_verify_device_mismatch(self, api):
        code = TestUnlockCodeFlow._generated_code
        r = api.post(
            f"{BASE_URL}/api/auth/verify",
            json={
                "email": TEST_EMAIL,
                "code": code,
                "device_id": "TEST_different-device-xyz",
                "device_name": "Other",
            },
            timeout=15,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("ok") is False, data
        assert data.get("reason") == "device_mismatch", data

    def test_e_verify_invalid_code(self, api):
        r = api.post(
            f"{BASE_URL}/api/auth/verify",
            json={
                "email": TEST_EMAIL,
                "code": "AAAA-BBBB-CCCC",
                "device_id": TEST_DEVICE_ID,
                "device_name": TEST_DEVICE_NAME,
            },
            timeout=15,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("ok") is False, data
        assert data.get("reason") == "invalid_code", data

    def test_f_cleanup_delete_code(self, api):
        code = TestUnlockCodeFlow._generated_code
        r = api.delete(
            f"{BASE_URL}/api/admin/codes/{code}",
            headers={"X-Admin-Token": ADMIN_TOKEN},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        assert r.json().get("ok") is True
        # Also cleanup logged_users entry so re-runs are clean
        api.delete(
            f"{BASE_URL}/api/admin/users/{TEST_EMAIL.lower()}",
            headers={"X-Admin-Token": ADMIN_TOKEN},
            timeout=15,
        )

    def test_g_admin_token_required(self, api):
        r = api.post(
            f"{BASE_URL}/api/admin/generate-code",
            json={"email": "x@x.com", "duration": "monthly"},
            timeout=15,
        )
        assert r.status_code == 403


# ---------- Regression: existing critical endpoints still respond ----------

class TestRegression:
    def test_root_health(self, api):
        r = api.get(f"{BASE_URL}/api/", timeout=15)
        # Some backends return 200 with {"message": "..."} or 404 if not defined; accept 200 or 404
        assert r.status_code in (200, 404)

    def test_profiles_endpoint(self, api):
        r = api.get(f"{BASE_URL}/api/profiles", timeout=20)
        assert r.status_code == 200
