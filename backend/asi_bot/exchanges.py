"""ASI-Bot — Exchange adapter via CCXT (Binance, Bybit, OKX, Bitget).

Only USDT-margined perpetual futures. We force defaultType="swap" and
reject any API key that has withdrawal permission enabled.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import time
from typing import Any, Literal
from urllib.parse import urlencode

import ccxt
import ccxt.async_support as ccxt_async
import httpx

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
        # v9.6.5 — Only load USDⓈ-M futures markets. Default CCXT also
        # loads /sapi/v1/margin/allPairs which requires "Enable Margin"
        # permission; API keys with only "Enable Futures" get HTTP 400
        # here even though they are valid for futures trading.
        config["options"]["fetchMarkets"] = ["linear"]
    proxy = os.environ.get("ASI_PROXY_URL") or os.environ.get("HTTPS_PROXY")
    if proxy:
        config["httpsProxy"] = proxy
    if password:
        config["password"] = password  # OKX passphrase, Bitget passphrase
    client = cls(config)
    if testnet:
        try:
            client.set_sandbox_mode(True)
        except Exception:
            pass
    return client


async def _binance_fapi_account(api_key: str, api_secret: str, testnet: bool) -> dict[str, Any]:
    """Signed GET /fapi/v2/account — Binance USDⓈ-M Futures only.

    v9.6.9 — Bypasses CCXT entirely for credential validation. CCXT's
    binanceusdm.fetchBalance() still fans out to /sapi/v1/capital/config/getall
    (spot wallet) which requires 'Enable Spot & Margin Trading' permission
    that users correctly don't tick. This endpoint touches ONLY /fapi so
    an API key with just 'Enable Futures' validates cleanly.
    """
    base = "https://testnet.binancefuture.com" if testnet else "https://fapi.binance.com"
    params = {"timestamp": int(time.time() * 1000), "recvWindow": 10000}
    qs = urlencode(params)
    sig = hmac.new(api_secret.encode(), qs.encode(), hashlib.sha256).hexdigest()
    proxy = os.environ.get("ASI_PROXY_URL") or os.environ.get("HTTPS_PROXY")
    async with httpx.AsyncClient(proxy=proxy, timeout=15) as c:
        r = await c.get(
            f"{base}/fapi/v2/account",
            params={**params, "signature": sig},
            headers={"X-MBX-APIKEY": api_key},
        )
    try:
        data = r.json()
    except Exception:
        raise Exception(f"HTTP {r.status_code}: {r.text[:200]}")
    if r.status_code != 200:
        code = data.get("code") if isinstance(data, dict) else None
        msg = data.get("msg") if isinstance(data, dict) else r.text[:200]
        raise Exception(f"code={code} msg={msg}")
    return data


async def _binance_api_restrictions(api_key: str, api_secret: str, testnet: bool) -> dict[str, Any]:
    """Signed GET /sapi/v1/account/apiRestrictions — the ONLY endpoint that
    truthfully reports API-key-level permissions (enableWithdrawals etc).
    """
    base = "https://testnet.binancefuture.com" if testnet else "https://api.binance.com"
    params = {"timestamp": int(time.time() * 1000), "recvWindow": 10000}
    qs = urlencode(params)
    sig = hmac.new(api_secret.encode(), qs.encode(), hashlib.sha256).hexdigest()
    proxy = os.environ.get("ASI_PROXY_URL") or os.environ.get("HTTPS_PROXY")
    async with httpx.AsyncClient(proxy=proxy, timeout=15) as c:
        r = await c.get(
            f"{base}/sapi/v1/account/apiRestrictions",
            params={**params, "signature": sig},
            headers={"X-MBX-APIKEY": api_key},
        )
    try:
        data = r.json()
    except Exception:
        raise Exception(f"HTTP {r.status_code}: {r.text[:200]}")
    if r.status_code != 200:
        code = data.get("code") if isinstance(data, dict) else None
        msg = data.get("msg") if isinstance(data, dict) else r.text[:200]
        raise Exception(f"code={code} msg={msg}")
    return data


async def validate_credentials(
    ex_id: ExchangeId, api_key: str, api_secret: str,
    password: str | None, testnet: bool,
) -> dict[str, Any]:
    """Verify key works AND rejects it if withdrawal permission is set.

    Returns {ok, uid, permissions, message}. Caller treats ok=False as
    400 and refuses to persist the credential.
    """
    # v9.6.9 — Binance validated via direct /fapi/v2/account signed call
    # (bypasses CCXT spot/margin endpoint quirks). Other exchanges still
    # go through CCXT since they don't have the same problem.
    if ex_id == "binance":
        try:
            acct = await _binance_fapi_account(api_key, api_secret, testnet)
        except Exception as e:
            msg = str(e)
            # v9.7.1 — Proxy / network layer failures are the #1 cause
            # of "silent" validation failures. Classify them explicitly
            # so the UI can display a clear, actionable message.
            if any(x in msg.lower() for x in ("readtimeout", "connecttimeout", "connecttimeouterror", "connecterror", "read timeout", "connection refused", "proxyerror")):
                return {"ok": False, "code": "proxy_down", "message": "Server IP relay is unreachable. Please contact admin."}
            if "-2015" in msg or "Invalid API-key" in msg:
                # v9.7.3 — Binance -2015 is ambiguous: bad key OR bad IP OR
                # missing permission. Disambiguate by probing the SPOT-side
                # permissions endpoint: if it succeeds, the key+IP are fine
                # and the failure is the missing Futures permission.
                if not testnet:
                    try:
                        await _binance_api_restrictions(api_key, api_secret, testnet)
                        return {"ok": False, "code": "trade_disabled",
                                "message": "API key is valid and IP whitelisted, but 'Enable Futures' is NOT ticked on this key. Enable it in Binance API Management."}
                    except Exception:
                        pass
                return {"ok": False, "code": "ip_or_key_invalid", "message": "Invalid API key/secret OR server IP not whitelisted (IP: 143.198.197.107)."}
            if "-2014" in msg or "API-key format invalid" in msg:
                return {"ok": False, "code": "key_format_invalid", "message": "Invalid API key format."}
            if "451" in msg or "Restricted Location" in msg:
                return {"ok": False, "code": "region_blocked", "message": "Binance rejected the server location (HTTP 451)."}
            return {"ok": False, "code": "auth_failed", "message": f"Authentication failed: {msg}"}
        perms = {
            "trade": bool(acct.get("canTrade", False)),
            "deposit": bool(acct.get("canDeposit", False)),
            "withdraw": None,  # v9.7.2 — placeholder; real check below
        }
        # v9.7.2 — /fapi/v2/account's canWithdraw refers to the ACCOUNT's
        # ability (basically always true), NOT the API key's permission.
        # The ONLY truthful source is /sapi/v1/account/apiRestrictions.
        # On testnet the sapi endpoint doesn't exist → skip check there.
        if not testnet:
            try:
                restr = await _binance_api_restrictions(api_key, api_secret, testnet)
            except Exception as e:
                return {"ok": False, "code": "auth_failed",
                        "message": f"Cannot verify API-key permissions: {e}"}
            perms = {
                "futures": bool(restr.get("enableFutures", False)),
                "withdraw": bool(restr.get("enableWithdrawals", False)),
                "universal_transfer": bool(restr.get("permitsUniversalTransfer", False)),
            }
            if perms["withdraw"] or perms["universal_transfer"]:
                return {"ok": False, "code": "withdraw_enabled", "permissions": perms,
                        "message": "Your API key has WITHDRAW permission. For safety, ASI-Bot rejects such keys."}
            if not perms["futures"]:
                return {"ok": False, "code": "trade_disabled", "permissions": perms,
                        "message": "API key has no Futures permission. Enable 'Futures' in Binance API Management."}
        return {"ok": True, "permissions": perms, "message": "OK"}

    # Non-Binance (bybit, okx, bitget) — via CCXT.
    client = _build(ex_id, api_key, api_secret, password, testnet)
    try:
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
