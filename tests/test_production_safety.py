import unittest

from production_v4 import feed_required, simulate


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

    def test_simulation_does_not_mutate_input(self):
        original = player()
        simulate(original, 21601.0)
        self.assertEqual(original["eggs"], 0)
        self.assertEqual(original["egg_at"], 1.0)


if __name__ == "__main__":
    unittest.main()
