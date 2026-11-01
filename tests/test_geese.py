import unittest
from unittest.mock import patch
from fastapi import HTTPException
import main
from production_v4 import simulate,forecast
from test_continuous_production import farm

class GeeseTests(unittest.TestCase):
    def birdfarm(self,hens=0,geese=1,grain=100):
        return dict(farm(hens,grain=grain),geese=geese,fed_geese=geese,farmer_level=3,goose_xp=0)
    def test_mixed_flock_has_correct_rate_and_next_egg(self):
        p=self.birdfarm(2,1)
        self.assertEqual(simulate(p,100000+6*3600)[1],5)
        self.assertEqual(forecast(p,100000)['seconds_to_next_egg'],4320)
        self.assertEqual(forecast(p,100000)['grain_required_next_feed'],4)
    def test_shared_feeding_consumes_two_grain_per_goose(self):
        p=self.birdfarm(3,2,grain=7)
        after,n,_=simulate(p,100000+18*3600)
        self.assertEqual((after['grain'],after['fed_hens'],after['fed_geese'],n),(0,3,2,27))
        later,n,_=simulate(after,100000+42*3600)
        self.assertEqual(n,27)
        self.assertEqual((later['fed_hens'],later['fed_geese']),(0,0))
    def test_no_half_ration_or_retroactive_eggs(self):
        p=self.birdfarm(0,1,grain=1)
        after,n,_=simulate(p,100000+18*3600)
        self.assertEqual((n,after['grain'],after['fed_geese']),(9,1,0))
        self.assertEqual(simulate(after,100000+24*3600)[1],0)
    def test_mixed_forecast_matches_simulation_with_feed_storage_and_autobuy(self):
        for hens in (0,2):
            for geese in (0,1,3):
                for grain in (0,3,100):
                    for auto in (False,True):
                        p=dict(self.birdfarm(hens,geese,grain),autobuy_enabled=auto,eggs=390)
                        f=forecast(p,100000)
                        for h in (6,12):self.assertEqual(f['eggs_next_'+str(h)+'h'],simulate(p,100000+h*3600)[1])
                        one=simulate(p,100000+30*3600)[0]
                        split=simulate(simulate(p,100000+12*3600)[0],100000+30*3600)[0]
                        for key in ('eggs','grain','coins','fed_hens','fed_geese','chickens','geese'):
                            self.assertEqual(one[key],split[key])
    def test_payback_is_twenty_four_days_after_feed_cost_excluding_feathers(self):
        p=dict(self.birdfarm(0,1,grain=1000),storage_level=50)
        end,n,_=simulate(p,100000+24*86400)
        self.assertEqual(n-2*(p['grain']-end['grain']),main.GOOSE_PRICE)
        self.assertGreater(main.GOOSE_PRICE,main.HEN_PRICE)
    def test_server_rejects_locked_and_overcrowded_goose_purchase(self):
        class DB:
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def execute(self,*args):raise AssertionError('Purchase should be rejected before mutation')
        for level,hens,geese in [(2,0,0),(3,9,1)]:
            p=dict(self.birdfarm(hens,geese),id='p',coins=1000,coop_level=1,farmer_level=level)
            with patch.object(main,'db',return_value=DB()),patch.object(main,'person',return_value=p),patch.object(main,'advance',return_value=p):
                with self.assertRaises(HTTPException):main.shop(main.Request(item='geese',amount=1,expected_price=main.GOOSE_PRICE),'Bearer owner')

class GooseTradingTests(unittest.TestCase):
    def setUp(self):
        from test_task_bot import Database
        self.c=Database()
        self.c.raw.create_function('LEAST',2,min)
        self.c.execute('CREATE TABLE players(id text PRIMARY KEY,coins int,chickens int,geese int,fed_hens int,fed_geese int,goose_xp int,coop_level int,farmer_level int,grain int,eggs int)')
        self.c.execute("INSERT INTO players VALUES('p',500,2,1,2,1,0,1,3,20,0)")
        self.c.execute('CREATE TABLE economy(id int PRIMARY KEY,treasury int)')
        self.c.execute('INSERT INTO economy VALUES(1,1000)')
        self.c.execute('CREATE TABLE money_log(id text,player_id text,kind text,delta int,details text,created double precision)')
        main.farm_wallet.initialize_sources(self.c)
        self.c.raw.commit()
    def player(self,*args):return self.c.execute("SELECT * FROM players WHERE id='p'").fetchone()
    def test_purchase_and_sale_adjust_correct_species_fed_count_coins_and_audit(self):
        with patch.object(main,'db',return_value=self.c),patch.object(main,'person',side_effect=self.player),patch.object(main,'advance',side_effect=lambda c,p:p):
            main.shop(main.Request(item='geese',amount=2,expected_price=main.GOOSE_PRICE),'Bearer p')
            p=self.player()
            self.assertEqual((p['coins'],p['chickens'],p['geese'],p['fed_geese'],p['goose_xp']),(180,2,3,3,40))
            main.sell_to_system(main.Request(item='geese',amount=2),'Bearer p')
            p=self.player()
            self.assertEqual((p['coins'],p['chickens'],p['geese'],p['fed_geese'],p['goose_xp']),(340,2,1,1,40))
            self.assertEqual(main.farm_wallet.available(self.c,p),0)
            self.assertEqual(self.c.execute('SELECT bonus FROM farm_money_sources').fetchone()['bonus'],160)
            with self.assertRaises(HTTPException):main.sell_to_system(main.Request(item='geese',amount=2),'Bearer p')
        self.assertEqual(len(self.c.execute('SELECT * FROM money_log').fetchall()),2)
        self.assertEqual(self.c.execute('SELECT treasury FROM economy').fetchone()['treasury'],1160)

    def test_old_or_missing_price_cannot_charge_the_new_price(self):
        with patch.object(main,'db',return_value=self.c),patch.object(main,'person',side_effect=self.player),patch.object(main,'advance',side_effect=lambda c,p:p):
            for old_price in (None,100):
                with self.assertRaises(HTTPException) as error:main.shop(main.Request(item='geese',amount=1,expected_price=old_price),'Bearer p')
                self.assertEqual(error.exception.status_code,409)
        self.assertEqual(self.player()['coins'],500)
        self.assertFalse(self.c.execute('SELECT * FROM money_log').fetchall())
