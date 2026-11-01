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

    def test_many_small_sellers_preserve_every_source(self):
        # Regression for largest-remainder rounding across three source pools.
        for n in range(1, 16):
            receipts = [(str(i), i + 1) for i in range(n)]
            total = sum(amount for _, amount in receipts)
            for bonus in range(total + 1):
                purchased = (total - bonus) // 2
                earned = total - bonus - purchased
                result = split_market_sources(
                    receipts, {"bonus": bonus, "purchased": purchased,
                               "earned": earned}, total)
                self.assertEqual(sum(v["bonus"] for v in result.values()), bonus)
                self.assertEqual(sum(v["purchased"] for v in result.values()), purchased)
                self.assertEqual(sum(v["earned"] for v in result.values()), earned)
                for key, amount in receipts:
                    self.assertEqual(sum(result[key].values()), amount)
                    self.assertTrue(all(value >= 0 for value in result[key].values()))

    def test_rejects_unfunded_payment(self):
        with self.assertRaises(ValueError):
            split_market_sources([("a", 10)], {"bonus": 1, "purchased": 1, "earned": 1}, 10)


    def test_bonus_cannot_be_laundered_through_seven_referral_levels(self):
        # Each referral hop may exchange goods, but it cannot create
        # withdrawable earnings from an originally non-withdrawable reward.
        for source in ("bonus", "purchased"):
            funds = {"bonus": 0, "purchased": 0, "earned": 0}
            funds[source] = 101
            for level in range(1, 8):
                receipt = split_market_sources(
                    [("level-" + str(level), 101)], funds, 101)
                funds = receipt["level-" + str(level)]
                self.assertEqual(funds["earned"], 0)
                self.assertEqual(sum(funds.values()), 101)

    def test_genuine_earnings_remain_withdrawable_after_seven_trades(self):
        funds = {"bonus": 0, "purchased": 0, "earned": 101}
        for level in range(1, 8):
            funds = split_market_sources(
                [("level-" + str(level), 101)], funds, 101)["level-" + str(level)]
        self.assertEqual(funds, {"bonus": 0, "purchased": 0, "earned": 101})


if __name__ == "__main__":
    unittest.main()
