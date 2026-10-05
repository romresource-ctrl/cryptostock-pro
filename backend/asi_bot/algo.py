"""ASI-Bot — Binance Futures Algo Order API client.

Since Dec 9, 2025, Binance migrated ALL conditional orders
(STOP_MARKET / TAKE_PROFIT_MARKET / STOP / TAKE_PROFIT /
TRAILING_STOP_MARKET) from `/fapi/v1/order` to the Algo Service:

    POST   /fapi/v1/algoOrder          (algoType=CONDITIONAL)
    DELETE /fapi/v1/algoOrder          (algoId=...)
    GET    /fapi/v1/openAlgoOrders

Calling the legacy endpoint returns -4120 "Order type not supported
for this endpoint. Please use the Algo Order API endpoints instead."

This module signs requests manually (HMAC-SHA256) so we are NOT
blocked waiting for CCXT support. Works on mainnet AND testnet.
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


def _base_url(testnet: bool) -> str:
    return TESTNET_BASE if testnet else MAINNET_BASE


def _proxy() -> str | None:
    return os.environ.get("ASI_PROXY_URL") or os.environ.get("HTTPS_PROXY")


def _sign(secret: str, params: dict[str, Any]) -> dict[str, Any]:
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    sig = hmac.new(secret.encode(), qs.encode(), hashlib.sha256).hexdigest()
    return {**params, "signature": sig}


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(proxy=_proxy(), timeout=15.0)


def _fmt_num(x: float) -> str:
    """v9.9.0 — Format float ke string desimal polos (tanpa notasi ilmiah
    seperti 5.9e-05) dan pangkas trailing zero berlebih. Binance menolak
    parameter numerik ber-format ilmiah."""
    from decimal import Decimal
    return format(Decimal(f"{x}").normalize(), "f")


async def new_conditional_order(
    api_key: str, api_secret: str, testnet: bool, *,
    symbol: str,          # e.g. "BTCUSDT"
    side: str,            # "BUY" | "SELL"  (closing side)
    order_type: str,      # "STOP_MARKET" | "TAKE_PROFIT_MARKET"
    trigger_price: float,
    quantity: float | None = None,   # partial close; None → closePosition
    close_position: bool = False,
    working_type: str = "MARK_PRICE",
) -> dict[str, Any]:
    """Place one conditional order via the Algo Service.

    Returns the raw Binance response dict. On acceptance it contains
    `algoId`, `algoStatus="NEW"`, etc. On failure raises Exception with
    the Binance error payload.
    """
    params: dict[str, Any] = {
        "algoType": "CONDITIONAL",
        "symbol": symbol.upper().replace("/", ""),
        "side": side.upper(),
        "type": order_type,
        "triggerPrice": _fmt_num(trigger_price),
        "workingType": working_type,
        "positionSide": "BOTH",
        "priceProtect": "TRUE",
        "timestamp": int(time.time() * 1000),
        "recvWindow": 10000,
    }
    if close_position:
        params["closePosition"] = "true"
    else:
        if quantity is None or quantity <= 0:
            raise ValueError("quantity required when close_position=False")
        params["quantity"] = _fmt_num(quantity)
        params["reduceOnly"] = "true"
    signed = _sign(api_secret, params)
    async with _client() as c:
        r = await c.post(
            f"{_base_url(testnet)}/fapi/v1/algoOrder",
            data=signed, headers={"X-MBX-APIKEY": api_key},
        )
    data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if r.status_code != 200 or "code" in data and not data.get("algoId"):
        raise Exception(f"algoOrder rejected: {data or r.text[:200]}")
    return data


async def new_trailing_stop_order(
    api_key: str, api_secret: str, testnet: bool, *,
    symbol: str,
    side: str,                     # closing side: SELL for long, BUY for short
    quantity: float,
    callback_rate: float,          # % — Binance range 0.1 .. 10
    activation_price: float | None = None,
    working_type: str = "MARK_PRICE",
) -> dict[str, Any]:
    """Native TRAILING_STOP_MARKET via Algo API.

    Binance geser SL otomatis mengikuti harga puncak terbaik:
      - long:  SL = max_price_since_open  * (1 - callback_rate/100)
      - short: SL = min_price_since_open  * (1 + callback_rate/100)
    Tidak bergantung backend uptime — exchange yang jaga.
    """
    cb = max(0.1, min(10.0, float(callback_rate)))
    params: dict[str, Any] = {
        "algoType": "CONDITIONAL",
        "symbol": symbol.upper().replace("/", ""),
        "side": side.upper(),
        "type": "TRAILING_STOP_MARKET",
        "quantity": _fmt_num(quantity),
        "callbackRate": f"{cb}",
        "reduceOnly": "true",
        "workingType": working_type,
        "positionSide": "BOTH",
        "timestamp": int(time.time() * 1000),
        "recvWindow": 10000,
    }
    if activation_price is not None:
        params["activationPrice"] = _fmt_num(activation_price)
    signed = _sign(api_secret, params)
    async with _client() as c:
        r = await c.post(
            f"{_base_url(testnet)}/fapi/v1/algoOrder",
            data=signed, headers={"X-MBX-APIKEY": api_key},
        )
    data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if r.status_code != 200 or ("code" in data and not data.get("algoId")):
        raise Exception(f"trailing algoOrder rejected: {data or r.text[:200]}")
    return data


async def cancel_conditional_order(
    api_key: str, api_secret: str, testnet: bool, *,
    algo_id: int | str | None = None,
    client_algo_id: str | None = None,
) -> dict[str, Any]:
    """Cancel one conditional order by algoId (or clientAlgoId)."""
    params: dict[str, Any] = {
        "timestamp": int(time.time() * 1000),
        "recvWindow": 10000,
    }
    if algo_id is not None:
        params["algoId"] = str(algo_id)
    elif client_algo_id:
        params["clientAlgoId"] = client_algo_id
    else:
        raise ValueError("algo_id or client_algo_id required")
    signed = _sign(api_secret, params)
    async with _client() as c:
        r = await c.delete(
            f"{_base_url(testnet)}/fapi/v1/algoOrder",
            params=signed, headers={"X-MBX-APIKEY": api_key},
        )
    try:
        return r.json()
    except Exception:
        return {"http_status": r.status_code, "body": r.text[:200]}


async def cancel_all_conditional(
    api_key: str, api_secret: str, testnet: bool, symbol: str,
) -> dict[str, Any]:
    """Cancel ALL open conditional orders for a symbol
    (DELETE /fapi/v1/algoOpenOrders)."""
    params: dict[str, Any] = {
        "symbol": symbol.upper().replace("/", ""),
        "timestamp": int(time.time() * 1000),
        "recvWindow": 10000,
    }
    signed = _sign(api_secret, params)
    async with _client() as c:
        r = await c.delete(
            f"{_base_url(testnet)}/fapi/v1/algoOpenOrders",
            params=signed, headers={"X-MBX-APIKEY": api_key},
        )
    try:
        return r.json()
    except Exception:
        return {"http_status": r.status_code, "body": r.text[:200]}


async def list_open_conditional(
    api_key: str, api_secret: str, testnet: bool, symbol: str | None = None,
) -> list[dict[str, Any]]:
    """List open conditional orders (GET /fapi/v1/openAlgoOrders)."""
    params: dict[str, Any] = {
        "timestamp": int(time.time() * 1000),
        "recvWindow": 10000,
    }
    if symbol:
        params["symbol"] = symbol.upper().replace("/", "")
    signed = _sign(api_secret, params)
    async with _client() as c:
        r = await c.get(
            f"{_base_url(testnet)}/fapi/v1/openAlgoOrders",
            params=signed, headers={"X-MBX-APIKEY": api_key},
        )
    try:
        data = r.json()
        return data if isinstance(data, list) else []
    except Exception:
        return []
