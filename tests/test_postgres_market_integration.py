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
            c.execute('DROP TABLE IF EXISTS staged_achievement_claims, daily_claims, weekly_claims, daily_activity, farm_events, market_trade_audit, reward_emission, incubator_jobs, farm_bot_transfers, star_orders, referral_codes, referrals, farm_money_sources, money_log, players, market CASCADE')
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


    def test_autobuy_coin_debit_is_atomic_under_contention(self):
        with self.connect() as c:
            c.execute("UPDATE players SET coins=20 WHERE id='buyer'")
        def buy_grain(_):
            with self.connect() as c:
                row=c.execute("SELECT coins FROM players WHERE id='buyer' FOR UPDATE").fetchone()
                if row["coins"] < 20:
                    return False
                changed=c.execute("UPDATE players SET coins=coins-20 WHERE id='buyer' AND coins>=20 RETURNING coins").fetchone()
                return changed is not None
        with ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(buy_grain,range(16)))
        self.assertEqual(sum(results),1)
        with self.connect() as c:
            self.assertEqual(c.execute("SELECT coins FROM players WHERE id='buyer'").fetchone()["coins"],0)

    def test_incubator_slot_claim_is_atomic_under_contention(self):
        with self.connect() as c:
            c.execute("CREATE TABLE incubator_jobs(id text PRIMARY KEY,player_id text,slot integer,eggs integer,coins integer,UNIQUE(player_id,slot))")
        def incubate(i):
            try:
                with self.connect() as c:
                    c.execute("INSERT INTO incubator_jobs VALUES(%s,'buyer',1,12,15)",(str(i),))
                return True
            except psycopg.errors.UniqueViolation:
                return False
        with ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(incubate,range(16)))
        self.assertEqual(sum(results),1)
        with self.connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) AS n FROM incubator_jobs").fetchone()["n"],1)


    def test_transfer_retry_key_is_unique_under_concurrency(self):
        with self.connect() as c:
            c.execute("CREATE TABLE farm_bot_transfers(id text PRIMARY KEY,player_id text,amount integer)")
        def transfer(_):
            try:
                with self.connect() as c:
                    c.execute("INSERT INTO farm_bot_transfers VALUES('same-request','buyer',100)")
                return True
            except psycopg.errors.UniqueViolation:
                return False
        with ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(transfer,range(16)))
        self.assertEqual(sum(results),1)
        with self.connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) AS n FROM farm_bot_transfers").fetchone()["n"],1)

    def test_stars_charge_cannot_be_assigned_to_two_orders(self):
        with self.connect() as c:
            c.execute("CREATE TABLE star_orders(id text PRIMARY KEY,charge_id text UNIQUE)")
        def credit(i):
            try:
                with self.connect() as c:
                    c.execute("INSERT INTO star_orders VALUES(%s,'same-telegram-charge')",(str(i),))
                return True
            except psycopg.errors.UniqueViolation:
                return False
        with ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(credit,range(16)))
        self.assertEqual(sum(results),1)
        with self.connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) AS n FROM star_orders").fetchone()["n"],1)


    def test_concurrent_reciprocal_referrals_cannot_form_cycle(self):
        with self.connect() as c:
            c.execute("CREATE TABLE referrals(child_id text PRIMARY KEY,parent_id text NOT NULL)")
        def link(pair):
            child, parent = pair
            with self.connect() as c:
                c.execute("SELECT pg_advisory_xact_lock(1984533)")
                cycle=c.execute("""WITH RECURSIVE descendants(id) AS (
                    SELECT child_id FROM referrals WHERE parent_id=%s
                    UNION SELECT r.child_id FROM referrals r
                    JOIN descendants d ON r.parent_id=d.id
                ) SELECT 1 FROM descendants WHERE id=%s LIMIT 1""",
                    (child,parent)).fetchone()
                if cycle:return False
                c.execute("INSERT INTO referrals VALUES(%s,%s)",(child,parent))
                return True
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes=list(pool.map(link,[("a","b"),("b","a")]))
        self.assertEqual(sum(outcomes),1)
        with self.connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) AS n FROM referrals").fetchone()["n"],1)


    def test_actual_referral_handler_rejects_concurrent_reciprocal_links(self):
        import main
        with self.connect() as c:
            c.execute("CREATE TABLE referral_codes(player_id text PRIMARY KEY,code text UNIQUE NOT NULL)")
            c.execute("CREATE TABLE referrals(child_id text PRIMARY KEY,parent_id text NOT NULL,created double precision)")
            c.execute("INSERT INTO referral_codes VALUES('a','aaaaaaaaaaaaaaaa'),('b','bbbbbbbbbbbbbbbb')")
        def register(args):
            child,code=args
            with self.connect() as c:
                return main.register_referral(c,child,code,1.0)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(register,[('a','bbbbbbbbbbbbbbbb'),('b','aaaaaaaaaaaaaaaa')]))
        with self.connect() as c:
            links=c.execute("SELECT child_id,parent_id FROM referrals").fetchall()
        self.assertEqual(len(links),1)
        # The handler returns True for the successful registration only.
        self.assertEqual(sum(results),1)




    def test_actual_achievement_claim_handler_is_exactly_once_under_contention(self):
        import main
        from unittest.mock import patch
        with self.connect() as c:
            c.execute("CREATE TABLE staged_achievement_claims(player_id text,track text,threshold integer,xp integer,claimed_at double precision,PRIMARY KEY(player_id,track,threshold))")
        def run_claim(_):
            try:
                return main.claim_staged_achievement(main.Request(item="feathers"),"Bearer test")["xp_awarded"]
            except main.HTTPException as exc:
                if exc.status_code == 409:
                    return 0
                raise
        with patch.object(main, "db", side_effect=self.connect), patch.object(main, "person", side_effect=lambda c,*a: {"id":"buyer"}), patch.object(main, "advance", side_effect=lambda c,p:p), patch.object(main.achievement_counters, "count", return_value=1):
            with ThreadPoolExecutor(max_workers=8) as pool:
                results=list(pool.map(run_claim,range(12)))
        self.assertEqual(sum(results),10)
        self.assertEqual(results.count(10),1)
        with self.connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) AS n FROM staged_achievement_claims").fetchone()["n"],1)
            self.assertEqual(c.execute("SELECT SUM(xp) AS n FROM staged_achievement_claims").fetchone()["n"],10)

    def test_actual_daily_claim_handler_is_exactly_once_under_contention(self):
        import main
        from unittest.mock import patch
        with self.connect() as c:
            c.execute("CREATE TABLE daily_claims(player_id text,day text,claim text,amount integer,PRIMARY KEY(player_id,day,claim))")
            c.execute("CREATE TABLE daily_activity(player_id text,day text,grain_bought integer,eggs_produced integer,eggs_listed integer)")
            c.execute("CREATE TABLE reward_emission(id integer PRIMARY KEY,total_minted integer)")
            c.execute("INSERT INTO reward_emission VALUES(1,0)")
            c.execute("INSERT INTO daily_activity VALUES('buyer',CURRENT_DATE::text,5,0,0)")
            c.execute("UPDATE players SET coins=0 WHERE id='buyer'")
        def run_claim(_):
            try:
                return main.claim_reward(main.Request(item="grain"), "Bearer test")["awarded"]
            except main.HTTPException as exc:
                if exc.status_code == 409:
                    return 0
                raise
        with patch.object(main, "db", side_effect=self.connect), patch.object(main, "person", side_effect=lambda c,*a: {"id":"buyer"}), patch.object(main, "advance", side_effect=lambda c,p:p):
            with ThreadPoolExecutor(max_workers=8) as pool:
                results=list(pool.map(run_claim, range(12)))
        amount = main.REWARD_AMOUNTS["grain"]
        self.assertEqual(sum(results),amount)
        self.assertEqual(results.count(amount),1)
        with self.connect() as c:
            self.assertEqual(c.execute("SELECT coins FROM players WHERE id='buyer'").fetchone()["coins"],amount)
            self.assertEqual(c.execute("SELECT total_minted FROM reward_emission WHERE id=1").fetchone()["total_minted"],amount)
            self.assertEqual(c.execute("SELECT COUNT(*) AS n FROM daily_claims").fetchone()["n"],1)
            self.assertEqual(c.execute("SELECT COUNT(*) AS n FROM money_log WHERE kind='daily_reward'").fetchone()["n"],1)

    def test_actual_weekly_claim_handler_is_exactly_once_under_contention(self):
        import main
        from unittest.mock import patch
        with self.connect() as c:
            c.execute("CREATE TABLE weekly_claims(player_id text,week text,claimed_at double precision,amount integer,PRIMARY KEY(player_id,week))")
            c.execute("CREATE TABLE daily_activity(player_id text,day text,grain_bought integer,eggs_produced integer,eggs_listed integer)")
            c.execute("CREATE TABLE farm_events(player_id text,kind text,amount integer,created double precision)")
            c.execute("CREATE TABLE market_trade_audit(seller_id text,quantity integer,created double precision)")
            c.execute("CREATE TABLE reward_emission(id integer PRIMARY KEY,total_minted integer)")
            c.execute("INSERT INTO reward_emission VALUES(1,0)")
            c.execute("INSERT INTO daily_activity VALUES('buyer',CURRENT_DATE::text,10,10,3)")
            c.execute("UPDATE players SET coins=0 WHERE id='buyer'")
        # Patching module globals is process-wide; run workers with the same
        # stable patch, not overlapping per-thread patch contexts.
        def run_claim(_):
            try:
                return main.claim_weekly("Bearer test")["awarded"]
            except main.HTTPException as exc:
                if exc.status_code == 409:
                    return 0
                raise
        with patch.object(main, "db", side_effect=self.connect), patch.object(main, "person", side_effect=lambda c,*a: {"id":"buyer"}), patch.object(main.farm_expansion, "progress", return_value={}):
            with ThreadPoolExecutor(max_workers=8) as pool:
                results=list(pool.map(run_claim, range(12)))
        self.assertEqual(sum(results),30)
        self.assertEqual(results.count(30),1)
        with self.connect() as c:
            self.assertEqual(c.execute("SELECT coins FROM players WHERE id='buyer'").fetchone()["coins"],30)
            self.assertEqual(c.execute("SELECT total_minted FROM reward_emission WHERE id=1").fetchone()["total_minted"],30)
            self.assertEqual(c.execute("SELECT COUNT(*) AS n FROM weekly_claims").fetchone()["n"],1)
            self.assertEqual(c.execute("SELECT COUNT(*) AS n FROM money_log WHERE kind='weekly_reward'").fetchone()["n"],1)


if __name__ == '__main__':
    unittest.main()
