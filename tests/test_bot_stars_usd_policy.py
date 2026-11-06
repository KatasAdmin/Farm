import unittest
from bot_stars_usd_policy import star_economics

class StarsUsdPolicyTests(unittest.TestCase):
    def test_ua_iphone_purchase_price_not_equal_to_publisher_income(self):
        q=star_economics(100)
        self.assertEqual(q["consumer_reference_ua_ios_usd"],"2.39")
        self.assertEqual(q["developer_reward_reference_usd"],"1.300")
        self.assertEqual(q["proposed_credit_micro_usd"],1_000_000)
        self.assertEqual(q["reference_reserve_micro_usd"],300_000)
        self.assertTrue(q["pending_policy_review"])

    def test_credit_cannot_exceed_developer_reference(self):
        for rate in ("0.014","0","-1","NaN","Infinity"):
            with self.assertRaises(ValueError):
                star_economics(100,proposed_credit_usd=rate)

    def test_fractional_star_quotes_must_be_exact(self):
        q=star_economics(1)
        self.assertEqual(q["proposed_credit_micro_usd"],10_000)
        self.assertEqual(q["reference_reserve_micro_usd"],3_000)

if __name__=="__main__":
    unittest.main()
