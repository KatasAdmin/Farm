"""Documented Telegram Stars economics for a future USD-denominated bot.

Official Telegram developer reward reference: 0.013 USD per Star.
Ukraine iOS consumer example: 100 Stars cost 2.39 USD; this is
NOT publisher revenue and must NEVER be used to fund withdrawable credit.
An operator must confirm provider charges and policy compliance before use.
No write paths import this module: the live bot remains UAH.
"""
from decimal import Decimal, ROUND_DOWN

PUBLISHER_USD_PER_STAR = Decimal("0.013")
UKRAINE_IOS_100_STARS_USD = Decimal("2.39")
# Risk budget per paid Star: deliberately smaller than Telegram's developer reward.
PROPOSED_USD_CREDIT_PER_STAR = Decimal("0.010")
STAR_PAYOUT_AVAILABILITY_DAYS = 21
USD_MICRO = 1_000_000

def star_economics(stars, *, proposed_credit_usd=PROPOSED_USD_CREDIT_PER_STAR):
    if type(stars) is not int or not 1 <= stars <= 10000:
        raise ValueError("Stars must be a positive integer <= 10000")
    rate=Decimal(str(proposed_credit_usd))
    if not rate.is_finite() or rate <= 0 or rate > PUBLISHER_USD_PER_STAR:
        raise ValueError("USD credit cannot exceed reference net developer reward")
    def micro(value):
        return int((value * USD_MICRO).to_integral_value(rounding=ROUND_DOWN))
    return {
        "stars":stars,
        "currency_paid":"XTR",
        "consumer_reference_ua_ios_usd":str(UKRAINE_IOS_100_STARS_USD*stars/100),
        "developer_reward_reference_usd":str(PUBLISHER_USD_PER_STAR*stars),
        "proposed_credit_usd":str(rate*stars),
        "proposed_credit_micro_usd":micro(rate*stars),
        "reference_reserve_micro_usd":micro((PUBLISHER_USD_PER_STAR-rate)*stars),
        "pending_policy_review":True,
        "developer_reward_release_up_to_days":STAR_PAYOUT_AVAILABILITY_DAYS,
    }
