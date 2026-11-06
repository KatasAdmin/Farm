"""USD deposit quotes. Staging only; not authorized payment confirmation.

Provider receipts, rates, commissions and a ledger transaction must be bound
to an immutable payment intent before the USD deposit flow becomes live.
"""
from decimal import Decimal, ROUND_DOWN
from bot_usd_currency import USD_SCALE, UAH_SCALE, _rate

def quote_uah_card_deposit(kopecks_received, uah_per_usd, fee_kopecks=0):
    if type(kopecks_received) is not int or kopecks_received <= 0:
        raise ValueError("Card payment must be positive UAH kopecks")
    if type(fee_kopecks) is not int or not 0 <= fee_kopecks < kopecks_received:
        raise ValueError("Invalid card settlement fee")
    rate = _rate(uah_per_usd)
    net_kopecks = kopecks_received-fee_kopecks
    credit_micro=int(
        (Decimal(net_kopecks)*USD_SCALE/(UAH_SCALE*rate)).to_integral_value(rounding=ROUND_DOWN)
    )
    if credit_micro <= 0:
        raise ValueError("Card payment too small to credit")
    return {
        "provider_currency":"UAH",
        "gross_received_kopecks":kopecks_received,
        "fee_kopecks":fee_kopecks,
        "exchange_rate_uah_per_usd":str(rate),
        "credit_usd_micro":credit_micro,
    }

def quote_stars_deposit(stars, micro_usd_per_star):
    """XTR rate from owner-set and immutable Stars invoice; do not use UAH rate."""
    if type(stars) is not int or not 1<=stars<=10000:
        raise ValueError("Invalid Stars amount")
    if type(micro_usd_per_star) is not int or micro_usd_per_star<=0:
        raise ValueError("Invalid USD rate for Stars")
    return {
        "provider_currency":"XTR",
        "stars":stars,
        "micro_usd_per_star":micro_usd_per_star,
        "credit_usd_micro":stars*micro_usd_per_star,
    }
