"""v10.2.37 — SL clamp 1–2%, margin per trade ($), trailing off → SL guard (no orders)."""
import sys

import pytest

sys.path.insert(0, "/app/backend")
from asi_bot import engine  # noqa: E402
from asi_bot.routes import BotConfigPayload  # noqa: E402


class _Stop(Exception):
    pass


async def _cap(monkeypatch, side, sl, tps, **kw):
    seen = {}

    async def fake_fb(doc, symbol, side_, entry, sl_, tps_, risk, lev, mode, tp_count, trailing, *a):
        seen.update(sl=sl_, tps=tps_, trailing=trailing)
        raise _Stop

    monkeypatch.setattr(engine, "_execute_ccxt_fallback", fake_fb)
    with pytest.raises(_Stop):
        await engine.execute_trade({"exchange": "bybit"}, "TIA", side, 100.0, sl, tps,
                                   5, 12, tp_count=3, trailing_callback_rate=2.0, **kw)
    return seen


@pytest.mark.asyncio
async def test_wide_sl_clamped_to_2pct(monkeypatch):
    s = await _cap(monkeypatch, "BUY", 94.9, [105, 108, 110])  # TIA-like 5.1%
    assert s["sl"] == pytest.approx(98.0)
    assert s["tps"][0] == pytest.approx(102.0)  # symmetry TP1 = 1R
    assert s["trailing"] == 0.0


@pytest.mark.asyncio
async def test_tight_sl_raised_to_1pct_short(monkeypatch):
    s = await _cap(monkeypatch, "SELL", 100.3, [99, 98, 97])
    assert s["sl"] == pytest.approx(101.0)


@pytest.mark.asyncio
async def test_kiss_pivot_sl_within_range(monkeypatch):
    s = await _cap(monkeypatch, "BUY", 99, [101, 102, 103], formula_tag="KISS Pivot")
    assert 0.01 - 1e-9 <= (100 - s["sl"]) / 100 <= 0.02 + 1e-9


def test_resolve_margin():
    assert engine._resolve_margin(1000, 5, 150) == 150
    assert engine._resolve_margin(100, 5, 150) == 100  # capped by balance
    assert engine._resolve_margin(1000, 5, 0) == 50  # legacy fallback


def test_config_margin_field():
    assert BotConfigPayload(exchange="binance", margin_usdt=120.5).margin_usdt == 120.5
    with pytest.raises(Exception):
        BotConfigPayload(exchange="binance", margin_usdt=-1)
