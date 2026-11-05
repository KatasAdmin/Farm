import unittest
from market_allocation import allocate


def listing(name, amount, price=1):
    return {"id": name, "quantity": amount, "price": price}


class ProportionalMarketTests(unittest.TestCase):
    def test_ten_and_forty_split_five_as_one_and_four(self):
        selected = allocate([listing("a", 10), listing("b", 40)], 5)
        self.assertEqual({r["id"]: n for r, n in selected}, {"a": 1, "b": 4})

    def test_lower_price_fills_before_higher(self):
        selected = allocate([listing("high", 100, 2), listing("low", 2, 1)], 4)
        self.assertEqual({r["id"]: n for r, n in selected}, {"low": 2, "high": 2})

    def test_deterministic_remainder(self):
        rows = [listing("c", 1), listing("b", 1), listing("a", 1)]
        self.assertEqual(allocate(rows, 2), allocate(list(reversed(rows)), 2))
        self.assertEqual([r["id"] for r, _ in allocate(rows, 2)], ["a", "b"])

    def test_whole_animals_four_and_three_buy_two(self):
        result = allocate([listing("a", 4), listing("b", 3)], 2)
        self.assertEqual({r["id"]: n for r, n in result}, {"a": 1, "b": 1})

    def test_fractional_tie_prefers_smaller_listing(self):
        result = allocate([listing("a", 3), listing("b", 1)], 2)
        self.assertEqual({r["id"]: n for r, n in result}, {"a": 1, "b": 1})

    def test_animal_seven_and_three_buy_one(self):
        result = allocate([listing("a", 7), listing("b", 3)], 1)
        self.assertEqual({r["id"]: n for r, n in result}, {"a": 1})

    def test_ten_sellers_conserve_whole_units(self):
        rows = [listing(str(i), i + 1) for i in range(10)]
        result = allocate(rows, 17)
        self.assertEqual(sum(q for _, q in result), 17)
        self.assertTrue(all(isinstance(q, int) and q >= 1 for _, q in result))
        self.assertTrue(all(q <= row["quantity"] for row, q in result))

    def test_no_overselling(self):
        rows = [listing("a", 2), listing("b", 3)]
        selected = allocate(rows, 5)
        self.assertEqual(sum(n for _, n in selected), 5)
        self.assertTrue(all(n <= r["quantity"] for r, n in selected))

    def test_invalid_requests(self):
        with self.assertRaises(ValueError):
            allocate([listing("a", 1)], 2)
        with self.assertRaises(ValueError):
            allocate([listing("a", 1)], 0)


if __name__ == "__main__":
    unittest.main()
