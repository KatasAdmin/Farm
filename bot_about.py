"""Public information, measured statistics and owner-managed Telegram links."""
import datetime as dt
import re
import time
import uuid
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

LINKS={'news':'♻️ Канал новостей','payouts':'💸 Выплаты','chat':'❤️ Наш чат','admin_url':'👨‍💻 Администратор'}


def core():
    import task_bot
    return task_bot


def initialize(c):
    c.execute("""CREATE TABLE IF NOT EXISTS bot_public_info(id integer PRIMARY KEY CHECK(id=1),
      started double precision NOT NULL,news text NOT NULL DEFAULT '',payouts text NOT NULL DEFAULT '',
      chat text NOT NULL DEFAULT '',admin_url text NOT NULL DEFAULT '')""")
    first=c.execute('SELECT min(created) AS first_at FROM bot_accounts').fetchone()['first_at']
    c.execute('INSERT INTO bot_public_info(id,started) VALUES(1,%s) ON CONFLICT DO NOTHING',
              (first if first is not None else time.time(),))


def settings(c):
    return c.execute('SELECT * FROM bot_public_info WHERE id=1').fetchone()


def home(c,uid):
    b=core()
    cfg=settings(c)
    def link(key):
        return {'text':LINKS[key],'url':cfg[key]} if cfg[key] else b.button(LINKS[key],'about:'+key)
    return b.bot_ui.screen(uid,'📚 <b>Информация о нашем боте</b>\n\n'
        '🌾 <b>Farm · Новая жизнь</b>\n'
        'Задания, продвижение проектов и ферма в одном месте.\n\n'
        '🚀 Выполняй задания\n📣 Продвигай свой проект\n🤝 Собирай команду\n🎮 Развивай ферму',[
        [b.button('📊 Статистика','about:stats')],
        [link('news'),link('payouts')],
        [link('chat'),b.button('📋 Правила бота','about:rules')],
        [link('admin_url')]])


def statistics(c,uid):
    b=core(); ui=b.bot_ui
    today=dt.datetime.fromtimestamp(time.time(),ZoneInfo('Europe/Kyiv'))
    start,end=ui.today_bounds(today)
    cfg=settings(c)
    since=dt.datetime.fromtimestamp(cfg['started'],ZoneInfo('Europe/Kyiv')).date()
    days=max(1,(today.date()-since).days+1)
    total=c.execute('SELECT count(*) AS n FROM bot_accounts').fetchone()['n']
    new=c.execute('SELECT count(*) AS n FROM bot_accounts WHERE created>=%s AND created<%s',(start,end)).fetchone()['n']
    paid={r['kind']:r['n'] for r in c.execute("""SELECT t.kind,count(*) AS n FROM bot_claims x
      JOIN bot_tasks t ON t.id=x.task WHERE x.status='paid' GROUP BY t.kind""").fetchall()}
    active={r['kind']:r['n'] for r in c.execute('SELECT t.kind,count(*) AS n FROM bot_tasks t WHERE '+
                                             ui.active_order_filter()+' GROUP BY t.kind').fetchall()}
    payouts=c.execute("SELECT coalesce(sum(amount),0) AS n FROM bot_payouts WHERE status='paid'").fetchone()['n']
    daily=c.execute('SELECT coalesce(sum(amount),0) AS n FROM bot_daily_claims').fetchone()['n']
    text=(f'📊 <b>Статистика нашего бота</b>\n\n'
          f'⏱ Работаем дней: <b>{days}</b>\n'
          f'📅 Отсчёт с: <b>{since.strftime("%d.%m.%Y")}</b>\n'
          f'👥 Всего пользователей: <b>{total}</b>\n'
          f'🆕 Новых за сегодня: <b>{new}</b>\n\n'
          '<b>✅ Оплаченные выполнения</b>\n'
          f'📣 Подписок на каналы: <b>{paid.get("channel",0)}</b>\n'
          f'👥 Вступлений в группы: <b>{paid.get("group",0)}</b>\n'
          f'👁 Наград за посты: <b>{paid.get("post",0)}</b>\n'
          f'🤖 Заданий на ботов: <b>{paid.get("bot",0)}</b>\n'
          f'📝 Ручных заданий: <b>{paid.get("manual",0)}</b>\n\n'
          '<b>📣 Доступные заказы</b>\n'
          f'📣 На каналы: <b>{active.get("channel",0)}</b>\n'
          f'👁 На посты: <b>{active.get("post",0)}</b>\n'
          f'👥 На группы: <b>{active.get("group",0)}</b>\n'
          f'🤖 На ботов: <b>{active.get("bot",0)}</b>\n'
          f'📝 Ручные задания: <b>{active.get("manual",0)}</b>\n'
          '⭐ Квесты: <i>готовятся</i>\n\n'
          f'🎁 Ежедневных наград начислено: <b>{b.money(daily)}</b>\n'
          f'💸 Выплачено всего: <b>{b.money(payouts)}</b>\n\n'
          f'<i>Обновлено: {today.strftime("%d.%m.%Y %H:%M")} · Киев</i>')
    return ui.screen(uid,text,[[b.button('🔄 Обновить','about:stats')],[b.button('⬅️ О боте','about')]])


def rules(c,uid):
    b=core()
    return b.bot_ui.screen(uid,'📋 <b>Правила и работа бота</b>\n\n'
        '💰 <b>Единый баланс в гривнах</b>\nЗаработок можно использовать для заказов или подать на ручную выплату. Stars и монеты фермы учитываются отдельно.\n\n'
        '✅ <b>Задания</b>\nНаграда выдаётся после проверки, один раз за выполнение. Подписки проверяются автоматически, ручные доказательства — рекламодателем. '
        'Для задания на бота нужна пересылка свежего ответа. Для поста оплачивается кнопка награды под исходной публикацией.\n\n'
        '📣 <b>Продвижение</b>\nПолная стоимость резервируется при подтверждении заказа. Публикация после модерации. Неиспользованный остаток возвращается при закрытии заказа.\n\n'
        '⏳ <b>Срок подписки и штраф</b>\nСрок, награда и штраф указаны в карточке до взятия задания. Эти условия сохраняются для твоего выполнения. '
        'Добровольный выход раньше срока приводит к указанному штрафу; рекламодателю возвращается полная цена выполнения, реферальные начисления сохраняются. '
        'Если денег не хватает, долг погашается из следующих поступлений. Исключение администратором и сбой проверки не вызывают автоматический штраф.\n\n'
        '🎁 <b>Ежедневная награда</b>\nПолучить можно один раз за календарный день по Киеву.\n\n'
        '💸 <b>Выплаты</b>\nЗаявку проверяет администратор, перевод выполняется вручную. Ожидающую заявку можно отменить в кабинете.\n\n'
        '🔐 Не отправляй CVV, PIN, пароли и коды подтверждения.',[
        [b.button('👨‍💻 Задать вопрос','about:admin_url')],[b.button('⬅️ О боте','about')]])


def route(c,uid,text,action):
    b=core()
    if text!='📚 О боте' and action!='about' and not action.startswith('about:'):
        return None
    b.state(c,uid,'clear')
    if text=='📚 О боте' or action=='about':
        return home(c,uid)
    key=action.split(':',1)[1]
    if key=='stats':
        return statistics(c,uid)
    if key=='rules':
        return rules(c,uid)
    if key=='admin_url':
        cfg=settings(c)
        if cfg['admin_url']:
            return b.bot_ui.screen(uid,'👨‍💻 <b>Связь с администратором</b>',[
                [{'text':'Написать администратору','url':cfg['admin_url']}],[b.button('⬅️ О боте','about')]])
        b.state(c,uid,'public_support')
        return b.bot_ui.input_screen(uid,'👨‍💻 <b>Связь с администрацией</b>\n\n'
            'Напиши свой вопрос одним текстовым сообщением. Он попадёт в обращения, ответ придёт в этот чат.\n'
            'Не отправляй пароли, CVV и коды.',cancel_action='about')
    if key in ('news','chat','payouts'):
        cfg=settings(c)
        if cfg[key]:
            return b.bot_ui.screen(uid,LINKS[key],[[{'text':'Открыть','url':cfg[key]}],[b.button('⬅️ О боте','about')]])
        if key=='payouts':
            row=c.execute("SELECT count(*) AS n,coalesce(sum(amount),0) AS amount FROM bot_payouts WHERE status='paid'").fetchone()
            message=f"💸 <b>Выплаты нашего бота</b>\n\n✅ Выполнено выплат: <b>{row['n']}</b>\n💰 Выплачено: <b>{b.money(row['amount'])}</b>\n\nКанал с публикациями выплат пока не подключён."
        else:
            message=LINKS[key]+'\n\n'+('Канал новостей' if key=='news' else 'Чат сообщества')+' пока не подключён.'
        return b.bot_ui.screen(uid,message,[[b.button('⬅️ О боте','about')]])
    raise b.UserError('Раздел не найден.')


def support(c,uid,text,message):
    b=core()
    if not 1<=len(text)<=1500 or message.get('photo') or message.get('document') or message.get('forward_origin') or '\x00' in text:
        raise b.UserError('Напиши вопрос своим текстом, одним сообщением до 1500 символов.')
    ticket=uuid.uuid4().hex[:12]
    name=c.execute('SELECT name FROM bot_accounts WHERE uid=%s',(uid,)).fetchone()['name']
    c.execute('INSERT INTO support_tickets(id,telegram_id,nickname,message,created) VALUES(%s,%s,%s,%s,%s)',
              (ticket,uid,name,text,time.time()))
    b.state(c,uid,'clear')
    return b.bot_ui.screen(uid,'📨 <b>Вопрос передан администрации</b>\n\nНомер обращения: <code>'+ticket+'</code>\nОтвет придёт в этот чат.',
                           [[b.button('⬅️ О боте','about')]])


def normalize_link(text):
    if text=='-':
        return ''
    if text.startswith('@'):
        text='https://t.me/'+text[1:]
    url=urlsplit(text)
    if (len(text)>250 or url.scheme!='https' or url.hostname not in ('t.me','telegram.me') or url.username or url.password
            or url.port or url.query or url.fragment or not re.fullmatch(r'/(?:[A-Za-z0-9_]{3,32}(?:/\d+)?|\+[A-Za-z0-9_-]{5,}|joinchat/[A-Za-z0-9_-]{5,})/?',url.path)):
        raise core().UserError('Укажи @имя или HTTPS-ссылку на Telegram. Минус (-) убирает ссылку.')
    return 'https://t.me/'+url.path.strip('/')


def admin(c,uid,action):
    b=core(); ui=b.bot_ui
    if action=='admin:about':
        cfg=settings(c)
        since=dt.datetime.fromtimestamp(cfg['started'],ZoneInfo('Europe/Kyiv')).strftime('%d.%m.%Y')
        text='📚 <b>Настройки раздела «О боте»</b>\n\n'+''.join(
            LINKS[k]+': '+(ui.esc(cfg[k]) if cfg[k] else '<i>не подключено</i>')+'\n' for k in LINKS)
        text+='\n📅 Дата отсчёта: '+since+'\n\nБез прямого контакта администратора кнопка открывает обращение внутри бота.'
        return ui.screen(uid,text,[
            [b.button('♻️ Новости','admin:aboutedit:news'),b.button('💸 Выплаты','admin:aboutedit:payouts')],
            [b.button('❤️ Чат','admin:aboutedit:chat'),b.button('👨‍💻 Контакт','admin:aboutedit:admin_url')],
            [b.button('📅 Дата отсчёта','admin:aboutedit:started')],
            [b.button('⬅️ Управление ботом','admin')]])
    if action.startswith('admin:aboutedit:'):
        field=action.split(':')[-1]
        if field not in (*LINKS,'started'):
            raise b.UserError('Неизвестная настройка.')
        b.state(c,uid,'about_edit',{'field':field})
        prompt=('Введи дату запуска в формате ГГГГ-ММ-ДД. Она не может быть в будущем.' if field=='started'
                else 'Пришли @имя или ссылку на нужный Telegram-канал/чат/контакт. Минус (-) уберёт ссылку.')
        return ui.input_screen(uid,'✏️ <b>Изменить настройку</b>\n\n'+prompt)
    return None


def edit(c,uid,text,data):
    b=core(); field=data['field']; before=settings(c)
    if field=='started':
        try:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}",text):
                raise ValueError
            day=dt.date.fromisoformat(text)
            today=dt.datetime.now(ZoneInfo('Europe/Kyiv')).date()
            if not dt.date(2000,1,1)<=day<=today:
                raise ValueError
        except ValueError:
            raise b.UserError('Нужна дата от 2000-01-01 до сегодняшнего дня, в формате ГГГГ-ММ-ДД.')
        value=dt.datetime.combine(day,dt.time(),tzinfo=ZoneInfo('Europe/Kyiv')).timestamp()
        c.execute('UPDATE bot_public_info SET started=%s WHERE id=1',(value,))
    elif field in LINKS:
        try:
            value=normalize_link(text)
        except ValueError:
            raise b.UserError('Некорректная Telegram-ссылка.')
        # Column names come only from the fixed allowlist above.
        c.execute('UPDATE bot_public_info SET '+field+'=%s WHERE id=1',(value,))
    else:
        raise b.UserError('Неизвестная настройка.')
    c.execute("INSERT INTO bot_ledger VALUES(%s,%s,0,'public_info_config',%s,%s)",
              (uuid.uuid4().hex,uid,field+': '+str(before[field])+' → '+str(value),time.time()))
    b.state(c,uid,'clear')
    return admin(c,uid,'admin:about')
