import unittest
from bot_usd_topups import quote_uah_card_deposit, quote_stars_deposit

class UsdTopupQuoteTests(unittest.TestCase):
    def test_card_exact_rate_and_fee(self):
        q=quote_uah_card_deposit(454432,"45.4432",fee_kopecks=0)
        self.assertEqual(q["credit_usd_micro"],100_000_000)
        self.assertEqual(q["provider_currency"],"UAH")
        self.assertEqual(q["exchange_rate_uah_per_usd"],"45.4432")

    def test_never_credit_more_than_funded(self):
        q=quote_uah_card_deposit(100,"45.4432")
        self.assertEqual(q["credit_usd_micro"],22005)
        self.assertEqual(quote_uah_card_deposit(100,"45.4432",fee_kopecks=50)["credit_usd_micro"],11002)

    def test_stars_uses_its_own_snapshotted_rate(self):
        self.assertEqual(quote_stars_deposit(20,12000)["credit_usd_micro"],240000)
        with self.assertRaises(ValueError):
            quote_stars_deposit(20,0)

    def test_invalid_card_rate_or_fee_does_not_credit(self):
        for rate,fee in [(0,0),(-1,0),(45,100),(45,-1)]:
            with self.assertRaises(ValueError):
                quote_uah_card_deposit(100,rate,fee)

if __name__=="__main__":
    unittest.main()
