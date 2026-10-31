"""Adversarial payer/worker journeys and manual bank payout interlocks."""
import unittest
import time
import task_bot as bot
import bot_decisions as decisions
import test_task_bot as base
import test_bot_extras as extended
import test_bot_economy as economy


class SafetyAuditTests(unittest.TestCase):
    setUp=extended.ExtendedBotTests.setUp
    api=extended.ExtendedBotTests.api
    send=base.TaskBotTests.send
    credit=base.TaskBotTests.credit
    balance=base.TaskBotTests.balance
    ads_balance=base.TaskBotTests.ads_balance
    invariant=base.TaskBotTests.invariant
    task=base.TaskBotTests.task
    create_bot_task=extended.ExtendedBotTests.create_bot_task
    create_post_task=extended.ExtendedBotTests.create_post_task
    forward=extended.ExtendedBotTests.forward
    channel_claim=extended.ExtendedBotTests.channel_claim
    paid_membership=economy.EconomyTests.paid_membership
    leave=economy.EconomyTests.leave
    row=economy.EconomyTests.row

    def payout(self,uid=2,value='5'):
        self.send(uid,action='withdraw');self.send(uid,value);self.send(uid,'TEST BANK RECIPIENT');self.send(uid,action='confirm_payout')
        return self.c.execute("SELECT id FROM bot_payouts WHERE uid=%s AND status='pending'",(uid,)).fetchone()['id']

    def review(self,tid,uid=3):
        self.send(uid,action='take:'+tid);self.send(uid,action='check:'+tid);self.send(uid,'Proof for this manual task')

    def prepare_refusal(self,actor,action,reason='Неверно выполнены условия'):
        self.send(actor,action=action);self.send(actor,reason)
        current=bot.state(self.c,actor)
        return ('admin:rejectdecision:' if current['state'].startswith('admin_') else 'rejectdecision:')+current['data']['nonce']

    def test_payout_in_work_blocks_cancel_and_survives_restart(self):
        self.credit();pid=self.payout()
        self.assertEqual(bot.liability(self.c),1000)
        self.send(1,action='admin:payref:'+pid)
        token=bot.bot_payouts.work(self.c,pid)['token']
        for _ in range(3):self.assertIn('отменить нельзя',self.send(2,action='cancelpayout')['text'])
        self.assertEqual(self.balance(2),500)
        self.assertIn('В работе',self.send(2,action='payouts')['text'])
        bot.initialize(self.c);self.c.raw.commit()
        self.send(1,action='admin:payref:'+pid)
        self.assertEqual(bot.bot_payouts.work(self.c,pid)['token'],token)
        self.assertEqual(bot.liability(self.c),1000)
        self.assertEqual(self.c.execute("SELECT count(*) AS n FROM bot_ledger WHERE kind='payout_processing'").fetchone()['n'],1)

    def test_bank_confirmation_requires_claim_and_valid_token(self):
        self.credit();pid=self.payout()
        self.assertIn('Взять в работу',self.send(1,f'/botpaid {pid} bank-ref')['text'])
        self.send(1,action='admin:payref:'+pid)
        self.send(1,action='admin:payrecord:'+pid);self.send(1,'bank-real-ref')
        self.send(1,action='admin:cancel')
        self.assertIsNotNone(bot.bot_payouts.work(self.c,pid))
        self.assertEqual(self.c.execute('SELECT amount FROM bot_cash_pool').fetchone()['amount'],1000)
        self.send(1,action='admin:payrecord:'+pid);self.send(1,'bank-real-ref')
        data=bot.state(self.c,1)['data'];nonce=data['nonce']
        data['work_token']='expired-token';bot.state(self.c,1,'admin_pay_confirm',data);self.c.raw.commit()
        self.assertIn('устарело',self.send(1,action='admin:payconfirm:'+nonce)['text'])
        self.assertEqual(self.c.execute('SELECT amount FROM bot_cash_pool').fetchone()['amount'],1000)
        self.send(1,action='admin:payrecord:'+pid);self.send(1,'bank-real-ref')
        self.send(1,action='admin:payconfirm')
        self.assertIsNone(bot.bot_payouts.work(self.c,pid))
        self.assertEqual(self.c.execute('SELECT amount FROM bot_cash_pool').fetchone()['amount'],500)

    def test_processing_allocations_cannot_promise_same_cash_twice(self):
        self.credit(2,'5','deposit-two');self.credit(3,'5','deposit-three')
        p2=self.payout(2);p3=self.payout(3)
        self.c.execute('UPDATE bot_cash_pool SET amount=500');self.c.raw.commit()
        self.send(1,action='admin:payref:'+p2)
        self.assertIn('Недостаточно',self.send(1,action='admin:payref:'+p3)['text'])
        self.assertIsNone(bot.bot_payouts.work(self.c,p3))
        self.assertIsNotNone(bot.bot_payouts.work(self.c,p2))

    def test_payout_reason_preview_cancellation_and_exactly_one_refund(self):
        self.credit();pid=self.payout();self.send(1,action='admin:payref:'+pid)
        self.send(1,action='admin:rejectpayout:'+pid)
        self.assertIn('5 до 500',self.send(1,'   ')['text'])
        action=self.prepare_refusal(1,'admin:rejectpayout:'+pid,'Уточни реквизиты получателя')
        self.assertEqual(self.balance(2),500)
        self.send(1,action='cancel_input')
        self.assertIn('устарело',self.send(1,action=action)['text'])
        self.assertEqual(self.balance(2),500)
        action=self.prepare_refusal(1,'admin:rejectpayout:'+pid,'Уточни реквизиты получателя')
        self.send(1,action=action);self.send(1,action=action)
        self.assertEqual(self.balance(2),1000)
        self.assertEqual(self.c.execute('SELECT count(*) AS n FROM bot_decisions').fetchone()['n'],1)
        self.assertIsNone(bot.bot_payouts.work(self.c,pid))
        self.assertIn('Уточни реквизиты',self.c.execute('SELECT reason FROM bot_decisions').fetchone()['reason'])

    def test_new_refund_or_penalty_does_not_release_inflight_bank_payment(self):
        tid=self.paid_membership();pid=self.payout(3,'0.56')
        self.send(1,action='admin:payref:'+pid)
        self.leave(tid)
        self.assertEqual(self.row('bot_payouts')['status'],'pending')
        self.assertIsNotNone(bot.bot_payouts.work(self.c,pid))
        self.assertEqual(self.balance(3),0)
        self.assertEqual(self.row('bot_debts')['amount'],112)
        base.complete_refusal(self,1,'admin:rejectpayout:'+pid)
        self.assertEqual(self.row('bot_debts')['amount'],56)
        self.assertEqual(self.balance(3),0)
        self.assertEqual(self.row('bot_cash_pool')['amount'],1000)

    def test_buying_channel_reserves_once_and_all_receipts_cannot_exceed_one_slot(self):
        tid=self.task(count='1')
        self.assertEqual(self.balance(2),930)
        self.assertEqual(self.row('bot_ad_orders')['slots'],1)
        self.send(4,'/start');self.send(5,'/start')
        self.send(3,action='take:'+tid);self.joined=True;self.send(3,action='check:'+tid)
        for _ in range(10):
            for uid in (2,3,4,5):
                self.send(uid,action='take:'+tid);self.send(uid,action='check:'+tid)
        self.assertEqual(self.balance(3),56)
        self.assertEqual((self.balance(4),self.balance(5)),(0,0))
        self.assertEqual(self.row('bot_tasks')['remaining'],0)
        self.assertEqual(self.c.execute("SELECT count(*) AS n FROM bot_claims WHERE status='paid'").fetchone()['n'],1)
        self.assertEqual(self.c.execute('SELECT count(*) AS n FROM bot_task_settlements').fetchone()['n'],1)
        self.send(2,action='close:'+tid);self.send(2,action='close:'+tid)
        self.assertEqual(self.balance(2),930)
        self.invariant()

    def test_immutable_execution_count_stops_extra_pay_even_if_remaining_is_corrupted(self):
        tid=self.task(count='1');self.send(3,action='take:'+tid);self.joined=True;self.send(3,action='check:'+tid)
        self.send(4,'/start');self.joined=False
        self.c.execute('UPDATE bot_tasks SET remaining=70');self.c.raw.commit()
        self.send(4,action='take:'+tid);self.joined=True
        self.assertIn('использованы',self.send(4,action='check:'+tid)['text'])
        self.assertEqual(self.balance(4),0)
        self.assertEqual(self.row('bot_tasks')['remaining'],70)

    def test_two_reviewers_last_manual_slot_and_rejection_require_reason(self):
        tid=self.task('manual','1');self.send(4,'/start')
        self.send(3,action='take:'+tid);self.send(4,action='take:'+tid)
        self.send(3,action='check:'+tid);self.send(4,action='check:'+tid)
        self.send(3,'First proof');self.send(4,'Second proof')
        self.assertEqual(self.c.execute("SELECT count(*) AS n FROM bot_claims WHERE status='review'").fetchone()['n'],1)
        self.assertEqual(self.row('bot_tasks')['remaining'],100)
        self.assertIn('другого',self.send(4,action='accept:'+tid+':3')['text'])
        self.assertIn('Сначала проверь',self.send(2,action='close:'+tid)['text'])
        action=self.prepare_refusal(2,'rejectwork:'+tid+':3','Нет нужного подтверждения')
        self.assertEqual(self.row('bot_tasks')['remaining'],100)
        self.assertEqual(self.row('bot_claims','uid=3')['status'],'review')
        self.send(2,action=action);self.send(2,action=action)
        self.assertEqual(self.row('bot_claims','uid=3')['status'],'rejected')
        self.review(tid,4)
        for _ in range(5):self.send(2,action='accept:'+tid+':4')
        self.assertEqual(self.balance(4),80)
        self.assertEqual(self.row('bot_tasks')['remaining'],0)
        self.assertEqual(self.balance(2),900)
        self.invariant()

    def test_buyer_progress_and_close_refunds_only_unused_gross(self):
        tid=self.task(count='3')
        self.send(3,action='take:'+tid);self.joined=True;self.send(3,action='check:'+tid)
        response=self.send(2,action='own:'+tid)
        self.assertIn('Заказано выполнений: <b>3</b>',response['text'])
        self.assertIn('Оплачено: 1',response['text'])
        self.assertIn('140',str(self.row('bot_tasks')['remaining']))
        for _ in range(5):self.send(2,action='close:'+tid)
        self.assertEqual(self.balance(2),930)
        self.assertEqual(self.c.execute("SELECT count(*) AS n FROM bot_ledger WHERE kind='task_close'").fetchone()['n'],1)
        self.assertEqual(self.row('bot_tasks')['remaining'],0)
        self.invariant()

    def test_task_moderation_refusal_preview_does_not_refund_until_confirmed(self):
        tid=self.task();self.c.execute("UPDATE bot_tasks SET status='pending'");self.c.raw.commit()
        action=self.prepare_refusal(1,'admin:rejecttask:'+tid,'Ссылка не соответствует заданию')
        self.assertEqual(self.balance(2),860)
        self.assertEqual(self.row('bot_tasks')['status'],'pending')
        self.send(1,action=action);self.send(1,action=action)
        self.assertEqual(self.balance(2),1000)
        self.assertEqual(self.row('bot_tasks')['remaining'],0)
        self.assertEqual(self.row('bot_decisions')['kind'],'task')

    def test_post_advertiser_pays_per_unique_claim_not_per_repeated_click(self):
        tid=self.create_post_task();self.send(4,'/start');self.send(5,'/start')
        for _ in range(5):self.channel_claim(3,tid)
        self.channel_claim(4,tid)
        for _ in range(5):self.channel_claim(5,tid)
        self.assertEqual((self.balance(3),self.balance(4),self.balance(5)),(3,3,0))
        self.assertEqual(self.row('bot_tasks')['remaining'],0)
        self.assertEqual(self.balance(2),992)
        self.assertEqual(self.c.execute('SELECT count(*) AS n FROM bot_task_settlements').fetchone()['n'],2)
        self.invariant()

    def test_bot_forward_retries_cannot_spend_more_than_bought_executions(self):
        tid=self.create_bot_task();self.send(4,'/start');self.send(5,'/start')
        for uid in (3,4):
            self.send(uid,action='take:'+tid)
            for _ in range(5):self.forward(uid)
        self.send(5,action='take:'+tid);self.forward(5)
        self.assertEqual((self.balance(3),self.balance(4),self.balance(5)),(32,32,0))
        self.assertEqual(self.row('bot_tasks')['remaining'],0)
        self.assertEqual(self.balance(2),920)
        self.assertEqual(self.c.execute('SELECT count(*) AS n FROM bot_bot_completions').fetchone()['n'],2)
        self.invariant()

    def test_legacy_limit_backfill_uses_original_funded_budget_after_restart(self):
        tid=self.task(count='3')
        self.send(3,action='take:'+tid);self.joined=True;self.send(3,action='check:'+tid)
        self.c.execute('DELETE FROM bot_ad_orders');self.c.raw.commit()
        bot.initialize(self.c);self.c.raw.commit()
        self.assertEqual(self.row('bot_ad_orders')['slots'],3)
        self.assertEqual(self.row('bot_ad_orders')['budget'],210)
        self.assertEqual(self.row('bot_tasks')['remaining'],140)

    def test_same_bank_payment_reference_never_pays_second_request(self):
        self.credit(2,'10','fund-worker-two');self.credit(3,'10','fund-worker-three')
        p2=self.payout(2);p3=self.payout(3)
        for pid in (p2,p3):
            self.send(1,action='admin:payref:'+pid)
            self.send(1,action='admin:payrecord:'+pid);self.send(1,'one-real-bank-reference')
            self.send(1,action='admin:payconfirm')
        self.assertEqual(self.c.execute("SELECT count(*) AS n FROM bot_payouts WHERE status='paid'").fetchone()['n'],1)
        self.assertEqual(self.row('bot_cash_pool')['amount'],1500)
        self.assertEqual(self.row('bot_payouts','id=%s',(p3,))['status'],'pending')
        self.assertIsNotNone(bot.bot_payouts.work(self.c,p3))

    def test_new_bad_callback_cannot_refuse_another_advertisers_work(self):
        tid=self.task('manual','1');self.review(tid)
        self.send(3,action='rejectwork:'+tid+':3')
        self.send(3,'Any invented rejection reason')
        self.assertEqual(self.row('bot_claims')['status'],'review')
        self.assertEqual(self.c.execute('SELECT count(*) AS n FROM bot_decisions').fetchone()['n'],0)
        self.assertEqual(self.balance(3),0)
        self.send(2,action='accept:'+tid+':3')
        self.assertEqual(self.balance(3),80)

    def test_stale_review_confirmation_cannot_undo_accepted_work(self):
        tid=self.task('manual','1');self.review(tid)
        action=self.prepare_refusal(2,'rejectwork:'+tid+':3','Не хватает подтверждения')
        self.send(2,action='accept:'+tid+':3')
        self.send(2,action=action)
        self.assertEqual(self.row('bot_claims')['status'],'paid')
        self.assertEqual(self.balance(3),80)
        self.assertEqual(self.row('bot_tasks')['remaining'],0)
        self.assertEqual(self.c.execute('SELECT count(*) AS n FROM bot_decisions').fetchone()['n'],0)
