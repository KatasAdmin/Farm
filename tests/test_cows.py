import unittest
from unittest.mock import patch
import main
from production_v4 import simulate,forecast,MILK_INTERVAL,MILK_PRICE,COW_PRICE
from test_continuous_production import farm
import test_money_provenance as market_base


def dairy(**changes):
    return dict(dict(farm(0,grain=1000),cows=1,fed_cows=1,milk=0,milk_progress=0,storage_level=50,cowshed_level=1),**changes)

class CowProductionTests(unittest.TestCase):
    def test_price_food_and_twenty_day_payback_by_actual_timer(self):
        p=dairy();q,_,_=simulate(p,100000+20*86400)
        self.assertEqual(COW_PRICE,500);self.assertEqual(MILK_PRICE,11)
        self.assertEqual(q['milk'],60);self.assertEqual(p['grain']-q['grain'],78)
        self.assertEqual(q['milk']*11-2*(p['grain']-q['grain']),504)
        before=simulate(p,100000+20*86400-1)[0]
        self.assertLess(before['milk']*11-2*(p['grain']-before['grain']),500)
        for elapsed_phase in (0,6*3600,17*3600):
            p=dairy(last_tick=100000-elapsed_phase)
            q=simulate(p,100000+20*86400+MILK_INTERVAL)[0]
            self.assertGreaterEqual(q['milk']*11-2*(p['grain']-q['grain']),500)
    def test_first_milk_multiple_cows_and_no_duplicate_collection(self):
        p=dairy(cows=4,fed_cows=4)
        self.assertEqual(simulate(p,100000+7199)[0]['milk'],0)
        q=simulate(p,100000+7200)[0];self.assertEqual(q['milk'],1)
        self.assertEqual(simulate(q,100000+7200)[0],q)
    def test_shared_feed_and_hunger_pause_milk_progress(self):
        p=dairy(grain=3)
        q=simulate(p,100000+18*3600)[0]
        self.assertEqual((q['grain'],q['fed_cows'],q['milk']),(0,1,2))
        q=simulate(q,100000+36*3600)[0]
        self.assertEqual(q['fed_cows'],0)
        r=simulate(q,100000+40*3600)[0]
        self.assertEqual((r['milk'],r['milk_progress']),(q['milk'],q['milk_progress']))
    def test_hungry_cow_forecast_waits_for_shared_feeding(self):
        p=dairy(grain=3,fed_cows=0,last_tick=100000-17*3600)
        f=forecast(p,100000)
        self.assertTrue(f['next_milk_scheduled']);self.assertEqual(f['seconds_to_next_milk'],9*3600)
        self.assertEqual(f['grain_required_next_feed'],3)
    def test_no_grain_means_no_false_milk_timer(self):
        p=dairy(grain=0,fed_cows=0)
        self.assertFalse(forecast(p,100000)['next_milk_scheduled'])
        self.assertEqual(simulate(p,100000+4*86400)[0]['milk'],0)
    def test_autobuy_one_grain_accumulates_without_partial_cow_feeding(self):
        p=dairy(grain=0,fed_cows=0,autobuy_enabled=True,autobuy_amount=1,coins=6)
        q=simulate(p,100000+54*3600)[0]
        self.assertEqual((q['grain'],q['fed_cows'],q['coins']),(0,1,0))
        self.assertEqual(forecast(p,100000)['seconds_to_next_milk'],62*3600)
    def test_milk_and_eggs_compete_by_event_time_not_login_frequency(self):
        p=dairy(chickens=1,fed_hens=1,cows=1,fed_cows=1,grain=0,eggs=99,storage_level=1,milk_progress=MILK_INTERVAL-3600)
        q=simulate(p,100000+8*3600)[0]
        r=simulate(simulate(p,100000+1800)[0],100000+8*3600)[0]
        self.assertEqual((q['eggs'],q['milk']),(99,1))
        for k in ('milk','milk_progress','egg_progress','eggs','grain'):self.assertAlmostEqual(q[k],r[k],places=6)
        self.assertFalse(forecast(dict(p,milk_progress=0),100000)['next_milk_scheduled'])
    def test_chunked_mixed_farm_matches_one_offline_catchup(self):
        p=dairy(chickens=3,fed_hens=3,geese=2,fed_geese=2,cows=2,fed_cows=2,feathers=0,feather_progress=0)
        q=simulate(p,100000+7*86400)[0];r=p
        for t in range(100000+1800,100000+7*86400+1,1800):r=simulate(r,t)[0]
        for k in ('milk','milk_progress','eggs','grain','coins','feathers','feather_progress','fed_cows'):self.assertAlmostEqual(q[k],r[k],places=5)
    def test_full_storage_and_long_starvation_never_overflow_or_go_negative(self):
        p=dairy(grain=0,milk=100,storage_level=1)
        q=simulate(p,100000+50*86400)[0]
        self.assertLessEqual(q['milk']+q['grain']+q['eggs']+q.get('feathers',0),100)
        self.assertGreaterEqual(q['cows'],0);self.assertLessEqual(q['fed_cows'],q['cows'])
    def test_committed_milk_gain_is_logged_once(self):
        class C:
            def __init__(self):self.logs=[]
            def execute(self,sql,args=()):self.logs.append((sql,args));return self
            def fetchall(self):return []
        c=C();p=dairy()
        with patch.object(main,'update_incubation',side_effect=lambda c,p,now:p):
            q=main.advance(c,p,100000+8*3600);main.advance(c,q,100000+8*3600)
        gains=[a for sql,a in c.logs if sql.startswith('INSERT INTO farm_events') and a[2]=='milk_produced']
        self.assertEqual(len(gains),1);self.assertEqual(gains[0][3],1)

class CowTradingTests(unittest.TestCase):
    def setUp(self):
        self.f=market_base.MarketProvenanceTests();self.f.setUp();self.c=self.f.c
        self.c.raw.create_function('LEAST',2,min)
        for key in ('cows','fed_cows','cow_xp','cowshed_level','chickens','geese'):
            self.c.execute('ALTER TABLE players ADD COLUMN '+key+' int DEFAULT '+('1' if key=='cowshed_level' else '0'))
        self.c.execute('ALTER TABLE players ADD COLUMN milk int DEFAULT 0')
        self.c.execute('CREATE TABLE economy(id int,treasury int)');self.c.execute('INSERT INTO economy VALUES(1,10000)')
        self.c.raw.commit()
    def test_buy_cow_price_capacity_shared_clock_and_bonus_buyback(self):
        self.f.credit('a','stars_purchase',1500,'paid')
        with patch.object(main,'db',return_value=self.c),patch.object(main,'person',side_effect=lambda *a:self.f.p('a')),patch.object(main,'advance',side_effect=lambda c,p:p):
            with self.assertRaises(main.HTTPException):main.shop(main.Request(item='cows',amount=1,expected_price=1),'Bearer a')
            main.shop(main.Request(item='cows',amount=2,expected_price=500),'Bearer a')
            p=self.f.p('a');self.assertEqual((p['cows'],p['fed_cows'],p['coins']),(2,2,500))
            with self.assertRaises(main.HTTPException):main.shop(main.Request(item='cows',amount=1,expected_price=500),'Bearer a')
            main.sell_to_system(main.Request(item='cows',amount=1),'Bearer a')
            p=self.f.p('a');self.assertEqual((p['cows'],p['fed_cows'],p['coins']),(1,1,750))
            self.assertEqual(main.farm_wallet.balances(self.c,p),{'bonus':250,'purchased':500,'earned':0})
    def test_milk_fixed_price_market_bonus_provenance_and_storage_check(self):
        self.c.execute("UPDATE players SET milk=10 WHERE id='b'");self.c.raw.commit()
        with patch.object(main,'db',return_value=self.c),patch.object(main,'person',side_effect=lambda *a:self.f.p('b')),patch.object(main,'advance',side_effect=lambda c,p:p):
            main.sell(main.Request(item='milk',amount=10,price=1),'Bearer b')
            with self.assertRaises(main.HTTPException):main.sell_to_system(main.Request(item='milk',amount=1),'Bearer b')
        self.assertEqual(self.c.execute('SELECT price FROM market').fetchone()['price'],11)
        self.f.credit('a','promo_reward',110,'bonus')
        with patch.object(main,'db',return_value=self.c),patch.object(main,'person',side_effect=lambda *a:self.f.p('a')),patch.object(main,'advance',side_effect=lambda c,p:p):
            main.buy(main.Request(item='milk',amount=10),'Bearer a')
        self.assertEqual(self.f.p('a')['milk'],10)
        self.assertEqual(main.farm_wallet.balances(self.c,self.f.p('b'))['bonus'],110)
        self.assertEqual(main.farm_wallet.available(self.c,self.f.p('b')),0)

class HundredLevelTests(unittest.TestCase):
    def test_hundred_level_limits_incubator_durations_and_costs(self):
        self.assertEqual(main.MAX_BUILDING_LEVEL,100)
        self.assertEqual(main.coop_limit({'coop_level':100}),1000)
        self.assertEqual(main.storage_limit({'storage_level':100}),10000)
        self.assertEqual(main.cowshed_limit({'cowshed_level':100}),200)
        self.assertEqual(set(main.INCUBATOR_UPGRADE_COST),set(range(1,100)))
        for level in range(1,101):
            a,b=main.incubation_stages(level);self.assertGreater(a,0);self.assertGreater(b,0)
        for kind in ('coop','storage','cowshed'):
            self.assertGreater(main.upgrade_cost(kind,99),main.upgrade_cost(kind,9))
