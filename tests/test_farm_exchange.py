"""Money safety regression tests: floor payouts, zero backing and idempotency."""
import unittest
from decimal import Decimal
from unittest.mock import patch
from fastapi import HTTPException
import farm_exchange


class Q:
    def __init__(self,one=None):self.one=one
    def fetchone(self):return self.one


class QuoteDB:
    def __init__(self,backing=1000,coins=100):
        self.backing=backing
        self.coins=coins
    def execute(self,sql,args=()):
        low=' '.join(sql.lower().split())
        if low.startswith('select backed_kopeks from farm_cash_reserve'):
            return Q({'backed_kopeks':self.backing})
        if low.startswith('select coalesce(sum(coins),0)::bigint as n from players'):
            return Q({'n':self.coins})
        if low.startswith('select coalesce(treasury,0)::bigint as n from economy'):
            return Q({'n':0})
        raise AssertionError(low)


class CreditDB(QuoteDB):
    def __init__(self):
        super().__init__(0,100)
        self.funded={}
    def execute(self,sql,args=()):
        q=' '.join(sql.lower().split())
        if q.startswith('insert into farm_cash_reserve_funding'):
            ref,value,source,_=args
            if ref in self.funded:return Q()
            self.funded[ref]=value
            return Q({'reference':ref})
        if q.startswith('update farm_cash_reserve set backed_kopeks=backed_kopeks+'):
            self.backing+=args[0]
            return Q()
        return super().execute(sql,args)


class ExchangeTests(unittest.TestCase):
    def test_price_is_minimum_of_liquid_cash_and_nominal_reserve(self):
        c=QuoteDB(backing=1200,coins=100)
        with patch.object(farm_exchange.farm_capitalization,'preview',
                          return_value={'nominal_capitalization_kopeks':1500}):
            q=farm_exchange.quote(c,Decimal('40'))
        self.assertEqual(q['coin_price_kopeks'],'12')
        self.assertEqual(q['purchase_price_kopeks'],'12')
        self.assertTrue(q['payout_enabled'])

    def test_unfunded_nominal_is_not_withdrawable_but_has_seed_price_for_bootstrap(self):
        c=QuoteDB(backing=0,coins=100)
        with patch.object(farm_exchange.farm_capitalization,'preview',
                          return_value={'nominal_capitalization_kopeks':4000}):
            q=farm_exchange.quote(c,Decimal('40'))
        self.assertFalse(q['payout_enabled'])
        self.assertEqual(q['coin_price_kopeks'],'0')
        self.assertEqual(q['purchase_price_kopeks'],'40')

    def test_one_real_cash_receipt_cannot_be_counted_twice(self):
        c=CreditDB()
        self.assertTrue(farm_exchange.credit_verified_card(c,'receipt-1',180))
        self.assertFalse(farm_exchange.credit_verified_card(c,'receipt-1',180))
        self.assertEqual(c.backing,180)

    def test_mint_uses_floor_and_bounds(self):
        with patch.object(farm_exchange,'quote',return_value={'purchase_price_kopeks':'3'}):
            coins,_=farm_exchange.mint_from_card(object(),100,Decimal('40'))
        self.assertEqual(coins,33)
        with patch.object(farm_exchange,'quote',return_value={'purchase_price_kopeks':'0'}):
            with self.assertRaises(ValueError):
                farm_exchange.mint_from_card(object(),100,Decimal('40'))

    def test_cannot_redeem_at_zero_cash_price(self):
        class C:
            def execute(self,sql,args=()):
                low=' '.join(sql.lower().split())
                if low.startswith('select player_id,telegram_id,coins,credited_kopeks from farm_coin_redemptions'):return Q()
                if low.startswith('select 1 from withdrawal_requests'):return Q()
                if low.startswith('select * from bot_account_controls'):return Q()
                raise AssertionError(low)
        with patch.object(farm_exchange,'quote',return_value={'payout_enabled':False}):
            with self.assertRaises(HTTPException) as err:
                farm_exchange.redeem(C(),{'id':'p','coins':100,'telegram_id':7},1,'idem-1',object(),Decimal('40'))
        self.assertEqual(err.exception.status_code,409)

if __name__=='__main__':
    unittest.main()
