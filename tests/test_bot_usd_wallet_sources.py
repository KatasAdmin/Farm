import unittest
from bot_usd_wallet_sources import (
    USDWallet, credit, spend, reserve_cashout, cancel_cashout, complete_cashout,
)

class USDWalletSourceTests(unittest.TestCase):
    def test_stars_cannot_be_withdrawn(self):
        w=credit(USDWallet(),"stars_purchase",1_000_000)
        self.assertEqual(w.available_micro,1_000_000)
        self.assertEqual(w.cashout_available_micro,0)
        with self.assertRaises(ValueError):
            reserve_cashout(w,1)

    def test_earned_work_can_be_reserved_once(self):
        w=credit(USDWallet(),"task_reward",200_000)
        w=reserve_cashout(w,150_000)
        self.assertEqual(w.available_micro,50_000)
        with self.assertRaises(ValueError):
            reserve_cashout(w,100_000)
        settled=complete_cashout(w,150_000)
        self.assertEqual(settled.earned_micro,50_000)
        self.assertEqual(settled.cashout_reserved_micro,0)

    def test_purchase_spend_does_not_erase_withdrawable_earnings_first(self):
        w=credit(credit(USDWallet(),"stars_purchase",100_000),"task_reward",300_000)
        w=spend(w,150_000)
        self.assertEqual(w.spend_only_micro,0)
        self.assertEqual(w.cashout_available_micro,250_000)

    def test_cancel_returns_reserved_earnings_once(self):
        w=reserve_cashout(credit(USDWallet(),"confirmed_ad_reward",100_000),70_000)
        returned=cancel_cashout(w,70_000)
        self.assertEqual(returned.cashout_available_micro,100_000)
        with self.assertRaises(ValueError):
            cancel_cashout(returned,70_000)

    def test_bonuses_and_card_deposits_are_not_earnings(self):
        w=USDWallet()
        for src in ("card_purchase","promo","daily_bonus","game_purchase"):
            w=credit(w,src,10_000)
        self.assertEqual(w.cashout_available_micro,0)
        self.assertEqual(w.available_micro,40_000)

    def test_invariant_rejects_negative_or_unknown_money_sources(self):
        with self.assertRaises(ValueError):
            USDWallet(earned_micro=1,cashout_reserved_micro=2)
        with self.assertRaises(ValueError):
            credit(USDWallet(),"unknown",10)
        with self.assertRaises(ValueError):
            spend(USDWallet(),1)

if __name__=="__main__":
    unittest.main()
