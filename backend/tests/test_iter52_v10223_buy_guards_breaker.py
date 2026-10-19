"""v10.2.23 — Paket anti-loss sisi BUY + circuit breaker PnL + cooldown simbol.

Konteks (iter52):
  User melaporkan loss beruntun sejak v10.2.20 (profit kecil, loss besar).
  Data riil 18/10: SAND di-LONG 3x beruntun saat dump pasca-pump (SL semua
  -$60/-$42/-$102), TIA LONG di puncak pump +3.67% (floating -43%).
  Akar: (1) anti-chase hanya utk SELL, BUY mengejar puncak/pisau jatuh;
  (2) tidak ada cooldown per-koin setelah loss; (3) circuit breaker lama
  v10.2.5 hanya menghitung close_reason=='SL' sehingga loss beralasan lain
  (position_closed_externally) memutus streak.

  Fix v10.2.23 di `asi_bot.scheduler`:
    1. CIRCUIT BREAKER berbasis PnL: CIRCUIT_BREAKER_LOSSES(3) closed
       terakhir semua pnl < -$1 (alasan APA PUN) & terbaru
       < CIRCUIT_BREAKER_PAUSE_HOURS(2) jam → device di-skip
       'circuit-breaker: ...' (istirahat 2 jam).
    2. COOLDOWN per-simbol: simbol yang baru rugi <
       SYMBOL_LOSS_COOLDOWN_HOURS(4) jam → reject
       'cooldown_loss_<SYM>_<4h'.
    3. ANTI-CHASE BUY: BUY ditolak bila alt naik > BUY_CHASE_PCT(3.0)%
       dalam BUY_CHASE_WINDOW_H(6) jam → 'anti_chase_buy_*'.
    4. DUMP GUARD BUY: BUY ditolak bila alt turun > BUY_DUMP_GUARD_PCT(2.5)%
       dalam BUY_DUMP_GUARD_WINDOW_H(2) jam → 'buy_dump_guard_*'.
    5. buy_gates audit +7 field baru.

Semua backend-only; tidak ada order Binance nyata (execute_trade,
resolve_credential, get_crypto_snapshot, _get_btc_regime di-monkeypatch).
Harness FakeDB diambil dari iter51 (test_iter51_v10222_trend_down_streak).
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asi_bot import scheduler as sched  # noqa: E402
import market_data  # noqa: E402

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL")
            or os.environ.get("EXPO_BACKEND_URL")
            or "https://cryptostock-pro.preview.emergentagent.com").rstrip("/")


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _ago(**kw) -> datetime:
    return datetime.now(timezone.utc) - timedelta(**kw)


# ───────────────────────── fake in-memory Mongo ─────────────────────────
_MISSING = object()


def _match(doc: dict, query: dict) -> bool:
    for key, cond in query.items():
        if key == "$or":
            if not any(_match(doc, sub) for sub in cond):
                return False
            continue
        val = doc.get(key, _MISSING)
        if isinstance(cond, dict):
            for op, operand in cond.items():
                if op == "$exists":
                    if (val is not _MISSING) != bool(operand):
                        return False
                elif op == "$in":
                    if val is _MISSING or val not in operand:
                        return False
                elif op == "$gte":
                    if val is _MISSING or not (val >= operand):
                        return False
                elif op == "$gt":
                    if val is _MISSING or not (val > operand):
                        return False
                elif op == "$ne":
                    if val is not _MISSING and val == cond:
                        return False
                else:
                    raise ValueError(f"unsupported op {op}")
        else:
            if val is _MISSING or val != cond:
                return False
    return True


class _Cursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, key, direction):
        self._docs = sorted(self._docs, key=lambda d: d.get(key) or "",
                            reverse=(direction < 0))
        return self

    def limit(self, n):
        self._docs = self._docs[:n]
        return self

    def __aiter__(self):
        async def _gen():
            for d in self._docs:
                yield d
        return _gen()

    async def to_list(self, n):
        return self._docs[:n]


class _Result:
    def __init__(self, matched=0):
        self.matched_count = matched


class FakeCollection:
    def __init__(self):
        self.docs: dict[str, dict] = {}

    def find(self, query):
        return _Cursor([d for d in self.docs.values() if _match(d, query)])

    async def find_one(self, query):
        for d in self.docs.values():
            if _match(d, query):
                return d
        return None

    async def count_documents(self, query):
        return sum(1 for d in self.docs.values() if _match(d, query))

    async def insert_one(self, doc):
        if doc["_id"] in self.docs:
            raise Exception("DuplicateKeyError")
        self.docs[doc["_id"]] = dict(doc)
        return _Result(1)

    async def update_one(self, filt, update, upsert=False):
        doc = self.docs.get(filt.get("_id"))
        if doc is None:
            for d in self.docs.values():
                if _match(d, filt):
                    doc = d
                    break
        if doc is None:
            if not upsert:
                return _Result(0)
            doc = dict(filt)
            self.docs[doc["_id"]] = doc
        for k, v in (update.get("$set") or {}).items():
            doc[k] = v
        return _Result(1)

    async def update_many(self, filt, update):
        n = 0
        for d in self.docs.values():
            if _match(d, filt):
                for k, v in (update.get("$set") or {}).items():
                    d[k] = v
                n += 1
        return _Result(n)

    async def replace_one(self, filt, doc, upsert=False):
        _id = filt.get("_id", doc.get("_id"))
        if _id not in self.docs and not upsert:
            return _Result(0)
        self.docs[_id] = dict(doc)
        return _Result(1)


class FakeDB:
    def __init__(self):
        self.asi_bot_config = FakeCollection()
        self.asi_scan_status = FakeCollection()
        self.asi_trades = FakeCollection()
        self.asi_buy_confirm = FakeCollection()
        self.asi_scan_claims = FakeCollection()


# ─────────────────────────── scanner harness ────────────────────────────
DEV = f"test-10223-{uuid.uuid4().hex[:8]}"


def _cfg(whitelist=None) -> dict:
    return {
        "_id": DEV, "device_id": DEV, "enabled": True, "full_enabled": True,
        "mode": "full", "exchange": "binance",
        "whitelist": whitelist or ["ETH"],
        "min_confidence": 90, "max_trades_per_day": 5, "risk_pct": 5.0,
        "leverage": 10, "active_testnet": True, "tp_count": 3,
        "trailing_callback_rate": 0.0, "margin_mode": "isolated",
        "entry_mode": "market", "signal_source": "asi_bot",
    }


def _signal(side: str, conf: int) -> dict:
    if side == "SELL":
        return {"side": "SELL", "entry": 100.0, "stop_loss": 105.0,
                "take_profits": [99.0, 98.0, 97.0], "confidence": conf,
                "profile": "longterm", "formula_tag": "TESTFORM"}
    return {"side": "BUY", "entry": 100.0, "stop_loss": 95.0,
            "take_profits": [101.0, 102.0, 103.0], "confidence": conf,
            "profile": "longterm", "formula_tag": "TESTFORM"}


def _closed_trade(symbol: str, pnl: float, closed_at: datetime,
                  reason: str = "SL") -> dict:
    return {
        "_id": f"{DEV}:{symbol}:{closed_at.timestamp()}",
        "device_id": DEV, "symbol": symbol, "status": "closed",
        "pnl_usdt": pnl, "close_reason": reason,
        "closed_at": _iso(closed_at), "updated_at": _iso(closed_at),
        "created_at": _iso(closed_at - timedelta(minutes=30)),
        "testnet": True,
    }


class ExecStub:
    def __init__(self):
        self.calls: list[dict] = []

    async def __call__(self, cred, symbol, side, entry, sl, tps, risk, lev,
                       **kw):
        self.calls.append({"symbol": symbol, "side": side, "entry": entry,
                           "sl": sl, "tps": list(tps), **kw})
        return {
            "ok": True, "symbol": symbol, "side": side,
            "entry_price": float(entry), "qty": 1.0, "leverage": lev,
            "entry_order_id": f"TESTORD-{len(self.calls)}",
            "status": "open",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }


def _regime_stub(regime: str, base: str, streak: int, streak_dn: int = 0):
    async def _fake(db):
        return {"regime": regime, "ok": True, "detail": "test-stub",
                "base_regime": base, "trend_up_streak": streak,
                "trend_down_streak": streak_dn,
                "rsi": 50.0, "chg_last": 0.0, "chg_prev": 0.0,
                "slope_up": False, "slope_dn": False}
    return _fake


# 4H close series (diverifikasi numerik vs indicators._ema, periode 50):
def closes_uptrend() -> list[float]:
    """price > EMA50, slope naik."""
    return [100.0 + i * 0.5 for i in range(60)]


def closes_downtrend() -> list[float]:
    """price < EMA50, slope turun."""
    return [130.0 - i * 0.5 for i in range(60)]


# 1H close series (<16 candle → RSI1h gate fail-open, momentum guard aktif):
def closes_1h_flat() -> list[float]:
    return [100.0] * 8


def closes_1h_pump() -> list[float]:
    """+4.6% dalam 6 jam (kasus TIA: long di puncak)."""
    return [100.0] * 6 + [104.6]


def closes_1h_dump() -> list[float]:
    """-4.9% dalam 2 jam terakhir, 6 jam -4.9% (kasus SAND: pisau jatuh)."""
    return [100.0] * 6 + [97.5, 95.1]


def closes_1h_dump5() -> list[float]:
    """-5.0% dalam 6 jam (regresi anti-chase SELL, kasus BCH 16/10)."""
    return [100.0] * 6 + [95.0]


def _snapshot_stub(closes_4h: list[float], closes_1h: list[float]):
    async def _fake(symbol, tf):
        if tf == "1h":
            return {"candles": [{"close": c, "high": c, "low": c}
                                for c in closes_1h]}
        return {"candles": [{"close": c, "high": c, "low": c}
                            for c in closes_4h]}
    return _fake


def make_harness(monkeypatch, *, side: str = "BUY", conf: int = 95,
                 regime: str = "neutral", base: str = "BULL", streak: int = 0,
                 streak_dn: int = 0, whitelist=None,
                 closes_4h: list[float] | None = None,
                 closes_1h: list[float] | None = None,
                 trades: list[dict] | None = None):
    db = FakeDB()
    db.asi_bot_config.docs[DEV] = _cfg(whitelist)
    for t in (trades or []):
        db.asi_trades.docs[t["_id"]] = t
    exec_stub = ExecStub()

    async def _fetcher(market, symbol, profile):
        return _signal(side, conf)

    async def _cred(db_, device_id, exchange, testnet):
        return {"_id": f"cred-{device_id}", "testnet": True}

    monkeypatch.setattr(sched, "_get_btc_regime",
                        _regime_stub(regime, base, streak, streak_dn))
    monkeypatch.setattr(sched, "resolve_credential", _cred)
    monkeypatch.setattr(sched, "execute_trade", exec_stub)
    if closes_4h is None:
        closes_4h = closes_uptrend() if side == "BUY" else closes_downtrend()
    if closes_1h is None:
        closes_1h = closes_1h_flat()
    monkeypatch.setattr(market_data, "get_crypto_snapshot",
                        _snapshot_stub(closes_4h, closes_1h))
    return db, exec_stub, _fetcher


def run_scan(db, fetcher):
    asyncio.run(sched._run_full_auto_scanner(db, fetcher))


def scanner_doc(db) -> dict:
    return db.asi_scan_status.docs.get("scanner") or {}


def device_report(db) -> dict:
    return (scanner_doc(db).get("devices") or {}).get(DEV) or {}


def rejects_of(db) -> dict:
    return device_report(db).get("rejects") or {}


# ════════════════════════════════════════════════════════════════════════
# UNIT: konstanta v10.2.23
# ════════════════════════════════════════════════════════════════════════
class TestConstants:
    def test_v10223_constants(self):
        assert sched.CIRCUIT_BREAKER_LOSSES == 3
        assert sched.CIRCUIT_BREAKER_PAUSE_HOURS == 2
        assert sched.SYMBOL_LOSS_COOLDOWN_HOURS == 4
        assert sched.BUY_CHASE_PCT == 3.0
        assert sched.BUY_CHASE_WINDOW_H == 6
        assert sched.BUY_DUMP_GUARD_PCT == 2.5
        assert sched.BUY_DUMP_GUARD_WINDOW_H == 2


# ════════════════════════════════════════════════════════════════════════
# CIRCUIT BREAKER berbasis PnL (menggantikan breaker v10.2.5 berbasis
# close_reason=='SL')
# ════════════════════════════════════════════════════════════════════════
class TestCircuitBreakerPnL:
    def test_breaker_trips_on_3_losses_mixed_close_reasons(self, monkeypatch):
        """3 closed terakhir pnl<-1 dgn alasan CAMPUR (SL,
        position_closed_externally, SL) & terbaru <2 jam → device SKIP
        'circuit-breaker'. Ini kasus persis bug lama: breaker v10.2.5
        memutus streak pada reason non-SL."""
        trades = [
            _closed_trade("SAND", -60.0, _ago(minutes=30),
                          reason="position_closed_externally"),
            _closed_trade("SAND", -42.0, _ago(hours=1), reason="SL"),
            _closed_trade("SAND", -102.0, _ago(minutes=90), reason="SL"),
        ]
        db, exec_stub, fetcher = make_harness(monkeypatch, trades=trades)
        run_scan(db, fetcher)
        rep = device_report(db)
        assert rep.get("scanned") is False, rep
        assert "circuit-breaker" in (rep.get("skip_reason") or ""), rep
        assert len(exec_stub.calls) == 0

    def test_no_breaker_when_one_of_3_pnl_positive(self, monkeypatch):
        """Salah satu dari 3 closed terakhir pnl>0 → breaker TIDAK aktif,
        device tetap discan."""
        trades = [
            _closed_trade("SAND", -60.0, _ago(minutes=30)),
            _closed_trade("ETH", +5.0, _ago(hours=1)),
            _closed_trade("SAND", -102.0, _ago(minutes=90)),
        ]
        db, exec_stub, fetcher = make_harness(monkeypatch, trades=trades)
        run_scan(db, fetcher)
        rep = device_report(db)
        assert "circuit-breaker" not in (rep.get("skip_reason") or ""), rep
        assert rep.get("scanned") is True, rep

    def test_no_breaker_when_newest_loss_older_than_2h(self, monkeypatch):
        """3 loss beruntun tapi yang terbaru >2 jam lalu → masa istirahat
        sudah lewat → TIDAK skip."""
        trades = [
            _closed_trade("SAND", -60.0, _ago(hours=3)),
            _closed_trade("SAND", -42.0, _ago(hours=4)),
            _closed_trade("SAND", -102.0, _ago(hours=5)),
        ]
        db, exec_stub, fetcher = make_harness(monkeypatch, trades=trades)
        run_scan(db, fetcher)
        rep = device_report(db)
        assert "circuit-breaker" not in (rep.get("skip_reason") or ""), rep
        assert rep.get("scanned") is True, rep

    def test_no_breaker_when_middle_pnl_breakeven(self, monkeypatch):
        """pnl 0.03 (break-even) di tengah streak → bukan 'rugi' →
        breaker TIDAK aktif."""
        trades = [
            _closed_trade("SAND", -50.0, _ago(minutes=30)),
            _closed_trade("COMP", 0.03, _ago(hours=1),
                          reason="position_closed_externally"),
            _closed_trade("SAND", -40.0, _ago(minutes=90)),
        ]
        db, exec_stub, fetcher = make_harness(monkeypatch, trades=trades)
        run_scan(db, fetcher)
        rep = device_report(db)
        assert "circuit-breaker" not in (rep.get("skip_reason") or ""), rep
        assert rep.get("scanned") is True, rep

    def test_no_breaker_when_only_2_recent_losses(self, monkeypatch):
        """Hanya 2 closed loss (< CIRCUIT_BREAKER_LOSSES) → TIDAK skip."""
        trades = [
            _closed_trade("SAND", -60.0, _ago(minutes=30)),
            _closed_trade("CRV", -42.0, _ago(hours=1)),
        ]
        db, exec_stub, fetcher = make_harness(monkeypatch, trades=trades)
        run_scan(db, fetcher)
        rep = device_report(db)
        assert "circuit-breaker" not in (rep.get("skip_reason") or ""), rep
        assert rep.get("scanned") is True, rep

    def test_breaker_loss_threshold_boundary(self, monkeypatch):
        """pnl tepat -1.00 TIDAK dihitung rugi (aturan pnl < -$1) →
        breaker TIDAK aktif."""
        trades = [
            _closed_trade("SAND", -60.0, _ago(minutes=30)),
            _closed_trade("SAND", -1.0, _ago(hours=1)),
            _closed_trade("SAND", -42.0, _ago(minutes=90)),
        ]
        db, exec_stub, fetcher = make_harness(monkeypatch, trades=trades)
        run_scan(db, fetcher)
        rep = device_report(db)
        assert "circuit-breaker" not in (rep.get("skip_reason") or ""), rep


# ════════════════════════════════════════════════════════════════════════
# COOLDOWN per-simbol setelah loss (<4 jam)
# ════════════════════════════════════════════════════════════════════════
class TestSymbolLossCooldown:
    def test_sand_loss_1h_ago_rejected_other_symbol_passes(self, monkeypatch):
        """SAND closed loss 1 jam lalu → sinyal SAND reject
        'cooldown_loss_SAND_<4h'; simbol lain (ETH) tetap lolos ke
        konfirmasi 2 siklus."""
        trades = [_closed_trade("SAND", -60.0, _ago(hours=1))]
        db, exec_stub, fetcher = make_harness(
            monkeypatch, whitelist=["SAND", "ETH"], trades=trades)
        run_scan(db, fetcher)
        rej = rejects_of(db)
        assert "cooldown_loss_SAND_<4h" in rej, rej
        assert "buy_menunggu_konfirmasi_siklus_2" in rej, rej  # ETH lolos
        assert len(exec_stub.calls) == 0

    def test_symbol_profit_within_4h_passes(self, monkeypatch):
        """Simbol yang closed PROFIT <4 jam lalu → TIDAK kena cooldown."""
        trades = [_closed_trade("SAND", +20.0, _ago(hours=1),
                                reason="TP")]
        db, exec_stub, fetcher = make_harness(
            monkeypatch, whitelist=["SAND"], trades=trades)
        run_scan(db, fetcher)
        rej = rejects_of(db)
        assert not any(r.startswith("cooldown_loss_") for r in rej), rej
        assert "buy_menunggu_konfirmasi_siklus_2" in rej, rej

    def test_symbol_loss_older_than_4h_passes(self, monkeypatch):
        """Simbol yang loss >4 jam lalu → cooldown sudah lewat → lolos."""
        trades = [_closed_trade("SAND", -60.0, _ago(hours=5))]
        db, exec_stub, fetcher = make_harness(
            monkeypatch, whitelist=["SAND"], trades=trades)
        run_scan(db, fetcher)
        rej = rejects_of(db)
        assert not any(r.startswith("cooldown_loss_") for r in rej), rej
        assert "buy_menunggu_konfirmasi_siklus_2" in rej, rej

    def test_small_loss_within_threshold_no_cooldown(self, monkeypatch):
        """Loss kecil (-0.50, di dalam ambang -$1) TIDAK memicu cooldown."""
        trades = [_closed_trade("SAND", -0.50, _ago(hours=1))]
        db, exec_stub, fetcher = make_harness(
            monkeypatch, whitelist=["SAND"], trades=trades)
        run_scan(db, fetcher)
        rej = rejects_of(db)
        assert not any(r.startswith("cooldown_loss_") for r in rej), rej
        assert "buy_menunggu_konfirmasi_siklus_2" in rej, rej


# ════════════════════════════════════════════════════════════════════════
# ANTI-CHASE BUY (cermin anti-chase SELL v10.2.21)
# ════════════════════════════════════════════════════════════════════════
class TestAntiChaseBuy:
    def test_buy_rejected_when_pumped_4_6pct_6h(self, monkeypatch):
        """closes 1h +4.6%/6 jam → BUY reject 'anti_chase_buy_*'
        (kasus TIA 18/10: LONG di puncak pump +3,67%)."""
        db, exec_stub, fetcher = make_harness(
            monkeypatch, side="BUY", closes_1h=closes_1h_pump())
        run_scan(db, fetcher)
        rej = rejects_of(db)
        assert any(r.startswith("anti_chase_buy_") for r in rej), rej
        assert len(exec_stub.calls) == 0

    def test_buy_passes_when_flat(self, monkeypatch):
        """closes 1h flat → anti-chase BUY tidak aktif → lolos ke
        konfirmasi 2 siklus."""
        db, exec_stub, fetcher = make_harness(
            monkeypatch, side="BUY", closes_1h=closes_1h_flat())
        run_scan(db, fetcher)
        rej = rejects_of(db)
        assert not any(r.startswith("anti_chase_buy_") for r in rej), rej
        assert "buy_menunggu_konfirmasi_siklus_2" in rej, rej

    def test_btc_not_subject_to_buy_guards(self, monkeypatch):
        """BTC dikecualikan dari momentum guards (referensi regime): BUY
        BTC saat +4.6%/6 jam TIDAK kena anti_chase_buy."""
        db, exec_stub, fetcher = make_harness(
            monkeypatch, side="BUY", whitelist=["BTC"],
            closes_1h=closes_1h_pump())
        run_scan(db, fetcher)
        rej = rejects_of(db)
        assert not any(r.startswith("anti_chase_buy_") for r in rej), rej
        assert not any(r.startswith("buy_dump_guard_") for r in rej), rej
        assert "buy_menunggu_konfirmasi_siklus_2" in rej, rej


# ════════════════════════════════════════════════════════════════════════
# DUMP GUARD BUY (pisau jatuh — kasus SAND -3,4%/2 jam saat entry)
# ════════════════════════════════════════════════════════════════════════
class TestBuyDumpGuard:
    def test_buy_rejected_when_dumped_4_9pct_2h(self, monkeypatch):
        """closes 1h -4.9%/2 jam terakhir → BUY reject 'buy_dump_guard_*'."""
        db, exec_stub, fetcher = make_harness(
            monkeypatch, side="BUY", closes_1h=closes_1h_dump())
        run_scan(db, fetcher)
        rej = rejects_of(db)
        assert any(r.startswith("buy_dump_guard_") for r in rej), rej
        assert not any(r.startswith("anti_chase_buy_") for r in rej), rej
        assert len(exec_stub.calls) == 0


# ══════════════════════════════════════════════════════════════════════
# REGRESI: ANTI-CHASE SELL (v10.2.21) tetap aktif
# ════════════════════════════════════════════════════════════════════════
class TestAntiChaseSellRegression:
    def test_sell_rejected_when_dumped_5pct_6h(self, monkeypatch):
        """closes 1h -5%/6 jam → SELL reject 'anti_chase_sell_*'
        (regresi v10.2.21, kasus BCH 16/10)."""
        db, exec_stub, fetcher = make_harness(
            monkeypatch, side="SELL", base="BEAR",
            closes_1h=closes_1h_dump5())
        run_scan(db, fetcher)
        rej = rejects_of(db)
        assert any(r.startswith("anti_chase_sell_") for r in rej), rej
        assert len(exec_stub.calls) == 0


# ════════════════════════════════════════════════════════════════════════
# INTEGRASI SCANNER 1 SIKLUS PENUH: reject tercatat + sinyal lolos tetap
# melewati konfirmasi 2 siklus → eksekusi
# ════════════════════════════════════════════════════════════════════════
class TestScannerIntegration:
    def test_reject_recorded_and_passing_signal_executes_cycle2(
            self, monkeypatch):
        """SAND loss 1 jam lalu + sinyal BUY SAND & ETH:
        siklus 1 → SAND reject cooldown tercatat di report device, ETH
        menunggu konfirmasi; siklus 2 → ETH TEREKSEKUSI (konfirmasi 2
        siklus tetap berlaku untuk sinyal yang lolos)."""
        trades = [_closed_trade("SAND", -60.0, _ago(hours=1))]
        db, exec_stub, fetcher = make_harness(
            monkeypatch, side="BUY", whitelist=["SAND", "ETH"],
            trades=trades)
        run_scan(db, fetcher)
        rej1 = rejects_of(db)
        assert "cooldown_loss_SAND_<4h" in rej1, rej1
        assert rej1.get("buy_menunggu_konfirmasi_siklus_2") == 1, rej1
        assert len(exec_stub.calls) == 0
        run_scan(db, fetcher)
        assert len(exec_stub.calls) == 1
        assert exec_stub.calls[0]["symbol"] == "ETH"
        assert exec_stub.calls[0]["side"] == "BUY"
        # trade tercatat di DB
        saved = [t for t in db.asi_trades.docs.values()
                 if t.get("status") == "open"]
        assert len(saved) == 1 and saved[0]["symbol"] == "ETH"

    def test_scanner_doc_buy_gates_has_7_new_fields(self, monkeypatch):
        """buy_gates audit di doc scanner memuat 7 field v10.2.23."""
        db, _, fetcher = make_harness(monkeypatch, side="BUY")
        run_scan(db, fetcher)
        gates = scanner_doc(db).get("buy_gates") or {}
        assert gates.get("buy_chase_pct") == 3.0, gates
        assert gates.get("buy_chase_window_h") == 6, gates
        assert gates.get("buy_dump_guard_pct") == 2.5, gates
        assert gates.get("buy_dump_guard_window_h") == 2, gates
        assert gates.get("circuit_breaker_losses") == 3, gates
        assert gates.get("circuit_breaker_pause_hours") == 2, gates
        assert gates.get("symbol_loss_cooldown_hours") == 4, gates


# ════════════════════════════════════════════════════════════════════════
# REGRESI gates v10.2.17 / v10.2.21 / v10.2.22 tetap hijau
# ════════════════════════════════════════════════════════════════════════
class TestGateRegressions:
    def test_buy_anti_flap_streak_below_3(self, monkeypatch):
        """v10.2.29: anti-flap dicabut — trending_up 1 siklus → BUY lanjut
        ke konfirmasi 2 siklus."""
        db, exec_stub, fetcher = make_harness(
            monkeypatch, side="BUY", regime="trending_up", streak=1)
        run_scan(db, fetcher)
        assert len(exec_stub.calls) == 0
        rej = rejects_of(db)
        assert not any(r.startswith("anti-flap") for r in rej), rej
        assert "buy_menunggu_konfirmasi_siklus_2" in rej, rej

    def test_buy_bear4h_conf_bonus(self, monkeypatch):
        """v10.2.17: base4H BEAR → min conf +5 (92 < 95 → reject)."""
        db, exec_stub, fetcher = make_harness(
            monkeypatch, side="BUY", conf=92, base="BEAR")
        run_scan(db, fetcher)
        assert len(exec_stub.calls) == 0
        assert "conf<95_bear4h" in rejects_of(db)

    def test_buy_two_cycle_confirmation(self, monkeypatch):
        """v10.2.17/21: konfirmasi 2 siklus BUY tetap berlaku."""
        db, exec_stub, fetcher = make_harness(monkeypatch, side="BUY")
        run_scan(db, fetcher)
        assert len(exec_stub.calls) == 0
        assert "buy_menunggu_konfirmasi_siklus_2" in rejects_of(db)
        run_scan(db, fetcher)
        assert len(exec_stub.calls) == 1

    def test_sell_two_cycle_confirmation(self, monkeypatch):
        """v10.2.21: konfirmasi 2 siklus SELL tetap berlaku."""
        db, exec_stub, fetcher = make_harness(
            monkeypatch, side="SELL", base="BEAR")
        run_scan(db, fetcher)
        assert len(exec_stub.calls) == 0
        assert "sell_menunggu_konfirmasi_siklus_2" in rejects_of(db)
        run_scan(db, fetcher)
        assert len(exec_stub.calls) == 1

    def test_trend4h_slope_relax_long(self, monkeypatch):
        """v10.2.22: LONG harga>EMA50 slope turun lolos saat BTC
        trending_up streak>=3."""
        def closes_long_relax():
            return [102.0 - i * (2.0 / 58) for i in range(59)] + [101.2]
        db, exec_stub, fetcher = make_harness(
            monkeypatch, side="BUY", regime="trending_up", streak=3,
            closes_4h=closes_long_relax())
        run_scan(db, fetcher)
        rej = rejects_of(db)
        assert "trend_filter_4h_blokir_LONG" not in rej, rej
        assert "buy_menunggu_konfirmasi_siklus_2" in rej, rej
        run_scan(db, fetcher)
        assert len(exec_stub.calls) == 1


# ════════════════════════════════════════════════════════════════════════
# HTTP: scan-debug endpoint (live, read-only) — 7 field buy_gates baru
# ════════════════════════════════════════════════════════════════════════
class TestScanDebugHTTP:
    def test_scan_debug_exposes_7_new_buy_gates_fields(self):
        r = requests.get(f"{BASE_URL}/api/asi/scan-debug",
                         params={"device_id": "hc"}, timeout=20)
        assert r.status_code == 200, r.text
        gates = r.json().get("buy_gates") or {}
        expected = {
            "buy_chase_pct": 3.0,
            "buy_chase_window_h": 6,
            "buy_dump_guard_pct": 2.5,
            "buy_dump_guard_window_h": 2,
            "circuit_breaker_losses": 3,
            "circuit_breaker_pause_hours": 2,
            "symbol_loss_cooldown_hours": 4,
        }
        for k, v in expected.items():
            assert gates.get(k) == v, f"{k}: {gates.get(k)} != {v}"

    def test_scanner_doc_fresh(self):
        body = requests.get(f"{BASE_URL}/api/asi/scan-debug",
                            params={"device_id": "hc"}, timeout=20).json()
        last = datetime.fromisoformat(
            str(body["last_scan_at"]).replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - last).total_seconds()
        assert age < 300, f"scanner doc stale: {age:.0f}s"
