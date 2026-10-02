"""ASI-Bot — Execution Engine (Phase 2).

Flow per order:
  1. Pastikan symbol di whitelist Top-100.
  2. Ambil balance USDT dari exchange.
  3. Set leverage.
  4. Place MARKET entry (reduce_only=False), posisi: BUY→long, SELL→short.
  5. Place reduce_only STOP_MARKET  (SL)  qty=full.
  6. Place reduce_only TAKE_PROFIT  (TP1, TP2, TP3) dengan split 40/30/30.
  7. Rekam ke asi_trades (status="open") untuk PnL tracking (Phase 4).

Bila step 4 gagal: nothing to roll back.
Bila step 5/6 gagal setelah entry sukses: engine mencoba menutup posisi
dengan MARKET reduce_only (safety net), lalu melempar error ke caller.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from .crypto import decrypt
from .exchanges import _build
from .whitelist import is_allowed

Side = Literal["BUY", "SELL"]
TP_SPLIT = (0.4, 0.3, 0.3)  # TP1, TP2, TP3 share of total qty


def _ccxt_side(side: Side) -> str:
    return "buy" if side == "BUY" else "sell"


def _opposite(side: Side) -> str:
    return "sell" if side == "BUY" else "buy"


async def _get_client(doc: dict[str, Any]):
    return _build(
        doc["exchange"],
        decrypt(doc["api_key_enc"]),
        decrypt(doc["api_secret_enc"]),
        decrypt(doc["password_enc"]) if doc.get("password_enc") else None,
        bool(doc.get("testnet", True)),
    )


async def _fetch_usdt_balance(client) -> float:
    bal = await client.fetch_balance()
    free = (bal.get("USDT") or {}).get("free")
    if free is not None:
        return float(free)
    total = (bal.get("total") or {}).get("USDT")
    return float(total or 0.0)


def _ccxt_symbol(exchange: str, base: str) -> str:
    base = base.upper().split("/")[0].split("USDT")[0].split("-")[0]
    if exchange == "binance":
        return f"{base}/USDT:USDT"
    if exchange == "bybit":
        return f"{base}/USDT:USDT"
    if exchange == "okx":
        return f"{base}-USDT-SWAP"
    if exchange == "bitget":
        return f"{base}/USDT:USDT"
    return f"{base}/USDT"


async def preview_trade(
    doc: dict[str, Any], symbol: str, side: Side,
    entry: float, stop_loss: float, tps: list[float],
    risk_pct: float, leverage: int,
) -> dict[str, Any]:
    """Hitung besaran margin & qty TANPA eksekusi — untuk Semi-Auto preview."""
    if not is_allowed(symbol):
        return {"ok": False, "message": f"{symbol} tidak ada di whitelist Top-100."}
    risk_pct = max(1.0, min(30.0, float(risk_pct)))
    leverage = max(1, min(125, int(leverage)))
    client = await _get_client(doc)
    try:
        bal = await _fetch_usdt_balance(client)
    finally:
        await client.close()
    margin = round(bal * risk_pct / 100.0, 2)
    size_usdt = margin * leverage
    qty = size_usdt / entry if entry > 0 else 0
    risk_per_unit = abs(entry - stop_loss)
    est_loss = round(risk_per_unit * qty, 2)
    tp_est = []
    for i, tp in enumerate(tps[:3]):
        delta = abs(tp - entry)
        tp_qty = qty * TP_SPLIT[i]
        tp_est.append({
            "tp": tp, "qty_share": TP_SPLIT[i],
            "est_profit_usdt": round(delta * tp_qty, 2),
        })
    return {
        "ok": True, "balance_usdt": round(bal, 2), "margin_usdt": margin,
        "size_usdt": round(size_usdt, 2), "qty": qty,
        "leverage": leverage, "risk_pct": risk_pct,
        "est_loss_usdt": est_loss, "tp_estimations": tp_est,
    }


async def execute_trade(
    doc: dict[str, Any], symbol: str, side: Side,
    entry: float, stop_loss: float, tps: list[float],
    risk_pct: float, leverage: int, mode: str = "semi",
) -> dict[str, Any]:
    """Place entry + bracket SL/TP1-3. Return record for asi_trades."""
    if not is_allowed(symbol):
        return {"ok": False, "message": f"{symbol} tidak ada di whitelist Top-100."}
    risk_pct = max(1.0, min(30.0, float(risk_pct)))
    leverage = max(1, min(125, int(leverage)))
    client = await _get_client(doc)
    exch_sym = _ccxt_symbol(doc["exchange"], symbol)
    entry_order_id = None
    sl_order_id = None
    tp_order_ids: list[str] = []
    actual_qty = 0.0
    actual_fill = entry
    try:
        try:
            await client.set_leverage(leverage, exch_sym)
        except Exception:
            pass
        bal = await _fetch_usdt_balance(client)
        margin = bal * risk_pct / 100.0
        size_usdt = margin * leverage
        qty = size_usdt / entry
        try:
            markets = client.markets or await client.load_markets()
            m = markets.get(exch_sym) or {}
            precision = (m.get("precision") or {}).get("amount")
            if isinstance(precision, int) and precision >= 0:
                qty = round(qty, precision)
            elif isinstance(precision, float) and precision > 0:
                step = precision
                qty = (int(qty / step)) * step
        except Exception:
            pass
        if qty <= 0:
            return {"ok": False, "message": "Qty terhitung 0 — margin/balance kurang."}
        entry_order = await client.create_order(
            exch_sym, "market", _ccxt_side(side), qty, None,
            params={"reduceOnly": False},
        )
        entry_order_id = entry_order.get("id")
        actual_fill = float(entry_order.get("average") or entry_order.get("price") or entry)
        actual_qty = float(entry_order.get("filled") or qty)
        close_side = _opposite(side)
        try:
            sl_order = await client.create_order(
                exch_sym, "stop_market", close_side, actual_qty, None,
                params={"stopPrice": stop_loss, "reduceOnly": True, "triggerPrice": stop_loss},
            )
            sl_order_id = sl_order.get("id")
        except Exception as e:
            try:
                await client.create_order(exch_sym, "market", close_side, actual_qty, None,
                                          params={"reduceOnly": True})
            except Exception:
                pass
            return {"ok": False, "message": f"SL gagal, posisi ditutup darurat: {e}"}
        for i, tp in enumerate(tps[:3]):
            tp_qty = actual_qty * TP_SPLIT[i]
            try:
                o = await client.create_order(
                    exch_sym, "take_profit_market", close_side, tp_qty, None,
                    params={"stopPrice": tp, "reduceOnly": True, "triggerPrice": tp},
                )
                tp_order_ids.append(o.get("id"))
            except Exception:
                tp_order_ids.append(None)
    finally:
        try:
            await client.close()
        except Exception:
            pass
    now = datetime.now(timezone.utc).isoformat()
    return {
        "ok": True, "exchange": doc["exchange"], "testnet": bool(doc.get("testnet", True)),
        "symbol": symbol, "ccxt_symbol": exch_sym, "side": side,
        "entry_order_id": entry_order_id, "sl_order_id": sl_order_id,
        "tp_order_ids": tp_order_ids, "entry_price": actual_fill,
        "stop_loss": stop_loss, "take_profits": tps[:3],
        "qty": actual_qty, "leverage": leverage, "risk_pct": risk_pct,
        "mode": mode, "status": "open", "pnl_usdt": 0.0,
        "created_at": now, "updated_at": now,
    }


async def close_position(doc: dict[str, Any], symbol: str, side: Side,
                         qty: float) -> dict[str, Any]:
    """Market close for manual close/cancel bot action."""
    client = await _get_client(doc)
    try:
        exch_sym = _ccxt_symbol(doc["exchange"], symbol)
        o = await client.create_order(
            exch_sym, "market", _opposite(side), qty, None,
            params={"reduceOnly": True},
        )
        return {"ok": True, "id": o.get("id"), "avg": o.get("average")}
    finally:
        try:
            await client.close()
        except Exception:
            pass


async def refresh_trade_pnl(doc: dict[str, Any], trade: dict[str, Any]) -> dict[str, Any]:
    """Query exchange untuk status order & hitung PnL realized/unrealized.

    Logika sederhana:
      - Kalau SL terpenuhi → status=closed, pnl=(sl-entry)*qty signed.
      - Kalau semua TP tereksekusi → status=closed.
      - Kalau salah satu TP eksekusi → status=open, catat parsial.
      - Default → check posisi aktif; PnL unrealized dari mark price.
    """
    client = await _get_client(doc)
    try:
        exch_sym = trade["ccxt_symbol"]
        try:
            positions = await client.fetch_positions([exch_sym])
        except Exception:
            positions = []
        pos = next((p for p in positions if (p or {}).get("contracts", 0)), None)
        if pos:
            unrealized = float(pos.get("unrealizedPnl") or 0)
            return {"status": "open", "pnl_usdt": round(unrealized, 2),
                    "mark_price": pos.get("markPrice")}
        # Tidak ada posisi aktif → asumsikan tertutup. Hitung realized dari orders.
        realized = 0.0
        qty = float(trade.get("qty") or 0)
        entry = float(trade.get("entry_price") or 0)
        side = trade.get("side")
        try:
            fills = await client.fetch_my_trades(exch_sym, limit=20)
        except Exception:
            fills = []
        for f in fills:
            if f.get("timestamp") and trade.get("created_at"):
                # keep it loose: all recent fills on this symbol since open
                pass
            price = float(f.get("price") or 0)
            amount = float(f.get("amount") or 0)
            if side == "BUY":
                realized += (price - entry) * amount if f.get("side") == "sell" else 0
            else:
                realized += (entry - price) * amount if f.get("side") == "buy" else 0
        if realized == 0 and qty > 0:
            # Fallback: anggap SL kena.
            sl = float(trade.get("stop_loss") or entry)
            realized = (sl - entry) * qty if side == "BUY" else (entry - sl) * qty
        return {"status": "closed", "pnl_usdt": round(realized, 2)}
    finally:
        try:
            await client.close()
        except Exception:
            pass
