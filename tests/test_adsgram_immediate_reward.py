"""Verify direct bot rewarded-view credits without daily or /reklama dependence."""
import time
import unittest
import bot_adsgram_daily as ad


class Q:
    def __init__(self,one=None):self.one=one
    def fetchone(self):return self.one


class ImmediateDB:
    def __init__(self,reward=5):
        self.pending=True
        self.reward=reward
        self.balance=100
        self.credits=[]
        self.ledger=[]
        self.attempt="ad-test-1"
        self.started=time.time()-1

    def execute(self,sql,args=()):
        q=' '.join(sql.lower().split())
        if q.startswith("select pg_advisory_xact_lock"):
            return Q()
        if q.startswith("select id,started_at from bot_adsgram_attempts"):
            return Q({'id':self.attempt,'started_at':self.started} if self.pending else None)
        if q.startswith("select id,player_id,item,started_at from bot_adsgram_farm_attempts"):
            return Q()
        if q.startswith("select value from bot_controls"):
            return Q({'value':self.reward})
        if q.startswith("update bot_adsgram_attempts"):
            self.pending=False
            return Q()
        if q.startswith("insert into bot_adsgram_immediate_rewards"):
            self.credits.append(args)
            return Q()
        if q.startswith("update bot_accounts set available=available"):
            self.balance+=args[0]
            return Q({'uid':args[1]})
        if q.startswith("insert into bot_ledger"):
            self.ledger.append(args)
            return Q()
        raise AssertionError(q)


class ConfirmedCashRewardTests(unittest.TestCase):
    def test_fixed_five_kopeks_once_at_confirmation(self):
        c=ImmediateDB()
        self.assertEqual(ad.confirm(c,7)['credited_kopeks'],5)
        self.assertEqual(c.balance,105)
        self.assertEqual(len(c.credits),1)
        self.assertEqual(len(c.ledger),1)
        self.assertFalse(ad.confirm(c,7)['confirmed'])
        self.assertEqual(c.balance,105)

    def test_owner_can_change_reward_for_new_confirmations(self):
        c=ImmediateDB(reward=7)
        self.assertEqual(ad.confirm(c,7)['credited_kopeks'],7)
        self.assertEqual(c.balance,107)
        self.assertEqual(c.credits[0][2],7)


if __name__=='__main__':
    unittest.main()
