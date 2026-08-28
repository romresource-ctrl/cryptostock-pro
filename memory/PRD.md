# AI Crypto Stock Pro — PRD

## Product Summary
AI-powered trading signal dashboard covering crypto, IDX stocks, US stocks, ETFs, gold/silver, commodity, forex. Bilingual (ID/EN), premium unlock, chatroom, AI Market Brief, WR history.

## Latest Session Deliverables (v8.12.35)
- **HOTFIX v8.12.35** — Fixed fatal crash when typing in the asset search bar. Root cause: `SearchResults` (module-scope) called `t("syncing_market")` without access to the `useI18n` hook. Added the hook and hardened `AssetCard` + `SearchHitCard` + result-merge with defensive null-safety (safe symbol/action/label/confidence/track_record/spark/market fallbacks) so partial payloads from small tokens never crash the tree.
- Verified across TRUMP, BTC, AAPL, SIDO, T, X, ZZZZZZ queries (no crash, correct results, empty state works).

## Previously Shipped
- Anti-FOMO Guard v3 for 7 markets
- WR formula excludes Break-Even & HOLD
- MarketSkeleton loader (dark theme)
- Chat presence indicator (online users)
- Watchlist fix for assets outside top-50
- SEO metadata + app_tagline

## Known Constraints
- Do NOT touch flicker fix in `/app/frontend/app/asset/[market]/[symbol].tsx` (blocked by user).
- Preview vs Production: user must re-Publish + re-Build APK/AAB to see frontend fixes on their device.
