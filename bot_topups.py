"""Wallet-specific Stars invoices and owner-verified card receipts.

No bank credit is inferred from a receipt, and Stars do not create UAH cash.
"""
import re
import time
import uuid

PREFIX='wallet_'


def core():
    import task_bot
    return task_bot


def initialize(c):
    for sql in [
        """CREATE TABLE IF NOT EXISTS bot_topup_config(id integer PRIMARY KEY CHECK(id=1),
          star_rate bigint NOT NULL DEFAULT 0 CHECK(star_rate>=0),card text NOT NULL DEFAULT '',
          recipient text NOT NULL DEFAULT '')""",
        'INSERT INTO bot_topup_config(id) VALUES(1) ON CONFLICT DO NOTHING',
        """CREATE TABLE IF NOT EXISTS bot_wallet_stars(id text PRIMARY KEY,uid bigint NOT NULL,
          stars integer NOT NULL CHECK(stars>0),amount bigint NOT NULL CHECK(amount>0),
          status text NOT NULL CHECK(status IN ('created','checkout','paid','refunded')),
          charge_id text UNIQUE,checkout_id text,created double precision NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS bot_card_topups(id text PRIMARY KEY,uid bigint NOT NULL,
          amount bigint NOT NULL CHECK(amount>0),card text NOT NULL,recipient text NOT NULL,
          file_id text NOT NULL,receipt_key text NOT NULL,media text NOT NULL,
          status text NOT NULL CHECK(status IN ('pending','approved','rejected')),
          reference text NOT NULL DEFAULT '',created double precision NOT NULL)""",
        "CREATE UNIQUE INDEX IF NOT EXISTS bot_one_pending_card ON bot_card_topups(uid) WHERE status='pending'",
        'CREATE INDEX IF NOT EXISTS bot_card_receipt ON bot_card_topups(receipt_key,status)',
    ]:
        c.execute(sql)


def config(c):
    return c.execute('SELECT * FROM bot_topup_config WHERE id=1').fetchone()


def menu(c,uid):
    b=core(); b.state(c,uid,'clear')
    return b.bot_ui.screen(uid,'➕ <b>Пополнение баланса</b>\n\nВыбери способ оплаты:\n\n'
        '⭐ <b>Telegram Stars</b> — зачисление автоматически после оплаты.\n'
        '💎 <b>Криптобот</b> — подключим позже.\n'
        '💳 <b>Карта</b> — перевод по реквизитам и квитанция на проверку.',[
        [b.button('⭐ Telegram Stars','topup:stars')],[b.button('💎 Криптобот · скоро','topup:crypto')],
        [b.button('💳 Банковская карта','topup:card')],[b.button('📥 Мои пополнения','topup:mine')],
        [b.button('⬅️ Мой кабинет','cabinet')]])


def route(c,uid,action):
    b=core(); ui=b.bot_ui
    if action=='deposit':
        return menu(c,uid)
    if action=='topup:crypto':
        b.state(c,uid,'clear')
        return ui.screen(uid,'💎 <b>Криптобот</b>\n\nЭтот способ ещё не подключён.',[[b.button('⬅️ Пополнение','deposit')]])
    if action=='topup:stars':
        cfg=config(c)
        if not cfg['star_rate']:
            return ui.screen(uid,'⭐ <b>Telegram Stars</b>\n\nКурс зачисления ещё не установлен администратором. Оплата пока недоступна.',[[b.button('⬅️ Пополнение','deposit')]])
        b.state(c,uid,'topup_stars',{'rate':cfg['star_rate']})
        return ui.screen(uid,'⭐ <b>Пополнить через Stars</b>\n\nКурс: <b>1 Star = '+b.money(cfg['star_rate'])+'</b>\n'
                         'Введи количество Stars целым числом от 1 до 10000. Перед оплатой увидишь сумму зачисления.\n/cancel — отмена.')
    if action=='topup:card':
        cfg=config(c)
        if not cfg['card']:
            return ui.screen(uid,'💳 <b>Перевод на карту</b>\n\nРеквизиты ещё не указаны администратором. Пока ничего не переводи.',[[b.button('⬅️ Пополнение','deposit')]])
        if c.execute("SELECT 1 FROM bot_card_topups WHERE uid=%s AND status='pending'",(uid,)).fetchone():
            raise b.UserError('Квитанция уже на проверке. Статус — в «Мои пополнения».')
        b.state(c,uid,'topup_card_amount',{'card':cfg['card'],'recipient':cfg['recipient']})
        return ui.screen(uid,'💳 <b>Перевод на карту</b>\n\nВведи сумму пополнения в гривнах. Затем получишь реквизиты и сможешь прикрепить квитанцию.\n/cancel — отмена.')
    if action=='topup:mine':
        b.state(c,uid,'clear')
        rows=c.execute("""SELECT id,amount,status,created,'card' AS kind FROM bot_card_topups WHERE uid=%s
          UNION ALL SELECT id,amount,status,created,'stars' AS kind FROM bot_wallet_stars WHERE uid=%s
          ORDER BY created DESC LIMIT 15""",(uid,uid)).fetchall()
        labels={'created':'Счёт создан','checkout':'Ожидаем подтверждение Telegram','paid':'Зачислено',
                'refunded':'Возвращено','pending':'На проверке','approved':'Зачислено','rejected':'Отклонено'}
        return ui.screen(uid,'📥 <b>Мои пополнения</b>\n\n'+('\n'.join(
            ('⭐' if r['kind']=='stars' else '💳')+' '+b.money(r['amount'])+' · '+labels[r['status']]+' · '+r['id'][:8] for r in rows) or 'Пополнений пока нет.'),
            [[b.button('🔄 Обновить','topup:mine')],[b.button('⬅️ Пополнение','deposit')]])
    return None


def input_text(c,uid,text,message,current):
    b=core(); ui=b.bot_ui; stage=current['state']; data=current['data']
    if stage=='topup_stars':
        if not re.fullmatch(r'\d{1,5}',text) or not 1<=int(text)<=10000:
            raise b.UserError('Количество Stars: целое число от 1 до 10000.')
        stars=int(text); amount=stars*data['rate']
        if amount>100_000_000:
            raise b.UserError('Слишком большая сумма. Укажи меньше Stars.')
        order=uuid.uuid4().hex
        c.execute("INSERT INTO bot_wallet_stars VALUES(%s,%s,%s,%s,'created',NULL,NULL,%s)",(order,uid,stars,amount,time.time()))
        b.state(c,uid,'clear')
        return {'method':'sendInvoice','chat_id':uid,'title':'Пополнение баланса бота',
                'description':'На баланс будет зачислено '+b.money(amount)+'. Счёт действителен 1 час.',
                'payload':PREFIX+order,'provider_token':'','currency':'XTR',
                'prices':[{'label':'Пополнение '+b.money(amount),'amount':stars}], 'start_parameter':PREFIX+order}
    if stage=='topup_card_amount':
        amount=b.amount(text)
        data['amount']=amount
        b.state(c,uid,'topup_card_receipt',data)
        return ui.screen(uid,'💳 <b>Реквизиты для перевода</b>\n\nКарта: <code>'+data['card']+'</code>\n'
                         'Получатель: <b>'+ui.esc(data['recipient'])+'</b>\nСумма: <b>'+b.money(amount)+'</b>\n\n'
                         'После перевода отправь квитанцию одним фото или PDF. Зачисление — после проверки поступления администратором.\n/cancel — отмена.')
    if stage=='topup_card_receipt':
        photos=message.get('photo') or []; doc=message.get('document') or {}
        file=photos[-1] if photos else doc
        media='photo' if photos else 'document'
        if message.get('media_group_id') or not file.get('file_id') or (not photos and doc.get('mime_type')!='application/pdf') or file.get('file_size',0)>20_000_000:
            raise b.UserError('Прикрепи одну квитанцию: фото или PDF до 20 МБ. Не альбом и не текст.')
        key=file.get('file_unique_id') or file['file_id']
        if c.execute("SELECT 1 FROM bot_card_topups WHERE (uid=%s OR receipt_key=%s) AND status='pending'",(uid,key)).fetchone() or c.execute("SELECT 1 FROM bot_card_topups WHERE receipt_key=%s AND status='approved'",(key,)).fetchone():
            raise b.UserError('Эта квитанция уже отправлена или оплачена. Проверь «Мои пополнения».')
        tid=uuid.uuid4().hex[:16]
        c.execute("INSERT INTO bot_card_topups VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'pending','',%s)",
                  (tid,uid,data['amount'],data['card'],data['recipient'],file['file_id'],key,media,time.time()))
        b.state(c,uid,'clear')
        return ui.screen(uid,'📨 <b>Квитанция отправлена на проверку</b>\n\nЗаявка: <code>'+tid+'</code>\nСумма: '+b.money(data['amount'])+
                         '\nСтатус доступен в «Мои пополнения».',[[b.button('📥 Мои пополнения','topup:mine')]])
    return None


def payment(payload,db):
    b=core(); q=payload.get('pre_checkout_query'); message=payload.get('message') or {}
    paid=message.get('successful_payment'); refund=message.get('refunded_payment')
    event=q or paid or refund
    raw=event.get('invoice_payload','') if isinstance(event,dict) else ''
    if not isinstance(raw,str) or not raw.startswith(PREFIX):
        return None
    oid=raw[len(PREFIX):]
    with db() as c:
        if not q:
            c.execute('SELECT pg_advisory_xact_lock(1984533)')
            c.execute('SELECT pg_advisory_xact_lock(%s)',(b.LOCK,))
        order=c.execute('SELECT * FROM bot_wallet_stars WHERE id=%s FOR UPDATE',(oid,)).fetchone()
        if q:
            valid=bool(order and order['status'] in ('created','checkout') and type(q.get('from',{}).get('id')) is int and order['uid']==q.get('from',{}).get('id')
                       and q.get('currency')=='XTR' and type(q.get('total_amount')) is int and q['total_amount']==order['stars']
                       and 0<=time.time()-order['created']<3600 and (not order['checkout_id'] or order['checkout_id']==q.get('id')))
            if valid:
                c.execute("UPDATE bot_wallet_stars SET status='checkout',checkout_id=%s WHERE id=%s",(q['id'],oid))
            return {'method':'answerPreCheckoutQuery','pre_checkout_query_id':q['id'],'ok':valid,
                    **({} if valid else {'error_message':'Счёт не найден, устарел или уже оплачен. Создай новый счёт.'})}
        charge=event.get('telegram_payment_charge_id')
        chat=message.get('chat') or {}
        if not order or not isinstance(charge,str) or not charge or event.get('currency')!='XTR' or type(event.get('total_amount')) is not int or event['total_amount']!=order['stars'] or type(chat.get('id')) is not int or chat.get('id')!=order['uid'] or chat.get('type')!='private':
            return {'ok':True}
        if paid:
            if type(message.get('from',{}).get('id')) is not int or message.get('from',{}).get('id')!=order['uid'] or order['status']!='checkout' or c.execute('SELECT 1 FROM bot_wallet_stars WHERE charge_id=%s',(charge,)).fetchone():
                return {'ok':True}
            c.execute("UPDATE bot_wallet_stars SET status='paid',charge_id=%s WHERE id=%s",(charge,oid))
            b.change(c,order['uid'],order['amount'],'stars_wallet_deposit','Оплата Stars · '+oid)
            return b.say(order['uid'],'✅ Оплата получена! На баланс начислено '+b.money(order['amount']),[[b.button('👤 Мой кабинет','cabinet')]])
        # Telegram can deliver a refund before the original success update is processed.
        # Record that terminal state without crediting or debiting an unpaid order.
        if order['status']=='checkout' and not c.execute('SELECT 1 FROM bot_wallet_stars WHERE charge_id=%s',(charge,)).fetchone():
            c.execute("UPDATE bot_wallet_stars SET status='refunded',charge_id=%s WHERE id=%s",(charge,oid))
            return {'ok':True}
        if order['status']=='paid' and order['charge_id']==charge:
            c.execute("UPDATE bot_wallet_stars SET status='refunded' WHERE id=%s",(oid,))
            c.execute('INSERT INTO bot_debts VALUES(%s,%s) ON CONFLICT(uid) DO UPDATE SET amount=bot_debts.amount+EXCLUDED.amount',(order['uid'],order['amount']))
            c.execute("INSERT INTO bot_ledger VALUES(%s,%s,0,'stars_wallet_refund',%s,%s)",(uuid.uuid4().hex,order['uid'],'Возврат оплаты Stars: '+b.money(order['amount'])+' · '+oid,time.time()))
            b.bot_economy.collect_debt(c,order['uid'])
            debt=c.execute('SELECT amount FROM bot_debts WHERE uid=%s',(order['uid'],)).fetchone()['amount']
            if debt:
                p=c.execute("UPDATE bot_payouts SET status='cancelled' WHERE uid=%s AND status='pending' RETURNING amount,id",(order['uid'],)).fetchone()
                if p:
                    b.change(c,order['uid'],p['amount'],'payout_cancel','Отмена заявки при возврате оплаты · '+p['id'])
        return {'ok':True}


def admin(c,uid,action):
    b=core(); ui=b.bot_ui
    if action=='admin:topupsettings':
        cfg=config(c)
        return ui.screen(uid,'⚙️ <b>Пополнения</b>\n\n⭐ За 1 Star: '+(b.money(cfg['star_rate']) if cfg['star_rate'] else 'курс не установлен')+
                         '\n💳 Карта: '+(cfg['card'] or 'не указана')+'\nПолучатель: '+ui.esc(cfg['recipient'])+
                         '\n\nStars учитываются отдельно от реальных гривен банковского резерва.',[
            [b.button('⭐ Курс Stars','admin:topupedit:rate'),b.button('💳 Реквизиты','admin:topupedit:card')],
            [b.button('📨 Квитанции на проверке','admin:cardtopups')]])
    if action.startswith('admin:topupedit:'):
        field=action.split(':')[-1]
        if field not in ('rate','card'):
            raise b.UserError('Неизвестная настройка.')
        b.state(c,uid,'topup_config',{'field':field})
        return ui.screen(uid,'Введи сумму в гривнах за 1 Star. 0 отключает оплату.' if field=='rate' else
                         'Пришли две строки: номер карты (16 цифр) и имя получателя. Минус (-) отключает способ.\n/cancel — отмена.')
    if action=='admin:cardtopups':
        rows=c.execute("SELECT id,amount FROM bot_card_topups WHERE status='pending' ORDER BY created LIMIT 10").fetchall()
        return ui.screen(uid,'📨 <b>Квитанции на проверке</b>\n\nПроверяй фактическое поступление в банке перед зачислением.',
                         [[b.button(r['id']+' · '+b.money(r['amount']),'admin:cardview:'+r['id'])] for r in rows]+[[b.button('⬅️ Пополнения','admin:topupsettings')]])
    if action.startswith(('admin:cardview:','admin:cardapprove:','admin:cardreject:')):
        tid=action.split(':')[-1]
        row=c.execute("SELECT * FROM bot_card_topups WHERE id=%s AND status='pending' FOR UPDATE",(tid,)).fetchone()
        if not row:
            raise b.UserError('Заявка уже обработана или не найдена.')
        if action.startswith('admin:cardreject:'):
            c.execute("UPDATE bot_card_topups SET status='rejected' WHERE id=%s",(tid,))
            return ui.screen(uid,'Заявка отклонена. Начисления нет.')
        if action.startswith('admin:cardapprove:'):
            b.state(c,uid,'topup_bank_reference',{'id':tid,'nonce':uuid.uuid4().hex[:12]})
            return ui.screen(uid,'Введи уникальный номер фактической банковской операции. Сумма: '+b.money(row['amount'])+'\n/cancel — отмена.')
        return {'method':'sendPhoto' if row['media']=='photo' else 'sendDocument','chat_id':uid,
                'photo' if row['media']=='photo' else 'document':row['file_id'],
                'caption':f"Пополнение {tid}\nПользователь: {row['uid']}\nСумма: {b.money(row['amount'])}\nКарта: {row['card']}\nПолучатель: {row['recipient']}",
                'reply_markup':{'inline_keyboard':[[b.button('✅ Зачислить','admin:cardapprove:'+tid),b.button('❌ Отклонить','admin:cardreject:'+tid)]]}}
    if action.startswith('admin:cardconfirm:'):
        st=b.state(c,uid)
        if not st or st['state']!='topup_bank_confirm' or st['data']['nonce']!=action.split(':')[-1]:
            raise b.UserError('Подтверждение устарело.')
        data=st['data']; row=c.execute("SELECT * FROM bot_card_topups WHERE id=%s AND status='pending' FOR UPDATE",(data['id'],)).fetchone()
        if not row:
            raise b.UserError('Заявка уже обработана.')
        if not c.execute('INSERT INTO bot_deposits VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING reference',
                         (data['reference'],row['uid'],row['amount'],time.time())).fetchone():
            raise b.UserError('Эта банковская операция уже учтена. Повторного начисления нет.')
        c.execute("UPDATE bot_card_topups SET status='approved',reference=%s WHERE id=%s",(data['reference'],row['id']))
        c.execute('UPDATE bot_cash_pool SET amount=amount+%s WHERE id=1',(row['amount'],))
        b.change(c,row['uid'],row['amount'],'manual_deposit','Перевод на карту · '+row['id'])
        b.state(c,uid,'clear')
        return ui.screen(uid,'✅ Зачислено '+b.money(row['amount'])+' пользователю '+str(row['uid']))
    return None


def admin_input(c,uid,text,current):
    b=core(); data=current['data']; cfg=config(c)
    if current['state']=='topup_bank_reference':
        if not 3<=len(text)<=80 or any(ord(ch)<32 for ch in text):
            raise b.UserError('Номер банковской операции: от 3 до 80 символов, одной строкой.')
        row=c.execute("SELECT uid,amount FROM bot_card_topups WHERE id=%s AND status='pending'",(data['id'],)).fetchone()
        if not row:
            raise b.UserError('Эта заявка уже обработана.')
        data['reference']=text; b.state(c,uid,'topup_bank_confirm',data)
        return b.bot_ui.screen(uid,'Подтверди зачисление только после проверки поступления в банке.\n'
                               'Пользователь: '+str(row['uid'])+'\nСумма: '+b.money(row['amount'])+'\nЗаявка: '+data['id']+'\nОперация: '+b.bot_ui.esc(text),
                               [[b.button('✅ Подтвердить','admin:cardconfirm:'+data['nonce'])],[b.button('Отмена','cancel_input')]])
    if current['state']=='topup_bank_confirm':
        return b.say(uid,'Используй кнопку подтверждения выше или /cancel.')
    if data['field']=='rate':
        rate=0 if text in ('0','0.00','0,00') else b.amount(text)
        c.execute('UPDATE bot_topup_config SET star_rate=%s WHERE id=1',(rate,))
        detail='Курс Stars: '+b.money(rate)
    else:
        parts=text.splitlines()
        if text=='-':
            card,name='',''
        else:
            card=re.sub(r'[ -]','',parts[0]) if parts else ''
            name=parts[1].strip() if len(parts)==2 else ''
            if not re.fullmatch(r'[0-9]{16}',card) or not 2<=len(name)<=100 or '\x00' in name:
                raise b.UserError('Нужны две строки: 16 цифр карты и имя получателя.')
            digits=[int(ch) for ch in card]
            if sum(sum(divmod(n*2,10)) if i%2==0 else n for i,n in enumerate(digits))%10:
                raise b.UserError('Проверь номер карты: контрольная сумма не сходится.')
        c.execute('UPDATE bot_topup_config SET card=%s,recipient=%s WHERE id=1',(card,name))
        detail='Реквизиты перевода обновлены'
    c.execute("INSERT INTO bot_ledger VALUES(%s,%s,0,'topup_config',%s,%s)",(uuid.uuid4().hex,uid,detail,time.time()))
    b.state(c,uid,'clear')
    return admin(c,uid,'admin:topupsettings')
