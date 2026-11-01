import os
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
import psycopg
from psycopg.rows import dict_row
import farm_wallet

DSN = os.environ.get("TEST_DATABASE_URL")


@unittest.skipUnless(DSN, "Set TEST_DATABASE_URL to an isolated PostgreSQL database")
class PostgresMarketLedgerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = "farm_ci_" + uuid.uuid4().hex[:16]
        with psycopg.connect(DSN, autocommit=True) as c:
            c.execute('CREATE SCHEMA "' + cls.schema + '"')

    @classmethod
    def tearDownClass(cls):
        with psycopg.connect(DSN, autocommit=True) as c:
            c.execute('DROP SCHEMA IF EXISTS "' + cls.schema + '" CASCADE')

    def connect(self):
        c = psycopg.connect(DSN, row_factory=dict_row)
        c.execute('SET search_path TO "' + self.schema + '"')
        return c

    def setUp(self):
        with self.connect() as c:
            c.execute('DROP TABLE IF EXISTS farm_money_sources, money_log, players, market CASCADE')
            c.execute('CREATE TABLE players(id text PRIMARY KEY, coins integer NOT NULL CHECK(coins>=0))')
            c.execute('CREATE TABLE money_log(id text PRIMARY KEY,player_id text NOT NULL,kind text NOT NULL,delta integer NOT NULL,details text,created double precision NOT NULL)')
            c.execute('CREATE TABLE market(id text PRIMARY KEY,seller text NOT NULL,quantity integer NOT NULL CHECK(quantity>=0),price integer NOT NULL CHECK(price>0))')
            farm_wallet.initialize_sources(c)
            c.execute("INSERT INTO players VALUES('buyer',100),('seller',0)")
            c.execute("INSERT INTO money_log VALUES('initial','buyer','stars_purchase',100,'test',1)")

    def test_provenance_is_not_laundered_on_postgres(self):
        with self.connect() as c:
            buyer = c.execute("SELECT * FROM players WHERE id='buyer'").fetchone()
            sources = farm_wallet.split_market_sources([('listing',100)],farm_wallet.balances(c,buyer),100)
            self.assertEqual(sources['listing'],{'bonus':0,'purchased':100,'earned':0})
            c.execute("UPDATE players SET coins=0 WHERE id='buyer'")
            c.execute("UPDATE players SET coins=100 WHERE id='seller'")
            c.execute("INSERT INTO money_log VALUES('sale','seller','market_sale',100,'test',2)")
            c.execute("INSERT INTO farm_money_sources VALUES('sale',0,100,0)")
            seller = c.execute("SELECT * FROM players WHERE id='seller'").fetchone()
            self.assertEqual(farm_wallet.available(c,seller),0)

    def test_competing_buyers_cannot_oversell(self):
        # Mimics the actual market transaction's advisory lock and FOR UPDATE.
        with self.connect() as c:
            c.execute("INSERT INTO market VALUES('listing','seller',1,1)")
        def purchase(_):
            with self.connect() as c:
                c.execute('SELECT pg_advisory_xact_lock(1984533)')
                listing=c.execute("SELECT quantity FROM market WHERE id='listing' FOR UPDATE").fetchone()
                if listing['quantity']<1:return False
                c.execute("UPDATE market SET quantity=quantity-1 WHERE id='listing'")
                return True
        with ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(purchase,range(16)))
        self.assertEqual(sum(results),1)
        with self.connect() as c:
            self.assertEqual(c.execute("SELECT quantity FROM market WHERE id='listing'").fetchone()['quantity'],0)


if __name__ == '__main__':
    unittest.main()
