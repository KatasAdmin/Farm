import unittest
from farm_missions import available

class MissionSelectionTest(unittest.TestCase):
    def test_no_animals_no_species_tasks(self):
        keys = {m.key for m in available("daily")}
        self.assertNotIn("milk_produced", keys)
        self.assertNotIn("feathers_collected", keys)
        self.assertNotIn("eggs_produced", keys)

    def test_cow_only(self):
        keys = {m.key for m in available("weekly", cows=1)}
        self.assertIn("milk_produced", keys)
        self.assertNotIn("feathers_collected", keys)

    def test_goose_only(self):
        keys = {m.key for m in available("daily", geese=1)}
        self.assertNotIn("feathers_collected", keys)
        self.assertIn("eggs_produced", keys)
        self.assertNotIn("milk_produced", keys)

    def test_feathers_not_required_for_daily_or_weekly(self):
        for period in ("daily", "weekly"):
            keys = {m.key for m in available(period, geese=1)}
            self.assertNotIn("feathers_collected", keys)

    def test_invalid_period(self):
        with self.assertRaises(ValueError):
            available("monthly")

if __name__ == "__main__":
    unittest.main()
