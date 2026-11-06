"""Isolated PostgreSQL checks: never use production DB credentials."""
import os
import uuid
import unittest
from urllib.parse import urlparse

import psycopg
from psycopg.rows import dict_row
import bot_usd_pg_wallet as wallet

DSN=os.getenv("TEST_DATABASE_URL")

@unittest.skipUnless(DSN,"Local isolated PostgreSQL test only")
class USDWalletPostgresTests(unittest.TestCase):
    def setUp(self):
        if urlparse(DSN).hostname not in ("localhost","127.0.0.1","postgres"):
            raise RuntimeError("Unsafe DB host for USD wallet tests")
        self.schema="usd_test_"+uuid.uuid4().hex
        with psycopg.connect(DSN,autocommit=True) as c:
            c.execute("CREATE SCHEMA "+self.schema)
        self.c=psycopg.connect(DSN,row_factory=dict_row,options="-c search_path="+self.schema)
        with self.c:
            wallet.initialize(self.c)
    def tearDown(self):
        self.c.close()
        with psycopg.connect(DSN,autocommit=True) as c:
            c.execute("DROP SCHEMA "+self.schema+" CASCADE")
    def balances(self):
        with self.c:
            return dict(wallet.snapshot(self.c,101))

    def test_verified_credits_and_cashout(self):
        with self.c:
            self.assertTrue(wallet.credit_verified(self.c,101,"sale-ref-0001","task_reward",500_000))
            self.assertTrue(wallet.credit_verified(self.c,101,"stars-ref-0001","stars_purchase",1_000_000))
            self.assertFalse(wallet.credit_verified(self.c,101,"sale-ref-0001","task_reward",500_000))
            self.assertTrue(wallet.reserve_cashout(self.c,101,"out-1001",400_000))
            self.assertFalse(wallet.reserve_cashout(self.c,101,"out-1001",400_000))
            with self.assertRaises(ValueError):
                wallet.reserve_cashout(self.c,101,"out-1002",200_000)
        row=self.balances()
        self.assertEqual((row["spend_only_micro"],row["earned_micro"],row["reserved_micro"]),(1_000_000,500_000,400_000))
        with self.c:
            self.assertTrue(wallet.finalize_cashout(self.c,101,"out-1001",True))
            self.assertFalse(wallet.finalize_cashout(self.c,101,"out-1001",True))
        self.assertEqual(self.balances()["earned_micro"],100_000)

    def test_bonuses_never_become_withdrawable(self):
        with self.c:
            wallet.credit_verified(self.c,101,"gift-ref-0001","daily_bonus",900_000)
            with self.assertRaises(ValueError):
                wallet.reserve_cashout(self.c,101,"out-1010",1)
        self.assertEqual(self.balances()["earned_micro"],0)

    def test_reused_provider_reference_is_rejected(self):
        with self.c:
            wallet.credit_verified(self.c,101,"same-reference","stars_purchase",200_000)
        with self.assertRaises(ValueError):
            with self.c:
                wallet.credit_verified(self.c,102,"same-reference","stars_purchase",200_000)
        with self.assertRaises(ValueError):
            with self.c:
                wallet.credit_verified(self.c,101,"same-reference","stars_purchase",300_000)

    def test_cancel_restores_cashout_eligibility(self):
        with self.c:
            wallet.credit_verified(self.c,101,"earned-101","confirmed_ad_reward",200_000)
            wallet.reserve_cashout(self.c,101,"cash-101",150_000)
            self.assertTrue(wallet.finalize_cashout(self.c,101,"cash-101",False))
        row=self.balances()
        self.assertEqual((row["earned_micro"],row["reserved_micro"]),(200_000,0))

if __name__=="__main__":
    unittest.main()
