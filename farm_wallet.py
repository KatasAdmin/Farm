"""Earned game coins can be transferred once to the verified user's bot wallet."""
import time
import uuid
from fastapi import HTTPException

SALE_KINDS={'market_sale','system_sale'}


def initialize(c):
    c.execute('CREATE TABLE IF NOT EXISTS farm_bot_transfers(id text PRIMARY KEY,player_id text NOT NULL,telegram_id bigint NOT NULL,amount integer NOT NULL CHECK(amount>=100),created double precision NOT NULL)')
    c.execute('CREATE INDEX IF NOT EXISTS farm_bot_transfers_player ON farm_bot_transfers(player_id,created)')
    c.execute('CREATE INDEX IF NOT EXISTS money_log_player_created ON money_log(player_id,created,id)')


def available(c, player):
    rows=c.execute('SELECT kind,delta FROM money_log WHERE player_id=%s ORDER BY created,id',(player['id'],)).fetchall()
    # Unclassified legacy funds are never presumed to be withdrawable.
    balance=max(0,player['coins']-sum(r['delta'] for r in rows))
    earned=0
    for row in rows:
        delta=row['delta'];balance+=delta
        if delta>0 and row['kind'] in SALE_KINDS:earned+=delta
        elif delta<0 and row['kind'] in ('farm_to_bot','withdraw_reserve'):
            earned=max(0,earned+delta)
        earned=min(earned,max(0,balance))
    return max(0,min(player['coins'],earned))


def transfer(c, player, amount, key, bot):
    uid=player['telegram_id']
    if not uid:raise HTTPException(403,'Сначала привяжите Telegram в профиле игры')
    old=c.execute('SELECT player_id,telegram_id,amount FROM farm_bot_transfers WHERE id=%s',(key,)).fetchone()
    if old:
        if old['player_id']!=player['id'] or old['telegram_id']!=uid or old['amount']!=amount:
            raise HTTPException(409,'Этот номер перевода уже использован')
        return {'ok':True,'id':key,'status':'credited','amount':amount,'repeated':True}
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
