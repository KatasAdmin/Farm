import unittest

import animal_market as market


class AnimalMarketMathTests(unittest.TestCase):
    def test_seven_and_three_shares_make_one_integer_animal(self):
        rows = [
            {"id": "a", "price": 40, "quantity_units": 7 * market.SCALE},
            {"id": "b", "price": 40, "quantity_units": 3 * market.SCALE},
        ]
        shares = market.allocate(rows, market.SCALE)
        self.assertEqual({row["id"]: units for row, units in shares},
                         {"a": 700_000_000, "b": 300_000_000})
        self.assertEqual(sum(units for _, units in shares), market.SCALE)

    def test_ten_sellers_split_exactly_and_repeat_deterministically(self):
        rows = [{"id": str(i), "price": 160, "quantity_units": (i + 1) * market.SCALE}
                for i in range(10)]
        first = market.allocate(rows, 7 * market.SCALE)
        second = market.allocate(rows, 7 * market.SCALE)
        self.assertEqual(first, second)
        self.assertEqual(sum(units for _, units in first), 7 * market.SCALE)
        self.assertTrue(all(0 < units <= row["quantity_units"] for row, units in first))

    def test_payment_rounding_conserves_every_coin(self):
        rows = [{"id": str(i), "units": 1} for i in range(10)]
        result = market.split_payment(rows, 10, 500)
        self.assertEqual(sum(coins for _, coins in result), 500)
        self.assertEqual(sorted(coins for _, coins in result), [50] * 10)

    def test_fractional_balance_debit_and_recombination_conserve_units(self):
        whole, fraction = market.apply_balance(7, 0, -700_000_000)
        self.assertEqual((whole, fraction), (6, 300_000_000))
        whole, fraction = market.apply_balance(6, fraction, 700_000_000)
        self.assertEqual((whole, fraction), (7, 0))
        with self.assertRaises(ValueError):
            market.apply_balance(0, 0, -1)

    def test_restricted_share_transfer_cannot_leave_tagged_value_behind(self):
        tagged = market.transfer_tagged_units(1_000_000_000, 3_000_000_000, 1_000_000_000)
        self.assertEqual(tagged, 333_333_334)
        self.assertEqual(market.transfer_tagged_units(17, 100, 100), 17)


if __name__ == "__main__":
    unittest.main()
