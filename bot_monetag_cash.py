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
