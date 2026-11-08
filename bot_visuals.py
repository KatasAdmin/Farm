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
    key = hashlib.sha256(json.dumps({k:v for k,v in snapshot.items() if k not in ('edit_message_id','caption')}, sort_keys=True, ensure_ascii=False).encode() + photo).hexdigest()
    hit = cached(_images, key)
    if hit:
        return key, hit
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
            remember(_files, key, result['photo'][-1]['file_id'], 86400 if snapshot['kind']=='welcome' else 300, 256)
        return result
    except Exception:
        # Do not print API exceptions: their URLs may contain the bot token.
        log.warning('trevixo_visual_text_fallback kind=%s', snapshot.get('kind'))
        return api('sendMessage', dict(response, chat_id=target, text=caption))
