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
    assert "btc15_up = await _btc_15m_candle_up()" in src
