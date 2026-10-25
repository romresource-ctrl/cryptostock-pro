"""v10.4.1 — AC monitor closes via market when margin ROI >= AC% (mocked, no orders)."""
import sys

import pytest

sys.path.insert(0, "/app/backend")
sys.path.insert(0, "/app/backend/tests")
from asi_bot import engine  # noqa: E402
from test_iter63_v1034_ghost_open import DOC, _patch  # noqa: E402

SL_ONLY = [{"algoId": 1, "orderType": "STOP_MARKET", "side": "BUY", "closePosition": True}]


def _t(**kw):
    t = {"symbol": "ATOM", "side": "SELL", "qty": 100, "entry_price": 1.61, "leverage": 50,
         "stop_loss": 1.628, "take_profits": [1.5858], "auto_close_pct": 75,
         "sl_order_id": 1, "created_at": "2026-10-25T11:47:00+00:00"}
    t.update(kw)
    return t


@pytest.mark.asyncio
async def test_ac_reached_closes_market(monkeypatch):
    closed = []
    # SHORT 50x: 1.5% turun = 75% ROI → mark 1.5855
    _patch(monkeypatch, {"positionAmt": "-100", "markPrice": "1.5855", "unRealizedProfit": "2.4"},
           algos=SL_ONLY, closed=closed)
    r = await engine._refresh_binance(DOC, _t())
    assert closed == [("ATOM", "SELL", 100)]
    assert r["status"] == "closed" and r["close_reason"] == "AC"


@pytest.mark.asyncio
async def test_ac_not_reached_stays_open_sl_only_is_hard(monkeypatch):
    closed = []
    _patch(monkeypatch, {"positionAmt": "-100", "markPrice": "1.60", "unRealizedProfit": "1"},
           algos=SL_ONLY, closed=closed)
    r = await engine._refresh_binance(DOC, _t())
    assert closed == [] and r["status"] == "open"
    assert r.get("bracket_type") == "hard"  # SL-only counts as protected for AC


@pytest.mark.asyncio
async def test_non_ac_trade_not_closed_by_roi(monkeypatch):
    closed = []
    algos = SL_ONLY + [{"algoId": 2, "orderType": "TAKE_PROFIT_MARKET", "side": "BUY"}]
    _patch(monkeypatch, {"positionAmt": "-100", "markPrice": "1.5855", "unRealizedProfit": "2.4"},
           algos=algos, closed=closed)
    r = await engine._refresh_binance(DOC, _t(auto_close_pct=0))
    assert closed == [] and r["status"] == "open"
