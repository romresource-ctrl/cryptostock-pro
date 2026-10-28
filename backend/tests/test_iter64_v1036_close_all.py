"""v10.6.1 — Close All Binance: sapu semua posisi live via REST (mocked, tanpa order)."""
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


def _setup(monkeypatch, remaining):
    async def cred(db, dev, exch, testnet):
        return {"exchange": "binance", "testnet": testnet}

    async def sweep(c):
        return list(remaining)

    async def rp(c, t):
        return {"pnl_usdt": -1.0}

    monkeypatch.setattr(routes, "resolve_credential", cred)
    monkeypatch.setattr(routes, "_sweep_binance_positions", sweep)
    monkeypatch.setattr(routes, "refresh_trade_pnl", rp)


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


def test_close_all_sweeps_everything(monkeypatch):
    _seed([("ATOM", "SELL"), ("ATOM", "SELL"), ("XRP", "BUY"), ("SOL", "BUY")])
    _setup(monkeypatch, remaining=[])
    r = _client().post(f"/api/asi/trades/close-all?device_id={DEV}").json()
    st = _statuses()
    assert r["ok"] is True and r["closed"] == 4, r
    assert set(st.values()) == {"closed"}


def test_close_all_reports_remaining(monkeypatch):
    _seed([("ATOM", "SELL"), ("XRP", "BUY")])
    _setup(monkeypatch, remaining=["XRPUSDT"])
    r = _client().post(f"/api/asi/trades/close-all?device_id={DEV}").json()
    st = _statuses()
    assert r["closed"] == 1 and r["errors"][0]["symbol"] == "XRPUSDT"
    assert st[f"{DEV}-0"] == "closed" and st[f"{DEV}-1"] == "open"


def test_sweep_closes_all_live_positions(monkeypatch):
    live = {"XRPUSDT": 12.0, "ATOMUSDT": -3.0}
    orders = []

    async def allpos(k, s, tn):
        return [{"symbol": sy, "positionAmt": a} for sy, a in live.items() if a]

    async def mo(k, s, tn, *, symbol, side, quantity, reduce_only=False):
        orders.append((symbol, side, quantity, reduce_only))
        live[symbol] = 0

    async def noop(*a, **kw):
        return {}

    async def filt(tn):
        return {}

    import asi_bot.algo as algo
    import asi_bot.whitelist as wl
    monkeypatch.setattr(routes.br, "all_position_risks", allpos)
    monkeypatch.setattr(routes.br, "market_order", mo)
    monkeypatch.setattr(routes.br, "cancel_all_legacy", noop)
    monkeypatch.setattr(algo, "cancel_all_conditional", noop)
    monkeypatch.setattr(wl, "binance_symbol_filters", filt)
    monkeypatch.setattr(routes, "decrypt", lambda x: x)
    left = asyncio.run(routes._sweep_binance_positions(
        {"api_key_enc": "k", "api_secret_enc": "s", "testnet": True}))
    assert left == []
    assert ("XRPUSDT", "SELL", 12.0, True) in orders
    assert ("ATOMUSDT", "BUY", 3.0, True) in orders
