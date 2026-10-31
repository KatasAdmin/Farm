"""Persistent copy catalog. Labels never change callback actions or financial values."""
import json
from pathlib import Path
import contextlib
import contextvars
import hashlib
import html
import re
import string
import time
import uuid
from html.parser import HTMLParser

_current=contextvars.ContextVar('bot_copy',default=None)


def initialize(c):
    c.execute("""CREATE TABLE IF NOT EXISTS bot_copy_catalog(key text PRIMARY KEY,kind text NOT NULL,
      section text NOT NULL,original text NOT NULL,custom text,html_mode integer NOT NULL DEFAULT 0,
      max_length integer NOT NULL DEFAULT 3000)""")
    c.execute('CREATE TABLE IF NOT EXISTS bot_menu_aliases(label text PRIMARY KEY,canonical text NOT NULL)')
    defaults=json.loads(Path(__file__).with_name('bot_copy_defaults.json').read_text())
    for item in defaults['texts']:
        key=key_for('text',item['original'],str(int(item['html_mode']))+'|'+str(item['limit']))
        c.execute('INSERT INTO bot_copy_catalog VALUES(%s,%s,%s,%s,NULL,%s,%s) ON CONFLICT DO NOTHING',
                  (key,'text',item['section'],item['original'],int(item['html_mode']),item['limit']))
    c.execute("""CREATE TABLE IF NOT EXISTS bot_copy_history(id text PRIMARY KEY,key text NOT NULL,
      previous text,replacement text,uid bigint NOT NULL,created double precision NOT NULL)""")
    with session(c):
        for item in defaults['buttons']:
            label(item['text'],item['action'])
        from task_bot import MENU
        menu(MENU)


@contextlib.contextmanager
def session(c,owner=False):
    ctx={'c':c,'owner':owner,'rows':{r['key']:r for r in c.execute('SELECT * FROM bot_copy_catalog').fetchall()},'new':{}}
    token=_current.set(ctx)
    try:
        yield ctx
        for key,row in ctx['new'].items():
            c.execute('INSERT INTO bot_copy_catalog VALUES(%s,%s,%s,%s,NULL,%s,%s) ON CONFLICT DO NOTHING',
                      (key,row['kind'],row['section'],row['original'],row['html_mode'],row['max_length']))
    finally:
        _current.reset(token)


def owner():
    ctx=_current.get()
    return bool(ctx and ctx['owner'])


def key_for(kind,original,extra=''):
    return hashlib.sha256((kind+'|'+extra+'|'+original).encode()).hexdigest()[:24]


def render(kind,original,values=None,html_mode=False,section='public',key=None,limit=3000):
    key=key or key_for(kind,original,str(int(html_mode))+'|'+str(limit))
    ctx=_current.get()
    body=original
    if ctx:
        if key not in ctx['rows']:
            row=dict(key=key,kind=kind,section=section,original=original,custom=None,html_mode=int(html_mode),max_length=limit)
            ctx['rows'][key]=row; ctx['new'][key]=row
        body=ctx['rows'][key]['custom'] or original
    def format_body(value):
        return value.format_map(values) if values is not None else value
    try:
        rendered=format_body(body)
        if len(rendered.encode('utf-16-le'))//2>max(limit,len(format_body(original).encode('utf-16-le'))//2):
            raise ValueError('Message too long')
        return rendered
    except (KeyError,ValueError,IndexError):
        return format_body(original)


def tr(original,values=None,html_mode=False,section='public',limit=3000):
    return render('text',original,values,html_mode,section,limit=limit)


def label(text,action):
    # These rows contain customer-supplied task titles, proofs or request identifiers.
    if action.split(':')[0] in ('task','own','review') or action.startswith(('admin:cardview:','admin:bindpost:','admin:payview:','admin:copyentry:','admin:copyrestore:','admin:ticketview:')):
        return text
    values={}
    def number(match):
        key='v'+str(len(values)); values[key]=match.group()
        return '{'+key+'}'
    original=re.sub(r'\d+(?:[.,]\d+)?',number,text.replace('{','{{').replace('}','}}'))
    parts=['*' if re.fullmatch(r'(?:[0-9a-f]{12,64}|\d+)',p) else p for p in action.split(':')]
    key=key_for('button',original,':'.join(parts))
    return render('button',original,values,False,'admin' if action.startswith('admin') else 'public',key,64)


def menu(rows):
    out=[]
    for i,row in enumerate(rows):
        result=[]
        for j,canonical in enumerate(row):
            key='menu_'+str(i)+'_'+str(j)
            result.append(render('menu',canonical,None,False,'menu',key,48))
        out.append(result)
    return out


def canonical_menu(c,text):
    row=c.execute('SELECT canonical FROM bot_menu_aliases WHERE label=%s',(text,)).fetchone()
    return row['canonical'] if row else text


def fields(template):
    return [field for _,field,spec,conv in string.Formatter().parse(template) if field is not None]


class Tags(HTMLParser):
    def __init__(self):
        super().__init__(); self.stack=[]; self.valid=True
    def handle_starttag(self,tag,attrs):
        if tag not in ('b','i','u','s','code','pre') or attrs:
            self.valid=False
        self.stack.append(tag)
    def handle_endtag(self,tag):
        if not self.stack or self.stack.pop()!=tag:
            self.valid=False


def validate(c,row,body):
    import task_bot as b
    if not body.strip() or any(ord(ch)<32 and ch not in '\n\t' for ch in body):
        raise b.UserError('Текст не может быть пустым.')
    if len(body.encode('utf-16-le'))//2>row['max_length']:
        raise b.UserError('Текст слишком длинный. Сократи его.')
    try:
        before=fields(row['original']); after=fields(body)
        if any(spec or conv for _,field,spec,conv in string.Formatter().parse(body) if field is not None):
            raise ValueError
        if sorted(before)!=sorted(after) or any(not re.fullmatch(r'v\d+',v) for v in after):
            raise ValueError
        body.format_map({v:'…' for v in after})
    except (ValueError,KeyError,IndexError,AttributeError):
        raise b.UserError('Сохрани все метки {v0}, {v1} и другие ровно по одному разу, как в исходном тексте.')
    if row['html_mode']:
        parser=Tags(); parser.feed(body)
        if not parser.valid:
            raise b.UserError('Используй только обычный текст и стандартное выделение Telegram.')
        if parser.stack:
            # Some older strings are HTML fragments. Preserve their tag structure.
            tag_pattern=r'</?(?:b|i|u|s|code|pre)(?:\s[^>]*)?>'
            if re.findall(tag_pattern,body)!=re.findall(tag_pattern,row['original']):
                raise b.UserError('Нарушено оформление. Используй исходные метки выделения или обычный текст.')
    if row['kind'] in ('menu','button') and ('\n' in body or '\t' in body):
        raise b.UserError('Надпись кнопки должна занимать одну строку.')
    if row['kind']=='menu':
        if body.startswith('/') or body.isdecimal():
            raise b.UserError('Для раздела меню нужно понятное название, не команда и не число.')
        canonical=row['original']
        existing=c.execute('SELECT canonical FROM bot_menu_aliases WHERE label=%s',(body,)).fetchone()
        if existing and existing['canonical']!=canonical:
            raise b.UserError('Это название уже используется другим разделом меню.')
        for r in c.execute("SELECT original FROM bot_copy_catalog WHERE kind='menu'").fetchall():
            if body==r['original'] and body!=canonical:
                raise b.UserError('Это название принадлежит другому разделу.')


def save(c,uid,key,body):
    row=c.execute('SELECT * FROM bot_copy_catalog WHERE key=%s',(key,)).fetchone()
    if not row:
        import task_bot as b
        raise b.UserError('Текст не найден. Открой каталог заново.')
    if body is not None:
        validate(c,row,body)
    c.execute('UPDATE bot_copy_catalog SET custom=%s WHERE key=%s',(body,key))
    c.execute('INSERT INTO bot_copy_history VALUES(%s,%s,%s,%s,%s,%s)',
              (uuid.uuid4().hex,key,row['custom'],body,uid,time.time()))
    if row['kind']=='menu':
        for name in (row['original'],body or row['original']):
            c.execute('INSERT INTO bot_menu_aliases VALUES(%s,%s) ON CONFLICT DO NOTHING',(name,row['original']))
    ctx=_current.get()
    if ctx and key in ctx['rows']:
        ctx['rows'][key]['custom']=body


def preview(row):
    body=row['custom'] or row['original']
    try:
        rendered=body.format_map({v:'‹значение›' for v in fields(body)})
    except (ValueError,KeyError):
        rendered=body
    return rendered if row['html_mode'] else html.escape(rendered)
