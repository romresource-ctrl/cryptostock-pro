# AITrade Pro – PRD (MVP)

## Vision
A no-login Android-ready Expo mobile app delivering Multi-AI ensemble trading
signals for Indonesian Stocks (IDX, via Yahoo Finance) and Cryptocurrency
(Binance public API). Pro-Exchange aesthetic with dark theme primary.

## Core Features (MVP – delivered)
1. **Two-column dashboard** (CRYPTO / SAHAM) showing 22+18 default assets with:
   - Price (Binance for crypto, Yahoo `.JK` for IDX stocks)
   - 24h change %
   - Sparkline (30 bars)
   - BUY / SELL / HOLD signal pill (LONG/SHORT label for crypto)
   - AI confidence %
2. **Timeframe selector**: 15m, 30m, 1h, 3h, 6h, 12h, 18h, 24h.
3. **Asset detail screen** with:
   - Line+area price chart (closing prices, react-native-svg)
   - Technical indicators (RSI, EMA20/50, MACD-H, ATR)
   - Entry / Stop-Loss / Take-Profit suggestions
   - Multi-AI ensemble button (calls Claude Sonnet 4.6, GPT-5.4, Gemini 3.1 Pro
     concurrently and aggregates a consensus signal, news factors, risks).
4. **Manage assets** screen – toggle which symbols are shown on each column,
   persisted in MongoDB (`watchlist` collection, single shared doc).
5. **Theme toggle** (dark primary, light alternate) persisted via AsyncStorage.

## Tech Stack
- Backend: FastAPI + Motor (MongoDB) + emergentintegrations (Emergent LLM key)
- Frontend: Expo SDK 54, expo-router, react-native-svg, safe-area-context
- Market data: `data-api.binance.vision` (Binance public), Yahoo Finance v8 chart
- AI: Claude Sonnet 4.6 + GPT-5.4 + Gemini 3.1 Pro via Emergent Universal Key

## API
- `GET /api/dashboard?market=crypto|stock&timeframe=…` → signals list
- `GET /api/watchlist` / `POST /api/watchlist` → CRUD watchlist
- `GET /api/asset/{market}/{symbol}/chart?timeframe=…` → candles + signal
- `POST /api/asset/{market}/{symbol}/analyze?timeframe=…` → Multi-AI consensus

## Out of scope (future)
- Push notifications when signal crosses threshold
- Backtesting / historical signal accuracy
- Order routing to Binance / Sinarmas Sekuritas (requires user API keys, KYC)
- Portfolio P&L tracking
