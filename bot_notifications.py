"""Transactional notification outbox. Retries never repeat a financial operation."""
import json
import logging
import threading
import time
from psycopg.types.json import Jsonb

log=logging.getLogger(__name__)
_signal=threading.Event()


def initialize(c):
    c.execute('CREATE TABLE IF NOT EXISTS farm_admin_identity(slot integer PRIMARY KEY CHECK(slot=1),telegram_id bigint NOT NULL UNIQUE,claimed_at double precision NOT NULL)')
    c.execute("""CREATE TABLE IF NOT EXISTS bot_notifications(
      id text PRIMARY KEY,recipient bigint NOT NULL,subject bigint NOT NULL,kind text NOT NULL,
      payload jsonb NOT NULL,status text NOT NULL DEFAULT 'pending',attempts integer NOT NULL DEFAULT 0,
      next_at double precision NOT NULL DEFAULT 0,created double precision NOT NULL,sent_at double precision)""")
    c.execute('CREATE INDEX IF NOT EXISTS bot_notifications_queue ON bot_notifications(status,next_at)')


def enqueue(c,event,text,action=None,recipient=0,subject=0,kind='event'):
    # Recipient 0 means the verified owner; a caller cannot nominate another owner.
    now=time.time()
    if kind=='intent' and c.execute('SELECT 1 FROM bot_notifications WHERE subject=%s AND kind=%s AND created>%s',
                                   (subject,kind,now-300)).fetchone():
        return
    payload={'text':text[:3500]}
    if action:
        payload['reply_markup']={'inline_keyboard':[[{'text':'📂 Открыть заявку','callback_data':'bot:'+action}]]}
    c.execute("INSERT INTO bot_notifications(id,recipient,subject,kind,payload,created) VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
              (event,recipient,subject,kind,Jsonb(payload),now))


def wake():
    _signal.set()


def dispatch(db,api,limit=10):
    for _ in range(limit):
        now=time.time()
        with db() as c:
            c.execute('SELECT pg_advisory_xact_lock(1984535)')
            c.execute("UPDATE bot_notifications SET status='pending' WHERE status='sending' AND next_at<=%s",(now,))
            owner=c.execute('SELECT telegram_id FROM farm_admin_identity WHERE slot=1').fetchone()
            row=c.execute("SELECT * FROM bot_notifications WHERE status='pending' AND next_at<=%s AND (recipient>0 OR %s>0) ORDER BY created,id LIMIT 1 FOR UPDATE",(now,owner['telegram_id'] if owner else 0)).fetchone()
            if not row:return
            target=row['recipient'] or owner['telegram_id']
            c.execute("UPDATE bot_notifications SET status='sending',attempts=attempts+1,next_at=%s WHERE id=%s",(now+120,row['id']))
        payload=row['payload']
        if isinstance(payload,str):payload=json.loads(payload)
        try:
            result=api('sendMessage',dict(payload,chat_id=target))
            if not isinstance(result,dict) or type(result.get('message_id')) is not int or (result.get('chat') or {}).get('id')!=target:
                raise RuntimeError('Notification delivery was not confirmed')
        except Exception:
            # A timed-out accepted send can be repeated; the stable event ID is kept.
            with db() as c:
                c.execute("UPDATE bot_notifications SET status='pending',next_at=%s WHERE id=%s AND status='sending'",
                          (time.time()+min(900,15*2**min(row['attempts'],6)),row['id']))
            log.warning('bot_notification_delivery_retry event=%s',row['id'])
        else:
            with db() as c:
                c.execute("UPDATE bot_notifications SET status='sent',sent_at=%s WHERE id=%s AND status='sending'",(time.time(),row['id']))


def worker(db,api,stop):
    while not stop.is_set():
        try:dispatch(db,api)
        except Exception:log.exception('bot_notification_worker_failed')
        _signal.wait(15)
        _signal.clear()
