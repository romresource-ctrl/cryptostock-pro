# THIS SECTION CONTAINS CRITICAL TESTING INSTRUCTIONS FOR BOTH AGENTS
# BOTH MAIN_AGENT AND TESTING_AGENT MUST PRESERVE THIS ENTIRE BLOCK

# Communication Protocol:
# If the `testing_agent` is available, main agent should delegate all testing tasks to it.
#
# You have access to a file called `test_result.md`. This file contains the complete testing state
# and history, and is the primary means of communication between main and the testing agent.
#
# Main and testing agents must follow this exact format to maintain testing data. 
# The testing data must be entered in yaml format Below is the data structure:
# 
## user_problem_statement: {problem_statement}
## backend:
##   - task: "Task name"
##     implemented: true
##     working: true  # or false or "NA"
##     file: "file_path.py"
##     stuck_count: 0
##     priority: "high"  # or "medium" or "low"
##     needs_retesting: false
##     status_history:
##         -working: true  # or false or "NA"
##         -agent: "main"  # or "testing" or "user"
##         -comment: "Detailed comment about status"
##
## frontend:
##   - task: "Task name"
##     implemented: true
##     working: true  # or false or "NA"
##     file: "file_path.js"
##     stuck_count: 0
##     priority: "high"  # or "medium" or "low"
##     needs_retesting: false
##     status_history:
##         -working: true  # or false or "NA"
##         -agent: "main"  # or "testing" or "user"
##         -comment: "Detailed comment about status"
##
## metadata:
##   created_by: "main_agent"
##   version: "1.0"
##   test_sequence: 0
##   run_ui: false
##
## test_plan:
##   current_focus:
##     - "Task name 1"
##     - "Task name 2"
##   stuck_tasks:
##     - "Task name with persistent issues"
##   test_all: false
##   test_priority: "high_first"  # or "sequential" or "stuck_first"
##
## agent_communication:
##     -agent: "main"  # or "testing" or "user"
##     -message: "Communication message between agents"

# Protocol Guidelines for Main agent
#
# 1. Update Test Result File Before Testing:
#    - Main agent must always update the `test_result.md` file before calling the testing agent
#    - Add implementation details to the status_history
#    - Set `needs_retesting` to true for tasks that need testing
#    - Update the `test_plan` section to guide testing priorities
#    - Add a message to `agent_communication` explaining what you've done
#
# 2. Incorporate User Feedback:
#    - When a user provides feedback that something is or isn't working, add this information to the relevant task's status_history
#    - Update the working status based on user feedback
#    - If a user reports an issue with a task that was marked as working, increment the stuck_count
#    - Whenever user reports issue in the app, if we have testing agent and task_result.md file so find the appropriate task for that and append in status_history of that task to contain the user concern and problem as well 
#
# 3. Track Stuck Tasks:
#    - Monitor which tasks have high stuck_count values or where you are fixing same issue again and again, analyze that when you read task_result.md
#    - For persistent issues, use websearch tool to find solutions
#    - Pay special attention to tasks in the stuck_tasks list
#    - When you fix an issue with a stuck task, don't reset the stuck_count until the testing agent confirms it's working
#
# 4. Provide Context to Testing Agent:
#    - When calling the testing agent, provide clear instructions about:
#      - Which tasks need testing (reference the test_plan)
#      - Any authentication details or configuration needed
#      - Specific test scenarios to focus on
#      - Any known issues or edge cases to verify
#
# 5. Call the testing agent with specific instructions referring to test_result.md
#
# IMPORTANT: Main agent must ALWAYS update test_result.md BEFORE calling the testing agent, as it relies on this file to understand what to test next.

#====================================================================================================
# END - Testing Protocol - DO NOT EDIT OR REMOVE THIS SECTION
#====================================================================================================



#====================================================================================================
# Testing Data - Main Agent and testing sub agent both should log testing data below this section
#====================================================================================================

user_problem_statement: |
  AI Crypto Stock Pro v3.0.8 — implement REAL Google Play Billing subscription
  ($20/month with 3-day free trial, product ID `ai_cryptostockpro_monthly`),
  server-side verification via Google Play Developer API, and enable R8/ProGuard.
  Frontend must gate premium features on `isPremium` (subscription entitlement)
  OR `isUnlocked` (legacy admin unlock code).

backend:
  - task: "Subscription verification endpoint (Google Play Developer API)"
    implemented: true
    working: "NA"
    file: "/app/backend/subscription_service.py, /app/backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          Added POST /api/subscription/verify and GET /api/subscription/status
          endpoints. Uses `subscription_service.py` which calls Google Play
          Publisher API `purchases.subscriptionsv2.get` (with v1 fallback) using
          a service account. If GOOGLE_PLAY_SERVICE_ACCOUNT_JSON env var is not
          set, endpoint returns status="unverified" and entitled=false — this is
          the current state (dev-mode fallback). Entitlement upserted into
          Mongo collection `subscriptions` keyed by (purchase_token, package_name).
          Test with fake token returns unverified as expected. Real verification
          only testable on Android Internal Testing after service account is
          configured by user.

frontend:
  - task: "Subscription hook, provider, and VipModal integration (react-native-iap 15.6)"
    implemented: true
    working: "NA"
    file: "/app/frontend/src/lib/subscription.ts, /app/frontend/src/lib/subscriptionContext.tsx, /app/frontend/src/components/VipModal.tsx, /app/frontend/app/_layout.tsx, /app/frontend/app/index.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          Rewrote subscription.ts as full imperative flow: initIap (lazy Android-only
          import), fetchSubscription, purchaseSubscription, restorePurchases,
          setupPurchaseListener (global). New SubscriptionProvider wraps app in
          _layout.tsx and exposes { isPremium, subscribe, restore, entitlement,
          product }. VipModal rewired to use useSubscription() — Subscribe button
          triggers real Google Play requestSubscription (Android) OR shows
          Android-only message (web/iOS). Restore Purchase button added.
          Dashboard gating updated: `hasAccess = isUnlocked || isPremium`.
          Web preview shows the correct fallback UI (screenshot verified).
          Actual purchase flow can only be validated on a real Android
          Internal Testing device.
  - task: "App version bump to 3.0.8"
    implemented: true
    working: true
    file: "/app/frontend/src/lib/version.ts, /app/frontend/app.json"
    stuck_count: 0
    priority: "medium"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: "Bumped from 3.0.7 → 3.0.8. Screenshot confirms 'Ver 3.0.8' in header."
  - task: "R8/ProGuard shrinking for AAB optimization"
    implemented: true
    working: "NA"
    file: "/app/frontend/app.json"
    stuck_count: 0
    priority: "medium"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          Added expo-build-properties plugin with
          enableProguardInReleaseBuilds=true, enableShrinkResourcesInReleaseBuilds=true.
          Added keep rules for react-native-iap, billing client, and nitro modules
          to prevent stripping. Only effective in release AAB — cannot test in
          dev mode / web preview.

metadata:
  created_by: "main_agent"
  version: "8.1.3"
  test_sequence: 19
  run_ui: false

test_plan:
  current_focus:
    - "Full-universe /api/search with Binance + Bitget auto-loaded universe + CoinGecko disambiguation"
    - "Interactive consensus filter (PREMIUM/BUY/HOLD/SELL) on dashboard"
    - "Extended world stocks (Japan/China/HK/Taiwan/Malaysia/Singapore/Russia/Korea + S&P500 extension)"
    - "IDX low-caps additions (COCO/DOOH/EMAS/ERAA/IMPC/KETR/KOTA/MSIN/SCMA/SINI/SOCI/VKTR/WBSA)"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

metadata:
  created_by: "main_agent"
  version: "8.1.6"
  test_sequence: 22
  run_ui: false

agent_communication:
  - agent: "main"
    message: |
      v8.1.6 — Deep-entry formula overhaul + AI prompt simplification.

      Feedback loop from user:
      "In my trading experience, if I entered at AI's suggested entry
      price I often ended up 50-100% negative. I have to wait 3-4 more
      valleys/peaks before entering. Please make entry price lower for
      LONG signals and higher for SHORT signals."

      NEW FORMULA (indicators.py):
        peaks, valleys = _find_swings(highs, lows, window=10)
        BUY  entry_deep = (avg_valley + lowest_valley)/2 − ATR × 0.5
             entry_moderate = avg_valley
             entry_aggressive = between price & avg_valley
             TP = avg(last 3 peaks)
             SL = entry_deep − ATR × 0.5  (tighter stop per user spec)
        SELL entry_deep = (avg_peak + highest_peak)/2 + ATR × 0.5
             entry_moderate = avg_peak
             entry_aggressive = between price & avg_peak
             TP = avg(last 3 valleys)
             SL = entry_deep + ATR × 0.5
        HOLD entry = price, TP/SL = ±ATR (unchanged safety fallback)

      Prior formula (v8.1.5) was `entry = current price` which caused
      users to enter tops on BUY / bottoms on SELL. Now entry sits well
      inside the recent structure. Verified live: BTC SELL entry_deep
      65707 vs price 64013 (above), HYPE SELL 58.47 vs price 53.82 (up),
      USDT BUY 1.00070 vs price 1.0011 (below). 3 BUYs / 6 SELLs on
      dashboard all satisfy the direction rule.

      NEW AI PROMPT (ai_engine.py):
      Reduced from v8.1.5's 5-line macro-heavy prompt to a 3-line
      v2.1.8-style prompt. Removed "macro / political / economic
      context" jargon. Summary now 200-400 chars typical (down from
      600+). AI still returns action/confidence but its entry/SL/TP
      are IGNORED — backend uses the deterministic formula above from
      `_all_levels` in the compute_signal payload. AI picks
      `entry_bias` ∈ {deep, moderate, aggressive} and the majority
      vote selects which cycle to serve as the consensus entry.

      RESULT: Consensus entry now deterministic (no more model
      variance jitter). Both Set 1 (technical card) and Set 2 (AI
      consensus card) remain displayed as user requested — they
      just carry different bias levels (Set 1 = deep default, Set 2
      = AI-chosen bias).

      SCHEMA CHANGES:
        AssetSignal (Pydantic): + entry_moderate, entry_aggressive
        Analyze response .technical: + entry_moderate, entry_aggressive,
          indicators.{avg_peak, avg_valley, peaks_found, valleys_found},
          _all_levels (internal)
        Analyze response .consensus: + entry_bias, bias_votes

      TESTED (17/17 via testing_agent iter22):
      - Formula sanity: all BUYs entry < price, all SELLs entry > price.
      - TP ≈ avg_peak/avg_valley (±1.5 ATR).
      - SL ≈ 0.5 ATR from chosen entry.
      - Dashboard exposes all 3 entry tiers.
      - AI summary length ≈ 226 chars (short v2.1.8-style).
      - AAPL non-crypto path OK.
      - Regressions clean: search, chat, subscription, batch.

      NOT CHANGED (still locked):
      - VipModal, ChatSheet, chat.tsx, subscription* — user only
        unlocked chat for v8.1.5 reply/voice-note work.

  - agent: "main"
    message: |
      v8.1.5 — Chatroom reply + voice notes (user-requested feature).

      NEW SINCE v8.1.4:
      1. WhatsApp-style REPLY on chat bubbles:
         - Swipe LEFT past 60px on any bubble → auto-focus composer +
           show reply preview strip above input (coloured bar, nickname,
           snippet, or media hint 📷/🎤, ✕ to cancel).
         - Outgoing message carries `reply_to` snapshot; recipients see
           inline reply block inside the bubble with tap target for
           future scroll-to-original.
      2. VOICE NOTES:
         - Press-and-hold mic button (replaces send arrow when composer
           is empty) → recording starts + red live strip with timer +
           "slide ← to cancel" hint.
         - Slide LEFT past 60px while recording → mic button turns red,
           on release the recording is discarded.
         - Release without cancel → uploads to backend as base64 M4A
           data URL (client soft-cap 20s; backend hard-cap 30s / 500KB).
         - Received voice bubbles show ▶️/⏸ button + waveform bar +
           duration; single-active playback (starting a new one auto-
           stops the previous).
      3. Backend: ChatMessage + ChatMessagePayload extended with
         `audio_data`, `audio_duration_ms`, `reply_to` (nested
         ChatReplyInfo model). Validation: mime prefix, char cap,
         duration cap. All fields optional so old clients keep working.
      4. Permissions: RECORD_AUDIO added to android.permissions;
         NSMicrophoneUsageDescription added to iOS infoPlist. expo-audio
         plugin configured with microphone permission string.
      5. Files edited (chat lock lifted per explicit user request):
         - server.py (chat models + POST validation)
         - ChatSheet.tsx (reply gesture + voice recorder/player + UI)
         - api.ts (no changes; direct fetch used in ChatSheet)
         - app.json (permissions + plugin config)
         - package.json (expo-audio@1.1.1 installed)

      NOT CHANGED (still locked):
      - VipModal, chat.tsx (full-screen chat), AuthContext, subscription*.

      TESTED (24/24 PASSED via testing_agent iter20):
      - Reply schema round-trip (POST + GET both preserve reply_to).
      - Audio data URL validation, duration cap, size cap.
      - Premium gating (403 without entitlement) still enforced.
      - Premium success path via seeded test entitlement.
      - Regression: /api/dashboard, /api/search, /api/subscription/health.

      NOT TESTED (native-only):
      - Actual voice recording — requires microphone hardware.
      - Native soft keyboard behavior after swipe-to-reply.
      - Playback of received voice notes on Android.
      → must be validated on real Android build.

  - agent: "main"
    message: |
      v8.1.3 — Regional filter chips + world stocks expansion (final iter).

      NEW SINCE PREVIOUS TEST:
      1. Chip row above search bar REPLACED — old Crypto/ETF/IDX asset
         chips (with "1"/"2" order badges) removed. New chip row lists
         17 country/region filters with flag emojis:
         All / US / Europe / Canada / China / HK / Japan / Korea /
         Taiwan / SG / Malaysia / India / AU / Gulf / LATAM / Africa /
         Russia. testID: `region-{key}`.
      2. Tap any region → WORLD STOCKS column loads top-50 tickers from
         that region via new `/api/dashboard?region=X` and
         `/api/dashboard/batch?region=X` query parameter. Region is
         derived server-side from Yahoo suffix (.T→japan, .SS/.SZ→china,
         .HK→hongkong, .TW→taiwan, .KL→malaysia, .SI→singapore,
         .KS/.KQ→korea, .ME→russia, .NS/.BO→india, .L/.PA/.DE/.MI/.AS/
         .MC/.SW/.CO→europe, .TO/.V→canada, .AX/.NZ→australia, .SR/.DU/
         .AD/.QA→gulf, .SA/.MX/.SN/.BA→latam, .JO→africa).
      3. Region filter ONLY affects stock_us column. crypto / etf /
         stock_id / gold_silver / commodity / forex pass-through
         unchanged so no data is hidden by tapping a region.
      4. Backend model `AssetSignal` now has optional `region` field on
         every response (null for non-stock markets).
      5. STOCK_US_YAHOO_MAP expanded 607 → 809 tickers: added UK (~23),
         Continental Europe (~50), India NSE (~38), Canada TSX (~20),
         Australia ASX (~18), Gulf .SR/.DU/.AD/.QA (~17), LATAM
         .SA/.MX/.SN (~18), South Africa .JO (~12).

      NOT CHANGED (safety):
      - VipModal, ChatSheet, chat.tsx, AuthContext, subscription* — locked.
      - Signal filter chips (PREMIUM/BUY/HOLD/SELL) — unchanged behaviour.
      - CoinGecko disambiguation, Binance/Bitget cascade — unchanged.

      PLEASE TEST BACKEND (region filter):
      1. GET /api/dashboard?market=stock_us&region=japan → top-50 all
         `.T` tickers (TOYOTA, SONYG, SOFTBANK…). Every asset has
         `region: "japan"`.
      2. Repeat for region=china (MOUTAI/WULIANGYE/ICBC…), region=hongkong
         (TENCENT/ALIBABA_HK/MEITUAN…), region=india (RELIANCE/TCS/INFY…),
         region=europe (LVMH/SAP/NESTLE…), region=canada (SHOP.TO/RY.TO…),
         region=australia (BHP.AX/CBA.AX…), region=gulf (ARAMCO/EMAAR…),
         region=latam (PETROBRAS/VALE_BR…), region=africa (NASPERS…),
         region=russia (SBER/GAZP…).
      3. GET /api/dashboard?market=stock_us (no region) or region=all
         must return the previous US default (AAPL/MSFT/NVDA…).
      4. GET /api/dashboard/batch?markets=stock_us&region=japan →
         `markets.stock_us.assets` contains Japan tickers.
      5. GET /api/dashboard/batch?markets=crypto&region=japan →
         `markets.crypto.assets` unchanged (region ignored for non-stock).
      6. All previous v8.1.3 search cases must still work (regression).

      CHANGES:
      1. /api/search now scans (a) all 7 static maps, (b) LIVE Binance USDT
         universe auto-loaded via /api/v3/exchangeInfo at startup + refreshed
         every 6h, (c) LIVE Bitget spot universe fallback, and (d) returns
         CoinGecko multi-match disambiguation for ambiguous short tickers
         when local hits are weak (e.g. CAT / POPCAT).
      2. get_crypto_snapshot cascade: Binance → Bitget → CoinGecko (all
         with OHLCV so AI signal + chart still work on obscure tokens).
      3. STOCK_US_YAHOO_MAP expanded from 176 → 607 tickers (S&P 500 top,
         Japan Nikkei ~55, China A-shares ~40, HK ~35, Taiwan ~20,
         Malaysia ~20, Singapore ~20, Russia ~10, Korea ~15).
      4. STOCK_YAHOO_MAP IDX expanded from 144 → 157 with user-requested
         low-caps: COCO, DOOH, EMAS, ERAA, IMPC, KETR, KOTA, MSIN, SCMA,
         SINI, SOCI, VKTR, WBSA.
      5. Interactive filter on the 4-item consensus strip: tap PREMIUM
         to filter all columns to premium picks only; tap BUY / HOLD /
         SELL to filter each. Tap the active filter again to clear.
         Visual: 22%-opacity background + coloured border on active chip.

      NOT CHANGED:
      - VipModal, ChatSheet, chat.tsx, AuthContext, subscription* — locked.
      - Dashboard batch loading path (top-50 per market) unchanged.
      - Google Play Billing product IDs / admin unlock — unchanged.

      PLEASE TEST BACKEND:
      1. /api/search?q=X for the following symbols must return hits or
         disambiguation (or both) — NEVER a 5xx:
         - Crypto CEX-listed: BTC, ETH, MOODENG, MEW, BRETT, AAVE, XMR
         - Crypto ambiguous: CAT (should return stock CAT + disambiguation),
           POPCAT (best effort — Bitget/CoinGecko rate limits acceptable)
         - IDX standard: AADI, DSSA, GOTO, BREN, NCKL
         - IDX low-cap: WBSA, COCO, DOOH, ERAA, MSIN, SCMA, VKTR
         - World stocks: TOYOTA, TSMC_TW, TENCENT, DBS, MOUTAI, HSBC,
           SAMSUNG, MAYBANK, SBER
      2. Startup should not crash even if Binance geo-block or Bitget 429.
      3. Dashboard batch endpoint MUST remain fast (< 3s p95) —
         universe loaders run in background task.
      4. GET /api/dashboard?market=stock_us still returns top-50
         (no change from before).

      NOT TO TEST (real Android only):
      - Google Play Billing purchase (1/3/6/12 month plans)
      - Native ChatSheet keyboard
      - Android soft keyboard behaviour


# ============================================================
# v8.12.1 — Formula BTC (regime-aware) & UI Ladder Alert refactor
# ============================================================
backend:
  - task: "Expose entry_moderate_low/high & entry_aggressive_low/high in /api/asset/{market}/{symbol}/chart signal payload"
    implemented: true
    working: "NA"
    file: "/app/backend/indicators.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          v8.12.1 — `compute_signal()` now surfaces the 3-tier entry
          ranges (deep, moderate, aggressive) as low/high floats so the
          frontend `usePriceZoneAlert` hook can trigger ENTRY-1 / ENTRY-2 /
          ENTRY-3 pills independently against the live ticker.
          Verified locally with curl on /api/asset/crypto/BTC/chart?timeframe=1h
          — response now contains entry_low/high, entry_moderate_low/high,
          entry_aggressive_low/high, plus regime (BULL/BEAR/BEAR_CAPITULATION/
          SIDEWAYS/UNKNOWN) and take_profit_2/3 for regime-aware BUY/SELL.

frontend:
  - task: "LadderAlertBadge labels — LONG/SHORT/BUY/SELL 1/2/3 + TP 1/2/3"
    implemented: true
    working: "NA"
    file: "/app/frontend/src/components/LadderAlertBadge.tsx, /app/frontend/app/asset/[market]/[symbol].tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          v8.12.1 — Fixed a broken `META[zone]` reference (only tp1/2/3
          worked before; entry tiers rendered nothing) by wiring both
          TP_META and metaForZone(entry1/2/3) into a single lookup. Labels
          now read:
            • crypto BUY → LONG 1 / LONG 2 / LONG 3
            • crypto SELL → SHORT 1 / SHORT 2 / SHORT 3
            • stocks BUY → BUY 1 / BUY 2 / BUY 3
            • stocks SELL → SELL 1 / SELL 2 / SELL 3
            • TPs → TP 1 / TP 2 / TP 3
          Layout: badge moved from absolute (top:8, left:8) inside the
          chart body to INLINE on the LEFT of the chart-type toggle row
          (right-hand group holds Candlestick + Line). This mirrors the
          user's ETH screenshot request. 700ms stability gate + fade-in
          protections preserved.
  - task: "Pill labels on price-line (CandlestickChart)"
    implemented: true
    working: "NA"
    file: "/app/frontend/src/components/CandlestickChart.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          v8.12.1 — Alert pill riding the live-price line now renders
          user-requested labels: "TP1-Hit!", "TP2-Hit!", "TP3-Hit!",
          "SL-Hit!", "HOLD", "ENTRY-1", "ENTRY-2", "ENTRY-3". Colour
          scheme: SL → red, TP → yellow, HOLD → neutral grey, ENTRY →
          side-tinted (green for BUY, red for SELL). alertZone type
          expanded from {entry|buy1|buy2|buy3|tp1|tp2|tp3|sl} to the
          new {entry1|entry2|entry3|tp1|tp2|tp3|sl|hold} set matching
          usePriceZoneAlert.
  - task: "Wire 3-tier entry ranges from backend into usePriceZoneAlert"
    implemented: true
    working: "NA"
    file: "/app/frontend/app/asset/[market]/[symbol].tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          v8.12.1 — Pass entry_moderate_low/high & entry_aggressive_low/high
          from the /api/asset chart response into usePriceZoneAlert so the
          hook can commit ENTRY-1/2/3 independently.
  - task: "App version bump 8.8.0 → 8.12.1"
    implemented: true
    working: true
    file: "/app/frontend/src/lib/version.ts, /app/frontend/app.json"
    stuck_count: 0
    priority: "low"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: "Bumped version + verified via screenshot."

metadata:
  created_by: "main_agent"
  version: "8.12.1"
  test_sequence: 24
  run_ui: false

test_plan:
  current_focus:
    - "Expose entry_moderate_low/high & entry_aggressive_low/high in /api/asset/{market}/{symbol}/chart signal payload"
    - "LadderAlertBadge labels — LONG/SHORT/BUY/SELL 1/2/3 + TP 1/2/3"
    - "Pill labels on price-line (CandlestickChart)"
    - "Wire 3-tier entry ranges from backend into usePriceZoneAlert"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
  - agent: "main"
    message: |
      v8.12.1 — Please validate the /api/asset/{market}/{symbol}/chart
      endpoint signal payload:
        1. For crypto (BTC, ETH, SOL, XRP, DOGE) with timeframe=1h and
           timeframe=4h: response.signal MUST include ALL of these fields
           as numeric floats (or null for HOLD/stock-like):
             entry_low, entry_high,
             entry_moderate_low, entry_moderate_high,
             entry_aggressive_low, entry_aggressive_high,
             take_profit, take_profit_2, take_profit_3,
             stop_loss, regime, action, confidence, label.
        2. `regime` must be one of BULL / BEAR / BEAR_CAPITULATION /
           SIDEWAYS / UNKNOWN for crypto. Non-crypto (stock_us / stock_id
           / etf / gold_silver) can be UNKNOWN.
        3. When action ∈ {BUY, SELL}: entry_high > entry (deep) and
           entry_aggressive_high > entry_moderate_high (i.e., three
           distinct laddered ranges, not degenerate).
        4. When action = HOLD: take_profit_2 and take_profit_3 may be null;
           this is expected.
        5. Dashboard endpoint (/api/dashboard?market=crypto) must still
           return the standard AssetSignal fields (no regression).
      NOT TO TEST via automated agent: live Binance WS streaming,
      real Google Play billing.

# ============================================================
# v9.0.0 — TOTAL FORMULA OVERHAUL "Confluence" + Dashboard-Detail Sync
# ============================================================
backend:
  - task: "v9.0.0 Confluence formula (indicators.py rewrite)"
    implemented: true
    working: "NA"
    file: "/app/backend/indicators.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          TOTAL REWRITE of compute_signal() per user demand (signal accuracy
          collapsed after v3: "kebanyakan loss, arah tertukar").
          REMOVED: v8.12.24 FLIP inversion (uptrend+overbought→SELL/TP was
          shorting users into bull runs), v8.12.27 pump/dump vetoes,
          multi-horizon near-extreme guards, v3 confidence gate, regime
          presets in level calc.
          NEW: structure spine (EMA fast/slow + price, optional EMA200 for
          swing/longterm), pullback entry zone (±1.5 ATR dari EMA fast),
          RSI health bands (BUY 35-68 / SELL 32-65; veto chase RSI≥72/≤28),
          MACD hist sign+direction, volume expansion, momentum, EMA200 bonus.
          Overextension → HOLD (never counter-trend flip).
          Confidence jujur 50-95 additive (structure 18 + zone 10 + macd
          6-10 + rsi 7 + vol 6 + mom 5 + ema200 5).
          Levels: entry ladder 1.0/0.5/0.2 ATR, SL = sl_mult×ATR per
          profile, TP ladder (1.0, 2.0, 3.0)R — dipilih dari BACKTEST:
          30 hari, 9 aset, 302 trade → TP1=1R WR 57.1% exp +0.136R vs
          TP1=1.5R WR 42.1% exp +0.048R vs formula lama v8 WR 51.8%
          exp +0.03R. Backtest script: /app/backend/backtest_v9.py.
          HOLD emits NO levels (v8.12.28 preserved). Response schema
          unchanged + new indicators.{structure, ema200, volume_ratio,
          momentum_5bar_pct}.
  - task: "Dashboard/Search ↔ Detail signal sync (profile param)"
    implemented: true
    working: "NA"
    file: "/app/backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          Root cause "dashboard DIP/TOP vs detail Sideways": dashboard
          _build_signal() called compute_signal WITHOUT profile (default
          day) while /asset chart passed user's profile → different EMA
          windows → different signals. FIX: ?profile= query param added
          to /api/dashboard, /api/dashboard/batch, /api/search and
          threaded through _build_dashboard_response → _build_signal →
          compute_signal. VERIFIED: 4/4 assets (BTC/ETH/SOL/XRP) identical
          action/label/confidence between batch & chart with profile=swing.
frontend:
  - task: "Frontend passes traderProfile to dashboardBatch + search"
    implemented: true
    working: "NA"
    file: "/app/frontend/src/lib/api.ts, /app/frontend/app/index.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          api.dashboard/dashboardBatch/search accept opts.profile; index.tsx
          load() sends traderProfile + reloads on profile change;
          SearchResults uses useTraderProfile and passes it to api.search.
          Version bumped 8.12.83 → 9.0.0 (version.ts + app.json).
metadata:
  created_by: "main_agent"
  version: "9.0.0"
  test_sequence: 25
  run_ui: false

test_plan:
  current_focus:
    - "v9.0.0 Confluence formula (indicators.py rewrite)"
    - "Dashboard/Search ↔ Detail signal sync (profile param)"
    - "Search returns premium US stocks (TSLA/INTC) — regression check"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
  - agent: "main"
    message: |
      v9.0.0 — PLEASE TEST BACKEND:
      1. /api/asset/crypto/{BTC,ETH,SOL}/chart?timeframe=1h (no profile)
         and with profile=scalper|day|swing|longterm: signal fields
         complete; for BUY/SELL: entry≠None, R:R TP1 ≈ 1.0
         (|tp1-entry| ≈ |entry-sl|), TP2≈2R, TP3≈3R; HOLD → all levels null.
      2. SYNC: /api/dashboard/batch?markets=crypto&profile=X vs
         /api/asset/crypto/{sym}/chart?profile=X → action/label/confidence
         MUST be identical per symbol (do for day + swing).
      3. /api/search?q=TSLA and q=INTC → hits contain stock_us TSLA/INTC
         (regression for user's "premium world stocks missing" report).
      4. /api/search?q=DOT → crypto hit, price has full precision.
      5. No FLIP labels: label set is only LONG/SHORT/BUY/SELL/HOLD —
         never "DIP"/"TP" anymore.
      6. Overextended uptrend (e.g. asset at local top) → HOLD with reason
         "tunggu pullback", NOT SELL.
      7. Regression: /api/dashboard?market=stock_id, /api/profiles,
         /api/subscription/health still OK.
      FRONTEND (light): dashboard loads, search renders hits.
      NOT TO TEST: Google Play billing, native voice notes.

# ============================================================
# v9.1.0 — VWAP Session Engine untuk Trader Profile (formula user)
# ============================================================
backend:
  - task: "VWAP Session Engine (SCALPER/INTRADAY/SWING) di indicators.py"
    implemented: true
    working: "NA"
    file: "/app/backend/indicators.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          User memberikan formula VWAP-based (anchored VWAP dengan reset
          per sesi/UTC-day, box breakout 10/20/50, pola reversal candle,
          deviasi threshold 1.5%). Diimplementasikan PERSIS:
            scalper → SCALPER (box 10, deviasi VWAP + reversal / breakout)
            day     → INTRADAY (box 20, reclaim/rejection VWAP cross)
            swing   → SWING (box 50, breakout + reversal + sisi VWAP)
            longterm → TETAP mesin Confluence v9.0 (EMA 50/100/200).
          Routing di compute_signal: profile scalper/day/swing → mesin
          VWAP di SEMUA market (VWAP memang konsep pasar sesi); fallback
          ke Confluence jika candle tidak punya volume.
          Level untuk mesin VWAP: tier rapat (0 / 0.3 / 0.6 ATR) karena
          sinyal = pemicu entry; SL sl_mult×ATR per profil; TP 1R/2R/3R.
          Stocklike tetap varian persentase. Schema response identik +
          indicators baru: vwap, price_dev_pct, box_high/low, flags.
          BACKTEST 30 hari (9 aset, 1h): scalper WR 56.0% +0.119R
          (462 trade, +55R) · day WR 50.9% +0.017R · swing WR 48.6%
          (40 trade, sampel kecil) · longterm confluence 49.5%.
          Guard longterm diperbaiki (snapshot 100 candle < EMA100+5
          membuat longterm selalu HOLD — sekarang cukup >= EMA period).
frontend:
  - task: "Trader Profile descriptions untuk mesin VWAP"
    implemented: true
    working: "NA"
    file: "/app/frontend/src/lib/useTraderProfile.ts"
    stuck_count: 0
    priority: "medium"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: "PROFILE_META descriptions diperbarui (VWAP deviasi/box/reclaim). Version bump 9.1.0."
metadata:
  created_by: "main_agent"
  version: "9.1.0"
  test_sequence: 26
  run_ui: false

test_plan:
  current_focus:
    - "VWAP Session Engine (SCALPER/INTRADAY/SWING) di indicators.py"
    - "Sync dashboard-detail dengan mesin VWAP per profile"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
  - agent: "main"
    message: |
      v9.1.0 — PLEASE TEST BACKEND:
      1. GET /api/asset/crypto/{BTC,ETH,SOL}/chart?timeframe=1h&profile=X
         untuk X in scalper|day|swing|longterm:
         - scalper/day/swing → indicators.vwap_engine == SCALPER/INTRADAY/
           SWING, indicators.vwap non-null, price_dev_pct numerik.
         - longterm → confluence (tidak ada vwap_engine).
         - Schema lengkap: action/label/confidence/reasons/entry/levels;
           HOLD → semua level null; BUY/SELL → level non-null.
      2. SYNC: /api/dashboard/batch?markets=crypto&profile=scalper vs
         /api/asset/crypto/{sym}/chart?profile=scalper → action/label/
         confidence identik per simbol.
      3. Stock path: /api/asset/stock_id/BBCA/chart?profile=day → 200,
         engine INTRADAY, level persentase wajar (entry dekat harga).
      4. Regresi: /api/search?q=TSLA, /api/dashboard?market=stock_us,
         /api/subscription/health.
      FRONTEND (light): dashboard load, trader profile modal menampilkan
      deskripsi baru.

# ============================================================
# v9.2.0 — Master 15-Video Formula (John Wick + Power of Tower)
# ============================================================
backend:
  - task: "Upgrade mesin VWAP ke Master 15-Video Formula"
    implemented: true
    working: "NA"
    file: "/app/backend/indicators.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          User memberikan Master Engine (gabungan 15 video): VWAP core +
          Separator (deviasi/mean-reversion) + KISS Pivot (bounce di VWAP)
          + John Wick (wick >= 60% range) + Power of Tower (impulsive body
          > 80% range lalu retrace 50%) + Box Theory + profile filters.
          Diimplementasikan persis versi Python backend:
            bull_rev = std_bull OR john_wick_bull OR power_of_tower_bull
            bear_rev = std_bear OR john_wick_bear OR power_of_tower_bear
          Confidence: +8 reversal, +6 John Wick, +6 Power of Tower.
          indicators baru: john_wick(_bull/_bear), power_of_tower(_bull/_bear).
          Trigger reasons menyebut nama pola yang menyala.
          UNIT TESTED: SCALPER BUY pada deviasi -1.52% + John Wick bull ✓;
          deteksi PoT bull ✓ (retrace 50% setelah impulsive red).
          BACKTEST 30d (9 aset): scalper 55.3% WR +50R · day 51.4% +12R
          · swing 51.3% +1R — semua ≥ v9.1.0.
metadata:
  created_by: "main_agent"
  version: "9.2.0"
  test_sequence: 27
  run_ui: false

test_plan:
  current_focus:
    - "Master 15-Video Formula: pola John Wick & Power of Tower aktif di sinyal live"
    - "Regresi sync dashboard-detail + search"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
  - agent: "main"
    message: |
      v9.2.0 — quick verification saja (fokus regresi):
      1. /api/asset/crypto/{BTC,ETH}/chart?profile=scalper|day|swing →
         200, schema lengkap, indicators.vwap_engine sesuai, indicators
         punya john_wick & power_of_tower flags.
      2. Sync batch vs chart untuk profile=day (2-3 simbol cukup).
      3. Regresi: /api/search?q=TSLA, /api/dashboard?market=stock_id.
      Frontend: dashboard load normal, Ver 9.2.0 di header.

# ============================================================
# v9.3.0 — Trader Profile jadi TOGGLE (unselect → Confluence v9.0)
# ============================================================
backend:
  - task: "VWAP engine hanya aktif saat profile eksplisit dipilih"
    implemented: true
    working: true
    file: "/app/backend/indicators.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          Permintaan user: tanpa pilihan profile → formula Confluence
          v9.0.0; hanya scalper/day/swing yang dipilih eksplisit → mesin
          VWAP. Routing diubah: `if profile in _PROFILE_TO_VWAP` (None
          tidak lagi di-default ke "day"). VERIFIED: tanpa profile →
          CONFLUENCE (BTC SELL/95), profile=scalper → SCALPER engine,
          sync batch vs chart tanpa profile = 0 mismatch.
frontend:
  - task: "Toggle unselect di TraderProfileModal + apiProfile null"
    implemented: true
    working: true
    file: "/app/frontend/src/lib/useTraderProfile.ts, /app/frontend/src/components/TraderProfileModal.tsx, /app/frontend/app/index.tsx, /app/frontend/app/asset/[market]/[symbol].tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          Hook: state _explicit (true hanya jika storage punya nilai /
          user memilih). setProfile toggle: ketuk profil aktif → unselect
          (remove AsyncStorage key). apiProfile = null saat tidak eksplisit
          → semua call API (dashboardBatch, search, chart, analyze) tidak
          mengirim ?profile=. Header pill: 🧠 + border netral saat default,
          emoji profil saat aktif. Modal: kartu tidak tercentang saat
          unselect, modal tetap terbuka, footer hint baru. E2E screenshot
          flow PASSED: Default→Scalper→unselect→Default. Ver 9.3.0.
metadata:
  created_by: "main_agent"
  version: "9.3.0"
  test_sequence: 28
  run_ui: false

agent_communication:
  - agent: "main"
    message: |
      v9.3.0 — Trader Profile toggle. Diverifikasi main agent via
      e2e screenshot flow + backend matrix curl. Tidak perlu retest
      kecuali user laporkan masalah.

# ============================================================
# v9.1.2 — Fix Premium Badge Hilang (rekalibrasi confidence & gate)
# ============================================================
backend:
  - task: "Premium badge kembali muncul di semua kolom"
    implemented: true
    working: true
    file: "/app/backend/indicators.py, /app/backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          User report: "premium badge hanya ada di kolom forex saja".
          ROOT CAUSE ganda:
          1. Mesin VWAP (scalper/day/swing) confidence mentok di ~79
             (base 55) → tak pernah lolos gate premium 85-90. Forex lolos
             karena fallback ke Confluence (tanpa volume). FIX: trigger
             utama engine +14, base 58 → setup kuat mencapai 85-95.
          2. Gate premium v8: tanpa histori WR butuh conf >= min_conf+5
             (92-95) DAN min_wr 72-75% — dikalibrasi untuk formula v1,
             mustahil untuk confidence jujur v9. FIX: threshold →
             (85, 55) mayoritas market; bar tanpa-histori +3.
          HASIL (batch 5 market): tanpa profile 56 premium (7 crypto,
          6 US, 20 IDX, 9 ETF, 14 forex) · scalper 36 (18 crypto) ·
          day 18 · swing 14. stock_us 0 di mode VWAP = kondisi trigger
          memang belum menyala sesi ini (dev 1.5%/box-10 jarang tercapai
          intraday saham) — bukan bug.
metadata:
  created_by: "main_agent"
  version: "9.1.1"
  test_sequence: 29
  run_ui: false

# ============================================================
# v9.1.3 — Fix sinyal berkedip HOLD↔SHORT tiap beberapa detik
# ============================================================
backend:
  - task: "Sinyal hanya dari candle TUTUP (drop forming candle)"
    implemented: true
    working: true
    file: "/app/backend/indicators.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          User: "ETH di dashboard HOLD sebentar lalu SHORT lalu HOLD lagi
          dalam beberapa detik". Root cause: candle terakhir yang masih
          BERJALAN ikut dihitung — kondisi cross VWAP / box breakout /
          pola wick / momentum berubah tiap detik mengikuti harga live.
          FIX: _drop_forming_candle() di awal compute_signal — umur bar
          terakhir < 1 spacing → dibuang dari perhitungan (standar
          industri, Pine barstate.isconfirmed). Backtest tidak terpengaruh
          (candle historis selalu lebih tua dari 1 bar). VERIFIED: 4 poll
          beruntun ETH → identik SELL/SHORT/91, harga sinyal tetap di
          candle tutup 2683.58 sementara live ticker bergerak 2691→2692.
frontend:
  - task: "Gate fetch pertama hingga Trader Profile termuat"
    implemented: true
    working: true
    file: "/app/frontend/app/index.tsx, /app/frontend/app/asset/[market]/[symbol].tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          Kedipan kedua saat startup: app boot memakai Confluence (profile
          belum termuat dari AsyncStorage) lalu beberapa detik kemudian
          beralih ke VWAP setelah storage terbaca. FIX: dashboard load()
          dan detail loadChart() di-gate `if (!profileLoaded) return` +
          profileLoaded masuk deps useEffect.
metadata:
  created_by: "main_agent"
  version: "9.1.2"
  test_sequence: 30
  run_ui: false

# ============================================================
# v9.1.4 — Fix indikator "ngawur" (EMA — / MACD 0.0000) di mesin VWAP
# ============================================================
backend:
  - task: "Panel indikator lengkap di mesin VWAP + level anchor live"
    implemented: true
    working: true
    file: "/app/backend/indicators.py, /app/backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          User murka: "indikator ngawur". Dua bug:
          1. Mesin VWAP tidak mengirim ema20/ema50/macd_hist → panel
             Sinyal Teknikal menampilkan "—" dan "0.0000". FIX: hitung
             EMA (window profil) + MACD hist di jalur VWAP. VERIFIED:
             LINK scalper → EMA20 13.289 / EMA50 13.173 / MACD 0.0055.
          2. Level entry/SL/TP dihitung dari candle TUTUP → saat harga
             bergerak cepat, semua TP berada di sisi salah vs harga live
             (LINK: TP 13.39-13.45 vs live 13.31 untuk SHORT). FIX:
             compute_signal terima live_price (ticker) → level di-anchor
             ke harga realtime (guard ±8 ATR). Arah sinyal tetap dari
             candle tutup (stabilitas terjaga).
frontend:
  - task: "TargetProfit pakai ladder backend TP1/TP2/TP3 apa adanya"
    implemented: true
    working: true
    file: "/app/frontend/src/components/TargetProfit.tsx, /app/frontend/app/asset/[market]/[symbol].tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          Kartu Target Profit menginterpolasi TP1/TP2 sendiri (40%/70%
          dari backend TP yang dianggap TP3) → angka berbeda dengan kartu
          Sinyal Teknikal & garis chart. FIX: props takeProfit2/3 baru;
          bila ladder backend valid & berurutan → tampilkan apa adanya;
          R:R kini terhadap TP1. Fallback interpolasi tetap untuk kartu
          AI consensus.
metadata:
  created_by: "main_agent"
  version: "9.1.3"
  test_sequence: 31
  run_ui: false

# ============================================================
# v9.1.4 (lanjutan) — Audit menyeluruh semua mode + EMA label dinamis
# ============================================================
backend:
  - task: "Audit 5 mode × 4 aset + longterm crypto fix + label EMA dinamis"
    implemented: true
    working: true
    file: "/app/backend/indicators.py, /app/backend/market_data.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          User: "periksa yang teliti — Entry, SL, TP1/2/3 harus sinkron
          dengan indikator sesuai selector / non-selector".
          AUDIT OTOMATIS 20 kombinasi (5 mode × LINK/ETH/BBCA/AAPL):
          indikator lengkap (RSI/EMA/MACD), ladder berurutan sesuai arah,
          R:R TP1≈1R, entry dekat harga live, HOLD tanpa level → 0 isu
          riil. FIX: (1) longterm crypto sebelumnya HOLD kosong karena
          snapshot 100 candle < EMA100 setelah forming-drop → limit
          candle dinaikkan 100→250 (TIMEFRAME_MAP) → EMA200 kini aktif,
          BTC/ETH longterm BUY 95%. (2) indicators mengirim ema_fast_n/
          ema_slow_n; label UI detail mengikuti (scalper=EMA9/EMA21).
          VISUAL VERIFIED: scalper LINK LONG 95% — ENTRY 13.0627-13.1328,
          SL 12.8639, TP 13.3315, Target3 13.7991 (1R/2R/3R persis),
          badge Risk -1.8%/Target +1.78% konsisten.
          UpdatePrompt diverifikasi utuh (index.tsx:1258, /api/app-version
          merespons latest_version 8.12.83 < 9.1.3 → nag tidak tampil
          untuk build terbaru, sesuai desain).
metadata:
  created_by: "main_agent"
  version: "9.1.3"
  test_sequence: 32
  run_ui: false

# ============================================================
# v9.1.6 — US stock universe lengkap (BNY/GEV/HONA + S&P 500/400/600)
# ============================================================
backend:
  - task: "Search-only US universe dari NASDAQ Trader resmi"
    implemented: true
    working: true
    file: "/app/backend/market_data.py, /app/backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          User report: "Saham US tidak muncul saat search: BNY, GEV, HONA;
          periksa semua big 200 US & S&P1000". Ketiganya memang tidak ada
          di map lama (810 ticker). FIX: bangun STOCK_US_YAHOO_MAP_EXTRA
          (5.256 ticker) dari sumber RESMI nasdaqtrader.com
          (nasdaqlisted.txt + otherlisted.txt, filter: bukan test issue,
          bukan ETF, bukan warrant/unit/preferred/notes) + S&P 500 CSV.
          Search-only: dashboard full=true tetap memakai 810 kurasi agar
          Yahoo batch fetch tidak kelebihan beban. Patch: search pool
          stock_us gabung EXTRA; get_stock_snapshot & region_for_symbol
          fallback ke EXTRA. VERIFIED: search BNY (150.19 SELL),
          GEV (955.04 BUY), HONA (158.46 HOLD) muncul sebagai stock_us di
          atas token crypto sejenis. S&P500 coverage 503/503 ✓. Sampling
          mid/small-cap (CROX, MSTR, SMCI, DUOL, WING, dst) 20/20 ✓.
          Sampling acak 6 ticker EXTRA via search API: 6/6 harga+sinyal
          valid. BNY chart endpoint OK (155 candle, SELL 91).
          Total universe US: 6.066 ticker.
metadata:
  created_by: "main_agent"
  version: "9.1.5"
  test_sequence: 33
  run_ui: false

# ============================================================
# v9.2.0 — Formula 68-Video + AI Suggestions (premium) + gating member
# ============================================================
backend:
  - task: "Modul 68-video: bias 50 SMA harian + liquidity + choke 3R + Pattern Scalp 15M"
    implemented: true
    working: true
    file: "/app/backend/indicators.py, /app/backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          Formula gabungan user (15+53 video) diintegrasikan ke 3 mesin
          VWAP: (1) Macro bias 50 SMA harian — searah: conf +6; lawan arah:
          SCALPER half-risk (-12), INTRADAY/SWING → HOLD; (2) Liquidity
          zones (PDH/PDL, swing H/L 10d, daily ATR) di indicators;
          (3) Choke Risk Protection: TP1 > 80% Daily ATR → HOLD;
          (4) Pattern Scalp 15M (manipulasi open ≥20% Daily ATR + John
          Wick wick>2xbody / Power of Tower) override untuk SCALPER di
          TF <=15m dengan level persis formula. Candle harian via
          _get_daily_candles (cache 4 jam).
  - task: "Endpoint /api/ai-suggestions (premium-only)"
    implemented: true
    working: true
    file: "/app/backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          GET /api/ai-suggestions?market=&profile=&device_id= → top-10
          aset bersinyal aktif (sort confidence) lengkap Entry/SL/TP1-3.
          Gate: entitled via subscriptions ATAU unlock_codes (admin) —
          keduanya dicek (fix: awalnya unlock-code user kena 403).
          AssetSignal model + take_profit_2/3. Verified: anon 403,
          device entitled 200 dengan 10 saran valid.
frontend:
  - task: "AI Suggestions sheet + Trader Profile premium-only + Confluence-only utk non-member"
    implemented: true
    working: true
    file: "/app/frontend/src/components/AISuggestionsSheet.tsx, TraderProfileModal.tsx, app/index.tsx, deviceId.ts"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          - Tombol profil di header: non-premium → 🔒 + paywall.
          - Modal Trader Profile berisi CTA emas "AI SUGGESTIONS PREMIUM"
            (desain dari design_agent, /app/design_guidelines.json).
          - Sheet AI Suggestions: chip kategori (6 market) → daftar aset
            berperingkat (rank, symbol, harga+24h%, chip LONG/SHORT,
            CONF emas) → tap expand grid berdivider (Entry Zone, SL,
            TP1/2/3, R:R, Bias Harian, alasan, tombol Buka Detail Aset).
            Loading skeleton, empty state, locked state blur + CTA emas.
          - Non-premium SELALU Confluence: profile tak dikirim ke
            dashboard/search/chart/analyze walau tersimpan.
          - Fix deviceId web: localStorage langsung (shim SecureStore web
            bikin id ephemeral → entitlement gagal di preview).
          - E2E screenshot PASSED: modal → CTA → sheet 10 kartu → expand
            ETH SHORT 95% (Entry 2691-2696, SL 2707, TP 2680/2667/2653).
metadata:
  created_by: "main_agent"
  version: "9.1.5"
  test_sequence: 34
  run_ui: false

# ======================================================
# v9.7.6 — Independent Semi/Full State + Manual Close
# ======================================================
backend_v976:
  - task: "Independent semi_enabled / full_enabled flags on BotConfig"
    implemented: true
    working: "NA"
    file: "/app/backend/asi_bot/routes.py, /app/backend/asi_bot/scheduler.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          BotConfigPayload sudah memiliki semi_enabled/full_enabled (v9.7.5).
          v9.7.6 — scheduler.py _run_full_auto_scanner diupdate: query
          sekarang {"$or":[{"full_enabled":True},{"enabled":True,"mode":"full",
          "full_enabled":{"$exists":False}}]} agar scanner HANYA jalan jika
          full_enabled True, dan tetap backward-compat utk doc lama.
          _enforce_daily_loss_limit juga sudah pakai $or (semua tetap bekerja).
  - task: "POST /asi/trades/{trade_id}/close manual close endpoint"
    implemented: true
    working: "NA"
    file: "/app/backend/asi_bot/routes.py (sudah ada), engine.py (close_position + cancel_all_conditional)"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          Endpoint sudah ada (v9.7.5). v9.7.6 — list_trades sekarang
          mengembalikan _id (str) agar frontend bisa memanggil close.
          Verifikasi smoke test lokal: POST ke trade non-exist → 404 "trade not found".
  - task: "list_trades mengembalikan _id string untuk CLOSE button"
    implemented: true
    working: "NA"
    file: "/app/backend/asi_bot/routes.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          GET /asi/trades sekarang menyertakan _id (sebelumnya di-pop)
          sehingga tombol CLOSE di Recent Trades punya identifier.
frontend_v976:
  - task: "Dua StatusCard independen (Semi hijau / Full orange)"
    implemented: true
    working: "NA"
    file: "/app/frontend/app/asi-bot.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          Komponen StatusCard baru menampilkan kartu Semi dan Full secara
          independen. Masing-masing punya START (pink) + STOP (light blue)
          sendiri. Dapat aktif bersamaan. Border aktif = hijau (semi) /
          orange (full). Verified screenshot: dua kartu tampil STOPPED.
  - task: "Recent Trades: badge SEMI/FULL + tombol CLOSE merah"
    implemented: true
    working: "NA"
    file: "/app/frontend/app/asi-bot.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          Tiap row trade menampilkan 2 badge (mode SEMI/FULL warna hijau/orange
          + status OPEN/CLOSED). Tombol CLOSE merah muncul HANYA untuk trade
          status=open; onPress langsung memanggil api.asi.closeTrade (tanpa
          dialog konfirmasi sesuai permintaan user), menampilkan state
          "closing…" selama request berjalan, lalu refresh daftar trade.
          Error ditangkap dan Alert dengan i18n "asi_close_failed".
  - task: "closeTrade() helper + types updated"
    implemented: true
    working: "NA"
    file: "/app/frontend/src/lib/api.ts"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          api.asi.closeTrade(deviceId, tradeId) ditambah. AsiBotConfig +
          AsiTradeResp diperluas dengan semi_enabled/full_enabled/mode/_id.
  - task: "i18n keys baru (EN/ID/RU/CN) utk kartu + close button"
    implemented: true
    working: "NA"
    file: "/app/frontend/src/i18n/I18nContext.tsx"
    stuck_count: 0
    priority: "medium"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          Keys baru: asi_card_semi_title, asi_card_full_title,
          asi_card_(semi|full)_sub_(on|off), asi_recent_close,
          asi_recent_closing, asi_badge_semi, asi_badge_full,
          asi_close_failed, asi_hint_concurrent.
metadata_v976:
  created_by: "main_agent"
  version: "9.7.6"
  test_sequence: 35
  run_ui: false

# ======================================================
# v9.7.6a — SATU kartu status di atas (pivot user)
# ======================================================
frontend_v976a:
  - task: "Satu box di atas yang berganti mengikuti tombol mode"
    implemented: true
    working: "NA"
    file: "/app/frontend/app/asi-bot.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          User menolak 2 kartu berdampingan. v9.7.6a — hanya SATU
          StatusCard dirender di paling atas; properti `kind` digerakkan
          oleh `bot.mode` yang berubah saat user menekan chip Semi-Auto /
          Full-Auto di seksi Mode di bawahnya. Border aktif = hijau
          (semi) / orange (full); badge SEMI / FULL di pojok kanan;
          START (pink) + STOP (light blue) per-mode tapi hanya SATU yang
          kelihatan sesuai mode terpilih. Backend tetap simpan
          semi_enabled + full_enabled independen sehingga kedua state
          tetap berjalan bersamaan walau UI hanya menampilkan salah satu.
          Verified via 2 screenshot: semi-active dan full-active berganti.

# ======================================================
# v9.7.7 — Semi READY mode + persistent disclaimer + fixes
# ======================================================
backend_v977:
  - task: "disclaimer_ack persistent di BotConfigPayload"
    implemented: true
    working: "NA"
    file: "/app/backend/asi_bot/routes.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          Field disclaimer_ack:bool default False ditambah ke BotConfigPayload.
          Smoke test lokal: POST dgn disclaimer_ack=true tersimpan; GET mengembalikan true.
  - task: "Fix phantom-close pada refresh_trade_pnl (engine.py)"
    implemented: true
    working: "NA"
    file: "/app/backend/asi_bot/engine.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          Sebelumnya: fetch_positions gagal → treat sebagai "closed" via SL fallback
          (hasilkan phantom close & PnL palsu).
          v9.7.7: hanya tandai closed jika fetch SUKSES & return list kosong.
          Jika fetch gagal, status tetap "open", pnl_usdt tidak berubah.
  - task: "live_leaderboard sort by unrealized_pct (hanya posisi profit)"
    implemented: true
    working: "NA"
    file: "/app/backend/asi_bot/pnl.py"
    stuck_count: 0
    priority: "medium"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          Pipeline aggregate: match unrealized_usdt > 0, lalu enrich dgn
          unrealized_pct (pnl/margin*100), filter pct > 0, sort desc by pct,
          assign rank. Verified via curl: rank 1 = 103.75%, rank 2 = 8.38%.
frontend_v977:
  - task: "Semi-Auto READY mode (no STOP) + PICK A SIGNAL button"
    implemented: true
    working: "NA"
    file: "/app/frontend/app/asi-bot.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          Komponen StatusCard dirombak: untuk kind='semi' render SATU tombol
          Pink "🎯 PICK A SIGNAL" yang membuka AISuggestionsSheet. Status
          text selalu "READY" (hijau), tidak pernah STOPPED. Full-Auto tetap
          2 tombol START (pink) + STOP (light blue).
          Border card: Semi selalu hijau accent; Full border hijau-orange hanya saat running.
          Screenshot verified: Semi menampilkan "SEMI-AUTO · READY" + 1 tombol pink;
          Full menampilkan "FULL-AUTO · STOPPED" + 2 tombol START/STOP.
  - task: "AsiTradeSheet duplicate-position confirm dialog"
    implemented: true
    working: "NA"
    file: "/app/frontend/src/components/AsiTradeSheet.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          Sebelum executeTrade, panggil api.asi.listTrades, cari OPEN trade
          dengan symbol+exchange yang sama. Jika ketemu → Alert konfirmasi
          "Posisi Sudah Terbuka — Anda sudah punya posisi SIDE SYMBOL aktif
          di EXCHANGE (PnL $X). Tambah posisi lagi (pyramid)?" dengan Batal / Ya,tambah.
  - task: "Disclaimer baca dari backend bot.disclaimer_ack (persistent)"
    implemented: true
    working: "NA"
    file: "/app/frontend/app/asi-bot.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          State local `disclaimerAck` DIHAPUS. canUseBot = activeCred && bot.disclaimer_ack.
          Box disclaimer hanya tampil jika !bot.disclaimer_ack. onPress checkbox
          langsung memanggil saveBot({disclaimer_ack:true}) → tersembunyi selamanya.
  - task: "AISuggestionsSheet mounted di asi-bot page"
    implemented: true
    working: "NA"
    file: "/app/frontend/app/asi-bot.tsx"
    stuck_count: 0
    priority: "medium"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          Import AISuggestionsSheet, state suggestOpen, dirender di akhir
          komponen setelah ConnectExchangeModal. onClose → setSuggestOpen(false) + refresh.
  - task: "Copy-trade leaderboard: % jadi metrik utama (angka besar)"
    implemented: true
    working: "NA"
    file: "/app/frontend/app/copy-trade.tsx"
    stuck_count: 0
    priority: "medium"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          Angka % font 20 (metrik utama), $ font 11 (sub-metrik di bawah).
          Backend sudah filter + sort by % desc.
metadata_v977:
  created_by: "main_agent"
  version: "9.7.7"
  test_sequence: 36
  run_ui: false

# ======================================================
# v9.7.8 — AI Suggestions one-tap EXECUTE SEMI-AUTO polish
# ======================================================
frontend_v978:
  - task: "AI Suggestions trade button: pink Semi badge + localized text"
    implemented: true
    working: "NA"
    file: "/app/frontend/src/components/AISuggestionsSheet.tsx"
    stuck_count: 0
    priority: "medium"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          Tombol "🤖 Trade with ASI-Bot" diganti jadi tombol pink (#EC4899)
          dengan badge "SEMI" (translucent putih) + teks "⚡ EXECUTE SEMI-AUTO"
          yang terlokalisasi (id/en/ru/cn via asi_badge_semi + ai_trade_execute_semi).
          Flow tetap sama: tap → setTradeIntent → AsiTradeSheet → executeTrade(mode=semi)
          → trade tersimpan ke /api/asi/trades dgn mode=semi.
  - task: "AsiTradeSheet success Alert dengan 'Lihat Recent Trades' action"
    implemented: true
    working: "NA"
    file: "/app/frontend/src/components/AsiTradeSheet.tsx"
    stuck_count: 0
    priority: "medium"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          Setelah executeTrade sukses, Alert menampilkan 2 tombol:
          "Lihat Recent Trades" → router.push("/asi-bot") &
          "Tutup" → onClose. Terlokalisasi via asi_exec_view_recent/common_close.
          useI18n hook ditambah ke komponen.
metadata_v978:
  created_by: "main_agent"
  version: "9.7.8"
  test_sequence: 37
  run_ui: false

# ======================================================
# v9.7.9 — TraderProfileModal UX fixes (user report)
# ======================================================
frontend_v979:
  - task: "Modal TIDAK auto-close setelah pilih profil"
    implemented: true
    working: true
    file: "/app/frontend/src/components/TraderProfileModal.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          BUG: pick() memanggil setTimeout(onClose, 180) → modal langsung
          menutup setelah pilih Scalper/Day/Swing. FIX: hapus auto-close;
          modal tetap terbuka, user bisa langsung tap tombol AI SUGGESTIONS.
          Verified Playwright: MODAL STILL OPEN AFTER PICK = True.
  - task: "Long-term / default Confluence bisa buka AI Suggestions"
    implemented: true
    working: true
    file: "/app/frontend/src/components/TraderProfileModal.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          BUG: gate aiProfileReady hanya izinkan scalper/day/swing —
          longterm & default (no profile) dapat popup "Select a Trader
          Profile First". FIX: gate dihapus total; AI Suggestions selalu
          membuka sheet. Backend sudah map profile non-VWAP → engine
          CONFLUENCE (server.py:803 + skip daily fetch di :1090), jadi
          aset Confluence selalu tersedia. Popup + style warn* dihapus;
          i18n ai_profile_required_* diganti ai_profile_footer_hint.
          Verified Playwright: WARN POPUP SHOWN = False; sheet terbuka
          (premium lock muncul untuk device non-premium — by design).
metadata_v979:
  created_by: "main_agent"
  version: "9.7.9"
  test_sequence: 38
  run_ui: false

# ======================================================
# v9.8.0 — THREE user-reported bugs FIXED (iter 34 ALL PASS)
# ======================================================
frontend_v980:
  - task: "Bug 1: AI Suggestions missing EXECUTE SEMI-AUTO button"
    implemented: true
    working: true
    file: "/app/frontend/src/components/AISuggestionsSheet.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          ROOT CAUSE: filter cek a.take_profits (plural array) tapi backend
          kirim a.take_profit / take_profit_2 / take_profit_3 (singular 3 field).
          FIX: normalize ke tps[] array; button pindah ke card body utama
          (tidak perlu tap expand); testID ai-trade-{symbol}.
          Verified iter34: 6 tombol pink muncul di semua crypto cards.
  - task: "Bug 2: PICK A SIGNAL selalu kirim profile=confluence"
    implemented: true
    working: true
    file: "/app/frontend/app/asi-bot.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          ROOT CAUSE: pickTopSignal baca bot.profile (backend config, default
          confluence), bukan useTraderProfile() hook yang user pilih di header.
          FIX: import useTraderProfile; map scalper/day/swing explicit → kirim
          apa adanya; longterm/default → confluence. useEffect auto-sync
          bot.profile ke backend saat traderProfile berubah (sehingga Full-Auto
          scheduler juga pakai profil yang benar). Pesan error "No valid signal"
          kini menampilkan nama profile yang BENAR, bukan selalu CONFLUENCE.
          Verified iter34: engine=VWAP-SCALPER saat trader-profile=scalper.
  - task: "Bug 3: Alert 'need_connect' muncul walau Binance tersambung"
    implemented: true
    working: true
    file: "/app/frontend/app/asi-bot.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          ROOT CAUSE: race condition — user tap PICK A SIGNAL sebelum
          refresh() selesai mengisi state creds. activeCred undefined →
          alert menyesatkan.
          FIX: tambah credsLoaded flag di-set true di finally{} refresh().
          pickTopSignal: `if (credsLoaded && !canUseBot)` — hanya tampilkan
          alert setelah fetch kredensial pertama selesai.
metadata_v980:
  created_by: "main_agent"
  version: "9.8.0"
  test_sequence: 39
  run_ui: false

# ======================================================
# v9.8.1 — PICK A SIGNAL = popup daftar aset + EXECUTE per aset
# ======================================================
frontend_v981:
  - task: "PICK A SIGNAL buka popup list aset dengan tombol EXECUTE"
    implemented: true
    working: true
    file: "/app/frontend/app/asi-bot.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          User request: PICK A SIGNAL harus membuka popup window berisi
          daftar aset yang sudah di-scan sesuai Trader Profile, dengan
          tombol EXECUTE langsung di samping tiap aset.
          FIX: pickTopSignal (auto-pick top-1) DIGANTI dgn openSignalPicker
          yang membuka AISuggestionsSheet (sudah punya list + tombol
          EXECUTE SEMI-AUTO per kartu sejak v9.8.0). Sheet sudah membaca
          useTraderProfile secara internal → aset difilter sesuai profil.
          Guard dilonggarkan: melihat sinyal TIDAK butuh koneksi exchange
          (eksekusi tetap dijaga AsiTradeSheet dgn CTA HUBUNGKAN EXCHANGE);
          hanya disclaimer_ack yang wajib (bypass __DEV__ untuk preview).
          State tradeIntent/scanning + AsiTradeSheet mount di asi-bot.tsx
          dihapus (sudah di-handle internal sheet).
          Verified Playwright: tap PICK A SIGNAL → popup muncul,
          10 tombol ai-trade-* terdeteksi (APT/ARB/OP/INJ/RENDER...).
metadata_v981:
  created_by: "main_agent"
  version: "9.8.1"
  test_sequence: 40
  run_ui: false

# ======================================================
# v9.8.2 — Whitelist Top-100 DIHAPUS (user report: STX blocked)
# ======================================================
backend_v982:
  - task: "Hapus batasan whitelist Top-100 dari preview/execute"
    implemented: true
    working: true
    file: "/app/backend/asi_bot/engine.py, routes.py, whitelist.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          USER REPORT: tombol EXECUTE abu-abu dengan error
          "STX tidak di whitelist Top-100" — user minta tidak dibatasi 100 aset.
          FIX: gate statis is_allowed() DIHAPUS dari routes preview/execute
          dan engine.preview_trade/execute_trade. Diganti validasi DINAMIS
          _ensure_tradable(client, exch_sym, base): load_markets dari
          exchange user → simbol boleh dieksekusi SELAMA benar-benar listed
          & aktif sebagai perpetual USDT (STX di Binance = valid).
          Jika load_markets gagal (network), tidak memblokir — biarkan
          exchange yang memvalidasi saat order placement.
          TOP_100_FUTURES tetap dipakai scheduler sebagai default scan
          universe (bukan batasan trade).
          Curl-verified: STX preview tidak lagi 400 whitelist → 404 connect
          (perilaku benar untuk device tanpa kredensial).
metadata_v982:
  created_by: "main_agent"
  version: "9.8.2"
  test_sequence: 41
  run_ui: false

# ======================================================
# v9.8.3 — Full i18n AsiTradeSheet + futures_tradable flag
# ======================================================
backend_v983:
  - task: "engine._ensure_tradable return reason code + ai-suggestions annotate futures_tradable"
    implemented: true
    working: true
    file: "/app/backend/asi_bot/engine.py, /app/backend/asi_bot/whitelist.py, /app/backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          _ensure_tradable kini return (reason, message): not_listed |
          market_inactive. preview_trade/execute_trade menyertakan reason di
          dict response. whitelist.py: tambah binance_perp_tradable() —
          fetch public /fapi/v1/exchangeInfo via proxy, cache 10 menit,
          return set base-symbols status TRADING. server.py ai-suggestions:
          annotate tiap sinyal crypto dgn futures_tradable (None = jangan
          filter). Verified curl: semua sinyal aktif futures_tradable=True.
frontend_v983:
  - task: "Lokalisasi penuh AsiTradeSheet (4 bahasa) + reason mapping"
    implemented: true
    working: true
    file: "/app/frontend/src/components/AsiTradeSheet.tsx, I18nContext.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          20+ string hardcoded diganti t(): subtitle, no-cred state, stepper
          labels (Risk/Leverage/Trailing), preview rows (Saldo/Margin/Ukuran/
          Potensi Rugi/TP Profit), footer, tombol EXECUTE/sending, dialog
          duplikat pyramid, alert gagal, error not_listed/market_inactive
          (pakai reason code backend + {symbol} placeholder).
          AISuggestionsSheet: aset futures_tradable=false → note abu-abu
          "ai_not_tradable" menggantikan tombol EXECUTE. Screenshot-verified:
          sheet tampil "Not connected to an exchange / CONNECT EXCHANGE"
          dalam English sesuai locale.

# ======================================================
# v9.8.4 — CLOSE button untuk SEMUA posisi open (user report)
# ======================================================
backend_v984:
  - task: "POST /asi/trades/close-by-symbol fallback endpoint"
    implemented: true
    working: true
    file: "/app/backend/asi_bot/routes.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          User report: sebagian posisi open tidak punya tombol CLOSE.
          Penyebab: row tanpa _id (response backend lama men-strip _id)
          membuat tombol disabled abu-abu; juga row yg keliru 'closed'
          (phantom-close pra-v9.7.7 di produksi) padahal posisi masih
          terbuka di exchange.
          FIX backend: endpoint close-by-symbol — cari trade open
          (case-insensitive) utk symbol+exchange; bila tidak ada, pakai
          row terakhir utk side/qty lalu close_position tetap membaca
          posisi REAL exchange (menutup residual yg DB-nya sudah closed).
          Semua trade open utk symbol itu ditandai closed/manual.
          Curl-verified: 404 benar utk symbol tanpa trade.
frontend_v984:
  - task: "CLOSE button selalu aktif utk open + fallback by-symbol"
    implemented: true
    working: true
    file: "/app/frontend/app/asi-bot.tsx, /app/frontend/src/lib/api.ts"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          isOpen kini case-insensitive ("open"/"OPEN"). Tombol CLOSE
          tidak pernah disabled karena _id hilang: bila tid kosong →
          fallback api.asi.closeTradeBySymbol. LockKey in-flight per
          (exchange:symbol) saat tanpa tid agar dedupe benar.
metadata_v984:
  created_by: "main_agent"
  version: "9.8.4"
  test_sequence: 42
  run_ui: false

# ======================================================
# v9.8.5 — EXECUTED button state + in-sheet result panel
# ======================================================
frontend_v985:
  - task: "Pesan 'Order Successfully Executed' tidak muncul setelah EXECUTE"
    implemented: true
    working: true
    file: "/app/frontend/src/components/AsiTradeSheet.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          ROOT CAUSE: hasil eksekusi memakai Alert.alert yang TIDAK tampil
          di web preview (RN Web no-op) → user tidak melihat konfirmasi apa
          pun. Dialog konfirmasi pyramid juga menggantung di web (promise
          tidak pernah resolve).
          FIX: (1) Hasil eksekusi kini panel in-sheet (hijau sukses / merah
          gagal) berisi judul terlokalisasi "Order Successfully Executed"
          + detail order + tombol "View Recent Trades" (biru muda) /
          "Try Again" (gagal) / "Close". (2) Tombol EXECUTE berubah jadi
          "✅ EXECUTED" hijau TERKUNCI setelah sukses (sesuai permintaan
          user — mencegah order ganda). (3) Dialog pyramid di web memakai
          window.confirm fallback. (4) execResult di-reset tiap intent baru.
          Keys i18n baru: ats_exec_done, ats_executed_btn, ats_try_again.
metadata_v985:
  created_by: "main_agent"
  version: "9.8.5"
  test_sequence: 43
  run_ui: false

# ======================================================
# v9.8.6 — Recent Trades: LONG/SHORT bukan BUY/SELL
# ======================================================
frontend_v986:
  - task: "Label side di Recent Trades diganti LONG/SHORT"
    implemented: true
    working: true
    file: "/app/frontend/app/asi-bot.tsx"
    stuck_count: 0
    priority: "medium"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          User: futures position harus tampil LONG/SHORT, bukan BUY/SELL.
          FIX: render side di row Recent Trades diganti
          tr.side === "BUY" ? "LONG" : "SHORT". Warna tetap hijau/merah.
          Copy-trade leaderboard sudah pakai LONG/SHORT (isLong) — konsisten.
metadata_v986:
  created_by: "main_agent"
  version: "9.8.6"
  test_sequence: 44
  run_ui: false

# ======================================================
# v9.8.7 — View Recent Trades menutup SEMUA layer sheet
# ======================================================
frontend_v987:
  - task: "Tombol 'View Recent Trades' setelah EXECUTED salah kembali ke popup AI Suggestions"
    implemented: true
    working: true
    file: "/app/frontend/src/components/AsiTradeSheet.tsx, AISuggestionsSheet.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          ROOT CAUSE: flow bersarang — ASI-Bot → PICK A SIGNAL membuka
          AISuggestionsSheet → EXECUTE membuka AsiTradeSheet di dalamnya.
          Tombol "View Recent Trades" hanya memanggil onClose() (menutup
          trade sheet) + router.push("/asi-bot") yang NO-OP karena user
          sudah di /asi-bot → popup AI Suggestions tetap terbuka di depan.
          FIX: prop baru onCloseAll di AsiTradeSheet; helper
          goToRecentTrades() menutup trade sheet + suggestions popup
          (onCloseAll) lalu router.replace("/asi-bot") (replace agar tidak
          menumpuk route sama). AISuggestionsSheet meneruskan
          onCloseAll = tutup tradeIntent + sheet. Tombol CONNECT EXCHANGE
          (no-cred state) juga diperbaiki dengan pola sama.
metadata_v987:
  created_by: "main_agent"
  version: "9.8.7"
  test_sequence: 45
  run_ui: false

# ======================================================
# v9.8.8 — HTTP 500 pada GALA/INJ: min-notional + entry try/except
# ======================================================
backend_v988:
  - task: "Fix HTTP 500 execute GALA/INJ (min notional Binance $5)"
    implemented: true
    working: true
    file: "/app/backend/asi_bot/engine.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          ROOT CAUSE (dari screenshot user): balance $9.62 x risk 5% x
          leverage 10x = size $4.80-4.81 < $5 minimum notional Binance
          Futures → entry order ditolak (-4164) → exception tak tertangani
          di execute_trade (try tanpa except) → HTTP 500 polos.
          FIX: (1) preview_trade kini load market limits dan menolak sejak
          PREVIEW dengan reason="min_notional" + field min_notional &
          size_usdt → tombol EXECUTE abu-abu dengan penjelasan localized.
          (2) execute_trade: cek min-notional sebelum order + entry
          create_order dibungkus try/except → return ok=False
          reason="entry_rejected" dengan pesan error exchange (route
          mengubah jadi HTTP 400 dengan pesan jelas, bukan 500).
frontend_v988:
  - task: "Mapping reason min_notional → pesan terlokalisasi"
    implemented: true
    working: true
    file: "/app/frontend/src/components/AsiTradeSheet.tsx, api.ts, I18nContext.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          AsiPreview type + min_notional field. Preview error IIFE menambah
          cabang min_notional → ats_err_min_notional (4 bahasa) dengan
          placeholder {size} {min}. Saran actionable: naikkan Risk/Leverage.
metadata_v988:
  created_by: "main_agent"
  version: "9.8.8"
  test_sequence: 46
  run_ui: false

# ======================================================
# v9.9.0 — Native SL/TP fix + Cross/Isolated + Repair
# ======================================================
backend_v990:
  - task: "Fix SL/TP native gagal terpasang di Binance"
    implemented: true
    working: true
    file: "/app/backend/asi_bot/engine.py, algo.py, whitelist.py"
    stuck_count: 0
    priority: "critical"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: |
          USER REPORT: posisi MANA/ARB/TURBO terbuka TANPA SL/TP sama sekali
          (Open Orders 0), semua Cross.
          FIXES: (1) triggerPrice kini dibulatkan ke tickSize resmi
          (binance_symbol_filters cache 10m, 525 simbol terverifikasi via
          proxy). (2) TP TIDAK lagi di-skip ketika SL gagal (sebelumnya
          `if soft_bracket` membuat posisi benar-benar telanjang).
          (3) _fmt_num di algo.py — harga/qty diformat Decimal polos,
          tanpa notasi ilmiah. (4) set_margin_mode dipanggil sebelum
          entry (default ISOLATED). (5) Error Binance mentah disimpan di
          soft_bracket_reason dan disertakan di response repair.
  - task: "POST /asi/trades/repair-brackets"
    implemented: true
    working: true
    file: "/app/backend/asi_bot/routes.py + engine.attach_brackets"
    stuck_count: 0
    priority: "critical"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: |
          attach_brackets() membaca qty posisi REAL dari exchange, lalu
          memasang ulang SL (closePosition) + TP (split qty) dengan tick
          rounding. Endpoint me-loop semua open trades user, update doc,
          return per-symbol errors. Curl-verified 404 tanpa kredensial.
  - task: "margin_mode di payload + scheduler Full-Auto"
    implemented: true
    working: true
    file: "routes.py (TradePayload/BotConfigPayload), scheduler.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          TradePayload.margin_mode (default isolated) + BotConfigPayload.
          margin_mode. Scheduler full-auto meneruskan cfg.margin_mode ke
          execute_trade. Simpan/ambil config verified via curl.
frontend_v990:
  - task: "Selector Cross/Isolated di trade sheet + bot config + badge ISO/CRS"
    implemented: true
    working: true
    file: "AsiTradeSheet.tsx, asi-bot.tsx, api.ts, I18nContext.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          Trade sheet: chips ISOLATED (default) / CROSS di bawah leverage +
          note SL/TP native. Default diambil dari bot config. Bot config page:
          selector yang sama (tersimpan → dipakai Full-Auto). Recent Trades:
          badge ISO (teal) / CRS (ungu) per row + badge ⚠️ utk soft-bracket
          (tap = alasan Binance) + banner merah REPAIR BRACKETS. Panel sukses
          eksekusi memperingatkan bila bracket soft. Screenshot-verified:
          selector Margin Mode tampil di Risk Parameters.
metadata_v990:
  created_by: "main_agent"
  version: "9.9.0"
  test_sequence: 47
  run_ui: false

# ======================================================
# v9.9.1 — Verifikasi proteksi per posisi open di Recent Trades
# ======================================================
frontend_v991:
  - task: "Tampilkan SL, TP, margin mode & status bracket di posisi open"
    implemented: true
    working: true
    file: "/app/frontend/app/asi-bot.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          User: posisi OPEN di Recent Trades harus menampilkan SL, TP, dan
          Iso/Cross supaya user yakin proteksi terpasang.
          FIX: tiap row open kini punya baris verifikasi:
          "SL <merah> · TP a/b/c <hijau> · ISOLATED|CROSS <teal/ungu> · 10x"
          + baris status bracket: "✓ SL/TP native aktif di Binance" (hijau)
          atau "⚠ SL/TP watcher soft — tap banner REPAIR" (oranye).
          leaderRow diubah jadi kolom (row utama + sub-baris). Harga pakai
          formatPrice crypto (presisi adaptif). Keys i18n baru 4 bahasa.
metadata_v991:
  created_by: "main_agent"
  version: "9.9.1"
  test_sequence: 48
  run_ui: false

# ======================================================
# v9.9.2 — FIX KRITIS: SL/TP Native yang BENAR + Auto-Rollback
# ======================================================
backend_v992:
  - task: "Direct signed Binance REST + verified SL/TP + auto-rollback"
    implemented: true
    working: true
    file: "/app/backend/asi_bot/binance_rest.py /app/backend/asi_bot/engine.py"
    stuck_count: 0
    priority: "critical"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: |
          Root cause ditemukan: (1) CCXT.set_margin_mode gagal dibungkus
          except pass → margin mode user DIAM-DIAM diabaikan, UI klaim
          ISOLATED padahal Binance Cross. (2) Response algo order tidak
          diverifikasi via GET /openAlgoOrders → status "hard" bisa muncul
          palsu kalau Binance return 200 tanpa benar-benar persist order.
          
          FIX: modul baru binance_rest.py (direct HMAC-SHA256 signed REST
          via proxy SG). engine.execute_trade Binance path ditulis ulang:
          - Baca positionRisk real → margin mismatch? ABORT entry.
          - set_margin_type via REST (bukan CCXT) + handle -4046.
          - Entry MARKET, poll positionRisk sampai positionAmt > 0.
          - SL + TP placement dengan retry 3× + VERIFY via openAlgoOrders.
          - Jika SL atau TP (verified) < expected → AUTO-ROLLBACK: cancel
            semua algo + MARKET close reduceOnly. Trade TIDAK disimpan.
          - Hanya SL+TP full-verified yang disimpan dengan bracket_type=hard.
          - Simpan actual_margin_mode (dari positionRisk) bukan request.
          
          E2E Testnet (user key, ~$5k USDT):
            ✓ Happy ETH BUY ISO: hard, 4 algo live (SL+3 TP).
            ✓ Margin mismatch SOL (cross pre-exist): REJECTED clean.
            ✓ XRP cross entry: actual_margin_mode=cross tersimpan.
            ✓ Rollback DOGE invalid SL: -2021 3× retry → auto market close,
              positionAmt=0, 0 algo sisa, pesan "balance aman — coba lagi".
          
          Juga di-upgrade:
          - engine.attach_brackets (repair) verify via openAlgoOrders.
          - engine.refresh_trade_pnl Binance pakai REST, update
            actual_margin_mode live + bracket_live flag.
          - routes.execute propagate code/message/rollback_done ke frontend.
frontend_v992:
  - task: "UI reflects verified bracket + actual margin + rollback dialogs"
    implemented: true
    working: true
    file: "/app/frontend/app/asi-bot.tsx /app/frontend/src/components/AsiTradeSheet.tsx /app/frontend/src/lib/api.ts /app/frontend/src/i18n/I18nContext.tsx"
    stuck_count: 0
    priority: "critical"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: |
          AsiTradeSheet menampilkan dialog kontekstual per error code:
            - bracket_sl_failed / tp_incomplete → "Entry Dibatalkan — SL/TP Gagal"
            - margin_mode_mismatch → "Margin Mode Tidak Cocok"
            - rollback_failed → "🚨 PERLU TINDAKAN MANUAL"
          Recent Trades: badge margin mode & label native pakai 
          actual_margin_mode + bracket_live (bukan field request-only). 
          Banner REPAIR hanya muncul untuk trade LAMA soft atau
          bracket_live=false. Version bump 9.9.1 → 9.9.2.

agent_communication:
  - agent: "main"
    message: |
      v9.9.2 FIX KRITIS SELESAI. Masalah utama: UI klaim SL/TP terpasang
      padahal Binance kosong. Root cause: CCXT silent error swallow +
      tidak ada verifikasi order post-placement.
      
      Testing agent: harap verifikasi di SIDE BACKEND dengan testnet key
      yang sama (sudah di test_credentials.md):
        - POST /api/asi/trades/execute → happy path simbol ETH/BTC/XRP.
        - Verifikasi response: bracket_type MUST BE "hard", 
          actual_margin_mode MUST match request (atau explicit reject).
        - Test rollback: kirim SL di sisi "salah" (SL atas entry utk LONG)
          → MUST return 400 dengan code=bracket_sl_failed, 
          rollback_done=true, position closed di Binance.
        - Test margin mismatch: buka posisi cross dulu via API, lalu
          POST execute dengan margin_mode=isolated → MUST return 400 
          code=margin_mode_mismatch.
      
      Testing agent: jangan ragu memakai testnet key yg disediakan;
      itu akun sandbox tanpa risiko. Setelah backend ok, tidak perlu
      frontend testing berat (yang penting user bisa langsung tes di
      APK Mainnet build mereka).

# ======================================================
# v9.9.4 — Smart Layering + Auto-Rebalance Brackets
# ======================================================
backend_v994:
  - task: "Layering detection + auto-rebalance SL/TP + merge DB rows"
    implemented: true
    working: true
    file: "/app/backend/asi_bot/engine.py /app/backend/asi_bot/routes.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          E2E testnet PASS: layer1 ETH 0.16 + layer2 → combined 0.319,
          avg entry 2719.14. SL lama auto-cancelled, SL+3TP baru live utk
          full qty (total TP qty == positionAmt). Opposite-side ditolak
          (reason=opposite_position). Rollback saat layering menutup
          seluruh posisi gabungan (user requirement: no unprotected).
          routes merge row lama → status="layered", layer_count di row baru.
frontend_v994:
  - task: "Layering dialog + badge + success note"
    implemented: true
    working: true
    file: "/app/frontend/src/components/AsiTradeSheet.tsx /app/frontend/app/asi-bot.tsx /app/frontend/src/i18n/I18nContext.tsx"
    stuck_count: 0
    priority: "medium"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          Dialog duplikat kini menjelaskan averaging + auto-rebalance SL/TP
          (4 bahasa). Panel sukses menampilkan catatan layer. Recent Trades
          badge "Layer ×n". Lint pass. Version 9.9.4.

# ======================================================
# v9.9.5 — Dual-Slot Credential + Badge DEMO + PnL Terpisah
# ======================================================
backend_v995:
  - task: "Credential mainnet/testnet slot terpisah + resolve per-network"
    implemented: true
    working: true
    file: "/app/backend/asi_bot/routes.py engine.py scheduler.py pnl.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          Slot _id = device:exchange:mainnet|testnet. resolve_credential()
          lazy-migrate legacy doc. BotConfig.active_testnet mengendalikan
          network Semi/Full-Auto. Verified: save testnet OK → save mainnet
          invalid DITOLAK tanpa menimpa slot testnet; preview testnet=true
          resolve slot benar; preview testnet=false tanpa slot → 404 jelas.
          PnL/leaderboard/WR/daily-loss hanya real; key demo terpisah.
frontend_v995:
  - task: "Network switch global + status 2 slot + badge DEMO trades"
    implemented: true
    working: true
    file: "/app/frontend/app/asi-bot.tsx src/components/AsiTradeSheet.tsx src/lib/api.ts src/i18n/I18nContext.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          Switch 🧪TESTNET/🔴MAINNET di halaman ASI-Bot (saveBot
          active_testnet). Baris exchange tampilkan status kedua slot.
          Simpan key suatu jaringan → otomatis jadikan aktif. AsiTradeSheet
          pakai credential network aktif. Recent Trades: badge biru DEMO
          utk trade testnet + baris demo PnL terpisah. Lint pass. v9.9.5.

# ======================================================
# v9.9.6 — Fix flicker tombol Execute di AsiTradeSheet
# ======================================================
frontend_v996:
  - task: "Anti-flicker tombol Execute (empty-state flash + preview error overwrite)"
    implemented: true
    working: true
    file: "/app/frontend/src/components/AsiTradeSheet.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: |
          User: tombol execute hilang-muncul saat sheet dibuka & saat tap
          leverage. Fix: (1) credsLoaded flag → empty-state hanya setelah
          fetch selesai; (2) exception jaringan saat refetch preview tidak
          menimpa preview bagus terakhir (keep last-good), hanya backend
          rejection yang mengubah state; (3) chip exchange sorot slot
          network aktif. Lint pass, halaman /asi-bot smoke OK.

# ======================================================
# v9.9.7 — Layout Recent Trades + v9.9.8 — Leaderboard Demo+Real
# ======================================================
frontend_v997:
  - task: "Recent Trades layout rapi (no overflow, DEMO row2, leverage hijau)"
    implemented: true
    working: true
    file: "/app/frontend/app/asi-bot.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          Row1: SEMI/FULL + ACTIVE + SIDE + SYMBOL + PnL + CLOSE (flexWrap,
          CLOSE flexShrink:0). ISO badge dihapus dari row1. Row2: chip
          DEMO/REAL selalu ada (susunan identik) + SL/TP/margin + leverage
          hijau tebal. Verified screenshot dengan trade demo ETH asli.
backend_v998:
  - task: "Leaderboard tampilkan DEMO+REAL dengan badge, limit 25"
    implemented: true
    working: true
    file: "/app/backend/asi_bot/pnl.py routes.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          Filter testnet dihapus dari live_leaderboard & leaderboard;
          group per (device, testnet); field testnet di response; limit 25.
          curl verified: entry demo & real sama-sama tampil. Badge DEMO
          biru / REAL hijau di copy-trade.tsx. PnL summary tetap terpisah.

# ======================================================
# v9.9.8 patch — Repair bracket senyap utk kasus tanpa risiko uang
# ======================================================
backend_v998_patch:
  - task: "attach_brackets: no_open_position / SL-2021 auto-close / TP-2021 skip bukan kegagalan"
    implemented: true
    working: true
    file: "/app/backend/asi_bot/engine.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          User: popup error mentah utk eksekusi gagal yg tidak merugikan
          uang tidak perlu tampil. Fix: posisi sudah tertutup → ok=True +
          mark closed; SL -2021 → auto market close (tindakan protektif
          yang sama dgn SL); TP -2021 → skip senyap (level terlewati).
          Frontend: popup hanya utk kegagalan nyata (posisi open & bracket
          tetap gagal). Tanpa bump versi (tetap 9.9.8) sesuai permintaan.

# ======================================================
# v9.9.9 patch — Copy Trade: EXECUTE aktif + detail lengkap + mock dibersihkan
# ======================================================
frontend_v999:
  - task: "EXECUTE copy-trade fungsional + Entry/SL/TP/Lev/PnL lengkap di leaderboard"
    implemented: true
    working: true
    file: "/app/frontend/app/copy-trade.tsx src/lib/api.ts src/i18n/I18nContext.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          EXECUTE fetch harga live via GET /api/asi/price (baru, public
          ticker via proxy) lalu buka AsiTradeSheet. Kartu menampilkan
          SL merah + TP hijau + leverage chip + running PnL % dan $.
          "+N posisi lain" bila open_count>1. Subtitle Top 10 → Top 25.
          Mock rows BTC@50k/TP999999 dihapus dari DB preview (4 row).
          Screenshot-verified. Tetap v9.9.9 (tidak bump).

# ======================================================
# v9.9.9 patch 2 — Detail lengkap pada trade CLOSED + closed_price
# ======================================================
frontend_backend_v999p2:
  - task: "Closed trades show Entry/SL/TP/Lev/ClosePrice/PnL in Recent Trades"
    implemented: true
    working: true
    file: "/app/frontend/app/asi-bot.tsx /app/backend/asi_bot/binance_rest.py engine.py scheduler.py routes.py"
    stuck_count: 0
    priority: "medium"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          closed_price direkam: refresh Binance ambil last fill
          (/fapi/v1/userTrades via last_fill_price), soft-close salin
          exit_price, manual close ikut simpan. UI render baris detail
          untuk trade closed: chip DEMO/REAL + Entry·SL·TP·margin·lev +
          "Closed @ harga · ALASAN". Screenshot-verified (SOL demo +
          ARB real closed). Legacy rows tanpa closed_price → "—".

# ======================================================
# v9.9.9 patch 3 — Saldo available realtime + Closed on Exchange
# ======================================================
v999p3:
  - task: "Available balance card atas Recent Trades + Closed on {exchange}"
    implemented: true
    working: true
    file: "/app/backend/asi_bot/routes.py engine.py /app/frontend/app/asi-bot.tsx src/lib/api.ts"
    stuck_count: 0
    priority: "medium"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          GET /api/asi/balance → saldo USDT jaringan aktif (curl verified
          $3,656.96 testnet). resolve_credential fallback ke slot v9.9.5
          bila legacy doc tidak ada. Baris 3 closed trade: "Closed @ X ·
          ALASAN · Closed on Binance". Screenshot-verified.

# ======================================================
# v9.9.9 patch 7 — Trade sheet: 2 chip DEMO/REAL sebelum execute
# ======================================================
frontend_v999p7:
  - task: "2 chip jaringan DEMO/REAL di trade sheet, chip ganda dihilangkan"
    implemented: true
    working: true
    file: "/app/frontend/src/components/AsiTradeSheet.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: true
        agent: "main"
        comment: |
          Exchange chips diganti 2 chip jaringan besar: DEMO (Testnet) &
          REAL (Mainnet). Tap = pilih jaringan utk preview+execute +
          persist active_testnet ke bot config. activeCred dibuat strict
          per jaringan (tidak ada fallback silang). Jaringan tanpa
          credential → chip redup "Not connected" + empty-state connect.
          Lint pass.

# ======================================================
# v9.9.9 patch 9 — FIX false-positive tanpa SL/TP + -4130 + duplikat row
# ======================================================
backend_v999p9:
  - task: "Verifikasi bracket berlapis (ID → karakteristik algo → legacy) + repair existing-aware + konsolidasi duplikat"
    implemented: true
    working: true
    file: "/app/backend/asi_bot/engine.py scheduler.py binance_rest.py /app/frontend/app/asi-bot.tsx"
    stuck_count: 0
    priority: "critical"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          Screenshot user menunjukkan XRP/BCH demo ditandai tanpa SL/TP
          padahal SL+TP algo ADA di Binance (diverifikasi langsung).
          -4130 pada repair = closePosition SL sudah ada. Fix: verifikasi
          karakteristik order + legacy openOrders; repair existing-aware
          (tidak ganggu proteksi sah); scheduler auto-merge row duplikat.
          E2E: repair XRP ok=True tanpa menyentuh 4 order existing.
          CATATAN INSIDEN: order tes sempat mereduksi posisi demo user
          30 XRP — dikembalikan (positionAmt -2565.3 utuh).

# ======================================================
# v9.9.12 — Fix akar "close di +0.4" & Full-Auto rugi berulang
# ======================================================
backend_v9912:
  - task: "Anchor-to-fill: SL/TP digeser ke harga fill MARKET aktual (engine.py)"
    implemented: true
    working: "NA"
    file: "/app/backend/asi_bot/engine.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          ROOT CAUSE (bukti live dashboard): sinyal memakai entry DEEP
          (offset 0.6-1.0 ATR dari harga), tapi bot eksekusi MARKET.
          TP1 dihitung dari entry deep → nempel/salah sisi vs harga fill
          (contoh live: HYPE SELL TP1 +0.053% vs harga = SISI SALAH;
          TIA BUY TP1 -0.763% vs harga). TP1 kena instan (1/3 posisi,
          profit kecil ~+0.4), sisa 2/3 mati di SL jauh → rugi berulang
          di SEMUA profil (scalper/day/swing/confluence).
          FIX: setelah fill, anchor_shift = actual_entry - entry_sinyal;
          sl_price & tps digeser sebesar shift (R:R & ladder utuh relatif
          ke fill). Diterapkan di jalur Binance REST + CCXT fallback.
          Disimpan di field trade "anchor_shift" untuk audit.
  - task: "Guard TP: buang TP sisi-salah/nempel vs avg entry aktual + floor TP1 (0.25% entry / 0.5x ATR)"
    implemented: true
    working: "NA"
    file: "/app/backend/asi_bot/engine.py, /app/backend/indicators.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          engine.execute_trade: setelah anchor shift, TP dengan jarak
          < max(0.25% entry, 0.2 x risk) dari fill DIBUANG; jika semua
          gugur -> sintesis 1 TP di 1.5R. attach_brackets: TP di sisi
          salah vs entryPrice live -> repair dibatalkan dgn pesan aman.
          indicators._floor_tp_ladder: floor TP1 min max(0.25% entry,
          0.5xATR), ladder tetap berurutan; diterapkan di
          _compute_vwap_levels, _compute_deep_levels (crypto+stocklike),
          dan jalur Pattern Scalp 15M.
  - task: "Soft watcher: TP split 1/3-1/3-1/3 (bukan tutup 100% di TP1)"
    implemented: true
    working: "NA"
    file: "/app/backend/asi_bot/scheduler.py, /app/backend/asi_bot/engine.py (close_position_partial)"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          _watch_soft_brackets kini menutup SEBAGIAN per TP sesuai bobot
          TP_SPLITS (TP1 1/3, TP2 1/3, TP terakhir = sisa penuh). SL
          tetap tutup semua. Tracking baru: tp_filled[], qty_remaining,
          soft_realized_pnl; close_reason kini "TP1"/"TP2"/"TP3"/"SL".
          close_position_partial (engine): market close reduceOnly TANPA
          cancel conditional & TANPA override qty dari positionRisk.
          Trade lama tanpa field baru: default aman (filled=False, qty
          remaining = qty asli).
test_plan:
  current_focus:
    - "Anchor-to-fill E2E Binance TESTNET: entry deep sengaja jauh dari harga -> SL/TP terpasang harus bergeser relatif ke fill, tidak ada TP salah sisi, bracket verified hard, lalu close bersih"
    - "Soft watcher split: unit/mock test logika TP1 partial 1/3 + DB fields (JANGAN live fire tanpa posisi kecil khusus)"
    - "Regresi: dashboard signal API, engine import, scheduler loop hidup"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"
agent_communication:
  - agent: "main"
    message: |
      v9.9.12 — User melaporkan Full-Auto Confluence/Intraday selalu rugi
      dan posisi tertutup di profit kecil ~+0.4 sebelum TP1/TP3.
      ROOT CAUSE ditemukan via data DB + audit live:
      1. Entry sinyal = DEEP (limit), eksekusi = MARKET -> TP1 nempel/
         salah sisi vs harga fill (bukti: HYPE SELL TP1 +0.053% vs harga,
         TIA BUY TP1 -0.763% vs harga).
      2. Soft watcher menutup 100% posisi saat TP pertama tersentuh
         (scheduler.py lama, loop reversed(tps) -> _close_soft_trade full).
      3. Layering rebalance mewarisi TP sinyal lama yang bisa salah sisi
         vs avg entry gabungan (bukti DB: ETH layered TP1 2714.47 < avg
         entry 2714.48 untuk BUY -> close instan, pnl -0.44).
      FIX (3 file): anchor-to-fill + TP guard (engine), TP floor
      (indicators), soft watcher split (scheduler + close_position_partial).
      Tolong test sesuai test_plan. Credential testnet tersedia di
      /app/memory/test_credentials.md (device web:qmeqflw0e2d-mui5ar38,
      slot testnet). HANYA TESTNET — Mainnet tidak boleh disentuh.

# ======================================================
# v9.9.13 — Entry LIMIT Deep (keputusan user) menggantikan MARKET
# ======================================================
backend_v9913:
  - task: "Entry LIMIT deep + expire 1 candle + auto-bracket setelah fill"
    implemented: true
    working: "NA"
    file: "/app/backend/asi_bot/engine.py, /app/backend/asi_bot/binance_rest.py, /app/backend/asi_bot/scheduler.py, /app/backend/asi_bot/routes.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          Keputusan user: entry bot BUKAN market price — LIMIT di entry
          Deep (-1.0 ATR confluence / -0.6 ATR VWAP), expire 1 candle,
          berlaku untuk Semi & Full-Auto.
          - engine.execute_trade (Binance): place LIMIT GTC di harga
            sinyal; poll 2.4s — bila FILLED instan (marketable) lanjut
            flow bracket seperti biasa (anchor shift + guard); bila
            belum -> trade tersimpan status "pending_entry" dengan
            entry_expire_at = now + 3600s, bracket_type "pending".
          - binance_rest: limit_order() + cancel_order() baru.
          - scheduler._process_pending_entries (tiap 20s): FILLED ->
            attach_brackets (rebalance paksa bila layered) + entry_price/
            qty aktual + merge row layering; EXPIRED -> cancel limit,
            race-guard cek posisi, tandai "expired"; attach GAGAL ->
            close_position demi keamanan (no-unprotected policy).
          - attach_brackets: trade.layered -> cancel algo+legacy dulu
            lalu pasang ulang utk total posisi (rebalance).
          - routes: execute skip merge layering utk pending; close by id
            pada pending -> batalkan limit (bukan market close);
            close-all juga membatalkan pending; scanner dup-guard
            memasukkan pending_entry.
frontend_v9913:
  - task: "Badge PENDING + panel LIMIT di trade sheet"
    implemented: true
    working: "NA"
    file: "/app/frontend/app/asi-bot.tsx, /app/frontend/src/components/AsiTradeSheet.tsx, /app/frontend/src/i18n/I18nContext.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: |
          Recent Trades: badge MENUNGGU (emas) utk status pending_entry,
          baris detail + tombol CLOSE (berfungsi cancel order limit),
          baris status "LIMIT menunggu terisi (maks 1 candle)".
          AsiTradeSheet: res.pending -> panel sukses "LIMIT ORDER
          TERPASANG" dgn penjelasan. i18n 4 bahasa: asi_status_pending,
          asi_pending_line, ats_pending_title, ats_pending_body.
          Versi 9.9.13 (version.ts + app.json + APP_LATEST_VERSION).
metadata:
  created_by: "main_agent"
  version: "9.9.13"
  test_sequence: 35
  run_ui: false

test_plan:
  current_focus:
    - "LIMIT entry E2E Testnet: execute dengan entry 2-3% di bawah pasar -> res.pending True, status pending_entry, order limit terlihat di Binance testnet; lalu cancel via endpoint close -> status cancelled; order hilang dari exchange"
    - "LIMIT entry marketable (entry = harga pasar) -> FILLED instan -> bracket SL/TP terpasang & terverifikasi, status open, anchor_shift ~0; lalu tutup bersih"
    - "v9.9.12 regression: anchor-to-fill (entry deep 3%), TP guard salah-sisi, soft watcher split (mock), TP floor via API"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

# ======================================================
# v9.9.13b — Mark price realtime + frame PnL hijau/merah
# ======================================================
frontend_v9913b:
  - task: "Mark price live 2 detik di samping symbol + frame kartu hijau(profit)/merah(loss) open & closed"
    implemented: true
    working: true
    file: "/app/frontend/app/asi-bot.tsx, /app/frontend/src/lib/api.ts, /app/backend/asi_bot/routes.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          Backend: GET /api/asi/prices?symbols= batch (cache 1s, proxy SG).
          Frontend: polling 2 detik utk simbol posisi open; harga live di
          samping symbol (hijau/merah vs entry); PnL $ & % dihitung live
          dari harga itu; FRAME kartu: hijau=profit, merah=loss (open &
          closed), emas=pending. Screenshot-verified dgn 4 trade dummy
          (SOL win hijau+121.02, ETH loss merah+2.699,72, BTC closed
          hijau, TRX closed merah). Dummy dibersihkan setelah tes.
backend_v9913b:
  - task: "Fix accounting soft-watcher (temuan testing agent iter36)"
    implemented: true
    working: true
    file: "/app/backend/asi_bot/scheduler.py"
    stuck_count: 0
    priority: "medium"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          Snapshot qty_remaining/soft_realized_pnl kini di-refresh per TP
          di dalam pass yang sama (gap move TP2+TP3 bersamaan tidak lagi
          overstate pnl). Test TestSoftWatcherSplit.test_tp_split_then_full_close
          yang sebelumnya FAIL kini PASS (1 passed).

# ======================================================
# v9.9.13c — Swipe-to-delete kartu history Recent Trades
# ======================================================
backend_v9913c:
  - task: "DELETE /asi/trades/{trade_id} — hapus kartu history"
    implemented: true
    working: true
    file: "/app/backend/asi_bot/routes.py"
    stuck_count: 0
    priority: "medium"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          Hanya status closed/expired/cancelled/layered yang bisa dihapus;
          open/pending_entry ditolak 400. Curl-verified: delete BTC 200,
          TRX tersisa, id invalid 404.
frontend_v9913c:
  - task: "Swipe-to-delete (ReanimatedSwipeable) pada kartu closed"
    implemented: true
    working: true
    file: "/app/frontend/app/asi-bot.tsx, /app/frontend/src/lib/api.ts"
    stuck_count: 0
    priority: "medium"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          Kartu history digeser kiri -> tombol merah HAPUS -> kartu hilang
          instan (state lokal) + DELETE ke backend. Posisi open/pending
          TIDAK dibungkus swipeable (tidak bisa dihapus). i18n 4 bahasa
          (asi_delete). Catatan: klik force pada action tersembunyi tidak
          bekerja di web preview (keterbatasan simulasi mouse); gesture
          swipe native RNGH standar untuk device asli.

# ======================================================
# v9.9.13d — Label formula per kartu + Entry Price di baris detail
# ======================================================
backend_v9913d:
  - task: "Trade record menyimpan profile formula saat eksekusi"
    implemented: true
    working: true
    file: "/app/backend/asi_bot/engine.py, /app/backend/asi_bot/routes.py, /app/backend/asi_bot/scheduler.py"
    stuck_count: 0
    priority: "medium"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          TradePayload.profile + execute_trade(profile=...) tersimpan di
          record (pending/filled/ccxt fallback). Full-Auto scanner
          meneruskan cfg.profile. Semi-Auto sheet mengirim apiProfile
          (default confluence).
frontend_v9913d:
  - task: "Baris formula di bawah tombol CLOSE + Entry antara Margin dan SL"
    implemented: true
    working: true
    file: "/app/frontend/app/asi-bot.tsx, /app/frontend/src/components/AsiTradeSheet.tsx, /app/frontend/src/i18n/I18nContext.tsx"
    stuck_count: 0
    priority: "medium"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          Baris formula per profile: Confluence v9 / Scalper (7 Fast VWAP,
          Box & Open-Scalp) / Intra-Day (5 KISS VWAP, Reclaim & Box-20) /
          Swing (5 Multi-day Trend & Box-50) + baris Macro/Risk (50-SMA &
          3R Choke) utk profil VWAP. Trade lama tanpa field profile tidak
          diberi label (tidak ditebak). Entry Price kini tampil di antara
          Margin dan SL pada baris OPEN (closed sudah ada). Screenshot-
          verified: SOL scalper open (Entry 118 + formula VWAP + macro),
          BTC day closed (Intra-Day), TRX confluence closed (Confluence v9).

# ======================================================
# v9.9.13e — Tag formula SINGKAT spesifik modul pemicu + rata kanan
# ======================================================
- backend: server._asi_formula_tag(indicators, reasons, profile) — deteksi
  modul yang benar-benar memicu: Open-Scalp Modules (SCALP-15M), Power of
  Tower Pattern, John Wick Candle Stick, KISS Pivot, Box Theory; fallback
  per profil: 7 Fast VWAP / 5 KISS VWAP / 5 Multi-day Trend. Diteruskan
  Full-Auto (scheduler) & disimpan di trade record (formula_tag).
- frontend: formulaTagFromSignal() di AsiTradeSheet (dipakai AI
  Suggestions + detail page); kartu menampilkan 1 baris singkat
  "⚙️ Formula: {tag}" RATA KANAN (textAlign right, numberOfLines 2,
  tidak melebihi bingkai), baris ketiga di bawah tombol CLOSE/CANCEL.
- Label badge pending -> LIMIT; tombol pending -> CANCEL (emas), open ->
  CLOSE (merah). Screenshot-verified. Unit tag logic PASS.

# ======================================================
# v9.9.14 — Entry LIMIT MODERATE + TTL 2 candle (keputusan user)
# ======================================================
backend_v9914:
  - task: "Bot limit entry memakai entry_moderate (Confluence -0.5xATR, VWAP -0.3xATR), TTL 7200s, cancel-only saat expired"
    implemented: true
    working: true
    file: "/app/backend/server.py, /app/backend/asi_bot/engine.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          Latar: semua LIMIT deep expired tanpa fill (harga tidak pernah
          retrace -1.0/-0.6 ATR). User pilih: moderate, 2 candle, cancel
          saja, Semi & Full-Auto.
          - _asi_signal_fetcher: entry=entry_moderate, SL/TP digeser
            sebesar (moderate-deep) -> R:R & ladder utuh. Diverifikasi
            live: SUI SELL confluence entry 1.19464, TP1 0.70R, TP3 2.50R.
          - ENTRY_LIMIT_TTL_SEC 3600 -> 7200.
          - Fallback expired TETAP cancel-only (tidak market/chase).
frontend_v9914:
  - task: "Semi-Auto sheet memakai entry moderate (SL/TP ikut shift) + teks 2 candle"
    implemented: true
    working: true
    file: "/app/frontend/src/components/AISuggestionsSheet.tsx, /app/frontend/src/i18n/I18nContext.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          Intent dari AI Suggestions: entry=entry_moderate, SL/TP shifted.
          Teks pending diubah ke "2 candle (±2 jam)" 4 bahasa. Detail page
          (AI consensus) tidak berlaku moderate (bukan level mesin
          indikator). Lint bersih.

# ======================================================
# v10.0.1 — Tombol Market Price / Limit Price (Semi & Full-Auto)
# ======================================================
backend_v1001:
  - task: "entry_mode limit|market di TradePayload + BotConfigPayload + engine + scheduler"
    implemented: true
    working: true
    file: "/app/backend/asi_bot/engine.py, /app/backend/asi_bot/routes.py, /app/backend/asi_bot/scheduler.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          E2E Testnet diverifikasi: entry_mode='market' -> ETH posisi
          open instan, bracket hard terverifikasi, anchor_shift 0.05,
          close bersih. entry_mode='limit' -> pending_entry + cancel OK.
          Full-Auto scheduler meneruskan cfg.entry_mode. Field tersimpan
          di trade record (entry_mode).
frontend_v1001:
  - task: "Tombol Market Price (ungu muda) / Limit Price (kuning) di sheet + halaman ASI-Bot"
    implemented: true
    working: true
    file: "/app/frontend/src/components/AsiTradeSheet.tsx, /app/frontend/app/asi-bot.tsx, /app/frontend/src/lib/api.ts"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          Sheet: selector di bawah Isolated/Cross, persist ke bot config.
          Halaman ASI-Bot: selector 'Execution Type' di Risk Parameters
          (dipakai Semi & Full via config bersama). Default: Limit Price.
          Screenshot-verified. Versi bump 10.0.1 (version.ts, app.json,
          APP_LATEST_VERSION + release notes update popup).

# ======================================================
# v10.0.1b — Polish warna & duplikat badge
# ======================================================
frontend_v1001b:
  - task: "Limit Price kuning asli, Margin kuning, hapus duplikat badge LIMIT"
    implemented: true
    working: true
    file: "/app/frontend/app/asi-bot.tsx"
    stuck_count: 0
    priority: "low"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          - Tambah const YELLOW #F0B90B (GOLD di file ini hijau muda).
          - Tombol Limit Price (Risk Parameters) + chip LIMIT + badge
            status LIMIT pending kini kuning; Market Price tetap ungu.
          - Teks 'Margin $..' di kartu open & closed kini kuning.
          - Chip entry-mode LIMIT disembunyikan saat status pending_entry
            (badge status sudah 'LIMIT') -> tidak ada lagi 2 tulisan
            LIMIT pada kartu antri. Terlihat dari screenshot user:
            SUI SHORT (semi) & BCH SHORT (full) pending limit moderate
            dengan SL/TP arah benar.

# ======================================================
# v10.0.2 — Formula R:R baru + layout badge final
# ======================================================
backend_v1002:
  - task: "SL 0.5xATR semua profil + TP ladder 1R/2R/3R (keputusan user); min_wr TETAP 70 (user batalkan 80)"
    implemented: true
    working: true
    file: "/app/backend/indicators.py, /app/backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          TRADER_PROFILES: sl_atr_mult -> 0.5 (scalper/day/swing/longterm),
          tp_ladder & vwap_tp_ladder -> (1.0, 2.0, 3.0). Live-verified:
          MANA SELL scalper TP1=1.00R TP2=2.00R TP3=3.00R, SL dist 1.05%.
          min_wr 70 TIDAK diubah (user: jangan sampai sinyal terlalu jarang).
          CATATAN: backtest summary di dashboard kini dihitung dengan
          parameter baru — angka WR hist. akan berubah.
frontend_v1002:
  - task: "Badge DEMO/REAL + tanggal/jam di baris paling atas kartu"
    implemented: true
    working: true
    file: "/app/frontend/app/asi-bot.tsx"
    stuck_count: 0
    priority: "medium"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          Baris atas: [DEMO(biru)/REAL(kuning)] [DD/MM · HH:MM]. Baris 2:
          [🦾hijau/🤖biru muda] [M ungu/L kuning] [ACTIVE/LIMIT/CLOSED]
          LONG/SHORT SYMBOL. Closed: 'Closed on {Exchange} · ALASAN' sejajar
          formula. Screenshot-verified (SOL open + MANA closed).
analisis_trade_user:
  comment: |
    Analisis 12 trade closed di DB preview: WR 42% (5/12), total +20.86
    USDT (ditopang 1 trade SOL +8.75 dgn TP1 2R). 11/12 BUY (satu arah).
    Trade rugi kecil punya TP1 0.26-0.5R (masalah lama, sudah di-fix).
    CATATAN PENTING: loss besar user (MANA -151, BCH -112, ADA -159) ada
    di database PRODUKSI (beda environment dengan preview) — tidak bisa
    dianalisis dari sini. Arah SL/TP di screenshot user sudah benar
    (tidak terbalik).

# ======================================================
# v10.0.3 — Filter Searah Trend Harian (50-SMA Daily) Full-Auto
# ======================================================
backend_v1003:
  - task: "Gate Full-Auto: LONG hanya di atas 50-SMA Daily, SHORT hanya di bawahnya"
    implemented: true
    working: true
    file: "/app/backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          _asi_signal_fetcher: bias dari indikator sinyal (mesin VWAP
          punya daily_bias) atau fallback _daily_trend_bias() — klines 1d
          Binance via proxy, cache 30 menit. Counter-trend -> sinyal
          dibuang (return None). Bias unknown (data gagal) -> TIDAK
          memblokir (bot tidak mati total saat jaringan bermasalah).
          Unit test sintetis PASS 3/3: BUY-vs-BEARISH diblokir,
          BUY-vs-BULLISH lolos, bias unknown lolos.
          CATATAN: gate ini khusus BOT (fetcher). Dashboard/tampilan
          sinyal manual TIDAK berubah. Semi-Auto (user tap) tidak
          diblokir — bisa ditambahkan warning bila diminta.
          Mesin VWAP day/swing sebenarnya sudah HOLD counter-trend
          (3R Rule); gate ini menutup celah mesin CONFLUENCE.

# ======================================================
# v10.0.3b — Leaderboard: semua posisi open sebagai kartu terpisah
# ======================================================
backend_v1003b:
  - task: "live_leaderboard mengirim open_trades[] (semua posisi, sort PnL desc)"
    implemented: true
    working: true
    file: "/app/backend/asi_bot/pnl.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: "Group pipeline kini $push semua dokumen open; response menyertakan open_trades dengan symbol/side/entry/SL/TP/leverage/created_at/pnl_usdt per posisi. Diverifikasi: 1 trader 2 posisi -> open_trades [SOL, ENA]."
frontend_v1003b:
  - task: "Kartu leaderboard merender tiap posisi open + EXECUTE per posisi"
    implemented: true
    working: true
    file: "/app/frontend/app/copy-trade.tsx, /app/frontend/src/lib/api.ts"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: "Teks '+1 more open position(s)' dihapus; tiap posisi jadi kartu sendiri dengan PnL live per posisi dan tombol EXECUTE yang menyalin posisi tersebut. preparingRank kini keyed per (rank:symbol). Screenshot-verified: trader 2 OPEN POS menampilkan kartu SOL LONG +$0.42 dan ENA SHORT +$0.06 terpisah."

# ======================================================
# v10.0.3 — Leaderboard Top 25 Profit 24h (open + closed)
# ======================================================
backend_v1003:
  - task: "live_leaderboard: Top 25 trader by TOTAL profit 24h (realized+unrealized)"
    implemented: true
    working: true
    file: "/app/backend/asi_bot/pnl.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: "Agregat open (unrealized) + closed 24h (realized) per device/network. Rank by total profit $ desc. Response: total_profit_usdt, realized_usdt, unrealized_usdt, open_count, closed_count, open_trades[] (hanya trade open). Diverifikasi: #1 trader all-closed (71.18), #2 all-closed (8.75), #3 mix open+closed (5.52) dengan kartu posisi SOL."
frontend_v1003:
  - task: "UI leaderboard menampilkan trader open & closed; kartu posisi hanya untuk open"
    implemented: true
    working: true
    file: "/app/frontend/app/copy-trade.tsx, /app/frontend/src/lib/api.ts, /app/frontend/src/i18n/I18nContext.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: "Metrik utama = $ total profit 24h (sebelumnya hanya % unrealized). Pill 'OPEN POS' biru utk online, '×N CLOSED' abu untuk closed-only. Label metrik '24H PROFIT' (ada open) atau '24H REALIZED' (closed only). Kartu posisi hanya dirender bila open_trades.length>0 (tidak lagi fallback ke latest_trade yang bisa closed). Versi bump 10.0.3 (version.ts/app.json/APP_LATEST_VERSION)."


# ======================================================
# v10.0.4 — Leaderboard: kartu CLOSED lengkap + pill counter dihapus
# ======================================================
backend_v1004:
  - task: "live_leaderboard kirim closed_trades lengkap (symbol/side/entry/SL/TP/leverage/PnL/closed_price/close_reason/closed_at)"
    implemented: true
    working: true
    file: "/app/backend/asi_bot/pnl.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          Permintaan user: posisi closed di leaderboard harus tampil LENGKAP
          seperti open position (bukan hanya inisial+PnL). $group kini juga
          push closed_trades; diurutkan closed_at desc, maks 10 per trader.
          Verifikasi curl data real: rank#1 DCC closed MANA SHORT +$54.17
          dan SAND SHORT +$17.01 lengkap entry/SL/TP/closed@.
frontend_v1004:
  - task: "Render kartu closed read-only + hapus pill 'OPEN POS'/'N× CLOSED'"
    implemented: true
    working: true
    file: "/app/frontend/app/copy-trade.tsx, /app/frontend/src/lib/api.ts, /app/frontend/src/i18n/I18nContext.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: true
        agent: "main"
        comment: |
          User: tiap posisi tampil satu per satu dengan PnL masing-masing
          (tidak digabung), jadi pill penghitung tidak perlu. Kartu closed:
          badge CLOSED abu, PnL realized, entry/SL/TP, 'Closed @ price ·
          reason · ago', opacity 0.75, TANPA tombol EXECUTE. copy_sub &
          copy_footer diperbarui (4 bahasa). Screenshot verified: pill hilang,
          2 kartu closed lengkap, 0 tombol EXECUTE utk closed.
          Versi bump 10.0.3 → 10.0.4 (version.ts, app.json, server.py
          APP_LATEST_VERSION + release notes).
