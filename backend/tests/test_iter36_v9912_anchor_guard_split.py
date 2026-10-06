"""ASI-Bot v9.9.12 — Backend tests for anchor-to-fill, TP guard, soft-watcher
split, TP floor, and regression.

Scenarios (per review_request iter36) — ALL live tests on Binance TESTNET ONLY:
  1. ANCHOR-TO-FILL: engine.execute_trade with entry ~3% below market (BUY ETH).
     Verify anchor_shift != 0, SL/TP shifted by anchor_shift, TPs on correct
     side with TP1 >= max(0.25% entry, 0.2R), bracket_type == 'hard'.
     Then close_position + verify no residue.
  2. TP GUARD wrong-side: BUY TIA with TP1 BELOW market → TP1 dropped from
     take_profits, tp_count adjusted. Then close clean.
  3. SOFT WATCHER SPLIT: seeded dummy soft-bracket trade in local Mongo,
     _public_mark_price / close functions monkeypatched (NO exchange orders).
     Verify TP1/TP2 close only 1/3 share each, tp_filled tracked, status stays
     open until final TP, close_reason TP1/TP3/SL.
  4. TP FLOOR: unit test indicators._floor_tp_ladder + GET chart endpoint
     (schema + floor invariant when a BUY/SELL signal exists).
  5. REGRESSION: /api/dashboard?market=crypto, /api/asi/trades, scheduler
     crash scan in backend logs.

Credentials: Binance TESTNET slot of device web:qmeqflw0e2d-mui5ar38 resolved
via engine.resolve_credential(db, device_id, 'binance', True). Mainnet slot
is NEVER touched.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from typing import Any

import httpx
import pytest
import requests
from dotenv import load_dotenv

sys.path.insert(0, "/app/backend")
load_dotenv("/app/backend/.env")

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

from asi_bot import binance_rest as br  # noqa: E402
from asi_bot import engine, scheduler  # noqa: E402
import indicators  # noqa: E402

# ───────── config ─────────
BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL")
            or "https://cryptostock-pro.preview.emergentagent.com").rstrip("/")
DEVICE_ID = "web:qmeqflw0e2d-mui5ar38"
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
PROXY = os.environ.get("ASI_PROXY_URL")


# ───────── helpers (testnet REST direct, for price/cleanup/verify) ─────────
def _price(sym: str) -> float:
    """Fetch TESTNET mark price (public ticker) via proxy."""
    async def _go():
        async with httpx.AsyncClient(proxy=PROXY, timeout=20) as c:
            r = await c.get(
                f"https://testnet.binancefuture.com/fapi/v1/ticker/price?symbol={sym}"
            )
            return float(r.json()["price"])
    return asyncio.run(_go())


def _testnet_keys() -> tuple[str, str]:
    """Resolve decrypted TESTNET credential for the device (never mainnet)."""
    async def _go():
        client = AsyncIOMotorClient(MONGO_URL)
        try:
            db = client[DB_NAME]
            doc = await engine.resolve_credential(db, DEVICE_ID, "binance", True)
            assert doc, "no testnet credential resolved"
            assert bool(doc.get("testnet", True)) is True, "resolved doc is NOT testnet!"
            from asi_bot.crypto import decrypt
            return decrypt(doc["api_key_enc"]), decrypt(doc["api_secret_enc"])
        finally:
            client.close()
    return asyncio.run(_go())


def _cleanup(sym: str) -> None:
    """Cancel all algos + market-close any open TESTNET position for sym."""
    key, sec = _testnet_keys()

    async def _go():
        try:
            await br.cancel_all_algo(key, sec, True, sym)
        except Exception:
            pass
        try:
            await br.cancel_all_legacy(key, sec, True, sym)
        except Exception:
            pass
        try:
            pos = await br.position_risk(key, sec, True, sym)
        except Exception:
            return
        amt = float((pos or {}).get("positionAmt") or 0)
        if abs(amt) > 0:
            side = "SELL" if amt > 0 else "BUY"
            try:
                await br.market_order(
                    key, sec, True,
                    symbol=sym, side=side, quantity=abs(amt), reduce_only=True,
                )
            except Exception:
                pass
    asyncio.run(_go())


def _position_amt(sym: str) -> float:
    key, sec = _testnet_keys()

    async def _go():
        try:
            pos = await br.position_risk(key, sec, True, sym)
            return float((pos or {}).get("positionAmt") or 0)
        except Exception:
            return 0.0
    return asyncio.run(_go())


def _open_algos(sym: str) -> list[dict[str, Any]]:
    key, sec = _testnet_keys()

    async def _go():
        try:
            return await br.open_algo_orders(key, sec, True, sym)
        except Exception:
            return []
    return asyncio.run(_go())


def _execute_on_testnet(**kwargs) -> dict[str, Any]:
    """Call engine.execute_trade directly with the TESTNET credential doc."""
    async def _go():
        client = AsyncIOMotorClient(MONGO_URL)
        try:
            db = client[DB_NAME]
            doc = await engine.resolve_credential(db, DEVICE_ID, "binance", True)
            assert doc, "testnet credential not found"
            assert bool(doc.get("testnet", True)) is True
            return await engine.execute_trade(doc, **kwargs)
        finally:
            client.close()
    return asyncio.run(_go())


def _close_on_testnet(symbol: str, side: str, qty: float) -> dict[str, Any]:
    async def _go():
        client = AsyncIOMotorClient(MONGO_URL)
        try:
            db = client[DB_NAME]
            doc = await engine.resolve_credential(db, DEVICE_ID, "binance", True)
            return await engine.close_position(doc, symbol, side, qty)
        finally:
            client.close()
    return asyncio.run(_go())


# ═════════════════ SCENARIO 1 — ANCHOR-TO-FILL (ETH, TESTNET) ═════════════
class TestAnchorToFill:
    SYMBOL_BIN = "ETHUSDT"
    BASE = "ETH"

    def setup_method(self):
        _cleanup(self.SYMBOL_BIN)
        time.sleep(0.4)

    def teardown_method(self):
        _cleanup(self.SYMBOL_BIN)

    def test_deep_entry_anchors_sl_tp_to_actual_fill(self):
        px = _price(self.SYMBOL_BIN)
        # Signal entry deliberately ~3% BELOW market (deep limit-style entry,
        # but engine always executes MARKET → big anchor shift expected).
        entry_sig = round(px * 0.97, 2)
        sl_sig = round(entry_sig * 0.99, 2)
        risk_sig = entry_sig - sl_sig
        tps_sig = [
            round(entry_sig + 0.7 * risk_sig, 2),
            round(entry_sig + 1.5 * risk_sig, 2),
            round(entry_sig + 2.5 * risk_sig, 2),
        ]
        res = _execute_on_testnet(
            symbol=self.BASE, side="BUY",
            entry=entry_sig, stop_loss=sl_sig, tps=tps_sig,
            risk_pct=1.0, leverage=5, mode="semi", tp_count=3,
            margin_mode="isolated",
        )
        assert res.get("ok") is True, f"execute failed: {res}"

        # (b) anchor shift recorded & non-zero (fill ~3% above signal entry)
        shift = float(res.get("anchor_shift") or 0.0)
        actual_entry = float(res["entry_price"])
        assert abs(shift) > 0, "anchor_shift should be non-zero"
        assert abs(shift - (actual_entry - entry_sig)) < 1e-6, (
            f"anchor_shift {shift} != actual_entry-entry {actual_entry - entry_sig}"
        )

        # (c) SL/TP shifted by anchor_shift relative to signal values
        tol = max(0.05, actual_entry * 0.0003)  # ~3 ticks
        sl_out = float(res["stop_loss"])
        tps_out = [float(t) for t in res["take_profits"]]
        assert abs(sl_out - (sl_sig + shift)) <= tol, (
            f"SL not anchored: out={sl_out} expected~{sl_sig + shift}"
        )
        assert len(tps_out) == 3, f"expected 3 TPs, got {tps_out}"
        for i, tp_sig in enumerate(tps_sig):
            assert abs(tps_out[i] - (tp_sig + shift)) <= tol, (
                f"TP{i + 1} not anchored: out={tps_out[i]} expected~{tp_sig + shift}"
            )

        # (d) all TPs on CORRECT side of actual entry, SL below, TP1 far enough
        assert sl_out < actual_entry, "SL must be below entry for BUY"
        risk_dist = abs(actual_entry - sl_out)
        min_tp_dist = max(actual_entry * 0.0025, risk_dist * 0.2)
        for t in tps_out:
            assert t > actual_entry, f"TP {t} not above entry {actual_entry}"
        assert tps_out[0] - actual_entry >= min_tp_dist - 1e-9, (
            f"TP1 too close: dist={tps_out[0] - actual_entry} min={min_tp_dist}"
        )

        # (e) hard bracket verified on exchange
        assert res.get("bracket_type") == "hard"
        algos = _open_algos(self.SYMBOL_BIN)
        live_ids = {str(a.get("algoId")) for a in algos}
        assert str(res["sl_order_id"]) in live_ids, "SL not live on Binance"

        # close via close_position → account left clean
        close_res = _close_on_testnet(self.BASE, "BUY", float(res["qty"]))
        assert close_res.get("ok") is True, f"close failed: {close_res}"
        time.sleep(1.0)
        assert abs(_position_amt(self.SYMBOL_BIN)) == 0.0, "position not closed"
        assert _open_algos(self.SYMBOL_BIN) == [], "orphan algo orders remain"


# ═════════════════ SCENARIO 2 — TP GUARD wrong-side (TIA, TESTNET) ════════
class TestTPGuardWrongSide:
    SYMBOL_BIN = "TIAUSDT"
    BASE = "TIA"

    def setup_method(self):
        _cleanup(self.SYMBOL_BIN)
        time.sleep(0.4)

    def teardown_method(self):
        _cleanup(self.SYMBOL_BIN)

    def test_wrong_side_tp_dropped(self):
        px = _price(self.SYMBOL_BIN)
        entry_sig = round(px, 4)
        sl_sig = round(px * 0.99, 4)
        wrong_tp = round(px * 0.995, 4)   # BELOW entry on a BUY → must be dropped
        tps_sig = [wrong_tp, round(px * 1.015, 4), round(px * 1.025, 4)]
        res = _execute_on_testnet(
            symbol=self.BASE, side="BUY",
            entry=entry_sig, stop_loss=sl_sig, tps=tps_sig,
            risk_pct=1.0, leverage=5, mode="semi", tp_count=3,
            margin_mode="isolated",
        )
        assert res.get("ok") is True, f"execute failed: {res}"

        actual_entry = float(res["entry_price"])
        tps_out = [float(t) for t in res["take_profits"]]
        shift = float(res.get("anchor_shift") or 0.0)

        # wrong-side TP (shifted) must NOT survive
        wrong_shifted = wrong_tp + shift
        assert all(abs(t - wrong_shifted) > actual_entry * 0.0005 for t in tps_out), (
            f"wrong-side TP survived: {tps_out} (wrong~{wrong_shifted})"
        )
        # tp_count adjusted to surviving TPs
        assert int(res.get("tp_count")) == len(tps_out) == 2, (
            f"tp_count={res.get('tp_count')} tps={tps_out}"
        )
        # every surviving TP on correct side with min distance
        risk_dist = abs(actual_entry - float(res["stop_loss"]))
        min_tp_dist = max(actual_entry * 0.0025, risk_dist * 0.2)
        for t in tps_out:
            assert t - actual_entry >= min_tp_dist - 1e-9, (
                f"surviving TP too close/wrong side: {t} vs entry {actual_entry}"
            )
        assert res.get("bracket_type") == "hard"

        close_res = _close_on_testnet(self.BASE, "BUY", float(res["qty"]))
        assert close_res.get("ok") is True
        time.sleep(1.0)
        assert abs(_position_amt(self.SYMBOL_BIN)) == 0.0
        assert _open_algos(self.SYMBOL_BIN) == []


# ═════════════════ SCENARIO 3 — SOFT WATCHER SPLIT (mocked exchange) ══════
class TestSoftWatcherSplit:
    """One-pass _watch_soft_brackets against local Mongo with monkeypatched
    mark price + close functions (NO exchange orders are sent)."""

    TRADE_ID = "TEST_iter36_soft1"
    SL_TRADE_ID = "TEST_iter36_soft2"

    def _mk_trade(self, _id: str) -> dict[str, Any]:
        return {
            "_id": _id,
            "device_id": "TEST_iter36_dev",
            "exchange": "binance",
            "testnet": True,
            "symbol": "ZZZFAKE",
            "ccxt_symbol": "ZZZFAKE/USDT:USDT",
            "side": "BUY",
            "entry_price": 100.0,
            "qty": 0.9,
            "stop_loss": 80.0,
            "take_profits": [105.0, 110.0, 115.0],
            "tp_count": 3,
            "status": "open",
            "bracket_type": "soft",
            "mode": "full",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }

    def _patch(self, monkeypatch, state, calls):
        async def fake_mark(exchange, sym, testnet):
            return state["mark"]

        async def fake_cred(db, device_id, exchange, testnet=None):
            return {"exchange": "binance", "testnet": True, "device_id": device_id}

        async def fake_partial(doc, symbol, side, qty):
            calls["partial"].append({"symbol": symbol, "side": side, "qty": qty})
            return {"ok": True, "id": "mock-partial", "avg": state["mark"]}

        async def fake_full(doc, symbol, side, qty):
            calls["full"].append({"symbol": symbol, "side": side, "qty": qty})
            return {"ok": True, "id": "mock-full", "avg": state["mark"]}

        async def fake_filters():
            return {}

        monkeypatch.setattr(scheduler, "_public_mark_price", fake_mark)
        monkeypatch.setattr(scheduler, "resolve_credential", fake_cred)
        monkeypatch.setattr(scheduler, "close_position_partial", fake_partial)
        monkeypatch.setattr(scheduler, "close_position", fake_full)
        monkeypatch.setattr(scheduler, "binance_symbol_filters", fake_filters)

    def test_tp_split_per_level(self, monkeypatch):
        state = {"mark": 111.0}  # TP1(105)+TP2(110) hit, TP3(115) not, SL(80) not
        calls: dict[str, list] = {"partial": [], "full": []}
        self._patch(monkeypatch, state, calls)

        snap: dict[str, dict] = {}

        async def _go():
            client = AsyncIOMotorClient(MONGO_URL)
            db = client[DB_NAME]
            try:
                await db.asi_trades.delete_many({"_id": {"$regex": "^TEST_iter36"}})
                await db.asi_trades.insert_one(self._mk_trade(self.TRADE_ID))
                await scheduler._watch_soft_brackets(db)          # pass 1
                t1 = await db.asi_trades.find_one({"_id": self.TRADE_ID})
                snap["pass1"] = {"partial": len(calls["partial"]),
                                 "full": len(calls["full"])}
                state["mark"] = 116.0                              # now TP3 hit
                await scheduler._watch_soft_brackets(db)          # pass 2
                t2 = await db.asi_trades.find_one({"_id": self.TRADE_ID})
                snap["pass2"] = {"partial": len(calls["partial"]),
                                 "full": len(calls["full"])}
                return t1, t2
            finally:
                await db.asi_trades.delete_many({"_id": {"$regex": "^TEST_iter36"}})
                client.close()

        t1, t2 = asyncio.run(_go())

        # pass 1: TP1 & TP2 each close ONLY 1/3 share (not the full position)
        assert snap["pass1"]["full"] == 0, (
            f"full close fired in pass 1 (too early): {calls}"
        )
        assert snap["pass1"]["partial"] == 2, f"expected 2 partial closes: {calls}"
        assert abs(calls["partial"][0]["qty"] - 0.3) < 1e-9
        assert abs(calls["partial"][1]["qty"] - 0.3) < 1e-9

        # tp_filled tracked, status stays OPEN until final TP
        assert t1.get("tp_filled") == [True, True, False], t1.get("tp_filled")
        assert t1.get("status") == "open", f"status={t1.get('status')}"
        assert not t1.get("close_reason"), "close_reason set before final TP"

        # qty_remaining / accumulated pnl after 2 x 1/3 partial closes
        assert abs(float(t1.get("qty_remaining")) - 0.3) < 1e-9, (
            f"qty_remaining={t1.get('qty_remaining')} (expected 0.3 after two 1/3 closes)"
        )
        assert abs(float(t1.get("soft_realized_pnl")) - 6.6) < 1e-6, (
            f"soft_realized_pnl={t1.get('soft_realized_pnl')} (expected 6.6 = 2 legs of 3.3)"
        )

        # pass 2: final TP closes the REST via FULL close, reason TP3
        assert len(calls["full"]) == 1, f"final full close missing: {calls}"
        assert abs(calls["full"][0]["qty"] - 0.3) < 1e-9, (
            f"final close qty={calls['full'][0]['qty']} (expected remaining 0.3)"
        )
        assert t2.get("status") == "closed"
        assert t2.get("close_reason") == "TP3", t2.get("close_reason")
        assert float(t2.get("qty_remaining")) == 0.0
        # total realized: legs (111-100)*0.3*2 + (116-100)*0.3 = 3.3+3.3+4.8
        assert abs(float(t2.get("pnl_usdt")) - 11.4) < 0.01, (
            f"pnl_usdt={t2.get('pnl_usdt')} (expected 11.4)"
        )

    def test_sl_closes_full_remainder(self, monkeypatch):
        state = {"mark": 79.0}  # SL(80) hit for BUY
        calls: dict[str, list] = {"partial": [], "full": []}
        self._patch(monkeypatch, state, calls)

        async def _go():
            client = AsyncIOMotorClient(MONGO_URL)
            db = client[DB_NAME]
            try:
                await db.asi_trades.delete_many({"_id": self.SL_TRADE_ID})
                await db.asi_trades.insert_one(self._mk_trade(self.SL_TRADE_ID))
                await scheduler._watch_soft_brackets(db)
                return await db.asi_trades.find_one({"_id": self.SL_TRADE_ID})
            finally:
                await db.asi_trades.delete_many({"_id": self.SL_TRADE_ID})
                client.close()

        t = asyncio.run(_go())
        assert len(calls["partial"]) == 0, f"SL must not partial-close: {calls}"
        assert len(calls["full"]) == 1, f"SL full close missing: {calls}"
        assert abs(calls["full"][0]["qty"] - 0.9) < 1e-9
        assert t.get("status") == "closed"
        assert t.get("close_reason") == "SL", t.get("close_reason")


# ═════════════════ SCENARIO 4 — TP FLOOR (indicators + API) ═══════════════
class TestTPFloor:
    def test_floor_tp_ladder_buy_unit(self):
        # TPs glued to entry → floored to max(0.25% entry, 0.5*ATR) = 0.5
        out = indicators._floor_tp_ladder("BUY", 100.0, 1.0, 100.1, 100.2, 100.3)
        assert out[0] >= 100.5 - 1e-9, out
        assert out[0] <= out[1] <= out[2], f"ladder not ordered: {out}"

    def test_floor_tp_ladder_sell_unit(self):
        out = indicators._floor_tp_ladder("SELL", 100.0, 1.0, 99.9, 99.8, 99.7)
        assert out[0] <= 99.5 + 1e-9, out
        assert out[0] >= out[1] >= out[2], f"ladder not ordered: {out}"

    def test_floor_tp_ladder_hold_passthrough(self):
        out = indicators._floor_tp_ladder("HOLD", None, 1.0, None, None, None)
        assert out == (None, None, None)

    def test_chart_api_schema_and_floor(self, api):
        r = api.get(
            f"{BASE_URL}/api/asset/crypto/BTC/chart",
            params={"timeframe": "1h", "profile": "scalper"},
            timeout=90,
        )
        assert r.status_code == 200, f"{r.status_code}: {r.text[:200]}"
        d = r.json()
        for k in ("symbol", "market", "timeframe", "ticker", "candles", "signal"):
            assert k in d, f"missing key {k}"
        sig = d["signal"]
        for k in ("action", "confidence", "entry", "stop_loss",
                  "take_profit", "take_profit_2", "take_profit_3"):
            assert k in sig, f"signal missing {k}"
        if sig.get("action") in ("BUY", "SELL") and sig.get("entry"):
            entry = float(sig["entry"])
            tp1 = float(sig["take_profit"])
            atr = float((sig.get("indicators") or {}).get("atr") or 0.0)
            floor = max(entry * 0.0025, atr * 0.5)
            assert abs(tp1 - entry) >= floor - 1e-9, (
                f"TP1 below floor: |{tp1}-{entry}|={abs(tp1 - entry)} < {floor}"
            )


# ═════════════════ SCENARIO 5 — REGRESSION ════════════════════════════════
class TestRegression:
    def test_dashboard_crypto(self, api):
        r = api.get(f"{BASE_URL}/api/dashboard",
                    params={"market": "crypto"}, timeout=90)
        assert r.status_code == 200, f"{r.status_code}: {r.text[:200]}"
        d = r.json()
        assets = d.get("assets") or d.get("items") or []
        assert len(assets) >= 5, f"dashboard assets too few: {list(d.keys())}"

    def test_asi_trades_list(self, api):
        r = api.get(f"{BASE_URL}/api/asi/trades",
                    params={"device_id": DEVICE_ID}, timeout=30)
        assert r.status_code == 200, f"{r.status_code}: {r.text[:200]}"
        assert "items" in r.json()

    def test_scheduler_loops_healthy(self):
        out = subprocess.run(
            ["grep", "-c", "loop crash",
             "/var/log/supervisor/backend.err.log"],
            capture_output=True, text=True,
        )
        crashes = int(out.stdout.strip() or 0)
        assert crashes == 0, f"scheduler loop crashes found in backend log: {crashes}"


# ───────── fixtures ─────────
@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s
