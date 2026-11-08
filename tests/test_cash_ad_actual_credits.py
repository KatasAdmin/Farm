"""Cash advertising payouts: duplicate Monetag postbacks and microcredits."""
import unittest
from decimal import Decimal
from unittest.mock import patch

import bot_cash_ad_credits as credits
from bot_economy import monetag_cash_allocation


class Result:
    def __init__(self,value=None):
        self.value=value
    def fetchone(self):
        return self.value


class FakeDb:
    def __init__(self):
        self.events={}
        self.accounts={11:0,22:0}
        self.fractions={}
        self.credited={}
        self.entries=[]
        self.locked=[]
    def execute(self,sql,args=()):
        normalized=" ".join(sql.split()).lower()
        if normalized.startswith("select viewer_uid,allocation"):
            return Result(self.events.get(args[0]))
        if normalized.startswith("select pg_advisory_xact_lock"):
            return Result(None)
        if normalized.startswith("select 1 from bot_accounts"):
            return Result({"present":1} if args[0] in self.accounts else None)
        if normalized.startswith("insert into bot_cash_ad_credits"):
            ymid,uid,usd,amount,_=args
            key=(ymid,uid,"viewer",0)
            if key in self.credited:return Result(None)
            self.credited[key]={"usd":usd,"kopeks":amount}
            return Result({"uid":uid})
        if normalized.startswith("insert into bot_cash_ad_fraction"):
            self.fractions.setdefault(args[0],Decimal(0))
            return Result()
        if normalized.startswith("select remainder from bot_cash_ad_fraction"):
            return Result({"remainder":self.fractions[args[0]]})
        if normalized.startswith("update bot_cash_ad_fraction"):
            self.fractions[args[1]]=Decimal(args[0])
            return Result()
        if normalized.startswith("update bot_cash_ad_credits"):
            amount,ymid,uid,role,level=args
            self.credited[(ymid,uid,role,level)]["kopeks"]=amount
            return Result()
        if normalized.startswith("update bot_accounts"):
            amount,uid=args
            self.accounts[uid]+=amount
            return Result({"uid":uid})
        if normalized.startswith("insert into bot_ledger"):
            self.entries.append(args)
            return Result()
        raise AssertionError("Unexpected SQL: "+normalized[:180])


class CashAdPayoutTests(unittest.TestCase):
    def valued(self,db,ymid,price,referrer=None):
        chain=(referrer,) if referrer is not None else ()
        db.events[ymid]={
            "viewer_uid":11,
            "allocation":monetag_cash_allocation(Decimal(price),chain),
            "reward_event_type":"valued",
            "event_type":"impression",
            "estimated_usd":Decimal(price)
        }
    def test_every_valued_event_pays_five_kopeks_with_no_ad_referrals(self):
        db=FakeDb()
        for n in range(3):
            self.valued(db,str(n),"0.0003000",referrer=22)
            result=credits.credit_verified_event(db,str(n))
            self.assertEqual(result["credited_kopeks"],5)
        self.assertEqual(db.accounts[11],15)
        self.assertEqual(db.accounts[22],0)
        self.assertEqual(sum(item[2] for item in db.entries),15)
        self.assertEqual(len(db.credited),3)
    def test_duplicate_postback_never_pays_twice(self):
        db=FakeDb()
        self.valued(db,"duplicate","0.010000",referrer=22)
        credits.credit_verified_event(db,"duplicate")
        before=(dict(db.accounts),dict(db.fractions),len(db.entries))
        credits.credit_verified_event(db,"duplicate")
        self.assertEqual((db.accounts,db.fractions,len(db.entries)),before)
    def test_nonvalued_event_not_paid(self):
        db=FakeDb()
        self.valued(db,"nonvalue","0.003")
        db.events["nonvalue"]["reward_event_type"]="non_valued"
        outcome=credits.credit_verified_event(db,"nonvalue")
        self.assertFalse(outcome["credited"])
        self.assertEqual(db.accounts[11],0)

    def test_legacy_referral_snapshots_no_longer_pay_ad_cash_referrals(self):
        db=FakeDb()
        self.valued(db,"all-levels","1.0")
        chain=tuple(range(22,29))
        db.accounts.update(dict.fromkeys(chain,0))
        db.events["all-levels"]["allocation"]=monetag_cash_allocation(Decimal(1),chain)
        result=credits.credit_verified_event(db,"all-levels")
        self.assertEqual(db.accounts[11],5)
        self.assertTrue(all(db.accounts[x]==0 for x in chain))
        self.assertEqual(result["credited_kopeks"],5)
        self.assertEqual(len(db.entries),1)


if __name__=="__main__":
    unittest.main()
