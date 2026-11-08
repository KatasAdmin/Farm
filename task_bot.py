import bot_promos
import referral_bridge
"""Task marketplace and UAH wallet in the existing farm bot.

All monetary values are integer kopecks. Telegram Stars are kept separate.
One transaction stores both the operation and its replayable webhook response.
"""
from bot_copy import tr
import json
import logging
import os
import re
import secrets
import time
import uuid
import threading
from concurrent.futures import ThreadPoolExecutor
import bot_extras
import bot_economy
import bot_ui
import bot_visuals
import bot_quests
import bot_monetag_cash
import bot_about
import bot_topups
import bot_crypto_pay
import bot_copy
import bot_visibility
import bot_admin
import bot_notifications
import bot_payout_channel
import bot_payouts
import bot_decisions
import bot_advertising
import bot_manual
import bot_identity
import bot_account_controls
import bot_moderation
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
    bot_identity.initialize(c)
    referral_bridge.initialize(c)
    bot_promos.initialize(c)
    statements = ['CREATE TABLE IF NOT EXISTS bot_accounts(\n          uid bigint PRIMARY KEY CHECK(uid>0), name text NOT NULL,\n          available bigint NOT NULL DEFAULT 0 CHECK(available>=0),\n          referrer bigint, created double precision NOT NULL)', 'ALTER TABLE bot_accounts ADD COLUMN IF NOT EXISTS advertising bigint NOT NULL DEFAULT 0 CHECK(advertising>=0)', 'CREATE TABLE IF NOT EXISTS bot_cash_pool(\n          id integer PRIMARY KEY CHECK(id=1), amount bigint NOT NULL DEFAULT 0 CHECK(amount>=0))', 'INSERT INTO bot_cash_pool(id) VALUES(1) ON CONFLICT DO NOTHING', 'CREATE TABLE IF NOT EXISTS bot_ledger(\n          id text PRIMARY KEY,uid bigint NOT NULL,delta bigint NOT NULL,kind text NOT NULL,\n          details text NOT NULL,created double precision NOT NULL)', 'CREATE INDEX IF NOT EXISTS bot_ledger_user ON bot_ledger(uid,created)', 'CREATE TABLE IF NOT EXISTS bot_receipts(\n          event text PRIMARY KEY,response jsonb NOT NULL,created double precision NOT NULL)', 'CREATE TABLE IF NOT EXISTS bot_states(\n          uid bigint PRIMARY KEY,state text NOT NULL,data jsonb NOT NULL,updated double precision NOT NULL)', "CREATE TABLE IF NOT EXISTS bot_tasks(\n          id text PRIMARY KEY,owner bigint NOT NULL,kind text NOT NULL,title text NOT NULL,\n          description text NOT NULL,url text NOT NULL,chat_id bigint,\n          reward bigint NOT NULL CHECK(reward>0),remaining bigint NOT NULL CHECK(remaining>=0),\n          status text NOT NULL CHECK(status IN ('pending','active','closed','rejected')),\n          created double precision NOT NULL)", 'CREATE INDEX IF NOT EXISTS bot_tasks_catalog ON bot_tasks(status,kind,created)', "CREATE TABLE IF NOT EXISTS bot_claims(\n          task text NOT NULL,uid bigint NOT NULL,status text NOT NULL,\n          proof text NOT NULL DEFAULT '',photo text NOT NULL DEFAULT '',created double precision NOT NULL,\n          PRIMARY KEY(task,uid))", "CREATE TABLE IF NOT EXISTS bot_payouts(\n          id text PRIMARY KEY,uid bigint NOT NULL,amount bigint NOT NULL CHECK(amount>0),\n          destination text NOT NULL,status text NOT NULL CHECK(status IN ('pending','paid','rejected','cancelled')),\n          reference text NOT NULL DEFAULT '',created double precision NOT NULL)", "CREATE UNIQUE INDEX IF NOT EXISTS bot_one_pending_payout ON bot_payouts(uid) WHERE status='pending'", 'CREATE TABLE IF NOT EXISTS bot_deposits(\n          reference text PRIMARY KEY,uid bigint NOT NULL,amount bigint NOT NULL CHECK(amount>0),created double precision NOT NULL)']
    for sql in statements:
        c.execute(sql)
    c.execute("CREATE TABLE IF NOT EXISTS bot_task_bot_modes(task text PRIMARY KEY,mode text NOT NULL CHECK(mode IN ('click','forward')))")
    c.execute("CREATE TABLE IF NOT EXISTS bot_bot_click_tokens(token text PRIMARY KEY,task text NOT NULL,uid bigint NOT NULL,created double precision NOT NULL,visited double precision,UNIQUE(task,uid))")
    c.execute('CREATE TABLE IF NOT EXISTS bot_bot_click_completions(uid bigint NOT NULL,username text NOT NULL,task text NOT NULL,created double precision NOT NULL,PRIMARY KEY(uid,username))')
    bot_extras.initialize(c)
    bot_economy.initialize(c)
    bot_ui.initialize(c)
    bot_quests.initialize(c)
    bot_about.initialize(c)
    bot_topups.initialize(c)
    bot_copy.initialize(c)
    bot_visibility.initialize(c)
    bot_admin.initialize(c)
    bot_notifications.initialize(c)
    bot_payout_channel.initialize(c)
    bot_crypto_pay.initialize(c)
    bot_payouts.initialize(c)
    import bot_adsgram_intervals
    bot_adsgram_intervals.initialize(c)
    bot_decisions.initialize(c)
    bot_advertising.initialize(c)
    bot_manual.initialize(c)
    bot_moderation.initialize(c)
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

# Native Telegram keyboard colors: primary (blue), success (green),
# danger (red).  Styling is presentation-only: labels, aliases, callbacks,
# visibility settings and financial logic remain unchanged.
MENU_STYLES = [
    ['success', 'primary'],  # Earn, Promotion
    ['primary', 'primary'],  # Games, Account
    ['primary', 'primary'],  # Partners, About: every button is colored
]

def say(uid, text, buttons=None):
    c=bot_copy.active_connection()
    if buttons is not None:
        # Inline screens don't use the reply keyboard. Building both used to
        # repeat six visibility queries before immediately discarding the menu.
        visible=bot_visibility.filter_buttons(c,buttons)
        return {'method':'sendMessage','chat_id':uid,'text':text,
                'reply_markup':{'inline_keyboard':style_inline_buttons(visible)} if visible else {'remove_keyboard':True}}
    menu=bot_copy.menu(MENU)
    styles_by_label={
        label: MENU_STYLES[i][j]
        for i,row in enumerate(menu)
        for j,label in enumerate(row)
    }
    if c:
        menu=bot_visibility.filter_menu(c,menu,MENU)
    menu=[
        [{'text':label, **({'style':styles_by_label[label]} if styles_by_label.get(label) else {})}
         for label in row]
        for row in menu
    ]
    out={'method':'sendMessage','chat_id':uid,'text':text}
    if menu:
        out['reply_markup']={'keyboard':menu,'resize_keyboard':True,'is_persistent':True,'one_time_keyboard':False}
    else:
        out['reply_markup']={'remove_keyboard':True}
    return out

def is_danger_label(label):
    """Cancel/decline/delete always looks dangerous regardless of callback route."""
    label=str(label or '').strip().casefold()
    # Handle emoji prefixes, custom labels and localized text.
    return any(word in label for word in (
        'отмен', 'скасув', 'cancel', 'удал', 'видал', 'відхил', 'отклон',
        'заблок', 'блокувати', 'отказ', 'відмов', 'остановить'
    ))


def button_style(action):
    """Semantic palette for all user-accessible callback buttons.

    Action identifiers are stable even when button labels are customized in
    the admin console. Every button gets a native Telegram color.
    """
    name=str(action or '').lower().removeprefix('bot:')
    terminal=name.rsplit(':',1)[-1]
    if (name in ('cancel_input','cancel','delete','confirm_delete','cancelpayout','reject','ban')
        or terminal in ('cancel','delete','reject','ban','remove','decline','deny','stop')
        or name.startswith(('admin:delete','admin:remove','admin:ban','admin:reject',
                            'admin:cancel','delete:','remove:','cancel:','reject:'))):
        return 'danger'
    if (name in ('earn','balance','withdraw','daily','daily_bonus','claim_bonus',
                 'deposit','bonus','pay','topup','cashout')
        or name.startswith(('withdraw:card','withdraw:crypto','deposit:','topup:',
                            'claim:','bonus:','quest:claim','quests:claim','daily:','payment:',
                            'admin:cardapprove:','admin:cardconfirm:','admin:payconfirm:',
                            'admin:moneyconfirm:'))):
        return 'success'
    # Navigational, informational, task-selection, and review controls are blue.
    return 'primary'


def style_inline_buttons(rows):
    """Apply colors to buttons built directly by every bot module.

    Preserve original callback/web_app/url/pay fields without mutating callers.
    """
    result=[]
    for row in rows or []:
        colored=[]
        for item in row:
            if not isinstance(item,dict):
                colored.append(item)
                continue
            entry=dict(item)
            if is_danger_label(entry.get('text','')):
                entry['style']='danger'
            elif 'style' not in entry:
                callback=entry.get('callback_data','')
                if callback:
                    entry['style']=button_style(callback)
                elif entry.get('web_app') or entry.get('url') or entry.get('switch_inline_query') is not None:
                    entry['style']='primary'
                elif entry.get('pay'):
                    entry['style']='success'
                else:
                    entry['style']='primary'
            colored.append(entry)
        result.append(colored)
    return result


def button(text, action):
    if action == 'cancel_input':
        text = '✖️ Отмена'
    visible=bot_copy.label(text,action)
    return {'text':visible,
            'callback_data':'bot:'+action,
            'style':'danger' if is_danger_label(visible) else button_style(action)}

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

def ledger_label(kind):
    labels={
        'crypto_invoice_paid':'💎 CryptoBot · пополнение',
        'cryptopay_deposit':'💎 CryptoBot · пополнение',
        'crypto_topup':'💎 CryptoBot · пополнение',
        'stars_wallet_deposit':'⭐ Stars · пополнение',
        'manual_deposit':'💳 Пополнение',
        'ads_manual_deposit':'💳 Пополнение рекламы',
        'task_reward':'✅ Награда за задание',
        'daily_bonus':'🎁 Ежедневный бонус',
        'friend_reward':'🤝 Приглашение друга',
        'referral_reward':'🤝 Реферальная награда',
        'payout_reserved':'💸 Вывод средств',
        'payout_refund':'↩️ Возврат выплаты',
        'payout_cancel':'↩️ Отмена выплаты'
    }
    if kind in labels:return labels[kind]
    if kind.startswith(('adsgram_interval_','adsgram_daily_')):
        return '🎬 AdsGram'
    if kind.startswith(('monetag','cash_ad_')):
        return '📺 Monetag'
    if 'crypto' in kind:
        return '💎 CryptoBot'
    if kind.startswith(('payout','withdraw')):
        return '💸 Вывод средств'
    if kind.startswith('task'):
        return '📣 Задания'
    if kind.startswith('retention'):
        return '↩️ Возврат удержания'
    return '💰 Операция'


def farm_url():
    domain = os.environ.get('RAILWAY_PUBLIC_DOMAIN', 'farm-web-production-cfb9.up.railway.app')
    return 'https://' + domain + '/'

def cabinet(c, uid):
    a = account(c, uid)
    totals = c.execute("""SELECT
      (SELECT coalesce(sum(amount),0) FROM bot_payouts WHERE uid=%s AND status='pending') AS pending,
      (SELECT coalesce(sum(remaining),0) FROM bot_tasks WHERE owner=%s AND status IN ('pending','active')) AS frozen,
      (SELECT coalesce(sum(delta),0) FROM bot_ledger WHERE uid=%s AND kind='task_reward') AS earned,
      (SELECT coalesce(sum(delta),0) FROM bot_ledger WHERE uid=%s AND kind IN ('daily_bonus','friend_reward','referral_reward')) AS bonuses,
      (SELECT coalesce(sum(delta),0) FROM bot_ledger WHERE uid=%s AND kind IN ('manual_deposit','ads_manual_deposit','stars_wallet_deposit','cryptopay_deposit')) AS deposits,
      (SELECT coalesce(sum(coalesce(q.net,p.amount)),0) FROM bot_payouts p LEFT JOIN bot_payout_terms q ON q.id=p.id WHERE p.uid=%s AND p.status='paid') AS paid,
      (SELECT coalesce(sum(coalesce(q.cost,t.reward)),0) FROM bot_tasks t LEFT JOIN bot_task_terms q ON q.task=t.id JOIN bot_claims x ON x.task=t.id AND x.status='paid' WHERE t.owner=%s)
        -(SELECT coalesce(sum(delta),0) FROM bot_ledger WHERE uid=%s AND kind='retention_refund') AS spent,
      (SELECT coalesce(sum(amount),0) FROM bot_debts WHERE uid=%s) AS debt""", (uid,)*9).fetchone()
    pending,frozen,earned,bonuses,deposits,paid,spent,debt = (totals[k] for k in
        ('pending','frozen','earned','bonuses','deposits','paid','spent','debt'))
    state(c, uid, 'clear')
    debt_line = tr('\n⚠️ Задолженность: {v0}', {'v0': money(debt)}, html_mode=True, section='task_bot', limit=3000) if debt else ''
    text = tr('👤 <b>Мой кабинет</b>\n🆔 <code>{v0}</code>\n\n💰 <b>Доступно: {v1}</b>{v2}\n\n📊 <b>Движение средств</b>\n💳 Пополнений: {v3}\n📣 Потрачено на рекламу: {v4}\n✅ Заработано на заданиях: {v5}\n🎁 Бонусы и рефералы: {v6}\n\n📌 <b>Остальные средства</b>\n❄️ В бюджете заданий: {v7}\n⏳ Ожидает выплаты: {v8}\n💸 Выведено всего: {v9}', {'v0': f'{uid}', 'v1': f"{money(a['available'])}", 'v2': f'{debt_line}', 'v3': f'{money(deposits)}', 'v4': f'{money(spent)}', 'v5': f'{money(earned)}', 'v6': f'{money(bonuses)}', 'v7': f'{money(frozen)}', 'v8': f'{money(pending)}', 'v9': f'{money(paid)}'}, html_mode=True, section='task_bot', limit=3000)
    buttons = [
        [button('➕ Пополнить','deposit'),button('💸 Вывести','withdraw')],
        [button('✅ Выполнения','claims'),button('📥 Заявки','payouts')],
        [button('📋 Мои задания','mine:0'),button('📜 История','history')],
        [button('👥 Рефералы','friends'),button('🔄 Обновить','cabinet')],
    ]
    if bot_copy.owner():
        buttons.append([button('📱 Привязать номер','identity:share'),button('🛡 Админ-панель','admin')])
    else:
        buttons.append([button('📱 Привязать номер','identity:share')])
    return bot_visuals.attach(bot_ui.screen(uid, text, buttons), 'profile',
        uid=uid, name=a['name'], balance=int(a['available']), created=a['created'])

def resolve_chat(api, target, kind):
    if re.fullmatch('-\\d+', target):
        key = int(target)
    else:
        path = urlsplit(target if '://' in target else 'https://t.me/' + target.lstrip('@'))
        if path.scheme != 'https' or path.hostname not in ('t.me', 'telegram.me') or (not re.fullmatch('[A-Za-z][A-Za-z0-9_]{3,31}', path.path.strip('/'))):
            raise UserError(tr('Укажи публичную ссылку https://t.me/имя или числовой ID чата. Для закрытого чата сначала добавь нашего бота администратором.', html_mode=False, section='task_bot', limit=3000))
        key = '@' + path.path.strip('/')
    try:
        info = api('getChat', {'chat_id': key})
    except Exception:
        raise UserError('Канал не найден или недоступен. Проверь ссылку и добавь @Farmlife2026bot администратором.')
    types = ('channel',) if kind == 'channel' else ('group', 'supergroup')
    if info.get('type') not in types:
        raise UserError(tr('Тип чата не соответствует заданию.', html_mode=False, section='task_bot', limit=3000))
    me = api('getMe', {})
    try:
        own = api('getChatMember', {'chat_id': info['id'], 'user_id': me['id']})
    except Exception:
        raise UserError('Не удалось проверить права @Farmlife2026bot. Добавь нашего бота администратором канала.')
    if own.get('status') not in ('administrator', 'creator'):
        raise UserError(tr('Наш бот @Farmlife2026bot не является администратором канала или группы. Добавь его в администраторы и повтори.', html_mode=False, section='task_bot', limit=3000))
    link = 'https://t.me/' + info['username'] if info.get('username') else info.get('invite_link')
    if not link:
        raise UserError(tr('Не удалось получить ссылку на закрытый чат. Выдай боту право приглашать участников.', html_mode=False, section='task_bot', limit=3000))
    return (info['id'], link)

def bot_mode(c,tid):
    row=c.execute('SELECT mode FROM bot_task_bot_modes WHERE task=%s',(tid,)).fetchone()
    return row['mode'] if row else 'forward'

def bot_click_card(c,t,uid):
    if t['owner']==uid or t['status']!='active':raise UserError('Задание недоступно.')
    username=urlsplit(t['url']).path.strip('/').lower()
    if c.execute('SELECT 1 FROM bot_bot_click_completions WHERE uid=%s AND username=%s',(uid,username)).fetchone():
        raise UserError('Награда за переход к этому боту уже получена.')
    claim=c.execute('SELECT status FROM bot_claims WHERE task=%s AND uid=%s',(t['id'],uid)).fetchone()
    if claim and claim['status']!='started':raise UserError('Это задание уже завершено.')
    if not claim:
        c.execute("INSERT INTO bot_claims(task,uid,status,created) VALUES(%s,%s,'started',%s)",(t['id'],uid,time.time()))
    token=c.execute('SELECT token FROM bot_bot_click_tokens WHERE task=%s AND uid=%s',(t['id'],uid)).fetchone()
    if not token:
        secret=secrets.token_urlsafe(24)
        c.execute('INSERT INTO bot_bot_click_tokens(token,task,uid,created) VALUES(%s,%s,%s,%s)',(secret,t['id'],uid,time.time()))
        token={'token':secret}
    link=farm_url()+'api/task/bot-click/'+token['token']
    return bot_ui.screen(uid,'🤖 <b>Перейти в бота</b>\n\n🎁 Награда: <b>'+money(t['reward'])+'</b>\n\nОткрой бота, ознакомься с ним и вернись сюда для проверки.',
       [[{'text':'🚀 Открыть бота','url':link}],
        [button('✅ Проверить переход','botclick:check:'+t['id'])],
        [button('➡️ Дальше','botclick:skip:'+t['id'])],
        [button('⬅️ Заработать','earn')]])
def bot_click_feed(c,uid,message,after_id=None,success=''):
    """Single editable card for paid outbound bot-link clicks."""
    params=[uid,uid,uid,uid]
    condition=''
    if after_id:
        previous=c.execute("SELECT created,id FROM bot_tasks WHERE id=%s AND kind='bot'",(after_id,)).fetchone()
        if not previous:raise UserError('Задание не найдено.')
        condition=' AND (t.created,t.id)>(%s,%s)'
        params.extend([previous['created'],previous['id']])
    task=c.execute('SELECT t.* FROM bot_tasks t JOIN bot_task_bot_modes m ON m.task=t.id WHERE '+bot_ui.catalog_filter()+" AND t.kind='bot' AND m.mode='click'"+condition+' ORDER BY t.created,t.id LIMIT 1',tuple(params)).fetchone()
    if task:
        out=bot_click_card(c,task,uid)
        if success:out['text']=success+'\n\n'+out['text']
    else:
        out=bot_ui.screen(uid,(success+'\n\n' if success else '')+'🤖 <b>Пока больше нет заданий на переход в ботов.</b>',
            [[button('🔄 Сначала','botclick:feed')],[button('⬅️ Заработать','earn')]])
    if message.get('_callback_id') and isinstance(message.get('message_id'),int) and not (message.get('photo') or message.get('video') or message.get('animation') or message.get('document')):
        out['method']='editMessageText'
        out['message_id']=message['message_id']
    return out
def task_card(t, uid, c):
    if t['kind']=='manual':return bot_manual.task_card(c,t,uid)
    if t['kind']=='bot' and bot_mode(c,t['id'])=='click':return bot_click_card(c,t,uid)
    if t['kind'] == 'bot':
        return say(uid, tr('🤖 {v0}\n\n{v1}\n\nНаграда: {v2}\nВозьми задание, запусти бота и перешли сюда свежий ответ от него. Это проверка источника пересылки, не гарантия первого запуска. Не пересылай пароли и коды.', {'v0': f"{t['title']}", 'v1': f"{t['description']}", 'v2': f"{money(t['reward'])}"}, html_mode=False, section='task_bot', limit=3000), [[{'text': tr('Перейти к боту', html_mode=False, section='task_bot', limit=3000), 'url': t['url']}], [button('Взять / отправить пересылку', 'take:' + t['id'])], [button('Пропустить', 'skip_bot')]])
    return say(uid, tr('{v0}\n\n{v1}\n\nНаграда: {v2}{v3}', {'v0': f"{t['title']}", 'v1': f"{t['description']}", 'v2': f"{money(t['reward'])}", 'v3': bot_economy.rule_text(c, t)}, html_mode=False, section='task_bot', limit=3000), [[{'text': tr('Открыть', html_mode=False, section='task_bot', limit=3000), 'url': t['url']}], [button('Взять задание', 'take:' + t['id']), button('Проверить', 'check:' + t['id'])], [button('⬅️ Задания', 'earn')]])

def membership_feed(c,uid,message,kind='channel',after_id=None,success='',api=None):
    """One current membership task, with new-member eligibility snapshotted before opening."""
    if kind not in ('channel','group'):raise UserError('Неизвестный тип задания.')
    params=[uid,uid,uid]
    condition=''
    if after_id:
        prev=c.execute('SELECT created,id FROM bot_tasks WHERE id=%s AND kind=%s',(after_id,kind)).fetchone()
        if not prev:raise UserError('Задание не найдено.')
        condition=' AND (t.created,t.id)>(%s,%s)'
        params.extend([prev['created'],prev['id']])
    row=None
    for _ in range(40):
        row=c.execute('SELECT t.* FROM bot_tasks t WHERE '+bot_ui.catalog_filter()+' AND t.kind=%s'+condition+' ORDER BY t.created,t.id LIMIT 1',tuple(params[:3]+[uid,kind]+params[3:])).fetchone()
        if not row:break
        claim=c.execute('SELECT status FROM bot_claims WHERE task=%s AND uid=%s',(row['id'],uid)).fetchone()
        if claim and claim['status']=='started':break
        if api is None:raise UserError('Не удалось запустить проверку вступления.')
        try:
            me=api('getMe',{})
            rights=api('getChatMember', {'chat_id':row['chat_id'],'user_id':me['id']})
            if rights.get('status') not in ('administrator','creator'):
                raise UserError('Проверка недоступна: @Farmlife2026bot больше не является администратором канала/группы.')
            current=api('getChatMember', {'chat_id':row['chat_id'],'user_id':uid})
        except UserError:raise
        except Exception:
            raise UserError('Не удалось проверить участников. Убедись, что @Farmlife2026bot администратор этого чата.')
        if not member(current):
            c.execute("INSERT INTO bot_claims(task,uid,status,created) VALUES(%s,%s,'started',%s) ON CONFLICT DO NOTHING",(row['id'],uid,time.time()))
            break
        condition=' AND (t.created,t.id)>(%s,%s)'
        params=[uid,uid,uid,row['created'],row['id']]
        row=None
    prefix='channel' if kind=='channel' else 'group'
    if row:
        heading='📣 <b>Подписаться на канал</b>' if kind=='channel' else '👥 <b>Вступить в группу</b>'
        instruction='Открой канал, подпишись и вернись для проверки.' if kind=='channel' else 'Открой группу, вступи и вернись для проверки.'
        body=(success+'\n\n' if success else '')+heading+'\n\n🎁 Награда: <b>'+money(row['reward'])+'</b>\n\n'+instruction
        rules=bot_economy.rule_text(c,row).replace('Нажимая «Взять задание»','Нажимая «Проверить подписку»' if kind=='channel' else 'Нажимая «Проверить вступление»')
        body+=rules
        buttons=[[{'text':'📣 Открыть канал' if kind=='channel' else '👥 Открыть группу','url':row['url']}],
                 [button('✅ Проверить подписку' if kind=='channel' else '✅ Проверить вступление',prefix+':check:'+row['id'])],
                 [button('➡️ Дальше',prefix+':skip:'+row['id'])],[button('⬅️ Заработать','earn')]]
    else:
        label='подписку' if kind=='channel' else 'вступление в группы'
        body=(success+'\n\n' if success else '')+'📭 <b>Пока больше нет заданий на '+label+'.</b>'
        buttons=[[button('🔄 Сначала',prefix+':feed')],[button('⬅️ Заработать','earn')]]
    out=bot_ui.screen(uid,body,buttons)
    if message.get('_callback_id') and isinstance(message.get('message_id'),int) and not (message.get('photo') or message.get('video') or message.get('animation') or message.get('document')):
        out['method']='editMessageText'
        out['message_id']=message['message_id']
    return out

def channel_feed(c,uid,message,after_id=None,success='',api=None):
    return membership_feed(c,uid,message,'channel',after_id,success,api)
def can_close_order(c,t):
    if t['kind']=='post' and c.execute("SELECT 1 FROM bot_post_publications WHERE task=%s AND status IN ('sending','uncertain')",(t['id'],)).fetchone():
        raise UserError('Сначала нужно проверить результат публикации поста.')
    if c.execute("SELECT 1 FROM bot_claims WHERE task=%s AND status='review'",(t['id'],)).fetchone():
        raise UserError('Сначала проверь присланные работы.')

def close_order(c,t):
    can_close_order(c,t)
    row=c.execute("UPDATE bot_tasks SET status='closed',remaining=0 WHERE id=%s AND status IN ('pending','active') RETURNING id",(t['id'],)).fetchone()
    if not row:raise UserError('Задание уже закрыто.')
    refund=t['remaining']
    if refund:change(c,t['owner'],refund,'task_close','Закрытие задания '+t['id'])
    return refund

def award(c, t, uid):
    bot_moderation.available(c,t['id'])
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

_callback_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='telegram-ack')
_callback_slots = threading.BoundedSemaphore(16)


def acknowledge_later(api, callback_id):
    """Acknowledgement is UI feedback; a slow Telegram call must not hold a command."""
    if not _callback_slots.acquire(blocking=False):
        return
    def send():
        try:
            api('answerCallbackQuery', {'callback_query_id':callback_id})
        except Exception:
            log.warning('task_bot_background_callback_ack_failed')
        finally:
            _callback_slots.release()
    try:
        _callback_pool.submit(send)
    except RuntimeError:
        _callback_slots.release()


def handle(payload, db, api, is_admin, deliver_posts_inline=True):
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
    if callback.get('id'):
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
    started = time.perf_counter()
    admin = is_admin(uid, uid)
    identity_ms = (time.perf_counter()-started)*1000
    # Acknowledge ordinary inline buttons before waiting for the global
    # accounting lock. Post-claim buttons retain their result-specific popup.
    callback_acked = False
    if callback.get('id') and not channel_claim:
        if not deliver_posts_inline:
            acknowledge_later(api, callback['id'])
            callback_acked = True
        else:
            try:
                api('answerCallbackQuery', {'callback_query_id': callback['id']})
                callback_acked = True
            except Exception:
                log.warning('task_bot_callback_early_ack_failed')
    try:
        with db() as c:
            c.execute('SELECT pg_advisory_xact_lock(1984533)')
            c.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK,))
            locked_ms = (time.perf_counter()-started)*1000
            old = c.execute('SELECT response FROM bot_receipts WHERE event=%s', (event,)).fetchone()
            if not admin and (action.startswith('bot:admin') or cmd.startswith('/bot') or cmd.startswith('/bonus')):
                return say(uid,'Доступ только администратору.')
            if old:
                cached=dict(old['response'])
                required=cached.pop('_requires_admin',False)
                if required and not admin:return say(uid,'Доступ только администратору.')
                return cached
            if channel_claim and (not account(c, uid)):
                return {'method': 'answerCallbackQuery', 'callback_query_id': callback['id'], 'text': tr('Сначала открой @Farmlife2026bot и нажми /start, затем вернись к посту.', html_mode=False, section='task_bot', limit=3000), 'show_alert': True}
            text = bot_copy.canonical_menu(c, text)
            is_new = not c.execute('SELECT 1 FROM bot_accounts WHERE uid=%s', (uid,)).fetchone()
            sync_referrals = is_new or cmd == '/start'
            ref = None
            if text.startswith('/start partner_'):
                raw = text.split('partner_', 1)[1]
                if raw.isdecimal() and len(raw) <= 19 and (0 < int(raw) <= 9223372036854775807) and (int(raw) != uid):
                    ref = c.execute('SELECT uid FROM bot_accounts WHERE uid=%s', (int(raw),)).fetchone()
            # A pre-existing game inviter takes precedence over a new bot link.
            game_ref=c.execute('SELECT p.telegram_id AS uid FROM referrals r JOIN players ch ON ch.id=r.child_id JOIN players p ON p.id=r.parent_id WHERE ch.telegram_id=%s',(uid,)).fetchone() if sync_referrals else None
            if game_ref:ref=game_ref if game_ref['uid'] else None
            if game_ref and game_ref['uid']:
                ref=game_ref
                c.execute('INSERT INTO bot_accounts(uid,name,created) VALUES(%s,%s,%s) ON CONFLICT(uid) DO NOTHING',(ref['uid'],'Игрок',time.time()))
            if ref and not referral_bridge.acyclic(c,uid,ref['uid']):ref=None
            c.execute('INSERT INTO bot_accounts(uid,name,referrer,created) VALUES(%s,%s,%s,%s)\n              ON CONFLICT(uid) DO UPDATE SET name=EXCLUDED.name', (uid, str(sender.get('first_name') or 'Игрок')[:100], ref['uid'] if ref else None, time.time()))
            bot_identity.record(c,uid,sender,message if not callback else None)
            if sync_referrals:
                referral_bridge.sync(c, uid)
            unify_balances(c, uid)
            prepared_ms = (time.perf_counter()-started)*1000
            message = dict(message, _new_referral=bool(is_new and ref and text.startswith('/start partner_')))
            with bot_copy.session(c, admin):
                copy_ms = (time.perf_counter()-started)*1000
                try:
                    with c.transaction():
                        response = route(c, uid, text, action[4:] if callback else '', message, api, admin)
                        response = bot_visuals.decorate(response, text, action[4:] if callback else '')
                except UserError as error:
                    response = {'method': 'answerCallbackQuery', 'callback_query_id': callback['id'], 'text': str(error)[:200], 'show_alert': True} if channel_claim else input_prompt(uid, str(error)) if state(c, uid) else say(uid, str(error))
                routed_ms = (time.perf_counter()-started)*1000
                if '_visual' in response:
                    if not deliver_posts_inline:
                        # Persist once with the existing event receipt, then render off webhook.
                        media = dict(response)
                        if callback and message.get('photo') and isinstance(message.get('message_id'), int):
                            media['_visual'] = dict(media['_visual'], edit_message_id=message['message_id'])
                        ready = bot_visuals.ready_response(media)
                        if ready is not None:
                            response = ready
                        else:
                            c.execute("INSERT INTO bot_notifications(id,recipient,subject,kind,payload,created) VALUES(%s,%s,%s,'visual',%s,%s) ON CONFLICT DO NOTHING",
                                      ('visual:'+event, uid, uid, Jsonb(media), time.time()))
                            response = {'ok': True}
                    else:
                        response = dict(response)
                        response.pop('_visual', None)
                c.execute('INSERT INTO bot_receipts VALUES(%s,%s,%s)', (event, Jsonb(dict(response,_requires_admin=admin)), time.time()))
    except Exception:
        log.exception('task_bot_update_failed')
        raise
    bot_notifications.wake()
    elapsed_ms = (time.perf_counter()-started)*1000
    if elapsed_ms>500:
        log.warning('task_bot_slow_update action=%s elapsed_ms=%.0f identity_ms=%.0f locked_ms=%.0f prepare_ms=%.0f copy_ms=%.0f route_ms=%.0f commit_ms=%.0f',
                    action.removeprefix('bot:').split(':')[0] or cmd or 'menu',
                    elapsed_ms,identity_ms,locked_ms,prepared_ms-locked_ms,copy_ms-prepared_ms,routed_ms-copy_ms,elapsed_ms-routed_ms)
    # Production uses a background worker; direct library callers retain synchronous outbox behavior.
    if deliver_posts_inline:
        bot_extras.deliver_posts(db, api)
    if callback.get('id') and not callback_acked and response.get('method') != 'answerCallbackQuery':
        try:
            api('answerCallbackQuery', {'callback_query_id': callback['id']})
        except Exception:
            log.warning('task_bot_callback_ack_failed')
    return response

def route(c, uid, text, action, message, api, admin):
    cmd = text.split(maxsplit=1)[0].split('@')[0] if text else ''
    # Enforce hidden public buttons even when an older Telegram message is
    # tapped, while still allowing all payment webhooks to settle above.
    feature=bot_visibility.key_for_action(action) if action else bot_visibility.MENU_KEYS.get(text)
    if feature and not bot_visibility.enabled(c,feature):
        return say(uid,'Этот раздел сейчас скрыт владельцем.')
    if cmd == '/menu':
        state(c,uid,'clear')
        return say(uid,'🏠 Главное меню восстановлено. Выбирай раздел ниже 👇')
    if cmd=='/farm':
        return say(uid,'🌾 Открой свою ферму и развивай хозяйство!',[[{'text':'🌾 Играть в ферму','web_app':{'url':farm_url()}}]])
    if cmd=='/profile':
        return cabinet(c,uid)
    if cmd=='/friends':
        return bot_ui.partners(c,uid)
    if cmd=='/adincome' or action=='ad_income':
        if not admin:
            return say(uid,'Этот раздел доступен только администратору.')
        earnings=bot_monetag_cash.estimated_earnings(c,uid)
        price=lambda x:'$'+format(x,'.9f')
        sumrow=c.execute("SELECT COALESCE(SUM(credited_kopeks),0) AS n FROM bot_cash_ad_credits WHERE uid=%s",(uid,)).fetchone()
        adsgram_credits=c.execute("SELECT COALESCE(SUM(reward_kopeks),0) AS n FROM bot_adsgram_immediate_rewards WHERE uid=%s",(uid,)).fetchone()
        adsgram_legacy=c.execute("SELECT COALESCE(SUM(credited_kopeks),0) AS n FROM bot_adsgram_daily_credits WHERE uid=%s",(uid,)).fetchone()
        adsgram_intervals=c.execute("SELECT COALESCE(SUM(credited_kopeks),0) AS n FROM bot_adsgram_interval_credits WHERE uid=%s",(uid,)).fetchone()
        adsgram_confirmed=c.execute("SELECT COUNT(*) AS n FROM bot_adsgram_attempts WHERE uid=%s AND state='confirmed'",(uid,)).fetchone()
        a=c.execute("SELECT available FROM bot_accounts WHERE uid=%s",(uid,)).fetchone()
        lines=['💵 <b>Мой рекламный доход</b>',
               '💰 Monetag зачислено: <b>'+money(int(sumrow['n']))+'</b>',
               '🎬 AdsGram подтверждено: '+str(adsgram_confirmed['n'])+' просмотров',
               '💰 AdsGram начислено: <b>'+money(int(adsgram_credits['n'])+int(adsgram_legacy['n'])+int(adsgram_intervals['n']))+'</b>',
               '💳 Доступный баланс: <b>'+money(a['available'] if a else 0)+'</b>', '',
               '👀 За свои просмотры (USD): '+price(earnings['viewer']),
               '🤝 От рефералов (USD): '+price(earnings['referral']),
               '📊 Всего оценка: '+price(earnings['total']), '',
               '🌱 <b>Реферальные уровни</b>']
        for index,amount in enumerate(earnings['levels'],1):
            lines.append(str(index)+' уровень: '+price(amount))
        lines.append('💡 AdsGram: '+money(bot_admin.adsgram_view_reward(c))+' за подтверждённый просмотр начисляется сразу. /reklama фиксирует реальный доход сети для сверки и не начисляет награды повторно. Monetag: оценка в USD не является подтверждённой выплатой.')
        return bot_ui.screen(uid,'\n'.join(lines),[[{'text':'🎬 Смотреть рекламу','web_app':{'url':farm_url()+'cash-ads-preview.html'}}],[button('🤝 Моя команда','friends')],[button('⬅️ Кабинет','cabinet')]])
    if cmd.startswith('/bonus'):
        return bot_promos.command(c,uid,text,admin)
    if text=='/start farmdeposit':
        return bot_topups.start_farm_card(c,uid)
    if admin and cmd=='/start' and text not in ('/start wallet','/start support') and not text.startswith('/start link_'):
        return bot_admin.panel(c,uid)
    if action.startswith('admin') or cmd.startswith('/bot') or cmd in ('/adsgramurl','/adsgramsettle','/reklama'):
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
    manual=bot_manual.route(c,uid,action,admin)
    if manual is not None:return manual
    if action=='identity:share':
        return {'method':'sendMessage','chat_id':uid,'text':'По желанию отправь свой номер телефона кнопкой ниже. Он будет доступен администратору для поиска твоего аккаунта.',
          'reply_markup':{'keyboard':[[{'text':'📱 Поделиться своим номером','request_contact':True,'style':'primary'}],[{'text':'👤 Мой кабинет','style':'primary'}]],'resize_keyboard':True,'one_time_keyboard':True}}
    if message.get('contact'):
        contact=message['contact']
        if contact.get('user_id')!=uid or not bot_identity.phone(contact.get('phone_number')):
            return say(uid,'Можно привязать только свой номер через кнопку «Поделиться своим номером».')
        return say(uid,'Номер сохранён. Администратор сможет найти твой аккаунт по нему.',[[button('⬅️ Мой кабинет','cabinet')]])
    if action.startswith('payout_public:'):
        current=state(c,uid)
        if not current or current['state']!='payout_confirm' or action.split(':')[-1]!=current['data'].get('nonce'):
            raise UserError('Подтверждение заявки устарело.')
        data=current['data']
        data['public_profile']=not data.get('public_profile',True)
        state(c,uid,'payout_confirm',data)
        label='Да' if data['public_profile'] else 'Нет'
        return bot_ui.screen(uid, '👤 <b>Показывать профиль в канале выплат: '+label+'</b>\n\n'
            'Если включено и канал публикует выплаты, другие смогут открыть твой Telegram-профиль.',
            [[button('👤 Аккаунт в канале: '+label, 'payout_public:'+data['nonce'])],
             [button('✅ Вывести', 'confirm_payout:'+data['nonce'])],
             [button('✖️ Отмена','cancel_input')]])
    if action.startswith(('confirm_task:', 'confirm_payout:')):
        return confirmation(c, uid, action, api)
    if text in sum(MENU, []) or cmd in ('/start', '/help', '/menu', '/cancel'):
        state(c, uid, 'clear')
    if action == 'watch_ads_info':
        # Old inline buttons still send this callback; do not gate ads behind VIP.
        return bot_ui.screen(uid,'🎬 <b>Смотреть рекламу AdsGram</b>\n\nПросмотр открыт всем пользователям. Награда учитывается после подтверждения сети.',[[{'text':'🎬 Смотреть рекламу','web_app':{'url':farm_url()+'cash-ads-preview.html'}}],[button('⬅️ Заработать','earn')]])

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
    if action == 'history' or action.startswith('history:page:'):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        page=0
        if action.startswith('history:page:'):
            raw=action.rsplit(':',1)[-1]
            if not raw.isdecimal() or len(raw)>4:
                raise UserError('Неверная страница истории.')
            page=min(int(raw),999)
        limit=10
        rows=c.execute("""SELECT id,delta,kind,created FROM bot_ledger
          WHERE uid=%s AND delta<>0 ORDER BY created DESC,id DESC LIMIT %s OFFSET %s""",
          (uid,limit+1,page*limit)).fetchall()
        buttons=[]
        for item in rows[:limit]:
            kind=str(item['kind'])
            label=ledger_label(kind)
            when=datetime.fromtimestamp(item['created'],ZoneInfo('Europe/Kyiv')).strftime('%d.%m %H:%M')
            prefix='+' if item['delta']>0 else '−'
            buttons.append([button(prefix+money(abs(item['delta']))+' · '+label+' · '+when,
                'history:detail:'+item['id'])])
        nav=[]
        if page:nav.append(button('⬅️ Ранее','history:page:'+str(page-1)))
        if len(rows)>limit:nav.append(button('Далее ➡️','history:page:'+str(page+1)))
        if nav:buttons.append(nav)
        buttons.append([button('⬅️ Кабинет','cabinet')])
        return bot_ui.screen(uid,'📜 <b>История баланса</b>\n\n'
            'Нажми на операцию, чтобы посмотреть подробности.\n'
            'Страница '+str(page+1) if rows or page==0 else '📜 <b>История баланса</b>\n\nБольше операций нет.',
            buttons)
    if action.startswith('history:detail:'):
        txid=action.rsplit(':',1)[-1]
        if not re.fullmatch(r'[a-f0-9]{32}',txid):
            raise UserError('Операция не найдена.')
        item=c.execute('SELECT id,delta,kind,details,created FROM bot_ledger WHERE uid=%s AND id=%s',
            (uid,txid)).fetchone()
        if not item or item['delta']==0:
            raise UserError('Операция не найдена.')
        from datetime import datetime
        from zoneinfo import ZoneInfo
        date=datetime.fromtimestamp(item['created'],ZoneInfo('Europe/Kyiv')).strftime('%d.%m.%Y %H:%M')
        label=ledger_label(str(item['kind']))
        prefix='+' if item['delta']>0 else '−'
        lines=['🧾 <b>Операция баланса</b>','',
            '<b>'+bot_ui.esc(label)+'</b>',
            'Сумма: <b>'+prefix+money(abs(item['delta']))+'</b>',
            'Дата: '+date,
            'ID: <code>'+bot_ui.esc(item['id'])+'</code>']
        # Free-form ledger descriptions are internal data. Show plain user-safe
        # descriptions only, never payment tokens, URLs, PINs or full card IDs.
        detail=str(item['details'] or '').strip()
        if (detail and len(detail)<=150 and
                not re.search(r'https?://|t\.me/|(?:[0-9]{12,}|[a-f0-9]{24,})|(?:token|secret|password|api[_ -]?key)',detail,re.I)
                and not any(ord(ch)<32 and ch not in '\n\t' for ch in detail)):
            lines.append('Описание: '+bot_ui.esc(detail))
        return bot_ui.screen(uid,'\n'.join(lines),
            [[button('⬅️ История баланса','history')],[button('👤 Кабинет','cabinet')]])
    if action == 'claims':
        rows = c.execute('SELECT t.title,x.status FROM bot_claims x JOIN bot_tasks t ON t.id=x.task\n          WHERE x.uid=%s ORDER BY x.created DESC LIMIT 15', (uid,)).fetchall()
        labels = {'started': tr('В работе', html_mode=False, section='task_bot', limit=3000), 'review': tr('На проверке', html_mode=False, section='task_bot', limit=3000), 'paid': tr('Оплачено', html_mode=False, section='task_bot', limit=3000), 'rejected': tr('Отклонено', html_mode=False, section='task_bot', limit=3000)}
        return say(uid, tr('✅ Мои выполнения\n{v0}', {'v0': '\n'.join((r['title'] + ' · ' + labels.get(r['status'], r['status']) for r in rows)) or 'Пока нет взятых заданий.'}, html_mode=False, section='task_bot', limit=3000))
    if action.startswith('payout:detail:'):
        pid=action.split(':')[-1]
        row=c.execute("""SELECT p.*,ch.check_id,ch.check_url,ch.state AS check_state,cp.crypto_amount,
                   h.payout_id AS liquidity_hold
            FROM bot_payouts p
            LEFT JOIN bot_crypto_checks ch ON ch.payout_id=p.id
            LEFT JOIN bot_crypto_payouts cp ON cp.payout_id=p.id
            LEFT JOIN bot_crypto_liquidity_wait h ON h.payout_id=p.id
            WHERE p.id=%s AND p.uid=%s""",(pid,uid)).fetchone()
        if not row:
            raise UserError('Выплата не найдена.')
        from datetime import datetime
        from zoneinfo import ZoneInfo
        when=datetime.fromtimestamp(row['created'],ZoneInfo('Europe/Kyiv')).strftime('%d.%m.%Y %H:%M')
        status={'pending':'⏳ Обрабатывается','paid':'✅ Выплачено',
            'cancelled':'↩️ Отменено','rejected':'❌ Отклонено'}.get(row['status'],'На проверке')
        if row['liquidity_hold']:
            status='⏳ Дополнительная проверка · пополнение резерва'
        elif row['check_state']=='active' and row['status']=='pending':
            status='🎁 Чек готов · ожидает активации'
        elif row['check_state']=='review' and row['status']=='pending':
            status='⏳ Дополнительная проверка · CryptoBot пока не подтвердил чек'
        lines=['💸 <b>Выплата</b>','ID: <code>'+bot_ui.esc(pid)+'</code>',
            'Списано: '+money(row['amount']),
            'Статус: '+status,'Дата: '+when]
        if row['crypto_amount'] is not None:
            lines.append('CryptoBot: '+bot_ui.esc(row['crypto_amount'])+' USDT')
        if row['check_id'] is not None:
            lines.append('Чек №'+str(row['check_id']))
        rows=[]
        if row['check_state']=='active' and row['status']=='pending' and row['check_url']:
            url=row['check_url']
            if url.startswith('https://t.me/'):
                rows.append([{'text':'🎁 Открыть мой чек CryptoBot','url':url}])
        rows.append([button('🔄 Обновить','payout:detail:'+pid)])
        rows.append([button('⬅️ Мои выплаты','payouts')])
        return bot_ui.screen(uid,'\n'.join(lines),rows)
    if action == 'payouts':
        rows=c.execute("""SELECT p.id,p.amount,p.status,ch.state AS check_state,
                   cp.state AS crypto_state,h.payout_id AS liquidity_hold FROM bot_payouts p
            LEFT JOIN bot_crypto_checks ch ON ch.payout_id=p.id
            LEFT JOIN bot_crypto_payouts cp ON cp.payout_id=p.id
            LEFT JOIN bot_crypto_liquidity_wait h ON h.payout_id=p.id
            WHERE p.uid=%s ORDER BY p.created DESC LIMIT 10""",(uid,)).fetchall()
        labels={'pending':'⏳ Ожидает','paid':'✅ Выплачено',
            'rejected':'❌ Отклонено','cancelled':'↩️ Отменено'}
        buttons=[]
        for r in rows:
            label='🎁 Чек готов' if r['check_state']=='active' and r['status']=='pending' else labels.get(r['status'],'⏳ Проверка')
            if r['liquidity_hold']:
                label='⏳ Дополнительная проверка'
            elif r['check_state']=='review' and r['status']=='pending':
                label='⏳ Дополнительная проверка'
            elif r['status']=='pending' and r['crypto_state']=='review' and r['check_state'] is None:
                label='⏳ Дополнительная проверка'
            elif r['status']=='pending' and r['crypto_state'] is not None:
                label='⏳ Автовыплата'
            buttons.append([button(label+' · '+money(r['amount'])+' · '+r['id'][:8],
                'payout:detail:'+r['id'])])
        buttons += [[button('⬅️ Кабинет','cabinet')]]
        if any(r['status']=='pending' and r['crypto_state'] is None for r in rows):
            buttons.insert(-1,[button('Отменить заявку на карту','cancelpayout')])
        working=c.execute("""SELECT count(*) AS n FROM bot_payout_work w
            JOIN bot_payouts p ON p.id=w.id
            WHERE p.uid=%s AND p.status='pending' AND w.phase='working'""",(uid,)).fetchone()['n']
        note=('\n🏦 В работе: '+str(working)) if working else ''
        return bot_ui.screen(uid,'📥 <b>История выплат</b>'+note+
            '\nНажми на операцию, чтобы посмотреть подробности или снова открыть свой чек.',buttons)
    if action == 'cancelpayout':
        row = c.execute("UPDATE bot_payouts SET status='cancelled' WHERE uid=%s AND status='pending' AND NOT EXISTS(SELECT 1 FROM bot_payout_work w WHERE w.id=bot_payouts.id AND w.phase='working') AND NOT EXISTS(SELECT 1 FROM bot_crypto_payouts cp WHERE cp.payout_id=bot_payouts.id) RETURNING amount,id", (uid,)).fetchone()
        if not row:
            raise UserError(tr('Нет заявки, доступной для отмены. Выплату в работе отменить нельзя.', html_mode=False, section='task_bot', limit=3000))
        change(c, uid, row['amount'], 'payout_cancel', 'Отмена ' + row['id'][:8])
        return cabinet(c, uid)
    if action == 'withdraw:card':
        if not bot_admin.method_enabled(c,'card_withdraw'):
            raise UserError('Вывод на карту сейчас отключён администратором.')
        current=state(c,uid)
        if not current or current['state']!='withdraw_method':
            raise UserError('Сначала выбери сумму вывода.')
        data=current['data']
        data['method']='card'
        state(c,uid,'destination',data)
        return input_prompt(uid,'💳 Введи номер банковской карты — ровно 16 цифр.\n\nНикаких CVV, PIN или срока действия карты.',cancel_action='cancel_input')
    if action == 'withdraw:crypto':
        if not bot_admin.method_enabled(c,'crypto_withdraw'):
            raise UserError('Вывод через Crypto Bot выключен владельцем.')
        if not bot_crypto_pay.withdrawals_enabled() or bot_crypto_pay.payout_cap(c)<=0:
            return bot_ui.screen(uid,'💎 <b>Crypto Bot: вывод временно недоступен</b>\n\n'
              'Пополнение работает отдельно. Чтобы включить реальные выплаты USDT, '
              'владелец должен разрешить переводы в Crypto Pay и активировать '
              'CRYPTOPAY_AUTO_PAYOUTS_ENABLED в Railway после проверки безопасности.',
              [[button('⬅️ К способам вывода','withdraw:back'),button('Отмена','cancel_input')]])
        current=state(c,uid)
        if not current or current['state']!='withdraw_method':
            raise UserError('Сначала выбери сумму вывода.')
        if not bot_crypto_pay.withdrawals_enabled():
            return say(uid,'💎 Автоматический вывод через Crypto Bot пока отключён. Владелец должен подключить API, включить переводы и установить лимит.',[[button('⬅️ Выбрать способ','withdraw:back')]])
        data=current['data']
        try:
            usdt=bot_crypto_pay.quote_usdt(data['net'],c)
        except bot_crypto_pay.CryptoPayError as exc:
            return bot_ui.screen(uid,'💎 <b>Вывод через CryptoBot</b>\n\n'+bot_ui.esc(str(exc)),
                [[button('⬅️ Другой способ','withdraw:back'),button('✖️ Отмена','cancel_input')]])
        data['method']='crypto'
        data['destination']='Crypto Bot · USDT на Telegram ID '+str(uid)
        data['crypto_usdt']=usdt
        data['crypto_quote_at']=time.time()
        data['nonce']=uuid.uuid4().hex[:12]
        # The user sees and can turn off profile sharing before confirming.
        data['public_profile']=True
        state(c,uid,'payout_confirm',data)
        return bot_ui.screen(uid,
            '💎 <b>Вывод через CryptoBot</b>\n\n'
            'С баланса: <b>'+money(data['amount'])+'</b>\n'
            'К получению: <b>'+usdt+' USDT</b>\n'
            'Способ: 🎁 именной чек\n\n'
            'Пришлём кнопку «🎁 Забрать чек» прямо в чат.\n\n'
            '👤 <b>Показывать профиль в канале выплат: Да</b>\n'
            '<i>По ссылке из публичного объявления другие смогут открыть твой Telegram. '
            'Можешь отключить до подтверждения.</i>',
            [[button('👤 Показывать профиль: Да','payout_public:'+data['nonce'])],
             [button('✅ Вывести','confirm_payout:'+data['nonce'])],
             [button('✖️ Отмена','cancel_input')]])
    if action == 'withdraw:back':
        current=state(c,uid)
        if not current or current['state']!='withdraw_method':
            return cabinet(c,uid)
        return say(uid,'Выбери способ получения:',withdrawal_method_rows(c))
    if action == 'withdraw':
        bot_account_controls.require_withdrawal(c,uid)
        state(c, uid, action)
        rules = bot_admin.limits(c)
        return input_prompt(uid, tr('💸 Вывод средств\n\nС баланса: от {v0} до {v1}\nКомиссия: {v2}%\n\nВведи сумму в гривнах. Затем выберешь банковскую карту или Crypto Bot.', {'v0': money(rules['withdraw_min']), 'v1': money(rules['withdraw_max']), 'v2': bot_economy.pct(rules['withdraw_fee'])}, section='task_bot'))
    if action in ('channel:feed','group:feed'):
        kind=action.split(':')[0]
        return membership_feed(c,uid,message,kind=kind,api=api)
    if action.startswith(('channel:','group:')):
        parts=action.split(':')
        if len(parts)!=3 or parts[1] not in ('take','check','skip'):
            raise UserError('Неизвестное действие с подпиской.')
        kind,op,tid=parts
        item=c.execute('SELECT kind FROM bot_tasks WHERE id=%s',(tid,)).fetchone()
        if not item or item['kind']!=kind:raise UserError('Задание на подписку или группу не найдено.')
        if op=='skip':return membership_feed(c,uid,message,kind,after_id=tid,api=api)
        if op=='check' and bot_economy.terms(c,tid):
            c.execute('INSERT INTO bot_membership_accept VALUES(%s,%s,%s) ON CONFLICT DO NOTHING',(tid,uid,time.time()))
        route(c,uid,'',op+':'+tid,message,api,admin)
        if op=='take':return membership_feed(c,uid,message,kind,api=api)
        good='✅ Подписка подтверждена, награда начислена!' if kind=='channel' else '✅ Вступление подтверждено, награда начислена!'
        return membership_feed(c,uid,message,kind,after_id=tid,success=good,api=api)
    if action=='botclick:feed':
        return bot_click_feed(c,uid,message)
    if action.startswith('botclick:skip:'):
        return bot_click_feed(c,uid,message,after_id=action.split(':')[-1])
    if action.startswith('botclick:check:'):
        tid=action.split(':')[-1]
        t=c.execute('SELECT * FROM bot_tasks WHERE id=%s FOR UPDATE',(tid,)).fetchone()
        if not t or t['kind']!='bot' or bot_mode(c,tid)!='click':raise UserError('Задание не найдено.')
        if t['owner']==uid or t['status']!='active' or t['remaining']<bot_economy.cost(c,t):
            raise UserError('Задание недоступно или места закончились.')
        record=c.execute('SELECT visited FROM bot_bot_click_tokens WHERE task=%s AND uid=%s',(tid,uid)).fetchone()
        if not record or not record['visited']:
            raise UserError('Переход ещё не зарегистрирован. Сначала нажми «Открыть бота».')
        name=urlsplit(t['url']).path.strip('/').lower()
        row=c.execute('INSERT INTO bot_bot_click_completions(uid,username,task,created) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING uid',(uid,name,tid,time.time())).fetchone()
        if not row:raise UserError('За переход к этому боту награда уже начислялась.')
        award(c,t,uid)
        return bot_click_feed(c,uid,message,after_id=tid,success='✅ Переход подтверждён. Начислено '+money(t['reward'])+'.')
    if action.startswith('new:'):
        kind = action.split(':')[1]
        if kind not in KINDS:
            raise UserError(tr('Неизвестный тип задания.', html_mode=False, section='task_bot', limit=3000))
        if kind=='manual':return bot_manual.begin(c,uid)
        if kind == 'post' and (not bot_extras.settings(c)['channel_id']):
            raise UserError(tr('Канал рекламных постов ещё не подключён администратором.', html_mode=False, section='task_bot', limit=3000))
        state(c, uid, 'task_url' if kind in ('channel','group','bot') else 'task_title', {'kind': kind})
        if kind=='bot':
            return input_prompt(uid,'🤖 Пришли ссылку на Telegram-бота (HTTPS, t.me).\n\nАдрес должен начинаться с https://t.me/ и содержать имя твоего бота.\n\nПроверка задания подтверждает переход по ссылке, а не запуск или регистрацию.')
        if kind in ('channel','group'):
            label='📣 Пришли ссылку на канал' if kind=='channel' else '👥 Пришли ссылку на группу'
            return input_prompt(uid,label+' (https://t.me/имя).\n\nСначала добавь @Farmlife2026bot администратором, чтобы мы могли проверять участников.')
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
            rows = c.execute('SELECT t.* FROM bot_tasks t WHERE ' + bot_ui.catalog_filter() + ' AND t.kind=%s ORDER BY t.created LIMIT 8 OFFSET %s', (uid, uid, uid, uid, kind, offset)).fetchall()
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
                # Older paid channel/group orders can self-activate on owner review.
                if t['status']=='pending' and t['kind'] in ('channel','group'):
                    me=api('getMe', {})
                    rights=api('getChatMember', {'chat_id':t['chat_id'],'user_id':me['id']})
                    if rights.get('status') not in ('administrator','creator'):
                        raise UserError('Наш бот @Farmlife2026bot не является администратором канала/группы. Добавь его и открой заказ ещё раз.')
                    c.execute("UPDATE bot_tasks SET status='active' WHERE id=%s AND status='pending'",(t['id'],))
                    t=c.execute('SELECT * FROM bot_tasks WHERE id=%s',(t['id'],)).fetchone()
                return bot_advertising.card(c,t)
            if op == 'close':
                refund = close_order(c,t)
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
        bot_moderation.available(c,t['id'])
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
        if op == 'take' and t['kind']=='bot' and bot_mode(c,t['id'])=='click':
            return bot_click_card(c,t,uid)
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
        if current['state'] in ('topup_stars', 'topup_card_amount', 'topup_card_receipt', 'topup_crypto_amount'):
            feature={'topup_stars':'stars','topup_card_amount':'card_topup',
                     'topup_crypto_amount':'crypto_topup'}.get(current['state'])
            if feature and not bot_visibility.enabled(c,feature):
                state(c,uid,'clear')
                return bot_ui.screen(uid,'Этот способ пополнения сейчас скрыт. Новые платежи не создаются.',
                    [[button('⬅️ Пополнение','deposit')]])
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
    if current['data'].get('kind')=='manual':
        if current['state'].startswith('manual_') or (current['state']=='task_confirm' and current['data'].get('draft')):
            return bot_manual.input_text(c,uid,text,message,current)
        if current['state'].startswith('task_') and current['state']!='task_confirm':
            return bot_manual.begin(c,uid)
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
    if stage in ('withdraw','withdraw_method','destination','payout_confirm'):
        bot_account_controls.require_withdrawal(c,uid)
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
        state(c, uid, 'withdraw_method', {'amount': n, 'fee': fee, 'net': n - fee})
        return bot_ui.screen(uid, '💸 <b>Вывод '+money(n-fee)+'</b>\n\nВыбери способ получения:', withdrawal_method_rows(c))
    if stage == 'withdraw_method':
        # Backward compatibility for existing in-flight forms and legacy IBAN clients.
        # Selecting the bank-card button uses strict sixteen-digit validation instead.
        raise UserError('Сначала выбери способ вывода кнопкой: «Банковской картой» или «Crypto Bot».')
    if stage == 'destination':
        if data.get('method')=='card' and not bot_admin.method_enabled(c,'card_withdraw'):
            raise UserError('Вывод на карту сейчас отключён. Новую заявку создать нельзя.')
        if data.get('method')=='card':
            if not re.fullmatch(r'[0-9]{16}',text):
                raise UserError('💳 Введи ровно 16 цифр номера карты, без пробелов и других символов.')
        elif not 8 <= len(text) <= 250:
            raise UserError(tr('Реквизиты должны содержать от 8 до 250 символов.', html_mode=False, section='task_bot', limit=3000))
        data['destination'] = text
        data['nonce'] = uuid.uuid4().hex[:12]
        data['public_profile'] = True
        state(c, uid, 'payout_confirm', data)
        return say(uid, tr('Проверить заявку\nСумма с баланса: {v0}\nКомиссия: {v1}\nК выплате: {v2}\nРеквизиты: {v3}\n\nПосле подтверждения сумма будет зарезервирована до ручной выплаты.\n\n👤 Аккаунт в канале выплат: Да. После подтверждённой выплаты посетители канала смогут открыть твой Telegram-профиль. Если не хочешь, выбери «Нет» кнопкой ниже.', {'v0': f"{money(data['amount'])}", 'v1': f"{money(data.get('fee', 0))}", 'v2': f"{money(data.get('net', data['amount']))}", 'v3': f'{text}'}, html_mode=False, section='task_bot', limit=3000), [[button('👤 Аккаунт в канале: Да', 'payout_public:' + data['nonce'])], [button('✅ Подтвердить', 'confirm_payout:' + data['nonce']), button('Отмена', 'cancel_input')]])
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
                    raise UserError(tr('Пришли ссылку на своего Telegram-бота: HTTPS-адрес t.me с именем бота, при необходимости с параметром start.', html_mode=False, section='task_bot', limit=3000))
                data['url'], data['bot_username'] = (text, username)
                data['chat_id'] = None
                data['bot_mode']='click'
                data['title']='Перейти в @'+username
                data['description']='Перейди по ссылке на бота и вернись проверить переход.'
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
                    if data['kind'] in ('channel','group'):
                        info=api('getChat', {'chat_id':data['chat_id']})
                        label='Подписаться на ' if data['kind']=='channel' else 'Вступить в '
                        data['title']=label+str(info.get('title') or info.get('username') or ('канал' if data['kind']=='channel' else 'группу'))[:75]
                        data['description']='Подпишись и нажми «Проверить подписку».' if data['kind']=='channel' else 'Вступи в группу и нажми «Проверить вступление».'
                except UserError:
                    raise
                except Exception:
                    raise UserError(tr('Telegram не смог проверить канал. Проверь ссылку и добавь @Farmlife2026bot администратором.', html_mode=False, section='task_bot', limit=3000))
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
            return say(uid, tr('{v0}\nНаграда: {v1}\nВыполнений: {v2}\nПолная цена выполнения: {v3}\nБюджет: {v4}\n', {'v0': f"{data['title']}", 'v1': f"{money(data['reward'])}", 'v2': f'{text}', 'v3': f"{money(data.get('terms', {}).get('cost', data['reward']))}", 'v4': f'{money(total)}'}, html_mode=False, section='task_bot', limit=3000), [[button('✅ Создать', 'confirm_task:' + data['nonce']), button('Отмена', 'cancel_input')]])
        else:
            return input_prompt(uid, tr('Подтверди действие кнопкой выше или нажми «Отмена».', html_mode=False, section='task_bot', limit=3000))
        state(c, uid, next_stage, data)
        return input_prompt(uid, prompt)
    return input_prompt(uid, tr('Подтверди действие кнопкой выше или нажми «Отмена».', html_mode=False, section='task_bot', limit=3000))

def confirmation(c, uid, action, api):
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
        c.execute("INSERT INTO bot_tasks(id,owner,kind,title,description,url,chat_id,reward,remaining,status,created) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,'active',%s)", (tid, uid, data['kind'], data['title'], data['description'], data['url'], data.get('chat_id'), data['reward'], data['budget'], time.time()))
        # The paid order becomes active immediately. Keep an audit/owner notification.
        if uid != (c.execute('SELECT telegram_id FROM farm_admin_identity WHERE slot=1').fetchone() or {}).get('telegram_id'):
            bot_notifications.enqueue(c,'task:'+tid,tr('✅ Новый заказ опубликован\n\nАвтор: {v0}\nНазвание: {v1}\nБюджет: {v2}', {'v0': str(uid), 'v1': data['title'], 'v2': money(data['budget'])}, section='notifications'),'admin:tasks',subject=uid)
        bot_economy.save_terms(c, tid, data)
        bot_advertising.save(c,tid,data)
        if data['kind']=='bot':
            c.execute('INSERT INTO bot_task_bot_modes(task,mode) VALUES(%s,%s)',(tid,data.get('bot_mode','forward')))
        if data['kind']=='manual':bot_manual.save(c,tid,data)
        if data['kind']=='post':
            bot_extras.queue_post(c, {'id':tid}, api)
        result = say(uid, tr('✅ Задание опубликовано!\n\n💰 Бюджет: {v0}', {'v0': money(data['budget'])}, html_mode=False, section='task_bot', limit=3000), [[button('📂 Мои заказы','mine:0')]])
    elif action == 'confirm_payout' and current['state'] == 'payout_confirm':
        if data.get('method')=='card' and not bot_admin.method_enabled(c,'card_withdraw'):
            raise UserError('Вывод на карту сейчас отключён администратором.')
        bot_account_controls.require_withdrawal(c,uid)
        if data.get('method')=='crypto':
            if not bot_admin.method_enabled(c,'crypto_withdraw') or not bot_crypto_pay.withdrawals_enabled() or bot_crypto_pay.payout_cap(c)<=0:
                raise UserError('Автоматический вывод временно недоступен. Средства не списаны.')
            if time.time()-data.get('crypto_quote_at',0)>120:
                raise UserError('Курс USDT устарел. Создай заявку заново, чтобы получить новый курс.')

        if c.execute("SELECT 1 FROM bot_payouts WHERE uid=%s AND status='pending'", (uid,)).fetchone():
            raise UserError(tr('У тебя уже есть ожидающая заявка.', html_mode=False, section='task_bot', limit=3000))
        pid = uuid.uuid4().hex[:16]
        change(c, uid, -data['amount'], 'payout_reserve', 'Резерв заявки ' + pid)
        c.execute("INSERT INTO bot_payouts(id,uid,amount,destination,status,created) VALUES(%s,%s,%s,%s,'pending',%s)", (pid, uid, data['amount'], data['destination'], time.time()))
        c.execute('INSERT INTO bot_payout_terms VALUES(%s,%s,%s)', (pid, data.get('fee', 0), data.get('net', data['amount'])))
        c.execute('UPDATE bot_payouts SET public_profile=%s WHERE id=%s',(bool(data.get('public_profile')),pid))
        if data.get('method')=='crypto':
            bot_crypto_pay.enqueue_payout(c,pid,data['crypto_usdt'])

        if data.get('method')!='crypto':
            # Only bank withdrawals need owner approval. Crypto Pay uses its own
            # automatic worker and sends confirmed results separately.
            bot_notifications.enqueue(c,'payout:'+pid,tr('💸 Новая заявка на вывод\n\nИгрок: {v0}\nС баланса: {v1}\nК выплате: {v2}\nЗаявка: {v3}\n\nСредства зарезервированы. Перевод ещё не выполнен.', {'v0': str(uid), 'v1': money(data['amount']), 'v2': money(data.get('net', data['amount'])), 'v3': pid}, section='notifications'),'admin:payview:'+pid,subject=uid)
        if data.get('method')=='crypto':
            result=bot_ui.screen(uid,
                '💎 <b>Выплата принята</b>\n\n'
                'Сумма: <b>'+money(data['amount'])+'</b>\n'
                'Способ: 🎁 именной чек\n\n'
                'Как только чек будет готов, получишь кнопку «🎁 Забрать чек».',
                [[button('📥 Мои выплаты','payouts')],[button('👤 Кабинет','cabinet')]])
        else:
            result=say(uid,tr('Заявка {v0} принята. Зарезервировано {v1}. Выплата выполняется администратором вручную.', {'v0': pid, 'v1': money(data['amount'])}, html_mode=False, section='task_bot', limit=3000))
    else:
        raise UserError(tr('Эта кнопка устарела.', html_mode=False, section='task_bot', limit=3000))
    state(c, uid, 'clear')
    return result

def withdrawal_method_rows(c):
    rows=[]
    if bot_admin.method_enabled(c,'card_withdraw'):
        rows.append([button('💳 Банковской картой','withdraw:card')])
    if bot_admin.method_enabled(c,'crypto_withdraw'):
        if bot_crypto_pay.withdrawals_enabled() and bot_crypto_pay.payout_cap(c)>0:
            rows.append([button('💎 Crypto Bot · USDT','withdraw:crypto')])
        else:
            rows.append([button('💎 Crypto Bot · пока недоступен','withdraw:crypto')])
    rows.append([button('Отмена','cancel_input')])
    return rows


def complete_manual_payout(c, uid, pid, reference=None):
    """Record an already completed external transfer exactly once.

    This does NOT send money. The admin's 'Перевод выполнен' button attests
    that the bank transfer has actually succeeded.
    """
    p=c.execute("SELECT * FROM bot_payouts WHERE id=%s AND status='pending' FOR UPDATE",(pid,)).fetchone()
    if not p:
        raise UserError('Заявка уже закрыта.')
    bot_payouts.require(c,p['id'],uid)
    reference=reference or 'confirmed-'+uuid.uuid4().hex
    if c.execute("SELECT 1 FROM bot_payouts WHERE status='paid' AND reference=%s",(reference,)).fetchone():
        raise UserError('Эта банковская операция уже использована для выплаты.')
    c.execute("UPDATE bot_payouts SET status='paid',reference=%s WHERE id=%s",(reference,p['id']))
    c.execute("UPDATE bot_payout_work SET phase='paid' WHERE id=%s",(p['id'],))
    net=bot_admin.net(c,p)
    c.execute('UPDATE bot_cash_pool SET amount=CASE WHEN amount>=%s THEN amount-%s ELSE 0 END WHERE id=1',(net,net))
    c.execute("INSERT INTO bot_ledger VALUES(%s,%s,0,'payout_paid',%s,%s)",(uuid.uuid4().hex,p['uid'],'Выплачено '+money(net)+' · '+p['id'],time.time()))
    bot_notifications.enqueue(c,'payout-paid:'+p['id'],tr('✅ Выплата выполнена\\n\\nСумма: {v0}\\nЗаявка: {v1}',{'v0':money(net),'v1':p['id']},section='notifications'),recipient=p['uid'])
    bot_payout_channel.enqueue_paid(c,p['id'],money(net),recipient_uid=p['uid'] if p['public_profile'] else None)
    state(c,uid,'clear')
    return say(uid,'✅ Выплата отмечена как выполненная. Пользователь и канал получат уведомления.')


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
    if command == '/adsgramurl':
        owner=c.execute('SELECT telegram_id FROM farm_admin_identity WHERE slot=1').fetchone()
        if not owner or int(owner['telegram_id'])!=uid:
            raise UserError('Эта команда доступна только владельцу.')
        import os
        import html
        secret=os.getenv('ADSGRAM_REWARD_URL_TOKEN','')
        if len(secret)<32:
            raise UserError('Reward URL ещё не настроен на Railway.')
        url='https://farm-web-production-cfb9.up.railway.app/api/ads/adsgram/reward?userId=[userId]&key='+secret
        return bot_ui.screen(uid,
          '🔐 <b>AdsGram Reward URL</b>\n'
          +'Скопируй ссылку ниже в настройки Rewarded-блока 58218, поле Reward URL.\n'
          +'<code>'+html.escape(url)+'</code>\n'
          +'<i>Это секретная ссылка. Не пересылай её другим людям.</i>',
          [[button('⬅️ Админ-панель','admin')]])
    if command == '/reklama':
        owner=c.execute('SELECT telegram_id FROM farm_admin_identity WHERE slot=1').fetchone()
        if not owner or int(owner['telegram_id'])!=uid:
            raise UserError('Только владелец FARM может фиксировать рекламный доход.')
        import bot_adsgram_intervals
        if len(parts)==2 and parts[1].lower()=='status':
            current=bot_adsgram_intervals.latest(c)
            if not current:
                return bot_ui.screen(uid,
                    '📍 <b>AdsGram: начальная точка ещё не задана.</b>\n\n'
                    'Введи <code>/reklama 1.50</code> с текущим общим балансом AdsGram.',
                    [[button('⬅️ Админка','admin')]])
            start=float(current['observed_at'])
            confirmed_bot=int(c.execute("""SELECT COUNT(*) AS n FROM bot_adsgram_attempts
                WHERE state='confirmed' AND confirmed_at>=%s""",(start,)).fetchone()['n'])
            confirmed_farm=int(c.execute("""SELECT COUNT(*) AS n FROM bot_adsgram_farm_attempts
                WHERE state='confirmed' AND confirmed_at>=%s""",(start,)).fetchone()['n'])
            pending=int(c.execute("""SELECT COUNT(*) AS n FROM bot_adsgram_attempts
                WHERE state='pending' AND started_at>=%s""",(start,)).fetchone()['n'])
            return bot_ui.screen(uid,
                '📊 <b>AdsGram — статистика дохода</b>\n\n'
                'Точка отсчёта: $'+bot_ui.esc(str(current['cumulative_usd']))+'\n'
                'Новых подтверждённых просмотров в боте: <b>'+str(confirmed_bot)+'</b>\n'
                'Новых подтверждённых просмотров в ферме: <b>'+str(confirmed_farm)+'</b>\n'
                'Ожидают подтверждения в боте: '+str(pending)+'\n\n'
                'Прибыль только фиксируется для статистики; награды уже начислены за успешные просмотры. '
                'Сброс не заменяет настройку SDK-подтверждений.',
                [[button('⬅️ Админка','admin')]])
        if len(parts)==3 and parts[1].lower()=='reset':
            try:
                result=bot_adsgram_intervals.reset_baseline(c,uid,parts[2].replace(',','.'))
            except (ValueError,TypeError) as exc:
                raise UserError('Старт не изменён: '+str(exc))
            return bot_ui.screen(uid,
                '🔄 <b>AdsGram: новая точка отсчёта</b>\n\n'
                'Начальный баланс: <b>$'+bot_ui.esc(result['balance'])+'</b>\n'
                'Начислено: <b>0 грн</b>\n\n'
                'Старые выплаты и история сохранены. Предыдущие просмотры исключены '
                'из будущих начислений. Дальше вводи обычную команду '
                '<code>/reklama 1.65</code> с новым накопленным балансом '
                '(он должен быть выше начального).',
                [[button('⬅️ Админка','admin')]])
        if len(parts)!=2:
            raise UserError('Формат: /reklama 1.65 — текущий баланс AdsGram в USD. '
                            'Сброс без удаления выплат: /reklama reset 1.50')
        try:
            result=bot_adsgram_intervals.report(c,uid,parts[1].replace(',','.'))
        except (ValueError,TypeError) as exc:
            raise UserError('Начисления не выполнены: '+str(exc))
        if result['baseline']:
            output='📍 <b>AdsGram: первый баланс сохранён</b>\n\nБаланс: $'+result['balance']+'\nНачислений пока нет.'
        elif result.get('unchanged'):
            output='🕒 <b>AdsGram: баланс не изменился</b>\n\nБаланс: $'+result['balance']+'\nКонтрольная точка сохранена прежней. Просмотры ожидают прироста дохода.'
        else:
            output=('✅ <b>AdsGram: новый доход записан</b>\n\n'
                 +'Баланс: $'+result['balance']
                 +'\nПрирост: $'+result['delta']
                 +'\nПросмотры в боте: '+str(result['cash_views'])
                 +'\nПросмотры в ферме: '+str(result['farm_views'])
                 +'\nВознаграждения за рекламу начисляются отдельно, сразу после успешного просмотра.')
        return bot_ui.screen(uid,output,[[button('⬅️ Кабинет','cabinet')]])
    if command == '/adsincome':
        # Only the primary FARM owner may allocate actual publisher revenue.
        owner=c.execute('SELECT telegram_id FROM farm_admin_identity WHERE slot=1').fetchone()
        if not owner or int(owner['telegram_id'])!=uid:
            raise UserError('Только владелец FARM может распределять рекламный доход.')
        if len(parts)!=2:
            raise UserError('Формат: /adsincome 0.25 — фактический доход AdsGram за вчера по Киеву в USDT. Без суммы за другие даты.')
        import bot_adsgram_daily
        try:
            result=bot_adsgram_daily.settle_yesterday(c,parts[1].replace(',','.'),uid)
        except (ValueError,TypeError) as exc:
            raise UserError('Начисления НЕ выполнены: '+str(exc))
        return bot_ui.screen(uid,
            '✅ <b>AdsGram: вчерашний доход записан</b>\n'
            +'Дата по Киеву: '+result['day']+'\n'
            +'Всего подтверждённых реклам: '+str(result['provider_impressions'])+'\n'
            +'Из них за игровые ресурсы: '+str(result['farm_views'])+'\n'
            +'За деньги в боте: '+str(result['cash_views'])+'\n'
            +'Доход AdsGram: '+result['publisher_usd']+' USDT\n'
            +'Зрители получают фиксированную награду сразу после просмотра; рекламных комиссий рефералам нет.\n'
            +'Это статистика, а не распределение денег.',
            [[button('⬅️ Админ-панель','admin')]])
    if command == '/adsgramsettle':
        # Additional bot moderators must not approve money transfers.
        owner=c.execute('SELECT telegram_id FROM farm_admin_identity WHERE slot=1').fetchone()
        if not owner or int(owner['telegram_id'])!=uid:
            raise UserError('Только владелец FARM может подтверждать рекламную выручку.')
        if len(parts)!=4:
            raise UserError('Формат: /adsgramsettle ГГГГ-ММ-ДД Сумма_USDT Показы. Сначала сверь отчёт AdsGram за завершённый день по Киеву.')
        import bot_adsgram_daily
        try:
            result=bot_adsgram_daily.settle_day(c,parts[1],parts[2],int(parts[3]),uid)
        except (ValueError,TypeError) as exc:
            raise UserError('Невозможно провести суточную сверку AdsGram: '+str(exc))
        return bot_ui.screen(uid,
            '✅ <b>AdsGram: суточный доход записан</b>\n'
            +'Дата по Киеву: '+result['day']+'\n'
            +'Подтверждённых показов: '+str(result['provider_impressions'])+'\n'
            +'Доход AdsGram: '+result['publisher_usd']+' USDT\n'
            +'Фиксированные награды начисляются за просмотр, без этой команды.\n'
            +'Реферальные награды по рекламе не начисляются.',
            [[button('⬅️ Админ-панель','admin')]])
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
        p=c.execute("SELECT * FROM bot_payouts WHERE id=%s AND status='pending' FOR UPDATE",(data['id'],)).fetchone()
        if not p:raise UserError('Заявка уже закрыта.')
        work=bot_payouts.require(c,p['id'],uid)
        if data.get('work_token')!=work['token']:
            raise UserError('Подтверждение устарело. Открой заявку заново.')
        return complete_manual_payout(c,uid,p['id'],reference=data['reference'])
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
            c.execute('INSERT INTO bot_task_admin_audit VALUES(%s,%s,%s,%s,%s,%s,%s)',(uuid.uuid4().hex,tid,uid,'approve','Одобрено модератором',0,time.time()))
            return say(uid, tr('Пост одобрен и поставлен в очередь публикации. Проверь результат кнопкой «Публикации» в управлении ботом.', html_mode=False, section='task_bot', limit=3000) if t['kind'] == 'post' else tr('Задание опубликовано.', html_mode=False, section='task_bot', limit=3000))
        return bot_decisions.begin(c,uid,'task',tid)
    if action == 'admin:postissues':
        rows = c.execute("SELECT task,status FROM bot_post_publications WHERE status IN ('sending','uncertain') LIMIT 8").fetchall()
        return say(uid, tr('Если пост опубликован, привяжи его пересылкой. Если публикации нет — обратись к разработчику для проверки, не отправляй её повторно вслепую.', html_mode=False, section='task_bot', limit=3000), [[button(r['task'] + ' · ' + r['status'], 'admin:bindpost:' + r['task'])] for r in rows])
    return bot_admin.panel(c, uid)
