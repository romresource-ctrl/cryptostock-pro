"""ASI-Bot — Direct signed Binance USDM Futures REST client.

v9.9.2 — kita berhenti bergantung pada CCXT untuk operasi kritis
(set margin mode, verifikasi posisi, placement SL/TP native) karena
CCXT secara diam-diam membungkus/menelan error exchange, membuat
engine mengira native bracket terpasang padahal tidak.

Semua request melewati `ASI_PROXY_URL` (Singapore egress) dan membawa
HMAC-SHA256 signature. Tidak menggunakan library tambahan di luar httpx.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time
from typing import Any

import httpx

MAINNET_BASE = "https://fapi.binance.com"
TESTNET_BASE = "https://testnet.binancefuture.com"


def _base(testnet: bool) -> str:
    return TESTNET_BASE if testnet else MAINNET_BASE


def _proxy() -> str | None:
    return os.environ.get("ASI_PROXY_URL") or os.environ.get("HTTPS_PROXY")


def _sign_qs(secret: str, params: dict[str, Any]) -> str:
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    sig = hmac.new(secret.encode(), qs.encode(), hashlib.sha256).hexdigest()
    return qs + "&signature=" + sig


async def _request(
    method: str, path: str, api_key: str, api_secret: str,
    testnet: bool, params: dict[str, Any] | None = None,
    timeout: float = 20.0,
) -> tuple[int, dict[str, Any] | list[Any]]:
    params = dict(params or {})
    params["timestamp"] = int(time.time() * 1000)
    params["recvWindow"] = params.get("recvWindow", 10000)
    qs = _sign_qs(api_secret, params)
    url = f"{_base(testnet)}{path}?{qs}"
    async with httpx.AsyncClient(proxy=_proxy(), timeout=timeout) as c:
        r = await c.request(method, url, headers={"X-MBX-APIKEY": api_key})
    try:
        data = r.json()
    except Exception:
        data = {"_raw": r.text[:300]}
    return r.status_code, data


# ──────────────────────────────────────────────────────────────────────
# Account / position
# ──────────────────────────────────────────────────────────────────────

async def available_usdt(api_key: str, api_secret: str, testnet: bool) -> float:
    code, data = await _request("GET", "/fapi/v2/account", api_key, api_secret, testnet)
    if code != 200 or not isinstance(data, dict):
        raise RuntimeError(f"account fetch failed: {data}")
    return float(data.get("availableBalance") or 0.0)


async def position_risk(
    api_key: str, api_secret: str, testnet: bool, symbol: str,
) -> dict[str, Any] | None:
    code, data = await _request(
        "GET", "/fapi/v2/positionRisk", api_key, api_secret, testnet,
        {"symbol": symbol.upper()},
    )
    if code != 200 or not isinstance(data, list):
        raise RuntimeError(f"positionRisk failed: {data}")
    for p in data:
        if abs(float(p.get("positionAmt") or 0)) > 0:
            return p
    # No open position for this symbol
    return data[0] if data else None


async def set_leverage(
    api_key: str, api_secret: str, testnet: bool, *,
    symbol: str, leverage: int,
) -> dict[str, Any]:
    code, data = await _request(
        "POST", "/fapi/v1/leverage", api_key, api_secret, testnet,
        {"symbol": symbol.upper(), "leverage": int(leverage)},
    )
    if code != 200:
        # don't abort entry on leverage failure; just surface it
        return {"ok": False, "error": data}
    return {"ok": True, **data} if isinstance(data, dict) else {"ok": True}


async def set_margin_type(
    api_key: str, api_secret: str, testnet: bool, *,
    symbol: str, margin_type: str,  # "ISOLATED" | "CROSS"
) -> dict[str, Any]:
    """Returns {ok: bool, code: int, msg: str, no_change: bool}.
    -4046 = "No need to change margin type" → treat as success/no_change.
    """
    mt = "ISOLATED" if margin_type.upper().startswith("ISO") else "CROSSED"
    code, data = await _request(
        "POST", "/fapi/v1/marginType", api_key, api_secret, testnet,
        {"symbol": symbol.upper(), "marginType": mt},
    )
    if code == 200:
        return {"ok": True, "no_change": False}
    err_code = (data or {}).get("code")
    err_msg = (data or {}).get("msg") or str(data)
    if err_code == -4046:
        return {"ok": True, "no_change": True, "msg": err_msg}
    return {"ok": False, "code": err_code, "msg": err_msg}


# ──────────────────────────────────────────────────────────────────────
# Orders
# ──────────────────────────────────────────────────────────────────────

async def market_order(
    api_key: str, api_secret: str, testnet: bool, *,
    symbol: str, side: str, quantity: float, reduce_only: bool = False,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "symbol": symbol.upper(), "side": side.upper(), "type": "MARKET",
        "quantity": _fmt(quantity),
    }
    if reduce_only:
        params["reduceOnly"] = "true"
    code, data = await _request("POST", "/fapi/v1/order", api_key, api_secret, testnet, params)
    if code != 200:
        raise RuntimeError(f"market order rejected: {data}")
    return data if isinstance(data, dict) else {}


async def order_status(
    api_key: str, api_secret: str, testnet: bool, *,
    symbol: str, order_id: int | str,
) -> dict[str, Any]:
    code, data = await _request(
        "GET", "/fapi/v1/order", api_key, api_secret, testnet,
        {"symbol": symbol.upper(), "orderId": str(order_id)},
    )
    if code != 200 or not isinstance(data, dict):
        raise RuntimeError(f"order status failed: {data}")
    return data


# ──────────────────────────────────────────────────────────────────────
# Algo orders (conditional SL/TP)
# ──────────────────────────────────────────────────────────────────────

def _fmt(x: float) -> str:
    """Decimal-safe non-scientific formatting."""
    from decimal import Decimal
    try:
        return format(Decimal(str(x)).normalize(), "f")
    except Exception:
        return str(x)


async def place_algo(
    api_key: str, api_secret: str, testnet: bool, *,
    symbol: str, side: str, order_type: str,
    trigger_price: float, quantity: float | None = None,
    close_position: bool = False, working_type: str = "MARK_PRICE",
) -> dict[str, Any]:
    """order_type ∈ {STOP_MARKET, TAKE_PROFIT_MARKET}.
    Returns raw dict (with algoId on success)."""
    params: dict[str, Any] = {
        "algoType": "CONDITIONAL", "symbol": symbol.upper(),
        "side": side.upper(), "type": order_type,
        "triggerPrice": _fmt(trigger_price), "workingType": working_type,
        "positionSide": "BOTH", "priceProtect": "TRUE",
    }
    if close_position:
        params["closePosition"] = "true"
    else:
        if quantity is None or quantity <= 0:
            raise ValueError("quantity required when close_position=False")
        params["quantity"] = _fmt(quantity)
        params["reduceOnly"] = "true"
    code, data = await _request(
        "POST", "/fapi/v1/algoOrder", api_key, api_secret, testnet, params,
    )
    if code != 200 or not isinstance(data, dict) or not data.get("algoId"):
        raise RuntimeError(f"algoOrder rejected ({code}): {data}")
    if data.get("algoStatus") not in ("NEW", "WORKING"):
        raise RuntimeError(f"algoOrder bad status: {data}")
    return data


async def open_algo_orders(
    api_key: str, api_secret: str, testnet: bool, symbol: str | None = None,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {}
    if symbol:
        params["symbol"] = symbol.upper()
    code, data = await _request(
        "GET", "/fapi/v1/openAlgoOrders", api_key, api_secret, testnet, params,
    )
    if code != 200 or not isinstance(data, list):
        return []
    return data


async def cancel_algo(
    api_key: str, api_secret: str, testnet: bool, *,
    algo_id: int | str | None = None,
) -> dict[str, Any]:
    if algo_id is None:
        raise ValueError("algo_id required")
    code, data = await _request(
        "DELETE", "/fapi/v1/algoOrder", api_key, api_secret, testnet,
        {"algoId": str(algo_id)},
    )
    return data if isinstance(data, dict) else {"code": code, "data": data}


async def cancel_all_algo(
    api_key: str, api_secret: str, testnet: bool, symbol: str,
) -> dict[str, Any]:
    code, data = await _request(
        "DELETE", "/fapi/v1/algoOpenOrders", api_key, api_secret, testnet,
        {"symbol": symbol.upper()},
    )
    return data if isinstance(data, dict) else {"code": code, "data": data}
