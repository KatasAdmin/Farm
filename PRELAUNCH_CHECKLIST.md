# Prelaunch deployment checklist — Farm

This branch is NOT automatically safe to deploy. Do not merge while checks are missing.

## Before deploying
1. Confirm the exact commit in PR #40, review changes, and ensure GitHub Actions checks pass.
2. Create a PostgreSQL backup using Railway's supported backup/export workflow. Record the backup timestamp and verify that the backup is restorable in an isolated database. Never test restore against production.
3. Record counts and aggregate balances before deployment:
   - players, market listings, farm events, withdrawal requests
   - sum of player coins and withdrawable ledger amounts
4. Verify Railway environment variables are present without copying secrets into logs or GitHub.
5. Deploy first to a separate Railway service with a disposable PostgreSQL database; run migrations and smoke tests there.
6. Verify auth, Telegram login, purchase, feed, collection, market, achievement claims, daily/weekly claims, and withdrawals using test accounts.
7. Test duplicate/concurrent claims and webhook replay on staging.
8. Only then merge and deploy during a monitored window; compare counts/balances after deployment.

## Smoke tests
- GET /health should return ok and release.
- GET /api/state with a test account must return progression.staged_achievements.
- POST /api/achievements/claim with item=eggs should award XP only after threshold.
- Repeating the same claim must not award the same stage twice; if progress already covers the next stage, that next stage may legitimately be claimed.
- Confirm level progression updates after the next state refresh.
- Ensure players without geese/cows do not see unavailable forecast sections.
- Test market purchases and withdrawals with separate test accounts, never live player funds.

## Rollback
- Retain the pre-deploy commit SHA and verified DB backup.
- Application rollback does not undo committed database migrations or money movements.
- New staged_achievement_claims table is additive; never drop it as a rollback shortcut.
- If payment accounting differs, stop withdrawals and investigate before restoring or replaying events.

## Current limitations
- New mission-selection helper is not wired into daily/weekly claims.
- Full financial security review and concurrency tests have not been completed.
- GitHub Actions only checks syntax and unit tests, not PostgreSQL or Railway integration.
- No production backup or staging restore has been verified.

## Economy and production test matrix (2026-11-02)
- Unit coverage added: chicken/goose/cow cycles, shared feeding, storage caps, zero-quantity autobuy, 45-day catch-up, truthful feather forecast, deterministic proportional market allocation, ROI.
- Theoretical no-bottleneck payback: chicken 30 days, goose 24 days, cow 20 days. This is NOT a guaranteed cash return or marketplace sale.
- Incubation still needs database-backed integration tests: one slot per incubator level, 12 eggs + 15 coins consumed atomically, maturity only once, coop-full jobs remain pending, no duplicate referral awards.
- Marketplace still needs concurrent PostgreSQL transaction tests for competing buyers, cancel vs buy, seller payout provenance, and trade audit integrity.
- Auto-grain purchases still need database tests for exact money-log/treasury reconciliation.
- Run the full test workflow before claiming the release is ready; a file committed to GitHub is not a passing test.

## Financial provenance change
- Market receipts now preserve buyer-funded bonus, Stars-purchased and earned categories; only earned-funded sale receipts are marked earned. This intentionally tightens withdrawal eligibility for new trades.
- Before staging deploy, verify historical market receipts and the current ledger baseline. This change does not retroactively reclassify old money_log entries or undo previous withdrawals.
- Run tests/test_market_sources.py, then PostgreSQL integration tests for multi-seller rounding, Stars payment retries, seller payout, concurrent buyer/seller operations and bot-transfer idempotency.
- Review whether legacy players with preexisting earned balances from purchased-funded sales require a controlled reconciliation. Never rewrite financial history without an approved audit and backup.

## Stars refund reconciliation (mandatory before live refunds)
- Run scripts/stars_reconciliation.py against a restored staging database first. It is read-only; matching amounts and timestamps are heuristic, so inspect flagged rows manually.
- A Telegram refund is an external side effect and is not atomic with PostgreSQL. A timeout or database commit failure after Telegram confirms a refund creates an ambiguous state. Do NOT retry automatically or debit/credit the player until Telegram payment status is independently verified.
- Before enabling automated refunds, implement a durable refund intent/outbox with a unique order key and an operator reconciliation path for unknown external outcomes. Existing refund flow does not provide this guarantee.
- Payment notification validation tests cover mismatched sender, order, currency, amount and replay, but must run in CI and be backed by a staging webhook integration test.

## Durable Stars refund intent
- The new stars_refund_intents table records 'calling' before contacting Telegram, then 'confirmed' on atomic ledger commit or 'needs_review' after ambiguous failure.
- No automatic retry is allowed for any existing intent. An operator must independently verify Telegram payment/refund status before reconciliation.
- Run scripts/stars_reconciliation.py and investigate all needs_review and stale calling intents.
- **Important**: The refund intent prevents duplicate external calls but does not make Telegram and PostgreSQL atomic. A concurrent purchase between intent creation and ledger debit can still require manual intervention. Do not enable refunds for live funds before a staging fault-injection test of network timeouts, DB failures, and concurrent purchases.

## Refund freeze coverage
- Player mutations that call person(c, authorization, True) now reject unresolved Stars refund intents with HTTP 423. Read-only account views remain accessible.
- Audit all bot-side, background, admin and webhook player balance mutations separately; the authorization guard is NOT a universal database-level freeze.
- Test concurrent refund vs market purchase, feed autobuy, withdrawal transfer, incubator and Stars webhook on a dedicated staging PostgreSQL instance before any live use.
