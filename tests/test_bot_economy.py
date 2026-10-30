"""Financial conservation, debt, terms snapshots and authentic leave events."""
import time
import unittest
from unittest.mock import patch
import task_bot as bot
import bot_economy as eco
import test_task_bot as base


class EconomyTests(unittest.TestCase):
    setUp = base.TaskBotTests.setUp
    api = base.TaskBotTests.api
    send = base.TaskBotTests.send
    credit = base.TaskBotTests.credit
    balance = base.TaskBotTests.balance
    task = base.TaskBotTests.task
    invariant = base.TaskBotTests.invariant

    def row(self, table, where='', args=()):
        return self.c.execute('SELECT * FROM '+table+(' WHERE '+where if where else ''),args).fetchone()

    def paid_membership(self):
        tid=self.task()
        self.send(3,action='take:'+tid)
        self.joined=True
        self.send(3,action='check:'+tid)
        self.assertEqual(self.balance(3),56)
        return tid

    def leave(self,tid,actor=3,when=None,event=12345,new='left'):
        r=self.row('bot_retention','task=%s',(tid,))
        payload={'update_id':event,'chat_member':{
            'chat':{'id':-10012,'type':'channel'},'from':{'id':actor},
            'date':int(r['started'] if when is None else when),
            'old_chat_member':{'user':{'id':3},'status':'member'},
            'new_chat_member':{'user':{'id':3},'status':new}}}
        return bot.handle(payload,lambda:self.c,self.api,lambda u,c:u==1)

    def test_prices_bonus_and_one_time_migration(self):
        self.assertEqual(self.row('bot_settings')['daily'],50)
        for kind,cost,reward in [('channel',70,56),('group',60,48),('bot',40,32),('post',4,3),('manual',100,80)]:
            q=eco.quote(self.c,kind)
            self.assertEqual((q['cost'],q['reward']),(cost,reward))
            self.assertEqual(sum(q['refs']),1000)
        self.c.execute('UPDATE bot_settings SET daily=25')
        bot.initialize(self.c)
        self.c.raw.commit()
        self.assertEqual(self.row('bot_settings')['daily'],25)

    def test_five_levels_exact_from_gross_not_net_reward(self):
        # 3 -> 4 -> 5 -> 6 -> 7 -> 8, each registered with an existing parent.
        self.send(8,'/start')
        for uid in (7,6,5,4):
            self.send(uid,f'/start partner_{uid+1}')
        self.c.execute('UPDATE bot_accounts SET referrer=4 WHERE uid=3')
        self.c.raw.commit()
        self.credit(2,'100','large-order')
        self.send(2,action='new:manual')
        for value in ('Big task','A manual proof is required','https://example.com','100','1'):
            self.send(2,value)
        self.send(2,action='confirm_task')
        tid=self.row('bot_tasks')['id']
        self.send(1,action='admin:approve:'+tid)
        self.send(3,action='take:'+tid)
        self.send(3,action='check:'+tid)
        self.send(3,'The proof')
        self.send(2,action=f'accept:{tid}:3')
        self.send(2,action=f'accept:{tid}:3')
        self.assertEqual(self.balance(3),8000)
        for uid,n in [(4,500),(5,250),(6,150),(7,75),(8,25)]:
            self.assertEqual(self.balance(uid),n)
        s=self.row('bot_task_settlements')
        self.assertEqual(s['cost']*10000,s['reward']*10000+s['ref_units']+s['platform_units'])
        self.assertEqual(s['platform_units'],1000*10000)
        self.invariant()

    def test_fractional_referrals_accumulate_and_reserve_liability(self):
        self.send(4,'/start partner_1')
        tid=self.task()
        self.send(4,action='take:'+tid)
        self.joined=True
        self.send(4,action='check:'+tid)
        self.assertEqual(self.balance(1),3)
        self.assertEqual(self.row('bot_ref_accruals')['units'],5000)
        self.send(5,'/start partner_1')
        self.joined=False
        self.send(5,action='take:'+tid)
        self.joined=True
        self.send(5,action='check:'+tid)
        self.assertEqual(self.balance(1),7)
        self.assertEqual(self.row('bot_ref_accruals')['units'],0)
        self.assertEqual(self.row('bot_tasks')['remaining'],0)
        self.invariant()

    def test_referral_cycle_does_not_mint_or_self_pay(self):
        self.c.execute('UPDATE bot_accounts SET referrer=1 WHERE uid=3')
        self.c.execute('UPDATE bot_accounts SET referrer=3 WHERE uid=1')
        self.c.raw.commit()
        self.paid_membership()
        self.assertEqual(self.balance(1),3)
        self.assertEqual(self.balance(3),56)
        self.assertEqual(self.c.execute('SELECT count(*) AS n FROM bot_ref_rewards').fetchone()['n'],1)
        self.invariant()

    def test_voluntary_leave_full_refund_fine_and_replay(self):
        tid=self.paid_membership()
        self.leave(tid)
        self.leave(tid)
        self.leave(tid,event=12346)
        self.assertEqual(self.balance(3),0)
        self.assertEqual(self.row('bot_debts')['amount'],56)
        self.assertEqual(self.balance(2),930)  # 860 + full 70 refund
        self.assertEqual(self.row('bot_retention')['state'],'violated')
        self.assertEqual(self.c.execute("SELECT count(*) AS n FROM bot_ledger WHERE kind='retention_refund'").fetchone()['n'],1)
        self.assertEqual(self.row('bot_cash_pool')['amount'],1000)
        self.invariant()

    def test_spent_reward_debt_not_cash_and_unfunded_refund_visible(self):
        tid=self.paid_membership()
        self.send(3,action='withdraw')
        self.send(3,'0.56')
        self.send(3,'UA123456789 User')
        self.send(3,action='confirm_payout')
        pid=self.row('bot_payouts')['id']
        self.send(1,f'/botpaid {pid} bank-executed')
        self.send(1,action='admin:payconfirm')
        self.assertEqual(self.row('bot_cash_pool')['amount'],944)
        self.leave(tid)
        self.assertEqual(self.row('bot_debts')['amount'],112)
        self.assertEqual(self.balance(2),930)
        # 70 task budget still reserved + refunded 930; no fictitious cash deposit.
        self.assertEqual(bot.liability(self.c),1000)
        self.assertEqual(self.row('bot_cash_pool')['amount'],944)
        self.assertIn('Нехватка покрытия: 0,56 грн',self.send(1,'/botadmin')['text'])
        self.credit(3,'0.50','debt-topup')
        self.assertEqual(self.balance(3),0)
        self.assertEqual(self.row('bot_debts')['amount'],62)
        self.credit(3,'1','debt-topup2')
        self.assertEqual(self.balance(3),38)
        self.assertEqual(self.row('bot_debts')['amount'],0)
        self.invariant()

    def test_pending_payout_cancelled_and_its_reserve_collected(self):
        tid=self.paid_membership()
        self.send(3,action='withdraw')
        self.send(3,'0.56')
        self.send(3,'UA123456789 User')
        self.send(3,action='confirm_payout')
        self.leave(tid)
        self.assertEqual(self.row('bot_payouts')['status'],'cancelled')
        self.assertEqual(self.row('bot_debts')['amount'],56)
        self.assertEqual(self.balance(3),0)
        self.invariant()

    def test_referrals_never_clawed_back_on_leave(self):
        self.c.execute('UPDATE bot_accounts SET referrer=1 WHERE uid=3')
        self.c.raw.commit()
        tid=self.paid_membership()
        self.assertEqual(self.balance(1),3)
        self.leave(tid)
        self.assertEqual(self.balance(1),3)
        self.assertEqual(self.row('bot_ref_accruals')['units'],5000)
        self.assertEqual(bot.liability(self.c),1004)  # retained referrals remain obligations
        self.assertEqual(self.row('bot_cash_pool')['amount'],1000)

    def test_admin_kick_never_penalizes(self):
        tid=self.paid_membership()
        self.leave(tid,actor=44,new='kicked')
        self.assertEqual(self.row('bot_retention')['state'],'exempt')
        self.assertIsNone(self.row('bot_debts'))
        self.assertEqual(self.balance(3),56)
        self.assertEqual(self.balance(2),860)

    def test_exact_deadline_not_penalized_but_delayed_early_event_is(self):
        tid=self.paid_membership()
        r=self.row('bot_retention')
        with patch('bot_economy.time.time',return_value=r['deadline']+2):
            self.leave(tid,when=r['deadline'])
        self.assertIsNone(self.row('bot_debts'))
        # A delayed event about an earlier departure is still applied after clearance.
        self.c.execute("UPDATE bot_retention SET state='cleared'")
        self.c.raw.commit()
        with patch('bot_economy.time.time',return_value=r['deadline']+2):
            self.leave(tid,when=r['deadline']-1,event=12346)
        self.assertEqual(self.row('bot_debts')['amount'],56)

    def test_poll_failure_or_missing_admin_rights_never_fines(self):
        self.paid_membership()
        self.c.execute('UPDATE bot_retention SET next_check=0')
        self.c.raw.commit()
        self.errors=True
        eco.sweep(lambda:self.c,self.api)
        self.assertIsNone(self.row('bot_debts'))
        self.errors=False
        self.c.execute('UPDATE bot_retention SET next_check=0')
        self.c.raw.commit()
        def no_rights(method,args):
            return {'id':99} if method=='getMe' else {'status':'left'}
        eco.sweep(lambda:self.c,no_rights)
        self.assertIsNone(self.row('bot_debts'))
        self.assertEqual(self.row('bot_retention')['state'],'watching')

    def test_ambiguous_poll_goes_to_review_and_admin_can_exempt(self):
        self.paid_membership()
        self.c.execute('UPDATE bot_retention SET next_check=0')
        self.c.raw.commit()
        self.joined=False
        eco.sweep(lambda:self.c,self.api)
        self.assertEqual(self.row('bot_retention')['state'],'review')
        self.assertIsNone(self.row('bot_debts'))
        self.send(1,action='admin:retention')
        nonce=bot.state(self.c,1)['data']['nonce']
        self.send(3,action='admin:retfine:'+nonce)
        self.assertIsNone(self.row('bot_debts'))
        self.send(1,action='admin:retexempt:'+nonce)
        self.assertEqual(self.row('bot_retention')['state'],'exempt')

    def test_verified_subscription_at_deadline_completes(self):
        self.paid_membership()
        r=self.row('bot_retention')
        self.c.execute('UPDATE bot_retention SET next_check=0')
        self.c.raw.commit()
        with patch('bot_economy.time.time',return_value=r['deadline']):
            eco.sweep(lambda:self.c,self.api)
        self.assertEqual(self.row('bot_retention')['state'],'cleared')
        self.assertIsNone(self.row('bot_debts'))

    def test_admin_edit_prices_rates_and_snapshots(self):
        tid=self.task()
        self.send(1,action='admin:ecoedit:prices')
        self.send(1,'1.00 0.50 0.80 0.05 0.03 2.00')
        self.assertEqual(eco.quote(self.c,'channel')['cost'],100)
        self.send(1,action='admin:ecoedit:rates')
        self.send(1,'30 5 2.5 1.5 0.75 0.25')
        self.send(1,action='admin:ecoedit:retention')
        self.send(1,'10 3')
        self.assertEqual(eco.quote(self.c,'channel')['reward'],70)
        q=eco.terms(self.c,tid)
        self.assertEqual((q['cost'],q['days'],q['multiplier']),(70,7,2))
        self.send(3,action='take:'+tid)
        self.joined=True
        self.send(3,action='check:'+tid)
        self.assertEqual(self.balance(3),56)
        self.assertEqual(self.row('bot_retention')['fine'],112)

    def test_admin_edit_validation_rollback_and_forged_input(self):
        self.send(3,action='admin:ecoedit:rates')
        self.send(3,'1 99 0 0 0 0')
        self.assertEqual(eco.config(self.c)['fee'],2000)
        self.send(1,action='admin:ecoedit:rates')
        self.send(1,'5 5 2.5 1.5 0.75 0.25')
        self.assertEqual(eco.config(self.c)['fee'],2000)
        self.send(1,action='admin:ecoedit:prices')
        self.send(1,'1 1 1 0.01 0.03 1')
        self.assertEqual(eco.quote(self.c,'channel')['cost'],70)
        # Stored input alone never grants administrator privileges.
        bot.state(self.c,3,'economy_edit',{'field':'retention'})
        self.c.raw.commit()
        self.send(3,'1 1')
        self.assertEqual(eco.config(self.c)['days'],7)

    def test_legacy_order_is_not_repriced_or_fined(self):
        self.credit()
        with self.c:
            bot.change(self.c,2,-100,'task_budget','legacy funded order')
            self.c.execute("INSERT INTO bot_tasks VALUES('old',2,'channel','Old order','Old agreement','https://t.me/test',-10012,100,100,'active',0)")
        self.send(3,action='take:old')
        self.joined=True
        self.send(3,action='check:old')
        self.assertEqual(self.balance(3),100)
        self.assertIsNone(self.row('bot_retention'))
        self.assertIsNone(self.row('bot_task_settlements'))
        self.invariant()

    def test_claim_cannot_pay_after_bot_loses_administrator_role(self):
        tid=self.task()
        self.send(3,action='take:'+tid)
        self.joined=True
        original=self.api
        def lost_role(method,args):
            if method=='getChatMember' and args['user_id']==99:
                return {'status':'member'}
            return original(method,args)
        self.api=lost_role
        reply=self.send(3,action='check:'+tid)
        self.assertIn('временно недоступна',reply['text'])
        self.assertEqual(self.balance(3),0)
        self.assertEqual(self.row('bot_tasks')['remaining'],140)
        self.assertIsNone(self.row('bot_retention'))

    def test_bonus_settings_without_funding_and_bonus_pays_debt_first(self):
        tid=self.paid_membership()
        self.leave(tid)
        self.send(1,action='admin:ecoedit:bonus')
        self.send(1,'0.50')
        self.assertEqual(self.row('bot_settings')['daily'],50)
        self.send(3,action='daily')
        self.send(3,action='daily')
        self.assertEqual(self.balance(3),0)
        self.assertEqual(self.row('bot_debts')['amount'],6)
        self.assertEqual(self.row('bot_cash_pool')['amount'],1000)
        self.invariant()

    def test_ambiguous_case_confirmed_once_by_owner(self):
        tid=self.paid_membership()
        self.c.execute("UPDATE bot_retention SET state='review'")
        self.c.raw.commit()
        self.send(1,action='admin:retention')
        nonce=bot.state(self.c,1)['data']['nonce']
        self.send(1,action='admin:retfine:'+nonce)
        self.send(1,action='admin:retfine:'+nonce)
        self.assertEqual(self.balance(2),930)
        self.assertEqual(self.row('bot_debts')['amount'],56)
        self.assertEqual(self.row('bot_retention')['state'],'violated')

    def test_terms_present_before_acceptance_and_close_does_not_cancel_retention(self):
        tid=self.paid_membership()
        card=bot.task_card(self.row('bot_tasks'),3,self.c)
        self.assertIn('7 суток',card['text'])
        self.assertIn('штраф 1,12 грн',card['text'])
        self.assertIn('долгом',card['text'])
        self.send(2,action='close:'+tid)
        self.assertEqual(self.balance(2),930)
        self.leave(tid)
        self.assertEqual(self.balance(2),1000)
        self.assertEqual(self.row('bot_tasks')['remaining'],0)
        self.assertIn('Потрачено на рекламу: 0,00 грн',self.send(2,action='cabinet')['text'])

    def test_partner_counts_five_levels_and_cycle_guard(self):
        self.send(4,'/start partner_3')
        self.send(5,'/start partner_4')
        self.send(6,'/start partner_5')
        self.send(7,'/start partner_6')
        self.send(8,'/start partner_7')
        self.send(9,'/start partner_8')
        reply=self.send(3,'👥 Партнёры')['text']
        for level in range(1,6):
            self.assertIn(f'Уровень {level}: 1',reply)
        self.c.execute('UPDATE bot_accounts SET referrer=8 WHERE uid=3')
        self.c.raw.commit()
        reply=self.send(3,'👥 Партнёры')['text']
        self.assertIn('Уровень 5: 1',reply)


if __name__=='__main__':
    unittest.main()
