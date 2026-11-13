"""City production, inventory and market operations over the shared farm wallet."""
from __future__ import annotations
import time
import uuid
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
import market_allocation
import farm_wallet
import ad_inventory
import city_nutrition
from production import GRAIN_PRICE
from production_v4 import MILK_PRICE, WOOL_PRICE

# Farm market prices are the only baseline; city products are priced from inputs.
FARM_REFERENCE_PRICES = {"eggs": 1, "grain": GRAIN_PRICE, "milk": MILK_PRICE,
                         "feathers": 5, "wool": WOOL_PRICE}

def recipe_price_guides():
    """Suggested prices, not enforced sale prices or guaranteed profits."""
    guides = {}
    for key, recipe in RECIPES.items():
        raw = sum(FARM_REFERENCE_PRICES[item] * qty for item, qty in recipe["needs"].items())
        # Nested products use their own suggested unit cost (no circular recipes).
        nested = sum(guides[item]["suggested_unit_price"] * qty
                     for item, qty in recipe.get("needs_products", {}).items())
        cost = raw + nested
        units = recipe["output"]
        suggested = (cost * 125 + 100 * units - 1) // (100 * units)
        guides[key] = {"batch_input_cost": cost, "batch_output": units,
                       "suggested_unit_price": max(1, suggested),
                       "batch_seconds": recipe["seconds"]}
    return guides


def business_investment_guides(batches_per_day=8, sell_through=0.8):
    """Indicative 20-30 day investments, not charges or guaranteed returns.

    Assumes each business concentrates on its first recipe. Players can freely
    select other recipes and market prices; unsold inventory earns nothing.
    """
    if batches_per_day <= 0 or not 0 <= sell_through <= 1:
        raise ValueError("Invalid business assumptions")
    guides = recipe_price_guides()
    result = {}
    for kind in BUSINESSES:
        recipe_key = next(key for key, spec in RECIPES.items()
                          if spec["business"] == kind)
        spec = RECIPES[recipe_key]
        quote = guides[recipe_key]
        margin = (quote["suggested_unit_price"] * spec["output"] * sell_through
                  - quote["batch_input_cost"])
        daily = max(0, margin * batches_per_day)
        result[kind] = {
            "reference_recipe": recipe_key,
            "assumed_batches_per_day": batches_per_day,
            "assumed_sell_through": sell_through,
            "estimated_daily_profit": round(daily, 2),
            "target_investment_20_days": round(daily * 20),
            "target_investment_30_days": round(daily * 30),
            "pricing_is_advisory": True,
        }
    return result


def food_value_guides():
    """Break-even farm output at zero fullness; avoids claiming universal ROI.

    A meal's bonus is the integral of fullness over time. Multiple meals,
    existing fullness and idle farms change the actual value.
    """
    prices = recipe_price_guides()
    guides = {}
    for item, restore in city_nutrition.FOOD_RESTORE.items():
        # Fullness decays linearly at five percentage points per hour.
        equivalent_extra_hours = (restore / city_nutrition.DECAY_PER_HOUR) * restore / 200 * city_nutrition.MAX_FOOD_BONUS
        price = prices[item]["suggested_unit_price"]
        guides[item] = {
            "suggested_price": price,
            "restore_fullness": restore,
            "bonus_equivalent_hours_from_empty": round(equivalent_extra_hours, 3),
            "break_even_farm_daily_output_coins": round(
                24 * price / equivalent_extra_hours, 2),
            "estimate_only": True,
        }
    return guides

# Capacity is tied to paid business upgrades, not unlimited instant jobs.
# The initial bakery remains free to avoid locking new players out.
BUSINESS_UPGRADE_BASE = {"bakery": 120, "restaurant": 180, "dairy": 240,
                         "atelier": 240, "store": 200}
MAX_BUSINESS_LEVEL = 10

def business_upgrade_cost(kind, current_level):
    if kind not in BUSINESS_UPGRADE_BASE or not 1 <= current_level < MAX_BUSINESS_LEVEL:
        raise ValueError("No upgrade available")
    return BUSINESS_UPGRADE_BASE[kind] * current_level

def business_batch_limit(level):
    return min(20, max(1, 2 * level))


router = APIRouter(prefix="/api/city", tags=["city"])
INGREDIENTS = ("eggs", "grain", "milk", "feathers", "wool")
MATERIALS = {"feathers", "wool"}
ANIMALS = ("chickens","geese","cows","sheep")
RECIPES = {
    "pancakes": {"name": "Блины", "business": "bakery", "needs": {"eggs": 4, "grain": 3, "milk": 1}, "output": 2, "seconds": 2400},
    "pie": {"name": "Пирог", "business": "bakery", "needs": {"eggs": 8, "grain": 5}, "output": 1, "seconds": 2700},
    "omelet": {"name": "Омлет", "business": "restaurant", "needs": {"eggs": 5, "milk": 1}, "output": 1, "seconds": 1800},
    "cheese": {"name": "Сыр", "business": "dairy", "needs": {"milk": 5}, "output": 2, "seconds": 2700},
    "yogurt": {"name": "Йогурт", "business": "dairy", "needs": {"milk": 3}, "output": 2, "seconds": 2100},
    "bread": {"name": "Хлеб", "business": "bakery", "needs": {"grain": 5}, "output": 2, "seconds": 1800},
    "pillow": {"name": "Подушка", "business": "atelier", "needs": {"feathers": 4, "wool": 2}, "output": 1, "seconds": 3600},
    "scarf": {"name": "Шарф", "business": "atelier", "needs": {"wool": 6}, "output": 1, "seconds": 3600},
    # Second-stage recipes give other businesses a reason to buy goods made
    # by bakers, dairies and textile workshops rather than only raw resources.
    "breakfast_set": {"name": "Фирменный завтрак", "business": "restaurant",
        "needs": {"eggs": 2}, "needs_products": {"bread": 1, "cheese": 1}, "output": 1, "seconds": 4500},
    "dessert_box": {"name": "Десертный набор", "business": "restaurant",
        "needs": {"milk": 2}, "needs_products": {"pancakes": 2, "pie": 1}, "output": 1, "seconds": 5400},
    "home_set": {"name": "Домашний уют", "business": "store",
        "needs": {}, "needs_products": {"pillow": 1, "scarf": 1}, "output": 1, "seconds": 6000},
    "lunch_box": {"name": "Обед с собой", "business": "store",
        "needs": {}, "needs_products": {"omelet": 1, "bread": 1}, "output": 1, "seconds": 4200},
}
BUSINESSES = {
    "bakery": {"name": "Пекарня", "emoji": "🥐", "open_cost": 0, "min_reputation": 0},
    "restaurant": {"name": "Ресторан", "emoji": "🍳", "open_cost": 0, "min_reputation": 20},
    "dairy": {"name": "Молочная", "emoji": "🥛", "open_cost": 0, "feather_cost": 5, "min_reputation": 50},
    "atelier": {"name": "Ателье", "emoji": "🧶", "open_cost": 0, "feather_cost": 12, "min_reputation": 100},
    "store": {"name": "Магазин", "emoji": "🛒", "open_cost": 0, "min_reputation": 160},
}

_db = _person = _advance = None

def setup(db, person, advance):
    global _db, _person, _advance
    _db, _person, _advance = db, person, advance
    return router

def initialize(c):
    city_nutrition.initialize(c)
    # One-time 1000-coin launch promo. Only the SHA-256 digest is persisted.
    # Redemption is handled by the existing farm promo endpoint and is
    # non-withdrawable by virtue of its promo_reward provenance.
    c.execute("""INSERT INTO promo_codes(code_hash,amount)
        VALUES(%s,1000) ON CONFLICT(code_hash) DO NOTHING""",
        ("045f21487f82922ac415acebd84bc553a9b44697ffbf81a09af5160914489013",))
    c.execute("""CREATE TABLE IF NOT EXISTS city_businesses(
        player_id text NOT NULL, kind text NOT NULL, level integer NOT NULL DEFAULT 1,
        opened double precision NOT NULL, PRIMARY KEY(player_id,kind))""")
    c.execute("""CREATE TABLE IF NOT EXISTS city_stock(
        player_id text NOT NULL, item text NOT NULL, quantity bigint NOT NULL DEFAULT 0
        CHECK(quantity>=0), PRIMARY KEY(player_id,item))""")
    c.execute("""CREATE TABLE IF NOT EXISTS city_products(
        player_id text NOT NULL, item text NOT NULL, quantity bigint NOT NULL DEFAULT 0
        CHECK(quantity>=0), PRIMARY KEY(player_id,item))""")
    c.execute("""CREATE TABLE IF NOT EXISTS farm_food(
        player_id text NOT NULL, item text NOT NULL, quantity bigint NOT NULL
        CHECK(quantity>=0), PRIMARY KEY(player_id,item))""")
    c.execute("""CREATE TABLE IF NOT EXISTS city_production_history(
        id text PRIMARY KEY, player_id text NOT NULL, recipe text NOT NULL,
        quantity integer NOT NULL CHECK(quantity>0),
        started_at double precision NOT NULL, ready_at double precision NOT NULL)""")
    c.execute("CREATE INDEX IF NOT EXISTS city_production_history_player ON city_production_history(player_id,started_at DESC)")
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
    c.execute("CREATE INDEX IF NOT EXISTS city_receipts_buyer ON city_receipts(buyer)")
    c.execute("CREATE INDEX IF NOT EXISTS city_receipts_seller ON city_receipts(seller)")
    c.execute("""CREATE TABLE IF NOT EXISTS city_raw_receipts(
        id text PRIMARY KEY, buyer text NOT NULL, seller text NOT NULL, item text NOT NULL,
        quantity integer NOT NULL CHECK(quantity>0), coins integer NOT NULL CHECK(coins>=0),
        created double precision NOT NULL)""")
    c.execute("CREATE INDEX IF NOT EXISTS city_raw_receipts_buyer ON city_raw_receipts(buyer)")
    c.execute("CREATE INDEX IF NOT EXISTS city_raw_receipts_created_item ON city_raw_receipts(created,item)")
    c.execute("""CREATE TABLE IF NOT EXISTS city_requests(
        id text PRIMARY KEY, player_id text NOT NULL, action text NOT NULL,
        item text NOT NULL, quantity integer NOT NULL, result jsonb)""")
    c.execute("""CREATE TABLE IF NOT EXISTS city_daily_orders(
        player_id text NOT NULL, day text NOT NULL, order_id text NOT NULL,
        completed_at double precision NOT NULL,
        PRIMARY KEY(player_id,day,order_id))""")
    c.execute("""CREATE TABLE IF NOT EXISTS city_reputation(
        player_id text PRIMARY KEY, points bigint NOT NULL DEFAULT 0 CHECK(points>=0))""")

    c.execute("""CREATE TABLE IF NOT EXISTS city_progress_log(
        player_id text NOT NULL, source text NOT NULL, kind text NOT NULL,
        created double precision NOT NULL, xp integer NOT NULL CHECK(xp>=0),
        reputation integer NOT NULL DEFAULT 0 CHECK(reputation>=0),
        read boolean NOT NULL DEFAULT false, PRIMARY KEY(player_id,source))""")
    c.execute("""CREATE INDEX IF NOT EXISTS city_progress_recent
        ON city_progress_log(player_id,created DESC)""")


CITY_XP_THRESHOLDS = (0, 50, 150, 300, 550, 900, 1400, 2100, 3000, 4200,
                      5800, 8000, 10500, 13500, 17000)


def _progress_event(c, pid, source, kind, now, xp, reputation=0):
    c.execute("""INSERT INTO city_progress_log(player_id,source,kind,created,xp,reputation)
        VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(player_id,source) DO NOTHING""",
        (pid, source, kind, now, xp, reputation))


def _progress_summary(c, pid):
    stats = c.execute("""SELECT COALESCE(SUM(xp),0) AS xp,
        COUNT(*) FILTER (WHERE NOT read) AS unread
        FROM city_progress_log WHERE player_id=%s""", (pid,)).fetchone()
    orders = c.execute("SELECT COUNT(*) AS n FROM city_daily_orders WHERE player_id=%s",
                       (pid,)).fetchone()["n"]
    xp = int(stats["xp"])
    level = sum(xp >= threshold for threshold in CITY_XP_THRESHOLDS)
    return {"xp": xp, "level": level, "level_xp": CITY_XP_THRESHOLDS[level-1],
            "next_xp": CITY_XP_THRESHOLDS[level] if level < len(CITY_XP_THRESHOLDS) else None,
            "orders": orders, "unread": stats["unread"]}


ACHIEVEMENTS = (
    ("entrepreneur", "Первый предприниматель", "Открыть предприятие", 1, 20),
    ("baker", "Пекарь", "Произвести хлеб", 100, 40),
    ("merchant", "Торговец", "Продать готовые товары другим игрокам", 100, 40),
    ("resident", "Любимец жителей", "Выполнить заказы жителей", 50, 60),
    ("industrialist", "Промышленник", "Улучшить предприятие до уровня", 5, 60),
    ("tycoon", "Магнат города", "Открыть предприятия", len(BUSINESSES), 100),
)


def _achievements(c, pid, now):
    counts = c.execute("""SELECT
        (SELECT COUNT(*) FROM city_businesses WHERE player_id=%(pid)s) AS businesses,
        (SELECT COALESCE(MAX(level),0) FROM city_businesses WHERE player_id=%(pid)s) AS business_level,
        (SELECT COALESCE(SUM(quantity),0) FROM city_production_history
            WHERE player_id=%(pid)s AND recipe='bread' AND ready_at<=%(now)s) AS bread,
        (SELECT COALESCE(SUM(quantity),0) FROM city_receipts
            WHERE seller=%(pid)s AND buyer<>seller) AS sales,
        (SELECT COUNT(*) FROM city_daily_orders WHERE player_id=%(pid)s) AS orders
        """, {"pid": pid, "now": now}).fetchone()
    values = (counts["businesses"], counts["bread"], counts["sales"], counts["orders"],
              counts["business_level"], counts["businesses"])
    achieved = []
    for (key, name, description, goal, xp), value in zip(ACHIEVEMENTS, values):
        done = value >= goal
        if done:
            _progress_event(c, pid, "achievement:" + key, "achievement", now, xp)
        achieved.append({"name": name, "description": description, "goal": goal,
                         "value": value, "xp": xp, "done": done})
    return achieved


@router.get("/progress-log")
def progress_log(authorization: str = Header(default="")):
    with _db() as c:
        pid = _auth(c, authorization)["id"]
        return c.execute("""SELECT source,kind,created,xp,reputation,read
            FROM city_progress_log WHERE player_id=%s
            ORDER BY created DESC,source LIMIT 100""", (pid,)).fetchall()


@router.post("/read-progress-log")
def read_progress_log(sources: list[str], authorization: str = Header(default="")):
    if len(sources) > 100 or any(len(source) > 160 for source in sources):
        raise HTTPException(400, "Слишком много уведомлений")
    with _db() as c:
        pid = _auth(c, authorization)["id"]
        c.execute("""UPDATE city_progress_log SET read=true
            WHERE player_id=%s AND source=ANY(%s) AND NOT read""", (pid, sources))
    return {"ok": True}


def daily_orders(c,pid,now=None):
    now=time.time() if now is None else now
    day=time.strftime("%Y-%m-%d",time.gmtime(now))
    rotation=int(now//86400)
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
        "quantity":1,"reputation":reward,"done":key in finished,"day":day}
        for key,options,reward in lineup]

def _auth(c, authorization, write=False):
    return _person(c, authorization, write)

def _counts(c, table, pid):
    return {r["item"]: int(r["quantity"]) for r in c.execute(
        "SELECT item,quantity FROM "+table+" WHERE player_id=%s AND quantity>0", (pid,)).fetchall()}

def _settle(c, pid):
    jobs=c.execute("SELECT * FROM city_jobs WHERE player_id=%s AND ready_at<=%s ORDER BY ready_at,id FOR UPDATE",(pid,time.time())).fetchall()
    for job in jobs:
        recipe=RECIPES[job["recipe"]]
        c.execute("""INSERT INTO city_products(player_id,item,quantity) VALUES(%s,%s,%s)
            ON CONFLICT(player_id,item) DO UPDATE
            SET quantity=city_products.quantity+EXCLUDED.quantity""",
            (pid,job["recipe"],job["quantity"]*recipe["output"]))
        ready = job["ready_at"]
        _progress_event(c, pid, "production-day:" + str(int(ready // 86400)),
                        "production_xp", ready, 5)
        _progress_event(c, pid, "production:" + job["id"], "production", ready, 0)
        c.execute("DELETE FROM city_jobs WHERE id=%s",(job["id"],))
    return len(jobs)

class Action(BaseModel):
    item: str = ""
    amount: int = 1
    price: int = 1
    request_id: str = ""
    expected_cost: int = -1
    listing_id: str = ""
    destination: str = "city"
    order_day: str = ""

def _request(c, q, pid, action):
    # Same transaction-level market lock as the farm. An identical retry key
    # returns its recorded result without repeating any resource or coin changes.
    key=q.request_id
    if not isinstance(key,str) or len(key)!=32 or any(ch not in "0123456789abcdef" for ch in key):
        raise HTTPException(400,"Операция требует действительный ключ повтора")
    created=c.execute("""INSERT INTO city_requests VALUES(%s,%s,%s,%s,%s,NULL)
        ON CONFLICT(id) DO NOTHING RETURNING id""",(key,pid,action,q.item,q.amount)).fetchone()
    if created:
        return None
    existing=c.execute("SELECT * FROM city_requests WHERE id=%s",(key,)).fetchone()
    if (existing["player_id"],existing["action"],existing["item"],existing["quantity"])!=(pid,action,q.item,q.amount):
        raise HTTPException(409,"Ключ операции уже использован")
    return existing["result"]

def _finish_request(c,q,result):
    from psycopg.types.json import Jsonb
    c.execute("UPDATE city_requests SET result=%s WHERE id=%s",(Jsonb(result),q.request_id))

def _allocation(rows, item, amount, grain_fallback=False):
    from_players=min(amount,sum(int(row["quantity"]) for row in rows))
    system_quantity=amount-from_players
    if system_quantity and not (grain_fallback and item=="grain"):
        raise HTTPException(409,"На рынке недостаточно предложений")
    chosen=market_allocation.allocate(rows,from_players) if from_players else []
    cost=sum(row["price"]*quantity for row,quantity in chosen)+system_quantity*GRAIN_PRICE
    return chosen,cost,system_quantity


def _quote(c,table,item,pid,n):
    rows=c.execute("SELECT * FROM "+table+" WHERE item=%s AND seller<>%s AND quantity>0 ORDER BY price,id",
        (item,pid)).fetchall()
    chosen,cost,system_quantity=_allocation(rows,item,n,grain_fallback=table=="market")
    return {"ok":True,"item":item,"quantity":n,"cost":cost,
        "sellers":len({row["seller"] for row,_ in chosen}),"system_quantity":system_quantity}


@router.post("/quote-ingredient")
def quote_ingredient(q:Action,authorization:str=Header(default="")):
    if q.item not in INGREDIENTS:raise HTTPException(400,"Неизвестный ингредиент")
    _amount(q.amount,500)
    with _db() as c:
        p=_auth(c,authorization)
        return _quote(c,"market",q.item,p["id"],q.amount)

def _product_purchase(c, item, pid, amount, *, farm, lock=False):
    """All offers, including the buyer's, trade on equal terms."""
    rows=c.execute("""SELECT * FROM city_listings WHERE item=%s AND quantity>0
        ORDER BY price,created,id""" + (" FOR UPDATE" if lock else ""),
        (item,)).fetchall()
    if sum(row["quantity"] for row in rows)<amount:
        raise HTTPException(409,"На рынке недостаточно предложений")
    chosen=market_allocation.allocate(rows,amount)
    cost=sum(row["price"]*quantity for row,quantity in chosen)
    return chosen,[],cost,0


@router.post("/quote-product")
def quote_product(q:Action,authorization:str=Header(default="")):
    if q.item not in RECIPES:raise HTTPException(400,"Неизвестный товар")
    _amount(q.amount,500)
    with _db() as c:
        p=_auth(c,authorization)
        chosen,_,cost,own_quantity=_product_purchase(c,q.item,p["id"],q.amount,
            farm=q.destination=="farm" and q.item in city_nutrition.FOOD_RESTORE)
        return {"ok":True,"item":q.item,"quantity":q.amount,"cost":cost,
            "sellers":len({row["seller"] for row,_ in chosen}),"system_quantity":0,
            "own_quantity":own_quantity}

def _amount(n, maximum=10000):
    if type(n) is not int or n<1 or n>maximum:
        raise HTTPException(400,"Укажите корректное количество")

def _product_catalog(c, pid, items=None):
    rows=c.execute("""SELECT item,COUNT(DISTINCT seller)::int AS sellers,
        SUM(quantity)::bigint AS quantity,MIN(price)::int AS min_price
        FROM city_listings WHERE quantity>0
        AND (%s::text[] IS NULL OR item=ANY(%s::text[]))
        GROUP BY item ORDER BY item""",(items,items)).fetchall()
    return {row["item"]:{"quantity":row["quantity"],"sellers":row["sellers"],
                          "min_price":row["min_price"]} for row in rows}


def _add_product(c, table, pid, item, quantity):
    c.execute(f"""INSERT INTO {table}(player_id,item,quantity) VALUES(%s,%s,%s)
        ON CONFLICT(player_id,item) DO UPDATE SET quantity={table}.quantity+EXCLUDED.quantity""",
        (pid,item,quantity))


@router.get("/farm-goods")
def farm_goods(authorization: str=Header(default="")):
    with _db() as c:
        p=_auth(c,authorization)
        own_offers=c.execute("""SELECT id,item,quantity,price FROM city_listings
            WHERE seller=%s AND quantity>0 ORDER BY created DESC,id""",(p["id"],)).fetchall()
        return {"recipes":RECIPES,"food_restore":city_nutrition.FOOD_RESTORE,
                "my_offers":own_offers,
                "city_catalog":_product_catalog(c,p["id"]),
                "food":_counts(c,"farm_food",p["id"]),
                "city_food":{item:quantity for item,quantity in _counts(c,"city_products",p["id"]).items()
                             if item in city_nutrition.FOOD_RESTORE},
                "nutrition":city_nutrition.status(city_nutrition.get(c,p["id"]))}


@router.get("/state")
def state(authorization: str=Header(default=""), compact: bool=False):
    with _db() as c:
        p=_auth(c,authorization)
        _settle(c,p["id"])
        business_levels={r["kind"]:r["level"] for r in c.execute(
            "SELECT kind,level FROM city_businesses WHERE player_id=%s",(p["id"],)).fetchall()}
        raw_catalog_rows=c.execute("""SELECT item,COUNT(DISTINCT seller)::int AS sellers,
            SUM(quantity)::bigint AS quantity,MIN(price)::int AS min_price
            FROM market WHERE quantity>0 AND seller<>%s AND item=ANY(%s)
            GROUP BY item ORDER BY item""",(p["id"],list(INGREDIENTS+ANIMALS))).fetchall()
        market_catalog={r["item"]:{"quantity":r["quantity"],"sellers":r["sellers"],
                               "min_price":r["min_price"]} for r in raw_catalog_rows}
        my_city_offers=c.execute("""SELECT id,item,quantity,price FROM city_listings
            WHERE seller=%s AND quantity>0 ORDER BY created DESC""",(p["id"],)).fetchall()
        city_catalog=_product_catalog(c,p["id"])
        jobs=c.execute("SELECT recipe,quantity,ready_at FROM city_jobs WHERE player_id=%s ORDER BY ready_at",(p["id"],)).fetchall()
        rep=c.execute("SELECT points FROM city_reputation WHERE player_id=%s",(p["id"],)).fetchone()
        # City accounting is a report of transfers between players, not a
        # second balance. A purchase in either game changes players.coins once.
        city_ingredient_spend=c.execute("""SELECT COALESCE(SUM(coins),0)::bigint AS coins
            FROM city_raw_receipts WHERE buyer=%s""",(p["id"],)).fetchone()["coins"]
        city_goods_purchases=c.execute("""SELECT COALESCE(SUM(coins),0)::bigint AS coins
            FROM city_receipts WHERE buyer=%s""",(p["id"],)).fetchone()["coins"]
        city_goods_sales=c.execute("""SELECT COALESCE(SUM(coins),0)::bigint AS coins
            FROM city_receipts WHERE seller=%s""",(p["id"],)).fetchone()["coins"]
        city_cashflow={
            "ingredient_spend":int(city_ingredient_spend),
            "goods_purchases":int(city_goods_purchases),
            "goods_sales":int(city_goods_sales),
            "net":int(city_goods_sales)-int(city_ingredient_spend)-int(city_goods_purchases),
            "label":"Денежный поток города, не чистая прибыль",
        }
        now=time.time()
        snapshot={"system_grain_price":GRAIN_PRICE,"name":p["name"],"coins":p["coins"],"businesses":list(business_levels),
            "business_levels":business_levels,
            "business_upgrade_prices":{kind:business_upgrade_cost(kind,level)
                for kind,level in business_levels.items() if level<MAX_BUSINESS_LEVEL},
            "business_batch_limits":{kind:business_batch_limit(level)
                for kind,level in business_levels.items()},
            "raw_catalog":{item:offer for item,offer in market_catalog.items() if item in INGREDIENTS},
            "animal_catalog":{item:offer for item,offer in market_catalog.items() if item in ANIMALS},
            "city_catalog":city_catalog,
            "food_items":list(city_nutrition.FOOD_RESTORE),"materials":sorted(MATERIALS),
            "wallet_mode":"shared_farm_city","cashflow":city_cashflow,
            "stock":_counts(c,"city_stock",p["id"]),
            "farm_feathers":int(p.get("feathers",0)),
            "products":_counts(c,"city_products",p["id"]),
            "recipes":RECIPES,"price_guides":recipe_price_guides(),
            "farm_reference_prices":FARM_REFERENCE_PRICES,
            "business_investment_guides":business_investment_guides(),
            "food_value_guides":food_value_guides(),
            "business_catalog":BUSINESSES,
            "my_city_offers":my_city_offers,"jobs":jobs,"now":now,
            "resident_orders":daily_orders(c,p["id"],now),
            "reputation":int(rep["points"]) if rep else 0}
        snapshot["achievements"] = _achievements(c, p["id"], now)
        snapshot["progress"] = _progress_summary(c, p["id"])
        if compact:
            return snapshot

        # The previous client may still be open during a rolling deployment.
        today_start=now-now%86400
        snapshot.update(
            nutrition=city_nutrition.status(city_nutrition.get(c,p["id"])),
            farm_offers=c.execute("""SELECT l.id,l.item,l.price,l.quantity,p.name AS seller
                FROM market l JOIN players p ON p.id=l.seller
                WHERE l.quantity>0 AND l.seller<>%s AND l.item=ANY(%s)
                ORDER BY l.item,l.price,l.id LIMIT 70""",(p["id"],list(INGREDIENTS))).fetchall(),
            city_offers=c.execute("""SELECT l.id,l.item,l.price,l.quantity,p.name AS seller
                FROM city_listings l JOIN players p ON p.id=l.seller
                WHERE l.quantity>0 AND l.seller<>%s
                ORDER BY l.item,l.price,l.id LIMIT 70""",(p["id"],)).fetchall(),
            farm_market_totals={r["item"]:r["n"] for r in c.execute("""SELECT item,SUM(quantity) AS n
                FROM market WHERE quantity>0 AND item=ANY(%s) GROUP BY item""",(list(INGREDIENTS),)).fetchall()},
            city_demand_today={r["item"]:r["n"] for r in c.execute("""SELECT item,SUM(quantity) AS n
                FROM city_raw_receipts WHERE created>=%s GROUP BY item""",(today_start,)).fetchall()})
        city_daily=c.execute("""SELECT COUNT(*) AS n,COALESCE(SUM(coins),0) AS coins
            FROM city_receipts WHERE created>=%s""",(today_start,)).fetchone()
        snapshot.update(finished_goods_sales_today=city_daily["n"],finished_goods_turnover_today=city_daily["coins"])
        return snapshot

@router.post("/open")
def open_business(q:Action, authorization: str=Header(default="")):
    if q.item not in BUSINESSES:raise HTTPException(400,"Неизвестное предприятие")
    with _db() as c:
        p=_auth(c,authorization,True)
        reputation=c.execute("SELECT points FROM city_reputation WHERE player_id=%s",(p["id"],)).fetchone()
        if (int(reputation["points"]) if reputation else 0)<BUSINESSES[q.item]["min_reputation"]:
            raise HTTPException(403,"Нужно больше репутации для открытия бизнеса")
        if c.execute("SELECT 1 FROM city_businesses WHERE player_id=%s AND kind=%s",(p["id"],q.item)).fetchone():
            return {"ok":True,"already_open":True}
        required=int(BUSINESSES[q.item].get("feather_cost",0))
        if required:
            # The farm owns the feathers. Spend them automatically when opening,
            # rather than creating a second transferable inventory.
            paid=c.execute("""UPDATE players SET feathers=feathers-%s
                WHERE id=%s AND feathers>=%s RETURNING feathers""",
                (required,p["id"],required)).fetchone()
            if not paid:raise HTTPException(409,f"Для открытия нужно {required} перьев на ферме")
        c.execute("INSERT INTO city_businesses VALUES(%s,%s,1,%s)",(p["id"],q.item,time.time()))
    return {"ok":True}

@router.post("/upgrade-business")
def upgrade_business(q:Action, authorization:str=Header(default="")):
    if q.item not in BUSINESSES:
        raise HTTPException(400,"Неизвестное предприятие")
    with _db() as c:
        p=_auth(c,authorization,True)
        c.execute("SELECT pg_advisory_xact_lock(1984533)")
        previous=_request(c,q,p["id"],"upgrade_business")
        if previous is not None:return previous
        row=c.execute("SELECT level FROM city_businesses WHERE player_id=%s AND kind=%s FOR UPDATE",
                      (p["id"],q.item)).fetchone()
        if not row:raise HTTPException(403,"Сначала откройте предприятие")
        level=int(row["level"])
        if level>=MAX_BUSINESS_LEVEL:raise HTTPException(409,"Достигнут максимальный уровень")
        cost=business_upgrade_cost(q.item,level)
        if q.expected_cost != -1 and q.expected_cost != cost:
            raise HTTPException(409,"Стоимость улучшения изменилась. Откройте предприятие заново")
        paid=c.execute("UPDATE players SET coins=coins-%s WHERE id=%s AND coins>=%s RETURNING coins",
                       (cost,p["id"],cost)).fetchone()
        if not paid:raise HTTPException(400,"Недостаточно монет")
        c.execute("UPDATE city_businesses SET level=level+1 WHERE player_id=%s AND kind=%s",
                  (p["id"],q.item))
        c.execute("UPDATE economy SET treasury=treasury+%s WHERE id=1",(cost,))
        now = time.time()
        _progress_event(c, p["id"], "upgrade-day:" + str(int(now // 86400)),
                        "upgrade", now, 15)
        result={"ok":True,"level":level+1,"spent":cost,
                "max_batch":business_batch_limit(level+1)}
        _finish_request(c,q,result)
    return result

@router.post("/buy-ingredient")
def buy_ingredient(q:Action,authorization:str=Header(default="")):
    """Buy market ingredients directly into the city warehouse."""
    if q.item not in INGREDIENTS:raise HTTPException(400,"Этот ресурс нельзя закупать")
    _amount(q.amount,500)
    with _db() as c:
        c.execute("SELECT pg_advisory_xact_lock(1984533)")
        p=_advance(c,_auth(c,authorization,True))
        previous=_request(c,q,p["id"],"buy_ingredient")
        if previous is not None:return previous
        rows=c.execute("""SELECT * FROM market WHERE item=%s AND seller<>%s
            AND quantity>0 ORDER BY price,id FOR UPDATE""",(q.item,p["id"])).fetchall()
        chosen,cost,system_quantity=_allocation(rows,q.item,q.amount,grain_fallback=True)
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
        ad_budget=ad_inventory.balance(c,p)
        receipts=[(row["id"],row["price"]*quantity) for row,quantity in chosen]
        system_cost=system_quantity*GRAIN_PRICE
        if system_cost:
            receipts.append(("__system__",system_cost))
        shares=farm_wallet.split_market_sources(receipts,sources,cost)
        c.execute("UPDATE players SET coins=coins-%s WHERE id=%s",(cost,p["id"]))
        for row,n in chosen:
            c.execute("UPDATE market SET quantity=quantity-%s WHERE id=%s",(n,row["id"]))
            receipt=row["price"]*n
            ad_row=c.execute("SELECT quantity FROM farm_ad_listings WHERE id=%s FOR UPDATE",(row["id"],)).fetchone()
            tagged=min(n,ad_row["quantity"]) if ad_row else 0
            if tagged:c.execute("UPDATE farm_ad_listings SET quantity=quantity-%s WHERE id=%s",(tagged,row["id"]))
            c.execute("UPDATE players SET coins=coins+%s WHERE id=%s",(receipt,row["seller"]))
            log_id=uuid.uuid4().hex
            paid_ad=min(ad_budget,receipt)
            ad_budget-=paid_ad
            restricted=max(paid_ad,tagged*row["price"])
            parts=ad_inventory.restricted_receipt(shares[row["id"]],restricted)
            c.execute("INSERT INTO money_log VALUES(%s,%s,'market_sale',%s,%s,%s)",
                (log_id,row["seller"],receipt,q.item+" x"+str(n),time.time()))
            c.execute("INSERT INTO farm_money_sources VALUES(%s,%s,%s,%s)",
                (log_id,parts["bonus"],parts["purchased"],parts["earned"]))
            seller=c.execute("SELECT * FROM players WHERE id=%s",(row["seller"],)).fetchone()
            if ad_inventory.active(seller):
                ad_inventory.credit(c,log_id,restricted)
            trade_at=time.time()
            c.execute("""INSERT INTO market_trade_audit(id,buyer_id,seller_id,item,quantity,coins,created)
                VALUES(%s,%s,%s,%s,%s,%s,%s)""",
                (uuid.uuid4().hex,p["id"],row["seller"],q.item,n,receipt,trade_at))
            c.execute("""INSERT INTO city_raw_receipts VALUES(%s,%s,%s,%s,%s,%s,%s)""",
                (uuid.uuid4().hex,p["id"],row["seller"],q.item,n,receipt,trade_at))
        if system_cost:
            c.execute("UPDATE economy SET treasury=treasury+%s WHERE id=1",(system_cost,))
        c.execute("INSERT INTO money_log VALUES(%s,%s,'market_buy',%s,%s,%s)",
                  (uuid.uuid4().hex,p["id"],-cost,q.item+" x"+str(q.amount),time.time()))
        c.execute("""INSERT INTO city_stock(player_id,item,quantity) VALUES(%s,%s,%s)
            ON CONFLICT(player_id,item) DO UPDATE SET quantity=city_stock.quantity+EXCLUDED.quantity""",
            (p["id"],q.item,q.amount))
        result={"ok":True,"spent":cost,"item":q.item,"quantity":q.amount,"system_quantity":system_quantity}
        _finish_request(c,q,result)
    return result

@router.post("/produce")
def produce(q:Action,authorization:str=Header(default="")):
    recipe=RECIPES.get(q.item)
    if not recipe:raise HTTPException(400,"Неизвестный рецепт")
    _amount(q.amount,20)
    with _db() as c:
        p=_auth(c,authorization,True)
        c.execute("SELECT pg_advisory_xact_lock(1984533)")
        if q.request_id:
            previous=_request(c,q,p["id"],"produce")
            if previous is not None:return previous
        _settle(c,p["id"])
        opened=c.execute("SELECT level FROM city_businesses WHERE player_id=%s AND kind=%s",
                         (p["id"],recipe["business"])).fetchone()
        if not opened:raise HTTPException(403,"Сначала откройте предприятие")
        if q.amount>business_batch_limit(int(opened["level"])):
            raise HTTPException(409,"Увеличьте уровень предприятия для такой партии")
        # Concurrent production capacity, not merely a per-request batch cap.
        # A single enterprise cannot bypass its level by submitting many jobs.
        now=time.time()
        pending=c.execute("""SELECT COALESCE(SUM(j.quantity),0) AS units
            FROM city_jobs j WHERE j.player_id=%s AND j.ready_at>%s
            AND j.recipe=ANY(%s)""",
            (p["id"],now,[key for key,spec in RECIPES.items()
                           if spec["business"]==recipe["business"]])).fetchone()
        occupied=int(pending["units"]) if pending else 0
        if occupied+q.amount>business_batch_limit(int(opened["level"])):
            raise HTTPException(409,"Все производственные мощности заняты. Дождитесь завершения или улучшите предприятие")
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
        started=time.time()
        ready=started+recipe["seconds"]*q.amount
        job_id=uuid.uuid4().hex
        c.execute("INSERT INTO city_jobs VALUES(%s,%s,%s,%s,%s)",
                  (job_id,p["id"],q.item,q.amount,ready))
        c.execute("INSERT INTO city_production_history VALUES(%s,%s,%s,%s,%s,%s)",
                  (job_id,p["id"],q.item,q.amount*recipe["output"],started,ready))
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
        if q.request_id:
            previous=_request(c,q,p["id"],"cancel_product:"+q.listing_id)
            if previous is not None:return previous
        row=c.execute("SELECT * FROM city_listings WHERE id=%s AND seller=%s FOR UPDATE",
            (q.listing_id,p["id"])).fetchone()
        if not row or row["quantity"]<=0:raise HTTPException(404,"Активный лот не найден")
        c.execute("UPDATE city_listings SET quantity=0 WHERE id=%s",(q.listing_id,))
        _add_product(c,"city_products",p["id"],row["item"],row["quantity"])
        result={"ok":True,"returned":row["quantity"]}
        if q.request_id:_finish_request(c,q,result)
    return result

@router.post("/buy-product")
def buy_product(q:Action,authorization:str=Header(default="")):
    if q.item not in RECIPES:raise HTTPException(400,"Неизвестный товар")
    if q.destination not in ("city","farm"):
        raise HTTPException(400,"Неизвестный склад")
    if q.destination=="farm" and q.item not in city_nutrition.FOOD_RESTORE:
        raise HTTPException(400,"На склад фермы можно купить готовую еду")
    _amount(q.amount,500)
    with _db() as c:
        c.execute("SELECT pg_advisory_xact_lock(1984533)")
        p=_auth(c,authorization,True)
        previous=_request(c,q,p["id"],"buy_farm_food" if q.destination=="farm" else "buy_product")
        if previous is not None:return previous
        chosen,taken,cost,own_quantity=_product_purchase(c,q.item,p["id"],q.amount,
            farm=q.destination=="farm",lock=True)
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
        if cost:
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
            receipt_id = uuid.uuid4().hex
            sold_at = time.time()
            c.execute("INSERT INTO city_receipts VALUES(%s,%s,%s,%s,%s,%s,%s)",
                      (receipt_id,p["id"],row["seller"],q.item,n,receipt,sold_at))
            if row["seller"] != p["id"]:
                _progress_event(c, row["seller"], "sale:" + receipt_id, "sale", sold_at, 0)
        if cost:
            c.execute("INSERT INTO money_log VALUES(%s,%s,'city_product_buy',%s,%s,%s)",
                      (uuid.uuid4().hex,p["id"],-cost,q.item+" x"+str(q.amount),time.time()))
        _add_product(c,"farm_food" if q.destination=="farm" else "city_products",p["id"],q.item,q.amount)
        result={"ok":True,"spent":cost,"own_quantity":own_quantity}
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
        now=time.time()
        order=next(x for x in daily_orders(c,p["id"],now) if x["id"]==q.item)
        if q.order_day and q.order_day!=order["day"]:
            raise HTTPException(409,"Заказы обновились. Открой список заново")
        if order["done"]:raise HTTPException(409,"Сегодня этот заказ уже выполнен")
        changed=c.execute("""UPDATE city_products SET quantity=quantity-%s
            WHERE player_id=%s AND item=%s AND quantity>=%s RETURNING quantity""",
            (order["quantity"],p["id"],order["recipe"],order["quantity"])).fetchone()
        if not changed:raise HTTPException(409,"Нужен товар: "+RECIPES[order["recipe"]]["name"])
        c.execute("INSERT INTO city_daily_orders VALUES(%s,%s,%s,%s)",
            (p["id"],order["day"],q.item,now))
        c.execute("""INSERT INTO city_reputation(player_id,points) VALUES(%s,%s)
            ON CONFLICT(player_id) DO UPDATE SET points=city_reputation.points+EXCLUDED.points""",
            (p["id"],order["reputation"]))
        _progress_event(c, p["id"], "order:" + order["day"] + ":" + q.item,
                        "order", now, 10, order["reputation"])
        result={"ok":True,"reputation_earned":order["reputation"]}
        if q.request_id:_finish_request(c,q,result)
    return result

@router.post("/move-food")
def move_food(q:Action,authorization:str=Header(default="")):
    if q.item not in city_nutrition.FOOD_RESTORE:
        raise HTTPException(400,"На ферму можно перенести только еду")
    _amount(q.amount,500)
    with _db() as c:
        p=_auth(c,authorization,True)
        previous=_request(c,q,p["id"],"move_food")
        if previous is not None:return previous
        updated=c.execute("""UPDATE city_products SET quantity=quantity-%s
            WHERE player_id=%s AND item=%s AND quantity>=%s RETURNING quantity""",
            (q.amount,p["id"],q.item,q.amount)).fetchone()
        if not updated:raise HTTPException(409,"Недостаточно еды на складе города")
        _add_product(c,"farm_food",p["id"],q.item,q.amount)
        result={"ok":True,"quantity":q.amount}
        _finish_request(c,q,result)
    return result


@router.post("/eat")
def eat(q:Action,authorization:str=Header(default="")):
    """Consume real city food. The bonus affects only future fed-animal
    production. Never create bonus coins or duplicate the consumed item."""
    if q.item not in city_nutrition.FOOD_RESTORE:
        raise HTTPException(400,"Этот товар нельзя съесть")
    if q.destination not in ("city","farm"):
        raise HTTPException(400,"Неизвестный склад")
    _amount(q.amount,20)
    if not q.request_id:raise HTTPException(400,"Нужен ключ операции")
    with _db() as c:
        c.execute("SELECT pg_advisory_xact_lock(1984533)")
        p=_auth(c,authorization,True)
        previous=_request(c,q,p["id"],"eat_farm_food" if q.destination=="farm" else "eat")
        if previous is not None:return previous
        # Settle all production BEFORE eating; food never boosts past hours.
        p=_advance(c,p)
        table="farm_food" if q.destination=="farm" else "city_products"
        if table=="city_products":
            _settle(c,p["id"])
        updated=c.execute(f"""UPDATE {table} SET quantity=quantity-%s
            WHERE player_id=%s AND item=%s AND quantity>=%s RETURNING quantity""",
            (q.amount,p["id"],q.item,q.amount)).fetchone()
        if not updated:raise HTTPException(409,"Недостаточно еды")
        nutrition=city_nutrition.eat(c,p["id"],q.item,q.amount)
        result={"ok":True,"nutrition":nutrition,"consumed":q.amount}
        _finish_request(c,q,result)
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
