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
