"""Cash-constrained farm coin exchange.

Only *verified, earmarked* cash is spendable: owner-confirmed bank receipts
and explicit owner-attested funds. Publisher estimates support a nominal index
but never create spendable cash. One bot credit / coin burn / reserve debit
commits in the same DB transaction, with replay keys and row locks.
"""
import time
import uuid
from decimal import Decimal, ROUND_FLOOR
from fastapi import HTTPException
import farm_capitalization
import bot_account_controls

MAX_MINT=1000000000
MAX_REDEEM=1000000000

def initialize(c):
    c.execute("""CREATE TABLE IF NOT EXISTS farm_cash_reserve(
      id integer PRIMARY KEY CHECK(id=1),
      backed_kopeks bigint NOT NULL DEFAULT 0 CHECK(backed_kopeks>=0))""")
    c.execute("INSERT INTO farm_cash_reserve(id,backed_kopeks) VALUES(1,0) ON CONFLICT(id) DO NOTHING")
    c.execute("""CREATE TABLE IF NOT EXISTS farm_cash_reserve_funding(
      reference text PRIMARY KEY,kopeks bigint NOT NULL CHECK(kopeks>0),
      source text NOT NULL,created_at double precision NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS farm_coin_redemptions(
      id text PRIMARY KEY,player_id text NOT NULL,telegram_id bigint NOT NULL,
      coins integer NOT NULL CHECK(coins>0),
      credited_kopeks bigint NOT NULL CHECK(credited_kopeks>0),
      created_at double precision NOT NULL)""")

def fund_verified(c,reference,kopeks,source):
    """Owner attests independently available fiat; never silently fund ad estimates."""
    if not isinstance(reference,str) or not 4<=len(reference)<=128:
        raise ValueError('Укажи идентификатор подтверждённого поступления')
    if type(kopeks) is not int or not 1<=kopeks<=100000000000:
        raise ValueError('Некорректная сумма обеспечения в копейках')
    if source not in ('seed','ads_cash','bank_reconciliation'):
        raise ValueError('Неверный источник резерва')
    lock=c.execute("SELECT backed_kopeks FROM farm_cash_reserve WHERE id=1 FOR UPDATE").fetchone()
    if not lock:raise RuntimeError('Резерв не инициализирован')
    inserted=c.execute("""INSERT INTO farm_cash_reserve_funding
       (reference,kopeks,source,created_at)
       VALUES(%s,%s,%s,%s) ON CONFLICT(reference) DO NOTHING RETURNING reference""",
       (reference,kopeks,source,time.time())).fetchone()
    if inserted:
        c.execute("UPDATE farm_cash_reserve SET backed_kopeks=backed_kopeks+%s WHERE id=1",(kopeks,))
    return bool(inserted)

def credit_verified_card(c,request_id,amount_kopeks):
    """Called once, in the same transaction as verified bank approval."""
    return fund_verified(c,'game-card:'+request_id,amount_kopeks,'bank_reconciliation')

def _supply(c):
    # Keep the cash exchange in sync with the displayed capitalization:
    # only coins currently held by players count toward the supply.
    players=c.execute("SELECT COALESCE(SUM(coins),0)::bigint AS n FROM players").fetchone()
    return int(players['n'])

def quote(c,usd_uah,lock=False):
    row=c.execute("SELECT backed_kopeks FROM farm_cash_reserve WHERE id=1"+
                  (" FOR UPDATE" if lock else "")).fetchone()
    if not row:raise RuntimeError('Резерв не инициализирован')
    nominal=farm_capitalization.preview(c,usd_uah)
    outstanding=_supply(c)
    backing=int(row['backed_kopeks'])
    nominal_value=int(nominal['nominal_capitalization_kopeks'])
    # Free, actually recorded bot cash can cover farm redemptions automatically.
    # The outstanding bot wallet/task/payout obligations and funds already
    # earmarked for the farm are NOT spendable again.
    import task_bot
    cash=c.execute("SELECT amount FROM bot_cash_pool WHERE id=1"+
                   (" FOR UPDATE" if lock else "")).fetchone()
    pool_kopeks=int(cash['amount']) if cash else 0
    other_liabilities=int(task_bot.liability(c))
    free_pool=max(0,pool_kopeks-other_liabilities-backing)
    spendable=min(nominal_value,backing+free_pool)
    # The coin's price is capitalization / circulating supply, never the
    # smaller liquidity / circulating supply. Cash availability determines
    # whether and how much may be redeemed, not a discounted coin rate.
    nominal_rate=(Decimal(nominal_value)/Decimal(outstanding)
                  if outstanding and nominal_value>0 else Decimal(0))
    rate=nominal_rate
    purchase_rate=nominal_rate
    return {'reserve_kopeks':backing,'free_pool_kopeks':free_pool,
            'nominal_kopeks':nominal_value,'cashable_kopeks':spendable,
            'total_coins':outstanding,
            'coin_price_kopeks':str(rate),
            'coin_price_uah':str(rate/Decimal(100)),
            'purchase_price_kopeks':str(purchase_rate),
            'purchase_price_uah':str(purchase_rate/Decimal(100)),
            'payout_enabled':spendable>0 and rate>0}

def mint_from_card(c,amount_kopeks,usd_uah):
    """Rate sampled before approval mints more coins; no infinite fallback."""
    if type(amount_kopeks) is not int or amount_kopeks<=0:
        raise ValueError('Некорректная сумма перевода')
    offer=quote(c,usd_uah,lock=True)
    price=Decimal(offer['purchase_price_kopeks'])
    if price<=0:
        raise ValueError('Начальная капитализация монеты равна нулю')
    count=int((Decimal(amount_kopeks)/price).to_integral_value(rounding=ROUND_FLOOR))
    if not 1<=count<=MAX_MINT:
        raise ValueError('Количество монет за этот перевод вне допустимого диапазона')
    return count,offer

def redeem(c,player,coins,key,bot,usd_uah):
    if type(coins) is not int or not 100<=coins<=MAX_REDEEM:
        raise HTTPException(400,'Минимальный перевод — 100 монет')
    if not isinstance(key,str) or len(key)>128 or not key:
        raise HTTPException(400,'Некорректный номер вывода')
    uid=player.get('telegram_id')
    if not uid:raise HTTPException(403,'Сначала привяжи Telegram к ферме')
    previous=c.execute("""SELECT player_id,telegram_id,coins,credited_kopeks
      FROM farm_coin_redemptions WHERE id=%s""",(key,)).fetchone()
    if previous:
        if previous['player_id']!=player['id'] or previous['telegram_id']!=uid or previous['coins']!=coins:
            raise HTTPException(409,'Номер вывода уже использован')
        return {'ok':True,'id':key,'status':'credited','amount':coins,
                'credited_kopeks':previous['credited_kopeks'],
                'repeated':True}
    if bot_account_controls.withdrawal_error(c,uid):
        raise HTTPException(403,bot_account_controls.withdrawal_error(c,uid))
    if c.execute("SELECT 1 FROM withdrawal_requests WHERE player_id=%s AND status='pending'",
                 (player['id'],)).fetchone():
        raise HTTPException(409,'Сначала отмени прежнюю заявку на вывод')
    pricing=quote(c,usd_uah,lock=True)
    if not pricing['payout_enabled']:
        raise HTTPException(409,'Курс пока равен нулю: подтверждённого резерва нет')
    available_coins=int(player['coins'])
    if coins>available_coins:raise HTTPException(400,'Недостаточно монет')
    amount=int((Decimal(coins)*Decimal(pricing['coin_price_kopeks'])).to_integral_value(rounding=ROUND_FLOOR))
    if amount<=0:raise HTTPException(409,'Стоимость выбранных монет меньше 1 копейки; укажи больше монет')
    if amount>int(pricing['cashable_kopeks']):raise HTTPException(409,'Недостаточно резерва')
    # Every mutation below belongs to the same caller-managed transaction.
    c.execute('INSERT INTO bot_accounts(uid,name,created) VALUES(%s,%s,%s) ON CONFLICT(uid) DO NOTHING',
              (uid,'Игрок',time.time()))
    bot.account(c,uid)
    player_row=c.execute("UPDATE players SET coins=coins-%s WHERE id=%s AND coins>=%s RETURNING id",
                         (coins,player['id'],coins)).fetchone()
    if not player_row:raise HTTPException(409,'Баланс изменился, обнови страницу')
    # Spend earmarked farm cash first. Any remainder is automatically funded
    # by the verified *free* bot cash pool, while crediting this amount to
    # bot liabilities in the same transaction. The common bot lock makes
    # competing cashouts and payouts serialize.
    from_reserve=min(amount,int(pricing['reserve_kopeks']))
    if from_reserve:
        debited=c.execute("""UPDATE farm_cash_reserve
          SET backed_kopeks=backed_kopeks-%s
          WHERE id=1 AND backed_kopeks>=%s RETURNING backed_kopeks""",
          (from_reserve,from_reserve)).fetchone()
        if not debited:raise HTTPException(409,'Резерв изменился, обнови курс')
    if amount-from_reserve>int(pricing['free_pool_kopeks']):
        raise HTTPException(409,'Недостаточно доступных средств для перевода')
    c.execute("""INSERT INTO farm_coin_redemptions(id,player_id,telegram_id,coins,credited_kopeks,created_at)
      VALUES(%s,%s,%s,%s,%s,%s)""",(key,player['id'],uid,coins,amount,time.time()))
    c.execute("""INSERT INTO money_log(id,player_id,kind,delta,details,created)
      VALUES(%s,%s,'farm_to_bot',%s,%s,%s)""",
      (uuid.uuid4().hex,player['id'],-coins,'Вывод по курсу в бот · '+key,time.time()))
    balance=bot.change(c,uid,amount,'farm_transfer',
                       'Вывод фермы: '+str(coins)+' монет · '+key)
    bot.bot_notifications.enqueue(c,'farm-exchange:'+key,
          '✅ Списано '+str(coins)+' монет; на баланс бота зачислено '+
          format(Decimal(amount)/100,'.2f')+' грн.',recipient=uid,subject=uid)
    return {'ok':True,'id':key,'status':'credited','amount':coins,
            'credited_kopeks':amount,'bot_balance_kopeks':balance,
            'rate_uah':pricing['coin_price_uah'],'repeated':False}
