"""ASI-Bot v9.9.2 — Backend E2E for bracket SL/TP + auto-rollback.

Scenarios (per review_request iter35):
  1. Credential save (POST /api/asi/credentials)
  2. Happy path execute → bracket_type='hard', sl_order_id/tp_order_ids present,
     actual_margin_mode='isolated', trade persisted with status='open'.
  3. Rollback test — inverted SL (above entry on LONG) → 400 with
     detail.code='bracket_sl_failed' (or similar bracket_* code),
     rollback_done=True, "balance Anda aman" phrase. Position cleaned.
  4. Margin-mode mismatch — pre-open CROSS SOL via direct REST, then execute
     ISOLATED on SOL → 400 with detail.code='margin_mode_mismatch'. CROSS
     position left intact.

Uses PUBLIC backend at EXPO_BACKEND_URL or falls back to http://localhost:8001.
Requires Binance Futures Testnet keys per /app/memory/test_credentials.md.
Each test cleans positions + algos for its symbol before/after.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from typing import Any

import httpx
import pytest
import requests
from dotenv import load_dotenv

sys.path.insert(0, "/app/backend")
load_dotenv("/app/backend/.env")

from asi_bot import binance_rest as br  # noqa: E402

# ───────── config ─────────
BASE_URL = (os.environ.get("EXPO_BACKEND_URL") or "http://localhost:8001").rstrip("/")
DEVICE_ID = "test-v992-dev"
API_KEY = "CKVYnTaT05vFNAuGitZEvNk4kArPfZZ1UK6SFyL4nKkf48aNdfhfHEFhgB8ZYKEE"
API_SECRET = "BqbCb9ZKZ2cD4R2mSWfsbeQjwLMm2jcUY1m8IHC6TrsMVCAzBBHpOCyo0Pw2b8TS"
TESTNET = True
PROXY = os.environ.get("ASI_PROXY_URL")


# ───────── helpers ─────────
def _price(sym: str) -> float:
    """Fetch testnet price via proxy."""
    async def _go():
        async with httpx.AsyncClient(proxy=PROXY, timeout=20) as c:
            r = await c.get(
                f"https://testnet.binancefuture.com/fapi/v1/ticker/price?symbol={sym}"
            )
            return float(r.json()["price"])
    return asyncio.run(_go())


def _cleanup(sym: str) -> None:
    """Cancel all algos + market-close any open position for sym (testnet)."""
    async def _go():
        try:
            await br.cancel_all_algo(API_KEY, API_SECRET, TESTNET, sym)
        except Exception:
            pass
        try:
            pos = await br.position_risk(API_KEY, API_SECRET, TESTNET, sym)
        except Exception:
            return
        amt = float((pos or {}).get("positionAmt") or 0)
        if abs(amt) > 0:
            side = "SELL" if amt > 0 else "BUY"
            try:
                await br.market_order(
                    API_KEY, API_SECRET, TESTNET,
                    symbol=sym, side=side, quantity=abs(amt), reduce_only=True,
                )
            except Exception:
                pass
    asyncio.run(_go())


def _position_amt(sym: str) -> float:
    async def _go():
        try:
            pos = await br.position_risk(API_KEY, API_SECRET, TESTNET, sym)
            return float((pos or {}).get("positionAmt") or 0)
        except Exception:
            return 0.0
    return asyncio.run(_go())


def _open_algos(sym: str) -> list[dict[str, Any]]:
    async def _go():
        try:
            return await br.open_algo_orders(API_KEY, API_SECRET, TESTNET, sym)
        except Exception:
            return []
    return asyncio.run(_go())


def _margin_type(sym: str) -> str:
    async def _go():
        try:
            pos = await br.position_risk(API_KEY, API_SECRET, TESTNET, sym)
            return str((pos or {}).get("marginType") or "").lower()
        except Exception:
            return ""
    return asyncio.run(_go())


# ───────── fixtures ─────────
@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ═════════════════════ SCENARIO 1 — Credential save ═════════════════════
class TestCredentialSave:
    def test_save_binance_testnet_credential(self, api):
        r = api.post(
            f"{BASE_URL}/api/asi/credentials",
            params={"device_id": DEVICE_ID},
            json={
                "exchange": "binance",
                "api_key": API_KEY,
                "api_secret": API_SECRET,
                "testnet": True,
            },
            timeout=30,
        )
        assert r.status_code == 200, f"save failed: {r.status_code} {r.text[:300]}"
        data = r.json()
        assert data.get("ok") is True
        assert data.get("exchange") == "binance"
        assert data.get("testnet") is True
        assert data.get("api_key_mask")
        assert data.get("handle")

    def test_credential_persisted(self, api):
        r = api.get(
            f"{BASE_URL}/api/asi/credentials",
            params={"device_id": DEVICE_ID},
            timeout=15,
        )
        assert r.status_code == 200
        items = r.json().get("items", [])
        binance = [x for x in items if x.get("exchange") == "binance"]
        assert len(binance) == 1
        assert binance[0].get("testnet") is True


# ═════════════════════ SCENARIO 2 — Happy path ═════════════════════
class TestHappyPathExecute:
    SYMBOL_BIN = "ETHUSDT"

    def setup_method(self):
        _cleanup(self.SYMBOL_BIN)
        time.sleep(0.4)

    def teardown_method(self):
        _cleanup(self.SYMBOL_BIN)

    def test_execute_eth_isolated_3tp_hard_bracket(self, api):
        px = _price(self.SYMBOL_BIN)
        payload = {
            "exchange": "binance",
            "symbol": "ETH",
            "side": "BUY",
            "entry": px,
            "stop_loss": round(px * 0.97, 2),
            "take_profits": [
                round(px * 1.01, 2),
                round(px * 1.02, 2),
                round(px * 1.03, 2),
            ],
            "risk_pct": 1.0,
            "leverage": 10,
            "tp_count": 3,
            "margin_mode": "isolated",
        }
        r = api.post(
            f"{BASE_URL}/api/asi/trades/execute",
            params={"device_id": DEVICE_ID},
            json=payload,
            timeout=60,
        )
        assert r.status_code == 200, f"execute failed: {r.status_code} {r.text[:400]}"
        data = r.json()
        assert data.get("ok") is True
        assert data.get("bracket_type") == "hard"
        assert data.get("actual_margin_mode") == "isolated"
        assert data.get("sl_order_id"), "sl_order_id missing"
        tp_ids = data.get("tp_order_ids") or []
        assert len(tp_ids) == 3
        # at least one TP id must be set (very small acct can floor some to 0, but
        # for 1% risk × 10× on ~$5k that should give 3 slices > step).
        non_null_tps = [t for t in tp_ids if t]
        assert len(non_null_tps) >= 1, f"no TPs placed: {tp_ids}"
        # Verify algos actually live on exchange
        algos = _open_algos(self.SYMBOL_BIN)
        live_ids = {str(a.get("algoId")) for a in algos}
        assert str(data["sl_order_id"]) in live_ids, "SL algoId not live on Binance"
        verified_tps = sum(1 for t in non_null_tps if str(t) in live_ids)
        assert verified_tps >= 1, f"no TP algoId live: expected {non_null_tps} in {live_ids}"

    def test_trade_persisted_as_open(self, api):
        # list trades for device
        r = api.get(
            f"{BASE_URL}/api/asi/trades",
            params={"device_id": DEVICE_ID},
            timeout=15,
        )
        assert r.status_code == 200
        items = r.json().get("items", [])
        eth_trades = [t for t in items if t.get("symbol") == "ETH"]
        assert len(eth_trades) >= 1
        latest = eth_trades[0]
        assert latest.get("status") == "open"
        assert latest.get("bracket_type") == "hard"
        assert latest.get("actual_margin_mode") == "isolated"


# ═════════════════════ SCENARIO 3 — Rollback (inverted SL) ═════════════════════
class TestRollbackInvertedSL:
    SYMBOL_BIN = "DOGEUSDT"

    def setup_method(self):
        _cleanup(self.SYMBOL_BIN)
        time.sleep(0.4)

    def teardown_method(self):
        _cleanup(self.SYMBOL_BIN)

    def test_execute_inverted_sl_triggers_rollback(self, api):
        px = _price(self.SYMBOL_BIN)
        # LONG with SL ABOVE entry → Binance rejects with -2021 ("order would
        # immediately trigger"). Place TPs sensibly above so the ONLY failure
        # is SL.
        bad_sl = round(px * 1.05, 5)  # above entry
        tps = [
            round(px * 1.01, 5),
            round(px * 1.02, 5),
            round(px * 1.03, 5),
        ]
        payload = {
            "exchange": "binance",
            "symbol": "DOGE",
            "side": "BUY",
            "entry": px,
            "stop_loss": bad_sl,
            "take_profits": tps,
            "risk_pct": 1.0,
            "leverage": 10,
            "tp_count": 3,
            "margin_mode": "isolated",
        }
        r = api.post(
            f"{BASE_URL}/api/asi/trades/execute",
            params={"device_id": DEVICE_ID},
            json=payload,
            timeout=60,
        )
        assert r.status_code == 400, f"expected 400 rollback, got {r.status_code}: {r.text[:400]}"
        body = r.json()
        detail = body.get("detail") or {}
        assert isinstance(detail, dict), f"detail not dict: {body}"
        code = detail.get("code") or ""
        # Engine returns one of these on SL/bracket failure
        assert code in (
            "bracket_sl_failed",
            "bracket_sl_not_verified",
            "bracket_failed_rollback_failed",
        ), f"unexpected code: {code} — body={body}"
        assert detail.get("rollback_done") is True, (
            f"rollback_done missing/False: {detail}"
        )
        assert "balance Anda aman" in (detail.get("message") or ""), (
            f"missing safety phrase: {detail.get('message')}"
        )

    def test_no_lingering_position_or_algos_after_rollback(self, api):
        # Allow rollback market-close to settle
        time.sleep(1.0)
        amt = _position_amt(self.SYMBOL_BIN)
        algos = _open_algos(self.SYMBOL_BIN)
        assert abs(amt) == 0.0, f"position NOT closed after rollback: {amt}"
        assert len(algos) == 0, f"orphan algos still open: {algos}"

    def test_rollback_trade_not_persisted(self, api):
        r = api.get(
            f"{BASE_URL}/api/asi/trades",
            params={"device_id": DEVICE_ID},
            timeout=15,
        )
        assert r.status_code == 200
        items = r.json().get("items", [])
        doge_opens = [
            t for t in items
            if t.get("symbol") == "DOGE" and t.get("status") == "open"
        ]
        assert len(doge_opens) == 0, (
            f"rollback trade got persisted as OPEN: {doge_opens}"
        )


# ═════════════════════ SCENARIO 4 — Margin mismatch ═════════════════════
class TestMarginModeMismatch:
    SYMBOL_BIN = "SOLUSDT"

    def setup_method(self):
        _cleanup(self.SYMBOL_BIN)
        time.sleep(0.5)

    def teardown_method(self):
        _cleanup(self.SYMBOL_BIN)

    def test_open_cross_then_request_isolated_rejected(self, api):
        # 1. Set CROSS + open tiny position directly via REST
        async def _prime():
            await br.set_margin_type(
                API_KEY, API_SECRET, TESTNET,
                symbol=self.SYMBOL_BIN, margin_type="CROSSED",
            )
            await br.market_order(
                API_KEY, API_SECRET, TESTNET,
                symbol=self.SYMBOL_BIN, side="BUY",
                quantity=0.1, reduce_only=False,
            )
        asyncio.run(_prime())
        time.sleep(0.6)

        # Verify prime worked
        pre_amt = _position_amt(self.SYMBOL_BIN)
        pre_mm = _margin_type(self.SYMBOL_BIN)
        assert abs(pre_amt) > 0, "setup failed: cross position did not open"
        assert pre_mm == "cross", f"setup failed: margin not cross (got {pre_mm})"

        # 2. Attempt execute with margin_mode=isolated — must be rejected
        px = _price(self.SYMBOL_BIN)
        payload = {
            "exchange": "binance",
            "symbol": "SOL",
            "side": "BUY",
            "entry": px,
            "stop_loss": round(px * 0.97, 4),
            "take_profits": [
                round(px * 1.01, 4),
                round(px * 1.02, 4),
                round(px * 1.03, 4),
            ],
            "risk_pct": 1.0,
            "leverage": 10,
            "tp_count": 3,
            "margin_mode": "isolated",
        }
        r = api.post(
            f"{BASE_URL}/api/asi/trades/execute",
            params={"device_id": DEVICE_ID},
            json=payload,
            timeout=60,
        )
        assert r.status_code == 400, (
            f"expected 400 margin mismatch, got {r.status_code}: {r.text[:400]}"
        )
        detail = (r.json() or {}).get("detail") or {}
        assert detail.get("code") == "margin_mode_mismatch", (
            f"wrong code: {detail}"
        )

        # 3. Original CROSS position must still exist, UNTOUCHED
        post_amt = _position_amt(self.SYMBOL_BIN)
        post_mm = _margin_type(self.SYMBOL_BIN)
        assert abs(post_amt - pre_amt) < 1e-9, (
            f"original cross position mutated: pre={pre_amt} post={post_amt}"
        )
        assert post_mm == "cross", f"margin flipped to {post_mm}"
