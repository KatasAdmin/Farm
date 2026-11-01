"""Earned game coins can be transferred once to the verified user's bot wallet."""
import time
import uuid
import bot_account_controls
from fastapi import HTTPException

SALE_KINDS={'market_sale','system_sale'}


def initialize(c):
    initialize_sources(c)
    c.execute('CREATE TABLE IF NOT EXISTS farm_bot_transfers(id text PRIMARY KEY,player_id text NOT NULL,telegram_id bigint NOT NULL,amount integer NOT NULL CHECK(amount>=100),created double precision NOT NULL)')
    c.execute('CREATE INDEX IF NOT EXISTS farm_bot_transfers_player ON farm_bot_transfers(player_id,created)')
    c.execute('CREATE INDEX IF NOT EXISTS money_log_player_created ON money_log(player_id,created,id)')


def initialize_sources(c):
    c.execute('CREATE TABLE IF NOT EXISTS farm_money_sources(log_id text PRIMARY KEY,bonus integer NOT NULL CHECK(bonus>=0),purchased integer NOT NULL CHECK(purchased>=0),earned integer NOT NULL CHECK(earned>=0))')


def balances(c, player):
    rows=c.execute("""SELECT m.kind,m.delta,s.bonus,s.purchased,s.earned FROM money_log m
      LEFT JOIN farm_money_sources s ON s.log_id=m.id
      WHERE m.player_id=%s ORDER BY m.created,m.id""",(player['id'],)).fetchall()
    bonus=max(0,player['coins']-sum(r['delta'] for r in rows));purchased=earned=0
    for row in rows:
        delta=row['delta'];kind=row['kind']
        if delta>0:
            if row['bonus'] is not None:
                parts=(row['bonus'],row['purchased'],row['earned'])
                if any(v is None or v<0 for v in parts) or sum(parts)!=delta:raise RuntimeError('Invalid recorded coin provenance')
                bonus+=parts[0];purchased+=parts[1];earned+=parts[2]
            elif kind in SALE_KINDS or kind=='withdraw_release':earned+=delta
            elif kind=='stars_purchase':purchased+=delta
            else:bonus+=delta
        elif delta<0:
            cost=-delta
            # Withdrawals spend earnings only. Ordinary purchases spend bonus
            # first, then deposits, then earnings. Refunds consume deposits first.
            order=['earned','bonus','purchased'] if kind in ('farm_to_bot','withdraw_reserve') else ['purchased','bonus','earned'] if kind=='stars_refund' else ['bonus','purchased','earned']
            buckets={'bonus':bonus,'purchased':purchased,'earned':earned}
            for key in order:
                used=min(cost,buckets[key]);buckets[key]-=used;cost-=used
            bonus,purchased,earned=(buckets[k] for k in ('bonus','purchased','earned'))
    # Catch-up previews can already include feed spending not yet in this log.
    excess=max(0,bonus+purchased+earned-player['coins'])
    for key in ('bonus','purchased','earned'):
        value={'bonus':bonus,'purchased':purchased,'earned':earned}[key]
        take=min(value,excess);excess-=take
        if key=='bonus':bonus-=take
        elif key=='purchased':purchased-=take
        else:earned-=take
    return {'bonus':bonus,'purchased':purchased,'earned':earned}


def available(c, player):
    return balances(c,player)['earned']


def split_receipts(receipts,bonus):
    """Integer largest-remainder allocation preserves both money sources exactly."""
    total=sum(cost for key,cost in receipts)
    if bonus<0 or bonus>total:raise ValueError('Invalid bonus amount')
    if not total:return {}
    shares={key:cost*bonus//total for key,cost in receipts}
    extra=bonus-sum(shares.values())
    order=sorted(receipts,key=lambda row:(-(row[1]*bonus%total),row[0]))
    for key,cost in order[:extra]:shares[key]+=1
    return shares


def transfer(c, player, amount, key, bot):
    uid=player['telegram_id']
    if not uid:raise HTTPException(403,'Сначала привяжите Telegram в профиле игры')
    old=c.execute('SELECT player_id,telegram_id,amount FROM farm_bot_transfers WHERE id=%s',(key,)).fetchone()
    if old:
        if old['player_id']!=player['id'] or old['telegram_id']!=uid or old['amount']!=amount:
            raise HTTPException(409,'Этот номер перевода уже использован')
        return {'ok':True,'id':key,'status':'credited','amount':amount,'repeated':True}
    error=bot_account_controls.withdrawal_error(c,uid)
    if error:raise HTTPException(403,error)
    if c.execute("SELECT 1 FROM withdrawal_requests WHERE player_id=%s AND status='pending'",(player['id'],)).fetchone():
        raise HTTPException(409,'Сначала отмените прежнюю заявку на вывод, чтобы вернуть резерв')
    eligible=available(c,player)
    if amount>eligible:raise HTTPException(400,'Доступно к переводу: '+str(eligible)+' монет. Бонусы и монеты по промокодам переводить нельзя')
    c.execute('INSERT INTO bot_accounts(uid,name,created) VALUES(%s,%s,%s) ON CONFLICT(uid) DO NOTHING',(uid,'Игрок',time.time()))
    bot.account(c,uid)
    c.execute('INSERT INTO farm_bot_transfers(id,player_id,telegram_id,amount,created) VALUES(%s,%s,%s,%s,%s)',(key,player['id'],uid,amount,time.time()))
    row=c.execute('UPDATE players SET coins=coins-%s WHERE id=%s AND coins>=%s RETURNING coins',(amount,player['id'],amount)).fetchone()
    if not row:raise HTTPException(409,'Баланс изменился. Обновите страницу')
    c.execute('INSERT INTO money_log VALUES(%s,%s,%s,%s,%s,%s)',(uuid.uuid4().hex,player['id'],'farm_to_bot',-amount,'Перевод на баланс бота · '+key,time.time()))
    balance=bot.change(c,uid,amount*100,'farm_transfer','Из игры: '+str(amount)+' монет · '+key)
    # Financial writes and durable notifications commit together.
    text='✅ Из игры на баланс бота зачислено '+str(amount)+',00 грн.\nБаланс бота: '+format(balance/100,'.2f')+' грн.'
    bot.bot_notifications.enqueue(c,'farm-credit:'+key,text,recipient=uid,subject=uid)
    bot.bot_notifications.enqueue(c,'farm-credit-admin:'+key,'🐔 Перевод из игры\nПользователь: '+str(uid)+'\nСумма: '+str(amount)+',00 грн\nНомер: '+key,subject=uid)
    return {'ok':True,'id':key,'status':'credited','amount':amount,'bot_balance':balance,'repeated':False}
