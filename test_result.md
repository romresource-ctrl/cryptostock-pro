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
  version: "7.0.7"
  test_sequence: 16
  run_ui: false

test_plan:
  current_focus:
    - "Asset detail route for slash symbols and all markets (commodity/gold_silver/forex/world_stocks)"
    - "Dashboard endpoint for forex/gold_silver (previous NameError crash regression)"
    - "Cross-market search returns correct market for each hit (CORN→commodity, EUR/USD→forex)"
    - "Chat retention 16h — old messages filtered + purged"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
  - agent: "main"
    message: |
      v7.0.7 — Fixed 2 P0 regressions reported by user:

      ROOT CAUSE #1 (CORN 404, screenshot-confirmed):
      `/app/frontend/app/asset/[market]/[symbol].tsx` line 73-74 had
      `validMarkets = ["crypto","etf","stock_id","stock_us"]` — did NOT
      include commodity, gold_silver, forex, world_stocks. Any tap on
      those markets forced market → "crypto" → API called
      `/asset/crypto/CORN/chart` → 404. FIXED: whitelist now includes
      all 8 markets; added displaySymbol for "EUR-USD" → "EUR/USD" in
      forex/gold_silver header; added badge labels for the extra 4 markets.

      ROOT CAUSE #2 (backend dashboard crash on forex/gold_silver):
      `/app/backend/server.py` `dashboard()` had erroneous copy-paste of
      the dash-decoder block that referenced an undefined `symbol` var,
      raising UnboundLocalError → 500. FIXED: removed the stray block.

      MANUAL VERIFICATION (backend, all return 200 on localhost:
      - GET /api/dashboard?market=commodity/forex/gold_silver → 200
      - GET /api/asset/commodity/CORN/chart → 200
      - GET /api/asset/forex/EUR-USD/chart → 200
      - GET /api/asset/gold_silver/XAU-USD/chart → 200
      - GET /api/asset/forex/EUR-USD/track-record → 200
      - GET /api/asset/commodity/CORN/news → 200
      - GET /api/asset/gold_silver/XAU-USD/news → 200

      PLEASE TEST (backend + frontend web):
      BACKEND:
      1. /api/dashboard for each of the 7 markets returns 200 with assets[] populated.
      2. /api/asset/{market}/{symbol}/{chart,analyze,track-record,news} for:
         - commodity/CORN, commodity/BRENT
         - forex/EUR-USD, forex/GBP-USD
         - gold_silver/XAU-USD, gold_silver/XAG-USD
         - world_stocks/AAPL
         - crypto/BTC (regression baseline)
      3. /api/search?q=CORN → hit has market="commodity" (NOT crypto).
      4. /api/search?q=EUR → hits include forex with proper market field.
      5. Chat 16h: POST message, then verify GET /api/chat/messages filters
         out anything older than 16h (cutoff computed relative to now).

      FRONTEND (web preview only):
      1. Header shows "Ver 7.0.7".
      2. Switch to Commodity chip → dashboard populates (previously crashed).
      3. Switch to Forex chip → dashboard populates.
      4. Switch to Gold/Silver chip → dashboard populates.
      5. Route /asset/commodity/CORN?timeframe=1h renders with header
         "CORN COMMODITY" (not "CORN CRYPTO"); chart loads.
      6. Route /asset/forex/EUR-USD?timeframe=1h renders "EUR/USD FOREX".
      7. Route /asset/gold_silver/XAU-USD?timeframe=1h renders "XAU/USD GOLD/SILVER".
      8. Search bar: type "CORN" → tap first hit → arrives at commodity detail (200).

      NOT TO TEST (requires real Android):
      - Google Play Billing purchase flow
      - Native soft-keyboard ChatSheet behaviour
      - Native image picker

      Credentials: /app/memory/test_credentials.md
