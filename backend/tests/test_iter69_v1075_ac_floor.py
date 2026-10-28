"""v10.7.5 — Full-Auto AC: untung minimal = rugi (AC ≥ jarak SL × leverage + fee)."""
import inspect
import math
import sys

sys.path.insert(0, "/app/backend")
from asi_bot import engine  # noqa: E402


def test_ac_floor_wired_full_only():
    src = inspect.getsource(engine.execute_trade)
    assert 'if auto_close_pct and mode == "full" and entry > 0 and stop_loss and leverage > 0:' in src
    assert "_min_ac = int(math.ceil(round((_sl_pct + 0.001) * leverage * 100.0, 6)))" in src
    i_floor = src.index("_min_ac = int(")
    i_tp = src.index("tps = [entry * (1 + _ac_sgn * auto_close_pct / 100.0 / leverage)]")
    assert i_floor < i_tp  # TP representatif memakai AC yang sudah dinaikkan


def test_floor_math_example():
    # SL 1.5% × 35x → minimal 56% (bukan 50%)
    assert int(math.ceil(round((0.015 + 0.001) * 35 * 100.0, 6))) == 56
    # SL 1.2% × 20x → 26%; AC 45% tidak diubah
    assert int(math.ceil(round((0.012 + 0.001) * 20 * 100.0, 6))) == 26


def test_sl_follows_ac_full_only():
    src = inspect.getsource(engine.execute_trade)
    assert "_d_sl = auto_close_pct / 100.0 / leverage - 0.001" in src
    i_sl = src.index("_d_sl = auto_close_pct / 100.0 / leverage - 0.001")
    i_floor = src.index("_min_ac = int(")
    assert i_sl < i_floor


def test_sl_follows_ac_math():
    # AC 45% @20x → SL 2.15% → dipotong 2%; AC 35% @20x → SL 1.65%
    f = lambda ac, lev: min(0.02, max(0.01, ac / 100 / lev - 0.001))
    assert abs(f(45, 20) - 0.02) < 1e-9
    assert abs(f(35, 20) - 0.0165) < 1e-9
    assert abs(f(35, 50) - 0.01) < 1e-9   # AC lalu dinaikkan floor → 55%
    assert int(math.ceil(round((0.01 + 0.001) * 50 * 100.0, 6))) == 55
