"""v10.7.7 — Long the Dip / Short the Top (Full-Auto)."""
import inspect
import sys

sys.path.insert(0, "/app/backend")
from asi_bot import scheduler  # noqa: E402

def _k(o, h, l, c):
    return {"open": o, "high": h, "low": l, "close": c}

# 15m tertutup: turun lalu candle hijau menembus high sebelumnya (wink dip)
WINK_UP = [_k(101, 101.2, 100.2, 100.4), _k(100.4, 100.5, 99.6, 99.8),
           _k(99.8, 99.9, 99.5, 99.6), _k(99.6, 100.3, 99.5, 100.2)]
# cermin: naik lalu candle merah menembus low sebelumnya (wink top)
WINK_DN = [_k(99, 99.8, 98.8, 99.6), _k(99.6, 100.4, 99.5, 100.2),
           _k(100.2, 100.5, 100.1, 100.4), _k(100.4, 100.5, 99.7, 99.8)]

SELL = {"side": "SELL", "entry": 100.0, "stop_loss": 101.5, "take_profits": [99.0], "formula_tag": "KISS"}
BUY = {"side": "BUY", "entry": 100.0, "stop_loss": 98.5, "take_profits": [101.0], "formula_tag": "KISS"}


def test_sell_near_low_oversold_becomes_long():
    r = scheduler._dip_top_flip(SELL, 25, 110.0, 99.5, WINK_UP)
    assert r["side"] == "BUY" and r["stop_loss"] == 98.5 and r["take_profits"] == [101.0]
    assert r["formula_tag"].endswith("LONG THE DIP")


def test_buy_near_high_overbought_becomes_short():
    r = scheduler._dip_top_flip(BUY, 75, 100.5, 90.0, WINK_DN)
    assert r["side"] == "SELL" and r["formula_tag"].endswith("SHORT THE TOP")


def test_no_flip_when_conditions_not_met():
    assert scheduler._dip_top_flip(SELL, 46, 110.0, 99.5) is None    # RSI >= 45
    assert scheduler._dip_top_flip(SELL, 25, 110.0, 97.0) is None    # >1% dari low
    assert scheduler._dip_top_flip(BUY, 54, 100.5, 90.0) is None
    assert scheduler._dip_top_flip(SELL, None, 110.0, 99.5) is None


def test_wired_before_filters():
    src = inspect.getsource(scheduler._run_full_auto_scanner)
    i = src.index("_dip = _dip_top_flip(sig, _rsi1h, _hi24, _lo24, [])")
    assert i < src.index('if btc15["state"] == "rebound" and sig["side"] == "SELL":')


def test_user_cases_icp_gala_dydx_flip():
    # ICP RSI 38 (0.6% dari low), GALA 43 (0.5%), DYDX 38 (0.4%) → LONG
    for e, lo, rsi in ((2.5371, 2.522, 38), (0.001727, 0.001719, 43), (0.10633, 0.1059, 38)):
        s = {"side": "SELL", "entry": e, "stop_loss": e * 1.015, "take_profits": [e * 0.99]}
        w = [_k(e * o, e * h, e * l, e * c) for o, h, l, c in
             ((1.01, 1.012, 1.002, 1.004), (1.004, 1.005, 0.999, 1.0),
              (1.0, 1.001, 0.998, 0.999), (0.999, 1.006, 0.998, 1.005))]
        assert scheduler._dip_top_flip(s, rsi, e * 1.08, lo, w)["side"] == "BUY"


def test_zone_without_wink_waits_not_executes():
    # v10.7.9 — zona dip tapi candle 15m masih merah → tunggu (bukan flip, bukan SELL)
    falling = WINK_UP[:3] + [_k(99.6, 99.7, 99.3, 99.4)]
    assert scheduler._dip_top_flip(SELL, 30, 110.0, 99.5, falling) == {"wait": "LONG THE DIP"}
    assert scheduler._dip_top_flip(BUY, 70, 100.5, 90.0, []) == {"wait": "SHORT THE TOP"}


def test_wink_rejects_chase_after_big_bounce():
    # bounce >1.5% dari low 4 candle → terlambat, jangan kejar
    big = WINK_UP[:3] + [_k(99.6, 101.5, 99.5, 101.4)]
    assert scheduler._wink("BUY", big) is False
    assert scheduler._wink("BUY", WINK_UP) and scheduler._wink("SELL", WINK_DN)


def test_wait_skips_signal_in_scanner():
    src = inspect.getsource(scheduler._run_full_auto_scanner)
    assert '_wait_reversal' in src and '_g15(sym, "15m")' in src
