"""ASI-Bot — background scheduler.

Two periodic jobs:

1. **Soft-bracket watcher** (every 20s):
   Fetches mark price via public ticker and compares to the stored SL/TP
   of every OPEN trade whose `bracket_type == "soft"`. If SL/TP hit it
   fires a MARKET reduceOnly close via `engine.close_position`, updates
   PnL and marks the trade `status="closed"`.

2. **Full-Auto scanner** (every 5 min):
   Walks `asi_bot_config` for every user with `enabled=True` and
   `mode="full"`. For each symbol in `whitelist`, pulls a dashboard-grade
   signal and — if confidence ≥ `min_confidence` and user has NOT hit
   `max_trades_per_day` — opens a bracket trade.

Both jobs are **fire-and-forget**: errors never crash the FastAPI
process. Kubernetes-safe: all state lives in Mongo; no in-memory queues.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from .crypto import decrypt
from .engine import close_position, execute_trade, refresh_trade_pnl
from .exchanges import _build
from .whitelist import is_allowed

logger = logging.getLogger("asi_bot.scheduler")

# Tunables (seconds).
WATCHER_INTERVAL = 20
SCANNER_INTERVAL = 300  # 5 min
# Minimum confidence required for full-auto execution.
MIN_FULL_AUTO_CONFIDENCE = 70


async def _public_mark_price(exchange: str, ccxt_symbol: str, testnet: bool) -> float | None:
    """Fetch mark/last price from a PUBLIC CCXT client (no API key)."""
    client = _build(exchange, "", "", None, testnet)
    try:
        try:
            t = await client.fetch_ticker(ccxt_symbol)
            px = t.get("mark") or t.get("last") or t.get("close")
            return float(px) if px else None
        except Exception as e:  # noqa: BLE001
            logger.debug("mark price fetch failed for %s: %s", ccxt_symbol, e)
            return None
    finally:
        try:
            await client.close()
        except Exception:
            pass


def _is_hit(side: str, mark: float, trigger: float, is_stop_loss: bool) -> bool:
    """SL hit → mark <= sl (long) or mark >= sl (short).
    TP hit → mark >= tp (long) or mark <= tp (short).
    """
    if side == "BUY":
        return mark <= trigger if is_stop_loss else mark >= trigger
    return mark >= trigger if is_stop_loss else mark <= trigger


async def _close_soft_trade(db: Any, trade: dict[str, Any], reason: str) -> None:
    cred = await db.asi_credentials.find_one({"_id": f"{trade['device_id']}:{trade['exchange']}"})
    if not cred:
        return
    try:
        r = await close_position(cred, trade["symbol"], trade["side"], float(trade["qty"]))
    except Exception as e:
        logger.warning("soft close failed %s: %s", trade.get("_id"), e)
        return
    exit_px = float((r or {}).get("avg") or 0) or None
    entry = float(trade.get("entry_price") or 0)
    qty = float(trade.get("qty") or 0)
    if exit_px:
        if trade["side"] == "BUY":
            pnl = (exit_px - entry) * qty
        else:
            pnl = (entry - exit_px) * qty
    else:
        # Fallback: use trigger price we closed at.
        pnl = 0.0
    await db.asi_trades.update_one(
        {"_id": trade["_id"]},
        {"$set": {
            "status": "closed",
            "closed_at": datetime.now(timezone.utc).isoformat(),
            "close_reason": reason,
            "exit_price": exit_px,
            "pnl_usdt": round(pnl, 2),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
    )
    logger.info("soft-bracket closed trade=%s reason=%s pnl=%.2f",
                trade.get("_id"), reason, pnl)


async def _watch_soft_brackets(db: Any) -> None:
    """One pass through all open soft-bracket trades."""
    cursor = db.asi_trades.find({
        "status": "open",
        "$or": [
            {"bracket_type": "soft"},
            # Legacy trades (pre-v9.4.0) only have `soft_bracket: True`.
            {"bracket_type": {"$exists": False}, "soft_bracket": True},
        ],
    })
    async for t in cursor:
        try:
            exchange = t.get("exchange")
            ccxt_sym = t.get("ccxt_symbol")
            testnet = bool(t.get("testnet", True))
            if not (exchange and ccxt_sym):
                continue
            mark = await _public_mark_price(exchange, ccxt_sym, testnet)
            if mark is None:
                continue
            side = t["side"]
            # Check SL first (safety priority).
            sl = float(t.get("stop_loss") or 0)
            if sl and _is_hit(side, mark, sl, is_stop_loss=True):
                await _close_soft_trade(db, t, reason="SL")
                continue
            # Then TPs — close first TP that is hit (watcher simplicity:
            # all-or-nothing on the final TP; partial TP management via
            # exchange-side orders remains unsupported in soft-bracket).
            tps = list(t.get("take_profits") or [])
            for tp in reversed(tps):  # start from furthest TP
                tp = float(tp)
                if _is_hit(side, mark, tp, is_stop_loss=False):
                    await _close_soft_trade(db, t, reason="TP")
                    break
        except Exception as e:  # noqa: BLE001
            logger.warning("watcher error on %s: %s", t.get("_id"), e)


async def _refresh_open_pnl(db: Any) -> None:
    """Keep unrealized PnL fresh for all open trades (hard & soft)."""
    cursor = db.asi_trades.find({"status": "open"})
    async for t in cursor:
        try:
            cred = await db.asi_credentials.find_one(
                {"_id": f"{t['device_id']}:{t['exchange']}"}
            )
            if not cred:
                continue
            upd = await refresh_trade_pnl(cred, t)
            upd["updated_at"] = datetime.now(timezone.utc).isoformat()
            await db.asi_trades.update_one({"_id": t["_id"]}, {"$set": upd})
        except Exception as e:  # noqa: BLE001
            logger.debug("pnl refresh %s: %s", t.get("_id"), e)


async def _trades_today_count(db: Any, device_id: str) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    return await db.asi_trades.count_documents(
        {"device_id": device_id, "created_at": {"$gte": cutoff}}
    )


async def _realized_pnl_today(db: Any, device_id: str) -> float:
    """Sum of pnl_usdt for CLOSED trades in the last 24h (realized loss/gain)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    pipeline = [
        {"$match": {
            "device_id": device_id, "status": "closed",
            "closed_at": {"$gte": cutoff},
        }},
        {"$group": {"_id": None, "pnl": {"$sum": "$pnl_usdt"}}},
    ]
    agg = await db.asi_trades.aggregate(pipeline).to_list(1)
    return float((agg[0] if agg else {}).get("pnl") or 0.0)


async def _enforce_daily_loss_limit(db: Any) -> None:
    """v9.4.1 — Auto-disable any bot whose realized loss today ≤ -limit.

    Writes `enabled=False` + `auto_disabled_reason` + `auto_disabled_at`
    so the UI can show WHY the bot stopped. Users must manually re-enable.
    """
    cursor = db.asi_bot_config.find({
        "enabled": True,
        "daily_loss_limit_usdt": {"$gt": 0},
    })
    async for cfg in cursor:
        try:
            device_id = cfg.get("device_id") or cfg.get("_id")
            if not device_id:
                continue
            limit = float(cfg.get("daily_loss_limit_usdt") or 0.0)
            if limit <= 0:
                continue
            realized = await _realized_pnl_today(db, device_id)
            if realized <= -limit:
                now = datetime.now(timezone.utc).isoformat()
                await db.asi_bot_config.update_one(
                    {"_id": cfg["_id"]},
                    {"$set": {
                        "enabled": False,
                        "auto_disabled_reason": (
                            f"Daily loss limit reached: "
                            f"${realized:.2f} ≤ -${limit:.2f}"
                        ),
                        "auto_disabled_at": now,
                        "updated_at": now,
                    }},
                )
                logger.warning(
                    "Bot auto-disabled for %s: realized=%.2f limit=%.2f",
                    device_id, realized, limit,
                )
        except Exception as e:  # noqa: BLE001
            logger.debug("daily loss check %s: %s", cfg.get("_id"), e)


async def _run_full_auto_scanner(
    db: Any,
    signal_fetcher: Callable[[str, str, str | None], Awaitable[dict[str, Any] | None]],
) -> None:
    """Scan every enabled Full-Auto bot config and trigger trades.

    `signal_fetcher(market, symbol, profile)` must return a dict with:
      side ("BUY"|"SELL"), entry, stop_loss, take_profits[], confidence
    Must return None/missing fields to skip.
    """
    cursor = db.asi_bot_config.find({"enabled": True, "mode": "full"})
    async for cfg in cursor:
        try:
            device_id = cfg.get("device_id") or cfg.get("_id")
            if not device_id:
                continue
            max_tr = int(cfg.get("max_trades_per_day") or 5)
            placed = await _trades_today_count(db, device_id)
            if placed >= max_tr:
                continue
            whitelist = cfg.get("whitelist") or []
            if not whitelist:
                continue
            exchange = cfg.get("exchange") or "binance"
            cred = await db.asi_credentials.find_one({"_id": f"{device_id}:{exchange}"})
            if not cred:
                continue
            risk = float(cfg.get("risk_pct") or 5.0)
            lev = int(cfg.get("leverage") or 10)
            user_min_conf = int(cfg.get("min_confidence") or MIN_FULL_AUTO_CONFIDENCE)
            # v9.6.1 — Hormati profil strategi user: scalper→VWAP-SCALPER,
            # day→VWAP-INTRADAY, swing→VWAP-SWING, confluence→mesin default.
            bot_profile = cfg.get("profile") or None
            budget = max_tr - placed
            for sym in whitelist[: budget * 3]:  # try ≤3x slots so we have options
                if not is_allowed(sym):
                    continue
                try:
                    sig = await signal_fetcher("crypto", sym, bot_profile)
                except Exception:
                    continue
                if not sig or not sig.get("side"):
                    continue
                if int(sig.get("confidence") or 0) < user_min_conf:
                    continue
                # Guard: skip if an OPEN trade on same symbol exists.
                dup = await db.asi_trades.find_one(
                    {"device_id": device_id, "symbol": sym, "status": "open"}
                )
                if dup:
                    continue
                try:
                    res = await execute_trade(
                        cred, sym, sig["side"],
                        float(sig["entry"]), float(sig["stop_loss"]),
                        [float(x) for x in sig.get("take_profits") or []],
                        risk, lev, mode="full",
                        tp_count=int(cfg.get("tp_count") or 3),
                        trailing_callback_rate=float(cfg.get("trailing_callback_rate") or 0.0),
                    )
                except Exception as e:
                    logger.warning("full-auto execute failed %s/%s: %s", device_id, sym, e)
                    continue
                if not res.get("ok"):
                    continue
                margin_usdt = round(
                    float(res["qty"]) * float(res["entry_price"])
                    / max(1, int(res["leverage"])), 2,
                )
                rec = {**res, "device_id": device_id, "margin_usdt": margin_usdt}
                if res.get("entry_order_id"):
                    rec["_id"] = f"{device_id}:{res['entry_order_id']}"
                    await db.asi_trades.replace_one({"_id": rec["_id"]}, rec, upsert=True)
                placed += 1
                logger.info("full-auto placed %s %s %s", device_id, sym, sig["side"])
                if placed >= max_tr:
                    break
        except Exception as e:  # noqa: BLE001
            logger.warning("full-auto scan error: %s", e)


class ASIScheduler:
    """Lightweight asyncio loop runner. Started on FastAPI startup."""

    def __init__(
        self,
        db: Any,
        signal_fetcher: Callable[[str, str, str | None], Awaitable[dict[str, Any] | None]],
    ) -> None:
        self.db = db
        self.signal_fetcher = signal_fetcher
        self._tasks: list[asyncio.Task] = []
        self._running = False

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._tasks = [
            asyncio.create_task(self._loop_watcher()),
            asyncio.create_task(self._loop_pnl()),
            asyncio.create_task(self._loop_scanner()),
        ]
        logger.info("ASI-Bot scheduler started: watcher + pnl + scanner")

    async def stop(self) -> None:
        self._running = False
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        self._tasks = []

    async def _loop_watcher(self) -> None:
        while self._running:
            try:
                await _watch_soft_brackets(self.db)
            except Exception as e:  # noqa: BLE001
                logger.exception("watcher loop crash: %s", e)
            await asyncio.sleep(WATCHER_INTERVAL)

    async def _loop_pnl(self) -> None:
        # Space out from watcher by a few seconds.
        await asyncio.sleep(10)
        while self._running:
            try:
                await _refresh_open_pnl(self.db)
                # v9.4.1 — After refreshing PnL, enforce daily loss limits.
                await _enforce_daily_loss_limit(self.db)
            except Exception as e:  # noqa: BLE001
                logger.exception("pnl loop crash: %s", e)
            await asyncio.sleep(60)  # unrealized PnL every 60s

    async def _loop_scanner(self) -> None:
        await asyncio.sleep(30)
        while self._running:
            try:
                await _run_full_auto_scanner(self.db, self.signal_fetcher)
            except Exception as e:  # noqa: BLE001
                logger.exception("scanner loop crash: %s", e)
            await asyncio.sleep(SCANNER_INTERVAL)
