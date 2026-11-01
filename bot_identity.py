"""Searchable Telegram identity data received from that user's own updates."""
import re
import time
from urllib.parse import urlsplit,parse_qs


def initialize(c):
    c.execute("CREATE TABLE IF NOT EXISTS bot_identities(uid bigint PRIMARY KEY,username text NOT NULL DEFAULT '',phone text NOT NULL DEFAULT '',updated double precision NOT NULL)")
    c.execute('CREATE INDEX IF NOT EXISTS bot_identity_username ON bot_identities(username)')
    c.execute('CREATE INDEX IF NOT EXISTS bot_identity_phone ON bot_identities(phone)')


def phone(value):
    if not isinstance(value,str) or len(value)>32 or not re.fullmatch(r'[+0-9 ()\-]+',value):return None
    digits=re.sub(r'\D','',value)
    if digits.startswith('00'):digits=digits[2:]
    if len(digits)==10 and digits.startswith('0'):digits='38'+digits
    if not 8<=len(digits)<=15:return None
    return '+'+digits


def record(c,uid,sender,message=None):
    username=sender.get('username') or ''
    username=username.lower() if re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{3,31}',username) else ''
    if username:c.execute("UPDATE bot_identities SET username='' WHERE username=%s AND uid<>%s",(username,uid))
    c.execute("INSERT INTO bot_identities(uid,username,updated) VALUES(%s,%s,%s) ON CONFLICT(uid) DO UPDATE SET username=EXCLUDED.username,updated=EXCLUDED.updated",(uid,username,time.time()))
    contact=(message or {}).get('contact') or {}
    if contact.get('user_id')==uid:
        value=phone(contact.get('phone_number'))
        if value:c.execute('UPDATE bot_identities SET phone=%s WHERE uid=%s',(value,uid))


def parse_query(raw):
    text=raw.strip()
    if text.startswith(('t.me/','telegram.me/')):text='https://'+text
    if text.startswith(('https://','http://','tg://')):
        parsed=urlsplit(text)
        if parsed.scheme=='tg' and parsed.netloc=='user':
            value=parse_qs(parsed.query).get('id',[''])[0]
            if value.isdecimal():return 'uid',value
        if parsed.hostname in ('t.me','telegram.me'):
            value=parsed.path.strip('/')
            if re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{3,31}',value):return 'username',value.lower()
        return 'invalid',''
    if text.startswith('@'):
        value=text[1:]
        return ('username',value.lower()) if re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{3,31}',value) else ('invalid','')
    # Plain digits retain exact Telegram-ID lookup. Also try phone as a fallback.
    if text.startswith('+') or text.startswith('00') or re.fullmatch(r'0\d{9}',text) or not text.isdecimal() and phone(text):
        value=phone(text)
        if value:return 'phone',value
    if text.isdecimal():return 'uid',text
    return 'name',text
