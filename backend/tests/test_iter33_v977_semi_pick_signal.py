"""v9.7.7 — ASI-Bot Semi-Auto PICK A SIGNAL + persistent disclaimer +
leaderboard profit-only + phantom-close regression.

Tests:
 - POST /api/asi/bot persists disclaimer_ack=True; GET returns same.
 - GET /api/asi/leaderboard/live returns only unrealized_pct>0 items,
   sorted desc, rank 1 = highest pct.
 - GET /api/ai-suggestions sorted by confidence desc (accept 403 as
   premium-gated outcome).
 - Regression: POST /api/asi/trades/{id}/close + GET /api/asi/trades
   returns _id as string.
 - Scheduler module query shape (code-level assertion):
   _run_full_auto_scanner's $or includes {full_enabled:True} and legacy
   {enabled:True, mode:full, full_enabled $exists:False}.
"""
from __future__ import annotations

import inspect
import os
import uuid
from datetime import datetime, timezone

import pytest
import requests

BASE_URL = os.environ.get("EXPO_BACKEND_URL") or "https://cryptostock-pro.preview.emergentagent.com"
BASE_URL = BASE_URL.rstrip("/")

DEV = f"test-977-{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    yield s
    # best-effort teardown — delete bot config for this device
    try:
        from motor.motor_asyncio import AsyncIOMotorClient
        import asyncio
        mongo = os.environ.get("MONGO_URL")
        db_name = os.environ.get("DB_NAME")
        if mongo and db_name:
            async def _cleanup():
                client = AsyncIOMotorClient(mongo)
                db = client[db_name]
                await db.asi_bot_config.delete_one({"_id": DEV})
                await db.asi_trades.delete_many({"device_id": DEV})
                await db.asi_credentials.delete_many({"device_id": DEV})
                client.close()
            try:
                asyncio.run(_cleanup())
            except Exception:
                pass
    except Exception:
        pass


# --- disclaimer persistence ----------------------------------------------
class TestDisclaimerPersistence:
    def test_post_bot_persists_disclaimer_ack_true(self, api):
        payload = {
            "enabled": False,
            "exchange": "binance",
            "mode": "semi",
            "max_trades_per_day": 5,
            "risk_pct": 5.0,
            "leverage": 10,
            "whitelist": [],
            "profile": "scalper",
            "min_confidence": 75,
            "daily_loss_limit_usdt": 0.0,
            "semi_enabled": False,
            "full_enabled": False,
            "tp_count": 3,
            "trailing_callback_rate": 2.0,
            "disclaimer_ack": True,
        }
        r = api.post(f"{BASE_URL}/api/asi/bot", params={"device_id": DEV}, json=payload)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True
        assert body.get("disclaimer_ack") is True

    def test_get_bot_returns_disclaimer_ack_true(self, api):
        r = api.get(f"{BASE_URL}/api/asi/bot", params={"device_id": DEV})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("exists") is True
        assert body.get("disclaimer_ack") is True, f"expected disclaimer_ack=True, got {body}"

    def test_post_bot_can_reset_disclaimer_ack_false(self, api):
        payload = {
            "enabled": False, "exchange": "binance", "mode": "semi",
            "max_trades_per_day": 5, "risk_pct": 5.0, "leverage": 10,
            "whitelist": [], "profile": None, "min_confidence": 75,
            "daily_loss_limit_usdt": 0.0,
            "semi_enabled": False, "full_enabled": False,
            "tp_count": 3, "trailing_callback_rate": 2.0,
            "disclaimer_ack": False,
        }
        r = api.post(f"{BASE_URL}/api/asi/bot", params={"device_id": DEV}, json=payload)
        assert r.status_code == 200
        g = api.get(f"{BASE_URL}/api/asi/bot", params={"device_id": DEV}).json()
        assert g.get("disclaimer_ack") is False
        # restore True for later tests expecting ack
        api.post(f"{BASE_URL}/api/asi/bot", params={"device_id": DEV},
                 json={**payload, "disclaimer_ack": True})


# --- live leaderboard: profit only, sorted desc by % ----------------------
class TestLiveLeaderboardProfitOnly:
    def test_leaderboard_live_returns_200(self, api):
        r = api.get(f"{BASE_URL}/api/asi/leaderboard/live")
        assert r.status_code == 200, r.text
        body = r.json()
        assert "items" in body and isinstance(body["items"], list)

    def test_leaderboard_only_positive_and_sorted_desc(self, api):
        items = api.get(f"{BASE_URL}/api/asi/leaderboard/live").json()["items"]
        if not items:
            pytest.skip("empty live leaderboard — nothing to assert ordering on")
        pcts = [float(it.get("unrealized_pct") or 0) for it in items]
        assert all(p > 0 for p in pcts), f"non-positive % present: {pcts}"
        assert pcts == sorted(pcts, reverse=True), f"not desc-sorted: {pcts}"
        # rank 1 has the highest pct
        ranks = [int(it.get("rank") or 0) for it in items]
        assert ranks == sorted(ranks), f"ranks not monotonic: {ranks}"
        assert ranks[0] == 1
        top = items[0]
        assert float(top["unrealized_pct"]) == max(pcts)


# --- /api/ai-suggestions sorted by confidence desc (accept 403) -----------
class TestAiSuggestionsSortedByConfidence:
    def test_ai_suggestions_shape(self, api):
        r = api.get(
            f"{BASE_URL}/api/ai-suggestions",
            params={"market": "crypto", "profile": "scalper", "device_id": DEV},
            timeout=60,
        )
        # Not premium → 403 is an acceptable outcome; verify shape when 200.
        assert r.status_code in (200, 403), r.text
        if r.status_code == 403:
            pytest.skip("premium gated — 403 observed, acceptable per task spec")
        body = r.json()
        # Shape: either {items|suggestions: [...]} or a bare list
        items = (body.get("items") if isinstance(body, dict) else None) \
            or (body.get("suggestions") if isinstance(body, dict) else None) \
            or (body if isinstance(body, list) else [])
        if not items:
            pytest.skip("premium ok but no suggestions returned for this profile")
        confs = [float((it.get("confidence") or it.get("conf") or 0)) for it in items]
        assert confs == sorted(confs, reverse=True), f"not desc-sorted by confidence: {confs}"


# --- regression: close + list trades --------------------------------------
class TestTradeRegression:
    def test_close_unknown_trade_returns_404(self, api):
        r = api.post(f"{BASE_URL}/api/asi/trades/does-not-exist/close",
                     params={"device_id": DEV})
        assert r.status_code == 404

    def test_list_trades_has_items_key_and_string_ids(self, api):
        r = api.get(f"{BASE_URL}/api/asi/trades", params={"device_id": DEV})
        assert r.status_code == 200
        body = r.json()
        assert "items" in body
        for t in body["items"]:
            if "_id" in t:
                assert isinstance(t["_id"], str), f"_id must be string, got {type(t['_id'])}"


# --- scheduler query shape (code-level) -----------------------------------
class TestSchedulerFullOnlyFilter:
    def test_full_auto_scanner_filter_has_full_enabled_and_legacy(self):
        from backend.asi_bot import scheduler as sch  # type: ignore
        src = inspect.getsource(sch._run_full_auto_scanner)
        assert "full_enabled" in src, "scanner must filter on full_enabled"
        # Must include legacy fallback for pre-v9.7.6 docs
        assert "mode" in src and "\"full\"" in src, "scanner must support legacy {enabled,mode:full}"
        assert "$exists" in src, "legacy branch should use $exists False guard"
        # Semi should NOT trigger scans — ensure semi_enabled is NOT in the
        # scanner's filter.
        # (We only check that no $or branch is keyed on semi_enabled.)
        # Allow the string to appear only in comments; split by lines and
        # look at the find() call block.
        assert "semi_enabled" not in src.split("async for cfg")[0] \
            or "semi_enabled" not in src.split("db.asi_bot_config.find(")[1].split(")")[0], \
            "scanner must not key on semi_enabled"


# --- phantom close regression --------------------------------------------
class TestPhantomCloseFix:
    def test_refresh_trade_pnl_returns_open_on_fetch_exception(self):
        """v9.7.7 — When fetch_positions raises, refresh_trade_pnl must
        return status='open' (NOT 'closed')."""
        import asyncio
        from backend.asi_bot import engine  # type: ignore

        class FakeClient:
            markets = {}
            async def fetch_positions(self, _syms):
                raise RuntimeError("API key invalid")
            async def fetch_my_trades(self, _s, limit=20):
                return []
            async def close(self):
                return None

        async def fake_get_client(_doc):
            return FakeClient()

        # Monkey-patch _get_client
        orig = engine._get_client
        engine._get_client = fake_get_client
        try:
            trade = {
                "ccxt_symbol": "BTC/USDT:USDT",
                "symbol": "BTCUSDT",
                "side": "BUY",
                "qty": 0.01,
                "entry_price": 50000.0,
                "stop_loss": 49000.0,
                "pnl_usdt": 1.23,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            doc = {"exchange": "binance",
                   "api_key_enc": None, "api_secret_enc": None, "testnet": True}
            result = asyncio.run(engine.refresh_trade_pnl(doc, trade))
            assert result["status"] == "open", f"expected open on fetch error, got {result}"
            # pnl preserved (not overwritten by fake SL fallback)
            assert float(result.get("pnl_usdt") or 0) == 1.23
        finally:
            engine._get_client = orig

    def test_refresh_trade_pnl_marks_closed_on_empty_positions_ok(self):
        """When fetch_positions SUCCEEDS and returns empty, trade is closed."""
        import asyncio
        from backend.asi_bot import engine  # type: ignore

        class FakeClient:
            markets = {}
            async def fetch_positions(self, _syms):
                return []  # genuine empty — exchange confirms closed
            async def fetch_my_trades(self, _s, limit=20):
                return []
            async def close(self):
                return None

        async def fake_get_client(_doc):
            return FakeClient()

        orig = engine._get_client
        engine._get_client = fake_get_client
        try:
            trade = {
                "ccxt_symbol": "BTC/USDT:USDT", "symbol": "BTCUSDT",
                "side": "BUY", "qty": 0.01, "entry_price": 50000.0,
                "stop_loss": 49000.0, "pnl_usdt": 0.0,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            doc = {"exchange": "binance",
                   "api_key_enc": None, "api_secret_enc": None, "testnet": True}
            result = asyncio.run(engine.refresh_trade_pnl(doc, trade))
            assert result["status"] == "closed", f"expected closed when positions truly empty, got {result}"
        finally:
            engine._get_client = orig
