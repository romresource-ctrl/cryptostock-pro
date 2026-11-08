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
    assert gate("BUY", 101, 100, 100.5) is None  # v10.7.30 — slope tidak dicek


def test_short_rules():
    assert gate("SELL", 99, 100, 101) is None
    assert gate("SELL", 101, 100, 101) == "trend_1h_ema50_block_SHORT"
    assert gate("SELL", 99, 100, 99.5) is None  # v10.7.30 — slope tidak dicek


def test_fail_closed_and_wiring():
    assert gate("BUY", None, 100, 99) == "trend_1h_data_unavailable"
    src = inspect.getsource(scheduler._run_full_auto_scanner)
    assert src.index("_trend1h_gate(sig[\"side\"]") < src.index("await _c5_check(")
    assert "_long_relaxed = False" in src
    assert scheduler.BUY_CONFIRM_CYCLES == 1 == scheduler.SELL_CONFIRM_CYCLES  # v10.7.30


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


def test_v10726_closed_candle_and_record():
    txt = open(scheduler.__file__).read()
    assert "_ema1h, _ema1h_prev, _px1h = _es[-2], _es[-5], _c1[-2]" in txt
    assert "return c1[-2], es[-2], es[-5]" in txt
    src = inspect.getsource(scheduler._run_full_auto_scanner)
    i = src.index('rec["trend1h_gate"] = {')
    assert i > src.index('_tg = _trend1h_gate(sig["side"]')
    for k in ('"price_1h_close": _px1h', '"ema50_1h": _ema1h', '"ema50_1h_prev": _ema1h_prev', '"result":'):
        assert k in src[i:i + 400]


def test_v10729_gates_restored_and_dip_skips_with_trend():
    src = inspect.getsource(scheduler._run_full_auto_scanner)
    assert "_scalper_exempt = False" in src
    assert "_tg_exempt = _tg" not in src
    assert "_dip = None if _with_trend else _dip_top_flip(" in src
    assert "if not _dip and not _with_trend and _diptop_hold_blocks(" in src


def test_v10730_price_only_cycles_and_strong_sell():
    g = _ns_v30 = {}
    exec(_raw_now()[_raw_now().index("def _trend1h_gate"):_raw_now().index("def _btc15m_short_block")], g)
    f = g["_trend1h_gate"]
    assert f("BUY", 101, 100, 105) is None          # slope turun tidak lagi memblok
    assert f("BUY", 99, 100, 95) == "trend_1h_ema50_block_LONG"
    assert f("SELL", 99, 100, 95) is None           # slope naik tidak lagi memblok
    assert f("SELL", 101, 100, 105) == "trend_1h_ema50_block_SHORT"
    assert scheduler.BUY_CONFIRM_CYCLES == 1 == scheduler.SELL_CONFIRM_CYCLES
    src = inspect.getsource(scheduler._run_full_auto_scanner)
    assert "if want_long and not bias_up:" in src and "if not want_long and bias_up:" in src
    assert "SELL_STRONG_CONF" not in src  # v10.7.31 — dikembalikan ke asli


def _raw_now():
    return open(scheduler.__file__).read()


def test_v10731_symmetric_btc_regime_and_ema50():
    txt = _raw_now()
    assert 'gate_block_sell = btc_regime["regime"] in (\n        "bullish_reversal", "trending_up", "bear_capitulation")' in txt
    assert 'gate_block_buy = btc_regime["regime"] in (\n        "bearish_reversal", "trending_down", "bear_capitulation")' in txt
    src = inspect.getsource(scheduler._run_full_auto_scanner)
    assert 'if sig["side"] == "SELL" and gate_block_sell:' in src
    assert 'if sig["side"] == "BUY" and gate_block_buy:' in src
    g = {}
    exec(txt[txt.index("def _trend1h_gate"):txt.index("def _btc15m_short_block")], g)
    f = g["_trend1h_gate"]
    assert f("SELL", 101, 100, 100) == "trend_1h_ema50_block_SHORT" and f("BUY", 101, 100, 100) is None
    assert f("BUY", 99, 100, 100) == "trend_1h_ema50_block_LONG" and f("SELL", 99, 100, 100) is None
