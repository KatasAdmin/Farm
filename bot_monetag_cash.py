"""Prepare Monetag cash ad attempts and validate provider postbacks."""
from decimal import Decimal, InvalidOperation
from bot_economy import monetag_cash_allocation, MONETAG_CASH_REFERRAL_BPS

def preview(estimated_usd, referral_uids=()):
    """Calculate the *estimated* distribution in USD, never payable money."""
    try:
        value=Decimal(str(estimated_usd))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError('Invalid USD estimate') from exc
    if not value.is_finite() or value < 0:
        raise ValueError('Invalid USD estimate')
    chain=tuple(referral_uids)
    if len(chain)>7 or any(uid is not None and (not isinstance(uid,int) or uid<=0) for uid in chain):
        raise ValueError('Invalid referral chain')
    result=monetag_cash_allocation(value,chain)
    result['referral_rates_percent']=[str(Decimal(bps)/100) for bps in MONETAG_CASH_REFERRAL_BPS]
    result['currency']='USD'
    result['withdrawable']=False
    return result


import secrets
import time

CASH_ZONE_ID = 12193261
CASH_ATTEMPT_TTL = 600
CASH_POSTBACK_TTL = 48 * 3600
CASH_ADS_PER_BREAK = 10
CASH_BREAK_SECONDS = 30


def initialize_cash_attempts(c):
    c.execute("""
        CREATE TABLE IF NOT EXISTS bot_monetag_cash_attempts(
            ymid text PRIMARY KEY,
            viewer_uid bigint NOT NULL,
            zone_id integer NOT NULL,
            placement text NOT NULL CHECK(placement='cash_rewarded_interstitial'),
            request_var text NOT NULL,
            created_at double precision NOT NULL,
            launched_at double precision,
            finished_at double precision,
            expires_at double precision NOT NULL,
            state text NOT NULL DEFAULT 'prepared'
                CHECK(state IN ('prepared','launched','confirmed','expired','rejected')),
            confirmed_at double precision
        )
    """)
    c.execute("ALTER TABLE bot_monetag_cash_attempts ADD COLUMN IF NOT EXISTS launched_at double precision")
    c.execute("ALTER TABLE bot_monetag_cash_attempts ADD COLUMN IF NOT EXISTS finished_at double precision")
    c.execute("ALTER TABLE bot_monetag_cash_attempts ADD COLUMN IF NOT EXISTS non_valued_at double precision")
    c.execute("ALTER TABLE bot_monetag_cash_attempts ADD COLUMN IF NOT EXISTS abandoned_at double precision")
    c.execute("""
        CREATE INDEX IF NOT EXISTS bot_monetag_cash_attempts_viewer
        ON bot_monetag_cash_attempts(viewer_uid,created_at)
    """)


def lock_cash_viewer(c, viewer_uid):
    """Serialize ad attempts for one Telegram UID inside a DB transaction."""
    if not isinstance(viewer_uid,int) or viewer_uid<=0:
        raise ValueError('Invalid viewer')
    # Namespace lock key avoids collisions with other advisory-lock users.
    c.execute("SELECT pg_advisory_xact_lock(%s,%s)",(3563430,viewer_uid % 2147483647))


def cash_cooldown(launch_times, now):
    """A tenth launch is allowed; afterward wait until 30s after launch #1.

    Breaks between launches count. A long gap clears the unfinished series.
    No daily cap and no carryover across sessions.
    """
    from math import ceil
    times=sorted(t for t in launch_times if t is not None and t<=now)
    block=[]
    for t in times:
        if block and t-block[-1]>=CASH_BREAK_SECONDS:
            block=[]
        if len(block)>=CASH_ADS_PER_BREAK:
            if t-block[0]>=CASH_BREAK_SECONDS:
                block=[]
            else:
                # Invalid historical overlap; do not extend a completed block.
                continue
        block.append(t)
    if len(block)<CASH_ADS_PER_BREAK:
        return {'retry_after':0,'block_launches':len(block)}
    return {'retry_after':max(0,ceil(CASH_BREAK_SECONDS-(now-block[0]))),
            'block_launches':len(block)}


def cash_attempt_quota(c, viewer_uid, now=None):
    """No daily cap; only launched ads count toward a 10-ad block."""
    now=time.time() if now is None else now
    rows=c.execute("""
        SELECT created_at,launched_at,COALESCE(finished_at,abandoned_at) AS finished_at,expires_at,state
        FROM bot_monetag_cash_attempts
        WHERE viewer_uid=%s AND (
          (launched_at IS NOT NULL AND launched_at>=%s)
          OR (state='prepared' AND expires_at>%s)
        )
        ORDER BY launched_at DESC NULLS LAST
    """,(viewer_uid,now-3600,now)).fetchall()
    active=any((r['state']=='prepared' and r['expires_at']>now) or
               (r['state']=='launched' and r['launched_at'] is not None and
                r['finished_at'] is None and r['launched_at']+120>now) for r in rows)
    launches=[r['launched_at'] for r in rows if r['launched_at'] is not None]
    cooldown=cash_cooldown(launches,now)
    return {'active':active,'retry_after':cooldown['retry_after'],
            'block_launches':cooldown['block_launches'],
            'hour_launches':len(launches),'daily_limit':None,
            'break_every':CASH_ADS_PER_BREAK,
            'break_seconds':CASH_BREAK_SECONDS}


def mark_cash_attempt_launched(c, viewer_uid, ymid, now=None):
    """Record one SDK launch. Caller must authenticate viewer and serialize updates."""
    now=time.time() if now is None else now
    lock_cash_viewer(c,viewer_uid)
    row=c.execute("""
        SELECT * FROM bot_monetag_cash_attempts
        WHERE ymid=%s AND viewer_uid=%s FOR UPDATE
    """,(ymid,viewer_uid)).fetchone()
    if not row or row['state']!='prepared' or now>row['expires_at']:
        raise ValueError('Invalid or expired cash ad preparation')
    quota=cash_attempt_quota(c,viewer_uid,now)
    if quota['retry_after']:
        raise ValueError('Cash ad cooldown')
    # The prepared attempt itself is active, but no *other* prepared or
    # in-progress attempt may coexist. This is protected by the viewer lock.
    others=c.execute("""
        SELECT 1 FROM bot_monetag_cash_attempts
        WHERE viewer_uid=%s AND ymid<>%s
          AND ((state='prepared' AND expires_at>%s)
            OR (state='launched' AND finished_at IS NULL AND abandoned_at IS NULL
                AND launched_at>%s))
        LIMIT 1
    """,(viewer_uid,ymid,now,now-120)).fetchone()
    if others:
        raise ValueError('Another cash ad attempt is active')
    c.execute("""
        UPDATE bot_monetag_cash_attempts SET state='launched',launched_at=%s
        WHERE ymid=%s
    """,(now,ymid))
    return {'ok':True,'ymid':ymid,'payable':False}


def finish_cash_attempt(c, viewer_uid, ymid):
    """SDK finished displaying; free the active slot, NEVER credit money.

    This signal is untrusted for earnings; only a verified Monetag postback
    can stage estimated income.
    """
    lock_cash_viewer(c,viewer_uid)
    row=c.execute("""
        UPDATE bot_monetag_cash_attempts SET finished_at=%s
        WHERE ymid=%s AND viewer_uid=%s AND state IN ('launched','confirmed')
          AND finished_at IS NULL AND abandoned_at IS NULL
        RETURNING ymid
    """,(time.time(),ymid,viewer_uid)).fetchone()
    return {'ok':bool(row),'payable':False}


def abandon_cash_attempt(c, viewer_uid, ymid):
    """End the SDK session without recording a completed view or rejecting postbacks."""
    lock_cash_viewer(c,viewer_uid)
    c.execute("""
        UPDATE bot_monetag_cash_attempts SET abandoned_at=%s
        WHERE ymid=%s AND viewer_uid=%s AND state IN ('launched','confirmed')
          AND finished_at IS NULL AND abandoned_at IS NULL
    """,(time.time(),ymid,viewer_uid))


def cancel_unlaunched_cash_attempt(c, viewer_uid, ymid):
    """A failed SDK start must not consume a view or earn a reward."""
    lock_cash_viewer(c,viewer_uid)
    row=c.execute("""
        UPDATE bot_monetag_cash_attempts SET state='rejected'
        WHERE ymid=%s AND viewer_uid=%s AND state='prepared'
        RETURNING ymid
    """,(ymid,viewer_uid)).fetchone()
    return bool(row)


def prepare_cash_attempt(c, verified_telegram_uid, now=None):
    """For future use AFTER publisher approval and server-side rate limiting.

    Caller must validate signed Telegram initData and enforce eligibility and
    quotas. This function does not launch SDK, pay users, or enable anything.
    """
    if not isinstance(verified_telegram_uid,int) or verified_telegram_uid<=0:
        raise ValueError('Telegram identity must be verified')
    now=time.time() if now is None else now
    # This function obtains a per-viewer transaction lock before quota check.
    lock_cash_viewer(c,verified_telegram_uid)
    quota=cash_attempt_quota(c,verified_telegram_uid,now)
    if quota['active'] or quota['retry_after']:
        raise ValueError('Cash ad cooldown or active attempt')
    ymid='cash_'+secrets.token_hex(20)
    request_var='cash_rewarded_interstitial'
    c.execute("""
        INSERT INTO bot_monetag_cash_attempts
        (ymid,viewer_uid,zone_id,placement,request_var,created_at,expires_at)
        VALUES(%s,%s,%s,%s,%s,%s,%s)
    """,(ymid,verified_telegram_uid,CASH_ZONE_ID,request_var,request_var,now,
         now+CASH_ATTEMPT_TTL))
    return {'ymid':ymid,'zone_id':CASH_ZONE_ID,'request_var':request_var,
            'expires_at':now+CASH_ATTEMPT_TTL,'payable':False}


def lookup_cash_attempt_for_postback(c, *, ymid, telegram_uid, zone_id,
                                     request_var, now=None):
    """Find the exact server-issued attempt; no payout or state transition."""
    now=time.time() if now is None else now
    if not isinstance(ymid,str) or not ymid.startswith('cash_'):
        return None
    row=c.execute("""
        SELECT * FROM bot_monetag_cash_attempts WHERE ymid=%s FOR UPDATE
    """,(ymid,)).fetchone()
    if not row or row['state']!='launched' or row.get('launched_at') is None:
        return None
    if now>row['launched_at']+CASH_POSTBACK_TTL or row['zone_id']!=zone_id:
        return None
    if row['viewer_uid']!=telegram_uid or row['request_var']!=request_var:
        return None
    return row


def stage_verified_cash_postback(c, *, secret, ymid, telegram_uid, zone_id,
                                 request_var, event_type, reward_event_type,
                                 estimated_price, referral_chain=None, now=None):
    """Stage a Monetag event without touching any payable wallet.

    Requires the configured secret from the trusted server request context.
    Does not authorize cash withdrawals, and does not update farm goods.
    """
    import os
    import hmac
    from decimal import Decimal
    import bot_economy

    configured=os.getenv('MONETAG_POSTBACK_SECRET','')
    if len(configured)<24 or not isinstance(secret,str) or not hmac.compare_digest(secret,configured):
        raise PermissionError('Invalid Monetag postback authorization')
    now=time.time() if now is None else now
    if not isinstance(telegram_uid,int) or telegram_uid<=0:
        raise ValueError('Invalid Telegram identity')
    if event_type not in ('impression','click') or reward_event_type not in ('valued','non_valued'):
        raise ValueError('Invalid Monetag event')
    attempt=lookup_cash_attempt_for_postback(
        c,ymid=ymid,telegram_uid=telegram_uid,zone_id=zone_id,
        request_var=request_var,now=now)
    if not attempt:
        return {'ok':False,'reason':'unknown_or_invalid_attempt'}
    # A confirmed unpaid impression permits the UI to try AdsGram instead.
    # Never treat a click or an unverified SDK callback as proof of no payment.
    if event_type=='impression' and reward_event_type=='non_valued':
        c.execute("""UPDATE bot_monetag_cash_attempts
           SET non_valued_at=COALESCE(non_valued_at,%s)
           WHERE ymid=%s AND viewer_uid=%s AND state='launched'""",
           (now,ymid,telegram_uid))
        return {'ok':True,'staged':False,'reason':'non_valued'}
    if event_type!='impression' or reward_event_type!='valued':
        return {'ok':True,'staged':False,'reason':'ignored_event'}
    from decimal import InvalidOperation
    try:
        price=Decimal(str(estimated_price))
    except InvalidOperation as exc:
        raise ValueError('Invalid Monetag price') from exc
    if not price.is_finite() or price<0:
        raise ValueError('Invalid Monetag price')
    if not price:
        # Preserve pending status for a later priced postback. Zero cannot fund a reward.
        return {'ok':True,'staged':False,'reason':'zero_price'}
    # Database column is numeric(28,12). Reject values that would silently
    # round away fractional earnings or overflow the provisional ledger.
    if price >= Decimal('10000000000000000') or price != price.quantize(Decimal('0.000000000001')):
        raise ValueError('Estimated price exceeds supported precision')
    # Prevent referral self-rewards and duplicate ancestors.
    chain=tuple(verified_bot_referral_chain(c,telegram_uid) if referral_chain is None else referral_chain)
    if telegram_uid in chain:
        raise ValueError('Self referral')
    result=bot_economy.stage_monetag_cash_event(
        c,ymid=ymid,viewer_uid=telegram_uid,zone_id=zone_id,
        placement=attempt['placement'],event_type=event_type,
        reward_event_type=reward_event_type,estimated_usd=price,
        referral_chain=chain)
    if result['recorded']:
        c.execute("""
            UPDATE bot_monetag_cash_attempts SET state='confirmed',confirmed_at=%s
            WHERE ymid=%s AND state='launched'
        """,(now,ymid))
    return {'ok':True,'staged':result['recorded'],
            'status':'pending_review','payable':False}


def verified_bot_referral_chain(c, viewer_uid, depth=7):
    """Snapshot the bot's actual referral ancestors; stop at gaps or cycles."""
    if not isinstance(viewer_uid,int) or viewer_uid<=0 or depth!=7:
        raise ValueError('Invalid referral lookup')
    seen={viewer_uid}
    chain=[]
    current=viewer_uid
    for _ in range(depth):
        row=c.execute(
            'SELECT referrer FROM bot_accounts WHERE uid=%s',(current,)
        ).fetchone()
        parent=row['referrer'] if row else None
        if parent is None:
            break
        if not isinstance(parent,int) or parent<=0 or parent in seen:
            break
        chain.append(parent)
        seen.add(parent)
        current=parent
    return tuple(chain)

def estimated_earnings(c, viewer_uid):
    """Personal provisional estimates from verified valued impressions.

    Does not credit a wallet. Reconciliation and withdrawals are intentionally
    separate and require confirmed publisher settlement.
    """
    from psycopg.types.json import Jsonb
    if not isinstance(viewer_uid,int) or viewer_uid<=0:
        raise ValueError('Invalid viewer ID')
    rows=c.execute("""
        SELECT viewer_uid,allocation,state
        FROM bot_monetag_cash_events
        WHERE event_type='impression' AND reward_event_type='valued'
          AND (viewer_uid=%s OR referral_chain @> %s)
    """,(viewer_uid,Jsonb([viewer_uid]))).fetchall()
    viewer=Decimal(0)
    referral=Decimal(0)
    levels=[Decimal(0) for _ in range(7)]
    for row in rows:
        if row['state']=='rejected':
            continue
        allocation=row['allocation']
        if row['viewer_uid']==viewer_uid:
            viewer+=Decimal(str(allocation['viewer_usd']))
        for item in allocation.get('referrals',[]):
            if item['uid']==viewer_uid and 1<=item['level']<=7:
                amount=Decimal(str(item['usd']))
                referral+=amount
                levels[item['level']-1]+=amount
    return {'viewer':viewer,'referral':referral,'total':viewer+referral,
            'levels':levels,'priced_events':len(rows),'payable':False}
