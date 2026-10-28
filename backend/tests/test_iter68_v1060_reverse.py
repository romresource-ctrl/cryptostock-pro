"""v10.6.0 — v10.5.1 bypass dibatalkan; Reverse sinyal Full-Auto."""
import inspect
import sys

sys.path.insert(0, "/app/backend")
from asi_bot import scheduler  # noqa: E402
from asi_bot.routes import BotConfigPayload  # noqa: E402


def test_bypass_only_when_reverse_on():
    src = inspect.getsource(scheduler._run_full_auto_scanner)
    assert '_gate_bypass = (_rev_active(cfg, btc15["state"])' in src
    assert 'if sym != "BTC" and not _gate_bypass:' in src
    assert 'if sig["side"] == "SELL" and gate_block_sell:' in src


def test_circuit_breaker_counts_any_loss():
    src = inspect.getsource(scheduler._run_full_auto_scanner)
    assert 'float(t.get("pnl_usdt") or 0) < 0\n' in src


def test_close_all_sweep_exists():
    from asi_bot import routes
    assert inspect.iscoroutinefunction(routes._sweep_binance_positions)


def test_reverse_auto_off_on_btc15_breakout():
    src = inspect.getsource(scheduler._reverse_regime_switch)
    assert '{"reverse_signal": True}' in src and '"reverse_signal": False' in src
    assert '"formula_tag": {"$regex": "REVERSE"}' in src
    assert "_cancel_pending_limit" in src and "close_position" in src
    assert '{"full_enabled": True, "reverse_signal": {"$ne": True}}' in src


def test_rev_active_by_btc15_state():
    assert scheduler._rev_active({"reverse_signal": True}, "rebound") is False
    assert scheduler._rev_active({"reverse_signal": True}, "dump") is False
    assert scheduler._rev_active({"reverse_signal": False}, "sideways") is True
    assert scheduler._rev_active({"reverse_signal": True}, "unknown") is True
    assert scheduler._rev_active({}, "unknown") is False


def test_save_without_toggle_keeps_reverse():
    from asi_bot import routes
    src = inspect.getsource(routes)
    assert 'doc["reverse_signal"] = bool(_prev.get("reverse_signal", False))' in src
    assert BotConfigPayload(exchange="binance").reverse_toggle is False


def test_reverse_long_to_short_mirrors_levels():
    side, sl, tps = scheduler._reverse_signal("BUY", 100.0, 98.5, [101.0, 102.0])
    assert side == "SELL"
    assert sl == 101.5 and tps == [99.0, 98.0]


def test_reverse_short_to_long():
    side, sl, tps = scheduler._reverse_signal("SELL", 50.0, 51.0, [49.0])
    assert side == "BUY" and sl == 49.0 and tps == [51.0]


def test_reverse_wired_and_default_off():
    src = inspect.getsource(scheduler._run_full_auto_scanner)
    assert '_rev_active(cfg, btc15["state"])' in src
    assert "cred, sym, _x_side," in src
    assert BotConfigPayload(exchange="binance").reverse_signal is False


def test_flip_happens_before_filters():
    src = inspect.getsource(scheduler._run_full_auto_scanner)
    i_flip = src.index('"reversed_from": sig["side"]')
    i_btc15 = src.index('if btc15["state"] == "rebound" and sig["side"] == "SELL":')
    i_trend = src.index('trend_filter_4h_blokir_SHORT')
    assert i_flip < i_btc15 < i_trend
    assert "_reverse_signal(sig[\"side\"], _entry" not in src


def test_2027_retries_lower_leverage():
    src = inspect.getsource(scheduler._run_full_auto_scanner)
    assert "for _lv in _lev_try:" in src
    assert '"-2027" not in str(res.get("message") or "")' in src
