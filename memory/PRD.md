# AI Crypto Stock Pro — PRD

> ## 🔒 BASELINE TERKUNCI: v10.2.32 (19 Oktober 2026)
> User telah menetapkan v10.2.32 sebagai **titik dasar resmi aplikasi**.
> Semua formula sinyal, gate scanner, risk protection, engine TP/SL, dan
> UI pada titik ini **DILARANG diubah** oleh perubahan apa pun kecuali
> atas **permintaan eksplisit user**. Dokumen lengkap kebijakan baseline:
> **`/app/memory/BASELINE_v10.2.32.md`**. Git restore point: tag
> **`baseline-v10.2.32`**. Jika ada masalah → kembali ke titik ini.
> Test baseline wajib hijau: **101/101** (iter50–53).

## Product Summary
AI-powered trading signal dashboard covering crypto, IDX stocks, US stocks, ETFs, gold/silver, commodity, forex. Bilingual (ID/EN/RU/CN), premium unlock, chatroom, AI Market Brief, WR history.

---

---

---
## v10.2.25 — Short-Dump Guard & Side Concurrency Cap (Oktober 2026)
Pelajaran 18/10 14:02–14:09 UTC: 7 SHORT (SUI, DASH, AR, WIF, SOL, SEI,
XLM) masuk dalam 8 menit tepat setelah BTC flip trending_down 13:38 UTC
(gate melepas antrean SELL). Entry berada di DEKAT LOW candle 13:00 UTC
yang baru saja −1 s/d −1,5%/1 jam — bot "shorting dasar bar bearish".
BTC bounce teknikal 14:15 UTC +0,17% → wick menyentuh SEI SL (−$20,95)
dan XLM BE (−$10,86); 4 SHORT lain floating. SUI akhirnya profit
+$13,73. Analisis: ARAH BENAR (BTC terus turun, dn-streak 31; base 4H
BEAR) — TIMING yang salah.
Dua fix (gate scheduler, formula sinyal tidak disentuh):
1. **SELL short-dump guard (window 2 jam)**: SELL ditolak bila alt
   turun >1,2%/2 jam. Lebih sensitif dari anti-chase 6h/3%; menargetkan
   kasus "shorting di dasar bar bearish". Simetris dengan dump-guard BUY
   yang sudah ada. Reject label: `sell_short_dump_<pct>pct_<n>h`.
2. **Side concurrency cap (MAX_OPEN_PER_SIDE=3)**: posisi OPEN per
   device per arah dibatasi 3. Mencegah correlated-loss saat regime
   flip melepas banyak sinyal serentak. Reject label:
   `max_open_<side>_<n>_>=_3`. Hitungan hanya `status=open` &
   `deleted!=true`, scoped per `device_id`.

**Testing (iter53, 94 regression tests)**: 19/19 unit v10.2.25 PASS;
iter50–52 regression 75/75 PASS. buy_gates live mengekspos
`sell_short_dump_pct=1.2`, `sell_short_dump_window_h=2`,
`max_open_per_side=3`. Engine/formula sinyal tidak disentuh.

## v10.2.26 — Fix Manual Close Semua Kartu (Oktober 2026)
Laporan user: close BCH SHORT di preview gagal. Curl langsung sukses
(BCH closed +$23.10) → bukan bug spesifik kartu, tapi 3 kerapuhan
generik diperbaiki untuk SEMUA kartu close (Running Positions, Recent
Trades, close-all):
1. **Precision qty**: qty live dari positionRisk dibulatkan turun ke
   stepSize Binance — sisa desimal pasca partial TP tidak lagi membuat
   market close ditolak filter LOT_SIZE.
2. **Flat = sukses**: posisi sudah 0 di exchange (SL telanjur hit /
   close sebelumnya sukses tapi respons hilang) → diperlakukan sukses,
   kartu langsung closed, bukan error 500.
3. **Refresh PnL non-fatal**: close sukses di exchange tetapi refresh
   PnL gagal → request tetap OK & kartu ditandai closed; user tidak
   lagi mengirim order ganda karena mengira close gagal.
Test: 4/4 skenario engine PASS; regresi iter50–53: 94/94 PASS.

## v10.2.27 — Tombol CLOSE ALL (Oktober 2026)
Permintaan user: satu tombol untuk menutup SEMUA posisi open sekaligus
+ membatalkan semua order LIMIT yang masih menunggu (pending).
- **Recent Trades (asi-bot.tsx)**: tombol merah kompak "CLOSE ALL" di
  kanan atas header section, samping toggle jumlah kartu; hanya tampil
  bila ada posisi open/pending.
- **Running Positions (trades-position.tsx)**: tombol merah KOMPAK di
  kanan header (samping ikon refresh), gaya persis sama dengan tombol di
  Recent Trades — revisi user: bukan full-width di atas kartu.
  Hanya tampil bila ada posisi open/pending.
- Konfirmasi dialog dulu (destructive), spinner saat berjalan, lalu
  refresh daftar. Error per-simbol ditampilkan bila ada yang gagal.
- Backend `POST /asi/trades/close-all` sudah menangani pending_entry
  (cancel) + open (market close) — tidak ada perubahan backend.
- i18n baru (id/en/ru/cn): asi_close_all, asi_close_all_working,
  asi_close_all_title, asi_close_all_body, asi_close_all_done.
- Verified via screenshot: tombol tampil di kedua halaman dengan device
  user yang punya posisi open.

## v10.2.28 — Clamp Qty ke Batas Maksimal Binance (Oktober 2026)
Bug nyata ditemukan saat audit "banyak sinyal tidak dieksekusi": ILV
SELL valid tapi gagal 7× beruntun dengan error `-4005 Quantity greater
than max quantity`. Bot menghitung qty dari risk%×leverage tanpa
membatasi ke batas order Binance.
Fix:
1. `whitelist.binance_symbol_filters` kini mengekstrak `max_qty`
   (MARKET_LOT_SIZE, fallback LOT_SIZE maxQty) per simbol per jaringan.
2. `engine.execute_trade` meng-clamp qty ke `max_qty` (dibulatkan turun
   ke step). Clamp ke bawah = risiko berkurang, posisi tetap terbuka
   dengan ukuran maksimal yang diizinkan. Tercatat di field trade
   `qty_clamped_max`.
Test: clamp logic 3/3 PASS; regresi iter50–53: 94/94 PASS.

## v10.2.29 — LONG Langsung Saat BTC Naik (Oktober 2026)
Keluhan user: "BTC sudah naik, bot terjegal — kesempatan LONG hilang
sebelum streak tercapai." Dua penahan BUY dipercepat (sisi SELL tidak
diubah):
1. **Anti-flap v10.2.17 DICABUT**: BUY tidak lagi ditahan 3 siklus
   setelah BTC flip `trending_up` — sinyal LONG langsung dievaluasi.
   Proteksi bounce-palsu tetap ada di lapis lain: konfirmasi 2 siklus,
   anti-chase (3%/6h), dump-guard, RSI 1h, trend filter 4H.
2. **Relaksasi slope EMA50 4H untuk LONG dipercepat**: aktif SEGERA saat
   BTC `trending_up` (sebelumnya menunggu streak ≥3). LONG cukup butuh
   harga > EMA50 4H; slope EMA50 yang masih turun pasca-dump tidak lagi
   menahan. Bias (harga harus di atas EMA50) TIDAK pernah dibebaskan.
Verifikasi live: reject `anti-flap` hilang dari scan-debug; kandidat
yang tersisa hanya ditolak `anti_chase_buy_8.1pct_6h` (alt sudah pump
+8.1%/6 jam — proteksi anti-kejar-puncak bekerja sesuai desain).
Test: suite diperbarui (anti-flap → ekspektasi baru), +1 test relaksasi
streak=1; total 95/95 PASS.

## v10.2.30 — Anti-Chase Relatif Terhadap BTC (Oktober 2026)
Keluhan user yang tajam dan BENAR: "anti-chase 3%/6h absolut bodoh —
BTC baru naik +0.5% dan alt sudah ditolak, padahal alt belum terlambat.
BTC rally 0.5→5→8→10% harus tetap bisa LONG, bukan dijegal selamanya."
Logika baru (adaptif, konteks penuh, seperti trader profesional):
- Fase 1 — **BTC early rally** (BTC_6h < BUY_CHASE_PCT=3%):
  anti-chase BUY **DIMATIKAN**. Alt yang ikut naik dianggap on-time.
- Fase 2 — **BTC late** (BTC_6h ≥ 3%):
  anti-chase hanya aktif jika alt OUTPACE BTC — gap `alt_6h - btc_6h`
  ≥ 3%. Alt yang cuma mengikuti beta BTC tidak dihalangi.
- Fase 3 — **BTC bull run berkelanjutan** (BTC terus naik +5, +8, +10%+):
  bot tetap bisa masuk LONG selama alt tidak "lari lebih kencang"
  dari BTC. Rally panjang tidak lagi memblokir eksekusi selamanya.
Reject label baru: `anti_chase_buy_rel_<gap>pct_vs_btc`.
Scan-debug `buy_gates` mengekspos `buy_chase_mode="relative_to_btc"`
+ `btc_chg_6h` aktual.
Bukti live scan-debug: BTC_6h=1.61% → reject `anti_chase_buy_*` HILANG
dari report; eksekusi mengalir (field `sudah_ada_posisi`: 1).
Test: 98/98 PASS (4 test baru + suite lama diperbarui).

## v10.2.31 — Konfirmasi 1 Siklus + RSI 72/28 (Oktober 2026)
Keluhan user: "seharian bot tidak eksekusi ini memalukan". Dua filter
yang paling sering menahan eksekusi dilonggarkan:
1. **BUY_CONFIRM_CYCLES: 2 → 1**. Sinyal BUY tereksekusi di siklus
   pertama (sebelumnya butuh 2 siklus = 90–180 detik jeda, sering
   sinyal hilang dulu di siklus kedua). SELL tetap 2 siklus (SHORT
   lebih berisiko).
2. **RSI 1h gate: 65/35 → 72/28**. 65 terlalu ketat untuk crypto yang
   rutin bergerak di RSI 70–80 saat rally (kasus ARB 69 tersaring).
   Ambang 72/28 hanya memblokir extreme overbought/oversold.
Proteksi lain tetap aktif: anti-chase relatif terhadap BTC, side-cap 3,
cooldown loss 4h, circuit breaker, trend filter 4H, BTC regime gate.
Bukti live: setelah deploy, scan report tidak lagi menampilkan
"menunggu_konfirmasi" untuk BUY. Test: 98/98 PASS.

## v10.2.32 — Anti-Chase Berbasis Momentum BTC (Oktober 2026)
Koreksi user atas v10.2.30: "JANGAN pakai threshold % tetap (3%/5%) —
itu memblokir sinyal di tengah rally besar. Ganti deteksi momentum
aktif." Diimplementasikan persis:
- **Momentum AKTIF** (chg_3h searah >±0.1% DAN candle terakhir tidak
  berlawanan >0.15% DAN RSI 1h belum exhaustion 28/72) → LONG/SHORT
  searah momentum BEBAS dieksekusi. Bot ikut SELURUH pergerakan BTC
  dari awal hingga akhir, bukan hanya 3% pertama.
- **Momentum PADAM** (arah 6h sudah terbentuk tapi flat / candle
  berbalik / RSI exhaustion) → blokir entry BARU di arah lama saja.
  Reject: `anti_chase_buy_btc_momentum_padam` /
  `anti_chase_sell_btc_momentum_padam`.
- BTC flat (|chg_6h| ≤ 0.3%) → tidak ada arah lama → dua arah bebas.
- Simetris naik/turun, berlaku semua profil. Guard per-simbol lain
  (short-dump 1.2%/2h, buy-dump 2.5%/2h, side-cap, cooldown, circuit
  breaker, RSI 72/28, trend filter 4H) TIDAK diubah.
Konstanta lama BUY/SELL_CHASE_* tidak lagi dipakai scanner;
`buy_gates` kini mengekspos `anti_chase_mode="btc_momentum"` +
state momentum aktual.
Bukti live: BTC up (chg_6h +1.25%, chg_3h +0.41%) → exhausted_up=False
→ LONG mengalir; bot membuka 3 BUY (ARB +$29.3, JUP +$8.3, AAVE +$9.8)
sampai side-cap 3 menahan kandidat ke-4 — proteksi konsentrasi bekerja.
Test: 101/101 PASS (suite anti-chase ditulis ulang ke semantik
momentum: flat/reversal/RSI-exhaustion memblokir, momentum hidup bebas,
dua arah simetris).

## v10.2.33 — tp_count User Dihormati Semua Profil (Oktober 2026)
Root cause keluhan "set 1 TP tapi eksekusi 3 TP": sinyal Scalper/
Intraday/Swing membawa formula_tag "KISS pivot" → blok hit-and-run di
`engine.execute_trade` memaksa `tp_count=3`. Override dihapus — setting
TP user kini berlaku untuk SEMUA profil & koin: 1 TP→100%, 2 TP→50/50,
3 TP→50/25/25 (ladder HAR 0.9/1.2/1.5% tetap, hanya dislice).
Test ladder+split 3/3 PASS; regresi 101/101 PASS.

## v10.2.34 — Chunked Close (Oktober 2026)
Root cause "CLOSE tidak bisa / tombol aktif lagi": posisi besar (kasus
nyata JUP 15.236 qty testnet) melebihi batas 1 market order Binance
→ `-4005 Quantity greater than max quantity`, gagal 4× beruntun.
`close_position` kini memecah close besar menjadi beberapa market order
reduceOnly ≤ MARKET_LOT_SIZE max_qty sampai posisi habis. Berlaku untuk
CLOSE per kartu DAN Close-All (keduanya lewat close_position).
Bukti live: JUP closed sukses (HTTP 200, close_reason=manual).
Regresi 101/101 PASS.

## v10.2.35 — Fix -2021 Bracket + Error i18n (Oktober 2026)
Keluhan user (AI Suggestions semi-auto): execute gagal dengan
`-2021 Order would immediately trigger` dan notifikasi error tampil
Bahasa Indonesia padahal locale EN.
1. **Clamp TP vs mark price**: harga bisa bergerak melewati TP antara
   fill entry & pemasangan bracket. Kini trigger yang terlewati
   di-clamp 0.1% ke arah profit (fallback eksekusi, formula TP/SL
   tidak diubah). TP yang kena -2021 saat placement di-retry dengan
   clamp vs mark segar. SL yang kena -2021 (harga sudah tembus stop)
   fail-fast → rollback dengan pesan jelas.
2. **Error i18n**: pesan backend `_emergency_close` kini English;
   frontend AsiTradeSheet memetakan code bracket_* ke 4 locale
   (id/en/ru/cn) — notifikasi mengikuti bahasa user.
Test: 101/101 PASS; lint bersih.


## v10.2.24 — Soft Delete Kartu Trade + Skip Simbol Tak Tersedia (Oktober 2026)
Laporan user: "tidak ada sinyal yang dieksekusi sama sekali".
Investigasi: bot tidak mati — periode hening 12:04–13:38 UTC adalah
kombinasi (1) circuit breaker v10.2.23 aktif (3 loss beruntun),
(2) BTC trending_up streak 80 memblokir semua SELL, (3) kandidat LONG
(FLOW) ditolak valid karena di bawah EMA50 4H-nya. Setelah BTC flip
trending_down 13:38, eksekusi normal kembali (BCH & FET SHORT 13:40–41
lewat konfirmasi 2 siklus).
Temuan desain nyata #1: delete kartu trade adalah HARD delete dari
asi_trades → circuit breaker & cooldown per-simbol (v10.2.23) kehilangan
riwayat loss saat user membersihkan kartu. Fix: delete kini SOFT DELETE
(deleted=true + deleted_at); GET /trades mengecualikan deleted, tapi
record tetap di DB untuk breaker/cooldown/statistik engine. Verifikasi
end-to-end: kartu tampil → DELETE → hilang dari list → record tetap ada
dengan deleted=true.
Temuan #2 (lanjutan laporan "sinyal tampil tapi tidak dieksekusi"):
sinyal ICP gagal terus dengan symbol_filters_missing — akar: ICPUSDT
memang TIDAK TERDAFTAR di Binance Futures TESTNET (0 entri di
exchangeInfo testnet; 528 simbol lain ada). Dashboard menampilkan sinyal
dari data mainnet, tapi eksekusi DEMO/testnet mustahil untuk simbol
yang tidak ada di testnet. Fix: saat execute_trade menolak dgn
symbol_filters_missing, simbol masuk set `_UNAVAILABLE_SYMS`
(modul-level, per jaringan) → siklus berikutnya skip dini dgn reason
jelas `symbol_<SYM>_tidak_tersedia_di_<jaringan>` tanpa spam log/slot
konfirmasi. Terverifikasi live: 13:54 UTC ICP di-skip dini.


## v10.2.23 — Anti-Loss Sisi BUY + Circuit Breaker Tangguh (Oktober 2026)
Laporan user: loss beruntun sejak v10.2.20, profit kecil loss besar.
Investigasi data riil 18/10 (UTC): SAND di-LONG 3× beruntun saat dump
pasca-pump +11% (SL semua: -$60, -$42, -$102) dan TIA LONG tepat di
puncak candle pump +3,67% (floating -43% ROE, SL lebar 4,4%). BTC sendiri
flat-chop seharian. Catatan: v10.2.20 murni perbaikan pencatatan fill
(tidak mengubah keputusan); keran LONG baru terbuka oleh v10.2.22
(relaksasi slope) — dan sisi BUY ternyata tidak punya pelindung momentum.
Akar sistemik:
1. Anti-chase hanya ada untuk SELL (v10.2.21); sisi BUY mengejar puncak
   pump (TIA) dan menangkap pisau jatuh (SAND).
2. Tidak ada cooldown per-koin setelah loss → revenge re-entry SAND 3×
   dalam 2,5 jam.
3. Circuit breaker lama (v10.2.5) punya LUBANG: hanya menghitung
   close_reason=="SL"; loss beralasan lain (mis. "position_closed_
   externally" ZIL 18/10) memutus streak → breaker tidak pernah aktif.
Perbaikan (layer gate, formula sinyal TIDAK diubah):
- **Circuit breaker berbasis PnL**: 3 closed terakhir semua rugi
  (pnl < -$1, alasan APA PUN) & terbaru <2 jam → istirahat 2 jam.
- **Cooldown per-simbol 4 jam**: simbol yang baru rugi tidak boleh
  di-entry ulang (anti revenge-entry).
- **Anti-chase BUY**: LONG ditolak bila alt naik >3%/6 jam (puncak pump).
- **Dump-guard BUY**: LONG ditolak bila alt turun >2,5%/2 jam (pisau
  jatuh). BTC dikecualikan dari momentum guard (sudah di-gate regim).
Audit: semua ambang terlihat di scan-debug → buy_gates (7 field baru).
Reject reason: anti_chase_buy_*, buy_dump_guard_*, cooldown_loss_*,
skip device "circuit-breaker: 3 loss beruntun <2 jam".
Teruji unit 12/12 (TIA +4,6%/6h blokir, SAND -4,9%/2h blokir, flat
lolos, regresi SELL anti-chase, breaker PnL campur reason AKTIF,
profit/BE memutus streak, loss lama >2h bebas, cooldown simbol tepat).


## v10.2.22 — Fix Bias Arah: Relaksasi Slope Trend-Filter 4H (Oktober 2026)
Laporan user: "3 hari semua posisi SHORT, tidak ada satu pun LONG padahal
BTC spike — loss besar, ada yang tidak beres."
Investigasi (data riil preview DB + log backend + scan-debug):
- 3 hari: 22 SELL vs 8 BUY dieksekusi; 0 slot konfirmasi BUY tercipta.
- Penyebab BUKAN engine sinyal dan BUKAN gate v10.2.17, melainkan
  trend-filter EMA50 4H per-koin (ditambahkan 15/10 pagi untuk mencegah
  bounce-trap): LONG wajib harga>EMA50 DAN slope EMA50 tidak menurun.
  EMA50 4H ≈ memori 200 jam (8 hari) → setelah dump seminggu, slope-nya
  tetap turun 1–2 hari pasca V-reversal, sehingga SEMUA LONG ditolak
  meski harga alt sudah kembali di atas EMA50 dan BTC sudah trending_up.
- Bukti live: siklus 04:44–04:47 UTC sinyal BUY FLOW ditolak gate ini
  (FLOW masih price<EMA50 → penolakan tetap valid).

Fix (keputusan user via judgment): saat BTC `trending_up` bertahan ≥3
siklus (streak anti-flap v10.2.17), LONG cukup syarat harga>EMA50
(slope dibebaskan). Simetris: streak `trending_down` ≥3 siklus → SHORT
cukup harga<EMA50. Ditambah pelacak `_trend_down_streak` (Mongo, tahan
restart). Saat BTC tidak terkonfirmasi, aturan slope penuh tetap aktif
(proteksi bounce-trap 15/10 tidak dihapus). Syarat harga vs EMA50 TIDAK
pernah dibebaskan — koin yang masih di bawah EMA50 4H-nya tetap ditolak.
Audit: scan-debug menampilkan `btc_trend_down_streak` + buy_gates baru
`trend4h_slope_relax_on_confirmed_btc`.
Teruji 10/10 unit (streak up/down naik-reset, relax saat streak≥3,
proteksi bounce-trap tetap aktif saat streak<3, bias tidak pernah
dibebaskan, simetri SHORT). Engine/formula tidak diubah.


## v10.2.21 — Anti-Loss SHORT & Early-Exit Longterm (Oktober 2026)
Analisis loss BCH SHORT 16/10: bot mengejar short di dasar lokal (BCH
sudah −4,3% dalam 9 jam sebelum entry), lalu BCH mean-reverting naik
6 jam berturut sampai kena SL penuh (−2,1%). Proteksi v10.2.17 hanya
BUY-side. Tiga guard baru di scheduler (BUKAN mengubah formula sinyal):
1. **ANTI-CHASE SELL**: SELL ditolak bila alt turun >`SELL_CHASE_PCT=3%`
   dalam `SELL_CHASE_WINDOW_H=6` jam. Mencegah short di dasar lokal
   yang berisiko bounce mean-reversion tinggi. Reject reason
   `anti_chase_sell_<pct>pct_<n>h`.
2. **KONFIRMASI SELL 2 SIKLUS**: simetris dengan BUY (keputusan user
   via judgment agent — base BTC 4H BEAR berkepanjangan memicu banyak
   sinyal SELL yang over-aggressive). `SELL_CONFIRM_CYCLES=2`. State di
   `asi_buy_confirm` (sekarang menyimpan `side` juga). Fail-CLOSED.
3. **EARLY-EXIT LONGTERM STALE**: posisi Confluence v9 / longterm /
   swing yang berjalan >`LONGTERM_STALE_HOURS=3` jam TAPI tidak pernah
   mencapai profit floating > `LONGTERM_STALE_MIN_PROFIT_PCT=0.5%`
   ditutup di market agar tidak kena SL penuh. Memakai field baru
   `max_floating_pct` di DB trade (histori). `close_reason='stale_exit'`
   dengan detail `longterm_stale_<age>h_max<+/-pct>`.
Audit via `/api/asi/scan-debug` → `buy_gates` kini juga memuat
`sell_confirm_cycles`, `sell_chase_pct`, `sell_chase_window_h`,
`longterm_stale_hours`, `longterm_stale_min_profit_pct`.
Verifikasi: 10/10 unit test PASS (helper confirm BUY/SELL default &
override; konstanta; simulasi anti-chase dump tajam vs grind lambat
vs flat); backend restart & /scan-debug mengembalikan field baru.


## v10.2.20 — Engine Lossless Fill Attribution (Oktober 2026)
Keputusan user: perbaiki LOGIKA ENGINE agar event TP1/TP2/TP3/SL hit
terdeteksi & dicatat benar untuk SEMUA koin dan SEMUA profil ke depan,
BUKAN patch per-kartu/per-koin. Kartu lama tidak disentuh.

Perubahan di `_refresh_binance` (engine.py): mekanisme lama memakai
`last_reduce_fill_price` tunggal (titik-tunggal gagal — satu kegagalan
API bisa membuat event tertelan selamanya). Mekanisme baru: setiap
tick menyusuri `/fapi/v1/userTrades` sejak `last_fill_check_ms` dan
meng-atribusi SETIAP fill reduce-only ke level TP (toleransi 0.4%)
atau SL (toleransi 1% karena slippage). Idempoten via `orderId`
(fill tercatat tidak diduplikasi di tick berikut). Fetch gagal →
`last_fill_check_ms` TIDAK dimajukan → tick berikut mengulang window
yang sama. SL guard otomatis pindah ke TP tertinggi yang baru ter-isi.

Jalur close full juga diperbaiki: close_reason=SL kini menulis
`sl_fill` sehingga UI dapat menampilkan "✕ SL hit · $xxx · −$yyy";
close_reason=TPx menulis entri `tp_fills` yang hilang bila belum ada.

Rollback: 3 backfill retrospektif (LINK/ADA/SOL) dihapus dari DB atas
instruksi user ("jangan sentuh kartu lama"). Endpoint `/trades/
reconcile` yang sempat ditambahkan juga dihapus (tidak ada patch
retroaktif). Fungsi helper `reconcile_trade_fills` di engine
dipertahankan sebagai utilitas internal tapi tidak dipanggil otomatis.

Teruji 7 skenario sintetis PASS: TP1, TP1+TP2 satu tick, idempoten
re-fetch, SL slippage, fetch fail, manual partial, close full SL.


## v10.2.19 — Fix Bug "TP Tertelan" pada Bracket Native (Oktober 2026)
Laporan user: "ZEC long turun ke 1,134, seharusnya TP 1,143 sudah hit tapi
tidak hit sejak perubahan TP/SL terakhir."
Investigasi langsung ke exchange (testnet): posisi ZEC SEBENARNYA SHORT,
dan TP1 1143.41 SUDAH terisi — fill BUY 0.967 @ 1143.37 pukul 17:15:57
UTC, realized +$37.53 (dibuktikan via /fapi/v1/userTrades).
Root cause: di `_refresh_binance` (engine.py), saat positionAmt mengecil,
satu kegagalan SESAAT `last_reduce_fill_price` (proxy/API) membuat event
tertelan selamanya — snapshot `prev_position_amt` tetap maju, jadi tick
berikutnya tidak pernah mendeteksi ulang. Akibat ganda: (1) `tp_fills`
kosong → UI tidak pernah menampilkan "TP1 HIT"; (2) SL-guard TIDAK
pernah bergerak ke TP1 (SL tertinggal di 1220.92). Ini juga kandidat kuat
akar kasus KAS closed-BE.
Fix: flag `_reduce_pending` — bila lookup harga fill gagal (None),
snapshot prev_position_amt TIDAK dimajukan → atribusi dicoba ulang tiap
tick sampai berhasil. Event hanya dikonsumsi bila harga fill ADA dan
memang tidak mencapai level TP (manual partial close). Cabang exception
juga tidak lagi memajukan snapshot. Teruji 3 skenario sintetis (lookup
gagal → retry; lookup sukses → tercatat TP1 + SL pindah 1143.41; fill
manual non-TP → dikonsumsi tanpa label TP) — PASS.
Backfill record ZEC: tp_fills [TP1 · $1143.37 · +$37.53], tp_filled
[True,False,False].
Keputusan user untuk sisa 0.967 ZEC (floating +$23): kunci profit
sekarang (opsi b). Dieksekusi via endpoint resmi POST /asi/trades/{id}/
close → leg kedua BUY 0.967 @ 1154.56, realized +$26.71. TOTAL REALIZED
**+$64.24 USDT**. Posisi live 0.000, tidak ada order algo yatim.


## v10.2.18 — Dashboard/Leaderboard Cache + Copy-Trade Direct Execute (Oktober 2026)
Empat permintaan user untuk performa & UX:
1. **Dashboard /dashboard/batch lambat + 502**: tambah response-level
   cache 60 detik + in-flight dedupe (anti-stampede). Kunci cache: markets,
   timeframe, sort, full, min_conf, min_wr, region, extras, profile.
   Boundary-aware (invalidate otomatis saat candle baru). Verified live:
   cold 2.56s → warm 0.036s; respons berfield `cached:true/false`.
   Error 5xx di frontend sudah ditangani v10.2.16 (banner Retry, tidak
   crash merah).
2. **Leaderboard lambat**: cache 60s + in-flight dedupe untuk
   `/api/asi/leaderboard` dan `/api/asi/leaderboard/live`; limit tetap
   25 item teratas. Verified: 0.209s → 0.058s.
3. **Copy-Trade EXECUTE tanpa sheet**: AsiTradeSheet dihapus dari
   copy-trade.tsx. Tombol EXECUTE sekarang langsung memanggil
   `api.asi.executeTrade` memakai parameter yang sudah di-set user di
   halaman ASI-Bot (risk%, leverage, margin_mode, tp_count,
   trailing_callback_rate, entry_mode, active_testnet, exchange).
   Entry = mark price saat ini. Sukses → `router.push("/trades-position")`.
   Guard: belum setup bot → CTA ke /asi-bot; duplikat posisi → konfirmasi
   pyramid; sinyal tanpa SL/TP → tolak.
4. **Preview "Calculating…" stuck**: AsiTradeSheet kini punya watchdog
   5 detik. Lewat batas atau request gagal tanpa HTTP code →
   `previewTimeout=true`, panel menampilkan pesan error + tombol
   Retry (`testID: ats-preview-retry`). Error HTTP backend tetap
   menimpa preview seperti sebelumnya.

Engine trading / formula sinyal / parameter ASI-Bot TIDAK diubah.
File: backend/server.py, backend/asi_bot/routes.py, frontend/app/copy-trade.tsx,
frontend/src/components/AsiTradeSheet.tsx, frontend/src/i18n/I18nContext.tsx.


## v10.2.17 — Anti-Loss BUY Gates (Oktober 2026)
Keputusan user setelah analisis loss LONG beruntun (ENA/XLM/BNB/ETH/YFI/CFX/
FET/GRT): BTC bounce singkat di tengah base 4H BEAR membuat rezim sesaat
`trending_up` → bot borong LONG lalu kena SL. Tiga gate baru di jalur
Full-Auto scheduler (dashboard/AI Suggestions TIDAK berubah):
1. **Anti-flap BTC regime**: BUY altcoin hanya lolos bila rezim SEGAR BTC
   `trending_up` bertahan ≥3 siklus scanner berturut-turut (±5 menit).
   Streak disimpan di Mongo `asi_scan_status.btc_regime.trend_up_streak`
   (tahan restart/multi-replica). Reject: "anti-flap: trending_up baru N/3".
2. **BTC base 4H BEAR**: LONG tetap BOLEH (bukan blokir total, pilihan
   user) tapi min confidence +5 poin (90→95). Reject: "conf<95_bear4h".
3. **Konfirmasi BUY 2 siklus**: sinyal BUY yang sama (device+symbol+
   fingerprint engine/formula) harus muncul 2 siklus scanner berturut-
   turut (±3 menit) sebelum dieksekusi; siklus 1 hanya mencatat kandidat
   di `asi_buy_confirm`. Sinyal absen >2× interval → hitungan reset.
   SELL tidak berubah. Fail-CLOSED bila state DB error.
Audit: `GET /api/asi/scan-debug` kini menampilkan `btc_base_regime_4h`,
`btc_trend_up_streak`, dan `buy_gates` config.
Verifikasi: testing agent 22/22 PASS (unit helper + integrasi fake-DB
tanpa order nyata: siklus 1 catat, siklus 2 eksekusi, siklus 3 tidak
re-eksekusi; anti-flap streak<3 reject; bear4H conf92 reject/conf96
lolos; SELL tetap eksekusi siklus pertama). Fix susulan: state konfirmasi
yang sudah `consumed` (count=0) tidak bisa dipakai konfirmasi ulang —
sinyal baru wajib mulai dari siklus 1 lagi.
Tidak ada order exchange sungguhan dalam pengujian.



## v10.2.6 — Panic Market Guard (Oktober 2026)

Guard portofolio berbasis BTC+ETH untuk Full-Auto + banner peringatan Semi-Auto. Didesain dengan anti-noise ketat agar TIDAK mengganggu bot operasi normal.

### Trigger Full-Auto (butuh KEDUA kondisi guard terpenuhi untuk close posisi)
Jalur A — Posisi loss salah arah:
- Butuh bias market panic (BTC & ETH SAMA-SAMA ≥1.0%/1h DAN slope EMA50 4h searah)
- ≥2 posisi OPEN Full-Auto side-nya salah arah (LONG saat dump, SHORT saat pump) DAN loss signifikan (≤ -1% margin DAN absolute ≥ $0.5)

Jalur B — Equity drawdown:
- Total unrealized PnL/equity Full-Auto ≤ -3% DAN total margin ≥ $5 DAN total PnL ≤ -$1

### Aksi saat panic trigger
- Tutup (MARKET close) semua posisi loss salah arah
- Cancel semua pending limit entry salah arah
- Set `panic_active=True` → scanner Full-Auto berhenti open posisi baru
- Catat event di `asi_panic_events` + `panic_closed_count`/`panic_cancelled_count`

### Release otomatis (condition-based, keputusan user)
- Bias market kembali neutral ATAU reversal pattern terdeteksi di candle 1h BTC+ETH
- `panic_active=False` → bot langsung bebas open posisi baru searah arah pasar baru

### Anti-noise (keputusan user: panic guard JANGAN jadi noise)
- Threshold 1h ketat: ≥1.0% + slope EMA50 4h searah (bukan 0.5% atau OR)
- Loss signifikan: ≥1% margin DAN ≥$0.5 (fluktuasi dust tidak dihitung)
- Hysteresis 3 menit setelah release: tidak boleh trigger ulang (hindari oscillation)
- Equity trigger butuh margin ≥$5 (akun kecil tidak kena false positive)
- **v10.2.6b (fix bug live)**: oscillation trigger→release→trigger tiap 2 menit
  terdeteksi saat 9 posisi SELL baru @10x swing -3% pada BTC +0.5%.
  Fix: (1) equity harus ≤ -3% selama 2 siklus berturut (persistence ±4 menit)
  sebelum trigger; (2) episode lock — jalur equity dikunci setelah trigger
  sampai equity pulih > -1%, mencegah retrigger berulang.
  Diverifikasi 6 skenario test sintetis — semua PASS.

## v10.2.7 — Scan Diagnostics (Oktober 2026)
Masalah: user HP v10.2.6 melaporkan bot tidak eksekusi; semua jalur skip
scanner bersifat silent (credential hilang, daily limit, panic cooldown,
loss-streak, trend filter, cooldown 15m, dup, conf, late-entry) sehingga
diagnosis selalu butuh gali DB/log manual.
- Scheduler kini mencatat laporan per-device tiap siklus ke
  `asi_scan_status.devices` (maks 20): scanned/skip_reason/signals/placed/
  rejects{alasan: jumlah}.
- Endpoint baru `GET /api/asi/scan-debug?device_id=` mengembalikan laporan
  + snapshot config (full_enabled, profile, min_confidence, dll).
- UI ASI-Bot menampilkan 1 baris diagnostik kecil di bawah status saat
  Full-Auto aktif: "✓ Scanner aktif · sinyal N · posisi baru M · reject
  terbanyak: X" atau "⏸ Scanner skip: <alasan>".
- Catatan insiden: device web preview tersimpan full_enabled=False (START

## v10.2.8 — Timing Filters Anti-Late-Entry (Oktober 2026)
Menjawab insiden 15/10: 9 sinyal SHORT (7 engine day/KISS Pivot, 2 scalper/
Box Theory) dieksekusi 06:29–06:32 UTC tepat di dasar bounce — candle 1h
BTC -1.23% memicu sinyal trend-following yang telat, candle berikutnya
+0.37%/+0.80% membuat semua SHORT day floating loss (total ≈ -$111 demo;
yang scalper justru profit). Keputusan user — tiga filter baru di jalur
Full-Auto (dashboard/AI Suggestions tidak berubah), dievaluasi PER SINYAL
supaya sinyal arah berlawanan (searah reversal) tetap bisa dipilih:
- (a) Exhaustion: candle 1h closed terakhir ≤ -1% → tolak SELL baru;
  ≥ +1% → tolak BUY baru (semua engine).
- (b) Post-spike cooling (khusus engine day): candle sebelum terakhir juga
  spike > 1% searah sinyal → tolak (tunggu pullback 2 candle).
- (c) RSI14 1h: < 35 → tolak SELL (oversold); > 65 → tolak BUY
  (overbought). Fail-open bila data 1h unavailable.
- Snapshot 1h per simbol diambil sekali per siklus (hanya bila ada sinyal)
  agar hemat rate limit; alasan reject masuk scan-debug rejects.
- STRK bracket fail (production, 14:15 WIB): detail error asli Binance kini
  disimpan ke `close_reason_detail` pada record trade (sebelumnya hilang,
  hanya "bracket fail"). Dugaan utama: -2021 "Order would immediately
  trigger" pada TP low-cap volatile; penanganan khusus menunggu bukti

## v10.2.9 — Performa Halaman & Delete Optimistic (Oktober 2026)
Keluhan user: hapus kartu lambat & kadang tidak ter-delete; grafik dari
kartu trade lambat; halaman Running Positions & Leaderboard lambat dibuka.
Padahal endpoint backend cepat (leaderboard 8ms lokal, 0.1-0.3s eksternal;
chart 0.2-0.35s) — akarnya pola frontend yang menunggu jaringan sebelum
menggambar.
- **Page cache (stale-while-revalidate)**: `src/lib/pageCache.ts` —
  payload sukses terakhir disimpan ke AsyncStorage; halaman render cache
  SEKETIKA saat dibuka lalu refresh background. Diterapkan ke:
  Running Positions (trades), Leaderboard (rows), ASI-Bot (Recent Trades),
  dan grafik aset (per key market|symbol|tf|profile — aman dari flash
  candle aset lain, regresi v8.13.x terjaga).
- **Chart prefetch**: `src/lib/chartCache.ts` — tap kartu di Running
  Positions/Recent Trades menembak `api.chart` SEBELUM router.push;
  halaman detail mengambil promise yang sudah berjalan (TTL 60s,
  single-use, maks 12 entri).
- **Fix double-fetch grafik**: effect loadChart kini menunggu
  `accessLoaded` + `profileLoaded`; sebelumnya fetch pertama jalan dengan
  profile=undefined lalu diulang dengan profile user → 2× round-trip dan

## v10.2.10 — Fix Definitif Grafik Statis (Oktober 2026)
Keluhan lama sejak v10.0.0: mark price di ujung grafik berkedip tapi
angka statis; makin parah di HP. Diagnosa langsung terhadap Binance WS
dari pod membuktikan: `fstream.binance.com` (URL utama sejak v10.0.13)
MEMBUKA koneksi tapi mengirim 0 pesan (silent-dead saat throttle/region
block), sementara `data-stream.binance.vision` ticking normal. Hook
menandai `connected=true` (badge LIVE tampil) dan fallback ke URL
cadangan hanya terjadi onclose — koneksi silent-dead tidak pernah close
→ harga statis selamanya. Ini menjelaskan kenapa perbaikan-perbaikan
sebelumnya tidak pernah tuntas: kode salah mengira koneksi sehat.
- Watchdog pesan pertama (8 detik) di useBinanceRealtime & useBinanceKline:
  koneksi tanpa data ditutup paksa → jatuh ke URL cadangan.
- Fallback backend /api/asi/prices (poll 500ms, hanya saat WS mati/stale
  >2.5 detik) sebagai jalur terakhir untuk HP yang ISP-nya memblokir
  semua domain Binance; `livePx` menjadi single source untuk header,
  label ujung grafik, zone/dip-top alert, dan harga eksekusi.
- Terverifikasi di web preview: sebelum = 6 sampel identik (statis),
  sesudah = 4 harga unik/6 sampel (ticking). Lint 3 file bersih.

## v10.2.11 — Focus-Gated Polling + Anti-Flicker Dashboard (Oktober 2026)
- **#3 Keluhan "grafik dari kartu Running Positions lambat, dari dashboard
  cepat"**: root cause = interval polling layar trade (harga 300ms +
  refresh 5s + market-risk 30s) TETAP BERJALAN saat layar tersembunyi di
  bawah halaman grafik (React Navigation stack tidak unmount) → CPU &
  network HP terus terbebani. Fix: semua interval di trades-position.tsx
  & asi-bot.tsx dipindah ke `useFocusEffect` — polling hanya berjalan
  saat layar terlihat, berhenti total saat user membuka grafik, hidup
  lagi saat kembali.
- **#2 Keluhan "dashboard bergantian tiap beberapa detik"**: repro di
  web preview STABIL (0 flip/54s, profile day aktif) → spesifik
  production. Mitigasi terpasang: response batch yang kategori-nya
  tiba-tiba kosong/menyusut >40% (ciri degraded/parsial) tidak boleh
  menimpa data yang sedang tampil. Root cause production (kemungkinan
  multi-instance cache atau response parsial upstream) masih perlu

## v10.2.13 — market_data via ASI_PROXY_URL + Retry 418/429 (Oktober 2026)
Permintaan user: pooled httpx client di market_data.py dirutekan lewat
relay ASI_PROXY_URL (pola yang sama seperti asi_bot/exchanges.py &
server.py) + retry/backoff untuk 418/429.
- `_http()`: `proxy=os.environ.get("ASI_PROXY_URL") or HTTPS_PROXY or None`
  — tanpa env → koneksi langsung (perilaku lama).
- `_get_with_retry()`: GET dengan backoff 0.5s→1.5s khusus status 418
  (IP ban, honor header Retry-After maks 2s) & 429 (rate limit); 3
  percobaan lalu raise → rantai fallback Bitget/OKX yang sudah ada tetap
  mengambil alih seperti semula. Dipasang di `_fetch_binance_klines` &
  `_fetch_binance_ticker`.
- Tujuan: menghentikan kejadian IP server kena 418/451 Binance saat beban
  scanner+panic guard naik (akar dashboard/grafik kehilangan data di
  production).

## v10.2.13b — Confluence v9 dilonggarkan 8→7 faktor (Oktober 2026)
Keputusan user: gerbang Confluence v9 (profile=longterm) terlalu sering

## v10.2.14 — Emergency Fix Crash ASI-Bot & Deployment Sukses (Oktober 2026)
- Fix crash di halaman ASI-Bot saat user tap tombol (ReferenceError: useCallback is not defined) akibat missing import di `app/asi-bot.tsx`.
- Verifikasi build pipeline dan resolusi 502 bad gateway upstream yarn registry. Build Android .APK dan .AAB v10.2.14 selesai 100% dan ter-deploy.
- Seluruh rangkaian fitur v10.2.6 - v10.2.14 aktif: Panic Market Guard, BTC Regime Gate (_detect_regime + RSI1h reversal latch), proxy anti-ban Binance + retry 418/429 di market_data, Confluence 7 faktor, fix harga live grafik & badge Dip/Top, page cache & optimistic delete.

kosong total (0/113 aset) → dilonggarkan 8 → 7 faktor. Default dashboard
(profile=None) tetap 5 faktor. Catatan investigasi: perbedaan badge
premium HP vs preview bersifat struktural — premium butuh wr_30d dari DB
track-record; DB production punya histori nyata (lebih akurat), DB preview
minim histori sehingga fallback conf≥73 menandai semua premium. Perbedaan
set sinyal HP vs preview = versi backend (Publish terakhir vs terbaru) +
cache 60s. Diverifikasi live: market saat perubahan memang flat (hanya
AGIX mencapai skor 4/7, sisanya tersaring sebelum tahap scoring) → 0
sinyal bukan bug; pelonggaran akan terasa saat setup confluence terbentuk.

- Test: mock transport (418→418→200 sukses; 429×3 raise ke fallback;
  200 tanpa retry) + live fetch BTC via proxy (250 candle OK, ~1.8s).

  observasi user berikutnya.
- **#1 Pertanyaan "kenapa ATOM & DASH tidak dieksekusi, hanya LTC &
  LDO"**: perilaku BY-DESIGN filter timing v10.2.8 — ATOM -6.8% &
  DASH -5.2% adalah kandidat "sell the bottom" (candle 1h dump >1% /
  RSI oversold) sehingga SELL-nya ditolak; alasan reject persisnya bisa
  dilihat user di baris diagnostik halaman ASI-Bot (v10.2.7+).


  engine salah sesaat.
- **Running Positions load**: fetch balance Binance dijadikan
  fire-and-forget — sebelumnya spinner list menunggu balance (1-3s di
  produksi saat cache 4s miss).
- **Delete optimistic** (kedua layar): kartu hilang seketika, request di
  background; gagal → kartu dikembalikan + alert. `deletedRef`/
  `deletedIdsRef` mencegat kartu "muncul lagi" akibat race dengan poll
  5 detik yang in-flight (akar "kadang tidak terdelete").
- Bump 10.2.9 (3 lokasi). Lint 6 file bersih; smoke test screenshot
  Running Positions + Leaderboard OK. Semua perubahan frontend → perlu
  Publish + build APK baru agar terasa di HP.

  error aktual. 4 skenario test sintetis (exhaustion, cooling, normal
  tetap eksekusi, RSI oversold) — semua PASS.

  BOT belum aktif) → scanner skip; setelah user enable, 9 posisi SELL
  dieksekusi 06:29–06:32 UTC. HP = environment production terpisah
  (device_id & DB berbeda) → perlu Publish agar backend production
  mendapat kode terbaru.


### Semi-Auto
- TIDAK menutup posisi manual user
- Banner peringatan tampil saat bias panic jelas (dump/pump): alasan teknikal (reversal BTC/ETH + persentase) dengan ajakan mempertimbangkan tutup posisi berlawanan arah
- Tidak ada integrasi news (keputusan user: alasan teknikal saja)

- **v10.2.12b** — User mengingatkan formula rezim SUDAH ada sejak desain
  sinyal awal: `_detect_regime` (port btc_trading_formula.py, v8.7.23)
  yang selama ini hanya dipakai per-aset untuk risk sizing. Gate kini
  DISELARASKAN: rezim trending memakai detektor orisinal user (price vs
  EMA50 4H + ATR% → BULL/BEAR/BEAR_CAPITULATION); deteksi reversal RSI 1h
  tetap sebagai lapisan dini. Rezim `bear_capitulation` (formula asli)
  memblokir KEDUA arah (falling knife + late short). Test: reversal blokir
  SELL, trending_down loloskan SELL+blokir BUY, kapitulasi blokir dua
  arah — semua PASS.

### Endpoint & interval
- `GET /api/asi/market-risk?device_id=...` — snapshot bias BTC/ETH + status panic per device
- Scheduler monitor BTC+ETH tiap 2 menit (`PANIC_INTERVAL = 120`)
- Frontend polling `/market-risk` tiap 30 detik untuk banner

Bump versi: 10.2.5 → **10.2.6** (frontend `version.ts` + `app.json` + backend `APP_LATEST_VERSION`).

---

## v10.2.5 — Guard Anti-Loss-Beruntun (Oktober 2026)

Berdasarkan analisis data aktual user: v10.1.7 WR 75% +$271 (market turun, bot SHORT searah) vs v10.2.4 WR ~20% -$150 (market dump, bot LONG bounce beruntun kena SL).

1. **Circuit Breaker Market-Wide**: BTC bergerak > ±2% dalam 1 jam → semua entry ke arah berlawanan diblokir siklus itu (dump → LONG diblokir, pump → SHORT diblokir). Menutup celah cooldown per-simbol yang tidak menangani koreksi serentak.
2. **Loss-Streak Breaker**: 3 trade terakhir semua SL dan SL terbaru < 2 jam → device istirahat siklus ini (auto-pause berlapis waktu).
3. **Trend Filter 4H pakai SLOPE EMA50**: LONG wajib harga > EMA50 DAN EMA50 tidak menurun; SHORT wajib harga < EMA50 DAN EMA50 tidak menaik. Mencegah bounce-trap saat EMA50 menurun.
4. **FX strip header dihapus** (redundan — kartu aset USDT sudah menampilkan konversi lokal per-perangkat).

Rollback: git tag `rollback-point-10.2.4`.

---

## v10.2.4 — Mark Price Tidak Boleh Kosong
- Kolom tengah kartu TIDAK PERNAH tampil '—': OPEN/LIMIT → mark price live ticking; CLOSED → harga exit (closed_price, fallback entry). Berlaku di Recent Trades & Running Positions, termasuk LIMIT WAITING.
- `/api/asi/prices` fallback berlapis (futures fapi → spot data-api.binance.vision → Bitget) + never-500 — sebelumnya satu kegagalan proxy membuat kolom kosong.

---

## TP Ladder Dirapatkan (backend-only)
- Scalper tetap 0.8/1.2/1.6R; **Intraday 1.2/1.5/1.8R** (dari 1.2/2.0/2.5R); **Swing 1.2/1.6/2.0R** (dari 1.5/3.0/4.0R); **Confluence 1.2/1.6/2.2R** (dari 1.5/3.0/4.5R). Alasan user: TP lama terlalu jauh tidak pernah tercapai. SL tidak berubah (1.0/1.2/1.5/2.0×ATR). Counter-trend scalp override (0.6/0.8/1.0R) tidak berubah. Versi resmi tetap 10.2.1 — cukup Publish, tidak perlu build.

---

## v10.2.2 — History 100 Posisi
- Backend `/api/asi/trades` default limit 50→100; kedua layar (Recent Trades & Running Positions) fetch 100.

---

## v10.2.0 — Model B: Aturan Bias Makro Terpadu (Oktober 2026)

- **Tiered TP/SL per profile**: scalper SL 1.0×ATR + TP (0.8/1.2/1.6R); day SL 1.2×ATR + TP (1.2/2.0/2.5R); swing SL 1.5×ATR + TP (1.5/3.0/4.0R); longterm/Confluence tetap SL 2.0×ATR + TP (1.5/3.0/4.5R) floating.
- **Counter-trend scalp hit-and-run**: SCALPER boleh counter-trend tapi ladder DIPAKSA (0.6/0.8/1.0R) + SL 1.0×ATR, apapun pilihan TP1/2/3 user → quick exit 15m-1 jam, label "SCALP COUNTER-TREND ⚡".
- **Intraday/Swing wajib searah bias makro** (3R Rule, tidak berubah).
- **Fail-closed**: data harian gagal dimuat → sinyal VWAP jadi HOLD "data makro tidak tersedia" (kasus ETH LONG tanpa filter tidak akan terulang).
- Rollback point: git tag `rollback-point-10.1.9`.

---

## v10.1.9 — Bump Versi & Fix UI Akhir (Oktober 2026)

- **Bump ke 10.1.9**: Memastikan APK/AAB baru memiliki nomor versi lebih tinggi agar popup update di HP user otomatis muncul (karena build 10.1.8 sebelumnya dibuat sebelum fix tombol kanan & ticking).
- **Semua perubahan frontend termuat di build baru**:
  1. Tombol CANCEL/CLOSE di baris khusus rata kanan (tidak lompat ke kiri).
  2. Label LIMIT WAITING konsisten di Recent Trades & Running Positions (tidak lagi salah tampil PnL $0.00).
  3. Polling harga mencakup kartu `pending_entry` (mark price ticking live terhadap harga limit).
  4. TTL cache `/api/asi/prices` 0.25s (harga berkedip 300ms).
  5. Sync refresh kedua layar 5 detik.

**Fix desync Dashboard vs AI Suggestions**: akar masalah = TTL cache berbeda (dashboard 300s/stale-900s vs suggestions 60s). Sinyal VWAP berbasis trigger breakout yang momentary — dashboard menyajikan 'no trigger' basi sampai 5-15 menit sementara suggestions sudah menangkap sinyal baru. Fix: DASHBOARD_CACHE_TTL 300s→60s, STALE_MAX 900s→120s. Cache global per (market,symbols,timeframe) → beban upstream maks 1 batch fetch/menit untuk seluruh user. BACKEND-ONLY: langsung aktif setelah Publish, tidak perlu build baru.

---


---

## v10.1.8 — Split Gate Tampilan vs Eksekusi + Full-Auto Overhaul (Oktober 2026)

**Full-Auto Anti-Loss (scheduler.py)**:
- Engine selection per Trader Profile: `longterm` (Confluence v9) → scan 1 engine saja; `scalper/day/swing` → scan 3 engine VWAP (tanpa longterm, anti-konflik).
- `MIN_FULL_AUTO_CONFIDENCE = 90` (dari 70).
- Cooldown 15 menit per-symbol (anti-flood, cegah kasus AVAX re-SHORT berulang).
- Trend-filter eksternal 4H EMA50: SHORT ditolak di bias UP, LONG ditolak di bias DOWN.
- Max trades/hari default 5 → 3.
- Skip sinyal `late_entry=True` (pertahanan ganda).

**Split Gate Dashboard vs Eksekusi (indicators.py + server.py)**:
- `compute_signal()` punya param baru `freshness_max_candles` (default 3) & `chase_atr_mult` (default 1.5) = gate EKSEKUSI ketat.
- Dashboard/chart/AI-analyze memakai gate LONGGAR (8 candle / 2.5 ATR) → sinyal LONG/SHORT kembali banyak untuk user non-premium.
- Sinyal yang lolos hanya karena gate longgar ditandai `late_entry=True` + reason "Late-entry — Full-Auto skip".
- `_asi_signal_fetcher` memanggil `_build_dashboard_response(strict_gates=True)` → eksekusi tetap ketat.

**Mark price 100ms (useBinanceRealtime.ts)**: stream `@ticker` (1 detik) → `@aggTrade` (per-trade) + throttle 100ms.

**Sync Interval 5 detik**: Recent Trades & Running Positions kini refresh tiap 5 detik (dari 20s/10s) agar status LIMIT WAITING→OPEN sinkron. Backend `/api/asi/balance` punya cache 4 detik per device+exchange untuk melindungi rate-limit API key user.

**Fix kartu pending Recent Trades**: trade LIMIT/pending kini tampil badge kuning "LIMIT WAITING" (bukan PnL +$0.00/+0.00%) — identik dengan Running Positions, menghilangkan kesan "sudah masuk posisi".

**Fix posisi tombol CANCEL/CLOSE**: tombol aksi dipindah ke baris sendiri yang SELALU rata kanan (`justifyContent: flex-end`) di kedua layar — sebelumnya tergabung di baris badge dengan flexWrap sehingga kadang jatuh ke kiri saat badge penuh.

**Fix kartu tidak ticking**: (1) TTL cache `/api/asi/prices` diturunkan 1.0s → 0.25s (cache global per-simbol, beban upstream tetap maks 4 fetch/s/simbol berapapun subscriber); (2) polling harga kini mencakup status `pending_entry` — kartu LIMIT juga ticking terhadap harga limit-nya. Terukur: 7/10 poll @300ms harga berubah.

**PERINGATAN TESTING**: Jangan storm-test `/api/dashboard?full=true` berulang — Binance `data-api.binance.vision` IP-ban pod (HTTP 418) setelah ratusan fetch. Ban ~7 menit. Dashboard recover otomatis via cache + fallback Bitget/CoinGecko.

---


---

## v10.1.7 — 7 Perbaikan Bug/Regresi (Oktober 2026)

1. **Logo splash & app icon diganti** — logo baru (file_0000000050ac8211a2ed46dd69c1f1fe.png, 2.3MB, 1254x1254) di-copy ke icon.png, adaptive-icon.png, splash-icon.png, splash-image.png, app-image.png, favicon.png.
2. **UI Kartu 3-Baris (anti-jiggle)** di `asi-bot.tsx` Recent Trades & `trades-position.tsx` Running Positions:
   - Baris 1: Tanggal & Jam (+ closed reason bila CLOSED).
   - Baris 2: Symbol/USDT (kiri) | Mark Price lebar tetap 110px tabular-nums (tengah) | PnL $ + % lebar tetap 100px tabular-nums (kanan) → tidak lagi bergeser saat harga berubah.
   - Baris 3: Semua badge dalam satu baris (D/R, 🤖/🦾 mode, L/M entry, LONG/SHORT, leverage, margin mode, layer, status, formula) + tombol CLOSE/CANCEL di ujung kanan.
3. **Closed position tetap tampil % PnL** di bawah nominal $ (sebelumnya hanya open yang menampilkan %).
4. **Badge "R" oranye & "D" biru muda** sudah seragam di semua kartu (asi-bot & trades-position pakai warna identik `#F97316`/`#60A5FA`).
5. **Mark price polling 300ms** (kembali seperti sebelumnya) di `asi-bot.tsx` dan `trades-position.tsx` — angka berkedip real-time persis seperti chart candlestick.
6. **Demo balance race-condition** — `setBalance` kini pakai functional updater yang mempertahankan nilai sebelumnya bila API balance sesaat gagal, jadi angka DEMO/REAL tidak lagi hilang-timbul.
7. **FX Rate strip USDT→lokal dikembalikan** — `<UsdtLocalRateStrip />` dipasang kembali di dashboard home antara tombol ASI-Bot/Copy Trade dan region chips (dulu dihapus v8.5.7, user minta aktif kembali).

**Bonus**: Simbol di kartu asi-bot.tsx Recent Trades sekarang `{symbol}/USDT` lengkap (sebelumnya hanya `{symbol}` → sumber laporan "koin pair hilang").

---


## v8.12.83 — Website Landing Page Baru (ASO/SEO)
- Tombol "Visit Our Website" di paywall kini mengarah ke landing page baru **https://aicryptostockpro.my.canva.site** (menggantikan cryptostockpro.my.canva.site). URL terverifikasi aktif (HTTP 200).

## v8.12.82 — Hapus Fitur Promo Code
- Tombol INPUT PROMO CODE + sheet panduan DIHAPUS dari paywall (keputusan user: trial promo 7D kalah menarik dari trial bawaan 14D pada plan 1m/3m/6m/12m, sehingga promo code tidak bernilai).
- Tombol website di bawah email tetap ada, label dinetralkan menjadi "Visit Our Website" → https://cryptostockpro.my.canva.site.
- Susunan paywall kini: Subscribe CTA → Restore Purchase → Email → Website.
- Endpoint backend /promo/redeem & /promo/redeemed dibiarkan (tidak dipakai frontend).
- Kampanye Play Console promo-2026 bisa user nonaktifkan sendiri di Play Console.
- Screenshot-verified.

## v8.12.81 — Fix Promo Code: Custom Codes HANYA Bisa In-App
- Root cause (dari dok resmi Google): **custom codes tidak bisa diredeem di play.google.com/redeem** (halaman itu hanya untuk gift card/one-time codes). Redeem custom code WAJIB lewat purchase sheet in-app: pilih plan → SUBSCRIBE → di payment sheet tap panah metode pembayaran → "Redeem code".
- Sheet Promo Code dirombak menjadi panduan 5 langkah + tombol "USE PROMO NOW" (otomatis memilih plan 1 Month agar user tinggal tap SUBSCRIBE).
- Deep-link redeem & pencatatan attempt per device DIHAPUS dari flow (Google sendiri menegakkan: 1× per akun + hanya untuk yang belum pernah subscribe).
- Screenshot-verified: panduan tampil, USE PROMO NOW memilih 1 Month.

## v8.12.80 — Fix Kritis Promo Code (404 + Premature Lock)
- FIX URL: redeem diarahkan ke URL resmi `https://play.google.com/redeem?code=...` (sebelumnya `/store/redeem` → 404 di device user).
- FIX lock logic: pencatatan server kini diperlakukan sebagai ATTEMPT; sheet hanya terkunci bila attempt ADA **dan** entitlement premium AKTIF (isPremium) — bukti trial benar-benar jalan. Redeem gagal/batal → user bisa coba lagi.
- Pesan sheet diperbarui: lock = "trial is active"; hint ditambah "If the redeem page fails, just come back and try again."

## v8.12.78 — Tombol Website "Get Promo Code & Redeem Guide"
- Tombol baru (ikon globe) tepat di bawah baris email di paywall → membuka website resmi `https://cryptostock-pro.emergent.host` tempat user mendapatkan promo code + panduan redeem.
- Sheet Promo Code kini berisi instruksi redeem 7-day trial langkah-demi-langkah (ambil kode → ketik persis → REDEEM ON PLAY STORE → konfirmasi).
- Screenshot-verified: tombol tampil rapi di bawah email.

## v8.12.76 — Promo Code 1× per Device (Anti Re-apply)
- Endpoint baru: `GET /api/promo/redeemed?device_id` + `POST /api/promo/redeem` (idempotent, first-wins) — koleksi Mongo `promo_redemptions`.
- Sheet Promo Code mengecek status redeem saat dibuka: jika device sudah pernah redeem → input diganti pesan "already redeemed on this device" (tombol redeem hilang).
- Pencatatan dilakukan TEPAT SEBELUM deep-link ke Play Store redeem page. Google Play juga membatasi custom code 1× per akun → proteksi ganda.
- Backend curl-verified: redeem ke-2 pada device yang sama mengembalikan `already: true`.

## v8.12.75 — Tombol Promo Code di Paywall
- Tombol **INPUT PROMO CODE** (gold outline) di bawah Restore Purchase, MENGGANTIKAN tombol Login Admin (admin tetap bisa login lewat ikon kunci 🔑 di header dashboard).
- Membuka sheet input kode → tombol "REDEEM ON PLAY STORE" deep-link ke `https://play.google.com/store/redeem?code=...` (kode terisi otomatis).
- Kampanye Play Console: **promo-2026**, Subscription AI Crypto Stock Pro Monthly, Free Trial 7 hari, **Custom codes** (`CRYPTOSTOCK-7D`, disimpan user-side — TIDAK di-hardcode di app), 9 Sep 2026 14:00 → 31 Dec 2026 00:00.
- Screenshot-verified: tombol tampil sesuai desain user + sheet promo terbuka.

## v8.12.74 — Fix: Ikon Trader Profile Tidak Berubah
- Root cause: `useTraderProfile` menyimpan useState PRIVAT per komponen — modal picker dan header dashboard punya state terpisah, jadi memilih profil di modal tidak pernah meng-update ikon header (tetap ⚡ sampai restart app).
- Fix: hook diubah menjadi shared module-level store via `useSyncExternalStore` — semua komponen sinkron instan.
- Verified via automation: pilih scalper/day/swing/longterm → header aria-label berubah sesuai ("Trader Profile: Scalper" dst) dan emoji ikon berubah (🏃⚡📈🐢).
- Catatan: request chart/analyze di halaman detail SUDAH membawa profil yang dipilih (membaca AsyncStorage saat screen mount), jadi sinyal tidak selalu Day Trader — hanya ikon header yang stale.

## v8.12.73 — 1 Week Juga Sekali Pakai
- Pernah beli **pro-1w** → kartu 1 Week terkunci "ALREADY CLAIMED" (tidak bisa resubscribe, harus lanjut 1m/3m/6m/12m) DAN kartu prepaid-2m terkunci "NOT AVAILABLE".
- Kedua first-subscriber plan kini strictly one-time per device.

## v8.12.72 — 1 Week & 2 Months Saling Eksklusif (First-Subscriber Plans)
- Aturan baru: pernah beli **pro-1w** → kartu **prepaid-2m** terkunci ("NOT AVAILABLE"); pernah beli **prepaid-2m** → kartu **pro-1w** terkunci. Hanya subscriber benar-benar baru yang bisa memilih salah satu.
- prepaid-2m yang sudah pernah diklaim tetap tampil "ALREADY CLAIMED".
- pro-1w sendiri tetap auto-renewing & bisa diperpanjang normal (hanya terkunci oleh klaim prepaid-2m).
- Cek klaim: prepaid-2m + legacy pro-2m + pro-1w via `/api/subscription/promo-claimed` (server-side, tahan reinstall).

## v8.12.71 — Migrasi Promo ke Prepaid `prepaid-2m`
- Base Plan ID untuk promo 2 Months diganti menjadi `prepaid-2m` (Prepaid, 2 Months, USD 19.99 / Rp 359.000).
- Tidak auto-renewing: langganan otomatis selesai setelah 2 bulan tanpa perpanjangan.
- Teks footnote: "Limited One Time Offer".
- Pemeriksaan satu kali klaim (`checkPromoClaimed`) mendukung `prepaid-2m` dan `pro-2m`.

## v8.12.69 — Promo Sekali Pakai + Update Popup
- **Promo 2 Months hanya 1× per device**: verify subscription kini mencatat `base_plan_id` di Mongo; endpoint baru `GET /api/subscription/promo-claimed?device_id&base_plan_id`; kartu pro-2m terkunci (dimmed, "ALREADY CLAIMED") setelah pernah dibeli — tahan reinstall.
- **Update prompt**: endpoint `GET /api/app-version` (APP_LATEST_VERSION di server.py — WAJIB bump tiap release); komponen `UpdatePrompt.tsx` di dashboard membandingkan APP_VERSION vs latest, popup "Update Available" → tombol buka Play Store (market:// + fallback https). Dismiss "Later", muncul lagi di cold start berikutnya.
- Default paywall selection = 3 Months (sesuai desain user).

## v8.12.68 — Migrasi 2 Months LIMITED ke Dedicated Base Plan `pro-2m`
- Kartu 2 Months LIMITED dimigrasikan dari nested offer `september-promo-2for1` (yang rentan gagal eligibilitas / parsing offer token) menjadi dedicated Base Plan ID `pro-2m` (Every 2 Months, USD 19.99 / Rp 359.000).
- Alur purchase sekarang memanggil `purchaseSubscription("pro-2m")` standar sama persis seperti `pro-1w`, `pro-1m`, `pro-3m`, `pro-6m`, `pro-1y` yang sudah terbukti 100% stabil.
- Begitu user membuat dan mengaktifkan base plan `pro-2m` di Play Console, pembelian 2 Months akan langsung sukses tanpa error.

## v8.12.67 — Fix: Error Promo Tertelan Handler Generik
- Root cause kandidat: pesan error "promo offer not active" milik app mengandung "try again" → tertangkap detector error generik Play, sehingga penyebab asli (offer tidak terlihat device) tersembunyi.
- Error promo kini pakai code APP_PROMO_NOT_FOUND → dialog khusus "Promo Not Available" berisi checklist Play Console (offer ID persis, ACTIVE di base plan pro-1m, tunggu propagasi).
- v8.12.66 — Dialog generik Play menampilkan "Detail:" berisi raw error + log visible offers.

## v8.12.65 — September Promo "2 Months LIMITED" di Paywall
- Tier baru "2 Months" (LIMITED badge merah, bingkai emas): offer Play Console `september-promo-2for1` pada base plan `pro-1m` — $10/bulan × 2 bulan ($19.99), eligibilitas "Never had any subscription" (ditegakkan Google Play).
- SubscriptionTier sekarang punya `id` unik + `offerId` opsional (promo share basePlanId pro-1m dengan tier 1 Month); purchase flow memilih offer persis by offerId.
- Teks kartu diselaraskan dengan desain user: "$4.79/week", "$20/month", "$10/month", footNote "NO FREE TRIAL" / "14-D FREE TRIAL" / "Limited Time Offer", Save badge sebaris dengan per-month.
- Screenshot-verified: 6 kartu 3 baris, CTA "SUBSCRIBE 2 MONTHS" + hint promo saat kartu LIMITED dipilih.
- CATATAN: harga Rp lokal baru muncul dari Play Billing di APK; web preview menampilkan fallback USD.

## v8.12.64 — Full-Board IDX (983 ticker) + Search Ranking Fix
- STOCK_YAHOO_MAP 594 → **983 ticker** (full board BEI, dari daftar resmi IDX 957 emiten + suplemen). Sumber: Draw-lh/idx-bei + Pulse-CLI tickers.json.
- FIX ranking search: safety-net crypto (CoinGecko) tidak lagi mendahului exact match pasar lain. Contoh: "ABBA" sebelumnya menampilkan token crypto acak; sekarang menampilkan saham IDX ABBA. TRUMP tetap crypto.
- Lint F601/F811/F821 dibersihkan (Any import, noqa F811).
- Verified: ABBA/AGRO/PACK/KICI/BBCA → stock_id; TRUMP → crypto.

## v8.12.63 — IDX Medium/Low-Cap Search Expansion
- STOCK_YAHOO_MAP expanded ~150 → 594 tickers (banks kecil, konsumer, teknologi, properti, manufaktur, kesehatan, media, logistik, tambang, perkebunan, infra, jasa). Termasuk PACK, KICI, BTPN, FILM, WIFI, dst.
- Ticker invalid/delisted otomatis ter-drop dari hasil search (snapshot Yahoo None) — aman.
- Duplicate dict keys dibersihkan (F601). Verified: search PACK/KICI/BTPN/FILM/WIFI return stock_id hits; prefix "PA" menampilkan PACK; UI search→detail PACK render lengkap.

## v8.12.62 — Universal Crypto Price Precision (AUDITED)
- formatPrice adaptive: ≥100→2dp, 1–100→4dp, 0.01–1→5dp, 0.0001→6dp, <0.0001→8dp.
- Audit 2026-09: SEMUA call site (AssetCard, SearchHitCard, detail header/High-Low/Entry-SL-TP, PositionSizeCalculator, CandlestickChart, DipTopPopup) memakai adaptive precision. Backend TIDAK membulatkan harga. API verified full precision untuk ATOM, AAVE, LTC, AVAX, BNB, BCH, XRP, INJ, TRUMP, HYPE, SOL, LINK, COMP, NEAR, TON, UNI, DOT, ARB, SAND.
- KESIMPULAN: fix presisi sudah benar di preview. Device user masih menampilkan 2 desimal karena APK lama — WAJIB Publish + rebuild APK.

## v8.12.36 — Voice + Trending + Live Chat Presence
1. **🎙️ Voice Search** — Mic button in the search bar. Native uses `expo-speech-recognition`, web falls back to Web Speech API. Cleaned transcript auto-fills the search input.
2. **🟢 Chatroom Online Badge** — Green pill on the CHATROOM button showing live online-member count. Polls new `/api/chat/online` every 20s. Sends presence heartbeat when the current user has access.
3. **🔥 Trending Tickers Column** — New dashboard column right after Watchlist. Ranks the top 12 loudest movers by |24h % change| across every loaded market. Purely client-side, updates live with dashboard polls.

Version 8.12.36 tested (backend 8/8 pytest + frontend PASS).

## v8.12.35 — Search Crash Hotfix
- Fixed `ReferenceError: t is not defined` in `SearchResults` (module-scope function was missing its `useI18n()` hook). Added defensive null-safety across AssetCard/SearchHitCard/merge.

## Previously Shipped
- Anti-FOMO Guard v3 for 7 markets
- WR formula excludes Break-Even & HOLD
- MarketSkeleton loader
- Chat presence indicator inside room
- Watchlist fix for outside-top-50 assets
- SEO metadata + tagline

## Known Constraints
- DO NOT touch flicker fix in `/app/frontend/app/asset/[market]/[symbol].tsx` (BLOCKED by user).
- Voice Search on native devices requires a fresh APK/AAB build (Expo Go bundle does NOT include the native module).
- Preview → Production: user must re-Publish + regenerate build APK/AAB for frontend features to reach their device.

## v9.0.0 — "Confluence" Total Formula Overhaul (Sept 2026)

**Pemicu**: User melaporkan 3 bug kritis — (1) akurasi sinyal anjlok pasca-v3
(kebanyakan loss, arah tertukar), (2) dashboard (DIP/TOP) tidak sinkron dengan
detail aset (Sideways vs Long/Short), (3) saham US premium (TSLA/INTC) hilang
dari search.

**Perubahan**:
- `backend/indicators.py` — compute_signal() ditulis ulang total:
  trend-following confluence (struktur EMA + zona pullback ±1.5 ATR + RSI
  band + MACD hist + volume + momentum + EMA200 bonus). FLIP/DIP/TP
  inversion DIHAPUS (overextended → HOLD "tunggu pullback", bukan sinyal
  berlawanan arah). Confidence jujur 50-95. TP ladder (1R/2R/3R) dipilih
  dari backtest: 30 hari, 9 aset, 302 trade → WR 57.1%, +0.136R/trade
  (vs formula lama 51.8%, +0.03R). Guard stablecoin (ATR<0.1% → HOLD).
- `backend/server.py` — ?profile= ditambahkan ke /api/dashboard,
  /api/dashboard/batch, /api/search → sinyal dashboard IDENTIK dengan
  detail (diverifikasi 8 aset × 2 profil, 0 mismatch).
- `frontend` — api.ts + index.tsx mengirim traderProfile ke dashboardBatch
  & search; reload saat profil berubah. Versi 9.0.0.
- `backend/backtest_v9.py` — harness backtest walk-forward.

**Testing**: 17/17 PASSED (iter29) — R:R ladder, sync dashboard-detail,
search TSLA/INTC, presisi harga DOT, label sanity, regresi endpoint.

**Catatan penting**: JANGAN mengembalikan logic FLIP atau confidence gate.
JANGAN sentuh flicker fix di asset/[market]/[symbol].tsx.

## v9.1.0–v9.2.0 — VWAP Session Engine + Master 15-Video Formula

**User memberikan formula sendiri** (dari 15 video trading) untuk Trader Profile:
- **VWAP Core**: anchored VWAP dengan reset per sesi (tanggal UTC).
- **Separator**: mean-reversion saat deviasi harga ≥1.5% dari VWAP.
- **KISS Pivot**: bounce/rejection tepat di garis VWAP (INTRADAY).
- **John Wick**: wick ≥60% dari range candle (rejection).
- **Power of Tower**: candle impulsif (body >80% range) + retrace 50%.
- **Box Theory**: breakout konsolidasi lookback 10/20/50 per profile.

**Routing** (backend/indicators.py): scalper→SCALPER(box10) · day→INTRADAY(box20)
· swing→SWING(box50) · longterm→Confluence v9.0 (EMA50/100/200).
Fallback ke Confluence jika tanpa volume (forex). Level VWAP: tier rapat
0/0.3/0.6 ATR (sinyal = pemicu), SL per profil, TP 1R/2R/3R.
Guard stablecoin hanya untuk crypto (forex 1h normal bervolatilitas <0.1%).

**Backtest 30d (9 aset)**: scalper 55.3% WR (+50R) · day 51.4% (+12R) ·
swing 51.3% (+1R). Testing iter30: 8/8 PASSED.

## v9.3.0 — Trader Profile Toggle (unselect → Confluence)

User request: profile selector jadi opsional/toggle. Tanpa pilihan → mesin
Confluence v9.0.0 (default, header 🧠). Ketuk profil aktif lagi = lepas.
Mesin VWAP (v9.1/9.2) hanya jalan saat scalper/day/swing dipilih eksplisit.
Backend: routing `profile in _PROFILE_TO_VWAP` (None → Confluence).
Frontend: `_explicit` state di useTraderProfile; apiProfile=null → param
?profile= tidak dikirim ke dashboardBatch/search/chart/analyze.

## v9.1.2 — Fix Premium Badge Hilang

Report: badge premium hanya tampil di kolom forex. Root cause: (1) confidence
mesin VWAP mentok ~79 (base 55) — tak pernah lolos gate 85+; (2) gate premium
warisan v8 (WR>=72-75%, bar tanpa-histori +5) mustahil untuk formula v9 yang
jujur (backtest WR 55-57%). Fix: VWAP trigger utama +14 confidence; threshold
market → (85, 55); bar tanpa-histori → +3. Hasil: 56 premium (Confluence),
36 (scalper), 18 (day), 14 (swing). stock_us 0 di mode VWAP = trigger memang
belum menyala (bukan bug).

## v9.1.3 — Fix Sinyal Berkedip (Anti-Flicker)

Report user: ETH di dashboard HOLD→SHORT→HOLD dalam hitungan detik. Dua root
cause: (1) candle live (forming) ikut dihitung — kondisi cross VWAP/breakout/
pola berubah tiap detik; fix: _drop_forming_candle() di compute_signal, sinyal
hanya dari candle TUTUP (standar Pine isconfirmed). (2) startup race: app boot
memakai Confluence lalu beralih ke VWAP setelah AsyncStorage termuat; fix:
gate profileLoaded di dashboard load() & detail loadChart(). Verified: 4 poll
beruntun identik (ETH SELL/91), harga sinyal anchor ke candle tutup.

## v9.1.4 — Sinkronisasi Penuh Detail Aset (audit user)

- Level entry/SL/TP di-anchor ke harga LIVE ticker (arah sinyal tetap dari
  candle tutup). Fix "TP di atas harga realtime".
- Mesin VWAP kini mengirim ema20/ema50/macd_hist (sebelumnya "—"/0.0000).
- TargetProfit.tsx menampilkan ladder backend TP1/2/3 apa adanya (tidak
  interpolasi 40/70% lagi); R:R terhadap TP1.
- Label indikator dinamis mengikuti periode EMA selector (9/21 scalper,
  20/50 day-swing, 50/100 longterm).
- Limit candle snapshot 100→250 → EMA200 aktif; longterm crypto berfungsi.
- UpdatePrompt (popup update announce) terverifikasi utuh; backend
  /api/app-version masih latest=8.12.83 (naikkan ke 9.1.3 setelah publish).

## v9.1.6 — US Stock Universe Lengkap

BNY/GEV/HONA tidak ada di map lama (810 ticker). Ditambahkan
STOCK_US_YAHOO_MAP_EXTRA (5.256 ticker) dari daftar resmi NASDAQ Trader
(nasdaqlisted + otherlisted, tanpa ETF/warrant/preferred/test-issue) +
S&P 500 penuh → total universe US 6.066 ticker. S&P500 coverage 503/503.
Sifatnya search-only (dashboard full=true tetap 810 kurasi agar fetch
Yahoo tidak berat). Fetch snapshot & region fallback ke EXTRA.

## v9.2.0 — Formula 68-Video + AI Suggestions (Premium)

- 3 mesin VWAP (scalper/day/swing) kini menyertakan: bias harian 50 SMA
  (lawan arah: scalper half-risk, day/swing HOLD), liquidity zones,
  Choke Risk Protection (TP1 > 80% Daily ATR → batal), Pattern Scalp 15M
  (manipulasi open + John Wick/Power of Tower, TF ≤15m, level persis pola).
- Fitur AI Suggestions (premium): tombol di popup Trader Profile → sheet
  kategori market → top-10 aset bersinyal lengkap Entry/SL/TP1-3 + bias.
- Gating: Trader Profile selector premium-only (header 🔒 → paywall);
  non-premium hanya dashboard dengan mesin Confluence (profile tak dikirim).
- Gate backend mengakui subscription Play Billing + unlock code admin.
- Fix: deviceId web kini stabil via localStorage (preview entitlement OK).
- Test unlock code E2E: E2E-AISUG-TEST → device web:aitest-e2e-001.

## v9.1.6 — Popup Wajib Profil untuk AI Suggestions

- Menekan tombol AI Suggestions di TraderProfileModal TANPA profil
  eksplisit (Confluence default) ATAU dengan profil Long-term kini
  menampilkan popup "Pilih Trader Profile Dulu" (Bahasa Indonesia).
  Sheet TIDAK dibuka, API /api/ai-suggestions TIDAK dipanggil.
- AI Suggestions hanya berjalan dengan profil Scalper / Day Trader
  (Intraday) / Swing (AI_SUGGESTION_PROFILES di TraderProfileModal.tsx).
- Tombol "PILIH PROFILE" menutup popup, modal profil tetap terbuka agar
  user langsung memilih; setelah pilih, user menekan AI Suggestions lagi.
- Non-premium tidak berubah: tombol profil di header → paywall;
  dashboard tetap Confluence. Toggle unselect profil tetap berfungsi
  untuk dashboard/detail (gating hanya pada tombol AI Suggestions).
- Terverifikasi e2e web: popup muncul tanpa profil; setelah pilih
  Scalper, sheet AI Suggestions terbuka normal.

## v9.2.0 — Lokalisasi AI Suggestions (EN/ID/RU/CN)

- Semua teks AI Suggestions kini mengikuti bahasa pilihan via i18n
  (I18nContext): judul & sub judul CTA di TraderProfileModal, popup
  "Pilih Trader Profile Dulu" (judul/body/tombol), header sheet,
  locked-state premium, empty-state, label kategori (reuse key
  category_*), label BIAS HARIAN, dan tombol "Buka Detail Aset".
- Key baru: ai_suggestions_title/sub, ai_profile_required_title/body/btn,
  ai_sheet_sub, ai_locked_title/sub, ai_upgrade, ai_empty_title/sub,
  ai_open_detail, ai_daily_bias.
- Terverifikasi e2e: 4 bahasa menghasilkan 4 terjemahan berbeda pada
  tombol AI Suggestions (EN "AI SUGGESTIONS" / ID "SARAN AI" /
  RU "РЕКОМЕНДАЦИИ ИИ" / CN "AI 建议").
- CATATAN: deskripsi kartu profil (Scalper/Day/Swing/Long-term) masih
  Bahasa Indonesia statis di PROFILE_META — belum dilokalkan.

## v9.2.1 — Fix AI Suggestions: World Stocks kosong + chip tak terbaca

- Backend /api/ai-suggestions kini full=True → memindai SELURUH universe
  terkurasi (stock_us 787 ticker, bukan 50 mega-cap). Hasil: stock_us
  mengembalikan 10/10/5 setup untuk scalper/day/swing (sebelumnya 0).
- Penyebab empty: universe 49 mega-cap + trigger VWAP ketat + gate bias
  50 SMA harian → semua HOLD. Bukan bug formula, tapi sampel terlalu kecil.
- Gold/Silver HANYA punya 4 instrumen (XAU/XAG/XPT/XPD) — empty state
  saat tak ada setup adalah kondisi pasar yang sah, bukan salah setup.
- Frontend chip kategori: flexShrink:0 + minHeight 40 + numberOfLines=1
  → teks chip tidak lagi tergepeng/terpotong saat daftar penuh (terlihat
  di device user sebagai teks bertumpuk tak terbaca pada IDX Stocks/Forex).
- Terverifikasi: 6 chip terbaca penuh satu baris di web preview.

## v9.2.1 — Fix UpdatePrompt tidak muncul

- Penyebab: APP_LATEST_VERSION di backend masih "8.12.83" sedangkan
  build terinstal 9.2.1 → isOutdated() false → popup tak pernah muncul.
- Fix: APP_LATEST_VERSION = "9.2.1" (server.py). Endpoint
  /api/app-version terverifikasi mengembalikan 9.2.1.
- Catatan: popup HANYA muncul di perangkat dengan versi < 9.2.1
  (mis. build lama 8.12.x / 9.1.x). Perangkat yang sudah 9.2.1 tidak
  akan melihat popup — by design.
- WAJIB: bump APP_LATEST_VERSION bersamaan setiap rilis versi baru.

## v9.2.2 — ETF ditambahkan ke AI Suggestions + bump versi

- ETF sebelumnya tidak terdaftar di ai-suggestions (Literal backend +
  CATEGORIES sheet). Kini ditambahkan: chip 📊 ETF (label reuse key
  category_etf), endpoint menerima market=etf.
- Universe ETF = 66 instrumen (FULL_ETF). Hasil tes: Confluence 10 pick
  (VTI, VXUS, ...); profil VWAP 0 saat ini — ETF bervolatilitas rendah
  jarang memicu box breakout/reversal + gate bias 50 SMA → HOLD. Ini
  perilaku formula yang sah, sama seperti Gold/Silver (4 instrumen).
- Bump versi 9.2.2 di version.ts, app.json, APP_LATEST_VERSION backend.

## v9.2.3 — WR label fix + perketat agresivitas sinyal

- Investigasi bug label WIN/LOSS terbalik: DB terbukti BENAR
  (ETH SELL pct=-1.41 → outcome=WIN, BTC SELL pct=+0.63 → BE, dst).
  Masalahnya UI menampilkan raw market pct, bukan P/L dari sisi trader.
- FIX UI: formatPct di WrHistoryModal kini balik tanda untuk action SELL
  → trade SHORT yang untung sekarang tampil "+1.23%" (bukan "-1.23%"),
  yang rugi tampil "-6.59%" (bukan "+6.59%"). Warna & label WIN/LOSS/BE
  otomatis konsisten dengan P/L view.
- WR formula: sudah wins/(wins+losses) exclude BE — sesuai permintaan
  user (jangan hitung BE/CL). Tidak berubah.
- Turunkan agresivitas Confluence: min_score default 4→5.
  Butuh minimal 5 komponen confluence untuk trigger BUY/SELL
  (sebelumnya 4). Verifikasi crypto dashboard: 17 sinyal aktif dengan
  RATA-RATA confidence 94.3 (sebelumnya jauh lebih rendah dan sinyal
  ambang lolos). Kualitas > kuantitas.
- Bump 9.2.3 di version.ts, app.json, APP_LATEST_VERSION.

## v9.2.4 — Opsi C: WR tuning Confluence & VWAP (user-approved)

Perubahan (indicators.py):
- TRADER_PROFILES: tp_ladder → (0.7,1.5,2.5) untuk semua; TAMBAHAN
  vwap_tp_ladder khusus mesin VWAP: scalper (0.5,1.0,1.75),
  day (0.55,1.1,2.0), swing (0.6,1.25,2.25), longterm (0.8,1.75,3.0).
- Confluence min_score: 5 → 8 (butuh 8 dari 9 faktor confluence).
- VWAP triggers: SCALPER & INTRADAY & SWING wajib pola reversal
  (bull_rev/bear_rev); SCALPER+INTRADAY wajib volume ekspansi x1.1;
  SWING tanpa volume gate (breakout box-50 multi-hari sering terjadi
  saat akumulasi bervolume biasa).
- Confidence floor VWAP: scalper/intraday 78, swing 72.
- FIX LATENT BUG: closes/highs/lows/atr di _compute_vwap_signal dipakai
  blok SCALP-15M sebelum didefinisikan → NameError setiap scalp pattern
  terpicu. Dipindah ke awal fungsi.
- backtest_24mo.py: jendela per mode (swing 96/12, day 36/6 candle).

Hasil backtest 24 bulan (5 big caps, 1h, TP1 vs SL, pra-tuning swing):
- Confluence (min_score 7): 467 trade, WR 67.2%, exp +0.16R
- Scalper: 125 trade, WR 79.2%, exp +0.20R  ✓ target 75-80
- Day: 122 trade, WR 77.7%, exp +0.21R  ✓ target 75-80
- Swing: 19 trade, WR 52.9%  ✗ (terlalu ketat di 1h + jendela 24 jam)
- Penyesuaian pasca-backtest (min_score 8, swing tanpa vol gate, floor
  swing 72, jendela swing 96 candle) BELUM di-backtest ulang — user
  minta publish segera. TODO: backtest ulang v3 untuk konfirmasi. Versi 9.2.4 sudah di-bump (version.ts, app.json, APP_LATEST_VERSION).

## v9.2.4 — Audit Konsistensi Menyeluruh & Fix Desync Dashboard vs Detail

Keluhan user: dashboard SUI LONG 95% tapi detail SIDEWAYS 58% (tanpa
profil, TF standar 1H). Screenshot user tepat di batas penutupan candle
1h (09:00/09:01).

Root cause bertingkat yang ditemukan & diperbaiki:
1. DEFAULT TF DETAIL: crypto default 1m (fitur animasi live) vs dashboard
   1h → FIXED: default 1h untuk semua market; AISuggestionsSheet.openDetail
   kini mengirim ?timeframe=1h.
2. CACHE DASHBOARD 300s (stale s/d 900s): dashboard menyajikan sinyal dari
   candle lama hingga 5-15 menit setelah candle baru tutup, sementara
   detail fetch segar → FIXED: _snapshot_cache kini candle-boundary-aware
   (server.py): cache dibatalkan begitu candle timeframe berganti; stale-
   while-revalidate hanya berlaku dalam candle yang sama.
3. CACHE YAHOO DETAIL 60s: aturan boundary yang sama diterapkan ke
   _YAHOO_CHART_CACHE (market_data.py) untuk konsistensi dua arah.
4. LIVE ANCHOR v9.1.4: Entry/SL/TP di-anchor ke live ticker → bergeser
   0.02-0.1% antar jalur fetch → FIXED: anchor = harga candle TUTUP
   (deterministik) di KEDUA mesin (Confluence & VWAP). Level identik di
   semua layar selama candle berjalan, berubah hanya saat candle tutup.

Verifikasi:
- audit_consistency.py (baru): 48 kasus (12 aset × 4 profil) membandingkan
  dashboard vs chart vs analyze vs search — termasuk Entry/SL/TP.
  Hasil final: 0 mismatch arah/label/confidence; chart == analyze identik.
- Residu terdokumentasi: Yahoo kadang me-restate closed candle lintas
  menit (drift level <0.1% pada komoditas antar-menit); dalam satu sesi
  user (dashboard→detail dalam hitungan detik) semua jalur berbagi cache
  per-symbol 60s yang sama → angka identik. Arah sinyal tidak pernah
  berubah karena ini.
- Testing agent E2E: 7/7 flow UI lulus (konsistensi kartu↔detail, gate
  profil AI Suggestions, popup, sheet↔detail, lokalisasi 4 bahasa, WR
  history P/L view). Pytest 11/12 (1 gagal = test harness GET vs POST
  analyze, bukan bug produk).
## v9.2.5 — bump rilis (semua perbaikan konsistensi v9.2.4 termasuk di dalamnya)

## v9.3.0-dev — ASI-Bot Phase 1 (Credential Management) ✓

- Dependensi baru: ccxt 4.4.100, cryptography 48.0.0 (sudah di requirements.txt)
- Modul: /app/backend/asi_bot/{crypto.py, exchanges.py, routes.py}
- Enkripsi AES-256-GCM envelope: master key 32B di ASI_MASTER_KEY (auto-generate ke .env saat first boot) + per-record 16B salt via HKDF-SHA256. Pola setara AWS Encryption SDK; siap migrate ke KMS tanpa ubah data.
- Routes (prefix /api/asi):
  * POST /credentials — validate via CCXT, TOLAK jika permission "withdraw" aktif, enkripsi api_key+secret+passphrase, simpan di asi_credentials.
  * GET /credentials — list user's masked connections.
  * DELETE /credentials/{exchange}
  * POST /credentials/{exchange}/test — re-validate stored key.
- 4 exchange didukung: binance (binanceusdm), bybit, okx, bitget — defaultType="swap" (USDT-M perpetual), set_sandbox_mode(True) untuk testnet.
- Fixed credential: auto-generate 3-huruf anonim dari email prefix (atau sha256 device_id).
- Verifikasi: list=200, invalid-key save=400 pesan jelas, 4 exchange terdaftar.

Fase berikutnya (BELUM):
- F2 Execution Engine (Entry + Bracket SL/TP1-3, Semi/Full-Auto, risk 1-30%, whitelist Top-100)
- F3 UI: tombol ASI-Bot & Copy Trade di dashboard, halaman ASI-Bot Semi/Full
- F4 PnL harian/mingguan/bulanan + Top-10 leaderboard
- F5 Copy Trade engine + UI
- F6 Legal update (Privacy + In-App Disclaimer), E2E testnet, bump versi, publish

## v9.3.0 — ASI-Bot FASE 2+3+4 ✓

### Fase 2 — Execution Engine (backend)
- /app/backend/asi_bot/engine.py: preview_trade(), execute_trade(),
  close_position(), refresh_trade_pnl()
- Flow: whitelist check → fetch USDT balance → set_leverage → MARKET
  entry → reduce-only STOP_MARKET SL → reduce-only TAKE_PROFIT_MARKET
  TP1/TP2/TP3 dengan split 40/30/30. Safety net: tutup posisi darurat
  bila SL gagal setelah entry sukses.
- /app/backend/asi_bot/whitelist.py: 100 futures crypto (BTC, ETH, SOL,
  …, PYR). is_allowed() cocok base symbol apapun.
- /app/backend/asi_bot/pnl.py: pnl_summary (daily/weekly/monthly dgn
  wins/losses) + leaderboard (top N by pnl periode N hari).

### Fase 3 — UI (frontend)
- /app/frontend/app/asi-bot.tsx: layar lengkap — status aktif/nonaktif,
  koneksi 4 exchange (modal input key+secret+passphrase+testnet switch),
  mode Semi/Full chip, parameter risk/leverage/max-trade stepper,
  disclaimer check wajib, kartu PnL 3-kolom, leaderboard 7-hari, trade
  terbaru. Validasi credential langsung lewat endpoint backend.
- /app/frontend/app/copy-trade.tsx: leaderboard full-page 7/30/90 hari
  dengan filter chip, kartu top-3 highlighted GOLD; tombol "Copy"
  disabled (SEGERA) menunggu jaringan trader-master.
- Dashboard header: 2 tombol eye-catching tinggi/lebar sama di bawah
  Login — "🤖 ASI-Bot" GOLD + "🏆 Copy Trade" PURPLE dengan shadow.

### Fase 4 — PnL + Leaderboard
- Endpoint: /api/asi/pnl, /api/asi/leaderboard, /api/asi/trades,
  /api/asi/trades/{id}/refresh. Terhubung dari UI.
- Anonim handle 3-huruf auto-generate dari email prefix atau sha256
  device_id (fallback).

### Verifikasi
- Semua lint pass (asi-bot.tsx, copy-trade.tsx, api.ts, index.tsx).
- Backend endpoint smoke-test (/whitelist=100 items, /pnl zero-state,
  /leaderboard empty-state).
- Screenshot web preview: 2 tombol dashboard tampil benar, halaman
  ASI-Bot terbuka dengan semua seksi (koneksi, mode, parameter, risk).

### Belum (Fase 5 & 6)
- F5: integrasi tombol "Trade with ASI-Bot" di dalam AI Suggestions
  sheet & halaman detail aset (preview trade dari sinyal aktif).
- F6: Legal — update Privacy Policy & Terms teks di-app dan dokumen
  publish ke Google Play Console; E2E dengan testnet exchange nyata
  (butuh user API key testnet).

### Bump versi
- 9.3.0: version.ts, app.json, APP_LATEST_VERSION backend.

## v9.3.0 — ASI-Bot Fase 5 + 6 ✓

### Fase 5 — Tombol Trade with ASI-Bot
- Komponen baru: /app/frontend/src/components/AsiTradeSheet.tsx
  (bottom sheet reusable). Terima AsiTradeIntent {symbol, side, entry,
  stop_loss, take_profits}. Alur: fetch creds → preview debounced →
  stepper Risk/Leverage → tampilkan balance/margin/qty/est loss/
  tp estimations → tombol EXECUTE memanggil /api/asi/trades/execute.
- Terintegrasi di 2 titik:
  * AI Suggestions sheet: tombol "🤖 Trade with ASI-Bot" per kartu
    (hanya kategori crypto dengan entry/sl/tp lengkap).
  * Asset detail page: tombol gold besar di bawah TargetProfit untuk
    aset crypto dengan sinyal BUY/SELL aktif.
- Jika user belum terhubung ke exchange → tampilkan empty state
  dengan CTA menuju /asi-bot untuk connect.

### Fase 6 — Legal, Privacy & Compliance
- Halaman baru: /app/frontend/app/asi-legal.tsx dengan 3 seksi:
  * In-App Disclaimer & Terms of Use (6 pasal: non-custodial, risiko
    trading, kegagalan pihak ketiga, larangan withdrawal, whitelist,
    yurisdiksi pengguna).
  * Privacy Policy ASI-Bot (penyimpanan AES-256-GCM, penggunaan kunci,
    data yang dikumpulkan, hak hapus).
  * Google Play Data Safety Declaration (checklist yang WAJIB
    dicantumkan di Play Console App Content → Data Safety).
- Link "Baca Terms, Privacy & Compliance Lengkap →" dari halaman
  ASI-Bot di bawah disclaimer.

### Belum (menunggu input user)
- Testnet Live: user perlu share Binance Futures Testnet API key +
  secret (dari https://testnet.binancefuture.com) agar saya dapat
  menjalankan E2E execute test real dari backend ke exchange.

## v9.3.0 — Testnet Live E2E ✓ dengan Catatan Penting

### Yang Terverifikasi Live
- Credential disimpan terenkripsi (AES-256-GCM). Handle "NEO".
- Preview trade: balance real $5000 testnet, hitung margin/qty/risk benar.
- Entry MARKET: order sukses, ID 28614597338, posisi 0.0057 BTC muncul
  di akun testnet (verifikasi lewat /fapi/v2/positionRisk).
- PnL unrealized tracked via refresh endpoint.

### Catatan untuk Mainnet / Testnet Lain
- Binance Futures Testnet akun ini menolak STOP_MARKET & TAKE_PROFIT_MARKET
  pada /fapi/v1/order dgn error -4120. Reproducible juga via raw HTTP
  (bukan bug CCXT atau kode kita). Kemungkinan kebijakan akun spesifik.
- Engine kini punya "SOFT BRACKET" fallback: entry sukses tetap tersimpan,
  SL/TP ID = null, field soft_bracket=True + soft_bracket_reason.
- TODO Fase 7: scheduler watcher yang poll fetch_positions tiap N detik;
  bila mark price menyentuh SL atau TP level yang disimpan di DB,
  kirim MARKET close reduceOnly. Pattern ini standar di bot pro
  (3Commas, Pionex) karena menghindari batasan conditional order
  per exchange.
- Pada Binance Mainnet standar, STOP_MARKET umumnya diterima — code
  path yang sama akan menghasilkan sl_order_id dan tp_order_ids
  berisi, soft_bracket=False.


## v9.5.0 — Version Bump & Play Store Prep (Sep 2026)
- Version bumped 9.4.3 → 9.5.0 di `frontend/app.json` dan `frontend/src/lib/version.ts`
  untuk rilis fitur: ASI-Bot auto trading, native SL/TP hard-bracket, daily risk limiter,
  dan Copy Trade LIVE leaderboard.
- Full Description Play Store diperbarui user (mencakup ASI-Bot, disclaimer, link legal).
- Legal URLs terverifikasi user di Play Console: /api/privacy, /api/data-deletion, /api/terms.
- Release notes v9.5.0 (ID & EN) sudah diberikan untuk kolom "What's new".


## v9.5.0 — E2E 3 Test Trade MAINNET (Okt 2026) — BUG DITEMUKAN & DIPERBAIKI
- Bug kritis engine: `split("/")[0] + "USDT"` pada simbol "SOLUSDT" menghasilkan
  "SOLUSDTUSDT" → Algo API -1121 Invalid symbol → bracket diam-diam jadi soft.
  Diperbaiki di execute_trade & close_position (strip "USDT" dulu).
- Bug presisi: trigger price tidak di-normalize ke tick size → -1111. Engine kini
  round stop_loss/TPs ke price tick market.
- Bug `_split_tp_qty`: remainder tidak align ke amount step → qty invalid.
  Ditulis ulang berbasis integer step-units (sum selalu pas & step-aligned).
- TP failure kini terekam di soft_bracket_reason (sebelumnya silent).
- Hasil live mainnet (balance 12 USDT): SOL entry 118.58 → SL 117.4 tereksekusi
  NATIVE oleh Binance (fill 117.34, realized -0.06 USDT) — bukti hard-bracket
  bekerja tanpa backend. ETH & XRP posisi long berjalan dgn SL+TP1-3 native.
- Orphan TP algo orders dibatalkan setelah SL trigger (cancel_all_conditional).
- SECURITY: test_mainnet_via_sg.py berisi API key+secret PLAINTEXT — dihapus dari
  working tree, TAPI masih ada di git history (commit 4e9ef2f, ba713dd).
  REKOMENDASI: user regenerate API key Binance.


## v9.5.0 — Lokalisasi ASI-Bot & Copy Trade (Okt 2026)
- Kedua halaman sebelumnya hardcode Bahasa Indonesia; kini mengikuti bahasa
  pilihan user di dashboard (EN/ID/RU/CN) via useI18n.
- +50 key baru di I18nContext.tsx (prefix asi_* dan copy_*).
- Template runtime {ex}/{n}/{wr}/{price}/{ago} untuk string dinamis.
- timeAgo copy-trade memakai key relatif existing (news_time_*).
- Lint bersih 3 file; screenshot-verified EN di web preview.


## v9.6.0 — Flexible TP + Native Trailing Stop (Okt 2026)
- Pengguna bisa pilih berapa TP (1/2/3). Default 3.
  - 1 TP → close 100% posisi
  - 2 TP → split 50 / 50
  - 3 TP → split ≈33 / 33 / 34 (step-aligned)
- Chip TP ditempatkan tepat di bawah Leverage (per permintaan user).
- Trailing Stop callbackRate (default 2%) default aktif.
  - Setelah TP1 fill, scheduler mendeteksi via refresh_trade_pnl, lalu:
    1) cancel SL original + sisa TP via Algo API
    2) pasang TRAILING_STOP_MARKET native via Binance Algo
  - SL mengikuti harga puncak secara otomatis di exchange (tidak bergantung
    uptime backend / polling). Matematis lebih aman dibanding set SL
    manual di `last price − 2%` yang telat.
- Idempotent via flag `trailing_activated` di dokumen trade.
- Semi-Auto sheet dapat override tp_count & trailing_callback_rate per-trade.
- `_split_tp_qty` di-generalisasi menerima `n_targets=1|2|3`, memakai
  perhitungan integer step-units supaya hasil step-aligned & sum = qty.
- Version bump 9.5.0 → 9.6.0.


## v9.6.1 — Full-Auto Hormati Profil Strategi (Okt 2026)
- Gap ditemukan: scheduler Full-Auto memanggil pipeline sinyal TANPA profil
  → selalu Confluence meski user simpan profile scalper/day/swing.
- Fix: scheduler meneruskan cfg.profile → _asi_signal_fetcher(market, symbol, profile)
  → _build_dashboard_response(profile=...). Sekarang:
  scalper=VWAP-SCALPER (+Pattern Scalp 15M bila TF≤15m), day=VWAP-INTRADAY,
  swing=VWAP-SWING, confluence/None=mesin default.
- Mesin VWAP mencakup: VWAP Core session, Box Theory breakout (10/20/50),
  KISS Pivot reclaim/rejection, John Wick, Power of Tower, volume-expansion gate.
- User TIDAK minta chip profil tambahan di halaman ASI-Bot (pakai yang tersimpan).
- Timeframe fetch tetap 1h (konsisten dashboard). Catatan: Pattern Scalp 15M
  hanya aktif bila TF≤15m — di Full-Auto 1h, scalper memakai VWAP+Box+KISS saja.


## v9.6.2 — Version Bump (Okt 2026)
- User generate build 9.6.1 tapi preview masih tampil 9.6.0 karena bump
  nomor versi tidak dilakukan saat fix v9.6.1 (backend-only change).
- Fix: app.json + version.ts → 9.6.2. Diverifikasi string "9.6.2" termuat
  di bundle preview.
- RULE MULAI SEKARANG: setiap perubahan yang akan di-build HARUS disertai
  bump APP_VERSION + app.json version agar label versi tidak stale.


## v9.6.3 — Bump + Investigasi Android Build Gagal (Okt 2026)
- User melaporkan "Android build generation failed" di Manage Publishing.
- Health check deployment: SEMUA pass (kompilasi OK, app.json valid,
  release build config OK). Hanya 1 warning iOS push (GoogleService-Info.plist
  belum ada — tidak relevan untuk Android).
- Tidak ada blocker kode → kemungkinan kegagalan transient sisi build infra.
- Versi di-bump 9.6.2 → 9.6.3 untuk build ulang.
- Saran ke user: Re-publish changes → generate Android build lagi.


## v9.6.4 — Premium Gate ASI-Bot & Copy Trade (Okt 2026)
- Kedua halaman dikunci untuk member premium via usePremiumAccess()
  (isPremium Google Play Billing ATAU isUnlocked kode admin).
- Komponen bersama baru: src/components/PremiumLocked.tsx (lock icon,
  judul, body per-halaman, CTA → dashboard). i18n 4 bahasa.
- __DEV__ bypass: di web preview halaman tetap terbuka (by design,
  sama seperti News/Chat) — di APK produksi non-premium melihat
  layar terkunci.
- Catatan: gate saat ini UI-side (mengikuti pola app). Endpoint /api/asi/*
  belum 403-gated per-device; pertimbangkan hardening backend bila perlu.


## v9.7.0 — Root Cause Koneksi Binance DITEMUKAN & DIPERBAIKI (Okt 2026)
- Akar masalah sebenarnya BUKAN kode: VPS Tinyproxy open-to-world
  (Allow 0.0.0.0/0) → scanner internet menghabiskan MaxClients=100 →
  koneksi backend hang di TCP accept (timeout, pesan error kosong).
- Fix di VPS (oleh user via console): config dibatasi
  Allow 35.193.209.116 (IP egress backend) + 127.0.0.1, BasicAuth asi,
  MaxClients 500. Diverifikasi fapi ping 200 via proxy dalam 1.5s.
- ASI_PROXY_URL kini berisi kredensial: http://asi:***@143.198.197.107:8888
- exchanges.py: validasi Binance bypass CCXT → signed GET /fapi/v2/account
  (zero sentuhan endpoint spot/margin); klasifikasi error code
  (proxy_down, ip_or_key_invalid, region_blocked, withdraw_enabled,
  trade_disabled, auth_failed) → frontend terjemahkan via i18n 4 bahasa.
- PENTING: IP egress backend saat ini 35.193.209.116. Jika backend
  redeploy ke node lain, IP bisa berubah → proxy harus di-update.
  TODO: monitor /api/asi/server-ip atau buat alert jika egress berubah.
- Credential lama (mainnet-e2e, Yrbx...) sudah dihapus user → -2015 valid.


## v9.7.3 — BUG Full-Auto Diam-Diam Tidak Pernah Eksekusi (Okt 2026)
- User: bot ACTIVE + Binance MAINNET terkoneksi (key baru 5wZL...AGZ7 sukses
  tersimpan setelah fix case-sensitivity paste) tapi Full-Auto tidak pernah
  buka posisi. UI tidak menampilkan error apa pun.
- ROOT CAUSE: scheduler `_run_full_auto_scanner` skip config jika
  `whitelist` kosong (`if not whitelist: continue`), padahal UI ASI-Bot
  TIDAK punya kontrol whitelist → semua user Full-Auto punya whitelist []
  → bot tidak pernah scan simbol apa pun, tanpa pesan error.
- FIX: whitelist kosong → default ke TOP_100_FUTURES.
- PERF: `_asi_signal_fetcher` kini cache response dashboard penuh per
  (market, profile) TTL 60s — sebelumnya tiap simbol membangun ulang
  seluruh dashboard (787 ticker). Terverifikasi: cold 2.5s, warm 0.00s.
- Format simbol whitelist ("BTC") cocok dengan format dashboard ✓.
- Kondisi pasar saat test: 9 sinyal actionable conf≥75 (LTC/INJ/AAVE/UNI/
  JASMY/PEOPLE/ROSE/CAKE/ARKM) → bot akan menemukan kandidat.
- Scanner interval 5 menit; watcher 20s; PnL 60s.
- CATATAN: min_confidence default 75 belum ada kontrol UI di asi-bot.tsx
  (state ada, ParamRow belum) — kandidat fitur berikutnya jika user minta.


## v9.7.4 — START/STOP Bot + UX ASI-Bot (Okt 2026)
- Tombol besar ▶ START BOT / ■ STOP BOT menggantikan Switch kecil; status
  card menampilkan RUNNING/STOPPED + badge FULL-AUTO.
- Mandatory Disclaimer box hanya tampil saat bot NONAKTIF; hilang saat ACTIVE
  dan posisinya digantikan Recent Trades (permintaan user).
- Recent Trades selalu tampil: empty-state saat belum ada trade; setiap baris
  menampilkan badge OPEN/CLOSED, side, simbol, PnL $ dan % (dari margin).
- Stop dengan posisi terbuka → dialog 3 opsi: Cancel / Keep Positions
  (SL-TP native tetap jaga di exchange; watcher tetap memantau) /
  Close All & Stop (endpoint baru POST /asi/trades/close-all).
- BUG FIX saveBot: stale-closure bisa menimpa enabled=true kembali false
  saat tap beruntun → diganti functional setState. Ini kemungkinan penyebab
  "bot tidak jalan" meski user sudah mengaktifkan.
- PENTING: environment dev/preview vs produksi TERPISAH (DB & egress IP
  berbeda). Bot user berjalan di produksi; test di container ini tidak
  menyentuh akun produksi.
- Perlu NEW BUILD 9.7.4 karena perubahan frontend.


## v9.7.5 — Copy Trade: PnL $ + % (Okt 2026)
- live_leaderboard kini menghitung unrealized_pct per trader:
  sum(pnl)/sum(margin)*100, fallback margin dari notional/leverage untuk
  record lama tanpa margin_usdt. Terverifikasi $2.5/$10 = 25.0%.
- Urutan tetap PnL tertinggi dulu (sort unrealized_usdt desc).
- Handle trader tetap dianonimkan ("MNT***") — keputusan privasi &
  kepatuhan Play Store; JANGAN pernah tampilkan identitas/API credential
  user lain di leaderboard.

## v9.7.6 — Independent Semi/Full State & Manual Close (Okt 2026)
- State Semi-Auto dan Full-Auto dipisahkan (`semi_enabled` dan `full_enabled`).
- Scheduler Full-Auto hanya berjalan jika `full_enabled=True`.
- Endpoint `POST /api/asi/trades/{symbol}/close` untuk menutup posisi manual via UI.
- UI Recent Trades: Badge "SEMI" / "FULL" per trade + tombol merah "CLOSE" untuk posisi OPEN.

## v9.7.7 — Single-Card Mode Swapping & Semi-Auto Pick Signal (Okt 2026)
- Desain box atas: 1 card dinamis yang berganti mengikuti mode chip (Semi = hijau, Full = oranye).
- Semi-Auto: Mode READY tanpa STOP, tombol tunggal "🎯 PICK A SIGNAL" yang otomatis memindai AI Suggestions sesuai Trader Profile aktif dan membuka konfirmasi 1-tap.
- Cek duplikat posisi (pyramid alert) sebelum mengeksekusi trade baru pada simbol yang sama.
- Copy Trade Leaderboard: Menampilkan hanya posisi profit (hijau), diurutkan berdasarkan Unrealized PnL % tertinggi (font 20px).
- Disclaimer acknowledgement disimpan permanen di database config backend (`disclaimer_ack: true`).
- Fix bug Phantom Close pada `engine.refresh_trade_pnl`.

## v9.7.8 — AI Suggestions Direct Execution Polish (Okt 2026)
- Tombol eksekusi Semi-Auto di kartu AI Suggestions ("⚡ EXECUTE SEMI-AUTO") dengan badge pink SEMI.
- Konfirmasi sukses kini menyediakan opsi langsung "Lihat Recent Trades" → navigasi ke `/asi-bot`.

## v9.9.11 — Bump versi + Tutup celah -4130 di jalur layering

Bump ke 9.9.11 (version.ts + app.json + APP_LATEST_VERSION backend).
Release notes popup diperbarui dengan butir stabilitas terbaru.
Fix tambahan: jalur layering kini juga membersihkan conditional LEGACY
sebelum rebalance bracket (sebelumnya hanya algo) — mencegah -4130 saat
menambah layer pada posisi yang punya SL/TP manual dari app Binance.

Dengan ini -4130 tertutup di SEMUA jalur: entry baru (flat → bersihkan
basi), SL retry (cancel+retry), layering (cancel algo+legacy), CLOSE
manual, dan emergency rollback.

## v9.9.10 (patch) — Sticky Execute Button + Fix -4130 Re-Entry + Panel Rollback Netral

**Masalah 1:** Tombol EXECUTE di trade sheet tidak terlihat saat sheet
dibuka (terdorong keluar viewport karena konten panjang); baru muncul
setelah user tap chip TP.
**Fix:** tombol EXECUTE dipindah ke STICKY FOOTER di luar area scroll —
selalu terlihat di bagian bawah sheet berapa pun panjang konten. Setelah
sukses tetap berubah "✅ EXECUTED" terkunci.

**Masalah 2:** Execute ETH kena -4130 ("an open stop order with
closePosition is existing") — ada bracket BASI dari posisi lama yang
sudah tertutup, sehingga SL closePosition baru ditolak dan engine
melakukan rollback (panel error merah).
**Fix (engine):**
- Saat posisi flat, SEMUA bracket basi (algo + legacy) dibersihkan
  SEBELUM entry baru.
- -4130 saat pasang SL → paksa bersihkan algo+legacy lalu retry.
- cancel_all_legacy juga dipanggil pada emergency close & tombol CLOSE
  manual (mencegah order yatim menembak posisi lain nanti).
- Panel rollback bersih (uang tidak berkurang) kini tampil INFO netral
  emas "Entry Dibatalkan — Saldo Aman", bukan alarm merah; hanya
  rollback-gagal-tutup yang tetap merah 🚨. Margin mismatch juga info.
**E2E PASS:** ATOM entry1 → close → entry2 tanpa -4130, bracket hard.

## v9.9.10 — Bump versi (rilis kumulatif v9.9.2–v9.9.10)

Nomor versi dinaikkan ke 9.9.10 (version.ts + app.json + APP_LATEST_VERSION
backend, sehingga popup update muncul untuk semua build lama). Mengemas:
verifikasi SL/TP native berlapis + auto-rollback, layering auto-rebalance,
dual-slot API key, badge DEMO + PnL terpisah, leaderboard 25 demo+real,
layout Recent Trades (CLOSE baris 2, toggle 10→20, margin USDT, detail
closed lengkap, "Closed on {exchange}"), 2 chip jaringan DEMO/REAL di
trade sheet, saldo demo+real live, fix false-positive SL/TP (-4130) +
konsolidasi row duplikat, popup update dengan release notes terlokalisasi.

## v9.9.9 (patch 10) — Margin USDT di Setiap Baris Open/Closed

User: setiap posisi open/closed di Recent Trades wajib menampilkan besaran
margin USDT. Implementasi: baris detail (open & closed) diawali
`Margin $XX.XX` (emas tebal), memakai `margin_usdt` tersimpan dengan
fallback hitung `entry*qty/leverage` untuk trade lama. Screenshot-verified
(Margin $39.32 pada history ETH). Lint pass. Tetap v9.9.9.

## v9.9.9 (patch 9) — FIX False-Positive "Tanpa SL/TP" + Error -4130 + Row Duplikat

**Temuan dari screenshot user (kritis):**
1. Posisi XRP/BCH demo user SEBENARNYA terproteksi — SL & TP algo ada di
   Binance (diverifikasi langsung: XRP SL 1.5155 + 3 TP, BCH SL 318.17 +
   2 TP), tapi UI menandai "tanpa SL/TP / soft watcher".
2. Repair gagal -4130 "closePosition order is existing" karena mencoba
   memasang SL kedua padahal sudah ada.
3. Dua row XRP SHORT identik (warisan kode pra-v9.9.4 layering).

**Root cause:** verifikasi hanya mencocokkan `sl_order_id` tersimpan vs
openAlgoOrders. Bila ID basi/tidak cocok (trade dari kode lama, layering,
atau SL/TP dipasang manual user di app Binance), posisi terproteksi salah
ditandai tanpa proteksi.

**Fix (engine + scheduler):**
- `_refresh_binance`: verifikasi berlapis — (1) ID cocok, (2) karakteristik
  algo (ada STOP_MARKET closePosition searah = SL armed; TAKE_PROFIT_MARKET
  searah = TP armed), (3) legacy openOrders. Terverifikasi → bracket_type
  otomatis "hard", label soft dihapus.
- `attach_brackets`: cek proteksi existing (algo + legacy) SEBELUM pasang;
  bila sudah ada → ok=True dengan note, TIDAK membatalkan/mengganggu order
  yang ada. -4130 kini diverifikasi & dianggap armed, bukan error.
  cancel_all_algo hanya dijalankan bila memang akan memasang SL baru.
- Scheduler `_refresh_open_pnl`: auto-konsolidasi row open duplikat
  (device+simbol+exchange+jaringan sama) → row lama status "layered".
- Frontend: ⚠️ & banner repair hanya muncul bila bracket_live === false
  atau soft yang belum terverifikasi — bukan lagi berdasar sl_order_id null.

**E2E testnet PASS:** repair XRP dengan SL+TP existing → ok=True, notes
"sudah terpasang", 0 errors, 4 order tidak tersentuh. Posisi demo user
(XRP short -2565.3) sempat tereduksi 30 XRP oleh order tes — sudah
dikembalikan persis.

## v9.9.9 (patch 8) — Kotak Angka Mengikuti Chip Jaringan (Demo/Real)

User: bila chip DEMO dipilih, kotak bawah (USDT Balance, Margin Used,
Position Size, Est. Loss, TP profit) harus menampilkan angka akun DEMO;
chip REAL → angka akun REAL.

Implementasi AsiTradeSheet:
- Ganti chip → `setPreview(null)` SEGERA (angka jaringan lama tidak
  sempat tampil menyesatkan) → effect refetch preview dengan
  `testnet` jaringan baru (sudah ada di payload sejak v9.9.5).
- Label baris balance kini eksplisit: "USDT Balance · DEMO/REAL".
- Penolakan HTTP backend (e.code/e.detail, mis. jaringan belum terhubung)
  kini MENIMPA preview (bukan keep last-good) sehingga keadaan jaringan
  baru selalu akurat; hanya exception jaringan murni (timeout) yang
  keep last-good (anti-flicker stepper v9.9.6 tetap berlaku).
- Box tidak lagi berkedip "calculating" saat tap stepper: angka lama
  tetap tampil selama refetch (hanya tampil calculating saat belum
  ada data sama sekali).

Lint pass. Tetap v9.9.9.

## v9.9.9 (patch 7) — Trade Sheet: 2 Chip Jaringan DEMO/REAL Sebelum Execute

User: di trade sheet (setelah pilih aset → EXECUTE), user harus bisa
langsung pilih Demo (Testnet) atau Real (Mainnet) sebelum eksekusi; chip
ganda BINANCE·🧪 (legacy doc + slot v9.9.5 sama-sama muncul) dihilangkan.

Implementasi AsiTradeSheet:
- Exchange picker diganti menjadi TEPAT 2 chip besar: **DEMO (Testnet)**
  biru dan **REAL (Mainnet)** hijau. Tap → langsung mengganti jaringan
  aktif untuk preview & execute DAN menyimpan `active_testnet` ke bot
  config (konsisten dengan switch di halaman ASI-Bot & Full-Auto).
- Jaringan tanpa credential tampil redup + label "Not connected"; memilih
  jaringan tsb menampilkan empty-state hubungkan API (bukan gagal sunyi).
- `activeCred` dibuat STRICT per jaringan (tanpa fallback silang) sehingga
  preview/execute tidak pernah diam-diam memakai key jaringan lain.
- Backend sudah mendukung: TradePayload.testnet → resolve_credential
  per-network (v9.9.5).

Lint pass. Tetap v9.9.9.

## v9.9.9 (patch 6) — Popup Update dengan Release Notes Terlokalisasi

APP_LATEST_VERSION backend 9.3.0 → 9.9.9. Endpoint /app-version kini
mengembalikan `notes` per bahasa (id/en). UpdatePrompt menampilkan release
notes dalam bahasa user + seluruh teks popup dilokalisasi (update_title/
body/now/later — 4 bahasa). Popup muncul otomatis di cold start untuk
build yang lebih tua dari 9.9.9 dan mengarah ke Play Store.

## v9.9.9 (patch 5) — Dua Kartu Saldo: DEMO di atas, REAL di bawah

User: kotak DEMO Available Balance diletakkan di atas kotak REAL Available
Balance. Endpoint /asi/balance diubah mengembalikan KEDUA jaringan
sekaligus (asyncio.gather paralel): {demo: {connected, available_usdt},
real: {...}}. Frontend menampilkan 2 kartu berurutan: DEMO (chip biru)
lalu REAL (chip hijau); jaringan tanpa credential menampilkan
"Not connected →". Screenshot-verified: DEMO $3,656.96 di atas, REAL
Not connected di bawah. Lint pass. Tetap v9.9.9.

## v9.9.9 (patch 4) — Baris 3 closed disederhanakan: hanya "Closed on {Exchange}"

User: tulisan "Closed @" di baris ketiga dihilangkan, cukup "Closed on
(exchange)", jangan dobel. Implementasi: baris 3 closed kini
`Closed on Binance · <ALASAN>` (alasan hanya bila ada). Screenshot-verified.

## v9.9.9 (patch 3) — Saldo Available Realtime + "Closed on {Exchange}"

1. Kartu **Saldo Tersedia** di atas Recent Trades: endpoint baru
   `GET /api/asi/balance` membaca available USDT langsung dari exchange
   untuk jaringan AKTIF (active_testnet config → resolve_credential).
   Chip DEMO/REAL menandai jaringan. Di-refresh bersama siklus PnL
   (interval bot + pull-to-refresh). Perbaikan bonus: resolve_credential
   kini fallback ke slot v9.9.5 mana pun bila device baru tidak punya
   legacy doc (sebelumnya balance execute bisa gagal menemukan key).
2. Baris ketiga trade closed kini: `Closed @ <harga> · <ALASAN> · Closed
   on Binance/Bybit/OKX/Bitget` sesuai exchange trade tsb.

Verified: endpoint mengembalikan saldo testnet asli ($3,656.96);
screenshot menampilkan kartu saldo DEMO + baris "Closed on Binance".
Lint pass. Tetap v9.9.9.

## v9.9.9 (patch 2) — History Closed Menampilkan Detail Lengkap + Closed Price

User: trade CLOSED di Recent Trades harus menampilkan detail lengkap
sama seperti posisi open: Entry Price, SL, TP1/2/3, Leverage, Close
Price, dan PnL.

**Backend:** field `closed_price` kini direkam saat posisi tertutup —
refresh Binance mengambil fill terakhir via `last_fill_price()`
(/fapi/v1/userTrades); soft-close watcher menyalin `exit_price` →
`closed_price`; close manual & close-all ikut menyimpan. Trade legacy
tanpa closed_price menampilkan "—".

**Frontend:** baris detail yang sebelumnya hanya untuk posisi OPEN kini
juga dirender untuk CLOSED: chip DEMO/REAL + Entry · SL · TP1/2/3 ·
ISOLATED/CROSS · leverage hijau + baris "Closed @ <harga> · <alasan
TP/SL/MANUAL>". PnL tetap di kanan atas ($ besar + %).

Screenshot-verified: SOL DEMO closed menampilkan Entry 118.50 · SL 115.00
· TP 121.00/123.50/126.00 · ISOLATED 20x · Closed @ 121.00 · TP · +$5.00
(+42.2%). ARB REAL cross tampil setara. Lint pass. Tetap v9.9.9.

## v9.9.9 (patch) — Copy Trade: EXECUTE Fungsional + Detail Lengkap + Bersih Mock

**Masalah 1:** Tombol EXECUTE di leaderboard tidak bisa diklik — memang
masih placeholder (hardcoded disabled sejak awal).
**Fix:** EXECUTE kini fungsional → fetch harga pasar SAAT INI via endpoint
baru `GET /api/asi/price?symbol=` (public ticker Binance via proxy SG),
lalu membuka AsiTradeSheet dengan intent posisi trader (symbol, side,
entry=harga kini, SL/TP trader). Fallback ke entry trader bila ticker
gagal. Spinner saat menyiapkan.

**Masalah 2:** Pill "2 OPEN POS" tapi kartu hanya tampilkan 1 posisi.
**Penjelasan:** pill menghitung TOTAL posisi terbuka trader; kartu
menampilkan posisi terbaru. Ditambah baris "+N posisi lain masih terbuka"
(i18n 4 bahasa) bila open_count > 1 supaya tidak membingungkan.
Rank #1/#2 sebelumnya adalah data MOCK/seed lama (BTC @50k, SL 10k,
TP 999999, umur 258-273 hari) — sudah dibersihkan dari DB preview
(4 row seed dihapus; trade testnet layout-test juga ditutup bersih).

**Masalah 3 (permintaan):** Leaderboard wajib menampilkan lengkap Entry,
SL, TP, Leverage, running PnL untuk semua rank 1-25.
**Fix:** kartu kini menampilkan baris SL (merah) + TP (hijau) di bawah
entry; leverage di chip LONG/SHORT; running PnL (% besar + $) tetap di
kanan. Subtitle diperbarui Top 10 → Top 25.

Lint pass. Screenshot-verified: #1 ABB DEMO menampilkan Entry $2,692.99,
SL 2,612.05, TP 2,719.76/2,746.69, LONG 10x, +5.29% / +$2.08, EXECUTE aktif.
Tetap versi 9.9.9 (tidak bump — mengikuti kontrol versi user).

## v9.9.9 — Bump versi (mengemas patch v9.9.8: repair senyap, CLOSE baris 2, history 10/20 + toggle)

Tidak ada perubahan fungsional — nomor versi dinaikkan ke 9.9.9
(version.ts + app.json) untuk rilis yang mengemas tiga patch v9.9.8:
repair bracket senyap, tombol CLOSE di baris 2, dan history Recent
Trades persisten dengan toggle 10→20.

## v9.9.8 (patch 3, tanpa bump) — History Recent Trades Persisten + Toggle 10/20

User: (1) trade closed (demo maupun real) TIDAK boleh hilang dari Recent
Trades — history harus tetap terlihat; (2) daftar tampilkan 10 trade,
bisa expand hingga max 20 via toggle di sisi kanan + scroll ke bawah.

Implementasi:
- Backend memang tidak pernah menghapus trade (status closed tetap di DB)
  — dikonfirmasi & dipertahankan; row "layered" (gabungan averaging) juga
  tetap tampil sebagai history.
- api.listTrades kini menerima limit (default 20) — frontend fetch 20.
- Header "Recent Trades" punya toggle chevron di kanan (muncul hanya bila
  >10 trade) menampilkan jumlah total; tap → expand ke max 20 dalam
  ScrollView bersarang (maxHeight 520, nestedScrollEnabled) yang bisa
  di-scroll ke bawah; tap lagi → kembali ke 10.
- Screenshot-verified dengan 13 trade (1 open + 12 dummy closed):
  collapsed 10 baris + badge "13 ⌄"; expanded menampilkan baris ke-13
  (ATOM) via scroll; toggle kembali "10 ⌃". Dummy dihapus setelah tes.

## v9.9.8 (patch 2, tanpa bump) — Tombol CLOSE pindah ke baris 2

User: CLOSE dipindah ke baris kedua persis di bawah angka PnL (paling
kanan, wajib di dalam frame). Implementasi: CLOSE dikeluarkan dari row 1
(hanya badges + SIDE + SYMBOL + PnL) dan ditempatkan di ujung kanan row 2
(sejajar dengan chip DEMO/REAL + SL/TP/margin/leverage), flexShrink:0,
minWidth 60. Screenshot-verified dengan trade demo ETH: CLOSE tepat di
bawah PnL, tidak keluar bingkai.

## v9.9.8 (patch, tanpa bump) — Repair Bracket Senyap untuk Kasus Tidak Berisiko

User: popup "Bracket Repair" menampilkan error mentah (-2021 dst) untuk
eksekusi yang tidak merugikan uang — tidak perlu ditampilkan apa pun.

**Backend `attach_brackets`:**
- Posisi sudah tertutup di exchange → BUKAN kegagalan: ok=True, trade
  ditandai closed (close_reason=position_closed_externally) agar berhenti
  muncul di banner repair.
- SL kena -2021 (level sudah terlewati = harga sudah di zona rugi) → bot
  langsung market-close posisi (persis yang akan dilakukan SL), trade
  ditandai closed (close_reason=sl_level_passed). ok=True.
- TP kena -2021 (harga sudah profit melewati target) → TP itu di-skip
  diam-diam, dicatat di `notes`, TIDAK dihitung kegagalan. Posisi tetap
  terlindungi SL + TP lain.

**Frontend banner repair:** popup HANYA muncul bila ada kegagalan nyata
(posisi masih terbuka & bracket tetap gagal = uang berisiko). Semua hasil
benign diproses senyap + refresh. Popup sukses juga dihapus.

## v9.9.8 — Leaderboard Copy Trade: DEMO + REAL dengan Badge (maks 25)

User: 2 posisi demo yang profit tidak tampil di leaderboard (kosong) karena
v9.9.5 mengecualikan testnet. Keputusan user: DEMO & REAL sama-sama tampil
(strategi bot identik, hanya beda uang asli/non-asli), trader demo BOLEH
di-copy nantinya.

**Perubahan:**
- `pnl.live_leaderboard` & `pnl.leaderboard`: filter `testnet != True`
  DIHAPUS; group diubah per (device, testnet) supaya entry demo & real
  trader yang sama tampil terpisah. Field `testnet` ditambahkan ke response.
- Limit leaderboard 10 → **25** (live & periode). Sorting tetap PnL %
  terbesar; nilai kecil tergeser keluar dari 25 list.
- `copy-trade.tsx`: badge kecil **DEMO (biru) / REAL (hijau)** di samping
  handle trader.
- `pnl_summary` TETAP memisah PnL real vs demo (permintaan sebelumnya
  tidak berubah); daily loss limit & kuota harian tetap per-jaringan.
- Catatan: DB preview punya 1 row seed lama (BTC @50k, TP 999999) yang kini
  tampil sebagai rank #1 demo — hanya ada di DB preview, bukan produksi.

Verified curl: /leaderboard/live menampilkan entry testnet:true (demo) dan
testnet:false (real). Lint pass. Versi 9.9.8.

## v9.9.7 — Rapikan Layout Recent Trades (user screenshot review)

Permintaan user (5 poin): (1) konten baris tidak keluar kotak, (2) badge
ISO di baris atas DIHAPUS — leverage pindah ke baris 2 dengan warna hijau
tebal (mis. 50x/100x) agar terbaca, (3) badge DEMO biru pindah ke baris 2,
(4) susunan demo & real IDENTIK & sejajar, (5) tombol CLOSE tidak keluar
bingkai.

Implementasi: Row 1 dirampingkan → [SEMI/FULL][Layer×n][ACTIVE/CLOSED]
SIDE SYMBOL … PnL [CLOSE] dengan flexWrap + flexShrink:0 pada PnL/CLOSE
(symbol flexShrink:1 + numberOfLines=1). Row 2 → chip [DEMO biru / REAL
hijau] (slot SELALU ada → susunan identik) + SL merah · TP hijau ·
ISOLATED/CROSS · **10x hijau tebal**. Row 3 status native tak berubah.
Verified screenshot dengan trade demo ETH sungguhan (testnet): baris rapi,
tidak overflow, DEMO di baris 2, leverage hijau. Versi 9.9.7.

## v9.9.6 — Fix Flicker Tombol Execute di Trade Sheet

User report: setelah pilih sinyal & klik EXECUTE SEMI-AUTO, tombol execute
di trade sheet "hilang lalu muncul lalu hilang lagi"; tombol hijau Execute
juga "kadang nyala kadang hilang" saat tap stepper leverage.

Root cause (2 sumber):
1. Flash empty-state: `creds` masih kosong sesaat saat sheet dibuka →
   empty-state "hubungkan exchange" ter-render (menggantikan seluruh konten
   termasuk tombol) → credential termuat → konten muncul.
   FIX: flag `credsLoaded`; empty-state hanya dirender SETELAH fetch
   credential selesai dan memang kosong untuk network aktif. Selama load
   menampilkan "calculating" netral.
2. Flicker hijau↔abu: tiap tap stepper risk/leverage memicu refetch
   preview via proxy Binance; bila fetch melempar exception jaringan,
   preview ditimpa ok:false → tombol disabled (abu). Fetch berikutnya
   sukses → hijau lagi.
   FIX: exception jaringan TIDAK lagi menimpa preview bagus terakhir
   (keep last-good); hanya penolakan backend (ok:false + reason, mis.
   min_notional) yang mengubah state tombol. Eksekusi tetap divalidasi
   ulang server-side sehingga aman.
Bonus: chip exchange kini menyorot slot network aktif saja dan label
jaringan memakai emoji 🧪/🔴 (bukan ·T).

Lint pass. Versi 9.9.6 (version.ts + app.json).

## v9.9.5 — Dual-Slot Credential (Mainnet+Testnet) + Badge DEMO & PnL Terpisah

**Masalah 1:** User simpan API key mainnet, lalu simpan testnet → mainnet
tertimpa; harus input ulang tiap ganti jaringan.
**Fix:** Credential disimpan di slot terpisah per jaringan
(`_id = device:exchange:mainnet|testnet`). Helper `resolve_credential()`
di engine dengan lazy-migration legacy doc (device:exchange tanpa suffix
→ otomatis disalin ke slot saat pertama dipakai). Network aktif disimpan
di bot config (`active_testnet`) dan diubah via switch 🧪/🔴 baru di
halaman ASI-Bot. TradePayload menerima `testnet` opsional (None → ikut
config). Preview/execute/close/repair/refresh/scheduler (scanner, watcher,
PnL) semuanya resolve per-network. Setelah simpan key suatu jaringan,
jaringan itu otomatis jadi aktif. Kuota harian Full-Auto dihitung per
jaringan; daily loss limit hanya real.
UI: baris exchange menampilkan status KEDUA slot (🧪✓/— 🔴✓/—) + mask
key slot aktif; AsiTradeSheet memakai credential network aktif dan
menolak preview bila slot network itu belum terhubung.

**Masalah 2:** User bingung membedakan posisi demo vs real; PnL demo
tidak boleh mengurangi PnL real.
**Fix:** pnl_summary kini hanya menghitung trade `testnet != true`
untuk daily/weekly/monthly + key `demo` terpisah. Leaderboard &
live leaderboard & WR-30d & daily-loss-limit hanya real. Recent Trades
menampilkan badge biru **DEMO** pada trade testnet + baris kecil
"Demo (Testnet): ±$x dari n trade — tidak masuk PnL real" di bawah
kartu PnL. i18n 4 bahasa (asi_demo_badge, asi_pnl_demo,
asi_net_other_only). Versi 9.9.5 (version.ts + app.json).

Verified curl: simpan testnet → simpan mainnet invalid ditolak TANPA
menimpa slot testnet; preview testnet resolve slot benar ($4355); preview
mainnet tanpa slot → 404 jelas; pnl mengembalikan key demo.

## v9.9.4 — Smart Layering (Averaging) + Auto-Rebalance Brackets

User request: trader profesional menambah muatan (layering/DCA) beberapa kali
saat posisi berlawanan arah sementara, supaya average entry & liquidation
price bergeser. Binance one-way mode menggabungkan posisi menjadi 1 dengan
average entry — bot harus mengikuti perilaku itu.

**Implementasi (Binance path di engine.execute_trade):**
- Deteksi posisi existing searah → `layered=True`. Eksekusi market layer baru.
- Setelah fill, baca positionRisk: qty gabungan + average entry aktual.
- **Auto-rebalance**: cancel semua algo lama → pasang SL (closePosition) +
  TP split untuk TOTAL posisi gabungan, trigger dari sinyal terbaru.
  Diverifikasi via openAlgoOrders seperti biasa (rollback bila gagal).
- Guard arah berlawanan: SELL pada posisi LONG aktif → DITOLAK
  (reason=opposite_position) karena akan mengurangi posisi tanpa disadari.
- routes.execute: row trade lama simbol sama ditandai `status="layered"`
  (close_reason=merged_into_layer, merged_into=<id baru>) agar tidak
  dihitung ganda di PnL/leaderboard; row baru mendapat `layer_count`.
- close_position Binance: baca qty LIVE dari positionRisk sebelum market
  close (qty row lama bisa lebih kecil dari posisi gabungan).
- UI: dialog duplikat AsiTradeSheet diubah menjadi penjelasan averaging +
  auto-rebalance; panel sukses menampilkan catatan layer; Recent Trades
  menampilkan badge "Layer ×n".

**E2E Testnet PASS:** layer1 ETH 0.16 → layer2 0.319 gabungan avg 2719.14,
SL lama cancelled, SL+3TP baru live untuk full qty, TP qty total == posisi,
opposite-side ditolak. Versi 9.9.4 (version.ts + app.json).

## v9.9.3 — Leverage AKTUAL (user temukan 50x request → 20x real di Binance)

User buka SOL long 103.8 SOL @121.06 via app (request leverage 50x), tapi
Binance menampilkan posisi 20x. Root cause: set_leverage best-effort — Binance
menolak 50x karena tier notional (~$12.5k melebihi bracket 50x SOL), engine
melanjutkan tanpa memberitahu, UI menampilkan angka request palsu.

FIX (backend): execute_trade kini membaca `leverage` AKTUAL dari positionRisk
setelah entry → disimpan sebagai `actual_leverage` + `leverage_note` (bila
berbeda dari request). refresh_trade_pnl & attach_brackets ikut memperbarui
field itu tiap siklus. Frontend Recent Trades menampilkan actual_leverage.

KLARIFIKASI PENTING (dijawab ke user): TP1/TP2 TIDAK tampil di kolom
"TP/SL for position" Binance karena kolom itu khusus order closePosition=true
(SL kami). TP parsial dengan quantity (split 50/50) muncul di tab
**Open Orders → Conditional/Algo**. Screenshot user menunjukkan
"Open Orders(3)" = cocok dengan SL + TP1 + TP2 — kemungkinan besar
proteksi lengkap. User diminta memverifikasi tab tersebut.

## v9.9.2 — Fix Kritis: SL/TP Native yang BENAR + Auto-Rollback (Jun 2026)

**Masalah user (sangat kritis):** UI ASI-Bot menyatakan SL/TP terpasang native
di Binance, padahal di Binance posisi SEBENARNYA tidak punya SL/TP. Posisi
Cross tidak bisa diubah ke Isolated setelah entry.

**Root cause ditemukan:**
1. `CCXT.set_margin_mode()` dibungkus `except: pass` → kegagalan set margin
   mode DIAM-DIAM diabaikan, UI klaim "ISOLATED" padahal Binance Cross.
2. Response algo order dari Binance tidak diverifikasi dengan
   `GET /openAlgoOrders` — hanya mengandalkan response POST yang bisa
   lolos tanpa benar-benar membuat order di buku.
3. CCXT path menelan error exchange, engine kehilangan visibilitas.

**Perbaikan v9.9.2:**
- Modul baru `/app/backend/asi_bot/binance_rest.py` — direct signed REST
  (HMAC-SHA256) untuk account, positionRisk, leverage, marginType, market
  order, algo order, openAlgoOrders, cancel. Semua lewat proxy Singapore.
- `engine.execute_trade` ditulis ulang khusus Binance path:
  1. Baca positionRisk real → jika posisi exist dengan margin mode berbeda
     dari request user → **ABORT entry** (reason=`margin_mode_mismatch`).
  2. Set margin type via REST signed (bukan CCXT) + handle -4046 (no change).
     Jika gagal → ABORT (reason=`margin_mode_set_failed`).
  3. Entry MARKET → poll positionRisk 10×0.3s sampai positionAmt > 0.
  4. SL placement dengan retry 3× → VERIFY via openAlgoOrders list.
  5. TP placement per-leg dengan retry 3× → VERIFY juga.
  6. Jika SL atau TP (verified) < expected → **AUTO-ROLLBACK**:
     cancel semua algo + MARKET close reduceOnly → trade TIDAK disimpan.
     Return `{ok:false, reason, message, rollback_done:true}`.
  7. Hanya trade yang SL+TP full-verified yang disimpan sebagai
     `bracket_type="hard"`, `bracket_verified_at=<ts>`,
     `actual_margin_mode=<binance real>`.
- `engine.attach_brackets` (repair) juga memverifikasi via openAlgoOrders;
  hanya tulis `hard` ke DB bila SL+TP benar-benar live.
- `engine.refresh_trade_pnl` untuk Binance pakai REST langsung:
  menyimpan `actual_margin_mode` live + `bracket_live` boolean
  (true=algo masih tersisa di exchange, false=user cancel manual).
- Routes `trades/execute` propagasi `code/message/rollback_done` sebagai
  JSON detail ke frontend (bukan string generik).
- Frontend `AsiTradeSheet.tsx` menampilkan dialog kontekstual:
  - "Entry Dibatalkan — SL/TP Gagal" (rollback bersih)
  - "Margin Mode Tidak Cocok" (mismatch posisi lama)
  - "🚨 PERLU TINDAKAN MANUAL" (rollback gagal — perlu close manual)
- Frontend `asi-bot.tsx` Recent Trades:
  - Badge margin mode pakai `actual_margin_mode` (bukan request).
  - "✓ Native SL/TP armed" hanya hijau bila `bracket_type=hard`
    DAN `bracket_live !== false`.
- Scheduler Full-Auto sudah meneruskan `margin_mode` ke engine (v9.9.0),
  sekarang juga akan mendapat verifikasi + rollback yang sama otomatis.

**Verifikasi E2E Testnet (Binance Futures Testnet, user-provided keys):**
- ✓ Happy path (ETH BUY ISO): SL + 3 TP terverifikasi di openAlgoOrders.
  Response: `bracket_type=hard`, `actual_margin_mode=isolated`.
- ✓ Margin mismatch: posisi SOL Cross aktif → request Isolated DITOLAK
  dengan pesan jelas, posisi lama tidak terganggu.
- ✓ Cross mode entry: `actual_margin_mode=cross` tersimpan apa adanya.
- ✓ Rollback: SL ditolak (-2021 immediate trigger) → setelah 3× retry,
  posisi otomatis ditutup, 0 algo order sisa, trade tidak disimpan,
  user dapat pesan "balance Anda aman — silakan coba lagi".

**Version:** 9.9.1 → 9.9.2 (version.ts + app.json).

**CATATAN KE USER:** v9.9.2 masih perlu Anda verifikasi langsung di akun
Binance Anda setelah rebuild APK — testnet mengkonfirmasi behavior, tapi
akun mainnet Anda mungkin punya posisi warisan v9.9.1 yang perlu dirapihkan
manual sekali. Setelah itu semua trade baru akan 100% hard-bracket atau
tidak dieksekusi sama sekali (no more silent fake SL/TP).

## v9.9.1 — (dilewati — digabung ke 9.9.2)

## v9.7.9 — Trader Profile Modal Fixes & Admin Code Unification (Okt 2026)
- TraderProfileModal tidak lagi auto-close setelah memilih profil, sehingga user bisa langsung menekan tombol "AI SUGGESTIONS".
- Profil Long-Term & default Confluence kini dapat membuka AI Suggestions (popup "Select a profile first" dihapus total).
- Sinkronisasi verifikasi unlock code antara Preview dan Production host (`https://cryptostock-pro.emergent.host`).
- Penyederhanaan otentikasi admin code generator.


## v9.9.12–v9.9.13 — Fix akar "close di +0.4" + Entry LIMIT Deep (Okt 2026)

**Root cause (bukti DB + audit live):** sinyal memakai entry DEEP (offset
0.6–1.0 ATR) tapi bot eksekusi MARKET → TP1 nempel/salah sisi vs harga fill
(bukti live: HYPE SELL TP1 +0.053% vs harga; TIA BUY TP1 −0.763% vs harga).
TP1 kena instan (⅓ posisi, profit kecil), sisa ⅔ mati di SL jauh → rugi
berulang di SEMUA profil. Ditambah: soft watcher menutup 100% posisi di TP
pertama, dan layering mewarisi TP salah sisi (ETH TP1 2714.47 < avg entry
2714.48 untuk BUY → close instan −0.44).

**Perbaikan:**
- Engine anchor-to-fill + TP guard (buang TP salah-sisi/nempel < max(0.25%
  entry, 0.2×risk); sintesis 1.5R bila semua gugur). Field `anchor_shift`.
- indicators._floor_tp_ladder: TP1 min max(0.25% entry, 0.5×ATR) — dipasang
  di VWAP levels, deep levels (crypto+stocklike), Pattern Scalp 15M.
- Soft watcher SPLIT TP per bobot (TP1 ⅓, TP2 ⅓, TP3 sisa), tracking
  tp_filled/qty_remaining/soft_realized_pnl, close_reason TP1/TP2/TP3.
- **KEPUTUSAN USER: entry LIMIT Deep (bukan market), expire 1 candle
  (3600s), Semi & Full-Auto.** engine.execute_trade place LIMIT GTC di
  harga sinyal; fill instan (marketable) → bracket langsung; belum →
  status pending_entry; scheduler._process_pending_entries (20s):
  fill→attach_brackets (layered→rebalance), expired→cancel+status expired,
  attach gagal→close_position (no-unprotected). CLOSE pada pending =
  cancel limit. Badge MENUNGGU + panel "LIMIT ORDER TERPASANG" (4 bahasa).
- Mark price realtime: GET /asi/prices batch (cache 1s); UI poll 2 detik;
  harga live di samping symbol; frame kartu hijau=profit / merah=loss
  (open & closed), emas=pending; PnL $ & % live.

**Testing:** testing_agent iter36: 10/11 PASS (E2E testnet LIMIT pending,
marketable fill, expire, TP guard, regresi). 1 bug accounting soft-watcher
ditemukan → diperbaiki, test PASS. Versi 9.9.13.

## v10.0.4 — Leaderboard Copy Trade: kartu posisi lengkap (open & closed)
- User: posisi CLOSED di leaderboard tetap tampil LENGKAP seperti open
  (symbol, side, entry, SL, TP, PnL realized) — bukan hanya inisial + PnL.
- User: tiap posisi tampil SATU PER SATU dengan PnL masing-masing (tidak
  digabung per aset) → pill penghitung "OPEN POS"/"N× CLOSED" DIHAPUS.
- Backend `pnl.live_leaderboard`: $group juga push `closed_trades`.
- Frontend `copy-trade.tsx`: kartu closed read-only, TANPA tombol EXECUTE.
- Versi 10.0.3 → 10.0.4. Terverifikasi curl data real + screenshot.

## v10.0.5 — Leaderboard: RANK PER POSISI (final, keputusan user)
- **1 rank = 1 POSISI** (open maupun closed 24 jam), PnL TIDAK digabung
  per trader/aset. Trader yang sama bisa muncul di banyak rank.
- Backend `pnl.live_leaderboard`: find open + closed-24h (pnl>0), sort
  pnl_usdt desc, limit 25; tiap row bawa symbol/side/entry/SL/TP/leverage/
  mode/entry_mode/pnl/pnl_pct/closed info + wr30d (cache per device).
- Frontend `copy-trade.tsx`: 1 kartu = 1 posisi; badge seperti Recent
  Trades (🦾 semi / 🤖 full, chip M ungu / L kuning, tanggal-jam entry,
  teks "Closed on SL/TP1..."); PnL $+% di PALING KANAN di atas tombol
  EXECUTE; EXECUTE hanya untuk posisi open.
- Tipe `AsiLiveTrade` dihapus; `AsiLiveRow` = satu posisi. copy_sub
  diperbarui 4 bahasa. Versi 10.0.5 (version.ts, app.json,
  APP_LATEST_VERSION + release notes). Verified curl + screenshot.


## v10.1.1 — Repair Positions/Recent Trades + Lifecycle Accounting + i18n (Okt 2026)
- **Positions**: judul "Running Positions · N" (N=open+pending), strip harian
  "W : L" + "P : L" nominal $ dan % (hijau/merah) yang reset pukul 00:00
  **jam device user** (bukan UTC — keputusan user). Entry putih terang +
  formula sejajar Recent Trades. Badge Demo="D" biru muda, Real="R" oranye.
- **Kartu tapable + swipe-delete hidup berdampingan**: kartu Positions &
  Recent Trades dibungkus TouchableOpacity dari react-native-gesture-handler
  (CardTouchable) — swipe kiri menampilkan DELETE TANPA navigasi; tap biasa
  menuju /asset/crypto/{symbol} (symbol dinormalisasi, strip suffix USDT).
  Tombol CLOSE/CANCEL/⚠️ di dalam kartu juga RNGH touchable (fix temuan
  testing agent: RN-core touchable di dalam RNGH touchable memicu dua
  onPress sekaligus di web).
- **Lifecycle accounting fix (root cause "QNT Closed on TP1 tapi PnL
  -26.88")**: native close path di engine.py dulu menyimpan pnl_usdt =
  unrealized STALE dari refresh terakhir dan closed_price = fill terakhir
  simbol (bisa milik trade lain). Kini br.realized_close_info menjumlahkan
  realizedPnl fills penutup aktual sejak trade dibuka. Label TP HANYA bila
  fill favorable vs entry. Reason baru TRAILING (trailing stop native —
  sebelumnya salah label position_closed_externally). Data historis lama
  TIDAK di-rewrite.
- **"Position_Closed_Externally"** = posisi exchange tertutup di luar jalur
  trade tsb: duplikasi trade simbol sama berbagi 1 posisi Binance (one-way
  mode), bracket trade lain menutup posisi gabungan / user tutup manual di
  app Binance / likuidasi.
- **Analisis loss formula day** (sampel DB preview): day WR 23.8% (-400.58)
  vs scalper 94.4% (+395.16), longterm 66.7%, confluence 55.6%. Sebagian
  besar loss day terkonsentrasi 1 sesi (9-10 Okt, ~12 SHORT serentak saat
  market rally) + bug akuntansi + label profile trade terekam dari config
  user BUKAN engine pemenang (sudah fix: sig.profile). User memutuskan Full
  Auto tetap multi-profile "sinyal terbaik & confidence tinggi" (msg #729).
- **Scanner guards**: skip sinyal entry<=0/SL<=0/tanpa TP (bug trade
  entry_price=0.0: ETH/LINK/SNX); record entry_price=0 tidak disimpan.
- **Warning SL/TP sticky**: menekan ⚠️ kini memicu repairBrackets+refresh
  (bukan hanya popup info); warning auto-hilang saat bracket terverifikasi.
- **i18n**: TraderProfileModal 100% terlokalisasi (judul/subtitle/deskripsi
  4 profil, 4 bahasa — sebelumnya deskripsi hardcode Indonesia); 3 string
  backend Indonesia → English (routes.py). Testing agent: 16/16 check lulus.
- Testing agent iter37: backend 6/6 PASS; frontend PASS kecuali bug nested
  touchable (diperbaiki, self-test ulang PASS: CLOSE/CANCEL tanpa navigasi,
  dialog tetap muncul, tap kartu navigasi, swipe-delete tanpa navigasi).
- Versi TETAP 10.1.1 (tidak bump, sesuai instruksi user).

## v10.1.2 — SL 1.2×ATR + Label Bersih (Keputusan User, Okt 2026)
- **SL multiplier 0.5×ATR → 1.2×ATR** (semua profil, keputusan user Opsi A):
  akar masalah SL terlalu dekat (BNB $1/0.12%, XRP 0.18%) adalah ATR 1H
  mengecil saat konsolidasi; 1.2×ATR memberi jarak wajar (BNB kini ~0.60%).
  Ladder TP dalam kelipatan R menyesuaikan otomatis.
- **Baris parsial posisi OPEN hanya menampilkan ✓ TP HIT** (keputusan user):
  catatan parsial berlabel SL (fill adverse/slippage) disembunyikan di
  Positions & Recent Trades agar posisi profit tidak tampak kena SL.
- **Reason baru BREAK_EVEN**: harga tutup ≈ entry (±0.2%) tanpa menyentuh
  SL/TP → "Closed on Break-Even" (bukan "Closed on exchange"). Kasus ORDI.
- **Label formula Confluence**: _asi_formula_tag fallback kini mengembalikan
  "Confluence v9" (longterm) / "Confluence" (default) — trade seperti WIF
  tidak lagi tampil tanpa nama formula.
- Penjelasan ARB BRACKET_FAILED_AFTER_FILL: Binance menolak bracket setelah
  entry fill → emergency rollback menutup posisi di $0.00 demi keamanan.
- Versi di-bump 10.1.1 → 10.1.2 (version.ts, app.json, APP_LATEST_VERSION).
  Catatan: fungsionalitas penuh via Deploy/Publish; build baru hanya untuk
  label versi di device.

## v10.1.2 (patch) — Formula SELALU tampil di kartu trade (Okt 2026)
- User report: kartu lama (mis. BNB, WIF) tampil tanpa formula karena
  formula_tag=null & profile=null di DB (trade dibuat sebelum fix backend;
  fix backend hanya berlaku untuk trade baru).
- Fix frontend: baris formula kini SELALU dirender dengan rantai fallback
  formula_tag → label profile → "Confluence" (Positions) dan formulaLines
  fallback → "Confluence v9" (Recent Trades). Kondisi render
  `(profile || formula_tag)` dihapus.
- Verified via seed (BNB null-formula open → "Formula: Confluence";
  WIF longterm closed → "Formula: Confluence v9") di kedua halaman.
  Seed dibersihkan. Versi tetap 10.1.2.

## v10.1.5 — UI Polish Batch (Okt 2026)
1. **Update modal**: body diganti "New Update is available on Google Play
   Store" (lokalisasi 4 bahasa) + baris versi kecil di bawahnya; tombol
   biru diganti "UPDATE NOW" (sebelumnya "GET LATEST APK"). File:
   UpdatePrompt.tsx, I18nContext.tsx.
2. **Formula Running Positions**: fallback terakhir diganti
   "Confluence v9" (konsisten dengan Recent Trades). Trades-position.tsx.
3. **Banner & ikon soft watcher dihilangkan**: banner global "⚠ Open
   positions WITHOUT native SL/TP" dan ikon per-kartu "⚠" + label
   "SL/TP on soft watcher — tap REPAIR banner" disembunyikan (set
   kondisi `false`). Soft watcher di BACKEND tetap aktif melindungi;
   hanya UI yang disembunyikan sesuai permintaan user. Asi-bot.tsx.
4. **POSITION_CLOSED_EXTERNALLY** tidak lagi diperlihatkan sebagai
   kode internal; kartu Recent Trades hanya menampilkan "Closed on
   Binance" dan trades-position menampilkan "Closed on exchange".
5. **Ringkasan harian** diubah dari 2 baris menjadi 2 KOLOM:
   kolom DEMO (biru #38BDF8) & kolom REAL (oranye #F97316) sesuai
   mockup user. Isi tiap kolom: P:L jumlah (W×/L×), P nominal $ + %,
   L nominal $ + %, dan Balance USDT available baris paling bawah.
   Reset tiap 00:00 jam DEVICE user (keputusan sebelumnya).
   Trades-position.tsx (fetch api.asi.balance ditambahkan).
6. **History limit 25 → 50**: listTrades(50) di trades-position dan
   asi-bot (sebelumnya 20 di asi-bot; user meminta 50 agar lebih
   banyak transaksi terlihat).
7. **Fix kartu jiggling 1INCH**: panel PnL kanan di asi-bot dibuat
   width TETAP 88, dan box mark price mendapat minWidth 92 +
   fontVariant tabular-nums supaya tidak membesar/mengecil saat
   digit berubah. Panel PnL di trades-position width tetap 110.
8. **Bump versi 10.1.5**: version.ts, app.json, APP_LATEST_VERSION
   di server.py. Verified via /api/app-version → 10.1.5.
- Verified via screenshot: Running Positions tampil 2 kolom DEMO/REAL
  (biru/oranye) dengan Balance; kartu BNB formula "Confluence v9";
  ORDI "Closed on exchange" tanpa kode internal; Recent Trades tanpa
  banner soft watcher dan tanpa POSITION_CLOSED_EXTERNALLY.

## v10.1.5 (patch) — Teks popup Update jadi SERVER-DRIVEN (Okt 2026)
- Masalah: popup update menampilkan teks yang TERTANAM di APK versi lama
  (mis. v10.1.2), sehingga pengguna lama selalu melihat teks lama ("Ask the
  admin for the latest APK...") walau kode baru sudah menggantinya. App TIDAK
  memakai OTA (expo-updates tidak terinstal, tidak ada runtimeVersion).
- Solusi permanen: backend `/api/app-version` kini mengembalikan object
  `prompt` berisi title/body/button/later terlokalisasi (id/en/ru/cn).
  Frontend `UpdatePrompt.tsx` v10.1.5+ memprioritaskan string server ini;
  bila field kosong/backend lama → fallback ke i18n hardcoded (aman).
- Hasil: mulai v10.1.5, teks popup update dapat diubah kapan saja cukup
  dengan Publish (tanpa build APK). Pengguna yang MASIH di v10.1.2 tetap
  melihat teks lama sampai mereka update ke v10.1.5 (keterbatasan APK lama
  yang tidak bisa diubah dari server).
- Verified: `GET /api/app-version` mengembalikan `prompt` lengkap 4 bahasa.

## v10.1.6 — Fix Deployment Blockers (Okt 2026)
Build EAS Android gagal dengan "No lockfile found in the project directory".
Investigasi: frontend/yarn.lock ADA, valid (yarn install --frozen-lockfile
sukses lokal), ter-track git. Penyebab: snapshot deploy stale tidak memuat
lockfile terkini. Fix: commit bersih seluruh perubahan → snapshot Publish
berikutnya memuat yarn.lock valid. Deployment agent (dipakai user) juga
menemukan 3 blocker policy yang DIPERBAIKI:
1. EXPO_BACKEND_REACH — AuthContext.tsx punya fallback hardcoded
   "https://cryptostock-pro.emergent.host" (2 tempat) yang bypass
   EXPO_PUBLIC_BACKEND_URL. DIHAPUS; auth kini hanya lewat backendBase()
   (env-driven). Trade-off: preview tidak lagi fallback ke host prod utk
   auth code — perilaku produksi yang benar.
2. DESTRUCTIVE_DB_STARTUP — scheduler _run_titan_relay memakai
   delete_many/delete_one pada asi_titan_state. Diubah jadi SOFT-disable
   (update active:False); dedup hanya cocokkan record aktif. Tidak ada
   hard delete di alur startup.
3. DESTRUCTIVE_DB_STARTUP — scanner _run_full_auto_scanner memakai
   delete_one pada asi_trades untuk slot klaim anti-duplikat. Klaim
   dipindah ke collection KHUSUS asi_scan_claims, dilepas SOFT
   (status→"released"); satu doc per (device,symbol) di-reuse. TIDAK ada
   delete_one/delete_many tersisa di alur scheduler/startup.
   (delete di routes.py = endpoint aksi eksplisit user: disconnect
   credential, swipe-delete trade, migrasi device — diizinkan policy.)
Hasil deployment agent: status FAIL → WARN (blocker 0). Sisa warning:
iOS push belum punya GoogleService-Info.plist (hanya relevan utk build
iOS; build Android tidak terpengaruh).
Versi di-bump 10.1.5 → 10.1.6 (version.ts, app.json, APP_LATEST_VERSION).
Aksi user: Publish ulang lalu generate build Android baru.

## v10.1.6 (patch 2) — ROOT CAUSE EAS build "No lockfile found" (Okt 2026)
Build gagal LAGI dgn error sama walau yarn.lock valid & ter-commit. Investigasi
decisif: build me-resolve expo-router@5.0.7 & @expo/vector-icons@14.1.0 → itu
versi dari admin-app/package.json (UnlockKeyGen), BUKAN frontend (expo-router
~6.0.24, vector-icons 15.1.1). Buildspec mendeteksi MOBILE_DIR dari package.json
PERTAMA yg punya app.json/app.config/eas.json; urutan `find` tidak deterministik
→ di environment build admin-app terpilih (admin-app TIDAK punya lockfile) →
"No lockfile found". Berisiko juga mem-build aplikasi yang salah.
FIX (code-level, reversible): `git mv admin-app/app.json admin-app/app.json.build`
→ detektor kini HANYA menemukan frontend (yang punya yarn.lock). Diverifikasi
lokal: hanya ./frontend yang terdeteksi.
REGRESSION CHECK (memastikan tidak mengganggu yg lain):
- Offline admin workflow pakai ZIP STATIS pre-built (backend/static/
  CryptoStock-Admin-Source.zip, sudah berisi app.json sendiri) → TIDAK terpengaruh.
- /api/admin-tool HTTP 200, /api/admin-source.zip HTTP 200.
- Tidak ada import admin-app dari frontend/backend (grep kosong).
- Backend & expo RUNNING stabil, tidak ada Traceback scheduler/titan/claims.
- AuthContext utuh (login/backendBase/unlock logic tidak tersentuh; hanya
  fallback hardcoded host yang dihapus), EXPO_PUBLIC_BACKEND_URL ada di .env.
- App utama load normal (screenshot: disclaimer + versi 10.1.6).
- Catatan ditambahkan di admin-app/README.md (cara restore app.json.build bila
  ingin build APK admin-app manual).
Aksi user: Publish ulang → generate build Android v10.1.6. Build kini memilih
frontend dgn yarn.lock → seharusnya lolos.

## v10.1.6 (patch 3) — Anti-Phishing Popup Update (Okt 2026)
Keluhan user: popup lama ("Ask the admin for the latest APK" / "Get Latest APK")
menakuti user karena banyak scam APK → banyak uninstall. Perbaikan:
- Backend `/api/app-version` kini mengembalikan `prompt` dengan:
  - body (4 bahasa): "New Update is available on Google Play Store."
  - button (4 bahasa): "Update Now" (bukan uppercase menakutkan).
  - source_label: "Opens Google Play Store" (ditampilkan di bawah tombol).
  - store_hint: "Google Play" (chip badge).
  - url: HTTPS Play Store Anda — eksplisit, bisa diubah via Publish.
- Frontend UpdatePrompt.tsx (v10.1.6):
  - Chip badge "📱 Google Play" DI ATAS judul (bukan roket) → user langsung tahu tujuan.
  - Tombol "Update Now" dengan ikon Google Play.
  - Baris anti-phishing di bawah tombol: ✓ "Opens Google Play Store" +
    URL target tampil `play.google.com/store/apps/details?id=...` → user
    bisa verifikasi SEBELUM menekan.
  - URL dari server (prompt.url), fallback play_store_url, fallback hard-coded.
  - Linking.openURL pakai HTTPS Play Store langsung (bukan skema market://
    yang bisa terkesan mencurigakan di beberapa device).
- Server-driven: perubahan teks berikutnya tidak butuh build APK baru,
  cukup Publish backend.
- Catatan: user APK versi lama (<10.1.6) TETAP tampil teks lama (tertanam
  di APK mereka). Mulai 10.1.6 ke depan, popup selalu memakai teks server.
Verified via /api/app-version: semua field body/button/source_label/store_hint/
url sesuai; frontend memparse dengan benar.

## v10.1.6 (patch 4) — Tuning Confluence v9 + Fix Lifecycle (Okt 2026)
Keputusan user atas 5 pertanyaan:
- Q1 (Confluence SL): longterm sl_atr_mult 1.2→2.0×ATR, tp_ladder (1,1.5,2)→
  (1.5,3.0,4.5)R. HANYA profil longterm; profil lain tetap 1.2×ATR. Verified
  live: BTC SELL SL distance 1.043%, TP1 tepat 1.5R.
- Q4 (sinyal Confluence terlambat / beli di puncak): engine sudah punya RSI
  band & zone gate, TAPI belum ada freshness. Ditambah: (a) Anti-chase guard
  — tolak BUY bila harga > EMA21+1.5×ATR, tolak SELL bila < EMA21-1.5×ATR
  (RSI>68/<32 sudah ditolak rsi_buy_ok/sell_ok); (b) Freshness filter —
  hanya entry bila struktur BULL/BEAR terbentuk ≤3 candle terakhir. Keduanya
  khusus jalur Confluence (compute_signal). Verified: tidak crash, sinyal
  valid, default dashboard tetap jalan.
- Q3 (RUNE TP1/TP2 harga sama): BUG pencatatan — reduksi qty apapun dulu
  dilabeli "TP hit" tanpa validasi harga & harga fill diambil dari fill
  terakhir simbol (bisa milik trade lain). Fix: harga fill dari fill yang
  benar-benar mengurangi posisi (last_reduce_fill_price, realizedPnl!=0) +
  baris TP hanya dicatat bila harga fill benar-benar mencapai level TP.
- Q2 (reset harian): caption ditambahkan di Running Positions — statistik
  P:L harian direset 00:00 jam device, bot Full-Auto TIDAK berhenti (24/7).
- Q5 (bot tetap jalan setelah STOP): akar = (1) saveBot menelan error
  diam-diam (`.catch(()=>{})`) → STOP gagal simpan tak terlihat. Fix: kini
  await + Alert "Save Failed" agar user bisa retry. (2) dual-flag
  enabled vs full_enabled — scanner jalan bila full_enabled=true; bila ada
  device_id LAMA (HP sebelum reinstall) dengan full_enabled:true + API key
  valid, bot itu tetap jalan. User diminta verifikasi di produksi.

## v10.2.16 — Panic Guard removal + ASI-Bot persistence (DONE, tested)
- Panic Guard dihapus TOTAL: scheduler (PANIC_INTERVAL), routes (/market-risk endpoint 404, panic_active reset di POST /bot, panic field di scan-debug), frontend api.ts (marketRisk helper), asi-bot.tsx (banner crash latent karena marketRisk state sudah tidak ada), i18n (asi_panic_* + asi_reversal_pattern keys).
- Persistence fix: root cause mode reset = key '@asi_preferred_mode' tidak pernah ditulis. Sekarang saveBot() menulis FULL merged config ke AsyncStorage '@asi_bot_prefs' (mode, parameter, disclaimer) dan restore saat mount sebelum refresh backend. Backend tetap source of truth.
- Bonus fix: useTraderProfile skip sync 422 untuk device tanpa bot config (exists:false).
- Testing: backend curl roundtrip OK (no panic keys), testing_agent frontend PASS 4/4 mode persistence (nav + reload, full↔semi), no panic banner, dashboard smoke PASS, lint bersih, py_compile OK.
- Versi konsisten 10.2.16 di version.ts / app.json / server.py. Publish-only, tanpa build APK.

## v10.2.16 — Fix balance DEMO/REAL "Not connected" tiap keluar-masuk ASI-Bot (DONE)
- Root cause: state `creds` & `balance` selalu mulai kosong saat remount; UI tampil "Not connected" sampai fetch selesai.
- Fix: page-cache (stale-while-revalidate) untuk credentials (`asibot-creds:{did}`) & balance (`asibot-balance:{did}`) — restore instan saat mount, refresh background menimpa dengan data segar. Logika sticky-connected v10.2.1 tetap dipertahankan.
- Lint bersih, smoke render OK. Catatan: di preview tanpa credential memang wajar tampil "Not connected".

## v10.2.16 — Verifikasi cache TESTNET/MAINNET (iteration_41 PASS)
- Status TESTNET/MAINNET per exchange digerakkan oleh `creds` yang sama → fix cache sebelumnya sudah mencakupnya.
- Testing agent membuktikan dengan network delay 4s: first paint langsung menampilkan "TESTNET ✓ · ****AB12" + saldo cache sebelum refresh tiba (SWR bekerja). Refresh kemudian menimpa dengan data backend — perilaku benar.

## v10.2.16 — Fix anti-hang grafik detail aset + AI Suggestions (iteration_42/43 PASS)
- Root cause "stuck berputar tanpa selesai": fetch TANPA timeout di 4 titik:
  1) api.chart (grafik) → kini 30s AbortController, masuk error state, bukan skeleton abadi.
  2) AuthContext /auth/verify cold-start → 8s abort (loaded selalu settle → accessLoaded tak lagi blokir loadChart selamanya).
  3) subscriptionContext initIap Android → Promise.race 6s (initConnection Play Billing bisa hang di device tertentu).
  4) api.aiSuggestions → 45s timeout.
- AISuggestionsSheet: state load_failed kini tampil ⚠️ + tombol Coba Lagi (testID ai-retry) — sebelumnya jatuh ke tampilan kosong yang misleading.
- Halaman detail aset: banner error kini tappable retry (testID chart-retry); timeout tidak di-retry 3x (banner ~30s, bukan ~90s).
- Testing agent PASS: normal flow ~3s chart tampil + harga LIVE; hang simulasi → banner + retry bekerja; timeframe switch bersih.

## v10.2.16 — KISS Pivot Hit-and-Run engine + prefetch chart saat list dimuat
- PREFETCH (frontend-only, keluhan "jangan pakai timeout sebagai solusi"): saat list Recent Trades / Running Positions selesai dimuat, chart SEMUA kartu (max 30 simbol unik, stagger 120ms) langsung di-prefetch ke chartCache (TTL 90s, kapasitas 60). Tap kartu → halaman detail aset tampil instan.
- HIT-AND-RUN engine (engine.py, keputusan user, HANYA trade formula_tag mengandung "KISS Pivot", trade lama tidak diubah):
  · Level override saat eksekusi: SL 0.5% (seukuran TP1), TP1 0.5%, TP2 0.8%, split qty 50/50 (TP_SPLITS[2]), trailing_callback_rate=0 agar SL Guard aktif.
  · Setelah TP1: 50% tertutup otomatis oleh bracket + SL Guard memindah SL ke harga TP1 (mekanisme existing v10.0.16).
  · Batas hold maksimum = horizon profil dari entry (Scalper 15m · Intraday 4h · Swing/Confluence 24h): monitor _refresh_binance menutup posisi via market bila masih profit & TP2 belum tercapai; bila loss dibiarkan ke SL 0.5% ketat.
- Verifikasi: py_compile OK, math sanity BUY/SELL OK, backend sehat, scanner jalan.
- CATATAN: aturan deadline hanya dijalankan monitor native Binance (_refresh_binance). Jalur ccxt fallback (non-Binance) hanya mendapat override level.

## v10.2.16 — Horizon exit digeneralisasi ke SEMUA formula (keputusan user)
- Aturan waktu + profit-cap kini berlaku untuk semua formula pada trade BARU (flag `horizon_exit` di dokumen trade):
  · Scalper: max 15 menit dari entry; profit ROE ≥ 10% → market-close segera.
  · Intraday(day): max 4 jam; profit ROE ≥ 15% → market-close segera.
  · Swing: max 24 jam; profit ROE ≥ 25% → market-close segera.
  · Lewat horizon & masih profit → market-close; loss → dibiarkan ke SL.
  · Confluence v9 / longterm: TIDAK ada cap & batas waktu — hold mengikuti SL/TP1-3.
- KISS Pivot tetap mendapat override level khusus (SL 0.5% / TP1 0.5% / TP2 0.8% / split 50-50) + ikut aturan horizon di atas.
- Posisi existing TIDAK terdampak (flag hanya ada pada trade baru).
- Implementasi: engine.py execute_trade (flag) + _refresh_binance (monitor close). Compile OK, backend sehat.

## v10.2.16 — Verifikasi: aturan horizon/hit-and-run berlaku untuk SEMI & FULL auto
- Kedua jalur eksekusi melewati execute_trade yang sama: Full-Auto (scheduler, profile+formula_tag dari sinyal) dan Semi-Auto (AsiTradeSheet → /trades/execute, profile+formula_tag dari payload).
- Flag hit_and_run & horizon_exit dihitung di dalam execute_trade → otomatis aktif di KEDUA mode tanpa perubahan tambahan.
- Parameter default otomatis dari bot config (risk, leverage, tp_count, margin, entry_mode); user bisa set ulang di sheet sebelum execute. Untuk trade KISS Pivot, override SL/TP memaksa parameter paket hit-and-run terlepas dari input user.

## v10.2.16 — Fix TDZ crash trades-position ("Cannot access 'apiProfile' before initialization")
- Penyebab: fix lint sebelumnya menambah apiProfile ke dependency array useCallback (baris ~120) padahal deklarasinya di baris ~170.
- Perbaikan: pindahkan deklarasi `const { apiProfile } = useTraderProfile()` ke atas (setelah useSafeAreaInsets), hapus deklarasi lama. Tanpa perubahan logika.
- Terverifikasi: lint bersih, halaman /trades-position render normal tanpa error.

## v10.2.16 — Timeout fetch chart DIHAPUS (keputusan user), andalkan prefetch+cache+skeleton
- api.chart: timeout 30s dihapus; get() tetap punya timeoutMs opsional (dipakai aiSuggestions 45s — tidak berubah).
- [symbol].tsx: logika retry timeout-exclusion dihapus (retry tetap untuk 502/network); spinner loading awal diganti SKELETON (kotak chart + 3 bar stat) agar tidak tampak "stuck berputar"; tombol chart-retry tetap ada untuk error nyata.
- Prefetch saat list dimuat sudah aktif dari perbaikan sebelumnya (trades-position + asi-bot, max 30 simbol, stagger 120ms, TTL 90s, kapasitas 60).
- Smoke test: /asset/crypto/BTC chart termuat + harga LIVE, tanpa error.

## v10.2.16 — Fix red-screen "Failed to fetch" dari prefetch chart
- Akar masalah: promise prefetch di chartCache.ts reject TANPA handler (floating promise) → unhandled rejection → red screen di dev/crash di HP. Bukan dari get() itu sendiri.
- Fix: promise prefetch dibungkus .catch → console.warn + return null (cache-miss). Halaman detail jatuh ke fetch normal (skeleton + retry banner). get() TIDAK diubah karena puluhan caller men-destructure respons (c.items, res.markets) — mengembalikan null akan memunculkan crash baru di tempat lain.
- Terverifikasi: intercept network-abort pada endpoint chart → halaman tetap render (harga LIVE via WS + skeleton chart + banner retry), tanpa red screen.

## v10.2.16b — KISS Pivot bracket diubah ke 3-TP (keputusan user)
- SL 0.9% (seukuran TP1, lawan arah) · TP1 0.9% · TP2 1.2% · TP3 1.5% · split qty 50/25/25 (TP_SPLITS[3]).
- Sebelumnya: SL 0.5% · TP1 0.5% · TP2 0.8% (2 TP, split 50/50).
- Berlaku untuk trade KISS Pivot BARU saja; posisi existing tidak diubah. SL Guard (SL→TP1 setelah TP1) & horizon exit tetap berlaku.
- Verifikasi: compile OK, math sanity BUY/SELL benar, backend sehat.

## v10.2.16c — Full-Auto scan 4 engine sekaligus (keputusan user)
- scheduler.py: profile scalper/day/swing kini scan {scalper, day, swing, longterm} — Confluence v9 ikut dieksekusi bila sinyalnya muncul (sebelumnya hanya 3 engine VWAP).
- Trade hasil engine longterm membawa profile "longterm" → otomatis TIDAK kena horizon exit/profit-cap (hold sesuai SL/TP1-3), sesuai aturan profil yang sudah disepakati.
- Semua gate eksekusi (BTC regime, trend filter 4H, late-entry, min confidence) tetap berlaku untuk keempat engine.
- Verifikasi: compile OK, backend restart sehat, scanner berjalan.

## ⭐ BASELINE RESMI — AI Crypto Stock Pro v10.2.16 (16 Okt 2026)
**Git tag: `baseline-v10.2.16` @ commit c73443f** — Titik pemulihan resmi atas permintaan user. Jika ada masalah di perubahan berikutnya, kembali ke titik ini.

### Isi baseline (semua terverifikasi):
1. Panic Guard DIHAPUS TOTAL (backend+frontend+i18n)
2. Persistensi ASI-Bot: mode Full/Semi + parameter + disclaimer via AsyncStorage `@asi_bot_prefs`
3. Cache koneksi/saldo exchange (TESTNET/MAINNET anti "Not connected" flicker)
4. Anti-hang: timeout AI Suggestions 45s + tombol Retry; auth verify 8s; Play Billing init 6s
5. Chart detail aset: prefetch semua kartu saat list dimuat + pageCache + skeleton (TANPA timeout chart — keputusan user)
6. Mark price & PnL kartu realtime via WebSocket multi-ticker Binance langsung dari device
7. Delete kartu sinkron lintas halaman (tombstone bersama)
8. Dashboard profile switch: SWR cache + skeleton instan + prefetch 4 profil (termasuk longterm)
9. Engine: BTC Regime Gate + Trend Filter 4H + anti-late-entry + min confidence (SEMUA tetap, tidak diubah)
10. Horizon exit semua formula: Scalper 15m/cap 10% · Intraday 4h/cap 15% · Swing 24h/cap 25% · Confluence v9 hold SL/TP
11. KISS Pivot hit-and-run: SL 0.9% · TP1 0.9% · TP2 1.2% · TP3 1.5% · split 50/25/25
12. Full-Auto scan 4 engine sekaligus (scalper+day+swing+longterm)
13. Red-screen prefetch crash fix (chartCache promise catch)

### ATURAN KERAS (permintaan user):
- Semua formula & perilaku di atas TIDAK BOLEH diubah oleh perubahan lain TANPA permintaan eksplisit user.
- Jika ada masalah/regresi → `git checkout baseline-v10.2.16` (atau revert ke commit c73443f).

## v10.2.16d — Fix mark price "berkedip 2x lalu statis" (iteration_46 PASS)
- Akar 1: watchdog WS hanya menjaga pesan PERTAMA → koneksi silent-dead setelah beberapa tick tak pernah terdeteksi. Fix: rolling watchdog 30s di-arm ulang TIAP pesan; silence → socket ditutup → fallback host berikutnya (terbukti: fstream silent-dead → pindah ke data-stream.binance.vision di detik ~10, 693 frame tanpa jeda).
- Akar 2: poll 300ms tanpa in-flight guard → request menumpuk di jaringan lambat → harga tampak beku. Fix: tick dilewati bila request sebelumnya belum selesai (kedua halaman).
- Uji stamina 85 detik: 18 sampel, 16 nilai berbeda, PnL akurat, tanpa red screen.

## v10.2.16e — Fix chart lambat/timeout di production (keputusan user, backend)
- Server-side cache 60s untuk /asset/{market}/{symbol}/chart (key: market|symbol|tf|profile) + in-flight dedupe: N request bersamaan berbagi SATU fetch upstream. Akar kelambatan: prefetch banyak kartu memukul exchange berulang tanpa cache → throttle → >30s untuk koin tertentu (GALA).
- Tampilan 1h di-trim ke 120 candle terakhir (dari 250) — sinyal TETAP dihitung dari set penuh (EMA200 utuh) → logika sinyal tidak berubah; hanya payload HP yang diperkecil.
- Verifikasi: GALA miss 4.3s → hit 0.024s; 5 request konkuren selesai serempak (dedupe OK); frontend sudah tanpa timeout chart (v10.2.16 sebelumnya).

## v10.2.16f — Pil mark price grafik mengikuti arah tick + kedip lebih responsif
- Akar "selalu merah": warna pil/garis live mengikuti arah CANDLE 1H TERTUTUP terakhir (bisa merah berjam-jam walau harga naik). Fix: warna mengikuti arah tick terakhir (naik=hijau, turun=merah, sama=warna dipertahankan), reset saat ganti simbol/TF.
- Akar "berkedip lambat": throttle redraw chart 1500ms → 400ms.
- Verifikasi visual: FET (koin dari screenshot user) kini menampilkan pil HIJAU saat harga naik; chart termuat normal + LIVE.

## v10.2.16g — Pil mark price sinkron dengan header
- Akar desync: memo chart (candlesEqual) melewatkan redraw bila perubahan harga < 0.05% → pil menampilkan harga redraw terakhir sementara header mengikuti tiap tick.
- Fix: ambang 0.05% dihapus; setiap perubahan harga memicu redraw pil, hanya dibatasi throttle 400ms. Konstan LIVE_LINE_MIN_PCT_CHANGE dihapus.
- Verifikasi visual: header 82,260.60 = pil 82260.60 (hijau searah), chart normal + LIVE.

## v10.2.16h — Penanganan 5xx menyeluruh + jawaban kasus KAS/GALA
- get(): auto-retry 1x setelah 3 detik untuk HTTP 5xx (502 dst) SEBELUM melempar error — gangguan backend sesaat tidak lagi langsung tampil ke UI. POST/PUT/DELETE (send()) sengaja TIDAK di-auto-retry (risiko double-execute trade).
- Dashboard load(): try…finally TANPA catch adalah akar red screen "HTTP 502 on /dashboard/batch" — kini catch → banner "Gagal memuat data, coba lagi" + tombol Retry (data lama tetap tampil). manage.tsx load() juga ditambah catch. Audit: semua poller halaman (dashboard, trades-position, asi-bot, news, copy-trade, chart) kini punya catch.
- Uji nyata: 502 disimulasikan → tidak ada red screen, banner tampil, Retry memulihkan dashboard (36 kartu premium termuat).
- KASUS KAS (jawaban user): SL Guard HANYA menggeser SL ke TP1 SETELAH TP1 benar-benar terisi di exchange (by design sesuai perintah user). Trade KAS tidak mencatat fill TP1 (0.03745) — harga berbalik sebelum TP1 — dan posisi tertutup di ≈entry (±0.2%) sehingga label jujur "BREAK_EVEN" ($0.00, tanpa loss). Tidak ada kode yang memindah SL ke entry — logika BE lama sudah digantikan SL→TP1 (scheduler.py v10.0.16).
- KASUS GALA (jawaban user): trade itu dieksekusi dengan paket KISS Pivot LAMA (TP1 0.5% / TP2 0.8%) karena terjadi sebelum update 3-TP (0.9/1.2/1.5) di-publish. Trade KISS baru memakai paket 3-TP.

## v10.2.17 — BIG-CAP level floors (keputusan user, koin > $100)
- Masalah: BTC/ETH/BNB level ATR-based terlalu rapat (TP1 +0.30% pada BNB scalper) → profit $3-5 tidak menutup fee Binance (~$4 per $100).
- Floor minimum per profil (diterapkan di execute_trade, berlaku semua jalur Semi+Full Auto, termasuk KISS Pivot; trade baru saja):
  · Scalper: SL 1.0% · TP1 1.0% / TP2 1.5% / TP3 2.0%
  · Intraday: SL 1.5% · TP1 1.5% / TP2 2.2% / TP3 3.0%
  · Swing: SL 2.5% · TP1 2.5% / TP2 3.5% / TP3 5.0%
- Floor bukan override: level formula yang lebih lebar tetap dipakai. Koin < $100 tidak terpengaruh. Confluence v9 (profile longterm) tidak kena floor (hold sesuai SL/TP formula).
- Verifikasi: compile OK; simulasi trade BNB asli user (entry 735.69): SL 733.21→728.33, TP1 737.88→743.05, TP2→746.73, TP3→750.40. Backend sehat.
- CATATAN: engine ini sizing margin-based (bukan SL-distance), jadi SL lebih lebar = risiko $ per trade lebih besar pada margin yang sama.

## v10.2.17 — Simetri SL=TP1 (R=1:1) untuk aset < $100 (keputusan user)
- Masalah: FET BUY TP1 0.869% < SL 0.917% (pembulatan tick exchange + formula asimetris) → trade basic tidak layak R:R.
- Fix: SETELAH big-cap floor, engine memaksa jarak Entry→TP1 = jarak Entry→SL (R simetri). TP2 ikut geser ke min 1.5R, TP3 min 2R dari entry (atau tetap pakai jarak formula bila lebih lebar). Berlaku semua formula/profil kecuali KISS Pivot (yang sudah simetri paket sendiri). Trade lama tidak diubah.
- Verifikasi: FET entry 0.2072 → SL 0.917% · TP1 0.917% (= SL) · TP2 1.375% · TP3 1.834%. Compile OK, backend sehat.

## v10.2.17b — Level floor diperluas ke SEMUA koin (keputusan user: low-cap TP1/TP2 kekecilan)
- Gate `entry > 100` dihapus → floor berlaku untuk semua koin. Konstanta di-rename BIGCAP_LEVEL_FLOORS → LEVEL_FLOORS_MIN.
- Efek low-cap: FET scalper SL 0.92%→1.0%, TP 0.87/1.16/1.45% → 1.0/1.5/2.0%. KISS Pivot ikut kena floor (0.9/1.2/1.5 → 1.0/1.5/2.0 untuk scalper).
- Urutan engine: KISS override → floor (semua koin) → simetri SL=TP1 (non-KISS). Compile OK, backend sehat.

## v10.2.17c — Scalper floor jalan tengah (keputusan user): SL 1.2% · TP 1.2/1.8/2.5%
- Dipilih user dari opsi jalan tengah (antara 1.0/1.5/2.0 dan samakan intraday 1.5/2.2/3.0).
- Intraday & Swing tidak berubah. KISS Pivot scalper ikut floor ini.

## Backend performance fix (Emergent Support, 16 Okt 2026) — JANGAN DIUBAH
Production berjalan di batas CPU 0.25 core. Perubahan berikut WAJIB dipertahankan:
- `server.py::_build_dashboard_response` membangun sinyal per simbol dengan `await asyncio.sleep(0)` (jangan kembali ke list-comprehension sinkron — itu membekukan seluruh backend 3–30 detik: grafik timeout, harga statis, 502, health check gagal).
- `market_data.py::get_batch` crypto lewat `_CRYPTO_SEM` (12) dan Yahoo `_YAHOO_SEM` (12) — jangan dinaikkan/dihapus.
- `dashboard_batch` memakai stale-while-revalidate (`_BATCH_STALE_MAX`).
- `/health` harus `async def` dan ringan.
Logika sinyal/engine trading TIDAK diubah oleh perbaikan ini.

## v10.2.36 — Auto-Close Profit + Anti-Whipsaw (Oct 2026)
- Auto-Close Profit: config/trade `auto_close_pct` ∈ {0,10,15,20,25,50,100} (ROI % of margin). When >0: 1 native TP at entry×(1±pct/lev) closes 100%, tp_count=1, trailing/HAR/horizon disabled for that trade. Mutually exclusive with 1/2/3 TP in UI (ASI-Bot page + AsiTradeSheet). New trades only.
- Full-Auto filters: max 2 same-side entries per 30 min (SIDE_BURST_*); after 2 consecutive same-side losses (latest <60m) the opposite side is blocked 60 min (WHIPSAW_*).
- Tests: backend/tests/test_iter60_v10236_autoclose_whipsaw.py (9 passed, mock only).

## v10.2.37 — Loss control (user decision 21/10 from 20/10 analysis)
- SL clamp: every new trade SL distance forced into 1–2% of entry (engine._clamp_sl, also preview); SL=TP1 symmetry follows.
- Margin per Trade ($): config/trade `margin_usdt` (0 → legacy risk_pct). UI replaces Risk % stepper (MarginInputRow) on ASI-Bot page + trade sheet. Binance path + preview.
- Trailing stop disabled for new trades → after TP1 hit, SL guard moves SL to TP1 price (native & soft). Trailing UI replaced with hint.
- AC badge on Running Positions cards.
- Tests: backend/tests/test_iter61_v10237_sl_margin.py.

## v10.2.38 — Sizing selector
- SizingSelector: user ticks Risk per Trade (%) OR Margin per Trade ($). Risk mode saves margin_usdt=0 (backend falls back to risk_pct). Used on ASI-Bot page + AsiTradeSheet (risk_pct now loaded from config).

## v10.3.0
- History grouped by close date with yellow daily headers (DEMO/REAL daily stats).
- AC trades closed on TP1 labelled "Closed on AC x%" / "AC x% hit" (Running Positions + Recent Trades); AC badge in Recent Trades.
- Daily Profit Limit $ (daily_profit_limit_usdt): Full-Auto auto-stops (full_enabled=False) when realized today >= limit.
- XRP early close root cause: Binance position (3189) larger than trade qty (1785.7) -> another bot instance (preview/production sharing same Binance keys) closed the shared one-way position. Not an AC ROI bug (TP 1.3617 = entry*(1+0.15/12)).
- Note: existing Daily Loss Limit sets enabled=False only, which does not stop full_enabled bots (not changed).

## v10.3.1
- Daily Loss Limit now also sets full_enabled=False (Full-Auto really stops). Test: backend/tests/test_iter62_v1031_daily_loss_stop.py

## v10.3.2
- Daily Profit Limit also covers legacy full configs and sets enabled+full_enabled False. Tests in test_iter62.

## v10.3.3 — Auto-resume 00:00
- Daily profit/loss limit now counts realized PnL since 00:00 LOCAL (tz_offset_min from device, default WIB 420) on the ACTIVE network (demo counts when active_testnet).
- On stop: auto_disabled_kind=daily_limit + auto_disabled_day. _auto_resume_daily_limits re-enables Full-Auto when local day changes. Any manual config save clears the marker (no resume).

## v10.3.4 — Ghost open positions + refresh
- _refresh_binance: (a) Binance position opposite side → record closed; (b) own qty fully reduced by recorded SL/TP fills → closed even if another position on same symbol exists; (c) SL order missing + mark crossed SL → emergency market close of own qty (reason SL, detail sl_missing_emergency_close).
- POST /api/asi/trades/sync?device_id → reconcile all open trades now; Running Positions refresh button calls it with spinner (testID tp-refresh).
- Tests: backend/tests/test_iter63_v1034_ghost_open.py

## v10.3.5
- Auto-Close options extended: 10/15/20/25/50/75/100/150/200 (no suggestion/warning per user).

## v10.3.6 — Close All reliability
- close-all groups open trades per (exchange,testnet,symbol), closes groups in PARALLEL (was sequential → ingress 60s timeout left positions open), retries up to 3x, verifies live positionAmt==0 before marking closed; failures reported per symbol and those rows stay open.
- Tests: backend/tests/test_iter64_v1036_close_all.py

## v10.3.7 — Price feed WS fix
- Root cause: Binance retired legacy USD-M futures WS URLs (fstream.binance.com/ws & /stream) on 23 Apr 2026; connections open but send no data. Now use wss://fstream.binance.com/market/ws/... and /market/stream?streams=... in useBinanceMultiTicker, useBinanceRealtime, useBinanceKline.
- Multi-ticker & realtime: rolling 30s watchdog, attempt reset on data (prefer futures), AppState foreground forced reconnect.

## v10.3.8 — Preview perf
- "0 open positions" in agent screenshots = fresh browser device_id (no DB isolation; engine updates the 3 open trades of web:qmeqflw0e2d-mui5ar38 every cycle).
- binance_rest._request: persistent keep-alive httpx client per loop (was new client + TLS via proxy per signed call ~1.5s).
- /asi/prices: persistent clients, single-flight lock, TTL 1s (1.67s → ~0.6s).
- /asi/trades/sync parallel.
- Titan relay: 10-min backoff on -2015/-2014 (was spamming Binance every cycle).
- asi_trades indexes (device_id+created_at, status+device_id, device_id+status+closed_at).
- close-all v10.3.6 leaves no resources open (gather over awaited tasks; no background tasks).

## v10.3.9
- Titan Relay temporarily disabled: scheduler.TITAN_RELAY_ENABLED=False (loop exits after startup). Set True after master key renewed.

## v10.4.0 — BTC 15m direction filter
- scheduler._btc_15m_direction (pure) + _get_btc_15m_direction (BTC 1m x15 Binance spot klines, once per cycle). rebound (last > 15m low +1%) → reject SELL; dump (last < 15m high -1%) → reject BUY; both → latest extreme wins; sideways/unknown → free. All coins, REAL & DEMO, all profiles; new entries only. Reject reason btc15m_rebound/btc15m_dump in scan-debug.
- Tests: backend/tests/test_iter65_v1040_btc15m.py

## v10.4.1
- AC mode = SL-only on exchange (execute + attach_brackets skip TP orders; bracket hard with SL only). AC monitor: _refresh_binance closes own qty via market when margin ROI >= AC% (reason AC); fast watcher _run_ac_watcher every 5s (positionRisk mark). Card TP = entry*(1±AC/lev).
- Semi preview passes auto_close_pct (calculator updates on TP/AC change).
- History: no daily header for today.
- Thumbnail: DisclaimerModal skipped on web; HTML splash removed on markAppReady (fallback fade 9s).
- Tests: test_iter66_v1041_ac_monitor.py

## v10.5.0 — Early Reversal
- indicators._early_reversal_signal: LONG = RSI14 prev<35 & rising + lower-low bullish candle (close>open) + MACD hist prev<0→now>0; SHORT symmetric (RSI>65 falling, higher-high bearish candle, hist >0→<0). Checked first in compute_signal (all profiles); SL beyond reversal candle extreme +0.2 ATR, TP 1R/1.5R/2R; formula_tag "Early Reversal"; confidence 80.
- Scanner skips 2-cycle confirmation for early_reversal signals; all other gates (BTC regime/15m, trend, caps, SL clamp) unchanged.
- Tests: test_iter67_v1050_early_reversal.py

## v10.5.1 (2026-06)
- Full-Auto: saat BTC 15m sideways (<±1%), gate rezim BTC 1H/4H lama dilewati (kecuali bear_capitulation); bonus conf BEAR4H tetap. Data 15m gagal → gate lama aktif.
- Temuan: early-reversal tidak memblokir sinyal; preview tidur 25/10 20:00–26/10 16:00 UTC (scanner tidak jalan).
- Test: tests/test_iter68_v1051_btc_gate_bypass.py

## v10.6.0
- v10.5.1 bypass filter BTC dibatalkan (filter 1H/4H lama aktif lagi).
- Tombol Reverse Sinyal (Full-Auto, DEMO & REAL): config `reverse_signal`; filter menilai sinyal asli, eksekusi dibalik, SL/TP dicerminkan dari entry; formula_tag diberi " · REVERSE".
- Test: tests/test_iter68_v1060_reverse.py

## v10.6.1
- Bypass filter BTC lama (v10.5.1) aktif HANYA saat Reverse ON + BTC 15m sideways.
- Circuit breaker: 3 loss beruntun (pnl<0, dulu <-$1) → pause 2 jam.
- Close All Binance: sapu semua posisi live via REST (positionRisk all → market reduceOnly paralel, ulang 3x).
- Badge OPEN/CLOSED pindah ke kanan atas (atas PnL) di Running Positions & Recent Trades.
- Leaderboard: badge Margin/AC/TP/Isolated/formula + tombol REVERSE 1-tap; EXECUTE kini ikut AC & margin user.
- Detail aset: tombol REVERSE: Long/Short with ASI-Bot (1-tap) menggantikan tombol kuning.
- src/lib/quickExecute.ts (quickExecute, reverseLevels).

## v10.6.2
- ASI-Bot: Start/Stop jadi 1 tombol toggle (asi-toggle-full); tombol REVERSE ON/OFF di kanannya (asi-reverse-toggle), dipindah dari bagian setting.

## v10.6.4
- Reverse otomatis (semua akun Full-Auto): BTC 15m sideways → ON; rebound/dump >1% → OFF + tutup posisi OPEN & batalkan LIMIT REVERSE Full-Auto (close_reason reverse_auto_off). _rev_active() menentukan reverse per siklus.
- -2027 → simbol cooldown 30 menit/device.
- Badge ⇅ REVERSE di Running Positions & Recent Trades.
- Baris diagnostik scanner pakai i18n.

## v10.6.5
- Reverse dibalik di HULU loop sinyal: semua filter menilai arah yang dieksekusi (keputusan user).
- APP_LATEST_VERSION (server.py) = versi LIVE di Google Play (10.5.0), TIDAK ikut bump saat uji coba. Ubah hanya bila user konfirmasi rilis Play.

## v10.6.6
- Auto-Close tambah 30/35/40/45/60/65% (engine, routes, ASI-Bot, Semi-Auto sheet).

## v10.6.7
- -2027 → Full-Auto ulang otomatis leverage ½ lalu ¼ (min 1x), baru cooldown 30 menit.
- GET /api/asi/stats/breakdown (per AC & Reverse vs Normal, DEMO/REAL) + kartu TradeStatsCard di Running Positions.

## v10.6.9
- Reverse HANYA bila user menyalakan tombol (auto-ON dihapus; migrasi startup mematikan Reverse yg dulu auto-ON).
- BTC 15m >1% → tombol Reverse OFF + tutup posisi/batalkan Limit REVERSE Full-Auto; user nyalakan lagi manual.
