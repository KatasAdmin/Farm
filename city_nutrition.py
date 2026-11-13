"""City food -> Farm production bonus.

This is intentionally separate from the existing animal feeding satiety field.
Only actually consumed city meals activate the bonus. The boost never transfers
coins, bypasses warehouse capacity, or creates ingredients without fed animals.
"""
from __future__ import annotations
import time

DECAY_PER_HOUR=5
DECAY_PER_SECOND=DECAY_PER_HOUR/3600.0
FOOD_RESTORE={"pancakes":35,"pie":45,"omelet":35,"cheese":25,"bread":20,
              "breakfast_set":75,"dessert_box":65,"lunch_box":70}
# Non-edible home goods can be used for city reputation, but cannot be eaten.

def initialize(c):
    c.execute("""CREATE TABLE IF NOT EXISTS city_nutrition(
      player_id text PRIMARY KEY,
      fullness double precision NOT NULL CHECK(fullness>=0 AND fullness<=100),
      updated_at double precision NOT NULL)""")

def get(c,pid):
    row=c.execute("SELECT fullness,updated_at FROM city_nutrition WHERE player_id=%s",
                  (pid,)).fetchone()
    return {"fullness":float(row["fullness"]),"updated_at":float(row["updated_at"])} if row else None

def fullness(food,at):
    if not food:return 0.0
    return max(0.,min(100.,float(food["fullness"])-DECAY_PER_SECOND*max(0.,float(at)-float(food["updated_at"]))))

def status(food,at=None):
    now=time.time() if at is None else at
    level=fullness(food,now)
    return {"active":food is not None,"fullness":round(level,1),
        "bonus_percent":round(level,1),"production_multiplier":round(1+level/100,4),
        "decay_per_hour":DECAY_PER_HOUR,
        "next_empty_at":food["updated_at"]+food["fullness"]/DECAY_PER_SECOND if food else None}

def bonus_seconds(food,start,end):
    """Integral of fractional fullness over [start,end]. Exact piecewise linear.
    Max 1x additional production; 0 for those who have never eaten."""
    if not food or end<=start:return 0.0
    base=float(food["updated_at"]);f=float(food["fullness"])
    if f<=0:return 0.
    stop=base+f/DECAY_PER_SECOND
    left=max(start,base)
    right=min(end,stop)
    # A food state only applies from when a meal was actually eaten, never
    # retroactively to the time before it.
    if right<=left:return 0.
    a=max(0.,f-DECAY_PER_SECOND*(left-base))
    b=max(0.,f-DECAY_PER_SECOND*(right-base))
    return (right-left)*(a+b)/200.

def eat(c,pid,item,qty,now=None):
    if item not in FOOD_RESTORE:raise ValueError("Item cannot be eaten")
    if qty<1 or qty>20:raise ValueError("Invalid meal quantity")
    now=time.time() if now is None else now
    old=get(c,pid)
    level=min(100.,fullness(old,now)+FOOD_RESTORE[item]*qty)
    c.execute("""INSERT INTO city_nutrition(player_id,fullness,updated_at)
      VALUES(%s,%s,%s) ON CONFLICT(player_id) DO UPDATE SET
      fullness=EXCLUDED.fullness,updated_at=EXCLUDED.updated_at""",(pid,level,now))
    return status({"fullness":level,"updated_at":now},now)
