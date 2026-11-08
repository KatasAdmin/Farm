"""AdsGram publisher balance snapshots are audit-only; they never mint rewards."""
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
        self.farm_allocations=[]
    def execute(self,sql,args=()):
        q=' '.join(sql.lower().split())
        if q.startswith("select value from bot_controls where key='adsgram_view_reward'"):
            return Query({'value':3})
        if q.startswith('select pg_advisory_xact_lock'):
            return Query()
        if q.startswith('select * from bot_adsgram_balance_checkpoints'):
            return Query(self.checkpoints[-1] if self.checkpoints else None)
        if q.startswith('select 1 from bot_adsgram_daily_settlements'):
            return Query()
        if q.startswith('select id,uid,referral_chain,paid_immediate from bot_adsgram_attempts'):
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
        if q.startswith('insert into farm_adsgram_revenue_allocations'):
            self.farm_allocations.append(args)
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
        self.assertEqual(db.wallet[2],0)  # All cash rewards arrive at callback, never here
        self.assertEqual(earned['credited_kopeks'],0)
        self.assertTrue(earned['report_only'])
        self.assertEqual(len(db.farm_allocations),0)
        self.assertEqual(len(db.credits),0)
        self.assertEqual(len(db.ledger),0)
        repeated=ads.report(db,1,'1.60',now=t+200)
        self.assertTrue(repeated['unchanged'])
        self.assertEqual(len(db.checkpoints),2)
        self.assertEqual(db.wallet[2],0)

    def test_low_revenue_does_not_block_fixed_reward_for_preexisting_unpaid_views(self):
        db=FakeDB()
        t=1762500000.0
        ads.report(db,1,'1.00',now=t)
        db.views=[{'id':'tiny','uid':2,'referral_chain':[],'confirmed_at':t+2}]
        with patch.object(ads,'nbu_usd_uah',return_value=Decimal('40')):
            result=ads.report(db,1,'1.0001',now=t+20)
        self.assertEqual(result['delta'],'0.0001')
        self.assertEqual(db.wallet[2],0)
        self.assertEqual(len(db.checkpoints),2)

    def test_revenue_without_confirmed_views_cannot_be_distributed(self):
        db=FakeDB()
        t=1762500000.0
        ads.report(db,1,'1.0',now=t)
        with self.assertRaisesRegex(ValueError,'нет подтверждённых'):
            ads.report(db,1,'1.5',now=t+60)
        self.assertEqual(len(db.checkpoints),1)

    def test_reset_starts_new_epoch_without_paying_or_replaying_old_views(self):
        db=FakeDB()
        t=1762500000.0
        ads.report(db,1,'1.00',now=t)
        # Revenue grew without SDK-verified views: regular report rejects it.
        with self.assertRaisesRegex(ValueError,'нет подтверждённых'):
            ads.report(db,1,'1.50',now=t+60)
        reset=ads.reset_baseline(db,1,'1.50',now=t+61)
        self.assertEqual(reset['previous'],'1.00')
        self.assertEqual(len(db.checkpoints),2)
        self.assertEqual(db.wallet[2],0)
        self.assertFalse(db.credits)
        self.assertFalse(db.ledger)
        self.assertEqual(db.checkpoints[-1]['delta_usd'],0)
        # An older callback cannot receive revenue from after the reset.
        db.views=[{'id':'old','uid':2,'referral_chain':[],'confirmed_at':t+10},
                  {'id':'new','uid':2,'referral_chain':[],'confirmed_at':t+70}]
        with patch.object(ads,'nbu_usd_uah',return_value=Decimal('40')):
            result=ads.report(db,1,'1.70',now=t+90)
        self.assertEqual(result['delta'],'0.20')
        self.assertEqual(result['cash_views'],1)
        self.assertEqual(db.wallet[2],3)
        self.assertEqual(len(db.ledger),0)

    def test_reset_preserves_earlier_paid_credits_and_allows_lower_balance(self):
        db=FakeDB()
        t=1762500000.0
        ads.report(db,1,'5.00',now=t)
        db.views=[{'id':'paid','uid':2,'referral_chain':[],'confirmed_at':t+10}]
        with patch.object(ads,'nbu_usd_uah',return_value=Decimal('40')):
            ads.report(db,1,'6.00',now=t+30)
        previous=db.wallet[2]
        count=len(db.credits)
        reset=ads.reset_baseline(db,1,'0.90',now=t+40)
        self.assertEqual(reset['previous'],'6.00')
        self.assertEqual(db.wallet[2],previous)
        self.assertEqual(len(db.credits),count)
        with self.assertRaisesRegex(ValueError,'позже предыдущей'):
            ads.reset_baseline(db,1,'0.90',now=t+40)
        with self.assertRaisesRegex(ValueError,'корректный баланс'):
            ads.reset_baseline(db,1,'NaN',now=t+50)

    def test_decrease_never_rewrites_previous_checkpoint(self):
        db=FakeDB()
        t=1762500000.0
        ads.report(db,1,'1.0',now=t)
        with self.assertRaisesRegex(ValueError,'Баланс уменьшился'):
            ads.report(db,1,'0.9',now=t+60)
        self.assertEqual(len(db.checkpoints),1)


if __name__=='__main__':
    unittest.main()
