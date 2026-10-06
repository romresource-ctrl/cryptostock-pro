"""ASI-Bot v9.9.13 — Backend tests for LIMIT ENTRY (deep) replacing MARKET entry.

Scenarios (per review_request iter37) — ALL live tests on Binance TESTNET ONLY:
  1. LIMIT ENTRY PENDING: engine.execute_trade with entry 3% BELOW market
     (BUY ETH) → res.ok, pending=True, status='pending_entry',
     entry_expire_at ~+3600s, bracket_type='pending'. Persist to DB exactly
     like routes.execute does. Verify LIMIT GTC order exists on testnet with
     matching price/qty. One pass of scheduler._process_pending_entries keeps
     it pending. Then POST /api/asi/trades/{id}/close cancels the limit order
     (gone on exchange), status='cancelled', NO market close (position 0).
  2. LIMIT ENTRY MARKETABLE: entry = current market price → fills instantly →
     status 'open', bracket_type 'hard', sl_order_id & tp_order_ids set,
     anchor_shift ~ 0, all TPs above / SL below actual entry, SL+TP live in
     openAlgoOrders. Then close_position → account fully clean.
  3. PENDING EXPIRE: fake pending_entry DB doc (entry_expire_at in the past)
     bound to a REAL far-below-market limit order placed manually. One pass of
     _process_pending_entries → status 'expired', close_reason 'entry_expired',
     order cancelled on exchange.
  4. TP GUARD wrong-side (v9.9.12): marketable BUY with one TP BELOW market →
     that TP dropped, tp_count adjusted, bracket stays hard. Close after.
  5. SOFT WATCHER SPLIT (v9.9.12, mocked): dummy soft trade ZZZFAKE qty 3,
     TPs [100,110,120], SL 90. mark=105 → TP1 partial 1/3, tp_filled tracked,
     status stays open, soft_realized_pnl set. mark=125 → TP2 partial, TP3
     full close → status 'closed', close_reason 'TP3'.
  6. TP FLOOR (v9.9.12): GET /api/asset/crypto/BTC/chart?timeframe=1h with and
     without profile=scalper — 200 + schema; if BUY/SELL, TP1 distance >=
     max(0.25% entry, 0.5*ATR).
  7. REGRESSION: /api/dashboard?market=crypto, /api/asi/trades,
     /api/asi/balance 200; no 'watcher loop crash'/'pending entry error'
     spam in backend logs.

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
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pytest
import requests
from dotenv import load_dotenv

sys.path.insert(0, "/app/backend")
load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

from asi_bot import binance_rest as br  # noqa: E402
from asi_bot import engine, scheduler  # noqa: E402

# ───────── config ─────────
BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL")
            or os.environ.get("EXPO_BACKEND_URL")
            or "https://cryptostock-pro.preview.emergentagent.com").rstrip("/")
DEVICE_ID = "web:qmeqflw0e2d-mui5ar38"
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
PROXY = os.environ.get("ASI_PROXY_URL")


# ───────── helpers (testnet REST direct, for price/cleanup/verify) ─────────
def _price(sym: str) -> float:
    """Fetch TESTNET last price (public ticker) via proxy."""
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
    """Cancel all algos + legacy/limit orders + market-close any TESTNET position."""
    key, sec = _testnet_keys()

    async def _go():
        try:
            await br.cancel_all_algo(key, sec, True, sym)
        except Exception:
            pass
        try:
            await br.cancel_all_legacy(key, sec, True, sym)  # also cancels LIMIT orders
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


def _open_limit_orders(sym: str) -> list[dict[str, Any]]:
    """Open LIMIT (regular) orders on testnet for sym."""
    key, sec = _testnet_keys()

    async def _go():
        try:
            orders = await br.open_orders_legacy(key, sec, True, sym)
            return [o for o in orders if str(o.get("type")) == "LIMIT"]
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


def _cancel_limit(sym: str, order_id) -> None:
    key, sec = _testnet_keys()
    asyncio.run(br.cancel_order(key, sec, True, symbol=sym, order_id=order_id))


def _execute_marketable(symbol_bin: str, base: str,
                        tps_fn, side: str = "BUY", attempts: int = 3,
                        markup: float = 0.0):
    """execute_trade with entry ~= current market price. round_to_tick floors,
    so a BUY limit may sit just under the ask and stay pending → cancel stale
    limit and retry with a fresh price (testnet book is thin). `markup`
    (e.g. 0.001 = +0.1%) makes the limit truly marketable on thin books;
    anchor_shift stays ~0 because the fill equals the limit price itself."""
    last: dict[str, Any] = {}
    px = 0.0
    for _ in range(attempts):
        px = _price(symbol_bin)
        last = _execute_on_testnet(
            symbol=base, side=side,
            entry=px * (1 + markup), stop_loss=round(px * 0.99, 6), tps=tps_fn(px),
            risk_pct=1.0, leverage=5, mode="semi", tp_count=3,
            trailing_callback_rate=0.0, margin_mode="isolated",
        )
        if last.get("ok") and not last.get("pending"):
            return last, px
        if last.get("pending"):
            _cancel_limit(symbol_bin, last["entry_order_id"])
            time.sleep(0.6)
            continue
        break
    if last.get("pending"):
        _cancel_limit(symbol_bin, last["entry_order_id"])  # no residue
    return last, px


# ═════════ SCENARIO 1 — LIMIT ENTRY PENDING (ETH, TESTNET) ════════════════
class TestLimitEntryPending:
    SYMBOL_BIN = "ETHUSDT"
    BASE = "ETH"
    rec_id: str | None = None

    def setup_method(self):
        _cleanup(self.SYMBOL_BIN)
        time.sleep(0.4)

    def teardown_method(self):
        _cleanup(self.SYMBOL_BIN)

        async def _del():
            client = AsyncIOMotorClient(MONGO_URL)
            try:
                if self.rec_id:
                    await client[DB_NAME].asi_trades.delete_many({"_id": self.rec_id})
            finally:
                client.close()
        asyncio.run(_del())

    def test_pending_limit_entry_full_flow(self, api):
        px = _price(self.SYMBOL_BIN)
        entry = round(px * 0.97, 2)          # 3% BELOW market → stays pending
        sl = round(entry * 0.99, 2)
        tps = [round(entry * 1.01, 2), round(entry * 1.02, 2), round(entry * 1.03, 2)]

        res = _execute_on_testnet(
            symbol=self.BASE, side="BUY",
            entry=entry, stop_loss=sl, tps=tps,
            risk_pct=1.0, leverage=5, mode="semi", tp_count=3,
            trailing_callback_rate=0.0, margin_mode="isolated",
        )
        assert res.get("ok") is True, f"execute failed: {res}"
        # ── pending contract ──
        assert res.get("pending") is True, f"expected pending=True: {list(res.items())[:8]}"
        assert res.get("status") == "pending_entry"
        assert res.get("bracket_type") == "pending"
        assert res.get("entry_order_id"), "entry_order_id missing"
        assert res.get("sl_order_id") is None
        expire_at = datetime.fromisoformat(str(res["entry_expire_at"]))
        delta = (expire_at - datetime.now(timezone.utc)).total_seconds()
        assert 3300 <= delta <= 3720, f"entry_expire_at not ~1h ahead: {delta:.0f}s"
        # limit price anchored to signal entry (tick-floored)
        assert abs(float(res["entry_price"]) - entry) <= max(0.05, entry * 0.001), (
            f"entry_price {res['entry_price']} vs signal {entry}"
        )

        # ── persist exactly like routes.execute ──
        margin_usdt = round(float(res["qty"]) * float(res["entry_price"])
                            / max(1, int(res["leverage"])), 2)
        rec = {**res, "device_id": DEVICE_ID, "margin_usdt": margin_usdt}
        rec["_id"] = f"{DEVICE_ID}:{res['entry_order_id']}"
        self.rec_id = rec["_id"]

        async def _save():
            client = AsyncIOMotorClient(MONGO_URL)
            try:
                db = client[DB_NAME]
                await db.asi_trades.replace_one({"_id": rec["_id"]}, rec, upsert=True)
            finally:
                client.close()
        asyncio.run(_save())

        # ── verify LIMIT GTC order live on Binance testnet ──
        limits = _open_limit_orders(self.SYMBOL_BIN)
        mine = [o for o in limits
                if str(o.get("orderId")) == str(res["entry_order_id"])]
        assert mine, f"LIMIT entry order NOT found on testnet: {limits}"
        o = mine[0]
        assert o.get("side") == "BUY"
        assert o.get("timeInForce") == "GTC", f"not GTC: {o.get('timeInForce')}"
        assert abs(float(o["price"]) - float(res["entry_price"])) <= max(0.05, entry * 0.001)
        assert abs(float(o["origQty"]) - float(res["qty"])) < 1e-6, (
            f"qty mismatch: exchange {o['origQty']} vs engine {res['qty']}"
        )

        # ── one scheduler pass: not filled & not expired → stays pending ──
        async def _pass():
            client = AsyncIOMotorClient(MONGO_URL)
            try:
                db = client[DB_NAME]
                await scheduler._process_pending_entries(db)
                return await db.asi_trades.find_one({"_id": rec["_id"]})
            finally:
                client.close()
        doc = asyncio.run(_pass())
        assert doc and doc.get("status") == "pending_entry", (
            f"scheduler changed pending state unexpectedly: "
            f"{doc and {k: doc.get(k) for k in ('status', 'close_reason')}}"
        )
        still = _open_limit_orders(self.SYMBOL_BIN)
        assert any(str(x.get("orderId")) == str(res["entry_order_id"]) for x in still), (
            "limit order vanished while trade still pending"
        )

        # ── user cancels via API → limit cancelled, NO market close ──
        pos_before = _position_amt(self.SYMBOL_BIN)
        assert pos_before == 0.0, "position must be flat before cancel"
        r = api.post(
            f"{BASE_URL}/api/asi/trades/{rec['_id']}/close",
            params={"device_id": DEVICE_ID}, timeout=30,
        )
        assert r.status_code == 200, f"{r.status_code}: {r.text[:200]}"
        body = r.json()
        assert body.get("ok") is True and body.get("cancelled_pending") is True, body
        time.sleep(1.0)

        after = _open_limit_orders(self.SYMBOL_BIN)
        assert not any(str(x.get("orderId")) == str(res["entry_order_id"]) for x in after), (
            f"limit order still open after cancel: {after}"
        )
        assert _position_amt(self.SYMBOL_BIN) == 0.0, (
            "position opened during cancel — market close must NOT fire for pending"
        )

        async def _check():
            client = AsyncIOMotorClient(MONGO_URL)
            try:
                return await client[DB_NAME].asi_trades.find_one({"_id": rec["_id"]})
            finally:
                client.close()
        doc2 = asyncio.run(_check())
        assert doc2.get("status") == "cancelled", doc2.get("status")
        assert doc2.get("close_reason") == "cancelled_pending"


# ═════════ SCENARIO 2 — LIMIT ENTRY MARKETABLE (instant fill) ═════════════
class TestLimitEntryMarketable:
    SYMBOL_BIN = "ETHUSDT"
    BASE = "ETH"

    def setup_method(self):
        _cleanup(self.SYMBOL_BIN)
        time.sleep(0.4)

    def teardown_method(self):
        _cleanup(self.SYMBOL_BIN)

    def test_marketable_limit_fills_and_brackets(self):
        res, px = _execute_marketable(
            self.SYMBOL_BIN, self.BASE,
            lambda p: [round(p * 1.01, 2), round(p * 1.02, 2), round(p * 1.03, 2)],
        )
        assert res.get("ok") is True, f"execute failed: {res}"
        assert not res.get("pending"), f"marketable limit went pending after retries: {res.get('status')}"
        assert res.get("status") == "open"
        assert res.get("bracket_type") == "hard"

        # anchor_shift ~ 0 (limit filled at its own price)
        shift = float(res.get("anchor_shift") or 0.0)
        actual_entry = float(res["entry_price"])
        assert abs(shift) <= max(0.05, actual_entry * 0.001), f"anchor_shift {shift}"

        # SL below / all TPs above actual entry
        sl = float(res["stop_loss"])
        tps = [float(t) for t in res["take_profits"]]
        assert sl < actual_entry, f"SL {sl} not below entry {actual_entry}"
        assert len(tps) == int(res.get("tp_count")) == 3, res.get("take_profits")
        for t in tps:
            assert t > actual_entry, f"TP {t} not above entry {actual_entry}"

        # bracket ids present & live in openAlgoOrders
        assert res.get("sl_order_id"), "sl_order_id missing"
        tp_ids = [t for t in (res.get("tp_order_ids") or []) if t]
        assert len(tp_ids) == 3, f"tp_order_ids={res.get('tp_order_ids')}"
        live = {str(a.get("algoId")) for a in _open_algos(self.SYMBOL_BIN)}
        assert str(res["sl_order_id"]) in live, "SL not live on testnet"
        for tid in tp_ids:
            assert str(tid) in live, f"TP {tid} not live on testnet"

        # close_position → account fully clean
        close_res = _close_on_testnet(self.BASE, "BUY", float(res["qty"]))
        assert close_res.get("ok") is True, f"close failed: {close_res}"
        time.sleep(1.2)
        assert abs(_position_amt(self.SYMBOL_BIN)) == 0.0, "position not closed"
        assert _open_algos(self.SYMBOL_BIN) == [], "orphan algo orders remain"
        assert _open_limit_orders(self.SYMBOL_BIN) == [], "orphan limit orders remain"


# ═════════ SCENARIO 3 — PENDING EXPIRE (scheduler unit w/ real order) ════
class TestPendingExpire:
    SYMBOL_BIN = "ETHUSDT"
    BASE = "ETH"
    DOC_ID = "TEST_iter37_expire1"

    def setup_method(self):
        _cleanup(self.SYMBOL_BIN)
        time.sleep(0.3)

    def teardown_method(self):
        _cleanup(self.SYMBOL_BIN)

        async def _del():
            client = AsyncIOMotorClient(MONGO_URL)
            try:
                await client[DB_NAME].asi_trades.delete_many({"_id": self.DOC_ID})
            finally:
                client.close()
        asyncio.run(_del())

    def test_expired_pending_entry_cancelled(self):
        px = _price(self.SYMBOL_BIN)
        far_px = round(px * 0.5, 2)          # far below market → never fills
        key, sec = _testnet_keys()
        order = asyncio.run(br.limit_order(
            key, sec, True, symbol=self.SYMBOL_BIN,
            side="BUY", quantity=0.02, price=far_px,   # notional ~$30 > $20 testnet min
        ))
        oid = order.get("orderId")
        assert oid, f"manual limit order rejected: {order}"

        now = datetime.now(timezone.utc)
        doc = {
            "_id": self.DOC_ID, "device_id": DEVICE_ID,
            "exchange": "binance", "testnet": True,
            "symbol": self.BASE, "ccxt_symbol": "ETH/USDT:USDT",
            "side": "BUY", "entry_order_id": oid,
            "entry_price": far_px, "stop_loss": round(far_px * 0.99, 2),
            "take_profits": [round(far_px * 1.01, 2)], "tp_count": 1,
            "qty": 0.02, "leverage": 5, "risk_pct": 1.0,
            "margin_mode": "isolated", "mode": "full",
            "status": "pending_entry", "pnl_usdt": 0.0,
            "bracket_type": "pending",
            "entry_expire_at": (now - timedelta(seconds=60)).isoformat(),  # PAST
            "created_at": now.isoformat(), "updated_at": now.isoformat(),
        }

        async def _go():
            client = AsyncIOMotorClient(MONGO_URL)
            try:
                db = client[DB_NAME]
                await db.asi_trades.replace_one({"_id": self.DOC_ID}, doc, upsert=True)
                await scheduler._process_pending_entries(db)
                return await db.asi_trades.find_one({"_id": self.DOC_ID})
            finally:
                client.close()
        out = asyncio.run(_go())
        assert out.get("status") == "expired", f"status={out.get('status')}"
        assert out.get("close_reason") == "entry_expired", out.get("close_reason")

        # order cancelled on exchange (CANCELED or gone from open orders)
        st = asyncio.run(br.order_status(
            key, sec, True, symbol=self.SYMBOL_BIN, order_id=oid))
        assert str(st.get("status")) in ("CANCELED", "EXPIRED"), (
            f"limit order not cancelled on exchange: {st.get('status')}"
        )
        assert not any(str(o.get("orderId")) == str(oid)
                       for o in _open_limit_orders(self.SYMBOL_BIN))


# ═════════ SCENARIO 4 — TP GUARD wrong-side (SOL, TESTNET) ═══════════════
class TestTPGuardWrongSide:
    SYMBOL_BIN = "SOLUSDT"
    BASE = "SOL"

    def setup_method(self):
        _cleanup(self.SYMBOL_BIN)
        time.sleep(0.4)

    def teardown_method(self):
        _cleanup(self.SYMBOL_BIN)

    def test_wrong_side_tp_dropped(self):
        captured: dict[str, float] = {}

        def tps_fn(p: float):
            captured["wrong"] = round(p * 0.995, 4)   # BELOW market on BUY
            return [captured["wrong"], round(p * 1.015, 4), round(p * 1.025, 4)]

        res, px = _execute_marketable(self.SYMBOL_BIN, self.BASE, tps_fn,
                                      markup=0.001)  # +0.1% → marketable on thin SOL book
        assert res.get("ok") is True, f"execute failed: {res}"
        assert not res.get("pending"), "marketable limit did not fill after retries"

        actual_entry = float(res["entry_price"])
        tps_out = [float(t) for t in res["take_profits"]]

        # wrong-side TP must NOT survive
        assert all(abs(t - captured["wrong"]) > actual_entry * 0.0005 for t in tps_out), (
            f"wrong-side TP survived: {tps_out} (wrong~{captured['wrong']})"
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


# ═════════ SCENARIO 5 — SOFT WATCHER SPLIT (mocked exchange) ═════════════
class TestSoftWatcherSplit:
    TRADE_ID = "TEST_iter37_soft1"

    def _mk_trade(self) -> dict[str, Any]:
        return {
            "_id": self.TRADE_ID,
            "device_id": "TEST_iter37_dev",
            "exchange": "binance",
            "testnet": True,
            "symbol": "ZZZFAKE",
            "ccxt_symbol": "ZZZFAKE/USDT:USDT",
            "side": "BUY",
            "entry_price": 95.0,
            "qty": 3.0,
            "stop_loss": 90.0,
            "take_profits": [100.0, 110.0, 120.0],
            "tp_count": 3,
            "status": "open",
            "bracket_type": "soft",
            "mode": "full",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }

    def test_tp_split_then_full_close(self, monkeypatch):
        state = {"mark": 105.0}   # TP1(100) hit; TP2/TP3 not; SL(90) not
        calls: dict[str, list] = {"partial": [], "full": []}

        async def fake_mark(exchange, sym, testnet):
            return state["mark"]

        async def fake_cred(db, device_id, exchange, testnet=None):
            return {"exchange": "binance", "testnet": True, "device_id": device_id}

        async def fake_partial(doc, symbol, side, qty):
            calls["partial"].append({"symbol": symbol, "side": side, "qty": qty})
            return {"ok": True, "id": "mock-partial", "avg": 100.0}

        async def fake_full(doc, symbol, side, qty):
            calls["full"].append({"symbol": symbol, "side": side, "qty": qty})
            return {"ok": True, "id": "mock-full", "avg": 100.0}

        async def fake_filters():
            return {}

        monkeypatch.setattr(scheduler, "_public_mark_price", fake_mark)
        monkeypatch.setattr(scheduler, "resolve_credential", fake_cred)
        monkeypatch.setattr(scheduler, "close_position_partial", fake_partial)
        monkeypatch.setattr(scheduler, "close_position", fake_full)
        monkeypatch.setattr(scheduler, "binance_symbol_filters", fake_filters)

        snap: dict[str, dict] = {}

        async def _go():
            client = AsyncIOMotorClient(MONGO_URL)
            db = client[DB_NAME]
            try:
                await db.asi_trades.delete_many({"_id": self.TRADE_ID})
                await db.asi_trades.insert_one(self._mk_trade())
                await scheduler._watch_soft_brackets(db)          # pass 1 (TP1)
                t1 = await db.asi_trades.find_one({"_id": self.TRADE_ID})
                snap["pass1"] = {"partial": len(calls["partial"]),
                                 "full": len(calls["full"])}
                state["mark"] = 125.0                             # TP2+TP3 hit
                await scheduler._watch_soft_brackets(db)          # pass 2
                t2 = await db.asi_trades.find_one({"_id": self.TRADE_ID})
                snap["pass2"] = {"partial": len(calls["partial"]),
                                 "full": len(calls["full"])}
                return t1, t2
            finally:
                await db.asi_trades.delete_many({"_id": self.TRADE_ID})
                client.close()

        t1, t2 = asyncio.run(_go())

        # pass 1: TP1 closes ONLY ~1/3, trade stays open
        assert snap["pass1"] == {"partial": 1, "full": 0}, (
            f"pass1 closes wrong: {snap} calls={calls}"
        )
        assert abs(calls["partial"][0]["qty"] - 1.0) < 1e-9, calls["partial"]
        assert t1.get("tp_filled") == [True, False, False], t1.get("tp_filled")
        assert t1.get("status") == "open", t1.get("status")
        assert not t1.get("close_reason")
        assert abs(float(t1.get("qty_remaining")) - 2.0) < 1e-9, t1.get("qty_remaining")
        # leg pnl = (100 avg - 95 entry) * 1.0 = 5.0
        assert abs(float(t1.get("soft_realized_pnl")) - 5.0) < 1e-6, (
            f"soft_realized_pnl={t1.get('soft_realized_pnl')} (expected 5.0)"
        )

        # pass 2: TP2 partial (~1/3), TP3 full close → closed w/ reason TP3
        assert snap["pass2"]["partial"] == 2, f"TP2 partial missing: {calls}"
        assert abs(calls["partial"][1]["qty"] - 1.0) < 1e-9, calls["partial"]
        assert snap["pass2"]["full"] == 1, f"final full close missing: {calls}"
        # TP3 must close the REMAINING 1.0 (3 - 1 - 1), not the stale
        # pass-start snapshot (2.0) — stale qty overstates realized PnL.
        assert abs(calls["full"][0]["qty"] - 1.0) < 1e-9, (
            f"TP3 full close qty={calls['full'][0]['qty']} — stale qty_remaining "
            "snapshot used inside one watcher pass (expected 1.0)"
        )
        assert t2.get("tp_filled") == [True, True, True], t2.get("tp_filled")
        assert t2.get("status") == "closed", t2.get("status")
        assert t2.get("close_reason") == "TP3", t2.get("close_reason")
        assert float(t2.get("qty_remaining")) == 0.0
        # total realized = 3 legs of (100-95)*1.0 = 15.0
        assert abs(float(t2.get("pnl_usdt")) - 15.0) < 0.01, (
            f"pnl_usdt={t2.get('pnl_usdt')} (expected 15.0)"
        )


# ═════════ SCENARIO 6 — TP FLOOR via chart API ═══════════════════════════
class TestTPFloor:
    def _check_chart(self, api, params: dict):
        r = api.get(f"{BASE_URL}/api/asset/crypto/BTC/chart",
                    params=params, timeout=120)
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

    def test_chart_no_profile(self, api):
        self._check_chart(api, {"timeframe": "1h"})

    def test_chart_scalper_profile(self, api):
        self._check_chart(api, {"timeframe": "1h", "profile": "scalper"})


# ═════════ SCENARIO 7 — REGRESSION ═══════════════════════════════════════
class TestRegression:
    def test_dashboard_crypto(self, api):
        r = api.get(f"{BASE_URL}/api/dashboard",
                    params={"market": "crypto"}, timeout=120)
        assert r.status_code == 200, f"{r.status_code}: {r.text[:200]}"
        d = r.json()
        assets = d.get("assets") or d.get("items") or []
        assert len(assets) >= 5, f"dashboard assets too few: {list(d.keys())}"

    def test_asi_trades_list(self, api):
        r = api.get(f"{BASE_URL}/api/asi/trades",
                    params={"device_id": DEVICE_ID}, timeout=30)
        assert r.status_code == 200, f"{r.status_code}: {r.text[:200]}"
        assert "items" in r.json()

    def test_asi_balance(self, api):
        r = api.get(f"{BASE_URL}/api/asi/balance",
                    params={"device_id": DEVICE_ID}, timeout=60)
        assert r.status_code == 200, f"{r.status_code}: {r.text[:200]}"
        d = r.json()
        assert d.get("ok") is True and "demo" in d and "real" in d, d
        assert (d.get("demo") or {}).get("connected") is True, (
            f"testnet credential not connected: {d.get('demo')}"
        )

    def test_scheduler_loops_healthy(self):
        for phrase in ("watcher loop crash", "pending entry error"):
            out = subprocess.run(
                ["sh", "-c",
                 f"tail -n 3000 /var/log/supervisor/backend.err.log 2>/dev/null "
                 f"| grep -c '{phrase}'"],
                capture_output=True, text=True,
            )
            cnt = int((out.stdout or "0").strip() or 0)
            assert cnt == 0, f"'{phrase}' found {cnt}x in recent backend log"


# ───────── fixtures ─────────
@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s
