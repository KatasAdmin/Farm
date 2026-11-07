"""Owner account inspection and reasoned, replay-safe wallet corrections."""
import datetime as dt
import uuid
import bot_account_controls as controls
import bot_account_details as details
import bot_identity
from zoneinfo import ZoneInfo


def core():
    import task_bot
    return task_bot


def target_id(raw):
    if not raw.isdecimal() or len(raw)>19 or not 0<int(raw)<=9223372036854775807:
        raise core().UserError('Укажи корректный Telegram ID пользователя.')
    return int(raw)


def page_number(raw):
    if not raw.isdecimal() or len(raw)>6 or int(raw)>100000:
        raise core().UserError('Неизвестная страница.')
    return int(raw)


def get(c,target):
    row=c.execute('SELECT * FROM bot_accounts WHERE uid=%s',(target,)).fetchone()
    if not row:raise core().UserError('Аккаунт не найден. Пользователь должен сначала открыть бота.')
    return row


def date(value):
    return dt.datetime.fromtimestamp(value,ZoneInfo('Europe/Kyiv')).strftime('%d.%m.%Y %H:%M')


def listing(c,uid,page=0,query='',review=False,flock=False):
    b=core();b.state(c,uid,'clear')
    if not 0<=page<=100000:raise b.UserError('Неизвестная страница.')
    if flock:
        rows=c.execute('SELECT a.*,p.chickens+coalesce(p.geese,0) AS birds FROM bot_accounts a JOIN players p ON p.telegram_id=a.uid ORDER BY birds DESC,a.uid LIMIT 9 OFFSET %s',(page*8,)).fetchall()
    elif review:
        rows=c.execute('SELECT a.* FROM bot_accounts a JOIN bot_account_controls k ON k.uid=a.uid WHERE k.suspicious=1 OR k.withdraw_blocked=1 ORDER BY k.updated DESC,a.uid LIMIT 9 OFFSET %s',(page*8,)).fetchall()
    elif query:
        kind,value=bot_identity.parse_query(query)
        if kind=='invalid':raise b.UserError('Пришли ник, ID, Telegram-ссылку, @username или телефон.')
        if kind=='uid':
            target=target_id(value)
            rows=c.execute('SELECT * FROM bot_accounts WHERE uid=%s',(target,)).fetchall()
            if not rows:
                normalized=bot_identity.phone(value)
                rows=c.execute('SELECT a.* FROM bot_accounts a JOIN bot_identities i ON i.uid=a.uid WHERE i.phone=%s ORDER BY a.uid',(normalized or '',)).fetchall()
        elif kind in ('username','phone'):
            field='username' if kind=='username' else 'phone'
            rows=c.execute('SELECT a.* FROM bot_accounts a JOIN bot_identities i ON i.uid=a.uid WHERE i.'+field+'=%s ORDER BY a.uid',(value,)).fetchall()
        else:
            pattern='%'+value.lower().replace('!','!!').replace('%','!%').replace('_','!_')+'%'
            rows=c.execute("SELECT DISTINCT a.* FROM bot_accounts a LEFT JOIN players p ON p.telegram_id=a.uid LEFT JOIN bot_identities i ON i.uid=a.uid WHERE lower(a.name) LIKE %s ESCAPE '!' OR lower(p.name) LIKE %s ESCAPE '!' OR p.id=%s OR i.username=%s ORDER BY a.created DESC,a.uid LIMIT 21",(pattern,pattern,value,value.lower())).fetchall()
    else:
        rows=c.execute('SELECT * FROM bot_accounts ORDER BY created DESC,uid LIMIT 9 OFFSET %s',(page*8,)).fetchall()
    limit=20 if query else 8
    buttons=[[b.button(r['name'][:24]+(' · '+str(r['birds'])+' птиц' if flock else '')+' · '+str(r['uid']),'admin:account:'+str(r['uid']))] for r in rows[:limit]]
    nav=[]
    prefix='admin:accountflock:' if flock else 'admin:accountreviews:' if review else 'admin:accounts:'
    if not query:
        if page:nav.append(b.button('⬅️ Назад',prefix+str(page-1)))
        if len(rows)>limit:nav.append(b.button('Далее ➡️',prefix+str(page+1)))
    if nav:buttons.append(nav)
    buttons.append([b.button('🐔 По размеру стада','admin:accountflock:0')])
    buttons.append([b.button('👥 Все аккаунты' if review else '⚠️ Отмеченные и заблокированные','admin:accounts:0' if review else 'admin:accountreviews:0')])
    buttons.extend([[b.button('🔎 Поиск игрока','admin:accountsearch')],[b.button('⬅️ Админ-панель','admin')]])
    return b.bot_ui.screen(uid,('⚠️ <b>Отмеченные и заблокированные</b>\n\n' if review else '👥 <b>Аккаунты игроков</b>\n\n')+('Выбери аккаунт. Поиск по Telegram ID точный.' if rows else 'Аккаунты не найдены.'),buttons)


def card(c,uid,target):
    b=core();a=get(c,target);b.state(c,uid,'clear');esc=b.bot_ui.esc
    farm=c.execute('SELECT * FROM players WHERE telegram_id=%s',(target,)).fetchone()
    debt=c.execute('SELECT amount FROM bot_debts WHERE uid=%s',(target,)).fetchone()
    text=('👤 <b>Аккаунт игрока</b>\n'
          '<b>'+esc(a['name'])+'</b>\n'
          'Telegram ID: <code>'+str(target)+'</code>\n'
          '💰 Доступно: <b>'+b.money(a['available'])+'</b>'
          ' · долг: '+b.money(debt['amount'] if debt else 0)+'\n'
          '📅 С нами: '+date(a['created']))
    if farm:
        text+='\n\n🐔 <b>Ферма</b> · '+esc(farm.get('name','—'))
        text+='\nМонеты: '+str(farm['coins'])+' · Куры: '+str(farm.get('chickens',0))
        text+=' · Гуси: '+str(farm.get('geese',0))
    else:
        text+='\n\n🐔 Ферма не привязана'
    identity=c.execute('SELECT username,phone FROM bot_identities WHERE uid=%s',(target,)).fetchone()
    if identity and identity['username']:
        text+='\nTelegram: @'+esc(identity['username'])
    if identity and identity['phone']:
        text+=' · '+esc(identity['phone'])
    control=controls.get(c,target)
    text+='\n\n🔒 Вывод: <b>'+('заблокирован' if control['withdraw_blocked'] else 'разрешён')+'</b>'
    if control['withdraw_blocked']:text+='\nПричина блокировки: '+esc(control['block_reason'][:120])
    text+='\n🔎 Проверка: <b>'+('требует проверки' if control['suspicious'] else 'без отметки')+'</b>'
    if control['suspicious']:text+='\nЗаметка администратора: '+esc(control['flag_reason'][:120])
    payouts=c.execute('SELECT * FROM bot_payouts WHERE uid=%s ORDER BY created DESC,id LIMIT 5',(target,)).fetchall()
    labels={'pending':'ожидает','paid':'выплачено','rejected':'отклонено','cancelled':'отменено'}
    buttons=[[{'text':'↗️ Профиль Telegram','url':'tg://user?id='+str(target)}],
             [b.button('➕ Начислить в бот','admin:accountop:credit:'+str(target)),b.button('➖ Списать из бота','admin:accountop:debit:'+str(target))],
             [b.button('🧾 Операции баланса','admin:accountledger:'+str(target)+':0')]]
    buttons.append([b.button('📋 Подробности фермы','admin:accountdetail:farm:'+str(target)+':0'),
                    b.button('📲 Связь и профиль','admin:accountdetail:support:'+str(target)+':0')])
    for pair in (('farm','finance'),('payments','payouts'),('referrals','tasks'),('farmledger','activity'),('market','incubator')):
        buttons.append([b.button(details.TITLES[k],'admin:accountdetail:'+k+':'+str(target)+':0') for k in pair])
    buttons.append([b.button(details.TITLES['support'],'admin:accountdetail:support:'+str(target)+':0')])
    buttons.append([b.button('🔓 Разблокировать вывод' if control['withdraw_blocked'] else '🔒 Заблокировать вывод','admin:accountcontrol:'+('unblock' if control['withdraw_blocked'] else 'block')+':'+str(target))])
    buttons.append([b.button('✅ Снять отметку' if control['suspicious'] else '⚠️ Требует проверки','admin:accountcontrol:'+('unflag' if control['suspicious'] else 'flag')+':'+str(target))])
    buttons.append([b.button('🛡 История проверок и блокировок','admin:accountaudit:'+str(target))])
    if payouts:
        text+='\n\n💸 <b>Последние заявки на вывод</b>'
        for p in payouts:buttons.append([b.button(b.money(p['amount'])+' · '+labels[p['status']]+' · '+p['id'][:6],'admin:payview:'+p['id'])])
    buttons.extend([[b.button('🔄 Обновить','admin:account:'+str(target))],[b.button('⬅️ Аккаунты','admin:accounts:0')]])
    return b.bot_ui.screen(uid,text,buttons)


def ledger(c,uid,target,page):
    b=core();get(c,target);b.state(c,uid,'clear')
    if not 0<=page<=100000:raise b.UserError('Неизвестная страница.')
    rows=c.execute('SELECT * FROM bot_ledger WHERE uid=%s ORDER BY created DESC,id LIMIT 7 OFFSET %s',(target,page*6)).fetchall()
    lines=['🧾 <b>Операции баланса</b>\nTelegram ID: <code>'+str(target)+'</code>']
    for r in rows[:6]:lines.append(date(r['created'])+' · <b>'+('+' if r['delta']>0 else '−' if r['delta']<0 else '')+b.money(abs(r['delta']))+'</b>\n'+b.bot_ui.esc(r['kind'])+'\n'+b.bot_ui.esc(r['details'][:220]))
    if not rows:lines.append('Операций пока нет.')
    nav=[]
    if page:nav.append(b.button('⬅️ Назад','admin:accountledger:'+str(target)+':'+str(page-1)))
    if len(rows)>6:nav.append(b.button('Далее ➡️','admin:accountledger:'+str(target)+':'+str(page+1)))
    return b.bot_ui.screen(uid,'\n\n'.join(lines),([nav] if nav else [])+[[b.button('⬅️ Аккаунт','admin:account:'+str(target))]])


def route(c,uid,action):
    b=core()
    if action.startswith('admin:accountdetail:'):
        parts=action.split(':')
        if len(parts)!=5:raise b.UserError('Неизвестная страница.')
        return details.screen(c,uid,target_id(parts[3]),parts[2],page_number(parts[4]))
    if action.startswith('admin:accountflock:'):return listing(c,uid,page_number(action.split(':')[-1]),flock=True)
    if action.startswith('admin:accountreviews:'):return listing(c,uid,page_number(action.split(':')[-1]),review=True)
    if action.startswith('admin:accountaudit:'):
        parts=action.split(':')
        if len(parts) not in (3,4):raise b.UserError('Неизвестная страница.')
        target=target_id(parts[2]);page=page_number(parts[3]) if len(parts)==4 else 0
        get(c,target);b.state(c,uid,'clear')
        rows=c.execute('SELECT * FROM bot_account_control_audit WHERE uid=%s ORDER BY created DESC,id LIMIT 3 OFFSET %s',(target,page*2)).fetchall()
        labels={'block':'🔒 Вывод заблокирован','unblock':'🔓 Вывод разрешён','flag':'⚠️ Требует проверки','unflag':'✅ Отметка снята'}
        lines=[date(r['created'])+' · '+labels[r['operation']]+'\nАдмин '+str(r['actor'])+'\n'+b.bot_ui.esc(r['reason']) for r in rows[:2]]
        nav=[]
        if page:nav.append(b.button('⬅️ Назад','admin:accountaudit:'+str(target)+':'+str(page-1)))
        if len(rows)>2:nav.append(b.button('Далее ➡️','admin:accountaudit:'+str(target)+':'+str(page+1)))
        return b.bot_ui.screen(uid,'🛡 <b>История изменений</b>\nTelegram ID: '+str(target)+'\n\n'+('\n\n'.join(lines) or 'История пуста.'),([nav] if nav else [])+[[b.button('⬅️ Аккаунт','admin:account:'+str(target))]])
    if action.startswith('admin:accounts:'):return listing(c,uid,page_number(action.split(':')[-1]))
    if action=='admin:accountsearch':
        b.state(c,uid,'admin_account_search')
        return b.bot_ui.input_screen(uid,'🔎 Пришли ник, ID, @username, ссылку Telegram или номер телефона (+380… / 06…). По телефону найдём только тех, кто сам поделился своим номером с ботом.')
    if action.startswith('admin:account:'):return card(c,uid,target_id(action.split(':')[-1]))
    if action.startswith('admin:accountledger:'):
        parts=action.split(':');return ledger(c,uid,target_id(parts[2]),page_number(parts[3]))
    if action.startswith('admin:accountop:'):
        parts=action.split(':');op=parts[2];target=target_id(parts[3]);a=get(c,target)
        if op not in ('credit','debit'):raise b.UserError('Неизвестная операция.')
        b.state(c,uid,'admin_account_amount',{'target':target,'op':op})
        return b.bot_ui.input_screen(uid,('➕ Начисление' if op=='credit' else '➖ Списание')+' на балансе бота\nИгрок: '+b.bot_ui.esc(a['name'])+' · '+str(target)+'\nБаланс: '+b.money(a['available'])+'\n\nВведи сумму в гривнах. Монеты фермы не меняются.')
    if action.startswith('admin:accountcontrol:'):
        parts=action.split(':');op=parts[2];target=target_id(parts[3]);get(c,target)
        if op not in ('block','unblock','flag','unflag'):raise b.UserError('Неизвестное действие.')
        b.state(c,uid,'admin_account_control_reason',{'target':target,'op':op})
        return b.bot_ui.input_screen(uid,'Укажи причину: от 5 до 300 символов. Блокировка запрещает новые заявки и переводы из фермы. Старые заявки не отменяются; уже отправленную выплату можно подтвердить. Отметка для проверки видна только администратору и сама по себе не блокирует вывод.')
    if action.startswith('admin:accountcontrolconfirm:'):
        st=b.state(c,uid)
        if not st or st['state']!='admin_account_control_confirm' or st['data'].get('nonce')!=action.split(':')[-1]:raise b.UserError('Подтверждение устарело. Открой аккаунт заново.')
        d=st['data'];controls.set_control(c,d['target'],uid,d['op'],d['reason'])
        b.state(c,uid,'clear')
        return card(c,uid,d['target'])
    if action.startswith('admin:accountconfirm:'):
        st=b.state(c,uid)
        if not st or st['state']!='admin_account_confirm' or st['data'].get('nonce')!=action.split(':')[-1]:raise b.UserError('Подтверждение устарело. Открой аккаунт заново.')
        d=st['data'];get(c,d['target'])
        delta=d['amount'] if d['op']=='credit' else -d['amount']
        b.change(c,d['target'],delta,'admin_adjustment','Админ '+str(uid)+' · '+d['reason']+' · '+d['nonce'])
        b.state(c,uid,'clear')
        return card(c,uid,d['target'])
    return None


def input_text(c,uid,text,current):
    b=core();d=current['data'];stage=current['state']
    if stage=='admin_account_search':
        if not 1<=len(text.strip())<=80:raise b.UserError('Для поиска введи от 1 до 80 символов.')
        return listing(c,uid,query=text.strip())
    if stage=='admin_account_amount':
        d['amount']=b.amount(text.strip());a=get(c,d['target'])
        if d['op']=='debit' and d['amount']>a['available']:raise b.UserError('Сумма больше доступного баланса. Зарезервированные выплаты не списываются.')
        b.state(c,uid,'admin_account_reason',d)
        return b.bot_ui.input_screen(uid,'Укажи причину изменения баланса: от 5 до 300 символов. Она сохранится в истории операций.')
    if stage=='admin_account_control_reason':
        if not 5<=len(text.strip())<=300:raise b.UserError('Причина: от 5 до 300 символов.')
        d.update(reason=text.strip(),nonce=uuid.uuid4().hex[:12]);a=get(c,d['target'])
        b.state(c,uid,'admin_account_control_confirm',d)
        label={'block':'Заблокировать вывод','unblock':'Разблокировать вывод','flag':'Отметить для проверки','unflag':'Снять отметку'}[d['op']]
        return b.bot_ui.screen(uid,'<b>'+label+'?</b>\n\nИгрок: '+b.bot_ui.esc(a['name'])+' · '+str(d['target'])+'\nПричина: '+b.bot_ui.esc(d['reason']),[[b.button('✅ Подтвердить','admin:accountcontrolconfirm:'+d['nonce'])],[b.button('✖️ Отмена','admin:account:'+str(d['target']))]])
    if stage=='admin_account_reason':
        if not 5<=len(text.strip())<=300:raise b.UserError('Причина: от 5 до 300 символов.')
        d.update(reason=text.strip(),nonce=uuid.uuid4().hex[:12]);a=get(c,d['target'])
        b.state(c,uid,'admin_account_confirm',d)
        label='Начислить' if d['op']=='credit' else 'Списать'
        return b.bot_ui.screen(uid,'💰 <b>Подтверждение изменения баланса бота</b>\n\nИгрок: '+b.bot_ui.esc(a['name'])+'\nTelegram ID: <code>'+str(d['target'])+'</code>\n'+label+': <b>'+b.money(d['amount'])+'</b>\nПричина: '+b.bot_ui.esc(d['reason'])+'\n\nЭто корректировка баланса, а не банковский перевод.',[[b.button('✅ '+label,'admin:accountconfirm:'+d['nonce'])],[b.button('✖️ Отмена','admin:account:'+str(d['target']))]])
    return b.bot_ui.input_screen(uid,'Подтверди действие кнопкой выше или отмени форму.')
