"""Read-only USD presentation for existing Farm coin units (staging).

Legacy game coins represent 1 UAH each, and MUST NOT be reclassified as
1 USD merely by changing frontend strings. This quote does not credit cash.
"""
from decimal import Decimal
from bot_usd_currency import MIGRATION_RATE_UAH_PER_USD, farm_coins_to_usd_micro, format_usd

def game_coin_usd_quote(coins, rate=MIGRATION_RATE_UAH_PER_USD):
    if type(coins) is not int or coins < 0:
        raise ValueError("Coin quote requires a nonnegative integer")
    micro = farm_coins_to_usd_micro(coins, rate)
    return {
        "source_currency": "FARM_COIN_LEGACY_UAH",
        "source_coins": coins,
        "quote_currency": "USD",
        "quote_micro_usd": micro,
        "quote_display": format_usd(micro),
        "uah_per_usd": str(Decimal(str(rate))),
        "quote_only": True,
    }
