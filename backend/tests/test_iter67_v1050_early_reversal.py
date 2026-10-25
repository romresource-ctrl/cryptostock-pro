"""v10.5.0 — Early reversal detection (pure)."""
import sys

sys.path.insert(0, "/app/backend")
from indicators import _early_reversal_signal, _macd_hist_recent, _rsi  # noqa: E402


def _mk(closes, last_open, last_low, last_high):
    cs = []
    for i, c in enumerate(closes[:-1]):
        p = closes[i - 1] if i else c
        cs.append({"open": p, "close": c, "high": max(p, c) * 1.001, "low": min(p, c) * 0.999})
    cs.append({"open": last_open, "close": closes[-1], "high": last_high, "low": last_low})
    return cs


def _find_long():
    # downtrend panjang lalu candle bullish lower-low besar → hist flip
    for jump in [x / 10 for x in range(5, 80)]:
        base = [100 - i * 0.6 for i in range(60)]
        last = base[-1] + jump
        c = _mk(base + [last], base[-1] * 0.995, base[-1] * 0.985, last * 1.001)
        h = _macd_hist_recent([x["close"] for x in c], 2)
        r0, r1 = _rsi([x["close"] for x in c][:-1], 14), _rsi([x["close"] for x in c], 14)
        if h[0] < 0 < h[1] and r0 < 35 and r1 > r0:
            return c
    return None


def test_long_detected_when_all_three():
    c = _find_long()
    assert c is not None
    s = _early_reversal_signal(c)
    assert s and s["action"] == "BUY" and s["early_reversal"]
    assert s["stop_loss"] < c[-1]["low"] < s["entry"] < s["take_profit"]


def test_short_symmetric():
    c = _find_long()
    inv = [{"open": 200 - x["open"], "close": 200 - x["close"],
            "high": 200 - x["low"], "low": 200 - x["high"]} for x in c]
    s = _early_reversal_signal(inv)
    assert s and s["action"] == "SELL" and s["stop_loss"] > inv[-1]["high"]


def test_no_signal_without_reversal_candle():
    c = _find_long()
    c[-1]["low"] = c[-2]["low"] * 1.01  # bukan lower-low
    assert _early_reversal_signal(c) is None


def test_no_signal_on_plain_downtrend():
    base = [100 - i * 0.6 for i in range(61)]
    assert _early_reversal_signal(_mk(base, base[-2], base[-1] * 0.999, base[-2] * 1.001)) is None
