"""v10.6.0 — v10.5.1 bypass dibatalkan; Reverse sinyal Full-Auto."""
import inspect
import sys

sys.path.insert(0, "/app/backend")
from asi_bot import scheduler  # noqa: E402
from asi_bot.routes import BotConfigPayload  # noqa: E402


def test_bypass_reverted():
    src = inspect.getsource(scheduler._run_full_auto_scanner)
    assert "_gate_bypass" not in src
    assert 'if sym != "BTC":' in src


def test_reverse_long_to_short_mirrors_levels():
    side, sl, tps = scheduler._reverse_signal("BUY", 100.0, 98.5, [101.0, 102.0])
    assert side == "SELL"
    assert sl == 101.5 and tps == [99.0, 98.0]


def test_reverse_short_to_long():
    side, sl, tps = scheduler._reverse_signal("SELL", 50.0, 51.0, [49.0])
    assert side == "BUY" and sl == 49.0 and tps == [51.0]


def test_reverse_wired_and_default_off():
    src = inspect.getsource(scheduler._run_full_auto_scanner)
    assert 'cfg.get("reverse_signal")' in src
    assert "cred, sym, _x_side," in src
    assert BotConfigPayload(exchange="binance").reverse_signal is False
