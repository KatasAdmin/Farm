"""Explicit one-time wallet grant requested by the owner on 2026-10-31.
The durable reference prevents startup/redeploy from repeating the credit.
"""
import time

REFERENCE='owner-request-20261031-8385663990-1000uah-01'
UID=8385663990
AMOUNT=100000  # integer kopeks


def apply(c,bot):
    old=c.execute('SELECT uid,amount FROM bot_deposits WHERE reference=%s',(REFERENCE,)).fetchone()
    if old:
        if old['uid']!=UID or old['amount']!=AMOUNT:
            raise RuntimeError('One-time grant reference conflict')
        return False
    c.execute('INSERT INTO bot_accounts(uid,name,created) VALUES(%s,%s,%s) ON CONFLICT(uid) DO NOTHING',(UID,'Игрок',time.time()))
    bot.account(c,UID)
    inserted=c.execute('INSERT INTO bot_deposits(reference,uid,amount,created) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING reference',(REFERENCE,UID,AMOUNT,time.time())).fetchone()
    if not inserted:return False
    bot.change(c,UID,AMOUNT,'owner_grant','Разовое начисление по запросу владельца · '+REFERENCE)
    bot.bot_notifications.enqueue(c,'grant:'+REFERENCE,'🎁 На ваш баланс бота начислено 1000,00 грн.',recipient=UID,subject=UID)
    return True
