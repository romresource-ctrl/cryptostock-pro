"""ASI-Bot — Execution Engine (Phase 2).

v9.9.2 — BINANCE PATH DITULIS ULANG untuk menghilangkan "false positive
native SL/TP". Alur baru:
  1. Validasi symbol dinamis via exchangeInfo (TRADING + USDT perp).
  2. Set/verify margin mode via REST signed langsung (bukan CCXT yang
     menelan error) — jika gagal diset ke yang user minta DAN posisi
     sudah ada di mode berbeda, entry DIBATALKAN sebelum fire.
  3. Set leverage via REST.
  4. Place MARKET entry via REST.
  5. Poll position_risk sampai positionAmt > 0 (max 10x 0.3s).
  6. Place SL (STOP_MARKET closePosition=true) via Algo API.
  7. VERIFY SL dengan GET /openAlgoOrders — bila algoId yang baru dibuat
     tidak terlihat → EMERGENCY MARKET CLOSE + jangan simpan trade.
  8. Place TP1..TPn (TAKE_PROFIT_MARKET + quantity) via Algo API.
  9. VERIFY semua TP di openAlgoOrders.
 10. Baca ulang position_risk untuk mendapat actual_margin_mode & entry.
 11. Simpan trade dengan bracket_type="hard" & actual_margin_mode.

Jika STEP 6/7 (SL) GAGAL → auto-rollback: cancel all algo + MARKET close
posisi + return error. Trade TIDAK pernah disimpan dalam keadaan tanpa
proteksi (user requirement v9.9.2).

Jika STEP 8/9 (TP) sebagian gagal → SL sudah terpasang (risk terbatas),
tapi karena user minta "tidak boleh ada status unprotected sama sekali",
kita retry 2x per-TP; bila masih gagal → emergency rollback juga.

Non-Binance exchanges tetap memakai CCXT path lama (akan diaudit terpisah).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from .crypto import decrypt
from .exchanges import _build
from .algo import (
    cancel_all_conditional,
    cancel_conditional_order,  # noqa: F401
    list_open_conditional,     # noqa: F401
    new_conditional_order,
    new_trailing_stop_order,
)
from . import binance_rest as br
from .whitelist import binance_symbol_filters, round_to_step, round_to_tick

logger = logging.getLogger("asi_bot.engine")

Side = Literal["BUY", "SELL"]
# v9.9.14 — Entry LIMIT MODERATE (keputusan user): bot TIDAK eksekusi
# MARKET. Order limit di harga entry moderate sinyal menunggu maksimal
# 2 candle (sinyal bot = 1h) lalu dibatalkan otomatis oleh scheduler.
ENTRY_LIMIT_TTL_SEC = 7200
# v9.6.0 — split dinamis mengikuti jumlah TP yang user pilih.
TP_SPLITS: dict[int, tuple[float, ...]] = {
    1: (1.0,),
    2: (0.5, 0.5),
    3: (1 / 3, 1 / 3, 1 / 3),  # TP3 kebagian sisa step-aligned remainder
}


def _split_tp_qty(qty: float, step: float | None,
                  n_targets: int = 3) -> list[float]:
    """Split qty across TP1..TPn, aligned to the market's amount step.

    v9.6.0 — jumlah TP sekarang user-driven (1 / 2 / 3). Memakai integer
    step-units supaya tiap potongan adalah kelipatan pasti dari `step`
    dan jumlahnya selalu sama dengan step-floored `qty`. Potongan yang
    bulat 0 digabung ke TP berikutnya supaya posisi kecil tetap ketutup.
    """
    n = max(1, min(3, int(n_targets)))
    weights = TP_SPLITS[n]
    if step and step > 0:
        import math
        units = int(math.floor(qty / step + 1e-9))
        if units <= 0:
            return [0.0] * n
        u = [int(units * w) for w in weights]
        # sisa akibat flooring → TP terakhir
        u[-1] = units - sum(u[:-1])
        parts = [round(x * step, 10) for x in u]
    else:
        parts = [qty * w for w in weights]
    for i in range(len(parts) - 1):
        if parts[i] <= 0:
            parts[i + 1] = round(parts[i + 1] + parts[i], 10)
            parts[i] = 0.0
    return parts


def _ccxt_side(side: Side) -> str:
    return "buy" if side == "BUY" else "sell"


def _opposite(side: Side) -> str:
    return "sell" if side == "BUY" else "buy"


def _sl_params(exchange: str, stop_loss: float, qty: float) -> dict[str, Any]:
    """Per-exchange STOP_MARKET params. Returns dict ready for ccxt.create_order."""
    if exchange == "binance":
        # closePosition=True → close FULL position when triggered, no qty needed.
        # workingType=MARK_PRICE → avoid wick-liquidations on last-price spikes.
        return {
            "stopPrice": float(stop_loss),
            "closePosition": True,
            "workingType": "MARK_PRICE",
            "timeInForce": "GTE_GTC",
        }
    if exchange == "bybit":
        return {
            "triggerPrice": float(stop_loss),
            "reduceOnly": True,
            "triggerBy": "MarkPrice",
        }
    if exchange == "okx":
        return {
            "stopLossPrice": float(stop_loss),
            "reduceOnly": True,
        }
    if exchange == "bitget":
        return {
            "triggerPrice": float(stop_loss),
            "reduceOnly": True,
            "triggerType": "mark_price",
        }
    return {"stopPrice": float(stop_loss), "reduceOnly": True}


def _tp_params(exchange: str, tp_price: float, qty: float) -> dict[str, Any]:
    """Per-exchange TAKE_PROFIT_MARKET params (partial close, split 40/30/30)."""
    if exchange == "binance":
        return {
            "stopPrice": float(tp_price),
            "reduceOnly": True,
            "workingType": "MARK_PRICE",
            "timeInForce": "GTE_GTC",
        }
    if exchange == "bybit":
        return {
            "triggerPrice": float(tp_price),
            "reduceOnly": True,
            "triggerBy": "MarkPrice",
        }
    if exchange == "okx":
        return {
            "takeProfitPrice": float(tp_price),
            "reduceOnly": True,
        }
    if exchange == "bitget":
        return {
            "triggerPrice": float(tp_price),
            "reduceOnly": True,
            "triggerType": "mark_price",
        }
    return {"stopPrice": float(tp_price), "reduceOnly": True}


async def _get_client(doc: dict[str, Any]):
    return _build(
        doc["exchange"],
        decrypt(doc["api_key_enc"]),
        decrypt(doc["api_secret_enc"]),
        decrypt(doc["password_enc"]) if doc.get("password_enc") else None,
        bool(doc.get("testnet", True)),
    )


async def resolve_credential(
    db: Any, device_id: str, exchange: str, testnet: bool | None = None,
) -> dict[str, Any] | None:
    """v9.9.5 — Dual-slot credential: mainnet & testnet disimpan TERPISAH
    per exchange (_id = device:exchange:mainnet|testnet) sehingga user
    tidak perlu input ulang API key saat pindah jaringan.

    Resolusi:
      1. Slot spesifik untuk network yang diminta.
      2. Legacy doc pre-v9.9.5 (device:exchange tanpa suffix) — hanya
         dipakai bila network-nya COCOK (atau testnet=None). Saat cocok,
         doc otomatis di-migrate (disalin) ke slot baru.
      3. None → caller menampilkan "hubungkan API untuk jaringan ini".
    """
    exchange = (exchange or "").lower()
    if testnet is not None:
        net = "testnet" if testnet else "mainnet"
        doc = await db.asi_credentials.find_one({"_id": f"{device_id}:{exchange}:{net}"})
        if doc:
            return doc
    legacy = await db.asi_credentials.find_one({"_id": f"{device_id}:{exchange}"})
    if legacy:
        legacy_net = bool(legacy.get("testnet", True))
        if testnet is None or legacy_net == bool(testnet):
            # Lazy-migrate ke slot baru supaya konsisten ke depan.
            net = "testnet" if legacy_net else "mainnet"
            slot_id = f"{device_id}:{exchange}:{net}"
            try:
                if not await db.asi_credentials.find_one({"_id": slot_id}):
                    await db.asi_credentials.insert_one({**legacy, "_id": slot_id})
            except Exception:
                pass
            return legacy
        return None  # network tidak cocok → jangan pakai key jaringan lain
    # Tidak ada legacy doc & network tidak ditentukan → pakai slot apa pun
    # yang tersedia (kasus device baru yang hanya punya slot v9.9.5).
    if testnet is None:
        for net in ("mainnet", "testnet"):
            doc = await db.asi_credentials.find_one({"_id": f"{device_id}:{exchange}:{net}"})
            if doc:
                return doc
    return None


async def _fetch_usdt_balance(client) -> float:
    bal = await client.fetch_balance()
    free = (bal.get("USDT") or {}).get("free")
    if free is not None:
        return float(free)
    total = (bal.get("total") or {}).get("USDT")
    return float(total or 0.0)


def _ccxt_symbol(exchange: str, base: str) -> str:
    base = base.upper().split("/")[0].split("USDT")[0].split("-")[0]
    if exchange == "binance":
        return f"{base}/USDT:USDT"
    if exchange == "bybit":
        return f"{base}/USDT:USDT"
    if exchange == "okx":
        return f"{base}-USDT-SWAP"
    if exchange == "bitget":
        return f"{base}/USDT:USDT"
    return f"{base}/USDT"


async def _ensure_tradable(client: Any, exch_sym: str, base: str) -> tuple[str, str] | None:
    """v9.8.2 — Validasi dinamis menggantikan whitelist statis Top-100.

    Simbol boleh dieksekusi SELAMA benar-benar terdaftar sebagai market
    aktif di exchange user (Binance/Bybit/OKX/Bitget).

    Return (reason_code, fallback_message) bila tidak valid, None bila valid.
    reason_code: "not_listed" | "market_inactive" — dipetakan ke pesan
    terlokalisasi di frontend. Jika load_markets gagal (network hiccup),
    kita TIDAK memblokir — biarkan order placement exchange yang memvalidasi.
    """
    try:
        markets = await client.load_markets()
    except Exception:
        return None
    m = markets.get(exch_sym)
    if not m:
        return ("not_listed",
                f"{base} tidak tersedia sebagai perpetual USDT di exchange ini.")
    if m.get("active") is False:
        return ("market_inactive",
                f"{base} sedang tidak aktif di exchange ini.")
    return None


async def preview_trade(
    doc: dict[str, Any], symbol: str, side: Side,
    entry: float, stop_loss: float, tps: list[float],
    risk_pct: float, leverage: int,
    tp_count: int = 3,
) -> dict[str, Any]:
    """Hitung besaran margin & qty TANPA eksekusi — untuk Semi-Auto preview."""
    risk_pct = max(1.0, min(30.0, float(risk_pct)))
    leverage = max(1, min(125, int(leverage)))
    tp_count = max(1, min(3, int(tp_count)))
    client = await _get_client(doc)
    exch_sym = _ccxt_symbol(doc["exchange"], symbol)
    try:
        # v9.8.2 — validasi dinamis ke daftar pasar exchange (bukan whitelist statis)
        bad = await _ensure_tradable(client, exch_sym, symbol)
        if bad:
            return {"ok": False, "reason": bad[0], "message": bad[1]}
        bal = await _fetch_usdt_balance(client)
        margin = round(bal * risk_pct / 100.0, 2)
        size_usdt = round(margin * leverage, 2)
        # v9.8.8 — Tolak sejak PREVIEW bila ukuran posisi di bawah
        # min-notional exchange (Binance -4164). User langsung tahu harus
        # menaikkan Risk % / Leverage, bukan gagal 500 saat EXECUTE.
        m = client.markets.get(exch_sym) or {}
        min_cost = ((m.get("limits") or {}).get("cost") or {}).get("min")
        if isinstance(min_cost, (int, float)) and min_cost and size_usdt < float(min_cost):
            return {
                "ok": False, "reason": "min_notional",
                "min_notional": float(min_cost),
                "balance_usdt": round(bal, 2), "margin_usdt": margin,
                "size_usdt": size_usdt, "qty": 0,
                "leverage": leverage, "risk_pct": risk_pct,
                "est_loss_usdt": 0, "tp_estimations": [],
                "message": (f"Ukuran posisi ${size_usdt:.2f} di bawah minimum "
                            f"exchange (${float(min_cost):.2f}). Naikkan Risk % atau Leverage."),
            }
    finally:
        await client.close()
    margin = round(bal * risk_pct / 100.0, 2)
    size_usdt = margin * leverage
    qty = size_usdt / entry if entry > 0 else 0
    risk_per_unit = abs(entry - stop_loss)
    est_loss = round(risk_per_unit * qty, 2)
    weights = TP_SPLITS[tp_count]
    tp_est = []
    for i, tp in enumerate(tps[:tp_count]):
        delta = abs(tp - entry)
        tp_qty = qty * weights[i]
        tp_est.append({
            "tp": tp, "qty_share": weights[i],
            "est_profit_usdt": round(delta * tp_qty, 2),
        })
    return {
        "ok": True, "balance_usdt": round(bal, 2), "margin_usdt": margin,
        "size_usdt": round(size_usdt, 2), "qty": qty,
        "leverage": leverage, "risk_pct": risk_pct, "tp_count": tp_count,
        "est_loss_usdt": est_loss, "tp_estimations": tp_est,
    }


async def execute_trade(
    doc: dict[str, Any], symbol: str, side: Side,
    entry: float, stop_loss: float, tps: list[float],
    risk_pct: float, leverage: int, mode: str = "semi",
    tp_count: int = 3,
    trailing_callback_rate: float = 2.0,
    margin_mode: str = "isolated",
    profile: str | None = None,
    formula_tag: str | None = None,
) -> dict[str, Any]:
    """v9.9.2 — Place entry + VERIFIED bracket SL/TP. Auto-rollback jika
    bracket tidak dapat terpasang & terverifikasi di exchange.

    Return record untuk asi_trades, atau {ok:false, reason, message}
    jika entry/bracket ditolak (posisi sudah ditutup di sisi exchange).
    """
    risk_pct = max(1.0, min(30.0, float(risk_pct)))
    leverage = max(1, min(125, int(leverage)))
    tp_count = max(1, min(3, int(tp_count)))
    tps = list(tps or [])[:tp_count]
    margin_mode = "cross" if str(margin_mode).lower() == "cross" else "isolated"
    exchange = (doc.get("exchange") or "binance").lower()

    # Non-Binance path → fallback ke CCXT lama (unchanged)
    if exchange != "binance":
        return await _execute_ccxt_fallback(
            doc, symbol, side, entry, stop_loss, tps,
            risk_pct, leverage, mode, tp_count,
            trailing_callback_rate, margin_mode, profile, formula_tag,
        )

    # ── BINANCE DIRECT REST PATH ─────────────────────────────────────
    api_key = decrypt(doc["api_key_enc"])
    api_secret = decrypt(doc["api_secret_enc"])
    is_testnet = bool(doc.get("testnet", True))
    base = symbol.upper().split("/")[0].split("USDT")[0].split("-")[0]
    bin_sym = base + "USDT"

    # (1) Market filters (tick/step/minNotional)
    filters = await binance_symbol_filters() or {}
    f = filters.get(base) or {}
    tick = float(f.get("tick") or 0.0)
    step = float(f.get("step") or 0.0)
    if tick <= 0 or step <= 0:
        return {"ok": False, "reason": "symbol_filters_missing",
                "message": f"Filter tick/step {bin_sym} tidak ditemukan. Coba ulang beberapa detik lagi."}

    # (2) Margin mode: baca posisi saat ini (bisa Nil) → set target
    try:
        pos = await br.position_risk(api_key, api_secret, is_testnet, bin_sym)
    except Exception as e:
        return {"ok": False, "reason": "exchange_unreachable",
                "message": f"Tidak bisa membaca status posisi: {str(e)[:160]}"}

    existing_amt = float((pos or {}).get("positionAmt") or 0)
    current_mt = str((pos or {}).get("marginType") or "").lower()  # "cross"|"isolated"
    desired_mt_upper = "ISOLATED" if margin_mode == "isolated" else "CROSSED"
    layering = False
    if abs(existing_amt) > 0:
        # Posisi SUDAH ADA → tidak bisa ganti margin mode. HARUS cocok.
        if current_mt and current_mt != margin_mode:
            return {
                "ok": False, "reason": "margin_mode_mismatch",
                "requested": margin_mode, "actual": current_mt,
                "message": (
                    f"{bin_sym} punya posisi {current_mt.upper()} aktif. "
                    f"Tidak bisa buka trade baru dalam mode {margin_mode.upper()}. "
                    "Tutup posisi dulu atau pilih margin mode yang sama."
                ),
            }
        # v9.9.4 — LAYERING (averaging): hanya boleh searah. Sinyal
        # berlawanan arah pada posisi terbuka akan mengurangi/menutup
        # posisi user secara tidak terduga di one-way mode → TOLAK.
        existing_side = "BUY" if existing_amt > 0 else "SELL"
        if existing_side != side:
            return {
                "ok": False, "reason": "opposite_position",
                "message": (
                    f"Posisi {'LONG' if existing_side == 'BUY' else 'SHORT'} {bin_sym} "
                    "masih aktif. Eksekusi berlawanan arah akan MENGURANGI posisi Anda "
                    "(one-way mode). Tutup posisi dulu bila ingin ganti arah."
                ),
            }
        layering = True
    else:
        # Posisi kosong → set margin type sesuai permintaan user.
        set_mt = await br.set_margin_type(
            api_key, api_secret, is_testnet,
            symbol=bin_sym, margin_type=desired_mt_upper,
        )
        if not set_mt.get("ok"):
            return {
                "ok": False, "reason": "margin_mode_set_failed",
                "requested": margin_mode,
                "message": f"Gagal set margin mode {margin_mode.upper()}: {set_mt.get('msg')}",
            }
        # v9.9.10 — Posisi flat: bersihkan bracket BASI dari posisi lama
        # yang sudah tertutup (SL/TP closePosition sisa, baik algo maupun
        # legacy). Tanpa ini, penempatan SL closePosition baru ditolak
        # Binance dengan -4130 ("an open stop order with closePosition in
        # the direction is existing") → entry jadi gagal/rollback.
        try:
            await br.cancel_all_algo(api_key, api_secret, is_testnet, bin_sym)
        except Exception:
            pass
        try:
            await br.cancel_all_legacy(api_key, api_secret, is_testnet, bin_sym)
        except Exception:
            pass

    # (3) Set leverage. Binance bisa menolak bila melebihi tier notional
    # (mis. request 50x tapi posisi $12k hanya boleh 20x) → error -4028.
    # Tidak fatal: kita lanjut dan baca leverage AKTUAL dari positionRisk
    # setelah entry; UI akan menampilkan angka asli + catatan.
    lev_rejected: str | None = None
    try:
        lev_res = await br.set_leverage(api_key, api_secret, is_testnet,
                                        symbol=bin_sym, leverage=leverage)
        if not lev_res.get("ok"):
            lev_rejected = str(lev_res.get("error"))[:160]
    except Exception as e:
        lev_rejected = str(e)[:160]
        logger.debug("set_leverage %s: %s", bin_sym, e)

    # (4) Compute qty from balance & risk
    try:
        bal = await br.available_usdt(api_key, api_secret, is_testnet)
    except Exception as e:
        return {"ok": False, "reason": "balance_fetch_failed",
                "message": str(e)[:200]}
    margin = bal * risk_pct / 100.0
    size_usdt = margin * leverage
    qty_raw = size_usdt / entry if entry > 0 else 0.0
    qty = round_to_step(qty_raw, step)
    if qty <= 0:
        return {"ok": False, "reason": "qty_zero",
                "message": "Margin terlalu kecil utk 1 step kontrak. Naikkan Risk% / Leverage."}

    # Min notional check (approx — Binance default $5-$20 for USD-M)
    notional = qty * entry
    if notional < 5.0:
        return {"ok": False, "reason": "min_notional",
                "min_notional": 5.0,
                "message": f"Nilai posisi ${notional:.2f} di bawah minimum $5. Naikkan Risk%/Leverage."}

    # Round trigger prices to tick
    sl_price = round_to_tick(float(stop_loss), tick)
    tps_rounded = [round_to_tick(float(t), tick) for t in tps]

    # Validate SL direction vs side (avoid instant trigger)
    close_side = "SELL" if side == "BUY" else "BUY"

    # (5) Place LIMIT entry di harga sinyal MODERATE (v9.9.14). Bot tidak
    # eksekusi MARKET — entry limit di -0.5xATR (Confluence) / -0.3xATR
    # (VWAP) dari harga; expire 2 candle bila tidak terisi. SL/TP sudah
    # di-shift oleh signal fetcher ke anchor moderate → R:R & ladder utuh.
    limit_px = round_to_tick(float(entry), tick)
    try:
        entry_res = await br.limit_order(
            api_key, api_secret, is_testnet,
            symbol=bin_sym, side=side, quantity=qty, price=limit_px,
        )
    except Exception as e:
        return {"ok": False, "reason": "entry_rejected",
                "message": f"Entry LIMIT ditolak Binance: {str(e)[:200]}"}

    entry_order_id = entry_res.get("orderId")

    # (6) Poll singkat status order: limit "marketable" (harga sudah
    # melewati level sinyal) terisi instan → lanjut pasang bracket di
    # bawah. Bila belum FILLED → simpan sebagai pending_entry; scheduler
    # memantau fill/expiry dan memasang bracket setelah fill.
    filled_now = False
    for _ in range(6):
        await asyncio.sleep(0.4)
        try:
            st = await br.order_status(
                api_key, api_secret, is_testnet,
                symbol=bin_sym, order_id=entry_order_id)
            filled_now = str(st.get("status")) == "FILLED"
        except Exception:
            filled_now = False
        if filled_now:
            break

    if not filled_now:
        now_p = datetime.now(timezone.utc)
        expire_p = now_p + timedelta(seconds=ENTRY_LIMIT_TTL_SEC)
        return {
            "ok": True, "pending": True, "exchange": "binance",
            "testnet": is_testnet,
            "symbol": base, "ccxt_symbol": f"{base}/USDT:USDT", "side": side,
            "entry_order_id": entry_order_id,
            "sl_order_id": None,
            "tp_order_ids": [None] * tp_count,
            "entry_price": limit_px,
            "stop_loss": sl_price, "take_profits": tps_rounded[:tp_count],
            "tp_count": tp_count,
            "trailing_callback_rate": float(trailing_callback_rate or 0.0),
            "trailing_order_id": None,
            "trailing_activated": False,
            "qty": qty, "leverage": leverage, "risk_pct": risk_pct,
            "margin_mode": margin_mode,
            "actual_margin_mode": None,
            "actual_leverage": None,
            "layered": layering,
            "anchor_shift": 0,
            "profile": profile,
            "formula_tag": formula_tag,
            "mode": mode, "status": "pending_entry", "pnl_usdt": 0.0,
            "entry_expire_at": expire_p.isoformat(),
            "soft_bracket": False, "soft_bracket_reason": None,
            "bracket_type": "pending",
            "created_at": now_p.isoformat(), "updated_at": now_p.isoformat(),
        }

    # Order limit sudah FILLED (instan) → lanjut verifikasi posisi.
    pos_final = None
    for _ in range(10):
        await asyncio.sleep(0.3)
        try:
            pos_final = await br.position_risk(
                api_key, api_secret, is_testnet, bin_sym)
        except Exception:
            continue
        if pos_final and abs(float(pos_final.get("positionAmt") or 0)) > abs(existing_amt):
            break

    if not pos_final or abs(float(pos_final.get("positionAmt") or 0)) <= 0:
        # Posisi tidak materialize? Market order mungkin instan direverse.
        return {"ok": False, "reason": "position_not_opened",
                "message": "Market order terkirim tapi posisi tidak muncul di akun. Cek Binance manual."}

    actual_qty = abs(float(pos_final.get("positionAmt") or 0))
    actual_entry = float(pos_final.get("entryPrice") or entry)
    actual_mm = str(pos_final.get("marginType") or margin_mode).lower()
    # v9.9.3 — Baca leverage AKTUAL dari Binance. Jika set_leverage gagal
    # diam-diam (mis. request 50x tapi tier notional hanya izinkan 20x),
    # simpan yang benar supaya UI tidak menampilkan angka request palsu.
    actual_leverage = int(float(pos_final.get("leverage") or leverage))

    # v9.9.12 — ANCHOR-TO-FILL: sinyal memakai entry DEEP (limit di bawah/
    # atas harga), tetapi bot SELALU eksekusi MARKET. Geser SL/TP sebesar
    # selisih fill aktual vs entry sinyal sehingga jarak R & ladder TP
    # tetap utuh relatif ke harga masuk SEBENARNYA. Tanpa ini TP1 bisa
    # nempel atau bahkan di sisi salah dari fill (akar keluhan "posisi
    # tertutup di +0.4 sebelum TP2/TP3").
    anchor_shift = actual_entry - float(entry)
    if abs(anchor_shift) > 0:
        sl_price = round_to_tick(sl_price + anchor_shift, tick)
        tps_rounded = [round_to_tick(t + anchor_shift, tick) for t in tps_rounded]

    # v9.9.12 — GUARD TP vs average entry AKTUAL: buang TP yang berada di
    # sisi salah / terlalu dekat (krusial setelah layering: TP lama bisa
    # jatuh di bawah avg entry untuk BUY → instan terpicu). Jika semua
    # gugur, sintesis 1 TP di 1.5R dari fill.
    risk_dist = abs(actual_entry - sl_price) or actual_entry * 0.005
    min_tp_dist = max(actual_entry * 0.0025, risk_dist * 0.2)
    if side == "BUY":
        tps_rounded = [t for t in tps_rounded if t - actual_entry >= min_tp_dist]
        if not tps_rounded:
            tps_rounded = [round_to_tick(actual_entry + risk_dist * 1.5, tick)]
    else:
        tps_rounded = [t for t in tps_rounded if actual_entry - t >= min_tp_dist]
        if not tps_rounded:
            tps_rounded = [round_to_tick(actual_entry - risk_dist * 1.5, tick)]
    tp_count = min(3, max(1, len(tps_rounded)))

    # v9.9.4 — AUTO-REBALANCE BRACKET saat layering: batalkan SL/TP lama
    # dari layer sebelumnya (qty-nya sudah usang), lalu pasang ulang di
    # bawah ini untuk TOTAL posisi gabungan dengan average entry baru.
    if layering:
        try:
            await br.cancel_all_algo(api_key, api_secret, is_testnet, bin_sym)
            logger.info("layering %s: cancelled old brackets before rebalance", bin_sym)
        except Exception as e:
            logger.warning("cancel old algos %s: %s", bin_sym, e)
        # v9.9.10 — bersihkan juga conditional LEGACY (mis. TP/SL manual
        # user di app Binance) supaya SL closePosition baru tidak kena
        # -4130 dan rollback tidak sampai menutup posisi gabungan.
        try:
            await br.cancel_all_legacy(api_key, api_secret, is_testnet, bin_sym)
        except Exception as e:
            logger.warning("cancel old legacy %s: %s", bin_sym, e)

    async def _emergency_close(reason: str, detail: str) -> dict[str, Any]:
        """Market-close posisi + batalkan semua algo. Dipanggil bila
        SL/TP tidak dapat terpasang & terverifikasi. User minta: TIDAK
        BOLEH ada posisi tanpa proteksi — rollback bersih."""
        try:
            await br.cancel_all_algo(api_key, api_secret, is_testnet, bin_sym)
        except Exception:
            pass
        # v9.9.10 — bersihkan juga conditional LEGACY (bila tertinggal,
        # bisa tereksekusi liar saat user buka posisi lain nanti).
        try:
            await br.cancel_all_legacy(api_key, api_secret, is_testnet, bin_sym)
        except Exception:
            pass
        try:
            await br.market_order(
                api_key, api_secret, is_testnet,
                symbol=bin_sym, side=close_side,
                quantity=actual_qty, reduce_only=True,
            )
        except Exception as e:
            logger.exception("emergency_close failed %s: %s", bin_sym, e)
            return {
                "ok": False, "reason": "bracket_failed_rollback_failed",
                "message": (
                    f"Entry sukses, bracket GAGAL ({detail}), rollback juga GAGAL. "
                    "SEGERA tutup posisi manual di Binance!"
                ),
                "requires_manual_action": True,
                "symbol": bin_sym, "qty": actual_qty, "side": side,
            }
        return {
            "ok": False, "reason": reason,
            "message": (
                f"Bracket SL/TP tidak dapat terpasang di Binance ({detail}). "
                + ("Seluruh posisi gabungan (termasuk layer sebelumnya) otomatis ditutup. "
                   if layering else "Posisi otomatis ditutup. ")
                + "Balance Anda aman. Silakan coba lagi."
            ),
            "rollback_done": True,
        }

    # (7) Place SL with retry
    sl_algo_id: str | None = None
    sl_error: str | None = None
    for attempt in range(3):
        try:
            sl_resp = await br.place_algo(
                api_key, api_secret, is_testnet,
                symbol=bin_sym, side=close_side,
                order_type="STOP_MARKET",
                trigger_price=sl_price, close_position=True,
            )
            sl_algo_id = str(sl_resp.get("algoId"))
            break
        except Exception as e:
            sl_error = str(e)[:200]
            logger.warning("SL attempt %d/%s %s: %s", attempt + 1, 3, bin_sym, sl_error)
            # v9.9.10 — -4130: masih ada closePosition order basi yang
            # lolos dari pembersihan awal → paksa bersihkan lalu retry.
            if "-4130" in sl_error:
                try:
                    await br.cancel_all_algo(api_key, api_secret, is_testnet, bin_sym)
                    await br.cancel_all_legacy(api_key, api_secret, is_testnet, bin_sym)
                except Exception:
                    pass
            await asyncio.sleep(0.4)

    if not sl_algo_id:
        return await _emergency_close("bracket_sl_failed", sl_error or "SL unknown")

    # (8) Place TPs — split qty
    tp_parts = _split_tp_qty(actual_qty, step, tp_count)
    tp_algo_ids: list[str | None] = []
    tp_errors: list[str] = []
    for i, tp in enumerate(tps_rounded[:tp_count]):
        tp_qty = tp_parts[i] if i < len(tp_parts) else 0.0
        if tp_qty <= 0:
            tp_algo_ids.append(None)
            continue
        placed_id: str | None = None
        last_err: str | None = None
        for attempt in range(3):
            try:
                tp_resp = await br.place_algo(
                    api_key, api_secret, is_testnet,
                    symbol=bin_sym, side=close_side,
                    order_type="TAKE_PROFIT_MARKET",
                    trigger_price=tp, quantity=tp_qty,
                )
                placed_id = str(tp_resp.get("algoId"))
                break
            except Exception as e:
                last_err = str(e)[:200]
                logger.warning("TP%d attempt %d %s: %s", i + 1, attempt + 1, bin_sym, last_err)
                await asyncio.sleep(0.4)
        if not placed_id:
            tp_errors.append(f"TP{i + 1}: {last_err}")
        tp_algo_ids.append(placed_id)

    # (9) Verify ALL algo orders exist on exchange
    try:
        open_algos = await br.open_algo_orders(
            api_key, api_secret, is_testnet, bin_sym)
    except Exception:
        open_algos = []
    live_ids = {str(a.get("algoId")) for a in open_algos}

    sl_verified = sl_algo_id in live_ids
    tp_verified_count = sum(1 for tid in tp_algo_ids if tid and tid in live_ids)
    expected_tp_count = sum(1 for p in tp_parts if p > 0)

    # SL must be verified. If TP partial failure → still rollback (user
    # requirement: tidak boleh ada tanda unprotected sama sekali).
    if not sl_verified:
        return await _emergency_close(
            "bracket_sl_not_verified",
            f"SL algoId {sl_algo_id} tidak terlihat di openAlgoOrders",
        )
    if tp_verified_count < expected_tp_count:
        return await _emergency_close(
            "bracket_tp_incomplete",
            f"{tp_verified_count}/{expected_tp_count} TP terpasang. {'; '.join(tp_errors)[:150]}",
        )

    # (10) All verified → save trade as HARD bracket
    now = datetime.now(timezone.utc).isoformat()
    return {
        "ok": True, "exchange": "binance", "testnet": is_testnet,
        "symbol": base, "ccxt_symbol": f"{base}/USDT:USDT", "side": side,
        "entry_order_id": entry_order_id,
        "sl_order_id": sl_algo_id,
        "tp_order_ids": tp_algo_ids,
        "entry_price": actual_entry,
        "stop_loss": sl_price, "take_profits": tps_rounded[:tp_count],
        "tp_count": tp_count,
        "trailing_callback_rate": float(trailing_callback_rate or 0.0),
        "trailing_order_id": None,
        "trailing_activated": False,
        "qty": actual_qty, "leverage": leverage, "risk_pct": risk_pct,
        "margin_mode": margin_mode,
        "actual_margin_mode": actual_mm,
        "actual_leverage": actual_leverage,
        # v9.9.4 — true bila ini eksekusi ke-2+ pada simbol yang sama
        # (averaging). Routes akan melebur row trade lama ke row ini.
        "layered": layering,
        "anchor_shift": round(anchor_shift, 10),
        "leverage_note": (
            f"Requested {leverage}x tetapi Binance set {actual_leverage}x"
            + (f" ({lev_rejected})" if lev_rejected else "")
        ) if actual_leverage != leverage else None,
        "profile": profile,
        "formula_tag": formula_tag,
        "mode": mode, "status": "open", "pnl_usdt": 0.0,
        "soft_bracket": False, "soft_bracket_reason": None,
        "bracket_type": "hard",
        "bracket_verified_at": now,
        "created_at": now, "updated_at": now,
    }


# ── CCXT fallback (bybit/okx/bitget) ──────────────────────────────────
async def _execute_ccxt_fallback(
    doc: dict[str, Any], symbol: str, side: Side,
    entry: float, stop_loss: float, tps: list[float],
    risk_pct: float, leverage: int, mode: str,
    tp_count: int, trailing_callback_rate: float, margin_mode: str,
    profile: str | None = None, formula_tag: str | None = None,
) -> dict[str, Any]:
    """Original CCXT-based path for non-Binance exchanges. Preserved as-is
    with its known soft-bracket fallback semantics."""
    client = await _get_client(doc)
    exch_sym = _ccxt_symbol(doc["exchange"], symbol)
    tradable_err = await _ensure_tradable(client, exch_sym, symbol)
    if tradable_err:
        try:
            await client.close()
        except Exception:
            pass
        return {"ok": False, "reason": tradable_err[0], "message": tradable_err[1]}
    entry_order_id = None
    sl_order_id = None
    tp_order_ids: list[str] = []
    actual_qty = 0.0
    actual_fill = entry
    try:
        try:
            await client.set_margin_mode(margin_mode, exch_sym)
        except Exception:
            pass
        try:
            await client.set_leverage(leverage, exch_sym)
        except Exception:
            pass
        bal = await _fetch_usdt_balance(client)
        margin = bal * risk_pct / 100.0
        size_usdt = margin * leverage
        qty = size_usdt / entry
        amount_step: float | None = None
        price_tick: float | None = None
        try:
            markets = client.markets or await client.load_markets()
            m = markets.get(exch_sym) or {}
            precision = (m.get("precision") or {}).get("amount")
            if isinstance(precision, int) and precision >= 0:
                qty = round(qty, precision)
                amount_step = 10 ** -precision if precision > 0 else 1.0
            elif isinstance(precision, float) and precision > 0:
                amount_step = precision
                qty = (int(qty / precision)) * precision
            pprec = (m.get("precision") or {}).get("price")
            if isinstance(pprec, int) and pprec >= 0:
                price_tick = 10 ** -pprec
            elif isinstance(pprec, float) and pprec > 0:
                price_tick = pprec
        except Exception:
            pass
        if price_tick and price_tick > 0:
            stop_loss = round(round(stop_loss / price_tick) * price_tick, 8)
            tps = [round(round(float(t) / price_tick) * price_tick, 8) for t in tps]
        if qty <= 0:
            return {"ok": False, "message": "Qty terhitung 0."}
        try:
            entry_order = await client.create_order(
                exch_sym, "market", _ccxt_side(side), qty, None,
                params={"reduceOnly": False},
            )
        except Exception as e:
            return {"ok": False, "reason": "entry_rejected",
                    "message": f"Order entry ditolak: {str(e)[:200]}"}
        entry_order_id = entry_order.get("id")
        actual_fill = float(entry_order.get("average") or entry_order.get("price") or entry)
        actual_qty = float(entry_order.get("filled") or qty)
        # v9.9.12 — anchor-to-fill + guard TP (setara jalur Binance):
        # geser SL/TP sebesar selisih fill aktual vs entry sinyal, lalu
        # buang TP sisi salah / nempel terhadap harga fill.
        shift = actual_fill - float(entry)
        if abs(shift) > 0:
            stop_loss = float(stop_loss) + shift
            tps = [float(t) + shift for t in tps]
            if price_tick and price_tick > 0:
                stop_loss = round(round(stop_loss / price_tick) * price_tick, 8)
                tps = [round(round(t / price_tick) * price_tick, 8) for t in tps]
        risk_dist = abs(actual_fill - float(stop_loss)) or actual_fill * 0.005
        min_tp_dist = max(actual_fill * 0.0025, risk_dist * 0.2)
        if side == "BUY":
            tps = [t for t in tps if t - actual_fill >= min_tp_dist] or [actual_fill + risk_dist * 1.5]
        else:
            tps = [t for t in tps if actual_fill - t >= min_tp_dist] or [actual_fill - risk_dist * 1.5]
        tp_count = min(3, max(1, len(tps)))
        close_side = _opposite(side)
        exchange = doc["exchange"].lower()
        soft_bracket = False
        sl_err: str | None = None
        tp_err: str | None = None
        sl_params = _sl_params(exchange, stop_loss, actual_qty)
        tp_params_fn = lambda tp_price, qty: _tp_params(exchange, tp_price, qty)
        try:
            sl_order = await client.create_order(
                exch_sym, "STOP_MARKET", close_side,
                None if sl_params.get("closePosition") else actual_qty, None,
                params=sl_params,
            )
            sl_order_id = sl_order.get("id")
        except Exception as e:
            sl_err = str(e)[:200]
            soft_bracket = True
        tp_parts = _split_tp_qty(actual_qty, amount_step, tp_count)
        for i, tp in enumerate(tps[:tp_count]):
            tp_qty = tp_parts[i] if i < len(tp_parts) else 0.0
            if soft_bracket or tp_qty <= 0:
                tp_order_ids.append(None)
                continue
            try:
                o = await client.create_order(
                    exch_sym, "TAKE_PROFIT_MARKET", close_side, tp_qty, None,
                    params=tp_params_fn(tp, tp_qty),
                )
                tp_order_ids.append(o.get("id"))
            except Exception:
                tp_order_ids.append(None)
                soft_bracket = True
    finally:
        try:
            await client.close()
        except Exception:
            pass
    now = datetime.now(timezone.utc).isoformat()
    return {
        "ok": True, "exchange": doc["exchange"], "testnet": bool(doc.get("testnet", True)),
        "symbol": symbol, "ccxt_symbol": exch_sym, "side": side,
        "entry_order_id": entry_order_id, "sl_order_id": sl_order_id,
        "tp_order_ids": tp_order_ids, "entry_price": actual_fill,
        "stop_loss": stop_loss, "take_profits": tps[:tp_count],
        "tp_count": tp_count,
        "trailing_callback_rate": float(trailing_callback_rate or 0.0),
        "trailing_order_id": None,
        "trailing_activated": False,
        "qty": actual_qty, "leverage": leverage, "risk_pct": risk_pct,
        "margin_mode": margin_mode,
        "actual_margin_mode": margin_mode,
        "actual_leverage": leverage,
        "profile": profile,
        "formula_tag": formula_tag,
        "mode": mode, "status": "open", "pnl_usdt": 0.0,
        "soft_bracket": soft_bracket,
        "soft_bracket_reason": (sl_err or tp_err) if soft_bracket else None,
        "bracket_type": "soft" if soft_bracket else "hard",
        "created_at": now, "updated_at": now,
    }


async def attach_brackets(
    doc: dict[str, Any], trade: dict[str, Any],
) -> dict[str, Any]:
    """v9.9.2 — (Re)pasang SL + TP native Binance untuk posisi yang SUDAH
    terbuka tapi tidak terverifikasi. VERIFIKASI via openAlgoOrders
    sebelum menyatakan sukses. Jika SL atau TP tidak terverifikasi,
    return ok=False dengan error detail (jangan tulis klaim palsu ke DB).
    """
    if (doc.get("exchange") or "").lower() != "binance":
        return {"ok": False, "error": "repair hanya didukung untuk Binance saat ini"}
    api_key = decrypt(doc["api_key_enc"])
    api_secret = decrypt(doc["api_secret_enc"])
    is_testnet = bool(doc.get("testnet", True))
    symbol = str(trade.get("symbol") or "").upper()
    base = symbol.split("/")[0].split("USDT")[0].split("-")[0]
    bin_sym = base + "USDT"
    close_side = "SELL" if trade.get("side") == "BUY" else "BUY"

    # Fetch real position
    try:
        pos = await br.position_risk(api_key, api_secret, is_testnet, bin_sym)
    except Exception as e:
        return {"ok": False, "symbol": symbol, "errors": [f"positionRisk: {str(e)[:160]}"]}
    now0 = datetime.now(timezone.utc).isoformat()
    if not pos or abs(float(pos.get("positionAmt") or 0)) <= 0:
        # v9.9.8 — Posisi SUDAH tertutup di exchange → bukan kegagalan.
        # Tandai trade closed agar berhenti muncul di banner repair.
        # Tidak ada uang berisiko → UI tidak perlu menampilkan apa pun.
        return {
            "ok": True, "symbol": symbol, "note": "position_already_closed",
            "update": {
                "status": "closed", "close_reason": "position_closed_externally",
                "closed_at": now0, "updated_at": now0,
                "soft_bracket_reason": None,
            },
        }
    qty = abs(float(pos.get("positionAmt") or 0))
    actual_mm = str(pos.get("marginType") or "").lower()
    actual_lev = int(float(pos.get("leverage") or trade.get("leverage") or 0))

    # Filters for rounding
    filters = await binance_symbol_filters() or {}
    f = filters.get(base) or {}
    tick = float(f.get("tick") or 0.0)
    step = float(f.get("step") or 0.0)

    stop_loss = float(trade.get("stop_loss") or 0)
    tps = list(trade.get("take_profits") or [])
    tp_count = int(trade.get("tp_count") or len(tps) or 3)
    if stop_loss <= 0 or not tps:
        return {
            "ok": False, "symbol": symbol,
            "errors": ["Trade lama tidak punya data SL/TP tersimpan — tidak bisa direpair otomatis."],
        }

    sl_price = round_to_tick(stop_loss, tick) if tick else stop_loss
    tps_rounded = [round_to_tick(float(t), tick) for t in tps] if tick else [float(t) for t in tps]

    # v9.9.12 — GUARD sisi TP vs entry LIVE exchange: repair tidak boleh
    # memasang TP yang berada di sisi salah (akan instan terpicu).
    entry_live = float(pos.get("entryPrice") or 0) or float(trade.get("entry_price") or 0)
    if entry_live > 0 and tps_rounded:
        if close_side == "SELL":  # posisi LONG
            tps_rounded = [t for t in tps_rounded if t > entry_live]
        else:  # posisi SHORT
            tps_rounded = [t for t in tps_rounded if t < entry_live]
        if not tps_rounded:
            return {
                "ok": False, "symbol": symbol,
                "errors": ["Semua TP tersimpan berada di sisi salah dari entry aktual — repair dibatalkan demi keamanan."],
            }

    # v9.9.10 — JANGAN cancel dulu: proteksi existing (algo/legacy) sah
    # dan akan terdeteksi di bawah. Cancel hanya dilakukan tepat sebelum
    # memasang SL baru (bila memang belum ada proteksi).

    # v9.9.13 — LAYERED fill (limit): bracket lama qty-nya sudah usang
    # → REBALANCE paksa: batalkan semua proteksi existing lalu pasang
    # ulang untuk TOTAL posisi gabungan (lewati shortcut "sudah ada").
    if trade.get("layered"):
        try:
            await br.cancel_all_algo(api_key, api_secret, is_testnet, bin_sym)
        except Exception:
            pass
        try:
            await br.cancel_all_legacy(api_key, api_secret, is_testnet, bin_sym)
        except Exception:
            pass

    # v9.9.10 — EXISTING-PROTECTION-AWARE: cek DUA sumber sebelum pasang:
    # (1) Algo API (order yang dibuat v9.9.2+), (2) legacy openOrders
    # (kode lama / manual user di app Binance). closePosition SL yang
    # sudah ada membuat Binance menolak SL baru dengan -4130 — dan
    # proteksi yang sudah ada itu SAH, jangan diganggu.
    if trade.get("layered"):
        # Baru saja dibatalkan di atas — jangan deteksi sebagai existing.
        legacy_orders = []
        existing_algos = []
    else:
        try:
            legacy_orders = await br.open_orders_legacy(
                api_key, api_secret, is_testnet, bin_sym)
        except Exception:
            legacy_orders = []
        try:
            existing_algos = await br.open_algo_orders(
                api_key, api_secret, is_testnet, bin_sym)
        except Exception:
            existing_algos = []
    existing_sl = (
        any(bool(o.get("closePosition"))
            and str(o.get("type", "")).startswith("STOP")
            and o.get("side") == close_side for o in legacy_orders)
        or any(a.get("orderType") == "STOP_MARKET"
               and a.get("side") == close_side
               and a.get("closePosition") in (True, "true", "True")
               for a in existing_algos)
    )
    existing_tp = (
        any(str(o.get("type", "")).startswith("TAKE_PROFIT")
            and o.get("side") == close_side for o in legacy_orders)
        or any(a.get("orderType") == "TAKE_PROFIT_MARKET"
               and a.get("side") == close_side for a in existing_algos)
    )
    legacy_sl = existing_sl
    legacy_tp_close = existing_tp

    errors: list[str] = []
    notes: list[str] = []
    sl_algo_id: str | None = None
    sl_passed = False
    if legacy_sl:
        notes.append("SL sudah terpasang (order existing di Binance)")
    else:
        # Belum ada proteksi → bersihkan algo usang lalu pasang baru.
        try:
            await br.cancel_all_algo(api_key, api_secret, is_testnet, bin_sym)
        except Exception:
            pass
        for attempt in range(3):
            try:
                r = await br.place_algo(
                    api_key, api_secret, is_testnet,
                    symbol=bin_sym, side=close_side,
                    order_type="STOP_MARKET",
                    trigger_price=sl_price, close_position=True,
                )
                sl_algo_id = str(r.get("algoId"))
                break
            except Exception as e:
                # v9.9.8 — -2021 "would immediately trigger" pada SL artinya
                # harga SUDAH melewati level SL → posisi sedang di zona rugi.
                # Tindakan protektif yang benar = market close sekarang (persis
                # yang akan dilakukan SL begitu terpasang). Bukan kegagalan.
                if "-2021" in str(e):
                    sl_passed = True
                    break
                # v9.9.10 — -4130: closePosition SL SUDAH ADA di Binance
                # (algo maupun legacy/manual). Verifikasi & anggap armed —
                # jangan laporkan sebagai kegagalan.
                if "-4130" in str(e):
                    try:
                        legacy_orders = await br.open_orders_legacy(
                            api_key, api_secret, is_testnet, bin_sym)
                        algos_now = await br.open_algo_orders(
                            api_key, api_secret, is_testnet, bin_sym)
                        legacy_sl = (
                            any(bool(o.get("closePosition"))
                                and str(o.get("type", "")).startswith("STOP")
                                and o.get("side") == close_side for o in legacy_orders)
                            or any(a.get("orderType") == "STOP_MARKET"
                                   and a.get("side") == close_side
                                   and a.get("closePosition") in (True, "true", "True")
                                   for a in algos_now)
                        )
                    except Exception:
                        pass
                    if legacy_sl:
                        notes.append("SL sudah terpasang (existing)")
                        break
                errors.append(f"SL try{attempt + 1}: {str(e)[:160]}")

    if sl_passed:
        try:
            await br.cancel_all_algo(api_key, api_secret, is_testnet, bin_sym)
        except Exception:
            pass
        try:
            await br.market_order(
                api_key, api_secret, is_testnet,
                symbol=bin_sym, side=close_side, quantity=qty, reduce_only=True,
            )
        except Exception as e:
            return {"ok": False, "symbol": symbol,
                    "errors": [f"SL level terlewati & auto-close gagal: {str(e)[:160]}"]}
        return {
            "ok": True, "symbol": symbol, "note": "sl_level_passed_auto_closed",
            "update": {
                "status": "closed", "close_reason": "sl_level_passed",
                "closed_at": now0, "updated_at": now0,
                "soft_bracket_reason": None,
            },
        }

    tp_parts = _split_tp_qty(qty, step or None, tp_count)
    tp_algo_ids: list[str | None] = []
    tp_failed = 0
    if legacy_tp_close:
        # v9.9.10 — TP closePosition legacy sudah menutupi SELURUH posisi.
        notes.append("TP sudah terpasang (existing closePosition di Binance)")
    else:
        for i, tp in enumerate(tps_rounded[:tp_count]):
            tp_qty = tp_parts[i] if i < len(tp_parts) else 0.0
            if tp_qty <= 0:
                tp_algo_ids.append(None)
                continue
            placed: str | None = None
            for attempt in range(3):
                try:
                    r = await br.place_algo(
                        api_key, api_secret, is_testnet,
                        symbol=bin_sym, side=close_side,
                        order_type="TAKE_PROFIT_MARKET",
                        trigger_price=tp, quantity=tp_qty,
                    )
                    placed = str(r.get("algoId"))
                    break
                except Exception as e:
                    # v9.9.8 — -2021 pada TP artinya harga sudah MELEWATI level
                    # TP (posisi profit melewati target). TP itu tidak lagi
                    # relevan → lewati diam-diam, BUKAN kegagalan. Posisi tetap
                    # terlindungi SL + TP lain.
                    if "-2021" in str(e):
                        notes.append(f"TP{i + 1} level already passed — skipped")
                        break
                    if "-4130" in str(e):
                        # TP closePosition legacy sudah ada → sudah ter-cover.
                        notes.append(f"TP{i + 1} covered by existing order")
                        break
                    if attempt == 2:
                        tp_failed += 1
                        errors.append(f"TP{i + 1} try{attempt + 1}: {str(e)[:160]}")
            tp_algo_ids.append(placed)

    # Verify via openAlgoOrders
    try:
        openalgos = await br.open_algo_orders(api_key, api_secret, is_testnet, bin_sym)
    except Exception:
        openalgos = []
    live_ids = {str(a.get("algoId")) for a in openalgos}
    # v9.9.10 — SL/TP existing legacy juga dihitung sebagai terpasang.
    sl_ok = bool(sl_algo_id and sl_algo_id in live_ids) or legacy_sl
    tp_ok = sum(1 for t in tp_algo_ids if t and t in live_ids)
    expected_tp = sum(1 for p in tp_parts if p > 0)
    # v9.9.8 — hard = SL terverifikasi DAN tidak ada TP yang GAGAL NYATA.
    # TP yang di-skip karena level sudah terlewati (harga profit melampaui
    # target) tidak dihitung sebagai kegagalan.
    hard = sl_ok and tp_failed == 0 and (tp_ok > 0 or expected_tp == 0 or bool(notes))

    now = datetime.now(timezone.utc).isoformat()
    update = {
        "sl_order_id": sl_algo_id if sl_ok else None,
        "tp_order_ids": [t if (t and t in live_ids) else None for t in tp_algo_ids],
        "soft_bracket": not hard,
        "soft_bracket_reason": None if hard else "; ".join(errors)[:220],
        "bracket_type": "hard" if hard else "soft",
        "actual_margin_mode": actual_mm or trade.get("margin_mode") or "cross",
        "actual_leverage": actual_lev,
        "updated_at": now,
    }
    if hard:
        update["bracket_verified_at"] = now
    return {
        "ok": hard, "symbol": symbol,
        "sl_order_id": sl_algo_id if sl_ok else None,
        "tp_order_ids": [t if (t and t in live_ids) else None for t in tp_algo_ids],
        "errors": errors,
        "notes": notes,
        "update": update,
    }


async def close_position(doc: dict[str, Any], symbol: str, side: Side,
                         qty: float) -> dict[str, Any]:
    """Market close for manual close/cancel bot action.

    v9.4.3 — For Binance, first cancel any open conditional orders
    (algo SL/TP) so no orphan triggers fire after the close.
    """
    if (doc.get("exchange") or "").lower() == "binance":
        try:
            await cancel_all_conditional(
                decrypt(doc["api_key_enc"]), decrypt(doc["api_secret_enc"]),
                bool(doc.get("testnet", True)),
                symbol.upper().split("/")[0].split("USDT")[0].split("-")[0] + "USDT",
            )
        except Exception:
            pass
        # v9.9.10 — bersihkan juga conditional legacy agar tidak ada
        # order yatim yang menembak posisi lain nanti.
        try:
            await br.cancel_all_legacy(
                decrypt(doc["api_key_enc"]), decrypt(doc["api_secret_enc"]),
                bool(doc.get("testnet", True)),
                symbol.upper().split("/")[0].split("USDT")[0].split("-")[0] + "USDT",
            )
        except Exception:
            pass
        # v9.9.4 — Baca qty LIVE dari positionRisk. Setelah layering, qty
        # di DB row lama bisa lebih kecil dari posisi fisik gabungan —
        # close harus menutup SELURUH posisi.
        try:
            bin_sym = symbol.upper().split("/")[0].split("USDT")[0].split("-")[0] + "USDT"
            pos = await br.position_risk(
                decrypt(doc["api_key_enc"]), decrypt(doc["api_secret_enc"]),
                bool(doc.get("testnet", True)), bin_sym,
            )
            live = abs(float((pos or {}).get("positionAmt") or 0))
            if live > 0:
                qty = live
        except Exception:
            pass
        if qty <= 0:
            return {"ok": True, "id": None, "avg": None, "note": "no_position"}
    client = await _get_client(doc)
    try:
        exch_sym = _ccxt_symbol(doc["exchange"], symbol)
        o = await client.create_order(
            exch_sym, "market", _opposite(side), qty, None,
            params={"reduceOnly": True},
        )
        return {"ok": True, "id": o.get("id"), "avg": o.get("average")}
    finally:
        try:
            await client.close()
        except Exception:
            pass


async def close_position_partial(doc: dict[str, Any], symbol: str, side: Side,
                                 qty: float) -> dict[str, Any]:
    """v9.9.12 — Market close SEBAGIAN posisi. Berbeda dari close_position:
    TIDAK membatalkan conditional order lain dan TIDAK menimpa qty dari
    positionRisk. Dipakai soft-watcher untuk TP split (TP1 1/3, TP2 1/3,
    sisanya di TP3/SL) agar konsisten dengan bracket native."""
    if (doc.get("exchange") or "").lower() == "binance":
        api_key = decrypt(doc["api_key_enc"])
        api_secret = decrypt(doc["api_secret_enc"])
        is_testnet = bool(doc.get("testnet", True))
        bin_sym = symbol.upper().split("/")[0].split("USDT")[0].split("-")[0] + "USDT"
        r = await br.market_order(
            api_key, api_secret, is_testnet,
            symbol=bin_sym, side="SELL" if side == "BUY" else "BUY",
            quantity=qty, reduce_only=True,
        )
        return {"ok": True, "id": r.get("orderId"),
                "avg": r.get("avgPrice") or r.get("price")}
    client = await _get_client(doc)
    try:
        exch_sym = _ccxt_symbol(doc["exchange"], symbol)
        o = await client.create_order(
            exch_sym, "market", _opposite(side), qty, None,
            params={"reduceOnly": True},
        )
        return {"ok": True, "id": o.get("id"), "avg": o.get("average")}
    finally:
        try:
            await client.close()
        except Exception:
            pass


async def _maybe_activate_trailing(
    doc: dict[str, Any], trade: dict[str, Any], pos: dict[str, Any],
) -> dict[str, Any] | None:
    """v9.6.0 — Setelah TP1 fill, cancel sisa TP + SL original lalu pasang
    TRAILING_STOP_MARKET native Binance untuk sisa qty.

    Dideteksi dari: `pos.contracts` < `trade.qty` DAN flag belum aktif
    DAN `trailing_callback_rate > 0` DAN exchange = binance.
    """
    if trade.get("trailing_activated"):
        return None
    cb = float(trade.get("trailing_callback_rate") or 0.0)
    if cb <= 0:
        return None
    if (doc.get("exchange") or "").lower() != "binance":
        return None
    try:
        current_qty = float(pos.get("contracts") or 0)
    except Exception:
        return None
    original_qty = float(trade.get("qty") or 0)
    if current_qty <= 0 or current_qty >= original_qty * 0.999:
        return None  # TP1 belum tersentuh
    api_key = decrypt(doc["api_key_enc"])
    api_secret = decrypt(doc["api_secret_enc"])
    is_testnet = bool(doc.get("testnet", True))
    sym = str(trade.get("symbol") or "").upper()
    spot_sym = sym.split("/")[0].split("USDT")[0].split("-")[0] + "USDT"
    close_side = "SELL" if trade.get("side") == "BUY" else "BUY"
    try:
        await cancel_all_conditional(api_key, api_secret, is_testnet, spot_sym)
    except Exception:
        pass
    try:
        o = await new_trailing_stop_order(
            api_key, api_secret, is_testnet,
            symbol=spot_sym, side=close_side, quantity=current_qty,
            callback_rate=cb,
        )
        return {
            "trailing_activated": True,
            "trailing_order_id": str(o.get("algoId") or ""),
            "sl_order_id": None,
            "tp_order_ids": [None] * int(trade.get("tp_count") or 3),
            "bracket_type": "trailing",
        }
    except Exception as e:
        return {"trailing_activated": False, "trailing_error": str(e)[:200]}



async def refresh_trade_pnl(doc: dict[str, Any], trade: dict[str, Any]) -> dict[str, Any]:
    """Query exchange untuk status order & hitung PnL realized/unrealized.

    v9.9.2 — Untuk Binance pakai REST langsung (bukan CCXT) agar
    actual_margin_mode / entry / markPrice selalu akurat. CCXT path
    tetap untuk exchange lain.

    v9.7.7 — PHANTOM-CLOSE FIX. Jika fetch GAGAL (API error), JANGAN
    tandai closed.
    """
    exchange = (doc.get("exchange") or "").lower()
    if exchange == "binance":
        return await _refresh_binance(doc, trade)
    # non-Binance → CCXT fallback
    client = await _get_client(doc)
    try:
        exch_sym = trade["ccxt_symbol"]
        fetch_ok = True
        positions = []
        try:
            positions = await client.fetch_positions([exch_sym])
        except Exception:
            fetch_ok = False
            positions = []
        pos = next((p for p in positions if (p or {}).get("contracts", 0)), None)
        extra_update: dict[str, Any] = {}
        if pos:
            try:
                extra_update = await _maybe_activate_trailing(doc, trade, pos) or {}
            except Exception:
                extra_update = {}
            unrealized = float(pos.get("unrealizedPnl") or 0)
            return {"status": "open", "pnl_usdt": round(unrealized, 2),
                    "mark_price": pos.get("markPrice"), **extra_update}
        if not fetch_ok:
            return {"status": "open", "pnl_usdt": float(trade.get("pnl_usdt") or 0.0)}
        realized = 0.0
        qty = float(trade.get("qty") or 0)
        entry = float(trade.get("entry_price") or 0)
        side = trade.get("side")
        try:
            fills = await client.fetch_my_trades(exch_sym, limit=20)
        except Exception:
            fills = []
        for f in fills:
            price = float(f.get("price") or 0)
            amount = float(f.get("amount") or 0)
            if side == "BUY":
                realized += (price - entry) * amount if f.get("side") == "sell" else 0
            else:
                realized += (entry - price) * amount if f.get("side") == "buy" else 0
        if realized == 0 and qty > 0:
            sl = float(trade.get("stop_loss") or entry)
            realized = (sl - entry) * qty if side == "BUY" else (entry - sl) * qty
        return {"status": "closed", "pnl_usdt": round(realized, 2)}
    finally:
        try:
            await client.close()
        except Exception:
            pass


async def _refresh_binance(doc: dict[str, Any], trade: dict[str, Any]) -> dict[str, Any]:
    """v9.9.2 — Direct REST refresh untuk Binance. Memperbarui actual
    margin mode + verifikasi bracket masih hidup di openAlgoOrders."""
    api_key = decrypt(doc["api_key_enc"])
    api_secret = decrypt(doc["api_secret_enc"])
    is_testnet = bool(doc.get("testnet", True))
    symbol = str(trade.get("symbol") or "").upper()
    base = symbol.split("/")[0].split("USDT")[0].split("-")[0]
    bin_sym = base + "USDT"
    try:
        pos = await br.position_risk(api_key, api_secret, is_testnet, bin_sym)
    except Exception:
        # Fetch failed → keep status open, PnL unchanged
        return {"status": "open", "pnl_usdt": float(trade.get("pnl_usdt") or 0.0)}
    amt = float((pos or {}).get("positionAmt") or 0)
    if abs(amt) > 0:
        unrealized = float(pos.get("unRealizedProfit") or 0)
        actual_mm = str(pos.get("marginType") or "").lower()
        mark = pos.get("markPrice")
        actual_lev = int(float(pos.get("leverage") or trade.get("leverage") or 0))
        # Verify bracket still armed in openAlgoOrders
        try:
            openalgos = await br.open_algo_orders(api_key, api_secret, is_testnet, bin_sym)
        except Exception:
            openalgos = None
        bracket_live = None
        if isinstance(openalgos, list):
            live_ids = {str(a.get("algoId")) for a in openalgos}
            sl_id = trade.get("sl_order_id")
            tp_ids = trade.get("tp_order_ids") or []
            close_side = "SELL" if float(pos.get("positionAmt") or 0) > 0 else "BUY"
            sl_live = bool(sl_id and str(sl_id) in live_ids)
            tp_live = any(str(t) in live_ids for t in tp_ids if t)
            # v9.9.10 — ID di DB bisa basi (trade dieksekusi kode lama /
            # posisi di-layer). Verifikasi berdasarkan KARAKTERISTIK order:
            # ada STOP_MARKET closePosition searah = SL armed; ada
            # TAKE_PROFIT_MARKET searah = TP armed.
            if not sl_live:
                sl_live = any(
                    a.get("orderType") == "STOP_MARKET"
                    and a.get("side") == close_side
                    and a.get("closePosition") in (True, "true", "True")
                    for a in openalgos)
            if not tp_live:
                tp_live = any(
                    a.get("orderType") == "TAKE_PROFIT_MARKET"
                    and a.get("side") == close_side
                    for a in openalgos)
            # v9.9.10 — FALLBACK LEGACY: SL/TP yang dipasang kode lama
            # (/fapi/v1/order) atau manual oleh user di app Binance tidak
            # tercatat di Algo API. Cek openOrders legacy sebelum
            # menyatakan posisi tanpa proteksi.
            if not (sl_live and tp_live):
                try:
                    legacy = await br.open_orders_legacy(
                        api_key, api_secret, is_testnet, bin_sym)
                except Exception:
                    legacy = []
                if not sl_live:
                    sl_live = any(
                        bool(o.get("closePosition"))
                        and str(o.get("type", "")).startswith("STOP")
                        and o.get("side") == close_side
                        for o in legacy)
                if not tp_live:
                    tp_live = any(
                        str(o.get("type", "")).startswith("TAKE_PROFIT")
                        and o.get("side") == close_side
                        for o in legacy)
            bracket_live = sl_live and tp_live
        upd: dict[str, Any] = {
            "status": "open",
            "pnl_usdt": round(unrealized, 2),
            "mark_price": float(mark) if mark else None,
            "actual_margin_mode": actual_mm,
            "actual_leverage": actual_lev,
        }
        if bracket_live is not None:
            upd["bracket_live"] = bracket_live
            # v9.9.10 — bracket terverifikasi (algo ATAU legacy) → tandai
            # hard & hapus label soft yang salah.
            if bracket_live:
                upd["bracket_type"] = "hard"
                upd["soft_bracket"] = False
                upd["soft_bracket_reason"] = None
        return upd
    # Position closed. Compute realized from stored data.
    realized = float(trade.get("pnl_usdt") or 0.0)
    # v9.9.9 — Rekam harga close aktual (fill terakhir) untuk history.
    closed_px = None
    try:
        closed_px = await br.last_fill_price(api_key, api_secret, is_testnet, bin_sym)
    except Exception:
        pass
    upd_closed: dict[str, Any] = {"status": "closed", "pnl_usdt": round(realized, 2)}
    if closed_px:
        upd_closed["closed_price"] = closed_px
    return upd_closed
