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
                   cows=1, fed_cows=1, grain=0, eggs=100, feather_progress=FEATHER_INTERVAL - 3600,
                   milk_progress=MILK_INTERVAL - 3600)
        self.assertFalse(forecast(p, 1.0)["next_feather_scheduled"])
        self.assertFalse(forecast(p, 1.0)["next_milk_scheduled"])

    def test_long_absence_is_idempotent(self):
        now = 1.0 + 45 * 86400
        first, produced, _ = simulate(player(grain=100, storage_level=2), now)
        second, again, refills = simulate(first, now)
        self.assertGreaterEqual(produced, 0)
        self.assertEqual(again, 0)
        self.assertEqual(refills, [])
        self.assertEqual(second["grain"], first["grain"])
        self.assertEqual(second["eggs"], first["eggs"])

    def test_auto_buy_disabled_by_zero_amount(self):
        p, _, refills = simulate(player(grain=0, autobuy_enabled=True,
                                        autobuy_amount=0), 64801.0)
        self.assertEqual(refills, [])
        self.assertEqual(p["coins"], 100)

    def test_auto_buy_never_overfills_storage(self):
        p, _, refills = simulate(player(grain=0, eggs=100, autobuy_enabled=True,
                                        autobuy_amount=10), 64801.0)
        self.assertEqual(refills, [])
        self.assertLessEqual(p["grain"] + p["eggs"] + p["milk"] + p["feathers"], 100)

    def test_feeding_happens_once_at_boundary(self):
        first, _, _ = simulate(player(chickens=2, fed_hens=2, grain=10), 64801.0)
        self.assertEqual(first["grain"], 8)
        second, produced, refills = simulate(first, 64801.0)
        self.assertEqual(second["grain"], 8)
        self.assertEqual(produced, 0)
        self.assertEqual(refills, [])

    def test_auto_buy_spends_exactly_once(self):
        base = player(grain=0, eggs=0, fed_hens=0,
                      autobuy_enabled=True, autobuy_amount=4)
        first, _, refills = simulate(base, 64801.0)
        self.assertEqual(refills, [4])
        self.assertEqual(first["coins"], 92)
        self.assertEqual(first["grain"], 3)
        second, _, repeat = simulate(first, 64801.0)
        self.assertEqual(repeat, [])
        self.assertEqual(second["coins"], 92)

    def test_no_feed_no_new_production_after_boundary(self):
        base = player(grain=0, chickens=1, fed_hens=1)
        first, _, _ = simulate(base, 64801.0)
        self.assertEqual(first["fed_hens"], 0)
        second, produced, _ = simulate(first, 86401.0)
        self.assertEqual(produced, 0)

    def test_simulation_does_not_mutate_input(self):
        original = player()
        simulate(original, 21601.0)
        self.assertEqual(original["eggs"], 0)
        self.assertEqual(original["egg_at"], 1.0)


    def test_thirty_day_mixed_farm_production_and_coin_conservation(self):
        # One of each animal, full feed supplied in advance, daily sales
        # to prevent warehouse capacity from distorting production.
        day = 86400
        p = player(chickens=1, fed_hens=1, geese=1, fed_geese=1,
                   cows=1, fed_cows=1, grain=250, coins=0,
                   storage_level=10)
        eggs = milk = feathers = 0
        for d in range(1, 31):
            p, made, refills = simulate(p, 1.0 + d * day)
            self.assertEqual(refills, [])
            self.assertEqual(made, p["eggs"])
            eggs += p["eggs"]
            milk += p["milk"]
            feathers += p["feathers"]
            self.assertLessEqual(
                p["grain"] + p["eggs"] + p["milk"] + p["feathers"],
                100 * p["storage_level"])
            p["eggs"] = p["milk"] = p["feathers"] = 0
        self.assertEqual(eggs, 480)
        self.assertEqual(milk, 90)
        self.assertEqual(feathers, 4)
        self.assertEqual(p["grain"], 10)
        self.assertEqual(p["chickens"], 1)
        self.assertEqual(p["geese"], 1)
        self.assertEqual(p["cows"], 1)
        # At base prices: eggs 1, milk 11, feathers 5, grain 2.
        revenue = eggs + milk * 11 + feathers * 5
        consumed_grain = 250 - p["grain"]
        self.assertEqual(revenue, 1490)
        self.assertEqual(consumed_grain, 240)
        self.assertEqual(revenue - consumed_grain * 2, 1010)


    def test_thirty_day_catchup_matches_daily_visits(self):
        start = player(chickens=1, fed_hens=1, geese=1, fed_geese=1,
                       cows=1, fed_cows=1, grain=250, coins=0,
                       storage_level=10)
        daily = start
        daily_eggs = 0
        for day in range(1, 31):
            daily, produced, _ = simulate(daily, 1.0 + day * 86400)
            daily_eggs += produced
        once, once_eggs, _ = simulate(start, 1.0 + 30 * 86400)
        self.assertEqual(daily_eggs, once_eggs)
        for key in ("eggs", "milk", "feathers", "grain", "coins",
                    "fed_hens", "fed_geese", "fed_cows", "last_tick",
                    "chickens", "geese", "cows"):
            self.assertEqual(daily[key], once[key], key)


if __name__ == "__main__":
    unittest.main()
