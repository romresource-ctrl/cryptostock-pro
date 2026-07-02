"""Duration-based unlock code management with device binding.

Replaces the older offline SHA-256 hash scheme. New codes are:
- Generated server-side (random) and stored in MongoDB `unlock_codes`.
- Tied to an email + duration + optional device fingerprint.
- Verified against the DB with expiry & device-match checks.

Legacy offline codes are INVALIDATED per user request.

Collection: `unlock_codes`
Document shape:
{
  "_id": "XXXX-XXXX-XXXX",       # code (uppercase hex, 12 chars w/ dashes)
  "email": "user@example.com",   # normalized (lower, trimmed)
  "duration": "monthly" | "quarterly" | "half_year" | "yearly" | "lifetime",
  "issued_at": iso8601,
  "expires_at": iso8601 | null,  # None = lifetime
  "device_id": str | null,       # null before first login, set on first verify
  "device_name": str | null,
  "first_used_at": iso8601 | null,
  "last_used_at": iso8601 | null,
  "login_count": int,
  "revoked": bool,
}
"""
from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from motor.motor_asyncio import AsyncIOMotorDatabase

Duration = Literal["monthly", "quarterly", "half_year", "yearly", "lifetime"]

DURATION_DAYS: dict[str, int | None] = {
    "monthly": 30,
    "quarterly": 90,
    "half_year": 180,
    "yearly": 365,
    "lifetime": None,
}

DURATION_LABEL: dict[str, str] = {
    "monthly": "Monthly (30 days)",
    "quarterly": "Quarterly (90 days)",
    "half_year": "Half Year (180 days)",
    "yearly": "Yearly (365 days)",
    "lifetime": "Lifetime",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _fmt(code_hex: str) -> str:
    c = code_hex.upper()
    return f"{c[0:4]}-{c[4:8]}-{c[8:12]}"


def _random_code() -> str:
    """12 uppercase hex chars formatted as XXXX-XXXX-XXXX. ~68 bits entropy."""
    raw = secrets.token_hex(6)  # 12 hex chars
    return _fmt(raw)


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


async def generate_code(
    db: AsyncIOMotorDatabase,
    email: str,
    duration: Duration,
) -> dict[str, Any]:
    """Create a new unlock code for an email + duration. Not device-bound yet."""
    if duration not in DURATION_DAYS:
        raise ValueError(f"Invalid duration: {duration}")
    email = normalize_email(email)
    if not email or "@" not in email:
        raise ValueError("Invalid email")

    # Collision-safe generation (extremely unlikely, but be defensive)
    for _ in range(6):
        code = _random_code()
        exists = await db.unlock_codes.find_one({"_id": code}, {"_id": 1})
        if not exists:
            break
    else:
        raise RuntimeError("Failed to generate unique code after retries")

    days = DURATION_DAYS[duration]
    expires_at = (_now() + timedelta(days=days)).isoformat() if days else None
    doc = {
        "_id": code,
        "email": email,
        "duration": duration,
        "issued_at": _now_iso(),
        "expires_at": expires_at,
        "device_id": None,
        "device_name": None,
        "first_used_at": None,
        "last_used_at": None,
        "login_count": 0,
        "revoked": False,
    }
    await db.unlock_codes.insert_one(doc)
    return {
        "code": code,
        "email": email,
        "duration": duration,
        "expires_at": expires_at,
        "issued_at": doc["issued_at"],
    }


async def verify_code(
    db: AsyncIOMotorDatabase,
    email: str,
    code: str,
    device_id: str | None,
    device_name: str | None,
) -> dict[str, Any]:
    """Verify code for email on a given device.

    Returns a dict with:
      { ok: bool, reason: str | None, expires_at: str | None,
        duration: str | None, email: str }

    Rules:
      - Code must exist and email must match
      - Not revoked
      - Not expired (unless lifetime)
      - Device binding:
          * If code has no device_id yet → bind to current device (first-time)
          * If code has device_id → must match current device_id
    """
    code = (code or "").strip().upper()
    email = normalize_email(email)
    doc = await db.unlock_codes.find_one({"_id": code})
    if not doc:
        return {"ok": False, "reason": "invalid_code", "email": email}
    if doc.get("email") != email:
        return {"ok": False, "reason": "email_mismatch", "email": email}
    if doc.get("revoked"):
        return {"ok": False, "reason": "revoked", "email": email}

    exp = doc.get("expires_at")
    if exp:
        try:
            exp_dt = datetime.fromisoformat(exp)
        except Exception:
            exp_dt = None
        if exp_dt and exp_dt <= _now():
            return {
                "ok": False,
                "reason": "expired",
                "email": email,
                "expires_at": exp,
                "duration": doc.get("duration"),
            }

    stored_dev = doc.get("device_id")
    now_iso = _now_iso()
    update: dict[str, Any] = {"last_used_at": now_iso}
    if stored_dev is None:
        # First-time bind
        update["device_id"] = device_id
        update["device_name"] = device_name
        update["first_used_at"] = now_iso
        update["login_count"] = doc.get("login_count", 0) + 1
    elif stored_dev == device_id:
        update["login_count"] = doc.get("login_count", 0) + 1
    else:
        return {
            "ok": False,
            "reason": "device_mismatch",
            "email": email,
            "device_name": doc.get("device_name"),
        }

    await db.unlock_codes.update_one({"_id": code}, {"$set": update})
    return {
        "ok": True,
        "reason": None,
        "email": email,
        "duration": doc.get("duration"),
        "expires_at": doc.get("expires_at"),
        "device_id": update.get("device_id", stored_dev),
    }


async def list_codes(db: AsyncIOMotorDatabase) -> list[dict[str, Any]]:
    """Return all codes sorted by issued_at desc (for admin dashboard)."""
    out: list[dict[str, Any]] = []
    async for d in db.unlock_codes.find().sort("issued_at", -1):
        d["code"] = d.pop("_id")
        out.append(d)
    return out


async def revoke_code(db: AsyncIOMotorDatabase, code: str) -> bool:
    """Mark a code as revoked (invalidates future logins)."""
    r = await db.unlock_codes.update_one({"_id": code.upper()}, {"$set": {"revoked": True}})
    return r.modified_count > 0


async def delete_code(db: AsyncIOMotorDatabase, code: str) -> bool:
    """Fully delete a code from DB."""
    r = await db.unlock_codes.delete_one({"_id": code.upper()})
    return r.deleted_count > 0


async def reset_device_binding(db: AsyncIOMotorDatabase, code: str) -> bool:
    """Clear device binding (allows re-bind to a new device on next login)."""
    r = await db.unlock_codes.update_one(
        {"_id": code.upper()},
        {"$set": {"device_id": None, "device_name": None, "first_used_at": None}},
    )
    return r.modified_count > 0
