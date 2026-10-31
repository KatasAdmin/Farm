"""Task marketplace and UAH wallet in the existing farm bot.

All monetary values are integer kopecks. Telegram Stars are kept separate.
One transaction stores both the operation and its replayable webhook response.
"""
from bot_copy import tr
import json
import logging
import os
import re
import time
import uuid
import bot_extras
import bot_economy
import bot_ui
import bot_about
import bot_topups
import bot_copy
import bot_admin
import bot_notifications
import bot_payouts
import bot_decisions
import bot_advertising
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit
from psycopg.types.json import Jsonb
log = logging.getLogger('farm.tasks')
MENU = [['🚀 Заработать', '📣 Продвижение'], ['🎮 Игры', '👤 Мой кабинет'], ['👥 Партнёры', '📚 О боте']]
KINDS = {'bot': '🤖 Боты', 'channel': '📣 Каналы', 'group': '👥 Группы', 'post': '👁 Посты', 'manual': '📝 Задания'}
LOCK = 1984534

class UserError(Exception):
    pass

def amount(text):
    if not re.fullmatch('\\d{1,7}([.,]\\d{1,2})?', text.strip()):
        raise UserError(tr('Укажи сумму в гривнах, например 5 или 0,50. Максимум два знака после запятой.', html_mode=False, section='task_bot', limit=3000))
    try:
        n = int(Decimal(text.replace(',', '.')) * 100)
    except (InvalidOperation, ValueError):
        raise UserError(tr('Некорректная сумма.', html_mode=False, section='task_bot', limit=3000))
    if not 1 <= n <= 100000000:
        raise UserError(tr('Допустимая сумма: от 0,01 до 1 000 000 грн.', html_mode=False, section='task_bot', limit=3000))
    return n

def money(n):
    return f'{int(n) // 100},{int(n) % 100:02d} грн'

def member(info):
    return info.get('status') in ('creator', 'administrator', 'member') or (info.get('status') == 'restricted' and info.get('is_member') is True)

def initialize(c):
    statements = ['CREATE TABLE IF NOT EXISTS bot_accounts(\n          uid bigint PRIMARY KEY CHECK(uid>0), name text NOT NULL,\n          available bigint NOT NULL DEFAULT 0 CHECK(available>=0),\n          referrer bigint, created double precision NOT NULL)', 'ALTER TABLE bot_accounts ADD COLUMN IF NOT EXISTS advertising bigint NOT NULL DEFAULT 0 CHECK(advertising>=0)', 'CREATE TABLE IF NOT EXISTS bot_cash_pool(\n          id integer PRIMARY KEY CHECK(id=1), amount bigint NOT NULL DEFAULT 0 CHECK(amount>=0))', 'INSERT INTO bot_cash_pool(id) VALUES(1) ON CONFLICT DO NOTHING', 'CREATE TABLE IF NOT EXISTS bot_ledger(\n          id text PRIMARY KEY,uid bigint NOT NULL,delta bigint NOT NULL,kind text NOT NULL,\n          details text NOT NULL,created double precision NOT NULL)', 'CREATE INDEX IF NOT EXISTS bot_ledger_user ON bot_ledger(uid,created)', 'CREATE TABLE IF NOT EXISTS bot_receipts(\n          event text PRIMARY KEY,response jsonb NOT NULL,created double precision NOT NULL)', 'CREATE TABLE IF NOT EXISTS bot_states(\n          uid bigint PRIMARY KEY,state text NOT NULL,data jsonb NOT NULL,updated double precision NOT NULL)', "CREATE TABLE IF NOT EXISTS bot_tasks(\n          id text PRIMARY KEY,owner bigint NOT NULL,kind text NOT NULL,title text NOT NULL,\n          description text NOT NULL,url text NOT NULL,chat_id bigint,\n          reward bigint NOT NULL CHECK(reward>0),remaining bigint NOT NULL CHECK(remaining>=0),\n          status text NOT NULL CHECK(status IN ('pending','active','closed','rejected')),\n          created double precision NOT NULL)", 'CREATE INDEX IF NOT EXISTS bot_tasks_catalog ON bot_tasks(status,kind,created)', "CREATE TABLE IF NOT EXISTS bot_claims(\n          task text NOT NULL,uid bigint NOT NULL,status text NOT NULL,\n          proof text NOT NULL DEFAULT '',photo text NOT NULL DEFAULT '',created double precision NOT NULL,\n          PRIMARY KEY(task,uid))", "CREATE TABLE IF NOT EXISTS bot_payouts(\n          id text PRIMARY KEY,uid bigint NOT NULL,amount bigint NOT NULL CHECK(amount>0),\n          destination text NOT NULL,status text NOT NULL CHECK(status IN ('pending','paid','rejected','cancelled')),\n          reference text NOT NULL DEFAULT '',created double precision NOT NULL)", "CREATE UNIQUE INDEX IF NOT EXISTS bot_one_pending_payout ON bot_payouts(uid) WHERE status='pending'", 'CREATE TABLE IF NOT EXISTS bot_deposits(\n          reference text PRIMARY KEY,uid bigint NOT NULL,amount bigint NOT NULL CHECK(amount>0),created double precision NOT NULL)']
    for sql in statements:
        c.execute(sql)
    bot_extras.initialize(c)
    bot_economy.initialize(c)
    bot_ui.initialize(c)
    bot_about.initialize(c)
    bot_topups.initialize(c)
    bot_copy.initialize(c)
    bot_admin.initialize(c)
    bot_notifications.initialize(c)
    bot_payouts.initialize(c)
    bot_decisions.initialize(c)
    bot_advertising.initialize(c)
    c.execute('SELECT pg_advisory_xact_lock(1984533)')
    c.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK,))
    unify_balances(c)

def unify_balances(c, uid=None):
    sql = 'SELECT uid,advertising FROM bot_accounts WHERE advertising>0'
    rows = c.execute(sql + (' AND uid=%s' if uid is not None else '') + ' FOR UPDATE', (uid,) if uid is not None else ()).fetchall()
    for row in rows:
        c.execute('UPDATE bot_accounts SET available=available+advertising,advertising=0 WHERE uid=%s', (row['uid'],))
        c.execute("INSERT INTO bot_ledger VALUES(%s,%s,0,'wallet_unified',%s,%s)", (uuid.uuid4().hex, row['uid'], 'Объединение балансов: ' + money(row['advertising']), time.time()))

def state(c, uid, stage=None, data=None):
    if stage is None:
        return c.execute('SELECT state,data FROM bot_states WHERE uid=%s', (uid,)).fetchone()
    if stage == 'clear':
        c.execute('DELETE FROM bot_states WHERE uid=%s', (uid,))
    else:
        c.execute('INSERT INTO bot_states VALUES(%s,%s,%s,%s) ON CONFLICT(uid)\n          DO UPDATE SET state=EXCLUDED.state,data=EXCLUDED.data,updated=EXCLUDED.updated', (uid, stage, Jsonb(data or {}), time.time()))

def say(uid, text, buttons=None):
    out = {'method': 'sendMessage', 'chat_id': uid, 'text': text, 'reply_markup': {'keyboard': bot_copy.menu(MENU), 'resize_keyboard': True, 'is_persistent': True, 'one_time_keyboard': False}}
    if buttons is not None:
        out['reply_markup'] = {'inline_keyboard': buttons}
    return out

def button(text, action):
    if action == 'cancel_input':
        text = '✖️ Отмена'
    return {'text': bot_copy.label(text, action), 'callback_data': 'bot:' + action}

def input_prompt(uid, text, buttons=None, cancel_action='cancel_input'):
    rows = list(buttons or [])
    if not any((b.get('callback_data') == 'bot:' + cancel_action for row in rows for b in row)):
        rows.append([button('✖️ Отмена', cancel_action)])
    return say(uid, text, rows)

def account(c, uid):
    unify_balances(c, uid)
    bot_economy.collect_debt(c, uid)
    return c.execute('SELECT * FROM bot_accounts WHERE uid=%s FOR UPDATE', (uid,)).fetchone()

def change(c, uid, delta, kind, details):
    row = c.execute('UPDATE bot_accounts SET available=available+%s\n      WHERE uid=%s AND available+%s>=0 RETURNING available', (delta, uid, delta)).fetchone()
    if not row:
        raise UserError(tr('Недостаточно средств на балансе.', html_mode=False, section='task_bot', limit=3000))
    c.execute('INSERT INTO bot_ledger VALUES(%s,%s,%s,%s,%s,%s)', (uuid.uuid4().hex, uid, delta, kind, details, time.time()))
    if delta > 0:
        bot_economy.collect_debt(c, uid)
    return c.execute('SELECT available FROM bot_accounts WHERE uid=%s', (uid,)).fetchone()['available']

def liability(c):
    return c.execute("SELECT\n      (SELECT coalesce(sum(available+advertising),0) FROM bot_accounts) +\n      (SELECT coalesce(sum(remaining),0) FROM bot_tasks WHERE status IN ('pending','active')) +\n      (SELECT coalesce(sum(amount),0) FROM bot_payouts WHERE status='pending') +\n      (CAST((SELECT coalesce(sum(units),0) FROM bot_ref_accruals) AS bigint)+9999)/10000 AS n").fetchone()['n']

def farm_url():
    domain = os.environ.get('RAILWAY_PUBLIC_DOMAIN', 'farm-web-production-cfb9.up.railway.app')
    return 'https://' + domain + '/'

def cabinet(c, uid):
    a = account(c, uid)
    pending = c.execute("SELECT coalesce(sum(amount),0) AS n FROM bot_payouts WHERE uid=%s AND status='pending'", (uid,)).fetchone()['n']
    frozen = c.execute("SELECT coalesce(sum(remaining),0) AS n FROM bot_tasks WHERE owner=%s AND status IN ('pending','active')", (uid,)).fetchone()['n']
    earned = c.execute("SELECT coalesce(sum(delta),0) AS n FROM bot_ledger WHERE uid=%s AND kind='task_reward'", (uid,)).fetchone()['n']
    bonuses = c.execute("SELECT coalesce(sum(delta),0) AS n FROM bot_ledger WHERE uid=%s AND kind IN ('daily_bonus','friend_reward','referral_reward')", (uid,)).fetchone()['n']
    deposits = c.execute("SELECT coalesce(sum(delta),0) AS n FROM bot_ledger WHERE uid=%s AND kind IN ('manual_deposit','ads_manual_deposit','stars_wallet_deposit')", (uid,)).fetchone()['n']
    paid = c.execute("SELECT coalesce(sum(coalesce(q.net,p.amount)),0) AS n FROM bot_payouts p LEFT JOIN bot_payout_terms q ON q.id=p.id WHERE p.uid=%s AND p.status='paid'", (uid,)).fetchone()['n']
    spent = c.execute("SELECT coalesce(sum(coalesce(q.cost,t.reward)),0) AS n FROM bot_tasks t LEFT JOIN bot_task_terms q ON q.task=t.id JOIN bot_claims x\n      ON x.task=t.id AND x.status='paid' WHERE t.owner=%s", (uid,)).fetchone()['n']
    spent -= c.execute("SELECT coalesce(sum(delta),0) AS n FROM bot_ledger WHERE uid=%s AND kind='retention_refund'", (uid,)).fetchone()['n']
    debt = c.execute('SELECT amount FROM bot_debts WHERE uid=%s', (uid,)).fetchone()
    debt = debt['amount'] if debt else 0
    state(c, uid, 'clear')
    debt_line = tr('\n⚠️ Задолженность: {v0}', {'v0': money(debt)}, html_mode=True, section='task_bot', limit=3000) if debt else ''
    text = tr('👤 <b>Мой кабинет</b>\n🆔 ID: <code>{v0}</code>\n\n<b>💰 Доступный баланс: {v1}</b>{v2}\n\n<b>📊 Статистика</b>\n💳 Пополнений: {v3}\n📣 Потрачено на рекламу: {v4}\n💵 Заработано на заданиях: {v5}\n🎁 Бонусы и рефералы: {v6}\n\n❄️ В бюджете заданий: {v7}\n⌛ Ожидает выплаты: {v8}\n💸 Выведено всего: {v9}', {'v0': f'{uid}', 'v1': f"{money(a['available'])}", 'v2': f'{debt_line}', 'v3': f'{money(deposits)}', 'v4': f'{money(spent)}', 'v5': f'{money(earned)}', 'v6': f'{money(bonuses)}', 'v7': f'{money(frozen)}', 'v8': f'{money(pending)}', 'v9': f'{money(paid)}'}, html_mode=True, section='task_bot', limit=3000)
    buttons = [[button('➕ Пополнить', 'deposit'), button('💸 Вывести', 'withdraw')], [button('✅ Мои выполнения', 'claims')], [button('📥 Мои заявки', 'payouts'), button('📜 История', 'history')]]
    if bot_copy.owner():
        buttons.append([button('🛠 Управление ботом', 'admin')])
    return bot_ui.screen(uid, text, buttons)

def resolve_chat(api, target, kind):
    if re.fullmatch('-\\d+', target):
        key = int(target)
    else:
        path = urlsplit(target if '://' in target else 'https://t.me/' + target.lstrip('@'))
        if path.scheme != 'https' or path.hostname not in ('t.me', 'telegram.me') or (not re.fullmatch('[A-Za-z][A-Za-z0-9_]{3,31}', path.path.strip('/'))):
            raise UserError(tr('Укажи публичную ссылку https://t.me/имя или числовой ID чата. Для закрытого чата сначала добавь нашего бота администратором.', html_mode=False, section='task_bot', limit=3000))
        key = '@' + path.path.strip('/')
    info = api('getChat', {'chat_id': key})
    types = ('channel',) if kind == 'channel' else ('group', 'supergroup')
    if info.get('type') not in types:
        raise UserError(tr('Тип чата не соответствует заданию.', html_mode=False, section='task_bot', limit=3000))
    me = api('getMe', {})
    own = api('getChatMember', {'chat_id': info['id'], 'user_id': me['id']})
    if own.get('status') not in ('administrator', 'creator'):
        raise UserError(tr('Добавь @Farmlife2026bot администратором этого канала/группы, затем повтори.', html_mode=False, section='task_bot', limit=3000))
    link = 'https://t.me/' + info['username'] if info.get('username') else info.get('invite_link')
    if not link:
        raise UserError(tr('Не удалось получить ссылку на закрытый чат. Выдай боту право приглашать участников.', html_mode=False, section='task_bot', limit=3000))
    return (info['id'], link)

def task_card(t, uid, c):
    if t['kind'] == 'bot':
        return say(uid, tr('🤖 {v0}\n\n{v1}\n\nНаграда: {v2}\nВозьми задание, запусти бота и перешли сюда свежий ответ от него. Это проверка источника пересылки, не гарантия первого запуска. Не пересылай пароли и коды.', {'v0': f"{t['title']}", 'v1': f"{t['description']}", 'v2': f"{money(t['reward'])}"}, html_mode=False, section='task_bot', limit=3000), [[{'text': tr('Перейти к боту', html_mode=False, section='task_bot', limit=3000), 'url': t['url']}], [button('Взять / отправить пересылку', 'take:' + t['id'])], [button('Пропустить', 'skip_bot')]])
    return say(uid, tr('{v0}\n\n{v1}\n\nНаграда: {v2}{v3}', {'v0': f"{t['title']}", 'v1': f"{t['description']}", 'v2': f"{money(t['reward'])}", 'v3': bot_economy.rule_text(c, t)}, html_mode=False, section='task_bot', limit=3000), [[{'text': tr('Открыть', html_mode=False, section='task_bot', limit=3000), 'url': t['url']}], [button('Взять задание', 'take:' + t['id']), button('Проверить', 'check:' + t['id'])], [button('⬅️ Задания', 'earn')]])

def award(c, t, uid):
    claim = c.execute('SELECT * FROM bot_claims WHERE task=%s AND uid=%s FOR UPDATE', (t['id'], uid)).fetchone()
    if not claim or claim['status'] not in ('started', 'review'):
        raise UserError(tr('Заявка уже обработана или задание не взято.', html_mode=False, section='task_bot', limit=3000))
    gross = bot_economy.cost(c, t)
    order=bot_advertising.order(c,t)
    if order and c.execute("SELECT count(*) AS n FROM bot_claims WHERE task=%s AND status='paid'",(t['id'],)).fetchone()['n']>=order['slots']:
        raise UserError('Все оплаченные выполнения уже использованы.')
    if t['status'] != 'active' or t['remaining'] < gross:
        raise UserError(tr('Бюджет задания закончился. Награда не списана.', html_mode=False, section='task_bot', limit=3000))
    if uid==t['owner'] or (t['kind']=='manual' and claim['status']!='review'):
        raise UserError('Своё задание и непроверенную работу оплачивать нельзя.')
    changed=c.execute("UPDATE bot_tasks SET remaining=remaining-%s WHERE id=%s AND status='active' AND remaining>=%s RETURNING remaining",(gross,t['id'],gross)).fetchone()
    if not changed:raise UserError('Бюджет задания закончился. Повторного списания нет.')
    paid=c.execute("UPDATE bot_claims SET status='paid' WHERE task=%s AND uid=%s AND status IN ('started','review') RETURNING uid",(t['id'],uid)).fetchone()
    if not paid:raise UserError('Работа уже обработана.')
    change(c, uid, t['reward'], 'task_reward', 'Задание ' + t['id'])
    bot_economy.settle(c, t, uid, time.time())

def _admin_input(db, uid):
    with db() as c:
        row = state(c, uid)
        return bool(row and (row['state'].startswith('admin_') or row['state'] in ('economy_edit', 'about_edit', 'topup_config', 'topup_bank_reference', 'topup_bank_confirm')))

def handle(payload, db, api, is_admin):
    """Return None for legacy farm/payment/support messages, else webhook response."""
    payment = bot_topups.payment(payload, db)
    if payment is not None:
        bot_notifications.wake()
        return payment
    retained = bot_economy.member_update(payload, db)
    if retained is not None:
        bot_notifications.wake()
        return retained
    callback = payload.get('callback_query') or {}
    message = callback.get('message') or payload.get('message') or {}
    if payload.get('pre_checkout_query') or message.get('successful_payment'):
        return None
    sender = callback.get('from') or message.get('from') or {}
    uid = sender.get('id')
    chat = message.get('chat') or {}
    action = callback.get('data', '')
    channel_claim = bool(callback and action.startswith('bot:postclaim:'))
    if not isinstance(uid, int) or isinstance(uid, bool) or uid <= 0 or sender.get('is_bot'):
        return None
    if not channel_claim and (chat.get('id') != uid or chat.get('type') != 'private'):
        return None
    if channel_claim:
        message = dict(message, _callback_id=callback['id'])
    text = '' if callback or message.get('forward_origin') else (message.get('text') or '').strip()
    cmd = text.split(maxsplit=1)[0].split('@')[0] if text else ''
    legacy = {'/admin', '/requests', '/zayavki', '/tickets', '/stars', '/paysupport', '/support', '/reply'}
    if callback and (not action.startswith('bot:')):
        return None
    if not callback and (cmd in legacy or text.startswith('/start link_') or text == '/start support'):
        return None
    event = 'callback:' + str(callback['id']) if callback.get('id') else 'message:' + str(uid) + ':' + str(message.get('message_id'))
    if not callback and (not isinstance(message.get('message_id'), int)):
        return None
    admin = is_admin(uid, uid)
    try:
        with db() as c:
            c.execute('SELECT pg_advisory_xact_lock(1984533)')
            c.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK,))
            old = c.execute('SELECT response FROM bot_receipts WHERE event=%s', (event,)).fetchone()
            if old:
                return old['response']
            if channel_claim and (not account(c, uid)):
                return {'method': 'answerCallbackQuery', 'callback_query_id': callback['id'], 'text': tr('Сначала открой @Farmlife2026bot и нажми /start, затем вернись к посту.', html_mode=False, section='task_bot', limit=3000), 'show_alert': True}
            text = bot_copy.canonical_menu(c, text)
            ref = None
            if text.startswith('/start partner_'):
                raw = text.split('partner_', 1)[1]
                if raw.isdecimal() and len(raw) <= 19 and (0 < int(raw) <= 9223372036854775807) and (int(raw) != uid):
                    ref = c.execute('SELECT uid FROM bot_accounts WHERE uid=%s', (int(raw),)).fetchone()
            is_new = not c.execute('SELECT 1 FROM bot_accounts WHERE uid=%s', (uid,)).fetchone()
            c.execute('INSERT INTO bot_accounts(uid,name,referrer,created) VALUES(%s,%s,%s,%s)\n              ON CONFLICT(uid) DO UPDATE SET name=EXCLUDED.name', (uid, str(sender.get('first_name') or 'Игрок')[:100], ref['uid'] if ref else None, time.time()))
            unify_balances(c, uid)
            message = dict(message, _new_referral=bool(is_new and ref and text.startswith('/start partner_')))
            with bot_copy.session(c, admin):
                try:
                    with c.transaction():
                        response = route(c, uid, text, action[4:] if callback else '', message, api, admin)
                except UserError as error:
                    response = {'method': 'answerCallbackQuery', 'callback_query_id': callback['id'], 'text': str(error)[:200], 'show_alert': True} if channel_claim else input_prompt(uid, str(error)) if state(c, uid) else say(uid, str(error))
                c.execute('INSERT INTO bot_receipts VALUES(%s,%s,%s)', (event, Jsonb(response), time.time()))
    except Exception:
        log.exception('task_bot_update_failed')
        raise
    bot_notifications.wake()
    bot_extras.deliver_posts(db, api)
    if callback.get('id') and response.get('method') != 'answerCallbackQuery':
        try:
            api('answerCallbackQuery', {'callback_query_id': callback['id']})
        except Exception:
            log.warning('task_bot_callback_ack_failed')
    return response

def route(c, uid, text, action, message, api, admin):
    cmd = text.split(maxsplit=1)[0].split('@')[0] if text else ''
    if action.startswith('admin') or cmd.startswith('/bot'):
        if not admin:
            return say(uid, tr('Доступ только администратору.', html_mode=False, section='task_bot', limit=3000))
        return administration(c, uid, text, action, api)
    extra = bot_extras.route(c, uid, text, action, message, api)
    if extra is not None:
        return extra
    presentation = bot_ui.route(c, uid, text, action, message)
    if presentation is not None:
        return presentation
    public = bot_about.route(c, uid, text, action)
    if public is not None:
        return public
    topup = bot_topups.route(c, uid, action)
    if topup is not None:
        return topup
    if action in ('history', 'claims', 'payouts', 'games'):
        state(c, uid, 'clear')
    if action == 'cancel_input':
        state(c, uid, 'clear')
        return say(uid, tr('Действие отменено. Выбери раздел в меню внизу.', html_mode=False, section='task_bot', limit=3000))
    if action.startswith(('confirm_task:', 'confirm_payout:')):
        return confirmation(c, uid, action)
    if text in sum(MENU, []) or cmd in ('/start', '/help', '/menu', '/cancel'):
        state(c, uid, 'clear')
    if text == '🚀 Заработать' or action == 'earn':
        return bot_ui.earn(c, uid)
    if text == '🎮 Игры' or action == 'games':
        return say(uid, tr('🎮 Игры\nОткрой свою ферму:', html_mode=False, section='task_bot', limit=3000), [[{'text': tr('🌾 Ферма', html_mode=False, section='task_bot', limit=3000), 'web_app': {'url': farm_url()}}]])
    if text in ('👤 Мой кабинет', '/start wallet') or action == 'cabinet':
        return cabinet(c, uid)
    if text == '📣 Продвижение' or action == 'promotion':
        return bot_ui.promotion(c, uid)
    if action in ('convert', 'convert_to_ads', 'convert_from_ads', 'tofarm', 'fromfarm'):
        state(c, uid, 'clear')
        return cabinet(c, uid)
    if action == 'history':
        rows = c.execute('SELECT delta,kind,details,created FROM bot_ledger WHERE uid=%s ORDER BY created DESC LIMIT 15', (uid,)).fetchall()
        return say(uid, tr('📜 Последние операции\n{v0}', {'v0': '\n'.join((('+' if r['delta'] >= 0 else '−') + money(abs(r['delta'])) + ' · ' + r['details'] for r in rows)) or 'Операций пока нет.'}, html_mode=False, section='task_bot', limit=3000))
    if action == 'claims':
        rows = c.execute('SELECT t.title,x.status FROM bot_claims x JOIN bot_tasks t ON t.id=x.task\n          WHERE x.uid=%s ORDER BY x.created DESC LIMIT 15', (uid,)).fetchall()
        labels = {'started': tr('В работе', html_mode=False, section='task_bot', limit=3000), 'review': tr('На проверке', html_mode=False, section='task_bot', limit=3000), 'paid': tr('Оплачено', html_mode=False, section='task_bot', limit=3000), 'rejected': tr('Отклонено', html_mode=False, section='task_bot', limit=3000)}
        return say(uid, tr('✅ Мои выполнения\n{v0}', {'v0': '\n'.join((r['title'] + ' · ' + labels.get(r['status'], r['status']) for r in rows)) or 'Пока нет взятых заданий.'}, html_mode=False, section='task_bot', limit=3000))
    if action == 'payouts':
        rows=c.execute("SELECT p.id,p.amount,CASE WHEN EXISTS(SELECT 1 FROM bot_payout_work w WHERE w.id=p.id AND w.phase='working') THEN 'working' ELSE p.status END AS status FROM bot_payouts p WHERE p.uid=%s ORDER BY p.created DESC LIMIT 10",(uid,)).fetchall()
        labels = {'working': '🏦 В работе', 'pending': tr('На проверке', html_mode=False, section='task_bot', limit=3000), 'paid': tr('Выплачено', html_mode=False, section='task_bot', limit=3000), 'rejected': tr('Отклонено', html_mode=False, section='task_bot', limit=3000), 'cancelled': tr('Отменено', html_mode=False, section='task_bot', limit=3000)}
        return say(uid, tr('📥 Заявки\n{v0}', {'v0': '\n'.join((r['id'][:8] + ' · ' + money(r['amount']) + ' · ' + labels[r['status']] for r in rows)) or 'Заявок пока нет.'}, html_mode=False, section='task_bot', limit=3000), [[button('Отменить ожидающую заявку', 'cancelpayout')]])
    if action == 'cancelpayout':
        row = c.execute("UPDATE bot_payouts SET status='cancelled' WHERE uid=%s AND status='pending' AND NOT EXISTS(SELECT 1 FROM bot_payout_work w WHERE w.id=bot_payouts.id AND w.phase='working') RETURNING amount,id", (uid,)).fetchone()
        if not row:
            raise UserError(tr('Нет заявки, доступной для отмены. Выплату в работе отменить нельзя.', html_mode=False, section='task_bot', limit=3000))
        change(c, uid, row['amount'], 'payout_cancel', 'Отмена ' + row['id'][:8])
        return cabinet(c, uid)
    if action == 'withdraw':
        state(c, uid, action)
        rules = bot_admin.limits(c)
        return input_prompt(uid, tr('💸 Вывод средств\n\nС баланса: от {v0} до {v1}\nКомиссия: {v2}%\n\nВведи сумму в гривнах. Затем укажешь реквизиты для ручной выплаты.', {'v0': money(rules['withdraw_min']), 'v1': money(rules['withdraw_max']), 'v2': bot_economy.pct(rules['withdraw_fee'])}, section='task_bot'))
    if action.startswith('new:'):
        kind = action.split(':')[1]
        if kind not in KINDS:
            raise UserError(tr('Неизвестный тип задания.', html_mode=False, section='task_bot', limit=3000))
        if kind == 'post' and (not bot_extras.settings(c)['channel_id']):
            raise UserError(tr('Канал рекламных постов ещё не подключён администратором.', html_mode=False, section='task_bot', limit=3000))
        state(c, uid, 'task_title', {'kind': kind})
        return input_prompt(uid, tr('{v0}Введи название задания (до 100 символов).', {'v0': 'Пост появится в нашем канале после модерации. Оплачивается нажатие кнопки, а не доказанное прочтение.\n\n' if kind == 'post' else ''}, html_mode=False, section='task_bot', limit=3000))
    if action.startswith(('list:', 'mine:', 'reviews:')):
        parts = action.split(':')
        try:
            offset = max(0, min(100000, int(parts[-1])))
        except ValueError:
            raise UserError(tr('Некорректная страница.', html_mode=False, section='task_bot', limit=3000))
        if parts[0] == 'reviews':
            rows = c.execute("SELECT x.task,x.uid FROM bot_claims x JOIN bot_tasks t ON t.id=x.task\n              WHERE t.owner=%s AND x.status='review' ORDER BY x.created LIMIT 8 OFFSET %s", (uid, offset)).fetchall()
            buttons = [[button(f"Работа {r['uid']} · {r['task'][:6]}", f"review:{r['task']}:{r['uid']}")] for r in rows]
        elif parts[0] == 'mine':
            rows = c.execute('SELECT * FROM bot_tasks WHERE owner=%s ORDER BY created DESC LIMIT 8 OFFSET %s', (uid, offset)).fetchall()
            buttons = [[button(f"{r['title'][:30]} · {r['status']}", 'own:' + r['id'])] for r in rows]
        else:
            kind = parts[1]
            rows = c.execute('SELECT t.* FROM bot_tasks t WHERE ' + bot_ui.catalog_filter() + ' AND t.kind=%s ORDER BY t.created LIMIT 8 OFFSET %s', (uid, uid, uid, kind, offset)).fetchall()
            buttons = [[button(r['title'][:35] + ' · ' + money(r['reward']), 'task:' + r['id'])] for r in rows]
        if len(rows) == 8:
            buttons.append([button('Далее →', ':'.join(parts[:-1]) + ':' + str(offset + 8))])
        if offset:
            buttons.append([button('← Назад', ':'.join(parts[:-1]) + ':' + str(max(0, offset - 8)))])
        return say(uid, tr('Выбери:', html_mode=False, section='task_bot', limit=3000) if rows else tr('Пока ничего нет.', html_mode=False, section='task_bot', limit=3000), buttons + [[button('⬅️ Продвижение' if parts[0] != 'list' else '⬅️ Заработать', 'promotion' if parts[0] != 'list' else 'earn')]])
    if action.startswith('rejectdecision:'):
        return bot_decisions.confirm(c,uid,action.split(':')[-1])
    if action.startswith(('task:', 'take:', 'check:', 'own:', 'close:', 'review:', 'accept:', 'rejectwork:')):
        parts = action.split(':')
        t = c.execute('SELECT * FROM bot_tasks WHERE id=%s FOR UPDATE', (parts[1],)).fetchone()
        if not t:
            raise UserError(tr('Задание не найдено.', html_mode=False, section='task_bot', limit=3000))
        op = parts[0]
        if op in ('own', 'close', 'review', 'accept', 'rejectwork'):
            if t['owner'] != uid:
                raise UserError(tr('Это задание другого рекламодателя.', html_mode=False, section='task_bot', limit=3000))
            if op == 'own':
                return bot_advertising.card(c,t)
            if op == 'close':
                if t['kind'] == 'post' and c.execute("SELECT 1 FROM bot_post_publications WHERE task=%s AND status IN ('sending','uncertain')", (t['id'],)).fetchone():
                    raise UserError(tr('Сначала администратор должен проверить результат публикации поста.', html_mode=False, section='task_bot', limit=3000))
                if c.execute("SELECT 1 FROM bot_claims WHERE task=%s AND status='review'", (t['id'],)).fetchone():
                    raise UserError(tr('Сначала проверь присланные работы.', html_mode=False, section='task_bot', limit=3000))
                refund = t['remaining']
                c.execute("UPDATE bot_tasks SET status='closed',remaining=0 WHERE id=%s", (t['id'],))
                if refund:
                    change(c, uid, refund, 'task_close', 'Закрытие задания ' + t['id'])
                return say(uid, tr('Задание закрыто. Возвращено: {v0}', {'v0': money(refund)}, html_mode=False, section='task_bot', limit=3000))
            try:
                worker = int(parts[2])
            except (IndexError, ValueError):
                raise UserError(tr('Некорректный номер работы.', html_mode=False, section='task_bot', limit=3000))
            claim = c.execute("SELECT * FROM bot_claims WHERE task=%s AND uid=%s AND status='review'", (t['id'], worker)).fetchone()
            if not claim:
                raise UserError(tr('Работа уже проверена.', html_mode=False, section='task_bot', limit=3000))
            if op == 'review':
                buttons = [[button('✅ Принять', f"accept:{t['id']}:{worker}"), button('❌ Отклонить', f"rejectwork:{t['id']}:{worker}")]]
                if claim['photo']:
                    return {'method': 'sendPhoto', 'chat_id': uid, 'photo': claim['photo'], 'caption': (t['title'] + '\nИгрок: ' + str(worker) + '\n' + claim['proof'])[:1000], 'reply_markup': {'inline_keyboard': buttons}}
                return say(uid, tr('{v0}\nИгрок: {v1}\n\n{v2}', {'v0': t['title'], 'v1': str(worker), 'v2': claim['proof']}, html_mode=False, section='task_bot', limit=3000), buttons)
            if op == 'accept':
                award(c, t, worker)
                state(c,uid,'clear')
                bot_notifications.enqueue(c,'work-accepted:'+t['id']+':'+str(worker),tr('✅ Работа принята\n\nЗадание: {v0}\nНачислено: {v1}', {'v0': t['title'], 'v1': money(t['reward'])}, section='notifications'),recipient=worker)
                return say(uid, tr('Работа принята, награда начислена игроку.', html_mode=False, section='task_bot', limit=3000))
            return bot_decisions.begin(c,uid,'work',t['id'],worker)
        if t['status'] != 'active' or t['remaining'] < bot_economy.cost(c, t) or t['owner'] == uid:
            raise UserError(tr('Задание недоступно или бюджет исчерпан.', html_mode=False, section='task_bot', limit=3000))
        reserved = c.execute("SELECT count(*) AS n FROM bot_claims WHERE task=%s AND status='review'", (t['id'],)).fetchone()['n']
        if t['remaining'] < (reserved + 1) * bot_economy.cost(c, t):
            raise UserError(tr('Все места этого задания сейчас на проверке. Выбери другое задание.', html_mode=False, section='task_bot', limit=3000))
        if t['kind'] == 'post':
            publication = c.execute("SELECT url FROM bot_post_publications WHERE task=%s AND status='posted'", (t['id'],)).fetchone()
            return say(uid, tr('Получить награду можно только кнопкой под исходным постом в нашем канале.', html_mode=False, section='task_bot', limit=3000), [[{'text': tr('Открыть пост', html_mode=False, section='task_bot', limit=3000), 'url': publication['url']}]] if publication else None)
        if op == 'task':
            return task_card(t, uid, c)
        claim = c.execute('SELECT * FROM bot_claims WHERE task=%s AND uid=%s', (t['id'], uid)).fetchone()
        if claim and claim['status'] in ('paid', 'rejected', 'review'):
            raise UserError({'paid': 'Награда уже получена.', 'rejected': 'Работа отклонена.', 'review': 'Работа ожидает ручной проверки.'}[claim['status']])
        if op in ('take', 'check') and t['kind'] in ('channel', 'group'):
            own = api('getMe', {})
            if api('getChatMember', {'chat_id': t['chat_id'], 'user_id': own['id']}).get('status') not in ('administrator', 'creator'):
                raise UserError(tr('Проверка временно недоступна: нашему боту нужны права администратора этого чата.', html_mode=False, section='task_bot', limit=3000))
        if op == 'take':
            if t['kind'] in ('channel', 'group') and bot_economy.terms(c, t['id']):
                c.execute('INSERT INTO bot_membership_accept VALUES(%s,%s,%s) ON CONFLICT DO NOTHING', (t['id'], uid, time.time()))
            if not claim:
                if t['kind'] in ('channel', 'group') and member(api('getChatMember', {'chat_id': t['chat_id'], 'user_id': uid})):
                    raise UserError(tr('Ты уже состоишь в этом канале/группе. Это задание для новых участников.', html_mode=False, section='task_bot', limit=3000))
                c.execute("INSERT INTO bot_claims(task,uid,status,created) VALUES(%s,%s,'started',%s)", (t['id'], uid, time.time()))
            if t['kind'] == 'bot':
                if c.execute('SELECT 1 FROM bot_bot_completions WHERE uid=%s AND bot_id=%s', (uid, t['chat_id'])).fetchone():
                    raise UserError(tr('Ты уже получал награду за этого бота.', html_mode=False, section='task_bot', limit=3000))
                state(c, uid, 'bot_forward', {'task': t['id']})
            return task_card(t, uid, c)
        if not claim:
            raise UserError(tr('Сначала нажми «Взять задание», затем выполни его и нажми «Проверить».', html_mode=False, section='task_bot', limit=3000))
        if t['kind'] == 'bot':
            state(c, uid, 'bot_forward', {'task': t['id']})
            return task_card(t, uid, c)
        if t['kind'] == 'manual':
            state(c, uid, 'proof', {'task': t['id']})
            return input_prompt(uid, tr('Отправь доказательство выполнения: текст или одно фото с подписью. Проверит рекламодатель.', html_mode=False, section='task_bot', limit=3000))
        if not member(api('getChatMember', {'chat_id': t['chat_id'], 'user_id': uid})):
            raise UserError(tr('Подписка пока не подтверждена. Вступи в канал/группу и повтори проверку.', html_mode=False, section='task_bot', limit=3000))
        award(c, t, uid)
        return say(uid, tr('✅ Проверка пройдена. Начислено {v0}', {'v0': money(t['reward'])}, html_mode=False, section='task_bot', limit=3000))
    current = state(c, uid)
    if current:
        if current['state'].startswith('admin_'):
            if not admin:
                raise UserError(tr('Доступ только администратору.', html_mode=False, section='task_bot', limit=3000))
            return bot_admin.input_text(c, uid, text, message, current, api)
        if current['state'] in ('topup_config', 'topup_bank_reference', 'topup_bank_confirm'):
            if not admin:
                raise UserError(tr('Доступ только администратору.', html_mode=False, section='task_bot', limit=3000))
            return bot_topups.admin_input(c, uid, text, current)
        if current['state'] in ('topup_stars', 'topup_card_amount', 'topup_card_receipt'):
            return bot_topups.input_text(c, uid, text, message, current)
        if current['state'] == 'public_support':
            return bot_about.support(c, uid, text, message)
        if current['state'] == 'about_edit':
            if not admin:
                raise UserError(tr('Доступ только администратору.', html_mode=False, section='task_bot', limit=3000))
            return bot_about.edit(c, uid, text, current['data'])
        if current['state'] in ('welcome_edit', 'welcome_confirm'):
            return bot_ui.input_text(c, uid, text, message, current)
        if current['state'] == 'economy_edit':
            if not admin:
                raise UserError(tr('Доступ только администратору.', html_mode=False, section='task_bot', limit=3000))
            return bot_economy.edit(c, uid, text, current['data'])
        return process_input(c, uid, text, message, current, api)
    return bot_ui.home(c, uid)

def process_input(c, uid, text, message, current, api):
    if current['state'] in ('work_rejection_reason','work_rejection_confirm'):
        return bot_decisions.input_text(c,uid,text,current)
    stage, data = (current['state'], current['data'])
    if stage == 'task_bot_identity':
        return bot_extras.bot_identity(c, uid, message, data)
    if stage == 'bot_forward':
        return bot_extras.bot_completion(c, uid, message, data)
    if stage == 'bind_post':
        origin = message.get('forward_origin') or {}
        if origin.get('type') != 'channel' or (origin.get('chat') or {}).get('id') != data['channel'] or (not isinstance(origin.get('message_id'), int)):
            raise UserError(tr('Перешли исходный пост именно из подключённого канала.', html_mode=False, section='task_bot', limit=3000))
        cfg = bot_extras.settings(c)
        c.execute("UPDATE bot_post_publications SET status='posted',message_id=%s,url=%s WHERE task=%s AND status IN ('sending','uncertain')", (origin['message_id'], bot_extras.publication_url(data['channel'], origin['message_id'], cfg['channel_url']), data['task']))
        state(c, uid, 'clear')
        return say(uid, tr('Пост привязан к заданию. Проверь, что кнопка получения награды стоит под правильным постом.', html_mode=False, section='task_bot', limit=3000))
    if stage in ('convert_to_ads', 'convert_from_ads', 'tofarm', 'fromfarm'):
        state(c, uid, 'clear')
        return cabinet(c, uid)
    if stage == 'deposit':
        return bot_topups.menu(c, uid)
    if stage == 'withdraw':
        n = amount(text)
        rules = bot_admin.limits(c)
        if not rules['withdraw_min'] <= n <= rules['withdraw_max']:
            raise UserError(tr('Сумма вывода: от {v0} до {v1}', {'v0': money(rules['withdraw_min']), 'v1': money(rules['withdraw_max'])}, html_mode=False, section='task_bot', limit=3000))
        fee = (n * rules['withdraw_fee'] + 9999) // 10000
        if n - fee < 1:
            raise UserError(tr('После комиссии сумма к выплате должна быть не меньше копейки.', html_mode=False, section='task_bot', limit=3000))
        if n > account(c, uid)['available']:
            raise UserError(tr('Недостаточно средств.', html_mode=False, section='task_bot', limit=3000))
        if c.execute("SELECT 1 FROM bot_payouts WHERE uid=%s AND status='pending'", (uid,)).fetchone():
            raise UserError(tr('Сначала дождись обработки предыдущей заявки или отмени её в кабинете.', html_mode=False, section='task_bot', limit=3000))
        state(c, uid, 'destination', {'amount': n, 'fee': fee, 'net': n - fee})
        return input_prompt(uid, tr('Укажи реквизиты для выплаты: номер карты или IBAN и имя получателя. Не отправляй CVV, PIN, пароли или коды.', html_mode=False, section='task_bot', limit=3000))
    if stage == 'destination':
        if not 8 <= len(text) <= 250:
            raise UserError(tr('Реквизиты должны содержать от 8 до 250 символов.', html_mode=False, section='task_bot', limit=3000))
        data['destination'] = text
        data['nonce'] = uuid.uuid4().hex[:12]
        state(c, uid, 'payout_confirm', data)
        return say(uid, tr('Проверить заявку\nСумма с баланса: {v0}\nКомиссия: {v1}\nК выплате: {v2}\nРеквизиты: {v3}\n\nПосле подтверждения сумма будет зарезервирована до ручной выплаты.', {'v0': f"{money(data['amount'])}", 'v1': f"{money(data.get('fee', 0))}", 'v2': f"{money(data.get('net', data['amount']))}", 'v3': f'{text}'}, html_mode=False, section='task_bot', limit=3000), [[button('✅ Подтвердить', 'confirm_payout:' + data['nonce']), button('Отмена', 'cancel_input')]])
    if stage == 'proof':
        photos = message.get('photo') or []
        proof = (text or message.get('text') or message.get('caption') or '').strip()
        if not proof and (not photos):
            raise UserError(tr('Отправь текст или фото, не документ и не альбом.', html_mode=False, section='task_bot', limit=3000))
        if message.get('media_group_id'):
            raise UserError(tr('Пришли одно фото, не альбом.', html_mode=False, section='task_bot', limit=3000))
        if len(proof) > 1500:
            raise UserError(tr('Сократи описание до 1500 символов.', html_mode=False, section='task_bot', limit=3000))
        t = c.execute('SELECT * FROM bot_tasks WHERE id=%s FOR UPDATE', (data['task'],)).fetchone()
        reviews = c.execute("SELECT count(*) AS n FROM bot_claims WHERE task=%s AND status='review'", (t['id'],)).fetchone()['n'] if t else 0
        if not t or t['status'] != 'active' or t['remaining'] < (reviews + 1) * bot_economy.cost(c, t):
            raise UserError(tr('Свободный бюджет задания закончился. Можно выбрать другое задание.', html_mode=False, section='task_bot', limit=3000))
        row = c.execute("UPDATE bot_claims SET status='review',proof=%s,photo=%s\n          WHERE task=%s AND uid=%s AND status='started' RETURNING uid", (proof, photos[-1]['file_id'] if photos else '', t['id'], uid)).fetchone()
        if not row:
            raise UserError(tr('Работа уже отправлена или задание не взято.', html_mode=False, section='task_bot', limit=3000))
        bot_notifications.enqueue(c,'work-review:'+t['id']+':'+str(uid),tr('📝 Пришла работа на проверку\n\nЗадание: {v0}\nИсполнитель: {v1}', {'v0': t['title'], 'v1': str(uid)}, section='notifications'),'review:'+t['id']+':'+str(uid),recipient=t['owner'])
        state(c, uid, 'clear')
        return say(uid, tr('Работа отправлена на ручную проверку. Результат и начисление появятся в кабинете.', html_mode=False, section='task_bot', limit=3000))
    if stage.startswith('task_'):
        if stage == 'task_title':
            if not 3 <= len(text) <= 100:
                raise UserError(tr('Название: от 3 до 100 символов.', html_mode=False, section='task_bot', limit=3000))
            data['title'] = text
            next_stage, prompt = ('task_description', tr('Опиши, что нужно сделать (10–1000 символов). Для ручного задания укажи, какое доказательство прислать.', html_mode=False, section='task_bot', limit=3000))
        elif stage == 'task_description':
            if not 10 <= len(text) <= 1000:
                raise UserError(tr('Описание: от 10 до 1000 символов.', html_mode=False, section='task_bot', limit=3000))
            data['description'] = text
            next_stage, prompt = ('task_url', tr('Добавь @Farmlife2026bot администратором канала/группы. Затем пришли ссылку или числовой ID. Права будут проверены автоматически.', html_mode=False, section='task_bot', limit=3000) if data['kind'] in ('channel', 'group') else tr('Пришли HTTPS-ссылку на бота/материал. Для поста без ссылки отправь минус (-).', html_mode=False, section='task_bot', limit=3000))
        elif stage == 'task_url':
            if data['kind'] == 'bot':
                path = urlsplit(text)
                username = path.path.strip('/')
                if len(text) > 400 or path.scheme != 'https' or path.hostname != 't.me' or (not re.fullmatch('[A-Za-z][A-Za-z0-9_]{3,31}', username)) or (not username.lower().endswith('bot')):
                    raise UserError(tr('Нужна ссылка https://t.me/ИмяБота, при необходимости с параметром start.', html_mode=False, section='task_bot', limit=3000))
                data['url'], data['bot_username'] = (text, username)
                data['chat_id'] = None
            elif data['kind'] == 'post' and text == '-':
                data['url'], data['chat_id'] = ('', None)
            elif data['kind'] in ('manual', 'post'):
                parsed = urlsplit(text)
                if len(text) > 400 or parsed.scheme != 'https' or (not parsed.hostname) or parsed.username or parsed.password:
                    raise UserError(tr('Нужна корректная HTTPS-ссылка без паролей в адресе.', html_mode=False, section='task_bot', limit=3000))
                data['url'], data['chat_id'] = (text, None)
            else:
                try:
                    data['chat_id'], data['url'] = resolve_chat(api, text, data['kind'])
                except UserError:
                    raise
                except Exception:
                    raise UserError(tr('Telegram не подтвердил доступ к чату. Проверь ссылку и права нашего бота.', html_mode=False, section='task_bot', limit=3000))
            if data['kind'] == 'manual':
                default = bot_economy.quote(c, 'manual')
                next_stage, prompt = ('task_reward', tr('Укажи полную цену одного выполнения, включая комиссию. Например: {v0}', {'v0': money(default['cost'])}, html_mode=False, section='task_bot', limit=3000))
            else:
                q = bot_economy.quote(c, data['kind'])
                data['terms'], data['reward'] = (q, q['reward'])
                next_stage, prompt = ('task_count', tr('Цена выполнения: {v0}. Награда исполнителю: {v1}.\nНа сколько выполнений выделить бюджет? От 1 до {v2}.', {'v0': money(q['cost']), 'v1': money(q['reward']), 'v2': str(bot_admin.limits(c)['max_executions'])}, html_mode=False, section='task_bot', limit=3000))
        elif stage == 'task_reward':
            q = bot_economy.quote(c, data['kind'], amount(text))
            data['terms'], data['reward'] = (q, q['reward'])
            next_stage, prompt = ('task_count', tr('На сколько выполнений выделить бюджет? От 1 до {v0}.', {'v0': str(bot_admin.limits(c)['max_executions'])}, html_mode=False, section='task_bot', limit=3000))
        elif stage == 'task_count':
            if not text.isdecimal() or not 1 <= int(text) <= bot_admin.limits(c)['max_executions']:
                raise UserError(tr('Укажи целое число от 1 до {v0}.', {'v0': str(bot_admin.limits(c)['max_executions'])}, html_mode=False, section='task_bot', limit=3000))
            total = data.get('terms', {}).get('cost', data['reward']) * int(text)
            if total > account(c, uid)['available']:
                raise UserError(tr('На балансе не хватает средств. Пополни баланс либо укажи меньше выполнений.', html_mode=False, section='task_bot', limit=3000))
            data['budget'] = total
            data['nonce'] = uuid.uuid4().hex[:12]
            state(c, uid, 'task_confirm', data)
            return say(uid, tr('{v0}\nНаграда: {v1}\nВыполнений: {v2}\nПолная цена выполнения: {v3}\nБюджет: {v4}\nКомиссия уже включена в цену\n\nПосле подтверждения бюджет резервируется, задание отправляется на модерацию.', {'v0': f"{data['title']}", 'v1': f"{money(data['reward'])}", 'v2': f'{text}', 'v3': f"{money(data.get('terms', {}).get('cost', data['reward']))}", 'v4': f'{money(total)}'}, html_mode=False, section='task_bot', limit=3000), [[button('✅ Создать', 'confirm_task:' + data['nonce']), button('Отмена', 'cancel_input')]])
        else:
            return input_prompt(uid, tr('Подтверди действие кнопкой выше или нажми «Отмена».', html_mode=False, section='task_bot', limit=3000))
        state(c, uid, next_stage, data)
        return input_prompt(uid, prompt)
    return input_prompt(uid, tr('Подтверди действие кнопкой выше или нажми «Отмена».', html_mode=False, section='task_bot', limit=3000))

def confirmation(c, uid, action):
    current = state(c, uid)
    if not current:
        raise UserError(tr('Действие уже выполнено или отменено.', html_mode=False, section='task_bot', limit=3000))
    data = current['data']
    action, nonce = action.split(':', 1)
    if nonce != data.get('nonce'):
        raise UserError(tr('Эта кнопка относится к другой заявке. Используй последнее подтверждение.', html_mode=False, section='task_bot', limit=3000))
    if action == 'confirm_task' and current['state'] == 'task_confirm':
        tid = uuid.uuid4().hex[:16]
        change(c, uid, -data['budget'], 'task_budget', 'Бюджет задания ' + tid)
        c.execute("INSERT INTO bot_tasks(id,owner,kind,title,description,url,chat_id,reward,remaining,status,created) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,'pending',%s)", (tid, uid, data['kind'], data['title'], data['description'], data['url'], data.get('chat_id'), data['reward'], data['budget'], time.time()))
        bot_notifications.enqueue(c,'task:'+tid,tr('📝 Новый заказ на модерации\n\nАвтор: {v0}\nНазвание: {v1}\nБюджет: {v2}', {'v0': str(uid), 'v1': data['title'], 'v2': money(data['budget'])}, section='notifications'),'admin:tasks',subject=uid)
        bot_economy.save_terms(c, tid, data)
        bot_advertising.save(c,tid,data)
        result = say(uid, tr('Задание {v0} создано и ожидает модерации. Бюджет зарезервирован.', {'v0': tid}, html_mode=False, section='task_bot', limit=3000))
    elif action == 'confirm_payout' and current['state'] == 'payout_confirm':
        if c.execute("SELECT 1 FROM bot_payouts WHERE uid=%s AND status='pending'", (uid,)).fetchone():
            raise UserError(tr('У тебя уже есть ожидающая заявка.', html_mode=False, section='task_bot', limit=3000))
        pid = uuid.uuid4().hex[:16]
        change(c, uid, -data['amount'], 'payout_reserve', 'Резерв заявки ' + pid)
        c.execute("INSERT INTO bot_payouts(id,uid,amount,destination,status,created) VALUES(%s,%s,%s,%s,'pending',%s)", (pid, uid, data['amount'], data['destination'], time.time()))
        c.execute('INSERT INTO bot_payout_terms VALUES(%s,%s,%s)', (pid, data.get('fee', 0), data.get('net', data['amount'])))
        bot_notifications.enqueue(c,'payout:'+pid,tr('💸 Новая заявка на вывод\n\nИгрок: {v0}\nС баланса: {v1}\nК выплате: {v2}\nЗаявка: {v3}\n\nСредства зарезервированы. Перевод ещё не выполнен.', {'v0': str(uid), 'v1': money(data['amount']), 'v2': money(data.get('net', data['amount'])), 'v3': pid}, section='notifications'),'admin:payview:'+pid,subject=uid)
        result = say(uid, tr('Заявка {v0} принята. Зарезервировано {v1}. Выплата выполняется администратором вручную.', {'v0': pid, 'v1': money(data['amount'])}, html_mode=False, section='task_bot', limit=3000))
    else:
        raise UserError(tr('Эта кнопка устарела.', html_mode=False, section='task_bot', limit=3000))
    state(c, uid, 'clear')
    return result

def administration(c, uid, text, action, api):
    result=_administration(c,uid,text,action,api)
    if action in ('admin:tasks','admin:postissues','admin:retention'):
        back='admin:section:tasks'
    elif action in ('admin:payouts','admin:topupsettings','admin:cardtopups'):
        back='admin:section:finance'
    elif action.startswith(('admin:approve:','admin:rejecttask:')):
        back='admin:tasks'
    elif action.startswith(('admin:cardconfirm:','admin:cardreject:')):
        back='admin:cardtopups'
    elif action.startswith(('admin:payconfirm:','admin:rejectpayout:')):
        back='admin:payouts'
    else:
        return result
    rows=(result.get('reply_markup') or {}).get('inline_keyboard',[])
    result['reply_markup']={'inline_keyboard':rows}
    rows[:]=[row for row in rows if not any(btn.get('callback_data')=='bot:admin' for btn in row)]
    rows.append([button('⬅️ Назад',back)])
    return result

def _administration(c, uid, text, action, api):
    decision=bot_decisions.admin(c,uid,action)
    if decision is not None:return decision
    console = bot_admin.admin(c, uid, text, action, api)
    if console is not None:
        return console
    topup = bot_topups.admin(c, uid, action)
    if topup is not None:
        return topup
    public = bot_about.admin(c, uid, action)
    if public is not None:
        return public
    economy = bot_economy.admin(c, uid, text, action)
    if economy is not None:
        return economy
    extra = bot_extras.administration(c, uid, text, action, api)
    if extra is not None:
        return extra
    parts = text.split()
    command = parts[0].split('@')[0] if parts else ''
    if command in ('/botcredit', '/botfund', '/botpaid'):
        try:
            if command == '/botcredit':
                if len(parts) not in (4, 5) or not parts[1].isdecimal() or (not 3 <= len(parts[3]) <= 80) or (len(parts) == 5 and parts[4] not in ('main', 'ads')):
                    raise UserError(tr('Формат: /botcredit TelegramID Сумма УникальныйНомерПлатежа Только после фактического получения денег. Игрок должен открыть бота хотя бы раз.', html_mode=False, section='task_bot', limit=3000))
                target, n, ref = (int(parts[1]), amount(parts[2]), parts[3])
                if not account(c, target):
                    raise UserError(tr('Игрок ещё не зарегистрирован в боте.', html_mode=False, section='task_bot', limit=3000))
                inserted = c.execute('INSERT INTO bot_deposits VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING reference', (ref, target, n, time.time())).fetchone()
                if not inserted:
                    raise UserError(tr('Такой платёж уже учтён. Повторного начисления нет.', html_mode=False, section='task_bot', limit=3000))
                c.execute('UPDATE bot_cash_pool SET amount=amount+%s WHERE id=1', (n,))
                change(c, target, n, 'manual_deposit', 'Подтверждённый платёж ' + ref)
                return say(uid, tr('Зачислено {v0} пользователю {v1} на единый баланс.', {'v0': f'{money(n)}', 'v1': f'{target}'}, html_mode=False, section='task_bot', limit=3000))
            if command == '/botfund':
                if len(parts) != 3 or not 3 <= len(parts[2]) <= 80:
                    raise UserError(tr('Формат: /botfund Сумма УникальныйНомерВзноса\nУчёт собственных денег, фактически выделенных на выплаты.', html_mode=False, section='task_bot', limit=3000))
                n, ref = (amount(parts[1]), parts[2])
                if not c.execute('INSERT INTO bot_deposits VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING reference', (ref, uid, n, time.time())).fetchone():
                    raise UserError(tr('Этот взнос уже учтён.', html_mode=False, section='task_bot', limit=3000))
                c.execute('UPDATE bot_cash_pool SET amount=amount+%s WHERE id=1', (n,))
                c.execute("INSERT INTO bot_ledger VALUES(%s,%s,0,'reserve_funding',%s,%s)", (uuid.uuid4().hex, uid, money(n) + ' · ' + ref, time.time()))
                return say(uid, tr('Резерв увеличен на {v0}', {'v0': money(n)}, html_mode=False, section='task_bot', limit=3000))
            if len(parts) != 3 or not 3 <= len(parts[2]) <= 80:
                raise UserError(tr('Формат: /botpaid НомерЗаявки НомерБанковскойОперации\nТолько после фактической выплаты. Команда не переводит деньги.', html_mode=False, section='task_bot', limit=3000))
            p = c.execute("SELECT * FROM bot_payouts WHERE id=%s AND status='pending' FOR UPDATE", (parts[1],)).fetchone()
            if not p:
                raise UserError(tr('Нет ожидающей заявки с таким номером.', html_mode=False, section='task_bot', limit=3000))
            work=bot_payouts.require(c,p['id'],uid)
            state(c, uid, 'admin_pay_confirm', {'id': p['id'], 'reference': parts[2], 'work_token':work['token'],'nonce': uuid.uuid4().hex[:12]})
            current = state(c, uid)
            return say(uid, tr('Подтвердить фактическую выплату?\nЗаявка: {v0}\nПолучатель: {v1}\nСумма: {v2}\nРеквизиты: {v3}\nОперация: {v4}', {'v0': f"{p['id']}", 'v1': f"{p['uid']}", 'v2': f'{money(bot_admin.net(c, p))}', 'v3': f"{p['destination']}", 'v4': f'{parts[2]}'}, html_mode=False, section='task_bot', limit=3000), [[button('✅ Выплачено, подтвердить', 'admin:payconfirm:' + current['data']['nonce']), button('Отмена', 'admin:cancel')]])
        except (ValueError, IndexError):
            raise UserError(tr('Проверь введённые данные и открой управление ботом кнопкой в кабинете.', html_mode=False, section='task_bot', limit=3000))
    if action == 'admin:cancel':
        state(c, uid, 'clear')
        return say(uid, tr('Подтверждение отменено.', html_mode=False, section='task_bot', limit=3000))
    if action.startswith('admin:payconfirm:'):
        current = state(c, uid)
        if not current or current['state'] != 'admin_pay_confirm':
            raise UserError(tr('Подтверждение устарело.', html_mode=False, section='task_bot', limit=3000))
        data = current['data']
        if action.split(':')[-1] != data.get('nonce'):
            raise UserError(tr('Подтверждение относится к другой выплате.', html_mode=False, section='task_bot', limit=3000))
        p = c.execute("SELECT * FROM bot_payouts WHERE id=%s AND status='pending' FOR UPDATE", (data['id'],)).fetchone()
        if not p:
            raise UserError(tr('Заявка уже закрыта.', html_mode=False, section='task_bot', limit=3000))
        work=bot_payouts.require(c,p['id'],uid)
        if data.get('work_token')!=work['token']:raise UserError('Подтверждение устарело. Открой заявку заново.')
        if c.execute("SELECT 1 FROM bot_payouts WHERE status='paid' AND reference=%s", (data['reference'],)).fetchone():
            raise UserError(tr('Эта банковская операция уже использована для выплаты.', html_mode=False, section='task_bot', limit=3000))
        c.execute("UPDATE bot_payouts SET status='paid',reference=%s WHERE id=%s", (data['reference'], p['id']))
        c.execute("UPDATE bot_payout_work SET phase='paid' WHERE id=%s",(p['id'],))
        row = c.execute('UPDATE bot_cash_pool SET amount=amount-%s WHERE id=1 AND amount>=%s RETURNING amount', (bot_admin.net(c, p), bot_admin.net(c, p))).fetchone()
        if not row:
            raise UserError(tr('Недостаточно учтённого резерва. Проверь учёт фактических поступлений.', html_mode=False, section='task_bot', limit=3000))
        c.execute("INSERT INTO bot_ledger VALUES(%s,%s,0,'payout_paid',%s,%s)", (uuid.uuid4().hex, p['uid'], 'Выплачено ' + money(bot_admin.net(c, p)) + ' · ' + p['id'], time.time()))
        bot_notifications.enqueue(c,'payout-paid:'+p['id'],tr('✅ Выплата выполнена\n\nСумма: {v0}\nЗаявка: {v1}', {'v0': money(bot_admin.net(c, p)), 'v1': p['id']}, section='notifications'),recipient=p['uid'])
        state(c, uid, 'clear')
        return say(uid, tr('Выплата подтверждена, заявка закрыта.', html_mode=False, section='task_bot', limit=3000))
    if action.startswith(('admin:approve:', 'admin:rejecttask:')):
        op, tid = action.split(':')[1:]
        t = c.execute("SELECT * FROM bot_tasks WHERE id=%s AND status='pending' FOR UPDATE", (tid,)).fetchone()
        if not t:
            raise UserError(tr('Задание уже прошло модерацию.', html_mode=False, section='task_bot', limit=3000))
        if op == 'approve':
            if t['kind'] == 'post':
                bot_extras.queue_post(c, t, api)
            if t['kind'] in ('channel', 'group'):
                me = api('getMe', {})
                info = api('getChatMember', {'chat_id': t['chat_id'], 'user_id': me['id']})
                if info.get('status') not in ('administrator', 'creator'):
                    raise UserError(tr('Сначала выдай нашему боту права администратора в целевом чате.', html_mode=False, section='task_bot', limit=3000))
            c.execute("UPDATE bot_tasks SET status='active' WHERE id=%s", (tid,))
            return say(uid, tr('Пост одобрен и поставлен в очередь публикации. Проверь результат кнопкой «Публикации» в управлении ботом.', html_mode=False, section='task_bot', limit=3000) if t['kind'] == 'post' else tr('Задание опубликовано.', html_mode=False, section='task_bot', limit=3000))
        return bot_decisions.begin(c,uid,'task',tid)
    if action == 'admin:postissues':
        rows = c.execute("SELECT task,status FROM bot_post_publications WHERE status IN ('sending','uncertain') LIMIT 8").fetchall()
        return say(uid, tr('Если пост опубликован, привяжи его пересылкой. Если публикации нет — обратись к разработчику для проверки, не отправляй её повторно вслепую.', html_mode=False, section='task_bot', limit=3000), [[button(r['task'] + ' · ' + r['status'], 'admin:bindpost:' + r['task'])] for r in rows])
    if action == 'admin:tasks':
        rows = c.execute("SELECT * FROM bot_tasks WHERE status='pending' ORDER BY created LIMIT 1").fetchall()
        if not rows:
            return say(uid, tr('Нет заданий на модерации.', html_mode=False, section='task_bot', limit=3000))
        t = rows[0]
        return say(uid, tr('Модерация {v0}\nАвтор: {v1}\nТип: {v2}\n{v3}\n{v4}\n{v5}\nНаграда: {v6}\nБюджет: {v7}', {'v0': f"{t['id']}", 'v1': f"{t['owner']}", 'v2': f"{t['kind']}", 'v3': f"{t['title']}", 'v4': f"{t['description']}", 'v5': f"{t['url']}", 'v6': f"{money(t['reward'])}", 'v7': f"{money(t['remaining'])}"}, html_mode=False, section='task_bot', limit=3000), [[button('✅ Опубликовать', 'admin:approve:' + t['id']), button('❌ Отклонить', 'admin:rejecttask:' + t['id'])]])
    return bot_admin.panel(c, uid)
