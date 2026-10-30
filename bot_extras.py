"""Forwarded-bot evidence, paid channel posts and explicitly funded rewards."""
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
    for sql in [
        """CREATE TABLE IF NOT EXISTS bot_settings(id integer PRIMARY KEY CHECK(id=1),
          daily bigint NOT NULL DEFAULT 0 CHECK(daily>=0),referral bigint NOT NULL DEFAULT 0 CHECK(referral>=0),
          budget bigint NOT NULL DEFAULT 0 CHECK(budget>=0),channel_id bigint,channel_url text NOT NULL DEFAULT '')""",
        'INSERT INTO bot_settings(id) VALUES(1) ON CONFLICT DO NOTHING',
        """CREATE TABLE IF NOT EXISTS bot_daily_claims(uid bigint NOT NULL,day text NOT NULL,
          amount bigint NOT NULL CHECK(amount>0),PRIMARY KEY(uid,day))""",
        """CREATE TABLE IF NOT EXISTS bot_friend_claims(child bigint PRIMARY KEY,parent bigint NOT NULL,
          amount bigint NOT NULL CHECK(amount>0),created double precision NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS bot_bot_completions(uid bigint NOT NULL,bot_id bigint NOT NULL,
          created double precision NOT NULL,PRIMARY KEY(uid,bot_id))""",
        """CREATE TABLE IF NOT EXISTS bot_post_publications(task text PRIMARY KEY,chat_id bigint NOT NULL,
          message_id bigint,status text NOT NULL CHECK(status IN ('queued','sending','posted','uncertain')),
          url text NOT NULL DEFAULT '')""",
    ]:
        c.execute(sql)


def settings(c):
    return c.execute('SELECT * FROM bot_settings WHERE id=1 FOR UPDATE').fetchone()


def forwarded_bot(message, expected_username=None, expected_id=None, since=None):
    b = core()
    origin = message.get('forward_origin') or {}
    sender = origin.get('sender_user') or {}
    if origin.get('type') != 'user' or sender.get('is_bot') is not True:
        raise b.UserError('Нужна настоящая пересылка сообщения от бота с видимым источником. Скопированный текст, скриншот или скрытый отправитель не подходят. Не пересылай пароли и коды.')
    if expected_username and sender.get('username', '').lower() != expected_username.lower():
        raise b.UserError('Это сообщение от другого бота. Перешли ответ именно указанного в задании бота.')
    if expected_id is not None and sender.get('id') != expected_id:
        raise b.UserError('Источник пересылки не совпадает с ботом из задания.')
    if not isinstance(sender.get('id'), int) or sender['id'] <= 0:
        raise b.UserError('Не удалось проверить источник сообщения.')
    if since is not None and (not isinstance(origin.get('date'), int) or origin['date'] < int(since) or origin['date'] > time.time() + 60):
        raise b.UserError('Нужен свежий ответ бота, полученный после взятия задания. Запусти его и перешли новый ответ.')
    return sender['id']


def bot_identity(c, uid, message, data):
    b = core()
    bid = forwarded_bot(message, expected_username=data['bot_username'])
    data['chat_id'] = bid
    b.state(c, uid, 'task_reward', data)
    return b.say(uid, 'Источник бота подтверждён. Укажи награду за одну подходящую пересылку в гривнах.\nВажно: пересылка не подтверждает первый запуск или то, что пользователь не заблокирует бота.')


def bot_completion(c, uid, message, data):
    b = core()
    t = c.execute('SELECT * FROM bot_tasks WHERE id=%s FOR UPDATE', (data['task'],)).fetchone()
    claim = c.execute('SELECT * FROM bot_claims WHERE task=%s AND uid=%s', (data['task'], uid)).fetchone()
    if not t or t['kind'] != 'bot' or not claim or claim['status'] != 'started':
        raise b.UserError('Сначала возьми доступное задание на бота.')
    bid = forwarded_bot(message, expected_username=urlsplit(t['url']).path.strip('/'), expected_id=t['chat_id'], since=claim['created'])
    if t['chat_id'] is None:
        c.execute('UPDATE bot_tasks SET chat_id=%s WHERE id=%s', (bid, t['id']))
        t['chat_id'] = bid
    fresh = c.execute('INSERT INTO bot_bot_completions VALUES(%s,%s,%s) ON CONFLICT DO NOTHING RETURNING uid', (uid, t['chat_id'], time.time())).fetchone()
    if not fresh:
        raise b.UserError('За этого бота ты уже получал награду. Повторной оплаты нет.')
    b.award(c, t, uid)
    b.state(c, uid, 'clear')
    return b.say(uid, '✅ Источник пересылки проверен. Начислено ' + b.money(t['reward']), [[b.button('Следующие задания', 'list:bot:0')]])


def reward_friend(c, child):
    b = core()
    a = c.execute('SELECT referrer FROM bot_accounts WHERE uid=%s', (child,)).fetchone()
    if not a or not a['referrer'] or a['referrer'] == child:
        return 0
    if not c.execute("SELECT 1 FROM bot_claims WHERE uid=%s AND status='paid'", (child,)).fetchone():
        return 0
    cfg = settings(c)
    n = cfg['referral']
    if n <= 0 or cfg['budget'] < n:
        return 0
    row = c.execute('INSERT INTO bot_friend_claims VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING child', (child, a['referrer'], n, time.time())).fetchone()
    if not row:
        return 0
    c.execute('UPDATE bot_settings SET budget=budget-%s WHERE id=1', (n,))
    b.change(c, a['referrer'], n, 'friend_reward', 'Первое выполненное задание друга ' + str(child))
    return n


def route(c, uid, text, action, message, api):
    b = core()
    if action in ('daily', 'friends') or action.startswith('list:post:') or text == '👥 Партнёры':
        b.state(c, uid, 'clear')
    if action == 'skip_bot':
        b.state(c, uid, 'clear')
        return b.say(uid, 'Выбери другое задание.', [[b.button('🤖 Боты', 'list:bot:0')]])
    if action == 'daily':
        cfg = settings(c)
        n = cfg['daily']
        if n <= 0:
            return b.say(uid, '🎁 Ежедневный бонус ещё не настроен администратором.')
        day = dt.datetime.now(ZoneInfo('Europe/Kyiv')).date().isoformat()
        if c.execute('SELECT 1 FROM bot_daily_claims WHERE uid=%s AND day=%s', (uid, day)).fetchone():
            raise b.UserError('Сегодня бонус уже получен. Следующий день считается по времени Киева.')
        if cfg['budget'] < n:
            raise b.UserError('Бюджет бонусов пока закончился. С баланса ничего не списано.')
        c.execute('INSERT INTO bot_daily_claims VALUES(%s,%s,%s)', (uid, day, n))
        c.execute('UPDATE bot_settings SET budget=budget-%s WHERE id=1', (n,))
        b.change(c, uid, n, 'daily_bonus', 'Ежедневный бонус ' + day)
        return b.say(uid, '🎁 Начислен ежедневный бонус: ' + b.money(n))
    if action == 'friends' or text == '👥 Партнёры':
        rows = c.execute('SELECT uid FROM bot_accounts WHERE referrer=%s ORDER BY created LIMIT 100', (uid,)).fetchall()
        paid_now = sum(reward_friend(c, r['uid']) for r in rows)
        count = c.execute('SELECT count(*) AS n FROM bot_accounts WHERE referrer=%s', (uid,)).fetchone()['n']
        qualified = c.execute("""SELECT count(*) AS n FROM bot_accounts a WHERE referrer=%s AND EXISTS(
          SELECT 1 FROM bot_claims x WHERE x.uid=a.uid AND x.status='paid')""", (uid,)).fetchone()['n']
        earned = c.execute('SELECT coalesce(sum(amount),0) AS n FROM bot_friend_claims WHERE parent=%s', (uid,)).fetchone()['n']
        cfg = settings(c)
        return b.say(uid, f"👥 Партнёры\nПриглашено: {count}\nВыполнили задание: {qualified}\nНачислено за друзей: {b.money(earned)}\nСейчас начислено: {b.money(paid_now)}\n\nНаграда за нового друга после первого оплаченного задания: {b.money(cfg['referral'])}\nПри нулевой сумме программа пока не активирована. Бонус выплачивается из отдельного бюджета.\n\nhttps://t.me/Farmlife2026bot?start=partner_{uid}", [[b.button('Обновить и получить бонусы', 'friends')]])
    if action.startswith('list:post:'):
        cfg = settings(c)
        if not cfg['channel_url']:
            return b.say(uid, 'Канал рекламных постов пока не указан администратором.')
        return b.say(uid, '👁 Рекламные посты публикуются в нашем канале. Под постом нажми кнопку награды. Оплачивается нажатие, подтвердить фактическое прочтение Telegram не позволяет.', [[{'text': '👁 Открыть посты', 'url': cfg['channel_url']}]])
    if action.startswith('postclaim:'):
        tid = action.split(':', 1)[1]
        publication = c.execute("SELECT * FROM bot_post_publications WHERE task=%s", (tid,)).fetchone()
        if publication and publication['status'] != 'posted':
            raise b.UserError('Публикация ещё проверяется администратором. Попробуй позже.')
        source = message.get('chat') or {}
        if not publication or source.get('id') != publication['chat_id'] or message.get('message_id') != publication['message_id']:
            raise b.UserError('Нажми кнопку под исходным постом в нашем канале.')
        t = c.execute('SELECT * FROM bot_tasks WHERE id=%s FOR UPDATE', (tid,)).fetchone()
        if not t or t['kind'] != 'post' or t['owner'] == uid or t['status'] != 'active':
            raise b.UserError('Этот пост недоступен для получения награды.')
        if c.execute('SELECT 1 FROM bot_claims WHERE task=%s AND uid=%s', (tid, uid)).fetchone():
            raise b.UserError('Награда за этот пост уже получена.')
        c.execute("INSERT INTO bot_claims(task,uid,status,created) VALUES(%s,%s,'started',%s)", (tid, uid, time.time()))
        b.award(c, t, uid)
        return {'method': 'answerCallbackQuery', 'callback_query_id': message['_callback_id'], 'text': 'Начислено ' + b.money(t['reward']), 'show_alert': True}
    return None


def administration(c, uid, text, action, api):
    b = core()
    parts = text.split()
    cmd = parts[0].split('@')[0] if parts else ''
    if cmd == '/botbonus':
        if len(parts) != 4:
            raise b.UserError('Формат: /botbonus БонусЗаДень БонусЗаДруга ДобавитьБюджет\nСуммы в гривнах; 0 отключает награду. Бюджет выделяется только из свободного фактически учтённого резерва. Пример формата: /botbonus 0 0 0')
        daily, referral, extra = (0 if p in ('0', '0.00', '0,00') else b.amount(p) for p in parts[1:])
        pool = c.execute('SELECT amount FROM bot_cash_pool WHERE id=1 FOR UPDATE').fetchone()['amount']
        if pool - b.liability(c) < extra:
            raise b.UserError('Свободного резерва недостаточно. Сначала учти фактически выделенные деньги через /botfund.')
        c.execute('UPDATE bot_settings SET daily=%s,referral=%s,budget=budget+%s WHERE id=1', (daily, referral, extra))
        c.execute("INSERT INTO bot_ledger VALUES(%s,%s,0,'bonus_config',%s,%s)",
                  (uuid.uuid4().hex, uid, f'За день {b.money(daily)}, за друга {b.money(referral)}, добавлено в бюджет {b.money(extra)}', time.time()))
        return b.say(uid, f'Настройки сохранены. За день: {b.money(daily)}. За друга: {b.money(referral)}. Добавлено в бюджет: {b.money(extra)}. Деньги пользователей и рекламодателей не расходуются на бонусы.')
    if cmd == '/botchannel':
        if len(parts) != 2:
            raise b.UserError('Формат: /botchannel @ИмяКанала\nСначала добавь нашего бота администратором с правом публикации сообщений.')
        cid, url = b.resolve_chat(api, parts[1], 'channel')
        me = api('getMe', {})
        rights = api('getChatMember', {'chat_id': cid, 'user_id': me['id']})
        if rights.get('status') != 'creator' and not rights.get('can_post_messages'):
            raise b.UserError('У нашего бота нет права публиковать сообщения в этом канале.')
        c.execute('UPDATE bot_settings SET channel_id=%s,channel_url=%s WHERE id=1', (cid, url))
        return b.say(uid, 'Канал рекламных постов подключён: ' + url)
    if action == 'admin:bonus':
        cfg = settings(c)
        return b.say(uid, f"🎁 Бонусы\nЗа день: {b.money(cfg['daily'])}\nЗа друга: {b.money(cfg['referral'])}\nБюджет: {b.money(cfg['budget'])}\n\nНастроить: /botbonus БонусЗаДень БонусЗаДруга ДобавитьБюджет\nПри 0 награда отключена. За друга — один раз после первого оплаченного задания.\n\nРекламный канал: {cfg['channel_url'] or 'не подключён'}\nПодключить: /botchannel @ИмяКанала")
    if action.startswith('admin:bindpost:'):
        tid = action.split(':')[-1]
        pub = c.execute("SELECT * FROM bot_post_publications WHERE task=%s AND status IN ('sending','uncertain')", (tid,)).fetchone()
        if not pub:
            raise b.UserError('Нет неопределённой публикации для этого задания.')
        b.state(c, uid, 'bind_post', {'task': tid, 'channel': pub['chat_id']})
        return b.say(uid, 'Перешли сюда опубликованный пост из нужного канала. Будет привязан его исходный ID; повторной отправки в канал не будет.')
    return None


def queue_post(c, t, api):
    b = core()
    cfg = settings(c)
    if not cfg['channel_id']:
        raise b.UserError('Сначала подключи канал постов командой /botchannel @ИмяКанала.')
    me = api('getMe', {})
    rights = api('getChatMember', {'chat_id': cfg['channel_id'], 'user_id': me['id']})
    if rights.get('status') not in ('administrator', 'creator') or (rights.get('status') != 'creator' and not rights.get('can_post_messages')):
        raise b.UserError('Проверь право бота публиковать сообщения в канале.')
    c.execute("INSERT INTO bot_post_publications(task,chat_id,status) VALUES(%s,%s,'queued') ON CONFLICT DO NOTHING", (t['id'], cfg['channel_id']))


def publication_url(cid, mid, channel_url):
    # Public channel URL or a private-channel message permalink.
    if urlsplit(channel_url).path.startswith('/+') or 'joinchat' in channel_url:
        return f'https://t.me/c/{str(cid).removeprefix("-100")}/{mid}'
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
            c.execute("DELETE FROM bot_post_publications WHERE task=%s", (pub['task'],))
            return
        c.execute("UPDATE bot_post_publications SET status='sending' WHERE task=%s", (t['id'],))
        cfg = settings(c)
        url = cfg['channel_url']
    try:
        result = api('sendMessage', {'chat_id': pub['chat_id'], 'text': '📣 Реклама\n' + t['title'] + '\n\n' + t['description'] + ('\n\n' + t['url'] if t['url'] else '') + '\n\nНаграда за нажатие кнопки — ' + b.money(t['reward']) + '. Один раз на пользователя.',
                     'reply_markup': {'inline_keyboard': [[b.button('💰 Получить ' + b.money(t['reward']), 'postclaim:' + t['id'])]]}})
        if not isinstance(result, dict) or not isinstance(result.get('message_id'), int) or (result.get('chat') or {}).get('id') != pub['chat_id']:
            raise RuntimeError('unexpected post publication response')
        with db() as c:
            published_chat = result['chat']
            permalink = ('https://t.me/' + published_chat['username'] + '/' + str(result['message_id'])
                         if published_chat.get('username') else f"https://t.me/c/{str(pub['chat_id']).removeprefix('-100')}/{result['message_id']}")
            c.execute("UPDATE bot_post_publications SET status='posted',message_id=%s,url=%s WHERE task=%s", (result['message_id'], permalink, t['id']))
    except Exception:
        with db() as c:
            c.execute("UPDATE bot_post_publications SET status='uncertain' WHERE task=%s", (t['id'],))
        log.warning('post_publication_uncertain task=%s; admin must reconcile forwarded channel post', t['id'])
