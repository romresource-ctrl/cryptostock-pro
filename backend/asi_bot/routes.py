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

import os
import re
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .crypto import decrypt, encrypt, mask
from .engine import execute_trade, preview_trade, refresh_trade_pnl
from .exchanges import EXCHANGE_DISPLAY, EXCHANGES, ExchangeId, validate_credentials
from .pnl import leaderboard, live_leaderboard, pnl_summary
from .whitelist import TOP_100_FUTURES, is_allowed

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


class TradePayload(BaseModel):
    exchange: Literal["binance", "bybit", "okx", "bitget"]
    symbol: str
    side: Literal["BUY", "SELL"]
    entry: float
    stop_loss: float
    take_profits: list[float] = Field(..., min_length=1, max_length=3)
    risk_pct: float = Field(5.0, ge=1.0, le=30.0)
    leverage: int = Field(10, ge=1, le=125)
    mode: Literal["semi", "full"] = "semi"


class BotConfigPayload(BaseModel):
    enabled: bool = False
    exchange: Literal["binance", "bybit", "okx", "bitget"]
    mode: Literal["semi", "full"] = "semi"
    max_trades_per_day: int = Field(5, ge=1, le=50)
    risk_pct: float = Field(5.0, ge=1.0, le=30.0)
    leverage: int = Field(10, ge=1, le=125)
    whitelist: list[str] = Field(default_factory=list)
    profile: Literal["confluence", "scalper", "day", "swing"] | None = None
    # v9.4.0 — Minimum confidence required to auto-execute (0-100).
    min_confidence: int = Field(75, ge=50, le=100)
    # v9.4.1 — Daily loss limit (USDT, absolute). 0 = disabled.
    daily_loss_limit_usdt: float = Field(0.0, ge=0.0, le=100_000.0)
    # Set to null to CLEAR previous auto-disable (when user re-enables manually).
    auto_disabled_reason: str | None = None
    auto_disabled_at: str | None = None


def register(app_api: APIRouter, db: Any) -> None:
    """Mount ASI-Bot routes onto an existing FastAPI APIRouter."""
    # Attach trade-level endpoints (defined below with `router` closure).
    _attach_trade_routes(db)

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


# Mounted via register(); keep extra endpoints under same router.
@router.get("/whitelist")
async def _get_whitelist() -> dict[str, Any]:
    return {"top_100": TOP_100_FUTURES, "count": len(TOP_100_FUTURES)}


@router.get("/server-ip")
async def _get_server_ip() -> dict[str, Any]:
    """v9.4.3 — Return the IP that exchange APIs ACTUALLY see.

    When ASI_PROXY_URL is set, trading traffic exits through the proxy,
    so we resolve the egress IP THROUGH the proxy — this is the address
    users must whitelist in Binance API Management.
    """
    import httpx
    proxy = os.environ.get("ASI_PROXY_URL") or os.environ.get("HTTPS_PROXY")
    ip = "143.198.197.107" if proxy else "35.193.209.116"
    try:
        async with httpx.AsyncClient(proxy=proxy, timeout=4.0) as client:
            r = await client.get("https://api.ipify.org?format=json")
            if r.status_code == 200:
                ip = r.json().get("ip", ip)
    except Exception:
        pass
    return {
        "ip": ip,
        "via_proxy": bool(proxy),
        "instructions": (
            "Masukkan IP ini ke 'Restrict access to trusted IPs only' "
            "di menu API Management Binance/exchange Anda."
        ),
    }


def _attach_trade_routes(db: Any) -> None:
    @router.post("/trades/preview")
    async def preview(payload: TradePayload, device_id: str = Query(..., min_length=4)):
        if not is_allowed(payload.symbol):
            raise HTTPException(400, f"{payload.symbol} tidak di whitelist Top-100.")
        doc = await db.asi_credentials.find_one({"_id": f"{device_id}:{payload.exchange}"})
        if not doc:
            raise HTTPException(404, "Hubungkan API exchange terlebih dahulu.")
        return await preview_trade(
            doc, payload.symbol, payload.side,
            payload.entry, payload.stop_loss, payload.take_profits,
            payload.risk_pct, payload.leverage,
        )

    @router.post("/trades/execute")
    async def execute(payload: TradePayload, device_id: str = Query(..., min_length=4)):
        if not is_allowed(payload.symbol):
            raise HTTPException(400, f"{payload.symbol} tidak di whitelist Top-100.")
        doc = await db.asi_credentials.find_one({"_id": f"{device_id}:{payload.exchange}"})
        if not doc:
            raise HTTPException(404, "Hubungkan API exchange terlebih dahulu.")
        res = await execute_trade(
            doc, payload.symbol, payload.side,
            payload.entry, payload.stop_loss, payload.take_profits,
            payload.risk_pct, payload.leverage, payload.mode,
        )
        if not res.get("ok"):
            raise HTTPException(400, res.get("message") or "Execute failed")
        margin_usdt = round(float(res["qty"]) * float(res["entry_price"]) / max(1, int(res["leverage"])), 2)
        rec = {**res, "device_id": device_id, "margin_usdt": margin_usdt}
        rec["_id"] = f"{device_id}:{res['entry_order_id']}" if res.get("entry_order_id") else None
        if rec["_id"]:
            await db.asi_trades.replace_one({"_id": rec["_id"]}, rec, upsert=True)
        return res

    @router.get("/trades")
    async def list_trades(device_id: str = Query(..., min_length=4), limit: int = 50):
        rows: list[dict[str, Any]] = []
        async for d in db.asi_trades.find({"device_id": device_id}).sort("created_at", -1).limit(limit):
            d.pop("_id", None)
            rows.append(d)
        return {"items": rows}

    @router.post("/trades/{trade_id}/refresh")
    async def refresh_trade(trade_id: str, device_id: str = Query(..., min_length=4)):
        doc = await db.asi_trades.find_one({"_id": f"{device_id}:{trade_id}"})
        if not doc:
            raise HTTPException(404, "Trade tidak ditemukan")
        cred = await db.asi_credentials.find_one({"_id": f"{device_id}:{doc['exchange']}"})
        if not cred:
            raise HTTPException(404, "Credential exchange tidak ditemukan")
        update = await refresh_trade_pnl(cred, doc)
        update["updated_at"] = _now_iso()
        await db.asi_trades.update_one({"_id": doc["_id"]}, {"$set": update})
        return {**doc, **update}

    @router.get("/pnl")
    async def pnl(device_id: str = Query(..., min_length=4)):
        return await pnl_summary(db, device_id)

    @router.get("/leaderboard")
    async def leader(period_days: int = Query(7, ge=1, le=90)):
        return {"items": await leaderboard(db, period_days=period_days, limit=10),
                "period_days": period_days}

    @router.get("/leaderboard/live")
    async def leader_live():
        """v9.4.0 — Only traders CURRENTLY in open positions, ranked by
        live unrealized PnL. Rows disappear automatically when positions
        close. No time-window parameter needed."""
        return {"items": await live_leaderboard(db, limit=10)}

    @router.get("/bot")
    async def get_bot(device_id: str = Query(..., min_length=4)):
        doc = await db.asi_bot_config.find_one({"_id": device_id})
        if not doc:
            return {"enabled": False, "exists": False}
        doc.pop("_id", None)
        return {**doc, "exists": True}

    @router.post("/bot")
    async def set_bot(payload: BotConfigPayload, device_id: str = Query(..., min_length=4)):
        doc = payload.model_dump()
        doc["device_id"] = device_id
        doc["_id"] = device_id
        doc["updated_at"] = _now_iso()
        await db.asi_bot_config.replace_one({"_id": device_id}, doc, upsert=True)
        return {"ok": True, **doc}
