"""Independent unit-economics calculations for city balancing.

No DB writes; all sales and activity rates are hypothetical, not guaranteed.
"""
from city_world import RECIPES, FARM_REFERENCE_PRICES, recipe_price_guides
from city_nutrition import FOOD_RESTORE, DECAY_PER_HOUR
from fields import FIELD_PRICE, COMBINE_PRICE, rate

def field_payback_days(plots, combines, sold_fraction=1):
    if plots < 0 or combines < 0 or not 0 <= sold_fraction <= 1:
        raise ValueError("invalid inputs")
    income = rate(plots, combines) * FARM_REFERENCE_PRICES["grain"] * sold_fraction
    return (plots * FIELD_PRICE + combines * COMBINE_PRICE) / income if income > 0 else None

def business_payback_days(recipe, investment, batches_per_day, sold_fraction=1):
    if recipe not in RECIPES or investment < 0 or batches_per_day < 0 or not 0 <= sold_fraction <= 1:
        raise ValueError("invalid inputs")
    spec = RECIPES[recipe]
    guide = recipe_price_guides()[recipe]
    margin = (guide["suggested_unit_price"] * spec["output"] * sold_fraction
              - guide["batch_input_cost"])
    daily_profit = margin * batches_per_day
    return investment / daily_profit if daily_profit > 0 else None

def food_break_even(item, price=None):
    """Required daily farm output value to repay one meal at zero fullness."""
    restore = FOOD_RESTORE[item]
    boost_hours = (restore / DECAY_PER_HOUR) * (restore / 100) / 2
    if price is None:
        price = recipe_price_guides()[item]["suggested_unit_price"]
    return price * 24 / boost_hours

def audit():
    guides = recipe_price_guides()
    assert all(g["suggested_unit_price"] * g["batch_output"] >= g["batch_input_cost"]
               for g in guides.values())
    assert field_payback_days(1, 1) == 20
    assert business_payback_days("bread", 500, 10, 0) is None
    assert business_payback_days("bread", 500, 10, 1) is not None
    assert food_break_even("bread") > 12
    return {
        "one_field_plus_combine_payback_days": round(field_payback_days(1, 1), 2),
        "bread_price": guides["bread"]["suggested_unit_price"],
        "bread_min_farm_daily_output_to_break_even": round(food_break_even("bread"), 2),
        "bakery_500_coins_10_batches_payback_days":
            round(business_payback_days("bread", 500, 10), 2),
    }

if __name__ == "__main__":
    print(audit())
