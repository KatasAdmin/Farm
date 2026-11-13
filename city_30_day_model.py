"""Thirty-day closed-wallet model of farm-to-city trade.

This is a scenario tool, not a claim of real demand or a live economy change.
Every coin transfer is conserved, including treasury investments.
"""
from city_world import recipe_price_guides, business_upgrade_cost

def run(days=30, farmers=100, businesses=100, initial_coins=1000,
        active_fraction=0.75, meals_per_active=1.0):
    if min(days,farmers,businesses,initial_coins)<0 or not 0<=active_fraction<=1:
        raise ValueError("invalid simulation parameters")
    farm_cash=farmers*initial_coins
    city_cash=businesses*initial_coins
    treasury=0
    bread=recipe_price_guides()["bread"]
    raw_cost=bread["batch_input_cost"]
    unit_price=bread["suggested_unit_price"]
    bread_output=bread["batch_output"]
    history=[]
    grain_stock=0
    food_stock=0
    for day in range(1,days+1):
        # One field + one combine per farmer; actual farm yields 11 grain/day.
        grain_stock+=farmers*11
        wanted=min(int((farmers+businesses)*active_fraction*meals_per_active),
                   businesses*8*bread_output)
        batches=min(grain_stock//5, (wanted+1)//bread_output, city_cash//raw_cost)
        # Business pays farmers for raw grain. Both parties keep their coins.
        paid=batches*raw_cost
        farm_cash+=paid
        city_cash-=paid
        grain_stock-=batches*5
        food_stock+=batches*bread_output
        # Consumers split across farm and city players proportionally.
        sold=min(food_stock,wanted)
        farmer_buyers=min(sold, int(sold*farmers/(farmers+businesses)))
        city_buyers=sold-farmer_buyers
        # Cap purchases to each sector's available wallet; no coin overdraft.
        farmer_buyers=min(farmer_buyers,farm_cash//unit_price)
        city_buyers=min(city_buyers,city_cash//unit_price)
        spend_farm=farmer_buyers*unit_price
        spend_city=city_buyers*unit_price
        farm_cash-=spend_farm
        city_cash+=spend_farm  # Farmer purchases transfer to city sellers.
        # City-to-city purchases are internal transfers and do not change totals.
        food_stock-=farmer_buyers+city_buyers
        assert farm_cash>=0 and city_cash>=0
        assert farm_cash+city_cash+treasury==(farmers+businesses)*initial_coins
        history.append(dict(day=day,farmer_coins=farm_cash,city_coins=city_cash,
                            treasury=treasury,grain_stock=grain_stock,
                            unsold_food=food_stock,food_sold=farmer_buyers+city_buyers))
    return history

def audit():
    for farmers,businesses in ((10,10),(100,100),(1000,1000)):
        for fraction in (0.25,0.5,0.75,1):
            history=run(farmers=farmers,businesses=businesses,active_fraction=fraction)
            assert len(history)==30
            assert all(row["farmer_coins"]>=0 and row["city_coins"]>=0 for row in history)
    return run()[-1]

if __name__=="__main__":
    print(audit())
