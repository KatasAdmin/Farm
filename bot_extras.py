"""Forwarded-bot evidence, paid channel posts and daily account rewards."""
from bot_copy import tr
import datetime as dt
import logging
import time
import uuid
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit
log = logging.getLogger('farm.tasks.extras')

def core():
    import task_bot
    return task_bot

def initialize(c):
    for sql in ["CREATE TABLE IF NOT EXISTS bot_settings(id integer PRIMARY KEY CHECK(id=1),\n          daily bigint NOT NULL DEFAULT 0 CHECK(daily>=0),referral bigint NOT NULL DEFAULT 0 CHECK(referral>=0),\n          budget bigint NOT NULL DEFAULT 0 CHECK(budget>=0),channel_id bigint,channel_url text NOT NULL DEFAULT '')", 'INSERT INTO bot_settings(id) VALUES(1) ON CONFLICT DO NOTHING', 'CREATE TABLE IF NOT EXISTS bot_daily_claims(uid bigint NOT NULL,day text NOT NULL,\n          amount bigint NOT NULL CHECK(amount>0),PRIMARY KEY(uid,day))', 'CREATE TABLE IF NOT EXISTS bot_friend_claims(child bigint PRIMARY KEY,parent bigint NOT NULL,\n          amount bigint NOT NULL CHECK(amount>0),created double precision NOT NULL)', 'CREATE TABLE IF NOT EXISTS bot_bot_completions(uid bigint NOT NULL,bot_id bigint NOT NULL,\n          created double precision NOT NULL,PRIMARY KEY(uid,bot_id))', "CREATE TABLE IF NOT EXISTS bot_post_publications(task text PRIMARY KEY,chat_id bigint NOT NULL,\n          message_id bigint,status text NOT NULL CHECK(status IN ('queued','sending','posted','uncertain')),\n          url text NOT NULL DEFAULT '')"]:
        c.execute(sql)

def settings(c):
    return c.execute('SELECT * FROM bot_settings WHERE id=1 FOR UPDATE').fetchone()

def forwarded_bot(message, expected_username=None, expected_id=None, since=None):
    b = core()
    origin = message.get('forward_origin') or {}
    sender = origin.get('sender_user') or {}
    if origin.get('type') != 'user' or sender.get('is_bot') is not True:
        raise b.UserError(tr('Нужна настоящая пересылка сообщения от бота с видимым источником. Скопированный текст, скриншот или скрытый отправитель не подходят. Не пересылай пароли и коды.', html_mode=False, section='bot_extras', limit=3000))
    if expected_username and sender.get('username', '').lower() != expected_username.lower():
        raise b.UserError(tr('Это сообщение от другого бота. Перешли ответ именно указанного в задании бота.', html_mode=False, section='bot_extras', limit=3000))
    if expected_id is not None and sender.get('id') != expected_id:
        raise b.UserError(tr('Источник пересылки не совпадает с ботом из задания.', html_mode=False, section='bot_extras', limit=3000))
    if not isinstance(sender.get('id'), int) or sender['id'] <= 0:
        raise b.UserError(tr('Не удалось проверить источник сообщения.', html_mode=False, section='bot_extras', limit=3000))
    if since is not None and (not isinstance(origin.get('date'), int) or origin['date'] < int(since) or origin['date'] > time.time() + 60):
        raise b.UserError(tr('Нужен свежий ответ бота, полученный после взятия задания. Запусти его и перешли новый ответ.', html_mode=False, section='bot_extras', limit=3000))
    return sender['id']

def bot_identity(c, uid, message, data):
    b = core()
    bid = forwarded_bot(message, expected_username=data['bot_username'])
    data['chat_id'] = bid
    b.state(c, uid, 'task_reward', data)
    return b.say(uid, tr('Источник бота подтверждён. Укажи награду за одну подходящую пересылку в гривнах.\nВажно: пересылка не подтверждает первый запуск или то, что пользователь не заблокирует бота.', html_mode=False, section='bot_extras', limit=3000))

def bot_completion(c, uid, message, data):
    b = core()
    t = c.execute('SELECT * FROM bot_tasks WHERE id=%s FOR UPDATE', (data['task'],)).fetchone()
    claim = c.execute('SELECT * FROM bot_claims WHERE task=%s AND uid=%s', (data['task'], uid)).fetchone()
    if not t or t['kind'] != 'bot' or (not claim) or (claim['status'] != 'started'):
        raise b.UserError(tr('Сначала возьми доступное задание на бота.', html_mode=False, section='bot_extras', limit=3000))
    bid = forwarded_bot(message, expected_username=urlsplit(t['url']).path.strip('/'), expected_id=t['chat_id'], since=claim['created'])
    if t['chat_id'] is None:
        c.execute('UPDATE bot_tasks SET chat_id=%s WHERE id=%s', (bid, t['id']))
        t['chat_id'] = bid
    fresh = c.execute('INSERT INTO bot_bot_completions VALUES(%s,%s,%s) ON CONFLICT DO NOTHING RETURNING uid', (uid, t['chat_id'], time.time())).fetchone()
    if not fresh:
        raise b.UserError(tr('За этого бота ты уже получал награду. Повторной оплаты нет.', html_mode=False, section='bot_extras', limit=3000))
    b.award(c, t, uid)
    b.state(c, uid, 'clear')
    return b.say(uid, tr('✅ Источник пересылки проверен. Начислено {v0}', {'v0': b.money(t['reward'])}, html_mode=False, section='bot_extras', limit=3000), [[b.button('Следующие задания', 'list:bot:0')]])

def route(c, uid, text, action, message, api):
    b = core()
    if action in ('daily', 'friends') or action.startswith('list:post:') or text == '👥 Партнёры':
        b.state(c, uid, 'clear')
    if action == 'skip_bot':
        b.state(c, uid, 'clear')
        return b.say(uid, tr('Выбери другое задание.', html_mode=False, section='bot_extras', limit=3000), [[b.button('🤖 Боты', 'list:bot:0')]])
    if action == 'daily':
        cfg = settings(c)
        n = cfg['daily']
        if n <= 0:
            return b.say(uid, tr('🎁 Ежедневная награда сейчас отключена.', html_mode=False, section='bot_extras', limit=3000))
        day = dt.datetime.now(ZoneInfo('Europe/Kyiv')).date().isoformat()
        if c.execute('SELECT 1 FROM bot_daily_claims WHERE uid=%s AND day=%s', (uid, day)).fetchone():
            raise b.UserError(tr('Сегодня бонус уже получен. Следующий день считается по времени Киева.', html_mode=False, section='bot_extras', limit=3000))
        c.execute('INSERT INTO bot_daily_claims VALUES(%s,%s,%s)', (uid, day, n))
        b.change(c, uid, n, 'daily_bonus', 'Ежедневный бонус ' + day)
        return b.say(uid, tr('🎁 Начислен ежедневный бонус: {v0}', {'v0': b.money(n)}, html_mode=False, section='bot_extras', limit=3000))
    if action == 'friends' or text == '👥 Партнёры':
        return b.bot_economy.partners(c, uid)
    if action.startswith('list:post:'):
        cfg = settings(c)
        if not cfg['channel_url']:
            return b.say(uid, tr('Канал рекламных постов пока не указан администратором.', html_mode=False, section='bot_extras', limit=3000))
        return b.say(uid, tr('👁 Рекламные посты публикуются в нашем канале. Под постом нажми кнопку награды. Оплачивается нажатие, подтвердить фактическое прочтение Telegram не позволяет.', html_mode=False, section='bot_extras', limit=3000), [[{'text': tr('👁 Открыть посты', html_mode=False, section='bot_extras', limit=3000), 'url': cfg['channel_url']}]])
    if action.startswith('postclaim:'):
        tid = action.split(':', 1)[1]
        publication = c.execute('SELECT * FROM bot_post_publications WHERE task=%s', (tid,)).fetchone()
        if publication and publication['status'] != 'posted':
            raise b.UserError(tr('Публикация ещё проверяется администратором. Попробуй позже.', html_mode=False, section='bot_extras', limit=3000))
        source = message.get('chat') or {}
        if not publication or source.get('id') != publication['chat_id'] or message.get('message_id') != publication['message_id']:
            raise b.UserError(tr('Нажми кнопку под исходным постом в нашем канале.', html_mode=False, section='bot_extras', limit=3000))
        t = c.execute('SELECT * FROM bot_tasks WHERE id=%s FOR UPDATE', (tid,)).fetchone()
        if not t or t['kind'] != 'post' or t['owner'] == uid or (t['status'] != 'active'):
            raise b.UserError(tr('Этот пост недоступен для получения награды.', html_mode=False, section='bot_extras', limit=3000))
        if c.execute('SELECT 1 FROM bot_claims WHERE task=%s AND uid=%s', (tid, uid)).fetchone():
            raise b.UserError(tr('Награда за этот пост уже получена.', html_mode=False, section='bot_extras', limit=3000))
        c.execute("INSERT INTO bot_claims(task,uid,status,created) VALUES(%s,%s,'started',%s)", (tid, uid, time.time()))
        b.award(c, t, uid)
        return {'method': 'answerCallbackQuery', 'callback_query_id': message['_callback_id'], 'text': tr('Начислено {v0}', {'v0': b.money(t['reward'])}, html_mode=False, section='bot_extras', limit=3000), 'show_alert': True}
    return None

def administration(c, uid, text, action, api):
    b = core()
    parts = text.split()
    cmd = parts[0].split('@')[0] if parts else ''
    if cmd == '/botbonus':
        if len(parts) != 2:
            raise b.UserError(tr('Формат: /botbonus СуммаЗаДень\nНапример: /botbonus 0.50. Сумма 0 отключает награду.', html_mode=False, section='bot_extras', limit=3000))
        daily = 0 if parts[1] in ('0', '0.00', '0,00') else b.amount(parts[1])
        c.execute('UPDATE bot_settings SET daily=%s WHERE id=1', (daily,))
        c.execute("INSERT INTO bot_ledger VALUES(%s,%s,0,'bonus_config',%s,%s)", (uuid.uuid4().hex, uid, 'Ежедневная награда: ' + b.money(daily), time.time()))
        return b.say(uid, tr('Ежедневная награда сохранена: {v0}. Зачисляется на баланс один раз в день.', {'v0': b.money(daily)}, html_mode=False, section='bot_extras', limit=3000))
    if cmd == '/botchannel':
        if len(parts) != 2:
            raise b.UserError(tr('Формат: /botchannel @ИмяКанала\nСначала добавь нашего бота администратором с правом публикации сообщений.', html_mode=False, section='bot_extras', limit=3000))
        cid, url = b.resolve_chat(api, parts[1], 'channel')
        me = api('getMe', {})
        rights = api('getChatMember', {'chat_id': cid, 'user_id': me['id']})
        if rights.get('status') != 'creator' and (not rights.get('can_post_messages')):
            raise b.UserError(tr('У нашего бота нет права публиковать сообщения в этом канале.', html_mode=False, section='bot_extras', limit=3000))
        c.execute('UPDATE bot_settings SET channel_id=%s,channel_url=%s WHERE id=1', (cid, url))
        return b.say(uid, tr('Канал рекламных постов подключён: {v0}', {'v0': url}, html_mode=False, section='bot_extras', limit=3000))
    if action == 'admin:bonus':
        cfg = settings(c)
        return b.say(uid, tr('🎁 Ежедневная награда: {v0}\nЗачисляется на баланс один раз в день.\n\nИзменить сумму: /botbonus 0.50\n\nРекламный канал: {v1}\nПодключить: /botchannel @ИмяКанала', {'v0': f"{b.money(cfg['daily'])}", 'v1': f"{cfg['channel_url'] or 'не подключён'}"}, html_mode=False, section='bot_extras', limit=3000), [[b.button('Изменить ежедневную награду', 'admin:ecoedit:bonus')]])
    if action.startswith('admin:bindpost:'):
        tid = action.split(':')[-1]
        pub = c.execute("SELECT * FROM bot_post_publications WHERE task=%s AND status IN ('sending','uncertain')", (tid,)).fetchone()
        if not pub:
            raise b.UserError(tr('Нет неопределённой публикации для этого задания.', html_mode=False, section='bot_extras', limit=3000))
        b.state(c, uid, 'bind_post', {'task': tid, 'channel': pub['chat_id']})
        return b.say(uid, tr('Перешли сюда опубликованный пост из нужного канала. Будет привязан его исходный ID; повторной отправки в канал не будет.', html_mode=False, section='bot_extras', limit=3000))
    return None

def queue_post(c, t, api):
    b = core()
    cfg = settings(c)
    if not cfg['channel_id']:
        raise b.UserError(tr('Подключи канал постов кнопкой «Канал постов» в управлении ботом.', html_mode=False, section='bot_extras', limit=3000))
    me = api('getMe', {})
    rights = api('getChatMember', {'chat_id': cfg['channel_id'], 'user_id': me['id']})
    if rights.get('status') not in ('administrator', 'creator') or (rights.get('status') != 'creator' and (not rights.get('can_post_messages'))):
        raise b.UserError(tr('Проверь право бота публиковать сообщения в канале.', html_mode=False, section='bot_extras', limit=3000))
    c.execute("INSERT INTO bot_post_publications(task,chat_id,status) VALUES(%s,%s,'queued') ON CONFLICT DO NOTHING", (t['id'], cfg['channel_id']))

def publication_url(cid, mid, channel_url):
    if urlsplit(channel_url).path.startswith('/+') or 'joinchat' in channel_url:
        return f"https://t.me/c/{str(cid).removeprefix('-100')}/{mid}"
    return channel_url.rstrip('/') + '/' + str(mid)

def deliver_posts(db, api):
    """One-shot outbox. Never resend after an ambiguous Telegram response."""
    b = core()
    with db() as c:
        c.execute('SELECT pg_advisory_xact_lock(%s)', (b.LOCK,))
        pub = c.execute("SELECT * FROM bot_post_publications WHERE status='queued' LIMIT 1 FOR UPDATE").fetchone()
        if not pub:
            return
        t = c.execute('SELECT * FROM bot_tasks WHERE id=%s', (pub['task'],)).fetchone()
        if not t or t['status'] != 'active':
            c.execute('DELETE FROM bot_post_publications WHERE task=%s', (pub['task'],))
            return
        c.execute("UPDATE bot_post_publications SET status='sending' WHERE task=%s", (t['id'],))
        cfg = settings(c)
        url = cfg['channel_url']
    try:
        result = api('sendMessage', {'chat_id': pub['chat_id'], 'text': tr('📣 Реклама\n{v0}\n\n{v1}{v2}\n\nНаграда за нажатие кнопки — {v3}. Один раз на пользователя.', {'v0': t['title'], 'v1': t['description'], 'v2': '\n\n' + t['url'] if t['url'] else '', 'v3': b.money(t['reward'])}, html_mode=False, section='bot_extras', limit=3000), 'reply_markup': {'inline_keyboard': [[b.button('💰 Получить ' + b.money(t['reward']), 'postclaim:' + t['id'])]]}})
        if not isinstance(result, dict) or not isinstance(result.get('message_id'), int) or (result.get('chat') or {}).get('id') != pub['chat_id']:
            raise RuntimeError('unexpected post publication response')
        with db() as c:
            published_chat = result['chat']
            permalink = 'https://t.me/' + published_chat['username'] + '/' + str(result['message_id']) if published_chat.get('username') else f"https://t.me/c/{str(pub['chat_id']).removeprefix('-100')}/{result['message_id']}"
            c.execute("UPDATE bot_post_publications SET status='posted',message_id=%s,url=%s WHERE task=%s", (result['message_id'], permalink, t['id']))
    except Exception:
        with db() as c:
            c.execute("UPDATE bot_post_publications SET status='uncertain' WHERE task=%s", (t['id'],))
        log.warning('post_publication_uncertain task=%s; admin must reconcile forwarded channel post', t['id'])
