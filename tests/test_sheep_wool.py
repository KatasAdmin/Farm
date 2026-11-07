"""Sheep and wool production stay deterministic and have no automatic cash minting."""
import unittest
from production_v4 import simulate, feed_required, SHEEP_PRICE, WOOL_PRICE
from test_continuous_production import farm


class SheepWoolTests(unittest.TestCase):
    def sheep(self, grain=100, fed=1, wool=0):
        p = farm(0, grain=grain, eggs=0)
        p.update(sheep=1, fed_sheep=fed, wool=wool, wool_progress=0.0)
        return p

    def test_pricing_and_feed(self):
        self.assertEqual(SHEEP_PRICE, 200)
        self.assertEqual(WOOL_PRICE, 12)
        self.assertEqual(feed_required(self.sheep()), 2)

    def test_one_wool_per_day_when_fed(self):
        p = self.sheep()
        after, egg_count, _ = simulate(p, 100000+24*3600)
        self.assertEqual(after["wool"], 1)
        self.assertEqual(egg_count, 0)
        self.assertEqual(after["grain"], 98)
        again, _, _ = simulate(after, 100000+24*3600)
        self.assertEqual(again["wool"], 1)
        self.assertEqual(again["grain"], 98)

    def test_no_wool_when_never_fed(self):
        p = self.sheep(grain=0, fed=0)
        after, _, _ = simulate(p, 100000+48*3600)
        self.assertEqual(after["wool"], 0)

    def test_warehouse_capacity_limits_wool(self):
        p = self.sheep(grain=0, wool=100)
        p["storage_level"] = 1
        after, _, _ = simulate(p, 100000+24*3600)
        self.assertEqual(after["wool"], 100)

    def test_split_ticks_equal_one_long_tick(self):
        p = self.sheep()
        long, _, _ = simulate(p,100000+48*3600)
        part, _, _ = simulate(p,100000+12*3600)
        part, _, _ = simulate(part,100000+24*3600)
        part, _, _ = simulate(part,100000+48*3600)
        self.assertEqual((part["wool"],part["grain"]),(long["wool"],long["grain"]))


if __name__=="__main__":
    unittest.main()
