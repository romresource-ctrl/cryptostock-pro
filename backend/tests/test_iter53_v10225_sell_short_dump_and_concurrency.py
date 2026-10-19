"""v10.2.25 — SELL short-dump guard + side concurrency cap (MAX_OPEN_PER_SIDE).

Reuses the FakeDB/scanner harness pattern from iter52 (frozen).

Scenarios (per request):
  A) Side concurrency cap (MAX_OPEN_PER_SIDE=3) via asi_trades.count_documents
     scoped to {device_id, status=open, side, deleted!=true}.
  B) SELL short-dump guard: SELL rejected when 1h closes drop
     >= SELL_SHORT_DUMP_PCT (1.2%) within SELL_SHORT_DUMP_WINDOW_H (2) hours.
     Note: reject label in scheduler.py line 1336 is
       `sell_short_dump_<pct>pct_<n>h`
     NOT `sell_short_dump_*` as mentioned in agent_communication (buy_gates
     field names use `sell_short_dump_pct`). Confirmed by direct code read.
  C) Regression — v10.2.17-24 guards still trigger.
  D) buy_gates audit exposes new v10.2.25 fields.
  E) Smoke: 1 cycle _run_full_auto_scanner completes without exception.
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


# ───────────────────── fake in-memory Mongo (iter52) ────────────────────
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
                    # {"deleted": {"$ne": True}} → doc missing field is OK
                    if val is _MISSING:
                        continue
                    if val == operand:
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
DEV = f"test-10225-{uuid.uuid4().hex[:8]}"


def _cfg(whitelist=None, device_id: str | None = None) -> dict:
    did = device_id or DEV
    return {
        "_id": did, "device_id": did, "enabled": True, "full_enabled": True,
        "mode": "full", "exchange": "binance",
        "whitelist": whitelist or ["ETH"],
        "min_confidence": 90, "max_trades_per_day": 5, "risk_pct": 5.0,
        "leverage": 10, "active_testnet": True, "tp_count": 3,
        "trailing_callback_rate": 0.0, "margin_mode": "isolated",
        "entry_mode": "market", "signal_source": "asi_bot",
    }


def _signal(side: str, conf: int = 95) -> dict:
    if side == "SELL":
        return {"side": "SELL", "entry": 100.0, "stop_loss": 105.0,
                "take_profits": [99.0, 98.0, 97.0], "confidence": conf,
                "profile": "longterm", "formula_tag": "TESTFORM"}
    return {"side": "BUY", "entry": 100.0, "stop_loss": 95.0,
            "take_profits": [101.0, 102.0, 103.0], "confidence": conf,
            "profile": "longterm", "formula_tag": "TESTFORM"}


def _open_trade(symbol: str, side: str, device_id: str | None = None,
                deleted: bool = False, idx: int = 0) -> dict:
    did = device_id or DEV
    return {
        "_id": f"open:{did}:{symbol}:{side}:{idx}:{uuid.uuid4().hex[:6]}",
        "device_id": did, "symbol": symbol, "status": "open",
        "side": side, "deleted": deleted,
        "created_at": _iso(_ago(minutes=5)),
        "updated_at": _iso(_ago(minutes=1)),
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


# 4H series (uptrend/downtrend)
def closes_uptrend() -> list[float]:
    return [100.0 + i * 0.5 for i in range(60)]


def closes_downtrend() -> list[float]:
    return [130.0 - i * 0.5 for i in range(60)]


# 1H series tailored to SELL short-dump guard
def closes_1h_flat() -> list[float]:
    return [100.0] * 8


def closes_1h_sell_shortdump_15() -> list[float]:
    """2h window: last close -1.5% vs c[-3]. 6h window: -1.5% (below 3%)."""
    return [100.0] * 7 + [98.5]


def closes_1h_sell_shortdump_08() -> list[float]:
    """2h window: -0.8% (below 1.2% threshold)."""
    return [100.0] * 7 + [99.2]


def closes_1h_sell_antichase_only() -> list[float]:
    """6h window: ~-3% ← triggers anti_chase_sell FIRST.
    2h window: ~-1.02% ← does NOT trigger short-dump (< 1.2%).
    Order matters: anti_chase_sell check is BEFORE short-dump check."""
    return [100.0, 99.5, 99.0, 98.5, 98.0, 97.5, 97.0]  # len 7


def closes_1h_dump5() -> list[float]:
    """-5%/6h for SELL anti-chase regression."""
    return [100.0] * 6 + [95.0]


def _snapshot_stub(closes_4h, closes_1h):
    async def _fake(symbol, tf):
        if tf == "1h":
            return {"candles": [{"close": c, "high": c, "low": c}
                                for c in closes_1h]}
        return {"candles": [{"close": c, "high": c, "low": c}
                            for c in closes_4h]}
    return _fake


def make_harness(monkeypatch, *, side: str = "SELL", conf: int = 95,
                 regime: str = "neutral", base: str = "BEAR",
                 streak: int = 0, streak_dn: int = 3,
                 whitelist=None,
                 closes_4h=None, closes_1h=None,
                 trades: list[dict] | None = None,
                 extra_configs: list[dict] | None = None,
                 fetcher_side_map: dict | None = None):
    db = FakeDB()
    db.asi_bot_config.docs[DEV] = _cfg(whitelist)
    for c in (extra_configs or []):
        db.asi_bot_config.docs[c["_id"]] = c
    for t in (trades or []):
        db.asi_trades.docs[t["_id"]] = t
    exec_stub = ExecStub()

    async def _fetcher(market, symbol, profile):
        if fetcher_side_map and symbol in fetcher_side_map:
            return _signal(fetcher_side_map[symbol], conf)
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


def device_report(db, device_id=None) -> dict:
    did = device_id or DEV
    return (scanner_doc(db).get("devices") or {}).get(did) or {}


def rejects_of(db, device_id=None) -> dict:
    return device_report(db, device_id).get("rejects") or {}


# ════════════════════════════════════════════════════════════════════════
# UNIT: konstanta v10.2.25
# ════════════════════════════════════════════════════════════════════════
class TestConstantsV10225:
    def test_constants_values(self):
        assert sched.SELL_SHORT_DUMP_PCT == 1.2
        assert sched.SELL_SHORT_DUMP_WINDOW_H == 2
        assert sched.MAX_OPEN_PER_SIDE == 3


# ════════════════════════════════════════════════════════════════════════
# A) SIDE CONCURRENCY CAP (MAX_OPEN_PER_SIDE=3)
# ════════════════════════════════════════════════════════════════════════
class TestSideConcurrencyCap:
    def test_a1_two_open_sell_new_sell_not_rejected_by_cap(self, monkeypatch):
        """2 open SELL → new SELL candidate for LOLOS is NOT rejected by
        max_open_sell. Should fall through to confirmation step."""
        trades = [
            _open_trade("SAND", "SELL", idx=1),
            _open_trade("XLM", "SELL", idx=2),
        ]
        db, exec_stub, fetcher = make_harness(
            monkeypatch, side="SELL", whitelist=["FET"], trades=trades)
        run_scan(db, fetcher)
        rej = rejects_of(db)
        assert not any(r.startswith("max_open_sell") for r in rej), rej
        # Should reach confirmation
        assert "sell_menunggu_konfirmasi_siklus_2" in rej, rej
        assert len(exec_stub.calls) == 0

    def test_a2_three_open_sell_new_sell_rejected(self, monkeypatch):
        """3 open SELL → new SELL REJECTED with reason containing
        'max_open_sell_3_>=_3'."""
        trades = [
            _open_trade("SAND", "SELL", idx=1),
            _open_trade("XLM", "SELL", idx=2),
            _open_trade("SUI", "SELL", idx=3),
        ]
        db, exec_stub, fetcher = make_harness(
            monkeypatch, side="SELL", whitelist=["FET"], trades=trades)
        run_scan(db, fetcher)
        rej = rejects_of(db)
        assert "max_open_sell_3_>=_3" in rej, rej
        assert len(exec_stub.calls) == 0

    def test_a3_three_open_sell_buy_candidate_passes(self, monkeypatch):
        """3 open SELL + BUY candidate for LOLOS → opposite side NOT
        blocked. Must not have max_open_buy reject."""
        trades = [
            _open_trade("SAND", "SELL", idx=1),
            _open_trade("XLM", "SELL", idx=2),
            _open_trade("SUI", "SELL", idx=3),
        ]
        db, exec_stub, fetcher = make_harness(
            monkeypatch, side="BUY", base="BULL",
            closes_4h=closes_uptrend(),
            whitelist=["FET"], trades=trades)
        run_scan(db, fetcher)
        rej = rejects_of(db)
        assert not any(r.startswith("max_open_buy") for r in rej), rej
        assert not any(r.startswith("max_open_sell") for r in rej), rej
        # BUY falls to confirmation
        assert "buy_menunggu_konfirmasi_siklus_1" in rej, rej

    def test_a4_soft_deleted_trades_not_counted(self, monkeypatch):
        """5 docs status=open, side=SELL; 3 have deleted=True → only 2
        counted → new SELL for LINK passes cap."""
        trades = [
            _open_trade("SAND", "SELL", idx=1, deleted=True),
            _open_trade("XLM", "SELL", idx=2, deleted=True),
            _open_trade("SUI", "SELL", idx=3, deleted=True),
            _open_trade("FET", "SELL", idx=4, deleted=False),
            _open_trade("BCH", "SELL", idx=5, deleted=False),
        ]
        db, exec_stub, fetcher = make_harness(
            monkeypatch, side="SELL", whitelist=["LINK"], trades=trades)
        # Bypass daily-trade quota (5 seed trades == cfg.max_trades_per_day=5)
        db.asi_bot_config.docs[DEV]["max_trades_per_day"] = 50
        run_scan(db, fetcher)
        rej = rejects_of(db)
        assert not any(r.startswith("max_open_sell") for r in rej), rej
        assert "sell_menunggu_konfirmasi_siklus_2" in rej, rej

    def test_a5_per_device_scope(self, monkeypatch):
        """3 open SELL under device_id OTHER → cap for device TEST = 0 →
        new SELL for TEST passes."""
        other = "test-10225-OTHER"
        trades = [
            _open_trade("SAND", "SELL", device_id=other, idx=1),
            _open_trade("XLM", "SELL", device_id=other, idx=2),
            _open_trade("SUI", "SELL", device_id=other, idx=3),
        ]
        db, exec_stub, fetcher = make_harness(
            monkeypatch, side="SELL", whitelist=["FET"], trades=trades)
        run_scan(db, fetcher)
        rej = rejects_of(db)
        assert not any(r.startswith("max_open_sell") for r in rej), rej
        assert "sell_menunggu_konfirmasi_siklus_2" in rej, rej


# ════════════════════════════════════════════════════════════════════════
# B) SELL SHORT-DUMP GUARD (-1.2%/2h)
# Reject label is `sell_short_dump_<pct>pct_<n>h` (per scheduler.py L1336).
# ════════════════════════════════════════════════════════════════════════
class TestSellShortDumpGuard:
    def test_b1_sell_rejected_when_dumped_15pct_2h(self, monkeypatch):
        """1h closes drop -1.5% in last 2h → SELL REJECTED with reason
        prefix 'sell_short_dump_'."""
        db, exec_stub, fetcher = make_harness(
            monkeypatch, side="SELL", whitelist=["FET"],
            closes_1h=closes_1h_sell_shortdump_15())
        run_scan(db, fetcher)
        rej = rejects_of(db)
        # Should fire the new v10.2.25 guard
        assert any(r.startswith("sell_short_dump_") for r in rej), rej
        # Should NOT trip legacy anti_chase_sell (-1.5% <= -3% is false)
        assert not any(r.startswith("anti_chase_sell_") for r in rej), rej
        assert len(exec_stub.calls) == 0

    def test_b2_sell_passes_short_dump_at_minus_08pct(self, monkeypatch):
        """1h closes drop only -0.8%/2h → short-dump NOT triggered →
        SELL continues to confirmation."""
        db, exec_stub, fetcher = make_harness(
            monkeypatch, side="SELL", whitelist=["FET"],
            closes_1h=closes_1h_sell_shortdump_08())
        run_scan(db, fetcher)
        rej = rejects_of(db)
        assert not any(r.startswith("sell_short_dump_") for r in rej), rej
        assert not any(r.startswith("anti_chase_sell_") for r in rej), rej
        assert "sell_menunggu_konfirmasi_siklus_2" in rej, rej

    def test_b3_sell_6h_drop_only_btc_flat_goes_to_confirmation(
            self, monkeypatch):
        """v10.2.32 — threshold % anti-chase dibuang: -3%/6h (tapi hanya
        ~-1.02%/2h) dengan BTC flat → anti_chase TIDAK muncul, short-dump
        juga tidak (-1.02% > -1.2%) → SELL lanjut konfirmasi 2 siklus."""
        db, exec_stub, fetcher = make_harness(
            monkeypatch, side="SELL", whitelist=["FET"],
            closes_1h=closes_1h_sell_antichase_only())
        run_scan(db, fetcher)
        rej = rejects_of(db)
        assert not any(r.startswith("anti_chase_sell_") for r in rej), rej
        assert not any(r.startswith("sell_short_dump_") for r in rej), rej
        assert "sell_menunggu_konfirmasi_siklus_2" in rej, rej
        assert len(exec_stub.calls) == 0

    def test_b4_btc_excluded_from_short_dump(self, monkeypatch):
        """BTC: short-dump guard must not change BTC pathway. The entire
        anti-chase/dump block is wrapped in `if sym != 'BTC'` (L1300).
        SELL on BTC with -1.5%/2h closes → NO sell_short_dump_ reject."""
        db, exec_stub, fetcher = make_harness(
            monkeypatch, side="SELL", whitelist=["BTC"],
            closes_1h=closes_1h_sell_shortdump_15())
        run_scan(db, fetcher)
        rej = rejects_of(db)
        assert not any(r.startswith("sell_short_dump_") for r in rej), rej


# ════════════════════════════════════════════════════════════════════════
# C) REGRESSION — v10.2.17-24 guards still fire
# ════════════════════════════════════════════════════════════════════════
class TestRegression:
    def test_c1_anti_flap_buy_streak_below_3(self, monkeypatch):
        """v10.2.29: anti-flap DICABUT — trending_up streak=1 → BUY TIDAK
        lagi ditolak anti-flap (lanjut ke konfirmasi 2 siklus)."""
        db, exec_stub, fetcher = make_harness(
            monkeypatch, side="BUY", base="BULL",
            closes_4h=closes_uptrend(),
            regime="trending_up", streak=1)
        run_scan(db, fetcher)
        rej = rejects_of(db)
        assert not any(r.startswith("anti-flap") for r in rej), rej
        # BUY tetap melewati konfirmasi 2 siklus (bukan eksekusi instan)
        assert "buy_menunggu_konfirmasi_siklus_1" in rej, rej
        assert len(exec_stub.calls) == 0

    def test_c2_buy_two_cycle_confirmation(self, monkeypatch):
        db, exec_stub, fetcher = make_harness(
            monkeypatch, side="BUY", base="BULL",
            closes_4h=closes_uptrend())
        run_scan(db, fetcher)
        assert "buy_menunggu_konfirmasi_siklus_1" in rejects_of(db)
        assert len(exec_stub.calls) == 0
        run_scan(db, fetcher)
        assert len(exec_stub.calls) == 1

    def test_c3_sell_two_cycle_confirmation(self, monkeypatch):
        db, exec_stub, fetcher = make_harness(
            monkeypatch, side="SELL", base="BEAR",
            closes_4h=closes_downtrend())
        run_scan(db, fetcher)
        assert "sell_menunggu_konfirmasi_siklus_2" in rejects_of(db)
        assert len(exec_stub.calls) == 0
        run_scan(db, fetcher)
        assert len(exec_stub.calls) == 1

    def test_c4_sell_dump_btc_flat_short_dump_guard_only(self, monkeypatch):
        """v10.2.32 — regresi diperbarui: dump -5%/6h dengan BTC flat →
        anti_chase TIDAK ada; short-dump guard per-simbol menahan."""
        db, exec_stub, fetcher = make_harness(
            monkeypatch, side="SELL", base="BEAR",
            closes_4h=closes_downtrend(),
            closes_1h=closes_1h_dump5())
        run_scan(db, fetcher)
        rej = rejects_of(db)
        assert not any(r.startswith("anti_chase_sell_") for r in rej), rej
        assert any(r.startswith("sell_short_dump_") for r in rej), rej
        assert len(exec_stub.calls) == 0

    def test_c5_btc_regime_blocks_sell_in_trending_up(self, monkeypatch):
        """trending_up → SELL on ALT rejected 'btc_regime trending_up:
        tolak SELL'."""
        db, exec_stub, fetcher = make_harness(
            monkeypatch, side="SELL", base="BULL",
            closes_4h=closes_downtrend(),
            regime="trending_up", streak=5, whitelist=["FET"])
        run_scan(db, fetcher)
        rej = rejects_of(db)
        assert any("tolak SELL" in r for r in rej), rej

    def test_c6_btc_regime_blocks_buy_in_trending_down(self, monkeypatch):
        db, exec_stub, fetcher = make_harness(
            monkeypatch, side="BUY", base="BEAR",
            closes_4h=closes_uptrend(),
            regime="trending_down", streak=0, streak_dn=5,
            whitelist=["FET"])
        run_scan(db, fetcher)
        rej = rejects_of(db)
        assert any("tolak BUY" in r for r in rej), rej


# ════════════════════════════════════════════════════════════════════════
# D) buy_gates audit (scanner doc) exposes v10.2.25 fields
# ════════════════════════════════════════════════════════════════════════
class TestBuyGatesAuditV10225:
    def test_d1_buy_gates_has_new_v10225_fields(self, monkeypatch):
        db, _, fetcher = make_harness(monkeypatch, side="BUY", base="BULL",
                                      closes_4h=closes_uptrend())
        run_scan(db, fetcher)
        gates = scanner_doc(db).get("buy_gates") or {}
        assert gates.get("sell_short_dump_pct") == 1.2, gates
        assert gates.get("sell_short_dump_window_h") == 2, gates
        assert gates.get("max_open_per_side") == 3, gates
        # v10.2.32: chase % tetap diganti mode momentum
        assert gates.get("anti_chase_mode") == "btc_momentum", gates
        # regression: previous keys still present
        assert gates.get("buy_dump_guard_pct") == 2.5, gates
        assert gates.get("circuit_breaker_losses") == 3, gates
        assert gates.get("symbol_loss_cooldown_hours") == 4, gates


# ════════════════════════════════════════════════════════════════════════
# E) SMOKE: 1 cycle completes without exception; reject reasons recorded
# ════════════════════════════════════════════════════════════════════════
class TestSmokeCycle:
    def test_e1_single_cycle_no_exception_and_rejects_recorded(
            self, monkeypatch):
        trades = [
            _open_trade("SAND", "SELL", idx=1),
            _open_trade("XLM", "SELL", idx=2),
            _open_trade("SUI", "SELL", idx=3),
        ]
        db, exec_stub, fetcher = make_harness(
            monkeypatch, side="SELL", whitelist=["FET"], trades=trades)
        # must complete w/o exception
        run_scan(db, fetcher)
        rep = device_report(db)
        assert rep, "device report missing"
        rej = rejects_of(db)
        assert "max_open_sell_3_>=_3" in rej


# ════════════════════════════════════════════════════════════════════════
# HTTP: scan-debug endpoint exposes new buy_gates fields (live, read-only)
# ════════════════════════════════════════════════════════════════════════
class TestScanDebugHTTPV10225:
    def test_http_buy_gates_exposes_v10225_fields(self):
        try:
            r = requests.get(f"{BASE_URL}/api/asi/scan-debug",
                             params={"device_id": "hc"}, timeout=20)
        except Exception as e:
            pytest.skip(f"scan-debug unreachable: {e}")
        if r.status_code != 200:
            pytest.skip(f"scan-debug non-200: {r.status_code}")
        gates = r.json().get("buy_gates") or {}
        assert gates.get("sell_short_dump_pct") == 1.2, gates
        assert gates.get("sell_short_dump_window_h") == 2, gates
        assert gates.get("max_open_per_side") == 3, gates
