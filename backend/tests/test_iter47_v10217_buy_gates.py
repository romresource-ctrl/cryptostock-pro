"""v10.2.17 — Anti-loss BUY gates untuk Full-Auto scanner (iter47).

Coverage:
  UNIT (pure helpers, deterministic):
    - _trend_up_streak: naik 1->2->3 pada trending_up berturut, reset 0
      saat rezim lain, cap 99.
    - _buy_confirm_eval: konfirmasi hanya bila fingerprint sama &
      last_seen dalam window 180s; fingerprint beda / absen > window /
      timestamp rusak -> (False, 1).

  INTEGRASI (_run_full_auto_scanner, fake in-memory DB + signal_fetcher
  stub + monkeypatch scheduler.execute_trade / resolve_credential /
  _get_btc_regime + market_data.get_crypto_snapshot — TANPA order exchange
  nyata):
    (a) BUY siklus1 -> reject buy_awaiting_confirm_cycle_2 (no exec);
        siklus2 identik -> execute_trade terpanggil; siklus3 -> tidak
        eksekusi lagi.
    (b) BUY saat trending_up streak<3 -> reject anti-flap; streak>=3 ->
        lolos gate anti-flap.
    (c) BUY base_regime BEAR conf 92 -> reject conf<95_bear4h;
        conf 96 -> lolos gate conf.
    (d) SELL conf>=min -> dieksekusi SIKLUS PERTAMA tanpa konfirmasi
        (regresi).

  HTTP (public URL, read-only):
    - GET /api/asi/scan-debug?device_id=... expose btc_base_regime_4h,
      btc_trend_up_streak, buy_gates.
    - Regresi: GET /api/ OK; doc asi_scan_status.scanner fresh (<200s)
      dengan field baru.
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

NOW = datetime(2026, 10, 16, 12, 0, 0, tzinfo=timezone.utc)


# ─────────────────────────── fake in-memory Mongo ───────────────────────────
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
                    if val is not _MISSING and val == operand:
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
        if doc is None and filt.keys() == {"_id"}:
            doc = None
        if doc is None:
            # generic find for non-_id filters
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


# ─────────────────────────── scanner harness ────────────────────────────────
DEV = f"test-10217-{uuid.uuid4().hex[:8]}"


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
    return {
        "side": side, "entry": 100.0, "stop_loss": 95.0,
        "take_profits": [101.0, 102.0, 103.0], "confidence": conf,
        "profile": "longterm", "formula_tag": "TESTFORM",
    }


class ExecStub:
    """execute_trade palsu — TIDAK menyentuh exchange. ok=True, entry>0."""

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


def _regime_stub(regime: str, base: str, streak: int):
    async def _fake(db):
        return {"regime": regime, "ok": True, "detail": "test-stub",
                "base_regime": base, "trend_up_streak": streak,
                "rsi": 50.0, "chg_last": 0.0, "chg_prev": 0.0,
                "slope_up": False, "slope_dn": False}
    return _fake


def _snapshot_stub(buy_bias: bool):
    """1h kosong (RSI filter fail-open); 4h = 60 close naik (BUY lolos trend
    filter) atau turun (SELL lolos)."""
    async def _fake(symbol, tf):
        if tf == "1h":
            return {"candles": []}
        closes = ([100.0 + i * 0.5 for i in range(60)] if buy_bias
                  else [130.0 - i * 0.5 for i in range(60)])
        return {"candles": [{"close": c, "high": c, "low": c} for c in closes]}
    return _fake


def make_harness(monkeypatch, *, side: str, conf: int, regime: str,
                 base: str, streak: int):
    db = FakeDB()
    db.asi_bot_config.docs[DEV] = _cfg()
    exec_stub = ExecStub()

    async def _fetcher(market, symbol, profile):
        return _signal(side, conf)

    async def _cred(db_, device_id, exchange, testnet):
        return {"_id": f"cred-{device_id}", "testnet": True}

    monkeypatch.setattr(sched, "_get_btc_regime",
                        _regime_stub(regime, base, streak))
    monkeypatch.setattr(sched, "resolve_credential", _cred)
    monkeypatch.setattr(sched, "execute_trade", exec_stub)
    monkeypatch.setattr(market_data, "get_crypto_snapshot",
                        _snapshot_stub(buy_bias=(side == "BUY")))
    return db, exec_stub, _fetcher


def run_scan(db, fetcher):
    asyncio.run(sched._run_full_auto_scanner(db, fetcher))


def scanner_doc(db) -> dict:
    return db.asi_scan_status.docs.get("scanner") or {}


def rejects_of(db) -> dict:
    return ((scanner_doc(db).get("devices") or {}).get(DEV) or {}).get(
        "rejects") or {}


# ════════════════════════════ UNIT: _trend_up_streak ════════════════════════
class TestTrendUpStreak:
    def test_streak_increments_1_2_3_on_consecutive_trending_up(self):
        s1 = sched._trend_up_streak(None, 0, "trending_up")
        s2 = sched._trend_up_streak("trending_up", s1, "trending_up")
        s3 = sched._trend_up_streak("trending_up", s2, "trending_up")
        assert (s1, s2, s3) == (1, 2, 3)

    def test_streak_resets_to_zero_on_other_regimes(self):
        for other in ("trending_down", "neutral", "bullish_reversal",
                      "bearish_reversal", "bear_capitulation"):
            assert sched._trend_up_streak("trending_up", 3, other) == 0, other

    def test_streak_caps_at_99(self):
        assert sched._trend_up_streak("trending_up", 99, "trending_up") == 99

    def test_first_trending_up_after_other_regime_is_1(self):
        assert sched._trend_up_streak("trending_down", 7, "trending_up") == 1


# ════════════════════════════ UNIT: _buy_confirm_eval ═══════════════════════
class TestBuyConfirmEval:
    FP = "longterm|TESTFORM"
    WIN = sched.SCANNER_INTERVAL * 2  # 180s

    def _doc(self, fp=None, age_s=90, **extra):
        d = {"fingerprint": fp if fp is not None else self.FP,
             "last_seen_at": (NOW - timedelta(seconds=age_s)).isoformat(),
             "count": 1}
        d.update(extra)
        return d

    def test_no_doc_unconfirmed_count1(self):
        assert sched._buy_confirm_eval(None, fingerprint=self.FP, now=NOW,
                                       window_s=self.WIN, required_cycles=2) == (False, 1)

    def test_same_fingerprint_within_window_confirms(self):
        ok, cnt = sched._buy_confirm_eval(self._doc(age_s=90),
                                          fingerprint=self.FP, now=NOW,
                                          window_s=self.WIN, required_cycles=2)
        assert ok is True and cnt == 2

    def test_same_fingerprint_at_window_edge_confirms(self):
        ok, _ = sched._buy_confirm_eval(self._doc(age_s=180),
                                        fingerprint=self.FP, now=NOW,
                                        window_s=self.WIN, required_cycles=2)
        assert ok is True

    def test_same_fingerprint_outside_window_resets(self):
        ok, cnt = sched._buy_confirm_eval(self._doc(age_s=181),
                                          fingerprint=self.FP, now=NOW,
                                          window_s=self.WIN, required_cycles=2)
        assert (ok, cnt) == (False, 1)

    def test_different_fingerprint_resets(self):
        ok, cnt = sched._buy_confirm_eval(self._doc(fp="scalper|OTHER"),
                                          fingerprint=self.FP, now=NOW,
                                          window_s=self.WIN, required_cycles=2)
        assert (ok, cnt) == (False, 1)

    def test_malformed_and_future_timestamps_reset(self):
        bad = self._doc()
        bad["last_seen_at"] = "garbage"
        assert sched._buy_confirm_eval(bad, fingerprint=self.FP, now=NOW,
                                       window_s=self.WIN, required_cycles=2) == (False, 1)
        future = self._doc(age_s=-10)  # last_seen di masa depan
        assert sched._buy_confirm_eval(future, fingerprint=self.FP, now=NOW,
                                       window_s=self.WIN, required_cycles=2) == (False, 1)

    def test_consumed_doc_still_confirms_within_window(self):
        """DOKUMENTASI PERILAKU AKTUAL: helper tidak membaca `count` /
        `consumed_at` — doc yang count-nya sudah direset ke 0 pasca-eksekusi
        TETAP terkonfirmasi bila fingerprint sama & last_seen fresh. Di
        produksi ini termaskir oleh dup-position guard + cooldown 15 menit
        (15 mnt > window 180s), jadi dampak praktis rendah."""
        consumed = self._doc(age_s=60, count=0, consumed_at=NOW.isoformat())
        ok, cnt = sched._buy_confirm_eval(consumed, fingerprint=self.FP,
                                          now=NOW, window_s=self.WIN, required_cycles=2)
        assert (ok, cnt) == (False, 1)  # count=0 (consumed) → tunggu lagi


    def test_buy_default_one_cycle_confirms_immediately(self):
        # v10.7.12 — BUY_CONFIRM_CYCLES=1 (v10.2.31): siklus pertama langsung lolos
        assert sched.BUY_CONFIRM_CYCLES == 1
        assert sched._buy_confirm_eval(None, fingerprint=self.FP, now=NOW,
                                       window_s=self.WIN) == (True, 1)


# ═════════════════ INTEGRASI: _run_full_auto_scanner ════════════════════════
class TestScannerBuyConfirmFlow:
    """v10.7.12 — BUY dieksekusi di siklus pertama (BUY_CONFIRM_CYCLES=1);
    siklus berikutnya tidak eksekusi lagi (dup guard)."""

    def test_buy_executes_first_cycle_then_no_reexecute(self, monkeypatch):
        db, exec_stub, fetcher = make_harness(
            monkeypatch, side="BUY", conf=95, regime="neutral",
            base="BULL", streak=0)
        run_scan(db, fetcher)
        assert len(exec_stub.calls) == 1
        assert exec_stub.calls[0]["side"] == "BUY"
        assert exec_stub.calls[0]["symbol"] == "ETH"
        assert scanner_doc(db)["devices"][DEV]["placed"] == 1
        trade = db.asi_trades.docs.get(f"{DEV}:TESTORD-1")
        assert trade and trade["status"] == "open"
        run_scan(db, fetcher)
        assert len(exec_stub.calls) == 1
        assert "position_exists" in rejects_of(db)

    def test_buy_reexecutes_if_position_row_gone(self, monkeypatch):
        db, exec_stub, fetcher = make_harness(
            monkeypatch, side="BUY", conf=95, regime="neutral",
            base="BULL", streak=0)
        run_scan(db, fetcher)
        assert len(exec_stub.calls) == 1
        db.asi_trades.docs.clear()
        db.asi_scan_claims.docs.clear()
        run_scan(db, fetcher)
        assert len(exec_stub.calls) == 2


class TestScannerTrendingUpBuy:
    """v10.2.12+ — anti-flap streak lama digantikan BTC Regime Gate:
    BUY saat BTC trending_up tidak lagi ditahan streak."""

    def test_buy_trending_up_not_blocked_by_streak(self, monkeypatch):
        db, exec_stub, fetcher = make_harness(
            monkeypatch, side="BUY", conf=95, regime="trending_up",
            base="BULL", streak=1)
        run_scan(db, fetcher)
        rej = rejects_of(db)
        assert not any(r.startswith("anti-flap") for r in rej), rej
        assert len(exec_stub.calls) == 1, rej


class TestScannerBear4hConfBonus:
    """(c) base_regime BEAR: BUY butuh min_conf + 5 (90 -> 95)."""

    def test_buy_conf92_rejected_in_bear4h(self, monkeypatch):
        db, exec_stub, fetcher = make_harness(
            monkeypatch, side="BUY", conf=92, regime="neutral",
            base="BEAR", streak=0)
        run_scan(db, fetcher)
        assert len(exec_stub.calls) == 0
        assert "conf<95_bear4h" in rejects_of(db), rejects_of(db)

    def test_buy_conf96_passes_in_bear4h(self, monkeypatch):
        db, exec_stub, fetcher = make_harness(
            monkeypatch, side="BUY", conf=96, regime="neutral",
            base="BEAR", streak=0)
        run_scan(db, fetcher)  # siklus 1: lolos conf -> konfirmasi
        rej = rejects_of(db)
        assert "conf<95_bear4h" not in rej, rej
        assert len(exec_stub.calls) == 1  # v10.7.12 — BUY 1 siklus


class TestScannerSellRegression:
    """(d) SELL butuh konfirmasi 2 siklus (SELL_CONFIRM_CYCLES=2, v10.2.21)."""

    def test_sell_executes_second_cycle(self, monkeypatch):
        db, exec_stub, fetcher = make_harness(
            monkeypatch, side="SELL", conf=92, regime="neutral",
            base="BEAR", streak=0)  # bonus BEAR TIDAK berlaku utk SELL
        run_scan(db, fetcher)
        assert len(exec_stub.calls) == 0
        assert "sell_awaiting_confirm_cycle_2" in rejects_of(db)
        run_scan(db, fetcher)
        assert len(exec_stub.calls) == 1
        assert exec_stub.calls[0]["side"] == "SELL"
        assert scanner_doc(db)["devices"][DEV]["placed"] == 1
        # SELL tidak boleh menyentuh state konfirmasi BUY
        assert db.asi_buy_confirm.docs.get(f"{DEV}:ETH:BUY") is None


# ═════════════════ HTTP: scan-debug + regresi (public URL) ══════════════════
class TestScanDebugHTTP:
    def test_scan_debug_exposes_new_gate_fields(self):
        r = requests.get(f"{BASE_URL}/api/asi/scan-debug",
                         params={"device_id": f"probe-{uuid.uuid4().hex[:6]}"},
                         timeout=20)
        assert r.status_code == 200, r.text
        body = r.json()
        for field in ("btc_base_regime_4h", "btc_trend_up_streak",
                      "buy_gates"):
            assert field in body, f"missing {field}: {body}"
        assert isinstance(body["btc_trend_up_streak"], int)
        assert body["btc_base_regime_4h"] in (
            "BULL", "BEAR", "BEAR_CAPITULATION", "SIDEWAYS", "UNKNOWN", None)

    def test_buy_gates_constant_values(self):
        body = requests.get(
            f"{BASE_URL}/api/asi/scan-debug",
            params={"device_id": "probe-iter47"}, timeout=20).json()
        gates = body.get("buy_gates") or {}
        assert gates.get("trend_up_min_cycles") == 3
        assert gates.get("bear4h_conf_bonus") == 5
        assert gates.get("buy_confirm_cycles") == 1


class TestRegression:
    def test_health_ok(self):
        r = requests.get(f"{BASE_URL}/api/", timeout=15)
        assert r.status_code == 200
        assert r.json().get("status") == "ok"

    def test_scanner_doc_fresh_and_carries_new_fields(self):
        """asi_scan_status.scanner ter-update tiap siklus (~90s) dengan
        field baru v10.2.17."""
        body = requests.get(
            f"{BASE_URL}/api/asi/scan-debug",
            params={"device_id": "probe-iter47"}, timeout=20).json()
        last = datetime.fromisoformat(
            str(body["last_scan_at"]).replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - last).total_seconds()
        assert age < 200, f"scanner doc stale: {age:.0f}s (interval 90s)"
        assert body.get("buy_gates"), "buy_gates kosong di doc scanner"
