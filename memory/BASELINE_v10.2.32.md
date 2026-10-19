# 🔒 BASELINE RESMI — AI Crypto Stock Pro / ASI-Bot v10.2.32

**Ditetapkan oleh user: 19 Oktober 2026.**
**Status: TITIK DASAR TERKUNCI. Dilarang mengubah formula, gate, atau
logika apa pun di bawah ini tanpa permintaan eksplisit user. Jika ada
masalah di masa depan, KEMBALI KE TITIK INI.**

Git restore point: tag `baseline-v10.2.32` (commit lihat `git log`).

> **AMANDEMEN v10.2.33 (permintaan eksplisit user, hari yang sama):**
> setting jumlah TP user (1/2/3) kini WAJIB dihormati untuk SEMUA profil
> termasuk KISS Pivot — override `tp_count=3` pada hit-and-run DIHAPUS
> dari `engine.py`. 1 TP→100% di TP1, 2 TP→50/50, 3 TP→50/25/25.
> Test baseline tetap 101/101 PASS.

---

## A. FORMULA SINYAL (TERKUNCI — JANGAN DIUBAH)
File: `backend/indicators.py` (compute_signal + 4 engine profil).
- Engine: Scalper, Intraday (day), Swing, Confluence v9 (longterm).
- Dashboard pakai gate longgar (8 candle / 2.5 ATR); Full-Auto pakai
  gate ketat (3 candle / 1.5 ATR) dengan flag `late_entry`.
- Confluence v9: 7 faktor confluence.
- TP/SL, leverage, sizing: `backend/asi_bot/engine.py` (TERKUNCI).

## B. BTC REGIME GATE (v10.2.12)
- Reversal 1h RSI latch 120 menit; trending dari base 4H
  (_detect_regime orisinal); bear_capitulation blokir DUA arah.
- trending_up/bullish_reversal → tolak SELL alt.
- trending_down/bearish_reversal → tolak BUY alt.
- BTC sendiri dikecualikan.

## C. ANTI-CHASE MOMENTUM BTC (v10.2.32 — FINAL)
TANPA threshold % tetap. Konstanta: `backend/asi_bot/scheduler.py`
- `BTC_MOM_DIR_PCT = 0.3` (|chg_6h| minimum = arah lama terbentuk)
- `BTC_MOM_CONT_PCT = 0.1` (|chg_3h| minimum = momentum lanjut)
- `BTC_MOM_REV_PCT = 0.15` (candle 1h terakhir berlawanan = reversal)
- `BTC_MOM_RSI_HI = 72.0` / `BTC_MOM_RSI_LO = 28.0` (RSI exhaustion)
Aturan:
- Momentum AKTIF searah → LONG/SHORT BEBAS (ikut seluruh rally/flush).
- Momentum PADAM (flat / candle berbalik / RSI exhaustion) → blokir
  entry BARU arah lama saja.
- BTC flat → dua arah bebas.
- Reject: `anti_chase_buy_btc_momentum_padam` /
  `anti_chase_sell_btc_momentum_padam`.

## D. GUARD PER-SIMBOL (TERKUNCI)
- SELL short-dump guard: tolak SELL bila alt turun >1.2%/2 jam
  (`SELL_SHORT_DUMP_PCT=1.2`, window 2h) — v10.2.25.
- BUY dump guard: tolak BUY bila alt turun >2.5%/2 jam — v10.2.23.
- RSI 1h per-aset: BUY ditolak >72, SELL ditolak <28 — v10.2.31.
- Trend filter 4H EMA50: bias wajib searah; slope LONG diriksa SEGERA
  saat BTC trending_up, SHORT menunggu streak≥3 — v10.2.29.
- Konfirmasi: BUY 1 siklus (v10.2.31), SELL 2 siklus.
- Confidence: base 4H BEAR → BUY butuh +5 poin conf — v10.2.17.

## E. RISK PROTECTION (TERKUNCI)
- `MAX_OPEN_PER_SIDE = 3` posisi open per arah per device — v10.2.25.
- Cooldown loss per simbol 4 jam (loss < -$1) — v10.2.23.
- Circuit breaker: 3 loss campur <2 jam → pause 2 jam — v10.2.23.
- Soft delete trade (riwayat tetap untuk risk controls) — v10.2.24.
- Daily loss limit auto-disable + max_trades_per_day.
- Clamp qty ke MARKET_LOT_SIZE Binance (`qty_clamped_max`) — v10.2.28.
- Anti-duplikat klaim slot atomik — v10.1.6.

## F. ENGINE & CLOSE (TERKUNCI)
- TP/SL attribution via sweep userTrades (forward-only) — v10.2.20.
- Manual close tangguh: precision stepSize, flat=sukses, refresh PnL
  non-fatal — v10.2.26.
- Close-all endpoint: cancel pending + market close semua open.

## G. FRONTEND (TERKUNCI)
- Tombol CLOSE ALL (Recent Trades header + Running Positions di atas
  kartu teratas, kompak rata kanan) — v10.2.27.
- Copy Trade EXECUTE langsung tanpa modal parameter — v10.2.18.
- Preview watchdog 5 detik + Retry — v10.2.18.
- Dashboard/leaderboard cache 60 detik — v10.2.18.

## H. VERSI
- `frontend/src/lib/version.ts`, `frontend/app.json`,
  `backend/server.py` semuanya = **10.2.32**.

## I. TEST BASELINE
- Suite: `backend/tests/test_iter50/51/52/53*.py` = **101/101 PASS**.
- Regresi wajib hijau sebelum perubahan apa pun di masa depan.

---

**ATURAN UNTUK AGENT MASA DEPAN:**
1. Baca file ini + PRD.md sebelum menyentuh scheduler/engine/indicators.
2. Perubahan policy/formula HANYA atas permintaan eksplisit user.
3. Setiap perubahan wajib: test suite tetap 100% hijau + catat di PRD.
4. Jika strategi bermasalah dan user minta "kembali ke dasar":
   `git checkout baseline-v10.2.32` untuk file trading.
