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


def initialize_cash_attempts(c):
    c.execute("""
        CREATE TABLE IF NOT EXISTS bot_monetag_cash_attempts(
            ymid text PRIMARY KEY,
            viewer_uid bigint NOT NULL,
            zone_id integer NOT NULL,
            placement text NOT NULL CHECK(placement='cash_rewarded_interstitial'),
            request_var text NOT NULL,
            created_at double precision NOT NULL,
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


def prepare_cash_attempt(c, verified_telegram_uid, now=None):
    """For future use AFTER publisher approval and server-side rate limiting.

    Caller must validate signed Telegram initData and enforce eligibility and
    quotas. This function does not launch SDK, pay users, or enable anything.
    """
    if not isinstance(verified_telegram_uid,int) or verified_telegram_uid<=0:
        raise ValueError('Telegram identity must be verified')
    now=time.time() if now is None else now
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
    if now>row['expires_at'] or row['zone_id']!=zone_id:
        return None
    if row['viewer_uid']!=telegram_uid or row['request_var']!=request_var:
        return None
    return row
