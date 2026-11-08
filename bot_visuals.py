"""Premium Telegram media, rendered only by the notification worker.

Snapshots contain only the requesting account's data. Images and avatars live in
bounded process caches, never on disk or in the accounting tables.
"""
from collections import OrderedDict
from datetime import datetime
from io import BytesIO
from pathlib import Path
import hashlib
import json
import logging
import threading
import time
import unicodedata
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger(__name__)
_lock = threading.RLock()
_images = OrderedDict()
_avatars = OrderedDict()
_files = OrderedDict()
_avatar_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='profile-avatar')
_avatar_jobs = set()
VERSION = 'premium-dark-2'
FONT = Path(__file__).parent / 'assets/fonts/RobotoCondensed.ttf'
SECTIONS = {
    'earn': ('ЗАРАБОТАТЬ', 'Задания · Реклама · Бонусы', '#3DAF85', 'coin'),
    'promotion': ('ПРОДВИЖЕНИЕ', 'Твои проекты. Новая аудитория.', '#9164ED', 'megaphone'),
    'games': ('ИГРОВАЯ', 'Ферма и новые возможности', '#5BA4D8', 'gamepad'),
    'about': ('МИР TREVIXO', 'Все возможности — рядом', '#D9B65D', 'orbit'),
    'quests': ('ТВОЙ ПРОГРЕСС', 'Квесты и достижения', '#D9B65D', 'medal'),
    'deposit': ('ПОПОЛНЕНИЕ', 'Выбери удобный способ', '#3DAF85', 'wallet'),
    'withdraw': ('ВЫВОД СРЕДСТВ', 'Твои средства. Понятные действия.', '#5BA4D8', 'shield'),
    'history': ('ИСТОРИЯ', 'Твоё движение средств', '#9D8DD4', 'ledger'),
    'orders': ('МОИ ЗАКАЗЫ', 'Управляй своим продвижением', '#9164ED', 'layers'),
    'reviews': ('ПРОВЕРКА РАБОТ', 'Выполнения твоих заданий', '#5BA4D8', 'checklist'),
    'payouts': ('МОИ ВЫПЛАТЫ', 'Заявки и статусы переводов', '#D9B65D', 'shield'),
    'claims': ('МОИ ВЫПОЛНЕНИЯ', 'Задания и результаты', '#3DAF85', 'checklist'),
    'rankings': ('ЛИДЕРЫ', 'Активность твоей команды', '#D9B65D', 'podium'),
    'statistics': ('В ЦИФРАХ', 'Актуальная статистика проекта', '#5AB8B1', 'chart'),
    'support': ('МЫ НА СВЯЗИ', 'Обращения и помощь', '#5BA4D8', 'chat'),
    'admin': ('УПРАВЛЕНИЕ', 'Рабочий кабинет TREVIXO', '#9D8DD4', 'shield'),
    'settings': ('НАСТРОЙКИ', 'Всё на своём месте', '#9D8DD4', 'sliders'),
}
SECTION_ACTIONS = {
    'earn':'earn', 'promotion':'promotion', 'games':'games', 'about':'about',
    'quests':'quests', 'deposit':'deposit', 'withdraw':'withdraw', 'history':'history',
    'mine:0':'orders', 'reviews:0':'reviews', 'payouts':'payouts', 'claims':'claims',
    'top:all':'rankings', 'top:today':'rankings', 'about:stats':'statistics',
    'about:admin_url':'support', 'admin':'admin', 'admin:section:manage':'settings',
}
SECTION_LABELS = {'🚀 Заработать':'earn', '📣 Продвижение':'promotion',
                  '🎮 Игры':'games', '📚 О боте':'about', '/quests':'quests', '/farm':'games'}


def decorate(response, text, action):
    """Only section entrances receive artwork; input and execution stay compact."""
    if response.get('method')!='sendMessage' or '_visual' in response:
        return response
    section = SECTION_ACTIONS.get(action) or SECTION_LABELS.get(text)
    if not section or not response.get('reply_markup', {}).get('inline_keyboard'):
        return response
    if len(response.get('text','').encode('utf-16-le'))//2>1024:
        return response
    return attach(response, 'section', section=section)


def section_image(section):
    from PIL import Image, ImageDraw, ImageFont
    title, subtitle, accent, icon = SECTIONS[section]
    rgb = tuple(int(accent[i:i+2],16) for i in (1,3,5))
    bg = Image.new('RGB',(300,110))
    px=bg.load()
    for y in range(110):
        for x in range(300):
            glow=max(0,1-(((x-250)/170)**2+((y-50)/100)**2))**2
            px[x,y]=tuple(int(base+channel*.22*glow) for base,channel in zip((16,16,27),rgb))
    im=bg.resize((1200,440),Image.Resampling.BICUBIC)
    d=ImageDraw.Draw(im);gold='#D9B65D';white='#F5F5FA'
    def label(x,y,value,size,color=white):
        d.text((x,y),value,font=ImageFont.truetype(str(FONT),size),fill=color)
    d.rounded_rectangle((20,20,1179,419),radius=30,outline='#4A3D5A',width=2)
    d.polygon([(64,64),(75,83),(92,55),(109,83),(120,64),(113,97),(71,97)],fill=gold)
    label(139,53,'TREVIXO',35)
    label(65,151,title,68)
    label(67,251,subtitle,29,'#BDB7CD')
    d.line((67,344,380,344),fill=accent,width=3)
    label(67,366,'PREMIUM SPACE',18,gold)
    d.ellipse((841,84,1131,374),outline='#493C58',width=2)
    d.arc((824,67,1148,391),245,345,fill=accent,width=3)
    d.arc((858,101,1114,357),65,145,fill=gold,width=2)
    # Each entrance has a different line illustration, without fake metrics.
    x,y=985,229
    def line(points,fill=accent,width=7):d.line(points,fill=fill,width=width,joint='curve')
    if icon=='coin':
        d.ellipse((x-72,y-72,x+72,y+72),outline=gold,width=7)
        d.ellipse((x-57,y-57,x+57,y+57),outline=accent,width=2)
        line((x-25,y-25,x+25,y-25),gold,7);line((x,y-25,x,y+33),gold,7)
        line((x-90,y+85,x-37,y+66,x+14,y+78,x+86,y+32),accent,5)
    elif icon=='megaphone':
        d.polygon([(x-74,y-30),(x-15,y-30),(x+65,y-68),(x+65,y+45),(x-15,y+14),(x-74,y+14)],outline=accent,width=7)
        line((x-37,y+18,x-23,y+77,x+4,y+77,x-2,y+21),gold,7)
        line((x+86,y-34,x+109,y-48),gold,5);line((x+89,y-8,x+117,y-8),gold,5)
    elif icon=='gamepad':
        d.rounded_rectangle((x-98,y-57,x+98,y+56),radius=35,outline=accent,width=7)
        line((x-68,y,x-25,y),gold);line((x-47,y-22,x-47,y+22),gold)
        for xx,yy in ((x+43,y+10),(x+66,y-13)):d.ellipse((xx-8,yy-8,xx+8,yy+8),fill=gold)
        line((x-15,y-58,x-15,y-85,x+12,y-85),accent,5)
    elif icon in ('shield','medal'):
        if icon=='shield':
            line((x,y-85,x+65,y-60,x+59,y+20,x+34,y+60,x,y+83,x-34,y+60,x-59,y+20,x-65,y-60,x,y-85))
            line((x-29,y,x-5,y+25,x+34,y-22),gold,8)
        else:
            d.polygon([(x-45,y+22),(x-69,y+88),(x-29,y+71),(x-6,y+99),(x+7,y+38)],outline=accent,width=5)
            d.polygon([(x+45,y+22),(x+69,y+88),(x+29,y+71),(x+6,y+99),(x-7,y+38)],outline=accent,width=5)
            d.ellipse((x-60,y-78,x+60,y+42),fill='#211C32',outline=gold,width=6)
            import math
            pts=[(x+math.cos(-math.pi/2+i*math.pi/5)*(33 if i%2==0 else 15),y-18+math.sin(-math.pi/2+i*math.pi/5)*(33 if i%2==0 else 15)) for i in range(10)]
            d.polygon(pts,fill=gold)
    elif icon=='wallet':
        d.rounded_rectangle((x-87,y-60,x+74,y+62),radius=17,outline=accent,width=7)
        d.rounded_rectangle((x+17,y-18,x+88,y+27),radius=9,fill='#242034',outline=gold,width=5)
        d.ellipse((x+34,y-1,x+43,y+8),fill=gold)
        line((x-43,y-25,x-43,y+26),gold,6);line((x-68,y,x-18,y),gold,6)
    elif icon in ('ledger','checklist'):
        d.rounded_rectangle((x-67,y-86,x+67,y+86),radius=13,outline=accent,width=6)
        for yy in (y-43,y,y+43):
            if icon=='checklist':line((x-44,yy,x-36,yy+9,x-23,yy-8),gold,5)
            else:d.ellipse((x-43,yy-4,x-35,yy+4),fill=gold)
            line((x-9,yy,x+42,yy),accent,5)
    elif icon=='layers':
        for offset in (39,9,-21):
            d.polygon([(x,y-48+offset),(x+87,y-6+offset),(x,y+36+offset),(x-87,y-6+offset)],fill='#211C32',outline=gold if offset==-21 else accent,width=5)
    elif icon in ('podium','chart'):
        for xx,top in ((x-74,y-2),(x-13,y-70),(x+48,y-29)):
            d.rounded_rectangle((xx,top,xx+45,y+69),radius=5,outline=gold if xx==x-13 else accent,width=6)
        line((x-94,y+83,x+112,y+83),accent,3)
    elif icon=='chat':
        d.rounded_rectangle((x-80,y-66,x+80,y+42),radius=25,outline=accent,width=7)
        line((x-41,y+42,x-53,y+76,x-4,y+43),accent,7)
        for xx in (x-34,x,x+34):d.ellipse((xx-6,y-18,xx+6,y-6),fill=gold)
    elif icon=='sliders':
        for xx,yy in ((x-55,y-35),(x,y+25),(x+55,y-8)):
            line((xx,y-75,xx,y+75),accent,5)
            d.ellipse((xx-13,yy-13,xx+13,yy+13),fill='#211C32',outline=gold,width=5)
    else:
        d.ellipse((x-44,y-44,x+44,y+44),outline=gold,width=6)
        for box in ((x-103,y-55,x+103,y+55),(x-54,y-101,x+54,y+101)):d.ellipse(box,outline=accent,width=3)
        d.ellipse((x+88,y-20,x+106,y-2),fill=gold)
    buf=BytesIO();im.save(buf,'JPEG',quality=87,optimize=True)
    return buf.getvalue()


def cached(cache, key):
    with _lock:
        item = cache.get(key)
        if item and item[0] > time.monotonic():
            cache.move_to_end(key)
            return item[1]
        cache.pop(key, None)


def remember(cache, key, value, ttl, limit):
    with _lock:
        cache[key] = (time.monotonic() + ttl, value)
        cache.move_to_end(key)
        while len(cache) > limit:
            cache.popitem(last=False)
    return value


def attach(response, kind, **snapshot):
    """Keep ordinary text available as a complete fallback."""
    response['_visual'] = dict(kind=kind, version=VERSION, **snapshot)
    return response


def amount(kopeks):
    whole, fraction = divmod(int(kopeks), 100)
    return f'{whole:,}'.replace(',', ' ') + f',{fraction:02d} грн'


def media_key(snapshot, photo=b''):
    return hashlib.sha256(json.dumps({k:v for k,v in snapshot.items() if k not in ('edit_message_id','caption')}, sort_keys=True, ensure_ascii=False).encode() + photo).hexdigest()


def ready_response(response):
    """Cached Telegram media can answer directly, without a delivery queue/API trip."""
    snapshot=response['_visual']
    if snapshot.get('uid',response['chat_id'])!=response['chat_id']:
        return None
    photo=(cached(_avatars,response['chat_id']) or b'') if snapshot['kind']=='profile' else b''
    file_id=cached(_files,media_key(snapshot,photo))
    caption=snapshot.get('caption') or response['text']
    if not file_id or len(caption.encode('utf-16-le'))//2>1024:
        return None
    out={k:v for k,v in response.items() if k not in ('_visual','text','link_preview_options','method')}
    if snapshot.get('edit_message_id') and out.get('reply_markup',{}).get('inline_keyboard'):
        mode=out.pop('parse_mode',None)
        media={'type':'photo','media':file_id,'caption':caption}
        if mode:media['parse_mode']=mode
        return dict(out,method='editMessageMedia',message_id=snapshot['edit_message_id'],media=media)
    return dict(out,method='sendPhoto',photo=file_id,caption=caption)


def avatar(uid, api):
    found = cached(_avatars, uid)
    if found is not None:
        return found
    # First display uses the branded silhouette immediately. Slow Telegram
    # avatar lookups run separately and become available on the next refresh.
    with _lock:
        if uid in _avatar_jobs or len(_avatar_jobs)>=16:
            return b''
        _avatar_jobs.add(uid)
    try:
        _avatar_pool.submit(_load_avatar,uid,api)
    except RuntimeError:
        with _lock:
            _avatar_jobs.discard(uid)
    return b''


def _load_avatar(uid, api):
    data = b''
    try:
        photos = api('getUserProfilePhotos', {'user_id': uid, 'limit': 1})
        rows = (photos or {}).get('photos') or []
        if rows:
            # The transport fetches only Telegram's own file path, with a size cap.
            data = api('_profilePhoto', {'file_id': rows[0][0]['file_id']})
    except Exception:
        log.info('trevixo_avatar_unavailable')
    remember(_avatars, uid, data, 21600 if data else 600, 128)
    with _lock:
        _avatar_jobs.discard(uid)


def render(snapshot, photo=b''):
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    key = media_key(snapshot,photo)
    hit = cached(_images, key)
    if hit:
        return key, hit
    if snapshot['kind']=='section':
        return key, remember(_images,key,section_image(snapshot['section']),86400,64)
    w, h = 1200, 650
    # Render glow on a small canvas and scale it once, keeping CPU work bounded.
    bg = Image.new('RGB', (300, 163))
    pixels = bg.load()
    for y in range(163):
        for x in range(300):
            glow = max(0, 1 - (((x-265)/220)**2 + ((y-25)/155)**2))**2
            pixels[x, y] = (int(16+37*glow), int(16+13*glow), int(27+78*glow))
    im = bg.resize((w, h), Image.Resampling.BICUBIC)
    d = ImageDraw.Draw(im)
    gold, white, muted = '#D9B65D', '#F5F5FA', '#B4AFC9'

    def font(size):
        return ImageFont.truetype(str(FONT), size)

    def text(x, y, value, size, fill=white, width=None):
        value = ''.join(ch for ch in str(value) if ch.isprintable() and unicodedata.category(ch) not in ('So','Sk','Cf'))
        if width:
            while size > 24 and d.textlength(value, font=font(size)) > width:
                size -= 1
            while value and d.textlength(value, font=font(size)) > width:
                value = value[:-2] + '…'
        d.text((x, y), value, font=font(size), fill=fill)

    d.rounded_rectangle((24, 24, 1175, 625), radius=32, outline='#655078', width=2)
    # Crown mark, shared across profile, welcome and partner cards.
    d.polygon([(66, 78), (78, 103), (103, 66), (128, 103), (142, 78), (133, 120), (75, 120)], fill=gold)
    d.line((77, 130, 132, 130), fill=gold, width=4)
    text(166, 65, 'TREVIXO', 55)
    text(168, 128, 'Возможности в одном месте', 22, muted)
    d.line((65, 196, 1134, 196), fill='#4D395E', width=2)
    kind = snapshot['kind']
    if kind == 'welcome':
        text(65, 255, 'ТВОИ ВОЗМОЖНОСТИ', 64, width=1060)
        text(65, 339, 'В ОДНОМ МЕСТЕ', 64, gold)
        text(67, 476, 'Задания   /   Продвижение   /   Игры', 31, muted)
        text(67, 563, 'TREVIXO  ·  PREMIUM DARK', 21, gold)
    else:
        text(720, 84, 'PREMIUM ACCOUNT' if kind == 'profile' else 'PARTNER NETWORK', 25, gold)
        if photo:
            try:
                av = Image.open(BytesIO(photo))
                av = ImageOps.fit(av.convert('RGB'), (88, 88))
                mask = Image.new('L', (88, 88))
                ImageDraw.Draw(mask).ellipse((0, 0, 87, 87), fill=255)
                im.paste(av, (1044, 65), mask)
            except Exception:
                photo = b''
        if not photo:
            d.ellipse((1044, 65, 1132, 153), fill='#5424A6', outline=gold, width=2)
            d.ellipse((1077, 84, 1099, 106), fill=white)
            d.arc((1063, 108, 1113, 152), 180, 360, fill=white, width=12)
        text(65, 224, snapshot['name'], 38, width=1010)
        text(67, 301, 'МОЙ БАЛАНС' if kind == 'profile' else 'МОЯ КОМАНДА', 25, muted)
        value = amount(snapshot['balance']) if kind == 'profile' else str(snapshot['total']) + ' участников'
        text(61, 341, value, 92, width=1060)
        if kind == 'partners':
            text(67, 463, 'Награды команды: ' + amount(snapshot['earned']), 30, gold, width=1060)
        else:
            text(67, 463, 'Цифровой профиль участника', 26, muted)
        text(67, 559, 'ID  ' + str(snapshot['uid']), 24, gold)
        if snapshot.get('created'):
            stamp = datetime.fromtimestamp(snapshot['created'], ZoneInfo('Europe/Kyiv')).strftime('%d.%m.%Y')
            text(515, 559, 'С нами с ' + stamp, 24, muted)
        d.line((1000, 573, 1129, 573), fill=gold, width=3)
    buf = BytesIO()
    im.save(buf, 'JPEG', quality=88, optimize=True)
    return key, remember(_images, key, buf.getvalue(), 86400 if kind=='welcome' else 300, 64)


def deliver(target, payload, api):
    """Called after transaction commit; a visual failure retains all actions."""
    response = dict(payload)
    snapshot = response.pop('_visual')
    if snapshot.get('uid', target) != target:
        raise ValueError('Card recipient mismatch')
    response.pop('method', None)
    response.pop('chat_id', None)
    caption = snapshot.get('caption') or response.pop('text')
    response.pop('text', None)
    response.pop('link_preview_options', None)
    # Captions have a 1024 UTF-16-unit limit. Long welcome messages stay text.
    if len(caption.encode('utf-16-le')) // 2 > 1024:
        return api('sendMessage', dict(response, chat_id=target, text=caption))
    try:
        photo = avatar(target, api) if snapshot['kind'] == 'profile' else b''
        key, content = render(snapshot, photo)
        file_id = cached(_files, key)
        params = dict(response, chat_id=target, caption=caption)
        if file_id:
            params['photo'] = file_id
        else:
            params['_photo_bytes'] = content
        message_id = snapshot.get('edit_message_id')
        if message_id and 'inline_keyboard' in params.get('reply_markup', {}):
            media = {'type':'photo', 'media':file_id or 'attach://photo', 'caption':caption,
                     'parse_mode':params.get('parse_mode', 'HTML')}
            edit = {'chat_id':target, 'message_id':message_id, 'media':media,
                    'reply_markup':params['reply_markup']}
            if not file_id:
                edit['_photo_bytes'] = content
            try:
                result = api('editMessageMedia', edit)
            except Exception:
                # A deleted, old or uneditable message can still be shown anew.
                result = api('sendPhoto', params)
        else:
            result = api('sendPhoto', params)
        if isinstance(result, dict) and result.get('photo'):
            remember(_files, key, result['photo'][-1]['file_id'], 86400 if snapshot['kind'] in ('welcome','section') else 300, 256)
        return result
    except Exception:
        # Do not print API exceptions: their URLs may contain the bot token.
        log.warning('trevixo_visual_text_fallback kind=%s', snapshot.get('kind'))
        return api('sendMessage', dict(response, chat_id=target, text=caption))
