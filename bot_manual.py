"""Advertiser-defined manual tasks: gross advertiser price and optional photo examples."""
import re
import uuid
from urllib.parse import urlsplit
from bot_copy import tr

MAX_PHOTOS=10


def core():
    import task_bot
    return task_bot


def initialize(c):
    c.execute('CREATE TABLE IF NOT EXISTS bot_task_photos(task text NOT NULL,position integer NOT NULL,file_id text NOT NULL,unique_id text NOT NULL,PRIMARY KEY(task,position),UNIQUE(task,unique_id))')


def begin(c,uid):
    b=core();b.state(c,uid,'manual_title',{'kind':'manual','images':[],'draft':uuid.uuid4().hex[:12],'pricing':'gross'})
    return b.input_prompt(uid,tr('📝 Своё задание\n\nВведи название: от 3 до 100 символов. Затем добавишь описание, ссылку, цену выполнения и фотографии с примерами.',section='bot_manual'))


def photo_rows(c,task):
    return c.execute('SELECT * FROM bot_task_photos WHERE task=%s ORDER BY position',(task,)).fetchall()


def save(c,task,data):
    for i,p in enumerate(data.get('images',[])):
        c.execute('INSERT INTO bot_task_photos VALUES(%s,%s,%s,%s)',(task,i,p['file_id'],p['unique_id']))


def price_quote(c,price):
    return core().bot_economy.quote(c,'manual',price)


def add_photo(data,message):
    b=core();photos=message.get('photo') or []
    photo=photos[-1] if photos else {}
    fid=photo.get('file_id');unique=photo.get('file_unique_id') or fid
    if not isinstance(fid,str) or not 1<=len(fid)<=1024 or not isinstance(unique,str) or not 1<=len(unique)<=1024:
        raise b.UserError('Пришли фотографию через галерею Telegram.')
    if photo.get('file_size',0)>10*1024*1024:raise b.UserError('Фото должно быть не больше 10 МБ.')
    images=data.setdefault('images',[])
    if any(p['unique_id']==unique for p in images):return
    if len(images)>=MAX_PHOTOS:raise b.UserError('Можно прикрепить до 10 фотографий. Удали фотографии или заверши добавление.')
    images.append({'file_id':fid,'unique_id':unique})


def photo_prompt(uid,data):
    b=core();n=len(data.get('images',[]))
    rows=[]
    if n:rows.extend([[b.button('👁 Посмотреть фото','manual:draft:'+data['draft']+':0')],[b.button('🗑 Убрать все фото','manual:clear_photos')]])
    rows.append([b.button('✅ Готово' if n else '⏭ Без фотографий','manual:photos_done')])
    return b.input_prompt(uid,tr('📷 Фотографии и примеры\n\nДобавлено: {v0} из 10.\nОтправь одно фото, несколько по очереди или альбом. Можно добавить пример выполнения, инструкцию или скриншот. Затем нажми «Готово».',{'v0':n},section='bot_manual'),rows)


def preview(c,uid,data):
    b=core()
    if data.get('pricing')!='gross':return begin(c,uid)
    q=data['terms'];count=data['count']
    data['budget']=q['cost']*count
    if data['budget']>b.account(c,uid)['available']:raise b.UserError('Для этого количества выполнений не хватает средств. Пополни баланс или создай заказ с меньшим бюджетом.')
    data['nonce']=uuid.uuid4().hex[:12]
    b.state(c,uid,'task_confirm',data)
    rows=[]
    if data['images']:rows.append([b.button('📷 Проверить фотографии','manual:draft:'+data['draft']+':0')])
    rows.extend([[b.button('📷 Изменить фотографии','manual:photos')],[b.button('✅ Создать задание','confirm_task:'+data['nonce'])]])
    return b.input_prompt(uid,tr('📝 Проверь задание\n\n{v0}\n\n{v1}\n\nСсылка: {v2}\nФотографий: {v3}\n\nНаграда исполнителю: {v4}\nВ том числе комиссия: {v5}\nПолная цена выполнения: {v6}\nКоличество выполнений: {v7}\n\nИТОГО С БАЛАНСА: {v8}\n\nПосле подтверждения бюджет резервируется один раз. Задание появится после модерации. Проверять доказательства выполнения будешь ты.',{'v0':data['title'],'v1':data['description'],'v2':data['url'] or 'не нужна','v3':len(data['images']),'v4':b.money(data['reward']),'v5':b.money(q['cost']-data['reward']),'v6':b.money(q['cost']),'v7':count,'v8':b.money(data['budget'])},section='bot_manual'),rows)


def input_text(c,uid,text,message,current):
    b=core();stage=current['state'];data=current['data']
    if data.get('pricing')!='gross':return begin(c,uid)
    if message.get('document') or message.get('video'):
        raise b.UserError('Для примера прикрепи фотографию или скриншот как фото. Документы и видео пока не поддерживаются.')
    text=(text or message.get('caption') or '').strip()
    # Album updates can arrive separately after the first caption has advanced the wizard.
    if message.get('photo') and stage!='manual_description':
        add_photo(data,message)
        if stage=='task_confirm':stage='manual_photos'
        b.state(c,uid,stage,data)
        if message.get('media_group_id'):return {'ok':True}
        return photo_prompt(uid,data) if stage=='manual_photos' else b.input_prompt(uid,'📷 Фото сохранено. Продолжи шаг, указанный выше.')
    if stage=='manual_title':
        if not 3<=len(text)<=100:raise b.UserError('Название: от 3 до 100 символов.')
        data['title']=text;b.state(c,uid,'manual_description',data)
        return b.input_prompt(uid,tr('✍️ Опиши задание\n\nЧто нужно сделать и какое доказательство прислать? От 10 до 1000 символов. Фото с примерами можно добавить сейчас или на отдельном шаге.',section='bot_manual'))
    if stage=='manual_description':
        if message.get('photo'):add_photo(data,message)
        if not text and message.get('photo'):
            b.state(c,uid,stage,data)
            return {'ok':True} if message.get('media_group_id') else b.input_prompt(uid,'📷 Фото добавлено. Теперь напиши описание задания: от 10 до 1000 символов.')
        if not 10<=len(text)<=1000:raise b.UserError('Описание: от 10 до 1000 символов.')
        data['description']=text;b.state(c,uid,'manual_url',data)
        return b.input_prompt(uid,tr('🔗 Добавь ссылку\n\nПришли HTTPS-ссылку на материал, сайт, канал или бота. Если ссылка не нужна, нажми кнопку ниже.',section='bot_manual'),[[b.button('⏭ Без ссылки','manual:skip_url')]])
    if stage=='manual_url':
        if text=='-':data['url']=''
        else:
            try:
                parsed=urlsplit(text)
                parsed.port
            except ValueError:
                raise b.UserError('Проверь HTTPS-ссылку или выбери «Без ссылки».')
            if len(text)>400 or parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or any(ch.isspace() for ch in text):
                raise b.UserError('Нужна HTTPS-ссылка без пробелов, логина и пароля. Или выбери «Без ссылки».')
            data['url']=text
        b.state(c,uid,'manual_price',data)
        return b.input_prompt(uid,tr('💰 Цена одного выполнения\n\nВведи сумму в гривнах, которую заплатишь за одно принятое выполнение. Комиссия уже входит в эту цену. Исполнитель получит сумму за вычетом комиссии. Расчёт покажем перед созданием.',section='bot_manual'))
    if stage=='manual_price':
        price=b.amount(text);q=price_quote(c,price)
        reward=q['reward']
        data['reward']=reward;data['terms']=q;b.state(c,uid,'manual_count',data)
        return b.input_prompt(uid,tr('👥 Сколько нужно выполнений?\n\nНаграда: {v0}\nКомиссия: {v1}\nЦена одного выполнения: {v2}\n\nВведи целое число от 1 до {v3}.',{'v0':b.money(reward),'v1':b.money(q['cost']-reward),'v2':b.money(q['cost']),'v3':b.bot_admin.limits(c)['max_executions']},section='bot_manual'))
    if stage=='manual_count':
        if not text.isdecimal() or not 1<=int(text)<=b.bot_admin.limits(c)['max_executions']:raise b.UserError('Укажи допустимое целое количество выполнений.')
        data['count']=int(text);data['budget']=data['terms']['cost']*data['count']
        if data['budget']>b.account(c,uid)['available']:raise b.UserError('Недостаточно средств. Укажи меньше выполнений или пополни баланс.')
        b.state(c,uid,'manual_photos',data)
        return photo_prompt(uid,data)
    if stage=='manual_photos':return photo_prompt(uid,data)
    return b.input_prompt(uid,'Проверь задание и подтверди создание кнопкой выше.')


def gallery(uid,images,index,back,title,prefix):
    b=core()
    if not 0<=index<len(images):raise b.UserError('Фотография не найдена.')
    nav=[]
    if index:nav.append(b.button('⬅️ Предыдущее',prefix+str(index-1)))
    if index+1<len(images):nav.append(b.button('Следующее ➡️',prefix+str(index+1)))
    rows=[nav] if nav else []
    rows.append([b.button('⬅️ К заданию',back)])
    return {'method':'sendPhoto','chat_id':uid,'photo':images[index]['file_id'],'caption':'📷 Пример '+str(index+1)+'/'+str(len(images))+'\n'+title[:100],'reply_markup':{'inline_keyboard':rows}}


def route(c,uid,action,admin=False):
    b=core()
    if not action.startswith('manual:'):return None
    parts=action.split(':')
    if parts[1]=='photo':
        if len(parts)!=4 or not parts[3].isdecimal():raise b.UserError('Фотография не найдена.')
        t=c.execute('SELECT * FROM bot_tasks WHERE id=%s',(parts[2],)).fetchone()
        if not t:raise b.UserError('Задание не найдено.')
        own=t['owner']==uid
        claim=c.execute('SELECT 1 FROM bot_claims WHERE task=%s AND uid=%s',(t['id'],uid)).fetchone()
        public=t['status']=='active' and not b.bot_moderation.paused(c,t['id']) and t['remaining']>=b.bot_economy.cost(c,t)
        if not (own or admin or claim or public):raise b.UserError('Примеры этого задания пока недоступны.')
        back='own:'+t['id'] if own else 'admin:task:'+t['id'] if admin else 'task:'+t['id'] if public else 'earn'
        return gallery(uid,photo_rows(c,t['id']),int(parts[3]),back,t['title'],'manual:photo:'+t['id']+':')
    current=b.state(c,uid)
    if not current or current['data'].get('kind')!='manual' or current['state'] not in ('manual_title','manual_description','manual_url','manual_price','manual_count','manual_photos','task_confirm'):
        raise b.UserError('Черновик уже закрыт. Создай новое задание.')
    data=current['data']
    if parts[1]=='skip_url' and current['state']=='manual_url':return input_text(c,uid,'-',{},current)
    if parts[1]=='draft':
        if len(parts)!=4 or parts[2]!=data['draft'] or not parts[3].isdecimal():raise b.UserError('Этот просмотр относится к другому черновику.')
        back='manual:photos' if current['state']!='task_confirm' else 'manual:photos_done'
        return gallery(uid,data['images'],int(parts[3]),back,data['title'],'manual:draft:'+data['draft']+':')
    if parts[1] in ('photos','photos_done','clear_photos') and current['state'] in ('manual_photos','task_confirm'):
        if parts[1]=='photos_done':return preview(c,uid,data)
        if parts[1]=='clear_photos':data['images']=[]
        b.state(c,uid,'manual_photos',data);return photo_prompt(uid,data)
    raise b.UserError('Заверши текущий шаг создания задания.')


def task_card(c,t,uid):
    b=core();photos=photo_rows(c,t['id']);rows=[]
    if t['url']:rows.append([{'text':'🔗 Открыть ссылку','url':t['url']}])
    if photos:rows.append([b.button('📷 Примеры · '+str(len(photos)),'manual:photo:'+t['id']+':0')])
    rows.extend([[b.button('Взять задание','take:'+t['id']),b.button('📤 Отправить выполнение','check:'+t['id'])],[b.button('⬅️ Задания','earn')]])
    return b.say(uid,tr('📝 {v0}\n\n{v1}\n\n💰 Награда за принятое выполнение: {v2}\n\nВыполни условия и отправь доказательство. Его проверит заказчик.',{'v0':t['title'],'v1':t['description'],'v2':b.money(t['reward'])},section='bot_manual'),rows)
