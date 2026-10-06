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
from .engine import (
    TP_SPLITS,
    attach_brackets,
    close_position,
    close_position_partial,
    execute_trade,
    refresh_trade_pnl,
    resolve_credential,
)
from .exchanges import _build
from .whitelist import TOP_100_FUTURES, binance_symbol_filters, is_allowed, round_to_step
from . import binance_rest as br

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


async def _close_soft_trade(db: Any, trade: dict[str, Any], reason: str,
                            qty_to_close: float | None = None) -> dict[str, Any] | None:
    """Tutup posisi soft-bracket.

    v9.9.12 — qty_to_close=None → tutup SELURUH sisa posisi (SL / TP
    terakhir). Dengan qty_to_close → PARTIAL TP split (TP1 1/3, TP2 1/3,
    dst), konsisten dengan bracket native Binance. Sebelumnya watcher
    menutup 100% posisi di TP pertama — akar keluhan "profit kecil
    langsung tertutup semua sebelum TP2/TP3".
    """
    cred = await resolve_credential(
        db, trade["device_id"], trade["exchange"], bool(trade.get("testnet", True)))
    if not cred:
        return None
    qty_remaining = float(trade.get("qty_remaining") or trade.get("qty") or 0)
    qty = qty_remaining if qty_to_close is None else min(float(qty_to_close), qty_remaining)
    if qty <= 0:
        return None
    try:
        if qty_to_close is None:
            r = await close_position(cred, trade["symbol"], trade["side"], qty)
        else:
            r = await close_position_partial(
                cred, trade["symbol"], trade["side"], qty)
    except Exception as e:
        logger.warning("soft close failed %s: %s", trade.get("_id"), e)
        return None
    exit_px = float((r or {}).get("avg") or 0) or None
    entry = float(trade.get("entry_price") or 0)
    sign = 1.0 if trade["side"] == "BUY" else -1.0
    leg_pnl = ((exit_px or 0.0) - entry) * qty * sign if exit_px else 0.0
    acc = float(trade.get("soft_realized_pnl") or 0.0) + leg_pnl
    remaining = qty_remaining - qty
    full_close = qty_to_close is None or remaining <= 1e-12
    now = datetime.now(timezone.utc).isoformat()
    upd: dict[str, Any] = {
        "soft_realized_pnl": round(acc, 6),
        "qty_remaining": 0.0 if full_close else remaining,
        "updated_at": now,
    }
    if full_close:
        upd.update({
            "status": "closed",
            "closed_at": now,
            "close_reason": reason,
            "exit_price": exit_px,
            "closed_price": exit_px,
            "pnl_usdt": round(acc, 2),
        })
    await db.asi_trades.update_one({"_id": trade["_id"]}, {"$set": upd})
    logger.info("soft-bracket %s trade=%s reason=%s qty=%.8f pnl=%.2f",
                "closed" if full_close else "partial",
                trade.get("_id"), reason, qty, acc)
    return {"full": full_close, "remaining": remaining,
            "exit_px": exit_px, "acc": acc}


async def _watch_soft_brackets(db: Any) -> None:
    """One pass through all open soft-bracket trades.

    v9.9.12 — TP kini SPLIT per level mengikuti bobot TP_SPLITS (TP1 1/3,
    TP2 1/3, TP3 sisa), alih-alih menutup seluruh posisi di TP pertama.
    SL tetap menutup seluruh sisa posisi (prioritas keamanan).
    """
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
            # Check SL first (safety priority) — tutup seluruh sisa.
            sl = float(t.get("stop_loss") or 0)
            if sl and _is_hit(side, mark, sl, is_stop_loss=True):
                await _close_soft_trade(db, t, reason="SL")
                continue
            tps = [float(x) for x in (t.get("take_profits") or [])]
            n = len(tps)
            if n == 0:
                continue
            filled = list(t.get("tp_filled") or [])
            filled = (filled + [False] * n)[:n]
            orig_qty = float(t.get("qty") or 0)
            weights = TP_SPLITS.get(n, TP_SPLITS[3])
            # Step rounding untuk Binance supaya partial qty valid.
            step: float | None = None
            if (exchange or "").lower() == "binance":
                base = str(t.get("symbol") or "").upper().split("/")[0].split("USDT")[0].split("-")[0]
                try:
                    f = (await binance_symbol_filters() or {}).get(base) or {}
                    step = float(f.get("step") or 0) or None
                except Exception:
                    step = None
            for i, tp in enumerate(tps):
                if filled[i] or not _is_hit(side, mark, tp, is_stop_loss=False):
                    continue
                is_last_unfilled = all(filled[j] for j in range(i + 1, n))
                if is_last_unfilled:
                    res = await _close_soft_trade(db, t, reason=f"TP{i + 1}")
                else:
                    share = orig_qty * weights[i]
                    if step:
                        share = round_to_step(share, step)
                    if share <= 0:
                        filled[i] = True
                        continue
                    res = await _close_soft_trade(
                        db, t, reason=f"TP{i + 1}", qty_to_close=share)
                if res is None:
                    break  # eksekusi gagal — coba lagi di pass berikutnya
                filled[i] = True
                # v9.9.13 — FIX accounting (temuan testing agent): teruskan
                # qty_remaining & akumulasi PnL TERBARU ke snapshot lokal,
                # agar TP berikutnya yang ter-hit DI PASS YANG SAMA
                # (gap move) memakai angka fresh, bukan snapshot basi
                # dari awal pass (pnl_usdt sempat ter-overstate).
                t["qty_remaining"] = res.get("remaining", t.get("qty_remaining"))
                t["soft_realized_pnl"] = res.get("acc", t.get("soft_realized_pnl"))
                await db.asi_trades.update_one(
                    {"_id": t["_id"]}, {"$set": {"tp_filled": filled}})
                if res.get("full"):
                    break
        except Exception as e:  # noqa: BLE001
            logger.warning("watcher error on %s: %s", t.get("_id"), e)


async def _process_pending_entries(db: Any) -> None:
    """v9.9.13 — Pantau order LIMIT entry (status "pending_entry"):

    1. Order FILLED → pasang SL/TP bracket via engine.attach_brackets
       (sudah termasuk guard sisi TP + verifikasi openAlgoOrders). Untuk
       layer (layered=True) attach_brackets me-REBALANCE total posisi.
       Jika bracket gagal → posisi ditutup demi keamanan (kebijakan
       no-unprotected v9.9.2 tetap berlaku).
    2. Belum filled & melewati entry_expire_at (1 candle) → batalkan
       order limit, tandai "expired" (tidak pernah buka posisi).
    """
    cursor = db.asi_trades.find({"status": "pending_entry"})
    async for t in cursor:
        try:
            exchange = (t.get("exchange") or "").lower()
            if exchange != "binance":
                continue
            cred = await resolve_credential(
                db, t["device_id"], t["exchange"], bool(t.get("testnet", True)))
            if not cred:
                continue
            api_key = decrypt(cred["api_key_enc"])
            api_secret = decrypt(cred["api_secret_enc"])
            is_testnet = bool(cred.get("testnet", True))
            base = str(t.get("symbol") or "").upper().split("/")[0].split("USDT")[0].split("-")[0]
            bin_sym = base + "USDT"
            now = datetime.now(timezone.utc)

            filled = False
            try:
                st = await br.order_status(
                    api_key, api_secret, is_testnet,
                    symbol=bin_sym, order_id=t["entry_order_id"])
                filled = str(st.get("status")) == "FILLED"
            except Exception:
                pass

            if not filled:
                exp = str(t.get("entry_expire_at") or "")
                if not exp or now.isoformat() < exp:
                    continue  # masih menunggu pullback
                # Expired → batalkan order. Race guard: kalau ternyata
                # terisi tepat sebelum cancel, posisi akan terdeteksi.
                try:
                    await br.cancel_order(
                        api_key, api_secret, is_testnet,
                        symbol=bin_sym, order_id=t["entry_order_id"])
                except Exception:
                    pass
                try:
                    pos = await br.position_risk(api_key, api_secret, is_testnet, bin_sym)
                except Exception:
                    pos = None
                if pos and abs(float(pos.get("positionAmt") or 0)) > 0:
                    filled = True  # jatuh ke jalur attach di bawah
                else:
                    await db.asi_trades.update_one(
                        {"_id": t["_id"]},
                        {"$set": {
                            "status": "expired",
                            "close_reason": "entry_expired",
                            "closed_at": now.isoformat(),
                            "updated_at": now.isoformat(),
                        }},
                    )
                    logger.info("pending entry expired %s %s", t.get("_id"), bin_sym)
                    continue

            # FILLED → pasang bracket. attach_brackets membaca posisi live
            # & trade SL/TP (sudah ter-anchor ke harga limit).
            res = await attach_brackets(cred, dict(t))
            if res.get("ok"):
                upd = dict(res.get("update") or {})
                upd["status"] = "open"
                upd["updated_at"] = now.isoformat()
                try:
                    pos = await br.position_risk(api_key, api_secret, is_testnet, bin_sym)
                    if pos:
                        upd["entry_price"] = float(pos.get("entryPrice") or t.get("entry_price") or 0)
                        upd["qty"] = abs(float(pos.get("positionAmt") or t.get("qty") or 0))
                except Exception:
                    pass
                await db.asi_trades.update_one({"_id": t["_id"]}, {"$set": upd})
                # Layering: lebur row open lama pada simbol yang sama.
                if t.get("layered"):
                    old_rows = [
                        d async for d in db.asi_trades.find({
                            "device_id": t["device_id"], "exchange": t["exchange"],
                            "symbol": base, "status": "open",
                            "_id": {"$ne": t["_id"]},
                        })
                    ]
                    if old_rows:
                        await db.asi_trades.update_many(
                            {"_id": {"$in": [d["_id"] for d in old_rows]}},
                            {"$set": {
                                "status": "layered",
                                "close_reason": "merged_into_layer",
                                "merged_into": t["_id"],
                                "closed_at": now.isoformat(),
                                "updated_at": now.isoformat(),
                            }},
                        )
                        await db.asi_trades.update_one(
                            {"_id": t["_id"]},
                            {"$set": {"layer_count": len(old_rows) + 1}},
                        )
                logger.info("pending entry filled+bracketed %s %s", t.get("_id"), bin_sym)
            else:
                # Bracket gagal terpasang/terverifikasi → tutup posisi
                # demi keamanan (tidak boleh ada posisi tanpa proteksi).
                logger.warning("attach failed after fill %s: %s",
                               t.get("_id"), (res.get("errors") or [])[:2])
                try:
                    await close_position(cred, t["symbol"], t["side"],
                                         float(t.get("qty") or 0))
                except Exception as e:
                    logger.exception("close after attach failure %s: %s", t.get("_id"), e)
                await db.asi_trades.update_one(
                    {"_id": t["_id"]},
                    {"$set": {
                        "status": "closed",
                        "close_reason": "bracket_failed_after_fill",
                        "closed_at": now.isoformat(),
                        "updated_at": now.isoformat(),
                    }},
                )
        except Exception as e:  # noqa: BLE001
            logger.warning("pending entry error %s: %s", t.get("_id"), e)


async def _consolidate_duplicate_open(db: Any) -> None:
    """v9.9.10 — Row open GANDA untuk (device, simbol, exchange, jaringan)
    yang sama adalah warisan kode lama (Binance one-way mode hanya punya
    SATU posisi fisik). Gabungkan: row terbaru dipertahankan, sisanya
    ditandai 'layered' agar history rapi & PnL tidak tampil dobel."""
    groups: dict[tuple, list[dict[str, Any]]] = {}
    cursor = db.asi_trades.find({"status": "open"})
    async for t in cursor:
        key = (t.get("device_id"), t.get("symbol"), t.get("exchange"),
               bool(t.get("testnet", True)))
        groups.setdefault(key, []).append(t)
    now = datetime.now(timezone.utc).isoformat()
    for rows in groups.values():
        if len(rows) <= 1:
            continue
        rows.sort(key=lambda r: r.get("created_at") or "")
        keep = rows[-1]
        try:
            await db.asi_trades.update_many(
                {"_id": {"$in": [r["_id"] for r in rows[:-1]]}},
                {"$set": {
                    "status": "layered", "close_reason": "merged_duplicate",
                    "merged_into": keep["_id"],
                    "closed_at": now, "updated_at": now,
                }},
            )
            logger.info("consolidated %d duplicate open rows into %s",
                        len(rows) - 1, keep["_id"])
        except Exception as e:
            logger.warning("consolidate failed %s: %s", key, e)


async def _refresh_open_pnl(db: Any) -> None:
    """Keep unrealized PnL fresh for all open trades (hard & soft)."""
    await _consolidate_duplicate_open(db)
    cursor = db.asi_trades.find({"status": "open"})
    async for t in cursor:
        try:
            cred = await resolve_credential(
                db, t["device_id"], t["exchange"], bool(t.get("testnet", True)))
            if not cred:
                continue
            upd = await refresh_trade_pnl(cred, t)
            upd["updated_at"] = datetime.now(timezone.utc).isoformat()
            await db.asi_trades.update_one({"_id": t["_id"]}, {"$set": upd})
        except Exception as e:  # noqa: BLE001
            logger.debug("pnl refresh %s: %s", t.get("_id"), e)


async def _trades_today_count(db: Any, device_id: str,
                              testnet: bool | None = None) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    # v9.9.5 — kuota harian dihitung per jaringan aktif: trade demo tidak
    # memakan kuota mainnet dan sebaliknya.
    q: dict[str, Any] = {"device_id": device_id, "created_at": {"$gte": cutoff}}
    if testnet is not None:
        q["testnet"] = bool(testnet)
    return await db.asi_trades.count_documents(q)


async def _realized_pnl_today(db: Any, device_id: str) -> float:
    """Sum of pnl_usdt for CLOSED trades in the last 24h (realized loss/gain)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    pipeline = [
        # v9.9.5 — daily loss limit hanya menghitung trade REAL (demo
        # testnet tidak boleh memicu auto-disable bot real).
        {"$match": {
            "device_id": device_id, "status": "closed",
            "closed_at": {"$gte": cutoff},
            "testnet": {"$ne": True},
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
        "$or": [{"enabled": True}, {"full_enabled": True}],
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
    # v9.7.6 — Semi & Full are independent toggles now. Scheduler only
    # cares about `full_enabled=True` (background scanner). `semi_enabled`
    # is a UI gate for 1-tap manual executes and does NOT trigger scans.
    # Fallback to legacy single flag `{enabled: True, mode: "full"}` for
    # pre-v9.7.6 docs that have not been resaved yet.
    cursor = db.asi_bot_config.find({
        "$or": [
            {"full_enabled": True},
            {"enabled": True, "mode": "full",
             "full_enabled": {"$exists": False}},
        ],
    })
    async for cfg in cursor:
        try:
            device_id = cfg.get("device_id") or cfg.get("_id")
            if not device_id:
                continue
            max_tr = int(cfg.get("max_trades_per_day") or 5)
            # v9.9.5 — network aktif ditentukan lebih awal supaya kuota
            # harian juga dihitung per jaringan.
            net = bool(cfg["active_testnet"]) if "active_testnet" in cfg else None
            placed = await _trades_today_count(db, device_id, net)
            if placed >= max_tr:
                continue
            # v9.7.3 — BUG FIX: empty whitelist silently disabled the bot
            # ("ACTIVE" tapi tidak pernah scan). Default ke Top-100 futures
            # agar Full-Auto langsung bekerja tanpa konfigurasi tambahan.
            whitelist = cfg.get("whitelist") or list(TOP_100_FUTURES)
            if not whitelist:
                continue
            exchange = cfg.get("exchange") or "binance"
            # v9.9.5 — Full-Auto memakai credential sesuai switch jaringan
            # aktif (active_testnet). Config lama tanpa field ini → None =
            # perilaku lama (credential apa pun yang tersedia).
            cred = await resolve_credential(db, device_id, exchange, net)
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
                # Guard: skip if an OPEN/pending trade on same symbol exists.
                dup = await db.asi_trades.find_one(
                    {"device_id": device_id, "symbol": sym,
                     "status": {"$in": ["open", "pending_entry"]}}
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
                        margin_mode=str(cfg.get("margin_mode") or "isolated"),
                        profile=bot_profile,
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
                # v9.9.13 — pantau order LIMIT entry (fill → bracket,
                # expired → cancel).
                await _process_pending_entries(self.db)
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
