# USD-only Farm bot — safe rollout checklist (staged, NOT LIVE)

## Current production state
The bot's accounting unit is UAH kopecks, persisted as integers in wallets, task marketplace, payouts, Stars and advertising revenue. The farm game separately treats 1 coin as 1 UAH. Changing only labels from UAH to USD would change outstanding value by ~45 times and is forbidden.

## Intended unit and exchange-rate snapshot
- Bot unit after migration: 1 USD = 1,000,000 micro-USD, including sub-cent ad/task rewards.
- Snapshot for historical positions only: 1 USD = 45.4432 UAH (NBU, 2026-11-06); store exact rate/date in migration metadata.
- Actual funding exchange rate is immutable per UAH receipt; USD account balances must not fluctuate daily.
- Stars stay Telegram XTR; separately configure micro-USD per Star. Existing paid invoices preserve original rates.

## Atomic migration requirements
1. Take verified PostgreSQL backup and exclusive migration lock. Disable new financial transactions during the cut-over.
2. Reconcile every wallet position and transaction: available/advertising balances, orders and budgets, pending and paid payouts, liabilities/cash pool, debts, referral fractional accruals, retention fines/refunds and historical receipts.
3. Convert via exact Decimal at one fixed recorded rate. Preserve original UAH values for audit. Reconcile rounding residuals explicitly.
4. Preserve every original task gross price, worker reward, purchased execution count and funding budget; all converted numbers must be internally consistent.
5. Existing pending Stars invoices and card receipts must settle at old UAH terms or be explicitly cancelled/refunded before USD wallet writes; never reinterpret old amounts.
6. Farm coins remain separate UAH-valued units. Apply an explicit UAH-to-USD rate on each farm-to-bot transfer and record the exact rate and transfer ID. Never credit a farm coin as $1.
7. Display sub-cent USD values accurately, not as $0.00.
8. Update wallet, pricing, ad, referral, bonus, management, bank-card, Stars, payments and withdrawal flows together before switching production. No rolling mixed-currency writes.
9. Test concurrency, duplicate callbacks, refunds, cancellations, admin changes and migration reruns. Confirm idempotence.
10. Run database reconciliation report and real deposit/withdraw test using a test wallet before enabling USD release.

## Still needed before production
- USD bank deposits: users can pay UAH; show exact rate, fees, final USD credit and bank currency.
- USD withdrawal: select USD/USDT payout rail or UAH bank cash-out, with exact conversion, fees and approval.
- Current bonus of 0.50 UAH is about $0.011; set a deliberate USD rate instead of changing to $0.50.
- Existing 1 UAH manual task price is about $0.022; do not change its financial obligation to $1.
- Migrate any old historical text to clearly identify the original UAH amount; preserve audit history.

STATUS: Preparatory branch only. NOT a USD production release. DO NOT MERGE as a currency switch until an end-to-end migration is implemented and validated.
