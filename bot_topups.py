"""Wallet-specific Stars invoices and owner-verified card receipts.

No bank credit is inferred from a receipt, and Stars do not create UAH cash.
"""
from bot_copy import tr
import re
import time
import uuid
PREFIX = 'wallet_'

def core():
    import task_bot
    return task_bot

def initialize(c):
    for sql in ["CREATE TABLE IF NOT EXISTS bot_topup_config(id integer PRIMARY KEY CHECK(id=1),\n          star_rate bigint NOT NULL DEFAULT 0 CHECK(star_rate>=0),card text NOT NULL DEFAULT '',\n          recipient text NOT NULL DEFAULT '')", 'INSERT INTO bot_topup_config(id) VALUES(1) ON CONFLICT DO NOTHING', 'CREATE TABLE IF NOT EXISTS bot_topup_migrations(id text PRIMARY KEY)', "CREATE TABLE IF NOT EXISTS bot_wallet_stars(id text PRIMARY KEY,uid bigint NOT NULL,\n          stars integer NOT NULL CHECK(stars>0),amount bigint NOT NULL CHECK(amount>0),\n          status text NOT NULL CHECK(status IN ('created','checkout','paid','refunded')),\n          charge_id text UNIQUE,checkout_id text,created double precision NOT NULL)", "CREATE TABLE IF NOT EXISTS bot_card_topups(id text PRIMARY KEY,uid bigint NOT NULL,\n          amount bigint NOT NULL CHECK(amount>0),card text NOT NULL,recipient text NOT NULL,\n          file_id text NOT NULL,receipt_key text NOT NULL,media text NOT NULL,\n          status text NOT NULL CHECK(status IN ('pending','approved','rejected')),\n          reference text NOT NULL DEFAULT '',created double precision NOT NULL)", "CREATE UNIQUE INDEX IF NOT EXISTS bot_one_pending_card ON bot_card_topups(uid) WHERE status='pending'", 'CREATE INDEX IF NOT EXISTS bot_card_receipt ON bot_card_topups(receipt_key,status)']:
        c.execute(sql)
    applied = c.execute("INSERT INTO bot_topup_migrations VALUES('wallet-stars-rate-50-2026-10-31') ON CONFLICT DO NOTHING RETURNING id").fetchone()
    if applied:
        c.execute('UPDATE bot_topup_config SET star_rate=50 WHERE id=1')

def config(c):
    return c.execute('SELECT * FROM bot_topup_config WHERE id=1').fetchone()

def menu(c, uid):
    b = core()
    b.state(c, uid, 'clear')
    return b.bot_ui.screen(uid, tr('➕ <b>Пополнение баланса</b>\n\nВыбери способ оплаты:\n\n⭐ <b>Telegram Stars</b> — зачисление автоматически после оплаты.\n💎 <b>Криптобот</b> — подключим позже.\n💳 <b>Карта</b> — перевод по реквизитам и квитанция на проверку.', html_mode=True, section='bot_topups', limit=3000), [[b.button('⭐ Telegram Stars', 'topup:stars')], [b.button('💎 Криптобот · скоро', 'topup:crypto')], [b.button('💳 Банковская карта', 'topup:card')], [b.button('📥 Мои пополнения', 'topup:mine')], [b.button('⬅️ Мой кабинет', 'cabinet')]])

def route(c, uid, action):
    b = core()
    ui = b.bot_ui
    if action == 'deposit':
        return menu(c, uid)
    if action == 'topup:crypto':
        b.state(c, uid, 'clear')
        return ui.screen(uid, tr('💎 <b>Криптобот</b>\n\nЭтот способ ещё не подключён.', html_mode=True, section='bot_topups', limit=3000), [[b.button('⬅️ Пополнение', 'deposit')]])
    if action == 'topup:stars':
        cfg = config(c)
        if not cfg['star_rate']:
            return ui.screen(uid, tr('⭐ <b>Telegram Stars</b>\n\nКурс зачисления ещё не установлен администратором. Оплата пока недоступна.', html_mode=True, section='bot_topups', limit=3000), [[b.button('⬅️ Пополнение', 'deposit')]])
        b.state(c, uid, 'topup_stars', {'rate': cfg['star_rate'], 'max': b.bot_admin.limits(c)['max_stars']})
        rate_label = '2 Stars = 1,00 грн' if cfg['star_rate'] == 50 else '1 Star = ' + b.money(cfg['star_rate'])
        return ui.input_screen(uid, tr('⭐ <b>Пополнение через Stars</b>\n\n💱 Курс: <b>{v0}</b>\n\nОтправь количество Stars, которое хочешь оплатить.\n✍️ Например: <code>20</code> → <b>{v1}</b> на баланс бота.\n\n🧾 Бот пришлёт счёт. После оплаты сумма зачислится автоматически.\n\n<i>От 1 до {v2} Stars, только целое число.</i>', {'v0': rate_label, 'v1': b.money(20 * cfg['star_rate']), 'v2': str(b.bot_admin.limits(c)['max_stars'])}, html_mode=True, section='bot_topups', limit=3000), cancel_action='deposit')
    if action == 'topup:card':
        cfg = config(c)
        if not cfg['card']:
            return ui.screen(uid, tr('💳 <b>Перевод на карту</b>\n\nРеквизиты ещё не указаны администратором. Пока ничего не переводи.', html_mode=True, section='bot_topups', limit=3000), [[b.button('⬅️ Пополнение', 'deposit')]])
        if c.execute("SELECT 1 FROM bot_card_topups WHERE uid=%s AND status='pending'", (uid,)).fetchone():
            raise b.UserError(tr('Квитанция уже на проверке. Статус — в «Мои пополнения».', html_mode=False, section='bot_topups', limit=3000))
        b.state(c, uid, 'topup_card_amount', {'card': cfg['card'], 'recipient': cfg['recipient']})
        return ui.input_screen(uid, tr('💳 <b>Перевод на карту</b>\n\nВведи сумму пополнения в гривнах. Затем получишь реквизиты и сможешь прикрепить квитанцию.', html_mode=True, section='bot_topups', limit=3000), cancel_action='deposit')
    if action == 'topup:mine':
        b.state(c, uid, 'clear')
        rows = c.execute("SELECT id,amount,status,created,'card' AS kind FROM bot_card_topups WHERE uid=%s\n          UNION ALL SELECT id,amount,status,created,'stars' AS kind FROM bot_wallet_stars WHERE uid=%s\n          ORDER BY created DESC LIMIT 15", (uid, uid)).fetchall()
        labels = {'created': tr('Счёт создан', html_mode=False, section='bot_topups', limit=3000), 'checkout': tr('Ожидаем подтверждение Telegram', html_mode=False, section='bot_topups', limit=3000), 'paid': tr('Зачислено', html_mode=False, section='bot_topups', limit=3000), 'refunded': tr('Возвращено', html_mode=False, section='bot_topups', limit=3000), 'pending': tr('На проверке', html_mode=False, section='bot_topups', limit=3000), 'approved': tr('Зачислено', html_mode=False, section='bot_topups', limit=3000), 'rejected': tr('Отклонено', html_mode=False, section='bot_topups', limit=3000)}
        return ui.screen(uid, tr('📥 <b>Мои пополнения</b>\n\n{v0}', {'v0': '\n'.join((('⭐' if r['kind'] == 'stars' else '💳') + ' ' + b.money(r['amount']) + ' · ' + labels[r['status']] + ' · ' + r['id'][:8] for r in rows)) or 'Пополнений пока нет.'}, html_mode=True, section='bot_topups', limit=3000), [[b.button('🔄 Обновить', 'topup:mine')], [b.button('⬅️ Пополнение', 'deposit')]])
    return None

def input_text(c, uid, text, message, current):
    b = core()
    ui = b.bot_ui
    stage = current['state']
    data = current['data']
    if stage == 'topup_stars':
        if not re.fullmatch('\\d{1,5}', text) or not 1 <= int(text) <= data.get('max', 10000):
            raise b.UserError(tr('Количество Stars: целое число от 1 до {v0}.', {'v0': str(data.get('max', 10000))}, html_mode=False, section='bot_topups', limit=3000))
        stars = int(text)
        amount = stars * data['rate']
        if amount > 100000000:
            raise b.UserError(tr('Слишком большая сумма. Укажи меньше Stars.', html_mode=False, section='bot_topups', limit=3000))
        order = uuid.uuid4().hex
        c.execute("INSERT INTO bot_wallet_stars VALUES(%s,%s,%s,%s,'created',NULL,NULL,%s)", (order, uid, stars, amount, time.time()))
        b.bot_notifications.enqueue(c,'stars-intent:'+order,tr('⭐ Создан счёт на пополнение\n\nИгрок: {v0}\nК оплате: {v1} Stars\nК зачислению: {v2}\n\nСчёт ещё не оплачен.', {'v0': str(uid), 'v1': str(stars), 'v2': b.money(amount)}, section='notifications'),'admin:payments:stars:0',subject=uid,kind='intent')
        b.state(c, uid, 'clear')
        return {'method': 'sendInvoice', 'chat_id': uid, 'title': tr('Пополнение баланса бота', html_mode=False, section='bot_topups', limit=32), 'description': tr('На баланс будет зачислено {v0}. Счёт действителен 1 час.', {'v0': b.money(amount)}, html_mode=False, section='bot_topups', limit=255), 'payload': PREFIX + order, 'provider_token': '', 'currency': 'XTR', 'prices': [{'label': 'Пополнение ' + b.money(amount), 'amount': stars}], 'start_parameter': PREFIX + order}
    if stage == 'topup_card_amount':
        amount = b.amount(text)
        rules = b.bot_admin.limits(c)
        if not rules['card_min'] <= amount <= rules['card_max']:
            raise b.UserError(tr('Сумма перевода: от {v0} до {v1}', {'v0': b.money(rules['card_min']), 'v1': b.money(rules['card_max'])}, html_mode=False, section='bot_topups', limit=3000))
        data['amount'] = amount
        intent=uuid.uuid4().hex
        b.bot_notifications.enqueue(c,'card-intent:'+intent,tr('💳 Пользователь начал пополнение картой\n\nИгрок: {v0}\nСумма: {v1}\n\nРеквизиты выданы. Квитанции пока нет — деньги не зачислены.', {'v0': str(uid), 'v1': b.money(amount)}, section='notifications'),'admin:cardtopups',subject=uid,kind='intent')
        b.state(c, uid, 'topup_card_receipt', data)
        return ui.input_screen(uid, tr('💳 <b>Реквизиты для перевода</b>\n\nКарта: <code>{v0}</code>\nПолучатель: <b>{v1}</b>\nСумма: <b>{v2}</b>\n\nПосле перевода отправь квитанцию одним фото или PDF. Зачисление — после проверки поступления администратором.', {'v0': data['card'], 'v1': ui.esc(data['recipient']), 'v2': b.money(amount)}, html_mode=True, section='bot_topups', limit=3000), cancel_action='deposit')
    if stage == 'topup_card_receipt':
        photos = message.get('photo') or []
        doc = message.get('document') or {}
        file = photos[-1] if photos else doc
        media = 'photo' if photos else 'document'
        if message.get('media_group_id') or not file.get('file_id') or (not photos and doc.get('mime_type') != 'application/pdf') or (file.get('file_size', 0) > 20000000):
            raise b.UserError(tr('Прикрепи одну квитанцию: фото или PDF до 20 МБ. Не альбом и не текст.', html_mode=False, section='bot_topups', limit=3000))
        key = file.get('file_unique_id') or file['file_id']
        if c.execute("SELECT 1 FROM bot_card_topups WHERE (uid=%s OR receipt_key=%s) AND status='pending'", (uid, key)).fetchone() or c.execute("SELECT 1 FROM bot_card_topups WHERE receipt_key=%s AND status='approved'", (key,)).fetchone():
            raise b.UserError(tr('Эта квитанция уже отправлена или оплачена. Проверь «Мои пополнения».', html_mode=False, section='bot_topups', limit=3000))
        tid = uuid.uuid4().hex[:16]
        c.execute("INSERT INTO bot_card_topups VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'pending','',%s)", (tid, uid, data['amount'], data['card'], data['recipient'], file['file_id'], key, media, time.time()))
        b.bot_notifications.enqueue(c,'card-receipt:'+tid,tr('📨 Новая квитанция на проверке\n\nИгрок: {v0}\nСумма: {v1}\nЗаявка: {v2}\n\nПеред зачислением проверь поступление в банке.', {'v0': str(uid), 'v1': b.money(data['amount']), 'v2': tid}, section='notifications'),'admin:cardview:'+tid,subject=uid)
        b.state(c, uid, 'clear')
        return ui.screen(uid, tr('📨 <b>Квитанция отправлена на проверку</b>\n\nЗаявка: <code>{v0}</code>\nСумма: {v1}\nСтатус доступен в «Мои пополнения».', {'v0': tid, 'v1': b.money(data['amount'])}, html_mode=True, section='bot_topups', limit=3000), [[b.button('📥 Мои пополнения', 'topup:mine')]])
    return None

def payment(payload, db):
    b = core()
    q = payload.get('pre_checkout_query')
    message = payload.get('message') or {}
    paid = message.get('successful_payment')
    refund = message.get('refunded_payment')
    event = q or paid or refund
    raw = event.get('invoice_payload', '') if isinstance(event, dict) else ''
    if not isinstance(raw, str) or not raw.startswith(PREFIX):
        return None
    oid = raw[len(PREFIX):]
    with db() as c, b.bot_copy.session(c):
        if not q:
            c.execute('SELECT pg_advisory_xact_lock(1984533)')
            c.execute('SELECT pg_advisory_xact_lock(%s)', (b.LOCK,))
        order = c.execute('SELECT * FROM bot_wallet_stars WHERE id=%s FOR UPDATE', (oid,)).fetchone()
        if q:
            valid = bool(order and order['status'] in ('created', 'checkout') and (type(q.get('from', {}).get('id')) is int) and (order['uid'] == q.get('from', {}).get('id')) and (q.get('currency') == 'XTR') and (type(q.get('total_amount')) is int) and (q['total_amount'] == order['stars']) and (0 <= time.time() - order['created'] < 3600) and (not order['checkout_id'] or order['checkout_id'] == q.get('id')))
            if valid:
                c.execute("UPDATE bot_wallet_stars SET status='checkout',checkout_id=%s WHERE id=%s", (q['id'], oid))
            return {'method': 'answerPreCheckoutQuery', 'pre_checkout_query_id': q['id'], 'ok': valid, **({} if valid else {'error_message': 'Счёт не найден, устарел или уже оплачен. Создай новый счёт.'})}
        charge = event.get('telegram_payment_charge_id')
        chat = message.get('chat') or {}
        if not order or not isinstance(charge, str) or (not charge) or (event.get('currency') != 'XTR') or (type(event.get('total_amount')) is not int) or (event['total_amount'] != order['stars']) or (type(chat.get('id')) is not int) or (chat.get('id') != order['uid']) or (chat.get('type') != 'private'):
            return {'ok': True}
        if paid:
            if type(message.get('from', {}).get('id')) is not int or message.get('from', {}).get('id') != order['uid'] or order['status'] != 'checkout' or c.execute('SELECT 1 FROM bot_wallet_stars WHERE charge_id=%s', (charge,)).fetchone():
                return {'ok': True}
            c.execute("UPDATE bot_wallet_stars SET status='paid',charge_id=%s WHERE id=%s", (charge, oid))
            b.change(c, order['uid'], order['amount'], 'stars_wallet_deposit', 'Оплата Stars · ' + oid)
            b.bot_notifications.enqueue(c,'stars-paid:'+oid,tr('✅ Пополнение Stars оплачено\n\nИгрок: {v0}\nОплачено: {v1} Stars\nЗачислено: {v2}', {'v0': str(order['uid']), 'v1': str(order['stars']), 'v2': b.money(order['amount'])}, section='notifications'),'admin:payments:stars:0',subject=order['uid'])
            return b.say(order['uid'], tr('✅ Оплата получена! На баланс начислено {v0}', {'v0': b.money(order['amount'])}, html_mode=False, section='bot_topups', limit=3000), [[b.button('👤 Мой кабинет', 'cabinet')]])
        if order['status'] == 'checkout' and (not c.execute('SELECT 1 FROM bot_wallet_stars WHERE charge_id=%s', (charge,)).fetchone()):
            c.execute("UPDATE bot_wallet_stars SET status='refunded',charge_id=%s WHERE id=%s", (charge, oid))
            refund_notice(c,order)
            return {'ok': True}
        if order['status'] == 'paid' and order['charge_id'] == charge:
            c.execute("UPDATE bot_wallet_stars SET status='refunded' WHERE id=%s", (oid,))
            refund_notice(c,order)
            c.execute('INSERT INTO bot_debts VALUES(%s,%s) ON CONFLICT(uid) DO UPDATE SET amount=bot_debts.amount+EXCLUDED.amount', (order['uid'], order['amount']))
            c.execute("INSERT INTO bot_ledger VALUES(%s,%s,0,'stars_wallet_refund',%s,%s)", (uuid.uuid4().hex, order['uid'], 'Возврат оплаты Stars: ' + b.money(order['amount']) + ' · ' + oid, time.time()))
            b.bot_economy.collect_debt(c, order['uid'])
            debt = c.execute('SELECT amount FROM bot_debts WHERE uid=%s', (order['uid'],)).fetchone()['amount']
            if debt:
                p = c.execute("UPDATE bot_payouts SET status='cancelled' WHERE uid=%s AND status='pending' RETURNING amount,id", (order['uid'],)).fetchone()
                if p:
                    b.change(c, order['uid'], p['amount'], 'payout_cancel', 'Отмена заявки при возврате оплаты · ' + p['id'])
        return {'ok': True}

def refund_notice(c,order):
    b=core(); oid=order['id']
    b.bot_notifications.enqueue(c,'stars-refunded:'+oid,tr('↩️ Возврат оплаты Stars\n\nИгрок: {v0}\nСумма: {v1} Stars\nЗачисление на баланс отменено.', {'v0': str(order['uid']), 'v1': str(order['stars'])}, section='notifications'),'admin:payments:stars:0',subject=order['uid'])
    b.bot_notifications.enqueue(c,'stars-refunded-user:'+oid,tr('↩️ Telegram подтвердил возврат {v0} Stars. Соответствующее зачисление на баланс отменено.', {'v0': str(order['stars'])}, section='notifications'),recipient=order['uid'])


def admin(c, uid, action):
    b = core()
    ui = b.bot_ui
    if action == 'admin:topupsettings':
        cfg = config(c)
        return ui.screen(uid, tr('⚙️ <b>Пополнения</b>\n\n⭐ За 1 Star: {v0}\n💳 Карта: {v1}\nПолучатель: {v2}\n\nStars учитываются отдельно от реальных гривен банковского резерва.', {'v0': b.money(cfg['star_rate']) if cfg['star_rate'] else 'курс не установлен', 'v1': cfg['card'] or 'не указана', 'v2': ui.esc(cfg['recipient'])}, html_mode=True, section='bot_topups', limit=3000), [[b.button('⭐ Курс Stars', 'admin:topupedit:rate'), b.button('💳 Реквизиты', 'admin:topupedit:card')], [b.button('📨 Квитанции на проверке', 'admin:cardtopups')]])
    if action.startswith('admin:topupedit:'):
        field = action.split(':')[-1]
        if field not in ('rate', 'card'):
            raise b.UserError(tr('Неизвестная настройка.', html_mode=False, section='bot_topups', limit=3000))
        b.state(c, uid, 'topup_config', {'field': field})
        return ui.input_screen(uid, tr('Введи сумму в гривнах за 1 Star. 0 отключает оплату.', html_mode=True, section='bot_topups', limit=3000) if field == 'rate' else tr('Пришли две строки: номер карты (16 цифр) и имя получателя. Минус (-) отключает способ.', html_mode=True, section='bot_topups', limit=3000))
    if action == 'admin:cardtopups':
        rows = c.execute("SELECT id,amount FROM bot_card_topups WHERE status='pending' ORDER BY created LIMIT 10").fetchall()
        return ui.screen(uid, tr('📨 <b>Квитанции на проверке</b>\n\nПроверяй фактическое поступление в банке перед зачислением.', html_mode=True, section='bot_topups', limit=3000), [[b.button(r['id'] + ' · ' + b.money(r['amount']), 'admin:cardview:' + r['id'])] for r in rows] + [[b.button('⬅️ Пополнения', 'admin:topupsettings')]])
    if action.startswith(('admin:cardview:', 'admin:cardapprove:', 'admin:cardreject:')):
        tid = action.split(':')[-1]
        row = c.execute("SELECT * FROM bot_card_topups WHERE id=%s FOR UPDATE", (tid,)).fetchone()
        if not row:
            raise b.UserError(tr('Заявка уже обработана или не найдена.', html_mode=False, section='bot_topups', limit=3000))
        if row['status']!='pending':
            if not action.startswith('admin:cardview:'):
                raise b.UserError('Эта заявка уже обработана. Повторного зачисления нет.')
            status='✅ Зачислено' if row['status']=='approved' else '❌ Отклонено'
            return ui.screen(uid,'💳 <b>Заявка на пополнение</b>\n\n'+ui.esc(tid)+'\nИгрок: '+str(row['uid'])+'\nСумма: '+b.money(row['amount'])+'\nСтатус: <b>'+status+'</b>',[[b.button('🧾 История оплат','admin:payments:card:0')],[b.button('⬅️ Квитанции','admin:cardtopups')]])
        if action.startswith('admin:cardreject:'):
            c.execute("UPDATE bot_card_topups SET status='rejected' WHERE id=%s", (tid,))
            b.bot_notifications.enqueue(c,'card-rejected:'+tid,tr('❌ Квитанция отклонена\n\nЗаявка: {v0}\nСумма: {v1}\nДеньги на баланс не зачислены. Если перевод был выполнен, обратись в поддержку.', {'v0': tid, 'v1': b.money(row['amount'])}, section='notifications'),recipient=row['uid'])
            return ui.screen(uid, tr('Заявка отклонена. Начисления нет.', html_mode=True, section='bot_topups', limit=3000))
        if action.startswith('admin:cardapprove:'):
            b.state(c, uid, 'topup_bank_reference', {'id': tid, 'nonce': uuid.uuid4().hex[:12]})
            return ui.input_screen(uid, tr('Введи уникальный номер фактической банковской операции. Сумма: {v0}', {'v0': b.money(row['amount'])}, html_mode=True, section='bot_topups', limit=3000))
        return {'method': 'sendPhoto' if row['media'] == 'photo' else 'sendDocument', 'chat_id': uid, 'photo' if row['media'] == 'photo' else 'document': row['file_id'], 'caption': tr('Пополнение {v0}\nПользователь: {v1}\nСумма: {v2}\nКарта: {v3}\nПолучатель: {v4}', {'v0': f'{tid}', 'v1': f"{row['uid']}", 'v2': f"{b.money(row['amount'])}", 'v3': f"{row['card']}", 'v4': f"{row['recipient']}"}, html_mode=False, section='bot_topups', limit=1024), 'reply_markup': {'inline_keyboard': [[b.button('✅ Зачислить', 'admin:cardapprove:' + tid), b.button('❌ Отклонить', 'admin:cardreject:' + tid)]]}}
    if action.startswith('admin:cardconfirm:'):
        st = b.state(c, uid)
        if not st or st['state'] != 'topup_bank_confirm' or st['data']['nonce'] != action.split(':')[-1]:
            raise b.UserError(tr('Подтверждение устарело.', html_mode=False, section='bot_topups', limit=3000))
        data = st['data']
        row = c.execute("SELECT * FROM bot_card_topups WHERE id=%s AND status='pending' FOR UPDATE", (data['id'],)).fetchone()
        if not row:
            raise b.UserError(tr('Заявка уже обработана.', html_mode=False, section='bot_topups', limit=3000))
        if not c.execute('INSERT INTO bot_deposits VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING reference', (data['reference'], row['uid'], row['amount'], time.time())).fetchone():
            raise b.UserError(tr('Эта банковская операция уже учтена. Повторного начисления нет.', html_mode=False, section='bot_topups', limit=3000))
        c.execute("UPDATE bot_card_topups SET status='approved',reference=%s WHERE id=%s", (data['reference'], row['id']))
        c.execute('UPDATE bot_cash_pool SET amount=amount+%s WHERE id=1', (row['amount'],))
        b.change(c, row['uid'], row['amount'], 'manual_deposit', 'Перевод на карту · ' + row['id'])
        b.bot_notifications.enqueue(c,'card-approved:'+row['id'],tr('✅ Пополнение подтверждено\n\nНа баланс зачислено: {v0}\nЗаявка: {v1}', {'v0': b.money(row['amount']), 'v1': row['id']}, section='notifications'),recipient=row['uid'])
        b.state(c, uid, 'clear')
        return ui.screen(uid, tr('✅ Зачислено {v0} пользователю {v1}', {'v0': b.money(row['amount']), 'v1': str(row['uid'])}, html_mode=True, section='bot_topups', limit=3000))
    return None

def admin_input(c, uid, text, current):
    b = core()
    data = current['data']
    cfg = config(c)
    if current['state'] == 'topup_bank_reference':
        if not 3 <= len(text) <= 80 or any((ord(ch) < 32 for ch in text)):
            raise b.UserError(tr('Номер банковской операции: от 3 до 80 символов, одной строкой.', html_mode=False, section='bot_topups', limit=3000))
        row = c.execute("SELECT uid,amount FROM bot_card_topups WHERE id=%s AND status='pending'", (data['id'],)).fetchone()
        if not row:
            raise b.UserError(tr('Эта заявка уже обработана.', html_mode=False, section='bot_topups', limit=3000))
        data['reference'] = text
        b.state(c, uid, 'topup_bank_confirm', data)
        return b.bot_ui.screen(uid, tr('Подтверди зачисление только после проверки поступления в банке.\nПользователь: {v0}\nСумма: {v1}\nЗаявка: {v2}\nОперация: {v3}', {'v0': str(row['uid']), 'v1': b.money(row['amount']), 'v2': data['id'], 'v3': b.bot_ui.esc(text)}, html_mode=True, section='bot_topups', limit=3000), [[b.button('✅ Подтвердить', 'admin:cardconfirm:' + data['nonce'])], [b.button('Отмена', 'cancel_input')]])
    if current['state'] == 'topup_bank_confirm':
        return b.input_prompt(uid, tr('Используй кнопку подтверждения выше или нажми «Отмена».', html_mode=False, section='bot_topups', limit=3000))
    if data['field'] == 'rate':
        rate = 0 if text in ('0', '0.00', '0,00') else b.amount(text)
        c.execute('UPDATE bot_topup_config SET star_rate=%s WHERE id=1', (rate,))
        detail = 'Курс Stars: ' + b.money(rate)
    else:
        parts = text.splitlines()
        if text == '-':
            card, name = ('', '')
        else:
            card = re.sub('[ -]', '', parts[0]) if parts else ''
            name = parts[1].strip() if len(parts) == 2 else ''
            if not re.fullmatch('[0-9]{16}', card) or not 2 <= len(name) <= 100 or '\x00' in name:
                raise b.UserError(tr('Нужны две строки: 16 цифр карты и имя получателя.', html_mode=False, section='bot_topups', limit=3000))
            digits = [int(ch) for ch in card]
            if sum((sum(divmod(n * 2, 10)) if i % 2 == 0 else n for i, n in enumerate(digits))) % 10:
                raise b.UserError(tr('Проверь номер карты: контрольная сумма не сходится.', html_mode=False, section='bot_topups', limit=3000))
        c.execute('UPDATE bot_topup_config SET card=%s,recipient=%s WHERE id=1', (card, name))
        detail = 'Реквизиты перевода обновлены'
    c.execute("INSERT INTO bot_ledger VALUES(%s,%s,0,'topup_config',%s,%s)", (uuid.uuid4().hex, uid, detail, time.time()))
    b.state(c, uid, 'clear')
    return admin(c, uid, 'admin:topupsettings')
