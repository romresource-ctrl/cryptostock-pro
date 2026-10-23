"""v10.3.6 — Close All: per-symbol grouping, parallel, retry, live verify (mocked, no orders)."""
import asyncio
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv  # noqa: E402

load_dotenv("/app/backend/.env")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

from asi_bot import routes  # noqa: E402

DEV = "TEST-iter64-closeall"


def _setup(monkeypatch, fail_first: set, live_left: dict):
    calls = []

    async def cred(db, dev, exch, testnet):
        return {"exchange": "binance", "testnet": testnet}

    async def cp(c, sym, side, qty):
        calls.append(sym)
        if sym in fail_first:
            fail_first.discard(sym)
            raise RuntimeError("-1003 rate limit")
        return {"ok": True}

    async def pr(c, sym):
        n = live_left.get(sym, 0)
        if n:
            live_left[sym] = n - 1
            return 5.0
        return 0.0

    async def rp(c, t):
        return {"pnl_usdt": -1.0}

    monkeypatch.setattr(routes, "resolve_credential", cred)
    monkeypatch.setattr(routes, "close_position", cp)
    monkeypatch.setattr(routes, "br_position_risk", pr)
    monkeypatch.setattr(routes, "refresh_trade_pnl", rp)
    return calls


def _seed(rows):
    async def go():
        db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
        await db.asi_trades.delete_many({"device_id": DEV})
        now = datetime.now(timezone.utc).isoformat()
        for i, (sym, side) in enumerate(rows):
            await db.asi_trades.insert_one({"_id": f"{DEV}-{i}", "device_id": DEV, "status": "open",
                                            "exchange": "binance", "testnet": True, "symbol": sym,
                                            "side": side, "qty": 10, "created_at": now})
    asyncio.run(go())


def _statuses():
    async def go():
        db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
        out = {d["_id"]: d["status"] async for d in db.asi_trades.find({"device_id": DEV})}
        await db.asi_trades.delete_many({"device_id": DEV})
        return out
    return asyncio.run(go())


_APP = None


def _client():
    global _APP
    if _APP is None:
        from fastapi import APIRouter
        api = APIRouter(prefix="/api")
        db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
        routes.register(api, db)
        app = FastAPI()
        app.include_router(api)
        _APP = TestClient(app).__enter__()
    return _APP


def test_close_all_retries_and_groups(monkeypatch):
    _seed([("ATOM", "SELL"), ("ATOM", "SELL"), ("XRP", "BUY"), ("SOL", "BUY")])
    calls = _setup(monkeypatch, fail_first={"XRP"}, live_left={"SOL": 1})
    if True:
        c = _client()
        r = c.post(f"/api/asi/trades/close-all?device_id={DEV}").json()
    st = _statuses()
    assert r["ok"] is True and r["closed"] == 4, r
    assert set(st.values()) == {"closed"}
    assert calls.count("ATOM") == 1  # one close per symbol
    assert calls.count("XRP") == 2 and calls.count("SOL") == 2  # retried


def test_close_all_reports_persistent_failure(monkeypatch):
    _seed([("ATOM", "SELL"), ("XRP", "BUY")])
    _setup(monkeypatch, fail_first=set(), live_left={"XRP": 99})
    if True:
        c = _client()
        r = c.post(f"/api/asi/trades/close-all?device_id={DEV}").json()
    st = _statuses()
    assert r["closed"] == 1 and r["errors"][0]["symbol"] == "XRP"
    assert st[f"{DEV}-0"] == "closed" and st[f"{DEV}-1"] == "open"
