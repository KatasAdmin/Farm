"""USD withdrawal quote calculations (staging only, no cash movement).

Real payment approval remains owned by the bot payout workflow. Quotes must be
attached to immutable withdrawal requests with a provider rate and timestamp
before enabling a USD payout path.
"""
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from bot_usd_currency import USD_SCALE, UAH_SCALE, _rate

def payout_quote_usd(micro_usd, method, *, fee_micro_usd=0, uah_per_usd=None, usdt_per_usd=None, network_fee_usdt=None, network=None):
    """Return net USD and destination amount; never round above funds held."""
    if type(micro_usd) is not int or micro_usd <= 0:
        raise ValueError("USD withdrawal must be positive micro-USD")
    if type(fee_micro_usd) is not int or not 0 <= fee_micro_usd < micro_usd:
        raise ValueError("Invalid withdrawal fee")
    net = micro_usd - fee_micro_usd
    if method == "usdt":
        if network not in ("TRC20", "TON"):
            raise ValueError("Explicit USDT network required")
        if usdt_per_usd is None or network_fee_usdt is None:
            raise ValueError("USDT payout requires separate rate and network fee")
        rate = _rate(usdt_per_usd)
        fee = Decimal(str(network_fee_usdt))
        if not fee.is_finite() or fee < 0:
            raise ValueError("Invalid USDT network fee")
        usdt_before_fee = Decimal(net) * rate / USD_SCALE
        usdt_micro = int(((usdt_before_fee - fee) * USD_SCALE).to_integral_value(rounding=ROUND_DOWN))
        if usdt_micro <= 0:
            raise ValueError("USDT transfer amount too small after fees")
        return {
            "debit_usd_micro": micro_usd,
            "fee_usd_micro": fee_micro_usd,
            "net_usd_micro": net,
            "method": method,
            "network": network,
            "rate_usdt_per_usd": str(rate),
            "network_fee_usdt": str(fee),
            "destination_usdt_micro": usdt_micro,
            "destination_currency": "USDT",
        }
    if method != "uah_card":
        raise ValueError("Unsupported destination method")
    if uah_per_usd is None:
        raise ValueError("UAH card withdrawal requires a real exchange rate")
    rate = _rate(uah_per_usd)
    payout_kopecks = int(
        (Decimal(net) * rate * UAH_SCALE / USD_SCALE).to_integral_value(rounding=ROUND_DOWN)
    )
    if payout_kopecks <= 0:
        raise ValueError("Withdrawal is below the smallest UAH bank settlement unit")
    return {
        "debit_usd_micro": micro_usd,
        "fee_usd_micro": fee_micro_usd,
        "net_usd_micro": net,
        "method": method,
        "rate_uah_per_usd": str(rate),
        "destination_kopecks": payout_kopecks,
        "destination_currency": "UAH",
    }
