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
    def __init__(self,backing=1000,coins=100,pool=0,liabilities=0):
        self.backing=backing
        self.coins=coins
        self.pool=pool
        self.liabilities=liabilities
    def execute(self,sql,args=()):
        low=' '.join(sql.lower().split())
        if low.startswith('select backed_kopeks from farm_cash_reserve'):
            return Q({'backed_kopeks':self.backing})
        if low.startswith('select amount from bot_cash_pool'):
            return Q({'amount':self.pool})
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
    def quote(self,c,nominal):
        with patch.object(farm_exchange.farm_capitalization,'preview',
                          return_value={'nominal_capitalization_kopeks':nominal}),patch('task_bot.liability',return_value=c.liabilities):
            return farm_exchange.quote(c,Decimal('40'))

    def test_price_tracks_capitalization_not_short_term_cash_liquidity(self):
        c=QuoteDB(backing=1200,coins=100)
        q=self.quote(c,1500)
        self.assertEqual(q['coin_price_kopeks'],'15')
        self.assertEqual(q['purchase_price_kopeks'],'15')
        self.assertTrue(q['payout_enabled'])

    def test_unfunded_nominal_is_not_withdrawable_but_has_seed_price_for_bootstrap(self):
        c=QuoteDB(backing=0,coins=100)
        q=self.quote(c,4000)
        self.assertFalse(q['payout_enabled'])
        self.assertEqual(q['coin_price_kopeks'],'40')
        self.assertEqual(q['purchase_price_kopeks'],'40')

    def test_unencumbered_bot_cash_is_automatically_usable_without_manual_funding(self):
        c=QuoteDB(backing=0,coins=100,pool=2000,liabilities=500)
        q=self.quote(c,1200)
        self.assertEqual(q['free_pool_kopeks'],1500)
        self.assertEqual(q['coin_price_kopeks'],'12')
        self.assertTrue(q['payout_enabled'])

    def test_bot_liabilities_and_existing_farm_reserve_cannot_be_spent_twice(self):
        c=QuoteDB(backing=250,coins=100,pool=1000,liabilities=700)
        q=self.quote(c,1200)
        self.assertEqual(q['free_pool_kopeks'],50)
        self.assertEqual(q['cashable_kopeks'],300)
        self.assertEqual(q['coin_price_kopeks'],'12')
        c.liabilities=800
        q=self.quote(c,1200)
        self.assertEqual(q['free_pool_kopeks'],0)
        self.assertEqual(q['cashable_kopeks'],250)
        self.assertEqual(q['coin_price_kopeks'],'12')  # Liquidity changes, not coin price.

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

    def test_all_coin_redemption_burns_exactly_once_and_credits_exact_kopeks(self):
        from types import SimpleNamespace
        class DB:
            def __init__(self):
                self.coins=100
                self.reserve=500
                self.redemptions={}
                self.logs=[]
            def execute(self,sql,args=()):
                q=' '.join(sql.lower().split())
                if q.startswith('select player_id,telegram_id,coins,credited_kopeks from farm_coin_redemptions'):
                    return Q(self.redemptions.get(args[0]))
                if q.startswith('select 1 from withdrawal_requests'):return Q()
                if q.startswith('select * from bot_account_controls'):return Q()
                if q.startswith('insert into bot_accounts'):return Q()
                if q.startswith('update players set coins=coins-'):
                    n,uid,_=args
                    if n>self.coins:return Q()
                    self.coins-=n
                    return Q({'id':uid})
                if q.startswith('update farm_cash_reserve set backed_kopeks=backed_kopeks-'):
                    n,_=args
                    if n>self.reserve:return Q()
                    self.reserve-=n
                    return Q({'backed_kopeks':self.reserve})
                if q.startswith('insert into farm_coin_redemptions'):
                    key,player,uid,coins,kopeks,_=args
                    self.redemptions[key]={'player_id':player,'telegram_id':uid,
                                           'coins':coins,'credited_kopeks':kopeks}
                    return Q()
                if q.startswith('insert into money_log'):
                    self.logs.append(args)
                    return Q()
                raise AssertionError(q)
        c=DB()
        credits=[]
        bot=SimpleNamespace(account=lambda *_:None,
             change=lambda _,uid,value,*rest:credits.append((uid,value)) or value,
             bot_notifications=SimpleNamespace(enqueue=lambda *args,**kwargs:None))
        rate={'payout_enabled':True,'coin_price_kopeks':'5',
              'cashable_kopeks':500,'coin_price_uah':'0.05',
              'reserve_kopeks':500,'free_pool_kopeks':0}
        player={'id':'p','telegram_id':7,'coins':100}
        with patch.object(farm_exchange,'quote',return_value=rate):
            first=farm_exchange.redeem(c,player,100,'redemption-1',bot,Decimal('40'))
            again=farm_exchange.redeem(c,player,100,'redemption-1',bot,Decimal('40'))
            with self.assertRaises(HTTPException):
                farm_exchange.redeem(c,player,101,'redemption-1',bot,Decimal('40'))
        self.assertEqual(first['credited_kopeks'],500)
        self.assertFalse(first['repeated'])
        self.assertTrue(again['repeated'])
        self.assertEqual(c.coins,0)
        self.assertEqual(c.reserve,0)
        self.assertEqual(credits,[(7,500)])
        self.assertEqual(len(c.logs),1)

    def test_minimum_redemption_is_100_coins(self):
        with self.assertRaises(HTTPException) as err:
            farm_exchange.redeem(object(),{'id':'p','telegram_id':7,'coins':100},99,'some-transfer',object(),Decimal('40'))
        self.assertEqual(err.exception.status_code,400)

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
                farm_exchange.redeem(C(),{'id':'p','coins':100,'telegram_id':7},100,'idem-1',object(),Decimal('40'))
        self.assertEqual(err.exception.status_code,409)

if __name__=='__main__':
    unittest.main()
