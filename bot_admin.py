"""Button-based owner console. Business settings and copy are independent of routing."""
from bot_copy import tr
import html
import json
import re
import time
import uuid
import bot_payments
LIMITS = {'withdraw_min': 1, 'withdraw_max': 100000000, 'withdraw_fee': 0, 'max_stars': 10000, 'max_executions': 10000, 'card_min': 1, 'card_max': 100000000}
TITLES = {'withdraw_min': 'Минимальный вывод', 'withdraw_max': 'Максимальный вывод', 'withdraw_fee': 'Комиссия вывода', 'max_stars': 'Максимум Stars за оплату', 'max_executions': 'Выполнений в одном заказе', 'card_min': 'Минимум перевода на карту', 'card_max': 'Максимум перевода на карту'}
KINDS = {'channel': '📣 Подписка на канал', 'bot': '🤖 Задание на бота', 'group': '👥 Вступление в группу', 'post': '👁 Пост', 'manual': '📝 Ручное задание'}

def core():
    import task_bot
    return task_bot

def initialize(c):
    c.execute('CREATE TABLE IF NOT EXISTS bot_controls(key text PRIMARY KEY,value bigint NOT NULL CHECK(value>=0))')
    c.execute('CREATE TABLE IF NOT EXISTS bot_payout_terms(id text PRIMARY KEY,fee bigint NOT NULL CHECK(fee>=0),net bigint NOT NULL CHECK(net>0))')
    for key, value in LIMITS.items():
        c.execute('INSERT INTO bot_controls VALUES(%s,%s) ON CONFLICT DO NOTHING', (key, value))

def limits(c):
    return {r['key']: r['value'] for r in c.execute('SELECT * FROM bot_controls').fetchall()}

def net(c, payout):
    row = c.execute('SELECT net FROM bot_payout_terms WHERE id=%s', (payout['id'],)).fetchone()
    return row['net'] if row else payout['amount']

def decimal(n):
    return f'{n // 100}.{n % 100:02d}'

def panel(c, uid):
    b = core()
    b.state(c, uid, 'clear')
    tasks=c.execute("SELECT count(*) AS n FROM bot_tasks WHERE status='pending'").fetchone()['n']
    payouts=c.execute("SELECT count(*) AS n FROM bot_payouts WHERE status='pending'").fetchone()['n']
    receipts=c.execute("SELECT count(*) AS n FROM bot_card_topups WHERE status='pending'").fetchone()['n']
    pool=c.execute('SELECT amount FROM bot_cash_pool WHERE id=1').fetchone()['amount']
    shortage=max(0,b.liability(c)-pool)
    alert=tr('\n⚠️ Нехватка покрытия: {v0}\n',{'v0':b.money(shortage)},html_mode=True,section='bot_admin') if shortage else ''
    text=tr('🛠 <b>Панель управления</b>\n\n<b>Ожидают проверки</b>\n📝 Задания: {v0}\n💸 Выплаты: {v1}\n💳 Квитанции: {v2}\n{v3}\nВыбери раздел ниже.',{'v0':tasks,'v1':payouts,'v2':receipts,'v3':alert},html_mode=True,section='bot_admin')
    quick=[]
    if receipts:quick.append([b.button('📨 Квитанции · '+str(receipts),'admin:cardtopups')])
    if payouts:quick.append([b.button('💸 Выплаты · '+str(payouts),'admin:payouts')])
    if tasks:quick.append([b.button('📝 Модерация · '+str(tasks),'admin:tasks')])
    return b.bot_ui.screen(uid,text,quick+[
        [b.button('💰 Финансы','admin:section:finance'),b.button('📝 Задания','admin:section:tasks')],
        [b.button('⚙️ Настройки','admin:section:settings'),b.button('🎨 Оформление','admin:copy')],
        [b.button('📚 О боте','admin:about'),b.button('🆘 Обращения','admin:tickets')],
        [b.button('⬅️ Мой кабинет','cabinet')]])


def section_screen(c,uid,key):
    b=core(); b.state(c,uid,'clear')
    if key=='finance':
        pool=c.execute('SELECT amount FROM bot_cash_pool WHERE id=1').fetchone()['amount']
        liabilities=b.liability(c)
        debt=c.execute('SELECT coalesce(sum(amount),0) AS n FROM bot_debts').fetchone()['n']
        text=tr('💰 <b>Финансы</b>\n\n<b>Средства и обязательства</b>\nРезерв: <b>{v0}</b>\nОбязательства: {v1}\nСвободно: {v2}\n\n<b>Требует внимания</b>\nНехватка покрытия: {v3}\nДолги исполнителей: {v4}',{'v0':b.money(pool),'v1':b.money(liabilities),'v2':b.money(max(0,pool-liabilities)),'v3':b.money(max(0,liabilities-pool)),'v4':b.money(debt)},html_mode=True,section='bot_admin')
        rows=[[b.button('💸 Заявки на вывод','admin:payouts')],[b.button('📨 Проверить квитанции','admin:cardtopups')],[b.button('🧾 История оплат','admin:payments:all:0')],[b.button('💳 Настройки пополнения','admin:topupsettings')],[b.button('📒 Учёт поступлений','admin:money')],[{'text':'🐔 Ферма и Stars','callback_data':'adm:farm'}]]
    elif key=='tasks':
        text=tr('📝 <b>Задания и публикации</b>\n\nПроверяй заказы, управляй рекламными постами и разбирай спорные отписки.',html_mode=True,section='bot_admin')
        rows=[[b.button('✅ Модерация заданий','admin:tasks')],[b.button('🔎 Проверка публикаций','admin:postissues')],[b.button('📣 Канал постов','admin:channel')],[b.button('⚠️ Спорные отписки','admin:retention')]]
    elif key=='settings':
        text=tr('⚙️ <b>Настройки бота</b>\n\nВыбери, что изменить. Условия уже созданных заказов сохранятся.',html_mode=True,section='bot_admin')
        rows=[[b.button('💰 Тарифы и комиссии','admin:economy')],[b.button('🎁 Бонус и рефералы','admin:settings:rewards')],[b.button('⏳ Срок подписки и штраф','admin:settings:retention')],[b.button('📐 Лимиты операций','admin:settings:limits')]]
    else:
        raise b.UserError(tr('Неизвестный раздел.',section='bot_admin'))
    return b.bot_ui.screen(uid,text,rows+[[b.button('⬅️ Управление','admin')]])


def settings(c, uid, section):
    b = core()
    cfg = b.bot_economy.config(c)
    rows = []
    if section == 'prices':
        text = tr('💰 <b>Тарифы и комиссии</b>\n\n<b>Цена → награда исполнителю</b>\n', html_mode=True, section='bot_admin', limit=3000)
        for kind, name in KINDS.items():
            p = b.bot_economy.quote(c, kind)
            text += f"{name}: {b.money(p['cost'])} → {b.money(p['reward'])}\n"
            rows.append([b.button(name + ' · ' + b.money(p['cost']), 'admin:field:price_' + kind)])
        rows += [[b.button('👁 Награда за пост', 'admin:field:post_reward')], [b.button('📊 Комиссия заданий · ' + b.bot_economy.pct(cfg['fee']) + '%', 'admin:field:fee')], [b.button('💸 Комиссия вывода', 'admin:field:withdraw_fee')]]
        text += tr('\nКомиссия включена в цену. Для постов цена и награда задаются отдельно.\nИзменения действуют для новых заказов.', html_mode=True, section='bot_admin', limit=3000)
    elif section == 'rewards':
        n = c.execute('SELECT daily FROM bot_settings WHERE id=1').fetchone()['daily']
        text = tr('🎁 <b>Награды и партнёры</b>\n\nЕжедневная награда: {v0}\n\n', {'v0': b.money(n)}, html_mode=True, section='bot_admin', limit=3000)
        rows = [[b.button('🎁 Ежедневная награда', 'admin:field:daily')]]
        for i in range(1, 6):
            text += tr('Уровень {v0}: {v1}%\n', {'v0': f'{i}', 'v1': f"{b.bot_economy.pct(cfg['ref' + str(i)])}"}, html_mode=True, section='bot_admin', limit=3000)
            rows.append([b.button('🤝 Уровень ' + str(i), 'admin:field:ref' + str(i))])
        text += tr('\nПроценты от полной цены выполнения. Их сумма не может превышать комиссию.', html_mode=True, section='bot_admin', limit=3000)
    elif section == 'retention':
        text = tr('⏳ <b>Подписка и штраф</b>\n\nСрок: {v0} суток\nШтраф: ×{v1} награды\n\nНовые значения применяются к новым заданиям.', {'v0': f"{cfg['days']}", 'v1': f"{cfg['multiplier']}"}, html_mode=True, section='bot_admin', limit=3000)
        rows = [[b.button('📅 Срок подписки', 'admin:field:days')], [b.button('⚠️ Множитель штрафа', 'admin:field:multiplier')], [b.button('🔎 Спорные отписки', 'admin:retention')]]
    else:
        text = tr('📐 <b>Лимиты</b>\n\nВыбери параметр. Изменения действуют для новых запросов.', html_mode=True, section='bot_admin', limit=3000)
        current = limits(c)
        for k in LIMITS:
            if k == 'withdraw_fee':
                continue
            value = str(current[k]) if k.startswith('max_') else b.money(current[k])
            rows.append([b.button(TITLES[k] + ' · ' + value, 'admin:field:' + k)])
    return b.bot_ui.screen(uid, text, rows + [[b.button('⬅️ Управление', 'admin')]])

def field_value(c, key):
    b = core()
    cfg = b.bot_economy.config(c)
    if key.startswith('price_') and key[6:] in KINDS:
        p = c.execute('SELECT cost FROM bot_prices WHERE kind=%s', (key[6:],)).fetchone()
        return (KINDS[key[6:]], b.money(p['cost']))
    if key == 'post_reward':
        return ('Награда за пост', b.money(c.execute("SELECT reward FROM bot_prices WHERE kind='post'").fetchone()['reward']))
    if key in ('fee', 'ref1', 'ref2', 'ref3', 'ref4', 'ref5'):
        return ('Комиссия заданий' if key == 'fee' else 'Реферальный уровень ' + key[-1], b.bot_economy.pct(cfg[key]) + '%')
    if key == 'daily':
        return ('Ежедневная награда', b.money(c.execute('SELECT daily FROM bot_settings WHERE id=1').fetchone()['daily']))
    if key in ('days', 'multiplier'):
        return ('Срок подписки' if key == 'days' else 'Множитель штрафа', str(cfg[key]))
    if key in LIMITS:
        value = limits(c)[key]
        return (TITLES[key], b.bot_economy.pct(value) + '%' if key == 'withdraw_fee' else str(value) if key.startswith('max_') else b.money(value))
    raise b.UserError(tr('Неизвестный параметр.', html_mode=False, section='bot_admin', limit=3000))

def save_field(c, uid, key, text):
    b = core()
    cfg = b.bot_economy.config(c)
    if key.startswith('price_') or key == 'post_reward':
        kinds = ['channel', 'bot', 'group', 'post', 'manual']
        prices = {r['kind']: r for r in c.execute('SELECT * FROM bot_prices').fetchall()}
        args = [prices[k]['cost'] for k in kinds[:4]] + [prices['post']['reward'], prices['manual']['cost']]
        index = 4 if key == 'post_reward' else kinds.index(key[6:]) if key[6:] != 'manual' else 5
        args[index] = b.amount(text)
        b.bot_economy.edit(c, uid, ' '.join((decimal(n) for n in args)), {'field': 'prices'})
        section = 'prices'
    elif key in ('fee', 'ref1', 'ref2', 'ref3', 'ref4', 'ref5'):
        keys = ['fee', 'ref1', 'ref2', 'ref3', 'ref4', 'ref5']
        values = [b.bot_economy.pct(cfg[k]) for k in keys]
        values[keys.index(key)] = text
        b.bot_economy.edit(c, uid, ' '.join(values), {'field': 'rates'})
        section = 'prices' if key == 'fee' else 'rewards'
    elif key == 'daily':
        b.bot_economy.edit(c, uid, text, {'field': 'bonus'})
        section = 'rewards'
    elif key in ('days', 'multiplier'):
        values = [str(cfg['days']), str(cfg['multiplier'])]
        values[0 if key == 'days' else 1] = text
        b.bot_economy.edit(c, uid, ' '.join(values), {'field': 'retention'})
        section = 'retention'
    else:
        before = limits(c)
        after = dict(before)
        if key == 'withdraw_fee':
            n = b.bot_economy.percentage(text)
            if n >= 10000:
                raise b.UserError(tr('Комиссия вывода должна быть меньше 100%.', html_mode=False, section='bot_admin', limit=3000))
        elif key.startswith('max_'):
            if not text.isdecimal() or not 1 <= int(text) <= 10000:
                raise b.UserError(tr('Введи целое число от 1 до 10000.', html_mode=False, section='bot_admin', limit=3000))
            n = int(text)
        else:
            n = b.amount(text)
        after[key] = n
        if after['withdraw_min'] > after['withdraw_max'] or after['card_min'] > after['card_max']:
            raise b.UserError(tr('Минимальная сумма не может превышать максимальную.', html_mode=False, section='bot_admin', limit=3000))
        c.execute('UPDATE bot_controls SET value=%s WHERE key=%s', (n, key))
        c.execute("INSERT INTO bot_ledger VALUES(%s,%s,0,'control_config',%s,%s)", (uuid.uuid4().hex, uid, key + ': ' + str(before[key]) + ' → ' + str(n), time.time()))
        section = 'prices' if key == 'withdraw_fee' else 'limits'
    b.state(c, uid, 'clear')
    return settings(c, uid, section)

def copy_menu(c, uid, kind=None, page=0):
    b = core()
    if kind is None:
        return b.bot_ui.screen(uid, tr('🎨 <b>Оформление бота</b>\n\nИзменяй надписи, сообщения и названия разделов. Метки в фигурных скобках подставляют реальные суммы и данные — их нужно сохранить. Назначение кнопок не меняется.', html_mode=True, section='bot_admin', limit=3000), [[b.button('📱 Главное меню', 'admin:copylist:menu:0')], [b.button('🔘 Кнопки', 'admin:copylist:button:0')], [b.button('📝 Сообщения', 'admin:copylist:text:0')], [b.button('🔎 Найти текст', 'admin:copysearch')], [b.button('🕘 История изменений', 'admin:copyhistory')], [b.button('⬅️ Управление', 'admin')]])
    rows = c.execute('SELECT * FROM bot_copy_catalog WHERE kind=%s ORDER BY section,original LIMIT 8 OFFSET %s', (kind, page * 8)).fetchall()
    buttons = []
    for row in rows:
        title = re.sub('<[^>]+>', '', row['original']).replace('\n', ' ')[:42]
        buttons.append([b.button(('✏️ ' if row['custom'] else '') + title, 'admin:copyentry:' + row['key'])])
    nav = []
    if page:
        nav.append(b.button('⬅️ Назад', 'admin:copylist:' + kind + ':' + str(page - 1)))
    if len(rows) == 8:
        nav.append(b.button('Далее ➡️', 'admin:copylist:' + kind + ':' + str(page + 1)))
    if nav:
        buttons.append(nav)
    return b.bot_ui.screen(uid, tr('🎨 <b>Выбери текст для изменения</b>\n\nОсновные тексты уже доступны. Динамические кнопки добавляются после открытия раздела. Для быстрого поиска вернись в «Оформление».', html_mode=True, section='bot_admin', limit=3000), buttons + [[b.button('⬅️ Оформление', 'admin:copy')]])

def copy_entry(c, uid, key):
    b = core()
    row = c.execute('SELECT * FROM bot_copy_catalog WHERE key=%s', (key,)).fetchone()
    if not row:
        raise b.UserError(tr('Текст не найден. Открой нужный раздел бота и вернись в каталог.', html_mode=False, section='bot_admin', limit=3000))
    preview = b.bot_copy.preview(row)
    return b.bot_ui.screen(uid, tr('🎨 <b>Текущий вариант</b>\n\n{v0}\n\nСуммы и данные в метках подставляются автоматически.', {'v0': html.escape(row['custom'] or row['original'])}, html_mode=True, section='bot_admin', limit=3000), [[b.button('✏️ Изменить', 'admin:copyedit:' + key)], [b.button('↩️ Исходный вариант', 'admin:copyreset:' + key)], [b.button('⬅️ Оформление', 'admin:copy')]])

def admin(c, uid, text, action, api):
    b = core()
    ui = b.bot_ui
    navigation={'admin','admin:economy','admin:bonus','admin:copy','admin:copyhistory','admin:money','admin:payouts','admin:tickets','admin:about','admin:topupsettings','admin:cardtopups','admin:postissues','admin:tasks','admin:retention'}
    if action in navigation or action.startswith(('admin:settings:','admin:copylist:','admin:copyentry:','admin:copyreset:','admin:copyrestore:','admin:payview:','admin:ticketview:')):
        b.state(c,uid,'clear')
    if action.startswith('admin:payments:'):
        b.state(c,uid,'clear')
        parts=action.split(':')
        if len(parts)!=4 or not parts[3].isdecimal():
            raise b.UserError('Неизвестная страница истории.')
        return bot_payments.screen(c,uid,parts[2],int(parts[3]))
    if action.startswith('admin:section:'):
        return section_screen(c,uid,action.split(':')[-1])
    if action.startswith('admin:moneyconfirm:'):
        return confirm_money(c, uid, action, api)
    if action in ('admin', 'admin:economy') or (text.split(maxsplit=1)[0].split('@')[0] if text else '') == '/botadmin':
        return panel(c, uid) if action != 'admin:economy' else settings(c, uid, 'prices')
    if action.startswith('admin:settings:'):
        section = action.split(':')[-1]
        if section not in ('prices', 'rewards', 'retention', 'limits'):
            raise b.UserError(tr('Неизвестный раздел.', html_mode=False, section='bot_admin', limit=3000))
        return settings(c, uid, section)
    if action.startswith('admin:field:'):
        key = action.split(':')[-1]
        title, value = field_value(c, key)
        b.state(c, uid, 'admin_field', {'key': key})
        return ui.input_screen(uid, tr('✏️ <b>{v0}</b>\n\nСейчас: <b>{v1}</b>\n\nВведи новое значение одним числом.', {'v0': ui.esc(title), 'v1': value}, html_mode=True, section='bot_admin', limit=3000))
    if action == 'admin:bonus':
        return settings(c, uid, 'rewards')
    if action == 'admin:channel':
        b.state(c, uid, 'admin_channel')
        return ui.input_screen(uid, tr('📣 <b>Канал рекламных постов</b>\n\nДобавь бота администратором с правом публикации, затем пришли @имя или ссылку на канал.', html_mode=True, section='bot_admin', limit=3000))
    if action == 'admin:money':
        return ui.screen(uid, tr('📒 <b>Учёт поступлений</b>\n\nПодтверждай только фактически полученные деньги.', html_mode=True, section='bot_admin', limit=3000), [[b.button('💳 Учесть пополнение игрока', 'admin:money:credit')], [b.button('🏦 Учесть собственный взнос', 'admin:money:fund')], [b.button('⬅️ Управление', 'admin')]])
    if action in ('admin:money:credit', 'admin:money:fund'):
        kind = action.split(':')[-1]
        b.state(c, uid, 'admin_money_uid' if kind == 'credit' else 'admin_money_amount', {'kind': kind})
        return ui.input_screen(uid, tr('Введи Telegram ID получателя.', html_mode=True, section='bot_admin', limit=3000) if kind == 'credit' else tr('Введи сумму фактического взноса в гривнах.', html_mode=True, section='bot_admin', limit=3000))
    if action == 'admin:payouts':
        rows = c.execute("SELECT * FROM bot_payouts WHERE status='pending' ORDER BY created LIMIT 10").fetchall()
        return ui.screen(uid, tr('💸 <b>Заявки на вывод</b>\n\n{v0}', {'v0': 'Выбери заявку.' if rows else 'Ожидающих заявок нет.'}, html_mode=True, section='bot_admin', limit=3000), [[b.button(str(r['uid']) + ' · ' + b.money(net(c, r)), 'admin:payview:' + r['id'])] for r in rows] + [[b.button('⬅️ Управление', 'admin')]])
    if action.startswith(('admin:payview:', 'admin:payref:')):
        pid = action.split(':')[-1]
        p = c.execute("SELECT * FROM bot_payouts WHERE id=%s AND status='pending'", (pid,)).fetchone()
        if not p:
            raise b.UserError(tr('Заявка уже закрыта.', html_mode=False, section='bot_admin', limit=3000))
        if action.startswith('admin:payref:'):
            b.state(c, uid, 'admin_pay_reference', {'id': pid})
            return ui.input_screen(uid, tr('После фактического перевода {v0} введи уникальный номер банковской операции.', {'v0': b.money(net(c, p))}, html_mode=True, section='bot_admin', limit=3000))
        return ui.screen(uid, tr('💸 <b>Выплата</b>\n\nID: {v0}\nЗарезервировано: {v1}\nК переводу: <b>{v2}</b>\nРеквизиты: {v3}', {'v0': f"{p['uid']}", 'v1': f"{b.money(p['amount'])}", 'v2': f'{b.money(net(c, p))}', 'v3': f"{ui.esc(p['destination'])}"}, html_mode=True, section='bot_admin', limit=3000), [[b.button('✅ Подтвердить перевод', 'admin:payref:' + pid)], [b.button('❌ Отклонить и вернуть', 'admin:rejectpayout:' + pid)], [b.button('⬅️ Выплаты', 'admin:payouts')]])
    if action == 'admin:copysearch':
        b.state(c, uid, 'admin_copy_search')
        return ui.input_screen(uid, tr('🔎 <b>Поиск надписей</b>\n\nНапиши несколько слов из нужного текста или названия кнопки.', html_mode=True, section='bot_admin', limit=3000))
    if action == 'admin:copy':
        return copy_menu(c, uid)
    if action.startswith('admin:copylist:'):
        parts = action.split(':')
        kind = parts[2]
        if kind not in ('menu', 'button', 'text') or not parts[3].isdecimal():
            raise b.UserError(tr('Неизвестная страница.', html_mode=False, section='bot_admin', limit=3000))
        return copy_menu(c, uid, kind, min(int(parts[3]), 10000))
    if action.startswith('admin:copyentry:'):
        return copy_entry(c, uid, action.split(':')[-1])
    if action.startswith('admin:copyreset:'):
        key = action.split(':')[-1]
        b.bot_copy.save(c, uid, key, None)
        return copy_entry(c, uid, key)
    if action.startswith('admin:copyedit:'):
        key = action.split(':')[-1]
        row = c.execute('SELECT * FROM bot_copy_catalog WHERE key=%s', (key,)).fetchone()
        if not row:
            raise b.UserError(tr('Текст не найден.', html_mode=False, section='bot_admin', limit=3000))
        b.state(c, uid, 'admin_copy_text', {'key': key})
        return ui.input_screen(uid, tr('✏️ <b>Новый текст</b>\n\n{v0}\n\nПришли новый вариант. Сохрани все метки в фигурных скобках. После ввода будет предпросмотр.', {'v0': html.escape(row['custom'] or row['original'])}, html_mode=True, section='bot_admin', limit=3000))
    if action.startswith('admin:copysave:'):
        st = b.state(c, uid)
        if not st or st['state'] != 'admin_copy_confirm' or st['data']['nonce'] != action.split(':')[-1]:
            raise b.UserError(tr('Подтверждение устарело.', html_mode=False, section='bot_admin', limit=3000))
        b.bot_copy.save(c, uid, st['data']['key'], st['data']['body'])
        key = st['data']['key']
        b.state(c, uid, 'clear')
        return copy_entry(c, uid, key)
    if action == 'admin:copyhistory':
        rows = c.execute('SELECT h.*,t.original FROM bot_copy_history h JOIN bot_copy_catalog t ON t.key=h.key ORDER BY h.created DESC LIMIT 10').fetchall()
        return ui.screen(uid, tr('🕘 <b>История оформления</b>\n\nВыбери изменение, чтобы вернуть предыдущий вариант.', html_mode=True, section='bot_admin', limit=3000), [[b.button(re.sub('<[^>]+>', '', r['original'])[:35], 'admin:copyrestore:' + r['id'])] for r in rows] + [[b.button('⬅️ Оформление', 'admin:copy')]])
    if action.startswith('admin:copyrestore:'):
        row = c.execute('SELECT * FROM bot_copy_history WHERE id=%s', (action.split(':')[-1],)).fetchone()
        if not row:
            raise b.UserError(tr('Запись не найдена.', html_mode=False, section='bot_admin', limit=3000))
        b.bot_copy.save(c, uid, row['key'], row['previous'])
        return copy_entry(c, uid, row['key'])
    if action == 'admin:tickets':
        rows = c.execute('SELECT id,nickname,message FROM support_tickets ORDER BY created DESC LIMIT 8').fetchall()
        return ui.screen(uid, tr('🆘 <b>Последние обращения</b>', html_mode=True, section='bot_admin', limit=3000), [[b.button(r['nickname'][:25] + ' · ' + r['id'], 'admin:ticketview:' + r['id'])] for r in rows] + [[b.button('⬅️ Управление', 'admin')]])
    if action.startswith('admin:ticketview:'):
        row = c.execute('SELECT * FROM support_tickets WHERE id=%s', (action.split(':')[-1],)).fetchone()
        if not row:
            raise b.UserError(tr('Обращение не найдено.', html_mode=False, section='bot_admin', limit=3000))
        return ui.screen(uid, tr('🆘 <b>Обращение</b>\n\n{v0}\n{v1}', {'v0': ui.esc(row['nickname']), 'v1': ui.esc(row['message'])}, html_mode=True, section='bot_admin', limit=3000), [[b.button('✉️ Ответить', 'admin:ticketreply:' + row['id'])], [b.button('⬅️ Обращения', 'admin:tickets')]])
    if action.startswith('admin:ticketreply:'):
        b.state(c, uid, 'admin_ticket_reply', {'id': action.split(':')[-1]})
        return ui.input_screen(uid, tr('Напиши ответ пользователю одним сообщением.', html_mode=True, section='bot_admin', limit=3000))
    return None

def input_text(c, uid, text, message, current, api):
    b = core()
    ui = b.bot_ui
    stage = current['state']
    data = current['data']
    if stage == 'admin_field':
        return save_field(c, uid, data['key'], text)
    if stage == 'admin_channel':
        result=b.bot_extras.administration(c, uid, '/botchannel ' + text, '', api)
        b.state(c,uid,'clear')
        return result
    if stage == 'admin_pay_reference':
        if not 3 <= len(text) <= 80 or any((ch.isspace() or ord(ch) < 32 for ch in text)):
            raise b.UserError(tr('Введи номер банковской операции без пробелов: от 3 до 80 символов.', html_mode=False, section='bot_admin', limit=3000))
        return b.administration(c, uid, '/botpaid ' + data['id'] + ' ' + text, '', api)
    if stage == 'admin_money_uid':
        if not text.isdecimal() or len(text) > 19 or (not 0 < int(text) <= 9223372036854775807) or (not c.execute('SELECT 1 FROM bot_accounts WHERE uid=%s', (int(text),)).fetchone()):
            raise b.UserError(tr('Пользователь не найден. Он должен сначала открыть бота.', html_mode=False, section='bot_admin', limit=3000))
        data['uid'] = int(text)
        b.state(c, uid, 'admin_money_amount', data)
        return ui.input_screen(uid, tr('Введи сумму фактического пополнения в гривнах.', html_mode=True, section='bot_admin', limit=3000))
    if stage == 'admin_money_amount':
        data['amount'] = b.amount(text)
        b.state(c, uid, 'admin_money_reference', data)
        return ui.input_screen(uid, tr('Введи уникальный номер банковского платежа или взноса.', html_mode=True, section='bot_admin', limit=3000))
    if stage == 'admin_money_reference':
        if not 3 <= len(text) <= 80 or any((ord(ch) < 32 for ch in text)) or ' ' in text:
            raise b.UserError(tr('Нужен номер одной строкой без пробелов: от 3 до 80 символов.', html_mode=False, section='bot_admin', limit=3000))
        data.update(reference=text, nonce=uuid.uuid4().hex[:12])
        b.state(c, uid, 'admin_money_confirm', data)
        return ui.screen(uid, tr('Подтверди фактическое поступление.\nСумма: {v0}\nПолучатель: {v1}\nОперация: {v2}', {'v0': b.money(data['amount']), 'v1': str(data.get('uid', 'резерв бота')), 'v2': ui.esc(text)}, html_mode=True, section='bot_admin', limit=3000), [[b.button('✅ Подтвердить поступление', 'admin:moneyconfirm:' + data['nonce'])], [b.button('✖️ Отмена', 'cancel_input')]])
    if stage == 'admin_copy_search':
        if not 2 <= len(text) <= 80:
            raise b.UserError(tr('Для поиска введи от 2 до 80 символов.', section='bot_admin'))
        rows = [r for r in c.execute('SELECT * FROM bot_copy_catalog ORDER BY kind,section,original').fetchall() if text.casefold() in (r['original'] + ' ' + (r['custom'] or '')).casefold()][:20]
        b.state(c, uid, 'clear')
        return ui.screen(uid, tr('🔎 <b>Результаты поиска</b>\n\nПоказано до 20 совпадений. Если нужного текста нет, попробуй более точный запрос.', html_mode=True, section='bot_admin'), [[b.button(re.sub('<[^>]+>', '', r['custom'] or r['original']).replace('\n', ' ')[:42], 'admin:copyentry:' + r['key'])] for r in rows] + [[b.button('🔎 Другой запрос', 'admin:copysearch')], [b.button('⬅️ Оформление', 'admin:copy')]])
    if stage == 'admin_copy_text':
        row = c.execute('SELECT * FROM bot_copy_catalog WHERE key=%s', (data['key'],)).fetchone()
        b.bot_copy.validate(c, row, text)
        data.update(body=text, nonce=uuid.uuid4().hex[:12])
        b.state(c, uid, 'admin_copy_confirm', data)
        return ui.screen(uid, tr('👁 <b>Предпросмотр</b>\n\n{v0}', {'v0': b.bot_copy.preview(dict(row, custom=text))}, html_mode=True, section='bot_admin', limit=3000), [[b.button('✅ Сохранить', 'admin:copysave:' + data['nonce'])], [b.button('✖️ Отмена', 'cancel_input')]])
    if stage == 'admin_ticket_reply':
        if not 1 <= len(text) <= 1500:
            raise b.UserError(tr('Ответ: от 1 до 1500 символов.', html_mode=False, section='bot_admin', limit=3000))
        ticket = c.execute('SELECT * FROM support_tickets WHERE id=%s', (data['id'],)).fetchone()
        if not ticket:
            raise b.UserError(tr('Обращение не найдено.', html_mode=False, section='bot_admin', limit=3000))
        b.state(c, uid, 'clear')
        return b.say(ticket['telegram_id'], tr('✉️ Ответ администрации\n\n{v0}', {'v0': text}, html_mode=False, section='bot_admin', limit=3000))
    return ui.input_screen(uid, tr('Подтверди действие кнопкой выше или нажми «Отмена».', html_mode=True, section='bot_admin', limit=3000))

def confirm_money(c, uid, action, api):
    b = core()
    st = b.state(c, uid)
    if not st or st['state'] != 'admin_money_confirm' or st['data']['nonce'] != action.split(':')[-1]:
        raise b.UserError(tr('Подтверждение устарело.', html_mode=False, section='bot_admin', limit=3000))
    d = st['data']
    command = ('/botcredit ' + str(d['uid']) + ' ' if d['kind'] == 'credit' else '/botfund ') + decimal(d['amount']) + ' ' + d['reference']
    response = b.administration(c, uid, command, '', api)
    b.state(c, uid, 'clear')
    return response
