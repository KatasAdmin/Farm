import unittest
from production import forecast, simulate, CYCLE
from test_fast_eggs import player
from main import advance
from test_fast_eggs import Database


class ForecastTests(unittest.TestCase):
    def test_one_fed_hen_and_separate_clocks(self):
        f = forecast(player(), 1)
        self.assertEqual((f['eggs_next_6h'], f['eggs_next_12h']), (1, 2))
        self.assertEqual(f['seconds_to_next_egg'], 21599)
        self.assertEqual(f['seconds_to_next_feed'], 64799)
        self.assertEqual(f['grain_required_next_feed'], 1)

    def test_five_fed_hens(self):
        f = forecast(player(chickens=5, fed_hens=5, grain=20), 100)
        self.assertEqual((f['eggs_next_6h'], f['eggs_next_12h']), (5, 10))

    def test_feed_shortage_changes_second_cycle_not_already_fed_eggs(self):
        p = player(chickens=5, fed_hens=5, grain=2, feed_phase=2)
        f = forecast(p, 10)
        self.assertEqual((f['eggs_next_6h'], f['eggs_next_12h']), (5, 7))
        self.assertEqual(f['grain_shortage'], 3)

    def test_zero_grain_currently_fed(self):
        f = forecast(player(grain=0, feed_phase=2), 1)
        self.assertEqual((f['eggs_next_6h'], f['eggs_next_12h']), (1, 1))

    def test_zero_grain_unfed(self):
        f = forecast(player(grain=0, fed_hens=0), 1)
        self.assertEqual((f['eggs_next_6h'], f['eggs_next_12h']), (0, 0))

    def test_no_hens(self):
        f = forecast(player(chickens=0, fed_hens=0), 1)
        self.assertEqual((f['eggs_next_6h'], f['eggs_next_12h']), (0, 0))
        self.assertEqual(f['grain_required_next_feed'], 0)

    def test_full_warehouse_blocks_eggs_until_feeding_frees_space(self):
        f = forecast(player(grain=1, eggs=99, feed_phase=2), 1)
        self.assertEqual((f['eggs_next_6h'], f['eggs_next_12h']), (0, 1))

    def test_autobuy_supplies_future_feeding(self):
        f = forecast(player(grain=0, feed_phase=2, autobuy_enabled=True), 1)
        self.assertEqual((f['eggs_next_6h'], f['eggs_next_12h']), (1, 2))
        self.assertTrue(f['autobuy_expected'])
        self.assertEqual(f['effective_grain_shortage'], 0)

    def test_autobuy_needs_real_coins(self):
        f = forecast(player(grain=0, coins=0, feed_phase=2, autobuy_enabled=True), 1)
        self.assertFalse(f['autobuy_expected'])
        self.assertEqual(f['eggs_next_12h'], 1)

    def test_autobuy_checks_space_after_production(self):
        p = player(grain=0, eggs=80, feed_phase=2, autobuy_enabled=True)
        f = forecast(p, 1)
        self.assertFalse(f['autobuy_expected'])  # 81 eggs + 20 grain cannot fit
        self.assertEqual(f['eggs_next_12h'], 1)

    def test_near_feed_boundary(self):
        p = player(grain=0, feed_phase=2)
        f = forecast(p, CYCLE-1)
        self.assertEqual(f['seconds_to_next_feed'], 1)
        self.assertEqual(f['eggs_next_12h'], 1)

    def test_known_chick_is_conservatively_annotated(self):
        f = forecast(player(), 1, [{'mature_at':100}])
        self.assertTrue(f['forecast_approximate'])
        self.assertEqual(f['known_maturing'], 1)
        self.assertIn('синхронизации', f['forecast_note'])

    def test_forecast_matches_committed_engine_for_all_requested_scenarios(self):
        for hens in (0,1,5):
            for grain in (0,2,20):
                for phase in (0,1,2):
                    for auto in (False,True):
                        for eggs in (0,80,100):
                            p=player(chickens=hens,fed_hens=hens,grain=grain,feed_phase=phase,autobuy_enabled=auto,eggs=eggs)
                            before=dict(p)
                            f=forecast(p, 100)
                            for h in (6,12):
                                actual=advance(Database(),p,100+h*3600)
                                self.assertEqual(f[f'eggs_next_{h}h'],actual['eggs']-p['eggs'])
                            self.assertEqual(p,before)

    def test_return_after_hours_is_idempotent(self):
        p=player(chickens=5,fed_hens=5,grain=20)
        returned=advance(Database(),p,13*3600)
        self.assertEqual(returned['eggs'],10)
        self.assertEqual(advance(Database(),returned,13*3600),returned)
        self.assertEqual(forecast(returned,13*3600)['eggs_next_6h'],5)
