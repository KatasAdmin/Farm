"""Manual payouts stay reserved while an administrator performs the bank transfer."""
import time
import uuid
import bot_account_controls as controls
from bot_copy import tr


def core():
    import task_bot
    return task_bot


def initialize(c):
    c.execute("""CREATE TABLE IF NOT EXISTS bot_payout_work(id text PRIMARY KEY,admin bigint NOT NULL,
      token text NOT NULL,started double precision NOT NULL,phase text NOT NULL DEFAULT 'working')""")


def work(c,pid):
    return c.execute("SELECT * FROM bot_payout_work WHERE id=%s AND phase='working'",(pid,)).fetchone()


def require(c,pid,uid):
    row=work(c,pid)
    if not row or row['admin']!=uid:
        raise core().UserError(tr('Сначала открой заявку и нажми «Взять в работу».',section='bot_payouts'))
    return row


def claim(c,pid,uid):
    b=core()
    p=c.execute("SELECT * FROM bot_payouts WHERE id=%s AND status='pending' FOR UPDATE",(pid,)).fetchone()
    if not p:raise b.UserError('Заявка уже закрыта.')
    current=work(c,pid)
    if current:
        require(c,pid,uid)
        return p
    c.execute("INSERT INTO bot_payout_work VALUES(%s,%s,%s,%s,'working')",(pid,uid,uuid.uuid4().hex[:12],time.time()))
    c.execute("INSERT INTO bot_ledger VALUES(%s,%s,0,'payout_processing',%s,%s)",(uuid.uuid4().hex,p['uid'],'В работе · '+pid,time.time()))
    b.bot_notifications.enqueue(c,'payout-working:'+pid,tr('🏦 Заявка {v0} взята в работу. Средства остаются зарезервированы. Отмена недоступна до решения администратора.',{'v0':pid},section='notifications'),recipient=p['uid'])
    return p


def view(c,uid,pid):
    b=core();ui=b.bot_ui
    p=c.execute('SELECT * FROM bot_payouts WHERE id=%s',(pid,)).fetchone()
    if not p:raise b.UserError('Заявка не найдена.')
    active=work(c,pid)
    status='🏦 В работе' if active else {'pending':'⏳ Ожидает проверки','paid':'✅ Выплачено','rejected':'❌ Отклонено','cancelled':'Отменено'}[p['status']]
    text=tr('💸 <b>Заявка на вывод</b>\n\nНомер: <code>{v0}</code>\nИгрок: {v1}\nСтатус: <b>{v2}</b>\nС баланса: {v3}\nК переводу: <b>{v4}</b>\nРеквизиты: {v5}',{'v0':pid,'v1':p['uid'],'v2':status,'v3':b.money(p['amount']),'v4':b.money(b.bot_admin.net(c,p)),'v5':ui.esc(p['destination'])},html_mode=True,section='bot_payouts')
    control=controls.get(c,p['uid'])
    if control['withdraw_blocked']:text+='\n\n🔒 <b>Вывод заблокирован</b>\n'+ui.esc(control['block_reason'])+'\nСтарая заявка сохранена. Если перевод уже отправлен, подтверди его; иначе сначала проверь блокировку.'
    if control['suspicious']:text+='\n\n⚠️ <b>Аккаунт требует проверки</b>\n'+ui.esc(control['flag_reason'])
    account=c.execute('SELECT name FROM bot_accounts WHERE uid=%s',(p['uid'],)).fetchone()
    farm=c.execute('SELECT * FROM players WHERE telegram_id=%s',(p['uid'],)).fetchone()
    text+='\n\n👤 Имя в боте: <b>'+ui.esc(account['name'] if account else '—')+'</b>\nTelegram ID: <code>'+str(p['uid'])+'</code>'
    if farm:text+='\nНик фермы: <b>'+ui.esc(farm.get('name','—'))+'</b>\nID фермы: <code>'+ui.esc(farm['id'])+'</code>'
    debt=c.execute('SELECT amount FROM bot_debts WHERE uid=%s',(p['uid'],)).fetchone()
    if debt and debt['amount']:
        text+=tr('\n\n⚠️ Задолженность получателя: {v0}. Проверь, выполнен ли уже банковский перевод. Не подтверждай отказ, если перевод отправлен или его результат неизвестен.',{'v0':b.money(debt['amount'])},html_mode=True,section='bot_payouts')
    rows=[[b.button('👤 Открыть аккаунт игрока','admin:account:'+str(p['uid']))]]
    if p['status']=='pending':
        if active:
            require(c,pid,uid)
            rows.append([b.button('✅ Перевод выполнен','admin:payrecord:'+pid)])
            text+=tr('\n\nПосле фактического перевода нажми «✅ Перевод выполнен» и подтверди действие. Если результат перевода неизвестен, сначала проверь его в банке.',html_mode=True,section='bot_payouts')
        else:rows.append([b.button('🏦 Взять в работу','admin:payref:'+pid)])
        rows.append([b.button('❌ Отклонить с причиной','admin:rejectpayout:'+pid)])
    return ui.screen(uid,text,rows+[[b.button('⬅️ Выплаты','admin:payouts')]])


def route(c,uid,action):
    b=core()
    if action.startswith('admin:payview:'):
        b.state(c,uid,'clear')
        return view(c,uid,action.split(':')[-1])
    if action.startswith('admin:payref:'):
        b.state(c,uid,'clear')
        pid=action.split(':')[-1];claim(c,pid,uid)
        return view(c,uid,pid)
    if action.startswith('admin:payrecord:'):
        pid=action.split(':')[-1];require(c,pid,uid)
        p=c.execute("SELECT * FROM bot_payouts WHERE id=%s AND status='pending'",(pid,)).fetchone()
        if not p:raise b.UserError('Заявка уже закрыта.')
        work_record=require(c,pid,uid)
        nonce=uuid.uuid4().hex[:12]
        # The internal reference uniquely identifies this confirmed bank payout.
        # Keep the legacy /botpaid <id> <bank-reference> path for explicit reconciliation.
        reference='confirmed-'+uuid.uuid4().hex
        b.state(c,uid,'admin_pay_confirm',{
            'id':pid,'reference':reference,
            'work_token':work_record['token'],'nonce':nonce})
        return b.say(uid,tr(
            '✅ Подтвердить выплату {v0} пользователю {v1}?\n\n'
            'Нажимай подтверждение ТОЛЬКО если перевод уже выполнен. '
            'Никаких банковских операций бот не совершает.',
            {'v0':b.money(b.bot_admin.net(c,p)),'v1':str(p['uid'])},
            section='bot_payouts'),[[
                b.button('✅ Да, деньги отправлены','admin:payconfirm:'+nonce),
                b.button('Отмена','admin:cancel')
            ]])
    return None


def debt_notice(c,uid,event):
    b=core()
    debt=c.execute('SELECT amount FROM bot_debts WHERE uid=%s',(uid,)).fetchone()
    if not debt or not debt['amount']:return
    rows=c.execute("SELECT p.id FROM bot_payouts p JOIN bot_payout_work w ON w.id=p.id WHERE p.uid=%s AND p.status='pending' AND w.phase='working'",(uid,)).fetchall()
    for row in rows:
        b.bot_notifications.enqueue(c,'working-debt:'+row['id']+':'+event,tr('⚠️ Долг у получателя выплаты в работе\n\nИгрок: {v0}\nЗадолженность: {v1}\nЗаявка: {v2}\n\nПроверь результат банковского перевода. Заявка автоматически не отменена, чтобы не вернуть уже отправленные деньги повторно.',{'v0':uid,'v1':b.money(debt['amount']),'v2':row['id']},section='notifications'),'admin:payview:'+row['id'],subject=uid)
