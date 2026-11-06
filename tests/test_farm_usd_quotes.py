import unittest
from farm_usd_quotes import game_coin_usd_quote
from bot_usd_currency import farm_coins_to_usd_micro, USD_SCALE

class FarmUsdQuoteTests(unittest.TestCase):
    def test_quote_one_coin_not_one_dollar(self):
        q=game_coin_usd_quote(1)
        self.assertEqual(q["quote_micro_usd"], farm_coins_to_usd_micro(1))
        self.assertLess(q["quote_micro_usd"], USD_SCALE)
        self.assertTrue(q["quote_only"])
        self.assertEqual(q["source_currency"], "FARM_COIN_LEGACY_UAH")

    def test_large_transfer_amount_is_preserved_as_valued_quote(self):
        q=game_coin_usd_quote(100)
        self.assertEqual(q["quote_display"], "$2.200549")
        self.assertEqual(q["source_coins"], 100)
        self.assertEqual(q["uah_per_usd"], "45.4432")

    def test_negative_and_fractional_not_allowed(self):
        for bad in (-1, 1.5, "100"):
            with self.assertRaises(ValueError):
                game_coin_usd_quote(bad)

if __name__ == "__main__":
    unittest.main()
