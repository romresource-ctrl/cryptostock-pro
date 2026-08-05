"""Emergent managed push notification integration.

Provides:
- `send_push(recipients, data, idempotency_key)` — server-side helper that
  relays a notification through the Emergent push service (SuprSend passthrough).
- `register_push_token(user_id, platform, device_token)` — upserts a device
  registration through the same relay.
- `save_subscriber(...)` — persist the {user_id, language} mapping in MongoDB
  so the scheduler knows which recipient IDs correspond to each language cohort.
- `subscribers_by_language(language)` — return recipient IDs for the scheduler.

The relay pattern is mandated by the Emergent push notification playbook —
DO NOT swap to a different provider or call the relay from the frontend.
Endpoints and payload shapes are exact.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Iterable

import httpx
from fastapi import HTTPException
from pydantic import BaseModel

logger = logging.getLogger("push")

PUSH_BASE_URL = "https://integrations.emergentagent.com"
PUSH_KEY = os.environ.get("EMERGENT_PUSH_KEY", "placeholder")

# Shared async client — reused across all outbound push calls so we don't
# reopen TLS connections on every trigger.
_client = httpx.AsyncClient(
    base_url=PUSH_BASE_URL,
    headers={"X-Push-Key": PUSH_KEY},
    timeout=10.0,
)


# ------------------------------ Pydantic --------------------------------


class RegisterPushBody(BaseModel):
    """Payload for POST /api/register-push.

    `language` is optional so old clients that don't send it still register;
    default is English. The scheduler groups recipients by this field to
    localise the daily notification content.
    """

    user_id: str
    platform: str  # "android" | "ios"
    device_token: str
    language: str | None = "en"


# ------------------------------ Relay -----------------------------------


async def register_push_token(user_id: str, platform: str, device_token: str) -> None:
    """Upsert a device registration in the Emergent push relay."""

    resp = await _client.post(
        "/api/v1/push/users/register",
        json={"user_id": user_id, "platform": platform, "device_token": device_token},
    )
    if resp.status_code == 401:
        raise HTTPException(500, "EMERGENT_PUSH_KEY missing or invalid")
    if resp.status_code >= 500:
        raise HTTPException(502, "Push provider unavailable")
    resp.raise_for_status()


async def send_push(
    recipients: list[str],
    data: dict[str, Any],
    idempotency_key: str | None = None,
) -> None:
    """Trigger a push notification through the Emergent relay.

    - `recipients`: list of `user_id` values already registered via
      `/api/register-push`. Max 100 per call (playbook constraint).
    - `data` must include `title` and `message`. Optional keys:
      `subtext`, `image_url`, `action_url`, `channel_id`.
    - `idempotency_key` recommended for retries (dedupes same intent).
    """

    if not recipients:
        return
    if len(recipients) > 100:
        raise ValueError("max 100 recipients per /trigger call; chunk before sending")
    if "title" not in data or "message" not in data:
        raise ValueError("data must include title and message")

    payload: dict[str, Any] = {"recipients": recipients, "data": data}
    if idempotency_key:
        payload["$idempotency_key"] = idempotency_key

    resp = await _client.post("/api/v1/push/trigger", json=payload)
    if resp.status_code == 401:
        raise HTTPException(500, "EMERGENT_PUSH_KEY missing or invalid")
    if resp.status_code >= 500:
        raise HTTPException(502, "Push provider unavailable")
    resp.raise_for_status()


# --------------------------- Subscriber store ---------------------------
# We persist a lightweight document per registered device so the scheduler
# can group recipients by language. Tokens themselves live inside the
# Emergent relay — we NEVER persist device_token in Mongo (per playbook).


async def save_subscriber(db: Any, user_id: str, language: str, platform: str) -> None:
    now = datetime.now(timezone.utc)
    await db["push_subscribers"].update_one(
        {"user_id": user_id},
        {
            "$set": {
                "user_id": user_id,
                "language": (language or "en").lower(),
                "platform": platform,
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )


async def subscribers_by_language(db: Any, language: str) -> list[str]:
    """Return `user_id`s subscribed to a given language cohort."""

    cursor = db["push_subscribers"].find({"language": language.lower()}, {"user_id": 1})
    return [doc["user_id"] async for doc in cursor]


async def all_languages(db: Any) -> list[str]:
    langs = await db["push_subscribers"].distinct("language")
    return [str(x).lower() for x in langs if x]


# ------------------------- Push history (24h) -------------------------
# v8.3.5 — Every push fired by the scheduler is also persisted here so
# premium users can re-read it later in the Market Brief page. The
# `sent_at` field is TTL-indexed at 24h, so records auto-expire and the
# next day's brief naturally replaces the previous day's.


async def ensure_history_indexes(db: Any) -> None:
    """Create the 24h TTL index. Safe to call repeatedly (idempotent)."""
    try:
        await db["push_history"].create_index("sent_at", expireAfterSeconds=24 * 3600)
        await db["push_history"].create_index([("language", 1), ("sent_at", -1)])
    except Exception:
        # Never let index creation crash startup — we'll retry on the next
        # scheduler tick.
        pass


async def save_history(
    db: Any,
    *,
    language: str,
    slot: str,
    title: str,
    body: str,
    action_url: str,
    market: str | None = None,
    signal_symbol: str | None = None,
    signal_action: str | None = None,
    signal_confidence: int | None = None,
    news_title: str | None = None,
) -> None:
    now = datetime.now(timezone.utc)
    doc = {
        "language": (language or "en").lower(),
        "slot": slot,
        "title": title,
        "body": body,
        "action_url": action_url,
        "market": market,
        "signal_symbol": signal_symbol,
        "signal_action": signal_action,
        "signal_confidence": signal_confidence,
        "news_title": news_title,
        "sent_at": now,
    }
    try:
        await db["push_history"].insert_one(doc)
    except Exception as e:
        logger.warning("push_history insert failed: %s", e)


async def get_history(db: Any, language: str, limit: int = 20) -> list[dict[str, Any]]:
    """Return the language cohort's push history within the last 24h,
    most recent first. Docs older than 24h are auto-removed by the TTL index.
    """
    cursor = (
        db["push_history"]
        .find({"language": (language or "en").lower()}, {"_id": 0})
        .sort("sent_at", -1)
        .limit(limit)
    )
    return [doc async for doc in cursor]


def chunk_recipients(recipients: Iterable[str], size: int = 100) -> list[list[str]]:
    """SuprSend enforces max 100 recipients per trigger — split before send."""

    bucket: list[str] = []
    out: list[list[str]] = []
    for r in recipients:
        bucket.append(r)
        if len(bucket) >= size:
            out.append(bucket)
            bucket = []
    if bucket:
        out.append(bucket)
    return out
