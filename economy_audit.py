"""Economy sanity checks for the agreed animal prices and feed cycles.

Assumes resources can be sold at listed base prices, with no warehouse
bottlenecks, trade fees, death or missed feeding. This is theoretical ROI,
not a promise of player profit or market liquidity.
"""
from production import CYCLE, FEED_EVERY, GRAIN_PRICE
from production_v4 import GOOSE_CYCLE, GOOSE_FEED, COW_FEED, MILK_INTERVAL, MILK_PRICE, COW_PRICE

HEN_PRICE = 40
GOOSE_PRICE = 160
EGG_PRICE = 1
DAY = 86400


def animal_economics():
    feed_interval = CYCLE * FEED_EVERY
    return {
        "chicken": {
            "price": HEN_PRICE,
            "daily_output": DAY / CYCLE,
            "daily_feed_cost": DAY / feed_interval * GRAIN_PRICE,
            "daily_net": DAY / CYCLE * EGG_PRICE - DAY / feed_interval * GRAIN_PRICE,
        },
        "goose": {
            "price": GOOSE_PRICE,
            "daily_output": DAY / GOOSE_CYCLE,
            "daily_feed_cost": DAY / feed_interval * GOOSE_FEED * GRAIN_PRICE,
            "daily_net": DAY / GOOSE_CYCLE * EGG_PRICE - DAY / feed_interval * GOOSE_FEED * GRAIN_PRICE,
        },
        "cow": {
            "price": COW_PRICE,
            "daily_output": DAY / MILK_INTERVAL,
            "daily_feed_cost": DAY / feed_interval * COW_FEED * GRAIN_PRICE,
            "daily_net": DAY / MILK_INTERVAL * MILK_PRICE - DAY / feed_interval * COW_FEED * GRAIN_PRICE,
        },
    }


def payback_days(animal):
    values = animal_economics()[animal]
    return values["price"] / values["daily_net"] if values["daily_net"] > 0 else None
