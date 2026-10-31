"""v10.7.20 — konfirmasi 2 candle 5m tertutup searah sinyal."""
import inspect
import sys
sys.path.insert(0, "/app/backend")
from asi_bot import scheduler  # noqa: E402


def k(o, c):
    return {"open": o, "close": c, "high": max(o, c), "low": min(o, c)}


def test_two_red_for_short_two_green_for_long():
    f = scheduler._two_closed_5m_confirm
    assert f("SELL", [k(10, 11), k(11, 10.8), k(10.8, 10.5)]) is True
    assert f("SELL", [k(11, 10.8), k(10.8, 10.9)]) is False
    assert f("BUY", [k(10, 10.2), k(10.2, 10.4)]) is True
    assert f("BUY", [k(10, 10.2), k(10.2, 10.1)]) is False
    assert f("BUY", [k(10, 10.2)]) is False
    assert f("BUY", [k(10, 10.2), k(10.2, 10.2)]) is False  # doji ≠ hijau


def test_wired_before_claim_and_drops_running_candle():
    src = inspect.getsource(scheduler._run_full_auto_scanner)
    i = src.index("await _c5_check(device_id, sym, sig[\"side\"])")
    assert i < src.index('slot_id = f"{device_id}:{sym}"')
    txt = open(scheduler.__file__).read()
    body = txt[txt.index("async def _c5_check"):txt.index("def _btc15m_short_block")]
    assert "(c or [])[:-1]" in body


def kt(t, o, c):
    return {"t": t, "open": o, "close": c}


def test_gate_cancel_on_against_candle_and_needs_new_signal():
    scheduler._C5_SIG.clear()
    T = 1_800_000_000  # detik
    t0 = T * 1000
    # sinyal SHORT terbentuk di T; candle tutup SETELAH T hijau → batal
    closed = [kt(t0 - 600_000, 10, 9.9), kt(t0 - 120_000, 9.9, 10.1)]
    assert scheduler._c5_gate("d:ETH:SELL", "SELL", closed, T) == "cancel"
    # meski kemudian 2 merah, tetap batal selama sinyal sama masih ada
    red2 = [kt(t0 + 300_000, 10.1, 10.0), kt(t0 + 600_000, 10.0, 9.9)]
    assert scheduler._c5_gate("d:ETH:SELL", "SELL", red2, T + 90) == "cancel"
    assert scheduler._c5_gate("d:ETH:SELL", "SELL", red2, T + 180) == "cancel"
    # sinyal hilang > gap lalu muncul lagi → sinyal baru, 2 merah → ok
    later = T + 180 + scheduler.C5_SIG_GAP_S + 1
    assert scheduler._c5_gate("d:ETH:SELL", "SELL", red2, later) == "ok"


def test_gate_wait_then_ok_for_long():
    scheduler._C5_SIG.clear()
    T = 1_800_000_000
    t0 = T * 1000
    pre = [kt(t0 - 900_000, 10, 9.8), kt(t0 - 600_000, 9.8, 9.7)]  # sebelum sinyal
    assert scheduler._c5_gate("d:SOL:BUY", "BUY", pre, T) == "wait"
    g1 = pre + [kt(t0 - 120_000, 9.7, 9.8)]   # tutup setelah sinyal, hijau
    assert scheduler._c5_gate("d:SOL:BUY", "BUY", g1, T + 200) == "wait"
    g2 = g1 + [kt(t0 + 180_000, 9.8, 9.9)]
    assert scheduler._c5_gate("d:SOL:BUY", "BUY", g2, T + 500) == "ok"
