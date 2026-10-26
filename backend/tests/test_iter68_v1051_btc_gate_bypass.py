"""v10.5.1 — BTC 15m sideways → gate rezim 1H/4H lama dilewati."""
import inspect
import sys

sys.path.insert(0, "/app/backend")
from asi_bot import scheduler  # noqa: E402


def test_bypass_wired_into_regime_gate():
    src = inspect.getsource(scheduler._run_full_auto_scanner)
    assert '_gate_bypass = (btc15["state"] == "sideways"' in src
    assert 'btc_regime["regime"] != "bear_capitulation"' in src
    assert 'if sym != "BTC" and not _gate_bypass:' in src


def test_15m_filter_still_blocks_before_gate():
    src = inspect.getsource(scheduler._run_full_auto_scanner)
    i15 = src.index('btc15["state"] == "rebound" and sig["side"] == "SELL"')
    igate = src.index('if sym != "BTC" and not _gate_bypass:')
    assert i15 < igate
