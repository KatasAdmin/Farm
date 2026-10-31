import unittest
from production_v4 import forecast,simulate,CYCLE,FEATHER_INTERVAL
from test_continuous_production import farm

class NextEggTests(unittest.TestCase):
    def test_mixed_flock_timer_predicts_first_real_egg(self):
        p=dict(farm(2),geese=1,fed_geese=1)
        f=forecast(p,100000)
        self.assertTrue(f['next_egg_scheduled'])
        self.assertAlmostEqual(f['seconds_to_next_egg'],4320)
        self.assertEqual(simulate(p,100000+4319)[1],0)
        self.assertEqual(simulate(p,100000+4320)[1],1)
    def test_feed_boundary_stops_false_promises(self):
        p=dict(farm(0,grain=0),geese=1,fed_geese=1,last_tick=100000-17*3600)
        f=forecast(p,100000)
        self.assertEqual(f['eggs_next_6h'],0)
        self.assertFalse(f['next_egg_scheduled'])
        self.assertEqual(f['next_egg_status'],'needs_feed')
    def test_hungry_goose_waits_for_the_shared_feed(self):
        p=dict(farm(0,grain=2),geese=1,fed_geese=0,last_tick=100000-17*3600)
        f=forecast(p,100000)
        self.assertTrue(f['next_egg_scheduled'])
        self.assertEqual(f['seconds_to_next_egg'],3*3600)
    def test_autobuy_can_accumulate_two_grain_across_feeds(self):
        p=dict(farm(0,grain=0),geese=1,fed_geese=0,autobuy_enabled=True,autobuy_amount=1,coins=4)
        f=forecast(p,100000)
        self.assertEqual(f['seconds_to_next_egg'],38*3600)
    def test_full_warehouse_has_no_false_timer_and_feeding_can_free_space(self):
        p=dict(farm(0,grain=0,eggs=100),geese=1,fed_geese=1,storage_level=1)
        f=forecast(p,100000)
        self.assertFalse(f['next_egg_scheduled']);self.assertEqual(f['next_egg_status'],'storage_full')
        p.update(grain=2,eggs=98)
        f=forecast(p,100000)
        self.assertTrue(f['next_egg_scheduled']);self.assertEqual(f['seconds_to_next_egg'],20*3600)
    def test_feather_can_take_last_slot_before_an_egg(self):
        p=dict(farm(0,grain=0,eggs=99),geese=1,fed_geese=1,storage_level=1,feather_progress=FEATHER_INTERVAL-3600)
        f=forecast(p,100000)
        self.assertFalse(f['next_egg_scheduled'])
        self.assertEqual(simulate(p,100000+7200)[0]['feathers'],1)
    def test_no_birds_and_repeated_forecasts_do_not_mutate_resources(self):
        p=dict(farm(0,grain=0),geese=0,fed_geese=0)
        old=dict(p);f=forecast(p,100000)
        self.assertFalse(f['next_egg_scheduled']);self.assertEqual(f['next_egg_status'],'empty')
        self.assertEqual(f,forecast(p,100000));self.assertEqual(p,old)
    def test_partial_feed_changes_mixed_flock_rate_before_the_egg(self):
        p=dict(farm(1,grain=1),geese=1,fed_geese=1,last_tick=100000-17.5*3600)
        f=forecast(p,100000)
        self.assertEqual(f['seconds_to_next_egg'],16200)
        self.assertEqual(simulate(p,100000+16199)[1],0)
        self.assertEqual(simulate(p,100000+16200)[1],1)
