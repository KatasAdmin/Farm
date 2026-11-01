"""Pure daily/weekly mission selection for the farm.

Selection is based on owned animals, so a player is never assigned a
species-specific production task without the corresponding producer.
Server-side event counters remain authoritative for progress.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class Mission:
    key: str
    target: int
    period: str

DAILY = (
    Mission("eggs_produced", 3, "daily"),
    Mission("feeding", 1, "daily"),
    Mission("market_sales", 1, "daily"),
    Mission("feathers_collected", 1, "daily"),
    Mission("milk_produced", 1, "daily"),
)
WEEKLY = (
    Mission("eggs_produced", 50, "weekly"),
    Mission("feeding", 7, "weekly"),
    Mission("market_sales", 5, "weekly"),
    Mission("feathers_collected", 1, "weekly"),
    Mission("milk_produced", 10, "weekly"),
)

def eligible(mission, chickens=0, geese=0, cows=0):
    if mission.key == "eggs_produced":
        return chickens > 0 or geese > 0
    if mission.key == "feathers_collected":
        return geese > 0
    if mission.key == "milk_produced":
        return cows > 0
    if mission.key == "feeding":
        return chickens + geese + cows > 0
    return True

def available(period, chickens=0, geese=0, cows=0):
    if period not in ("daily", "weekly"):
        raise ValueError("unknown mission period")
    pool = DAILY if period == "daily" else WEEKLY
    return tuple(m for m in pool if eligible(m, chickens, geese, cows))
