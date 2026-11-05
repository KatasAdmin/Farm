"""Owner-only opt-in broadcast drafts. No delivery before explicit confirmation."""
import time,uuid
from psycopg.types.json import Jsonb
import bot_notifications

def initialize(c):
    c.execute("""CREATE TABLE IF NOT EXISTS bot_broadcasts(
      id text PRIMARY KEY, owner bigint NOT NULL, body text NOT NULL,
      status text NOT NULL CHECK(status IN ('draft','queued')),
      created double precision NOT NULL, queued_at double precision, tested_at double precision)""")

def screen(c,uid):
    import task_bot as b
    rows=c.execute("SELECT id,status,created FROM bot_broadcasts WHERE owner=%s ORDER BY created DESC LIMIT 5",(uid,)).fetchall()
    total=c.execute("SELECT count(*) n FROM bot_accounts").fetchone()['n']
    buttons=[[b.button('✍️ Создать рассылку','admin:broadcast:new')]]
    buttons += [[b.button(('📝 ' if r['status']=='draft' else '📨 ')+r['id'][:8], 'admin:broadcast:view:'+r['id'])] for r in rows]
    buttons.append([b.button('⬅️ Админ-панель','admin')])
    return b.bot_ui.screen(uid,'📢 <b>Рассылки</b>\n\nПользователей в базе: '+str(total)+'\nОтправка только после теста и отдельного подтверждения.',buttons)

def view(c,uid,bid):
    import task_bot as b
    r=c.execute("SELECT * FROM bot_broadcasts WHERE id=%s AND owner=%s",(bid,uid)).fetchone()
    if not r: raise b.UserError('Рассылка не найдена.')
    count=c.execute("SELECT count(*) n FROM bot_notifications WHERE kind=%s",('broadcast:'+bid,)).fetchone()['n']
    sent=c.execute("SELECT count(*) n FROM bot_notifications WHERE kind=%s AND status='sent'",('broadcast:'+bid,)).fetchone()['n']
    buttons=[]
    if r['status']=='draft':
        buttons=[[b.button('🧪 Тест только мне','admin:broadcast:test:'+bid)],
                 [b.button('🔐 Подготовить подтверждение','admin:broadcast:prepare:'+bid)],
                 [b.button('🗑 Удалить черновик','admin:broadcast:delete:'+bid)]]
    buttons.append([b.button('⬅️ Рассылки','admin:broadcast')])
    return b.bot_ui.screen(uid,'📢 <b>Рассылка '+bid[:8]+'</b>\nСтатус: '+r['status']+'\nПолучателей в очереди: '+str(count)+'\nПодтверждено доставок: '+str(sent)+'\n\n'+b.bot_ui.esc(r['body']),buttons)

def route(c,uid,action,api):
    import task_bot as b
    if action=='admin:broadcast':return screen(c,uid)
    if action=='admin:broadcast:new':
        b.state(c,uid,'admin_broadcast_body')
        return b.bot_ui.input_screen(uid,'✍️ Отправь текст объявления одним сообщением (до 3500 символов).')
    parts=action.split(':')
    if len(parts)!=4 or parts[:2]!=['admin','broadcast']:return None
    kind,bid=parts[2:]
    row=c.execute("SELECT * FROM bot_broadcasts WHERE id=%s AND owner=%s",(bid,uid)).fetchone()
    if not row:raise b.UserError('Черновик не найден.')
    if kind=='view':return view(c,uid,bid)
    if row['status']!='draft':raise b.UserError('Рассылка уже поставлена в очередь.')
    if kind=='test':
        # Only owner's own chat; failure is reported rather than silently ignored.
        result=api('sendMessage',{'chat_id':uid,'text':'🧪 ТЕСТ РАССЫЛКИ\n\n'+row['body']})
        if not isinstance(result,dict) or not result.get('message_id'):raise b.UserError('Тест не доставлен. Проверь бота.')
        c.execute("UPDATE bot_broadcasts SET tested_at=%s WHERE id=%s",(time.time(),bid))
        return b.bot_ui.screen(uid,'✅ Тест отправлен только тебе. Проверь сообщение перед подтверждением.',[[b.button('⬅️ К рассылке','admin:broadcast:view:'+bid)]])
    if kind=='prepare':
        if not row['tested_at']:raise b.UserError('Сначала отправь тест себе.')
        total=c.execute('SELECT count(*) n FROM bot_accounts WHERE uid>0').fetchone()['n']
        b.state(c,uid,'admin_broadcast_confirm',{'id':bid})
        return b.bot_ui.screen(uid,'⚠️ <b>Последнее подтверждение</b>\n\nПолучателей: '+str(total)+'\nПосле нажатия «Отправить всем» рассылка начнётся.\n\n'+b.bot_ui.esc(row['body']),[[b.button('🚀 Отправить всем','admin:broadcast:send:'+bid)],[b.button('❌ Отмена','admin:broadcast:view:'+bid)]])
    if kind=='send':
        st=b.state(c,uid)
        if not row['tested_at']:raise b.UserError('Сначала отправь тест себе.')
        if not st or st['state']!='admin_broadcast_confirm' or st['data'].get('id')!=bid:
            raise b.UserError('Сначала открой подтверждение рассылки.')
        # Lock draft row and prevent duplicate enqueue from repeated callbacks.
        locked=c.execute('SELECT status FROM bot_broadcasts WHERE id=%s FOR UPDATE',(bid,)).fetchone()
        if locked['status']!='draft':raise b.UserError('Уже отправляется.')
        c.execute("UPDATE bot_broadcasts SET status='queued',queued_at=%s WHERE id=%s",(time.time(),bid))
        now=time.time()
        c.execute("""INSERT INTO bot_notifications(id,recipient,subject,kind,payload,created)
          SELECT %s || ':' || uid::text,uid,uid,%s,%s, %s FROM bot_accounts WHERE uid>0
          ON CONFLICT DO NOTHING""",(bid,'broadcast:'+bid,Jsonb({'text':row['body']}),now))
        b.state(c,uid,'clear')
        return b.bot_ui.screen(uid,'📨 Рассылка поставлена в очередь. Отчёт доступен в этом разделе.',[[b.button('📊 Отчёт','admin:broadcast:view:'+bid)]])
    if kind=='delete':
        c.execute("DELETE FROM bot_broadcasts WHERE id=%s AND status='draft'",(bid,))
        return screen(c,uid)
    return None

def input_text(c,uid,text):
    import task_bot as b
    if not 1<=len(text)<=3500:raise b.UserError('Текст должен содержать от 1 до 3500 символов.')
    bid=uuid.uuid4().hex
    c.execute("INSERT INTO bot_broadcasts(id,owner,body,status,created) VALUES(%s,%s,%s,'draft',%s)",(bid,uid,text,time.time()))
    b.state(c,uid,'clear')
    return view(c,uid,bid)
