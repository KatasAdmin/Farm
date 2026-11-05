"""Transactional market tests on the repository's SQLite compatibility fixture."""
import unittest
from unittest.mock import patch

import animal_market
import main
from test_money_provenance import MarketProvenanceTests


class AnimalMarketTransactions(unittest.TestCase):
    def setUp(self):
        base = MarketProvenanceTests()
        base.setUp()
        self.base, self.c = base, base.c
        self.c.raw.create_function('LEAST', 2, min)
        for name, default in (
            ('chickens', 0), ('geese', 0), ('cows', 0),
            ('fed_hens', 0), ('fed_geese', 0), ('fed_cows', 0),
            ('coop_level', 10), ('cowshed_level', 10), ('farmer_level', 3),
            ('goose_xp', 0), ('cow_xp', 0), ('milk', 0),
        ):
            self.c.execute(f'ALTER TABLE players ADD COLUMN {name} int DEFAULT {default}')
        self.c.execute('CREATE TABLE animal_market_balances(player_id text,item text,fraction_units bigint DEFAULT 0,ad_units bigint DEFAULT 0,coin_fraction_units bigint DEFAULT 0,PRIMARY KEY(player_id,item))')
        self.c.execute('CREATE TABLE animal_market_listings(id text PRIMARY KEY,seller text,item text,quantity_units bigint,ad_units bigint,price int,coins_received bigint DEFAULT 0,created real)')
        self.c.execute('CREATE TABLE animal_market_trades(id text,order_id text,listing_id text,buyer_id text,seller_id text,item text,share_units bigint,coin_units bigint,coins int,created real)')
        self.c.execute('CREATE TABLE animal_market_cash_escrow(id int PRIMARY KEY,coins bigint)')
        self.c.execute('INSERT INTO animal_market_cash_escrow VALUES(1,0)')
        self.c.execute('CREATE TABLE economy(id int,treasury bigint)')
        self.c.execute('INSERT INTO economy VALUES(1,0)')
        self.c.execute('CREATE TABLE daily_activity(player_id text,day text,eggs_produced int DEFAULT 0,PRIMARY KEY(player_id,day))')
        self.c.raw.commit()

    def run_as(self, player, fn, *args):
        with patch.object(main, 'db', return_value=self.c), patch.object(main, 'person', side_effect=lambda *_: self.base.p(player)), patch.object(main, 'advance', side_effect=lambda c,p,*rest:p):
            return fn(*args, 'Bearer ' + player)

    def offer(self, player, item, amount):
        return self.run_as(player, main.sell, main.Request(item=item, amount=amount, price=main.ANIMAL_MARKET_PRICES[item]))['listing_id']

    def buy(self, player, item, amount):
        return self.run_as(player, main.shop, main.Request(item=item, amount=amount, expected_price=main.ANIMAL_MARKET_PRICES[item]))

    def total_units(self, item):
        whole = sum(self.base.p(pid)[item] for pid in ('a','b','c','d')) * animal_market.SCALE
        fractions = self.c.execute('SELECT COALESCE(SUM(fraction_units),0) AS n FROM animal_market_balances WHERE item=%s', (item,)).fetchone()['n']
        return whole + fractions

    def test_split_7_3_then_cancel_whole_and_buy_remaining(self):
        self.c.execute("UPDATE players SET chickens=7,fed_hens=7 WHERE id='b'")
        self.c.execute("UPDATE players SET chickens=3,fed_hens=3 WHERE id='c'")
        self.c.raw.commit()
        self.base.credit('a','stars_purchase',400,'funded')
        first, second = self.offer('b','chickens',7), self.offer('c','chickens',3)
        self.assertEqual(self.total_units('chickens'),10*animal_market.SCALE)
        response=self.buy('a','chickens',1)
        self.assertEqual(response['from_players'],1)
        self.assertEqual((self.base.p('b')['chickens'],self.base.p('c')['chickens']), (6,2))
        self.assertEqual(self.base.p('a')['chickens'],1)
        self.assertEqual(self.total_units('chickens'),10*animal_market.SCALE)
        shares=self.c.execute('SELECT seller_id,share_units FROM animal_market_trades ORDER BY seller_id').fetchall()
        self.assertEqual([(r['seller_id'],r['share_units']) for r in shares],[('b',700_000_000),('c',300_000_000)])
        self.assertEqual((self.base.p('b')['coins'],self.base.p('c')['coins']),(28,12))
        self.assertEqual((self.base.p('b')['fed_hens'],self.base.p('c')['fed_hens']),(6,2))
        # A second whole purchase combines the seller fractions with a whole animal.
        self.buy('a','chickens',1)
        self.assertEqual(self.total_units('chickens'),10*animal_market.SCALE)
        self.assertEqual(self.base.p('a')['chickens'],2)
        self.assertEqual(sum(self.base.p(pid)['coins'] for pid in ('a','b','c','d'))+self.c.execute('SELECT coins FROM animal_market_cash_escrow').fetchone()['coins']+self.c.execute('SELECT treasury FROM economy').fetchone()['treasury'],400)

    def test_market_first_system_shortfall_and_no_system_buyback(self):
        self.c.execute("UPDATE players SET cows=1,fed_cows=1 WHERE id='b'")
        self.c.raw.commit()
        self.base.credit('a','stars_purchase',1500,'funded')
        self.offer('b','cows',1)
        result=self.buy('a','cows',3)
        self.assertEqual((result['from_players'],result['from_system']),(1,2))
        self.assertEqual((self.base.p('a')['cows'],self.base.p('b')['cows']),(3,0))
        self.assertEqual(self.c.execute('SELECT treasury FROM economy').fetchone()['treasury'],1000)
        with self.assertRaises(main.HTTPException):self.run_as('a',main.sell_to_system,main.Request(item='cows',amount=1))

    def test_cancel_whole_and_explicitly_close_stranded_fractions(self):
        self.c.execute("UPDATE players SET chickens=7,fed_hens=7 WHERE id='b'")
        self.c.execute("UPDATE players SET chickens=3,fed_hens=3 WHERE id='c'")
        self.c.raw.commit()
        self.base.credit('a','stars_purchase',40,'buyer-funded')
        self.base.credit('b','stars_purchase',28,'b-funded')
        self.base.credit('c','stars_purchase',12,'c-funded')
        b=self.offer('b','chickens',7);c=self.offer('c','chickens',3)
        self.buy('a','chickens',1)
        self.assertEqual(self.run_as('b',main.cancel_listing,b)['returned'],6)
        self.assertEqual(self.run_as('c',main.cancel_listing,c)['returned'],2)
        self.assertEqual(self.c.execute('SELECT quantity_units FROM animal_market_listings WHERE id=%s',(b,)).fetchone()['quantity_units'],300_000_000)
        with self.assertRaises(main.HTTPException):self.run_as('b',main.cancel_listing,b)
        self.assertEqual(self.run_as('b',main.redeem_animal_fraction,'chickens')['spent'],28)
        self.assertEqual(self.run_as('c',main.redeem_animal_fraction,'chickens')['spent'],12)
        self.assertEqual(self.total_units('chickens'),11*animal_market.SCALE)
        self.assertEqual(self.c.execute('SELECT treasury FROM economy').fetchone()['treasury'],40)
        self.assertEqual(self.c.execute('SELECT SUM(quantity_units) AS n FROM animal_market_listings').fetchone()['n'],0)

    def test_goose_purchase_and_no_phantom_coin_after_fractional_repeats(self):
        self.c.execute("UPDATE players SET geese=7,fed_geese=7 WHERE id='b'")
        self.c.execute("UPDATE players SET geese=3,fed_geese=3 WHERE id='c'")
        self.c.raw.commit()
        self.base.credit('a','stars_purchase',1600,'funded')
        self.offer('b','geese',7);self.offer('c','geese',3)
        for _ in range(10):self.buy('a','geese',1)
        self.assertEqual(self.total_units('geese'),10*animal_market.SCALE)
        self.assertEqual(self.base.p('a')['geese'],10)
        total=sum(self.base.p(pid)['coins'] for pid in ('a','b','c','d'))
        total+=self.c.execute('SELECT coins FROM animal_market_cash_escrow').fetchone()['coins']
        total+=self.c.execute('SELECT treasury FROM economy').fetchone()['treasury']
        self.assertEqual(total,1600)

    def test_ten_sellers_repeated_small_orders_preserve_cash_escrow(self):
        for i in range(10):
            self.c.execute('INSERT INTO players(id,coins,grain,eggs,feathers,storage_level,chickens,fed_hens) VALUES(%s,0,0,0,0,100,%s,%s)',(f's{i}',i+1,i+1))
        self.c.raw.commit()
        self.base.credit('a','stars_purchase',2200,'funded-ten')
        for i in range(10):self.offer(f's{i}','chickens',i+1)
        for _ in range(55):self.buy('a','chickens',1)
        self.assertEqual(self.base.p('a')['chickens'],55)
        self.assertEqual(self.c.execute('SELECT SUM(chickens) AS n FROM players').fetchone()['n'],55)
        self.assertEqual(self.c.execute('SELECT SUM(fraction_units) AS n FROM animal_market_balances').fetchone()['n'],0)
        self.assertEqual(self.c.execute('SELECT SUM(coins) AS n FROM players').fetchone()['n']+self.c.execute('SELECT coins FROM animal_market_cash_escrow').fetchone()['coins'],2200)
        self.assertEqual(self.c.execute('SELECT coins FROM animal_market_cash_escrow').fetchone()['coins'],0)

    def test_base_incubator_takes_twenty_eggs_and_zero_coins(self):
        self.c.execute('ALTER TABLE players ADD COLUMN incubator_owned int DEFAULT 0')
        self.c.execute('ALTER TABLE players ADD COLUMN incubator_level int DEFAULT 1')
        self.c.execute('CREATE TABLE incubation_jobs(id text,player_id text,started real,hatch_at real,mature_at real)')
        self.c.execute("UPDATE players SET eggs=25 WHERE id='a'")
        self.c.raw.commit()
        self.assertEqual(self.run_as('a',main.incubator_action,main.Request(item='buy'))['spent'],0)
        self.run_as('a',main.incubator_action,main.Request(item='start'))
        self.assertEqual((self.base.p('a')['coins'],self.base.p('a')['eggs'],self.base.p('a')['incubator_level']),(0,5,1))
        self.assertEqual(self.c.execute('SELECT COUNT(*) AS n FROM incubation_jobs').fetchone()['n'],1)


if __name__ == '__main__':unittest.main()
