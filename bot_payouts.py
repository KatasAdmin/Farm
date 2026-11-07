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
    c.execute("""CREATE TABLE IF NOT EXISTS bot_crypto_admin_audit(
      id text PRIMARY KEY,payout_id text NOT NULL,actor bigint NOT NULL,
      decision text NOT NULL,provider_status text NOT NULL,created double precision NOT NULL)""")


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
    crypto=c.execute("SELECT state,asset,crypto_amount FROM bot_crypto_payouts WHERE payout_id=%s",(pid,)).fetchone()
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
    if p['status']=='pending' and crypto:
        hold=c.execute('SELECT 1 FROM bot_crypto_liquidity_wait WHERE payout_id=%s',(pid,)).fetchone()
        status_crypto='⏳ Дополнительная проверка: недостаточно средств' if hold else ui.esc(crypto['state'])
        text+='\n\n💎 <b>Crypto Bot</b>: '+ui.esc(crypto['crypto_amount'])+' '+ui.esc(crypto['asset'])+' · '+status_crypto
        if hold:
            text+='\nВыплата возобновится автоматически после подтверждения пополнения CryptoBot.'
            rows.append([b.button('❌ Отменить и вернуть на баланс','admin:cryptocancel:'+pid)])
        else:
            text+='\nРезультат API ещё неизвестен. Автоматический повтор запрещён.'
            if crypto['state']=='review':
                rows.append([b.button('🔄 Проверить в CryptoBot','admin:cryptoverify:'+pid)])
                rows.append([b.button('⚙️ Решить вручную','admin:cryptomanage:'+pid)])
    elif p['status']=='pending':
        if active:
            require(c,pid,uid)
            rows.append([b.button('✅ Перевод выполнен','admin:payrecord:'+pid)])
            text+=tr('\n\n⚠️ Кнопка «✅ Перевод выполнен» сразу закрывает заявку. Нажимай только после успешного банковского перевода. Если результат неизвестен, сначала проверь его в банке.',html_mode=True,section='bot_payouts')
        else:rows.append([b.button('🏦 Взять в работу','admin:payref:'+pid)])
        rows.append([b.button('❌ Отклонить с причиной','admin:rejectpayout:'+pid)])
    return ui.screen(uid,text,rows+[[b.button('⬅️ Выплаты','admin:payouts')]])



def _owner(c,uid):
    row=c.execute('SELECT telegram_id FROM farm_admin_identity WHERE slot=1').fetchone()
    if not row or int(row['telegram_id'])!=uid:
        raise core().UserError('Только владелец может вручную закрывать спорные криптовыплаты.')


def _crypto_review(c,pid):
    b=core()
    payout=c.execute("SELECT * FROM bot_payouts WHERE id=%s AND status='pending' FOR UPDATE",(pid,)).fetchone()
    crypto=c.execute("SELECT * FROM bot_crypto_payouts WHERE payout_id=%s AND state='review' FOR UPDATE",(pid,)).fetchone()
    if not payout or not crypto:
        raise b.UserError('Заявка уже обработана либо не требует ручной сверки.')
    check=c.execute("SELECT check_id,check_url,state FROM bot_crypto_checks WHERE payout_id=%s",(pid,)).fetchone()
    if check and (check['check_id'] is not None or check['check_url'] or check['state']=='active'):
        raise b.UserError('Существующий чек нельзя отменять здесь: сначала проверь его статус в CryptoBot.')
    return payout,crypto


def _provider_status(crypto,payout):
    import bot_crypto_pay as pay
    try:
        found=pay._find_transfer(crypto)
        if found:
            if pay._verified_transfer(crypto,found,payout['uid']):
                return 'completed',found
            # If the provider reports any transfer for the same spend ID,
            # never cancel or mark an ambiguous transfer automatically.
            return 'transfer_exists',found
        return 'not_found',None
    except Exception:
        return 'api_unavailable',None


def _review_screen(c,uid,pid):
    _owner(c,uid)
    payout,crypto=_crypto_review(c,pid)
    return core().bot_ui.screen(uid,
        '⚠️ <b>Ручное решение по CryptoBot</b>\n\n'
        'Заявка: <code>'+pid+'</code>\n'
        'К выводу: '+core().money(payout['amount'])+'\n'
        'USDT: '+crypto['crypto_amount']+'\n\n'
        '<b>Важно:</b> если Crypto Pay уже отправил деньги, возврат суммы на баланс создаст двойную выплату. '
        'Сначала проверь перевод в @CryptoBot по spend_id.\n'
        '«Выплачено» лишь фиксирует реальную внешнюю выплату и НЕ отправляет её повторно.',
        [[core().button('🔍 Сверить через API','admin:cryptoverify:'+pid)],
         [core().button('↩️ Не выплачено — вернуть деньги','admin:cryptodecision:cancel:'+pid)],
         [core().button('✅ Уже выплачено — закрыть','admin:cryptodecision:paid:'+pid)],
         [core().button('⬅️ Заявка','admin:payview:'+pid)]])


def _decision_begin(c,uid,mode,pid):
    b=core()
    _owner(c,uid)
    if mode not in ('cancel','paid'):
        raise b.UserError('Неизвестное решение.')
    payout,crypto=_crypto_review(c,pid)
    provider,found=_provider_status(crypto,payout)
    if provider=='completed':
        raise b.UserError('Crypto Pay подтвердил отправку. Сначала нажми «Проверить в CryptoBot», чтобы закрыть заявку без возврата.')
    if provider=='transfer_exists':
        raise b.UserError('Crypto Pay сообщает о переводе с этим идентификатором. Отмена и ручное закрытие заблокированы до уточнения результата.')
    nonce=uuid.uuid4().hex[:12]
    b.state(c,uid,'admin_crypto_review_decision',{'pid':pid,'mode':mode,'nonce':nonce,'created':time.time()})
    notice=('Подтверждаю, что после независимой проверки перевод или чек НЕ был создан. '
            'Зарезервированная сумма будет возвращена игроку. '
            'Если API недоступен, возможна двойная выплата.'
            if mode=='cancel' else
            'Подтверждаю, что деньги ФАКТИЧЕСКИ отправлены получателю другим способом. '
            'Эта кнопка НЕ отправляет криптовалюту, а только закрывает долг по заявке.')
    return b.bot_ui.screen(uid,'⚠️ <b>Последнее подтверждение</b>\n\n'
        'Заявка: <code>'+pid+'</code>\n'
        'Сумма: '+b.money(payout['amount'])+'\n'
        'API: '+provider+'\n\n'+notice,
        [[b.button('✅ Подтверждаю решение','admin:cryptoconfirm:'+mode+':'+pid+':'+nonce)],
         [b.button('✖️ Не менять','admin:payview:'+pid)]])


def _decision_confirm(c,uid,mode,pid,nonce):
    b=core()
    _owner(c,uid)
    st=b.state(c,uid)
    if (not st or st['state']!='admin_crypto_review_decision'
        or st['data'].get('nonce')!=nonce or st['data'].get('pid')!=pid
        or st['data'].get('mode')!=mode or time.time()-st['data'].get('created',0)>180):
        raise b.UserError('Подтверждение устарело. Начни заново.')
    # Serialize against the automated worker. Do not erase the spend_id.
    c.execute('SELECT pg_advisory_xact_lock(1984537)')
    payout,crypto=_crypto_review(c,pid)
    provider,found=_provider_status(crypto,payout)
    if provider in ('completed','transfer_exists'):
        raise b.UserError('Crypto Pay сообщает о переводе — решение отклонено. Используй сверку API.')
    if mode=='cancel':
        unresolved_check=c.execute("""SELECT state,check_id,check_url FROM bot_crypto_checks
            WHERE payout_id=%s FOR UPDATE""",(pid,)).fetchone()
        if unresolved_check:
            incident=c.execute("""SELECT reason,phase FROM bot_crypto_incidents
                WHERE payout_id=%s""",(pid,)).fetchone()
            # Denied upstream before a valid response, no issued check ID,
            # and explicit owner confirmation; still retains the attempt.
            if (unresolved_check['state']!='review' or unresolved_check['check_id'] is not None
                or unresolved_check['check_url'] or not incident
                or incident['phase']!='createCheck'
                or not incident['reason'].startswith('HTTP 403:')):
                raise b.UserError('Отмена чека недоступна: невозможно подтвердить отказ провайдера. Необходима сверка.')
        c.execute("UPDATE bot_payouts SET status='cancelled' WHERE id=%s AND status='pending'",(pid,))
        c.execute("UPDATE bot_crypto_payouts SET state='completed' WHERE payout_id=%s AND state='review'",(pid,))
        b.change(c,payout['uid'],payout['amount'],'payout_cancel',
                 'Ручная отмена CryptoBot · '+pid+' · админ '+str(uid))
        note='↩️ Выплата CryptoBot отменена администратором. '+b.money(payout['amount'])+' возвращены на баланс.'
    else:
        net=b.bot_admin.net(c,payout)
        c.execute("UPDATE bot_payouts SET status='paid',reference=%s WHERE id=%s AND status='pending'",
                  ('owner_verified_external_'+pid,pid))
        c.execute("UPDATE bot_crypto_payouts SET state='completed' WHERE payout_id=%s AND state='review'",(pid,))
        c.execute('UPDATE bot_cash_pool SET amount=GREATEST(0,amount-%s) WHERE id=1',(net,))
        c.execute("INSERT INTO bot_ledger VALUES(%s,%s,0,'payout_paid',%s,%s)",
                  (uuid.uuid4().hex,payout['uid'],'Внешний перевод подтверждён владельцем · '+pid,time.time()))
        b.bot_payout_channel.enqueue_paid(c,pid,b.money(net),
            recipient_uid=payout['uid'] if payout['public_profile'] else None)
        note='✅ Администратор подтвердил внешнюю выплату '+b.money(net)+'. Заявка закрыта.'
    c.execute('INSERT INTO bot_crypto_admin_audit VALUES(%s,%s,%s,%s,%s,%s)',
              (uuid.uuid4().hex,pid,uid,mode,provider,time.time()))
    b.bot_notifications.enqueue(c,'crypto-owner-resolution:'+pid,note,recipient=payout['uid'])
    b.state(c,uid,'clear')
    return b.bot_ui.screen(uid,'✅ Решение сохранено.\n'+note,
       [[b.button('⬅️ Заявка','admin:payview:'+pid)],
        [b.button('💸 Все выплаты','admin:payouts')]])


def route(c,uid,action):
    b=core()
    if action.startswith('admin:cryptoverify:'):
        _owner(c,uid)
        pid=action.split(':')[-1]
        payout,crypto=_crypto_review(c,pid)
        status,transfer=_provider_status(crypto,payout)
        if status=='completed':
            # Reuse the normal completion accounting, with this open
            # transaction and with no second Crypto Pay transfer.
            import bot_crypto_pay as pay
            net=b.bot_admin.net(c,payout)
            ref='cryptopay_'+str(transfer['transfer_id'])
            c.execute("UPDATE bot_payouts SET status='paid',reference=%s WHERE id=%s",(ref,pid))
            c.execute("UPDATE bot_crypto_payouts SET state='completed',transfer_id=%s WHERE payout_id=%s",
                      (transfer['transfer_id'],pid))
            c.execute('UPDATE bot_cash_pool SET amount=GREATEST(0,amount-%s) WHERE id=1',(net,))
            c.execute("INSERT INTO bot_ledger VALUES(%s,%s,0,'payout_paid',%s,%s)",
                      (uuid.uuid4().hex,payout['uid'],'Crypto Pay подтверждён по API · '+pid,time.time()))
            b.bot_notifications.enqueue(c,'payout-paid:'+pid,
                '✅ CryptoBot подтвердил перевод '+crypto['crypto_amount']+' USDT.',recipient=payout['uid'])
            b.bot_payout_channel.enqueue_paid(c,pid,b.money(net),
                recipient_uid=payout['uid'] if payout['public_profile'] else None)
            return view(c,uid,pid)
        return b.bot_ui.screen(uid,'🔍 <b>Проверка Crypto Pay</b>\n\n'
            'Заявка: <code>'+pid+'</code>\n'
            'Результат: '+{'not_found':'перевод пока не найден',
                'api_unavailable':'API недоступен, результат неизвестен',
                'transfer_exists':'перевод найден, статус требует проверки'}[status]+
            '\n\nОтсутствие записи в API ещё не доказывает, что перевод не произойдёт.',
            [[b.button('⚙️ Ручное решение','admin:cryptomanage:'+pid)],
             [b.button('⬅️ Заявка','admin:payview:'+pid)]])
    if action.startswith('admin:cryptomanage:'):
        return _review_screen(c,uid,action.split(':')[-1])
    if action.startswith('admin:cryptodecision:'):
        _,_,mode,pid=action.split(':',3)
        return _decision_begin(c,uid,mode,pid)
    if action.startswith('admin:cryptoconfirm:'):
        parts=action.split(':')
        if len(parts)!=5:raise b.UserError('Некорректное подтверждение.')
        return _decision_confirm(c,uid,parts[2],parts[3],parts[4])
    if action.startswith('admin:cryptocancel:'):
        pid=action.split(':')[-1]
        c.execute('SELECT pg_advisory_xact_lock(1984537)')
        hold=c.execute('SELECT payout_id FROM bot_crypto_liquidity_wait WHERE payout_id=%s FOR UPDATE',(pid,)).fetchone()
        payout=c.execute("SELECT * FROM bot_payouts WHERE id=%s AND status='pending' FOR UPDATE",(pid,)).fetchone()
        crypto=c.execute("SELECT * FROM bot_crypto_payouts WHERE payout_id=%s AND state='pending' FOR UPDATE",(pid,)).fetchone()
        if not (hold and payout and crypto):
            raise b.UserError('Отмена недоступна: выплата не подтверждена как ожидающая резерв. Необходимо проверить перевод.')
        if c.execute("SELECT 1 FROM bot_crypto_checks WHERE payout_id=%s",(pid,)).fetchone():
            raise b.UserError('Для этой заявки существует чек. Сначала сверь его состояние в CryptoBot.')
        c.execute('DELETE FROM bot_crypto_liquidity_wait WHERE payout_id=%s',(pid,))
        c.execute("DELETE FROM bot_crypto_payouts WHERE payout_id=%s AND state='pending'",(pid,))
        c.execute("UPDATE bot_payouts SET status='cancelled' WHERE id=%s AND status='pending'",(pid,))
        b.change(c,payout['uid'],payout['amount'],'payout_cancel','Возврат резерва CryptoBot · '+pid)
        b.bot_notifications.enqueue(c,'liquidity-cancelled:'+pid,
            '↩️ Выплата CryptoBot отменена владельцем. '+b.money(payout['amount'])+
            ' возвращены на твой баланс.',recipient=payout['uid'])
        return view(c,uid,pid)
    if action.startswith('admin:payview:'):
        b.state(c,uid,'clear')
        return view(c,uid,action.split(':')[-1])
    if action.startswith('admin:payref:'):
        b.state(c,uid,'clear')
        pid=action.split(':')[-1]
        if c.execute('SELECT 1 FROM bot_crypto_payouts WHERE payout_id=%s',(pid,)).fetchone():
            raise b.UserError('Этот вывод выполняется через Crypto Bot и не подтверждается вручную.')
        claim(c,pid,uid)
        return view(c,uid,pid)
    if action.startswith('admin:payrecord:'):
        pid=action.split(':')[-1]
        if c.execute('SELECT 1 FROM bot_crypto_payouts WHERE payout_id=%s',(pid,)).fetchone():
            raise b.UserError('Этот вывод выполняется через Crypto Bot.')
        require(c,pid,uid)
        return b.complete_manual_payout(c,uid,pid)
    return None


def debt_notice(c,uid,event):
    b=core()
    debt=c.execute('SELECT amount FROM bot_debts WHERE uid=%s',(uid,)).fetchone()
    if not debt or not debt['amount']:return
    rows=c.execute("SELECT p.id FROM bot_payouts p JOIN bot_payout_work w ON w.id=p.id WHERE p.uid=%s AND p.status='pending' AND w.phase='working'",(uid,)).fetchall()
    for row in rows:
        b.bot_notifications.enqueue(c,'working-debt:'+row['id']+':'+event,tr('⚠️ Долг у получателя выплаты в работе\n\nИгрок: {v0}\nЗадолженность: {v1}\nЗаявка: {v2}\n\nПроверь результат банковского перевода. Заявка автоматически не отменена, чтобы не вернуть уже отправленные деньги повторно.',{'v0':uid,'v1':b.money(debt['amount']),'v2':row['id']},section='notifications'),'admin:payview:'+row['id'],subject=uid)
