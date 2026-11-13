"""Business City MVP: isolated city inventory, genuine farm-market purchases.

No raw resources can be transferred from a player's farm warehouse to their city
business. All city ingredients must be bought from a DIFFERENT farmer's listing.
No NPC money emissions or withdrawable city-product rewards.
"""
from __future__ import annotations
import time
import uuid
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
import market_allocation
import farm_wallet
import ad_inventory

router = APIRouter(prefix="/api/city", tags=["city"])
INGREDIENTS = ("eggs", "grain", "milk", "feathers", "wool")
RECIPES = {
    "pancakes": {"name": "Блины", "business": "bakery", "needs": {"eggs": 4, "grain": 3, "milk": 1}, "output": 2, "seconds": 30},
    "pie": {"name": "Пирог", "business": "bakery", "needs": {"eggs": 8, "grain": 5}, "output": 1, "seconds": 45},
    "omelet": {"name": "Омлет", "business": "restaurant", "needs": {"eggs": 5, "milk": 1}, "output": 1, "seconds": 30},
    "cheese": {"name": "Сыр", "business": "dairy", "needs": {"milk": 5}, "output": 2, "seconds": 45},
    "bread": {"name": "Хлеб", "business": "bakery", "needs": {"grain": 5}, "output": 2, "seconds": 30},
    "pillow": {"name": "Подушка", "business": "atelier", "needs": {"feathers": 4, "wool": 2}, "output": 1, "seconds": 60},
    "scarf": {"name": "Шарф", "business": "atelier", "needs": {"wool": 6}, "output": 1, "seconds": 60},
    # Second-stage recipes give other businesses a reason to buy goods made
    # by bakers, dairies and textile workshops rather than only raw resources.
    "breakfast_set": {"name": "Фирменный завтрак", "business": "restaurant",
        "needs": {"eggs": 2}, "needs_products": {"bread": 1, "cheese": 1}, "output": 1, "seconds": 75},
    "dessert_box": {"name": "Десертный набор", "business": "restaurant",
        "needs": {"milk": 2}, "needs_products": {"pancakes": 2, "pie": 1}, "output": 1, "seconds": 90},
    "home_set": {"name": "Домашний уют", "business": "store",
        "needs": {}, "needs_products": {"pillow": 1, "scarf": 1}, "output": 1, "seconds": 100},
    "lunch_box": {"name": "Обед с собой", "business": "store",
        "needs": {}, "needs_products": {"omelet": 1, "bread": 1}, "output": 1, "seconds": 70},
}
BUSINESSES = {
    "bakery": {"name": "Пекарня", "emoji": "🥐", "open_cost": 0, "min_reputation": 0},
    "restaurant": {"name": "Ресторан", "emoji": "🍳", "open_cost": 0, "min_reputation": 20},
    "dairy": {"name": "Молочная", "emoji": "🥛", "open_cost": 0, "min_reputation": 50},
    "atelier": {"name": "Ателье", "emoji": "🧶", "open_cost": 0, "min_reputation": 100},
    "store": {"name": "Магазин", "emoji": "🛒", "open_cost": 0, "min_reputation": 160},
}

_db = _person = _advance = None

def setup(db, person, advance):
    global _db, _person, _advance
    _db, _person, _advance = db, person, advance
    return router

def initialize(c):
    c.execute("""CREATE TABLE IF NOT EXISTS city_businesses(
        player_id text NOT NULL, kind text NOT NULL, level integer NOT NULL DEFAULT 1,
        opened double precision NOT NULL, PRIMARY KEY(player_id,kind))""")
    c.execute("""CREATE TABLE IF NOT EXISTS city_stock(
        player_id text NOT NULL, item text NOT NULL, quantity bigint NOT NULL DEFAULT 0
        CHECK(quantity>=0), PRIMARY KEY(player_id,item))""")
    c.execute("""CREATE TABLE IF NOT EXISTS city_products(
        player_id text NOT NULL, item text NOT NULL, quantity bigint NOT NULL DEFAULT 0
        CHECK(quantity>=0), PRIMARY KEY(player_id,item))""")
    c.execute("""CREATE TABLE IF NOT EXISTS city_jobs(
        id text PRIMARY KEY, player_id text NOT NULL, recipe text NOT NULL,
        quantity integer NOT NULL CHECK(quantity>0), ready_at double precision NOT NULL)""")
    c.execute("CREATE INDEX IF NOT EXISTS city_jobs_player_ready ON city_jobs(player_id,ready_at)")
    c.execute("""CREATE TABLE IF NOT EXISTS city_listings(
        id text PRIMARY KEY, seller text NOT NULL, item text NOT NULL,
        quantity integer NOT NULL CHECK(quantity>=0), price integer NOT NULL CHECK(price>0),
        created double precision NOT NULL)""")
    c.execute("CREATE INDEX IF NOT EXISTS city_listings_item ON city_listings(item,price) WHERE quantity>0")
    c.execute("""CREATE TABLE IF NOT EXISTS city_receipts(
        id text PRIMARY KEY, buyer text NOT NULL, seller text NOT NULL,
        item text NOT NULL, quantity integer NOT NULL, coins integer NOT NULL,
        created double precision NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS city_requests(
        id text PRIMARY KEY, player_id text NOT NULL, action text NOT NULL,
        item text NOT NULL, quantity integer NOT NULL, result jsonb)""")
    c.execute("""CREATE TABLE IF NOT EXISTS city_daily_orders(
        player_id text NOT NULL, day text NOT NULL, order_id text NOT NULL,
        completed_at double precision NOT NULL,
        PRIMARY KEY(player_id,day,order_id))""")
    c.execute("""CREATE TABLE IF NOT EXISTS city_reputation(
        player_id text PRIMARY KEY, points bigint NOT NULL DEFAULT 0 CHECK(points>=0))""")

def daily_orders(c,pid):
    day=time.strftime("%Y-%m-%d",time.gmtime())
    rotation=int(time.time()//86400)
    lineup=(
        ("breakfast",("bread","pancakes","pie"),15),
        ("lunch",("omelet","cheese"),25),
        ("comfort",("pillow","scarf"),35),
        ("dinner",("breakfast_set","dessert_box","lunch_box"),45),
        ("home",("home_set","pillow","scarf"),55),
    )
    finished={r["order_id"] for r in c.execute(
        "SELECT order_id FROM city_daily_orders WHERE player_id=%s AND day=%s",
        (pid,day)).fetchall()}
    return [{"id":key,"recipe":options[rotation%len(options)],
        "quantity":1,"reputation":reward,"done":key in finished}
        for key,options,reward in lineup]

def _auth(c, authorization, write=False):
    return _person(c, authorization, write)

def _counts(c, table, pid):
    return {r["item"]: int(r["quantity"]) for r in c.execute(
        "SELECT item,quantity FROM "+table+" WHERE player_id=%s AND quantity>0", (pid,)).fetchall()}

def _settle(c, pid):
    jobs=c.execute("SELECT * FROM city_jobs WHERE player_id=%s AND ready_at<=%s FOR UPDATE",(pid,time.time())).fetchall()
    for job in jobs:
        recipe=RECIPES[job["recipe"]]
        c.execute("""INSERT INTO city_products(player_id,item,quantity) VALUES(%s,%s,%s)
            ON CONFLICT(player_id,item) DO UPDATE
            SET quantity=city_products.quantity+EXCLUDED.quantity""",
            (pid,job["recipe"],job["quantity"]*recipe["output"]))
        c.execute("DELETE FROM city_jobs WHERE id=%s",(job["id"],))
    return len(jobs)

class Action(BaseModel):
    item: str = ""
    amount: int = 1
    price: int = 1
    request_id: str = ""
    expected_cost: int = -1
    listing_id: str = ""

def _request(c, q, pid, action):
    # Same transaction-level market lock as the farm. An identical retry key
    # returns its recorded result without repeating any resource or coin changes.
    key=q.request_id
    if not isinstance(key,str) or len(key)!=32 or any(ch not in "0123456789abcdef" for ch in key):
        raise HTTPException(400,"Операция требует действительный ключ повтора")
    existing=c.execute("SELECT * FROM city_requests WHERE id=%s FOR UPDATE",(key,)).fetchone()
    if existing:
        if (existing["player_id"],existing["action"],existing["item"],existing["quantity"])!=(pid,action,q.item,q.amount):
            raise HTTPException(409,"Ключ операции уже использован")
        return existing["result"]
    c.execute("INSERT INTO city_requests VALUES(%s,%s,%s,%s,%s,NULL)",(key,pid,action,q.item,q.amount))
    return None

def _finish_request(c,q,result):
    from psycopg.types.json import Jsonb
    c.execute("UPDATE city_requests SET result=%s WHERE id=%s",(Jsonb(result),q.request_id))

def _quote(c,table,item,pid,n):
    rows=c.execute("SELECT * FROM "+table+" WHERE item=%s AND seller<>%s AND quantity>0 ORDER BY price,id",
        (item,pid)).fetchall()
    if sum(int(r["quantity"]) for r in rows)<n:
        raise HTTPException(409,"На рынке недостаточно предложений")
    chosen=market_allocation.allocate(rows,n)
    return {"ok":True,"item":item,"quantity":n,
        "cost":sum(r["price"]*qty for r,qty in chosen),
        "sellers":len({r["seller"] for r,qty in chosen})}

@router.post("/quote-ingredient")
def quote_ingredient(q:Action,authorization:str=Header(default="")):
    if q.item not in INGREDIENTS:raise HTTPException(400,"Неизвестный ингредиент")
    _amount(q.amount,500)
    with _db() as c:
        p=_auth(c,authorization)
        return _quote(c,"market",q.item,p["id"],q.amount)

@router.post("/quote-product")
def quote_product(q:Action,authorization:str=Header(default="")):
    if q.item not in RECIPES:raise HTTPException(400,"Неизвестный товар")
    _amount(q.amount,500)
    with _db() as c:
        p=_auth(c,authorization)
        return _quote(c,"city_listings",q.item,p["id"],q.amount)

def _amount(n, maximum=10000):
    if type(n) is not int or n<1 or n>maximum:
        raise HTTPException(400,"Укажите корректное количество")

@router.get("/catalog")
def public_catalog():
    # Safe static catalog for a read-only demonstration of the City.
    return {"recipes":RECIPES,"business_catalog":BUSINESSES,"demo":True}

@router.get("/state")
def state(authorization: str=Header(default="")):
    with _db() as c:
        p=_auth(c,authorization)
        _settle(c,p["id"])
        businesses=[r["kind"] for r in c.execute(
            "SELECT kind FROM city_businesses WHERE player_id=%s",(p["id"],)).fetchall()]
        offers=c.execute("""SELECT l.id,l.item,l.price,l.quantity,p.name AS seller FROM market l
            JOIN players p ON p.id=l.seller
            WHERE l.quantity>0 AND l.seller<>%s AND l.item=ANY(%s)
            ORDER BY l.item,l.price,l.id LIMIT 70""",(p["id"],list(INGREDIENTS))).fetchall()
        my_city_offers=c.execute("SELECT id,item,quantity,price FROM city_listings WHERE seller=%s AND quantity>0 ORDER BY created DESC",(p["id"],)).fetchall()
        city_offers=c.execute("""SELECT l.id,l.item,l.price,l.quantity,p.name AS seller
            FROM city_listings l JOIN players p ON p.id=l.seller
            WHERE l.quantity>0 AND l.seller<>%s ORDER BY l.item,l.price,l.id LIMIT 70""",(p["id"],)).fetchall()
        jobs=c.execute("SELECT recipe,quantity,ready_at FROM city_jobs WHERE player_id=%s ORDER BY ready_at",(p["id"],)).fetchall()
        rep=c.execute("SELECT points FROM city_reputation WHERE player_id=%s",(p["id"],)).fetchone()
        return {"name":p["name"],"coins":p["coins"],"businesses":businesses,
            "stock":_counts(c,"city_stock",p["id"]),
            "products":_counts(c,"city_products",p["id"]),
            "recipes":RECIPES,"business_catalog":BUSINESSES,
            "farm_offers":offers,"city_offers":city_offers,
            "my_city_offers":my_city_offers,"jobs":jobs,
            "resident_orders":daily_orders(c,p["id"]),
            "reputation":int(rep["points"]) if rep else 0}

@router.post("/open")
def open_business(q:Action, authorization: str=Header(default="")):
    if q.item not in BUSINESSES:raise HTTPException(400,"Неизвестное предприятие")
    with _db() as c:
        p=_auth(c,authorization,True)
        reputation=c.execute("SELECT points FROM city_reputation WHERE player_id=%s",(p["id"],)).fetchone()
        if (int(reputation["points"]) if reputation else 0)<BUSINESSES[q.item]["min_reputation"]:
            raise HTTPException(403,"Нужно больше репутации для открытия бизнеса")
        c.execute("INSERT INTO city_businesses VALUES(%s,%s,1,%s) ON CONFLICT DO NOTHING",(p["id"],q.item,time.time()))
    return {"ok":True}

@router.post("/buy-ingredient")
def buy_ingredient(q:Action,authorization:str=Header(default="")):
    """Buy only market listings belonging to other players, directly into city_stock."""
    if q.item not in INGREDIENTS:raise HTTPException(400,"Этот ресурс нельзя закупать")
    _amount(q.amount,500)
    with _db() as c:
        c.execute("SELECT pg_advisory_xact_lock(1984533)")
        p=_advance(c,_auth(c,authorization,True))
        previous=_request(c,q,p["id"],"buy_ingredient")
        if previous is not None:return previous
        rows=c.execute("""SELECT * FROM market WHERE item=%s AND seller<>%s
            AND quantity>0 ORDER BY price,id FOR UPDATE""",(q.item,p["id"])).fetchall()
        if sum(int(row["quantity"]) for row in rows)<q.amount:
            raise HTTPException(409,"Недостаточно предложений других фермеров")
        chosen=market_allocation.allocate(rows,q.amount)
        cost=sum(row["price"]*n for row,n in chosen)
        if q.expected_cost!=cost:raise HTTPException(409,"Цена изменилась. Обновите предложение")
        if cost>p["coins"]:raise HTTPException(400,"Недостаточно монет")
        for seller_id in sorted({row["seller"] for row,n in chosen}):
            if not c.execute("SELECT id FROM players WHERE id=%s FOR UPDATE",(seller_id,)).fetchone():
                raise HTTPException(409,"Продавец больше не доступен")
            refund=c.execute("""SELECT 1 FROM stars_refund_intents i
                JOIN star_orders o ON o.id=i.order_id WHERE o.player_id=%s
                AND i.status IN ('calling','needs_review') LIMIT 1""",(seller_id,)).fetchone()
            if refund:raise HTTPException(409,"Продавец временно недоступен")
        # Use the existing farm-market provenance split. City products are
        # intentionally *not* eligible for earned-withdrawal credits in v1.
        sources=farm_wallet.balances(c,p)
        shares=farm_wallet.split_market_sources([(r["id"],r["price"]*n) for r,n in chosen],sources,cost)
        c.execute("UPDATE players SET coins=coins-%s WHERE id=%s",(cost,p["id"]))
        for row,n in chosen:
            c.execute("UPDATE market SET quantity=quantity-%s WHERE id=%s",(n,row["id"]))
            receipt=row["price"]*n
            ad_row=c.execute("SELECT quantity FROM farm_ad_listings WHERE id=%s FOR UPDATE",(row["id"],)).fetchone()
            tagged=min(n,ad_row["quantity"]) if ad_row else 0
            if tagged:c.execute("UPDATE farm_ad_listings SET quantity=quantity-%s WHERE id=%s",(tagged,row["id"]))
            c.execute("UPDATE players SET coins=coins+%s WHERE id=%s",(receipt,row["seller"]))
            log_id=uuid.uuid4().hex
            parts=ad_inventory.restricted_receipt(shares[row["id"]],tagged*row["price"])
            c.execute("INSERT INTO money_log VALUES(%s,%s,'market_sale',%s,%s,%s)",
                (log_id,row["seller"],receipt,q.item+" x"+str(n),time.time()))
            c.execute("INSERT INTO farm_money_sources VALUES(%s,%s,%s,%s)",
                (log_id,parts["bonus"],parts["purchased"],parts["earned"]))
            seller=c.execute("SELECT * FROM players WHERE id=%s",(row["seller"],)).fetchone()
            if ad_inventory.active(seller):
                ad_inventory.credit(c,log_id,tagged*row["price"])
            c.execute("""INSERT INTO market_trade_audit(id,buyer_id,seller_id,item,quantity,coins,created)
                VALUES(%s,%s,%s,%s,%s,%s,%s)""",
                (uuid.uuid4().hex,p["id"],row["seller"],q.item,n,receipt,time.time()))
        c.execute("INSERT INTO money_log VALUES(%s,%s,'market_buy',%s,%s,%s)",
                  (uuid.uuid4().hex,p["id"],-cost,q.item+" x"+str(q.amount),time.time()))
        c.execute("""INSERT INTO city_stock(player_id,item,quantity) VALUES(%s,%s,%s)
            ON CONFLICT(player_id,item) DO UPDATE SET quantity=city_stock.quantity+EXCLUDED.quantity""",
            (p["id"],q.item,q.amount))
        result={"ok":True,"spent":cost,"item":q.item,"quantity":q.amount}
        _finish_request(c,q,result)
    return result

@router.post("/produce")
def produce(q:Action,authorization:str=Header(default="")):
    recipe=RECIPES.get(q.item)
    if not recipe:raise HTTPException(400,"Неизвестный рецепт")
    _amount(q.amount,20)
    with _db() as c:
        p=_auth(c,authorization,True)
        if q.request_id:
            previous=_request(c,q,p["id"],"produce")
            if previous is not None:return previous
        opened=c.execute("SELECT 1 FROM city_businesses WHERE player_id=%s AND kind=%s",
                         (p["id"],recipe["business"])).fetchone()
        if not opened:raise HTTPException(403,"Сначала откройте предприятие")
        for item,qty in recipe["needs"].items():
            changed=c.execute("""UPDATE city_stock SET quantity=quantity-%s
                WHERE player_id=%s AND item=%s AND quantity>=%s RETURNING quantity""",
                (qty*q.amount,p["id"],item,qty*q.amount)).fetchone()
            if not changed:raise HTTPException(409,"Недостаточно сырья: "+item)
        for item,qty in recipe.get("needs_products",{}).items():
            changed=c.execute("""UPDATE city_products SET quantity=quantity-%s
                WHERE player_id=%s AND item=%s AND quantity>=%s RETURNING quantity""",
                (qty*q.amount,p["id"],item,qty*q.amount)).fetchone()
            if not changed:raise HTTPException(409,"Недостаточно готовых ингредиентов: "+RECIPES[item]["name"])
        ready=time.time()+recipe["seconds"]*q.amount
        c.execute("INSERT INTO city_jobs VALUES(%s,%s,%s,%s,%s)",
                  (uuid.uuid4().hex,p["id"],q.item,q.amount,ready))
        result={"ok":True,"ready_at":ready}
        if q.request_id:_finish_request(c,q,result)
    return result

@router.post("/list-product")
def list_product(q:Action,authorization:str=Header(default="")):
    if q.item not in RECIPES:raise HTTPException(400,"Неизвестный товар")
    _amount(q.amount,500)
    _amount(q.price,100000)
    with _db() as c:
        p=_auth(c,authorization,True)
        _settle(c,p["id"])
        if q.request_id:
            previous=_request(c,q,p["id"],"list_product:"+str(q.price))
            if previous is not None:return previous
        updated=c.execute("""UPDATE city_products SET quantity=quantity-%s
            WHERE player_id=%s AND item=%s AND quantity>=%s RETURNING quantity""",
            (q.amount,p["id"],q.item,q.amount)).fetchone()
        if not updated:raise HTTPException(409,"Недостаточно продукции")
        listing_id=uuid.uuid4().hex
        c.execute("INSERT INTO city_listings VALUES(%s,%s,%s,%s,%s,%s)",
                  (listing_id,p["id"],q.item,q.amount,q.price,time.time()))
        result={"ok":True,"listing_id":listing_id}
        if q.request_id:_finish_request(c,q,result)
    return result

@router.post("/cancel-product")
def cancel_product(q:Action,authorization:str=Header(default="")):
    if len(q.listing_id)!=32 or any(ch not in "0123456789abcdef" for ch in q.listing_id):
        raise HTTPException(400,"Неверное объявление")
    with _db() as c:
        c.execute("SELECT pg_advisory_xact_lock(1984533)")
        p=_auth(c,authorization,True)
        row=c.execute("SELECT * FROM city_listings WHERE id=%s AND seller=%s FOR UPDATE",
            (q.listing_id,p["id"])).fetchone()
        if not row or row["quantity"]<=0:raise HTTPException(404,"Активный лот не найден")
        c.execute("UPDATE city_listings SET quantity=0 WHERE id=%s",(q.listing_id,))
        c.execute("""INSERT INTO city_products(player_id,item,quantity) VALUES(%s,%s,%s)
            ON CONFLICT(player_id,item) DO UPDATE SET quantity=city_products.quantity+EXCLUDED.quantity""",
            (p["id"],row["item"],row["quantity"]))
    return {"ok":True,"returned":row["quantity"]}

@router.post("/buy-product")
def buy_product(q:Action,authorization:str=Header(default="")):
    if q.item not in RECIPES:raise HTTPException(400,"Неизвестный товар")
    _amount(q.amount,500)
    with _db() as c:
        c.execute("SELECT pg_advisory_xact_lock(1984533)")
        p=_auth(c,authorization,True)
        previous=_request(c,q,p["id"],"buy_product")
        if previous is not None:return previous
        rows=c.execute("""SELECT * FROM city_listings WHERE item=%s AND seller<>%s
            AND quantity>0 ORDER BY price,id FOR UPDATE""",(q.item,p["id"])).fetchall()
        if sum(int(row["quantity"]) for row in rows)<q.amount:
            raise HTTPException(409,"Недостаточно готовых товаров на рынке")
        chosen=market_allocation.allocate(rows,q.amount)
        cost=sum(row["price"]*n for row,n in chosen)
        if q.expected_cost!=cost:raise HTTPException(409,"Цена изменилась. Обновите предложение")
        if p["coins"]<cost:raise HTTPException(409,"Недостаточно монет")
        for seller in sorted({row["seller"] for row,n in chosen}):
            if not c.execute("SELECT id FROM players WHERE id=%s FOR UPDATE",(seller,)).fetchone():
                raise HTTPException(409,"Продавец недоступен")
            refund=c.execute("""SELECT 1 FROM stars_refund_intents i
                JOIN star_orders o ON o.id=i.order_id
                WHERE o.player_id=%s AND i.status IN ('calling','needs_review') LIMIT 1""",
                (seller,)).fetchone()
            if refund:raise HTTPException(409,"Продавец временно недоступен: проверка возврата Stars")
        c.execute("UPDATE players SET coins=coins-%s WHERE id=%s",(cost,p["id"]))
        for row,n in chosen:
            c.execute("UPDATE city_listings SET quantity=quantity-%s WHERE id=%s",(n,row["id"]))
            receipt=row["price"]*n
            c.execute("UPDATE players SET coins=coins+%s WHERE id=%s",(receipt,row["seller"]))
            log_id=uuid.uuid4().hex
            # City MVP provenance is conservative: no newly withdrawable coin
            # is ever created by product transformation or NPC sales.
            c.execute("INSERT INTO money_log VALUES(%s,%s,'city_product_sale',%s,%s,%s)",
                      (log_id,row["seller"],receipt,q.item+" x"+str(n),time.time()))
            c.execute("INSERT INTO farm_money_sources VALUES(%s,%s,0,0)",(log_id,receipt))
            c.execute("INSERT INTO city_receipts VALUES(%s,%s,%s,%s,%s,%s,%s)",
                      (uuid.uuid4().hex,p["id"],row["seller"],q.item,n,receipt,time.time()))
        c.execute("INSERT INTO money_log VALUES(%s,%s,'city_product_buy',%s,%s,%s)",
                  (uuid.uuid4().hex,p["id"],-cost,q.item+" x"+str(q.amount),time.time()))
        c.execute("""INSERT INTO city_products(player_id,item,quantity) VALUES(%s,%s,%s)
            ON CONFLICT(player_id,item) DO UPDATE SET quantity=city_products.quantity+EXCLUDED.quantity""",
            (p["id"],q.item,q.amount))
        result={"ok":True,"spent":cost}
        _finish_request(c,q,result)
    return result

@router.post("/fulfill-order")
def fulfill_order(q:Action,authorization:str=Header(default="")):
    if q.item not in ("breakfast","lunch","comfort","dinner","home"):
        raise HTTPException(400,"Неизвестный заказ")
    with _db() as c:
        p=_auth(c,authorization,True)
        if q.request_id:
            previous=_request(c,q,p["id"],"fulfill_order")
            if previous is not None:return previous
        _settle(c,p["id"])
        order=next(x for x in daily_orders(c,p["id"]) if x["id"]==q.item)
        if order["done"]:raise HTTPException(409,"Сегодня этот заказ уже выполнен")
        changed=c.execute("""UPDATE city_products SET quantity=quantity-%s
            WHERE player_id=%s AND item=%s AND quantity>=%s RETURNING quantity""",
            (order["quantity"],p["id"],order["recipe"],order["quantity"])).fetchone()
        if not changed:raise HTTPException(409,"Нужен товар: "+RECIPES[order["recipe"]]["name"])
        day=time.strftime("%Y-%m-%d",time.gmtime())
        c.execute("INSERT INTO city_daily_orders VALUES(%s,%s,%s,%s)",
            (p["id"],day,q.item,time.time()))
        c.execute("""INSERT INTO city_reputation(player_id,points) VALUES(%s,%s)
            ON CONFLICT(player_id) DO UPDATE SET points=city_reputation.points+EXCLUDED.points""",
            (p["id"],order["reputation"]))
        result={"ok":True,"reputation_earned":order["reputation"]}
        if q.request_id:_finish_request(c,q,result)
    return result

@router.post("/consume")
def consume(q:Action,authorization:str=Header(default="")):
    """Resident/character use: city reputation only, never system coin emissions."""
    if q.item not in RECIPES:raise HTTPException(400,"Неизвестный товар")
    _amount(q.amount,100)
    with _db() as c:
        p=_auth(c,authorization,True)
        if q.request_id:
            previous=_request(c,q,p["id"],"consume")
            if previous is not None:return previous
        _settle(c,p["id"])
        row=c.execute("""UPDATE city_products SET quantity=quantity-%s
            WHERE player_id=%s AND item=%s AND quantity>=%s RETURNING quantity""",
            (q.amount,p["id"],q.item,q.amount)).fetchone()
        if not row:raise HTTPException(409,"Недостаточно товаров")
        c.execute("""INSERT INTO city_reputation(player_id,points) VALUES(%s,%s)
            ON CONFLICT(player_id) DO UPDATE SET points=city_reputation.points+EXCLUDED.points""",
            (p["id"],q.amount*5))
        result={"ok":True,"reputation_earned":q.amount*5}
        if q.request_id:_finish_request(c,q,result)
    return result
