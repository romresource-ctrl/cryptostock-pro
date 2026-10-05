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
from .engine import close_position, execute_trade, preview_trade, refresh_trade_pnl
from .exchanges import EXCHANGE_DISPLAY, EXCHANGES, ExchangeId, validate_credentials
from .pnl import leaderboard, live_leaderboard, pnl_summary
from .whitelist import TOP_100_FUTURES

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
    # v9.6.0 — TP strategy & trailing stop
    tp_count: Literal[1, 2, 3] = 3
    trailing_callback_rate: float = Field(2.0, ge=0.0, le=10.0)


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
    # v9.7.5 — Semi & Full are independent on/off states. The scheduler only
    # cares about full_enabled. Semi-Auto is a user-trigger flag.
    semi_enabled: bool = False
    full_enabled: bool = False
    # v9.6.0 — TP strategy. 1=TP1 100%, 2=TP1/TP2 50/50, 3=TP1/TP2/TP3 33/33/34.
    tp_count: Literal[1, 2, 3] = 3
    # v9.6.0 — Trailing stop callback rate %. 0 = disabled. Active after TP1.
    trailing_callback_rate: float = Field(2.0, ge=0.0, le=10.0)
    # Set to null to CLEAR previous auto-disable (when user re-enables manually).
    auto_disabled_reason: str | None = None
    auto_disabled_at: str | None = None
    # v9.7.7 — Disclaimer persistent: once ticked it stays acknowledged
    # across sessions. Frontend hides disclaimer card forever when True.
    disclaimer_ack: bool = False


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
            # v9.6.9 — Return JSON body with both `code` and `message` so
            # the frontend can translate per-locale. HTTPException(detail=...)
            # accepts dict and FastAPI serializes it as JSON.
            raise HTTPException(400, detail={
                "code": res.get("code") or "auth_failed",
                "message": res["message"],
            })
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


@router.get("/egress-ip")
async def _get_egress_ip() -> dict[str, Any]:
    """v9.7.1 — Diagnostic: report THIS backend's DIRECT egress IP
    (no proxy). Used to populate the Tinyproxy Allow list on the VPS.
    """
    import httpx
    ip = None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:  # NO proxy
            r = await client.get("https://api.ipify.org")
            if r.status_code == 200:
                ip = r.text.strip()
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}
    return {"ok": True, "egress_ip": ip}


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
        # v9.8.2 — whitelist statis Top-100 DIHAPUS. Engine memvalidasi
        # simbol secara dinamis terhadap daftar pasar exchange user.
        doc = await db.asi_credentials.find_one({"_id": f"{device_id}:{payload.exchange}"})
        if not doc:
            raise HTTPException(404, "Hubungkan API exchange terlebih dahulu.")
        return await preview_trade(
            doc, payload.symbol, payload.side,
            payload.entry, payload.stop_loss, payload.take_profits,
            payload.risk_pct, payload.leverage,
            tp_count=payload.tp_count,
        )

    @router.post("/trades/execute")
    async def execute(payload: TradePayload, device_id: str = Query(..., min_length=4)):
        # v9.8.2 — whitelist statis Top-100 DIHAPUS (lihat engine._ensure_tradable).
        doc = await db.asi_credentials.find_one({"_id": f"{device_id}:{payload.exchange}"})
        if not doc:
            raise HTTPException(404, "Hubungkan API exchange terlebih dahulu.")
        res = await execute_trade(
            doc, payload.symbol, payload.side,
            payload.entry, payload.stop_loss, payload.take_profits,
            payload.risk_pct, payload.leverage, payload.mode,
            tp_count=payload.tp_count,
            trailing_callback_rate=payload.trailing_callback_rate,
        )
        if not res.get("ok"):
            raise HTTPException(400, res.get("message") or "Execute failed")
        margin_usdt = round(float(res["qty"]) * float(res["entry_price"]) / max(1, int(res["leverage"])), 2)
        rec = {**res, "device_id": device_id, "margin_usdt": margin_usdt}
        rec["_id"] = f"{device_id}:{res['entry_order_id']}" if res.get("entry_order_id") else None
        if rec["_id"]:
            await db.asi_trades.replace_one({"_id": rec["_id"]}, rec, upsert=True)
        return res

    @router.post("/trades/{trade_id}/close")
    async def close_one_trade(trade_id: str, device_id: str = Query(..., min_length=4)):
        """v9.7.5 — Close ONE open position by trade _id."""
        t = await db.asi_trades.find_one({"_id": trade_id, "device_id": device_id})
        if not t:
            raise HTTPException(404, "trade not found")
        if t.get("status") != "open":
            return {"ok": True, "already_closed": True}
        cred = await db.asi_credentials.find_one({"_id": f"{device_id}:{t['exchange']}"})
        if not cred:
            raise HTTPException(400, "credential missing")
        try:
            await close_position(cred, t["symbol"], t["side"], float(t.get("qty") or 0))
            upd = await refresh_trade_pnl(cred, t)
            now = datetime.now(timezone.utc).isoformat()
            await db.asi_trades.update_one({"_id": t["_id"]}, {"$set": {
                "status": "closed", "close_reason": "manual",
                "closed_at": now, "updated_at": now,
                **{k: v for k, v in upd.items() if k in ("pnl_usdt", "mark_price")},
            }})
            return {"ok": True}
        except Exception as e:  # noqa: BLE001
            raise HTTPException(500, str(e)[:200])

    @router.post("/trades/close-all")
    async def close_all_trades(device_id: str = Query(..., min_length=4)):
        """v9.7.4 — Close ALL open positions for this device.

        Dipakai saat user menonaktifkan bot dan memilih menutup posisi.
        Native SL/TP orders di exchange ikut dibatalkan lewat
        engine.close_position (cancel_all_conditional di dalamnya).
        """
        open_trades = [
            d async for d in db.asi_trades.find(
                {"device_id": device_id, "status": "open"}
            )
        ]
        if not open_trades:
            return {"ok": True, "closed": 0, "errors": []}
        closed_ok = 0
        errors: list[dict[str, str]] = []
        for t in open_trades:
            try:
                cred = await db.asi_credentials.find_one(
                    {"_id": f"{device_id}:{t['exchange']}"}
                )
                if not cred:
                    errors.append({"symbol": t.get("symbol", "?"), "error": "credential missing"})
                    continue
                await close_position(cred, t["symbol"], t["side"], float(t.get("qty") or 0))
                upd = await refresh_trade_pnl(cred, t)
                now = datetime.now(timezone.utc).isoformat()
                await db.asi_trades.update_one(
                    {"_id": t["_id"]},
                    {"$set": {
                        "status": "closed",
                        "close_reason": "manual_close_all",
                        "closed_at": now,
                        "updated_at": now,
                        **{k: v for k, v in upd.items() if k in ("pnl_usdt", "mark_price")},
                    }},
                )
                closed_ok += 1
            except Exception as e:  # noqa: BLE001
                errors.append({"symbol": t.get("symbol", "?"), "error": str(e)[:200]})
        return {"ok": not errors, "closed": closed_ok, "errors": errors}

    @router.get("/trades")
    async def list_trades(device_id: str = Query(..., min_length=4), limit: int = 50):
        rows: list[dict[str, Any]] = []
        async for d in db.asi_trades.find({"device_id": device_id}).sort("created_at", -1).limit(limit):
            # v9.7.6 — keep `_id` so frontend can call POST /trades/{id}/close
            tid = d.pop("_id", None)
            if tid is not None:
                d["_id"] = str(tid)
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
