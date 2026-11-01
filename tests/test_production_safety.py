import unittest

from production_v4 import feed_required, simulate, forecast, next_feather_delay, FEATHER_INTERVAL, MILK_INTERVAL


def player(**changes):
    base = {
        "chickens": 1, "geese": 0, "cows": 0,
        "fed_hens": 1, "fed_geese": 0, "fed_cows": 0,
        "grain": 10, "eggs": 0, "milk": 0, "feathers": 0,
        "coins": 100, "storage_level": 1,
        "egg_at": 1.0, "egg_progress": 0.0,
        "feather_progress": 0.0, "milk_progress": 0.0,
        "last_tick": 1.0, "feed_phase": 0,
        "satiety": 100, "critical_cycles": 0,
        "autobuy_amount": 0, "autobuy_enabled": False,
    }
    base.update(changes)
    return base


class ProductionSafetyTest(unittest.TestCase):
    def test_shared_feed_requirements(self):
        self.assertEqual(feed_required(player(chickens=2, geese=3, cows=4)), 20)

    def test_one_fed_hen_produces_one_egg_after_six_hours(self):
        p, produced, refills = simulate(player(), 21601.0)
        self.assertEqual(produced, 1)
        self.assertEqual(p["eggs"], 1)
        self.assertEqual(refills, [])

    def test_no_production_from_unfed_hen(self):
        p, produced, _ = simulate(player(fed_hens=0), 21601.0)
        self.assertEqual(produced, 0)
        self.assertEqual(p["eggs"], 0)

    def test_full_storage_never_overflows(self):
        p, produced, _ = simulate(player(grain=10, eggs=90), 21601.0)
        self.assertEqual(produced, 0)
        self.assertEqual(p["grain"] + p["eggs"] + p["milk"] + p["feathers"], 100)

    def test_fed_cow_produces_milk_at_eight_hours(self):
        p, produced, _ = simulate(player(chickens=0, fed_hens=0, cows=1, fed_cows=1), 28801.0)
        self.assertEqual(produced, 0)
        self.assertEqual(p["milk"], 1)

    def test_fed_goose_produces_three_eggs_in_six_hours(self):
        p, produced, _ = simulate(player(chickens=0, fed_hens=0, geese=1, fed_geese=1), 21601.0)
        self.assertEqual(produced, 3)
        self.assertEqual(p["eggs"], 3)

    def test_shared_feeding_deducts_exact_grain(self):
        p, _, _ = simulate(player(chickens=1, geese=1, cows=1, fed_geese=1, fed_cows=1), 64801.0)
        self.assertEqual(p["grain"], 4)
        self.assertEqual(p["fed_hens"], 1)
        self.assertEqual(p["fed_geese"], 1)
        self.assertEqual(p["fed_cows"], 1)

    def test_feather_not_promised_without_feed(self):
        p = player(chickens=0, fed_hens=0, geese=1, fed_geese=0, grain=0)
        self.assertIsNone(next_feather_delay(p, 1.0))
        self.assertFalse(forecast(p, 1.0)["next_feather_scheduled"])

    def test_feather_due_with_fed_goose(self):
        p = player(chickens=0, fed_hens=0, geese=1, fed_geese=1,
                   feather_progress=FEATHER_INTERVAL - 3600)
        self.assertAlmostEqual(next_feather_delay(p, 1.0), 3600, delta=1)

    def test_full_storage_blocks_milk_and_feathers(self):
        p = player(chickens=0, fed_hens=0, geese=1, fed_geese=1,
                   cows=1, fed_cows=1, grain=100, feather_progress=FEATHER_INTERVAL - 3600,
                   milk_progress=MILK_INTERVAL - 3600)
        self.assertFalse(forecast(p, 1.0)["next_feather_scheduled"])
        self.assertFalse(forecast(p, 1.0)["next_milk_scheduled"])

    def test_simulation_does_not_mutate_input(self):
        original = player()
        simulate(original, 21601.0)
        self.assertEqual(original["eggs"], 0)
        self.assertEqual(original["egg_at"], 1.0)


if __name__ == "__main__":
    unittest.main()
