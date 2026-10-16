"""v10.2.20 — Backend engine tests for the "TP tertelan" bug fix.

The engine now walks /fapi/v1/userTrades every tick (instead of a single
`last_reduce_fill_price` snapshot) and attributes every reduce-only fill
to a TP level (±0.4%) or SL (±1%), idempotently via `orderId`, and only
advances `last_fill_check_ms` when the HTTP call succeeded (lossless).

All scenarios here mock br.* and engine.move_sl_to_breakeven; no real
Binance order is placed.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Any

import pytest

from backend.asi_bot import engine  # type: ignore


# ─────────────────────── fixtures ──────────────────────────────────────
def _mk_trade(**overrides: Any) -> dict[str, Any]:
    base = {
        "symbol": "XYZ",
        "ccxt_symbol": "XYZ/USDT:USDT",
        "side": "SELL",                # TP < entry < SL (reduce side = BUY)
        "entry_price": 100.0,
        "qty": 10.0,
        "take_profits": [98.0, 96.0, 94.0],
        "stop_loss": 103.0,
        "created_at": "2026-10-20T00:00:00+00:00",
        "trailing_callback_rate": 0.0,
        "trailing_activated": False,
    }
    base.update(overrides)
    return base


DOC = {"api_key_enc": "x", "api_secret_enc": "y",
       "testnet": True, "exchange": "binance"}

T0_MS = 1_770_000_000_000  # fixed epoch within window


def _pos_open(amt: float = 10.0, mark: float = 97.0) -> dict[str, Any]:
    return {"positionAmt": -amt if amt > 0 else amt,  # SELL → negative
            "unRealizedProfit": 0.0, "marginType": "isolated",
            "markPrice": mark, "leverage": 10}


def _pos_flat() -> dict[str, Any]:
    return {"positionAmt": 0, "unRealizedProfit": 0.0,
            "marginType": "isolated", "markPrice": 0.0, "leverage": 10}


def _fill(order_id: str, price: float, qty: float, t_ms: int,
          side: str = "BUY", pnl: float = 0.0) -> dict[str, Any]:
    return {"orderId": order_id, "price": str(price), "qty": str(qty),
            "realizedPnl": str(pnl), "side": side, "time": t_ms,
            "symbol": "XYZUSDT"}


@pytest.fixture(autouse=True)
def _patch_decrypt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine, "decrypt", lambda s: s)


# ─────────────────────── helper: install mocks ─────────────────────────
def _install_binance_mocks(
    monkeypatch: pytest.MonkeyPatch, *,
    pos: dict[str, Any],
    user_trades: list[dict[str, Any]] | None = None,
    user_trades_code: int = 200,
    user_trades_raise: bool = False,
    realized: dict[str, Any] | None = None,
    sl_target_price: float | None = None,
) -> dict[str, Any]:
    """Monkeypatch br.* and engine.move_sl_to_breakeven; return a dict of
    captured call counters so tests can assert behaviours."""
    captured: dict[str, Any] = {"userTrades_calls": 0, "move_sl_calls": []}

    async def fake_position_risk(*_a: Any, **_kw: Any) -> dict[str, Any]:
        return pos

    async def fake_request(method: str, path: str, *_a: Any, **_kw: Any):
        if path == "/fapi/v1/userTrades":
            captured["userTrades_calls"] += 1
            if user_trades_raise:
                raise RuntimeError("network down")
            return (user_trades_code, user_trades if user_trades is not None else [])
        return (200, [])

    async def fake_realized(*_a: Any, **_kw: Any):
        return realized

    async def fake_open_algo(*_a: Any, **_kw: Any):
        return []

    async def fake_open_legacy(*_a: Any, **_kw: Any):
        return []

    async def fake_move_sl(_doc: Any, _trade: Any, *,
                           target_price: float) -> dict[str, Any]:
        captured["move_sl_calls"].append(target_price)
        return {"ok": True, "new_sl": target_price, "detail": "mocked"}

    monkeypatch.setattr(engine.br, "position_risk", fake_position_risk)
    monkeypatch.setattr(engine.br, "_request", fake_request)
    monkeypatch.setattr(engine.br, "realized_close_info", fake_realized)
    monkeypatch.setattr(engine.br, "open_algo_orders", fake_open_algo)
    monkeypatch.setattr(engine.br, "open_orders_legacy", fake_open_legacy)

    async def fake_last_fill(*_a: Any, **_kw: Any):
        return None

    monkeypatch.setattr(engine.br, "last_fill_price", fake_last_fill)
    monkeypatch.setattr(engine, "move_sl_to_breakeven", fake_move_sl)
    return captured


# ─────────────────────── scenarios ─────────────────────────────────────
# Scenario 1 — TP1 only
@pytest.mark.asyncio
async def test_scenario1_tp1_only(monkeypatch: pytest.MonkeyPatch) -> None:
    trade = _mk_trade(qty=10.0, last_fill_check_ms=T0_MS)
    fills = [_fill("111", price=97.9, qty=5.0, t_ms=T0_MS + 1000, pnl=10.5)]
    captured = _install_binance_mocks(
        monkeypatch, pos=_pos_open(amt=5.0), user_trades=fills)
    upd = await engine._refresh_binance(DOC, trade)
    assert upd["status"] == "open"
    assert "tp_fills" in upd and len(upd["tp_fills"]) == 1
    assert upd["tp_fills"][0]["level"] == "TP1"
    assert upd["tp_filled"] == [True, False, False]
    assert upd["stop_loss"] == pytest.approx(98.0)
    assert captured["move_sl_calls"] == [98.0]
    # last_fill_check_ms must have been advanced past the fill
    assert upd["last_fill_check_ms"] == T0_MS + 1001


# Scenario 2 — TP1+TP2 in a single window
@pytest.mark.asyncio
async def test_scenario2_tp1_and_tp2(monkeypatch: pytest.MonkeyPatch) -> None:
    trade = _mk_trade()
    fills = [
        _fill("111", 97.9, 5.0, T0_MS + 1000, pnl=10.5),
        _fill("222", 96.1, 2.5, T0_MS + 2000, pnl=9.75),
    ]
    captured = _install_binance_mocks(
        monkeypatch, pos=_pos_open(amt=2.5), user_trades=fills)
    upd = await engine._refresh_binance(DOC, trade)
    assert len(upd["tp_fills"]) == 2
    assert [x["level"] for x in upd["tp_fills"]] == ["TP1", "TP2"]
    assert upd["tp_filled"] == [True, True, False]
    # SL guard follows highest TP in window → TP2 price
    assert upd["stop_loss"] == pytest.approx(96.0)
    assert captured["move_sl_calls"] == [96.0]


# Scenario 3 — Idempotent: same orderId already present
@pytest.mark.asyncio
async def test_scenario3_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    existing = {"level": "TP1", "price": 97.9, "qty": 5.0, "pnl": 10.5,
                "at": "2026-10-20T00:16:40+00:00", "orderId": "111"}
    trade = _mk_trade(tp_fills=[existing], tp_filled=[True, False, False],
                      last_fill_check_ms=T0_MS)
    # Re-fetch returns the SAME fill — must be ignored
    fills = [_fill("111", 97.9, 5.0, T0_MS + 1000, pnl=10.5)]
    captured = _install_binance_mocks(
        monkeypatch, pos=_pos_open(amt=5.0), user_trades=fills)
    upd = await engine._refresh_binance(DOC, trade)
    # tp_fills should NOT have been written again (no duplication)
    assert "tp_fills" not in upd or len(upd["tp_fills"]) == 1
    assert captured["move_sl_calls"] == []  # SL guard already consumed


# Scenario 4 — SL slippage within 1% tolerance
@pytest.mark.asyncio
async def test_scenario4_sl_slippage(monkeypatch: pytest.MonkeyPatch) -> None:
    trade = _mk_trade()
    # SL=103, fill@103.5 → 0.49% slippage (<1%) → treated as SL
    fills = [_fill("333", 103.5, 10.0, T0_MS + 1500, pnl=-35.0)]
    _install_binance_mocks(
        monkeypatch, pos=_pos_open(amt=10.0), user_trades=fills)
    upd = await engine._refresh_binance(DOC, trade)
    assert "sl_fill" in upd
    assert upd["sl_fill"]["level"] == "SL"
    assert upd["sl_fill"]["price"] == pytest.approx(103.5)
    # Status still open in this scenario (positionAmt > 0)
    assert upd["status"] == "open"


# Scenario 5 — Fetch failed (HTTP 500) → check-point must NOT advance
@pytest.mark.asyncio
async def test_scenario5_fetch_failed_lossless(
        monkeypatch: pytest.MonkeyPatch) -> None:
    trade = _mk_trade(last_fill_check_ms=T0_MS)
    _install_binance_mocks(
        monkeypatch, pos=_pos_open(amt=10.0),
        user_trades=[], user_trades_code=500)
    upd = await engine._refresh_binance(DOC, trade)
    # last_fill_check_ms must NOT be present (lossless retry next tick)
    assert "last_fill_check_ms" not in upd
    # No tp_fills / sl_fill touched
    assert "tp_fills" not in upd
    assert "sl_fill" not in upd


@pytest.mark.asyncio
async def test_scenario5b_fetch_raises(
        monkeypatch: pytest.MonkeyPatch) -> None:
    trade = _mk_trade(last_fill_check_ms=T0_MS)
    _install_binance_mocks(
        monkeypatch, pos=_pos_open(amt=10.0), user_trades_raise=True)
    upd = await engine._refresh_binance(DOC, trade)
    assert "last_fill_check_ms" not in upd
    assert "tp_fills" not in upd


# Scenario 6 — Manual partial fill far from any TP/SL level
@pytest.mark.asyncio
async def test_scenario6_manual_partial(
        monkeypatch: pytest.MonkeyPatch) -> None:
    trade = _mk_trade()
    # Fill @99.5 — far from TP1=98 (1.53%) and SL=103 (3.4%) → no label
    fills = [_fill("444", 99.5, 2.0, T0_MS + 500, pnl=1.0)]
    _install_binance_mocks(
        monkeypatch, pos=_pos_open(amt=8.0), user_trades=fills)
    upd = await engine._refresh_binance(DOC, trade)
    assert "tp_fills" not in upd
    assert "sl_fill" not in upd
    assert upd["qty_remaining"] == pytest.approx(8.0)


# Scenario 7 — Full close via realized_close_info → close_reason=SL
@pytest.mark.asyncio
async def test_scenario7_full_close_sl(
        monkeypatch: pytest.MonkeyPatch) -> None:
    trade = _mk_trade()
    _install_binance_mocks(
        monkeypatch, pos=_pos_flat(),
        realized={"pnl": -32.5, "price": 103.0})
    upd = await engine._refresh_binance(DOC, trade)
    assert upd["status"] == "closed"
    assert upd["close_reason"] == "SL"
    assert upd["closed_price"] == pytest.approx(103.0)
    assert "sl_fill" in upd and upd["sl_fill"]["level"] == "SL"


# ─────────────────────── extra edge cases (agent's duty) ────────────────
# E1 — BUY fill on the loss side for a SELL trade (price > entry): must
# NOT be labelled TP. For SELL entry=100, fill@102 is reduce side (BUY)
# but ABOVE entry → neither TP (TPs are 98/96/94) nor SL (103 within 1%?
# 102 vs 103 = 0.97% < 1% → actually would hit SL tolerance). Use 101.5
# which is 1.46% from SL → neither TP nor SL, pure manual.
@pytest.mark.asyncio
async def test_edge_buy_fill_on_loss_side_not_labelled_tp(
        monkeypatch: pytest.MonkeyPatch) -> None:
    trade = _mk_trade()
    fills = [_fill("555", 101.5, 3.0, T0_MS + 500, pnl=-4.5)]
    _install_binance_mocks(
        monkeypatch, pos=_pos_open(amt=7.0), user_trades=fills)
    upd = await engine._refresh_binance(DOC, trade)
    assert "tp_fills" not in upd   # 101.5 is far above every TP
    assert "sl_fill" not in upd    # 101.5 vs 103 = 1.46% > 1%


# E2 — TP ladder with only 2 levels (not 3) → tp_filled length matches
@pytest.mark.asyncio
async def test_edge_two_tp_ladder(monkeypatch: pytest.MonkeyPatch) -> None:
    trade = _mk_trade(take_profits=[98.0, 96.0])
    fills = [_fill("666", 97.9, 5.0, T0_MS + 500, pnl=10.5)]
    _install_binance_mocks(
        monkeypatch, pos=_pos_open(amt=5.0), user_trades=fills)
    upd = await engine._refresh_binance(DOC, trade)
    assert upd["tp_filled"] == [True, False]
    assert len(upd["tp_filled"]) == 2


# E3 — trailing_callback_rate > 0 → SL guard must NOT be invoked
@pytest.mark.asyncio
async def test_edge_trailing_disables_sl_guard(
        monkeypatch: pytest.MonkeyPatch) -> None:
    trade = _mk_trade(trailing_callback_rate=1.5)
    fills = [_fill("777", 97.9, 5.0, T0_MS + 500, pnl=10.5)]
    captured = _install_binance_mocks(
        monkeypatch, pos=_pos_open(amt=5.0), user_trades=fills)
    upd = await engine._refresh_binance(DOC, trade)
    assert len(upd["tp_fills"]) == 1
    assert captured["move_sl_calls"] == []  # guard disabled
    # stop_loss must NOT have been moved
    assert "stop_loss" not in upd


# E4 — opposite-side fill (SELL on a SELL trade) must be skipped entirely
@pytest.mark.asyncio
async def test_edge_wrong_side_fill_skipped(
        monkeypatch: pytest.MonkeyPatch) -> None:
    trade = _mk_trade()
    # side=SELL for a SELL trade → not reduce side → engine must ignore
    fills = [_fill("888", 97.9, 5.0, T0_MS + 500, pnl=0.0, side="SELL")]
    _install_binance_mocks(
        monkeypatch, pos=_pos_open(amt=10.0), user_trades=fills)
    upd = await engine._refresh_binance(DOC, trade)
    assert "tp_fills" not in upd
    assert "sl_fill" not in upd


# ─────────────────────── public API regression ─────────────────────────
BASE_URL = (os.environ.get("EXPO_BACKEND_URL") or "").rstrip("/")


@pytest.mark.skipif(not BASE_URL, reason="EXPO_BACKEND_URL not set")
def test_no_trades_reconcile_endpoint() -> None:
    """v10.2.20 — /trades/reconcile has been removed (engine does it inline)."""
    import requests
    r = requests.post(f"{BASE_URL}/api/asi/trades/reconcile",
                      json={}, timeout=10)
    assert r.status_code in (404, 405), (
        f"/trades/reconcile should be gone, got {r.status_code}")
