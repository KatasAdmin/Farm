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
