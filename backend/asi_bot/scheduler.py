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
    move_sl_to_breakeven,
    refresh_trade_pnl,
    resolve_credential,
)
from .exchanges import _build
from .whitelist import TOP_50_FUTURES, TOP_100_FUTURES, binance_symbol_filters, is_allowed, round_to_step
from . import binance_rest as br

logger = logging.getLogger("asi_bot.scheduler")

# Tunables (seconds).
WATCHER_INTERVAL = 20
# v10.1.1 — Scanner dipercepat 300s → 90s (keputusan user: Full-Auto
# tidak eksekusi padahal AI Suggestions sudah penuh sinyal; selisih
# 5 menit terlalu lama). 90s cukup untuk tetap aman rate-limit API.
SCANNER_INTERVAL = 90
TITAN_RELAY_INTERVAL = 25  # v10.0.15 — polling posisi master Titan-Bot
# v10.2.6 — Panic Market Guard interval (BTC+ETH monitor tiap 2 menit).
PANIC_INTERVAL = 120
# Minimum confidence required for full-auto execution.
MIN_FULL_AUTO_CONFIDENCE = 90


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
    # v10.0.13 — Fix label bug: watcher memicu "TPx" tapi harga fill
    # ternyata di sisi loss (slippage/wick/stale ticker). Relabel ke
    # "SL" supaya tp_fills + close_reason mencerminkan hasil nyata,
    # bukan intensi trigger. SL/manual tetap pakai reason asli.
    effective_reason = reason
    if (exit_px and reason and reason.startswith("TP")
            and leg_pnl < 0):
        effective_reason = "SL"
    acc = float(trade.get("soft_realized_pnl") or 0.0) + leg_pnl
    remaining = qty_remaining - qty
    full_close = qty_to_close is None or remaining <= 1e-12
    now = datetime.now(timezone.utc).isoformat()
    upd: dict[str, Any] = {
        "soft_realized_pnl": round(acc, 6),
        "qty_remaining": 0.0 if full_close else remaining,
        "updated_at": now,
    }
    # v10.0.13 — Rekam harga setiap TP hit (atau SL). Dipakai UI untuk
    # menampilkan "TP1 hit · $xxx", "TP2 hit · $xxx" per baris trade. SL
    # dan close terakhir juga ikut ter-rekam. Pakai `effective_reason`
    # agar label TPx tidak dicatat ketika fill ternyata loss.
    if exit_px:
        tp_fills = list(trade.get("tp_fills") or [])
        tp_fills.append({
            "level": effective_reason,  # "TP1" / "TP2" / "TP3" / "SL"
            "price": round(exit_px, 8),
            "qty": round(qty, 10),
            "pnl": round(leg_pnl, 4),
            "at": now,
        })
        upd["tp_fills"] = tp_fills
    if full_close:
        upd.update({
            "status": "closed",
            "closed_at": now,
            "close_reason": effective_reason,
            "exit_price": exit_px,
            "closed_price": exit_px,
            "pnl_usdt": round(acc, 2),
        })
    await db.asi_trades.update_one({"_id": trade["_id"]}, {"$set": upd})
    logger.info("soft-bracket %s trade=%s reason=%s (eff=%s) qty=%.8f pnl=%.2f",
                "closed" if full_close else "partial",
                trade.get("_id"), reason, effective_reason, qty, acc)
    return {"full": full_close, "remaining": remaining,
            "exit_px": exit_px, "acc": acc,
            "effective_reason": effective_reason}


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
                # v10.0.16 — SL GUARD: setiap partial TP ter-isi, SL geser
                # ke harga TP yang baru hit (TP1→SL=TP1, TP2→SL=TP2).
                # Menggantikan logika BE lama (SL=entry) — lebih agresif
                # mengamankan profit. Hanya untuk partial (bukan full close),
                # tidak double (sl_guard_idx), dan skip bila trailing aktif.
                # Guard arah: SL baru harus LEBIH BAIK dari SL lama.
                if (not res.get("full")
                        and int(t.get("sl_guard_idx") or 0) <= i
                        and res.get("effective_reason") != "SL"
                        and float(t.get("trailing_callback_rate") or 0) <= 0):
                    cur_sl = float(t.get("stop_loss") or 0)
                    new_sl = float(tp)
                    better = (new_sl > cur_sl) if side == "BUY" else (new_sl < cur_sl or cur_sl == 0)
                    if better:
                        cred_sg = await resolve_credential(
                            db, t["device_id"], t["exchange"],
                            bool(t.get("testnet", True)))
                        if cred_sg:
                            try:
                                sg_res = await move_sl_to_breakeven(
                                    cred_sg, t, target_price=new_sl)
                            except Exception as _e:  # noqa: BLE001
                                sg_res = {"ok": False, "detail": str(_e)[:200]}
                            sg_upd: dict[str, Any] = {
                                "sl_guard_idx": i + 1,
                                "sl_guard_detail": sg_res.get("detail"),
                                "be_moved": True,  # kompat UI badge lama
                            }
                            if sg_res.get("ok") and sg_res.get("new_sl"):
                                sg_upd["stop_loss"] = float(sg_res["new_sl"])
                                t["stop_loss"] = float(sg_res["new_sl"])
                            else:
                                # Native gagal → tetap guard via soft watcher.
                                t["stop_loss"] = new_sl
                                sg_upd["stop_loss"] = new_sl
                            await db.asi_trades.update_one(
                                {"_id": t["_id"]}, {"$set": sg_upd})
                            logger.info(
                                "SL guard trade=%s tp_idx=%d ok=%s new_sl=%s",
                                t.get("_id"), i, sg_res.get("ok"),
                                sg_upd.get("stop_loss"))
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
    now = datetime.now(timezone.utc)
    cursor = db.asi_trades.find({"status": "open"})
    async for t in cursor:
        try:
            cred = await resolve_credential(
                db, t["device_id"], t["exchange"], bool(t.get("testnet", True)))
            if not cred:
                # v10.0.6 — ORPHAN SWEEPER: trade open milik device yang
                # credential-nya sudah tidak ada (mis. user reinstall dan
                # credential yatim di device lama) tidak bisa direconcile
                # ke Binance. Bila sudah > 1 jam tidak tersentuh, tandai
                # "orphaned" agar tidak tampil selamanya sebagai posisi
                # open phantom di leaderboard. Data PnL terakhir dipertahankan;
                # bila user reconnect API key yang sama, migrasi history
                # akan memulihkan trade ini ke device barunya.
                try:
                    last = datetime.fromisoformat(
                        str(t.get("updated_at") or t.get("created_at")).replace("Z", "+00:00"))
                except Exception:
                    last = now
                age_s = (now - last).total_seconds()
                if age_s > 3600:
                    await db.asi_trades.update_one(
                        {"_id": t["_id"]},
                        {"$set": {"status": "orphaned",
                                  "close_reason": "orphaned_no_credential",
                                  "updated_at": now.isoformat()}})
                    logger.warning(
                        "orphaned open trade %s (%s %s) — no credential for device",
                        t.get("_id"), t.get("symbol"), t.get("side"))
                continue
            upd = await refresh_trade_pnl(cred, t)
            upd["updated_at"] = now.isoformat()
            await db.asi_trades.update_one({"_id": t["_id"]}, {"$set": upd})
        except Exception as e:  # noqa: BLE001
            # v10.0.6 — warning (bukan debug) supaya kegagalan reconcile
            # terlihat di log produksi.
            logger.warning("pnl refresh %s gagal: %s", t.get("_id"), e)


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
    # v10.1.2 — Audit counters untuk statistik scan (lihat asi_scan_status).
    scanned = 0
    sigs_found = 0
    total_placed = 0
    # v10.2.5 — CIRCUIT BREAKER MARKET-WIDE (permintaan user setelah
    # analisis loss 15/10 pagi: 10 LONG SL beruntun saat market dump).
    # Bila BTC bergerak ekstrem > 2% dalam 1 jam terakhir, Full-Auto
    # berhenti membuka posisi ke arah yang MELAWAN gerakan itu:
    #   dump tajam → semua entry LONG diblokir siklus ini
    #   pump tajam → semua entry SHORT diblokir siklus ini
    # Cooldown per-simbol tidak bisa menangani koreksi market serentak;
    # guard ini bekerja di level portofolio.
    cb_block_long = False
    cb_block_short = False
    try:
        from market_data import get_crypto_snapshot as _gcs
        _btc = await _gcs("BTC", "1h")
        _bc = [float(c["close"]) for c in ((_btc or {}).get("candles") or []) if c.get("close")]
        if len(_bc) >= 2 and _bc[-2] > 0:
            _chg1h = (_bc[-1] - _bc[-2]) / _bc[-2] * 100.0
            if _chg1h <= -2.0:
                cb_block_long = True
                logger.warning("circuit-breaker: BTC %.2f%%/1h → semua entry LONG diblokir siklus ini", _chg1h)
            elif _chg1h >= 2.0:
                cb_block_short = True
                logger.warning("circuit-breaker: BTC +%.2f%%/1h → semua entry SHORT diblokir siklus ini", _chg1h)
    except Exception as _cb_err:
        logger.debug("circuit-breaker check gagal (skip, fail-open): %s", _cb_err)
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
            # v10.0.14 — Hormati signal_source: "cloud_pro" HANYA menerima
            # sinyal dari webhook /asi/webhook/cloud, scanner internal
            # di-skip. "hybrid" menerima dari KEDUA sumber (scanner tetap
            # jalan). "asi_bot" (default) → scanner internal saja.
            if (cfg.get("signal_source") or "asi_bot") == "cloud_pro":
                continue
            # v10.2.6 — PANIC GUARD: skip user yang sedang panic_active
            # (cooldown panic market). Scanner tidak membuka posisi baru
            # sampai _run_panic_guard melepas cooldown (BTC/ETH neutral
            # atau reversal pattern terdeteksi).
            if cfg.get("panic_active"):
                continue
            scanned += 1
            max_tr = int(cfg.get("max_trades_per_day") or 3)
            # v9.9.5 — network aktif ditentukan lebih awal supaya kuota
            # harian juga dihitung per jaringan.
            net = bool(cfg["active_testnet"]) if "active_testnet" in cfg else None
            placed = await _trades_today_count(db, device_id, net)
            if placed >= max_tr:
                continue
            # v10.2.5 — LOSS-STREAK BREAKER: bila 3 trade terakhir yang
            # closed SEMUANYA kena SL dan SL terbaru < 2 jam lalu, bot
            # istirahat dulu (skip siklus ini). Mencegah loss beruntun
            # membesar seperti pagi 15/10 (-$150 dalam satu sesi dump).
            try:
                _recent_closed = [
                    t async for t in db.asi_trades.find(
                        {"device_id": device_id, "status": "closed"}
                    ).sort("closed_at", -1).limit(3)
                ]
                if len(_recent_closed) == 3 and all(
                    t.get("close_reason") == "SL" for t in _recent_closed
                ):
                    _cutoff = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
                    if str(_recent_closed[0].get("closed_at") or "") > _cutoff:
                        logger.warning(
                            "loss-streak breaker: %s 3 SL beruntun <2 jam → istirahat siklus ini",
                            device_id)
                        continue
            except Exception as _ls_err:
                logger.debug("loss-streak check gagal (skip, fail-open): %s", _ls_err)
            # v9.7.3 — BUG FIX: empty whitelist silently disabled the bot
            # ("ACTIVE" tapi tidak pernah scan). Default ke Top-100 futures
            # agar Full-Auto langsung bekerja tanpa konfigurasi tambahan.
            # v10.0.16 — FULL-AUTO kembali scan Top-100 (keputusan user,
            # sebelumnya Top-50). Semi-Auto tetap bebas semua aset.
            whitelist = cfg.get("whitelist") or list(TOP_100_FUTURES)
            whitelist = [s for s in whitelist if s in TOP_100_FUTURES]
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
            # v10.0.16 — Bot MENGIKUTI Trader Profile pilihan user
            # (scalper/day/swing/longterm). Legacy "confluence" (default
            # lama saat user belum memilih) dipetakan ke None → dashboard
            # default gate 5 (gaya v5.1.8). "longterm" = Confluence v9
            # gate 8 (ketat, hanya bila user eksplisit memilihnya).
            bot_profile = cfg.get("profile") or None
            if bot_profile == "confluence":
                bot_profile = None
            budget = max_tr - placed
            # v10.1.2 — MULTI-PROFILE SCAN (keputusan user): sinyal
            # executable yang muncul di AI Suggestions dari MANA PUN
            # (Scalper / Intraday / Swing / Confluence v9) harus langsung
            # memicu eksekusi Full-Auto, tanpa dibatasi 1 profile dan
            # tanpa filter tambahan. Keempat engine dievaluasi PARALEL
            # per koin; sinyal dengan confidence tertinggi yang lolos
            # threshold user yang dipakai.
            # v10.1.7 — ENGINE SELECTION per Trader Profile (keputusan user):
            #   • Profile = longterm (Confluence v9) → scan HANYA engine
            #     `longterm`. Ini engine full-EMA200 gate, paling konservatif,
            #     tidak pernah counter-trend. Cocok untuk Full-Auto harian.
            #   • Profile = scalper / day / swing → scan KETIGA engine
            #     {scalper, day, swing} sekaligus (ambil confidence
            #     tertinggi). Engine `longterm` TIDAK ikut supaya tidak
            #     konflik dengan pilihan user yang mau trading cepat.
            #   • Default (belum pilih) → aman: hanya `longterm` (Confluence v9).
            if bot_profile in ("scalper", "day", "swing"):
                _ENGINES = ["scalper", "day", "swing"]
            else:
                # longterm / None / "confluence" → 1 engine saja.
                _ENGINES = ["longterm"]
            async def _fetch_signal(s: str, p: str) -> dict[str, Any] | None:
                try:
                    return await signal_fetcher("crypto", s, p)
                except Exception:
                    return None
            # v10.1.2 — FIX BUG UNIVERSE TERPOTONG: slice `[: budget*3]`
            # membuat scanner hanya melihat ±57 koin pertama; sinyal valid
            # di koin urutan belakang (mis. ONDO #84) tidak pernah dievaluasi.
            # Sekarang scan SELURUH whitelist; loop berhenti sendiri saat
            # kuota harian habis (break di dalam).
            for sym in whitelist:
                if not is_allowed(sym):
                    continue
                try:
                    results = await asyncio.gather(
                        *[_fetch_signal(sym, p) for p in _ENGINES],
                        return_exceptions=True,
                    )
                except Exception:
                    continue
                best = None
                for sig in results:
                    if not isinstance(sig, dict) or not sig.get("side"):
                        continue
                    # v10.1.8 — Skip sinyal late-entry (lolos gate tampilan
                    # longgar tapi gagal gate eksekusi ketat 3-candle/1.5ATR).
                    if sig.get("late_entry"):
                        continue
                    # v10.2.5 — CIRCUIT BREAKER: blokir arah yang melawan
                    # gerakan ekstrem BTC (>2%/1h). Dihitung sekali per
                    # siklus di atas.
                    if sig["side"] == "BUY" and cb_block_long:
                        continue
                    if sig["side"] == "SELL" and cb_block_short:
                        continue
                    if int(sig.get("confidence") or 0) < user_min_conf:
                        continue
                    sigs_found += 1
                    if best is None or int(sig.get("confidence") or 0) > int(best.get("confidence") or 0):
                        best = sig
                if not best:
                    continue
                sig = best
                # v10.1.2 — GUARD LEVEL: jangan pernah eksekusi sinyal
                # tanpa level valid (bug: ada trade tersimpan dgn
                # entry_price=0.0). Skip & log supaya tidak jadi black box.
                try:
                    _entry = float(sig.get("entry") or 0)
                    _sl = float(sig.get("stop_loss") or 0)
                    _tps = [float(x) for x in sig.get("take_profits") or [] if float(x) > 0]
                except Exception:
                    continue
                if _entry <= 0 or _sl <= 0 or not _tps:
                    logger.info("full-auto skip %s/%s: level tidak valid (entry=%s sl=%s tps=%s)",
                                device_id, sym, sig.get("entry"), sig.get("stop_loss"),
                                sig.get("take_profits"))
                    continue
                # Guard: skip if an OPEN/pending trade on same symbol exists.
                dup = await db.asi_trades.find_one(
                    {"device_id": device_id, "symbol": sym,
                     "status": {"$in": ["open", "pending_entry"]}}
                )
                if dup:
                    continue
                # v10.1.7 — COOLDOWN 15 MENIT per-symbol (anti-flood):
                # Setelah close/cancel, symbol yang sama TIDAK boleh
                # re-execute dalam 15 menit. Mencegah pola yang user
                # keluhkan: AVAX SHORT dijalankan berulang di harga sama,
                # kena SL berulang → loss beruntun. Beri waktu market
                # settle sebelum coba lagi dengan sinyal fresh.
                cutoff_cooldown = (datetime.now(timezone.utc)
                                   - timedelta(minutes=15)).isoformat()
                recent = await db.asi_trades.find_one({
                    "device_id": device_id, "symbol": sym,
                    "status": {"$in": ["closed", "cancelled", "expired",
                                       "orphaned"]},
                    "updated_at": {"$gt": cutoff_cooldown},
                })
                if recent:
                    logger.info("full-auto cooldown skip %s/%s: ditutup "
                                "dalam 15 menit terakhir", device_id, sym)
                    continue
                # v10.2.5 — TREND FILTER 4H DIPERTAJAM (permintaan user):
                # bukan lagi sekadar posisi harga vs EMA50, tapi juga ARAH/
                # SLOPE EMA50. "Saat EMA50 menurun, LONG dilarang walau
                # harga sesaat di atasnya" — mencegah bounce-trap LONG di
                # tengah dump seperti pagi 15/10.
                #   LONG  wajib: harga > EMA50  DAN  EMA50 tidak menurun
                #   SHORT wajib: harga < EMA50  DAN  EMA50 tidak menaik
                try:
                    from indicators import _ema  # noqa
                    from market_data import get_crypto_snapshot
                    snap4h = await get_crypto_snapshot(sym, "4h")
                    cands = (snap4h or {}).get("candles") or []
                    closes_4h = [float(c["close"]) for c in cands
                                 if c.get("close")]
                    if len(closes_4h) >= 54:
                        ema_series = _ema(closes_4h, 50)
                        ema50_4h = ema_series[-1] if ema_series else 0.0
                        ema50_prev = ema_series[-4] if len(ema_series) >= 4 else ema50_4h
                        last_price = closes_4h[-1]
                        bias_up = last_price > ema50_4h
                        slope_up = ema50_4h > ema50_prev
                        slope_dn = ema50_4h < ema50_prev
                        want_long = sig["side"] == "BUY"
                        if want_long and (not bias_up or slope_dn):
                            logger.info("full-auto trend-filter skip %s/%s: "
                                        "LONG ditolak (price%sEMA50 %.4f, slope %s)",
                                        device_id, sym,
                                        ">" if bias_up else "<", ema50_4h,
                                        "turun" if slope_dn else "naik/datar")
                            continue
                        if not want_long and (bias_up or slope_up):
                            logger.info("full-auto trend-filter skip %s/%s: "
                                        "SHORT ditolak (price%sEMA50 %.4f, slope %s)",
                                        device_id, sym,
                                        ">" if bias_up else "<", ema50_4h,
                                        "naik" if slope_up else "turun/datar")
                            continue
                except Exception as _tf_err:
                    logger.debug("trend-filter error %s: %s", sym, _tf_err)
                # v10.1.2 — ANTI-DUPLIKAT ATOMIK (root cause "2 trade TRX
                # identik"): dua proses scanner (multi-replica / restart)
                # bisa sama-sama lolos dup-check lalu sama-sama eksekusi.
                # Solusinya klaim slot DULU per (device, symbol) SEBELUM
                # eksekusi — proses kedua gagal klaim dan otomatis skip.
                # v10.1.6 — Klaim dipindah ke collection KHUSUS
                # `asi_scan_claims` dan dilepas secara SOFT (status→
                # "released"), BUKAN delete dari asi_trades. Sesuai
                # deployment policy: tidak ada hard-delete record MongoDB di
                # alur scheduler startup. Record klaim dipertahankan sebagai
                # audit; satu doc per (device,symbol) di-reuse (tidak
                # menumpuk).
                slot_id = f"{device_id}:{sym}"
                now_dt = datetime.now(timezone.utc)
                now_claim = now_dt.isoformat()

                async def _release_claim() -> None:
                    await db.asi_scan_claims.update_one(
                        {"_id": slot_id},
                        {"$set": {"status": "released", "released_at":
                                  datetime.now(timezone.utc).isoformat()}},
                    )

                claimed = False
                try:
                    await db.asi_scan_claims.insert_one({
                        "_id": slot_id, "device_id": device_id,
                        "symbol": sym, "side": sig["side"],
                        "status": "active",
                        "created_at": now_claim, "updated_at": now_claim,
                    })
                    claimed = True
                except Exception:
                    # Sudah ada klaim → ambil alih bila released / basi
                    # (>5 menit, proses mati di tengah jalan).
                    cur = await db.asi_scan_claims.find_one({"_id": slot_id})
                    reusable = False
                    if cur:
                        if cur.get("status") != "active":
                            reusable = True
                        else:
                            up = str(cur.get("updated_at") or "")
                            try:
                                reusable = (now_dt - datetime.fromisoformat(up)
                                            ).total_seconds() > 300
                            except Exception:
                                reusable = False
                    if reusable:
                        r = await db.asi_scan_claims.update_one(
                            {"_id": slot_id},
                            {"$set": {"device_id": device_id, "symbol": sym,
                                      "side": sig["side"], "status": "active",
                                      "updated_at": now_claim}})
                        claimed = r.matched_count > 0
                if not claimed:
                    continue
                try:
                    res = await execute_trade(
                        cred, sym, sig["side"],
                        _entry, _sl, _tps,
                        risk, lev, mode="full",
                        tp_count=int(cfg.get("tp_count") or 3),
                        trailing_callback_rate=float(cfg.get("trailing_callback_rate") or 0.0),
                        margin_mode=str(cfg.get("margin_mode") or "isolated"),
                        # v10.1.2 — Rekam ENGINE yang menghasilkan sinyal
                        # (bukan profile config user) agar statistik WR
                        # per profile & label kartu akurat.
                        profile=sig.get("profile") or bot_profile,
                        formula_tag=sig.get("formula_tag"),
                        entry_mode=str(cfg.get("entry_mode") or "limit"),
                    )
                except Exception as e:
                    logger.warning("full-auto execute failed %s/%s: %s", device_id, sym, e)
                    await _release_claim()
                    continue
                if not res.get("ok"):
                    # v10.1.2 — Log alasan skip supaya tidak jadi black box.
                    logger.info("full-auto skip %s/%s: %s | %s", device_id, sym,
                                res.get("reason"), str(res.get("message") or "")[:120])
                    await _release_claim()
                    continue
                # v10.1.2 — GUARD: jangan simpan record tanpa fill nyata
                # (entry_price 0 = order gagal tapi ok=True). Lepas slot.
                if float(res.get("entry_price") or 0) <= 0 \
                        and res.get("status") != "pending_entry":
                    logger.warning("full-auto drop %s/%s: entry_price=0 pada res ok", device_id, sym)
                    await _release_claim()
                    continue
                margin_usdt = round(
                    float(res["qty"]) * float(res["entry_price"])
                    / max(1, int(res["leverage"])), 2,
                )
                rec = {**res, "device_id": device_id, "margin_usdt": margin_usdt}
                # v10.1.2 — SELALU simpan record walau entry_order_id kosong
                # (bug lama: trade tereksekusi di Binance tapi tak pernah
                # masuk DB → user mengira bot tidak eksekusi). Fallback _id
                # memakai timestamp supaya tetap unik. Slot klaim lalu
                # dilepas supaya bisa dipakai trade berikutnya.
                oid = res.get("entry_order_id")
                rec["_id"] = (f"{device_id}:{oid}" if oid
                              else f"{device_id}:auto:{res.get('created_at')}")
                await db.asi_trades.replace_one(
                    {"_id": rec["_id"]}, rec, upsert=True)
                await _release_claim()
                placed += 1
                total_placed += 1
                logger.info("full-auto placed %s %s %s", device_id, sym, sig["side"])
                if placed >= max_tr:
                    break
        except Exception as e:  # noqa: BLE001
            logger.warning("full-auto scan error: %s", e)
    # v10.1.2 — Audit trail: simpan statistik scan terakhir supaya user/
    # admin bisa cek "kapan bot terakhir jalan & kenapa tidak eksekusi"
    # via GET /asi/bot/status.
    try:
        await db.asi_scan_status.replace_one(
            {"_id": "scanner"},
            {"_id": "scanner",
             "last_scan_at": datetime.now(timezone.utc).isoformat(),
             "devices_scanned": scanned,
             "signals_found": sigs_found,
             "placed": total_placed},
            upsert=True)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# v10.0.15 — TITAN RELAY (Cara 1)
# WunderTrading mengeksekusi bot di akun Binance MASTER → scheduler ini membaca
# posisi master tiap ~25 detik → setiap posisi BARU direplikasi (fan-out) ke
# semua user Full-Auto yang memilih engine "Titan-Bot" (signal_source="cloud_pro").
#
# Aturan:
#  • Entry  = harga mark SAAT INI (market mode) — tidak memakai harga entry
#    historis master supaya user tidak masuk di harga basi.
#  • SL/TP  = disalin PERSIS dari bracket master (openAlgoOrders / legacy).
#    Jika master tidak punya SL → SKIP (tidak boleh open posisi tanpa proteksi
#    di akun user).
#  • Risk %, leverage, margin mode → tetap dari setting masing-masing user.
#  • Dedup  = collection `asi_titan_state` melacak posisi master yang sudah
#    pernah direlay (key = symbol:side).
#  • Master CLOSED → TIDAK force-close user; bracket SL/TP native masing-masing
#    user yang bekerja (sesuai pilihan aman default).
# ─────────────────────────────────────────────────────────────────────────────
async def _run_titan_relay(db: Any) -> None:
    cfg = await db.asi_titan_config.find_one({"_id": "titan_master", "enabled": True})
    if not cfg:
        return  # relay belum dikonfigurasi
    api_key = decrypt(cfg["api_key_enc"])
    api_secret = decrypt(cfg["api_secret_enc"])
    testnet = bool(cfg.get("testnet", False))
    try:
        positions = await br.all_position_risks(api_key, api_secret, testnet)
    except Exception as e:
        logger.warning("titan relay: master positionRisk gagal: %s", e)
        return
    if not positions:
        # Master flat → nonaktifkan state lama supaya entry baru bisa
        # direlay. v10.1.6 — SOFT-disable (bukan hard delete) sesuai
        # deployment policy: scheduler startup tidak boleh menghapus
        # record MongoDB secara otomatis. Record dipertahankan.
        await db.asi_titan_state.update_many({}, {"$set": {"active": False}})
        return
    # User target: Full-Auto ON + engine Titan-Bot (cloud_pro).
    users = await db.asi_bot_config.find({
        "full_enabled": True, "signal_source": "cloud_pro",
    }).to_list(200)
    if not users:
        return

    for p in positions:
        try:
            amt = float(p.get("positionAmt") or 0)
            if abs(amt) <= 0:
                continue
            symbol_raw = str(p.get("symbol") or "").upper()  # e.g. "BTCUSDT"
            base = symbol_raw.replace("USDT", "")
            if not base:
                continue
            side: str = "BUY" if amt > 0 else "SELL"
            state_key = f"{base}:{side}"
            # Dedup: posisi master ini sudah pernah direlay?
            # v10.1.6 — Hanya state AKTIF yang menghalangi relay ulang
            # (state lama di-soft-disable saat posisi tutup / master flat).
            state = await db.asi_titan_state.find_one(
                {"_id": state_key, "active": {"$ne": False}})
            if state:
                continue  # posisi lama — biarkan bracket user bekerja
            # Baca bracket SL/TP master dari Algo Orders (+ legacy fallback).
            sl_price: float | None = None
            tps: list[float] = []
            close_side = "SELL" if side == "BUY" else "BUY"
            try:
                algos = await br.open_algo_orders(
                    api_key, api_secret, testnet, symbol_raw)
            except Exception:
                algos = []
            for a in algos or []:
                if a.get("side") != close_side:
                    continue
                trig = float(a.get("triggerPrice") or 0)
                if not trig:
                    continue
                otype = a.get("orderType") or ""
                if otype == "STOP_MARKET" and sl_price is None:
                    sl_price = trig
                elif otype == "TAKE_PROFIT_MARKET":
                    tps.append(trig)
            if sl_price is None or not tps:
                try:
                    legacy = await br.open_orders_legacy(
                        api_key, api_secret, testnet, symbol_raw)
                except Exception:
                    legacy = []
                for o in legacy or []:
                    if o.get("side") != close_side:
                        continue
                    trig = float(o.get("stopPrice") or 0)
                    if not trig:
                        continue
                    otype = str(o.get("type") or "")
                    if otype.startswith("STOP") and sl_price is None:
                        sl_price = trig
                    elif otype.startswith("TAKE_PROFIT"):
                        tps.append(trig)
            if sl_price is None:
                logger.warning("titan relay: %s %s master tanpa SL — SKIP",
                               base, side)
                continue
            if not tps:
                # Fallback aman: TP1 sederhana 1R dari entry master.
                entry_m = float(p.get("entryPrice") or 0)
                if not entry_m:
                    continue
                dist = abs(entry_m - sl_price)
                tps = [entry_m + dist if side == "BUY" else entry_m - dist]
            tps = sorted(set(round(float(x), 8) for x in tps if x > 0))[:3]
            tps = [x for x in tps if (x > sl_price if side == "BUY" else x < sl_price)]
            if not tps:
                continue
            mark = float(p.get("markPrice") or 0)
            if not mark:
                continue
            now = datetime.now(timezone.utc).isoformat()
            # Fan-out ke setiap user Titan-Bot.
            for u in users:
                dev = u.get("device_id") or u.get("_id")
                if not dev:
                    continue
                try:
                    dup = await db.asi_trades.find_one(
                        {"device_id": dev, "symbol": base,
                         "status": {"$in": ["open", "pending_entry"]}})
                    if dup:
                        continue
                    net = bool(u["active_testnet"]) if "active_testnet" in u else None
                    exchange = u.get("exchange") or "binance"
                    cred = await resolve_credential(db, dev, exchange, net)
                    if not cred:
                        continue
                    res = await execute_trade(
                        cred, base, side,
                        mark, sl_price, tps,
                        float(u.get("risk_pct") or 5.0),
                        int(u.get("leverage") or 10),
                        mode="full",
                        tp_count=int(u.get("tp_count") or 3),
                        trailing_callback_rate=float(u.get("trailing_callback_rate") or 0.0),
                        margin_mode=str(u.get("margin_mode") or "isolated"),
                        profile=None,
                        formula_tag="Titan-Bot",
                        entry_mode="market",  # relay selalu market (follow master)
                    )
                    if not res.get("ok"):
                        continue
                    margin_usdt = round(
                        float(res["qty"]) * float(res["entry_price"])
                        / max(1, int(res["leverage"])), 2)
                    rec = {**res, "device_id": dev, "margin_usdt": margin_usdt,
                           "signal_source": "cloud_pro",
                           "formula_tag": "Titan-Bot",
                           "titan_master_entry": float(p.get("entryPrice") or 0)}
                    if res.get("entry_order_id"):
                        rec["_id"] = f"{dev}:{res['entry_order_id']}"
                        await db.asi_trades.replace_one(
                            {"_id": rec["_id"]}, rec, upsert=True)
                    logger.info("titan relay: %s %s fanned out to %s",
                                side, base, dev)
                except Exception as e:  # noqa: BLE001
                    logger.warning("titan relay fan-out %s %s: %s", dev, base, e)
                    continue
            # Tandai posisi master sudah direlay supaya tidak di-retry
            # tiap siklus.
            await db.asi_titan_state.replace_one(
                {"_id": state_key},
                {"_id": state_key, "symbol": base, "side": side,
                 "entry_master": float(p.get("entryPrice") or 0),
                 "sl": sl_price, "tps": tps, "relayed_at": now,
                 "active": True},
                upsert=True)
        except Exception as e:  # noqa: BLE001
            logger.warning("titan relay pos err: %s", e)
            continue
    # Bersihkan state untuk posisi master yang SUDAH TUTUP supaya entry
    # berikutnya di symbol yang sama bisa direlay lagi.
    open_keys = {f"{str(p.get('symbol') or '').upper().replace('USDT', '')}:"
                 f"{'BUY' if float(p.get('positionAmt') or 0) > 0 else 'SELL'}"
                 for p in positions}
    async for st in db.asi_titan_state.find({}):
        if st.get("_id") not in open_keys:
            # v10.1.6 — SOFT-disable (bukan delete_one) sesuai policy.
            await db.asi_titan_state.update_one(
                {"_id": st["_id"]}, {"$set": {"active": False}})

# ─────────────────────────────────────────────────────────────────────────────
# v10.2.6 — PANIC MARKET GUARD (Full-Auto) + market risk snapshot (Semi-Auto UI)
#
# Setiap 2 menit:
#   1. Baca bias market dari BTC + ETH (1h change + 4H EMA50 slope).
#   2. Simpan snapshot ke `asi_market_bias` → dibaca endpoint /asi/market-risk
#      untuk banner peringatan di Semi-Auto UI.
#   3. Untuk setiap user Full-Auto:
#        a. Jika panic_active → cek normalisasi (bias neutral atau reversal
#           pattern terdeteksi) → lepas cooldown; scanner langsung bisa
#           open posisi baru searah pergerakan market.
#        b. Jika belum panic & bias ekstrem (BTC+ETH searah dump/pump):
#           hitung berapa posisi OPEN Full-Auto yang salah arah & loss;
#           hitung total unrealized PnL% terhadap total margin terpakai.
#           Trigger panic bila ≥2 posisi loss salah arah ATAU equity ≤ -3%.
#           Aksi: close posisi loss salah arah (market) + cancel pending
#           limit salah arah → set panic_active=True (cooldown).
#
# Definisi "salah arah" (keputusan user):
#   • LONG salah arah bila BTC & ETH keduanya bearish/dump.
#   • SHORT salah arah bila BTC & ETH keduanya bullish/pump.
# ─────────────────────────────────────────────────────────────────────────────
async def _market_bias_snapshot() -> dict[str, Any]:
    """Hitung bias market terbaru dari BTC + ETH.

    Kombinasi:
      - 1h close-vs-prev → % perubahan jangka pendek
      - 4h EMA50 slope → arah trend menengah
    Bias "dump" (bearish ekstrem) bila BTC & ETH SAMA-SAMA punya
    perubahan 1h ≤ -0.5% ATAU slope EMA50 4h menurun. "pump" simetris.
    """
    out: dict[str, Any] = {
        "btc_change_1h": 0.0,
        "eth_change_1h": 0.0,
        "btc_slope_up": False,
        "btc_slope_dn": False,
        "eth_slope_up": False,
        "eth_slope_dn": False,
        "combined_bias": "neutral",
        "is_panic_dump": False,
        "is_panic_pump": False,
        "reversal_detected": False,
        "reason": "data_unavailable",
        "ok": False,
    }
    try:
        from market_data import get_crypto_snapshot
    except Exception:
        return out
    try:
        from indicators import _ema  # type: ignore
    except Exception:
        _ema = None  # type: ignore
    try:
        btc1h = await get_crypto_snapshot("BTC", "1h")
        eth1h = await get_crypto_snapshot("ETH", "1h")
        btc4h = await get_crypto_snapshot("BTC", "4h")
        eth4h = await get_crypto_snapshot("ETH", "4h")
    except Exception as e:
        logger.debug("panic bias snapshot upstream fail: %s", e)
        return out

    def _closes(snap: Any) -> list[float]:
        return [
            float(c["close"]) for c in ((snap or {}).get("candles") or [])
            if c.get("close")
        ]

    btc1h_c = _closes(btc1h)
    eth1h_c = _closes(eth1h)
    btc4h_c = _closes(btc4h)
    eth4h_c = _closes(eth4h)
    if len(btc1h_c) < 2 or len(eth1h_c) < 2:
        return out

    def _chg(cs: list[float]) -> float:
        if len(cs) >= 2 and cs[-2] > 0:
            return (cs[-1] - cs[-2]) / cs[-2] * 100.0
        return 0.0

    out["btc_change_1h"] = _chg(btc1h_c)
    out["eth_change_1h"] = _chg(eth1h_c)

    if _ema is not None and len(btc4h_c) >= 54:
        try:
            e_series = _ema(btc4h_c, 50)
            prev = e_series[-4] if len(e_series) >= 4 else e_series[-1]
            out["btc_slope_up"] = e_series[-1] > prev
            out["btc_slope_dn"] = e_series[-1] < prev
        except Exception:
            pass
    if _ema is not None and len(eth4h_c) >= 54:
        try:
            e_series = _ema(eth4h_c, 50)
            prev = e_series[-4] if len(e_series) >= 4 else e_series[-1]
            out["eth_slope_up"] = e_series[-1] > prev
            out["eth_slope_dn"] = e_series[-1] < prev
        except Exception:
            pass

    # v10.2.6 — Threshold KETAT (anti-noise, keputusan user):
    #   • 1h change ≥ 1.0% (bukan 0.5% atau 0.7%) DAN slope EMA50 4h searah.
    #   • Butuh KEDUA BTC dan ETH memenuhi — satu doang tidak cukup.
    # Dengan ini, fluktuasi harian normal (±0.5%) tidak akan memicu panic
    # dan bot tetap boleh entry seperti biasa.
    btc_bear = (out["btc_change_1h"] <= -1.0) and out["btc_slope_dn"]
    btc_bull = (out["btc_change_1h"] >= 1.0) and out["btc_slope_up"]
    eth_bear = (out["eth_change_1h"] <= -1.0) and out["eth_slope_dn"]
    eth_bull = (out["eth_change_1h"] >= 1.0) and out["eth_slope_up"]
    out["is_panic_dump"] = bool(btc_bear and eth_bear)
    out["is_panic_pump"] = bool(btc_bull and eth_bull)
    if out["is_panic_dump"]:
        out["combined_bias"] = "bearish"
    elif out["is_panic_pump"]:
        out["combined_bias"] = "bullish"
    else:
        out["combined_bias"] = "neutral"

    def _reversal(cs: list[float]) -> bool:
        """Candle terakhir 1h bergerak berlawanan dari candle sebelumnya
        (shift momentum). Dipakai sebagai early-release panic cooldown."""
        if len(cs) < 3:
            return False
        last_diff = cs[-1] - cs[-2]
        prev_diff = cs[-2] - cs[-3]
        return (last_diff > 0 and prev_diff < 0) or (last_diff < 0 and prev_diff > 0)

    out["reversal_detected"] = _reversal(btc1h_c) and _reversal(eth1h_c)
    out["reason"] = (
        f"BTC {out['btc_change_1h']:+.2f}%/1h, "
        f"ETH {out['eth_change_1h']:+.2f}%/1h"
    )
    out["ok"] = True
    return out


def _position_wrong_direction(trade_side: str, bias: dict[str, Any]) -> bool:
    """LONG salah arah bila panic_dump; SHORT salah arah bila panic_pump."""
    if trade_side == "BUY":
        return bool(bias.get("is_panic_dump"))
    return bool(bias.get("is_panic_pump"))


async def _panic_cancel_pending_limit(db: Any, t: dict[str, Any]) -> None:
    """Batalkan 1 order LIMIT entry pending (duplikat minimal dari
    routes._cancel_pending_limit supaya scheduler tidak import routes)."""
    cred = await resolve_credential(
        db, t["device_id"], t["exchange"], bool(t.get("testnet", True)))
    if cred and (t.get("exchange") or "").lower() == "binance":
        try:
            bin_sym = (
                str(t.get("symbol") or "").upper()
                .split("/")[0].split("USDT")[0].split("-")[0] + "USDT"
            )
            await br.cancel_order(
                decrypt(cred["api_key_enc"]), decrypt(cred["api_secret_enc"]),
                bool(cred.get("testnet", True)),
                symbol=bin_sym, order_id=t.get("entry_order_id"))
        except Exception:
            pass
    now = datetime.now(timezone.utc).isoformat()
    await db.asi_trades.update_one(
        {"_id": t["_id"]},
        {"$set": {"status": "cancelled", "close_reason": "panic_guard",
                  "closed_at": now, "updated_at": now}},
    )


async def _user_equity_pnl_pct(db: Any, device_id: str,
                                testnet: bool | None) -> tuple[float, float, float]:
    """Return (equity_pct, total_pnl, total_margin) untuk posisi Full-Auto
    OPEN device. equity_pct = total_pnl / total_margin * 100."""
    total_pnl = 0.0
    total_margin = 0.0
    q: dict[str, Any] = {"device_id": device_id, "status": "open",
                          "mode": "full"}
    if testnet is not None:
        q["testnet"] = bool(testnet)
    async for t in db.asi_trades.find(q):
        total_pnl += float(t.get("pnl_usdt") or 0)
        m = t.get("margin_usdt")
        if m is None:
            try:
                m = (float(t.get("entry_price") or 0)
                     * float(t.get("qty") or 0)
                     / max(1, int(t.get("leverage") or 10)))
            except Exception:
                m = 0.0
        total_margin += float(m or 0)
    pct = (total_pnl / total_margin * 100.0) if total_margin > 0 else 0.0
    return pct, total_pnl, total_margin


async def _run_panic_guard(db: Any) -> None:
    """Panic Market Guard — dieksekusi tiap PANIC_INTERVAL detik (120s)."""
    bias = await _market_bias_snapshot()
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    # Simpan snapshot bias (dipakai Semi-Auto UI + status endpoint).
    try:
        await db.asi_market_bias.replace_one(
            {"_id": "market"},
            {"_id": "market", "updated_at": now_iso, **bias},
            upsert=True,
        )
    except Exception as e:
        logger.debug("panic bias snapshot save fail: %s", e)
    if not bias.get("ok"):
        return  # fail-open: data tidak tersedia → tidak melakukan apa-apa

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
            net = bool(cfg["active_testnet"]) if "active_testnet" in cfg else None

            panic_active = bool(cfg.get("panic_active"))
            if panic_active:
                # Cek normalisasi: bias neutral ATAU reversal_detected
                # (keputusan user: condition-based tanpa minimal waktu).
                release_now = (
                    bias["combined_bias"] == "neutral"
                    or bias.get("reversal_detected")
                )
                if release_now:
                    rel_reason = "neutral" if bias["combined_bias"] == "neutral" else "reversal"
                    await db.asi_bot_config.update_one(
                        {"_id": cfg["_id"]},
                        {"$set": {
                            "panic_active": False,
                            "panic_released_at": now_iso,
                            "panic_release_reason": f"{rel_reason} | {bias['reason']}",
                            "updated_at": now_iso,
                        }},
                    )
                    try:
                        await db.asi_panic_events.insert_one({
                            "device_id": device_id,
                            "event": "released",
                            "at": now_iso,
                            "release_reason": rel_reason,
                            "bias": bias.get("reason"),
                            "reversal_detected": bool(bias.get("reversal_detected")),
                        })
                    except Exception:
                        pass
                    logger.warning(
                        "panic-guard RELEASED for %s: %s | %s",
                        device_id, rel_reason, bias["reason"])
                continue

            # Belum panic → evaluasi trigger.
            # 2 jalur trigger (keputusan user):
            #   A. ≥2 posisi loss salah arah SIGNIFIKAN (pnl ≤ -1% margin)
            #      butuh bias ekstrem untuk mendefinisikan "salah arah"
            #   B. Total unrealized PnL/equity ≤ -3%
            #
            # ANTI-NOISE (keputusan user: panic guard JANGAN mengganggu
            # bot normal atau jadi noise untuk entry baru):
            #   • Hitung loss hanya kalau PnL ≤ -1% dari margin posisi
            #     (fluktuasi kecil −$0.01 TIDAK boleh dihitung).
            #   • Hysteresis 3 menit setelah panic release — hindari
            #     toggle on/off beruntun saat bias dekat threshold.
            released_at = cfg.get("panic_released_at")
            if released_at:
                try:
                    rel_dt = datetime.fromisoformat(
                        str(released_at).replace("Z", "+00:00"))
                    if (now - rel_dt).total_seconds() < 180:
                        continue  # masih dalam hysteresis window
                except Exception:
                    pass

            loss_wrong_count = 0
            open_trades: list[dict[str, Any]] = []
            async for t in db.asi_trades.find({
                "device_id": device_id, "status": "open", "mode": "full",
            }):
                open_trades.append(t)
                if not _position_wrong_direction(t.get("side"), bias):
                    continue
                pnl_t = float(t.get("pnl_usdt") or 0)
                if pnl_t >= 0:
                    continue
                margin_t = float(t.get("margin_usdt") or 0)
                if margin_t <= 0:
                    try:
                        margin_t = (float(t.get("entry_price") or 0)
                                    * float(t.get("qty") or 0)
                                    / max(1, int(t.get("leverage") or 10)))
                    except Exception:
                        margin_t = 0.0
                # Loss harus signifikan: ≥ 1% margin DAN absolute ≥ $0.5
                # supaya posisi dust/baru open tidak dihitung.
                sig_loss = (margin_t > 0 and (pnl_t / margin_t) <= -0.01
                            and abs(pnl_t) >= 0.5)
                if sig_loss:
                    loss_wrong_count += 1

            equity_pct, total_pnl, total_margin = await _user_equity_pnl_pct(
                db, device_id, net)
            # Equity trigger juga punya floor absolute: butuh total_margin
            # minimal $5 agar akun demo kecil tidak kena false trigger.
            trigger_loss_wrong = loss_wrong_count >= 2
            trigger_equity = (equity_pct <= -3.0 and total_margin >= 5.0
                              and total_pnl <= -1.0)
            if not (trigger_loss_wrong or trigger_equity):
                continue

            # ─── TRIGGER PANIC ───
            closed_count = 0
            closed_pnl = 0.0
            for t in open_trades:
                if not _position_wrong_direction(t.get("side"), bias):
                    continue
                pnl_t = float(t.get("pnl_usdt") or 0)
                if pnl_t >= 0:
                    continue  # hanya tutup yang loss
                cred = await resolve_credential(
                    db, device_id, t["exchange"],
                    bool(t.get("testnet", True)))
                if not cred:
                    continue
                qty = float(t.get("qty_remaining") or t.get("qty") or 0)
                if qty <= 0:
                    continue
                try:
                    await close_position(cred, t["symbol"], t["side"], qty)
                    await db.asi_trades.update_one(
                        {"_id": t["_id"]},
                        {"$set": {
                            "status": "closed",
                            "close_reason": "panic_guard",
                            "closed_at": now_iso,
                            "updated_at": now_iso,
                            "pnl_usdt": round(pnl_t, 2),
                        }},
                    )
                    closed_count += 1
                    closed_pnl += pnl_t
                except Exception as e:
                    logger.warning("panic close %s: %s", t.get("_id"), e)

            cancelled_count = 0
            async for t in db.asi_trades.find({
                "device_id": device_id, "status": "pending_entry",
                "mode": "full",
            }):
                if not _position_wrong_direction(t.get("side"), bias):
                    continue
                try:
                    await _panic_cancel_pending_limit(db, t)
                    cancelled_count += 1
                except Exception as e:
                    logger.warning("panic cancel pending %s: %s",
                                   t.get("_id"), e)

            reasons: list[str] = []
            if trigger_loss_wrong:
                reasons.append(f"{loss_wrong_count} posisi loss salah arah")
            if trigger_equity:
                reasons.append(f"equity {equity_pct:+.2f}% ≤ -3%")
            panic_reason = " + ".join(reasons) + f" | {bias['reason']}"

            await db.asi_bot_config.update_one(
                {"_id": cfg["_id"]},
                {"$set": {
                    "panic_active": True,
                    "panic_at": now_iso,
                    "panic_reason": panic_reason,
                    "panic_closed_count": closed_count,
                    "panic_closed_pnl": round(closed_pnl, 2),
                    "panic_cancelled_count": cancelled_count,
                    "panic_bias": bias["combined_bias"],
                    "updated_at": now_iso,
                }},
            )
            try:
                await db.asi_panic_events.insert_one({
                    "device_id": device_id,
                    "event": "triggered",
                    "at": now_iso,
                    "reason": panic_reason,
                    "closed_count": closed_count,
                    "closed_pnl": round(closed_pnl, 2),
                    "cancelled_count": cancelled_count,
                    "bias_snapshot": {
                        "combined_bias": bias["combined_bias"],
                        "btc_change_1h": bias["btc_change_1h"],
                        "eth_change_1h": bias["eth_change_1h"],
                    },
                })
            except Exception:
                pass
            logger.warning(
                "panic-guard TRIGGERED for %s: %s | closed=%d (pnl=%.2f) cancelled=%d",
                device_id, panic_reason, closed_count, closed_pnl, cancelled_count)
        except Exception as e:  # noqa: BLE001
            logger.exception("panic guard device err %s: %s",
                             cfg.get("_id"), e)




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
            asyncio.create_task(self._loop_titan_relay()),
            asyncio.create_task(self._loop_panic_guard()),
        ]
        logger.info("ASI-Bot scheduler started: watcher + pnl + scanner + titan_relay + panic_guard")

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
        # v10.1.1 — Scanner langsung jalan saat startup (tanpa delay 30s)
        # supaya user yang baru nyalakan Full-Auto tidak menunggu lama.
        while self._running:
            try:
                await _run_full_auto_scanner(self.db, self.signal_fetcher)
            except Exception as e:  # noqa: BLE001
                logger.exception("scanner loop crash: %s", e)
            await asyncio.sleep(SCANNER_INTERVAL)

    async def _loop_titan_relay(self) -> None:
        """v10.0.15 — Titan Relay (Cara 1): membaca posisi akun master
        (Binance yang dieksekusi WunderTrading) dan mem-broadcast-nya ke
        semua user Full-Auto dengan signal_source="cloud_pro" (Titan-Bot).
        Entry memakai harga mark saat ini; SL/TP disalin persis dari
        bracket master. Kalau master tidak punya SL/TP, relay di-skip
        demi keamanan (tidak open posisi telanjang di akun user)."""
        await asyncio.sleep(20)  # startup delay
        while self._running:
            try:
                await _run_titan_relay(self.db)
            except Exception as e:  # noqa: BLE001
                logger.exception("titan relay loop crash: %s", e)
            await asyncio.sleep(TITAN_RELAY_INTERVAL)

    async def _loop_panic_guard(self) -> None:
        """v10.2.6 — Panic Market Guard: tiap 2 menit baca BTC+ETH,
        trigger panic cooldown Full-Auto bila ≥2 posisi loss salah arah
        atau equity ≤ -3%; lepas cooldown saat bias neutral/reversal."""
        await asyncio.sleep(15)  # startup delay — tunggu market_data warm
        while self._running:
            try:
                await _run_panic_guard(self.db)
            except Exception as e:  # noqa: BLE001
                logger.exception("panic guard loop crash: %s", e)
            await asyncio.sleep(PANIC_INTERVAL)
