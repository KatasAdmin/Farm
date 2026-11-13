"""Regression checks for proposed city economic balancing."""
import unittest
from city_world import (
    RECIPES, FARM_REFERENCE_PRICES, recipe_price_guides,
    business_investment_guides, business_upgrade_cost, business_batch_limit,
    food_value_guides,
)
from city_economy_audit import field_payback_days, business_payback_days, food_break_even
from importlib import import_module
run = import_module('city_30_day_model').run


class CityEconomyTests(unittest.TestCase):
    def test_existing_farm_prices(self):
        self.assertEqual(FARM_REFERENCE_PRICES, {
            "eggs": 1, "grain": 2, "milk": 11, "feathers": 5, "wool": 12
        })

    def test_recipe_prices_cover_inputs(self):
        for key, quote in recipe_price_guides().items():
            self.assertGreaterEqual(quote["suggested_unit_price"] * quote["batch_output"],
                                    quote["batch_input_cost"], key)
            self.assertGreaterEqual(RECIPES[key]["seconds"], 1800)

    def test_bread_price_and_payback(self):
        self.assertEqual(recipe_price_guides()["bread"]["batch_input_cost"], 10)
        self.assertEqual(recipe_price_guides()["bread"]["suggested_unit_price"], 7)
        self.assertAlmostEqual(field_payback_days(1, 1), 20)
        self.assertIsNone(business_payback_days("bread", 500, 10, 0))
        self.assertGreater(food_break_even("bread"), 12)

    def test_business_upgrades(self):
        self.assertEqual(business_upgrade_cost("bakery", 1), 120)
        self.assertEqual(business_batch_limit(1), 2)
        self.assertEqual(business_batch_limit(10), 20)
        with self.assertRaises(ValueError):
            business_upgrade_cost("bakery", 10)

    def test_food_and_investment_guides(self):
        self.assertEqual(set(food_value_guides()), {
            "bread", "yogurt", "pancakes", "cheese", "omelet", "pie",
            "breakfast_set", "dessert_box", "lunch_box"
        })
        self.assertIn("bakery", business_investment_guides())

    def test_wallet_conservation_for_30_days(self):
        for size in (10, 100, 1000):
            for activity in (0.25, 0.5, 0.75, 1.0):
                with self.subTest(size=size, activity=activity):
                    days = run(farmers=size, businesses=size, active_fraction=activity)
                    self.assertEqual(len(days), 30)
                    self.assertEqual(days[-1]["farmer_coins"] +
                                     days[-1]["city_coins"] +
                                     days[-1]["treasury"], size * 2 * 1000)


if __name__ == "__main__":
    unittest.main()
