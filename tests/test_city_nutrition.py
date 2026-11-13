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
        self.assertEqual(city_nutrition.status(food,10000)["bonus_percent"],50)
        self.assertEqual(city_nutrition.status(food,10000+8*3600)["bonus_percent"],30)
        self.assertEqual(city_nutrition.status(food,10000+8*3600)["production_multiplier"],1.3)
        self.assertEqual(city_nutrition.status(food,10000+20*3600)["production_multiplier"],1)
        self.assertEqual(city_nutrition.status(food,10000+50*3600)["fullness"],0)
    def test_food_is_never_retroactive_and_integral_is_exact(self):
        food={"fullness":100,"updated_at":3600}
        self.assertEqual(city_nutrition.bonus_seconds(food,0,3600),0)
        self.assertAlmostEqual(city_nutrition.bonus_seconds(food,3600,7200),0.4875*3600,places=4)
        self.assertAlmostEqual(city_nutrition.bonus_seconds(food,0,7200),0.4875*3600,places=4)
        self.assertAlmostEqual(city_nutrition.bonus_seconds(food,3600,3600+20*3600),5*3600,places=3)
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
        self.assertEqual(partly_fed,7)
        self.assertEqual(fed,8)
        self.assertTrue(no_food<partly_fed<fed)
        self.assertEqual(simulate(dict(p,fed_hens=0,
             _city_food={"fullness":100,"updated_at":1.0}),21601.0)[1],0)

    def test_meal_increases_yield_without_advancing_the_base_clock(self):
        from production import CYCLE
        from production_v4 import next_egg_delay, simulate
        from test_production_safety import player

        start=1.0
        food={"fullness":100,"updated_at":start}
        p=player(chickens=1,fed_hens=1,grain=20,storage_level=5)
        fed=dict(p,_city_food=food)
        self.assertEqual(next_egg_delay(fed,start),next_egg_delay(p,start))
        self.assertEqual(simulate(fed,start+CYCLE-1)[1],0)
        self.assertEqual(simulate(fed,start+2*CYCLE)[1],2)

    def test_bonus_progress_survives_polling_and_is_not_retroactive(self):
        from production import CYCLE
        from production_v4 import simulate
        from test_production_safety import player

        food={"fullness":100,"updated_at":1.0+CYCLE/2}
        p=player(chickens=4,fed_hens=4,grain=20,storage_level=5)
        p["_city_food"]=food
        direct=simulate(p,1.0+CYCLE)[0]
        midpoint=simulate(p,1.0+0.75*CYCLE)[0]
        midpoint["_city_food"]={**food,"bonus_progress":midpoint["_city_bonus_progress"]}
        after=simulate(midpoint,1.0+CYCLE)[0]
        self.assertEqual(after["eggs"],direct["eggs"])
        self.assertEqual(direct["eggs"],4)
        self.assertAlmostEqual(after["_city_bonus_progress"]["eggs"],direct["_city_bonus_progress"]["eggs"])

if __name__=="__main__":unittest.main()
