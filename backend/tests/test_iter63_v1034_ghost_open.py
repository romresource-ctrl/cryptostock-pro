"""v10.3.4 — Ghost open trade fixes in _refresh_binance (mocked Binance, no orders)."""
import sys

import pytest

sys.path.insert(0, "/app/backend")
from asi_bot import engine  # noqa: E402

DOC = {"exchange": "binance", "api_key_enc": "x", "api_secret_enc": "y", "testnet": True}


def _patch(monkeypatch, pos, fills=None, algos=None, closed=None):
    monkeypatch.setattr(engine, "decrypt", lambda v: v)

    async def position_risk(*a, **k):
        return pos

    async def req(*a, **k):
        return 200, fills or []

    async def algo(*a, **k):
        return algos if algos is not None else []

    async def legacy(*a, **k):
        return []

    async def rci(*a, **k):
        return {"pnl": -34.7, "price": 1.722}

    async def cp(doc, sym, side, qty):
        closed.append((sym, side, qty))
        return {"ok": True, "avg": 1.3140}

    monkeypatch.setattr(engine.br, "position_risk", position_risk)
    monkeypatch.setattr(engine.br, "_request", req)
    monkeypatch.setattr(engine.br, "open_algo_orders", algo)
    monkeypatch.setattr(engine.br, "open_orders_legacy", legacy)
    monkeypatch.setattr(engine.br, "realized_close_info", rci)
    monkeypatch.setattr(engine, "close_position", cp)


@pytest.mark.asyncio
async def test_opposite_side_position_closes_record(monkeypatch):
    _patch(monkeypatch, {"positionAmt": "500", "markPrice": "1.71"}, closed=[])
    t = {"symbol": "ATOM", "side": "SELL", "qty": 1509, "entry_price": 1.699,
         "stop_loss": 1.724, "take_profits": [1.677], "created_at": "2026-10-22T10:03:00+00:00"}
    r = await engine._refresh_binance(DOC, t)
    assert r["status"] == "closed"


@pytest.mark.asyncio
async def test_sl_fill_full_qty_closes_even_if_other_position(monkeypatch):
    _patch(monkeypatch, {"positionAmt": "-1275", "markPrice": "1.714", "unRealizedProfit": "-5"},
           closed=[])
    t = {"symbol": "ATOM", "side": "SELL", "qty": 1509, "entry_price": 1.699,
         "stop_loss": 1.724, "take_profits": [1.677], "created_at": "2026-10-22T10:03:00+00:00",
         "sl_fill": {"level": "SL", "price": 1.722, "qty": 1509, "pnl": -34.71}}
    r = await engine._refresh_binance(DOC, t)
    assert r["status"] == "closed" and r["close_reason"] == "SL"


@pytest.mark.asyncio
async def test_missing_sl_and_crossed_emergency_close(monkeypatch):
    closed = []
    _patch(monkeypatch, {"positionAmt": "1403", "markPrice": "1.3142", "unRealizedProfit": "-53"},
           algos=[], closed=closed)
    t = {"symbol": "XRP", "side": "BUY", "qty": 1403, "entry_price": 1.3522,
         "stop_loss": 1.3360, "take_profits": [1.3682], "created_at": "2026-10-21T08:52:00+00:00"}
    r = await engine._refresh_binance(DOC, t)
    assert closed == [("XRP", "BUY", 1403)]
    assert r["status"] == "closed" and "emergency" in r["close_reason_detail"]


@pytest.mark.asyncio
async def test_sl_live_no_emergency(monkeypatch):
    closed = []
    algos = [{"algoId": 1, "orderType": "STOP_MARKET", "side": "SELL", "closePosition": True},
             {"algoId": 2, "orderType": "TAKE_PROFIT_MARKET", "side": "SELL"}]
    _patch(monkeypatch, {"positionAmt": "1403", "markPrice": "1.3142", "unRealizedProfit": "-53"},
           algos=algos, closed=closed)
    t = {"symbol": "XRP", "side": "BUY", "qty": 1403, "entry_price": 1.3522,
         "stop_loss": 1.3360, "take_profits": [1.3682], "created_at": "2026-10-21T08:52:00+00:00"}
    r = await engine._refresh_binance(DOC, t)
    assert closed == [] and r["status"] == "open"


@pytest.mark.asyncio
async def test_normal_open_stays_open(monkeypatch):
    closed = []
    _patch(monkeypatch, {"positionAmt": "1403", "markPrice": "1.35", "unRealizedProfit": "-3"},
           algos=[], closed=closed)
    t = {"symbol": "XRP", "side": "BUY", "qty": 1403, "entry_price": 1.3522,
         "stop_loss": 1.3360, "take_profits": [1.3682], "created_at": "2026-10-21T08:52:00+00:00"}
    r = await engine._refresh_binance(DOC, t)
    assert closed == [] and r["status"] == "open"
