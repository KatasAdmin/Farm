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
            c.execute("""CREATE TABLE market(id text PRIMARY KEY,seller text,item text,quantity integer,price integer)""")
            c.execute("""CREATE TABLE money_log(id text PRIMARY KEY,player_id text,kind text,delta integer,details text,created double precision)""")
            c.execute("""CREATE TABLE market_trade_audit(id text PRIMARY KEY,buyer_id text,seller_id text,item text,quantity integer,coins integer,created double precision)""")
            c.execute("""CREATE TABLE star_orders(id text PRIMARY KEY,player_id text)""")
            c.execute("""CREATE TABLE stars_refund_intents(order_id text PRIMARY KEY,status text)""")
            farm_wallet.initialize_sources(c)
            ad_inventory.initialize(c)
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
