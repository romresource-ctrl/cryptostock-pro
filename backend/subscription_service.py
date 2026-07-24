"""Google Play Billing subscription verification service.

Handles server-side verification of Play Store subscription purchases via the
Google Play Developer API (`purchases.subscriptionsv2.get`), interprets the
lifecycle state, and persists an entitlement record in MongoDB.

Environment variables:
- GOOGLE_PLAY_SERVICE_ACCOUNT_JSON: path to the service-account JSON file, OR
  the raw JSON string. If neither is set, verification is skipped and status
  is returned as 'unverified' (dev-mode fallback).
- ANDROID_PACKAGE_NAME: must match the app package (defaults to
  'com.cryptostockapps.aicryptostockpro').

Play subscription lifecycle states we map into:
    active | grace_period | on_hold | paused | canceled | expired | pending
Entitled statuses (unlock premium): 'active', 'grace_period'
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Literal

logger = logging.getLogger("aitrade.subscription")

SubStatus = Literal[
    "active",
    "grace_period",
    "on_hold",
    "paused",
    "canceled",
    "expired",
    "pending",
    "unverified",
    "invalid",
]

ENTITLED_STATUSES: set[str] = {"active", "grace_period"}

DEFAULT_PACKAGE = "com.cryptostockapps.aicryptostockpro"


def _package_name() -> str:
    return os.environ.get("ANDROID_PACKAGE_NAME", DEFAULT_PACKAGE)


def _load_service_account_info() -> dict[str, Any] | None:
    """Load service-account credentials from env.

    Supports either:
      - GOOGLE_PLAY_SERVICE_ACCOUNT_JSON=<path/to/file.json>
      - GOOGLE_PLAY_SERVICE_ACCOUNT_JSON=<full raw JSON string>
    """
    raw = os.environ.get("GOOGLE_PLAY_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw:
        return None
    # If it looks like a path, read it
    if raw.startswith("{"):
        try:
            return json.loads(raw)
        except Exception as e:  # pragma: no cover
            logger.warning("Failed to parse inline service-account JSON: %s", e)
            return None
    if os.path.isfile(raw):
        try:
            with open(raw, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:  # pragma: no cover
            logger.warning("Failed to read service-account file %s: %s", raw, e)
            return None
    logger.warning("GOOGLE_PLAY_SERVICE_ACCOUNT_JSON is set but not a file or JSON")
    return None


_ANDROID_PUBLISHER_SCOPE = "https://www.googleapis.com/auth/androidpublisher"


class _CachedClient:
    """Lazy cached Google Play Publisher client (one per process)."""

    _client: Any | None = None

    @classmethod
    def get(cls) -> Any | None:
        if cls._client is not None:
            return cls._client
        info = _load_service_account_info()
        if info is None:
            return None
        try:
            # Lazy import so the whole app doesn't fail if the library is missing
            from google.oauth2 import service_account  # type: ignore
            from googleapiclient.discovery import build  # type: ignore

            creds = service_account.Credentials.from_service_account_info(
                info, scopes=[_ANDROID_PUBLISHER_SCOPE]
            )
            cls._client = build(
                "androidpublisher", "v3", credentials=creds, cache_discovery=False
            )
            logger.info("Google Play Publisher client initialised")
            return cls._client
        except Exception as e:  # pragma: no cover
            logger.warning("Failed to build Google Play Publisher client: %s", e)
            return None


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _interpret_v2(sub_v2: dict[str, Any]) -> tuple[SubStatus, datetime | None]:
    """Interpret a v2 SubscriptionPurchase resource.

    v2 schema fields we rely on:
      subscriptionState: 'SUBSCRIPTION_STATE_ACTIVE' | 'SUBSCRIPTION_STATE_CANCELED'
                       | 'SUBSCRIPTION_STATE_IN_GRACE_PERIOD'
                       | 'SUBSCRIPTION_STATE_ON_HOLD'
                       | 'SUBSCRIPTION_STATE_PAUSED'
                       | 'SUBSCRIPTION_STATE_EXPIRED'
                       | 'SUBSCRIPTION_STATE_PENDING'
      lineItems[].expiryTime (RFC3339)
    """
    state = sub_v2.get("subscriptionState", "")

    mapping: dict[str, SubStatus] = {
        "SUBSCRIPTION_STATE_ACTIVE": "active",
        "SUBSCRIPTION_STATE_CANCELED": "canceled",
        "SUBSCRIPTION_STATE_IN_GRACE_PERIOD": "grace_period",
        "SUBSCRIPTION_STATE_ON_HOLD": "on_hold",
        "SUBSCRIPTION_STATE_PAUSED": "paused",
        "SUBSCRIPTION_STATE_EXPIRED": "expired",
        "SUBSCRIPTION_STATE_PENDING": "pending",
    }
    status: SubStatus = mapping.get(state, "invalid")

    # Extract expiry from lineItems (v2)
    expiry: datetime | None = None
    for item in sub_v2.get("lineItems", []) or []:
        exp = item.get("expiryTime")
        if exp:
            try:
                # RFC3339 with Z suffix
                expiry = datetime.fromisoformat(exp.replace("Z", "+00:00"))
                break
            except Exception:
                continue

    # If canceled but expiry is in the future, we still keep access → treat as active
    if status == "canceled" and expiry and expiry > _now():
        # Access retained until expiry, but flag as canceled so client can show "will not renew"
        pass  # keep "canceled" as-is; client uses ENTITLED_STATUSES to gate

    return status, expiry


def _interpret_v1(sub_v1: dict[str, Any]) -> tuple[SubStatus, datetime | None]:
    """Interpret legacy v1 SubscriptionPurchase (purchases.subscriptions.get)."""
    expiry_ms = sub_v1.get("expiryTimeMillis")
    expiry: datetime | None = None
    if expiry_ms:
        try:
            expiry = datetime.fromtimestamp(int(expiry_ms) / 1000.0, tz=timezone.utc)
        except Exception:
            expiry = None

    now = _now()
    payment_state = sub_v1.get("paymentState")
    cancel_reason = sub_v1.get("cancelReason")
    auto_renewing = bool(sub_v1.get("autoRenewing"))

    if expiry and expiry <= now:
        return ("expired", expiry)

    # paymentState: 0=pending, 1=received, 2=free trial, 3=deferred
    if payment_state == 0:
        # Pending payment but still within period → grace-ish, treat as pending
        return ("pending", expiry)

    if cancel_reason is not None:
        # 0=user, 1=system, 2=replaced, 3=developer
        if expiry and expiry > now:
            return ("canceled", expiry)
        return ("expired", expiry)

    if expiry and expiry > now:
        if auto_renewing:
            return ("active", expiry)
        # Not auto-renewing but not expired: still active
        return ("active", expiry)

    return ("invalid", expiry)


def verify_purchase(
    purchase_token: str, product_id: str, package_name: str | None = None
) -> dict[str, Any]:
    """Verify a purchase token with Google Play and return status + expiry.

    Returns:
        {
          "status": SubStatus,
          "expiry_time": Optional[datetime],
          "entitled": bool,
          "raw": {..} | None,
          "source": "google_play_v2" | "google_play_v1" | "unverified",
        }
    """
    pkg = package_name or _package_name()
    client = _CachedClient.get()

    if client is None:
        logger.warning(
            "Service account not configured — returning unverified status. "
            "Set GOOGLE_PLAY_SERVICE_ACCOUNT_JSON to enable real verification."
        )
        return {
            "status": "unverified",
            "expiry_time": None,
            "entitled": False,
            "raw": None,
            "source": "unverified",
        }

    # Try v2 first (recommended by Google), fall back to v1
    try:
        v2 = (
            client.purchases()
            .subscriptionsv2()
            .get(packageName=pkg, token=purchase_token)
            .execute()
        )
        status, expiry = _interpret_v2(v2)
        return {
            "status": status,
            "expiry_time": expiry,
            "entitled": status in ENTITLED_STATUSES,
            "raw": v2,
            "source": "google_play_v2",
        }
    except Exception as e_v2:
        logger.info("v2 subscription lookup failed (%s), trying v1", e_v2)

    try:
        v1 = (
            client.purchases()
            .subscriptions()
            .get(packageName=pkg, subscriptionId=product_id, token=purchase_token)
            .execute()
        )
        status, expiry = _interpret_v1(v1)
        return {
            "status": status,
            "expiry_time": expiry,
            "entitled": status in ENTITLED_STATUSES,
            "raw": v1,
            "source": "google_play_v1",
        }
    except Exception as e_v1:
        logger.warning("v1 subscription lookup failed: %s", e_v1)
        return {
            "status": "invalid",
            "expiry_time": None,
            "entitled": False,
            "raw": None,
            "source": "unverified",
        }
