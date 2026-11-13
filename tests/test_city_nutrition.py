"""Farm/City nutrition safety and monotonic food bonus tests."""
import unittest
from pathlib import Path
import city_nutrition

ROOT=Path(__file__).resolve().parents[1]

class NutritionTests(unittest.TestCase):
    def test_no_food_no_bonus(self):
        self.assertEqual(city_nutrition.bonus_seconds(None,0,3600),0)
        self.assertEqual(city_nutrition.status(None,3600)["production_multiplier"],1)
    def test_one_meal_full_bonus_then_60_percent(self):
        food={"fullness":100,"updated_at":10000}
        self.assertEqual(city_nutrition.status(food,10000)["bonus_percent"],100)
        self.assertEqual(city_nutrition.status(food,10000+8*3600)["bonus_percent"],60)
        self.assertEqual(city_nutrition.status(food,10000+8*3600)["production_multiplier"],1.6)
        self.assertEqual(city_nutrition.status(food,10000+20*3600)["production_multiplier"],1)
        self.assertEqual(city_nutrition.status(food,10000+50*3600)["fullness"],0)
    def test_food_is_never_retroactive_and_integral_is_exact(self):
        food={"fullness":100,"updated_at":3600}
        self.assertEqual(city_nutrition.bonus_seconds(food,0,3600),0)
        self.assertAlmostEqual(city_nutrition.bonus_seconds(food,3600,7200),0.975*3600,places=4)
        self.assertAlmostEqual(city_nutrition.bonus_seconds(food,0,7200),0.975*3600,places=4)
        self.assertAlmostEqual(city_nutrition.bonus_seconds(food,3600,3600+20*3600),10*3600,places=3)
    def test_only_food_can_be_eaten(self):
        self.assertNotIn("pillow",city_nutrition.FOOD_RESTORE)
        self.assertNotIn("scarf",city_nutrition.FOOD_RESTORE)
        self.assertIn("omelet",city_nutrition.FOOD_RESTORE)
    def test_real_six_hour_egg_production_scales_with_food_safely(self):
        from production_v4 import simulate
        from test_production_safety import player
        p=player(chickens=6,fed_hens=6,grain=20,storage_level=5)
        no_food=simulate(p,21601.0)[1]
        fed=simulate(dict(p,_city_food={"fullness":100,"updated_at":1.0}),21601.0)[1]
        partly_fed=simulate(dict(p,_city_food={"fullness":60,"updated_at":1.0}),21601.0)[1]
        self.assertEqual(no_food,6)
        self.assertEqual(partly_fed,8)
        self.assertEqual(fed,11)
        self.assertTrue(no_food<partly_fed<fed)
        self.assertEqual(simulate(dict(p,fed_hens=0,
             _city_food={"fullness":100,"updated_at":1.0}),21601.0)[1],0)

    def test_production_uses_integrated_bonus_without_minting(self):
        src=(ROOT/"production_v4.py").read_text("utf8")
        self.assertIn('city_nutrition.bonus_seconds(food,cursor,step)',src)
        self.assertIn("progress+rate*productive_elapsed",src)
        self.assertIn("milk_progress+=fed_cows*productive_elapsed",src)
        self.assertIn("wool_progress+=fed_sheep*productive_elapsed",src)
        self.assertIn("feather_progress+=fed_geese*productive_elapsed",src)
        main=(ROOT/"main.py").read_text("utf8")
        self.assertIn('city_nutrition.get(c,p["id"])',main)
        city=(ROOT/"city_world.py").read_text("utf8")
        self.assertIn('p=_advance(c,p)',city)
        self.assertIn('UPDATE city_products SET quantity=quantity-%s',city)

if __name__=="__main__":unittest.main()
