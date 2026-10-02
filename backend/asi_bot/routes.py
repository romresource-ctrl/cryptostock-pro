"""ASI-Bot — Phase 1 API: credential management.

Routes (prefixed /api/asi):
  POST   /credentials          - add/replace API key for an exchange
  GET    /credentials          - list user's connected exchanges (masked)
  DELETE /credentials/{ex_id}  - remove a connection
  POST   /credentials/{ex_id}/test - re-validate a stored key

Caller identity: `device_id` for now (reuses existing premium entitlement
device). Phase 4 will optionally bind to an auth user id if present.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .crypto import decrypt, encrypt, mask
from .exchanges import EXCHANGE_DISPLAY, EXCHANGES, ExchangeId, validate_credentials

router = APIRouter(prefix="/asi", tags=["asi-bot"])


def _initials_from_email(email: str | None, device_id: str) -> str:
    """3-letter anonymous handle: first 3 non-dot chars of email prefix,
    uppercased; falls back to deterministic hash of device_id."""
    if email:
        prefix = re.sub(r"[^A-Za-z]", "", email.split("@")[0])
        if len(prefix) >= 3:
            return prefix[:3].upper()
    import hashlib
    h = hashlib.sha256(device_id.encode()).hexdigest().upper()
    return "".join(c for c in h if c.isalpha())[:3] or "USR"


class SaveCredentialPayload(BaseModel):
    exchange: Literal["binance", "bybit", "okx", "bitget"]
    api_key: str = Field(..., min_length=10, max_length=256)
    api_secret: str = Field(..., min_length=10, max_length=256)
    password: str | None = Field(None, max_length=256)  # OKX/Bitget passphrase
    testnet: bool = True
    email: str | None = None  # optional for leaderboard initials


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def register(app_api: APIRouter, db: Any) -> None:
    """Mount ASI-Bot routes onto an existing FastAPI APIRouter."""

    @router.post("/credentials")
    async def save_credential(payload: SaveCredentialPayload,
                              device_id: str = Query(..., min_length=4)):
        res = await validate_credentials(
            payload.exchange, payload.api_key, payload.api_secret,
            payload.password, payload.testnet,
        )
        if not res["ok"]:
            raise HTTPException(400, res["message"])
        enc_key = encrypt(payload.api_key)
        enc_sec = encrypt(payload.api_secret)
        enc_pwd = encrypt(payload.password) if payload.password else None
        now = _now_iso()
        doc = {
            "_id": f"{device_id}:{payload.exchange}",
            "device_id": device_id,
            "exchange": payload.exchange,
            "testnet": bool(payload.testnet),
            "api_key_enc": enc_key,
            "api_secret_enc": enc_sec,
            "password_enc": enc_pwd,
            "permissions": res.get("permissions"),
            "api_key_mask": mask(payload.api_key),
            "handle": _initials_from_email(payload.email, device_id),
            "created_at": now,
            "updated_at": now,
        }
        await db.asi_credentials.replace_one({"_id": doc["_id"]}, doc, upsert=True)
        return {
            "ok": True, "exchange": payload.exchange,
            "display": EXCHANGE_DISPLAY[payload.exchange],
            "testnet": payload.testnet, "api_key_mask": doc["api_key_mask"],
            "handle": doc["handle"], "message": "Koneksi API tersimpan aman (AES-256-GCM).",
        }

    @router.get("/credentials")
    async def list_credentials(device_id: str = Query(..., min_length=4)):
        out = []
        async for d in db.asi_credentials.find(
            {"device_id": device_id},
            {"_id": 0, "api_key_enc": 0, "api_secret_enc": 0, "password_enc": 0},
        ):
            d["display"] = EXCHANGE_DISPLAY.get(d.get("exchange"), d.get("exchange"))
            out.append(d)
        return {"items": out, "supported_exchanges": [
            {"id": x, "display": EXCHANGE_DISPLAY[x]} for x in EXCHANGES
        ]}

    @router.delete("/credentials/{exchange}")
    async def delete_credential(exchange: ExchangeId,
                                device_id: str = Query(..., min_length=4)):
        r = await db.asi_credentials.delete_one({"_id": f"{device_id}:{exchange}"})
        return {"deleted": r.deleted_count}

    @router.post("/credentials/{exchange}/test")
    async def test_credential(exchange: ExchangeId,
                              device_id: str = Query(..., min_length=4)):
        doc = await db.asi_credentials.find_one({"_id": f"{device_id}:{exchange}"})
        if not doc:
            raise HTTPException(404, "Credential tidak ditemukan")
        res = await validate_credentials(
            exchange,
            decrypt(doc["api_key_enc"]), decrypt(doc["api_secret_enc"]),
            decrypt(doc["password_enc"]) if doc.get("password_enc") else None,
            bool(doc.get("testnet", True)),
        )
        return res

    app_api.include_router(router)
