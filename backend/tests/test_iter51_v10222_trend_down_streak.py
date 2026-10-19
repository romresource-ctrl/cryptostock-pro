"""v10.2.22 — Symmetric 4H trend-filter slope relaxation (_trend_down_streak).

Context (iter51):
  Bug: selama 3 hari ASI-Bot hanya eksekusi SHORT (0 LONG) walau BTC
  V-reversal, karena slope EMA50 4H (memori ~200 jam) tetap turun 1-2 hari
  pasca dump sehingga trend-filter menolak SEMUA LONG.

  Fix v10.2.22 di `asi_bot.scheduler`:
    * Fungsi baru `_trend_down_streak` (cermin `_trend_up_streak`).
    * `_get_btc_regime` menyimpan `trend_down_streak` di doc
      asi_scan_status.btc_regime dan meneruskannya (juga jalur latch).
    * Trend-filter 4H di `_run_full_auto_scanner`:
        LONG  ditolak bila (not bias_up) or (slope_dn and up_streak<3)
        SHORT ditolak bila (bias_up)     or (slope_up and dn_streak<3)
      → slope dibebaskan saat rezim BTC terkonfirmasi >=3 siklus;
        BIAS (harga vs EMA50) TIDAK pernah dibebaskan.
    * scan-debug expose `btc_trend_down_streak` +
      `buy_gates.trend4h_slope_relax_on_confirmed_btc = True`.

Semua backend-only; tidak ada order Binance nyata (br.*, execute_trade,
resolve_credential, get_crypto_snapshot di-monkeypatch).
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

BASE_URL = (os.environ.get("EXPO_BACKEND_URL")
            or "https://cryptostock-pro.preview.emergentagent.com").rstrip("/")

NOW = datetime(2026, 10, 18, 12, 0, 0, tzinfo=timezone.utc)


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
DEV = f"test-10222-{uuid.uuid4().hex[:8]}"


def _cfg() -> dict:
    return {
        "_id": DEV, "device_id": DEV, "enabled": True, "full_enabled": True,
        "mode": "full", "exchange": "binance", "whitelist": ["ETH"],
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
def closes_long_relax() -> list[float]:
    """price > EMA50 tapi slope EMA50 TURUN (V-reversal dangkal)."""
    return [102.0 - i * (2.0 / 58) for i in range(59)] + [101.2]


def closes_short_relax() -> list[float]:
    """price < EMA50 tapi slope EMA50 NAIK (inverse-V dangkal)."""
    return [100.0 + i * (2.0 / 58) for i in range(59)] + [100.9]


def closes_downtrend() -> list[float]:
    """price < EMA50, slope turun."""
    return [130.0 - i * 0.5 for i in range(60)]


def closes_uptrend() -> list[float]:
    """price > EMA50, slope naik."""
    return [100.0 + i * 0.5 for i in range(60)]


def _snapshot_stub(closes_4h: list[float]):
    """4h memakai closes_4h custom; 1h kosong (fail-open untuk RSI1h &
    anti-chase SELL)."""
    async def _fake(symbol, tf):
        if tf == "1h":
            return {"candles": []}
        return {"candles": [{"close": c, "high": c, "low": c}
                            for c in closes_4h]}
    return _fake


def make_harness(monkeypatch, *, side: str, conf: int, regime: str,
                 base: str, streak: int, streak_dn: int = 0,
                 closes_4h: list[float] | None = None):
    db = FakeDB()
    db.asi_bot_config.docs[DEV] = _cfg()
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
    monkeypatch.setattr(market_data, "get_crypto_snapshot",
                        _snapshot_stub(closes_4h))
    return db, exec_stub, _fetcher


def run_scan(db, fetcher):
    asyncio.run(sched._run_full_auto_scanner(db, fetcher))


def scanner_doc(db) -> dict:
    return db.asi_scan_status.docs.get("scanner") or {}


def rejects_of(db) -> dict:
    return ((scanner_doc(db).get("devices") or {}).get(DEV) or {}).get(
        "rejects") or {}


# ════════════════════════════════════════════════════════════════════════
# UNIT: _trend_down_streak (baru) + _trend_up_streak (regresi v10.2.17)
# ════════════════════════════════════════════════════════════════════════
class TestTrendDownStreakUnit:
    def test_rises_1_2_3_on_consecutive_trending_down(self):
        s = sched._trend_down_streak(None, 0, "trending_down")
        assert s == 1
        s = sched._trend_down_streak("trending_down", s, "trending_down")
        assert s == 2
        s = sched._trend_down_streak("trending_down", s, "trending_down")
        assert s == 3

    def test_reset_to_zero_on_other_regime(self):
        assert sched._trend_down_streak("trending_down", 5, "neutral") == 0
        assert sched._trend_down_streak("trending_down", 5, "trending_up") == 0
        assert sched._trend_down_streak(
            "trending_down", 5, "bearish_reversal") == 0

    def test_first_trending_down_after_other_regime_is_1(self):
        assert sched._trend_down_streak("neutral", 7, "trending_down") == 1

    def test_capped_at_99(self):
        assert sched._trend_down_streak(
            "trending_down", 99, "trending_down") == 99


class TestTrendUpStreakRegression:
    """_trend_up_streak harus tetap berperilaku seperti v10.2.17."""
    def test_rises_1_2_3_on_consecutive_trending_up(self):
        s = sched._trend_up_streak(None, 0, "trending_up")
        assert s == 1
        s = sched._trend_up_streak("trending_up", s, "trending_up")
        assert s == 2
        s = sched._trend_up_streak("trending_up", s, "trending_up")
        assert s == 3

    def test_reset_to_zero_on_other_regime(self):
        assert sched._trend_up_streak("trending_up", 5, "neutral") == 0
        assert sched._trend_up_streak("trending_up", 5, "trending_down") == 0

    def test_first_trending_up_after_other_regime_is_1(self):
        assert sched._trend_up_streak("neutral", 7, "trending_up") == 1

    def test_trend_up_min_cycles_const(self):
        assert sched.TREND_UP_MIN_CYCLES == 3


# ════════════════════════════════════════════════════════════════════════
# UNIT+DB: _get_btc_regime menyimpan & meneruskan trend_down_streak
# ════════════════════════════════════════════════════════════════════════
def _fresh_regime(regime: str):
    return {"regime": regime, "ok": True, "detail": f"stub-{regime}",
            "base_regime": "BEAR" if regime == "trending_down" else "BULL",
            "rsi": 50.0, "chg_last": 0.0, "chg_prev": 0.0,
            "slope_up": False, "slope_dn": False}


class TestGetBtcRegimeStreakPersistence:
    def _run(self, db):
        return asyncio.run(sched._get_btc_regime(db))

    def test_trend_down_streak_accumulates_and_persists(self, monkeypatch):
        db = FakeDB()
        monkeypatch.setattr(sched, "_compute_btc_regime",
                            lambda: _fresh_regime("trending_down"))
        # _compute_btc_regime dipatch sebagai coroutine
        async def _c():
            return _fresh_regime("trending_down")
        monkeypatch.setattr(sched, "_compute_btc_regime", _c)
        for expect in (1, 2, 3):
            out = self._run(db)
            assert out["trend_down_streak"] == expect, out
            assert out["trend_up_streak"] == 0
            doc = db.asi_scan_status.docs["btc_regime"]
            assert doc["trend_down_streak"] == expect
            assert doc["last_fresh_regime"] == "trending_down"

    def test_trend_down_streak_resets_on_regime_change(self, monkeypatch):
        db = FakeDB()
        async def _down():
            return _fresh_regime("trending_down")
        monkeypatch.setattr(sched, "_compute_btc_regime", _down)
        self._run(db)
        self._run(db)
        assert db.asi_scan_status.docs["btc_regime"]["trend_down_streak"] == 2

        async def _neutral():
            return _fresh_regime("neutral")
        monkeypatch.setattr(sched, "_compute_btc_regime", _neutral)
        out = self._run(db)
        assert out["trend_down_streak"] == 0
        assert db.asi_scan_status.docs["btc_regime"]["trend_down_streak"] == 0

    def test_trend_up_streak_still_tracked(self, monkeypatch):
        """Regresi v10.2.17: trend_up_streak tetap naik & tersimpan."""
        db = FakeDB()
        async def _up():
            return _fresh_regime("trending_up")
        monkeypatch.setattr(sched, "_compute_btc_regime", _up)
        for expect in (1, 2, 3):
            out = self._run(db)
            assert out["trend_up_streak"] == expect, out
            assert out["trend_down_streak"] == 0
        assert db.asi_scan_status.docs["btc_regime"]["trend_up_streak"] == 3

    def test_latch_path_carries_trend_down_streak(self, monkeypatch):
        """Saat latch reversal aktif, field trend_down_streak ikut
        diteruskan pada dict kembalian."""
        db = FakeDB()

        async def _rev():
            return _fresh_regime("bearish_reversal")
        monkeypatch.setattr(sched, "_compute_btc_regime", _rev)
        out = self._run(db)
        assert out.get("latched") is True
        assert "trend_down_streak" in out

        # siklus berikut: fresh neutral tapi latch masih berlaku
        async def _neutral():
            return _fresh_regime("neutral")
        monkeypatch.setattr(sched, "_compute_btc_regime", _neutral)
        out = self._run(db)
        assert out.get("latched") is True
        assert out["regime"] == "bearish_reversal"
        assert "trend_down_streak" in out
        assert out["trend_down_streak"] == 0  # fresh netral mereset streak


# ════════════════════════════════════════════════════════════════════════
# INTEGRASI SCANNER: relaksasi slope LONG saat BTC trending_up terkonfirmasi
# ════════════════════════════════════════════════════════════════════════
class TestLongSlopeRelaxation:
    def test_long_passes_when_price_above_ema_slope_dn_and_streak_ge_3(
            self, monkeypatch):
        """harga>EMA50 & slope turun, regime trending_up & streak>=3 →
        trend-filter LOLOS (lanjut konfirmasi 2 siklus → eksekusi)."""
        db, exec_stub, fetcher = make_harness(
            monkeypatch, side="BUY", conf=95, regime="trending_up",
            base="BULL", streak=3, closes_4h=closes_long_relax())
        run_scan(db, fetcher)  # siklus 1 → lolos filter, menunggu konfirmasi
        rej = rejects_of(db)
        assert "trend_filter_4h_blokir_LONG" not in rej, rej
        assert "buy_menunggu_konfirmasi_siklus_1" in rej, rej
        assert len(exec_stub.calls) == 0
        run_scan(db, fetcher)  # siklus 2 → tereksekusi
        assert len(exec_stub.calls) == 1
        assert exec_stub.calls[0]["side"] == "BUY"

    def test_long_rejected_when_slope_dn_and_streak_0(self, monkeypatch):
        """BTC tidak terkonfirmasi (netral, streak 0) → proteksi slope
        penuh AKTIF: reject 'trend_filter_4h_blokir_LONG'."""
        db, exec_stub, fetcher = make_harness(
            monkeypatch, side="BUY", conf=95, regime="neutral",
            base="BULL", streak=0, closes_4h=closes_long_relax())
        run_scan(db, fetcher)
        rej = rejects_of(db)
        assert "trend_filter_4h_blokir_LONG" in rej, rej
        assert len(exec_stub.calls) == 0

    def test_long_rejected_when_price_below_ema_regardless_of_streak(
            self, monkeypatch):
        """BIAS tidak pernah dibebaskan: harga<EMA50 → SELALU reject walau
        streak sangat besar."""
        db, exec_stub, fetcher = make_harness(
            monkeypatch, side="BUY", conf=95, regime="trending_up",
            base="BULL", streak=20, closes_4h=closes_downtrend())
        run_scan(db, fetcher)
        rej = rejects_of(db)
        assert "trend_filter_4h_blokir_LONG" in rej, rej
        assert len(exec_stub.calls) == 0

    def test_long_slope_relaxed_immediately_on_trending_up_v10229(
            self, monkeypatch):
        """v10.2.29 — Relaksasi slope LONG aktif SEGERA saat BTC
        trending_up (streak=1, tanpa tunggu 3 siklus): harga>EMA50 &
        slope turun → LOLOS filter, lanjut konfirmasi 2 siklus."""
        db, exec_stub, fetcher = make_harness(
            monkeypatch, side="BUY", conf=95, regime="trending_up",
            base="BULL", streak=1, closes_4h=closes_long_relax())
        run_scan(db, fetcher)
        rej = rejects_of(db)
        assert "trend_filter_4h_blokir_LONG" not in rej, rej
        assert not any(r.startswith("anti-flap") for r in rej), rej
        assert "buy_menunggu_konfirmasi_siklus_1" in rej, rej
        run_scan(db, fetcher)
        assert len(exec_stub.calls) == 1
        assert exec_stub.calls[0]["side"] == "BUY"


# ════════════════════════════════════════════════════════════════════════
# INTEGRASI SCANNER: relaksasi slope SHORT saat BTC trending_down terkonfirmasi
# ════════════════════════════════════════════════════════════════════════
class TestShortSlopeRelaxation:
    def test_short_passes_when_price_below_ema_slope_up_and_dn_streak_ge_3(
            self, monkeypatch):
        """harga<EMA50 & slope naik, regime trending_down & dn_streak>=3 →
        trend-filter LOLOS (lanjut konfirmasi SELL 2 siklus → eksekusi)."""
        db, exec_stub, fetcher = make_harness(
            monkeypatch, side="SELL", conf=95, regime="trending_down",
            base="BEAR", streak=0, streak_dn=3,
            closes_4h=closes_short_relax())
        run_scan(db, fetcher)
        rej = rejects_of(db)
        assert "trend_filter_4h_blokir_SHORT" not in rej, rej
        assert "sell_menunggu_konfirmasi_siklus_2" in rej, rej
        assert len(exec_stub.calls) == 0
        run_scan(db, fetcher)
        assert len(exec_stub.calls) == 1
        assert exec_stub.calls[0]["side"] == "SELL"

    def test_short_rejected_when_slope_up_and_dn_streak_0(self, monkeypatch):
        """trending_down tapi streak baru 0 → proteksi slope penuh AKTIF:
        reject 'trend_filter_4h_blokir_SHORT'."""
        db, exec_stub, fetcher = make_harness(
            monkeypatch, side="SELL", conf=95, regime="trending_down",
            base="BEAR", streak=0, streak_dn=0,
            closes_4h=closes_short_relax())
        run_scan(db, fetcher)
        rej = rejects_of(db)
        assert "trend_filter_4h_blokir_SHORT" in rej, rej
        assert len(exec_stub.calls) == 0

    def test_short_rejected_when_price_above_ema_regardless_of_streak(
            self, monkeypatch):
        """BIAS tidak pernah dibebaskan (simetris): harga>EMA50 → SELALU
        reject SHORT walau dn_streak besar."""
        db, exec_stub, fetcher = make_harness(
            monkeypatch, side="SELL", conf=95, regime="trending_down",
            base="BEAR", streak=0, streak_dn=20,
            closes_4h=closes_uptrend())
        run_scan(db, fetcher)
        rej = rejects_of(db)
        assert "trend_filter_4h_blokir_SHORT" in rej, rej
        assert len(exec_stub.calls) == 0


# ════════════════════════════════════════════════════════════════════════
# REGRESI: gate-gate v10.2.17 / v10.2.21 tetap utuh
# ════════════════════════════════════════════════════════════════════════
class TestGateRegressions:
    def test_buy_anti_flap_streak_below_3(self, monkeypatch):
        """v10.2.29: anti-flap dicabut — trending_up baru 1 siklus, BUY
        lanjut ke konfirmasi (bukan ditolak anti-flap)."""
        db, exec_stub, fetcher = make_harness(
            monkeypatch, side="BUY", conf=95, regime="trending_up",
            base="BULL", streak=1, closes_4h=closes_uptrend())
        run_scan(db, fetcher)
        assert len(exec_stub.calls) == 0
        rej = rejects_of(db)
        assert not any(r.startswith("anti-flap") for r in rej), rej
        assert "buy_menunggu_konfirmasi_siklus_1" in rej, rej

    def test_buy_bear4h_conf_bonus(self, monkeypatch):
        """v10.2.17: base4H BEAR → min conf +5 (92 < 95 → reject)."""
        db, exec_stub, fetcher = make_harness(
            monkeypatch, side="BUY", conf=92, regime="neutral",
            base="BEAR", streak=0, closes_4h=closes_uptrend())
        run_scan(db, fetcher)
        assert len(exec_stub.calls) == 0
        assert "conf<95_bear4h" in rejects_of(db)

    def test_buy_two_cycle_confirmation(self, monkeypatch):
        """v10.2.17/21: konfirmasi 2 siklus BUY tetap berlaku."""
        db, exec_stub, fetcher = make_harness(
            monkeypatch, side="BUY", conf=95, regime="neutral",
            base="BULL", streak=0, closes_4h=closes_uptrend())
        run_scan(db, fetcher)
        assert len(exec_stub.calls) == 0
        assert "buy_menunggu_konfirmasi_siklus_1" in rejects_of(db)
        run_scan(db, fetcher)
        assert len(exec_stub.calls) == 1

    def test_sell_two_cycle_confirmation(self, monkeypatch):
        """v10.2.21: konfirmasi 2 siklus SELL tetap berlaku."""
        db, exec_stub, fetcher = make_harness(
            monkeypatch, side="SELL", conf=95, regime="neutral",
            base="BEAR", streak=0, closes_4h=closes_downtrend())
        run_scan(db, fetcher)
        assert len(exec_stub.calls) == 0
        assert "sell_menunggu_konfirmasi_siklus_2" in rejects_of(db)
        run_scan(db, fetcher)
        assert len(exec_stub.calls) == 1


# ════════════════════════════════════════════════════════════════════════
# SCANNER DOC: field v10.2.22 tertulis di asi_scan_status.scanner
# ════════════════════════════════════════════════════════════════════════
class TestScannerDocFields:
    def test_scanner_doc_has_down_streak_and_relax_flag(self, monkeypatch):
        db, _, fetcher = make_harness(
            monkeypatch, side="BUY", conf=95, regime="trending_up",
            base="BULL", streak=5, streak_dn=0,
            closes_4h=closes_long_relax())
        run_scan(db, fetcher)
        doc = scanner_doc(db)
        assert doc.get("btc_trend_up_streak") == 5
        assert doc.get("btc_trend_down_streak") == 0
        gates = doc.get("buy_gates") or {}
        assert gates.get("trend4h_slope_relax_on_confirmed_btc") is True
        assert gates.get("trend_up_min_cycles") == sched.TREND_UP_MIN_CYCLES


# ════════════════════════════════════════════════════════════════════════
# HTTP: scan-debug endpoint (live, read-only)
# ════════════════════════════════════════════════════════════════════════
class TestScanDebugHTTP:
    def test_scan_debug_exposes_down_streak_and_relax_flag(self):
        r = requests.get(f"{BASE_URL}/api/asi/scan-debug",
                         params={"device_id": "hc"}, timeout=20)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "btc_trend_down_streak" in body, body.keys()
        assert "btc_trend_up_streak" in body
        gates = body.get("buy_gates") or {}
        assert gates.get("trend4h_slope_relax_on_confirmed_btc") is True, gates

    def test_scanner_doc_fresh(self):
        body = requests.get(f"{BASE_URL}/api/asi/scan-debug",
                            params={"device_id": "hc"}, timeout=20).json()
        last = datetime.fromisoformat(
            str(body["last_scan_at"]).replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - last).total_seconds()
        assert age < 300, f"scanner doc stale: {age:.0f}s"
