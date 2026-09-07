# AI Crypto Stock Pro — PRD

## Product Summary
AI-powered trading signal dashboard covering crypto, IDX stocks, US stocks, ETFs, gold/silver, commodity, forex. Bilingual (ID/EN/RU/CN), premium unlock, chatroom, AI Market Brief, WR history.

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
