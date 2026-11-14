"""Transactional City integration tests on isolated PostgreSQL schema."""
import os
import uuid
import unittest
from contextlib import contextmanager
import psycopg
from psycopg.rows import dict_row
from fastapi import HTTPException
import city_world
import farm_wallet
import ad_inventory

DSN=os.getenv("TEST_DATABASE_URL")

@unittest.skipUnless(DSN,"Requires isolated PostgreSQL TEST_DATABASE_URL")
class CityTransactions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema="city_ci_"+uuid.uuid4().hex[:16]
        with psycopg.connect(DSN,autocommit=True) as c:
            c.execute('CREATE SCHEMA "'+cls.schema+'"')

    @classmethod
    def tearDownClass(cls):
        with psycopg.connect(DSN,autocommit=True) as c:
            c.execute('DROP SCHEMA IF EXISTS "'+cls.schema+'" CASCADE')

    def connect(self):
        c=psycopg.connect(DSN,row_factory=dict_row)
        c.execute('SET search_path TO "'+self.schema+'"')
        return c

    def setUp(self):
        with self.connect() as c:
            c.execute('DROP SCHEMA "'+self.schema+'" CASCADE')
            c.execute('CREATE SCHEMA "'+self.schema+'"')
            c.execute('SET search_path TO "'+self.schema+'"')
            c.execute("""CREATE TABLE players(id text PRIMARY KEY,token text,name text,coins integer)""")
            c.execute("CREATE TABLE economy(id integer PRIMARY KEY, treasury integer)")
            c.execute("INSERT INTO economy VALUES(1,0)")
            c.execute("""CREATE TABLE market(id text PRIMARY KEY,seller text,item text,quantity integer,price integer)""")
            c.execute("""CREATE TABLE money_log(id text PRIMARY KEY,player_id text,kind text,delta integer,details text,created double precision)""")
            c.execute("""CREATE TABLE market_trade_audit(id text PRIMARY KEY,buyer_id text,seller_id text,item text,quantity integer,coins integer,created double precision)""")
            c.execute("""CREATE TABLE star_orders(id text PRIMARY KEY,player_id text)""")
            c.execute("""CREATE TABLE stars_refund_intents(order_id text PRIMARY KEY,status text)""")
            farm_wallet.initialize_sources(c)
            ad_inventory.initialize(c)
            c.execute("""CREATE TABLE promo_codes(code_hash text PRIMARY KEY, amount integer,
                redeemed_by text,redeemed_at double precision)""")
            c.execute("""CREATE TABLE reward_emission(id integer PRIMARY KEY,total_minted integer)""")
            c.execute("INSERT INTO reward_emission VALUES(1,0)")
            city_world.initialize(c)
            c.execute("""INSERT INTO players(id,token,name,coins)
                VALUES ('buyer','t-buyer','Покупатель',200),
                       ('seller','t-seller','Продавец',0),
                       ('other','t-other','Другой',200)""")
            c.execute("""INSERT INTO market VALUES
               ('egg-sale','seller','eggs',10,1),
               ('own-egg-sale','buyer','eggs',20,1),
               ('grain-sale','seller','grain',10,2),
               ('milk-sale','seller','milk',10,3)""")
        self.saved=(city_world._db,city_world._person,city_world._advance)
        def person(c,h,lock=False):
            return c.execute("SELECT * FROM players WHERE token=%s"+(" FOR UPDATE" if lock else ""),(h.replace("Bearer ",""),)).fetchone()
        city_world.setup(self.connect,person,lambda c,p:p)

    def tearDown(self):
        city_world._db,city_world._person,city_world._advance=self.saved

    def action(self,item="",amount=1,price=1,request_id="",expected_cost=-1,listing_id=""):
        return city_world.Action(item=item,amount=amount,price=price,
            request_id=request_id,expected_cost=expected_cost,listing_id=listing_id)

    def test_city_progress_is_awarded_once_for_orders_upgrades_and_completed_jobs(self):
        auth = "Bearer t-buyer"
        city_world.open_business(self.action("bakery"), authorization=auth)
        upgrade = self.action("bakery", request_id=uuid.uuid4().hex)
        self.assertEqual(city_world.upgrade_business(upgrade, authorization=auth),
                         city_world.upgrade_business(upgrade, authorization=auth))
        with self.connect() as c:
            order = city_world.daily_orders(c, "buyer")[0]
            city_world._add_product(c, "city_products", "buyer", order["recipe"], 1)
            for _ in range(2):
                c.execute("INSERT INTO city_jobs VALUES(%s,%s,%s,%s,%s)",
                          (uuid.uuid4().hex, "buyer", "bread", 1, city_world.time.time() - 10))
        order_action = self.action(order["id"], request_id=uuid.uuid4().hex)
        self.assertEqual(city_world.fulfill_order(order_action, authorization=auth),
                         city_world.fulfill_order(order_action, authorization=auth))
        snapshot = city_world.state(authorization=auth, compact=True)
        self.assertEqual(snapshot["progress"]["xp"], 50)
        self.assertEqual(snapshot["progress"]["level"], 2)
        self.assertEqual(snapshot["progress"]["orders"], 1)
        self.assertEqual(snapshot["reputation"], order["reputation"])
        self.assertEqual(snapshot["products"]["bread"], 4)
        events = city_world.progress_log(authorization=auth)
        self.assertEqual(sum(event["kind"] == "production" for event in events), 2)
        self.assertEqual(sum(event["kind"] == "production_xp" for event in events), 1)
        city_world.read_progress_log([event["source"] for event in events], authorization=auth)
        progress = city_world.state(authorization=auth, compact=True)["progress"]
        self.assertEqual(progress["unread"], 0)
        self.assertEqual(progress["xp"], 50)

    def test_daily_goal_uses_completed_batches_and_is_idempotent(self):
        auth = "Bearer t-buyer"
        now = city_world.time.time()
        start = now - now % 86400
        with self.connect() as c:
            c.execute("INSERT INTO city_production_history VALUES(%s,%s,%s,%s,%s,%s)",
                      ("test-batch", "buyer", "bread", 2, start-5, now+60))
        daily = city_world.goals(authorization=auth)["daily"]
        claim = city_world.GoalClaim(scope=daily["id"], key="batches")
        with self.assertRaises(HTTPException):
            city_world.claim_goal(claim, authorization=auth)
        with self.connect() as c:
            c.execute("UPDATE city_production_history SET ready_at=%s WHERE id='test-batch'", (start,))
        self.assertTrue(city_world.claim_goal(claim, authorization=auth)["ok"])
        self.assertTrue(city_world.claim_goal(claim, authorization=auth)["ok"])
        self.assertEqual(city_world.state(authorization=auth, compact=True)["progress"]["xp"], 5)

    def test_season_reward_is_owned_once_and_can_be_equipped(self):
        auth = "Bearer t-buyer"
        now = city_world.time.time()
        with self.connect() as c:
            c.execute("UPDATE city_campaigns SET starts=%s,ends=%s", (now-3600, now+3600))
            for index in range(5):
                c.execute("INSERT INTO city_production_history VALUES(%s,%s,%s,%s,%s,%s)",
                          (str(index), "buyer", "bread", 2, now-300, now-60))
        scope = "city-development"
        claim = city_world.GoalClaim(scope=scope, key="batches")
        reward = city_world.GoalClaim(scope=scope, key="reward:founder")
        with self.assertRaises(HTTPException):
            city_world.claim_goal(reward, authorization=auth)
        city_world.claim_goal(claim, authorization=auth)
        city_world.claim_goal(claim, authorization=auth)
        city_world.claim_goal(reward, authorization=auth)
        city_world.claim_goal(reward, authorization=auth)
        season = city_world.goals(authorization=auth)["campaigns"][0]
        self.assertEqual(season["xp"], 50)
        self.assertEqual(season["level"], 2)
        with self.assertRaises(HTTPException):
            city_world.save_preferences(city_world.CityPreferences(cosmetic="gold"), authorization=auth)
        city_world.save_preferences(city_world.CityPreferences(cosmetic="founder"), authorization=auth)
        snapshot = city_world.state(authorization=auth, compact=True)
        self.assertEqual(snapshot["preferences"]["cosmetic"], "founder")
        self.assertEqual(len(snapshot["cosmetics"]), 1)
        self.assertEqual(snapshot["progress"]["xp"], 0)
        self.assertEqual(snapshot["coins"], 200)

    def test_single_use_promo_uses_existing_nonwithdrawable_farm_ledger(self):
        import hashlib
        import main
        from unittest.mock import patch
        test_code="FARM-"+"A"*23
        digest=hashlib.sha256(test_code.encode()).hexdigest()
        with self.connect() as c:
            c.execute("INSERT INTO promo_codes(code_hash,amount) VALUES(%s,1000)",(digest,))
        with patch.object(main,"db",self.connect),patch.object(main,"person",city_world._person):
            result=main.redeem_promo(main.Request(code=test_code),
                authorization="Bearer t-buyer")
            self.assertEqual(result["awarded"],1000)
            with self.assertRaises(HTTPException) as err:
                main.redeem_promo(main.Request(code=test_code),
                    authorization="Bearer t-buyer")
            self.assertEqual(err.exception.status_code,409)
        with self.connect() as c:
            buyer=c.execute("SELECT * FROM players WHERE id='buyer'").fetchone()
            self.assertEqual(buyer["coins"],1200)
            self.assertEqual(farm_wallet.available(c,buyer),0)
            self.assertEqual(c.execute("SELECT total_minted FROM reward_emission WHERE id=1").fetchone()["total_minted"],1000)

    def test_shared_wallet_single_balance_and_city_cashflow(self):
        # The same players.coins column is the wallet across both games.
        original=city_world.state(authorization="Bearer t-buyer")
        self.assertEqual(original["coins"],200)
        self.assertEqual(original["wallet_mode"],"shared_farm_city")
        city_world.buy_ingredient(self.action("eggs",2,request_id="7"*32,expected_cost=2),
                                  authorization="Bearer t-buyer")
        after=city_world.state(authorization="Bearer t-buyer")
        self.assertEqual(after["coins"],198)
        self.assertEqual(after["cashflow"]["ingredient_spend"],2)
        self.assertEqual(after["cashflow"]["goods_purchases"],0)
        self.assertEqual(after["cashflow"]["goods_sales"],0)
        self.assertEqual(after["cashflow"]["net"],-2)
        with self.connect() as c:
            self.assertEqual(c.execute("SELECT coins FROM players WHERE id='buyer'").fetchone()["coins"],198)
            self.assertEqual(c.execute("SELECT COUNT(*) AS n FROM money_log WHERE player_id='buyer' AND kind='market_buy'").fetchone()["n"],1)
        self.assertEqual(city_world.state(authorization="Bearer t-buyer")["coins"],198)

    def test_city_eat_is_single_use_and_increases_farmer_fullness(self):
        with self.connect() as c:
            c.execute("INSERT INTO city_products VALUES('buyer','omelet',2)")
        meal=self.action("omelet",1,request_id="4"*32)
        result=city_world.eat(meal,authorization="Bearer t-buyer")
        self.assertTrue(result["ok"])
        self.assertEqual(result["nutrition"]["fullness"],28)
        same=city_world.eat(meal,authorization="Bearer t-buyer")
        self.assertEqual(result,same)
        with self.connect() as c:
            self.assertEqual(c.execute("SELECT quantity FROM city_products WHERE player_id='buyer' AND item='omelet'").fetchone()["quantity"],1)
            self.assertEqual(c.execute("SELECT COUNT(*) AS n FROM city_requests WHERE id=%s",("4"*32,)).fetchone()["n"],1)
        with self.assertRaises(HTTPException):
            city_world.eat(self.action("pillow",1,request_id="5"*32),authorization="Bearer t-buyer")

    def test_competing_buyers_farm_food_is_atomic_and_separate(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier

        with self.connect() as c:
            c.execute("INSERT INTO city_listings VALUES('food','seller','bread',1,10,0)")
        barrier=Barrier(2)

        def buy(player):
            request=self.action("bread",request_id=uuid.uuid4().hex,expected_cost=10)
            request.destination="farm"
            barrier.wait(timeout=5)
            try:
                result=city_world.buy_product(request,authorization="Bearer t-"+player)
                self.assertEqual(city_world.buy_product(request,authorization="Bearer t-"+player),result)
                return player
            except HTTPException as error:
                self.assertEqual(error.status_code,409)
                return None

        with ThreadPoolExecutor(2) as pool:
            winners=[player for player in pool.map(buy,("buyer","other")) if player]
        self.assertEqual(len(winners),1)
        with self.connect() as c:
            self.assertEqual(c.execute("SELECT SUM(coins) AS n FROM players").fetchone()["n"],400)
            self.assertEqual(c.execute("SELECT COUNT(*) AS n FROM city_receipts").fetchone()["n"],1)
            self.assertEqual(c.execute("SELECT COUNT(*) AS n FROM city_products").fetchone()["n"],0)
        winner=winners[0]
        auth="Bearer t-"+winner
        self.assertEqual(city_world.farm_goods(authorization=auth)["food"],{"bread":1})
        meal=self.action("bread",request_id=uuid.uuid4().hex)
        meal.destination="farm"
        self.assertEqual(city_world.eat(meal,authorization=auth)["nutrition"]["fullness"],5)
        self.assertEqual(city_world.farm_goods(authorization=auth)["food"],{})

    def test_pancakes_listing_visible_on_farm_to_owner_and_buyer(self):
        seller="Bearer t-seller"
        buyer="Bearer t-buyer"
        with self.connect() as c:
            c.execute("INSERT INTO city_products VALUES('seller','pancakes',2)")
        listed=city_world.list_product(self.action("pancakes",2,price=5),authorization=seller)
        listing_id=listed["listing_id"]
        own=city_world.farm_goods(authorization=seller)
        self.assertEqual(own["my_offers"],[{"id":listing_id,"item":"pancakes","quantity":2,"price":5}])
        self.assertEqual(own["city_catalog"]["pancakes"]["quantity"],2)
        self.assertEqual(city_world.farm_goods(authorization=buyer)["city_catalog"]["pancakes"]["quantity"],2)

        request=self.action("pancakes",1,request_id=uuid.uuid4().hex,expected_cost=5)
        request.destination="farm"
        city_world.buy_product(request,authorization=buyer)
        self.assertEqual(city_world.farm_goods(authorization=buyer)["food"],{"pancakes":1})
        city_world.cancel_product(self.action(listing_id=listing_id),authorization=seller)
        self.assertEqual(city_world.farm_goods(authorization=seller)["my_offers"],[])
        self.assertEqual(city_world.farm_goods(authorization=seller)["city_food"],{"pancakes":1})

    def test_farm_market_treats_own_and_other_listings_equally(self):
        buyer="Bearer t-buyer"
        with self.connect() as c:
            c.execute("""INSERT INTO city_listings VALUES
                ('own-new','buyer','pancakes',2,1,30),
                ('own-old','buyer','pancakes',2,3,10),
                ('external-new','other','pancakes',1,5,20),
                ('external-old','seller','pancakes',1,5,10)""")

        def buy(amount,cost):
            request=self.action("pancakes",amount,request_id=uuid.uuid4().hex,expected_cost=cost)
            request.destination="farm"
            quote=city_world.quote_product(request,authorization=buyer)
            self.assertEqual((quote["cost"],quote["own_quantity"]),(cost,0))
            result=city_world.buy_product(request,authorization=buyer)
            self.assertEqual((result["spent"],result["own_quantity"]),(cost,0))
            self.assertEqual(city_world.buy_product(request,authorization=buyer),result)

        buy(1,1)
        buy(2,4)
        buy(1,3)
        self.assertEqual(city_world.farm_goods(authorization=buyer)["food"],{"pancakes":4})
        with self.connect() as c:
            balances=c.execute("SELECT coins FROM players ORDER BY id").fetchall()
            self.assertEqual([row["coins"] for row in balances],[200,200,0])
            self.assertEqual(c.execute("SELECT COUNT(*) AS n FROM city_receipts").fetchone()["n"],4)
            self.assertEqual(c.execute("SELECT quantity FROM city_listings WHERE id='own-old'").fetchone()["quantity"],0)
            self.assertEqual(c.execute("SELECT quantity FROM city_listings WHERE id='own-new'").fetchone()["quantity"],0)
            self.assertEqual(c.execute("SELECT quantity FROM city_listings WHERE id='external-old'").fetchone()["quantity"],1)

    def test_existing_city_food_moves_once_without_changing_balances(self):
        auth="Bearer t-buyer"
        with self.connect() as c:
            c.execute("INSERT INTO city_products VALUES('buyer','bread',2)")
            city_world.initialize(c)
        self.assertEqual(city_world.farm_goods(authorization=auth)["city_food"],{"bread":2})
        q=self.action("bread",request_id=uuid.uuid4().hex)
        result=city_world.move_food(q,authorization=auth)
        self.assertEqual(city_world.move_food(q,authorization=auth),result)
        snapshot=city_world.farm_goods(authorization=auth)
        self.assertEqual(snapshot["food"],{"bread":1})
        self.assertEqual(snapshot["city_food"],{"bread":1})
        self.assertEqual(city_world.state(authorization=auth,compact=True)["coins"],200)

    def test_daily_order_rollover_rejects_stale_order_and_never_mints(self):
        from unittest.mock import patch

        auth="Bearer t-buyer"
        now=86400*20000+86399
        with patch.object(city_world.time,"time",return_value=now),self.connect() as c:
            order=city_world.daily_orders(c,"buyer")[0]
            c.execute("INSERT INTO city_products VALUES('buyer',%s,2)",(order["recipe"],))
        request=self.action(order["id"],request_id=uuid.uuid4().hex)
        request.order_day=order["day"]
        with patch.object(city_world.time,"time",return_value=now+1):
            with self.assertRaises(HTTPException) as error:
                city_world.fulfill_order(request,authorization=auth)
            self.assertEqual(error.exception.status_code,409)
        with patch.object(city_world.time,"time",return_value=now):
            result=city_world.fulfill_order(request,authorization=auth)
            self.assertEqual(city_world.fulfill_order(request,authorization=auth),result)
            self.assertEqual(result["reputation_earned"],order["reputation"])
        with self.connect() as c:
            self.assertEqual(c.execute("SELECT SUM(coins) AS n FROM players").fetchone()["n"],400)
            self.assertEqual(c.execute("SELECT quantity FROM city_products").fetchone()["quantity"],1)

    def test_city_eggs_use_same_price_proportional_allocation(self):
        with self.connect() as c:
            c.execute("INSERT INTO market VALUES('egg-second','other','eggs',10,1)")
        q=self.action("eggs",6,request_id="6"*32,expected_cost=6)
        result=city_world.buy_ingredient(q,authorization="Bearer t-buyer")
        self.assertEqual(result["quantity"],6)
        with self.connect() as c:
            rows=c.execute("SELECT seller,quantity FROM city_raw_receipts WHERE buyer='buyer' AND item='eggs' ORDER BY seller").fetchall()
            self.assertEqual({r["seller"]:r["quantity"] for r in rows},{"seller":3,"other":3})
            self.assertEqual(c.execute("SELECT coins FROM players WHERE id='buyer'").fetchone()["coins"],194)
        self.assertEqual(city_world.buy_ingredient(q,authorization="Bearer t-buyer"),result)

    def test_same_price_eggs_are_proportionally_bought_from_all_sellers(self):
        with self.connect() as c:
            c.execute("INSERT INTO market VALUES('small-egg-sale','other','eggs',2,1)")
        quote=city_world.quote_ingredient(self.action("eggs",6),authorization="Bearer t-buyer")
        self.assertEqual(quote["cost"],6)
        self.assertEqual(quote["sellers"],2)
        city_world.buy_ingredient(self.action("eggs",6,request_id="8"*32,expected_cost=6),
                                  authorization="Bearer t-buyer")
        with self.connect() as c:
            amounts={r["seller_id"]:r["quantity"] for r in c.execute(
                "SELECT seller_id,quantity FROM market_trade_audit WHERE buyer_id='buyer' AND item='eggs'").fetchall()}
            self.assertEqual(amounts,{"seller":5,"other":1})
            self.assertEqual(c.execute("SELECT quantity FROM market WHERE id='own-egg-sale'").fetchone()["quantity"],20)

    def test_one_shared_food_stock_and_safe_migration(self):
        from unittest.mock import patch
        import simple_economy
        auth="Bearer t-buyer"
        with self.connect() as c:
            c.execute("INSERT INTO farm_food VALUES('buyer','bread',3)")
            c.execute("INSERT INTO city_products VALUES('buyer','bread',2)")
            c.execute("INSERT INTO farm_food VALUES('buyer','omelet',1)")
        with patch.object(simple_economy,"enabled",return_value=True):
            with self.connect() as c:
                simple_economy.initialize(c)
                city_world.initialize(c)
                self.assertEqual(c.execute("SELECT quantity FROM city_products WHERE player_id='buyer' AND item='bread'").fetchone()["quantity"],5)
                self.assertEqual(c.execute("SELECT COUNT(*) AS n FROM farm_food").fetchone()["n"],0)
                # Source emptied atomically, so later initialization cannot add it again.
                self.assertEqual(c.execute("SELECT quantity FROM city_products WHERE player_id='buyer' AND item='bread'").fetchone()["quantity"],5)
            self.assertEqual(city_world.farm_goods(authorization=auth)["food"],{"bread":5,"omelet":1})
            self.assertEqual(city_world.farm_goods(authorization=auth)["city_food"],{})
            price=simple_economy.prices(city_world.RECIPES)["bread"]["buy"]
            q=self.action("bread",1,request_id=uuid.uuid4().hex,expected_cost=price)
            q.destination="farm"
            city_world.buy_product(q,authorization=auth)
            self.assertEqual(city_world.farm_goods(authorization=auth)["food"]["bread"],6)
            meal=self.action("bread",2,request_id=uuid.uuid4().hex)
            meal.destination="farm"
            city_world.eat(meal,authorization=auth)
            self.assertEqual(city_world.farm_goods(authorization=auth)["food"]["bread"],4)
            sale=self.action("bread",1,request_id=uuid.uuid4().hex)
            sale.destination="city"
            city_world.list_product(sale,authorization=auth)
            self.assertEqual(city_world.farm_goods(authorization=auth)["food"]["bread"],3)
            with self.connect() as c:
                self.assertEqual(c.execute("SELECT COUNT(*) AS n FROM farm_food").fetchone()["n"],0)

    def test_simple_system_uses_treasury_and_nonwithdrawable_game_credits(self):
        import simple_economy
        with self.connect() as db:
            simple_economy.initialize(db)
            db.execute("UPDATE economy SET treasury=100 WHERE id=1")
            p=db.execute("SELECT * FROM players WHERE id='buyer'").fetchone()
            bought=simple_economy.raw_city_trade(db,p,"eggs",3,"buy")
            self.assertEqual(bought["spent"],6)
            sold=simple_economy.raw_city_trade(db,p,"eggs",2,"sell")
            self.assertEqual(sold["received"],2)
            self.assertEqual(db.execute("SELECT treasury FROM economy WHERE id=1").fetchone()["treasury"],104)
            buyer=db.execute("SELECT * FROM players WHERE id='buyer'").fetchone()
            self.assertEqual(buyer["coins"],196)
            self.assertEqual(farm_wallet.available(db,buyer),0)
            self.assertEqual(db.execute("SELECT quantity FROM city_stock WHERE player_id='buyer' AND item='eggs'").fetchone()["quantity"],1)

    def test_simple_system_unfunded_buyback_credits_coins_and_debits_treasury(self):
        import simple_economy
        with self.connect() as db:
            simple_economy.initialize(db)
            db.execute("INSERT INTO city_products VALUES('buyer','pancakes',3)")
            p=db.execute("SELECT * FROM players WHERE id='buyer'").fetchone()
            result=simple_economy.city_product_trade(db,p,"pancakes",2,"sell",city_world.RECIPES)
            self.assertGreater(result["received"],0)
            self.assertEqual(db.execute("SELECT quantity FROM city_products WHERE player_id='buyer' AND item='pancakes'").fetchone()["quantity"],1)
            self.assertEqual(db.execute("SELECT coins FROM players WHERE id='buyer'").fetchone()["coins"],200+result["received"])
            self.assertEqual(db.execute("SELECT treasury FROM economy WHERE id=1").fetchone()["treasury"],-result["received"])
            self.assertEqual(farm_wallet.available(db,db.execute("SELECT * FROM players WHERE id='buyer'").fetchone()),0)

    def test_simple_market_old_listings_restore_exactly_once(self):
        import simple_economy
        with self.connect() as db:
            simple_economy.initialize(db)
            db.execute("ALTER TABLE players ADD COLUMN eggs bigint DEFAULT 0")
            db.execute("ALTER TABLE players ADD COLUMN grain bigint DEFAULT 0")
            db.execute("ALTER TABLE players ADD COLUMN milk bigint DEFAULT 0")
            db.execute("ALTER TABLE players ADD COLUMN feathers bigint DEFAULT 0")
            db.execute("ALTER TABLE players ADD COLUMN wool bigint DEFAULT 0")
            db.execute("INSERT INTO city_listings VALUES('old-lot','buyer','pancakes',4,10,100)")
            first=simple_economy.migrate_listings(db)
            self.assertEqual(first["city_lots"],1)
            self.assertGreaterEqual(first["farm_lots"],1)
            self.assertEqual(simple_economy.migrate_listings(db),{"farm_lots":0,"city_lots":0})
            self.assertEqual(db.execute("SELECT eggs FROM players WHERE id='seller'").fetchone()["eggs"],10)
            self.assertEqual(db.execute("SELECT quantity FROM city_products WHERE player_id='buyer' AND item='pancakes'").fetchone()["quantity"],4)
            self.assertEqual(db.execute("SELECT COUNT(*) AS n FROM market WHERE quantity>0").fetchone()["n"],0)
            self.assertEqual(db.execute("SELECT COUNT(*) AS n FROM city_listings WHERE quantity>0").fetchone()["n"],0)
            self.assertEqual(db.execute("SELECT coins FROM players WHERE id='buyer'").fetchone()["coins"],200)

    def test_farm_to_business_to_farm_is_free_and_exact(self):
        import simple_economy
        with self.connect() as db:
            simple_economy.initialize(db)
            db.execute("ALTER TABLE players ADD COLUMN eggs bigint DEFAULT 0")
            db.execute("ALTER TABLE players ADD COLUMN grain bigint DEFAULT 0")
            db.execute("ALTER TABLE players ADD COLUMN milk bigint DEFAULT 0")
            db.execute("ALTER TABLE players ADD COLUMN feathers bigint DEFAULT 0")
            db.execute("ALTER TABLE players ADD COLUMN wool bigint DEFAULT 0")
            db.execute("UPDATE players SET eggs=8 WHERE id='buyer'")
            p=db.execute("SELECT * FROM players WHERE id='buyer'").fetchone()
            simple_economy.raw_transfer(db,p,"eggs",3,"to_city",storage_limit=100)
            p=db.execute("SELECT * FROM players WHERE id='buyer'").fetchone()
            simple_economy.raw_transfer(db,p,"eggs",2,"to_farm",storage_limit=100)
            self.assertEqual(db.execute("SELECT eggs FROM players WHERE id='buyer'").fetchone()["eggs"],7)
            self.assertEqual(db.execute("SELECT quantity FROM city_stock WHERE item='eggs' AND player_id='buyer'").fetchone()["quantity"],1)
            self.assertEqual(db.execute("SELECT coins FROM players WHERE id='buyer'").fetchone()["coins"],200)

    def test_fixed_prices_have_no_instant_craft_arbitrage(self):
        import simple_economy
        product_prices=simple_economy.prices(city_world.RECIPES)
        for key,recipe in city_world.RECIPES.items():
            self.assertLess(product_prices[key]["sell"]*recipe["output"],
                            product_prices[key]["batch_input_cost"]+1)
            self.assertGreater(product_prices[key]["buy"],product_prices[key]["sell"])

    def test_ingredient_trade_excludes_self_and_is_idempotent(self):
        q=self.action("eggs",5,request_id="a"*32,expected_cost=5)
        result=city_world.buy_ingredient(q,authorization="Bearer t-buyer")
        self.assertEqual(result["spent"],5)
        self.assertEqual(city_world.buy_ingredient(q,authorization="Bearer t-buyer"),result)
        with self.connect() as c:
            self.assertEqual(c.execute("SELECT coins FROM players WHERE id='buyer'").fetchone()["coins"],195)
            self.assertEqual(c.execute("SELECT coins FROM players WHERE id='seller'").fetchone()["coins"],5)
            self.assertEqual(c.execute("SELECT quantity FROM market WHERE id='egg-sale'").fetchone()["quantity"],5)
            self.assertEqual(c.execute("SELECT quantity FROM market WHERE id='own-egg-sale'").fetchone()["quantity"],20)
            self.assertEqual(c.execute("SELECT quantity FROM city_stock WHERE player_id='buyer' AND item='eggs'").fetchone()["quantity"],5)
            self.assertEqual(c.execute("SELECT COUNT(*) AS n FROM market_trade_audit").fetchone()["n"],1)
            self.assertEqual(c.execute("SELECT COUNT(*) AS n FROM city_raw_receipts").fetchone()["n"],1)
        snapshot=city_world.state(authorization="Bearer t-buyer")
        self.assertEqual(snapshot["city_demand_today"]["eggs"],5)
        self.assertEqual(snapshot["farm_market_totals"]["eggs"],25)

    def test_grain_uses_existing_system_supply_only_after_players(self):
        auth="Bearer t-buyer"
        quote=city_world.quote_ingredient(self.action("grain",12),authorization=auth)
        self.assertEqual((quote["cost"],quote["system_quantity"]),(24,2))
        q=self.action("grain",12,request_id=uuid.uuid4().hex,expected_cost=quote["cost"])
        city_world.buy_ingredient(q,authorization=auth)
        with self.connect() as c:
            self.assertEqual(c.execute("SELECT coins FROM players WHERE id='seller'").fetchone()["coins"],20)
            self.assertEqual(c.execute("SELECT treasury FROM economy").fetchone()["treasury"],4)
            self.assertEqual(c.execute("SELECT quantity FROM city_stock WHERE item='grain'").fetchone()["quantity"],12)
        with self.assertRaises(HTTPException):
            city_world.quote_product(self.action("bread",1),authorization=auth)

    def test_buy_requires_unchanged_quote(self):
        q=self.action("eggs",3,request_id="b"*32,expected_cost=1)
        with self.assertRaises(HTTPException) as error:
            city_world.buy_ingredient(q,authorization="Bearer t-buyer")
        self.assertEqual(error.exception.status_code,409)
        with self.connect() as c:
            self.assertEqual(c.execute("SELECT coins FROM players WHERE id='buyer'").fetchone()["coins"],200)

    def test_business_cannot_use_farm_warehouse_and_consumes_city_stock(self):
        city_world.open_business(self.action("bakery"),authorization="Bearer t-buyer")
        with self.assertRaises(HTTPException):
            city_world.produce(self.action("pancakes"),authorization="Bearer t-buyer")
        for kind,n,price,key in [("eggs",4,1,"c"),("grain",3,2,"d"),("milk",1,3,"e")]:
            city_world.buy_ingredient(self.action(kind,n,request_id=key*32,expected_cost=n*price),authorization="Bearer t-buyer")
        result=city_world.produce(self.action("pancakes"),authorization="Bearer t-buyer")
        self.assertTrue(result["ok"])
        with self.connect() as c:
            self.assertEqual(c.execute("SELECT quantity FROM city_stock WHERE item='eggs' AND player_id='buyer'").fetchone()["quantity"],0)
            c.execute("UPDATE city_jobs SET ready_at=0")
        state=city_world.state(authorization="Bearer t-buyer")
        self.assertEqual(state["products"]["pancakes"],2)

    def test_finished_city_goods_reach_other_players_as_nonwithdrawable_sale(self):
        with self.connect() as c:
            c.execute("INSERT INTO city_products VALUES('seller','bread',2)")
        city_world.list_product(self.action("bread",amount=2,price=7),authorization="Bearer t-seller")
        quote=city_world.quote_product(self.action("bread",amount=1),authorization="Bearer t-buyer")
        self.assertEqual(quote["cost"],7)
        city_world.buy_product(self.action("bread",amount=1,request_id="f"*32,expected_cost=7),
            authorization="Bearer t-buyer")
        with self.connect() as c:
            seller=c.execute("SELECT * FROM players WHERE id='seller'").fetchone()
            self.assertEqual(farm_wallet.available(c,seller),0)
            self.assertEqual(c.execute("SELECT quantity FROM city_products WHERE player_id='buyer' AND item='bread'").fetchone()["quantity"],1)

    def test_secondary_recipe_requires_real_city_products(self):
        with self.connect() as c:
            c.execute("INSERT INTO city_reputation VALUES('buyer',30)")
            c.execute("INSERT INTO city_products VALUES('seller','bread',2),('seller','cheese',2)")
        city_world.open_business(self.action("restaurant"),authorization="Bearer t-buyer")
        with self.assertRaises(HTTPException):
            city_world.produce(self.action("breakfast_set"),authorization="Bearer t-buyer")
        # Seller's two products are available on the City market. No free
        # transfer from the buyer's farm warehouse is possible.
        city_world.list_product(self.action("bread",amount=1,price=5),authorization="Bearer t-seller")
        city_world.list_product(self.action("cheese",amount=1,price=7),authorization="Bearer t-seller")
        for item,cost,key in (("bread",5,"b"),("cheese",7,"c")):
            city_world.buy_product(self.action(item,1,request_id=key*32,expected_cost=cost),
                                   authorization="Bearer t-buyer")
        city_world.buy_ingredient(self.action("eggs",2,request_id="d"*32,expected_cost=2),
                                  authorization="Bearer t-buyer")
        city_world.produce(self.action("breakfast_set"),authorization="Bearer t-buyer")
        with self.connect() as c:
            for item in ("bread","cheese"):
                self.assertEqual(c.execute("SELECT quantity FROM city_products WHERE player_id='buyer' AND item=%s",(item,)).fetchone()["quantity"],0)
            self.assertEqual(c.execute("SELECT quantity FROM city_stock WHERE player_id='buyer' AND item='eggs'").fetchone()["quantity"],0)
            self.assertEqual(c.execute("SELECT COUNT(*) AS n FROM city_jobs WHERE player_id='buyer' AND recipe='breakfast_set'").fetchone()["n"],1)

    def test_secondary_recipe_shortage_rolls_back_all_ingredients(self):
        with self.connect() as c:
            c.execute("INSERT INTO city_reputation VALUES('buyer',30)")
            c.execute("INSERT INTO city_stock VALUES('buyer','eggs',2)")
            c.execute("INSERT INTO city_products VALUES('buyer','bread',1)")
        city_world.open_business(self.action("restaurant"),authorization="Bearer t-buyer")
        with self.assertRaises(HTTPException):
            city_world.produce(self.action("breakfast_set"),authorization="Bearer t-buyer")
        with self.connect() as c:
            self.assertEqual(c.execute("SELECT quantity FROM city_stock WHERE player_id='buyer' AND item='eggs'").fetchone()["quantity"],2)
            self.assertEqual(c.execute("SELECT quantity FROM city_products WHERE player_id='buyer' AND item='bread'").fetchone()["quantity"],1)

    def test_refund_pending_seller_blocks_city_product_purchase(self):
        with self.connect() as c:
            c.execute("INSERT INTO city_products VALUES('seller','bread',1)")
        city_world.list_product(self.action("bread",1,7),authorization="Bearer t-seller")
        with self.connect() as c:
            c.execute("INSERT INTO star_orders VALUES('order-1','seller')")
            c.execute("INSERT INTO stars_refund_intents VALUES('order-1','needs_review')")
        with self.assertRaises(HTTPException) as err:
            city_world.buy_product(self.action("bread",1,request_id="e"*32,expected_cost=7),
                                   authorization="Bearer t-buyer")
        self.assertEqual(err.exception.status_code,409)
        with self.connect() as c:
            self.assertEqual(c.execute("SELECT coins FROM players WHERE id='buyer'").fetchone()["coins"],200)

    def test_production_retry_does_not_consume_ingredients_twice(self):
        city_world.open_business(self.action("bakery"),authorization="Bearer t-buyer")
        with self.connect() as c:
            for item,n in (("eggs",8),("grain",10)):
                c.execute("INSERT INTO city_stock VALUES('buyer',%s,%s)",(item,n))
        q=self.action("pie",1,request_id="1"*32)
        first=city_world.produce(q,authorization="Bearer t-buyer")
        self.assertEqual(city_world.produce(q,authorization="Bearer t-buyer"),first)
        with self.connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) AS n FROM city_jobs WHERE player_id='buyer'").fetchone()["n"],1)
            self.assertEqual(c.execute("SELECT quantity FROM city_stock WHERE item='eggs' AND player_id='buyer'").fetchone()["quantity"],0)

    def test_listing_retry_and_consumption_retry_do_not_double_spend(self):
        with self.connect() as c:
            c.execute("INSERT INTO city_products VALUES('buyer','bread',4)")
        listing=self.action("bread",2,price=3,request_id="2"*32)
        first=city_world.list_product(listing,authorization="Bearer t-buyer")
        self.assertEqual(city_world.list_product(listing,authorization="Bearer t-buyer"),first)
        with self.connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) AS n FROM city_listings WHERE seller='buyer'").fetchone()["n"],1)
        consume=self.action("bread",1,request_id="3"*32)
        result=city_world.consume(consume,authorization="Bearer t-buyer")
        self.assertEqual(city_world.consume(consume,authorization="Bearer t-buyer"),result)
        with self.connect() as c:
            self.assertEqual(c.execute("SELECT points FROM city_reputation WHERE player_id='buyer'").fetchone()["points"],5)
            self.assertEqual(c.execute("SELECT quantity FROM city_products WHERE player_id='buyer' AND item='bread'").fetchone()["quantity"],1)

    def test_city_meal_grants_no_coins_and_never_eats_twice(self):
        with self.connect() as c:
            c.execute("INSERT INTO city_products VALUES('buyer','omelet',2)")
        q=self.action("omelet",1,request_id="9"*32)
        first=city_world.eat(q,authorization="Bearer t-buyer")
        again=city_world.eat(q,authorization="Bearer t-buyer")
        self.assertEqual(first,again)
        self.assertGreater(first["nutrition"]["fullness"],0)
        with self.connect() as c:
            self.assertEqual(c.execute("SELECT coins FROM players WHERE id='buyer'").fetchone()["coins"],200)
            self.assertEqual(c.execute("SELECT quantity FROM city_products WHERE player_id='buyer' AND item='omelet'").fetchone()["quantity"],1)
            self.assertEqual(c.execute("SELECT COUNT(*) AS n FROM city_requests WHERE player_id='buyer' AND action='eat'").fetchone()["n"],1)

    def test_city_daily_orders_do_not_pay_coins(self):
        with self.connect() as c:
            o=city_world.daily_orders(c,"buyer")[0]
            c.execute("INSERT INTO city_products VALUES(%s,%s,1)",("buyer",o["recipe"]))
        city_world.fulfill_order(self.action(o["id"]),authorization="Bearer t-buyer")
        with self.connect() as c:
            self.assertEqual(c.execute("SELECT coins FROM players WHERE id='buyer'").fetchone()["coins"],200)
            self.assertEqual(c.execute("SELECT points FROM city_reputation WHERE player_id='buyer'").fetchone()["points"],o["reputation"])
        with self.assertRaises(HTTPException):
            city_world.fulfill_order(self.action(o["id"]),authorization="Bearer t-buyer")

if __name__=="__main__":unittest.main()
