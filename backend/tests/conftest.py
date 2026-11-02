"""v10.7.20 — scanner harness tests tidak boleh bergantung pada candle 5m
live Binance: konfirmasi 2 candle 5m di-stub lolos (diuji terpisah di
test_iter73_v10720_5m_confirm.py)."""
import sys

import pytest

sys.path.insert(0, "/app/backend")


@pytest.fixture(autouse=True)
def _stub_5m_confirm(monkeypatch):
    try:
        from asi_bot import scheduler
    except Exception:
        yield
        return

    async def _ok(device_id, sym, side):
        return "ok"
    monkeypatch.setattr(scheduler, "_c5_check", _ok)
    # v10.7.23 — harness tidak punya candle 1H: gate EMA50 1H di-stub lolos
    # (diuji terpisah di test_iter74_v10723_trend1h_gate.py)
    monkeypatch.setattr(scheduler, "_trend1h_gate", lambda *a, **k: None)
    yield
