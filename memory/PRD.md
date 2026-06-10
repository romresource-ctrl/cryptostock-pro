# AITrade Pro – PRD (MVP)

## Vision
A no-login Android-ready Expo mobile app delivering Multi-AI ensemble trading
signals for Indonesian Stocks (IDX, via Yahoo Finance) and Cryptocurrency
(Binance public API). Pro-Exchange aesthetic with dark theme primary.

## Core Features (delivered)
1. **Two-column dashboard** (CRYPTO / SAHAM) with price, sparkline, BUY/SELL/HOLD signal,
   AI confidence %, **WR 30d badge** (track-record win rate) per asset.
2. **Timeframe selector**: 15m, 30m, 1h, 3h, 6h, 12h, 18h, 24h.
3. **Asset detail screen** with line+area chart, technical indicators, Entry/SL/TP,
   Multi-AI ensemble (Claude Sonnet 4.6 + GPT-5.2 + Gemini 3.1 Pro) with live news,
   plus **📊 Track Record** section (WR 7d/30d/all + recent signals with hit/miss).
4. **Multi-profile watchlist** – default seeded profiles: **Spot Crypto**, **Futures Crypto**,
   **Saham Konservatif**. Create/rename/delete/activate via Manage screen.
5. **Theme toggle** (dark primary, light alternate), persisted via storage.
6. **Live News Feed** – RSS aggregator (CoinDesk, CoinTelegraph, Decrypt, CryptoPanic,
   Bitcoin Magazine, Bisnis.com, Kontan, CNBC Indonesia, Investing.com Indonesia,
   Yahoo Finance) with 5-min cache + 60s frontend auto-refresh, **OG image thumbnails**,
   filter pills SEMUA/CRYPTO/SAHAM, **per-symbol chip filter** (tap BTC/ETH/BBCA etc.).
7. **Signal history & backtesting** – every `/analyze` records a signal; lazily evaluated
   N candles later vs spot price; hit threshold 1%. Win-rate aggregated 7d/30d/all-time.

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
