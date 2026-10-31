"""v10.7.17 — blokir SHORT baru saat BTC 15m rebound (candle naik +
exhausted_down/rebound). Posisi open tidak disentuh; gate 4H tak berubah."""
import inspect
import sys
sys.path.insert(0, "/app/backend")
from asi_bot import scheduler  # noqa: E402


def test_block_rules():
    f = scheduler._btc15m_short_block
    assert f(True, "sideways", True) is True
    assert f(True, "rebound", False) is True
    assert f(False, "rebound", True) is False      # candle 15m tidak naik
    assert f(True, "sideways", False) is False     # momentum tidak padam
    assert f(True, "dump", False) is False


def test_wired_only_for_new_sell_entries():
    src = inspect.getsource(scheduler._run_full_auto_scanner)
    assert 'btc15m_rebound_candle_up: block SELL' in src
    assert 'sig["side"] == "SELL" and _btc15m_short_block(' in src
    assert "btc15_dir = await _btc_15m_candle_dir()" in src


def test_long_block_rules_symmetric():
    f = scheduler._btc15m_long_block
    assert f(True, "sideways", True) is True
    assert f(True, "dump", False) is True
    assert f(False, "dump", True) is False         # candle 15m tidak turun
    assert f(True, "sideways", False) is False
    assert f(True, "rebound", False) is False
    src = inspect.getsource(scheduler._run_full_auto_scanner)
    assert 'sig["side"] == "BUY" and _btc15m_long_block(' in src
    assert "btc15m_drop_candle_down: block BUY" in src
