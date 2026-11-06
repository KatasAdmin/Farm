import unittest
from bot_usd_payout import payout_quote_usd

class UsdPayoutQuoteTests(unittest.TestCase):
    def test_card_exchange_quote_preserves_debit_and_fee(self):
        q=payout_quote_usd(10_000_000, "uah_card", fee_micro_usd=500_000, uah_per_usd="45.4432")
        self.assertEqual(q["debit_usd_micro"],10_000_000)
        self.assertEqual(q["net_usd_micro"],9_500_000)
        self.assertEqual(q["destination_kopecks"],43171)
        self.assertEqual(q["destination_currency"],"UAH")

    def test_never_invent_crypto_parity_or_rate(self):
        for params in [
            dict(micro_usd=1000000,method="usdt"),
            dict(micro_usd=1000000,method="uah_card"),
            dict(micro_usd=1000000,method="uah_card",uah_per_usd=0),
            dict(micro_usd=1000000,method="uah_card",fee_micro_usd=1000000,uah_per_usd=45),
        ]:
            with self.assertRaises(ValueError):
                payout_quote_usd(**params)

    def test_usdt_network_and_quote_are_explicit(self):
        q=payout_quote_usd(10_000_000,"usdt",
            network="TRC20", usdt_per_usd="0.995", network_fee_usdt="0.5")
        self.assertEqual(q["destination_currency"],"USDT")
        self.assertEqual(q["destination_usdt_micro"],9_450_000)
        self.assertEqual(q["network"],"TRC20")

    def test_unpriced_or_too_small_usdt_payout_rejected(self):
        with self.assertRaises(ValueError):
            payout_quote_usd(1_000_000,"usdt",network="TRC20",usdt_per_usd="1.0")
        with self.assertRaises(ValueError):
            payout_quote_usd(1_000_000,"usdt",network="TRC20",usdt_per_usd="1.0",network_fee_usdt="2.0")

    def test_below_minimum_bank_payout_rejected(self):
        with self.assertRaises(ValueError):
            payout_quote_usd(1,"uah_card",uah_per_usd="45.4432")

if __name__=="__main__":
    unittest.main()
