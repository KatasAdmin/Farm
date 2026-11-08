import unittest
import uuid
from unittest.mock import patch
from fastapi import HTTPException
import main
import task_bot as bot
import farm_wallet as wallet
from test_task_bot import Database

class FarmWalletTests(unittest.TestCase):
    def setUp(self):
        self.c=Database();bot.initialize(self.c)
        self.c.execute('CREATE TABLE players(id text PRIMARY KEY,telegram_id bigint UNIQUE,coins int)')
        self.c.execute('CREATE TABLE money_log(id text PRIMARY KEY,player_id text,kind text,delta int,details text,created double precision)')
        self.c.execute("CREATE TABLE withdrawal_requests(id text PRIMARY KEY,player_id text,amount int,status text,created double precision,reserved boolean)")
        wallet.initialize(self.c)
        self.c.execute("INSERT INTO players VALUES('p',55,10)");self.clock=0
        self.key=str(uuid.uuid4())
        self.c.raw.commit()
    def add(self,kind,delta):
        self.clock+=1
        self.c.execute('UPDATE players SET coins=coins+%s WHERE id=%s',(delta,'p'))
        self.c.execute('INSERT INTO money_log VALUES(%s,%s,%s,%s,%s,%s)',(str(uuid.uuid4()),'p',kind,delta,'test',self.clock))
    def player(self):return self.c.execute("SELECT * FROM players WHERE id='p'").fetchone()
    def test_bonus_promo_start_and_purchase_are_not_earned(self):
        for kind in ('promo_reward','daily_reward','weekly_reward','tutorial','referral_bonus','stars_purchase'):self.add(kind,1000)
        self.assertEqual(wallet.available(self.c,self.player()),0)
        self.add('market_sale',150);self.add('system_sale',50)
        self.assertEqual(wallet.available(self.c,self.player()),200)
    def test_bonus_spent_first_but_new_bonus_never_restores_withdrawn_earnings(self):
        self.add('promo_reward',1000);self.add('market_sale',200)
        self.add('shop',-1100)
        self.assertEqual(wallet.available(self.c,self.player()),110)
        self.add('farm_to_bot',-100);self.add('promo_reward',1000)
        self.assertEqual(wallet.available(self.c,self.player()),10)
    def test_transfer_credits_exact_own_uid_once_and_preserves_bonus(self):
        self.add('promo_reward',1000);self.add('market_sale',200);self.c.raw.commit()
        with self.c:result=wallet.transfer(self.c,self.player(),100,self.key,bot)
        with self.c:again=wallet.transfer(self.c,self.player(),100,self.key,bot)
        self.assertFalse(result['repeated']);self.assertTrue(again['repeated'])
        self.assertEqual(self.player()['coins'],1110)
        self.assertEqual(self.c.execute('SELECT available FROM bot_accounts WHERE uid=55').fetchone()['available'],10000)
        self.assertEqual(wallet.available(self.c,self.player()),100)
        self.assertEqual(len(self.c.execute('SELECT * FROM farm_bot_transfers').fetchall()),1)
        self.assertEqual(len(self.c.execute('SELECT * FROM bot_notifications').fetchall()),2)
        with self.assertRaises(HTTPException):wallet.transfer(self.c,self.player(),200,self.key,bot)
    def test_promo_only_refused_without_side_effects(self):
        self.add('promo_reward',1000)
        with self.assertRaises(HTTPException):wallet.transfer(self.c,self.player(),100,self.key,bot)
        self.assertEqual(self.player()['coins'],1010)
        self.assertEqual(len(self.c.execute('SELECT * FROM bot_ledger').fetchall()),0)
    def test_wallet_error_rolls_back_game_debit_and_transfer(self):
        self.add('market_sale',200);self.c.raw.commit()
        with patch.object(bot,'change',side_effect=RuntimeError('wallet unavailable')):
            with self.assertRaises(RuntimeError):
                with self.c:wallet.transfer(self.c,self.player(),100,self.key,bot)
        self.assertEqual(self.player()['coins'],210)
        self.assertEqual(len(self.c.execute('SELECT * FROM farm_bot_transfers').fetchall()),0)
        self.assertEqual(len(self.c.execute('SELECT * FROM money_log').fetchall()),1)
    def test_legacy_pending_request_must_be_cancelled(self):
        self.add('market_sale',200)
        self.c.execute("INSERT INTO withdrawal_requests VALUES('old','p',100,'pending',0,true)")
        with self.assertRaises(HTTPException) as e:wallet.transfer(self.c,self.player(),100,self.key,bot)
        self.assertEqual(e.exception.status_code,409)
    def test_http_uses_authenticated_player_and_retries_same_key(self):
        self.add('market_sale',200);self.c.raw.commit()
        with patch.object(main,'db',return_value=self.c),patch.object(main,'person',side_effect=lambda *args:self.player()),patch.object(main,'advance',side_effect=lambda c,p:p),patch.object(main.bot_cash_ad_credits,'nbu_usd_uah',return_value=40),patch.object(main.farm_exchange,'redeem',side_effect=[{'ok':True,'repeated':False},{'ok':True,'repeated':True}]) as redeem:
            a=main.request_withdrawal(main.Request(amount=100,transfer_id=self.key),'Bearer owner')
            b=main.request_withdrawal(main.Request(amount=100,transfer_id=self.key),'Bearer owner')
        self.assertEqual(redeem.call_count,2)
        self.assertFalse(a['repeated']);self.assertTrue(b['repeated'])
        with self.c:
            p=dict(self.player(),id='other')
            with self.assertRaises(HTTPException):wallet.transfer(self.c,p,100,self.key,bot)
    def test_failure_after_bot_credit_rolls_back_both_wallets(self):
        self.add('market_sale',200);self.c.raw.commit()
        with patch.object(bot.bot_notifications,'enqueue',side_effect=RuntimeError('outbox failure')):
            with self.assertRaises(RuntimeError):
                with self.c:wallet.transfer(self.c,self.player(),100,self.key,bot)
        self.assertEqual(self.player()['coins'],210)
        self.assertEqual(len(self.c.execute('SELECT * FROM bot_accounts').fetchall()),0)
        self.assertEqual(len(self.c.execute('SELECT * FROM bot_ledger').fetchall()),0)
    def test_new_transfer_cannot_spend_bonus_after_earned_coins_are_exhausted(self):
        self.add('market_sale',100);self.add('promo_reward',1000);self.c.raw.commit()
        with self.c:wallet.transfer(self.c,self.player(),100,self.key,bot)
        with self.assertRaises(HTTPException):
            with self.c:wallet.transfer(self.c,self.player(),100,str(uuid.uuid4()),bot)
        self.assertEqual(self.player()['coins'],1010)
        self.assertEqual(self.c.execute('SELECT available FROM bot_accounts WHERE uid=55').fetchone()['available'],10000)
