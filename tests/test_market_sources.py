import unittest
from farm_wallet import split_market_sources


class MarketSourceTests(unittest.TestCase):
    def test_purchased_coins_do_not_become_earned(self):
        result = split_market_sources([("a", 10)], {"bonus": 0, "purchased": 10, "earned": 0}, 10)
        self.assertEqual(result["a"], {"bonus": 0, "purchased": 10, "earned": 0})

    def test_bonus_coins_do_not_become_earned(self):
        result = split_market_sources([("a", 10)], {"bonus": 10, "purchased": 0, "earned": 0}, 10)
        self.assertEqual(result["a"], {"bonus": 10, "purchased": 0, "earned": 0})

    def test_mixed_bonus_and_earned_without_stars(self):
        result = split_market_sources([("a", 10), ("b", 40)],
                                      {"bonus": 12, "purchased": 0, "earned": 38}, 50)
        self.assertEqual(sum(v["purchased"] for v in result.values()), 0)
        self.assertEqual(sum(v["bonus"] for v in result.values()), 12)
        self.assertEqual(sum(v["earned"] for v in result.values()), 38)

    def test_earned_coins_remain_earned(self):
        result = split_market_sources([("a", 10)], {"bonus": 0, "purchased": 0, "earned": 10}, 10)
        self.assertEqual(result["a"], {"bonus": 0, "purchased": 0, "earned": 10})

    def test_proportional_split_conserves_all_sources(self):
        result = split_market_sources([("a", 10), ("b", 40)],
                                      {"bonus": 12, "purchased": 17, "earned": 21}, 50)
        self.assertEqual(sum(v["bonus"] for v in result.values()), 12)
        self.assertEqual(sum(v["purchased"] for v in result.values()), 17)
        self.assertEqual(sum(v["earned"] for v in result.values()), 21)
        self.assertEqual(sum(result["a"].values()), 10)
        self.assertEqual(sum(result["b"].values()), 40)

    def test_rejects_unfunded_payment(self):
        with self.assertRaises(ValueError):
            split_market_sources([("a", 10)], {"bonus": 1, "purchased": 1, "earned": 1}, 10)


if __name__ == "__main__":
    unittest.main()
