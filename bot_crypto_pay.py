"""TREVIXO Crypto Pay integration: verified UAH invoices and idempotent USDT payouts.

Never accepts a user-supplied payment confirmation. Transfers are disabled unless the
owner explicitly supplies credentials, enables transfers and defines a UAH ceiling.
"""
import json
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


def token():
    return os.getenv('CRYPTOPAY_API_TOKEN','').strip()


def available():
    return bool(token() and os.getenv('CRYPTOPAY_DEPOSITS_ENABLED')=='1')


def withdrawals_enabled():
    try:
        cap=int(os.getenv('CRYPTOPAY_MAX_PAYOUT_UAH','0'))
    except ValueError:
        return False
    return bool(token() and os.getenv('CRYPTOPAY_AUTO_PAYOUTS_ENABLED')=='1' and cap>0)


def call(method, data=None):
    if method not in ('getMe','getInvoices','createInvoice','getTransfers','transfer','getExchangeRates'):
        raise ValueError('Invalid Crypto Pay method')
    secret=token()
    if not secret:
        raise CryptoPayError('Crypto Pay is not configured')
    base=HOSTS['test'] if os.getenv('CRYPTOPAY_TESTNET')=='1' else HOSTS['main']
    raw=json.dumps(data or {},ensure_ascii=True).encode('utf-8')
    req=Request(base+method, data=raw, method='POST',headers={
        'Crypto-Pay-API-Token':secret,
        'Content-Type':'application/json',
        'Accept':'application/json'})
    try:
        with urlopen(req,timeout=12) as response:
            body=response.read(100000)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise CryptoPayError('Crypto Pay request unavailable: '+type(exc).__name__) from None
    try:
        result=json.loads(body)
    except (ValueError,TypeError):
        raise CryptoPayError('Invalid Crypto Pay response') from None
    if not isinstance(result,dict) or result.get('ok') is not True:
        raise CryptoPayError('Crypto Pay request was not accepted')
    return result['result']


def initialize(c):
    c.execute("""CREATE TABLE IF NOT EXISTS bot_crypto_invoices(
        id text PRIMARY KEY, uid bigint NOT NULL, invoice_id bigint NOT NULL UNIQUE,
        amount bigint NOT NULL CHECK(amount>0),
        status text NOT NULL CHECK(status IN ('pending','paid')),
        created double precision NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS bot_crypto_payouts(
        payout_id text PRIMARY KEY, asset text NOT NULL, crypto_amount text NOT NULL,
        spend_id text NOT NULL UNIQUE,
        state text NOT NULL CHECK(state IN ('pending','sending','review','completed')),
        created double precision NOT NULL, transfer_id bigint)""")
    c.execute('CREATE INDEX IF NOT EXISTS bot_crypto_invoice_queue ON bot_crypto_invoices(status,created)')
    c.execute('CREATE INDEX IF NOT EXISTS bot_crypto_payout_queue ON bot_crypto_payouts(state,created)')
    # If process crashed after sending, do NOT send again: first reconcile spend_id.
    c.execute("UPDATE bot_crypto_payouts SET state='review' WHERE state='sending'")


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
    if not isinstance(result,list):
        raise CryptoPayError('Invalid invoice list')
    for item in result:
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
    return True


def quote_usdt(net):
    if not withdrawals_enabled():
        raise CryptoPayError('Автоматический криптовывод ещё не включён.')
    try:
        cap=int(os.getenv('CRYPTOPAY_MAX_PAYOUT_UAH','0'))
    except ValueError:
        cap=0
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
    if value<Decimal('1'):
        raise CryptoPayError('Минимальный криптовывод — эквивалент 1 USDT.')
    return format(value,'.6f')


def enqueue_payout(c,pid,usdt):
    amount=Decimal(str(usdt))
    if amount<1 or amount>25000:
        raise CryptoPayError('Invalid cryptocurrency amount')
    c.execute("""INSERT INTO bot_crypto_payouts(payout_id,asset,crypto_amount,spend_id,state,created)
      VALUES(%s,'USDT',%s,%s,'pending',%s) ON CONFLICT DO NOTHING""",
      (pid,format(amount,'.6f'),'trevixo_'+pid,time.time()))


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
    if not isinstance(result,list):
        raise CryptoPayError('Invalid transfer list')
    return next((i for i in result if isinstance(i,dict) and i.get('spend_id')==row['spend_id']),None)


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
        c.execute('UPDATE bot_cash_pool SET amount=CASE WHEN amount>=%s THEN amount-%s ELSE 0 END WHERE id=1',(net,net))
        c.execute("INSERT INTO bot_ledger VALUES(%s,%s,0,'payout_paid',%s,%s)",
                  (uuid.uuid4().hex,p['uid'],'Crypto Bot · '+b.money(net)+' · '+p['id'],time.time()))
        b.bot_notifications.enqueue(c,'payout-paid:'+p['id'],
            '✅ Crypto Bot перевёл '+row['crypto_amount']+' USDT. Заявка '+p['id'],recipient=p['uid'])
        b.bot_payout_channel.enqueue_paid(c,p['id'],b.money(net),recipient_uid=p['uid'] if p['public_profile'] else None)
    return True


def dispatch(db):
    if not token():
        return False
    # Reconcile uncertain outcomes first; never make a second blind transfer.
    with db() as c:
        c.execute('SELECT pg_advisory_xact_lock(1984537)')
        row=c.execute("""SELECT cp.*,p.uid FROM bot_crypto_payouts cp
          JOIN bot_payouts p ON p.id=cp.payout_id
          WHERE cp.state='review' AND p.status='pending'
          ORDER BY cp.created LIMIT 1""").fetchone()
    if row:
        try:
            transfer=_find_transfer(row)
            if transfer and _verified_transfer(row,transfer,row['uid']):
                return _finalize_transfer(db,row,transfer)
        except Exception:
            log.warning('Crypto Pay payout reconciliation pending for %s',row['payout_id'])
        return False
    if not withdrawals_enabled():
        return False
    with db() as c:
        c.execute('SELECT pg_advisory_xact_lock(1984537)')
        row=c.execute("""SELECT cp.*,p.uid FROM bot_crypto_payouts cp
          JOIN bot_payouts p ON p.id=cp.payout_id
          WHERE cp.state='pending' AND p.status='pending'
          ORDER BY cp.created LIMIT 1 FOR UPDATE""").fetchone()
        if not row:return False
        c.execute("UPDATE bot_crypto_payouts SET state='sending' WHERE payout_id=%s",(row['payout_id'],))
    try:
        transfer=call('transfer',{'user_id':row['uid'],'asset':row['asset'],
            'amount':row['crypto_amount'],'spend_id':row['spend_id'],
            'comment':'TREVIXO payout'})
        if not _verified_transfer(row,transfer,row['uid']):
            raise CryptoPayError('Unverified transfer result')
        return _finalize_transfer(db,row,transfer)
    except Exception:
        # Unknown outcome may have succeeded externally. No retry: reconcile by spend_id.
        with db() as c:
            c.execute("UPDATE bot_crypto_payouts SET state='review' WHERE payout_id=%s AND state='sending'",(row['payout_id'],))
        log.warning('Crypto Pay payout needs reconciliation %s',row['payout_id'])
        return False


def poll(db):
    if not available():
        return False
    with db() as c:
        row=c.execute("""SELECT id FROM bot_crypto_invoices WHERE status='pending'
          ORDER BY created LIMIT 1""").fetchone()
    return settle_invoice(db,row['id']) if row else False
