"""Task marketplace and UAH wallet in the existing farm bot.

All monetary values are integer kopecks. Telegram Stars are kept separate.
One transaction stores both the operation and its replayable webhook response.
"""
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
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit
from psycopg.types.json import Jsonb

log = logging.getLogger("farm.tasks")
MENU = [["🚀 Заработать", "📣 Продвижение"],
        ["🎮 Игры", "👤 Мой кабинет"], ["👥 Партнёры", "📚 О боте"]]
KINDS = {"bot": "🤖 Боты", "channel": "📣 Каналы", "group": "👥 Группы", "post": "👁 Посты", "manual": "📝 Задания"}
LOCK = 1984534


class UserError(Exception):
    pass


def amount(text):
    if not re.fullmatch(r"\d{1,7}([.,]\d{1,2})?", text.strip()):
        raise UserError("Укажи сумму в гривнах, например 5 или 0,50. Максимум два знака после запятой.")
    try:
        n = int(Decimal(text.replace(",", ".")) * 100)
    except (InvalidOperation, ValueError):
        raise UserError("Некорректная сумма.")
    if not 1 <= n <= 100_000_000:
        raise UserError("Допустимая сумма: от 0,01 до 1 000 000 грн.")
    return n


def money(n):
    return f"{int(n) // 100},{int(n) % 100:02d} грн"


def member(info):
    return info.get("status") in ("creator", "administrator", "member") or (
        info.get("status") == "restricted" and info.get("is_member") is True)


def initialize(c):
    statements = [
        """CREATE TABLE IF NOT EXISTS bot_accounts(
          uid bigint PRIMARY KEY CHECK(uid>0), name text NOT NULL,
          available bigint NOT NULL DEFAULT 0 CHECK(available>=0),
          referrer bigint, created double precision NOT NULL)""",
        "ALTER TABLE bot_accounts ADD COLUMN IF NOT EXISTS advertising bigint NOT NULL DEFAULT 0 CHECK(advertising>=0)",
        """CREATE TABLE IF NOT EXISTS bot_cash_pool(
          id integer PRIMARY KEY CHECK(id=1), amount bigint NOT NULL DEFAULT 0 CHECK(amount>=0))""",
        "INSERT INTO bot_cash_pool(id) VALUES(1) ON CONFLICT DO NOTHING",
        """CREATE TABLE IF NOT EXISTS bot_ledger(
          id text PRIMARY KEY,uid bigint NOT NULL,delta bigint NOT NULL,kind text NOT NULL,
          details text NOT NULL,created double precision NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS bot_ledger_user ON bot_ledger(uid,created)",
        """CREATE TABLE IF NOT EXISTS bot_receipts(
          event text PRIMARY KEY,response jsonb NOT NULL,created double precision NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS bot_states(
          uid bigint PRIMARY KEY,state text NOT NULL,data jsonb NOT NULL,updated double precision NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS bot_tasks(
          id text PRIMARY KEY,owner bigint NOT NULL,kind text NOT NULL,title text NOT NULL,
          description text NOT NULL,url text NOT NULL,chat_id bigint,
          reward bigint NOT NULL CHECK(reward>0),remaining bigint NOT NULL CHECK(remaining>=0),
          status text NOT NULL CHECK(status IN ('pending','active','closed','rejected')),
          created double precision NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS bot_tasks_catalog ON bot_tasks(status,kind,created)",
        """CREATE TABLE IF NOT EXISTS bot_claims(
          task text NOT NULL,uid bigint NOT NULL,status text NOT NULL,
          proof text NOT NULL DEFAULT '',photo text NOT NULL DEFAULT '',created double precision NOT NULL,
          PRIMARY KEY(task,uid))""",
        """CREATE TABLE IF NOT EXISTS bot_payouts(
          id text PRIMARY KEY,uid bigint NOT NULL,amount bigint NOT NULL CHECK(amount>0),
          destination text NOT NULL,status text NOT NULL CHECK(status IN ('pending','paid','rejected','cancelled')),
          reference text NOT NULL DEFAULT '',created double precision NOT NULL)""",
        "CREATE UNIQUE INDEX IF NOT EXISTS bot_one_pending_payout ON bot_payouts(uid) WHERE status='pending'",
        """CREATE TABLE IF NOT EXISTS bot_deposits(
          reference text PRIMARY KEY,uid bigint NOT NULL,amount bigint NOT NULL CHECK(amount>0),created double precision NOT NULL)""",
    ]
    for sql in statements:
        c.execute(sql)
    bot_extras.initialize(c)
    bot_economy.initialize(c)
    bot_ui.initialize(c)
    bot_about.initialize(c)
    bot_topups.initialize(c)
    c.execute("SELECT pg_advisory_xact_lock(1984533)")
    c.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK,))
    unify_balances(c)


def unify_balances(c, uid=None):
    # Preserve every kopeck, including balances written by a retiring old instance.
    sql = "SELECT uid,advertising FROM bot_accounts WHERE advertising>0"
    rows = c.execute(sql + (" AND uid=%s" if uid is not None else "") + " FOR UPDATE",
                     (uid,) if uid is not None else ()).fetchall()
    for row in rows:
        c.execute("UPDATE bot_accounts SET available=available+advertising,advertising=0 WHERE uid=%s", (row["uid"],))
        c.execute("INSERT INTO bot_ledger VALUES(%s,%s,0,'wallet_unified',%s,%s)",
                  (uuid.uuid4().hex, row["uid"], "Объединение балансов: " + money(row["advertising"]), time.time()))


def state(c, uid, stage=None, data=None):
    if stage is None:
        return c.execute("SELECT state,data FROM bot_states WHERE uid=%s", (uid,)).fetchone()
    if stage == "clear":
        c.execute("DELETE FROM bot_states WHERE uid=%s", (uid,))
    else:
        c.execute("""INSERT INTO bot_states VALUES(%s,%s,%s,%s) ON CONFLICT(uid)
          DO UPDATE SET state=EXCLUDED.state,data=EXCLUDED.data,updated=EXCLUDED.updated""",
                  (uid, stage, Jsonb(data or {}), time.time()))


def say(uid, text, buttons=None):
    out = {"method": "sendMessage", "chat_id": uid, "text": text,
           "reply_markup": {"keyboard": MENU, "resize_keyboard": True,
                            "is_persistent": True, "one_time_keyboard": False}}
    if buttons is not None:
        out["reply_markup"] = {"inline_keyboard": buttons}
    return out


def button(text, action):
    return {"text": text, "callback_data": "bot:" + action}


def account(c, uid):
    unify_balances(c, uid)
    bot_economy.collect_debt(c, uid)
    return c.execute("SELECT * FROM bot_accounts WHERE uid=%s FOR UPDATE", (uid,)).fetchone()


def change(c, uid, delta, kind, details):
    row = c.execute("""UPDATE bot_accounts SET available=available+%s
      WHERE uid=%s AND available+%s>=0 RETURNING available""", (delta, uid, delta)).fetchone()
    if not row:
        raise UserError("Недостаточно средств на балансе.")
    c.execute("INSERT INTO bot_ledger VALUES(%s,%s,%s,%s,%s,%s)",
              (uuid.uuid4().hex, uid, delta, kind, details, time.time()))
    if delta > 0:
        bot_economy.collect_debt(c, uid)
    return c.execute("SELECT available FROM bot_accounts WHERE uid=%s", (uid,)).fetchone()["available"]


def liability(c):
    return c.execute("""SELECT
      (SELECT coalesce(sum(available+advertising),0) FROM bot_accounts) +
      (SELECT coalesce(sum(remaining),0) FROM bot_tasks WHERE status IN ('pending','active')) +
      (SELECT coalesce(sum(amount),0) FROM bot_payouts WHERE status='pending') +
      (CAST((SELECT coalesce(sum(units),0) FROM bot_ref_accruals) AS bigint)+9999)/10000 AS n""").fetchone()["n"]


def farm_url():
    domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "farm-web-production-cfb9.up.railway.app")
    return "https://" + domain + "/"


def cabinet(c, uid):
    a = account(c, uid)
    pending = c.execute("SELECT coalesce(sum(amount),0) AS n FROM bot_payouts WHERE uid=%s AND status='pending'", (uid,)).fetchone()["n"]
    frozen = c.execute("SELECT coalesce(sum(remaining),0) AS n FROM bot_tasks WHERE owner=%s AND status IN ('pending','active')", (uid,)).fetchone()["n"]
    earned = c.execute("SELECT coalesce(sum(delta),0) AS n FROM bot_ledger WHERE uid=%s AND kind='task_reward'", (uid,)).fetchone()["n"]
    bonuses = c.execute("SELECT coalesce(sum(delta),0) AS n FROM bot_ledger WHERE uid=%s AND kind IN ('daily_bonus','friend_reward','referral_reward')", (uid,)).fetchone()["n"]
    deposits = c.execute("SELECT coalesce(sum(delta),0) AS n FROM bot_ledger WHERE uid=%s AND kind IN ('manual_deposit','ads_manual_deposit','stars_wallet_deposit')", (uid,)).fetchone()["n"]
    paid = c.execute("SELECT coalesce(sum(amount),0) AS n FROM bot_payouts WHERE uid=%s AND status='paid'", (uid,)).fetchone()["n"]
    spent = c.execute("""SELECT coalesce(sum(coalesce(q.cost,t.reward)),0) AS n FROM bot_tasks t LEFT JOIN bot_task_terms q ON q.task=t.id JOIN bot_claims x
      ON x.task=t.id AND x.status='paid' WHERE t.owner=%s""", (uid,)).fetchone()["n"]
    spent -= c.execute("SELECT coalesce(sum(delta),0) AS n FROM bot_ledger WHERE uid=%s AND kind='retention_refund'", (uid,)).fetchone()['n']
    debt = c.execute("SELECT amount FROM bot_debts WHERE uid=%s", (uid,)).fetchone()
    debt = debt["amount"] if debt else 0
    state(c, uid, 'clear')
    debt_line = ('\n⚠️ Задолженность: '+money(debt)) if debt else ''
    text = (f"👤 <b>Мой кабинет</b>\n🆔 ID: <code>{uid}</code>\n\n"
            f"<b>💰 Доступный баланс: {money(a['available'])}</b>{debt_line}\n\n"
            "<b>📊 Статистика</b>\n"
            f"💳 Пополнений: {money(deposits)}\n📣 Потрачено на рекламу: {money(spent)}\n"
            f"💵 Заработано на заданиях: {money(earned)}\n🎁 Бонусы и рефералы: {money(bonuses)}\n\n"
            f"❄️ В бюджете заданий: {money(frozen)}\n⌛ Ожидает выплаты: {money(pending)}\n💸 Выведено всего: {money(paid)}")
    return bot_ui.screen(uid,text,[
        [button('➕ Пополнить','deposit'),button('💸 Вывести','withdraw')],
        [button('✅ Мои выполнения','claims')],
        [button('📥 Мои заявки','payouts'),button('📜 История','history')]])



def resolve_chat(api, target, kind):
    if re.fullmatch(r"-\d+", target):
        key = int(target)
    else:
        path = urlsplit(target if "://" in target else "https://t.me/" + target.lstrip("@"))
        if path.scheme != "https" or path.hostname not in ("t.me", "telegram.me") or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{3,31}", path.path.strip("/")):
            raise UserError("Укажи публичную ссылку https://t.me/имя или числовой ID чата. Для закрытого чата сначала добавь нашего бота администратором.")
        key = "@" + path.path.strip("/")
    info = api("getChat", {"chat_id": key})
    types = ("channel",) if kind == "channel" else ("group", "supergroup")
    if info.get("type") not in types:
        raise UserError("Тип чата не соответствует заданию.")
    me = api("getMe", {})
    own = api("getChatMember", {"chat_id": info["id"], "user_id": me["id"]})
    if own.get("status") not in ("administrator", "creator"):
        raise UserError("Добавь @Farmlife2026bot администратором этого канала/группы, затем повтори.")
    link = "https://t.me/" + info["username"] if info.get("username") else info.get("invite_link")
    if not link:
        raise UserError("Не удалось получить ссылку на закрытый чат. Выдай боту право приглашать участников.")
    return info["id"], link


def task_card(t, uid, c):
    if t['kind'] == 'bot':
        return say(uid, f"🤖 {t['title']}\n\n{t['description']}\n\nНаграда: {money(t['reward'])}\nВозьми задание, запусти бота и перешли сюда свежий ответ от него. Это проверка источника пересылки, не гарантия первого запуска. Не пересылай пароли и коды.", [
            [{"text": "Перейти к боту", "url": t['url']}],
            [button("Взять / отправить пересылку", "take:" + t['id'])],
            [button("Пропустить", "skip_bot")]])
    return say(uid, f"{t['title']}\n\n{t['description']}\n\nНаграда: {money(t['reward'])}" + bot_economy.rule_text(c, t), [
        [{"text": "Открыть", "url": t["url"]}],
        [button("Взять задание", "take:" + t["id"]), button("Проверить", "check:" + t["id"])],
        [button("⬅️ Задания", "earn")]])


def award(c, t, uid):
    claim = c.execute("SELECT * FROM bot_claims WHERE task=%s AND uid=%s FOR UPDATE", (t["id"], uid)).fetchone()
    if not claim or claim["status"] not in ("started", "review"):
        raise UserError("Заявка уже обработана или задание не взято.")
    gross = bot_economy.cost(c, t)
    if t["status"] != "active" or t["remaining"] < gross:
        raise UserError("Бюджет задания закончился. Награда не списана.")
    c.execute("UPDATE bot_tasks SET remaining=remaining-%s WHERE id=%s", (gross, t["id"]))
    c.execute("UPDATE bot_claims SET status='paid' WHERE task=%s AND uid=%s", (t["id"], uid))
    change(c, uid, t["reward"], "task_reward", "Задание " + t["id"])
    bot_economy.settle(c, t, uid, time.time())


def _admin_input(db, uid):
    with db() as c:
        row = state(c, uid)
        return bool(row and row['state'] in ('economy_edit','about_edit','topup_config','topup_bank_reference','topup_bank_confirm'))


def handle(payload, db, api, is_admin):
    """Return None for legacy farm/payment/support messages, else webhook response."""
    payment = bot_topups.payment(payload,db)
    if payment is not None:
        return payment
    retained = bot_economy.member_update(payload, db)
    if retained is not None:
        return retained
    callback = payload.get("callback_query") or {}
    message = callback.get("message") or payload.get("message") or {}
    if payload.get("pre_checkout_query") or message.get("successful_payment"):
        return None
    sender = callback.get("from") or message.get("from") or {}
    uid = sender.get("id")
    chat = message.get("chat") or {}
    action = callback.get("data", "")
    channel_claim = bool(callback and action.startswith("bot:postclaim:"))
    if not isinstance(uid, int) or isinstance(uid, bool) or uid <= 0 or sender.get('is_bot'):
        return None
    if not channel_claim and (chat.get("id") != uid or chat.get("type") != "private"):
        return None
    if channel_claim:
        message = dict(message, _callback_id=callback['id'])
    # A channel post or forwarded bot response is evidence, never a command.
    text = "" if callback or message.get("forward_origin") else (message.get("text") or "").strip()
    cmd = text.split(maxsplit=1)[0].split("@")[0] if text else ""
    legacy = {"/admin", "/requests", "/zayavki", "/tickets", "/stars", "/paysupport", "/support", "/reply"}
    if callback and not action.startswith("bot:"):
        return None
    if not callback and (cmd in legacy or text.startswith("/start link_") or text == "/start support"):
        return None
    event = ("callback:" + str(callback["id"])) if callback.get("id") else ("message:" + str(uid) + ":" + str(message.get("message_id")))
    if not callback and not isinstance(message.get("message_id"), int):
        return None
    admin = is_admin(uid, uid) if (action.startswith("bot:admin") or cmd.startswith("/bot") or (text and _admin_input(db, uid))) else False
    try:
        with db() as c:
            # Farm trade lock first, then wallet lock: consistent order across transfers.
            c.execute("SELECT pg_advisory_xact_lock(1984533)")
            c.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK,))
            old = c.execute("SELECT response FROM bot_receipts WHERE event=%s", (event,)).fetchone()
            if old:
                return old["response"]
            if channel_claim and not account(c, uid):
                return {"method": "answerCallbackQuery", "callback_query_id": callback['id'], "text": "Сначала открой @Farmlife2026bot и нажми /start, затем вернись к посту.", "show_alert": True}
            ref = None
            if text.startswith("/start partner_"):
                raw = text.split("partner_", 1)[1]
                if raw.isdecimal() and len(raw)<=19 and 0<int(raw)<=9223372036854775807 and int(raw) != uid:
                    ref = c.execute("SELECT uid FROM bot_accounts WHERE uid=%s", (int(raw),)).fetchone()
            is_new = not c.execute("SELECT 1 FROM bot_accounts WHERE uid=%s", (uid,)).fetchone()
            c.execute("""INSERT INTO bot_accounts(uid,name,referrer,created) VALUES(%s,%s,%s,%s)
              ON CONFLICT(uid) DO UPDATE SET name=EXCLUDED.name""",
                      (uid, str(sender.get("first_name") or "Игрок")[:100], ref["uid"] if ref else None, time.time()))
            unify_balances(c, uid)
            message = dict(message, _new_referral=bool(is_new and ref and text.startswith("/start partner_")))
            # A savepoint rolls back every partial mutation on a user-facing validation error.
            try:
                with c.transaction():
                    response = route(c, uid, text, action[4:] if callback else "", message, api, admin)
            except UserError as error:
                response = ({"method": "answerCallbackQuery", "callback_query_id": callback['id'], "text": str(error)[:200], "show_alert": True}
                            if channel_claim else say(uid, str(error)))
            c.execute("INSERT INTO bot_receipts VALUES(%s,%s,%s)", (event, Jsonb(response), time.time()))
    except Exception:
        # Do not acknowledge processing failures: Telegram will retry the same update.
        log.exception("task_bot_update_failed")
        raise
    bot_extras.deliver_posts(db, api)
    if callback.get("id") and response.get('method') != 'answerCallbackQuery':
        try:
            api("answerCallbackQuery", {"callback_query_id": callback["id"]})
        except Exception:
            log.warning("task_bot_callback_ack_failed")
    return response


def route(c, uid, text, action, message, api, admin):
    cmd = text.split(maxsplit=1)[0].split("@")[0] if text else ""
    if action.startswith("admin") or cmd.startswith("/bot"):
        if not admin:
            return say(uid, "Доступ только администратору.")
        return administration(c, uid, text, action, api)
    extra = bot_extras.route(c, uid, text, action, message, api)
    if extra is not None:
        return extra
    presentation = bot_ui.route(c, uid, text, action, message)
    if presentation is not None:
        return presentation
    public = bot_about.route(c,uid,text,action)
    if public is not None:
        return public
    topup = bot_topups.route(c,uid,action)
    if topup is not None:
        return topup
    if action in ('history','claims','payouts','games'):
        state(c,uid,'clear')
    if action == "cancel_input":
        state(c, uid, "clear")
        return say(uid, "Действие отменено. Выбери раздел в меню внизу.")
    if action.startswith(("confirm_task:", "confirm_payout:")):
        return confirmation(c, uid, action)
    if text in sum(MENU, []) or cmd in ("/start", "/help", "/menu", "/cancel"):
        state(c, uid, "clear")
    if text == "🚀 Заработать" or action == "earn":
        return bot_ui.earn(c,uid)
    if text == "🎮 Игры" or action == "games":
        return say(uid, "🎮 Игры\nОткрой свою ферму:", [[{"text": "🌾 Ферма", "web_app": {"url": farm_url()}}]])
    if text in ("👤 Мой кабинет", "/start wallet") or action == "cabinet":
        return cabinet(c, uid)
    if text == "📣 Продвижение" or action == "promotion":
        return bot_ui.promotion(c,uid)
    if action in ("convert", "convert_to_ads", "convert_from_ads", "tofarm", "fromfarm"):
        state(c, uid, "clear")
        return cabinet(c, uid)
    if action == "history":
        rows = c.execute("SELECT delta,kind,details,created FROM bot_ledger WHERE uid=%s ORDER BY created DESC LIMIT 15", (uid,)).fetchall()
        return say(uid, "📜 Последние операции\n" + ("\n".join(("+" if r["delta"] >= 0 else "−") + money(abs(r["delta"])) + " · " + r["details"] for r in rows) or "Операций пока нет."))
    if action == "claims":
        rows = c.execute("""SELECT t.title,x.status FROM bot_claims x JOIN bot_tasks t ON t.id=x.task
          WHERE x.uid=%s ORDER BY x.created DESC LIMIT 15""", (uid,)).fetchall()
        labels = {"started": "В работе", "review": "На проверке", "paid": "Оплачено", "rejected": "Отклонено"}
        return say(uid, "✅ Мои выполнения\n" + ("\n".join(r["title"] + " · " + labels.get(r["status"], r["status"]) for r in rows) or "Пока нет взятых заданий."))
    if action == "payouts":
        rows = c.execute("SELECT id,amount,status FROM bot_payouts WHERE uid=%s ORDER BY created DESC LIMIT 10", (uid,)).fetchall()
        labels = {"pending": "На проверке", "paid": "Выплачено", "rejected": "Отклонено", "cancelled": "Отменено"}
        return say(uid, "📥 Заявки\n" + ("\n".join(r["id"][:8] + " · " + money(r["amount"]) + " · " + labels[r["status"]] for r in rows) or "Заявок пока нет."),
                   [[button("Отменить ожидающую заявку", "cancelpayout")]])
    if action == "cancelpayout":
        row = c.execute("UPDATE bot_payouts SET status='cancelled' WHERE uid=%s AND status='pending' RETURNING amount,id", (uid,)).fetchone()
        if not row:
            raise UserError("Нет ожидающей заявки.")
        change(c, uid, row["amount"], "payout_cancel", "Отмена " + row["id"][:8])
        return cabinet(c, uid)
    if action == "withdraw":
        state(c, uid, action)
        return say(uid, "Введи сумму в гривнах. Затем укажешь реквизиты для ручной выплаты.\n/cancel — отмена.")
    if action.startswith("new:"):
        kind = action.split(":")[1]
        if kind not in KINDS:
            raise UserError("Неизвестный тип задания.")
        if kind == 'post' and not bot_extras.settings(c)['channel_id']:
            raise UserError('Канал рекламных постов ещё не подключён администратором.')
        state(c, uid, "task_title", {"kind": kind})
        return say(uid, ("Пост появится в нашем канале после модерации. Оплачивается нажатие кнопки, а не доказанное прочтение.\n\n" if kind == "post" else "") + "Введи название задания (до 100 символов). /cancel — отмена.")
    if action.startswith(("list:", "mine:", "reviews:")):
        parts = action.split(":")
        try:
            offset = max(0, min(100000, int(parts[-1])))
        except ValueError:
            raise UserError("Некорректная страница.")
        if parts[0] == "reviews":
            rows = c.execute("""SELECT x.task,x.uid FROM bot_claims x JOIN bot_tasks t ON t.id=x.task
              WHERE t.owner=%s AND x.status='review' ORDER BY x.created LIMIT 8 OFFSET %s""", (uid, offset)).fetchall()
            buttons = [[button(f"Работа {r['uid']} · {r['task'][:6]}", f"review:{r['task']}:{r['uid']}")] for r in rows]
        elif parts[0] == "mine":
            rows = c.execute("SELECT * FROM bot_tasks WHERE owner=%s ORDER BY created DESC LIMIT 8 OFFSET %s", (uid, offset)).fetchall()
            buttons = [[button(f"{r['title'][:30]} · {r['status']}", "own:" + r["id"])] for r in rows]
        else:
            kind = parts[1]
            rows = c.execute('SELECT t.* FROM bot_tasks t WHERE '+bot_ui.catalog_filter()+
                             ' AND t.kind=%s ORDER BY t.created LIMIT 8 OFFSET %s', (uid,uid,uid,kind,offset)).fetchall()
            buttons = [[button(r["title"][:35] + " · " + money(r["reward"]), "task:" + r["id"])] for r in rows]
        if len(rows) == 8:
            buttons.append([button("Далее →", ":".join(parts[:-1]) + ":" + str(offset + 8))])
        if offset:
            buttons.append([button("← Назад", ":".join(parts[:-1]) + ":" + str(max(0, offset - 8)))])
        return say(uid, "Выбери:" if rows else "Пока ничего нет.", buttons + [[button("⬅️ Продвижение" if parts[0] != "list" else "⬅️ Заработать", "promotion" if parts[0] != "list" else "earn")]])
    if action.startswith(("task:", "take:", "check:", "own:", "close:", "review:", "accept:", "rejectwork:")):
        parts = action.split(":")
        t = c.execute("SELECT * FROM bot_tasks WHERE id=%s FOR UPDATE", (parts[1],)).fetchone()
        if not t:
            raise UserError("Задание не найдено.")
        op = parts[0]
        if op in ("own", "close", "review", "accept", "rejectwork"):
            if t["owner"] != uid:
                raise UserError("Это задание другого рекламодателя.")
            if op == "own":
                buttons = [[button("Закрыть и вернуть остаток", "close:" + t["id"])]]
                if t['kind'] == 'post':
                    publication = c.execute("SELECT url FROM bot_post_publications WHERE task=%s AND status='posted'", (t['id'],)).fetchone()
                    if publication:
                        buttons.insert(0, [{'text': 'Посмотреть опубликованный пост', 'url': publication['url']}])
                return say(uid, f"{t['title']}\nСтатус: {t['status']}\nНаграда: {money(t['reward'])}\nОстаток бюджета: {money(t['remaining'])}", buttons)
            if op == "close":
                if t['kind'] == 'post' and c.execute("SELECT 1 FROM bot_post_publications WHERE task=%s AND status IN ('sending','uncertain')", (t['id'],)).fetchone():
                    raise UserError('Сначала администратор должен проверить результат публикации поста.')
                if c.execute("SELECT 1 FROM bot_claims WHERE task=%s AND status='review'", (t["id"],)).fetchone():
                    raise UserError("Сначала проверь присланные работы.")
                refund = t["remaining"]
                c.execute("UPDATE bot_tasks SET status='closed',remaining=0 WHERE id=%s", (t["id"],))
                if refund:
                    change(c, uid, refund, "task_close", "Закрытие задания " + t["id"])
                return say(uid, "Задание закрыто. Возвращено: " + money(refund))
            try:
                worker = int(parts[2])
            except (IndexError, ValueError):
                raise UserError("Некорректный номер работы.")
            claim = c.execute("SELECT * FROM bot_claims WHERE task=%s AND uid=%s AND status='review'", (t["id"], worker)).fetchone()
            if not claim:
                raise UserError("Работа уже проверена.")
            if op == "review":
                buttons = [[button("✅ Принять", f"accept:{t['id']}:{worker}"), button("❌ Отклонить", f"rejectwork:{t['id']}:{worker}")]]
                if claim["photo"]:
                    return {"method": "sendPhoto", "chat_id": uid, "photo": claim["photo"], "caption": (t["title"] + "\nИгрок: " + str(worker) + "\n" + claim["proof"])[:1000], "reply_markup": {"inline_keyboard": buttons}}
                return say(uid, t["title"] + "\nИгрок: " + str(worker) + "\n\n" + claim["proof"], buttons)
            if op == "accept":
                award(c, t, worker)
                return say(uid, "Работа принята, награда начислена игроку.")
            c.execute("UPDATE bot_claims SET status='rejected' WHERE task=%s AND uid=%s", (t["id"], worker))
            return say(uid, "Работа отклонена. Начисления нет.")
        if t["status"] != "active" or t["remaining"] < bot_economy.cost(c, t) or t["owner"] == uid:
            raise UserError("Задание недоступно или бюджет исчерпан.")
        reserved = c.execute("SELECT count(*) AS n FROM bot_claims WHERE task=%s AND status='review'", (t["id"],)).fetchone()["n"]
        if t["remaining"] < (reserved + 1) * bot_economy.cost(c, t):
            raise UserError("Все места этого задания сейчас на проверке. Выбери другое задание.")
        if t['kind'] == 'post':
            publication = c.execute("SELECT url FROM bot_post_publications WHERE task=%s AND status='posted'", (t['id'],)).fetchone()
            return say(uid, 'Получить награду можно только кнопкой под исходным постом в нашем канале.',
                       [[{'text': 'Открыть пост', 'url': publication['url']}]] if publication else None)
        if op == "task":
            return task_card(t, uid, c)
        claim = c.execute("SELECT * FROM bot_claims WHERE task=%s AND uid=%s", (t["id"], uid)).fetchone()
        if claim and claim["status"] in ("paid", "rejected", "review"):
            raise UserError({"paid": "Награда уже получена.", "rejected": "Работа отклонена.", "review": "Работа ожидает ручной проверки."}[claim["status"]])
        if op in ('take','check') and t['kind'] in ('channel','group'):
            own = api('getMe', {})
            if api('getChatMember', {'chat_id':t['chat_id'],'user_id':own['id']}).get('status') not in ('administrator','creator'):
                raise UserError('Проверка временно недоступна: нашему боту нужны права администратора этого чата.')
        if op == "take":
            if t['kind'] in ('channel','group') and bot_economy.terms(c,t['id']):
                c.execute('INSERT INTO bot_membership_accept VALUES(%s,%s,%s) ON CONFLICT DO NOTHING', (t['id'],uid,time.time()))
            if not claim:
                if t["kind"] in ("channel", "group") and member(api("getChatMember", {"chat_id": t["chat_id"], "user_id": uid})):
                    raise UserError("Ты уже состоишь в этом канале/группе. Это задание для новых участников.")
                c.execute("INSERT INTO bot_claims(task,uid,status,created) VALUES(%s,%s,'started',%s)", (t["id"], uid, time.time()))
            if t['kind'] == 'bot':
                if c.execute('SELECT 1 FROM bot_bot_completions WHERE uid=%s AND bot_id=%s', (uid, t['chat_id'])).fetchone():
                    raise UserError('Ты уже получал награду за этого бота.')
                state(c, uid, 'bot_forward', {'task': t['id']})
            return task_card(t, uid, c)
        if not claim:
            raise UserError("Сначала нажми «Взять задание», затем выполни его и нажми «Проверить».")
        if t['kind'] == 'bot':
            state(c, uid, 'bot_forward', {'task': t['id']})
            return task_card(t, uid, c)
        if t["kind"] == "manual":
            state(c, uid, "proof", {"task": t["id"]})
            return say(uid, "Отправь доказательство выполнения: текст или одно фото с подписью. Проверит рекламодатель. /cancel — отмена.")
        if not member(api("getChatMember", {"chat_id": t["chat_id"], "user_id": uid})):
            raise UserError("Подписка пока не подтверждена. Вступи в канал/группу и повтори проверку.")
        award(c, t, uid)
        return say(uid, "✅ Проверка пройдена. Начислено " + money(t["reward"]))
    current = state(c, uid)
    if current:
        if current['state'] in ('topup_config','topup_bank_reference','topup_bank_confirm'):
            if not admin:
                raise UserError('Доступ только администратору.')
            return bot_topups.admin_input(c,uid,text,current)
        if current['state'] in ('topup_stars','topup_card_amount','topup_card_receipt'):
            return bot_topups.input_text(c,uid,text,message,current)
        if current['state']=='public_support':
            return bot_about.support(c,uid,text,message)
        if current['state']=='about_edit':
            if not admin:
                raise UserError('Доступ только администратору.')
            return bot_about.edit(c,uid,text,current['data'])
        if current["state"] in ("welcome_edit","welcome_confirm"):
            return bot_ui.input_text(c,uid,text,message,current)
        if current["state"] == "economy_edit":
            if not admin:
                raise UserError("Доступ только администратору.")
            return bot_economy.edit(c, uid, text, current["data"])
        return process_input(c, uid, text, message, current, api)
    return bot_ui.home(c,uid)


def process_input(c, uid, text, message, current, api):
    stage, data = current["state"], current["data"]
    if stage == 'task_bot_identity':
        return bot_extras.bot_identity(c, uid, message, data)
    if stage == 'bot_forward':
        return bot_extras.bot_completion(c, uid, message, data)
    if stage == 'bind_post':
        origin = message.get('forward_origin') or {}
        if origin.get('type') != 'channel' or (origin.get('chat') or {}).get('id') != data['channel'] or not isinstance(origin.get('message_id'), int):
            raise UserError('Перешли исходный пост именно из подключённого канала.')
        cfg = bot_extras.settings(c)
        c.execute("UPDATE bot_post_publications SET status='posted',message_id=%s,url=%s WHERE task=%s AND status IN ('sending','uncertain')",
                  (origin['message_id'], bot_extras.publication_url(data['channel'], origin['message_id'], cfg['channel_url']), data['task']))
        state(c, uid, 'clear')
        return say(uid, 'Пост привязан к заданию. Проверь, что кнопка получения награды стоит под правильным постом.')
    if stage in ("convert_to_ads", "convert_from_ads", "tofarm", "fromfarm"):
        state(c, uid, "clear")
        return cabinet(c, uid)
    if stage == "deposit":
        return bot_topups.menu(c,uid)
    if stage == "withdraw":
        n = amount(text)
        if n > account(c, uid)["available"]:
            raise UserError("Недостаточно средств.")
        if c.execute("SELECT 1 FROM bot_payouts WHERE uid=%s AND status='pending'", (uid,)).fetchone():
            raise UserError("Сначала дождись обработки предыдущей заявки или отмени её в кабинете.")
        state(c, uid, "destination", {"amount": n})
        return say(uid, "Укажи реквизиты для выплаты: номер карты или IBAN и имя получателя. Не отправляй CVV, PIN, пароли или коды.\n/cancel — отмена.")
    if stage == "destination":
        if not 8 <= len(text) <= 250:
            raise UserError("Реквизиты должны содержать от 8 до 250 символов.")
        data["destination"] = text
        data["nonce"] = uuid.uuid4().hex[:12]
        state(c, uid, "payout_confirm", data)
        return say(uid, f"Проверить заявку\nСумма: {money(data['amount'])}\nРеквизиты: {text}\n\nПосле подтверждения сумма будет зарезервирована до ручной выплаты.", [[button("✅ Подтвердить", "confirm_payout:" + data["nonce"]), button("Отмена", "cancel_input")]])
    if stage == "proof":
        photos = message.get("photo") or []
        proof = (text or message.get("text") or message.get("caption") or "").strip()
        if not proof and not photos:
            raise UserError("Отправь текст или фото, не документ и не альбом.")
        if message.get("media_group_id"):
            raise UserError("Пришли одно фото, не альбом.")
        if len(proof) > 1500:
            raise UserError("Сократи описание до 1500 символов.")
        t = c.execute("SELECT * FROM bot_tasks WHERE id=%s FOR UPDATE", (data["task"],)).fetchone()
        reviews = c.execute("SELECT count(*) AS n FROM bot_claims WHERE task=%s AND status='review'", (t["id"],)).fetchone()["n"] if t else 0
        if not t or t["status"] != "active" or t["remaining"] < (reviews + 1) * bot_economy.cost(c, t):
            raise UserError("Свободный бюджет задания закончился. Можно выбрать другое задание.")
        row = c.execute("""UPDATE bot_claims SET status='review',proof=%s,photo=%s
          WHERE task=%s AND uid=%s AND status='started' RETURNING uid""",
                        (proof, photos[-1]["file_id"] if photos else "", t["id"], uid)).fetchone()
        if not row:
            raise UserError("Работа уже отправлена или задание не взято.")
        state(c, uid, "clear")
        return say(uid, "Работа отправлена на ручную проверку. Результат и начисление появятся в кабинете.")
    if stage.startswith("task_"):
        if stage == "task_title":
            if not 3 <= len(text) <= 100:
                raise UserError("Название: от 3 до 100 символов.")
            data["title"] = text
            next_stage, prompt = "task_description", "Опиши, что нужно сделать (10–1000 символов). Для ручного задания укажи, какое доказательство прислать."
        elif stage == "task_description":
            if not 10 <= len(text) <= 1000:
                raise UserError("Описание: от 10 до 1000 символов.")
            data["description"] = text
            next_stage, prompt = "task_url", ("Добавь @Farmlife2026bot администратором канала/группы. Затем пришли ссылку или числовой ID. Права будут проверены автоматически."
                if data['kind'] in ('channel','group') else 'Пришли HTTPS-ссылку на бота/материал. Для поста без ссылки отправь минус (-).')
        elif stage == "task_url":
            if data['kind'] == 'bot':
                path = urlsplit(text)
                username = path.path.strip('/')
                if len(text)>400 or path.scheme!='https' or path.hostname!='t.me' or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{3,31}', username) or not username.lower().endswith('bot'):
                    raise UserError('Нужна ссылка https://t.me/ИмяБота, при необходимости с параметром start.')
                data['url'], data['bot_username'] = text, username
                data['chat_id'] = None
            elif data['kind'] == 'post' and text == '-':
                data['url'], data['chat_id'] = '', None
            elif data["kind"] in ("manual", "post"):
                parsed = urlsplit(text)
                if len(text) > 400 or parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                    raise UserError("Нужна корректная HTTPS-ссылка без паролей в адресе.")
                data["url"], data["chat_id"] = text, None
            else:
                try:
                    data["chat_id"], data["url"] = resolve_chat(api, text, data["kind"])
                except UserError:
                    raise
                except Exception:
                    raise UserError("Telegram не подтвердил доступ к чату. Проверь ссылку и права нашего бота.")
            if data['kind'] == 'manual':
                default = bot_economy.quote(c, 'manual')
                next_stage, prompt = 'task_reward', 'Укажи полную цену одного выполнения, включая комиссию. Например: ' + money(default['cost'])
            else:
                q = bot_economy.quote(c,data['kind'])
                data['terms'], data['reward'] = q, q['reward']
                next_stage, prompt = 'task_count', 'Цена выполнения: ' + money(q['cost']) + '. Награда исполнителю: ' + money(q['reward']) + '.\nНа сколько выполнений выделить бюджет? От 1 до 10000.' 
        elif stage == "task_reward":
            q = bot_economy.quote(c, data["kind"], amount(text))
            data["terms"], data["reward"] = q, q["reward"]
            next_stage, prompt = "task_count", "На сколько выполнений выделить бюджет? От 1 до 10000."
        elif stage == "task_count":
            if not text.isdecimal() or not 1 <= int(text) <= 10000:
                raise UserError("Укажи целое число от 1 до 10000.")
            total = data.get("terms", {}).get("cost", data["reward"]) * int(text)
            if total > account(c, uid)["available"]:
                raise UserError("На балансе не хватает средств. Пополни баланс либо укажи меньше выполнений.")
            data["budget"] = total
            data["nonce"] = uuid.uuid4().hex[:12]
            state(c, uid, "task_confirm", data)
            return say(uid, f"{data['title']}\nНаграда: {money(data['reward'])}\nВыполнений: {text}\nПолная цена выполнения: {money(data.get('terms',{}).get('cost',data['reward']))}\nБюджет: {money(total)}\nКомиссия уже включена в цену\n\nПосле подтверждения бюджет резервируется, задание отправляется на модерацию.", [[button("✅ Создать", "confirm_task:" + data["nonce"]), button("Отмена", "cancel_input")]])
        else:
            return say(uid, "Подтверди действие кнопкой выше или отправь /cancel.")
        state(c, uid, next_stage, data)
        return say(uid, prompt + "\n/cancel — отмена.")
    return say(uid, "Подтверди действие кнопкой выше или отправь /cancel.")


def confirmation(c, uid, action):
    current = state(c, uid)
    if not current:
        raise UserError("Действие уже выполнено или отменено.")
    data = current["data"]
    action, nonce = action.split(":", 1)
    if nonce != data.get("nonce"):
        raise UserError("Эта кнопка относится к другой заявке. Используй последнее подтверждение.")
    if action == "confirm_task" and current["state"] == "task_confirm":
        tid = uuid.uuid4().hex[:16]
        change(c, uid, -data["budget"], "task_budget", "Бюджет задания " + tid)
        c.execute("INSERT INTO bot_tasks(id,owner,kind,title,description,url,chat_id,reward,remaining,status,created) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,'pending',%s)",
                  (tid, uid, data["kind"], data["title"], data["description"], data["url"], data.get("chat_id"), data["reward"], data["budget"], time.time()))
        bot_economy.save_terms(c, tid, data)
        result = say(uid, "Задание " + tid + " создано и ожидает модерации. Бюджет зарезервирован.")
    elif action == "confirm_payout" and current["state"] == "payout_confirm":
        if c.execute("SELECT 1 FROM bot_payouts WHERE uid=%s AND status='pending'", (uid,)).fetchone():
            raise UserError("У тебя уже есть ожидающая заявка.")
        pid = uuid.uuid4().hex[:16]
        change(c, uid, -data["amount"], "payout_reserve", "Резерв заявки " + pid)
        c.execute("INSERT INTO bot_payouts(id,uid,amount,destination,status,created) VALUES(%s,%s,%s,%s,'pending',%s)",
                  (pid, uid, data["amount"], data["destination"], time.time()))
        result = say(uid, "Заявка " + pid + " принята. Зарезервировано " + money(data["amount"]) + ". Выплата выполняется администратором вручную.")
    else:
        raise UserError("Эта кнопка устарела.")
    state(c, uid, "clear")
    return result


def administration(c, uid, text, action, api):
    topup = bot_topups.admin(c,uid,action)
    if topup is not None:
        return topup
    public = bot_about.admin(c,uid,action)
    if public is not None:
        return public
    economy = bot_economy.admin(c, uid, text, action)
    if economy is not None:
        return economy
    extra = bot_extras.administration(c, uid, text, action, api)
    if extra is not None:
        return extra
    parts = text.split()
    command = parts[0].split("@")[0] if parts else ""
    if command in ("/botcredit", "/botfund", "/botpaid"):
        try:
            if command == "/botcredit":
                if len(parts) not in (4,5) or not parts[1].isdecimal() or not 3 <= len(parts[3]) <= 80 or (len(parts)==5 and parts[4] not in ('main','ads')):
                    raise UserError("Формат: /botcredit TelegramID Сумма УникальныйНомерПлатежа Только после фактического получения денег. Игрок должен открыть бота хотя бы раз.")
                target, n, ref = int(parts[1]), amount(parts[2]), parts[3]
                if not account(c, target):
                    raise UserError("Игрок ещё не зарегистрирован в боте.")
                inserted = c.execute("INSERT INTO bot_deposits VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING reference", (ref, target, n, time.time())).fetchone()
                if not inserted:
                    raise UserError("Такой платёж уже учтён. Повторного начисления нет.")
                c.execute("UPDATE bot_cash_pool SET amount=amount+%s WHERE id=1", (n,))
                # Legacy 'ads' argument is accepted but always credits the unified wallet.
                change(c, target, n, "manual_deposit", "Подтверждённый платёж " + ref)
                return say(uid, f"Зачислено {money(n)} пользователю {target} на единый баланс.")
            if command == "/botfund":
                if len(parts) != 3 or not 3 <= len(parts[2]) <= 80:
                    raise UserError("Формат: /botfund Сумма УникальныйНомерВзноса\nУчёт собственных денег, фактически выделенных на выплаты.")
                n, ref = amount(parts[1]), parts[2]
                if not c.execute("INSERT INTO bot_deposits VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING reference", (ref, uid, n, time.time())).fetchone():
                    raise UserError("Этот взнос уже учтён.")
                c.execute("UPDATE bot_cash_pool SET amount=amount+%s WHERE id=1", (n,))
                c.execute("INSERT INTO bot_ledger VALUES(%s,%s,0,'reserve_funding',%s,%s)", (uuid.uuid4().hex, uid, money(n) + " · " + ref, time.time()))
                return say(uid, "Резерв увеличен на " + money(n))
            if len(parts) != 3 or not 3 <= len(parts[2]) <= 80:
                raise UserError("Формат: /botpaid НомерЗаявки НомерБанковскойОперации\nТолько после фактической выплаты. Команда не переводит деньги.")
            p = c.execute("SELECT * FROM bot_payouts WHERE id=%s AND status='pending' FOR UPDATE", (parts[1],)).fetchone()
            if not p:
                raise UserError("Нет ожидающей заявки с таким номером.")
            state(c, uid, "admin_pay_confirm", {"id": p["id"], "reference": parts[2], "nonce": uuid.uuid4().hex[:12]})
            current = state(c, uid)
            return say(uid, f"Подтвердить фактическую выплату?\nЗаявка: {p['id']}\nПолучатель: {p['uid']}\nСумма: {money(p['amount'])}\nРеквизиты: {p['destination']}\nОперация: {parts[2]}", [[button("✅ Выплачено, подтвердить", "admin:payconfirm:" + current["data"]["nonce"]), button("Отмена", "admin:cancel")]])
        except (ValueError, IndexError):
            raise UserError("Некорректный формат команды. /botadmin — помощь.")
    if action == "admin:cancel":
        state(c, uid, "clear")
        return say(uid, "Подтверждение отменено.")
    if action.startswith("admin:payconfirm:"):
        current = state(c, uid)
        if not current or current["state"] != "admin_pay_confirm":
            raise UserError("Подтверждение устарело.")
        data = current["data"]
        if action.split(":")[-1] != data.get("nonce"):
            raise UserError("Подтверждение относится к другой выплате.")
        p = c.execute("SELECT * FROM bot_payouts WHERE id=%s AND status='pending' FOR UPDATE", (data["id"],)).fetchone()
        if not p:
            raise UserError("Заявка уже закрыта.")
        if c.execute("SELECT 1 FROM bot_payouts WHERE status='paid' AND reference=%s", (data["reference"],)).fetchone():
            raise UserError("Эта банковская операция уже использована для выплаты.")
        c.execute("UPDATE bot_payouts SET status='paid',reference=%s WHERE id=%s", (data["reference"], p["id"]))
        row = c.execute("UPDATE bot_cash_pool SET amount=amount-%s WHERE id=1 AND amount>=%s RETURNING amount", (p["amount"], p["amount"])).fetchone()
        if not row:
            raise UserError("Недостаточно учтённого резерва. Проверь учёт фактических поступлений.")
        c.execute("INSERT INTO bot_ledger VALUES(%s,%s,0,'payout_paid',%s,%s)", (uuid.uuid4().hex, p["uid"], "Выплачено " + money(p["amount"]) + " · " + p["id"], time.time()))
        state(c, uid, "clear")
        return say(uid, "Выплата подтверждена, заявка закрыта.")
    if action.startswith(("admin:approve:", "admin:rejecttask:")):
        op, tid = action.split(":")[1:]
        t = c.execute("SELECT * FROM bot_tasks WHERE id=%s AND status='pending' FOR UPDATE", (tid,)).fetchone()
        if not t:
            raise UserError("Задание уже прошло модерацию.")
        if op == "approve":
            if t['kind'] == 'post':
                bot_extras.queue_post(c, t, api)
            if t["kind"] in ("channel", "group"):
                me = api("getMe", {})
                info = api("getChatMember", {"chat_id": t["chat_id"], "user_id": me["id"]})
                if info.get("status") not in ("administrator", "creator"):
                    raise UserError("Сначала выдай нашему боту права администратора в целевом чате.")
            c.execute("UPDATE bot_tasks SET status='active' WHERE id=%s", (tid,))
            return say(uid, "Пост одобрен и поставлен в очередь публикации. Результат можно проверить в /botadmin → Проверить публикации." if t["kind"] == "post" else "Задание опубликовано.")
        c.execute("UPDATE bot_tasks SET status='rejected',remaining=0 WHERE id=%s", (tid,))
        change(c, t["owner"], t["remaining"], "task_rejected", "Отклонено модерацией " + tid)
        return say(uid, "Задание отклонено, бюджет возвращён.")
    if action.startswith("admin:rejectpayout:"):
        pid = action.split(":")[-1]
        p = c.execute("UPDATE bot_payouts SET status='rejected' WHERE id=%s AND status='pending' RETURNING *", (pid,)).fetchone()
        if not p:
            raise UserError("Заявка уже закрыта.")
        change(c, p["uid"], p["amount"], "payout_rejected", "Возврат по заявке " + pid)
        return say(uid, "Заявка отклонена, деньги возвращены на баланс.")
    if action == 'admin:postissues':
        rows = c.execute("SELECT task,status FROM bot_post_publications WHERE status IN ('sending','uncertain') LIMIT 8").fetchall()
        return say(uid, 'Если пост опубликован, привяжи его пересылкой. Если публикации нет — обратись к разработчику для проверки, не отправляй её повторно вслепую.',
                   [[button(r['task'] + ' · ' + r['status'], 'admin:bindpost:' + r['task'])] for r in rows])
    if action == "admin:tasks":
        rows = c.execute("SELECT * FROM bot_tasks WHERE status='pending' ORDER BY created LIMIT 1").fetchall()
        if not rows:
            return say(uid, "Нет заданий на модерации.")
        t = rows[0]
        return say(uid, f"Модерация {t['id']}\nАвтор: {t['owner']}\nТип: {t['kind']}\n{t['title']}\n{t['description']}\n{t['url']}\nНаграда: {money(t['reward'])}\nБюджет: {money(t['remaining'])}", [[button("✅ Опубликовать", "admin:approve:" + t["id"]), button("❌ Отклонить", "admin:rejecttask:" + t["id"])]])
    if action == "admin:payouts":
        rows = c.execute("SELECT * FROM bot_payouts WHERE status='pending' ORDER BY created LIMIT 1").fetchall()
        if not rows:
            return say(uid, "Нет заявок на выплату.")
        p = rows[0]
        return say(uid, f"Выплата {p['id']}\nID игрока: {p['uid']}\n{money(p['amount'])}\n{p['destination']}\n\nПосле реального перевода:\n/botpaid {p['id']} НомерБанковскойОперации", [[button("Отклонить и вернуть деньги", "admin:rejectpayout:" + p["id"])]])
    pool = c.execute("SELECT amount FROM bot_cash_pool WHERE id=1").fetchone()["amount"]
    return say(uid, f"🛡 Управление ботом\nУчтённый резерв: {money(pool)}\nОбязательства: {money(liability(c))}\nСвободный резерв: {money(max(0,pool-liability(c)))}\nНехватка покрытия: {money(max(0,liability(c)-pool))}\nДолги исполнителей: {money(c.execute('SELECT coalesce(sum(amount),0) AS n FROM bot_debts').fetchone()['n'])}\n\n/botcredit TelegramID Сумма НомерПлатежа — подтвердить фактически полученное пополнение\n/botfund Сумма НомерВзноса — учесть собственный резерв\n/botpaid НомерЗаявки НомерОперации — подтвердить фактически выполненную выплату\n\nРеквизиты для пополнений согласовываются через обращения: /tickets.\nОбзор администратора: /admin.", [[button("⚙️ Тарифы и правила", "admin:economy")], [button("📝 Модерация заданий", "admin:tasks"), button("💸 Выплаты", "admin:payouts")], [button("🎁 Бонусы и канал постов", "admin:bonus"), button("Проверить публикации", "admin:postissues")], [button("📚 Настройки «О боте»", "admin:about"), button("➕ Пополнения", "admin:topupsettings")]])
