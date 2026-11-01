import random
import unittest
from production_v4 import forecast, simulate, feed_required
from test_cows import dairy

NOW=100000
FEED=18*3600

class FeedEconomyAudit(unittest.TestCase):
    def test_cow_purchase_reduces_whole_herd_reserve_and_changes_ration(self):
        before=dairy(chickens=20,fed_hens=20,geese=2,fed_geese=2,cows=0,fed_cows=0,grain=48,coins=1000)
        after=dict(before,cows=1,fed_cows=1,coins=before['coins']-500)
        a,b=forecast(before,NOW),forecast(after,NOW)
        self.assertEqual((a['grain_required_next_feed'],b['grain_required_next_feed']),(24,27))
        self.assertEqual((a['feed_stock_seconds'],b['feed_stock_seconds']),(3*FEED,2*FEED))
        self.assertEqual((a['complete_feeds_available'],b['complete_feeds_available']),(2,1))
        fed=simulate(after,NOW+FEED)[0]
        self.assertEqual((fed['grain'],fed['fed_hens'],fed['fed_geese'],fed['fed_cows']),(21,20,2,1))

    def test_shortage_is_extra_grain_needed_not_entire_unfed_cow_ration(self):
        for grain in range(3):
            with self.subTest(grain=grain):
                f=forecast(dairy(grain=grain),NOW)
                self.assertEqual(f['effective_grain_shortage'],3-grain)
        f=forecast(dairy(chickens=2,fed_hens=2,geese=1,fed_geese=1,grain=6),NOW)
        self.assertEqual(f['grain_required_next_feed'],7)
        self.assertEqual(f['effective_grain_shortage'],1)

    def test_small_autobuy_shortage_and_budget_are_exact(self):
        for coins,expected in ((0,2),(2,1)):
            f=forecast(dairy(grain=1,autobuy_enabled=True,autobuy_amount=1,coins=coins),NOW)
            self.assertEqual(f['effective_grain_shortage'],expected)
        f=forecast(dairy(grain=1,autobuy_enabled=True,autobuy_amount=2,coins=4),NOW)
        self.assertEqual(f['effective_grain_shortage'],0)

    def test_cow_only_and_no_animal_reserve(self):
        f=forecast(dairy(grain=6,last_tick=NOW-17*3600),NOW)
        self.assertEqual(f['feed_stock_seconds'],37*3600)
        empty=forecast(dairy(cows=0,fed_cows=0,grain=6),NOW)
        self.assertEqual((empty['grain_required_next_feed'],empty['complete_feeds_available'],empty['feed_stock_seconds']),(0,0,0))

    def test_reserve_boundary_matches_first_incomplete_feed(self):
        for hens,geese,cows in ((0,0,1),(1,0,0),(0,1,0),(20,2,3)):
            p=dairy(chickens=hens,fed_hens=hens,geese=geese,fed_geese=geese,cows=cows,fed_cows=cows)
            required=feed_required(p)
            for remainder in (0,required-1):
                p['grain']=required*2+remainder
                f=forecast(p,NOW)
                self.assertEqual(f['feed_stock_seconds'],3*FEED)
                q=simulate(p,NOW+3*FEED-1)[0]
                self.assertEqual((q['fed_hens'],q['fed_geese'],q['fed_cows']),(hens,geese,cows))
                q=simulate(p,NOW+3*FEED)[0]
                self.assertLess(q['fed_hens']+2*q['fed_geese']+3*q['fed_cows'],required)

    def test_random_mixed_farms_conserve_money_and_match_login_frequency(self):
        rng=random.Random(311)
        for case in range(100):
            hens,geese,cows=(rng.randrange(16),rng.randrange(6),rng.randrange(5))
            p=dairy(chickens=hens,fed_hens=rng.randrange(hens+1),geese=geese,fed_geese=rng.randrange(geese+1),cows=cows,fed_cows=rng.randrange(cows+1),grain=rng.randrange(150),eggs=rng.randrange(200),milk=rng.randrange(20),storage_level=5,coins=rng.randrange(300),autobuy_enabled=bool(rng.randrange(2)),autobuy_amount=rng.randrange(1,81))
            end=NOW+rng.randrange(1,12*86400)
            whole,_,refills=simulate(p,end)
            chunk=p;chunks=[]
            for t in list(range(NOW+3600,end,3600))+[end]:
                chunk,_,r=simulate(chunk,t);chunks+=r
            with self.subTest(case=case):
                for key in ('grain','eggs','milk','feathers','coins','fed_hens','fed_geese','fed_cows','satiety'):
                    self.assertEqual(whole[key],chunk[key],key)
                    self.assertGreaterEqual(whole[key],0,key)
                self.assertEqual(refills,chunks)
                self.assertEqual(p['coins']-whole['coins'],2*sum(refills))
                self.assertLessEqual(sum(whole[k] for k in ('grain','eggs','milk','feathers')),500)
                self.assertEqual(simulate(whole,end)[0],whole)
