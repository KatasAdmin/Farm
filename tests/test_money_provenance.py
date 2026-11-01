import unittest
import time
from unittest.mock import patch
import main
import farm_wallet as wallet
from test_task_bot import Database


class MarketProvenanceTests(unittest.TestCase):
    def setUp(self):
        class MarketDB(Database):
            def execute(self,sql,params=()):return super().execute(sql.replace('::int',''),params)
        self.c=MarketDB();c=self.c
        c.execute('CREATE TABLE players(id text PRIMARY KEY,coins int,grain int,eggs int,feathers int,storage_level int)')
        c.execute('CREATE TABLE market(id text PRIMARY KEY,seller text,item text,quantity int,price int)')
        c.execute('CREATE TABLE money_log(id text PRIMARY KEY,player_id text,kind text,delta int,details text,created real)')
        c.execute('CREATE TABLE market_trade_audit(id text,buyer_id text,seller_id text,item text,quantity int,coins int,created real)')
        c.execute('CREATE TABLE trade_risk_events(id text,buyer_id text,seller_id text,item text,quantity int,coins int,reason text,created real)')
        wallet.initialize_sources(c)
        for p in ('a','b','c','d'):c.execute('INSERT INTO players VALUES(%s,0,0,500,0,100)',(p,))
        c.raw.commit()
    def p(self,pid):return self.c.execute('SELECT * FROM players WHERE id=%s',(pid,)).fetchone()
    def credit(self,pid,kind,n,key):
        self.c.execute('UPDATE players SET coins=coins+%s WHERE id=%s',(n,pid))
        self.c.execute('INSERT INTO money_log VALUES(%s,%s,%s,%s,%s,%s)',(key,pid,kind,n,'test',time.time()))
        self.c.raw.commit()
    def buy(self,buyer,seller,n,listing):
        self.c.execute('INSERT INTO market VALUES(%s,%s,%s,%s,1)',(listing,seller,'eggs',n));self.c.raw.commit()
        with patch.object(main,'db',return_value=self.c),patch.object(main,'person',side_effect=lambda *a:self.p(buyer)),patch.object(main,'advance',side_effect=lambda c,p:p):
            return main.buy(main.Request(item='eggs',amount=n),'Bearer buyer')
    def test_bonus_stays_bonus_across_four_accounts_and_cannot_be_withdrawn(self):
        self.credit('a','promo_reward',300,'promo')
        for i,(buyer,seller) in enumerate([('a','b'),('b','c'),('c','d'),('d','a')]):
            self.buy(buyer,seller,300,str(i))
            self.assertEqual(wallet.balances(self.c,self.p(seller)),{'bonus':300,'purchased':0,'earned':0})
        self.assertEqual(sum(wallet.available(self.c,self.p(p)) for p in ('a','b','c','d')),0)
        self.assertEqual(sum(self.p(p)['coins'] for p in ('a','b','c','d')),300)
    def test_mixed_payment_splits_multiple_sellers_and_preserves_each_source(self):
        self.credit('a','promo_reward',50,'bonus');self.credit('a','stars_purchase',50,'paid')
        for key,seller in [('1','b'),('2','c')]:self.c.execute("INSERT INTO market VALUES(%s,%s,'eggs',40,1)",(key,seller))
        self.c.raw.commit()
        with patch.object(main,'db',return_value=self.c),patch.object(main,'person',side_effect=lambda *a:self.p('a')),patch.object(main,'advance',side_effect=lambda c,p:p):main.buy(main.Request(item='eggs',amount=80),'Bearer a')
        for seller in ('b','c'):self.assertEqual(wallet.balances(self.c,self.p(seller)),{'bonus':25,'purchased':0,'earned':15})
        self.assertEqual(wallet.balances(self.c,self.p('a')),{'bonus':0,'purchased':20,'earned':0})
    def test_paid_source_never_becomes_bonus_and_debit_spends_bonus_first(self):
        self.credit('a','stars_purchase',100,'paid')
        self.buy('a','b',100,'first')
        self.assertEqual(wallet.available(self.c,self.p('b')),100)
        self.credit('b','daily_reward',100,'daily')
        self.buy('b','c',100,'second')
        self.assertEqual(wallet.available(self.c,self.p('b')),100)
        self.assertEqual(wallet.available(self.c,self.p('c')),0)
    def test_partial_trade_failure_rolls_back_both_wallets_and_inventory(self):
        self.credit('a','stars_purchase',100,'paid')
        self.c.execute("INSERT INTO market VALUES('l','b','eggs',100,1)");self.c.raw.commit()
        execute=self.c.execute
        def failing(sql,args=()):
            if sql.startswith('INSERT INTO farm_money_sources'):raise RuntimeError('audit unavailable')
            return execute(sql,args)
        with patch.object(main,'db',return_value=self.c),patch.object(main,'person',side_effect=lambda *a:self.p('a')),patch.object(main,'advance',side_effect=lambda c,p:p),patch.object(self.c,'execute',side_effect=failing):
            with self.assertRaises(RuntimeError):main.buy(main.Request(item='eggs',amount=100),'Bearer a')
        self.assertEqual((self.p('a')['coins'],self.p('b')['coins']),(100,0))
        self.assertEqual(self.c.execute('SELECT quantity FROM market').fetchone()['quantity'],100)
        self.assertEqual(self.c.execute('SELECT count(*) AS n FROM money_log').fetchone()['n'],1)
    def test_rounding_preserves_bonus_and_never_overfills_receipts(self):
        for total_bonus in range(14):
            shares=wallet.split_receipts([('a',2),('b',4),('c',7)],total_bonus)
            self.assertEqual(sum(shares.values()),total_bonus)
            self.assertTrue(all(0<=shares[k]<=n for k,n in [('a',2),('b',4),('c',7)]))
    def test_legacy_sales_are_preserved_and_explicit_sources_cannot_be_forged(self):
        self.credit('a','market_sale',100,'old-sale')
        self.assertEqual(wallet.available(self.c,self.p('a')),100)
        self.c.execute("INSERT INTO farm_money_sources VALUES('old-sale',100,0,100)")
        with self.assertRaises(RuntimeError):wallet.available(self.c,self.p('a'))

    def test_replacing_spent_deposit_with_bonus_does_not_allow_stars_refund(self):
        self.credit('a','stars_purchase',100,'paid')
        self.buy('a','b',100,'spent-deposit')
        self.credit('a','promo_reward',100,'replacement-bonus')
        self.c.execute('ALTER TABLE players ADD COLUMN purchased_coins int DEFAULT 100')
        self.c.execute('CREATE TABLE star_orders(id text,player_id text,telegram_id bigint,coins int,stars int,status text,charge_id text,created real)')
        self.c.execute("INSERT INTO star_orders VALUES(%s,'a',2,100,200,'paid','charge-ref',1)",('f'*32,));self.c.raw.commit()
        with patch.object(main,'db',return_value=self.c),patch.object(main,'telegram_api') as api:
            result=main.stars_refund_order('f'*32,1)
        self.assertIn('заблокирован',result);api.assert_not_called()
        self.assertEqual(self.p('a')['coins'],100)
