"""TREVIXO simple-system economy. No player orders or auction matching.

System sales create non-withdrawable game credits; the treasury is a signed
accounting balance rather than a spending limit. Buying from system replenishes treasury.
All changes in a single PostgreSQL transaction guarded by the shared lock.
"""
from __future__ import annotations
import os,time,uuid,math
from fastapi import HTTPException
from production import GRAIN_PRICE
from production_v4 import MILK_PRICE
import city_nutrition

RAW_BUY={"eggs":2,"grain":2,"milk":15,"feathers":7,"wool":20}
RAW_SELL={"eggs":1,"grain":1,"milk":12,"feathers":5,"wool":16}
ANIMAL_BUY={"chickens":20,"geese":120,"cows":500,"sheep":200}
ANIMAL_SELL={k:max(1,p//2) for k,p in ANIMAL_BUY.items()}
BUSINESS_COST={"bakery":80,"restaurant":180,"dairy":280,"atelier":360,"store":500}
ALL_FARM=tuple(RAW_BUY)+tuple(ANIMAL_BUY)
KIND="simple_system"

def enabled():
    # Test fixture runs must remain backward compatible, even when the
    # deployed app has enabled the simpler system economy.
    if os.environ.get("TEST_DATABASE_URL"):
        return False
    return os.environ.get("SIMPLE_SYSTEM_ECONOMY","0").lower() in ("1","true","yes")

def prices(recipes):
    """Products sell below system input acquisition cost, and buy above sell."""
    output={}
    for key,r in recipes.items():
        cost=sum(RAW_BUY[k]*n for k,n in r.get("needs",{}).items())
        cost+=sum(output[k]["buy"]*n for k,n in r.get("needs_products",{}).items())
        per_unit=max(1,int(math.floor(cost*0.88/max(1,r["output"]))))
        output[key]={"sell":per_unit,"buy":max(per_unit+1,int(math.ceil(per_unit*1.25))),
                     "batch_input_cost":cost}
    return output

def initialize(c):
    c.execute("""CREATE TABLE IF NOT EXISTS simple_system_trades (
        id text PRIMARY KEY,player_id text NOT NULL,item text NOT NULL,
        kind text NOT NULL,quantity bigint NOT NULL CHECK(quantity>0),
        coins bigint NOT NULL CHECK(coins>=0),created double precision NOT NULL)""")
    c.execute("""CREATE INDEX IF NOT EXISTS simple_trades_player
        ON simple_system_trades(player_id,created DESC)""")

def migrate_listings(c):
    """Release all historical listings exactly once, preserving balances."""
    c.execute("SELECT pg_advisory_xact_lock(1984533)")
    old=c.execute("SELECT seller,item,quantity FROM market WHERE quantity>0 FOR UPDATE").fetchall()
    for row in old:
        if row["item"] in RAW_BUY:
            c.execute("UPDATE players SET "+row["item"]+"="+row["item"]+"+%s WHERE id=%s",
                      (row["quantity"],row["seller"]))
        # Living animals were always reserved in the player herd, not removed.
    c.execute("UPDATE market SET quantity=0 WHERE quantity>0")
    old_city=c.execute("SELECT seller,item,quantity FROM city_listings WHERE quantity>0 FOR UPDATE").fetchall()
    for row in old_city:
        c.execute("""INSERT INTO city_products(player_id,item,quantity) VALUES(%s,%s,%s)
          ON CONFLICT(player_id,item) DO UPDATE SET quantity=city_products.quantity+EXCLUDED.quantity""",
          (row["seller"],row["item"],row["quantity"]))
    c.execute("UPDATE city_listings SET quantity=0 WHERE quantity>0")
    return {"farm_lots":len(old),"city_lots":len(old_city)}

def amount(n,limit=500):
    if type(n) is not int or n<1 or n>limit:
        raise HTTPException(400,"Количество от 1 до "+str(limit))

def _record(c,pid,item,kind,n,value):
    c.execute("INSERT INTO simple_system_trades VALUES(%s,%s,%s,%s,%s,%s,%s)",
              (uuid.uuid4().hex,pid,item,kind,n,value,time.time()))

def _cash(c,p,coins,kind,item,n):
    """A system trade is always a bonus/purchasing-credit source, never earned."""
    from psycopg.types.json import Jsonb
    if kind=="buy":
        paid=c.execute("UPDATE players SET coins=coins-%s WHERE id=%s AND coins>=%s RETURNING coins",
                       (coins,p["id"],coins)).fetchone()
        if not paid:raise HTTPException(409,"Недостаточно монет")
        c.execute("UPDATE economy SET treasury=treasury+%s WHERE id=1",(coins,))
        delta=-coins
    else:
        c.execute("UPDATE economy SET treasury=treasury-%s WHERE id=1",(coins,))
        c.execute("UPDATE players SET coins=coins+%s WHERE id=%s",(coins,p["id"]))
        delta=coins
    log_id=uuid.uuid4().hex
    c.execute("INSERT INTO money_log VALUES(%s,%s,%s,%s,%s,%s)",
              (log_id,p["id"],"simple_system_"+kind,delta,item+" x"+str(n),time.time()))
    if delta>0:
        c.execute("INSERT INTO farm_money_sources VALUES(%s,%s,0,0)",(log_id,delta))
    _record(c,p["id"],item,kind,n,coins)

def farm_trade(c,p,item,n,kind,*,storage_limit=None,coop_limit=None,cowshed_limit=None):
    amount(n)
    prices=({**RAW_BUY,**ANIMAL_BUY} if kind=="buy" else {**RAW_SELL,**ANIMAL_SELL})
    if item not in prices:raise HTTPException(400,"Неизвестный товар")
    total=prices[item]*n
    if kind=="buy":
        if item in RAW_BUY:
            if storage_limit is not None and sum(int(p.get(k,0)) for k in RAW_BUY)+n>storage_limit:
                raise HTTPException(409,"Склад заполнен")
        elif item in ("chickens","geese") and coop_limit is not None:
            if p["chickens"]+p.get("geese",0)+n>coop_limit:raise HTTPException(409,"Нет места в курятнике")
        elif cowshed_limit is not None:
            if p.get("cows",0)+p.get("sheep",0)+n>cowshed_limit:raise HTTPException(409,"Нет места в стаднике")
    else:
        if p.get(item,0)<n:raise HTTPException(409,"Недостаточно товара")
    _cash(c,p,total,kind,item,n)
    if kind=="buy":
        if item=="chickens":
            c.execute("UPDATE players SET chickens=chickens+%s,fed_hens=fed_hens+%s WHERE id=%s",(n,n,p["id"]))
        elif item=="geese":
            c.execute("UPDATE players SET geese=geese+%s,fed_geese=fed_geese+%s WHERE id=%s",(n,n,p["id"]))
        elif item=="cows":
            c.execute("UPDATE players SET cows=cows+%s,fed_cows=fed_cows+%s WHERE id=%s",(n,n,p["id"]))
        elif item=="sheep":
            c.execute("UPDATE players SET sheep=sheep+%s,fed_sheep=fed_sheep+%s WHERE id=%s",(n,n,p["id"]))
        else:
            c.execute("UPDATE players SET "+item+"="+item+"+%s WHERE id=%s",(n,p["id"]))
    else:
        if item in ANIMAL_BUY:
            fed={"chickens":"fed_hens","geese":"fed_geese","cows":"fed_cows","sheep":"fed_sheep"}[item]
            c.execute("UPDATE players SET "+item+"="+item+"-%s,"+fed+"=LEAST("+fed+","+item+"-%s) WHERE id=%s",(n,n,p["id"]))
        else:
            c.execute("UPDATE players SET "+item+"="+item+"-%s WHERE id=%s",(n,p["id"]))
    return {"ok":True,"spent":total if kind=="buy" else 0,
            "received":total if kind=="sell" else 0,"unit_price":prices[item]}

def raw_city_trade(c,p,item,n,kind):
    amount(n)
    if item not in RAW_BUY:raise HTTPException(400,"Неизвестное сырьё")
    if kind=="sell":
        row=c.execute("""UPDATE city_stock SET quantity=quantity-%s
            WHERE player_id=%s AND item=%s AND quantity>=%s RETURNING quantity""",
            (n,p["id"],item,n)).fetchone()
        if not row:raise HTTPException(409,"Недостаточно сырья")
    _cash(c,p,(RAW_BUY if kind=="buy" else RAW_SELL)[item]*n,kind,item,n)
    if kind=="buy":
        _add_city(c,"city_stock",p["id"],item,n)
    price=(RAW_BUY if kind=="buy" else RAW_SELL)[item]
    return {"ok":True,"spent":price*n if kind=="buy" else 0,
            "received":price*n if kind=="sell" else 0,"unit_price":price}

def _add_city(c,table,pid,item,n):
    if table not in ("city_stock","city_products","farm_food"):raise ValueError("Invalid warehouse")
    c.execute(f"""INSERT INTO {table}(player_id,item,quantity) VALUES(%s,%s,%s)
     ON CONFLICT(player_id,item) DO UPDATE SET quantity={table}.quantity+EXCLUDED.quantity""",
     (pid,item,n))

def city_product_trade(c,p,item,n,kind,recipes,*,destination="city"):
    amount(n)
    catalog=prices(recipes)
    if item not in catalog:raise HTTPException(400,"Неизвестный товар")
    if destination=="farm" and item not in city_nutrition.FOOD_RESTORE:
        raise HTTPException(400,"На фермерский склад можно купить только еду")
    table="farm_food" if destination=="farm" else "city_products"
    if kind=="sell":
        row=c.execute(f"""UPDATE {table} SET quantity=quantity-%s
          WHERE player_id=%s AND item=%s AND quantity>=%s RETURNING quantity""",
          (n,p["id"],item,n)).fetchone()
        if not row:raise HTTPException(409,"Недостаточно продукции")
    unit=catalog[item][kind]
    _cash(c,p,n*unit,kind,item,n)
    if kind=="buy":_add_city(c,table,p["id"],item,n)
    return {"ok":True,"spent":unit*n if kind=="buy" else 0,
            "received":unit*n if kind=="sell" else 0,"unit_price":unit}

def raw_transfer(c,p,item,n,direction,*,storage_limit=None):
    amount(n)
    if item not in RAW_BUY:raise HTTPException(400,"Неизвестный ресурс")
    if direction=="to_city":
        if p.get(item,0)<n:raise HTTPException(409,"Недостаточно ресурсов на ферме")
        c.execute("UPDATE players SET "+item+"="+item+"-%s WHERE id=%s",(n,p["id"]))
        _add_city(c,"city_stock",p["id"],item,n)
    elif direction=="to_farm":
        if storage_limit is not None and sum(int(p.get(k,0)) for k in RAW_BUY)+n>storage_limit:
            raise HTTPException(409,"Недостаточно места на ферме")
        row=c.execute("""UPDATE city_stock SET quantity=quantity-%s
            WHERE player_id=%s AND item=%s AND quantity>=%s RETURNING quantity""",
            (n,p["id"],item,n)).fetchone()
        if not row:raise HTTPException(409,"Недостаточно ресурсов в городе")
        c.execute("UPDATE players SET "+item+"="+item+"+%s WHERE id=%s",(n,p["id"]))
    else:raise HTTPException(400,"Неверное направление")
    _record(c,p["id"],item,direction,n,0)
    return {"ok":True,"transferred":n,"destination":direction}

def product_transfer(c,p,item,n,direction):
    amount(n)
    if item not in city_nutrition.FOOD_RESTORE:
        raise HTTPException(400,"Переносить на ферму можно только еду")
    if direction=="to_farm":source,target="city_products","farm_food"
    elif direction=="to_city":source,target="farm_food","city_products"
    else:raise HTTPException(400,"Неверное направление")
    row=c.execute(f"""UPDATE {source} SET quantity=quantity-%s
        WHERE player_id=%s AND item=%s AND quantity>=%s RETURNING quantity""",
        (n,p["id"],item,n)).fetchone()
    if not row:raise HTTPException(409,"Недостаточно еды")
    _add_city(c,target,p["id"],item,n)
    _record(c,p["id"],item,direction,n,0)
    return {"ok":True,"transferred":n,"destination":direction}
