# AITrade Pro – PRD (MVP)

## Vision
A no-login Android-ready Expo mobile app delivering Multi-AI ensemble trading
signals for Indonesian Stocks (IDX, via Yahoo Finance) and Cryptocurrency
(Binance public API). Pro-Exchange aesthetic with dark theme primary.

## Core Features (delivered)
1. **Two-column dashboard** (CRYPTO / SAHAM) with price, sparkline, BUY/SELL/HOLD signal,
   AI confidence %, **WR 30d badge**, and **⭐ PREMIUM ribbon** (gold border + glow) for
   high-conviction signals (AI confidence ≥85% AND WR 30d ≥70% AND non-HOLD).
2. **Sort & Filter row** – `Sort: Premium / AI% / WR / Default` + `⭐ PREMIUM ONLY` toggle.
3. **Timeframe selector**: 15m, 30m, 1h, 3h, 6h, 12h, 18h, 24h.
4. **Asset detail screen** with line+area chart, indicators, Entry/SL/TP, Multi-AI ensemble
   (Claude Sonnet 4.6 + GPT-5.2 + Gemini 3.1 Pro) + live news + 📊 Track Record (WR 7d/30d/all).
5. **Multi-profile watchlist** – Spot Crypto / Futures Crypto / Saham Konservatif (default
   seeded; create/rename/delete/activate via Manage screen).
6. **Theme toggle** (dark primary, light alternate).
7. **Live News Feed** – RSS aggregator, OG image thumbnails, 5-min cache + 60s auto-refresh,
   market filter pills + per-symbol chip filter.
8. **Signal history & backtesting** – every analyze records to MongoDB; lazy eval after N
   candles; 1% hit threshold; aggregated WR 7d/30d/all-time per asset.

## Tech Stack
- Backend: FastAPI + Motor (MongoDB) + emergentintegrations (Emergent LLM key)
- Frontend: Expo SDK 54, expo-router, react-native-svg, safe-area-context
- Market data: `data-api.binance.vision` (Binance public), Yahoo Finance v8 chart
- AI: Claude Sonnet 4.6 + GPT-5.4 + Gemini 3.1 Pro via Emergent Universal Key

## API
- `GET /api/dashboard?market=crypto|stock&timeframe=…` → signals + track_record per asset
- `GET /api/profiles` / `POST /api/profiles` / `PUT /api/profiles/{id}` /
  `DELETE /api/profiles/{id}` / `POST /api/profiles/{id}/activate`
- `GET /api/watchlist` / `POST /api/watchlist` → CRUD active profile's lists (legacy)
- `GET /api/asset/{market}/{symbol}/chart?timeframe=…` → candles + signal
- `POST /api/asset/{market}/{symbol}/analyze?timeframe=…` → AI consensus + news_used + records signal
- `GET /api/asset/{market}/{symbol}/track-record` → WR 7d/30d/all + recent signals
- `GET /api/news?market=crypto|stock|all&limit=N` → live RSS aggregator (image incl.)
- `GET /api/asset/{market}/{symbol}/news?limit=N` → news matched to symbol aliases

## Out of scope (future)
- Push notifications when signal crosses threshold
- Backtesting / historical signal accuracy
- Order routing to Binance / Sinarmas Sekuritas (requires user API keys, KYC)
- Portfolio P&L tracking
