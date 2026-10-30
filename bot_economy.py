"""Versioned gross prices, exact referral accruals and membership contracts.

Cash is never manufactured: refunds are wallet liabilities, debts are receivables.
All callers hold the common market/wallet transaction locks.
"""
import json
import logging
import time
import uuid
from decimal import Decimal, InvalidOperation

log = logging.getLogger('farm.tasks.economy')
SCALE = 10000  # exact basis-point fractions of one kopeck


def core():
    import task_bot
    return task_bot


def initialize(c):
    for sql in [
        """CREATE TABLE IF NOT EXISTS bot_economics(id integer PRIMARY KEY CHECK(id=1),
          fee integer NOT NULL,ref1 integer NOT NULL,ref2 integer NOT NULL,ref3 integer NOT NULL,
          ref4 integer NOT NULL,ref5 integer NOT NULL,days integer NOT NULL,multiplier integer NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS bot_prices(kind text PRIMARY KEY,cost bigint NOT NULL CHECK(cost>0),
          reward bigint NOT NULL CHECK(reward>0))""",
        """CREATE TABLE IF NOT EXISTS bot_task_terms(task text PRIMARY KEY,cost bigint NOT NULL CHECK(cost>0),
          ref1 integer NOT NULL,ref2 integer NOT NULL,ref3 integer NOT NULL,ref4 integer NOT NULL,
          ref5 integer NOT NULL,days integer NOT NULL,multiplier integer NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS bot_ref_accruals(uid bigint PRIMARY KEY,
          units bigint NOT NULL DEFAULT 0 CHECK(units>=0 AND units<10000))""",
        """CREATE TABLE IF NOT EXISTS bot_ref_rewards(task text NOT NULL,worker bigint NOT NULL,
          parent bigint NOT NULL,level integer NOT NULL,units bigint NOT NULL CHECK(units>=0),
          PRIMARY KEY(task,worker,level))""",
        """CREATE TABLE IF NOT EXISTS bot_task_settlements(task text NOT NULL,uid bigint NOT NULL,
          cost bigint NOT NULL,reward bigint NOT NULL,ref_units bigint NOT NULL,
          platform_units bigint NOT NULL,created double precision NOT NULL,PRIMARY KEY(task,uid))""",
        """CREATE TABLE IF NOT EXISTS bot_debts(uid bigint PRIMARY KEY,amount bigint NOT NULL CHECK(amount>=0))""",
        """CREATE TABLE IF NOT EXISTS bot_membership_accept(task text NOT NULL,uid bigint NOT NULL,
          accepted double precision NOT NULL,PRIMARY KEY(task,uid))""",
        """CREATE TABLE IF NOT EXISTS bot_retention(task text NOT NULL,uid bigint NOT NULL,
          chat_id bigint NOT NULL,owner bigint NOT NULL,cost bigint NOT NULL,reward bigint NOT NULL,
          fine bigint NOT NULL,started double precision NOT NULL,deadline double precision NOT NULL,
          state text NOT NULL,next_check double precision NOT NULL,evidence text NOT NULL DEFAULT '',
          PRIMARY KEY(task,uid))""",
        'CREATE INDEX IF NOT EXISTS bot_retention_due ON bot_retention(state,next_check)',
        'CREATE INDEX IF NOT EXISTS bot_retention_member ON bot_retention(uid,chat_id,deadline)',
        'CREATE INDEX IF NOT EXISTS bot_accounts_referrer ON bot_accounts(referrer)',
        """CREATE TABLE IF NOT EXISTS bot_retention_events(event text PRIMARY KEY,created double precision NOT NULL)""",
    ]:
        c.execute(sql)
    first = c.execute('INSERT INTO bot_economics VALUES(1,2000,500,250,150,75,25,7,2) ON CONFLICT DO NOTHING RETURNING id').fetchone()
    if first:
        # A one-time migration, never reset an administrator's later changes.
        c.execute('UPDATE bot_settings SET daily=50,referral=0 WHERE id=1')
    for kind, cost, reward in [('channel',70,56),('bot',40,32),('group',60,48),('post',4,3),('manual',100,80)]:
        c.execute('INSERT INTO bot_prices VALUES(%s,%s,%s) ON CONFLICT DO NOTHING', (kind,cost,reward))


def config(c):
    return c.execute('SELECT * FROM bot_economics WHERE id=1 FOR UPDATE').fetchone()


def terms(c, task):
    return c.execute('SELECT * FROM bot_task_terms WHERE task=%s', (task,)).fetchone()


def cost(c, task):
    t = terms(c, task['id'])
    return t['cost'] if t else task['reward']  # grandfather existing funded orders


def quote(c, kind, custom=None):
    cfg = config(c)
    p = c.execute('SELECT * FROM bot_prices WHERE kind=%s', (kind,)).fetchone()
    gross = custom if custom is not None else p['cost']
    reward = p['reward'] if kind == 'post' else gross * (10000-cfg['fee']) // 10000
    refs = [cfg['ref'+str(i)] for i in range(1,6)]
    if reward <= 0 or reward*SCALE + gross*sum(refs) > gross*SCALE:
        raise core().UserError('Цена слишком мала для награды и реферальных отчислений. Увеличь цену.')
    return dict(cost=gross,reward=reward,refs=refs,days=cfg['days'] if kind in ('channel','group') else 0,multiplier=cfg['multiplier'])


def save_terms(c, tid, data):
    q = data.get('terms')
    if q:
        c.execute('INSERT INTO bot_task_terms VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                  (tid,q['cost'],*q['refs'],q['days'],q['multiplier']))


def collect_debt(c, uid):
    b = core()
    d = c.execute('SELECT amount FROM bot_debts WHERE uid=%s FOR UPDATE', (uid,)).fetchone()
    if not d or not d['amount']:
        return 0
    a = c.execute('SELECT available FROM bot_accounts WHERE uid=%s FOR UPDATE', (uid,)).fetchone()
    n = min(d['amount'], a['available'])
    if n:
        c.execute('UPDATE bot_accounts SET available=available-%s WHERE uid=%s', (n,uid))
        c.execute('UPDATE bot_debts SET amount=amount-%s WHERE uid=%s', (n,uid))
        c.execute("INSERT INTO bot_ledger VALUES(%s,%s,%s,'debt_repayment',%s,%s)",
                  (uuid.uuid4().hex,uid,-n,'Погашение штрафа: '+b.money(n),time.time()))
    return n


def settle(c, task, uid, paid_at):
    b = core()
    q = terms(c, task['id'])
    if not q:
        return  # old contracts retain their old zero-fee economics
    parent = uid
    seen = {uid}
    distributed = 0
    for level in range(1,6):
        row = c.execute('SELECT referrer FROM bot_accounts WHERE uid=%s', (parent,)).fetchone()
        parent = row['referrer'] if row else None
        if not parent or parent in seen:
            break  # never self-refer or traverse a cycle
        seen.add(parent)
        units = q['cost'] * q['ref'+str(level)]
        distributed += units
        c.execute('INSERT INTO bot_ref_rewards VALUES(%s,%s,%s,%s,%s)', (task['id'],uid,parent,level,units))
        c.execute('INSERT INTO bot_ref_accruals VALUES(%s,0) ON CONFLICT DO NOTHING', (parent,))
        old = c.execute('SELECT units FROM bot_ref_accruals WHERE uid=%s FOR UPDATE', (parent,)).fetchone()['units']
        whole, remainder = divmod(old+units,SCALE)
        c.execute('UPDATE bot_ref_accruals SET units=%s WHERE uid=%s', (remainder,parent))
        if whole:
            b.change(c,parent,whole,'referral_reward',f'Уровень {level}, выполнение {task["id"]}, игрок {uid}')
    c.execute('INSERT INTO bot_task_settlements VALUES(%s,%s,%s,%s,%s,%s,%s)',
              (task['id'],uid,q['cost'],task['reward'],distributed,(q['cost']-task['reward'])*SCALE-distributed,paid_at))
    if q['days']:
        accepted = c.execute('SELECT 1 FROM bot_membership_accept WHERE task=%s AND uid=%s', (task['id'],uid)).fetchone()
        if not accepted:
            raise b.UserError('Условия подписки обновились. Открой карточку и снова нажми «Взять задание».')
        c.execute("INSERT INTO bot_retention VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,'watching',%s,'')",
                  (task['id'],uid,task['chat_id'],task['owner'],q['cost'],task['reward'],task['reward']*q['multiplier'],
                   int(paid_at),int(paid_at)+q['days']*86400,paid_at+300))


def rule_text(c, task):
    b = core()
    q = terms(c,task['id'])
    if not q or not q['days']:
        return ''
    return f"\n\nУсловия: сохраняй подписку {q['days']} суток после получения награды. За добровольную отписку раньше срока — штраф {b.money(task['reward']*q['multiplier'])}. Если денег не хватит, остаток станет долгом и будет удерживаться из следующих поступлений. Нажимая «Взять задание», ты принимаешь эти условия."


def penalize(c, r, evidence):
    b = core()
    changed = c.execute("UPDATE bot_retention SET state='violated',evidence=%s WHERE task=%s AND uid=%s AND state NOT IN ('violated','exempt') RETURNING task",
                        (evidence,r['task'],r['uid'])).fetchone()
    if not changed:
        return False
    c.execute('INSERT INTO bot_debts VALUES(%s,%s) ON CONFLICT(uid) DO UPDATE SET amount=bot_debts.amount+EXCLUDED.amount', (r['uid'],r['fine']))
    c.execute("INSERT INTO bot_ledger VALUES(%s,%s,0,'retention_fine',%s,%s)",
              (uuid.uuid4().hex,r['uid'],'Штраф '+b.money(r['fine'])+' за раннюю отписку · '+r['task'],time.time()))
    collect_debt(c,r['uid'])
    # A pending request is not an executed bank transfer; cancel and recover its reserve.
    pending = c.execute("UPDATE bot_payouts SET status='cancelled' WHERE uid=%s AND status='pending' RETURNING amount,id", (r['uid'],)).fetchone()
    if pending:
        b.change(c,r['uid'],pending['amount'],'payout_cancel','Заявка отменена из-за штрафа · '+pending['id'])
    # No cash-pool increase: even an uncovered refund is a real wallet liability.
    b.change(c,r['owner'],r['cost'],'retention_refund','Полный возврат цены выполнения · '+r['task']+' · '+str(r['uid']))
    return True


def member_update(payload, db):
    u = payload.get('chat_member')
    if not u:
        return None
    b = core()
    event_id = payload.get('update_id')
    if not isinstance(event_id,int):
        return {'ok':True}
    old, new = u.get('old_chat_member') or {}, u.get('new_chat_member') or {}
    uid = (new.get('user') or {}).get('id')
    chat_id = (u.get('chat') or {}).get('id')
    when = u.get('date')
    if not isinstance(uid,int) or not isinstance(when,int) or when>time.time()+60:
        return {'ok':True}
    with db() as c:
        c.execute('SELECT pg_advisory_xact_lock(1984533)')
        c.execute('SELECT pg_advisory_xact_lock(%s)', (b.LOCK,))
        fresh = c.execute('INSERT INTO bot_retention_events VALUES(%s,%s) ON CONFLICT DO NOTHING RETURNING event',
                          ('member:'+str(event_id),time.time())).fetchone()
        if not fresh:
            return {'ok':True}
        if b.member(old) and not b.member(new):
            rows = c.execute("SELECT * FROM bot_retention WHERE uid=%s AND chat_id=%s AND started<=%s AND deadline>%s AND state NOT IN ('violated','exempt') FOR UPDATE",
                             (uid,chat_id,when,when)).fetchall()
            for r in rows:
                if (u.get('from') or {}).get('id') == uid and new.get('status') == 'left':
                    penalize(c,r,'Добровольный выход, Telegram update '+str(event_id))
                else:
                    c.execute("UPDATE bot_retention SET state='exempt',evidence=%s WHERE task=%s AND uid=%s",
                              ('Исключение администратором: штраф не применяется',r['task'],uid))
    return {'ok':True}


def sweep(db, api):
    """Telegram calls stay outside the wallet lock. Missing users require evidence."""
    b = core()
    now = time.time()
    with db() as c:
        rows = c.execute("SELECT * FROM bot_retention WHERE state='watching' AND next_check<=%s ORDER BY next_check LIMIT 5", (now,)).fetchall()
    if not rows:
        return
    try:
        me = api('getMe', {})['id']
    except Exception:
        return
    rights = {}
    for snapshot in rows:
        status = None
        try:
            cid = snapshot['chat_id']
            if cid not in rights:
                rights[cid] = api('getChatMember', {'chat_id':cid,'user_id':me}).get('status') in ('administrator','creator')
            if rights[cid]:
                status = api('getChatMember', {'chat_id':cid,'user_id':snapshot['uid']})
        except Exception:
            pass
        with db() as c:
            c.execute('SELECT pg_advisory_xact_lock(1984533)')
            c.execute('SELECT pg_advisory_xact_lock(%s)', (b.LOCK,))
            r = c.execute("SELECT * FROM bot_retention WHERE task=%s AND uid=%s AND state='watching' AND next_check<=%s FOR UPDATE", (snapshot['task'],snapshot['uid'],now)).fetchone()
            if not r:
                continue
            c.execute('UPDATE bot_retention SET next_check=%s WHERE task=%s AND uid=%s', (now+300,r['task'],r['uid']))
            if status is None:
                continue
            if not b.member(status):
                c.execute("UPDATE bot_retention SET state='review',evidence='Нет подписки при сверке; нужно установить причину и время выхода' WHERE task=%s AND uid=%s", (r['task'],r['uid']))
            elif now>=r['deadline']:
                c.execute("UPDATE bot_retention SET state='cleared' WHERE task=%s AND uid=%s", (r['task'],r['uid']))


def worker(db, api, stop):
    while not stop.wait(60):
        try:
            sweep(db,api)
        except Exception:
            log.exception('bot_retention_sweep_failed')


def pct(n):
    return str(Decimal(n)/100).rstrip('0').rstrip('.') if n%100 else str(n//100)


def percentage(raw):
    try:
        x = Decimal(raw.replace(',','.'))
        if not x.is_finite() or x<0 or x>100 or x*100 != (x*100).to_integral_value():
            raise ValueError
        return int(x*100)
    except (InvalidOperation,ValueError):
        raise core().UserError('Процент: от 0 до 100, максимум два знака после запятой.')


def partners(c, uid):
    b = core()
    cfg = config(c)
    # Bounded recursion and an explicit path guard, even for malformed legacy cycles.
    rows = c.execute("""WITH RECURSIVE team(uid,depth,path) AS (
      SELECT uid,1,',' || CAST(%s AS text) || ',' || CAST(uid AS text) || ','
        FROM bot_accounts WHERE referrer=%s AND uid<>%s
      UNION ALL
      SELECT a.uid,t.depth+1,t.path || CAST(a.uid AS text) || ','
        FROM bot_accounts a JOIN team t ON a.referrer=t.uid
        WHERE t.depth<5 AND replace(t.path,',' || CAST(a.uid AS text) || ',','')=t.path)
      SELECT depth,count(*) AS n FROM team GROUP BY depth""", (uid,uid,uid)).fetchall()
    by_level = {r['depth']:r['n'] for r in rows}
    counts = [by_level.get(i,0) for i in range(1,6)]
    earned = c.execute('SELECT coalesce(sum(units),0) AS n FROM bot_ref_rewards WHERE parent=%s', (uid,)).fetchone()['n']
    return b.say(uid,'👥 Партнёры\n'+ '\n'.join(f"Уровень {i}: {counts[i-1]} · {pct(cfg['ref'+str(i)])}%" for i in range(1,6))+
                 f'\n\nНачислено: {b.money(earned//SCALE)}\nДоля меньше копейки: {Decimal(earned%SCALE)/SCALE} коп.\nПроценты от полной цены оплаченных выполнений твоей команды.\n\nhttps://t.me/Farmlife2026bot?start=partner_{uid}')


def admin(c, uid, text, action):
    b=core()
    if action=='admin:economy':
        cfg=config(c)
        prices=c.execute('SELECT * FROM bot_prices ORDER BY kind').fetchall()
        daily=c.execute('SELECT daily FROM bot_settings WHERE id=1').fetchone()['daily']
        return b.say(uid,'⚙️ Тарифы и правила\n'+ '\n'.join(b.KINDS[p['kind']]+': '+b.money(p['cost'])+' → '+b.money(quote(c,p['kind'])['reward']) for p in prices)+
                     f"\n\nКомиссия: {pct(cfg['fee'])}% (для постов задаётся цена и награда отдельно).\nРефералы: "+' / '.join(pct(cfg['ref'+str(i)])+'%' for i in range(1,6))+
                     f"\nБонус: {b.money(daily)}\nПодписка: {cfg['days']} суток; штраф ×{cfg['multiplier']}.\nИзменения действуют для новых заказов.",
                     [[b.button('Изменить тарифы','admin:ecoedit:prices'),b.button('Комиссия / рефералы','admin:ecoedit:rates')],
                      [b.button('Срок / штраф','admin:ecoedit:retention'),b.button('Ежедневная награда','admin:bonus')],
                      [b.button('Спорные отписки','admin:retention')]])
    if action.startswith('admin:ecoedit:'):
        field=action.split(':')[-1]
        prompts={'prices':'Введи: канал бот группа пост наградаЗаПост задание. Все суммы в гривнах.\nПример: 0.70 0.40 0.60 0.04 0.03 1.00',
                 'rates':'Введи комиссию и 5 реферальных процентов.\nПример: 20 5 2.5 1.5 0.75 0.25',
                 'bonus':'Введи сумму ежедневной награды в гривнах.\nПример: 0.50. Сумма 0 отключает награду.',
                 'retention':'Введи срок подписки в сутках и множитель штрафа.\nПример: 7 2'}
        if field not in prompts:
            raise b.UserError('Неизвестная настройка.')
        b.state(c,uid,'economy_edit',{'field':field})
        return b.say(uid,prompts[field]+'\n/cancel — отмена.')
    if action=='admin:retention':
        row=c.execute("SELECT * FROM bot_retention WHERE state='review' ORDER BY started LIMIT 1").fetchone()
        if not row:
            return b.say(uid,'Спорных отписок нет.')
        b.state(c,uid,'retention_review',{'task':row['task'],'worker':row['uid'],'nonce':uuid.uuid4().hex[:12]})
        nonce=b.state(c,uid)['data']['nonce']
        return b.say(uid,f"Проверка отписки\nИгрок {row['uid']} · {row['task']}\nЧат {row['chat_id']}\n{row['evidence']}\nШтраф: {b.money(row['fine'])}; возврат: {b.money(row['cost'])}.\nПодтверждай только доказанный добровольный выход раньше срока.",
                     [[b.button('Добровольный выход — штраф','admin:retfine:'+nonce)],
                      [b.button('Не штрафовать','admin:retexempt:'+nonce)]])
    if action.startswith(('admin:retfine:','admin:retexempt:')):
        s=b.state(c,uid)
        if not s or s['state']!='retention_review' or s['data']['nonce']!=action.split(':')[-1]:
            raise b.UserError('Подтверждение устарело.')
        r=c.execute("SELECT * FROM bot_retention WHERE task=%s AND uid=%s AND state='review' FOR UPDATE", (s['data']['task'],s['data']['worker'])).fetchone()
        if not r:
            raise b.UserError('Эта отписка уже обработана.')
        if action.startswith('admin:retfine:'):
            penalize(c,r,'Добровольный выход до срока подтверждён администратором '+str(uid))
        else:
            c.execute("UPDATE bot_retention SET state='exempt',evidence='Штраф отменён администратором' WHERE task=%s AND uid=%s", (r['task'],r['uid']))
        b.state(c,uid,'clear')
        return b.say(uid,'Решение сохранено.')
    return None


def edit(c,uid,text,data):
    b=core()
    p=text.split()
    cfg=config(c)
    field=data['field']
    if field=='prices':
        if len(p)!=6:
            raise b.UserError('Нужны 6 сумм: канал бот группа пост наградаЗаПост задание.')
        channel,bot,group,post,reward,manual=map(b.amount,p)
        if reward*SCALE+post*sum(cfg['ref'+str(i)] for i in range(1,6))>post*SCALE:
            raise b.UserError('Цена поста не покрывает награду и рефералов.')
        for kind,n in [('channel',channel),('bot',bot),('group',group),('post',post),('manual',manual)]:
            r=reward if kind=='post' else n*(10000-cfg['fee'])//10000
            if not r:
                raise b.UserError('Тариф не покрывает хотя бы одну копейку награды.')
            c.execute('UPDATE bot_prices SET cost=%s,reward=%s WHERE kind=%s',(n,r,kind))
    elif field=='rates':
        if len(p)!=6:
            raise b.UserError('Нужны комиссия и 5 реферальных процентов.')
        fee,*refs=map(percentage,p)
        if fee>=10000 or sum(refs)>fee:
            raise b.UserError('Комиссия должна покрывать все реферальные проценты и быть меньше 100%.')
        post=c.execute("SELECT * FROM bot_prices WHERE kind='post'").fetchone()
        if post['reward']*SCALE+post['cost']*sum(refs)>post['cost']*SCALE:
            raise b.UserError('Проценты превышают доступную комиссию за пост.')
        if any(p['cost']*(10000-fee)//10000<1 for p in c.execute("SELECT * FROM bot_prices WHERE kind<>'post'").fetchall()):
            raise b.UserError('При такой комиссии один из тарифов даёт нулевую награду.')
        c.execute('UPDATE bot_economics SET fee=%s,ref1=%s,ref2=%s,ref3=%s,ref4=%s,ref5=%s WHERE id=1',(fee,*refs))
    elif field=='bonus':
        if len(p)!=1:
            raise b.UserError('Введи только сумму ежедневной награды. Например: 0.50.')
        daily = 0 if p[0] in ('0','0.00','0,00') else b.amount(p[0])
        c.execute('UPDATE bot_settings SET daily=%s WHERE id=1',(daily,))
    elif field=='retention':
        if len(p)!=2 or not all(x.isdecimal() for x in p) or not 1<=int(p[0])<=365 or not 1<=int(p[1])<=10:
            raise b.UserError('Срок: 1–365 суток; множитель: 1–10.')
        c.execute('UPDATE bot_economics SET days=%s,multiplier=%s WHERE id=1',tuple(map(int,p)))
    c.execute("INSERT INTO bot_ledger VALUES(%s,%s,0,'economy_config',%s,%s)",(uuid.uuid4().hex,uid,json.dumps({'field':field,'before':cfg,'input':text},ensure_ascii=False),time.time()))
    b.state(c,uid,'clear')
    return admin(c,uid,'','admin:economy')
