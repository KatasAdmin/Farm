"""Cumulative AdsGram publisher snapshots: delta, viewer weighting, and replay guards."""
import unittest
from decimal import Decimal
from unittest.mock import patch
import bot_adsgram_intervals as ads


class Query:
    def __init__(self, one=None, many=None):
        self.one=one
        self.many=many or []
    def fetchone(self):
        return self.one
    def fetchall(self):
        return self.many


class FakeDB:
    def __init__(self):
        self.checkpoints=[]
        self.views=[]
        self.farm=[]
        self.wallet={2:0,3:0}
        self.fraction={}
        self.credits=[]
        self.ledger=[]
    def execute(self,sql,args=()):
        q=' '.join(sql.lower().split())
        if q.startswith('select pg_advisory_xact_lock'):
            return Query()
        if q.startswith('select * from bot_adsgram_balance_checkpoints'):
            return Query(self.checkpoints[-1] if self.checkpoints else None)
        if q.startswith('select 1 from bot_adsgram_daily_settlements'):
            return Query()
        if q.startswith('select id,uid,referral_chain from bot_adsgram_attempts'):
            lo,hi=args
            return Query(many=[x for x in self.views if lo<=x['confirmed_at']<hi])
        if q.startswith('select count(*) as n from bot_adsgram_farm_attempts'):
            lo,hi=args
            return Query({'n':len([x for x in self.farm if lo<=x<hi])})
        if q.startswith('insert into bot_adsgram_balance_checkpoints'):
            if len(args)==5:
                ident,at,balance,uid,created=args
                row={'id':ident,'observed_at':at,'cumulative_usd':balance,'delta_usd':Decimal(0),
                     'owner_uid':uid,'credited_kopeks':0}
            else:
                ident,at,balance,delta,cash,farm,uid,created=args
                row={'id':ident,'observed_at':at,'cumulative_usd':balance,'delta_usd':delta,
                     'owner_uid':uid,'cash_views':cash,'farm_views':farm,'credited_kopeks':0}
            self.checkpoints.append(row)
            return Query()
        if q.startswith('select 1 from bot_accounts'):
            return Query({'ok':1} if args[0] in self.wallet else None)
        if q.startswith('insert into bot_cash_ad_fraction'):
            self.fraction.setdefault(args[0],Decimal(0))
            return Query()
        if q.startswith('select remainder from bot_cash_ad_fraction'):
            return Query({'remainder':self.fraction[args[0]]})
        if q.startswith('update bot_cash_ad_fraction'):
            self.fraction[args[1]]=Decimal(str(args[0]))
            return Query()
        if q.startswith('insert into bot_adsgram_interval_credits'):
            self.credits.append(args)
            return Query()
        if q.startswith('update bot_accounts'):
            n,uid=args
            self.wallet[uid]+=n
            return Query()
        if q.startswith('insert into bot_ledger'):
            self.ledger.append(args)
            return Query()
        if q.startswith('update bot_adsgram_balance_checkpoints'):
            self.checkpoints[-1]['credited_kopeks']=args[0]
            return Query()
        raise AssertionError('Unexpected SQL: '+q[:160])


class IntervalTests(unittest.TestCase):
    def test_two_reports_pay_only_increment_and_weight_confirmed_views(self):
        db=FakeDB()
        t=1762500000.0
        baseline=ads.report(db,1,'1.00',now=t)
        self.assertTrue(baseline['baseline'])
        self.assertEqual(db.wallet[2],0)
        db.views=[{'id':'a','uid':2,'referral_chain':[],'confirmed_at':t+10},
                  {'id':'b','uid':2,'referral_chain':[],'confirmed_at':t+20}]
        db.farm=[t+30]
        with patch.object(ads,'nbu_usd_uah',return_value=Decimal('40')):
            earned=ads.report(db,1,'1.60',now=t+100)
        self.assertEqual(earned['delta'],'0.60')
        self.assertEqual((earned['cash_views'],earned['farm_views']),(2,1))
        self.assertEqual(db.wallet[2],480)  # 2 bot views x $0.20 x 30% x 40 UAH
        self.assertEqual(earned['credited_kopeks'],480)
        self.assertEqual(len(db.credits),1)
        self.assertEqual(len(db.ledger),1)
        repeated=ads.report(db,1,'1.60',now=t+200)
        self.assertTrue(repeated['unchanged'])
        self.assertEqual(len(db.checkpoints),2)
        self.assertEqual(db.wallet[2],480)

    def test_revenue_without_confirmed_views_cannot_be_distributed(self):
        db=FakeDB()
        t=1762500000.0
        ads.report(db,1,'1.0',now=t)
        with self.assertRaisesRegex(ValueError,'нет подтверждённых'):
            ads.report(db,1,'1.5',now=t+60)
        self.assertEqual(len(db.checkpoints),1)

    def test_decrease_never_rewrites_previous_checkpoint(self):
        db=FakeDB()
        t=1762500000.0
        ads.report(db,1,'1.0',now=t)
        with self.assertRaisesRegex(ValueError,'Баланс уменьшился'):
            ads.report(db,1,'0.9',now=t+60)
        self.assertEqual(len(db.checkpoints),1)


if __name__=='__main__':
    unittest.main()
