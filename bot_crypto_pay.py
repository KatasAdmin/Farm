"""TREVIXO Crypto Pay integration: verified UAH invoices and idempotent USDT payouts.

Never accepts a user-supplied payment confirmation. Transfers are disabled unless the
owner explicitly supplies credentials, enables transfers and defines a UAH ceiling.
"""
import json
import base64
import hashlib
from cryptography.fernet import Fernet, InvalidToken
import logging
import os
import time
import uuid
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

log = logging.getLogger(__name__)
HOSTS = {'main':'https://pay.crypt.bot/api/','test':'https://testnet-pay.crypt.bot/api/'}
ASSET = 'USDT'


class CryptoPayError(Exception):
    pass


_runtime_token = None

def _cipher():
    """Encrypt owner-edited token at rest with a key NOT stored in the database."""
    key=os.getenv('TELEGRAM_BOT_TOKEN','')
    if not key:
        raise CryptoPayError('Encryption key unavailable')
    derived=hashlib.sha256(('TREVIXO Crypto Pay token v1:'+key).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(derived))

def token():
    return _runtime_token if _runtime_token is not None else os.getenv('CRYPTOPAY_API_TOKEN','').strip()

def replace_token(c, plaintext):
    """Must only be called by owner admin route after deleting the input message."""
    global _runtime_token
    if not isinstance(plaintext,str) or not (20 <= len(plaintext) <= 400) or any(ch.isspace() for ch in plaintext):
        raise CryptoPayError('Invalid Crypto Pay token')
    old=_runtime_token
    _runtime_token=plaintext
    try:
        data=call('getMe')
        if not isinstance(data,dict):
            raise CryptoPayError('Crypto Pay did not confirm the token')
        encrypted=_cipher().encrypt(plaintext.encode()).decode()
        c.execute("INSERT INTO bot_crypto_credentials(id,encrypted_token) VALUES(1,%s) ON CONFLICT(id) DO UPDATE SET encrypted_token=EXCLUDED.encrypted_token",(encrypted,))
    except Exception:
        _runtime_token=old
        raise

def reset_token(c):
    global _runtime_token
    c.execute("DELETE FROM bot_crypto_credentials WHERE id=1")
    _runtime_token=None

def payout_cap(c):
    try:
        env_cap=max(0,int(os.getenv('CRYPTOPAY_MAX_PAYOUT_UAH','0')))
    except ValueError:
        env_cap=0
    row=c.execute("SELECT value FROM bot_controls WHERE key='crypto_payout_cap'").fetchone()
    chosen=row['value'] if row else env_cap
    return min(env_cap,chosen)

def available():
    return bool(token() and os.getenv('CRYPTOPAY_DEPOSITS_ENABLED')=='1')


def withdrawals_enabled():
    try:
        cap=int(os.getenv('CRYPTOPAY_MAX_PAYOUT_UAH','0'))
    except ValueError:
        return False
    return bool(token() and os.getenv('CRYPTOPAY_AUTO_PAYOUTS_ENABLED')=='1' and cap>0)


def call(method, data=None):
    if method not in ('getMe','getInvoices','createInvoice','getTransfers','transfer','getExchangeRates','createCheck','getChecks','deleteCheck','getBalance'):
        raise ValueError('Invalid Crypto Pay method')
    secret=token()
    if not secret:
        raise CryptoPayError('Crypto Pay is not configured')
    base=HOSTS['test'] if os.getenv('CRYPTOPAY_TESTNET')=='1' else HOSTS['main']
    raw=json.dumps(data or {},ensure_ascii=True).encode('utf-8')
    # getMe is parameterless. The documented GET avoids an unnecessary body,
    # and a clear User-Agent reduces false positives at upstream edge filters.
    is_get=method in ('getMe','getBalance')
    req=Request(base+method, data=None if is_get else raw,
        method='GET' if is_get else 'POST',headers={
        'Crypto-Pay-API-Token':secret,
        'Content-Type':'application/json',
        'Accept':'application/json',
        'User-Agent':'TrevixoCryptoPay/1.0 (+merchant integration)'})
    try:
        with urlopen(req,timeout=12) as response:
            body=response.read(100000)
    except HTTPError as exc:
        # Show only a safe diagnostic category, never response bodies or headers.
        # An HTML 403 is usually an edge denial; JSON errors are API decisions.
        content_type=str(exc.headers.get('Content-Type','')).lower()
        server=str(exc.headers.get('Server','')).lower()
        try:
            payload=json.loads(exc.read(8192)) if 'json' in content_type else None
        except (ValueError,TypeError,OSError):
            payload=None
        code=payload.get('error') if isinstance(payload,dict) else None
        if isinstance(code,str) and 1<=len(code)<=100 and all(ch.isalnum() or ch=='_' for ch in code):
            raise CryptoPayError('Crypto Pay HTTP '+str(exc.code)+': '+code) from None
        if exc.code==403 and ('html' in content_type or 'cloudflare' in server):
            raise CryptoPayError('HTTP 403: доступ отклонён сетевой защитой Crypto Pay/CDN (HTML). Токен может быть верным; требуется проверка у поддержки.') from None
        raise CryptoPayError('Crypto Pay HTTP '+str(exc.code)+': ответ без кода API. Проверь доступ приложения и сеть.') from None
    except (URLError, TimeoutError, OSError) as exc:
        raise CryptoPayError('Соединение с Crypto Pay недоступно: '+type(exc).__name__) from None
    try:
        result=json.loads(body)
    except (ValueError,TypeError):
        raise CryptoPayError('Некорректный ответ Crypto Pay') from None
    if not isinstance(result,dict) or result.get('ok') is not True:
        code=result.get('error') if isinstance(result,dict) else None
        if isinstance(code,str) and 1<=len(code)<=100 and all(ch.isalnum() or ch=='_' for ch in code):
            raise CryptoPayError('Crypto Pay: '+code)
        raise CryptoPayError('Crypto Pay отклонил запрос; проверь API и настройки приложения.')
    return result['result']


def initialize(c):
    global _runtime_token
    c.execute("CREATE TABLE IF NOT EXISTS bot_crypto_credentials(id integer PRIMARY KEY CHECK(id=1),encrypted_token text NOT NULL)")
    row=c.execute("SELECT encrypted_token FROM bot_crypto_credentials WHERE id=1").fetchone()
    if row:
        try:
            _runtime_token=_cipher().decrypt(row['encrypted_token'].encode()).decode()
        except (InvalidToken,ValueError):
            raise CryptoPayError('Crypto Pay saved token cannot be decrypted; restore original bot secret or reset credentials')
    else:
        _runtime_token=None
    c.execute("""CREATE TABLE IF NOT EXISTS bot_crypto_invoices(
        id text PRIMARY KEY, uid bigint NOT NULL, invoice_id bigint NOT NULL UNIQUE,
        amount bigint NOT NULL CHECK(amount>0),
        status text NOT NULL CHECK(status IN ('pending','paid')),
        created double precision NOT NULL)""")
    c.execute("CREATE TABLE IF NOT EXISTS bot_crypto_schema_migrations(key text PRIMARY KEY)")
    fresh=c.execute("""INSERT INTO bot_crypto_schema_migrations(key)
      VALUES('invoice-last-checked-v1') ON CONFLICT DO NOTHING RETURNING key""").fetchone()
    if fresh:
        c.execute("ALTER TABLE bot_crypto_invoices ADD COLUMN last_checked_at double precision NOT NULL DEFAULT 0")
    c.execute("""CREATE TABLE IF NOT EXISTS bot_crypto_payouts(
        payout_id text PRIMARY KEY, asset text NOT NULL, crypto_amount text NOT NULL,
        spend_id text NOT NULL UNIQUE,
        state text NOT NULL CHECK(state IN ('pending','sending','review','completed')),
        created double precision NOT NULL, transfer_id bigint)""")
    c.execute('CREATE INDEX IF NOT EXISTS bot_crypto_invoice_queue ON bot_crypto_invoices(status,created)')
    c.execute('CREATE INDEX IF NOT EXISTS bot_crypto_payout_queue ON bot_crypto_payouts(state,created)')
    # Check creation is never blindly repeated: Crypto Pay's public createCheck
    # does not guarantee a caller-supplied idempotency key.
    c.execute("""CREATE TABLE IF NOT EXISTS bot_crypto_checks(
        payout_id text PRIMARY KEY,check_id bigint UNIQUE,check_url text NOT NULL DEFAULT '',
        state text NOT NULL CHECK(state IN ('creating','active','review','activated')),
        created double precision NOT NULL)""")
    c.execute("UPDATE bot_crypto_checks SET state='review' WHERE state='creating'")
    c.execute("""CREATE TABLE IF NOT EXISTS bot_crypto_liquidity_wait(
        payout_id text PRIMARY KEY REFERENCES bot_crypto_payouts(payout_id),
        created double precision NOT NULL,
        checked double precision NOT NULL DEFAULT 0)""")
    # If process crashed after sending, do NOT send again: first reconcile spend_id.
    c.execute("UPDATE bot_crypto_payouts SET state='review' WHERE state='sending'")
    c.execute("""CREATE TABLE IF NOT EXISTS bot_crypto_incidents(
       payout_id text PRIMARY KEY, phase text NOT NULL,
       reason text NOT NULL, created double precision NOT NULL)""")


def uah(n):
    return format(Decimal(n)/100,'.2f')


def create_invoice(c,uid,amount):
    if not available():
        raise CryptoPayError('Пополнение через Crypto Bot пока не включено.')
    if type(amount) is not int or not 100<=amount<=1000000:
        raise CryptoPayError('Для Crypto Bot укажи сумму от 1 до 10 000 грн.')
    order=uuid.uuid4().hex
    external=call('createInvoice', {
        'currency_type':'fiat','fiat':'UAH','amount':uah(amount),
        'accepted_assets':'USDT,TON,BTC,ETH,LTC,TRX,USDC',
        'payload':'trevixo_'+order,'description':'Пополнение TREVIXO',
        'allow_anonymous':False,'expires_in':3600})
    if not isinstance(external,dict) or type(external.get('invoice_id')) is not int:
        raise CryptoPayError('Crypto Bot не вернул корректный счёт.')
    url=external.get('bot_invoice_url') or external.get('mini_app_invoice_url')
    if not isinstance(url,str) or not url.startswith(('https://t.me/','https://pay.crypt.bot/','https://testnet-pay.crypt.bot/')):
        raise CryptoPayError('Crypto Bot не вернул безопасную ссылку на оплату.')
    c.execute("""INSERT INTO bot_crypto_invoices(id,uid,invoice_id,amount,status,created)
      VALUES(%s,%s,%s,%s,'pending',%s)""",(order,uid,external['invoice_id'],amount,time.time()))
    return order,url


def _lookup_invoice(invoice_id):
    result=call('getInvoices',{'invoice_ids':str(invoice_id)})
    # Crypto Pay wraps the list as {"count":N,"items":[...]}.
    # Accept a plain list too for compatibility with historical fixtures.
    items=result.get('items') if isinstance(result,dict) else result
    if not isinstance(items,list):
        raise CryptoPayError('Crypto Pay вернул некорректный список счетов')
    for item in items:
        if isinstance(item,dict) and item.get('invoice_id')==invoice_id:
            return item
    return None


def _verified_invoice(row,record):
    if not isinstance(record,dict) or record.get('status')!='paid':
        return False
    try:
        amount=Decimal(str(record.get('amount','')))
    except InvalidOperation:
        return False
    return (record.get('invoice_id')==row['invoice_id']
        and record.get('currency_type')=='fiat'
        and record.get('fiat')=='UAH'
        and record.get('payload')=='trevixo_'+row['id']
        and amount==Decimal(row['amount'])/100)


def settle_invoice(db,order_id):
    if not available():
        return False
    with db() as c:
        row=c.execute("SELECT * FROM bot_crypto_invoices WHERE id=%s AND status='pending'",(order_id,)).fetchone()
    if not row:
        return False
    payment=_lookup_invoice(row['invoice_id'])
    if not _verified_invoice(row,payment):
        return False
    import task_bot as b
    with db() as c:
        c.execute('SELECT pg_advisory_xact_lock(1984533)')
        row=c.execute("SELECT * FROM bot_crypto_invoices WHERE id=%s AND status='pending' FOR UPDATE",(order_id,)).fetchone()
        if not row:
            return False
        # No credit without independently confirmed paid invoice.
        c.execute("UPDATE bot_crypto_invoices SET status='paid' WHERE id=%s",(order_id,))
        b.change(c,row['uid'],row['amount'],'cryptopay_deposit','Crypto Pay · '+order_id)
        c.execute('UPDATE bot_cash_pool SET amount=amount+%s WHERE id=1',(row['amount'],))
        b.bot_notifications.enqueue(c,'crypto-paid:'+order_id,
            '✅ Crypto Bot: пополнение '+b.money(row['amount'])+' зачислено.',
            recipient=row['uid'])
        # Owner notification must be persisted with the same successful credit.
        b.bot_notifications.enqueue(c,'crypto-paid-admin:'+order_id,
            '💎 Пополнение CryptoBot подтверждено\n'
            'Пользователь: '+str(row['uid'])+'\n'
            'Зачислено: '+b.money(row['amount'])+'\n'
            'Счёт: '+str(row['invoice_id'])+'\n'
            'Операция: '+order_id,
            action='admin:payments:all:0',subject=row['uid'])
    return True


def quote_usdt(net,c=None):
    if not withdrawals_enabled():
        raise CryptoPayError('Автоматический криптовывод ещё не включён.')
    try:
        cap=int(os.getenv('CRYPTOPAY_MAX_PAYOUT_UAH','0'))
    except ValueError:
        cap=0
    if c is not None:
        cap=min(cap,payout_cap(c))
        # Avoid trapping additional user balances while Crypto Pay's CDN blocks
        # outbound payout requests. This pauses new requests, not reconciliation.
        outage=c.execute("""SELECT reason,created FROM bot_crypto_incidents
            WHERE reason LIKE 'HTTP 403:%' ORDER BY created DESC LIMIT 1""").fetchone()
        if outage and time.time()-outage['created']<600:
            raise CryptoPayError(
                'CryptoBot временно не принимает новые выплаты. '
                'Уже созданные заявки сохранены. Выбери вывод на карту или повтори позже.')
    if type(net) is not int or net<100 or net>cap*100:
        raise CryptoPayError('Сумма криптовывода вне разрешённого лимита.')
    rates=call('getExchangeRates')
    if not isinstance(rates,list):
        raise CryptoPayError('Курс Crypto Bot недоступен.')
    item=next((r for r in rates if isinstance(r,dict) and r.get('source')=='USDT'
               and r.get('target')=='UAH' and r.get('is_valid') is True),None)
    if not item:
        raise CryptoPayError('Нет актуального курса USDT/UAH.')
    try:
        rate=Decimal(str(item['rate']))
        if rate<=0:raise InvalidOperation()
        value=((Decimal(net)/100)/rate).quantize(Decimal('0.000001'),rounding=ROUND_DOWN)
    except (InvalidOperation, ValueError):
        raise CryptoPayError('Недопустимый курс.')
    if value<=0:
        raise CryptoPayError('Сумма слишком мала для точности USDT. Выбери другой способ выплаты.')
    # Up to and including 1 USDT is paid by a user-pinned single-use check;
    # provider-specific minimums are enforced by Crypto Pay when creating it.
    return format(value,'.6f')


def enqueue_payout(c,pid,usdt):
    amount=Decimal(str(usdt))
    if amount<=0 or amount>25000:
        raise CryptoPayError('Invalid cryptocurrency amount')
    c.execute("""INSERT INTO bot_crypto_payouts(payout_id,asset,crypto_amount,spend_id,state,created)
      VALUES(%s,'USDT',%s,%s,'pending',%s) ON CONFLICT DO NOTHING""",
      (pid,format(amount,'.6f'),'trevixo_'+pid,time.time()))



def _record_incident(db,row,phase,exc):
    # Expose only sanitized diagnostic text, never API tokens or raw headers.
    reason=str(exc) if isinstance(exc,CryptoPayError) else type(exc).__name__
    reason=reason[:300]
    with db() as c:
        c.execute("""INSERT INTO bot_crypto_incidents(payout_id,phase,reason,created)
            VALUES(%s,%s,%s,%s) ON CONFLICT(payout_id)
            DO UPDATE SET phase=EXCLUDED.phase,reason=EXCLUDED.reason,created=EXCLUDED.created""",
            (row['payout_id'],phase,reason,time.time()))


def _insufficient_funds(exc):
    if not isinstance(exc,CryptoPayError):
        return False
    reason=str(exc).upper()
    return any(word in reason for word in (
        'INSUFFICIENT_FUNDS','INSUFFICIENT_BALANCE','NOT_ENOUGH_FUNDS',
        'NOT_ENOUGH_BALANCE','BALANCE_NOT_ENOUGH','INSUFFICIENT_ASSET'))


def _wait_for_liquidity(db,row,kind):
    # Only an explicit provider rejection is safe to retry automatically.
    import task_bot as b
    with db() as c:
        c.execute("UPDATE bot_crypto_payouts SET state='pending' WHERE payout_id=%s AND state='sending'",(row['payout_id'],))
        if kind=='check':
            c.execute("DELETE FROM bot_crypto_checks WHERE payout_id=%s AND state='creating'",(row['payout_id'],))
        c.execute("""INSERT INTO bot_crypto_liquidity_wait(payout_id,created) VALUES(%s,%s)
            ON CONFLICT DO NOTHING""",(row['payout_id'],time.time()))
        b.bot_notifications.enqueue(c,'liquidity-admin:'+row['payout_id'],
            '⚠️ CryptoBot: недостаточно USDT.\n'
            'Заявка: '+row['payout_id']+' · '+row['crypto_amount']+' USDT.\n'
            'Пополните резерв — бот повторит автоматически. Можно проверить вручную в заявке.',
            action='admin:payview:'+row['payout_id'],subject=row['uid'])


def _balance_usdt():
    result=call('getBalance')
    items=result.get('items') if isinstance(result,dict) else result
    if not isinstance(items,list):
        raise CryptoPayError('Crypto Pay returned invalid balance information')
    asset=next((entry for entry in items
        if isinstance(entry,dict) and entry.get('currency_code')=='USDT'),None)
    if not asset:
        return Decimal('0')
    try:
        return Decimal(str(asset.get('available','0')))
    except (InvalidOperation,ValueError):
        raise CryptoPayError('Crypto Pay balance is invalid') from None


def _preflight_liquidity(db,row,kind):
    # A confirmed lack of funds is a safe, retryable non-send. If the balance
    # endpoint itself fails, leave the payout to the normal provider path.
    try:
        enough=_balance_usdt() >= Decimal(row['crypto_amount'])
    except (CryptoPayError,ValueError,InvalidOperation):
        return True
    if enough:
        return True
    _wait_for_liquidity(db,row,kind)
    return False


def _release_funded_hold(db):
    # The provider must independently confirm enough available USDT.
    with db() as c:
        row=c.execute("""SELECT h.payout_id,cp.crypto_amount FROM bot_crypto_liquidity_wait h
            JOIN bot_crypto_payouts cp ON cp.payout_id=h.payout_id
            JOIN bot_payouts p ON p.id=cp.payout_id
            WHERE cp.state='pending' AND p.status='pending'
            ORDER BY h.created LIMIT 1""").fetchone()
    if not row:
        return False
    try:
        if _balance_usdt()<Decimal(row['crypto_amount']):
            return False
    except (CryptoPayError,ValueError,InvalidOperation,TypeError):
        return False
    with db() as c:
        c.execute("DELETE FROM bot_crypto_liquidity_wait WHERE payout_id=%s",(row['payout_id'],))
    return True


def _check_items(check_id):
    result=call('getChecks',{'check_ids':str(check_id)})
    items=result.get('items') if isinstance(result,dict) else result
    if not isinstance(items,list):
        raise CryptoPayError('Crypto Pay returned an invalid check list')
    return [x for x in items if isinstance(x,dict) and x.get('check_id')==check_id]


def _verified_check(check, remote):
    if not isinstance(remote,dict) or remote.get('check_id')!=check['check_id']:
        return False
    if remote.get('asset')!='USDT':
        return False
    try:
        payout=Decimal(check['crypto_amount'])
        amount=Decimal(str(remote.get('amount','')))
    except (ValueError,InvalidOperation):
        return False
    return amount==payout and remote.get('status') in ('active','activated')


def _finalize_check(db,check,remote):
    if remote.get('status')!='activated' or not _verified_check(check,remote):
        return False
    import task_bot as b
    with db() as c:
        c.execute('SELECT pg_advisory_xact_lock(1984533)')
        p=c.execute("SELECT * FROM bot_payouts WHERE id=%s AND status='pending' FOR UPDATE",(check['payout_id'],)).fetchone()
        ch=c.execute("SELECT * FROM bot_crypto_checks WHERE payout_id=%s AND state='active' FOR UPDATE",(check['payout_id'],)).fetchone()
        if not p or not ch or ch['check_id']!=check['check_id']:
            return False
        net=b.bot_admin.net(c,p)
        c.execute("UPDATE bot_crypto_checks SET state='activated' WHERE payout_id=%s",(p['id'],))
        c.execute("UPDATE bot_crypto_payouts SET state='completed' WHERE payout_id=%s",(p['id'],))
        c.execute("DELETE FROM bot_crypto_incidents WHERE payout_id=%s",(p['id'],))
        c.execute("UPDATE bot_payouts SET status='paid',reference=%s WHERE id=%s",('cryptocheck_'+str(ch['check_id']),p['id']))
        c.execute('UPDATE bot_cash_pool SET amount=CASE WHEN amount>=%s THEN amount-%s ELSE 0 END WHERE id=1',(net,net))
        c.execute("INSERT INTO bot_ledger VALUES(%s,%s,0,'payout_paid',%s,%s)",(uuid.uuid4().hex,p['uid'],'Crypto Pay check activated '+str(ch['check_id']),time.time()))
        b.bot_notifications.enqueue(c,'check-activated-user:'+p['id'],
            '✅ Выплата '+b.money(net)+' получена через CryptoBot.',recipient=p['uid'])
        b.bot_notifications.enqueue(c,'check-activated-admin:'+p['id'],
            '✅ CryptoBot: именной чек активирован. Получатель: '+str(p['uid'])+
            '. Сумма: '+b.money(net)+'. Чек №'+str(ch['check_id']),
            action='admin:payview:'+p['id'],subject=p['uid'])
        b.bot_payout_channel.enqueue_paid(c,p['id'],b.money(net),recipient_uid=p['uid'] if p['public_profile'] else None)
    return True


def _check_dispatch(db):
    # Reconcile one known check before creating additional checks.
    with db() as c:
        row=c.execute("""SELECT cp.*,p.uid,ch.check_id,ch.check_url,ch.state AS check_state
          FROM bot_crypto_payouts cp
          JOIN bot_payouts p ON p.id=cp.payout_id
          JOIN bot_crypto_checks ch ON ch.payout_id=cp.payout_id
          WHERE ch.state='active' AND p.status='pending'
          ORDER BY ch.created LIMIT 1""").fetchone()
    if row:
        try:
            remote=next(iter(_check_items(row['check_id'])),None)
            if remote and _verified_check(row,remote):
                return _finalize_check(db,row,remote)
        except Exception:
            log.warning('Crypto Pay check reconciliation temporarily unavailable payout=%s',row['payout_id'])
        # An active check is not a blocker for new payouts.
    if not withdrawals_enabled():
        return False
    import bot_admin
    with db() as c:
        if not bot_admin.method_enabled(c,'crypto_withdraw') or payout_cap(c)<=0:
            return False
        c.execute('SELECT pg_advisory_xact_lock(1984537)')
        selected=c.execute("""SELECT cp.*,p.uid FROM bot_crypto_payouts cp
            JOIN bot_payouts p ON p.id=cp.payout_id
            LEFT JOIN bot_crypto_checks ch ON ch.payout_id=cp.payout_id
            WHERE cp.state='pending' AND p.status='pending'
              AND ch.payout_id IS NULL
              AND NOT EXISTS(SELECT 1 FROM bot_crypto_liquidity_wait h WHERE h.payout_id=cp.payout_id)
            ORDER BY cp.created FOR UPDATE OF cp LIMIT 20""").fetchall()
        row=next((r for r in selected if Decimal(r['crypto_amount'])<=Decimal('1')),None)
        if not row:
            return False
        caprow=c.execute('SELECT net FROM bot_payout_terms WHERE id=%s',(row['payout_id'],)).fetchone()
        if caprow and caprow['net']>payout_cap(c)*100:
            return False
        c.execute("UPDATE bot_crypto_payouts SET state='sending' WHERE payout_id=%s",(row['payout_id'],))
        c.execute("INSERT INTO bot_crypto_checks(payout_id,state,created) VALUES(%s,'creating',%s)",(row['payout_id'],time.time()))
    try:
        if not _preflight_liquidity(db,row,'check'):
            return False
        remote=call('createCheck',{'asset':'USDT','amount':row['crypto_amount'],'pin_to_user_id':row['uid']})
        check_id=remote.get('check_id') if isinstance(remote,dict) else None
        url=remote.get('bot_check_url') if isinstance(remote,dict) else None
        if type(check_id) is not int or not isinstance(url,str) or not url.startswith('https://t.me/'):
            raise CryptoPayError('Unverified check creation result')
        if remote.get('asset')!='USDT' or Decimal(str(remote.get('amount',''))) != Decimal(row['crypto_amount']):
            raise CryptoPayError('Check amount mismatch')
        with db() as c:
            c.execute("UPDATE bot_crypto_checks SET state='active',check_id=%s,check_url=%s WHERE payout_id=%s AND state='creating'",(check_id,url,row['payout_id']))
            c.execute("UPDATE bot_crypto_payouts SET state='review' WHERE payout_id=%s AND state='sending'",(row['payout_id'],))
            import task_bot as b
            b.bot_notifications.enqueue(c,'check-issued:'+row['payout_id'],
                '🎁 Твой чек CryptoBot готов!\n'
                'К получению: '+row['crypto_amount']+' USDT.\n'
                'Нажми «Забрать чек». Если потеряешь его, ссылка есть в «Мои выплаты».',
                recipient=row['uid'],url=url)
        return True
    except Exception as exc:
        _record_incident(db,row,'createCheck',exc)
        if _insufficient_funds(exc):
            _wait_for_liquidity(db,row,'check')
            return False
        # Unknown result might have created a check. Do not issue a second one.
        log.warning('Crypto Pay check not confirmed payout=%s kind=%s reason=%s',
                    row['payout_id'],type(exc).__name__,
                    str(exc) if isinstance(exc,CryptoPayError) else type(exc).__name__)
        with db() as c:
            c.execute("UPDATE bot_crypto_checks SET state='review' WHERE payout_id=%s AND state='creating'",(row['payout_id'],))
            c.execute("UPDATE bot_crypto_payouts SET state='review' WHERE payout_id=%s AND state='sending'",(row['payout_id'],))
        with db() as c:
            import task_bot as b
            b.bot_notifications.enqueue(c,'check-review-admin:'+row['payout_id'],
                '⚠️ CryptoBot: неизвестный результат создания чека. Заявка '+row['payout_id']+
                '. Не повторяй выплату до проверки в Crypto Pay.',
                action='admin:payview:'+row['payout_id'],subject=row['uid'])
        log.warning('Crypto Pay check creation requires manual reconciliation payout=%s',row['payout_id'])
        return False


def _verified_transfer(row, transfer, uid):
    if not isinstance(transfer,dict) or transfer.get('status')!='completed':
        return False
    try:
        amount=Decimal(str(transfer.get('amount','')))
        target=int(transfer.get('user_id',0))
    except (ValueError,TypeError,InvalidOperation):
        return False
    return (transfer.get('spend_id')==row['spend_id']
        and transfer.get('asset')==row['asset']
        and amount==Decimal(row['crypto_amount'])
        and target==uid
        and type(transfer.get('transfer_id')) is int)


def _find_transfer(row):
    result=call('getTransfers',{'spend_id':row['spend_id']})
    # Crypto Pay versions may return either a list or a paginated items object.
    items=result.get('items') if isinstance(result,dict) else result
    if not isinstance(items,list):
        raise CryptoPayError('Invalid transfer list')
    return next((i for i in items if isinstance(i,dict) and i.get('spend_id')==row['spend_id']),None)


def _finalize_transfer(db,row,transfer):
    import task_bot as b
    with db() as c:
        c.execute('SELECT pg_advisory_xact_lock(1984533)')
        p=c.execute("SELECT * FROM bot_payouts WHERE id=%s AND status='pending' FOR UPDATE",(row['payout_id'],)).fetchone()
        active=c.execute("SELECT * FROM bot_crypto_payouts WHERE payout_id=%s AND state IN ('sending','review') FOR UPDATE",(row['payout_id'],)).fetchone()
        if not p or not active:
            return False
        if not _verified_transfer(active,transfer,p['uid']):
            raise CryptoPayError('Transfer reconciliation mismatch')
        net=b.bot_admin.net(c,p)
        ref='cryptopay_'+str(transfer['transfer_id'])
        c.execute("UPDATE bot_payouts SET status='paid',reference=%s WHERE id=%s",(ref,p['id']))
        c.execute("UPDATE bot_crypto_payouts SET state='completed',transfer_id=%s WHERE payout_id=%s",(transfer['transfer_id'],p['id']))
        c.execute("DELETE FROM bot_crypto_incidents WHERE payout_id=%s",(p['id'],))
        c.execute('UPDATE bot_cash_pool SET amount=CASE WHEN amount>=%s THEN amount-%s ELSE 0 END WHERE id=1',(net,net))
        c.execute("INSERT INTO bot_ledger VALUES(%s,%s,0,'payout_paid',%s,%s)",
                  (uuid.uuid4().hex,p['uid'],'Crypto Bot · '+b.money(net)+' · '+p['id'],time.time()))
        b.bot_notifications.enqueue(c,'payout-paid:'+p['id'],
            '✅ Выплата готова! CryptoBot перевёл '+row['crypto_amount']+' USDT.',recipient=p['uid'])
        b.bot_notifications.enqueue(c,'payout-paid-admin:'+p['id'],
            '✅ CryptoBot: выплата подтверждена\n'
            'Пользователь: '+str(p['uid'])+'\n'
            'Сумма: '+b.money(net)+'\n'
            'Переведено: '+row['crypto_amount']+' USDT\n'
            'ID перевода: '+str(transfer['transfer_id']),
            action='admin:payview:'+p['id'],subject=p['uid'])
        b.bot_payout_channel.enqueue_paid(c,p['id'],b.money(net),recipient_uid=p['uid'] if p['public_profile'] else None)
    return True


def dispatch(db):
    if not token():
        return False
    _release_funded_hold(db)
    _check_dispatch(db)
    # Reconcile uncertain transfer outcomes first; never make a second blind transfer.
    with db() as c:
        c.execute('SELECT pg_advisory_xact_lock(1984537)')
        row=c.execute("""SELECT cp.*,p.uid FROM bot_crypto_payouts cp
          JOIN bot_payouts p ON p.id=cp.payout_id
          WHERE cp.state='review' AND p.status='pending'
            AND NOT EXISTS(SELECT 1 FROM bot_crypto_checks ch WHERE ch.payout_id=cp.payout_id)
          ORDER BY cp.created LIMIT 1""").fetchone()
    if row:
        try:
            transfer=_find_transfer(row)
            if transfer and _verified_transfer(row,transfer,row['uid']):
                return _finalize_transfer(db,row,transfer)
        except Exception:
            log.warning('Crypto Pay payout reconciliation pending for %s',row['payout_id'])
        # Keep reconciling this uncertain payout on later cycles, but never
        # block unrelated payouts whose provider outcome is known.
    if not withdrawals_enabled():
        return False
    # Owner switch also gates dispatch: disabling withdrawals must stop new
    # transfers, not merely hide the menu for new users.
    import bot_admin
    with db() as c:
        if not bot_admin.method_enabled(c,'crypto_withdraw') or payout_cap(c)<=0:
            return False
    with db() as c:
        c.execute('SELECT pg_advisory_xact_lock(1984537)')
        row=c.execute("""SELECT cp.*,p.uid FROM bot_crypto_payouts cp
          JOIN bot_payouts p ON p.id=cp.payout_id
          WHERE cp.state='pending' AND p.status='pending'
            AND CAST(cp.crypto_amount AS numeric)>1
            AND NOT EXISTS(SELECT 1 FROM bot_crypto_liquidity_wait h WHERE h.payout_id=cp.payout_id)
          ORDER BY cp.created LIMIT 1 FOR UPDATE""").fetchone()
        if not row:return False
        # Stop queued transfers exceeding a lowered owner cap.
        p=c.execute("SELECT net FROM bot_payout_terms WHERE id=%s",(row['payout_id'],)).fetchone()
        if p and p['net']>payout_cap(c)*100:
            return False
        c.execute("UPDATE bot_crypto_payouts SET state='sending' WHERE payout_id=%s",(row['payout_id'],))
    try:
        if not _preflight_liquidity(db,row,'transfer'):
            return False
        transfer=call('transfer',{'user_id':row['uid'],'asset':row['asset'],
            'amount':row['crypto_amount'],'spend_id':row['spend_id'],
            'comment':'TREVIXO payout'})
        if not _verified_transfer(row,transfer,row['uid']):
            raise CryptoPayError('Unverified transfer result')
        return _finalize_transfer(db,row,transfer)
    except Exception as exc:
        _record_incident(db,row,'transfer',exc)
        if _insufficient_funds(exc):
            _wait_for_liquidity(db,row,'transfer')
            return False
        # Unknown outcome may have succeeded externally. No retry: reconcile by spend_id.
        # Log safe error classification without exposing headers or payment secrets.
        log.warning('Crypto Pay transfer not confirmed payout=%s kind=%s reason=%s',
                    row['payout_id'],type(exc).__name__,
                    str(exc) if isinstance(exc,CryptoPayError) else type(exc).__name__)
        with db() as c:
            c.execute("UPDATE bot_crypto_payouts SET state='review' WHERE payout_id=%s AND state='sending'",(row['payout_id'],))
        with db() as c:
            import task_bot as b
            b.bot_notifications.enqueue(c,'crypto-review-admin:'+row['payout_id'],
                '⚠️ CryptoBot: результат USDT-перевода неизвестен. Заявка '+row['payout_id']+
                '. Требуется сверка по spend_id; повторный перевод запрещён.',
                action='admin:payview:'+row['payout_id'],subject=row['uid'])
        log.warning('Crypto Pay payout needs reconciliation %s',row['payout_id'])
        return False


def poll(db):
    if not available():
        return False
    with db() as c:
        # Round-robin unpaid invoices. An old unpaid invoice must never
        # prevent the worker from detecting payment of a newer invoice.
        c.execute('SELECT pg_advisory_xact_lock(1984541)')
        row=c.execute("""SELECT id FROM bot_crypto_invoices WHERE status='pending'
          ORDER BY last_checked_at ASC,created ASC LIMIT 1 FOR UPDATE""").fetchone()
        if row:
            c.execute("UPDATE bot_crypto_invoices SET last_checked_at=%s WHERE id=%s",
                      (time.time(),row['id']))
    return settle_invoice(db,row['id']) if row else False
