"""Owner task browser and audited controls; no hard deletion of financial records."""
import re
import time
import uuid
from bot_copy import tr

LABELS={'pending':'⏳ На проверке','active':'🟢 Активные','paused':'⏸ Остановленные','closed':'📦 Архив','all':'📋 Все задания'}

def core():
    import task_bot
    return task_bot

def initialize(c):
    c.execute('CREATE TABLE IF NOT EXISTS bot_task_controls(task text PRIMARY KEY,paused integer NOT NULL DEFAULT 0 CHECK(paused IN (0,1)))')
    c.execute('CREATE TABLE IF NOT EXISTS bot_task_admin_audit(id text PRIMARY KEY,task text NOT NULL,actor bigint NOT NULL,operation text NOT NULL,reason text NOT NULL,refund bigint NOT NULL,created double precision NOT NULL)')

def paused(c,tid):
    r=c.execute('SELECT paused FROM bot_task_controls WHERE task=%s',(tid,)).fetchone()
    return bool(r and r['paused'])

def available(c,tid):
    if paused(c,tid):raise core().UserError('Задание временно остановлено администратором. Начисления приостановлены.')

def task(c,tid):
    if not re.fullmatch('[a-f0-9]{16}',tid):raise core().UserError('Укажи полный ID задания: 16 символов из карточки заказа.')
    t=c.execute('SELECT * FROM bot_tasks WHERE id=%s FOR UPDATE',(tid,)).fetchone()
    if not t:raise core().UserError('Задание с таким ID не найдено.')
    return t

def listing(c,uid,kind='pending',page=0):
    b=core();b.state(c,uid,'clear')
    if kind not in LABELS or not 0<=page<=12500:raise b.UserError('Неизвестная страница.')
    predicates={'pending':"t.status='pending'",'active':"t.status='active' AND coalesce(k.paused,0)=0",'paused':"t.status='active' AND k.paused=1",'closed':"t.status IN ('closed','rejected')",'all':'1=1'}
    rows=c.execute('SELECT t.* FROM bot_tasks t LEFT JOIN bot_task_controls k ON k.task=t.id WHERE '+predicates[kind]+' ORDER BY t.created DESC,t.id LIMIT 9 OFFSET %s',(page*8,)).fetchall()
    buttons=[[b.button(LABELS[k],'admin:tasklist:'+k+':0') for k in ('pending','active')], [b.button(LABELS[k],'admin:tasklist:'+k+':0') for k in ('paused','closed')], [b.button('📋 Все задания','admin:tasklist:all:0'),b.button('🔎 Поиск по ID','admin:tasksearch')]]
    for t in rows[:8]:buttons.append([b.button(t['title'][:28]+' · '+t['id'][:6],'admin:task:'+t['id'])])
    nav=[]
    if page:nav.append(b.button('⬅️ Назад','admin:tasklist:'+kind+':'+str(page-1)))
    if len(rows)>8:nav.append(b.button('Далее ➡️','admin:tasklist:'+kind+':'+str(page+1)))
    if nav:buttons.append(nav)
    buttons.append([b.button('⬅️ Управление','admin:section:manage')])
    return b.bot_ui.screen(uid,tr('📝 <b>Управление заданиями</b>\n\n{v0} · страница {v1}\n{v2}\n\nОткрой карточку: автор, условия, оплата, выполнения и действия. Закрытые заказы остаются в архиве.',{'v0':LABELS[kind],'v1':page+1,'v2':'Выбери задание ниже.' if rows else 'В этом разделе заданий нет.'},html_mode=True,section='bot_moderation'),buttons)

def card(c,uid,tid):
    b=core();t=task(c,tid);q=b.bot_advertising.order(c,t)
    author=b.account(c,t['owner']);counts={r['status']:r['n'] for r in c.execute('SELECT status,count(*) AS n FROM bot_claims WHERE task=%s GROUP BY status',(tid,)).fetchall()}
    status='⏸ Остановлено' if t['status']=='active' and paused(c,tid) else {'pending':'⏳ На модерации','active':'🟢 Активно','closed':'📦 Закрыто','rejected':'❌ Отклонено'}[t['status']]
    text=tr('📝 <b>{v0}</b>\n<code>{v1}</code>\n\n{v2}\nТип: {v3}\n👤 Автор: {v4}\nID автора: <code>{v5}</code>\n\n<b>Условия</b>\n{v6}\n\n🔗 {v7}\n\n<b>Оплата и выполнения</b>\nЦена: {v8}\nНаграда: {v9}\nЗаказано: {v10}\n✅ Оплачено: {v11}\n⏳ На проверке: {v12}\n🛠 В работе: {v13}\n💰 Остаток: {v14}',{'v0':b.bot_ui.esc(t['title']),'v1':tid,'v2':status,'v3':b.KINDS[t['kind']],'v4':b.bot_ui.esc(author['name'] if author else 'Пользователь'),'v5':t['owner'],'v6':b.bot_ui.esc(t['description']),'v7':b.bot_ui.esc(t['url'] or 'Ссылка не указана'),'v8':b.money(b.bot_economy.cost(c,t)),'v9':b.money(t['reward']),'v10':q['slots'] if q else 'Старый заказ','v11':counts.get('paid',0),'v12':counts.get('review',0),'v13':counts.get('started',0),'v14':b.money(t['remaining'])},html_mode=True,section='bot_moderation')
    rows=[]
    if t['url']:rows.append([{'text':'🔗 Открыть материал','url':t['url']}])
    if b.bot_manual.photo_rows(c,tid):rows.append([b.button('📷 Примеры задания','manual:photo:'+tid+':0')])
    rows.append([b.button('👥 Выполнения','admin:taskclaims:'+tid+':0'),b.button('🕘 Действия админа','admin:taskaudit:'+tid)])
    if t['status']=='pending':rows.append([b.button('✅ Опубликовать','admin:approve:'+tid),b.button('❌ Отклонить','admin:rejecttask:'+tid)])
    if t['status']=='active':rows.append([b.button('▶️ Возобновить' if paused(c,tid) else '⏸ Остановить','admin:taskop:'+('resume' if paused(c,tid) else 'pause')+':'+tid)])
    if t['status'] in ('pending','active'):rows.append([b.button('📦 Закрыть и вернуть остаток','admin:taskop:archive:'+tid)])
    rows.extend([[b.button('🔄 Обновить','admin:task:'+tid)],[b.button('⬅️ Список заданий','admin:tasks')]])
    return b.bot_ui.screen(uid,text,rows)

def begin(c,uid,op,tid):
    b=core();t=task(c,tid)
    validate(c,t,op)
    data={'id':tid,'op':op,'nonce':uuid.uuid4().hex[:12]}
    b.state(c,uid,'admin_task_reason' if op=='archive' else 'admin_task_control_confirm',data)
    if op=='archive':return b.bot_ui.input_screen(uid,tr('📦 Закрытие задания\n\nНапиши причину: от 5 до 500 символов. Её увидит рекламодатель. Остаток вернётся после подтверждения; история выполнений сохранится.',section='bot_moderation'))
    return confirm_screen(c,uid,data)

def validate(c,t,op):
    b=core()
    if op not in ('pause','resume','archive'):raise b.UserError('Неизвестное действие.')
    if op=='archive':
        if t['status'] not in ('pending','active'):raise b.UserError('Задание уже закрыто.')
        b.can_close_order(c,t)
    elif t['status']!='active' or paused(c,t['id'])!=(op=='resume'):raise b.UserError('Статус задания уже изменился. Обнови карточку.')

def confirm_screen(c,uid,data):
    b=core();t=task(c,data['id']);validate(c,t,data['op'])
    data['remaining']=t['remaining'];data['nonce']=uuid.uuid4().hex[:12]
    b.state(c,uid,'admin_task_control_confirm',data)
    label={'pause':'⏸ Остановить задание','resume':'▶️ Возобновить задание','archive':'📦 Закрыть задание'}[data['op']]
    note=('Остаток к возврату: '+b.money(t['remaining'])+'\nПричина: '+data.get('reason','')) if data['op']=='archive' else 'Пауза не возвращает бюджет. Во время паузы новые выполнения и начисления запрещены.'
    return b.bot_ui.screen(uid,tr('<b>{v0}?</b>\n\n{v1}\nID: <code>{v2}</code>\n\n{v3}',{'v0':label,'v1':b.bot_ui.esc(t['title']),'v2':t['id'],'v3':b.bot_ui.esc(note)},html_mode=True,section='bot_moderation'),[[b.button('✅ Подтвердить','admin:taskcontrol:'+data['nonce'])],[b.button('✖️ Отмена','admin:task:'+t['id'])]])

def input_text(c,uid,text,st):
    b=core()
    if st['state']=='admin_task_search':return card(c,uid,text.strip().lower())
    if st['state']=='admin_task_reason':
        if not 5<=len(text.strip())<=500:raise b.UserError('Причина: от 5 до 500 символов.')
        data=st['data'];data['reason']=text.strip();b.state(c,uid,'admin_task_control_confirm',data)
        return confirm_screen(c,uid,data)
    return b.bot_ui.input_screen(uid,'Подтверди действие кнопкой выше или отмени форму.')

def route(c,uid,action):
    b=core()
    if action=='admin:tasks':return listing(c,uid)
    if action.startswith('admin:tasklist:'):
        p=action.split(':')
        if len(p)!=4 or not p[3].isdecimal():raise b.UserError('Неверная страница.')
        return listing(c,uid,p[2],int(p[3]))
    if action=='admin:tasksearch':
        b.state(c,uid,'admin_task_search');return b.bot_ui.input_screen(uid,tr('🔎 Поиск задания\n\nПришли полный ID из карточки заказа. Команды не нужны.',section='bot_moderation'))
    if action.startswith('admin:task:'):
        b.state(c,uid,'clear');return card(c,uid,action.split(':')[-1])
    if action.startswith('admin:taskop:'):
        p=action.split(':')
        if len(p)!=4:raise b.UserError('Неверное действие.')
        return begin(c,uid,p[2],p[3])
    if action.startswith('admin:taskcontrol:'):
        st=b.state(c,uid)
        if not st or st['state']!='admin_task_control_confirm' or st['data'].get('nonce')!=action.split(':')[-1]:raise b.UserError('Подтверждение устарело.')
        d=st['data'];t=task(c,d['id']);validate(c,t,d['op']);refund=0
        if d['op']=='archive' and d.get('remaining')!=t['remaining']:return confirm_screen(c,uid,d)
        if d['op']=='archive':refund=b.close_order(c,t)
        else:c.execute('INSERT INTO bot_task_controls VALUES(%s,%s) ON CONFLICT(task) DO UPDATE SET paused=EXCLUDED.paused',(t['id'],int(d['op']=='pause')))
        c.execute('INSERT INTO bot_task_admin_audit VALUES(%s,%s,%s,%s,%s,%s,%s)',(uuid.uuid4().hex,t['id'],uid,d['op'],d.get('reason',''),refund,time.time()))
        b.bot_notifications.enqueue(c,'task-control:'+d['nonce'],'📝 Изменение задания\nID: '+t['id']+'\nДействие: '+{'pause':'Остановлено','resume':'Возобновлено','archive':'Закрыто'}[d['op']]+'\nВозврат остатка: '+b.money(refund)+'\n'+d.get('reason',''),recipient=t['owner'])
        b.state(c,uid,'clear');return card(c,uid,t['id'])
    if action.startswith('admin:taskclaims:'):
        p=action.split(':')
        if len(p)!=4 or not p[3].isdecimal() or int(p[3])>12500:raise b.UserError('Неверная страница.')
        t=task(c,p[2]);page=int(p[3]);rows=c.execute('SELECT uid,status,proof FROM bot_claims WHERE task=%s ORDER BY created,uid LIMIT 9 OFFSET %s',(t['id'],page*8)).fetchall()
        labels={'started':'В работе','review':'На проверке','paid':'Оплачено','rejected':'Отклонено'}
        lines=['👤 '+str(r['uid'])+' · '+labels[r['status']] for r in rows[:8]]
        nav=[]
        if page:nav.append(b.button('⬅️ Назад','admin:taskclaims:'+t['id']+':'+str(page-1)))
        if len(rows)>8:nav.append(b.button('Далее ➡️','admin:taskclaims:'+t['id']+':'+str(page+1)))
        work_buttons=[[b.button('👤 '+str(r['uid'])+' · '+labels[r['status']],'admin:taskwork:'+t['id']+':'+str(r['uid']))] for r in rows[:8]]
        return b.bot_ui.screen(uid,'👥 Выполнения задания\n'+t['id']+'\n\n'+('\n'.join(lines) or 'Выполнений пока нет.'),work_buttons+([nav] if nav else [])+[[b.button('⬅️ Карточка','admin:task:'+t['id'])]])
    if action.startswith('admin:taskwork:'):
        p=action.split(':')
        if len(p)!=4 or not p[3].isdecimal():raise b.UserError('Неверная работа.')
        t=task(c,p[2]);r=c.execute('SELECT * FROM bot_claims WHERE task=%s AND uid=%s',(t['id'],int(p[3]))).fetchone()
        if not r:raise b.UserError('Выполнение не найдено.')
        text='👤 Исполнитель: '+str(r['uid'])+'\nСтатус: '+r['status']+'\n\n'+r['proof']+'\n\nРучную работу принимает или отклоняет заказчик.'
        rows=[[b.button('⬅️ Выполнения','admin:taskclaims:'+t['id']+':0')]]
        if r['photo']:return {'method':'sendPhoto','chat_id':uid,'photo':r['photo'],'caption':text[:1000],'reply_markup':{'inline_keyboard':rows}}
        return b.say(uid,text[:2800],rows)
    if action.startswith('admin:taskaudit:'):
        t=task(c,action.split(':')[-1]);rows=c.execute('SELECT * FROM bot_task_admin_audit WHERE task=%s ORDER BY created DESC LIMIT 10',(t['id'],)).fetchall()
        lines=[r['operation']+' · админ '+str(r['actor'])+' · возврат '+b.money(r['refund'])+'\n'+r['reason'] for r in rows]
        return b.say(uid,'🕘 Последние действия\n'+t['id']+'\n\n'+(('\n\n'.join(lines))[:2600] or 'Изменений нет.'),[[b.button('⬅️ Карточка','admin:task:'+t['id'])]])
    return None
