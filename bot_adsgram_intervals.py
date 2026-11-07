"""Cumulative AdsGram publisher balance checkpoints and nonoverlapping interval payouts.

Owner reports a cumulative USD/USDT balance, not the incremental revenue.
First report sets a baseline. Each subsequent report allocates only the delta
to SDK-confirmed bot views in [previous checkpoint, current checkpoint).
Farm views affect impressions, but earn game goods rather than cash here.
"""
import time
import uuid
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from bot_economy import monetag_cash_allocation
from bot_cash_ad_credits import nbu_usd_uah

KYIV=ZoneInfo('Europe/Kyiv')

def initialize(c):
    c.execute("""CREATE TABLE IF NOT EXISTS bot_adsgram_balance_checkpoints(
      id text PRIMARY KEY, observed_at double precision NOT NULL,
      cumulative_usd numeric(25,12) NOT NULL CHECK(cumulative_usd>=0),
      delta_usd numeric(25,12) NOT NULL CHECK(delta_usd>=0),
      cash_views integer NOT NULL DEFAULT 0, farm_views integer NOT NULL DEFAULT 0,
      credited_kopeks bigint NOT NULL DEFAULT 0,
      owner_uid bigint NOT NULL,
      created_at double precision NOT NULL)""")
    # Accounting-only USD allocation of publisher revenue attributable to farm views.
    # Never credit redeemable coins from an unverified or estimated impression.
    c.execute("""CREATE TABLE IF NOT EXISTS farm_adsgram_revenue_allocations(
      checkpoint_id text PRIMARY KEY REFERENCES bot_adsgram_balance_checkpoints(id),
      farm_views integer NOT NULL CHECK(farm_views>=0),
      bot_views integer NOT NULL CHECK(bot_views>=0),
      share_usd numeric(28,18) NOT NULL CHECK(share_usd>=0),
      recorded_at double precision NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS bot_adsgram_interval_credits(
      checkpoint_id text NOT NULL REFERENCES bot_adsgram_balance_checkpoints(id),
      uid bigint NOT NULL, role text NOT NULL CHECK(role IN ('viewer','referral')),
      level integer NOT NULL,
      earned_usd numeric(28,18) NOT NULL,
      credited_kopeks bigint NOT NULL,
      PRIMARY KEY(checkpoint_id,uid,role,level))""")

def latest(c):
    return c.execute("""SELECT * FROM bot_adsgram_balance_checkpoints
        ORDER BY observed_at DESC,id DESC LIMIT 1""").fetchone()

def _unsettled_daily(c,start,end):
    # Prevent the old daily commands from double-paying overlapping impressions.
    first=datetime.fromtimestamp(start,KYIV).date()
    last=datetime.fromtimestamp(end,KYIV).date()
    day=first
    while day<=last:
        if c.execute("SELECT 1 FROM bot_adsgram_daily_settlements WHERE utc_day=%s",(day.isoformat(),)).fetchone():
            raise ValueError('Период пересекается с ранее закрытым суточным отчётом AdsGram.')
        day+=timedelta(days=1)

def _has_interval(c,start,end):
    row=c.execute("""SELECT 1 FROM bot_adsgram_balance_checkpoints
      WHERE delta_usd>0 AND observed_at>%s AND observed_at<=%s LIMIT 1""",(start,end)).fetchone()
    return bool(row)

def reset_baseline(c,owner_uid,new_balance,now=None):
    """Start a new epoch without deleting/repaying previous checkpoints or views.

    The caller must enter the current *cumulative* AdsGram publisher balance.
    Past revenue before this observation is excluded; the next report will
    pay only newer confirmed views and the increment above this new baseline.
    """
    try:
        balance=Decimal(str(new_balance))
    except (ValueError,TypeError,InvalidOperation):
        raise ValueError('Укажи текущий накопленный баланс, например /reklama reset 1.50')
    if (not balance.is_finite() or balance<0 or balance>Decimal('100000000')
            or balance.as_tuple().exponent < -6):
        raise ValueError('Укажи корректный баланс USD (до 6 знаков после запятой).')
    now=time.time() if now is None else float(now)
    c.execute("SELECT pg_advisory_xact_lock(%s)",(125492051,))
    prev=latest(c)
    if prev and now<=prev['observed_at']:
        raise ValueError('Время нового старта должно быть позже предыдущей точки.')
    c.execute("""INSERT INTO bot_adsgram_balance_checkpoints
        (id,observed_at,cumulative_usd,delta_usd,owner_uid,created_at)
        VALUES(%s,%s,%s,0,%s,%s)""",
        (uuid.uuid4().hex,now,balance,owner_uid,time.time()))
    return {'baseline':True,'balance':str(balance),
            'previous':str(prev['cumulative_usd']) if prev else None}


def report(c,owner_uid,new_balance,now=None):
    """Atomic checkpoint; rejection never advances start or pays funds."""
    try:
        balance=Decimal(str(new_balance))
    except (ValueError,TypeError,InvalidOperation):
        raise ValueError('Введи накопленный баланс USD, например /reklama 1.65')
    if not balance.is_finite() or balance<0 or balance>Decimal('100000000'):
        raise ValueError('Недопустимый накопленный баланс USD')
    if balance.as_tuple().exponent < -6:
        raise ValueError('Не более 6 знаков после запятой')
    now=time.time() if now is None else float(now)
    c.execute("SELECT pg_advisory_xact_lock(%s)",(125492051,))
    prev=latest(c)
    if prev and now<=prev['observed_at']:
        raise ValueError('Время новой контрольной точки должно быть позже предыдущей.')
    if prev and balance<Decimal(str(prev['cumulative_usd'])):
        raise ValueError('Баланс уменьшился. Возможно, был вывод средств или корректировка рекламной сети. Нужна отдельная сверка, выплаты не произведены.')
    if not prev:
        # Prevent a baseline taken mid-day from re-paying an already closed day.
        if c.execute("SELECT 1 FROM bot_adsgram_daily_settlements WHERE utc_day=%s",
                     (datetime.fromtimestamp(now,KYIV).date().isoformat(),)).fetchone():
            raise ValueError('Текущий день уже закрыт суточным отчётом AdsGram.')
        c.execute("""INSERT INTO bot_adsgram_balance_checkpoints
            (id,observed_at,cumulative_usd,delta_usd,owner_uid,created_at)
            VALUES(%s,%s,%s,0,%s,%s)""",(uuid.uuid4().hex,now,balance,owner_uid,time.time()))
        return {'baseline':True,'balance':str(balance),'delta':'0'}
    start=prev['observed_at']
    _unsettled_daily(c,start,now)
    delta=balance-Decimal(str(prev['cumulative_usd']))
    # If the publisher total has not moved, keep the previous checkpoint:
    # later revenue can still cover callbacks that arrived in the meantime.
    if delta==0:
        return {'baseline':False,'unchanged':True,'balance':str(balance),
                'delta':'0','cash_views':0,'farm_views':0,
                'credited_kopeks':0,'platform_usd_at_least':'0'}
    cash=c.execute("""SELECT id,uid,referral_chain FROM bot_adsgram_attempts
      WHERE state='confirmed' AND confirmed_at>=%s AND confirmed_at<%s
      ORDER BY confirmed_at,id FOR UPDATE""",(start,now)).fetchall()
    farm_count=int(c.execute("""SELECT COUNT(*) AS n FROM bot_adsgram_farm_attempts
      WHERE state='confirmed' AND confirmed_at>=%s AND confirmed_at<%s""",
      (start,now)).fetchone()['n'])
    count=len(cash)+farm_count
    if delta>0 and count==0:
        raise ValueError('Доход вырос, но за этот период нет подтверждённых AdsGram просмотров. Начисления остановлены; проверь источник дохода.')
    ident=uuid.uuid4().hex
    rate=nbu_usd_uah(c) if delta>0 else None
    total=0
    c.execute("""INSERT INTO bot_adsgram_balance_checkpoints
      (id,observed_at,cumulative_usd,delta_usd,cash_views,farm_views,owner_uid,created_at)
      VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
      (ident,now,balance,delta,len(cash),farm_count,owner_uid,time.time()))
    if delta>0:
        per_view=delta/Decimal(count)
        # This amount stays in internal USD accounting until a separate,
        # fully funded coin-value mechanism is explicitly approved.
        farm_share=per_view*Decimal(farm_count)
        c.execute("""INSERT INTO farm_adsgram_revenue_allocations
          (checkpoint_id,farm_views,bot_views,share_usd,recorded_at)
          VALUES(%s,%s,%s,%s,%s)""",
          (ident,farm_count,len(cash),farm_share,time.time()))
        ledger={}
        for r in cash:
            alloc=monetag_cash_allocation(per_view,tuple(r['referral_chain']))
            entries=[('viewer',int(r['uid']),0,Decimal(alloc['viewer_usd']))]
            entries.extend(('referral',int(q['uid']),int(q['level']),Decimal(q['usd']))
                           for q in alloc['referrals'])
            for role,uid,level,usd in entries:
                key=(uid,role,level)
                ledger[key]=ledger.get(key,Decimal(0))+usd
        for (uid,role,level),earned in sorted(ledger.items()):
            if earned<=0:continue
            if not c.execute("SELECT 1 FROM bot_accounts WHERE uid=%s",(uid,)).fetchone():
                raise ValueError('Реферал не найден; начисления остановлены для сверки.')
            c.execute("""INSERT INTO bot_cash_ad_fraction(uid,remainder)
              VALUES(%s,0) ON CONFLICT(uid) DO NOTHING""",(uid,))
            fraction=c.execute("""SELECT remainder FROM bot_cash_ad_fraction
              WHERE uid=%s FOR UPDATE""",(uid,)).fetchone()
            kopeks=Decimal(str(fraction['remainder']))+earned*rate*100
            whole=int(kopeks.to_integral_value(rounding=ROUND_FLOOR))
            if whole<0 or whole>9223372036854775807:
                raise ValueError('Сумма начисления вне диапазона')
            c.execute("UPDATE bot_cash_ad_fraction SET remainder=%s WHERE uid=%s",
                      (kopeks-Decimal(whole),uid))
            c.execute("""INSERT INTO bot_adsgram_interval_credits
              (checkpoint_id,uid,role,level,earned_usd,credited_kopeks)
              VALUES(%s,%s,%s,%s,%s,%s)""",(ident,uid,role,level,earned,whole))
            if whole:
                c.execute("UPDATE bot_accounts SET available=available+%s WHERE uid=%s",(whole,uid))
                c.execute("""INSERT INTO bot_ledger(id,uid,delta,kind,details,created)
                  VALUES(%s,%s,%s,%s,%s,%s)""",(
                   uuid.uuid4().hex,uid,whole,'adsgram_interval_'+role,
                   'AdsGram interval '+ident+' level '+str(level),time.time()))
            total+=whole
    c.execute("UPDATE bot_adsgram_balance_checkpoints SET credited_kopeks=%s WHERE id=%s",
              (total,ident))
    return {'baseline':False,'balance':str(balance),'delta':str(delta),
            'cash_views':len(cash),'farm_views':farm_count,'credited_kopeks':total,
            'farm_share_usd':str(delta*Decimal(farm_count)/Decimal(count)),
            'platform_usd_at_least':str(delta*Decimal('0.35'))}
