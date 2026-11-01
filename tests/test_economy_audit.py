import unittest
from economy_audit import animal_economics, payback_days


class AnimalEconomyTest(unittest.TestCase):
    def test_chicken_pays_back_in_thirty_days(self):
        self.assertAlmostEqual(payback_days("chicken"), 30)

    def test_goose_pays_back_in_twenty_four_days(self):
        self.assertAlmostEqual(payback_days("goose"), 24)

    def test_cow_pays_back_in_twenty_days(self):
        self.assertAlmostEqual(payback_days("cow"), 20)

    def test_all_daily_net_values_are_positive(self):
        for animal, values in animal_economics().items():
            with self.subTest(animal=animal):
                self.assertGreater(values["daily_net"], 0)
                self.assertGreater(values["daily_feed_cost"], 0)


if __name__ == "__main__":
    unittest.main()
