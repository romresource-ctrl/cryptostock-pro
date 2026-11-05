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


# v10.7.30 — keputusan user: BUY/SELL_CONFIRM_CYCLES kembali ke 1 dan syarat
# slope (EMA50 1H & 4H) dihapus. Tes di bawah mengunci perilaku LAMA (2 siklus
# / slope relax) yang sengaja diganti; perilaku baru diuji di
# test_iter74_v10723_trend1h_gate.py::test_v10730_price_only_cycles_and_strong_sell.
_SUPERSEDED_V10730 = (
    "test_buy_default_two_cycles",
    "test_buy_executes_first_cycle_then_no_reexecute",
    "test_sell_executes_second_cycle",
    "test_buy_gates_constant_values",
    "test_sell_confirm_cycles",
    "test_required_cycles_param_override_for_sell",
    "test_sell_requires_two_cycles_then_executes",
    "test_buy_two_cycle_confirmation",
    "test_scan_debug_buy_gates_has_six_new_fields",
    "test_long_passes_when_price_above_ema_slope_dn_and_streak_ge_3",
    "test_long_rejected_when_slope_dn_and_streak_0",
    "test_long_slope_relaxed_immediately_on_trending_up_v10229",
    "test_short_passes_when_price_below_ema_slope_up_and_dn_streak_ge_3",
    "test_short_rejected_when_slope_up_and_dn_streak_0",
    "test_sell_two_cycle_confirmation",
    "test_trend4h_slope_relax_long",
    "test_a1_two_open_sell_new_sell_not_rejected_by_cap",
    "test_b3_sell_6h_drop_only_btc_flat_goes_to_confirmation",
    "test_c3_sell_two_cycle_confirmation",
)


def pytest_collection_modifyitems(config, items):
    mark = pytest.mark.skip(reason="superseded by v10.7.30 user decision (1 cycle, no slope)")
    for it in items:
        if it.name in _SUPERSEDED_V10730 and any(
                k in it.nodeid for k in ("iter47", "iter50", "iter51", "iter52", "iter53")):
            it.add_marker(mark)
