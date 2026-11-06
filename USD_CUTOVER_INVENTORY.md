# USD cutover audit: Farm + Telegram bot
Status: PREPARATION ONLY. Live UAH service unchanged.

Legacy: task_bot.py wallet is integer UAH kopecks; main.py game wallet is integer game coins historically worth 1 UAH. Both must be converted consistently. Do not relabel UAH/coins as USD at 1:1.

Required touched paths:
- task_bot.py, bot_ui.py, bot_economy.py, bot_manual.py, bot_advertising.py: USD balances, history, orders, prices, task rewards, referrals, reserves.
- bot_topups.py, bot_payments.py, bot_payouts.py, bot_admin.py, bot_accounts_admin.py: XTR invoices, UAH card rates, withdrawal FX quotes, fees, confirmation IDs, payout audit.
- bot_extras.py, bot_quests.py, bot_cash_ad_credits.py, bot_adsgram_daily.py: daily rewards, AdsGram and Monetag settlements, no double conversion.
- main.py, farm_wallet.py, production.py, production_v4.py, market_allocation.py, fields.py: game balances, coin store, product costs, trades, profitability, farm-to-bot transfers and withdrawal.
- index.html and assets/game.js: user-facing USD values and currency inputs; keep grain, eggs and hens as non-currency inventory.
- all tests for invoices, withdrawal, task spending, farm trading and referrals.

Staged exact arithmetic:
- bot_usd_currency.py — legacy UAH / farm coin / Stars conversion to integer micro-USD.
- bot_usd_payout.py — USD to UAH card cash-out quote with FX rate and fees; refuses unpriced USDT.
- bot_usd_topups.py — UAH card and XTR funding quotes with recorded rates.
- tests/test_bot_usd_*.py — conversion arithmetic tests.

Invariants:
1. 1 old farm coin == 1 UAH historically, not $1.
2. Existing 1-UAH task cost is about $0.022 at snapshot; do not reinterpret as $1.
3. Existing daily reward 0.50 UAH is about $0.011; do not relabel $0.50.
4. Never credit an old pending UAH card or Stars intent under USD denomination.
5. Preserve immutable purchased task slots, escrow, debts, refunds and payouts.
6. Use same snapshot conversion for every historical balance and obligation; store original UAH source and exact rate for audit.
7. Complete a verified database backup and offline reconciliation before transactional cutover.
8. Do not advertise real USD/USDT cash-out until a payment route and fee schedule exist.
9. Do not deploy with a mixed USD UI and UAH ledger.
