# AI Crypto Stock Pro — PRD

## Product Summary
AI-powered trading signal dashboard covering crypto, IDX stocks, US stocks, ETFs, gold/silver, commodity, forex. Bilingual (ID/EN/RU/CN), premium unlock, chatroom, AI Market Brief, WR history.

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
