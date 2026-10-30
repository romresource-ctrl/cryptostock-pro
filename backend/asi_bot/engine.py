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
import math
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
# v10.0.16 — Komposisi split baru (keputusan user): TP1 menutup 50%,
# TP2 25%, TP3 25% (bukan lagi 33/33/34). Untuk 2 TP tetap 50/50.
# v10.2.36 — Pilihan target Auto-Close Profit (ROI % dari margin). 0 = off.
AUTO_CLOSE_PCTS = (0, 10, 15, 20, 25, 30, 35, 40, 45, 50, 60, 65, 75, 100, 150, 200)
# v10.2.37 — Jarak SL wajib 1–2% dari entry (keputusan user).
SL_MIN_PCT = 0.01
SL_MAX_PCT = 0.02


def _clamp_sl(entry: float, stop_loss: float, side: str) -> float:
    sgn = 1.0 if side == "BUY" else -1.0
    dist = abs(entry - stop_loss) / entry
    dist = min(SL_MAX_PCT, max(SL_MIN_PCT, dist))
    return entry * (1 - sgn * dist)


def _resolve_margin(bal: float, risk_pct: float, margin_usdt: float | None) -> float:
    """v10.2.37 — Margin per trade ($) user; fallback risk % saldo (legacy).
    Tidak boleh melebihi saldo tersedia."""
    m = float(margin_usdt or 0)
    if m > 0:
        return min(m, bal)
    return bal * risk_pct / 100.0
TP_SPLITS: dict[int, tuple[float, ...]] = {
    1: (1.0,),
    2: (0.5, 0.5),
    3: (0.5, 0.25, 0.25),
}

# v10.2.16 — HIT-AND-RUN (KISS Pivot) params, keputusan user:
# "masuk di tengah → keluar cepat sebelum berbalik, profit kecil pun
# tidak apa-apa". HANYA untuk trade ber-formula_tag mengandung
# "KISS Pivot". Trade lama (sudah open) TIDAK diubah.
# v10.2.16b — Keputusan user: naik ke 3 TP berbasis R terhadap SL.
# SL 0.9% dan TP1 0.9% (sama besar → TP1 = 1:1 vs SL), TP2 1.2%,
# TP3 1.5%. Split qty mengikuti TP_SPLITS[3] = 50/25/25.
HAR_TP_PCTS = (0.009, 0.012, 0.015)  # TP1 0.9% · TP2 1.2% · TP3 1.5%
HAR_SL_PCT = 0.009                   # SL 0.9% — seukuran TP1, lawan arah
HAR_TRAILING_RATE = 1.5              # trailing stop % setelah batas horizon
# Batas hold maksimum = horizon profil (dari kartu Trader Profile):
# Scalper 5-15m · Intraday 1-4h · Swing 4-24h.
HAR_MAX_HOLD_MIN = {"scalper": 15, "day": 240, "swing": 1440, "longterm": 1440}
# v10.2.16 — PROFIT CAP per profil (keputusan user): bila ROE posisi
# sudah ≥ ambang ini → bot langsung market-close ("jika sudah profit
# diatas X% - close"). Confluence v9 / longterm TIDAK punya cap & tidak
# ada batas waktu — holding mengikuti SL/TP1-3.
PROFILE_PROFIT_CAP_ROE = {"scalper": 10.0, "day": 15.0, "swing": 25.0}
# v10.2.17 — LEVEL FLOORS untuk SEMUA koin (keputusan user): TP1/TP2
# jangan pernah terlalu kecil sampai profit tidak menutup fee exchange
# (~$4 per $100). Floor jarak MINIMUM per profil; level formula yang
# lebih lebar tetap dipakai apa adanya. Berlaku untuk big-cap (> $100)
# MAUPUN low-cap (< $100) — low-cap saat ATR tenang juga bisa rapat.
LEVEL_FLOORS_MIN: dict[str, tuple[float, tuple[float, float, float]]] = {
    "scalper": (0.012, (0.012, 0.018, 0.025)),  # SL 1.2% · TP 1.2/1.8/2.5%
    "day":     (0.015, (0.015, 0.022, 0.030)),  # SL 1.5% · TP 1.5/2.2/3.0%
    "swing":   (0.025, (0.025, 0.035, 0.050)),  # SL 2.5% · TP 2.5/3.5/5.0%
}


def _shift_tp_ladder(tps: list[float] | None, tp_count: int) -> list[float]:
    """v10.0.16 — Ladder TIDAK lagi digeser: memilih N TP memakai TP1..TPN
    persis (keputusan user). tp_count=2 → [TP1, TP2], close terakhir 100%
    di harga TP2 (bukan lagi di titik TP3). tp_count=1 → [TP1]."""
    full = [float(x) for x in (tps or []) if x]
    n = max(1, min(3, int(tp_count)))
    return full[:n]


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
    margin_usdt: float = 0.0,
    auto_close_pct: int = 0,
) -> dict[str, Any]:
    """Hitung besaran margin & qty TANPA eksekusi — untuk Semi-Auto preview."""
    risk_pct = max(1.0, min(30.0, float(risk_pct)))
    leverage = max(1, min(125, int(leverage)))
    tp_count = max(1, min(3, int(tp_count)))
    # v10.4.1 — preview mengikuti AC: 1 target = entry × (1 ± AC%/leverage)
    if int(auto_close_pct or 0) in AUTO_CLOSE_PCTS and int(auto_close_pct or 0) > 0 and entry > 0:
        _sg = 1.0 if side == "BUY" else -1.0
        tps = [entry * (1 + _sg * int(auto_close_pct) / 100.0 / leverage)]
        tp_count = 1
    client = await _get_client(doc)
    exch_sym = _ccxt_symbol(doc["exchange"], symbol)
    try:
        # v9.8.2 — validasi dinamis ke daftar pasar exchange (bukan whitelist statis)
        bad = await _ensure_tradable(client, exch_sym, symbol)
        if bad:
            return {"ok": False, "reason": bad[0], "message": bad[1]}
        bal = await _fetch_usdt_balance(client)
        margin = round(_resolve_margin(bal, risk_pct, margin_usdt), 2)
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
                "message": (f"Position size ${size_usdt:.2f} is below the "
                            f"exchange minimum (${float(min_cost):.2f}). Raise Risk % or Leverage."),
            }
    finally:
        await client.close()
    margin = round(_resolve_margin(bal, risk_pct, margin_usdt), 2)
    size_usdt = margin * leverage
    qty = size_usdt / entry if entry > 0 else 0
    if entry > 0 and stop_loss:
        stop_loss = _clamp_sl(entry, float(stop_loss), side)  # v10.2.37
    risk_per_unit = abs(entry - stop_loss)
    est_loss = round(risk_per_unit * qty, 2)
    weights = TP_SPLITS[tp_count]
    tp_est = []
    # v10.0.9 — preview menampilkan level yang BENAR-BENAR dipasang
    # (ladder bergeser saat tp_count < 3).
    for i, tp in enumerate(_shift_tp_ladder(tps, tp_count)):
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
    entry_mode: str = "limit",
    auto_close_pct: int = 0,
    margin_usdt: float = 0.0,
) -> dict[str, Any]:
    """v9.9.2 — Place entry + VERIFIED bracket SL/TP. Auto-rollback jika
    bracket tidak dapat terpasang & terverifikasi di exchange.

    Return record untuk asi_trades, atau {ok:false, reason, message}
    jika entry/bracket ditolak (posisi sudah ditutup di sisi exchange).
    """
    risk_pct = max(1.0, min(30.0, float(risk_pct)))
    leverage = max(1, min(125, int(leverage)))
    tp_count = max(1, min(3, int(tp_count)))
    # v10.2.16 — HIT-AND-RUN bracket khusus formula KISS Pivot (keputusan
    # user): pola ini masuk di TENGAH pergerakan → wajib keluar cepat
    # dengan profit kecil sebelum harga berbalik. Override level (3 TP):
    # SL 0.9% (seukuran TP1, lawan arah), TP1 0.9% / TP2 1.2% / TP3 1.5%,
    # split qty 50/25/25 via TP_SPLITS[3]. SL Guard memindah SL ke TP1
    # setelah TP1 kena (trailing_callback_rate=0 supaya guard tidak
    # diskip). Monitor _refresh_binance menutup posisi via market begitu
    # umur trade melewati horizon profil (Scalper 15m · Intraday 4h ·
    # Swing 24h) jika masih profit.
    hit_and_run = "kiss pivot" in str(formula_tag or "").lower()
    if hit_and_run and entry > 0:
        # v10.2.33 — Keputusan user TERBARU (menimpa v10.2.16b): setting
        # jumlah TP user di halaman ASI-Bot WAJIB dihormati untuk SEMUA
        # profil & formula, termasuk KISS Pivot. Override `tp_count=3`
        # lama DIHAPUS — ladder HAR (0.9/1.2/1.5%) tetap, tapi dislice
        # oleh _shift_tp_ladder sesuai tp_count user (1→100% di TP1,
        # 2→50/50, 3→50/25/25).
        _har_sign = 1.0 if side == "BUY" else -1.0
        stop_loss = entry * (1 - _har_sign * HAR_SL_PCT)
        tps = [entry * (1 + _har_sign * p) for p in HAR_TP_PCTS]
        trailing_callback_rate = 0.0
    # v10.2.16 — Horizon exit per profil (Scalper/Intraday/Swing) untuk
    # SEMUA formula: profit-cap ROE + batas waktu maksimum. Hanya trade
    # BARU yang membawa flag ini; posisi existing tetap aturan lama.
    horizon_exit = str(profile or "").lower() in PROFILE_PROFIT_CAP_ROE
    # v10.2.17 — BIG-CAP floor (keputusan user): untuk koin harga > $100
    # (BTC/ETH/BNB dst), level formula sering terlalu rapat sampai profit
    # tidak menutup fee. Terapkan jarak MINIMUM SL/TP per profil (floor,
    # bukan override — level formula yang lebih lebar tetap dipakai).
    # Ditempatkan SEBELUM cabang fallback ccxt supaya berlaku di semua
    # jalur eksekusi; trade lama tidak diubah.
    # v10.2.17 — Level floor (keputusan user): TP1/TP2 jangan terlalu
    # kecil sampai tidak menutup fee — berlaku untuk SEMUA koin (big-cap
    # maupun low-cap). Floor = jarak MINIMUM SL/TP per profil; level
    # formula yang lebih lebar tetap dipakai. Ditempatkan SEBELUM cabang
    # fallback ccxt supaya berlaku di semua jalur; trade lama tidak diubah.
    if entry > 0:
        _bc = LEVEL_FLOORS_MIN.get(str(profile or "").lower())
        if _bc:
            _bc_sgn = 1.0 if side == "BUY" else -1.0
            _bc_sl_min, _bc_tp_mins = _bc
            if stop_loss:
                _bc_sl_dist = abs(entry - float(stop_loss)) / entry
                if _bc_sl_dist < _bc_sl_min:
                    stop_loss = entry * (1 - _bc_sgn * _bc_sl_min)
            _bc_tps = []
            for _bc_i, _bc_tp in enumerate(tps):
                _bc_tp = float(_bc_tp)
                _bc_floor = _bc_tp_mins[min(_bc_i, len(_bc_tp_mins) - 1)]
                if abs(_bc_tp - entry) / entry < _bc_floor:
                    _bc_tp = entry * (1 + _bc_sgn * _bc_floor)
                _bc_tps.append(_bc_tp)
            tps = _bc_tps

    # v10.2.37 — SL CLAMP 1–2% (keputusan user, loss TIA 20/10: SL 5,1%
    # → -57% margin). Semua trade baru: jarak Entry→SL dipaksa di
    # rentang [SL_MIN_PCT, SL_MAX_PCT]. Simetri di bawah ikut menyesuaikan TP1.
    if entry > 0 and stop_loss:
        stop_loss = _clamp_sl(entry, float(stop_loss), side)
    # v10.2.17 — SIMETRI SL=TP1 (keputusan user): jarak Entry→SL harus
    # SAMA DENGAN jarak Entry→TP1 (R = 1:1). TP2 & TP3 ikut digeser
    # berdasarkan rasio ladder asli (menjaga progresi 1R/1.5R/2R). Jika
    # jarak SL = 0 (sinyal cacat), lewati — bracket builder akan tolak.
    # Berlaku SETELAH big-cap floor di atas sehingga simetri menang.
    # Tidak diterapkan pada KISS Pivot karena paket itu SENGAJA simetri
    # sendiri (SL 0.9% / TP1 0.9%) dan tidak perlu digeser.
    if (not hit_and_run) and entry > 0 and stop_loss and tps:
        _sym_sgn = 1.0 if side == "BUY" else -1.0
        _sym_sl_dist = abs(entry - float(stop_loss))
        if _sym_sl_dist > 0:
            _sym_tp1_dist_old = abs(float(tps[0]) - entry)
            _sym_tp1 = entry + _sym_sgn * _sym_sl_dist  # TP1 = 1R dari entry
            _sym_tps = [_sym_tp1]
            # TP2/TP3: geser proporsional terhadap perubahan TP1.
            # Jika ladder asli lebih lebar dari TP1 baru, pakai ladder asli.
            for _old in tps[1:]:
                _old_dist = abs(float(_old) - entry)
                _new_dist = max(_old_dist, _sym_sl_dist * 1.5) if len(_sym_tps) == 1 \
                            else max(_old_dist, _sym_sl_dist * 2.0)
                _sym_tps.append(entry + _sym_sgn * _new_dist)
            tps = _sym_tps
    # v10.2.36 — AUTO-CLOSE PROFIT (keputusan user): target ROI % dari
    # margin (10/15/20/25/50/100). Menggantikan ladder TP: 1 TP native
    # 100% di harga entry × (1 ± pct/leverage). TP native di-anchor ke
    # fill aktual (anchor_shift), sehingga tidak ada close ganda.
    auto_close_pct = int(auto_close_pct or 0)
    if auto_close_pct not in AUTO_CLOSE_PCTS:
        auto_close_pct = 0
    auto_close_pct_user = auto_close_pct
    # v10.7.6 — keputusan user (Full-Auto): SL OTOMATIS menyesuaikan AC.
    # Jarak SL = AC% ÷ leverage − 0.1% (buffer fee) → rugi saat SL ≈ untung
    # saat AC. Tetap dijaga di rentang SL 1–2%; bila terpotong batas 1%,
    # floor di bawah menaikkan AC agar untung tetap ≥ rugi.
    if auto_close_pct and mode == "full" and entry > 0 and leverage > 0:
        _sgn_sl = 1.0 if side == "BUY" else -1.0
        _d_sl = auto_close_pct / 100.0 / leverage - 0.001
        _d_sl = min(SL_MAX_PCT, max(SL_MIN_PCT, _d_sl))
        stop_loss = entry * (1 - _sgn_sl * _d_sl)
    # v10.7.5 — keputusan user (Full-Auto): UNTUNG ≥ RUGI. Target AC (ROI
    # margin) minimal = jarak SL × leverage + buffer fee 0.1% harga, dibulatkan
    # ke atas. Contoh SL 1.5% × 35x → AC minimal 56% (bukan 50%).
    if auto_close_pct and mode == "full" and entry > 0 and stop_loss and leverage > 0:
        _sl_pct = abs(entry - float(stop_loss)) / entry
        _min_ac = int(math.ceil(round((_sl_pct + 0.001) * leverage * 100.0, 6)))
        if _min_ac > auto_close_pct:
            logger.info("AC dinaikkan %s%% → %s%% (SL %.2f%% × %sx) %s",
                        auto_close_pct, _min_ac, _sl_pct * 100, leverage, symbol)
            auto_close_pct = _min_ac
    if auto_close_pct and entry > 0:
        _ac_sgn = 1.0 if side == "BUY" else -1.0
        tps = [entry * (1 + _ac_sgn * auto_close_pct / 100.0 / leverage)]
        tp_count = 1
        trailing_callback_rate = 0.0
        # Target user menang: profit-cap/horizon profil & HAR tidak boleh
        # menutup lebih awal (anti tabrakan).
        hit_and_run = False
        horizon_exit = False
    # v10.2.37 — Keputusan user: setelah TP1 hit, SL digeser ke TP1 (SL
    # guard), BUKAN diganti trailing stop (trailing membatalkan SL & sering
    # menutup di sekitar entry). Trailing dimatikan untuk trade baru.
    trailing_callback_rate = 0.0
    # v10.0.9 — Geser ladder: tp_count<3 memakai level TP yang lebih tinggi.
    tps = _shift_tp_ladder(tps, tp_count)
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
    filters = await binance_symbol_filters(is_testnet) or {}
    f = filters.get(base) or {}
    tick = float(f.get("tick") or 0.0)
    step = float(f.get("step") or 0.0)
    if tick <= 0 or step <= 0:
        return {"ok": False, "reason": "symbol_filters_missing",
                "message": f"Tick/step filters for {bin_sym} not found. Retry in a few seconds."}

    # (2) Margin mode: baca posisi saat ini (bisa Nil) → set target
    try:
        pos = await br.position_risk(api_key, api_secret, is_testnet, bin_sym)
    except Exception as e:
        return {"ok": False, "reason": "exchange_unreachable",
                "message": f"Could not read position status: {str(e)[:160]}"}

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
                    f"{bin_sym} has an active {current_mt.upper()} position. "
                    f"Cannot open a new trade in {margin_mode.upper()} mode. "
                    "Close the position first or pick the same margin mode."
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
                    f"A {'LONG' if existing_side == 'BUY' else 'SHORT'} position on {bin_sym} "
                    "is still active. An opposite-side execution would REDUCE your position "
                    "(one-way mode). Close the position first if you want to flip direction."
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
            # v10.1.2 — Binance menolak ganti margin mode bila MASIH ADA
            # open orders di simbol ini ("Position side cannot be changed
            # if there exists open orders"). Bersihkan order menggantung
            # (algo + legacy) lalu coba SEKALI lagi — tanpa ini, sinyal
            # valid di simbol dengan order basi tidak pernah tereksekusi.
            if "open orders" in str(set_mt.get("msg") or "").lower():
                try:
                    await br.cancel_all_algo(
                        api_key, api_secret, is_testnet, bin_sym)
                except Exception:
                    pass
                try:
                    await br.cancel_all_legacy(
                        api_key, api_secret, is_testnet, bin_sym)
                except Exception:
                    pass
                set_mt = await br.set_margin_type(
                    api_key, api_secret, is_testnet,
                    symbol=bin_sym, margin_type=desired_mt_upper,
                )
            if not set_mt.get("ok"):
                return {
                    "ok": False, "reason": "margin_mode_set_failed",
                    "requested": margin_mode,
                    "message": f"Failed to set margin mode {margin_mode.upper()}: {set_mt.get('msg')}",
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
    margin = _resolve_margin(bal, risk_pct, margin_usdt)
    size_usdt = margin * leverage
    qty_raw = size_usdt / entry if entry > 0 else 0.0
    qty = round_to_step(qty_raw, step)
    # v10.2.28 — Clamp ke batas maksimal qty per order Binance
    # (MARKET_LOT_SIZE). Kasus nyata ILV testnet: qty hasil risk%×leverage
    # melebihi batas → -4005 "Quantity greater than max quantity" dan
    # sinyal valid gagal tereksekusi 7× beruntun. Clamp ke BAWAH = risiko
    # berkurang (aman), posisi tetap terbuka dengan ukuran maksimal yang
    # diizinkan exchange.
    max_qty = float(f.get("max_qty") or 0.0)
    qty_clamped = False
    if max_qty > 0 and qty > max_qty:
        qty_clamped = True
        qty = round_to_step(max_qty, step)
        logger.info(
            "qty clamp %s: %.6f → %.6f (batas maksimal Binance)",
            bin_sym, round_to_step(qty_raw, step), qty)
    if qty <= 0:
        return {"ok": False, "reason": "qty_zero",
                "message": "Margin too small for 1 contract step. Raise Risk % or Leverage."}

    # Min notional check (approx — Binance default $5-$20 for USD-M)
    notional = qty * entry
    if notional < 5.0:
        return {"ok": False, "reason": "min_notional",
                "min_notional": 5.0,
                "message": f"Position value ${notional:.2f} is below the $5 minimum. Raise Risk % or Leverage."}

    # Round trigger prices to tick
    sl_price = round_to_tick(float(stop_loss), tick)
    tps_rounded = [round_to_tick(float(t), tick) for t in tps]

    # Validate SL direction vs side (avoid instant trigger)
    close_side = "SELL" if side == "BUY" else "BUY"

    # (5) Place entry — v10.0.1: entry_mode "limit" (harga moderate,
    # expire 2 candle bila tidak terisi) atau "market" (eksekusi instan;
    # SL/TP di-anchor ke fill aktual via anchor_shift di bawah).
    if entry_mode == "market":
        try:
            entry_res = await br.market_order(
                api_key, api_secret, is_testnet,
                symbol=bin_sym, side=side, quantity=qty, reduce_only=False,
            )
        except Exception as e:
            return {"ok": False, "reason": "entry_rejected",
                    "message": f"Entry MARKET ditolak Binance: {str(e)[:200]}"}
        entry_order_id = entry_res.get("orderId")
        filled_now = True
        limit_px = float(entry)
    else:
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
            "hit_and_run": hit_and_run,
            "horizon_exit": horizon_exit,
        "auto_close_pct": auto_close_pct,
        "auto_close_pct_user": auto_close_pct_user,
            "trailing_order_id": None,
            "trailing_activated": False,
            "qty": qty, "leverage": leverage, "risk_pct": risk_pct,
            "margin_mode": margin_mode,
            "actual_margin_mode": None,
            "actual_leverage": None,
            "qty_clamped_max": qty_clamped,
            "layered": layering,
            "anchor_shift": 0,
            "entry_mode": entry_mode,
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
                "message": "Market order sent but position did not appear in the account. Check Binance manually."}

    actual_qty = abs(float(pos_final.get("positionAmt") or 0))
    actual_entry = float(pos_final.get("entryPrice") or entry)
    actual_mm = str(pos_final.get("marginType") or margin_mode).lower()
    # v9.9.3 — Baca leverage AKTUAL dari Binance. Jika set_leverage gagal
    # diam-diam (mis. request 50x tapi tier notional hanya izinkan 20x),
    # simpan yang benar supaya UI tidak menampilkan angka request palsu.
    # v10.6.8 — positionRisk v3 bisa mengembalikan leverage "0"/kosong →
    # pakai leverage request bila nilai Binance tidak valid (≤0).
    try:
        _lv_ex = int(float(pos_final.get("leverage") or 0))
    except (TypeError, ValueError):
        _lv_ex = 0
    actual_leverage = _lv_ex if _lv_ex > 0 else int(leverage)

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

    # v10.2.35 — GUARD TP vs MARK PRICE TERKINI (bukan hanya vs entry).
    # Kasus user (AI Suggestions): harga bergerak melewati TP antara fill
    # entry & pemasangan bracket → Binance -2021 "Order would immediately
    # trigger" → 3× retry gagal → posisi di-rollback ("tidak bisa
    # execute"). Fix level-eksekusi (formula TP/SL tidak disentuh):
    # trigger yang sudah terlewati di-clamp ke jarak minimal valid dari
    # mark (0.1% ke arah profit) agar bracket tetap terpasang.
    try:
        _mark_now = float(pos_final.get("markPrice") or 0.0)
    except Exception:
        _mark_now = 0.0
    if _mark_now > 0:
        _clamped_tps: list[float] = []
        for _t in tps_rounded:
            if side == "BUY" and _t <= _mark_now:
                _t = round_to_tick(_mark_now * 1.001, tick)
                if _t <= _mark_now:
                    _t = round_to_tick(_mark_now + tick, tick)
            elif side == "SELL" and _t >= _mark_now:
                _t = round_to_tick(_mark_now * 0.999, tick)
                if _t >= _mark_now:
                    _t = round_to_tick(_mark_now - tick, tick)
            _clamped_tps.append(_t)
        tps_rounded = _clamped_tps

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
                    f"Entry succeeded, bracket FAILED ({detail}), rollback also FAILED. "
                    "Close the position manually on Binance IMMEDIATELY!"
                ),
                "requires_manual_action": True,
                "symbol": bin_sym, "qty": actual_qty, "side": side,
            }
        return {
            "ok": False, "reason": reason,
            "message": (
                f"SL/TP bracket could not be placed on Binance ({detail}). "
                + ("Combined position (incl. previous layers) was auto-closed. "
                   if layering else "Position was auto-closed. ")
                + "Your balance is safe. Please try again."
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
            # v10.2.35 — -2021 "would immediately trigger" pada SL:
            # harga SUDAH menembus level stop saat bracket dipasang →
            # retry dengan harga yang sama tidak akan pernah berhasil.
            # Hentikan retry; posisi memang sudah seharusnya tertutup.
            if "-2021" in sl_error:
                sl_error = ("price already beyond stop level "
                            f"({sl_error})")
                break
            await asyncio.sleep(0.4)

    if not sl_algo_id:
        return await _emergency_close("bracket_sl_failed", sl_error or "SL unknown")

    # (8) Place TPs — split qty
    tp_parts = _split_tp_qty(actual_qty, step, tp_count)
    tp_algo_ids: list[str | None] = []
    tp_errors: list[str] = []
    # v10.4.1 — AC aktif: HANYA SL di exchange. TP order tidak dikirim;
    # AC monitor backend menutup posisi via market order saat ROI tercapai.
    for i, tp in enumerate(tps_rounded[:(0 if auto_close_pct else tp_count)]):
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
                # v10.2.35 — -2021: harga sudah melewati target TP saat
                # bracket dipasang (pasar bergerak cepat). Ambil mark
                # terkini lalu clamp trigger ke jarak minimal valid
                # (0.1% ke arah profit) dan coba lagi — eksekusi tidak
                # boleh batal total hanya karena pasar bergerak duluan.
                if "-2021" in last_err:
                    try:
                        _pos = await br.position_risk(
                            api_key, api_secret, is_testnet, bin_sym)
                        _m = float((_pos or {}).get("markPrice") or 0.0)
                        if _m > 0:
                            if side == "BUY" and tp <= _m:
                                tp = round_to_tick(_m * 1.001, tick)
                                if tp <= _m:
                                    tp = round_to_tick(_m + tick, tick)
                            elif side == "SELL" and tp >= _m:
                                tp = round_to_tick(_m * 0.999, tick)
                                if tp >= _m:
                                    tp = round_to_tick(_m - tick, tick)
                    except Exception:
                        pass
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
    expected_tp_count = 0 if auto_close_pct else sum(1 for p in tp_parts if p > 0)

    # SL must be verified. If TP partial failure → still rollback (user
    # requirement: tidak boleh ada tanda unprotected sama sekali).
    if not sl_verified:
        return await _emergency_close(
            "bracket_sl_not_verified",
            f"SL algoId {sl_algo_id} not visible in openAlgoOrders",
        )
    if tp_verified_count < expected_tp_count:
        return await _emergency_close(
            "bracket_tp_incomplete",
            f"{tp_verified_count}/{expected_tp_count} TP placed. {'; '.join(tp_errors)[:150]}",
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
        "hit_and_run": hit_and_run,
        "horizon_exit": horizon_exit,
        "auto_close_pct": auto_close_pct,
        "auto_close_pct_user": auto_close_pct_user,
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
        "entry_mode": entry_mode,
        "qty_clamped_max": qty_clamped,
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
        "hit_and_run": "kiss pivot" in str(formula_tag or "").lower(),
        "horizon_exit": str(profile or "").lower() in PROFILE_PROFIT_CAP_ROE,
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
    filters = await binance_symbol_filters(is_testnet) or {}
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
    _ac_trade = int(trade.get("auto_close_pct") or 0) > 0  # v10.4.1 — SL-only

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
    if _ac_trade:
        tp_parts = []
        notes.append("AC mode — SL only (no TP orders)")
    elif legacy_tp_close:
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
            # v10.2.26 — positionRisk SUKSES & flat → tidak ada yang perlu
            # ditutup; jangan kirim market order sia-sia (DB qty bisa
            # basi). Sebelumnya jatuh ke qty DB → Binance -2022 → user
            # melihat "gagal closing".
            if live <= 0:
                return {"ok": True, "id": None, "avg": None,
                        "note": "no_position"}
            qty = live
        except Exception:
            pass
        # v10.2.26 — PRECISION FIX untuk SEMUA kartu: qty live dari
        # positionRisk bisa mengandung sisa desimal di luar stepSize
        # (mis. 58.113 padahal step 0.01 setelah partial TP) → Binance
        # menolak market close dengan error LOT_SIZE dan user melihat
        # "gagal closing" walau posisi masih terbuka. Bulatkan TURUN ke
        # step; sisa debu di bawah 1 step tidak bisa diorder (Binance
        # memang menolaknya) dan akan dibersihkan monitor.
        _max_qty = 0.0
        if qty > 0:
            try:
                _base = symbol.upper().split("/")[0].split("USDT")[0].split("-")[0]
                _filt = await binance_symbol_filters(bool(doc.get("testnet", True)))
                _fsym = (_filt or {}).get(_base) or {}
                _step = _fsym.get("step") or 0.0
                qty = round_to_step(qty, _step)
                # v10.2.34 — Ambil juga batas maksimal qty per order
                # (MARKET_LOT_SIZE) untuk chunked close di bawah.
                _max_qty = float(_fsym.get("max_qty") or 0.0)
            except Exception:
                pass
        if qty <= 0:
            return {"ok": True, "id": None, "avg": None, "note": "no_position"}
    client = await _get_client(doc)
    try:
        exch_sym = _ccxt_symbol(doc["exchange"], symbol)
        # v10.2.34 — CHUNKED CLOSE (kasus nyata JUP testnet: posisi
        # 15236 > batas maksimal 1 market order → Binance -4005 "Quantity
        # greater than max quantity", CLOSE gagal total 4× dan user
        # melihat tombol aktif lagi tanpa penjelasan). Tutup posisi
        # besar dengan beberapa market order reduceOnly berukuran
        # ≤ max_qty sampai habis.
        placed: list[dict[str, Any]] = []
        remaining = qty
        while remaining > 1e-12:
            chunk = remaining
            if _max_qty > 0 and chunk > _max_qty:
                try:
                    _base = symbol.upper().split("/")[0].split("USDT")[0].split("-")[0]
                    _filt = await binance_symbol_filters(bool(doc.get("testnet", True)))
                    _step = ((_filt or {}).get(_base) or {}).get("step") or 0.0
                    chunk = round_to_step(_max_qty, _step)
                except Exception:
                    chunk = _max_qty
            if chunk <= 0:
                break
            try:
                o = await client.create_order(
                    exch_sym, "market", _opposite(side), chunk, None,
                    params={"reduceOnly": True},
                )
                placed.append(o)
                remaining = round(remaining - chunk, 10)
            except Exception as close_err:
                # v10.2.26 — Posisi ternyata SUDAH flat di exchange (mis. SL
                # tersentuh tepat sebelum user menekan CLOSE, atau close
                # sebelumnya sukses tapi respons API gagal): Binance menolak
                # reduceOnly dengan -2022. Perlakukan sebagai SUKSES —
                # tujuan user (posisi tertutup) sudah tercapai; kartu harus
                # ditandai closed, bukan melempar error 500 yang
                # membingungkan.
                _msg = str(close_err).lower()
                if "reduceonly" in _msg or "-2022" in _msg or "no position" in _msg:
                    logger.info("close_position %s: posisi sudah flat (%s)",
                                symbol, close_err)
                    return {"ok": True, "id": None, "avg": None,
                            "note": "no_position"}
                raise
        last = placed[-1] if placed else {}
        return {"ok": True, "id": last.get("id"), "avg": last.get("average"),
                "chunks": len(placed)}
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


async def move_sl_to_breakeven(
    doc: dict[str, Any], trade: dict[str, Any],
    target_price: float | None = None,
) -> dict[str, Any]:
    """v10.0.13/16 — SL GUARD: pindahkan SL native Binance ke harga target.

    • target_price=None → break-even (harga entry).
    • target_price=TPx  → SL guard mengikuti TP yang baru ter-isi
      (v10.0.16: TP1 hit → SL=TP1; TP2 hit → SL=TP2).

    Buffer 0.1% diberikan ke arah aman supaya Binance tidak menolak
    trigger yang persis sama dengan mark (error -2021 "would immediately
    trigger").

    Hanya aktif untuk Binance (native). Trade yang pakai trailing
    (trailing_callback_rate > 0) tidak masuk ke jalur ini — trailing
    sudah mengambil alih via `_maybe_activate_trailing`.

    Returns {"ok": bool, "new_sl": float|None, "detail": str}.
    """
    if (doc.get("exchange") or "").lower() != "binance":
        return {"ok": False, "detail": "not binance"}
    entry = float(trade.get("entry_price") or 0)
    side = trade.get("side")
    if not entry or side not in ("BUY", "SELL"):
        return {"ok": False, "detail": "no entry/side"}
    # v10.7.15 — keputusan user: TIDAK ada break-even ke harga entry.
    # Hanya SL guard ke level TP (TP1→SL=TP1, TP2→SL=TP2) yang dilayani.
    if not target_price:
        return {"ok": False, "detail": "break-even disabled (v10.7.15)"}
    raw_target = float(target_price)
    # Buffer 0.1% ke sisi aman (di bawah target utk LONG, di atas utk SHORT).
    guard_px = raw_target * (0.999 if side == "BUY" else 1.001)
    api_key = decrypt(doc["api_key_enc"])
    api_secret = decrypt(doc["api_secret_enc"])
    is_testnet = bool(doc.get("testnet", True))
    sym = str(trade.get("symbol") or "").upper()
    base = sym.split("/")[0].split("USDT")[0].split("-")[0]
    bin_sym = base + "USDT"
    # Rounding harga ke tickSize supaya triggerPrice tidak ditolak -1111.
    be_price = guard_px
    try:
        from .whitelist import binance_symbol_filters, round_to_tick
        filters = await binance_symbol_filters(is_testnet) or {}
        tick = (filters.get(base) or {}).get("tick") or 0.0
        if tick > 0:
            be_price = round_to_tick(guard_px, tick)
    except Exception:
        pass
    close_side = "SELL" if side == "BUY" else "BUY"
    # Cancel SL lama (STOP_MARKET closePosition searah).
    try:
        openalgos = await br.open_algo_orders(
            api_key, api_secret, is_testnet, bin_sym)
    except Exception:
        openalgos = []
    for a in openalgos or []:
        if (a.get("orderType") == "STOP_MARKET"
                and a.get("side") == close_side
                and a.get("closePosition") in (True, "true", "True")):
            try:
                await br.cancel_algo(
                    api_key, api_secret, is_testnet, algo_id=a.get("algoId"))
            except Exception:
                pass
    # Legacy conditional orders (TP/SL manual) juga dibersihkan.
    try:
        legacy = await br.open_orders_legacy(
            api_key, api_secret, is_testnet, bin_sym)
    except Exception:
        legacy = []
    for o in legacy or []:
        if (bool(o.get("closePosition"))
                and str(o.get("type", "")).startswith("STOP")
                and o.get("side") == close_side):
            try:
                await br.cancel_order(
                    api_key, api_secret, is_testnet,
                    symbol=bin_sym, order_id=o.get("orderId"))
            except Exception:
                pass
    # Pasang SL baru di harga entry (closePosition=True).
    try:
        resp = await br.place_algo(
            api_key, api_secret, is_testnet,
            symbol=bin_sym, side=close_side,
            order_type="STOP_MARKET", trigger_price=be_price,
            close_position=True,
        )
        return {"ok": True, "new_sl": be_price,
                "algo_id": resp.get("algoId"), "detail": "moved"}
    except Exception as e:
        return {"ok": False, "new_sl": be_price, "detail": str(e)[:200]}



async def reconcile_trade_fills(
    doc: dict[str, Any],
    trade: dict[str, Any],
    *,
    tolerance: float = 0.004,
) -> dict[str, Any]:
    """v10.2.20 — Rekonsiliasi tp_fills & sl_fill dari userTrades riil
    (Binance). Dibuat setelah bug 'TP tertelan' agar baris 'TPx hit' /
    'SL hit' selalu muncul di kartu — bahkan untuk trade yang partial-
    reduce-nya dulu gagal ter-atribusi karena lookup harga sesaat
    error (akar bug ZEC/LINK/SOL/ADA 2026-10-16).

    Prinsip (general, bukan per-koin):
    * Ambil semua fill reduce-only sejak created_at.
    * Cocokkan tiap fill ke level TP (toleransi 0.4%) atau SL
      (toleransi 0.4%, atau toleransi 1% bila terjadi gap/slippage).
    * Isi/lengkapi tp_fills[] & sl_fill (idempoten: fill yg sudah
      tercatat berdasarkan orderId tidak diduplikasi).
    * Perbaiki close_reason bila doc menandai 'position_closed_
      externally' padahal fill-nya di level TP/SL.
    """
    if (doc.get("exchange") or "").lower() != "binance":
        return {}
    try:
        api_key = decrypt(doc["api_key_enc"])
        api_secret = decrypt(doc["api_secret_enc"])
        is_testnet = bool(doc.get("testnet", True))
    except Exception:
        return {}
    base = str(trade.get("symbol") or "").replace("/USDT", "").replace("USDT", "")
    if not base:
        return {}
    exch_sym = base + "USDT"
    created_at = trade.get("created_at")
    try:
        from datetime import datetime as _dt, timezone as _tz
        start_ms = int(_dt.fromisoformat(
            str(created_at).replace("Z", "+00:00")).timestamp() * 1000) - 60_000
    except Exception:
        return {}
    code, fills = await br._request(
        "GET", "/fapi/v1/userTrades", api_key, api_secret, is_testnet,
        {"symbol": exch_sym, "limit": "100", "startTime": str(start_ms)})
    if code != 200 or not isinstance(fills, list):
        return {}
    side = str(trade.get("side") or "").upper()
    reduce_side = "BUY" if side == "SELL" else "SELL"
    closed_at = trade.get("closed_at")
    end_ms: int | None = None
    try:
        if closed_at:
            from datetime import datetime as _dt2
            end_ms = int(_dt2.fromisoformat(
                str(closed_at).replace("Z", "+00:00")).timestamp() * 1000) + 60_000
    except Exception:
        end_ms = None
    rfills = [f for f in fills
              if f.get("side") == reduce_side
              and (end_ms is None or f.get("time", 0) <= end_ms)]
    tps = [float(x) for x in (trade.get("take_profits") or [])][:3]
    sl = float(trade.get("stop_loss") or 0) or None
    tp_fills_in = list(trade.get("tp_fills") or [])
    seen_order_ids = {str(x.get("orderId") or "")
                      for x in tp_fills_in if x.get("orderId") is not None}
    tp_fills_new = list(tp_fills_in)
    sl_fill_new: dict[str, Any] | None = trade.get("sl_fill")
    taken_tp_idx: set[int] = set()
    for _x in tp_fills_in:
        _lvl = str(_x.get("level") or "")
        if _lvl.startswith("TP"):
            try:
                taken_tp_idx.add(int(_lvl.replace("TP", "")) - 1)
            except Exception:
                pass
    from datetime import datetime as _dtf, timezone as _tzf
    for f in rfills:
        oid = str(f.get("orderId") or "")
        if oid and oid in seen_order_ids:
            continue
        try:
            fx = float(f["price"]); fq = float(f["qty"]); rp = float(f["realizedPnl"])
        except Exception:
            continue
        when = _dtf.fromtimestamp(f["time"] / 1000, tz=_tzf).isoformat()
        matched = False
        for i, tp in enumerate(tps):
            if i in taken_tp_idx or tp <= 0:
                continue
            if abs(fx - tp) / tp < tolerance:
                tp_fills_new.append({
                    "level": f"TP{i+1}", "price": fx, "qty": fq,
                    "pnl": round(rp, 4), "at": when,
                    "orderId": f.get("orderId"), "reconciled": True,
                })
                taken_tp_idx.add(i)
                matched = True
                break
        if matched:
            continue
        if sl and abs(fx - sl) / sl < max(tolerance, 0.01):
            # SL hit (toleransi lebih longgar — SL sering slippage).
            sl_fill_new = {
                "level": "SL", "price": fx, "qty": fq,
                "pnl": round(rp, 4), "at": when,
                "orderId": f.get("orderId"), "reconciled": True,
            }
    upd: dict[str, Any] = {}
    if len(tp_fills_new) != len(tp_fills_in):
        upd["tp_fills"] = tp_fills_new
        n_tp = len(trade.get("take_profits") or []) or 3
        tp_filled = [False] * n_tp
        for x in tp_fills_new:
            try:
                idx = int(str(x.get("level")).replace("TP", "")) - 1
                if 0 <= idx < n_tp:
                    tp_filled[idx] = True
            except Exception:
                pass
        upd["tp_filled"] = tp_filled
    if sl_fill_new is not None and sl_fill_new is not trade.get("sl_fill"):
        upd["sl_fill"] = sl_fill_new
    # Perbaiki close_reason bila 'position_closed_externally' padahal
    # sebenarnya hit TP/SL yang jelas.
    status = str(trade.get("status") or "").lower()
    reason = str(trade.get("close_reason") or "").lower()
    if status == "closed" and reason == "position_closed_externally":
        if upd.get("sl_fill") or sl_fill_new:
            upd["close_reason"] = "SL"
            upd["close_reason_detail"] = "reconciled from userTrades (v10.2.20)"
        elif upd.get("tp_fills") or tp_fills_new:
            # pakai TP paling terakhir yang hit
            levels = [str(x.get("level")) for x in (upd.get("tp_fills") or tp_fills_new)
                      if str(x.get("level") or "").startswith("TP")]
            if levels:
                upd["close_reason"] = levels[-1]
                upd["close_reason_detail"] = "reconciled from userTrades (v10.2.20)"
    return upd


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
    _ghost_extra: dict[str, Any] = {}
    # v10.3.4 — GHOST FIX: posisi di Binance berlawanan arah dgn trade ini
    # (one-way mode) → posisi milik trade ini sudah tidak ada.
    if abs(amt) > 0 and ((amt > 0) != (str(trade.get("side") or "BUY") == "BUY")):
        amt = 0.0
    if abs(amt) > 0:
        unrealized = float(pos.get("unRealizedProfit") or 0)
        actual_mm = str(pos.get("marginType") or "").lower()
        mark = pos.get("markPrice")
        actual_lev = int(float(pos.get("leverage") or trade.get("leverage") or 0))
        # v10.2.20 — ENGINE LOSSLESS FILL ATTRIBUTION (ganti total jalur
        # last_reduce_fill_price yang bisa gagal titik-tunggal). Alih-
        # alih menebak harga reduksi dari satu panggilan API, engine
        # sekarang menyusuri /fapi/v1/userTrades sejak `last_fill_check_ms`
        # dan meng-atribusi SETIAP fill reduce-only ke level TP (toleransi
        # 0.4%) atau SL (toleransi 1% karena slippage). Idempoten via
        # orderId; jika panggilan gagal, `last_fill_check_ms` TIDAK
        # dimajukan sehingga tick berikutnya mengulang window yang sama
        # — mustahil ada event TP/SL yang tertelan. SL guard mengikuti
        # setiap TP yang baru ter-isi.
        _native_partial_upd: dict[str, Any] = {}
        try:
            new_qty = abs(amt)
            tps = [float(x) for x in (trade.get("take_profits") or []) if x]
            tp_fills_in = list(trade.get("tp_fills") or [])
            seen_order_ids = {str(x.get("orderId") or "")
                              for x in tp_fills_in if x.get("orderId") is not None}
            taken_tp_idx: set[int] = set()
            for x in tp_fills_in:
                lvl = str(x.get("level") or "")
                if lvl.startswith("TP"):
                    try:
                        taken_tp_idx.add(int(lvl.replace("TP", "")) - 1)
                    except Exception:
                        pass
            sl_level = float(trade.get("stop_loss") or 0) or None
            sl_fill_existing = trade.get("sl_fill")
            # Window check-point (ms). Default = created_at − 60s saat
            # trade baru dibuat atau belum pernah dicek.
            prev_check_ms = int(trade.get("last_fill_check_ms") or 0)
            if prev_check_ms <= 0:
                try:
                    prev_check_ms = int(datetime.fromisoformat(
                        str(trade.get("created_at")).replace("Z", "+00:00")
                    ).timestamp() * 1000) - 60_000
                except Exception:
                    prev_check_ms = int(datetime.now(timezone.utc).timestamp() * 1000) - 86_400_000
            fills: list[dict[str, Any]] = []
            fetch_ok = False
            try:
                code, data = await br._request(
                    "GET", "/fapi/v1/userTrades", api_key, api_secret, is_testnet,
                    {"symbol": bin_sym, "limit": "100", "startTime": str(prev_check_ms)})
                if code == 200 and isinstance(data, list):
                    fills = data
                    fetch_ok = True
            except Exception:
                fetch_ok = False
            if fetch_ok and (tps or sl_level):
                side_u = str(trade.get("side") or "").upper()
                reduce_side = "BUY" if side_u == "SELL" else "SELL"
                tp_fills_new = list(tp_fills_in)
                sl_fill_new = sl_fill_existing
                max_fill_time = prev_check_ms
                # Urutkan ascending waktu agar atribusi mengikuti urutan
                # eksekusi (penting bila 2 TP di tick sama).
                for f in sorted(fills, key=lambda x: int(x.get("time") or 0)):
                    try:
                        if f.get("side") != reduce_side:
                            continue
                        oid = str(f.get("orderId") or "")
                        if oid and oid in seen_order_ids:
                            continue
                        fx = float(f["price"]); fq = float(f["qty"])
                        rp = float(f["realizedPnl"])
                        when_ms = int(f.get("time") or 0)
                    except Exception:
                        continue
                    if when_ms > max_fill_time:
                        max_fill_time = when_ms
                    when_iso = datetime.fromtimestamp(
                        when_ms / 1000, tz=timezone.utc).isoformat()
                    # 1) Cocokkan ke TP level unfilled (toleransi 0.4%).
                    matched_tp = False
                    for i, tp in enumerate(tps[:3]):
                        if i in taken_tp_idx or tp <= 0:
                            continue
                        if abs(fx - tp) / tp < 0.004:
                            tp_fills_new.append({
                                "level": f"TP{i+1}", "price": round(fx, 10),
                                "qty": round(fq, 10),
                                "pnl": round(rp, 4), "at": when_iso,
                                "orderId": f.get("orderId"),
                            })
                            taken_tp_idx.add(i)
                            seen_order_ids.add(oid)
                            matched_tp = True
                            break
                    if matched_tp:
                        continue
                    # 2) Cocokkan ke SL level (toleransi 1% untuk slippage).
                    if (sl_level and sl_fill_new is None
                            and abs(fx - sl_level) / sl_level < 0.01):
                        sl_fill_new = {
                            "level": "SL", "price": round(fx, 10),
                            "qty": round(fq, 10),
                            "pnl": round(rp, 4), "at": when_iso,
                            "orderId": f.get("orderId"),
                        }
                        seen_order_ids.add(oid)
                        continue
                    # 3) Reduce di luar level TP/SL (manual close dsb) →
                    #    tidak dilabeli; cukup catat di seen agar tidak
                    #    diulang.
                    seen_order_ids.add(oid)
                # Terapkan hasil.
                if len(tp_fills_new) != len(tp_fills_in):
                    _native_partial_upd["tp_fills"] = tp_fills_new
                    n_tp = len(tps) or 3
                    tp_filled_arr = [False] * n_tp
                    for x in tp_fills_new:
                        try:
                            idx = int(str(x.get("level")).replace("TP", "")) - 1
                            if 0 <= idx < n_tp:
                                tp_filled_arr[idx] = True
                        except Exception:
                            pass
                    _native_partial_upd["tp_filled"] = tp_filled_arr
                    # SL GUARD: ikuti TP tertinggi yang baru ter-isi.
                    highest_new = -1
                    for x in tp_fills_new[len(tp_fills_in):]:
                        try:
                            idx = int(str(x.get("level")).replace("TP", "")) - 1
                            if idx > highest_new:
                                highest_new = idx
                        except Exception:
                            pass
                    if (highest_new >= 0
                            and not trade.get("trailing_activated")
                            and float(trade.get("trailing_callback_rate") or 0) <= 0
                            and int(trade.get("sl_guard_idx") or 0) <= highest_new):
                        try:
                            sg_res = await move_sl_to_breakeven(
                                doc, trade, target_price=tps[highest_new])
                        except Exception as _e:  # noqa: BLE001
                            sg_res = {"ok": False, "detail": str(_e)[:200]}
                        _native_partial_upd["sl_guard_idx"] = highest_new + 1
                        _native_partial_upd["sl_guard_detail"] = sg_res.get("detail")
                        _native_partial_upd["be_moved"] = True
                        if sg_res.get("ok") and sg_res.get("new_sl"):
                            _native_partial_upd["stop_loss"] = float(sg_res["new_sl"])
                        else:
                            _native_partial_upd["stop_loss"] = float(tps[highest_new])
                if sl_fill_new is not None and sl_fill_new is not sl_fill_existing:
                    _native_partial_upd["sl_fill"] = sl_fill_new
                _native_partial_upd["qty_remaining"] = round(new_qty, 10)
                _native_partial_upd["prev_position_amt"] = round(new_qty, 10)
                # Majukan check-point HANYA bila fetch sukses.
                _native_partial_upd["last_fill_check_ms"] = max_fill_time + 1
            else:
                # Fetch gagal → jangan majukan check-point apa pun.
                # Posisi update qty tetap aman (dari positionRisk).
                _native_partial_upd["qty_remaining"] = round(new_qty, 10)
        except Exception:
            # Error tak terduga: tidak boleh menelan event (biarkan tick
            # berikutnya mengulang window yang sama).
            _native_partial_upd = {}
        # v10.2.16 — PROFILE HORIZON EXIT (keputusan user): "bot masuk
        # dan keluar sesuai waktu profil". Berlaku untuk SEMUA formula
        # pada trade BARU (flag horizon_exit) di profil Scalper/Intraday/
        # Swing — posisi existing & Confluence v9 tidak terdampak.
        #   1) Profit ROE ≥ cap (Scalper 10% · Intraday 15% · Swing 25%)
        #      → market-close SEKARANG ("jika sudah profit diatas X% -
        #      close").
        #   2) Umur ≥ horizon maks (15m / 4h / 24h dari entry) & posisi
        #      masih profit → market-close (keluar sesuai waktu profil).
        #   3) Posisi loss saat horizon habis → dibiarkan ke SL.
        #   Confluence v9 (longterm): TIDAK ada cap & tidak ada batas
        #   waktu — holding mengikuti SL/TP1-3.
        if ((trade.get("horizon_exit") or trade.get("hit_and_run"))
                and not trade.get("trailing_activated")
                and not _native_partial_upd.get("trailing_activated")):
            try:
                _hp = str(trade.get("profile") or "day").lower()
                _hx_entry_px = float(trade.get("entry_price") or 0)
                _hx_mark = float(mark or 0)
                _hx_sign = 1.0 if trade.get("side") == "BUY" else -1.0
                _hx_profit = bool(
                    _hx_mark and _hx_entry_px
                    and (_hx_mark - _hx_entry_px) * _hx_sign > 0)
                _hx_close_why = None
                _hx_cap = PROFILE_PROFIT_CAP_ROE.get(_hp)
                if _hx_cap and _hx_mark and _hx_entry_px:
                    _hx_lev = float(trade.get("actual_leverage")
                                    or trade.get("leverage") or 1)
                    _hx_roe = ((_hx_mark - _hx_entry_px) * _hx_sign
                               / _hx_entry_px * _hx_lev * 100)
                    if _hx_roe >= _hx_cap:
                        _hx_close_why = f"profit_cap_{_hx_cap:g}pct"
                # v10.7.15 — keputusan user: horizon (batas waktu profil)
                # DIHAPUS sepenuhnya — tidak close, tidak geser SL ke entry.
                # Posisi berjalan sampai TP/SL asli saat entry.
                if _hx_close_why:
                    _cr = await close_position(
                        doc, symbol, trade.get("side") or "BUY", abs(amt))
                    _native_partial_upd["horizon_exit_at"] = (
                        _hx_close_why if _cr.get("ok")
                        else f"close_failed: {str(_cr)[:120]}")
            except Exception as _e:  # noqa: BLE001
                _native_partial_upd["horizon_exit_error"] = str(_e)[:200]
        # v10.2.21 — EARLY-EXIT STALE LONGTERM (Confluence v9): posisi
        # longterm yg berjalan >LONGTERM_STALE_HOURS jam TAPI tidak
        # pernah mencapai profit floating > LONGTERM_STALE_MIN_PROFIT_PCT
        # ditutup di market agar tidak kena SL penuh (kasus BCH/XTZ
        # 16/10 yang grind lawan arah 6+ jam sampai SL). Memakai
        # pct_floating saat ini + histori max tersimpan di DB.
        try:
            _lp = str(trade.get("profile") or "").lower()
            _lt_tag = str(trade.get("formula_tag") or "").lower()
            _is_longterm = (
                _lp in ("longterm", "long_term", "long-term", "swing")
                or "confluence" in _lt_tag)
            if _is_longterm and amt and not _native_partial_upd.get("horizon_exit_at"):
                from asi_bot.scheduler import (
                    LONGTERM_STALE_HOURS as _LT_H,
                    LONGTERM_STALE_MIN_PROFIT_PCT as _LT_MIN,
                )
                _entry_px = float(trade.get("entry_price") or 0)
                try:
                    _mark_px = float(mark or 0)
                except Exception:
                    _mark_px = 0.0
                _sign = 1.0 if (trade.get("side") or "BUY") == "BUY" else -1.0
                _pct = (((_mark_px - _entry_px) / _entry_px) * 100.0 * _sign
                        if _entry_px and _mark_px else None)
                _prev_max = float(trade.get("max_floating_pct") or -1e9)
                if _pct is not None and _pct > _prev_max:
                    _native_partial_upd["max_floating_pct"] = round(_pct, 4)
                    _effective_max = _pct
                else:
                    _effective_max = _prev_max
                _entry_at = trade.get("filled_at") or trade.get("created_at")
                _age_h = None
                if _entry_at:
                    try:
                        _age_h = (
                            datetime.now(timezone.utc)
                            - datetime.fromisoformat(
                                str(_entry_at).replace("Z", "+00:00"))
                        ).total_seconds() / 3600.0
                    except Exception:
                        _age_h = None
                if (_age_h is not None and _age_h >= _LT_H
                        and _effective_max < _LT_MIN
                        and _effective_max > -1e8):
                    _cr2 = await close_position(
                        doc, symbol, trade.get("side") or "BUY", abs(amt))
                    _native_partial_upd["stale_exit_at"] = (
                        f"longterm_stale_{_age_h:.1f}h_max{_effective_max:+.2f}pct"
                        if _cr2.get("ok") else f"close_failed: {str(_cr2)[:120]}")
                    _native_partial_upd["close_reason"] = "stale_exit"
        except Exception as _se:  # noqa: BLE001
            _native_partial_upd["stale_exit_error"] = str(_se)[:200]
        # Verify bracket still armed in openAlgoOrders
        try:
            openalgos = await br.open_algo_orders(api_key, api_secret, is_testnet, bin_sym)
        except Exception:
            openalgos = None
        bracket_live = None
        sl_live = None
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
            bracket_live = sl_live and (tp_live or int(trade.get("auto_close_pct") or 0) > 0)
        upd: dict[str, Any] = {
            "status": "open",
            "pnl_usdt": round(unrealized, 2),
            "mark_price": float(mark) if mark else None,
            "actual_margin_mode": actual_mm,
            "actual_leverage": actual_lev,
            **_native_partial_upd,
        }
        if bracket_live is not None:
            upd["bracket_live"] = bracket_live
            # v9.9.10 — bracket terverifikasi (algo ATAU legacy) → tandai
            # hard & hapus label soft yang salah.
            if bracket_live:
                upd["bracket_type"] = "hard"
                upd["soft_bracket"] = False
                upd["soft_bracket_reason"] = None
        # v10.4.1 — AC MONITOR: ROI margin (mark vs entry × leverage) ≥ AC%
        # → tutup qty trade ini via market order (reduce-only, chunked).
        _ac = int(trade.get("auto_close_pct") or 0)
        _ent_ac = float(trade.get("entry_price") or 0)
        _lev_ac = float(trade.get("actual_leverage") or trade.get("leverage") or 0)
        if _ac > 0 and _ent_ac > 0 and _lev_ac > 0 and mark:
            _sg_ac = 1.0 if trade.get("side") == "BUY" else -1.0
            _roi = (float(mark) - _ent_ac) / _ent_ac * _lev_ac * _sg_ac * 100.0
            if _roi >= _ac:
                _q_ac = min(float(trade.get("qty_remaining") or trade.get("qty") or abs(amt)), abs(amt))
                try:
                    _r_ac = await close_position(doc, symbol, trade.get("side") or "BUY", _q_ac)
                except Exception as _e:  # noqa: BLE001
                    _r_ac = {"ok": False, "detail": str(_e)[:200]}
                if _r_ac.get("ok"):
                    _now_ac = datetime.now(timezone.utc).isoformat()
                    _px_ac = float(_r_ac.get("avg") or mark)
                    _pnl_ac = round((_px_ac - _ent_ac) * _q_ac * _sg_ac, 2)
                    return {
                        "status": "closed", "close_reason": "AC",
                        "close_reason_detail": f"auto_close {_ac}% ROI reached ({_roi:.1f}%)",
                        "closed_price": _px_ac, "closed_at": _now_ac, "updated_at": _now_ac,
                        "pnl_usdt": _pnl_ac,
                        "tp_fills": [{"level": "TP1", "price": _px_ac, "qty": _q_ac,
                                      "pnl": _pnl_ac, "at": _now_ac}],
                    }
                upd["ac_close_error"] = str(_r_ac)[:200]
        # v10.3.4 — GHOST FIX: qty milik trade ini sudah habis ter-reduce
        # (SL/TP fill tercatat) walau Binance masih punya posisi simbol ini
        # (milik trade/bot lain di akun yg sama) → tutup record ini.
        _merged = {**trade, **_native_partial_upd}
        _own_qty = float(trade.get("qty") or 0)
        _reduced = sum(float(x.get("qty") or 0) for x in (_merged.get("tp_fills") or [])) \
            + float((_merged.get("sl_fill") or {}).get("qty") or 0)
        if _own_qty > 0 and _reduced >= _own_qty * 0.98:
            trade = _merged
            _ghost_extra = {k: v for k, v in _native_partial_upd.items()
                            if k in ("sl_fill", "tp_fills", "tp_filled", "last_fill_check_ms")}
        else:
            # v10.3.4 — SL HILANG: order SL tidak ada di Binance & harga
            # sudah melewati SL → tutup qty trade ini di market (darurat).
            _sl = float(trade.get("stop_loss") or 0)
            _mk = float(mark or 0)
            _crossed = bool(_sl and _mk) and (
                _mk <= _sl if trade.get("side") == "BUY" else _mk >= _sl)
            if sl_live is False and _crossed:
                _q = min(float(trade.get("qty_remaining") or _own_qty or abs(amt)), abs(amt))
                try:
                    _er = await close_position(doc, symbol, trade.get("side") or "BUY", _q)
                except Exception as _e:  # noqa: BLE001
                    _er = {"ok": False, "detail": str(_e)[:200]}
                if _er.get("ok"):
                    _now_e = datetime.now(timezone.utc).isoformat()
                    _px = float(_er.get("avg") or _mk)
                    _ent = float(trade.get("entry_price") or 0)
                    _sg = 1.0 if trade.get("side") == "BUY" else -1.0
                    _pnl = round((_px - _ent) * _q * _sg, 2) if _ent else round(unrealized, 2)
                    return {
                        "status": "closed", "close_reason": "SL",
                        "close_reason_detail": "sl_missing_emergency_close (v10.3.4)",
                        "closed_price": _px, "closed_at": _now_e, "updated_at": _now_e,
                        "pnl_usdt": _pnl,
                        "sl_fill": {"level": "SL", "price": _px, "qty": _q,
                                    "pnl": _pnl, "at": _now_e},
                    }
                upd["emergency_close_error"] = str(_er)[:200]
            return upd
    # Position closed.
    # v10.1.1 — PnL & harga close diambil dari FILLS AKTUAL exchange
    # (sum realizedPnl fills penutup sejak trade dibuka). Sebelumnya
    # pnl_usdt = unrealized STALE dari refresh terakhir (bisa jauh dari
    # realized, mis. tercatat -26.88 padahal TP1 profit) dan closed_price
    # = fill terakhir simbol (bisa milik trade/layer lain).
    realized = float(trade.get("pnl_usdt") or 0.0)
    closed_px = None
    _close_origin = None
    try:
        _since = None
        _ca = trade.get("filled_at") or trade.get("created_at")
        if _ca:
            _since = int(datetime.fromisoformat(
                str(_ca).replace("Z", "+00:00")).timestamp() * 1000)
        info = await br.realized_close_info(
            api_key, api_secret, is_testnet, bin_sym, _since)
        if info:
            realized = info["pnl"]
            closed_px = info["price"]
            if info.get("order_id"):
                _close_origin = await br.order_origin(
                    api_key, api_secret, is_testnet, bin_sym, info["order_id"])
    except Exception:
        pass
    if closed_px is None:
        # v9.9.9 — Fallback lama: harga fill terakhir simbol.
        try:
            closed_px = await br.last_fill_price(api_key, api_secret, is_testnet, bin_sym)
        except Exception:
            pass
    # v10.0.5 — Simpulkan ALASAN close dari harga fill vs level SL/TP
    # (sebelumnya None → kartu history tidak tahu kenapa tertutup) dan
    # SELALU catat closed_at (dibutuhkan leaderboard 24h).
    now_c = datetime.now(timezone.utc).isoformat()
    reason = None
    if closed_px:
        # v10.1.1 — Label TP HANYA bila fill benar-benar FAVORABLE vs
        # entry (LONG: exit > entry; SHORT: exit < entry). Fill yang
        # kebetulan dekat level TP tapi merugi (slippage/wick/akuntansi
        # layer) TIDAK boleh dilabeli TP — dilaporkan netral.
        entry_px = float(trade.get("entry_price") or 0)
        sign_c = 1.0 if trade.get("side") == "BUY" else -1.0
        favorable = bool(entry_px) and ((closed_px - entry_px) * sign_c) > 0
        sl = float(trade.get("stop_loss") or 0)
        tps = [float(x) for x in (trade.get("take_profits") or []) if x]
        tol = 0.004  # toleransi 0.4% utk slippage trigger
        if trade.get("side") == "BUY":
            if sl and closed_px <= sl * (1 + tol):
                reason = "SL"
            elif favorable:
                for i, tp in enumerate(tps, 1):
                    if closed_px >= tp * (1 - tol):
                        reason = f"TP{i}"
                        break
        else:
            if sl and closed_px >= sl * (1 - tol):
                reason = "SL"
            elif favorable:
                for i, tp in enumerate(tps, 1):
                    if closed_px <= tp * (1 + tol):
                        reason = f"TP{i}"
                        break
        # v10.1.1 — BREAK-EVEN (keputusan user): harga tutup ≈ harga entry
        # (±0.2%) dan tidak menyentuh SL/TP → label jujur "BREAK_EVEN",
        # bukan "position_closed_externally" yang membingungkan.
        # v10.7.14 — penutup dari luar bot (app/web Binance, likuidasi)
        # dilabeli jujur, bukan "Break-Even" palsu.
        _ext = br.classify_close_origin(_close_origin)
        if reason is None and _ext:
            reason = _ext
        if reason is None and entry_px \
                and abs(closed_px - entry_px) / entry_px <= 0.002:
            reason = "BREAK_EVEN"
        # v10.1.1 — Trailing stop native menutup posisi di luar level
        # SL/TP tersimpan → label khusus (bukan "closed externally").
        if reason is None and trade.get("trailing_activated"):
            reason = "TRAILING"
    upd_closed: dict[str, Any] = {
        "status": "closed",
        "pnl_usdt": round(realized, 2),
        "closed_at": now_c,
        "updated_at": now_c,
        "close_reason": reason or "position_closed_externally",
    }
    if closed_px:
        upd_closed["closed_price"] = closed_px
    if _close_origin:
        upd_closed["close_order_type"] = _close_origin.get("type")
        upd_closed["close_order_client_id"] = _close_origin.get("client_id")
    # v10.2.20 — Catat sl_fill saat close full = SL hit, agar UI dapat
    # menampilkan baris "SL hit · $xxx · −$yyy" (konsisten dengan
    # tp_fills). Hanya diisi bila belum ada dan reason terdeteksi SL.
    if reason == "SL" and closed_px and not trade.get("sl_fill"):
        upd_closed["sl_fill"] = {
            "level": "SL", "price": float(closed_px),
            # qty = sisa posisi sebelum close
            "qty": float(trade.get("qty_remaining") or trade.get("qty") or 0),
            "pnl": round(realized - sum(
                float(x.get("pnl") or 0) for x in (trade.get("tp_fills") or [])
            ), 4),
            "at": now_c,
        }
    # v10.2.20 — Catat tp_fills saat close full = TP akhir hit, agar
    # kartu history yang tutup langsung di level TP tetap tampil
    # "TPx hit · $xxx · +$yyy" meski tidak melalui partial.
    if (reason and reason.startswith("TP") and closed_px
            and not any(str(x.get("level") or "") == reason
                        for x in (trade.get("tp_fills") or []))):
        tp_fills_closed = list(trade.get("tp_fills") or [])
        tp_fills_closed.append({
            "level": reason, "price": float(closed_px),
            "qty": float(trade.get("qty_remaining") or trade.get("qty") or 0),
            "pnl": round(realized - sum(
                float(x.get("pnl") or 0) for x in (trade.get("tp_fills") or [])
            ), 4),
            "at": now_c,
        })
        upd_closed["tp_fills"] = tp_fills_closed
        n_tp = len(trade.get("take_profits") or []) or 3
        tp_filled_arr = list(trade.get("tp_filled") or [False] * n_tp)
        while len(tp_filled_arr) < n_tp:
            tp_filled_arr.append(False)
        try:
            idx_c = int(reason.replace("TP", "")) - 1
            if 0 <= idx_c < n_tp:
                tp_filled_arr[idx_c] = True
        except Exception:
            pass
        upd_closed["tp_filled"] = tp_filled_arr
    return {**_ghost_extra, **upd_closed}
