"""Telegram screens with escaped HTML, real catalog totals and referral tools."""
import datetime as dt
import html
import time
import uuid
from zoneinfo import ZoneInfo


def core():
    import task_bot
    return task_bot


def esc(value):
    return html.escape(str(value))


def screen(uid, text, buttons=None):
    result = core().say(uid, text, buttons)
    result['parse_mode'] = 'HTML'
    result['link_preview_options'] = {'is_disabled': True}
    return result


def initialize(c):
    c.execute('CREATE INDEX IF NOT EXISTS bot_claims_user ON bot_claims(uid,status)')
    c.execute('CREATE INDEX IF NOT EXISTS bot_ref_rewards_parent ON bot_ref_rewards(parent,level)')
    c.execute('CREATE INDEX IF NOT EXISTS bot_accounts_created ON bot_accounts(created,referrer)')
    c.execute("""CREATE TABLE IF NOT EXISTS bot_ref_welcomes(uid bigint PRIMARY KEY,
      body text NOT NULL,updated double precision NOT NULL)""")


def catalog_filter():
    # Shared by the overview and actual task list; one reward per worker/order.
    return """t.status='active' AND t.owner<>%s
      AND t.remaining>=coalesce((SELECT cost FROM bot_task_terms q WHERE q.task=t.id),t.reward)*
        (1+(SELECT count(*) FROM bot_claims r WHERE r.task=t.id AND r.status='review'))
      AND (t.kind<>'post' OR EXISTS(SELECT 1 FROM bot_post_publications p WHERE p.task=t.id AND p.status='posted'))
      AND NOT EXISTS(SELECT 1 FROM bot_claims x WHERE x.task=t.id AND x.uid=%s
        AND x.status IN ('paid','rejected','review'))
      AND (t.kind<>'bot' OR t.chat_id IS NULL OR NOT EXISTS(
        SELECT 1 FROM bot_bot_completions done WHERE done.uid=%s AND done.bot_id=t.chat_id))"""


def earn(c, uid):
    b = core()
    b.state(c,uid,'clear')
    rows = c.execute("""SELECT kind,count(*) AS n,sum(reward) AS total,
      min(reward) AS low,max(reward) AS high FROM bot_tasks t WHERE """+
      catalog_filter()+" GROUP BY kind", (uid,uid,uid)).fetchall()
    kinds = {r['kind']:r for r in rows}
    total = sum(r['total'] for r in rows)
    settings = c.execute('SELECT daily,channel_url FROM bot_settings WHERE id=1').fetchone()
    daily = settings['daily']
    def count(kind):
        return kinds.get(kind,{}).get('n',0)
    def rate(kind):
        if kind in kinds:
            row=kinds[kind]
            return ('от ' if row['low']!=row['high'] or kind=='manual' else '+')+b.money(row['low'])
        if kind=='manual':
            return ''
        return '+'+b.money(b.bot_economy.quote(c,kind)['reward'])
    def label(text,kind):
        reward=rate(kind)
        return text+(' · '+reward if reward else '')
    text = ('🚀 <b>Как хочешь заработать?</b>\n\n'
            '<b>💼 Доступные задания</b>\n'
            f'📣 Подписаться на канал: <b>{count("channel")}</b>\n'
            f'👁 Посмотреть пост: <b>{count("post")}</b>\n'
            f'🤖 Перейти в бота: <b>{count("bot")}</b>\n'
            f'👥 Вступить в группу: <b>{count("group")}</b>\n'
            f'📝 Выполнить задание: <b>{count("manual")}</b>\n'
            '🤝 Приглашать друзей: <b>можно</b>\n'
            '⭐ Квесты: <i>готовятся</i>\n\n'
            f'<b>💎 Награды в доступных заданиях: {b.money(total)}</b>\n'
            '<i>За каждое задание награда выдаётся один раз после проверки.</i>')
    posts_button = ({'text':label('👁 Смотреть посты','post'),'url':settings['channel_url']}
                    if settings['channel_url'] else b.button(label('👁 Смотреть посты','post'),'list:post:0'))
    return screen(uid,text,[
        [b.button(label('🤖 Перейти в бота','bot'),'list:bot:0')],
        [b.button(label('📣 Подписаться на канал','channel'),'list:channel:0')],
        [b.button(label('👥 Вступить в группу','group'),'list:group:0')],
        [posts_button],
        [b.button('⭐ Квесты','quests'),b.button('📝 Задания','list:manual:0')],
        [b.button('🎁 Бонус '+b.money(daily),'daily'),b.button('🤝 За друга','friends')]])


def promotion(c,uid):
    b=core()
    b.state(c,uid,'clear')
    a=b.account(c,uid)
    return screen(uid,'📣 <b>Что хочешь продвинуть?</b>\n\n'+
                  '<b>💰 Баланс: '+b.money(a['available'])+'</b>\n\n'+
                  'Выбери формат и создай свой заказ.\n'
                  'Полная стоимость резервируется после подтверждения. Публикация — после модерации.',[
        [b.button('👁 Пост','new:post'),b.button('📣 Канал','new:channel')],
        [b.button('🤖 Бота','new:bot'),b.button('👥 Группу','new:group')],
        [b.button('📝 Задание','new:manual')],
        [b.button('📋 Мои заказы','mine:0'),b.button('✅ Проверить работы','reviews:0')],
        [b.button('➕ Пополнить','deposit')]])


def team_rows(c,uid):
    return c.execute("""WITH RECURSIVE team(uid,depth,path) AS (
      SELECT uid,1,',' || CAST(%s AS text) || ',' || CAST(uid AS text) || ','
        FROM bot_accounts WHERE referrer=%s AND uid<>%s
      UNION ALL
      SELECT a.uid,t.depth+1,t.path || CAST(a.uid AS text) || ','
        FROM bot_accounts a JOIN team t ON a.referrer=t.uid
        WHERE t.depth<5 AND replace(t.path,',' || CAST(a.uid AS text) || ',','')=t.path)
      SELECT depth,count(*) AS n,sum(CASE WHEN EXISTS(
        SELECT 1 FROM bot_claims x WHERE x.uid=team.uid AND x.status='paid') THEN 1 ELSE 0 END) AS active
        FROM team GROUP BY depth""",(uid,uid,uid)).fetchall()


def partners(c,uid):
    b=core()
    cfg=b.bot_economy.config(c)
    rows={r['depth']:r for r in team_rows(c,uid)}
    earnings={r['level']:r['units'] for r in c.execute(
        'SELECT level,sum(units) AS units FROM bot_ref_rewards WHERE parent=%s GROUP BY level',(uid,)).fetchall()}
    a=c.execute('SELECT referrer FROM bot_accounts WHERE uid=%s',(uid,)).fetchone()
    source='🌱 Ты пришёл самостоятельно'
    if a and a['referrer']:
        parent=c.execute('SELECT name FROM bot_accounts WHERE uid=%s',(a['referrer'],)).fetchone()
        source='🤝 Тебя пригласил: <b>'+esc((parent['name'] if parent else 'Участник')[:32])+'</b>'
    total=sum(r['n'] for r in rows.values())
    active=sum(r['active'] for r in rows.values())
    text=('👥 <b>Твоя партнёрская команда</b>\n\n'+source+'\n\n'
          f'👤 Приглашено в команду: <b>{total}</b>\n'
          f'🔥 Активных: <b>{active}</b>\n'
          f'💤 Пока без выполнений: <b>{total-active}</b>\n'
          '<i>Активный участник выполнил хотя бы одно оплаченное задание.</i>\n\n'
          '<b>💎 Пять уровней дохода</b>\n')
    icons=['🥇','🥈','🥉','🔹','🔸']
    for level in range(1,6):
        count=rows.get(level,{}).get('n',0)
        units=earnings.get(level,0)
        percent=b.bot_economy.pct(cfg['ref'+str(level)]).replace('.',',')
        text+=f"{icons[level-1]} Уровень {level}: {count} чел. · <b>{percent}%</b> · {b.money(units//10000)}\n"
    earned=sum(earnings.values())
    text+=(f'\n<b>💰 Доход от команды: {b.money(earned//10000)}</b>\n'
           '<i>Доли меньше копейки накапливаются автоматически.</i>\n\n'
           '🔗 <b>Твоя ссылка для приглашений</b>\n'
           f'https://t.me/Farmlife2026bot?start=partner_{uid}\n\n'
           'Проценты начисляются с полной цены оплаченных выполнений команды.\n'
           '<b>🤝 Приглашай друзей — зарабатывайте вместе!</b>')
    return screen(uid,text,[
        [b.button('🏆 Топ рефоводов','top:all'),b.button('🔥 Топ сегодня','top:today')],
        [b.button('✉️ Приветственное сообщение','welcome')]])


def today_bounds():
    now=dt.datetime.now(ZoneInfo('Europe/Kyiv'))
    start=now.replace(hour=0,minute=0,second=0,microsecond=0)
    return start.timestamp(),(start+dt.timedelta(days=1)).timestamp()


def leaderboard(c,uid,period):
    b=core()
    condition=''
    args=()
    if period=='today':
        condition=' AND child.created>=%s AND child.created<%s'
        args=today_bounds()
    query="""SELECT parent.uid,parent.name,count(*) AS n,min(child.created) AS first_at
      FROM bot_accounts child JOIN bot_accounts parent ON parent.uid=child.referrer
      WHERE child.uid<>parent.uid"""+condition+" GROUP BY parent.uid,parent.name"
    rows=c.execute(query+' ORDER BY n DESC,first_at,parent.uid LIMIT 10',args).fetchall()
    mine=c.execute('SELECT count(*) AS n FROM bot_accounts child WHERE child.referrer=%s AND child.uid<>%s'+condition,(uid,uid,*args)).fetchone()['n']
    title='🔥 <b>Топ рефоводов сегодня</b>' if period=='today' else '🏆 <b>Топ рефоводов за всё время</b>'
    text=title+'\n<i>По числу личных приглашений первого уровня'+(' за день по Киеву' if period=='today' else '')+'.</i>\n\n'
    for rank,row in enumerate(rows,1):
        icon=['🥇','🥈','🥉'][rank-1] if rank<=3 else str(rank)+'.'
        text+=f"{icon} <b>{esc(row['name'][:32])}</b> — {row['n']} чел.\n"
    if not rows:
        text+='🌱 Пока нет приглашений. Ты можешь стать первым!\n'
    text+=f'\n🤝 Твоих приглашений: <b>{mine}</b>'
    return screen(uid,text,[[b.button('🏆 За всё время','top:all'),b.button('🔥 Сегодня','top:today')],
                            [b.button('⬅️ Партнёры','friends')]])


def home(c,uid,invited=False):
    b=core()
    a=c.execute('SELECT name,referrer FROM bot_accounts WHERE uid=%s',(uid,)).fetchone()
    text=f"🌾 <b>Farm · Новая жизнь</b>\n\nПривет, <b>{esc(a['name'][:48])}</b>! 👋\n\n"
    if invited and a['referrer']:
        welcome=c.execute('SELECT w.body,a.name FROM bot_ref_welcomes w JOIN bot_accounts a ON a.uid=w.uid WHERE w.uid=%s',(a['referrer'],)).fetchone()
        if welcome:
            text+='✉️ <b>Сообщение от пригласившего '+esc(welcome['name'][:32])+':</b>\n'+esc(welcome['body'])+'\n\n'
    text+=('🚀 <b>Зарабатывай</b> на заданиях\n'
           '📣 <b>Продвигай</b> свои проекты\n'
           '🎮 <b>Играй</b> и развивай ферму\n'
           '🤝 <b>Приглашай друзей</b> в свою команду\n\n'
           '👇 Выбери раздел в меню внизу')
    return screen(uid,text)


def welcome(c,uid):
    b=core()
    row=c.execute('SELECT body FROM bot_ref_welcomes WHERE uid=%s',(uid,)).fetchone()
    text=('✉️ <b>Твоё приветственное сообщение</b>\n\n'
          'Его увидят новые участники, которые впервые запустят бота по твоей партнёрской ссылке. '
          'Расскажи о команде, помоги освоиться или добавь ссылку на свой проект.\n\n'
          '🎁 <b>Функция бесплатная.</b> Текст можно менять в любое время.\n\n'
          '<b>Текущий текст:</b>\n'+(esc(row['body']) if row else '<i>Ещё не добавлен</i>'))
    buttons=[[b.button('✏️ Изменить текст','welcome:edit')]]
    if row:
        buttons+=[[b.button('👁 Предпросмотр','welcome:preview'),b.button('🗑 Удалить','welcome:delete')]]
    buttons+=[[b.button('⬅️ Партнёры','friends')]]
    return screen(uid,text,buttons)


def route(c,uid,text,action,message):
    b=core()
    cmd=text.split(maxsplit=1)[0].split('@')[0] if text else ''
    if cmd in ('/start','/menu','/help') and text!='/start wallet':
        b.state(c,uid,'clear')
        return home(c,uid,bool(message.get('_new_referral')))
    if action=='quests':
        b.state(c,uid,'clear')
        return screen(uid,'⭐ <b>Квесты готовятся</b>\n\nПока выбирай задания, получай ежедневную награду и приглашай друзей.',
                      [[b.button('🚀 К заданиям','earn')]])
    if action.startswith('top:'):
        period=action.split(':',1)[1]
        if period not in ('all','today'):
            raise b.UserError('Такого рейтинга нет.')
        b.state(c,uid,'clear')
        return leaderboard(c,uid,period)
    if action=='welcome':
        b.state(c,uid,'clear')
        return welcome(c,uid)
    if action=='welcome:edit':
        b.state(c,uid,'welcome_edit')
        return screen(uid,'✏️ <b>Новое приветствие</b>\n\nПришли текст от 1 до 500 символов. Можно добавить ссылки.\n/cancel — отмена.')
    if action=='welcome:preview':
        row=c.execute('SELECT body FROM bot_ref_welcomes WHERE uid=%s',(uid,)).fetchone()
        if not row:
            raise b.UserError('Сначала добавь текст приветствия.')
        return screen(uid,'👁 <b>Так увидит сообщение новый участник</b>\n\n'+esc(row['body']),
                      [[b.button('⬅️ К приветствию','welcome')]])
    if action=='welcome:delete':
        c.execute('DELETE FROM bot_ref_welcomes WHERE uid=%s',(uid,))
        b.state(c,uid,'clear')
        return welcome(c,uid)
    if action.startswith('welcome:save:'):
        current=b.state(c,uid)
        if not current or current['state']!='welcome_confirm' or current['data'].get('nonce')!=action.split(':')[-1]:
            raise b.UserError('Эта кнопка устарела. Снова открой редактирование приветствия.')
        c.execute('INSERT INTO bot_ref_welcomes VALUES(%s,%s,%s) ON CONFLICT(uid) DO UPDATE SET body=EXCLUDED.body,updated=EXCLUDED.updated',
                  (uid,current['data']['body'],time.time()))
        b.state(c,uid,'clear')
        return welcome(c,uid)
    return None


def input_text(c,uid,text,message,current):
    b=core()
    if current['state']=='welcome_confirm':
        return screen(uid,'Нажми «Сохранить» под предпросмотром или отправь /cancel.')
    if (not 1<=len(text)<=500 or any(ord(ch)<32 and ch not in '\n\t' for ch in text)
            or message.get('photo') or message.get('document') or message.get('forward_origin') or message.get('media_group_id')):
        raise b.UserError('Пришли свой текст от 1 до 500 символов, одним сообщением.')
    data={'body':text,'nonce':uuid.uuid4().hex[:12]}
    b.state(c,uid,'welcome_confirm',data)
    return screen(uid,'✉️ <b>Проверь приветствие</b>\n\n'+esc(text),
                  [[b.button('✅ Сохранить','welcome:save:'+data['nonce']),b.button('✏️ Изменить','welcome:edit')],
                   [b.button('Отмена','cancel_input')]])
