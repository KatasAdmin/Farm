import unittest
from main import advance, CYCLE, HEN_PRICE, GRAIN_PRICE, EGG_PRICE

class Cursor:
    def fetchall(self):
        return []

class Database:
    def execute(self, sql, params=None):
        return Cursor()

def player(**overrides):
    base = {
        "id": "test", "last_tick": 0.0, "grain": 10, "eggs": 0,
        "chickens": 1, "coins": 100, "satiety": 100,
        "critical_cycles": 0, "fed_hens": 1, "feed_phase": 0,
        "autobuy_enabled": False, "autobuy_amount": 20,
        "storage_level": 1, "coop_level": 1,
    }
    base.update(overrides)
    return base

class ProductionTests(unittest.TestCase):
    def test_prices_and_cycle(self):
        self.assertEqual((CYCLE, HEN_PRICE, GRAIN_PRICE, EGG_PRICE), (21600, 40, 2, 1))

    def test_first_egg_after_six_hours(self):
        p = advance(Database(), player(), CYCLE)
        self.assertEqual(p["eggs"], 1)
        self.assertEqual(p["grain"], 10)
        self.assertEqual(p["feed_phase"], 1)

    def test_four_eggs_first_day(self):
        p = advance(Database(), player(), 86400)
        self.assertEqual(p["eggs"], 4)
        self.assertEqual(p["grain"], 9)
        self.assertEqual(p["feed_phase"], 1)
        self.assertEqual(advance(Database(), p, 86400)["eggs"], 4)

    def test_feed_stops_egg_production_when_empty(self):
        p = advance(Database(), player(grain=0), 86400)
        self.assertEqual(p["eggs"], 3)
        self.assertEqual(p["fed_hens"], 0)
        self.assertEqual(p["grain"], 0)

    def test_warehouse_capacity_blocks_overproduction(self):
        p = advance(Database(), player(grain=2, eggs=98), CYCLE)
        self.assertEqual(p["eggs"], 98)
        self.assertEqual(p["grain"], 2)

    def test_thirty_day_payback(self):
        eggs = (30 * 86400 // CYCLE) * EGG_PRICE
        feed_cost = (30 * 86400 // (CYCLE * 3)) * GRAIN_PRICE
        self.assertEqual(eggs - feed_cost, HEN_PRICE)

    def test_multiple_chickens(self):
        p = advance(Database(), player(chickens=2, fed_hens=2, grain=20), 86400)
        self.assertEqual((p["eggs"], p["grain"]), (8, 18))

if __name__ == "__main__":
    unittest.main()
