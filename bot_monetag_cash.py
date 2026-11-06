"""Read-only, opt-in Monetag cash rewards preview.

This module deliberately does not call Monetag, change balances, or send payouts.
Enable only after the publisher explicitly approves withdrawable cash rewards.
"""
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


# Future cash-ad attempts are intentionally isolated from farm goods attempts.
# These helpers are not invoked by the production app.
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
            expires_at double precision NOT NULL,
            state text NOT NULL DEFAULT 'prepared'
                CHECK(state IN ('prepared','launched','confirmed','expired','rejected')),
            confirmed_at double precision
        )
    """)
    c.execute("""
        CREATE INDEX IF NOT EXISTS bot_monetag_cash_attempts_viewer
        ON bot_monetag_cash_attempts(viewer_uid,created_at)
    """)


def cash_attempt_quota(c, viewer_uid, now=None):
    """Pause 30s after each tenth *launched* ad; failed preparations do not count."""
    now=time.time() if now is None else now
    rows=c.execute("""
        SELECT created_at,launched_at,expires_at,state
        FROM bot_monetag_cash_attempts
        WHERE viewer_uid=%s AND (
          (launched_at IS NOT NULL AND launched_at>=%s)
          OR (state='prepared' AND expires_at>%s)
        )
        ORDER BY launched_at DESC NULLS LAST
    """,(viewer_uid,now-3600,now)).fetchall()
    active=any(r['state'] in ('prepared','launched') and
               r['expires_at']>now for r in rows)
    launches=[r['launched_at'] for r in rows if r['launched_at'] is not None]
    count=len(launches)
    last=launches[0] if launches else 0
    wait=max(0,int(last+CASH_BREAK_SECONDS-now+0.999)) if count and count%CASH_ADS_PER_BREAK==0 else 0
    return {'active':active,'retry_after':wait,'hour_launches':count,
            'daily_limit':None,'break_every':CASH_ADS_PER_BREAK,
            'break_seconds':CASH_BREAK_SECONDS}


def mark_cash_attempt_launched(c, viewer_uid, ymid, now=None):
    """Record one SDK launch. Caller must authenticate viewer and serialize updates."""
    now=time.time() if now is None else now
    row=c.execute("""
        SELECT * FROM bot_monetag_cash_attempts
        WHERE ymid=%s AND viewer_uid=%s FOR UPDATE
    """,(ymid,viewer_uid)).fetchone()
    if not row or row['state']!='prepared' or now>row['expires_at']:
        raise ValueError('Invalid or expired cash ad preparation')
    quota=cash_attempt_quota(c,viewer_uid,now)
    if quota['retry_after']:
        raise ValueError('Cash ad cooldown')
    c.execute("""
        UPDATE bot_monetag_cash_attempts SET state='launched',launched_at=%s
        WHERE ymid=%s
    """,(now,ymid))
    return {'ok':True,'ymid':ymid,'payable':False}


def cancel_unlaunched_cash_attempt(c, viewer_uid, ymid):
    """A failed SDK start must not consume a view or earn a reward."""
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
    # Caller must serialize attempts per viewer (transaction advisory lock).
    quota=cash_attempt_quota(c,verified_telegram_uid,now)
    if quota['active'] or quota['retry_after']:
        raise ValueError('Cash ad cooldown or active attempt')
    ymid='cash_'+secrets.token_hex(20)
    request_var='cash_rewarded_interstitial'
    c.execute("""
        INSERT INTO bot_monetag_cash_attempts
        (ymid,viewer_uid,zone_id,placement,request_var,created_at,expires_at)
        VALUES(%s,%s,%s,%s,%s,%s,%s)
    """,(ymid,verified_telegram_uid,CASH_ZONE_ID,request_var,now,
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
    if not row or row['state'] not in ('prepared','launched'):
        return None
    if now>row['created_at']+CASH_POSTBACK_TTL or row['zone_id']!=zone_id:
        return None
    if row['viewer_uid']!=telegram_uid or row['request_var']!=request_var:
        return None
    return row


def stage_verified_cash_postback(c, *, secret, ymid, telegram_uid, zone_id,
                                 request_var, event_type, reward_event_type,
                                 estimated_price, referral_chain=(), now=None):
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
    try:
        price=Decimal(str(estimated_price))
    except Exception as exc:
        raise ValueError('Invalid Monetag price') from exc
    if not price.is_finite() or price<0:
        raise ValueError('Invalid Monetag price')
    attempt=lookup_cash_attempt_for_postback(
        c,ymid=ymid,telegram_uid=telegram_uid,zone_id=zone_id,
        request_var=request_var,now=now)
    if not attempt:
        return {'ok':False,'reason':'unknown_or_invalid_attempt'}
    # Non-valued events are telemetry only. Positive estimated income is not
    # enough to create a payable balance; publisher settlement is still needed.
    if reward_event_type!='valued' or price==0:
        return {'ok':True,'staged':False,'reason':'not_valued'}
    # Prevent referral self-rewards and duplicate ancestors.
    chain=tuple(referral_chain)
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
            WHERE ymid=%s AND state IN ('prepared','launched')
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
