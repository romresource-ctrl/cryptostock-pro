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
# Minimum confidence required for full-auto execution.
MIN_FULL_AUTO_CONFIDENCE = 90
# v10.2.17 — Anti-loss BUY gates (keputusan user, analisis loss LONG
# beruntun saat base 4H BTC bearish):
# 1. ANTI-FLAP: rezim "trending_up" harus bertahan 3 siklus scanner
#    berturut-turut sebelum BUY altcoin dipercaya (bounce 1 siklus di
#    tengah dump tidak lagi memicu LONG).
# 2. BEAR 4H: base_regime BTC "BEAR" → BUY tetap boleh tapi min
#    confidence +5 poin (jalan tengah, BUKAN blokir total).
# 3. KONFIRMASI 2 SIKLUS: sinyal BUY yang sama (device+symbol+side+
#    fingerprint formula) harus muncul 2 siklus scanner berturut-turut
#    sebelum Full-Auto mengeksekusi.
TREND_UP_MIN_CYCLES = 3
BEAR4H_CONF_BONUS = 5
BUY_CONFIRM_CYCLES = 1
# v10.2.31 — Keputusan user (eksekusi lebih sering, "jangan sampai
# seharian tidak eksekusi"): BUY tidak lagi butuh 2 siklus konfirmasi;
# satu siklus cukup. Risiko flap kecil karena proteksi lain tetap:
# anti-chase relatif, RSI, trend 4H, side-cap 3, cooldown loss 4h.
# v10.2.21 — Guard anti-loss baru (keputusan user, analisis loss BCH
# SHORT 16/10 yang masuk di dasar lokal −4,3% dalam 9 jam lalu kena SL):
# 4. ANTI-CHASE SELL: SELL ditolak bila alt sudah turun >SELL_CHASE_PCT
#    dalam SELL_CHASE_WINDOW_H jam terakhir (anti-short-di-dasar).
# 5. KONFIRMASI SELL 2 SIKLUS: simetri dgn BUY — SELL yang sama harus
#    muncul 2 siklus scanner berturut sebelum dieksekusi.
# 6. EARLY EXIT LONGTERM: posisi Confluence v9 (longterm) yang berjalan
#    >LONGTERM_STALE_HOURS jam tanpa pernah mencapai profit floating
#    > LONGTERM_STALE_MIN_PROFIT_PCT ditutup di market agar tidak kena
#    SL penuh (mengurangi exposure posisi "mati").
SELL_CHASE_PCT = 3.0            # %
SELL_CHASE_WINDOW_H = 6         # jam
SELL_CONFIRM_CYCLES = 2
LONGTERM_STALE_HOURS = 3.0
LONGTERM_STALE_MIN_PROFIT_PCT = 0.5  # %
# v10.2.23 — Paket anti-loss sisi BUY + circuit breaker yang tangguh
# (analisis loss beruntun 18/10: TIA LONG di puncak pump +3,7%, SAND
# di-LONG 3× beruntun saat dump → SL semua, total -$205; breaker lama
# v10.2.5 tidak aktif karena hanya menghitung close_reason=="SL"
# sedangkan loss beralasan lain memutus streak).
# 1. CIRCUIT BREAKER berbasis PnL: N closed terakhir semua rugi
#    (pnl < -$1, alasan APA PUN) & terbaru <2 jam → istirahat 2 jam.
# 2. COOLDOWN per-simbol: simbol yang baru rugi <4 jam tidak boleh
#    di-entry ulang (anti revenge-entry, kasus SAND 18/10).
# 3. ANTI-CHASE BUY (cermin SELL): LONG ditolak bila alt sudah naik
#    >BUY_CHASE_PCT dalam BUY_CHASE_WINDOW_H jam (kasus TIA: +4,6%/6 jam).
# 4. DUMP GUARD BUY: LONG ditolak bila alt turun >BUY_DUMP_GUARD_PCT
#    dalam BUY_DUMP_GUARD_WINDOW_H jam terakhir (menangkap pisau jatuh,
#    kasus SAND: -3,4%/2 jam saat entry).
CIRCUIT_BREAKER_LOSSES = 3
CIRCUIT_BREAKER_PAUSE_HOURS = 2
SYMBOL_LOSS_COOLDOWN_HOURS = 4
BUY_CHASE_PCT = 3.0
BUY_CHASE_WINDOW_H = 6
BUY_DUMP_GUARD_PCT = 2.5
BUY_DUMP_GUARD_WINDOW_H = 2
# v10.2.25 — Lesson 18/10 14:02-14:09 UTC: 7 SHORT serentak di dasar
# candle 13:00 UTC (semua alt -1 s/d -1,5% dalam 1 jam) → BTC bounce
# kecil, semua kena SL/BE. Dua tambahan:
# A. SELL short-window: SELL ditolak bila alt turun >SELL_SHORT_DUMP_PCT
#    dalam SELL_SHORT_DUMP_WINDOW_H jam terakhir (anti-shorting-dasar-bar).
#    Simetris dengan dump-guard BUY.
# B. SIDE_CONCURRENCY: posisi OPEN per device per arah dibatasi
#    MAX_OPEN_PER_SIDE. Mencegah correlated correlated-loss saat regime
#    flip melepas banyak sinyal serentak.
SELL_SHORT_DUMP_PCT = 1.2
SELL_SHORT_DUMP_WINDOW_H = 2
MAX_OPEN_PER_SIDE = 3
# Set simbol yang TIDAK terdaftar di jaringan aktif (ICP testnet).
_UNAVAILABLE_SYMS: set[str] = set()


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
                # v10.2.8 — Simpan DETAIL error asli (mis. "-2021 Order
                # would immediately trigger", tick size, min notional)
                # ke record trade supaya bisa didiagnosis dari DB/UI
                # tanpa menggali log backend (kasus STRK 15/10).
                _errs = res.get("errors") or []
                _detail = str(_errs[0])[:200] if _errs else "unknown"
                logger.warning("attach failed after fill %s: %s",
                               t.get("_id"), _errs[:2])
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
                        "close_reason_detail": _detail,
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


# ─────────────────────────────────────────────────────────────────────────────
# v10.2.12 — BTC REGIME GATE
#
# Keputusan user (15/10 malam): "semua koin sebagian besar dipengaruhi
# pergerakan BTC — daripada bermacam-macam guard, buat SATU formula
# deteksi overbought/oversold BTC yang menahan sinyal salah arah sampai
# pembalikan BTC terkonfirmasi, lalu kirim sinyal searah."
#
# Rezim dihitung SEKALI per siklus scanner dari BTC saja:
#   bullish_reversal : RSI14 1h ≤ 35 & candle terakhir ≥ +0.3%,
#                      ATAU candle sebelumnya ≤ -0.5% diikuti bounce ≥ +0.3%
#                      → blokir SEMUA SELL altcoin (tunggu reversal; LONG lolos)
#   bearish_reversal : RSI14 1h ≥ 65 & candle terakhir ≤ -0.3%,
#                      ATAU candle sebelumnya ≥ +0.5% diikuti drop ≤ -0.3%
#                      → blokir SEMUA BUY altcoin (SHORT lolos)
#   trending_up      : RSI14 55–75 & slope EMA50 4H naik  → hanya LONG
#   trending_down    : RSI14 25–45 & slope EMA50 4H turun → hanya SHORT
#   neutral          : lainnya → semua arah lolos
#
# Rezim reversal di-LATCH 2 candle 1h (120 menit, keputusan user) supaya
# tidak flicker; rezim trending/neutral dievaluasi segar tiap siklus.
# BTC sendiri dikecualikan dari gate (ia referensi, bukan ikutan).
# Fail-open: data tidak tersedia → neutral (bot jalan normal).
# ─────────────────────────────────────────────────────────────────────────────
REGIME_LATCH_MINUTES = 120  # 2 candle 1h (keputusan user, opsi 3=a)


def _trend_up_streak(prev_fresh_regime: str | None, prev_streak: int,
                     fresh_regime: str) -> int:
    """v10.2.17 — Hitung berapa siklus berturut-turut rezim SEGAR BTC
    berada di trending_up. Reset ke 0 begitu rezim berubah. Dipakai
    untuk anti-flap: BUY hanya lolos bila streak >= TREND_UP_MIN_CYCLES.
    Fungsi murni (mudah di-unit-test)."""
    if fresh_regime == "trending_up":
        return min(prev_streak + 1, 99) if prev_fresh_regime == "trending_up" else 1
    return 0


def _trend_down_streak(prev_fresh_regime: str | None, prev_streak: int,
                       fresh_regime: str) -> int:
    """v10.2.22 — Pasangan simetris _trend_up_streak untuk trending_down.
    Dipakai agar relaksasi slope trend-filter 4H bersifat dua arah
    (LONG & SHORT diperlakukan setara)."""
    if fresh_regime == "trending_down":
        return min(prev_streak + 1, 99) if prev_fresh_regime == "trending_down" else 1
    return 0


def _buy_confirm_eval(doc: dict[str, Any] | None, *, fingerprint: str,
                      now: datetime, window_s: int,
                      required_cycles: int = BUY_CONFIRM_CYCLES) -> tuple[bool, int]:
    """v10.2.17 — Evaluasi konfirmasi sinyal BUY 2 siklus berturut-turut.

    Return (confirmed, new_count): confirmed=True hanya bila sinyal
    dengan fingerprint SAMA terlihat pada siklus sebelumnya (last_seen
    dalam window_s detik). Jendela 2× interval scanner menoleransi
    jitter; siklus yang terlewat (sinyal absen) mereset hitungan.
    Fungsi murni (mudah di-unit-test)."""
    if doc and doc.get("fingerprint") == fingerprint \
            and int(doc.get("count") or 0) >= 1:
        try:
            last = datetime.fromisoformat(
                str(doc.get("last_seen_at")).replace("Z", "+00:00"))
            if 0 <= (now - last).total_seconds() <= window_s:
                return True, required_cycles
        except Exception:
            pass
    return False, 1


async def _compute_btc_regime() -> dict[str, Any]:
    out: dict[str, Any] = {"regime": "neutral", "rsi": None, "chg_last": 0.0,
                           "chg_prev": 0.0, "slope_up": False, "slope_dn": False,
                           "ok": False, "detail": "data_unavailable"}
    try:
        from market_data import get_crypto_snapshot
        from indicators import _ema, _rsi, _detect_regime
    except Exception:
        return out
    try:
        btc1h = await get_crypto_snapshot("BTC", "1h")
        btc4h = await get_crypto_snapshot("BTC", "4h")
    except Exception as e:
        logger.debug("btc regime fetch gagal: %s", e)
        return out
    closes1h = [float(c["close"]) for c in ((btc1h or {}).get("candles") or [])
                if c.get("close")]
    if len(closes1h) < 17:
        return out
    # Index -1 = candle berjalan; closed terakhir = -2, sebelumnya = -3.
    chg_last = (closes1h[-2] - closes1h[-3]) / closes1h[-3] * 100.0 if closes1h[-3] else 0.0
    chg_prev = (closes1h[-3] - closes1h[-4]) / closes1h[-4] * 100.0 if closes1h[-4] else 0.0
    # v10.2.30 — BTC change 6-hour (persentase, dari candle closed
    # terakhir vs. 6 candle sebelumnya). Dipakai anti-chase relatif:
    # bot menolak membeli alt hanya ketika BTC-nya SENDIRI sudah
    # bergerak jauh (BTC yang "late", bukan alt yang "early").
    btc_chg_6h = 0.0
    if len(closes1h) >= 8 and closes1h[-8]:
        btc_chg_6h = (closes1h[-2] - closes1h[-8]) / closes1h[-8] * 100.0
    rsi = _rsi(closes1h[:-1], 14)
    closes4h = [float(c["close"]) for c in ((btc4h or {}).get("candles") or [])
                if c.get("close")]
    highs4h = [float(c.get("high") or c["close"]) for c in ((btc4h or {}).get("candles") or [])
               if c.get("close")]
    lows4h = [float(c.get("low") or c["close"]) for c in ((btc4h or {}).get("candles") or [])
              if c.get("close")]
    slope_up = slope_dn = False
    if len(closes4h) >= 54:
        try:
            e = _ema(closes4h, 50)
            prev = e[-4] if len(e) >= 4 else e[-1]
            slope_up = e[-1] > prev
            slope_dn = e[-1] < prev
        except Exception:
            pass
    # v10.2.12b — ALIGN dengan FORMULA REZIM ASLI USER
    # (btc_trading_formula.py → _detect_regime, ada sejak v8.7.23 di
    # desain sinyal awal, sebelum ASI-Bot). Rezim trending memakai
    # detektor orisinal (price vs EMA50 4H + ATR% capitulation);
    # deteksi reversal RSI 1h (lapisan baru) menangkap pembalikan
    # lebih dini dan mendahului rezim trending.
    base = _detect_regime(closes4h, highs4h, lows4h) if len(closes4h) >= 58 \
        else {"regime": "UNKNOWN"}
    base_regime = base.get("regime", "UNKNOWN")
    out.update({"rsi": rsi, "chg_last": chg_last, "chg_prev": chg_prev,
                "chg_6h": btc_chg_6h,
                "slope_up": slope_up, "slope_dn": slope_dn, "ok": True,
                "base_regime": base_regime})
    if rsi is not None and (
        (rsi <= 35 and chg_last >= 0.3)
        or (chg_prev <= -0.5 and chg_last >= 0.3)
    ):
        out["regime"] = "bullish_reversal"
    elif rsi is not None and (
        (rsi >= 65 and chg_last <= -0.3)
        or (chg_prev >= 0.5 and chg_last <= -0.3)
    ):
        out["regime"] = "bearish_reversal"
    elif base_regime == "BULL":
        out["regime"] = "trending_up"
    elif base_regime == "BEAR_CAPITULATION":
        # Formula asli user: kapitulasi = dump bervolatilitas ekstrem.
        # LONG berbahaya (falling knife), SHORT telat (risiko bounce
        # keras) → blokir KEDUA arah sampai volatilitas mereda.
        out["regime"] = "bear_capitulation"
    elif base_regime == "BEAR":
        out["regime"] = "trending_down"
    else:
        out["regime"] = "neutral"
    out["detail"] = (
        f"RSI1h {rsi:.0f}" if rsi is not None else "RSI n/a"
    ) + f", 1h {chg_last:+.2f}%/{chg_prev:+.2f}%, base4H {base_regime}"
    return out


async def _get_btc_regime(db: Any) -> dict[str, Any]:
    """Rezim BTC dengan latch 120 menit untuk reversal (anti-flicker).
    Deteksi reversal segar selalu menimpa latch lama; trending/neutral
    tidak di-latch."""
    fresh = await _compute_btc_regime()
    now = datetime.now(timezone.utc)
    doc = None
    try:
        doc = await db.asi_scan_status.find_one({"_id": "btc_regime"})
    except Exception:
        pass
    # v10.2.17 — ANTI-FLAP: catat streak rezim trending_up SEGAR tiap
    # siklus scanner (fungsi ini hanya dipanggil scanner, 1× per siklus).
    # Disimpan di Mongo agar tahan restart / multi-replica.
    streak = int((doc or {}).get("trend_up_streak") or 0)
    streak_dn = int((doc or {}).get("trend_down_streak") or 0)
    if fresh.get("ok"):
        streak = _trend_up_streak(
            (doc or {}).get("last_fresh_regime"), streak, fresh["regime"])
        # v10.2.22 — streak simetris untuk trending_down (dipakai relaksasi
        # slope trend-filter 4H untuk SHORT, pasangan anti-flap BUY).
        streak_dn = _trend_down_streak(
            (doc or {}).get("last_fresh_regime"), streak_dn, fresh["regime"])
        try:
            await db.asi_scan_status.update_one(
                {"_id": "btc_regime"},
                {"$set": {
                    "last_fresh_regime": fresh["regime"],
                    "trend_up_streak": streak,
                    "trend_down_streak": streak_dn,
                    "streak_updated_at": now.isoformat(),
                }},
                upsert=True,
            )
        except Exception:
            pass
    fresh["trend_up_streak"] = streak
    fresh["trend_down_streak"] = streak_dn
    if fresh.get("ok") and fresh["regime"] in ("bullish_reversal", "bearish_reversal"):
        # Reversal terdeteksi → (re)latch 120 menit.
        try:
            await db.asi_scan_status.update_one(
                {"_id": "btc_regime"},
                {"$set": {
                    "regime": fresh["regime"],
                    "detail": fresh["detail"],
                    "latched_at": now.isoformat(),
                    "latched_until": (
                        now + timedelta(minutes=REGIME_LATCH_MINUTES)
                    ).isoformat(),
                }},
                upsert=True,
            )
        except Exception:
            pass
        fresh["latched"] = True
        return fresh
    # Bukan reversal segar → pakai latch bila masih berlaku.
    if doc and doc.get("latched_until"):
        try:
            until = datetime.fromisoformat(
                str(doc["latched_until"]).replace("Z", "+00:00"))
            if now < until and doc.get("regime") in (
                    "bullish_reversal", "bearish_reversal"):
                return {"regime": doc["regime"], "ok": True,
                        "detail": f"latched: {doc.get('detail')}",
                        "rsi": fresh.get("rsi"), "chg_last": fresh.get("chg_last", 0.0),
                        "chg_prev": fresh.get("chg_prev", 0.0),
                        "slope_up": fresh.get("slope_up", False),
                        "slope_dn": fresh.get("slope_dn", False),
                        # v10.2.17 — base 4H & streak ikut diteruskan saat
                        # latch aktif (dipakai gate conf BEAR + anti-flap).
                        "base_regime": fresh.get("base_regime"),
                        "trend_up_streak": streak,
                        "trend_down_streak": streak_dn,
                        "latched": True}
        except Exception:
            pass
    return fresh


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
    # v10.2.7 — SCAN DIAGNOSTICS (permintaan user: "kenapa bot tidak
    # eksekusi di HP?"). Semua jalur skip scanner sebelumnya SILENT —
    # tidak terlihat tanpa menggali DB/log. Sekarang setiap device
    # dicatat: discan atau di-skip + alasannya, sinyal lolos, posisi
    # terpasang, dan alasan reject per simbol. Disimpan di
    # asi_scan_status.devices → endpoint GET /asi/scan-debug.
    device_reports: dict[str, dict[str, Any]] = {}

    def _dev_skip(did: str, reason: str) -> None:
        device_reports[did] = {"scanned": False, "skip_reason": reason,
                               "signals": 0, "placed": 0, "rejects": {}}

    def _dev_reject(rep: dict[str, Any] | None, reason: str) -> None:
        if rep is None:
            return
        r = rep.setdefault("rejects", {})
        r[reason] = int(r.get(reason) or 0) + 1
    # v10.2.12 — BTC REGIME GATE (keputusan user 15/10 malam, menggantikan
    # circuit breaker v10.2.5 + filter exhaustion/cooling v10.2.8).
    # Rasional user: "semua koin sebagian besar dipengaruhi pergerakan BTC"
    # — maka SATU gate di hulu scanner menentukan arah yang boleh dieksekusi
    # berdasarkan rezim BTC, menggantikan guard-guard per-aset yang
    # tumpang tindih. Rezim dihitung SEKALI per siklus (RSI14 1h + 2 candle
    # 1h terakhir + slope EMA50 4H) dan di-latch 2 candle (120 menit) untuk
    # rezim reversal supaya tidak flicker.
    btc_regime = await _get_btc_regime(db)
    # v10.2.17 — streak trending_up untuk anti-flap (BUY baru boleh bila
    # rezim trending_up bertahan TREND_UP_MIN_CYCLES siklus berturut).
    trend_up_streak = int(btc_regime.get("trend_up_streak") or 0)
    # v10.2.22 — streak trending_down simetris (relaksasi slope SHORT).
    trend_down_streak = int(btc_regime.get("trend_down_streak") or 0)
    # Kapitulasi memblokir KEDUA arah (falling knife + late short).
    gate_block_sell = btc_regime["regime"] in (
        "bullish_reversal", "trending_up", "bear_capitulation")
    gate_block_buy = btc_regime["regime"] in (
        "bearish_reversal", "trending_down", "bear_capitulation")
    if btc_regime["regime"] != "neutral":
        logger.info("btc-regime gate: %s (%s) → blokir %s | streak_up=%d base4H=%s",
                    btc_regime["regime"], btc_regime.get("detail"),
                    "SELL" if gate_block_sell else "BUY" if gate_block_buy else "-",
                    trend_up_streak, btc_regime.get("base_regime"))
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
                _dev_skip(device_id, "signal_source=cloud_pro (menunggu Titan relay)")
                continue
            scanned += 1
            rep: dict[str, Any] = {"scanned": True, "skip_reason": None,
                                   "signals": 0, "placed": 0, "rejects": {}}
            device_reports[device_id] = rep
            max_tr = int(cfg.get("max_trades_per_day") or 3)
            # v9.9.5 — network aktif ditentukan lebih awal supaya kuota
            # harian juga dihitung per jaringan.
            net = bool(cfg["active_testnet"]) if "active_testnet" in cfg else None
            placed = await _trades_today_count(db, device_id, net)
            if placed >= max_tr:
                _dev_skip(device_id, f"daily limit tercapai ({placed}/{max_tr} trades hari ini)")
                continue
            # v10.2.23 — CIRCUIT BREAKER berbasis PnL + COOLDOWN per-
            # simbol (menggantikan loss-streak breaker v10.2.5 yang hanya
            # menghitung close_reason=="SL"; loss beralasan lain — mis.
            # "position_closed_externally" seperti ZIL 18/10 — dulu
            # MEMUTUS streak sehingga breaker tidak aktif saat loss
            # campur aduk). Aturan: CIRCUIT_BREAKER_LOSSES closed
            # terakhir semua rugi (pnl < -$1, alasan apa pun) DAN yang
            # terbaru <2 jam lalu → istirahat 2 jam. Sekaligus bangun
            # peta cooldown: simbol yang baru rugi <
            # SYMBOL_LOSS_COOLDOWN_HOURS jam tidak boleh di-entry ulang
            # (anti revenge-entry — kasus SAND 18/10 di-LONG 3× beruntun,
            # SL semua: -$60, -$42, -$102).
            _sym_loss_cd: dict[str, str] = {}
            try:
                _recent_closed = [
                    t async for t in db.asi_trades.find(
                        {"device_id": device_id, "status": "closed"}
                    ).sort("closed_at", -1).limit(25)
                ]
                _now_cb = datetime.now(timezone.utc)
                _cutoff_cb = (_now_cb - timedelta(
                    hours=CIRCUIT_BREAKER_PAUSE_HOURS)).isoformat()
                if (len(_recent_closed) >= CIRCUIT_BREAKER_LOSSES
                        and all(float(t.get("pnl_usdt") or 0) < -1.0
                                for t in _recent_closed[:CIRCUIT_BREAKER_LOSSES])
                        and str(_recent_closed[0].get("closed_at") or "") > _cutoff_cb):
                    logger.warning(
                        "circuit-breaker: %s %d loss beruntun <%dj → istirahat",
                        device_id, CIRCUIT_BREAKER_LOSSES,
                        CIRCUIT_BREAKER_PAUSE_HOURS)
                    _dev_skip(
                        device_id,
                        f"circuit-breaker: {CIRCUIT_BREAKER_LOSSES} loss "
                        f"beruntun <{CIRCUIT_BREAKER_PAUSE_HOURS} jam")
                    continue
                _cd_cut = (_now_cb - timedelta(
                    hours=SYMBOL_LOSS_COOLDOWN_HOURS)).isoformat()
                for t in _recent_closed:
                    _s = str(t.get("symbol") or "").upper()
                    if (_s and float(t.get("pnl_usdt") or 0) < -1.0
                            and str(t.get("closed_at") or "") > _cd_cut
                            and _s not in _sym_loss_cd):
                        _sym_loss_cd[_s] = str(t.get("closed_at"))
            except Exception as _ls_err:
                logger.debug("circuit-breaker check gagal (skip, fail-open): %s", _ls_err)
            # v9.7.3 — BUG FIX: empty whitelist silently disabled the bot
            # ("ACTIVE" tapi tidak pernah scan). Default ke Top-100 futures
            # agar Full-Auto langsung bekerja tanpa konfigurasi tambahan.
            # v10.0.16 — FULL-AUTO kembali scan Top-100 (keputusan user,
            # sebelumnya Top-50). Semi-Auto tetap bebas semua aset.
            whitelist = cfg.get("whitelist") or list(TOP_100_FUTURES)
            whitelist = [s for s in whitelist if s in TOP_100_FUTURES]
            if not whitelist:
                _dev_skip(device_id, "whitelist kosong (tidak ada simbol untuk discan)")
                continue
            exchange = cfg.get("exchange") or "binance"
            # v9.9.5 — Full-Auto memakai credential sesuai switch jaringan
            # aktif (active_testnet). Config lama tanpa field ini → None =
            # perilaku lama (credential apa pun yang tersedia).
            cred = await resolve_credential(db, device_id, exchange, net)
            if not cred:
                _dev_skip(device_id, f"credential {exchange} tidak terhubung — Connect exchange dulu di app")
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
            #     tertinggi).
            #   • Default (belum pilih) → aman: hanya `longterm` (Confluence v9).
            # v10.2.16 — Keputusan user: profile scalper/day/swing kini
            # juga MENYERTAKAN engine `longterm` (Confluence v9) → keempat
            # engine dievaluasi berbarengan; sinyal Confluence v9 ikut
            # dieksekusi bila muncul. Trade hasil engine longterm membawa
            # profile "longterm" → otomatis bebas aturan horizon/profit-cap
            # (hold mengikuti SL/TP1-3 sesuai keputusan user sebelumnya).
            if bot_profile in ("scalper", "day", "swing"):
                _ENGINES = ["scalper", "day", "swing", "longterm"]
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
                # v10.2.12 — Snapshot 1h per simbol kini HANYA untuk RSI14
                # (lapis kedua anti sell-bottom/buy-top). Filter exhaustion
                # & cooling v10.2.8 dicabut — digantikan BTC Regime Gate.
                # Fail-open bila data 1h tidak tersedia.
                _rsi1h: float | None = None
                _timing_ready = False
                if any(isinstance(s, dict) and s.get("side") for s in results):
                    try:
                        from market_data import get_crypto_snapshot as _g1h
                        from indicators import _rsi as _rsi_fn
                        _snap = await _g1h(sym, "1h")
                        _c1 = [float(c["close"]) for c in ((_snap or {}).get("candles") or [])
                               if c.get("close")]
                        if len(_c1) >= 16:
                            _rsi1h = _rsi_fn(_c1[:-1], 14)
                            _timing_ready = True
                    except Exception as _te:
                        logger.debug("rsi filter fetch %s gagal (fail-open): %s", sym, _te)
                best = None
                for sig in results:
                    if not isinstance(sig, dict) or not sig.get("side"):
                        continue
                    # v10.1.8 — Skip sinyal late-entry (lolos gate tampilan
                    # longgar tapi gagal gate eksekusi ketat 3-candle/1.5ATR).
                    if sig.get("late_entry"):
                        _dev_reject(rep, "late_entry")
                        continue
                    # v10.2.23 — COOLDOWN per-simbol setelah loss: simbol
                    # yang baru rugi <4 jam tidak boleh di-entry ulang
                    # (anti revenge-entry SAND 18/10: LONG 3× beruntun,
                    # SL semua). BTC juga tunduk — revenge-entry di BTC
                    # sama berbahayanya.
                    if sym in _sym_loss_cd:
                        _dev_reject(
                            rep, f"cooldown_loss_{sym}_<{SYMBOL_LOSS_COOLDOWN_HOURS}h")
                        continue
                    # v10.2.24 — Simbol tidak terdaftar di jaringan aktif
                    # (mis. ICP di testnet): skip dini, jangan pakai slot
                    # konfirmasi / spam log tiap siklus.
                    if f"{net}:{sym}" in _UNAVAILABLE_SYMS:
                        _dev_reject(
                            rep,
                            f"symbol_{sym}_tidak_tersedia_di_"
                            f"{'testnet' if net else 'mainnet'}")
                        continue
                    # v10.2.25 — SIDE CONCURRENCY: batasi N posisi OPEN
                    # per arah (BUY/SELL) agar tidak terjadi correlated
                    # loss saat regime flip melepas banyak sinyal
                    # serentak (kasus 18/10 14:02-14:09 UTC: 7 SHORT
                    # masuk dalam 8 menit, satu bounce BTC → semua
                    # tertekan). Hitung dari asi_trades.status=open
                    # (soft-delete sudah dikecualikan).
                    try:
                        _open_side = await db.asi_trades.count_documents({
                            "device_id": device_id, "status": "open",
                            "side": sig["side"],
                            "deleted": {"$ne": True},
                        })
                        if _open_side >= MAX_OPEN_PER_SIDE:
                            _dev_reject(
                                rep,
                                f"max_open_{sig['side'].lower()}_{_open_side}_>=_{MAX_OPEN_PER_SIDE}")
                            continue
                    except Exception as _co_err:
                        logger.debug("side-concurrency check gagal: %s", _co_err)
                    # v10.2.12 — BTC REGIME GATE: rezim BTC menentukan arah
                    # yang boleh dieksekusi untuk ALTCOIN (BTC sendiri
                    # dikecualikan — ia referensi, bukan ikutan). Rezim
                    # bullish_reversal/trending_up → blokir SELL;
                    # bearish_reversal/trending_down → blokir BUY.
                    if sym != "BTC":
                        if sig["side"] == "SELL" and gate_block_sell:
                            _dev_reject(rep, f"btc_regime {btc_regime['regime']}: tolak SELL")
                            continue
                        if sig["side"] == "BUY" and gate_block_buy:
                            _dev_reject(rep, f"btc_regime {btc_regime['regime']}: tolak BUY")
                            continue
                        # v10.2.29 — ANTI-FLAP DICABUT (keputusan user):
                        # menahan BUY 3 siklus setelah BTC flip
                        # trending_up membuat bot kehilangan momentum
                        # awal rally ("saat BTC naik alt harus langsung
                        # bisa LONG"). Begitu rezim trending_up, BUY
                        # langsung boleh dievaluasi — proteksi palsu-
                        # bounce tetap ada di lapis lain (konfirmasi 2
                        # siklus, anti-chase, RSI, trend filter 4H).
                    # v10.2.17 — BTC base 4H BEAR: BUY tetap BOLEH (bukan
                    # blokir total) tapi min confidence +BEAR4H_CONF_BONUS
                    # poin (keputusan user: jalan tengah, 90→95).
                    _bear4h_buy = (sig["side"] == "BUY"
                                   and btc_regime.get("base_regime") == "BEAR")
                    _eff_min_conf = user_min_conf + (
                        BEAR4H_CONF_BONUS if _bear4h_buy else 0)
                    if int(sig.get("confidence") or 0) < _eff_min_conf:
                        _dev_reject(rep, f"conf<{_eff_min_conf}"
                                    + ("_bear4h" if _bear4h_buy else ""))
                        continue
                    # v10.2.12 — RSI per-aset DIPERTAHANKAN sebagai lapis
                    # kedua (anti sell-bottom/buy-top aset volatile).
                    # Filter exhaustion & cooling v10.2.8 DICABUT — sudah
                    # digantikan BTC Regime Gate di hulu.
                    if _timing_ready:
                        _wl = sig["side"] == "BUY"
                        if _rsi1h is not None:
                            # v10.2.31 — Ambang RSI 1h dilonggarkan dari
                            # 65/35 → 72/28 (keputusan user: crypto rutin
                            # bergerak di RSI 70-80 saat trending; 65
                            # terlalu ketat sehingga alt di rally awal
                            # pun langsung terblokir — kasus ARB 69).
                            if not _wl and _rsi1h < 28:
                                _dev_reject(rep, f"RSI1h {_rsi1h:.0f}<28 oversold: tolak SELL")
                                continue
                            if _wl and _rsi1h > 72:
                                _dev_reject(rep, f"RSI1h {_rsi1h:.0f}>72 overbought: tolak BUY")
                                continue
                    sigs_found += 1
                    rep["signals"] = int(rep.get("signals") or 0) + 1
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
                    _dev_reject(rep, "level_tidak_valid")
                    continue
                # Guard: skip if an OPEN/pending trade on same symbol exists.
                dup = await db.asi_trades.find_one(
                    {"device_id": device_id, "symbol": sym,
                     "status": {"$in": ["open", "pending_entry"]}}
                )
                if dup:
                    _dev_reject(rep, "sudah_ada_posisi")
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
                    _dev_reject(rep, "cooldown_15menit")
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
                        # v10.2.22 — RELAKSASI SLOPE SAAT BTC TERKONFIRMASI
                        # (keputusan user, kasus 16–18/10: 3 hari 0 BUY
                        # padahal BTC V-reversal). EMA50 4H ≈ memori 8 hari
                        # sehingga slope-nya tetap turun lama setelah dump,
                        # memblokir semua LONG meski harga sudah kembali di
                        # atas EMA50.
                        # v10.2.29 — Relaksasi LONG dipercepat (keputusan
                        # user): aktif SEGERA saat BTC trending_up (tanpa
                        # menunggu streak 3) — LONG cukup butuh harga >
                        # EMA50. SHORT tetap menunggu streak 3 (sisi SELL
                        # tidak diubah).
                        _long_relaxed = btc_regime["regime"] == "trending_up"
                        _short_relaxed = trend_down_streak >= TREND_UP_MIN_CYCLES
                        if want_long and (not bias_up
                                          or (slope_dn and not _long_relaxed)):
                            logger.info("full-auto trend-filter skip %s/%s: "
                                        "LONG ditolak (price%sEMA50 %.4f, slope %s, btc_up_streak=%d)",
                                        device_id, sym,
                                        ">" if bias_up else "<", ema50_4h,
                                        "turun" if slope_dn else "naik/datar",
                                        trend_up_streak)
                            _dev_reject(rep, "trend_filter_4h_blokir_LONG")
                            continue
                        if not want_long and (bias_up
                                              or (slope_up and not _short_relaxed)):
                            logger.info("full-auto trend-filter skip %s/%s: "
                                        "SHORT ditolak (price%sEMA50 %.4f, slope %s, btc_dn_streak=%d)",
                                        device_id, sym,
                                        ">" if bias_up else "<", ema50_4h,
                                        "naik" if slope_up else "turun/datar",
                                        trend_down_streak)
                            _dev_reject(rep, "trend_filter_4h_blokir_SHORT")
                            continue
                except Exception as _tf_err:
                    logger.debug("trend-filter error %s: %s", sym, _tf_err)
                # v10.2.21/v10.2.23 — MOMENTUM GUARDS dua arah (fetch 1h
                # snapshot SEKALI per sinyal, biasanya cache):
                #   • ANTI-CHASE SELL: SELL ditolak bila alt turun
                #     >3%/6 jam (short di dasar — kasus BCH 16/10).
                #   • ANTI-CHASE BUY (v10.2.23): BUY ditolak bila alt
                #     naik >3%/6 jam (long di puncak — kasus TIA 18/10
                #     entry di ujung candle +3,67%, sekarang -43% ROE).
                #   • DUMP GUARD BUY (v10.2.23): BUY ditolak bila alt
                #     turun >2,5%/2 jam (menangkap pisau jatuh — kasus
                #     SAND 18/10: LONG saat dump -3,4%/2 jam, SL 3×).
                # BTC dikecualikan (referensi; regim BTC sendiri sudah
                # di-gate di hulu).
                if sym != "BTC":
                    try:
                        from market_data import get_crypto_snapshot
                        snap1h = await get_crypto_snapshot(sym, "1h")
                        c1h = [float(c["close"]) for c in
                               ((snap1h or {}).get("candles") or [])
                               if c.get("close")]
                        if sig["side"] == "SELL":
                            n = min(SELL_CHASE_WINDOW_H, len(c1h) - 1)
                            if n >= 2 and c1h[-1 - n] > 0:
                                chg_pct = (c1h[-1] - c1h[-1 - n]) / c1h[-1 - n] * 100
                                if chg_pct <= -SELL_CHASE_PCT:
                                    logger.info(
                                        "full-auto anti-chase skip %s/%s: SELL "
                                        "ditolak (turun %.2f%% dalam %dj, ambang -%.1f%%)",
                                        device_id, sym, chg_pct, n, SELL_CHASE_PCT)
                                    _dev_reject(
                                        rep,
                                        f"anti_chase_sell_{abs(chg_pct):.1f}pct_{n}h")
                                    continue
                            # v10.2.25 — SELL short-window dump guard
                            # (pelajaran 18/10 14:02-14:09 UTC: 7 SHORT
                            # di dasar bar -1 s/d -1,5%/1h → bounce →
                            # semua SL/BE). Lebih sensitif dari window
                            # 6h di atas.
                            n2 = min(SELL_SHORT_DUMP_WINDOW_H,
                                     len(c1h) - 1)
                            if n2 >= 2 and c1h[-1 - n2] > 0:
                                chg2 = (c1h[-1] - c1h[-1 - n2]) / c1h[-1 - n2] * 100
                                if chg2 <= -SELL_SHORT_DUMP_PCT:
                                    logger.info(
                                        "full-auto short-dump skip %s/%s: "
                                        "SELL ditolak (turun %.2f%% dalam %dj — dasar bar)",
                                        device_id, sym, chg2, n2)
                                    _dev_reject(
                                        rep,
                                        f"sell_short_dump_{abs(chg2):.1f}pct_{n2}h")
                                    continue
                        else:  # BUY
                            # v10.2.30 — ANTI-CHASE BUY ADAPTIF
                            # (keputusan user: "anti-chase harus relatif
                            # terhadap BTC, bukan absolut 3%/6h"):
                            # • BTC_6h < BUY_CHASE_PCT (3%)  → BTC masih
                            #   di fase awal rally; alt yang ikut naik
                            #   BELUM dianggap chasing → anti-chase
                            #   DIMATIKAN.
                            # • BTC_6h ≥ BUY_CHASE_PCT         → BTC
                            #   sudah bergerak signifikan; alt dianggap
                            #   chasing hanya bila OUTPACE BTC lebih
                            #   dari BUY_CHASE_PCT (gap relatif).
                            # Logika sebelumnya (absolut) menolak semua
                            # alt setelah BTC pump — bot melewatkan
                            # seluruh fase rally.
                            btc_6h = float(btc_regime.get("chg_6h") or 0.0)
                            n6 = min(BUY_CHASE_WINDOW_H, len(c1h) - 1)
                            if n6 >= 2 and c1h[-1 - n6] > 0:
                                chg6 = (c1h[-1] - c1h[-1 - n6]) / c1h[-1 - n6] * 100
                                _btc_late = btc_6h >= BUY_CHASE_PCT
                                _rel_gap = chg6 - btc_6h
                                if _btc_late and _rel_gap >= BUY_CHASE_PCT:
                                    logger.info(
                                        "full-auto anti-chase skip %s/%s: "
                                        "alt +%.2f%% vs BTC +%.2f%% (gap "
                                        "+%.2f%%) — alt chasing di puncak",
                                        device_id, sym, chg6, btc_6h, _rel_gap)
                                    _dev_reject(
                                        rep,
                                        f"anti_chase_buy_rel_{_rel_gap:.1f}pct_vs_btc")
                                    continue
                            n2 = min(BUY_DUMP_GUARD_WINDOW_H, len(c1h) - 1)
                            if n2 >= 2 and c1h[-1 - n2] > 0:
                                chg2 = (c1h[-1] - c1h[-1 - n2]) / c1h[-1 - n2] * 100
                                if chg2 <= -BUY_DUMP_GUARD_PCT:
                                    logger.info(
                                        "full-auto dump-guard skip %s/%s: BUY "
                                        "ditolak (turun %.2f%% dalam %dj — pisau jatuh)",
                                        device_id, sym, chg2, n2)
                                    _dev_reject(
                                        rep,
                                        f"buy_dump_guard_{abs(chg2):.1f}pct_{n2}h")
                                    continue
                    except Exception as _ac_err:
                        logger.debug("momentum-guard error %s: %s", sym, _ac_err)
                # v10.2.17/v10.2.21 — KONFIRMASI SINYAL 2 SIKLUS. Awalnya
                # hanya BUY (anti-flap BTC trending_up); kini SIMETRIS
                # untuk SELL juga karena base BTC 4H BEAR berkepanjangan
                # memicu banyak sinyal SELL yang terkadang over-aggressive.
                # Sinyal yang SAMA (device+symbol+side+fingerprint
                # engine/formula) harus muncul 2 siklus scanner berturut-
                # turut sebelum dieksekusi. Siklus pertama hanya MENCATAT
                # kandidat; eksekusi terjadi di siklus kedua. State di
                # Mongo (tahan restart). Fail-CLOSED bila DB state error.
                _confirm_key: str | None = None
                if sig["side"] in ("BUY", "SELL"):
                    _confirm_key = f"{device_id}:{sym}:{sig['side']}"
                    _fprint = (f"{sig.get('profile') or ''}|"
                               f"{sig.get('formula_tag') or ''}")
                    _now_cf = datetime.now(timezone.utc)
                    _req_cycles = (BUY_CONFIRM_CYCLES if sig["side"] == "BUY"
                                   else SELL_CONFIRM_CYCLES)
                    try:
                        _doc_cf = await db.asi_buy_confirm.find_one(
                            {"_id": _confirm_key})
                        _confirmed, _cnt = _buy_confirm_eval(
                            _doc_cf, fingerprint=_fprint, now=_now_cf,
                            window_s=SCANNER_INTERVAL * 2,
                            required_cycles=_req_cycles)
                        await db.asi_buy_confirm.update_one(
                            {"_id": _confirm_key},
                            {"$set": {
                                "device_id": device_id, "symbol": sym,
                                "side": sig["side"],
                                "fingerprint": _fprint, "count": _cnt,
                                "confidence": int(sig.get("confidence") or 0),
                                "last_seen_at": _now_cf.isoformat()}},
                            upsert=True)
                    except Exception as _cf_err:
                        # Fail-CLOSED untuk BUY/SELL: gagal baca state →
                        # anggap belum terkonfirmasi (lebih aman daripada
                        # double-exec saat Mongo blip).
                        logger.debug("signal-confirm state error %s: %s", sym, _cf_err)
                        _confirmed, _cnt = False, 1
                    if not _confirmed:
                        logger.info("full-auto %s %s/%s menunggu konfirmasi "
                                    "siklus %d (fingerprint %s)",
                                    sig["side"], device_id, sym, _req_cycles, _fprint)
                        _dev_reject(
                            rep,
                            ("buy" if sig["side"] == "BUY" else "sell")
                            + f"_menunggu_konfirmasi_siklus_{_req_cycles}")
                        continue
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
                    _dev_reject(rep, f"execute_error: {str(e)[:60]}")
                    await _release_claim()
                    continue
                if not res.get("ok"):
                    # v10.1.2 — Log alasan skip supaya tidak jadi black box.
                    logger.info("full-auto skip %s/%s: %s | %s", device_id, sym,
                                res.get("reason"), str(res.get("message") or "")[:120])
                    # v10.2.24 — Simbol yang tidak terdaftar di jaringan
                    # aktif (mis. ICP tidak ada di Binance Futures TESTNET)
                    # tidak akan pernah berhasil berapapun kali dicoba.
                    # Masukkan ke set tidak-tersedia per (jaringan) supaya
                    # siklus berikutnya skip dini tanpa memakai slot
                    # konfirmasi & spam log. Reset saat backend restart.
                    if res.get("reason") == "symbol_filters_missing":
                        _UNAVAILABLE_SYMS.add(f"{net}:{sym}")
                    _dev_reject(rep, f"execute_ditolak: {res.get('reason')}")
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
                # v10.2.17 — BUY terkonfirmasi & tereksekusi → reset state
                # konfirmasi supaya sinyal berikutnya mulai dari siklus 1.
                if _confirm_key:
                    try:
                        await db.asi_buy_confirm.update_one(
                            {"_id": _confirm_key},
                            {"$set": {"count": 0,
                                      "consumed_at": datetime.now(
                                          timezone.utc).isoformat()}})
                    except Exception:
                        pass
                placed += 1
                rep["placed"] = int(rep.get("placed") or 0) + 1
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
             "placed": total_placed,
             # v10.2.12 — Rezim BTC gate siklus ini (untuk scan-debug UI).
             "btc_regime": btc_regime.get("regime"),
             "btc_regime_detail": btc_regime.get("detail"),
             # v10.2.17 — state anti-loss BUY gates (audit via scan-debug).
             "btc_base_regime_4h": btc_regime.get("base_regime"),
             "btc_trend_up_streak": trend_up_streak,
             "btc_trend_down_streak": trend_down_streak,
             "buy_gates": {
                 "trend_up_min_cycles": TREND_UP_MIN_CYCLES,
                 "bear4h_conf_bonus": BEAR4H_CONF_BONUS,
                 "buy_confirm_cycles": BUY_CONFIRM_CYCLES,
                 "sell_confirm_cycles": SELL_CONFIRM_CYCLES,
                 "sell_chase_pct": SELL_CHASE_PCT,
                 "sell_chase_window_h": SELL_CHASE_WINDOW_H,
                 "longterm_stale_hours": LONGTERM_STALE_HOURS,
                 "longterm_stale_min_profit_pct": LONGTERM_STALE_MIN_PROFIT_PCT,
                 # v10.2.22 — relaksasi slope trend-filter 4H saat BTC
                 # terkonfirmasi (streak ≥ TREND_UP_MIN_CYCLES).
                 "trend4h_slope_relax_on_confirmed_btc": True,
                 # v10.2.23 — paket anti-loss BUY + breaker tangguh.
                 "buy_chase_pct": BUY_CHASE_PCT,
                 "buy_chase_window_h": BUY_CHASE_WINDOW_H,
                 # v10.2.30 — anti-chase BUY sekarang RELATIF terhadap
                 # BTC: hanya aktif saat BTC_6h ≥ buy_chase_pct DAN alt
                 # outpace BTC >= buy_chase_pct (gap). Field berikut
                 # memaparkan BTC 6h change aktual siklus ini.
                 "buy_chase_mode": "relative_to_btc",
                 "btc_chg_6h": round(float(btc_regime.get("chg_6h") or 0.0), 2),
                 "buy_dump_guard_pct": BUY_DUMP_GUARD_PCT,
                 "buy_dump_guard_window_h": BUY_DUMP_GUARD_WINDOW_H,
                 "circuit_breaker_losses": CIRCUIT_BREAKER_LOSSES,
                 "circuit_breaker_pause_hours": CIRCUIT_BREAKER_PAUSE_HOURS,
                 "symbol_loss_cooldown_hours": SYMBOL_LOSS_COOLDOWN_HOURS,
                 # v10.2.25 — pelajaran 7 SHORT serentak 18/10.
                 "sell_short_dump_pct": SELL_SHORT_DUMP_PCT,
                 "sell_short_dump_window_h": SELL_SHORT_DUMP_WINDOW_H,
                 "max_open_per_side": MAX_OPEN_PER_SIDE,
             },
             # v10.2.7 — per-device diagnostics (maks 20 device agar doc
             # tetap kecil; cukup untuk menjawab "kenapa bot saya tidak
             # eksekusi").
             "devices": dict(list(device_reports.items())[:20])},
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
        ]
        logger.info("ASI-Bot scheduler started: watcher + pnl + scanner + titan_relay")

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

