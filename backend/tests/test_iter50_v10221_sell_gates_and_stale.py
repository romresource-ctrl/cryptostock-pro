"""v10.2.21 — Anti-chase SELL + SELL confirm 2 cycles + Longterm stale-exit.

Context (iter50):
  Constants in `asi_bot.scheduler`:
    - SELL_CHASE_PCT = 3.0, SELL_CHASE_WINDOW_H = 6
    - SELL_CONFIRM_CYCLES = 2 (symmetric with BUY_CONFIRM_CYCLES=2)
    - LONGTERM_STALE_HOURS = 3.0, LONGTERM_STALE_MIN_PROFIT_PCT = 0.5

  Scanner (`_run_full_auto_scanner`):
    * Anti-chase SELL: if 1h snapshot shows last SELL_CHASE_WINDOW_H hours
      down >= SELL_CHASE_PCT %, SELL for non-BTC alt is rejected with
      reject reason prefix 'anti_chase_sell_'.
    * SELL confirmation: identical SELL signal must appear in 2 scanner
      cycles in a row before `execute_trade` is called (same mechanism as
      BUY; `_buy_confirm_eval` now takes `required_cycles` param).
    * BUY regressions preserved (v10.2.17): anti-flap trending_up streak,
      bear4h conf bonus, BUY_CONFIRM_CYCLES=2.

  Engine (`_refresh_binance`):
    * Early-exit stale: for longterm / Confluence trades older than
      LONGTERM_STALE_HOURS whose floating pct never reached
      LONGTERM_STALE_MIN_PROFIT_PCT, invoke `close_position` and set
      `close_reason='stale_exit'` + `stale_exit_at='longterm_stale_<age>h_max<pct>'`.
    * `max_floating_pct` is persisted in the partial update.
    * If `horizon_exit` already fired in the same tick, stale-exit must
      NOT also call `close_position` (no double close).

  HTTP:
    * GET /api/asi/scan-debug?device_id=hc returns buy_gates containing
      the 6 new/required fields.

All backend-only; no real exchange calls. Mocks mirror iter47 (scheduler)
and iter49 (engine).
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asi_bot import scheduler as sched  # noqa: E402
from asi_bot import engine  # noqa: E402
import market_data  # noqa: E402

BASE_URL = (os.environ.get("EXPO_BACKEND_URL")
            or "https://cryptostock-pro.preview.emergentagent.com").rstrip("/")

NOW = datetime(2026, 10, 17, 12, 0, 0, tzinfo=timezone.utc)


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
DEV = f"test-10221-{uuid.uuid4().hex[:8]}"


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
    # SELL: entry < sl & tp < entry (short)
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


def _regime_stub(regime: str, base: str, streak: int):
    async def _fake(db):
        return {"regime": regime, "ok": True, "detail": "test-stub",
                "base_regime": base, "trend_up_streak": streak,
                "rsi": 50.0, "chg_last": 0.0, "chg_prev": 0.0,
                "slope_up": False, "slope_dn": False}
    return _fake


def _snapshot_stub(buy_bias: bool, *, c1h_drop_pct: float | None = None):
    """4h always provided (trend filter friendly). 1h: by default empty
    (fail-open); when c1h_drop_pct provided, synthesize 1h candles whose
    first→last (6h window) move matches c1h_drop_pct.

    IMPORTANT: scheduler also uses 1h for the BTC RSI gate / RSI1h check.
    The RSI filter in iter47 harness opens with empty candles. Here we
    provide 1h only for the SELL alt test so the anti-chase branch has
    real data.
    """
    async def _fake(symbol, tf):
        if tf == "1h":
            if c1h_drop_pct is None:
                return {"candles": []}
            # 7 candles so n = min(6, len-1) = 6
            closes = [100.0] * 7
            # last close = 100 * (1 + drop/100)
            closes[-1] = 100.0 * (1.0 + c1h_drop_pct / 100.0)
            return {"candles": [{"close": c, "high": c, "low": c}
                                for c in closes]}
        # 4h — 60 closes, trending as per buy_bias (for 4h trend-filter)
        closes = ([100.0 + i * 0.5 for i in range(60)] if buy_bias
                  else [130.0 - i * 0.5 for i in range(60)])
        return {"candles": [{"close": c, "high": c, "low": c} for c in closes]}
    return _fake


def make_harness(monkeypatch, *, side: str, conf: int, regime: str,
                 base: str, streak: int, c1h_drop_pct: float | None = None):
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
                        _snapshot_stub(buy_bias=(side == "BUY"),
                                       c1h_drop_pct=c1h_drop_pct))
    return db, exec_stub, _fetcher


def run_scan(db, fetcher):
    asyncio.run(sched._run_full_auto_scanner(db, fetcher))


def scanner_doc(db) -> dict:
    return db.asi_scan_status.docs.get("scanner") or {}


def rejects_of(db) -> dict:
    return ((scanner_doc(db).get("devices") or {}).get(DEV) or {}).get(
        "rejects") or {}


# ════════════════════════════════════════════════════════════════════════
# UNIT: constants + helper
# ════════════════════════════════════════════════════════════════════════
class TestConstants:
    def test_sell_chase_pct(self):
        assert sched.SELL_CHASE_PCT == 3.0

    def test_sell_chase_window_h(self):
        assert sched.SELL_CHASE_WINDOW_H == 6

    def test_sell_confirm_cycles(self):
        assert sched.SELL_CONFIRM_CYCLES == 2

    def test_longterm_stale_hours(self):
        assert sched.LONGTERM_STALE_HOURS == 3.0

    def test_longterm_stale_min_profit_pct(self):
        assert sched.LONGTERM_STALE_MIN_PROFIT_PCT == 0.5


class TestBuyConfirmEvalRequiredCycles:
    """_buy_confirm_eval must accept `required_cycles` kwarg (defaults to
    BUY_CONFIRM_CYCLES) and use it to decide confirmation threshold."""
    FP = "longterm|TESTFORM"
    WIN = sched.SCANNER_INTERVAL * 2

    def test_required_cycles_default_matches_buy_const(self):
        # same fingerprint fresh → confirmed, cnt reaches required_cycles
        doc = {"fingerprint": self.FP,
               "last_seen_at": (NOW - timedelta(seconds=90)).isoformat(),
               "count": 1}
        ok, cnt = sched._buy_confirm_eval(doc, fingerprint=self.FP, now=NOW,
                                          window_s=self.WIN)
        assert (ok, cnt) == (True, sched.BUY_CONFIRM_CYCLES)

    def test_required_cycles_param_override_for_sell(self):
        doc = {"fingerprint": self.FP,
               "last_seen_at": (NOW - timedelta(seconds=90)).isoformat(),
               "count": 1}
        ok, cnt = sched._buy_confirm_eval(doc, fingerprint=self.FP, now=NOW,
                                          window_s=self.WIN,
                                          required_cycles=sched.SELL_CONFIRM_CYCLES)
        assert ok is True and cnt == sched.SELL_CONFIRM_CYCLES == 2


# ════════════════════════════════════════════════════════════════════════
# INTEGRATION: anti-chase SELL
# ════════════════════════════════════════════════════════════════════════
class TestAntiChaseSell:
    def test_sell_dump_btc_flat_short_dump_guard_only(self, monkeypatch):
        """v10.2.32 — threshold % anti-chase dibuang. Alt dump -5%/6h
        dengan BTC flat → anti_chase TIDAK muncul; short-dump guard
        per-simbol (-1.2%/2h) yang menahan."""
        db, exec_stub, fetcher = make_harness(
            monkeypatch, side="SELL", conf=95, regime="neutral",
            base="BEAR", streak=0, c1h_drop_pct=-5.0)
        run_scan(db, fetcher)
        rej = rejects_of(db)
        assert not any(r.startswith("anti_chase_sell_") for r in rej), rej
        assert any(r.startswith("sell_short_dump_") for r in rej), rej
        assert len(exec_stub.calls) == 0

    def test_sell_not_rejected_when_1h_drop_2pct(self, monkeypatch):
        db, exec_stub, fetcher = make_harness(
            monkeypatch, side="SELL", conf=95, regime="neutral",
            base="BEAR", streak=0, c1h_drop_pct=-1.0)
        run_scan(db, fetcher)
        rej = rejects_of(db)
        # anti_chase must NOT be present
        assert not any(r.startswith("anti_chase_sell_") for r in rej), rej
        # v10.2.25 short-dump guard also must NOT fire (<1.2%/2h)
        assert not any(r.startswith("sell_short_dump_") for r in rej), rej
        # SELL now goes through confirmation (2 cycles) — expect
        # sell_awaiting_confirm_cycle_2 on first scan
        assert "sell_awaiting_confirm_cycle_2" in rej, rej


# ════════════════════════════════════════════════════════════════════════
# INTEGRATION: SELL confirmation 2 cycles (symmetric with BUY)
# ════════════════════════════════════════════════════════════════════════
class TestSellConfirmationTwoCycles:
    def test_sell_requires_two_cycles_then_executes(self, monkeypatch):
        db, exec_stub, fetcher = make_harness(
            monkeypatch, side="SELL", conf=95, regime="neutral",
            base="BEAR", streak=0, c1h_drop_pct=-1.0)
        cf_key = f"{DEV}:ETH:SELL"

        # Cycle 1 — no execute, rejects records sell_menunggu_konfirmasi
        run_scan(db, fetcher)
        assert len(exec_stub.calls) == 0
        assert "sell_awaiting_confirm_cycle_2" in rejects_of(db)
        doc = db.asi_buy_confirm.docs.get(cf_key)
        assert doc and doc["count"] == 1
        assert doc["side"] == "SELL"
        assert doc["fingerprint"] == "longterm|TESTFORM"

        # Cycle 2 — identical signal → execute
        run_scan(db, fetcher)
        assert len(exec_stub.calls) == 1
        assert exec_stub.calls[0]["side"] == "SELL"
        assert exec_stub.calls[0]["symbol"] == "ETH"
        doc = db.asi_buy_confirm.docs[cf_key]
        assert doc["count"] == 0 and doc.get("consumed_at"), (
            f"count/consumed_at expected to be reset after exec: {doc}")

    def test_sell_count_resets_after_exec(self, monkeypatch):
        """Documents post-exec confirm state: count=0 + consumed_at set so
        next identical SELL has to wait again (combined with 15m cooldown
        + dup-position guard in production)."""
        db, exec_stub, fetcher = make_harness(
            monkeypatch, side="SELL", conf=95, regime="neutral",
            base="BEAR", streak=0, c1h_drop_pct=-1.0)
        run_scan(db, fetcher)  # cycle 1
        run_scan(db, fetcher)  # cycle 2 → exec
        cf_key = f"{DEV}:ETH:SELL"
        doc = db.asi_buy_confirm.docs[cf_key]
        assert doc["count"] == 0
        assert doc.get("consumed_at")


# ════════════════════════════════════════════════════════════════════════
# INTEGRATION: BUY regressions (v10.2.17 preserved)
# ════════════════════════════════════════════════════════════════════════
class TestBuyRegressionGates:
    def test_buy_two_cycle_confirmation(self, monkeypatch):
        db, exec_stub, fetcher = make_harness(
            monkeypatch, side="BUY", conf=95, regime="neutral",
            base="BULL", streak=0)
        run_scan(db, fetcher)  # v10.7.12 — BUY 1 siklus langsung eksekusi
        assert len(exec_stub.calls) == 1
        run_scan(db, fetcher)
        assert len(exec_stub.calls) == 1

    def test_buy_anti_flap_trending_up_streak_below_3(self, monkeypatch):
        # v10.2.29 — anti-flap DICABUT: trending_up streak=1 TIDAK lagi
        # menolak BUY; sinyal lanjut ke konfirmasi 2 siklus.
        db, exec_stub, fetcher = make_harness(
            monkeypatch, side="BUY", conf=95, regime="trending_up",
            base="BULL", streak=1)
        run_scan(db, fetcher)
        rej = rejects_of(db)
        assert not any(r.startswith("anti-flap") for r in rej), rej
        assert len(exec_stub.calls) == 1, rej

    def test_buy_bear4h_conf_bonus(self, monkeypatch):
        db, exec_stub, fetcher = make_harness(
            monkeypatch, side="BUY", conf=92, regime="neutral",
            base="BEAR", streak=0)
        run_scan(db, fetcher)
        assert len(exec_stub.calls) == 0
        assert "conf<95_bear4h" in rejects_of(db)


# ════════════════════════════════════════════════════════════════════════
# ENGINE: Early-exit stale longterm
# ════════════════════════════════════════════════════════════════════════
DOC_ENG = {"api_key_enc": "x", "api_secret_enc": "y",
           "testnet": True, "exchange": "binance"}


def _pos_open(amt: float, mark: float, side: str = "BUY") -> dict[str, Any]:
    sign = 1 if side == "BUY" else -1
    return {"positionAmt": sign * abs(amt),
            "unRealizedProfit": 0.0, "marginType": "isolated",
            "markPrice": mark, "leverage": 10}


def _mk_long_trade(**overrides: Any) -> dict[str, Any]:
    base = {
        "symbol": "BCH", "ccxt_symbol": "BCH/USDT:USDT",
        "side": "BUY", "entry_price": 100.0, "qty": 10.0,
        "stop_loss": 95.0, "take_profits": [101.0, 102.0, 103.0],
        "leverage": 10, "profile": "longterm",
        "formula_tag": "Confluence v9",
        "trailing_callback_rate": 0.0,
        "trailing_activated": False,
        "filled_at": (datetime.now(timezone.utc)
                      - timedelta(hours=4)).isoformat(),
        "created_at": (datetime.now(timezone.utc)
                       - timedelta(hours=4)).isoformat(),
    }
    base.update(overrides)
    return base


def _install_engine_mocks(monkeypatch, *, pos, close_result=None,
                          user_trades=None):
    captured: dict[str, Any] = {"close_calls": [], "move_sl_calls": []}

    async def fake_position_risk(*_a, **_kw):
        return pos

    async def fake_request(method, path, *_a, **_kw):
        if path == "/fapi/v1/userTrades":
            return (200, user_trades or [])
        return (200, [])

    async def fake_realized(*_a, **_kw):
        return None

    async def fake_open_algo(*_a, **_kw):
        return []

    async def fake_open_legacy(*_a, **_kw):
        return []

    async def fake_last_fill(*_a, **_kw):
        return None

    async def fake_move_sl(_doc, _trade, *, target_price):
        captured["move_sl_calls"].append(target_price)
        return {"ok": True, "new_sl": target_price, "detail": "mocked"}

    async def fake_close_position(doc, symbol, side, qty):
        captured["close_calls"].append(
            {"symbol": symbol, "side": side, "qty": qty})
        return close_result if close_result is not None else {
            "ok": True, "closed_price": 97.5}

    monkeypatch.setattr(engine, "decrypt", lambda s: s)
    monkeypatch.setattr(engine.br, "position_risk", fake_position_risk)
    monkeypatch.setattr(engine.br, "_request", fake_request)
    monkeypatch.setattr(engine.br, "realized_close_info", fake_realized)
    monkeypatch.setattr(engine.br, "open_algo_orders", fake_open_algo)
    monkeypatch.setattr(engine.br, "open_orders_legacy", fake_open_legacy)
    monkeypatch.setattr(engine.br, "last_fill_price", fake_last_fill)
    monkeypatch.setattr(engine, "move_sl_to_breakeven", fake_move_sl)
    monkeypatch.setattr(engine, "close_position", fake_close_position)
    return captured


class TestLongtermStaleExit:
    def _run(self, trade, pos, monkeypatch, **kw):
        captured = _install_engine_mocks(monkeypatch, pos=pos, **kw)
        upd = asyncio.run(engine._refresh_binance(DOC_ENG, trade))
        return captured, upd

    # ─── positive: longterm profile + age>3h + max<0.5% → close
    def test_stale_exit_fires_for_longterm_lowprofit(self, monkeypatch):
        trade = _mk_long_trade(profile="longterm",
                               formula_tag="OtherFormula",
                               max_floating_pct=0.1)
        pos = _pos_open(10.0, mark=100.2, side="BUY")  # +0.2% floating
        captured, upd = self._run(trade, pos, monkeypatch)
        assert len(captured["close_calls"]) == 1, (
            f"expected close_position call, got {captured}")
        assert upd.get("close_reason") == "stale_exit"
        se = str(upd.get("stale_exit_at") or "")
        assert se.startswith("longterm_stale_"), se
        assert "max" in se

    # ─── positive: confluence tag + swing (not in longterm set but tag matches)
    def test_stale_exit_fires_for_confluence_v9_tag(self, monkeypatch):
        trade = _mk_long_trade(profile="scalper",  # non-longterm profile
                               formula_tag="Confluence v9")
        pos = _pos_open(10.0, mark=100.3, side="BUY")
        captured, upd = self._run(trade, pos, monkeypatch)
        assert len(captured["close_calls"]) == 1
        assert upd.get("close_reason") == "stale_exit"

    # ─── max_floating_pct persisted on update
    def test_max_floating_pct_persisted_when_higher(self, monkeypatch):
        trade = _mk_long_trade(profile="longterm", max_floating_pct=0.05)
        pos = _pos_open(10.0, mark=100.3, side="BUY")  # +0.3% floating
        _, upd = self._run(trade, pos, monkeypatch)
        # new max 0.3 > 0.05 → persisted
        assert "max_floating_pct" in upd
        assert abs(upd["max_floating_pct"] - 0.3) < 1e-6

    # ─── negative controls
    def test_no_close_when_age_below_3h(self, monkeypatch):
        trade = _mk_long_trade(
            profile="longterm",
            filled_at=(datetime.now(timezone.utc)
                       - timedelta(hours=1)).isoformat())
        pos = _pos_open(10.0, mark=100.2, side="BUY")
        captured, upd = self._run(trade, pos, monkeypatch)
        assert captured["close_calls"] == []
        assert upd.get("close_reason") != "stale_exit"
        assert "stale_exit_at" not in upd

    def test_no_close_when_prev_max_above_threshold(self, monkeypatch):
        trade = _mk_long_trade(profile="longterm",
                               max_floating_pct=0.9)  # exceeded 0.5
        pos = _pos_open(10.0, mark=100.2, side="BUY")
        captured, upd = self._run(trade, pos, monkeypatch)
        assert captured["close_calls"] == []
        assert upd.get("close_reason") != "stale_exit"

    def test_no_close_when_current_pct_above_threshold(self, monkeypatch):
        """Even with max=0 stored, if current floating pct > threshold
        the effective_max becomes the current pct and triggers 'not stale'."""
        trade = _mk_long_trade(profile="longterm", max_floating_pct=0.0)
        pos = _pos_open(10.0, mark=101.0, side="BUY")  # +1% floating
        captured, upd = self._run(trade, pos, monkeypatch)
        assert captured["close_calls"] == []
        # max_floating_pct now bumped to ~1.0
        assert upd.get("max_floating_pct", 0) >= 0.99

    def test_no_close_for_scalper_profile_and_no_confluence_tag(
            self, monkeypatch):
        trade = _mk_long_trade(profile="scalper",
                               formula_tag="OtherFormula")
        pos = _pos_open(10.0, mark=100.2, side="BUY")
        captured, upd = self._run(trade, pos, monkeypatch)
        assert captured["close_calls"] == []
        assert upd.get("close_reason") != "stale_exit"
        assert "stale_exit_at" not in upd

    def test_no_close_for_day_profile(self, monkeypatch):
        trade = _mk_long_trade(profile="day", formula_tag="OtherFormula")
        pos = _pos_open(10.0, mark=100.2, side="BUY")
        captured, upd = self._run(trade, pos, monkeypatch)
        assert captured["close_calls"] == []

    # ─── no double close: horizon_exit already fired this tick
    def test_horizon_exit_prevents_double_close(self, monkeypatch):
        """swing profile → horizon_exit=True on creation; mark price above
        entry (profit) + aged past 24h horizon → horizon_exit fires. Then
        the stale-exit block MUST skip since horizon_exit_at is already
        set in _native_partial_upd (even though swing matches
        _is_longterm). We expect exactly 1 close_position call total."""
        trade = _mk_long_trade(
            profile="swing",                 # swing is in PROFILE_PROFIT_CAP_ROE
            formula_tag="OtherFormula",
            horizon_exit=True,               # explicit flag
            hit_and_run=True,
            filled_at=(datetime.now(timezone.utc)
                       - timedelta(hours=25)).isoformat(),  # > 24h horizon
            max_floating_pct=0.0,            # stale conditions also hold
        )
        # mark slightly above entry → horizon_exit profit path triggers
        pos = _pos_open(10.0, mark=100.2, side="BUY")
        captured, upd = self._run(trade, pos, monkeypatch)
        # Exactly ONE close_position call (horizon_exit), not two
        assert len(captured["close_calls"]) == 1, (
            f"expected single close (horizon_exit) only, got "
            f"{captured['close_calls']}, upd={upd}")
        assert upd.get("horizon_exit_at", "").startswith("horizon_exit_swing")
        # stale_exit_at must NOT be set
        assert "stale_exit_at" not in upd
        # close_reason stale_exit must NOT be set
        assert upd.get("close_reason") != "stale_exit"


# ════════════════════════════════════════════════════════════════════════
# HTTP: scan-debug endpoint
# ════════════════════════════════════════════════════════════════════════
class TestScanDebugHTTP:
    def test_scan_debug_buy_gates_has_six_new_fields(self):
        r = requests.get(f"{BASE_URL}/api/asi/scan-debug",
                         params={"device_id": "hc"}, timeout=20)
        assert r.status_code == 200, r.text
        body = r.json()
        gates = body.get("buy_gates") or {}
        for f in ("buy_confirm_cycles", "sell_confirm_cycles",
                  "anti_chase_mode",
                  "longterm_stale_hours", "longterm_stale_min_profit_pct"):
            assert f in gates, f"missing field {f} in buy_gates={gates}"
        assert gates["buy_confirm_cycles"] == 1  # v10.2.31
        assert gates["sell_confirm_cycles"] == 2
        assert gates["anti_chase_mode"] == "btc_momentum"  # v10.2.32
        assert gates["longterm_stale_hours"] == 3.0
        assert gates["longterm_stale_min_profit_pct"] == 0.5

    def test_scanner_doc_fresh(self):
        body = requests.get(f"{BASE_URL}/api/asi/scan-debug",
                            params={"device_id": "hc"}, timeout=20).json()
        last = datetime.fromisoformat(
            str(body["last_scan_at"]).replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - last).total_seconds()
        assert age < 300, f"scanner doc stale: {age:.0f}s"
