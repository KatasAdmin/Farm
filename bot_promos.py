"""Admin-only, replay-safe issuance of single-use farm bonus vouchers."""
import hashlib
import re
import secrets
import time


def initialize(c):
    c.execute('CREATE TABLE IF NOT EXISTS promo_codes(code_hash text PRIMARY KEY,amount integer NOT NULL CHECK(amount>0),redeemed_by text,redeemed_at double precision)')
    c.execute('CREATE TABLE IF NOT EXISTS farm_promo_issuance(code_hash text PRIMARY KEY,created_by bigint NOT NULL,amount integer NOT NULL CHECK(amount>0),created double precision NOT NULL)')


def command(c,uid,text,admin):
    import task_bot as b
    if not admin:return b.say(uid,'Доступ только администратору.')
    parts=text.split(maxsplit=1)
    normalized=parts[0].split('@',1)[0]+(' '+parts[1] if len(parts)>1 else '')
    match=re.fullmatch(r'/bonus(?:([0-9]{1,7})|\s+([0-9]{1,7}))',normalized)
    amount=int(next(g for g in match.groups() if g is not None)) if match else 0
    if not 1<=amount<=1000000:
        return b.say(uid,'🎁 Промокод для фермы\n\nНапиши /bonus1000 — код на 1000 монет.\nИли /bonus100 — на 100 монет.\nСумма: от 1 до 1 000 000 монет.')
    b.state(c,uid,'clear')
    for _ in range(5):
        code='FARM-'+'-'.join(''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(5)) for _ in range(4))
        digest=hashlib.sha256(code.encode()).hexdigest()
        fresh=c.execute('INSERT INTO promo_codes(code_hash,amount) VALUES(%s,%s) ON CONFLICT(code_hash) DO NOTHING RETURNING code_hash',(digest,amount)).fetchone()
        if fresh:break
    else:raise b.UserError('Не удалось создать уникальный код. Попробуй ещё раз.')
    c.execute('INSERT INTO farm_promo_issuance(code_hash,created_by,amount,created) VALUES(%s,%s,%s,%s)',(digest,uid,amount,time.time()))
    result=b.say(uid,'🎁 Код на '+str(amount)+' монет для фермы\n\n'+code+'\n\nОдноразовый. Активируется в кошельке игры.\nМонеты бонусные — напрямую переводить в бот нельзя.',[[b.button('⬅️ Админ-панель','admin')]])
    return result
