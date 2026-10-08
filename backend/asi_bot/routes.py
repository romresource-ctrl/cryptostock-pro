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

import asyncio
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .crypto import decrypt, encrypt, mask
from .engine import (
    close_position, execute_trade, preview_trade, refresh_trade_pnl,
    resolve_credential,
)
from .exchanges import EXCHANGE_DISPLAY, EXCHANGES, ExchangeId, validate_credentials
from .pnl import leaderboard, live_leaderboard, pnl_summary
from .whitelist import TOP_100_FUTURES
from . import binance_rest as br

logger = logging.getLogger("asi_bot.routes")



async def _cancel_pending_limit(db: Any, t: dict, reason: str) -> None:
    """v9.9.13 — Batalkan order LIMIT entry yang masih pending (belum
    pernah membuka posisi) lalu tandai trade cancelled/expired."""
    cred = await resolve_credential(
        db, t["device_id"], t["exchange"], bool(t.get("testnet", True)))
    if cred and (t.get("exchange") or "").lower() == "binance":
        try:
            bin_sym = (str(t.get("symbol") or "").upper()
                       .split("/")[0].split("USDT")[0].split("-")[0] + "USDT")
            await br.cancel_order(
                decrypt(cred["api_key_enc"]), decrypt(cred["api_secret_enc"]),
                bool(cred.get("testnet", True)),
                symbol=bin_sym, order_id=t.get("entry_order_id"))
        except Exception:
            pass
    now = datetime.now(timezone.utc).isoformat()
    await db.asi_trades.update_one(
        {"_id": t["_id"]},
        {"$set": {"status": "cancelled", "close_reason": reason,
                  "closed_at": now, "updated_at": now}},
    )

router = APIRouter(prefix="/asi", tags=["asi-bot"])

# v9.9.9 — module-level DB ref supaya endpoint di luar closure register()
# (price, balance, egress-ip) bisa mengakses Mongo.
_DB: Any = None

# v9.9.13 — Cache harga 1 detik per simbol untuk endpoint batch /prices
# (dipoll tiap 2 detik oleh UI Recent Trades untuk mark price realtime).
_PX_CACHE: dict[str, tuple[float, float]] = {}


@router.get("/prices")
async def get_prices(symbols: str = Query(..., min_length=2, max_length=200)):
    """v9.9.13 — Batch harga live Binance Futures (public, via proxy SG).
    Dipakai Recent Trades untuk mark price realtime posisi open.
    Maks 10 simbol per call; cache 1 detik per simbol."""
    import time as _time

    import httpx as _hx
    syms = []
    for s in symbols.split(","):
        s = s.strip().upper().replace("/", "").replace("USDT", "")
        if s:
            syms.append(s + "USDT")
    syms = syms[:10]
    now = _time.time()
    out: dict[str, float] = {}
    missing: list[str] = []
    for s in syms:
        hit = _PX_CACHE.get(s)
        if hit and now - hit[0] < 1.0:
            out[s] = hit[1]
        else:
            missing.append(s)
    if missing:
        async with _hx.AsyncClient(proxy=os.environ.get("ASI_PROXY_URL"), timeout=8.0) as c:
            if len(missing) == 1:
                r = await c.get(
                    f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={missing[0]}")
                if r.status_code == 200:
                    p = float(r.json()["price"])
                    _PX_CACHE[missing[0]] = (now, p)
                    out[missing[0]] = p
            else:
                r = await c.get("https://fapi.binance.com/fapi/v1/ticker/price")
                if r.status_code == 200:
                    want = set(missing)
                    for row in r.json():
                        s = row.get("symbol")
                        if s in want:
                            p = float(row["price"])
                            _PX_CACHE[s] = (now, p)
                            out[s] = p
    return {"prices": out}


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
    # v9.9.13 — Profil formula yang dipakai saat eksekusi (untuk label
    # formula di kartu Recent Trades).
    profile: str | None = None
    # Tag singkat modul yang memicu (mis. "John Wick Candle Stick").
    formula_tag: str | None = None
    # v10.0.1 — Tipe eksekusi entry: "limit" (moderate, default) atau
    # "market" (instan, SL/TP di-anchor ke fill aktual).
    entry_mode: Literal["limit", "market"] = "limit"
    # v9.6.0 — TP strategy & trailing stop
    tp_count: Literal[1, 2, 3] = 3
    trailing_callback_rate: float = Field(2.0, ge=0.0, le=10.0)
    # v9.9.0 — Margin mode dipilih user sebelum eksekusi (wajib).
    # Default ISOLATED: kerugian terbatas pada margin posisi saja.
    margin_mode: Literal["isolated", "cross"] = "isolated"
    # v9.9.5 — Network mana yang dipakai. None → ikuti active_testnet di
    # bot config (switch di halaman ASI-Bot). Credential mainnet/testnet
    # disimpan di slot terpisah sehingga switching tanpa input ulang.
    testnet: bool | None = None


# v10.0.14 — Payload sinyal masuk dari engine eksternal (WunderTrading)
# via webhook POST /asi/webhook/cloud. Nama di UI = "Titan-Bot"
# (white-label). Secret token dibagikan ke engine untuk mencegah spam.
class CloudSignalPayload(BaseModel):
    secret: str = Field(..., min_length=8, max_length=256)
    symbol: str = Field(..., min_length=2, max_length=20)
    side: Literal["BUY", "SELL", "LONG", "SHORT", "buy", "sell", "long", "short"]
    entry: float = Field(..., gt=0)
    stop_loss: float = Field(..., gt=0)
    take_profits: list[float] = Field(..., min_length=1, max_length=3)
    risk_pct: float | None = Field(None, ge=0.1, le=30.0)
    leverage: int | None = Field(None, ge=1, le=125)
    confidence: int | None = Field(None, ge=0, le=100)
    source_tag: str | None = Field(None, max_length=64)
    strategy_name: str | None = Field(None, max_length=64)


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
    # v10.0.1 — Tipe eksekusi entry bot: limit (moderate) / market.
    entry_mode: Literal["limit", "market"] = "limit"
    auto_disabled_at: str | None = None
    # v9.7.7 — Disclaimer persistent: once ticked it stays acknowledged
    # across sessions. Frontend hides disclaimer card forever when True.
    disclaimer_ack: bool = False
    # v9.9.0 — Default margin mode bot (dipakai Full-Auto & default sheet).
    margin_mode: Literal["isolated", "cross"] = "isolated"
    # v9.9.5 — Network aktif (testnet/mainnet) untuk Semi & Full-Auto.
    # Diubah via switch jaringan di halaman ASI-Bot; credential tiap
    # jaringan disimpan di slot terpisah.
    active_testnet: bool = True
    # v10.0.14 — Sumber sinyal eksekusi.
    #   asi_bot    → formula internal (Confluence v9 / VWAP engines)
    #   cloud_pro  → sinyal eksternal "Titan-Bot" via webhook
    #   hybrid     → terima dari keduanya
    # White-label: nama "Titan-Bot" di UI, backend memakai webhook
    # eksternal (WunderTrading) sebagai salah satu feeder.
    signal_source: Literal["asi_bot", "cloud_pro", "hybrid"] = "asi_bot"


def register(app_api: APIRouter, db: Any) -> None:
    """Mount ASI-Bot routes onto an existing FastAPI APIRouter."""
    global _DB
    _DB = db
    # Attach trade-level endpoints (defined below with `router` closure).
    _attach_trade_routes(db)

    async def _migrate_same_key_history(db: Any, device_id: str,
                                        exchange: str, testnet: bool) -> int:
        """v10.0.6 — REINSTALL/DEVICE-CHANGE RECOVERY.

        Bila user reinstall app, device ID bisa berubah (signing key baru /
        vendor ID reset). Credential lama yatim di device lama → riwayat
        trade "hilang" dari Recent Trades dan posisi open lama tidak bisa
        direconcile scheduler (phantom open di leaderboard).

        Bila API key yang SAMA ditemukan di device lain (exchange + network
        sama), pindahkan trade + bot config device lama ke device ini dan
        hapus credential yatim. Return jumlah device lama yang dimigrasi.
        """
        net = "testnet" if testnet else "mainnet"
        my_doc = await db.asi_credentials.find_one(
            {"_id": f"{device_id}:{exchange}:{net}"})
        if not my_doc:
            return 0
        try:
            my_key = decrypt(my_doc["api_key_enc"])
        except Exception:
            return 0
        # Query murah dulu: ada kandidat device lain di exchange+net ini?
        candidates = await db.asi_credentials.find(
            {"exchange": exchange, "testnet": bool(testnet),
             "device_id": {"$ne": device_id}},
            {"device_id": 1, "api_key_enc": 1}).to_list(20)
        migrated = 0
        now = _now_iso()
        for cand in candidates:
            try:
                if decrypt(cand["api_key_enc"]) != my_key:
                    continue
            except Exception:
                continue
            old_dev = cand["device_id"]
            # Pindahkan trade (exchange+network sama saja) ke device baru.
            await db.asi_trades.update_many(
                {"device_id": old_dev, "exchange": exchange,
                 "testnet": bool(testnet)},
                {"$set": {"device_id": device_id, "updated_at": now}})
            # Pindahkan bot config bila device baru belum punya.
            old_cfg = await db.asi_bot_config.find_one({"_id": old_dev})
            new_cfg = await db.asi_bot_config.find_one({"_id": device_id})
            if old_cfg and not new_cfg:
                old_cfg.pop("_id", None)
                old_cfg["device_id"] = device_id
                old_cfg["updated_at"] = now
                await db.asi_bot_config.replace_one(
                    {"_id": device_id}, old_cfg, upsert=True)
                await db.asi_bot_config.delete_one({"_id": old_dev})
            # Hapus credential yatim supaya tidak dipakai scheduler 2×.
            await db.asi_credentials.delete_one({"_id": cand["_id"]})
            migrated += 1
            logger.info(
                "ASI credential migration: %s (%s/%s) -> %s",
                old_dev, exchange, net, device_id)
        return migrated

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
        # v9.9.5 — Dual slot: mainnet & testnet disimpan terpisah agar
        # switching jaringan tidak meminta API key ulang.
        net = "testnet" if payload.testnet else "mainnet"
        doc = {
            "_id": f"{device_id}:{payload.exchange}:{net}",
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
        # v10.0.6 — Setelah reconnect (mis. pasca reinstall), pindahkan
        # riwayat trade dari device lama yang memakai API key sama.
        try:
            migrated = await _migrate_same_key_history(
                db, device_id, payload.exchange, bool(payload.testnet))
            if migrated:
                logger.info("migrated history from %d old device(s)", migrated)
        except Exception as e:  # noqa: BLE001
            logger.warning("history migration failed: %s", e)
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
        # v10.0.6 — Lazy self-heal: bila device ini punya credential yang
        # API key-nya juga terdaftar di device LAMA (reinstall), pindahkan
        # riwayat trade otomatis. Query kandidat murah; no-op bila tidak
        # ada duplikat lintas device.
        for d in out:
            try:
                await _migrate_same_key_history(
                    db, device_id, d.get("exchange"), bool(d.get("testnet")))
            except Exception as e:  # noqa: BLE001
                logger.warning("lazy history migration failed: %s", e)
        return {"items": out, "supported_exchanges": [
            {"id": x, "display": EXCHANGE_DISPLAY[x]} for x in EXCHANGES
        ]}

    @router.delete("/credentials/{exchange}")
    async def delete_credential(exchange: ExchangeId,
                                device_id: str = Query(..., min_length=4),
                                testnet: bool | None = Query(None)):
        # v9.9.5 — testnet param opsional: hapus 1 slot saja. Tanpa param
        # → hapus semua slot (legacy + mainnet + testnet).
        if testnet is not None:
            net = "testnet" if testnet else "mainnet"
            r = await db.asi_credentials.delete_one({"_id": f"{device_id}:{exchange}:{net}"})
            return {"deleted": r.deleted_count}
        r = await db.asi_credentials.delete_many({
            "device_id": device_id, "exchange": exchange,
        })
        return {"deleted": r.deleted_count}

    @router.post("/credentials/{exchange}/test")
    async def test_credential(exchange: ExchangeId,
                              device_id: str = Query(..., min_length=4),
                              testnet: bool | None = Query(None)):
        doc = await resolve_credential(db, device_id, exchange, testnet)
        if not doc:
            raise HTTPException(404, "Credential tidak ditemukan untuk jaringan ini")
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


@router.get("/price")
async def get_price(symbol: str = Query(..., min_length=2, max_length=20)):
    """v9.9.9 — Harga live Binance Futures (public, via proxy SG).
    Dipakai Copy Trade untuk entry copy pada harga pasar SAAT INI,
    bukan harga entry lama trader yang di-copy."""
    import httpx as _hx
    base = symbol.upper().replace("/", "").replace("USDT", "") + "USDT"
    async with _hx.AsyncClient(proxy=os.environ.get("ASI_PROXY_URL"), timeout=10.0) as c:
        r = await c.get(f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={base}")
    if r.status_code != 200:
        raise HTTPException(400, f"Simbol {base} tidak ditemukan di Binance Futures")
    return {"symbol": base, "price": float(r.json()["price"])}



@router.get("/balance")
async def get_balance(device_id: str = Query(..., min_length=4),
                      exchange: ExchangeId = Query("binance")):
    """v9.9.9 — Saldo USDT available dari exchange untuk KEDUA jaringan
    (demo/testnet + real/mainnet) sekaligus. Ditampilkan sebagai 2 kartu
    di atas Recent Trades; di-refresh frontend bersama siklus PnL."""
    from .engine import _get_client, _fetch_usdt_balance
    from . import binance_rest as br

    async def _one(testnet: bool) -> dict[str, Any]:
        cred = await resolve_credential(_DB, device_id, exchange, testnet)
        if not cred:
            return {"connected": False, "available_usdt": None}
        try:
            if exchange == "binance":
                bal = await br.available_usdt(
                    decrypt(cred["api_key_enc"]), decrypt(cred["api_secret_enc"]),
                    bool(cred.get("testnet", True)),
                )
            else:
                client = await _get_client(cred)
                try:
                    bal = await _fetch_usdt_balance(client)
                finally:
                    try:
                        await client.close()
                    except Exception:
                        pass
            return {"connected": True, "available_usdt": round(float(bal), 2)}
        except Exception:  # noqa: BLE001
            return {"connected": True, "available_usdt": None}

    demo, real = await asyncio.gather(_one(True), _one(False))
    return {"ok": True, "demo": demo, "real": real}

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


async def _resolve_trade_cred(db: Any, device_id: str, exchange: str,
                              requested_testnet: bool | None) -> dict[str, Any] | None:
    """v9.9.5 — Tentukan network: payload → bot config active_testnet →
    legacy (None = pakai credential apa pun yang ada, perilaku lama)."""
    net = requested_testnet
    if net is None:
        cfg = await db.asi_bot_config.find_one({"_id": device_id})
        if cfg and "active_testnet" in cfg:
            net = bool(cfg.get("active_testnet"))
    return await resolve_credential(db, device_id, exchange, net)


def _attach_trade_routes(db: Any) -> None:
    @router.post("/trades/preview")
    async def preview(payload: TradePayload, device_id: str = Query(..., min_length=4)):
        # v9.8.2 — whitelist statis Top-100 DIHAPUS. Engine memvalidasi
        # simbol secara dinamis terhadap daftar pasar exchange user.
        doc = await _resolve_trade_cred(db, device_id, payload.exchange, payload.testnet)
        if not doc:
            raise HTTPException(404, "Hubungkan API exchange untuk jaringan ini terlebih dahulu.")
        return await preview_trade(
            doc, payload.symbol, payload.side,
            payload.entry, payload.stop_loss, payload.take_profits,
            payload.risk_pct, payload.leverage,
            tp_count=payload.tp_count,
        )

    @router.post("/trades/execute")
    async def execute(payload: TradePayload, device_id: str = Query(..., min_length=4)):
        # v9.8.2 — whitelist statis Top-100 DIHAPUS (lihat engine._ensure_tradable).
        doc = await _resolve_trade_cred(db, device_id, payload.exchange, payload.testnet)
        if not doc:
            raise HTTPException(404, "Hubungkan API exchange untuk jaringan ini terlebih dahulu.")
        res = await execute_trade(
            doc, payload.symbol, payload.side,
            payload.entry, payload.stop_loss, payload.take_profits,
            payload.risk_pct, payload.leverage, payload.mode,
            tp_count=payload.tp_count,
            trailing_callback_rate=payload.trailing_callback_rate,
            margin_mode=payload.margin_mode,
            profile=payload.profile,
            formula_tag=payload.formula_tag,
            entry_mode=payload.entry_mode,
        )
        if not res.get("ok"):
            # v9.9.2 — Pass through structured reason & message so frontend
            # can show user-friendly dialog (rollback vs margin mismatch
            # vs min notional, etc.). HTTPException(detail=dict) → JSON.
            raise HTTPException(400, detail={
                "code": res.get("reason") or "execute_failed",
                "message": res.get("message") or "Execute failed",
                "rollback_done": bool(res.get("rollback_done")),
                "requires_manual_action": bool(res.get("requires_manual_action")),
            })
        margin_usdt = round(float(res["qty"]) * float(res["entry_price"]) / max(1, int(res["leverage"])), 2)
        rec = {**res, "device_id": device_id, "margin_usdt": margin_usdt}
        rec["_id"] = f"{device_id}:{res['entry_order_id']}" if res.get("entry_order_id") else None
        if rec["_id"]:
            await db.asi_trades.replace_one({"_id": rec["_id"]}, rec, upsert=True)
        # v9.9.4 — LAYERING: lebur row trade lama pada simbol yang sama
        # ke row baru (Binance one-way mode menggabungkan posisi fisik;
        # DB harus mencerminkan hal yang sama agar PnL tidak ganda).
        # v9.9.13 — LIMIT entry: merge row layering DITUNDA sampai order
        # benar-benar terisi (dilakukan scheduler _process_pending_entries).
        # Jika di-merge sekarang dan limit tidak terisi, row posisi lama
        # akan hilang dari daftar padahal posisi masih terbuka.
        if res.get("layered") and rec.get("_id") and not res.get("pending"):
            base_sym = payload.symbol.upper().split("/")[0].split("USDT")[0].split("-")[0]
            now = datetime.now(timezone.utc).isoformat()
            old_rows = [
                d async for d in db.asi_trades.find({
                    "device_id": device_id, "exchange": payload.exchange,
                    "symbol": base_sym, "status": "open",
                    "_id": {"$ne": rec["_id"]},
                })
            ]
            if old_rows:
                await db.asi_trades.update_many(
                    {"_id": {"$in": [d["_id"] for d in old_rows]}},
                    {"$set": {
                        "status": "layered",
                        "close_reason": "merged_into_layer",
                        "merged_into": rec["_id"],
                        "closed_at": now, "updated_at": now,
                    }},
                )
                await db.asi_trades.update_one(
                    {"_id": rec["_id"]},
                    {"$set": {"layer_count": len(old_rows) + 1}},
                )
        return res

    @router.post("/trades/{trade_id}/close")
    async def close_one_trade(trade_id: str, device_id: str = Query(..., min_length=4)):
        """v9.7.5 — Close ONE open position by trade _id."""
        t = await db.asi_trades.find_one({"_id": trade_id, "device_id": device_id})
        if not t:
            raise HTTPException(404, "trade not found")
        # v9.9.13 — Pending LIMIT entry: belum ada posisi → cukup batalkan
        # order limit di exchange, jangan kirim market close.
        if str(t.get("status") or "").lower() == "pending_entry":
            await _cancel_pending_limit(db, t, "cancelled_pending")
            return {"ok": True, "cancelled_pending": True}
        if t.get("status") != "open":
            return {"ok": True, "already_closed": True}
        cred = await resolve_credential(
            db, device_id, t["exchange"], bool(t.get("testnet", True)))
        if not cred:
            raise HTTPException(400, "credential missing")
        try:
            await close_position(cred, t["symbol"], t["side"], float(t.get("qty") or 0))
            upd = await refresh_trade_pnl(cred, t)
            now = datetime.now(timezone.utc).isoformat()
            await db.asi_trades.update_one({"_id": t["_id"]}, {"$set": {
                "status": "closed", "close_reason": "manual",
                "closed_at": now, "updated_at": now,
                **{k: v for k, v in upd.items() if k in ("pnl_usdt", "mark_price", "closed_price")},
            }})
            return {"ok": True}
        except Exception as e:  # noqa: BLE001
            raise HTTPException(500, str(e)[:200])

    @router.delete("/trades/{trade_id}")
    async def delete_trade(trade_id: str, device_id: str = Query(..., min_length=4)):
        """v9.9.13 — Hapus kartu dari history Recent Trades. Hanya untuk
        trade yang sudah selesai (closed/layered/expired/cancelled) —
        posisi open/pending harus di-close/cancel dulu."""
        t = await db.asi_trades.find_one({"_id": trade_id, "device_id": device_id})
        if not t:
            raise HTTPException(404, "trade not found")
        if str(t.get("status") or "").lower() in ("open", "pending_entry"):
            raise HTTPException(
                400, "Posisi aktif tidak bisa dihapus — tutup/batalkan dulu.")
        await db.asi_trades.delete_one({"_id": t["_id"]})
        return {"ok": True}

    @router.post("/trades/close-all")
    async def close_all_trades(device_id: str = Query(..., min_length=4)):
        """v9.7.4 — Close ALL open positions for this device.

        Dipakai saat user menonaktifkan bot dan memilih menutup posisi.
        Native SL/TP orders di exchange ikut dibatalkan lewat
        engine.close_position (cancel_all_conditional di dalamnya).
        """
        # v9.9.13 — sertakan pending LIMIT entry: dibatalkan, bukan di-close.
        pendings = [
            d async for d in db.asi_trades.find(
                {"device_id": device_id, "status": "pending_entry"}
            )
        ]
        for p in pendings:
            await _cancel_pending_limit(db, p, "cancelled_pending")
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
                cred = await resolve_credential(
                    db, device_id, t["exchange"], bool(t.get("testnet", True)))
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
                        **{k: v for k, v in upd.items() if k in ("pnl_usdt", "mark_price", "closed_price")},
                    }},
                )
                closed_ok += 1
            except Exception as e:  # noqa: BLE001
                errors.append({"symbol": t.get("symbol", "?"), "error": str(e)[:200]})
        return {"ok": not errors, "closed": closed_ok, "errors": errors}

    @router.post("/trades/close-by-symbol")
    async def close_by_symbol(
        device_id: str = Query(..., min_length=4),
        symbol: str = Query(..., min_length=1),
        exchange: str = Query(..., min_length=2),
    ):
        """v9.8.4 — Fallback close ketika row trade tidak punya `_id`
        (mis. response dari backend lama yang men-strip _id) ATAU posisi
        masih terbuka di exchange walau row sudah bertanda closed.

        Urutan:
          1. Cari trade OPEN (case-insensitive) terbaru utk symbol+exchange.
          2. Bila tidak ada, pakai trade TERAKHIR (status apa pun) untuk
             mengambil side/qty — lalu tetap panggil close_position yang
             membaca posisi REAL dari exchange (no-op bila memang kosong).
          3. Tandai semua trade open utk symbol itu sebagai closed/manual.
        """
        sym = symbol.upper().split("/")[0].split("USDT")[0].split("-")[0]
        trades = [
            d async for d in db.asi_trades.find(
                {"device_id": device_id, "symbol": sym, "exchange": exchange}
            ).sort("created_at", -1).limit(10)
        ]
        if not trades:
            raise HTTPException(404, f"Tidak ada trade {sym} di {exchange}.")
        open_trades = [t for t in trades
                       if str(t.get("status", "")).lower() == "open"]
        ref = open_trades[0] if open_trades else trades[0]
        cred = await resolve_credential(
            db, device_id, exchange, bool(ref.get("testnet", True)))
        if not cred:
            raise HTTPException(404, "Hubungkan API exchange untuk jaringan ini terlebih dahulu.")
        try:
            await close_position(
                cred, ref["symbol"], ref["side"], float(ref.get("qty") or 0),
            )
        except Exception as e:  # noqa: BLE001
            raise HTTPException(500, str(e)[:200])
        now = datetime.now(timezone.utc).isoformat()
        ids = [t["_id"] for t in open_trades]
        if ids:
            await db.asi_trades.update_many(
                {"_id": {"$in": ids}},
                {"$set": {"status": "closed", "close_reason": "manual",
                          "closed_at": now, "updated_at": now}},
            )
        return {"ok": True, "closed": len(ids), "symbol": sym,
                "note": "db_row_missing" if not open_trades else None}

    @router.post("/trades/repair-brackets")
    async def repair_brackets(
        device_id: str = Query(..., min_length=4),
        exchange: str = Query("binance"),
    ):
        """v9.9.0 — Pasang ulang SL/TP native untuk SEMUA posisi open milik
        user yang bracket-nya soft/gagal (mis. akibat bug format harga lama).
        Response menyertakan error mentah Binance per simbol sehingga mudah
        didiagnosis dari UI."""
        from .engine import attach_brackets
        # v9.9.5 — resolve credential PER-TRADE sesuai jaringan trade tsb
        # (posisi testnet tidak bisa di-repair dengan key mainnet).
        open_trades = [
            d async for d in db.asi_trades.find({
                "device_id": device_id, "exchange": exchange, "status": "open",
            }).sort("created_at", -1).limit(50)
        ]
        results: list[dict[str, Any]] = []
        for tr in open_trades:
            try:
                cred = await resolve_credential(
                    db, device_id, exchange, bool(tr.get("testnet", True)))
                if not cred:
                    res = {"ok": False, "symbol": tr.get("symbol"),
                           "errors": ["credential missing untuk jaringan trade ini"]}
                else:
                    res = await attach_brackets(cred, tr)
            except Exception as e:  # noqa: BLE001
                res = {"ok": False, "symbol": tr.get("symbol"),
                       "errors": [str(e)[:180]]}
            if res.get("update"):
                await db.asi_trades.update_one(
                    {"_id": tr["_id"]}, {"$set": res["update"]},
                )
            results.append(res)
        return {"ok": True, "repaired": sum(1 for r in results if r.get("ok")),
                "total": len(results), "results": results}

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
        cred = await resolve_credential(
            db, device_id, doc["exchange"], bool(doc.get("testnet", True)))
        if not cred:
            raise HTTPException(404, "Credential exchange tidak ditemukan untuk jaringan ini")
        update = await refresh_trade_pnl(cred, doc)
        update["updated_at"] = _now_iso()
        await db.asi_trades.update_one({"_id": doc["_id"]}, {"$set": update})
        return {**doc, **update}

    @router.get("/pnl")
    async def pnl(device_id: str = Query(..., min_length=4)):
        return await pnl_summary(db, device_id)

    @router.get("/leaderboard")
    async def leader(period_days: int = Query(7, ge=1, le=90)):
        return {"items": await leaderboard(db, period_days=period_days, limit=25),
                "period_days": period_days}

    @router.get("/leaderboard/live")
    async def leader_live():
        """v9.4.0 — Only traders CURRENTLY in open positions, ranked by
        live unrealized PnL. Rows disappear automatically when positions
        close. No time-window parameter needed."""
        return {"items": await live_leaderboard(db, limit=25)}

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

    # v10.0.14 — Webhook penerima sinyal dari Titan-Bot
    # (white-label: WunderTrading / TradingView alert / strategy eksternal).
    # Secret token dishare dengan pengirim; mencegah pihak tak dikenal
    # mengirim sinyal palsu. Setelah divalidasi, sinyal:
    #   1. Disimpan di collection `asi_cloud_signals` (dibaca Semi-Auto
    #      user via sheet "Titan-Bot Signals" untuk 1-tap execute),
    #   2. Dieksekusi otomatis untuk setiap user Full-Auto yang memilih
    #      signal_source ∈ {"cloud_pro", "hybrid"} — risk/leverage/margin
    #      ikut config masing-masing user, bukan payload.
    @router.post("/webhook/cloud")
    async def webhook_cloud(payload: CloudSignalPayload):
        want = os.environ.get("WUNDER_WEBHOOK_SECRET") or ""
        if not want or payload.secret != want:
            raise HTTPException(401, "unauthorized")
        side_up = payload.side.upper()
        side_norm: Literal["BUY", "SELL"] = "BUY" if side_up in ("BUY", "LONG") else "SELL"
        symbol_norm = payload.symbol.upper().replace("/", "").replace("USDT", "").split("-")[0]
        if not symbol_norm:
            raise HTTPException(400, "invalid symbol")
        now = _now_iso()
        sig_doc: dict[str, Any] = {
            "symbol": symbol_norm,
            "side": side_norm,
            "entry": float(payload.entry),
            "stop_loss": float(payload.stop_loss),
            "take_profits": [float(x) for x in payload.take_profits],
            "confidence": int(payload.confidence or 85),
            "source": "cloud_pro",
            # Internal only — tidak dikirim ke client (white-label).
            "source_tag": payload.source_tag or payload.strategy_name,
            "received_at": now,
            "expires_at": (datetime.now(timezone.utc)
                           + timedelta(minutes=10)).isoformat(),
            "status": "new",
            "fan_out": {"attempted": 0, "ok": 0, "fail": 0},
        }
        result = await db.asi_cloud_signals.insert_one(sig_doc)
        sig_id = str(result.inserted_id)
        # Fan-out ke semua user Full-Auto yang pilih cloud_pro / hybrid.
        attempted = ok_cnt = fail_cnt = 0
        cursor = db.asi_bot_config.find({
            "full_enabled": True,
            "signal_source": {"$in": ["cloud_pro", "hybrid"]},
        })
        async for cfg in cursor:
            dev = cfg.get("device_id") or cfg.get("_id")
            if not dev:
                continue
            attempted += 1
            try:
                net = bool(cfg["active_testnet"]) if "active_testnet" in cfg else None
                exchange = cfg.get("exchange") or "binance"
                cred = await resolve_credential(db, dev, exchange, net)
                if not cred:
                    fail_cnt += 1
                    continue
                dup = await db.asi_trades.find_one(
                    {"device_id": dev, "symbol": symbol_norm,
                     "status": {"$in": ["open", "pending_entry"]}}
                )
                if dup:
                    fail_cnt += 1
                    continue
                risk = float(cfg.get("risk_pct") or 5.0)
                lev = int(cfg.get("leverage") or 10)
                res = await execute_trade(
                    cred, symbol_norm, side_norm,
                    float(payload.entry), float(payload.stop_loss),
                    [float(x) for x in payload.take_profits],
                    risk, lev, mode="full",
                    tp_count=int(cfg.get("tp_count") or 3),
                    trailing_callback_rate=float(cfg.get("trailing_callback_rate") or 0.0),
                    margin_mode=str(cfg.get("margin_mode") or "isolated"),
                    profile=None,
                    formula_tag="Titan-Bot",
                    entry_mode=str(cfg.get("entry_mode") or "limit"),
                )
                if not res.get("ok"):
                    fail_cnt += 1
                    continue
                margin_usdt = round(
                    float(res["qty"]) * float(res["entry_price"])
                    / max(1, int(res["leverage"])), 2)
                rec = {**res, "device_id": dev, "margin_usdt": margin_usdt,
                       "signal_source": "cloud_pro", "signal_id": sig_id,
                       "formula_tag": "Titan-Bot"}
                if res.get("entry_order_id"):
                    rec["_id"] = f"{dev}:{res['entry_order_id']}"
                    await db.asi_trades.replace_one(
                        {"_id": rec["_id"]}, rec, upsert=True)
                ok_cnt += 1
            except Exception as e:  # noqa: BLE001
                logger.warning("cloud fan-out fail %s: %s", dev, e)
                fail_cnt += 1
                continue
        await db.asi_cloud_signals.update_one(
            {"_id": result.inserted_id},
            {"$set": {"fan_out": {"attempted": attempted, "ok": ok_cnt, "fail": fail_cnt},
                      "status": "dispatched"}})
        return {"ok": True, "signal_id": sig_id,
                "fan_out": {"attempted": attempted, "ok": ok_cnt, "fail": fail_cnt}}

    @router.get("/signals/cloud")
    async def list_cloud_signals(limit: int = Query(20, ge=1, le=100)):
        """List sinyal Titan-Bot aktif (belum expired). Dipakai halaman
        ASI-Bot untuk kartu rekomendasi Semi-Auto 1-tap execute."""
        now = datetime.now(timezone.utc).isoformat()
        rows = []
        cursor = db.asi_cloud_signals.find(
            {"expires_at": {"$gte": now}}
        ).sort("received_at", -1).limit(limit)
        async for d in cursor:
            d["_id"] = str(d.get("_id"))
            # White-label: jangan ekspos source_tag asli ke client.
            d.pop("source_tag", None)
            d["engine"] = "Titan-Bot"
            rows.append(d)
        return {"items": rows}

    # v10.0.15 — Status Titan Relay (read-only, tanpa auth: hanya info
    # kesehatan publik — tidak mengekspos credential/saldo sensitif).
    @router.get("/titan/status")
    async def titan_status():
        cfg = await db.asi_titan_config.find_one({"_id": "titan_master"})
        if not cfg or not cfg.get("enabled"):
            return {"configured": False, "relay": "off"}
        try:
            k = decrypt(cfg["api_key_enc"])
            s = decrypt(cfg["api_secret_enc"])
            tn = bool(cfg.get("testnet", False))
            positions = await br.all_position_risks(k, s, tn)
        except Exception as e:
            return {"configured": True, "relay": "error",
                    "detail": str(e)[:200]}
        relayed = await db.asi_titan_state.count_documents({})
        return {
            "configured": True,
            "relay": "active",
            "network": "testnet" if tn else "mainnet",
            "master_open_positions": len(positions),
            "positions_relayed": relayed,
        }
