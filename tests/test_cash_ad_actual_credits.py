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
            ymid,uid,role,level,usd,rate,_=args
            key=(ymid,uid,role,level)
            if key in self.credited:return Result(None)
            self.credited[key]={"usd":usd,"kopeks":0}
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
    def test_fractional_kopeks_accumulate_without_inflation(self):
        db=FakeDb()
        with patch.object(credits,"nbu_usd_uah",return_value=Decimal("45.443200")):
            for n in range(3):
                self.valued(db,str(n),"0.0003000",referrer=22)
                credits.credit_verified_event(db,str(n))
        # 30% viewer of $0.0003 = 0.4089888 kopeks per event.
        self.assertEqual(db.accounts[11],1)
        self.assertEqual(db.accounts[22],0)
        self.assertGreater(db.fractions[11],0)
        self.assertLess(db.fractions[11],1)
        self.assertEqual(sum(item[2] for item in db.entries),1)
    def test_duplicate_postback_never_pays_twice(self):
        db=FakeDb()
        self.valued(db,"duplicate","0.010000",referrer=22)
        with patch.object(credits,"nbu_usd_uah",return_value=Decimal("45.443200")):
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

    def test_confirmed_impression_funds_viewer_and_all_seven_referral_levels(self):
        db=FakeDb()
        self.valued(db,"all-levels","1.0")
        chain=tuple(range(22,29))
        db.accounts.update(dict.fromkeys(chain,0))
        allocation=monetag_cash_allocation(Decimal(1),chain)
        db.events["all-levels"]["allocation"]=allocation
        with patch.object(credits,"nbu_usd_uah",return_value=Decimal("40")):
            result=credits.credit_verified_event(db,"all-levels")
        self.assertEqual(Decimal(allocation["platform_usd"]),Decimal("0.35"))
        self.assertEqual(list(db.accounts.values()),[1200,400,280,200,160,120,120,120])
        self.assertEqual(result["credited_kopeks"],2600)
        self.assertEqual(len(db.entries),8)


if __name__=="__main__":
    unittest.main()
