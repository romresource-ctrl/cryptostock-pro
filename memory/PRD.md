# AI Crypto Stock Pro — PRD

## Product Summary
AI-powered trading signal dashboard covering crypto, IDX stocks, US stocks, ETFs, gold/silver, commodity, forex. Bilingual (ID/EN/RU/CN), premium unlock, chatroom, AI Market Brief, WR history.

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
