"""Public TREVIXO payout announcements, separate from private payment notifications.

The news channel is configured in the existing owner-controlled 'О боте' settings.
Only confirmed paid transfers are queued; never include bank data in text.
A recipient profile button is shown only when the payee explicitly opts in.
Ambiguous Telegram send results require manual review rather than blind reposts.
"""
import logging
import re
import time
from urllib.parse import urlsplit

log = logging.getLogger(__name__)


def initialize(c):
    c.execute("""CREATE TABLE IF NOT EXISTS bot_payout_channel_posts(
      payout_id text PRIMARY KEY,
      body text NOT NULL,
      state text NOT NULL DEFAULT 'pending'
        CHECK(state IN ('pending','sending','sent','needs_review')),
      created double precision NOT NULL,
      sent_at double precision,
      message_id bigint,
      error text NOT NULL DEFAULT '')""")
    c.execute("CREATE INDEX IF NOT EXISTS bot_payout_channel_queue ON bot_payout_channel_posts(state,created)")
    c.execute("ALTER TABLE bot_payout_channel_posts ADD COLUMN IF NOT EXISTS recipient_uid bigint")
    c.execute("ALTER TABLE bot_payouts ADD COLUMN IF NOT EXISTS public_profile boolean NOT NULL DEFAULT false")
    # Public marketing posts are opt-in for the project, independent of private notifications.
    c.execute("CREATE TABLE IF NOT EXISTS bot_payout_channel_options(key text PRIMARY KEY, enabled boolean NOT NULL)")
    c.execute("INSERT INTO bot_payout_channel_options(key,enabled) VALUES('publish_paid',false) ON CONFLICT DO NOTHING")
    # Do not publish a backlog of older transactions if this setting is enabled later.
    enabled=c.execute("SELECT enabled FROM bot_payout_channel_options WHERE key='publish_paid'").fetchone()
    if not enabled or not enabled['enabled']:
        c.execute("""UPDATE bot_payout_channel_posts SET state='needs_review',error='public_feed_disabled'
            WHERE state='pending'""")


def enqueue_paid(c, payout_id, amount_formatted, recipient_uid=None):
    """Call in the same database transaction which changes payout status to paid."""
    if not payout_id or not amount_formatted:
        raise ValueError("Missing confirmed payout")
    body = (
        "✅ Выплата выполнена!\n\n"
        "💸 Сумма: " + str(amount_formatted) + "\n"
        "🎉 Ещё одна подтверждённая выплата в TREVIXO.\n\n"
        "🚀 Выполняй задания, приглашай друзей и развивайся вместе с нами!"
    )
    if recipient_uid is not None and (type(recipient_uid) is not int or recipient_uid<=0):
        raise ValueError("Invalid payout recipient")
    c.execute("""INSERT INTO bot_payout_channel_posts(payout_id,body,created,recipient_uid)
      VALUES(%s,%s,%s,%s) ON CONFLICT(payout_id) DO NOTHING""",
      (str(payout_id),body,time.time(),recipient_uid))


def public_channel(link):
    """Use only public Telegram channel usernames, never private invite links."""
    if not isinstance(link,str) or not link:
        return None
    if link.startswith('@'):
        username=link[1:]
    else:
        try:
            parsed=urlsplit(link)
        except ValueError:
            return None
        if parsed.scheme!='https' or parsed.netloc.lower() not in ('t.me','telegram.me'):
            return None
        username=parsed.path.strip('/')
        if parsed.query or parsed.fragment or '/' in username:
            return None
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{4,31}',username):
        return None
    return '@'+username


def dispatch(db,api):
    """At most one send attempt per payout. Unknown outcomes are held for review."""
    with db() as c:
        c.execute('SELECT pg_advisory_xact_lock(1984536)')
        enabled=c.execute("SELECT enabled FROM bot_payout_channel_options WHERE key='publish_paid'").fetchone()
        if not enabled or not enabled['enabled']:
            return False
        cfg=c.execute("SELECT news FROM bot_public_info WHERE id=1").fetchone()
        target=public_channel(cfg['news']) if cfg else None
        if target is None:
            return False  # Can safely remain pending until admin configures public news URL.
        row=c.execute("""SELECT payout_id,body,recipient_uid FROM bot_payout_channel_posts
          WHERE state='pending' ORDER BY created,payout_id LIMIT 1 FOR UPDATE""").fetchone()
        if not row:
            return False
        c.execute("UPDATE bot_payout_channel_posts SET state='sending' WHERE payout_id=%s",
                  (row['payout_id'],))
    try:
        payload={'chat_id':target,'text':row['body']}
        if row['recipient_uid']:
            payload['reply_markup']={'inline_keyboard':[[{
                'text':'✅ Выплата выполнена',
                'url':'tg://user?id='+str(row['recipient_uid'])
            }]]}
        result=api('sendMessage',payload)
        chat=(result or {}).get('chat') or {}
        if (type((result or {}).get('message_id')) is not int
                or chat.get('type')!='channel'
                or str(chat.get('username','')).lower()!=target[1:].lower()):
            raise RuntimeError("Channel post acknowledgement was not verified")
    except Exception as exc:
        # Do not resend automatically: Telegram might have posted before a timeout.
        with db() as c:
            c.execute("""UPDATE bot_payout_channel_posts
              SET state='needs_review',error=%s WHERE payout_id=%s AND state='sending'""",
              (type(exc).__name__,row['payout_id']))
        log.warning("payout_channel_post_needs_review payout=%s reason=%s",
                    row['payout_id'],type(exc).__name__)
        return False
    with db() as c:
        c.execute("""UPDATE bot_payout_channel_posts
          SET state='sent',sent_at=%s,message_id=%s,error=''
          WHERE payout_id=%s AND state='sending'""",
          (time.time(),result['message_id'],row['payout_id']))
    return True
