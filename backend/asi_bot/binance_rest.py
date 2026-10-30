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


_CLIENTS: dict[tuple, httpx.AsyncClient] = {}


def _client() -> httpx.AsyncClient:
    """v10.3.8 — httpx client PERSISTEN (keep-alive) per event-loop+proxy.
    Dulu setiap panggilan signed membuat client + handshake TLS baru via
    proxy (~1.5 dtk/panggilan) → monitor posisi, balance, close lambat."""
    import asyncio as _aio
    key = (id(_aio.get_running_loop()), _proxy())
    c = _CLIENTS.get(key)
    if c is None or c.is_closed:
        c = httpx.AsyncClient(proxy=key[1], timeout=20.0,
                              limits=httpx.Limits(max_connections=50, max_keepalive_connections=20))
        _CLIENTS[key] = c
    return c


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
    r = await _client().request(method, url, headers={"X-MBX-APIKEY": api_key},
                                timeout=timeout)
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


async def all_position_risks(
    api_key: str, api_secret: str, testnet: bool,
) -> list[dict[str, Any]]:
    """v10.0.15 — Semua posisi OPEN di akun (tanpa filter symbol).
    Dipakai Titan Relay untuk membaca posisi akun master WunderTrading."""
    code, data = await _request(
        "GET", "/fapi/v2/positionRisk", api_key, api_secret, testnet, {},
    )
    if code != 200 or not isinstance(data, list):
        raise RuntimeError(f"positionRisk(all) failed: {data}")
    return [p for p in data if abs(float(p.get("positionAmt") or 0)) > 0]


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


async def limit_order(
    api_key: str, api_secret: str, testnet: bool, *,
    symbol: str, side: str, quantity: float, price: float,
    time_in_force: str = "GTC",
) -> dict[str, Any]:
    """v9.9.13 — Entry LIMIT (deep). Bot tidak lagi eksekusi MARKET."""
    params: dict[str, Any] = {
        "symbol": symbol.upper(), "side": side.upper(), "type": "LIMIT",
        "timeInForce": time_in_force,
        "quantity": _fmt(quantity), "price": _fmt(price),
    }
    code, data = await _request("POST", "/fapi/v1/order", api_key, api_secret, testnet, params)
    if code != 200:
        raise RuntimeError(f"limit order rejected: {data}")
    return data if isinstance(data, dict) else {}


async def cancel_order(
    api_key: str, api_secret: str, testnet: bool, *,
    symbol: str, order_id: int | str,
) -> bool:
    """v9.9.13 — Batalkan satu order limit (dipakai saat pending entry
    expired / di-cancel user). True bila berhasil."""
    code, data = await _request(
        "DELETE", "/fapi/v1/order", api_key, api_secret, testnet,
        {"symbol": symbol.upper(), "orderId": str(order_id)},
    )
    return code == 200


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


async def last_fill_price(
    api_key: str, api_secret: str, testnet: bool, symbol: str,
) -> float | None:
    """v9.9.9 — Harga fill TERAKHIR user pada simbol (dipakai untuk merekam
    closed_price saat posisi tertutup oleh SL/TP/trailing di exchange)."""
    code, data = await _request(
        "GET", "/fapi/v1/userTrades", api_key, api_secret, testnet,
        {"symbol": symbol.upper(), "limit": 5},
    )
    if code != 200 or not isinstance(data, list) or not data:
        return None
    try:
        return float(data[-1].get("price") or 0) or None
    except Exception:
        return None


async def last_reduce_fill_price(
    api_key: str, api_secret: str, testnet: bool, symbol: str,
) -> float | None:
    """v10.1.6 — Harga fill TERAKHIR yang benar-benar MENGURANGI posisi
    (realizedPnl != 0). Berbeda dari `last_fill_price` yang mengambil fill
    terakhir simbol — bisa milik trade lain atau fill penambah posisi,
    sehingga harga yang terekam keliru (mis. RUNE tercatat "TP1 hit 0.65450"
    padahal TP1 sebenarnya 0.66410). Dipakai untuk validasi partial TP."""
    code, data = await _request(
        "GET", "/fapi/v1/userTrades", api_key, api_secret, testnet,
        {"symbol": symbol.upper(), "limit": 30},
    )
    if code != 200 or not isinstance(data, list) or not data:
        return None
    for f in reversed(data):  # terbaru dulu
        try:
            if abs(float(f.get("realizedPnl") or 0)) > 1e-12:
                return float(f.get("price") or 0) or None
        except Exception:
            continue
    return None

async def realized_close_info(
    api_key: str, api_secret: str, testnet: bool, symbol: str,
    since_ms: int | None = None,
) -> dict[str, float] | None:
    """v10.1.1 — Realized PnL AKTUAL + harga penutup dari fills exchange.

    Mengambil /fapi/v1/userTrades sejak posisi dibuka; hanya fills dengan
    realizedPnl != 0 yang benar-benar MENUTUP (mengurangi) posisi.
    Menjumlahkan realizedPnl → PnL realized yang sebenarnya, dan memakai
    harga fill penutup terakhir sebagai closed_price. Menggantikan pola
    lama: pnl_usdt stale dari refresh terakhir + last_fill_price (fill
    terakhir simbol — bisa milik trade/layer lain pada simbol yang sama).
    """
    params: dict[str, Any] = {"symbol": symbol.upper(), "limit": 200}
    if since_ms:
        params["startTime"] = int(since_ms)
    code, data = await _request(
        "GET", "/fapi/v1/userTrades", api_key, api_secret, testnet, params)
    if code != 200 or not isinstance(data, list) or not data:
        return None
    realized = 0.0
    close_px: float | None = None
    close_oid = None
    for f in data:
        try:
            rp = float(f.get("realizedPnl") or 0)
        except Exception:
            rp = 0.0
        if abs(rp) > 1e-12:
            realized += rp
            close_oid = f.get("orderId") or close_oid
            try:
                close_px = float(f.get("price") or 0) or close_px
            except Exception:
                pass
    if close_px is None:
        return None
    return {"pnl": realized, "price": close_px, "order_id": close_oid}


async def order_origin(
    api_key: str, api_secret: str, testnet: bool, symbol: str, order_id: Any,
) -> dict[str, Any] | None:
    """v10.7.14 — Siapa yang menutup posisi: tipe order + clientOrderId."""
    code, data = await _request(
        "GET", "/fapi/v1/order", api_key, api_secret, testnet,
        {"symbol": symbol.upper(), "orderId": str(order_id)})
    if code != 200 or not isinstance(data, dict):
        return None
    return {"type": data.get("origType") or data.get("type"),
            "client_id": str(data.get("clientOrderId") or "")}


def classify_close_origin(origin: dict[str, Any] | None) -> str | None:
    """v10.7.14 — clientOrderId Binance: web_/android_/ios_/electron_ =
    ditutup manual dari app/web Binance; autoclose-/adl_ = likuidasi/ADL."""
    if not origin:
        return None
    cid = origin.get("client_id", "").lower()
    if cid.startswith(("web_", "android_", "ios_", "electron_", "app_")):
        return "Manual on Binance app"
    if cid.startswith("autoclose-"):
        return "Liquidation"
    if cid.startswith("adl_autoclose"):
        return "ADL"
    return None



async def open_orders_legacy(
    api_key: str, api_secret: str, testnet: bool, symbol: str,
) -> list[dict[str, Any]]:
    """v9.9.10 — Legacy conditional orders (endpoint /fapi/v1/order).

    SL/TP yang dipasang oleh KODE LAMA (sebelum migrasi Algo API) atau
    yang dipasang MANUAL oleh user lewat fitur "TP/SL for position" di
    aplikasi Binance TIDAK muncul di GET /openAlgoOrders. Tanpa cek ini:
      - posisi yang SEBENARNYA terproteksi salah ditandai "tanpa SL/TP";
      - repair mencoba pasang SL closePosition baru → Binance menolak
        -4130 ("an open stop order with closePosition is existing").
    """
    code, data = await _request(
        "GET", "/fapi/v1/openOrders", api_key, api_secret, testnet,
        {"symbol": symbol.upper()},
    )
    if code != 200 or not isinstance(data, list):
        return []
    return data


async def cancel_all_legacy(
    api_key: str, api_secret: str, testnet: bool, symbol: str,
) -> dict[str, Any]:
    """v9.9.10 — Batalkan SEMUA order legacy (regular + conditional lama)
    untuk simbol. Dipakai untuk membersihkan bracket basi sebelum entry
    baru (mencegah -4130) dan sebelum emergency close."""
    code, data = await _request(
        "DELETE", "/fapi/v1/allOpenOrders", api_key, api_secret, testnet,
        {"symbol": symbol.upper()},
    )
    return data if isinstance(data, dict) else {"code": code, "data": data}
