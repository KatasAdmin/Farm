"""Exact denomination helpers for a staged UAH-to-USD wallet migration.

Not wired into production money flows. Existing production ledger is UAH
kopecks until every dependent table and payment path is migrated atomically.
"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN

USD_SCALE = 1_000_000
UAH_SCALE = 100
MIGRATION_RATE_UAH_PER_USD = Decimal("45.4432")  # NBU 2026-11-06 snapshot

def _rate(rate):
    try:
        value = Decimal(str(rate))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("Invalid USD/UAH exchange rate") from exc
    if not value.is_finite() or value <= 0:
        raise ValueError("USD/UAH exchange rate must be positive")
    return value

def uah_kopecks_to_usd_micro(kopecks, rate=MIGRATION_RATE_UAH_PER_USD):
    """Convert historical UAH value, never relabel kopecks as USD cents."""
    if type(kopecks) is not int:
        raise TypeError("kopecks must be an integer")
    result = Decimal(kopecks) * USD_SCALE / (UAH_SCALE * _rate(rate))
    return int(result.to_integral_value(rounding=ROUND_HALF_EVEN))

def usd_micro_to_uah_kopecks(micro, rate):
    """For future UAH bank settlement, with the rate fixed on the receipt."""
    if type(micro) is not int:
        raise TypeError("micro must be an integer")
    result = Decimal(micro) * UAH_SCALE * _rate(rate) / USD_SCALE
    return int(result.to_integral_value(rounding=ROUND_HALF_EVEN))

def parse_usd_micro(text):
    """Accept up to six decimals, reject exponent notation, negatives and NaN."""
    import re
    if not isinstance(text, str) or not re.fullmatch(r"(?:0|[1-9][0-9]{0,8})(?:[.,][0-9]{1,6})?", text.strip()):
        raise ValueError("Enter a USD amount with up to 6 decimals")
    value = Decimal(text.strip().replace(",", "."))
    result = value * USD_SCALE
    if result <= 0:
        raise ValueError("Amount must be positive")
    return int(result)

def format_usd(micro):
    if type(micro) is not int:
        raise TypeError("micro must be an integer")
    sign = "-" if micro < 0 else ""
    absolute = abs(micro)
    whole, fraction = divmod(absolute, USD_SCALE)
    decimals = f"{fraction:06d}".rstrip("0")
    decimals = decimals.ljust(2, "0")
    return f"{sign}$" + str(whole) + "." + decimals

def farm_coins_to_usd_micro(coins, rate=MIGRATION_RATE_UAH_PER_USD):
    """Legacy farm coin = 1 UAH. This is not a USD dollar."""
    if type(coins) is not int:
        raise TypeError("coins must be an integer")
    return uah_kopecks_to_usd_micro(coins * UAH_SCALE, rate)

def usd_micro_to_farm_coins(micro, rate=MIGRATION_RATE_UAH_PER_USD):
    """Round to whole game coins at a fixed disclosed exchange rate."""
    return usd_micro_to_uah_kopecks(micro, rate) // UAH_SCALE

def legacy_stars_rate_to_usd_micro(kopecks_per_star, rate=MIGRATION_RATE_UAH_PER_USD):
    """Old Stars wallet rate was UAH kopecks per XTR; preserve its value."""
    return uah_kopecks_to_usd_micro(kopecks_per_star, rate)
