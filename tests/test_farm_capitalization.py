import unittest
from decimal import Decimal
from farm_capitalization import calculate,preview


class Row:
    def __init__(self,n):self.n=n
    def fetchone(self):return {'n':self.n}


class FakeCapitalDB:
    def execute(self,sql,args=()):
        q=' '.join(sql.lower().split())
        if "from farm_capitalization_baseline" in q:
            return type('Baseline',(),{'fetchone':lambda self:{'started_at':1762500000.0,'seed_usd':Decimal('1')}})()
        if "from bot_adsgram_farm_attempts" in q:return Row(12)
        if "from monetag_ad_attempts" in q:return Row(8)
        if "from bot_card_topups" in q:return Row(5000)
        if "from farm_bot_transfers" in q:return Row(10)
        if "from farm_coin_redemptions" in q:return Row(0)
        if "from players" in q:return Row(800)
        if "from economy" in q:return Row(200)
        raise AssertionError(q)


class CapitalizationTests(unittest.TestCase):
    def test_quote_from_one_usd_ads_confirmed_cards_and_all_coins(self):
        result=preview(FakeCapitalDB(),Decimal('40'))
        self.assertEqual(result['game_views'],20)
        self.assertEqual(result['game_views_kopeks'],100)
        self.assertEqual(result['approved_deposits_kopeks'],5000)
        self.assertEqual(result['historical_transfers_kopeks'],1000)
        self.assertEqual(result['total_coins'],1000)
        self.assertEqual(result['nominal_capitalization_kopeks'],8100)
        self.assertEqual(Decimal(result['nominal_coin_price_uah']),Decimal('0.081'))
        self.assertFalse(result['payout_enabled'])

    def test_zero_denominator_and_zero_reserve_never_imply_a_cash_payout(self):
        self.assertEqual(Decimal(calculate(100,0,0,0,0)['nominal_coin_price_uah']),0)
        result=calculate(100,0,0,101,20)
        self.assertEqual(Decimal(result['nominal_coin_price_uah']),0)
        self.assertFalse(result['payout_enabled'])

    def test_invalid_and_negative_parameters_rejected(self):
        with self.assertRaises(ValueError):calculate(100,-1,0,0,10)
        with self.assertRaises(ValueError):calculate(100,0,0,0,1.5)

if __name__=='__main__':
    unittest.main()
