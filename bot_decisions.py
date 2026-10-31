"""Reasoned refusals are checked again at confirmation; drafts never move money."""
import time
import uuid
from bot_copy import tr


def core():
    import task_bot
    return task_bot


def initialize(c):
    c.execute('CREATE TABLE IF NOT EXISTS bot_decisions(id text PRIMARY KEY,kind text NOT NULL,target text NOT NULL,worker bigint NOT NULL,actor bigint NOT NULL,reason text NOT NULL,created double precision NOT NULL)')


def target(c,uid,kind,key,worker=0):
    b=core()
    if kind=='payout':
        row=c.execute("SELECT * FROM bot_payouts WHERE id=%s AND status='pending' FOR UPDATE",(key,)).fetchone()
        active=b.bot_payouts.work(c,key)
        if active:b.bot_payouts.require(c,key,uid)
    elif kind=='card':row=c.execute("SELECT * FROM bot_card_topups WHERE id=%s AND status='pending' FOR UPDATE",(key,)).fetchone()
    elif kind=='task':row=c.execute("SELECT * FROM bot_tasks WHERE id=%s AND status='pending' FOR UPDATE",(key,)).fetchone()
    elif kind=='work':
        row=c.execute("SELECT * FROM bot_tasks WHERE id=%s AND owner=%s AND status='active' FOR UPDATE",(key,uid)).fetchone()
        if not row or not c.execute("SELECT 1 FROM bot_claims WHERE task=%s AND uid=%s AND status='review'",(key,worker)).fetchone():
            raise b.UserError('Работа уже проверена или принадлежит другому рекламодателю.')
    else:raise b.UserError('Неизвестное решение.')
    if not row:raise b.UserError('Заявка уже обработана.')
    return row


def begin(c,uid,kind,key,worker=0):
    b=core();target(c,uid,kind,key,worker)
    b.state(c,uid,'work_rejection_reason' if kind=='work' else 'admin_rejection_reason',{'kind':kind,'id':key,'worker':worker})
    return b.bot_ui.input_screen(uid,tr('📝 <b>Причина отказа</b>\n\nОбъясни, что не подходит и что нужно исправить: от 5 до 500 символов. Причину увидит пользователь. До подтверждения решение не применяется.',html_mode=True,section='bot_decisions'))


def input_text(c,uid,text,st):
    b=core();data=st['data']
    if st['state'].endswith('_confirm'):
        return b.bot_ui.input_screen(uid,'Подтверди решение кнопкой выше или отмени форму.')
    if not 5<=len(text.strip())<=500 or any(ord(ch)<32 and ch!='\n' for ch in text):raise b.UserError('Причина должна содержать от 5 до 500 символов.')
    target(c,uid,data['kind'],data['id'],data['worker'])
    data.update(reason=text.strip(),nonce=uuid.uuid4().hex[:12])
    b.state(c,uid,'work_rejection_confirm' if data['kind']=='work' else 'admin_rejection_confirm',data)
    action=('rejectdecision:' if data['kind']=='work' else 'admin:rejectdecision:')+data['nonce']
    note='Если деньги уже переведены или результат перевода неизвестен, не подтверждай отказ.' if data['kind']=='payout' else 'Деньги и статус изменятся только после подтверждения.'
    return b.bot_ui.screen(uid,tr('❌ <b>Подтвердить отказ?</b>\n\nПричина: {v0}\n\n{v1}',{'v0':b.bot_ui.esc(data['reason']),'v1':note},html_mode=True,section='bot_decisions'),[[b.button('❌ Подтвердить отказ',action)],[b.button('✖️ Отмена','cancel_input')]])


def confirm(c,uid,nonce,admin=False):
    b=core();st=b.state(c,uid)
    if not st or st['state'] not in ('admin_rejection_confirm','work_rejection_confirm') or st['data'].get('nonce')!=nonce:raise b.UserError('Подтверждение устарело.')
    d=st['data'];kind,key,worker=d['kind'],d['id'],d['worker']
    if kind!='work' and not admin:raise b.UserError('Доступ только администратору.')
    row=target(c,uid,kind,key,worker)
    recipient=worker if kind=='work' else row['owner'] if kind=='task' else row['uid']
    if kind=='payout':
        c.execute("UPDATE bot_payouts SET status='rejected' WHERE id=%s",(key,))
        c.execute("UPDATE bot_payout_work SET phase='rejected' WHERE id=%s",(key,))
        b.change(c,recipient,row['amount'],'payout_rejected','Возврат по заявке '+key)
        result='Заявка отклонена, деньги возвращены на баланс.'
        detail='Зарезервировано к возврату: '+b.money(row['amount'])+'. При наличии задолженности средства идут на её погашение.'
    elif kind=='card':
        c.execute("UPDATE bot_card_topups SET status='rejected' WHERE id=%s",(key,));result='Квитанция отклонена. Начисления нет.';detail='Зачисления на баланс нет.'
    elif kind=='task':
        c.execute("UPDATE bot_tasks SET status='rejected',remaining=0 WHERE id=%s",(key,))
        b.change(c,recipient,row['remaining'],'task_rejected','Отклонено модерацией '+key)
        result='Задание отклонено, бюджет возвращён.';detail='Остаток бюджета возвращён: '+b.money(row['remaining'])
    else:
        c.execute("UPDATE bot_claims SET status='rejected' WHERE task=%s AND uid=%s",(key,worker))
        result='Работа отклонена. Начисления нет.';detail='Награда не начислена. Можно обратиться в поддержку, если не согласен с решением.'
    decision=uuid.uuid4().hex
    c.execute('INSERT INTO bot_decisions VALUES(%s,%s,%s,%s,%s,%s,%s)',(decision,kind,key,worker,uid,d['reason'],time.time()))
    b.bot_notifications.enqueue(c,'decision:'+decision,tr('❌ Получен отказ\n\nЗаявка: {v0}\nПричина: {v1}\n\n{v2}',{'v0':key,'v1':d['reason'],'v2':detail},section='notifications'),recipient=recipient)
    b.state(c,uid,'clear')
    back='admin:payouts' if kind=='payout' else 'admin:cardtopups' if kind=='card' else 'admin:tasks' if kind=='task' else 'reviews:0'
    return b.say(uid,result,[[b.button('⬅️ К списку',back)]])


def admin(c,uid,action):
    for prefix,kind in [('admin:rejectpayout:','payout'),('admin:cardreject:','card'),('admin:rejecttask:','task')]:
        if action.startswith(prefix):return begin(c,uid,kind,action.split(':')[-1])
    if action.startswith('admin:rejectdecision:'):return confirm(c,uid,action.split(':')[-1],admin=True)
    return None
