"""v10.2.36 — Auto-Close Profit (ROI margin) + anti-whipsaw/burst (pure tests, no orders)."""
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, "/app/backend")
from asi_bot import engine  # noqa: E402
from asi_bot.scheduler import _whipsaw_block_side  # noqa: E402
from asi_bot.routes import BotConfigPayload, TradePayload  # noqa: E402


class _Stop(Exception):
    pass


async def _capture(monkeypatch, side, pct, lev=12, profile=None, tag=None):
    seen = {}

    async def fake_fb(doc, symbol, side_, entry, sl, tps, risk, lev_, mode, tp_count, *a):
        seen.update(tps=tps, tp_count=tp_count, trailing=a[0])
        raise _Stop

    monkeypatch.setattr(engine, "_execute_ccxt_fallback", fake_fb)
    with pytest.raises(_Stop):
        await engine.execute_trade(
            {"exchange": "bybit"}, "LTC", side, 100.0,
            101.0 if side == "SELL" else 99.0,
            [99.0, 98.0, 97.0] if side == "SELL" else [101.0, 102.0, 103.0],
            5, lev, tp_count=3, profile=profile, formula_tag=tag,
            auto_close_pct=pct)
    return seen


@pytest.mark.asyncio
async def test_long_target_roi(monkeypatch):
    s = await _capture(monkeypatch, "BUY", 10, lev=10)
    assert s["tp_count"] == 1 and s["trailing"] == 0.0
    assert s["tps"] == [pytest.approx(101.0)]  # +1% price × 10x = 10% ROI


@pytest.mark.asyncio
async def test_short_target_roi(monkeypatch):
    s = await _capture(monkeypatch, "SELL", 50, lev=10)
    assert s["tps"] == [pytest.approx(95.0)]


@pytest.mark.asyncio
async def test_kiss_pivot_target_wins(monkeypatch):
    s = await _capture(monkeypatch, "BUY", 25, lev=12, tag="KISS Pivot")
    assert s["tps"] == [pytest.approx(100 * (1 + 0.25 / 12))]


@pytest.mark.asyncio
async def test_off_keeps_tp_ladder(monkeypatch):
    s = await _capture(monkeypatch, "BUY", 0)
    assert s["tp_count"] == 3 and len(s["tps"]) == 3


@pytest.mark.asyncio
async def test_invalid_pct_ignored(monkeypatch):
    s = await _capture(monkeypatch, "BUY", 33)
    assert s["tp_count"] == 3


def test_payloads_accept_values():
    for p in (0, 10, 15, 20, 25, 50, 100):
        assert BotConfigPayload(exchange="binance", auto_close_pct=p).auto_close_pct == p
    with pytest.raises(Exception):
        BotConfigPayload(exchange="binance", auto_close_pct=30)
    tp = TradePayload(exchange="binance", symbol="LTC", side="BUY", entry=1,
                      stop_loss=0.9, take_profits=[1.1], auto_close_pct=15)
    assert tp.auto_close_pct == 15


def _t(side, pnl, mins_ago, now):
    return {"side": side, "pnl_usdt": pnl,
            "closed_at": (now - timedelta(minutes=mins_ago)).isoformat()}


def test_whipsaw_blocks_opposite_after_short_losses():
    now = datetime.now(timezone.utc)
    rc = [_t("SELL", -52, 5, now), _t("SELL", -33, 20, now)]
    assert _whipsaw_block_side(rc, now) == "BUY"


def test_whipsaw_expires_after_60m():
    now = datetime.now(timezone.utc)
    assert _whipsaw_block_side([_t("SELL", -52, 61, now), _t("SELL", -33, 90, now)], now) is None


def test_whipsaw_needs_same_side_losses():
    now = datetime.now(timezone.utc)
    assert _whipsaw_block_side([_t("SELL", -52, 5, now), _t("BUY", -33, 9, now)], now) is None
    assert _whipsaw_block_side([_t("SELL", -52, 5, now), _t("SELL", 18, 9, now)], now) is None
    assert _whipsaw_block_side([_t("SELL", -52, 5, now)], now) is None
