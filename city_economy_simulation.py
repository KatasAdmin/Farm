"""Deterministic stress test for city food demand; no database or coin minting."""
from __future__ import annotations
from dataclasses import dataclass
from city_world import RECIPES, FARM_REFERENCE_PRICES, recipe_price_guides
from city_nutrition import FOOD_RESTORE

@dataclass(frozen=True)
class Scenario:
    farmers: int
    businesses: int
    chickens_per_farmer: int
    buyers_fraction: float
    meals_per_buyer: float
    business_utilization: float

def evaluate(s: Scenario):
    # Four eggs per chicken per day is the unboosted two-hour production rate
    # adjusted to a conservative 1/3 realized output (feeding/storage/absence).
    eggs_supply = s.farmers * s.chickens_per_farmer * 4
    demand_meals = (s.farmers+s.businesses)*s.buyers_fraction*s.meals_per_buyer
    # One third of demand is egg-intensive meals; the other two thirds use
    # bread, dairy and prepared meals. This is an assumption, not observed data.
    egg_meals = demand_meals / 3
    egg_demand = egg_meals * 4
    bakery_capacity = s.businesses * s.business_utilization * 12
    sold_meals = min(demand_meals, bakery_capacity)
    return dict(eggs_supply=round(eggs_supply), eggs_demand=round(egg_demand),
                demand_meals=round(demand_meals), meal_capacity=round(bakery_capacity),
                sold_meals=round(sold_meals),
                egg_coverage=round(eggs_supply/egg_demand, 3) if egg_demand else None)

def stress_1001():
    """Exactly 1001 distinct scenarios across activity, flock size and utilization."""
    results=[]
    for i in range(1001):
        s=Scenario(farmers=100,businesses=100,
                   chickens_per_farmer=1+i%10,
                   buyers_fraction=(20+(i//10)%9*10)/100,
                   meals_per_buyer=1+(i//90)%4,
                   business_utilization=(25+(i//360)%3*25)/100)
        results.append((s,evaluate(s)))
    return results

def check_price_integrity():
    guides=recipe_price_guides()
    assert FARM_REFERENCE_PRICES['grain']==2
    assert FARM_REFERENCE_PRICES['milk']==11
    assert FARM_REFERENCE_PRICES['eggs']==1
    assert FARM_REFERENCE_PRICES['wool']==12
    for key, recipe in RECIPES.items():
        guide=guides[key]
        assert guide['batch_input_cost']>0
        assert guide['suggested_unit_price']*recipe['output']>=guide['batch_input_cost']
        assert guide['batch_seconds']>=1800
    assert set(FOOD_RESTORE).issubset(RECIPES)

if __name__=='__main__':
    check_price_integrity()
    scenarios=stress_1001()
    assert len(scenarios)==1001
    assert all(r['eggs_supply']>=0 and r['sold_meals']<=r['meal_capacity']
               for _,r in scenarios)
    print('1001 stress scenarios passed; sample:', scenarios[500])
