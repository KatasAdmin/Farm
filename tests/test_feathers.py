import unittest
from unittest.mock import patch
from fastapi import HTTPException
import main
from production_v4 import simulate,forecast,FEATHER_INTERVAL
import test_geese as geese_base

class FeatherProductionTests(unittest.TestCase):
    def farm(self,**changes):
        return dict(geese_base.GeeseTests().birdfarm(0,1,grain=1000),storage_level=50,**changes)
    def test_one_feather_per_seven_fed_goose_days_and_no_polling_duplicates(self):
        p=self.farm()
        before=simulate(p,100000+FEATHER_INTERVAL-1)[0]
        self.assertEqual(before['feathers'],0)
        end=simulate(before,100000+FEATHER_INTERVAL)[0]
        self.assertEqual(end['feathers'],1)
        self.assertEqual(simulate(end,100000+FEATHER_INTERVAL)[0],end)
        end['feathers']=0
        self.assertEqual(simulate(end,100000+FEATHER_INTERVAL)[0]['feathers'],0)
    def test_hungry_geese_do_not_make_feathers(self):
        p=dict(self.farm(),grain=0,fed_geese=0)
        end=simulate(p,100000+FEATHER_INTERVAL)[0]
        self.assertEqual((end['feathers'],end['feather_progress']),(0,0))
    def test_multiple_geese_pool_rare_resource_production(self):
        p=dict(self.farm(),geese=2,fed_geese=2)
        self.assertEqual(simulate(p,100000+FEATHER_INTERVAL/2)[0]['feathers'],1)
    def test_last_slot_is_allocated_by_event_time_not_login_frequency(self):
        for feather_due,expected_eggs,expected_feathers in [(3600,99,1),(7200,100,0)]:
            p=dict(self.farm(),storage_level=1,grain=0,eggs=99,feather_progress=FEATHER_INTERVAL-feather_due)
            one=simulate(p,100000+7200)[0]
            split=simulate(simulate(p,100000+1800)[0],100000+7200)[0]
            self.assertEqual((one['eggs'],one['feathers']),(expected_eggs,expected_feathers))
            for k in ('eggs','feathers','grain','feather_progress'):
                self.assertAlmostEqual(one[k],split[k],places=6)
            self.assertLessEqual(one['eggs']+one['grain']+one['feathers'],100)
    def test_feathers_use_warehouse_space_and_forecast_is_read_only(self):
        p=dict(self.farm(),grain=0,eggs=99,feathers=1,storage_level=1)
        before=dict(p);f=forecast(p,100000)
        self.assertEqual(f['eggs_next_6h'],0);self.assertEqual(p,before)
    def test_24_day_net_payback_excludes_additional_feather_revenue(self):
        p=self.farm();end,n,_=simulate(p,100000+24*86400)
        net_eggs=n-2*(p['grain']-end['grain'])
        self.assertEqual(net_eggs,160)
        self.assertEqual(end['feathers'],3)
        self.assertEqual(net_eggs+end['feathers']*5,175)

class FeatherSalesTests(unittest.TestCase):
    def setUp(self):
        self.base=geese_base.GooseTradingTests();self.base.setUp();self.c=self.base.c
        self.c.execute('ALTER TABLE players ADD COLUMN feathers int DEFAULT 0')
        self.c.execute('CREATE TABLE market(id text,seller text,item text,quantity int,price int)')
        self.c.execute("UPDATE players SET feathers=2 WHERE id='p'");self.c.raw.commit()
    def test_sale_at_five_and_cannot_resell_consumed_stock(self):
        with patch.object(main,'db',return_value=self.c),patch.object(main,'person',side_effect=self.base.player),patch.object(main,'advance',side_effect=lambda c,p:p):
            result=main.sell_to_system(main.Request(item='feathers',amount=2),'Bearer p')
            self.assertEqual(result['received'],10)
            self.assertEqual(self.base.player()['coins'],510)
            self.assertEqual(self.base.player()['feathers'],0)
            with self.assertRaises(HTTPException):main.sell_to_system(main.Request(item='feathers',amount=1),'Bearer p')
        self.assertEqual(self.c.execute('SELECT treasury FROM economy').fetchone()['treasury'],990)
        self.assertEqual(len(self.c.execute('SELECT * FROM money_log').fetchall()),1)
    def test_feathers_also_block_new_grain_when_warehouse_is_full(self):
        p=dict(self.base.player(),grain=98,eggs=0,feathers=2,storage_level=1)
        with patch.object(main,'db',return_value=self.c),patch.object(main,'person',return_value=p),patch.object(main,'advance',return_value=p):
            with self.assertRaises(HTTPException) as error:main.shop(main.Request(item='grain',amount=1),'Bearer p')
        self.assertEqual(error.exception.status_code,400)
        self.assertEqual(self.base.player()['coins'],500)
