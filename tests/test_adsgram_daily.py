"""AdsGram daily payout tests: proportional viewers, seven-level shares and replay safety."""
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch
import bot_adsgram_daily as ads


class Query:
    def __init__(self, value=None, rows=None):
        self.value=value
        self.rows=rows or []
    def fetchone(self):
        return self.value
    def fetchall(self):
        return self.rows


class FakeDB:
    def __init__(self, rows, farm_count=0):
        self.rows=rows
        self.farm_count=farm_count
        self.settlements={}
        self.balances={1:0,2:0,3:0}
        self.fractions={}
        self.credits=[]
        self.ledger=[]
    def execute(self,sql,args=()):
        query=' '.join(sql.lower().split())
        if query.startswith('select pg_advisory_xact_lock'):
            return Query()
        if query.startswith('select 1 from bot_adsgram_daily_settlements'):
            return Query({'found':1} if args[0] in self.settlements else None)
        if query.startswith('select uid,referral_chain from bot_adsgram_attempts'):
            return Query(rows=self.rows)
        if query.startswith('select count(*) as n from bot_adsgram_farm_attempts'):
            return Query({'n':self.farm_count})
        if query.startswith('insert into bot_adsgram_daily_settlements'):
            day,revenue,impressions,rate,created,owner=args
            self.settlements[day]={'revenue':revenue,'impressions':impressions,'credited':0}
            return Query()
        if query.startswith('select 1 from bot_accounts'):
            return Query({'ok':1} if args[0] in self.balances else None)
        if query.startswith('insert into bot_cash_ad_fraction'):
            self.fractions.setdefault(args[0],Decimal(0))
            return Query()
        if query.startswith('select remainder from bot_cash_ad_fraction'):
            return Query({'remainder':self.fractions[args[0]]})
        if query.startswith('update bot_cash_ad_fraction'):
            self.fractions[args[1]]=Decimal(args[0])
            return Query()
        if query.startswith('insert into bot_adsgram_daily_credits'):
            self.credits.append(args)
            return Query()
        if query.startswith('update bot_accounts'):
            amount,uid=args
            self.balances[uid]+=amount
            return Query()
        if query.startswith('insert into bot_ledger'):
            self.ledger.append(args)
            return Query()
        if query.startswith('update bot_adsgram_daily_settlements'):
            self.settlements[args[1]]['credited']=args[0]
            return Query()
        raise AssertionError('Unexpected SQL: '+query[:150])


class DailyAdsGramTests(unittest.TestCase):
    def day(self):
        return (datetime.now(timezone.utc).date()-timedelta(days=2)).isoformat()

    def test_five_and_ten_views_split_proportionally(self):
        rows=[{'uid':1,'referral_chain':[3]} for _ in range(5)]
        rows +=[{'uid':2,'referral_chain':[]} for _ in range(10)]
        db=FakeDB(rows)
        with patch.object(ads,'nbu_usd_uah',return_value=Decimal('40')):
            result=ads.settle_day(db,self.day(),'1.50',15,1)
        self.assertEqual(result['credited_kopeks'],2000)
        self.assertEqual(db.balances[1],600)  # viewer 5x
        self.assertEqual(db.balances[2],1200) # viewer 10x
        self.assertEqual(db.balances[3],200)  # 10% from 5 views
        self.assertEqual(len(db.ledger),3)
        self.assertEqual(sum(x[2] for x in db.ledger),2000)
        self.assertEqual(db.settlements[self.day()]['impressions'],15)

    def test_farm_views_count_in_shared_block_but_not_cash_rewarded(self):
        db=FakeDB([{'uid':1,'referral_chain':[]}],farm_count=1)
        with patch.object(ads,'nbu_usd_uah',return_value=Decimal('40')):
            result=ads.settle_day(db,self.day(),'0.20',2,1)
        self.assertEqual(result['cash_views'],1)
        self.assertEqual(result['farm_views'],1)
        self.assertEqual(db.balances[1],120)  # 30% of cash view's $0.10

    def test_duplicate_day_never_credits_again(self):
        db=FakeDB([{'uid':1,'referral_chain':[]}])
        with patch.object(ads,'nbu_usd_uah',return_value=Decimal('40')):
            ads.settle_day(db,self.day(),'0.10',1,1)
            before=dict(db.balances)
            with self.assertRaisesRegex(ValueError,'already reconciled'):
                ads.settle_day(db,self.day(),'0.10',1,1)
            self.assertEqual(db.balances,before)

    def test_dashboard_impression_mismatch_rejected(self):
        db=FakeDB([{'uid':1,'referral_chain':[]}])
        with self.assertRaisesRegex(ValueError,'do not match'):
            ads.settle_day(db,self.day(),'0.10',2,1)
        self.assertFalse(db.settlements)

    def test_reject_current_day(self):
        with self.assertRaises(ValueError):
            ads._day(datetime.now(timezone.utc).date().isoformat())


if __name__=='__main__':
    unittest.main()
