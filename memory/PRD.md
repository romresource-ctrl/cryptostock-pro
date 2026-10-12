# AI Crypto Stock Pro — PRD

## Product Summary
AI-powered trading signal dashboard covering crypto, IDX stocks, US stocks, ETFs, gold/silver, commodity, forex. Bilingual (ID/EN/RU/CN), premium unlock, chatroom, AI Market Brief, WR history.

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
