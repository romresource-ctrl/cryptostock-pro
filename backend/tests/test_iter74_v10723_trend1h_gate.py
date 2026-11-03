"""v10.7.23 — hard gate EMA50 1H simbol, bypass _long_relaxed off, BUY 2 siklus."""
import inspect
import sys
sys.path.insert(0, "/app/backend")
from asi_bot import scheduler  # noqa: E402

_raw = open(scheduler.__file__).read()
_ns: dict = {}
exec(_raw[_raw.index("def _trend1h_gate"):_raw.index("def _btc15m_short_block")], _ns)
gate = _ns["_trend1h_gate"]


def test_long_rules():
    assert gate("BUY", 101, 100, 99) is None
    assert gate("BUY", 99, 100, 99) == "trend_1h_ema50_block_LONG"    # di bawah EMA
    assert gate("BUY", 101, 100, 100.5) == "trend_1h_ema50_block_LONG"  # slope turun


def test_short_rules():
    assert gate("SELL", 99, 100, 101) is None
    assert gate("SELL", 101, 100, 101) == "trend_1h_ema50_block_SHORT"
    assert gate("SELL", 99, 100, 99.5) == "trend_1h_ema50_block_SHORT"


def test_fail_closed_and_wiring():
    assert gate("BUY", None, 100, 99) == "trend_1h_data_unavailable"
    src = inspect.getsource(scheduler._run_full_auto_scanner)
    assert src.index("_trend1h_gate(sig[\"side\"]") < src.index("await _c5_check(")
    assert "_long_relaxed = False" in src
    assert scheduler.BUY_CONFIRM_CYCLES == 2 == scheduler.SELL_CONFIRM_CYCLES


def test_gate_unconditional_for_all_formulas_and_paths():
    # v10.7.25 — gate tidak dibungkus kondisi formula/profil apa pun
    src = inspect.getsource(scheduler._run_full_auto_scanner)
    i = src.index('_tg = _trend1h_gate(sig["side"], _px1h, _ema1h, _ema1h_prev)')
    pre = src[max(0, i - 400):i]
    for word in ("formula", "longterm", "Confluence", "profile", "engine"):
        assert f"if {word}" not in pre and f"{word} ==" not in pre.split("\n")[-2]
    # EMA 1H dihitung utk SEMUA simbol yg punya sinyal (tanpa filter formula)
    assert 'if any(isinstance(s, dict) and s.get("side") for s in results):' in src
    # relay Titan juga lewat gate
    relay = inspect.getsource(scheduler._run_titan_relay) if hasattr(scheduler, "_run_titan_relay") else open(scheduler.__file__).read()
    assert "_trend1h_gate(side, *(await _trend1h_inputs(base)))" in relay
