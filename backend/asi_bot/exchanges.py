"""ASI-Bot — Exchange adapter via CCXT (Binance, Bybit, OKX, Bitget).

Only USDT-margined perpetual futures. We force defaultType="swap" and
reject any API key that has withdrawal permission enabled.
"""
from __future__ import annotations

import asyncio
from typing import Any, Literal

import ccxt
import ccxt.async_support as ccxt_async

ExchangeId = Literal["binance", "bybit", "okx", "bitget"]
EXCHANGES: tuple[ExchangeId, ...] = ("binance", "bybit", "okx", "bitget")

EXCHANGE_DISPLAY = {
    "binance": "Binance Futures (USDⓈ-M)",
    "bybit":   "Bybit Perpetual",
    "okx":     "OKX Perpetual Swap",
    "bitget":  "Bitget Futures",
}


def _build(ex_id: ExchangeId, api_key: str, api_secret: str,
           password: str | None, testnet: bool, use_async: bool = True) -> Any:
    """Create a CCXT client configured for USDT-margined futures."""
    mod = ccxt_async if use_async else ccxt
    cls_name = "binanceusdm" if ex_id == "binance" else ex_id
    cls = getattr(mod, cls_name)
    config: dict[str, Any] = {
        "apiKey": api_key,
        "secret": api_secret,
        "enableRateLimit": True,
        "options": {"defaultType": "swap"},
    }
    # v9.3.0 — Explicitly disable portfolio margin routing for Binance.
    # Without this flag, CCXT 4.4 can route STOP_MARKET through the
    # Portfolio Margin "conditional" endpoint which returns -4120.
    if ex_id == "binance":
        config["options"]["portfolioMargin"] = False
    if password:
        config["password"] = password  # OKX passphrase, Bitget passphrase
    client = cls(config)
    if testnet:
        try:
            client.set_sandbox_mode(True)
        except Exception:
            pass
    return client


async def validate_credentials(
    ex_id: ExchangeId, api_key: str, api_secret: str,
    password: str | None, testnet: bool,
) -> dict[str, Any]:
    """Verify key works AND rejects it if withdrawal permission is set.

    Returns {ok, uid, permissions, message}. Caller treats ok=False as
    400 and refuses to persist the credential.
    """
    client = _build(ex_id, api_key, api_secret, password, testnet)
    try:
        try:
            await client.load_markets()
        except Exception as e:
            return {"ok": False, "message": f"Tidak dapat terkoneksi ke {ex_id}: {e}"}
        try:
            bal = await client.fetch_balance()
        except Exception as e:
            return {"ok": False, "message": f"API key gagal autentikasi: {e}"}
        perms = {"read": True, "trade": None, "withdraw": None}
        info = (bal or {}).get("info") or {}
        for k in ("permissions", "apiKeyPermissions", "permission"):
            if k in info:
                perms["raw"] = info[k]
                raw = info[k]
                if isinstance(raw, dict):
                    for kk, vv in raw.items():
                        lk = kk.lower()
                        if "withdraw" in lk:
                            perms["withdraw"] = bool(vv)
                        elif "trade" in lk or "spot" in lk or "future" in lk or "swap" in lk:
                            perms["trade"] = bool(vv) or perms.get("trade") or False
                elif isinstance(raw, list):
                    joined = ",".join(str(x).lower() for x in raw)
                    perms["withdraw"] = "withdraw" in joined
                    perms["trade"] = any(w in joined for w in ("trade", "future", "swap", "spot"))
        if perms.get("withdraw") is True:
            return {
                "ok": False,
                "permissions": perms,
                "message": (
                    "API key Anda MEMILIKI izin PENARIKAN (Withdraw). "
                    "Demi keamanan, ASI-Bot MENOLAK key dengan izin ini. "
                    "Mohon buat API key BARU di exchange dengan izin "
                    "'Enable Futures' saja — JANGAN centang 'Enable Withdrawals'."
                ),
            }
        return {"ok": True, "permissions": perms, "message": "OK"}
    finally:
        try:
            await client.close()
        except Exception:
            pass


async def ping(client: Any) -> bool:
    try:
        await client.fetch_time()
        return True
    except Exception:
        return False
