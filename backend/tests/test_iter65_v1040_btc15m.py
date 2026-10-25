"""v10.4.0 — BTC 15m direction filter (pure)."""
import sys

sys.path.insert(0, "/app/backend")
from asi_bot.scheduler import _btc_15m_direction  # noqa: E402


def _c(prices):
    return [{"close": p, "high": p, "low": p} for p in prices]


def test_rebound_blocks_short():
    assert _btc_15m_direction(_c([100, 99, 98, 98.5, 99, 99.5]))["state"] == "rebound"  # +1.53%


def test_dump_blocks_long():
    assert _btc_15m_direction(_c([100, 101, 101.5, 100.8, 100.2, 100.3]))["state"] == "dump"  # -1.18%


def test_sideways():
    assert _btc_15m_direction(_c([100, 100.4, 99.8, 100.2, 100.5, 100.1]))["state"] == "sideways"


def test_both_latest_extreme_wins():
    # turun dari 102 ke 99 lalu naik ke 100.5 → low terbaru → rebound
    assert _btc_15m_direction(_c([102, 101, 100, 99, 99.8, 100.5]))["state"] == "rebound"
    # naik dari 99 ke 102 lalu turun ke 100.5 → high terbaru → dump
    assert _btc_15m_direction(_c([99, 100, 101, 102, 101.2, 100.5]))["state"] == "dump"


def test_insufficient_data():
    assert _btc_15m_direction([])["state"] == "unknown"


def test_only_last_15_candles():
    old_low = [90] + [100] * 20  # low 90 lebih dari 15 candle lalu → abaikan
    assert _btc_15m_direction(_c(old_low))["state"] == "sideways"
