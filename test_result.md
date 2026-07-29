#====================================================================================================
# START - Testing Protocol - DO NOT EDIT OR REMOVE THIS SECTION
#====================================================================================================

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

agent_communication:
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
