"""Payment journal and durable notifications use the real transaction boundaries."""
import json
import time
import unittest
from unittest.mock import patch
import task_bot as bot
import bot_notifications as notices
import main
import test_task_bot as base
import test_bot_topups as topups


class OperationTests(unittest.TestCase):
    api=base.TaskBotTests.api
    send=base.TaskBotTests.send
    credit=base.TaskBotTests.credit
    balance=base.TaskBotTests.balance
    configure_rate=topups.TopupTests.configure_rate
    configure_card=topups.TopupTests.configure_card
    receipt=topups.TopupTests.receipt
    card_request=topups.TopupTests.card_request
    confirm_card=topups.TopupTests.confirm_card
    invoice=topups.TopupTests.invoice
    checkout=topups.TopupTests.checkout
    payment=topups.TopupTests.payment

    def setUp(self):
        base.TaskBotTests.setUp(self)
        self.c.execute('INSERT INTO farm_admin_identity VALUES(1,1,0)')
        self.c.execute('CREATE TABLE star_orders(id text,telegram_id bigint,coins int,stars int,status text,created float)')
        self.c.raw.commit()
        self.delivered=[]

    def notification_api(self,method,payload):
        self.assertEqual(method,'sendMessage')
        self.delivered.append(payload)
        return {'message_id':len(self.delivered),'chat':{'id':payload['chat_id']}}

    def dispatch(self):
        notices.dispatch(lambda:self.c,self.notification_api)

    def payout(self):
        self.credit();self.send(2,action='withdraw');self.send(2,'5');self.send(2,'TEST RECIPIENT BANK')
        self.send(2,action='confirm_payout',event=555)
        return self.c.execute('SELECT id FROM bot_payouts').fetchone()['id']

    def test_empty_history_valid_markup_from_old_and_new_entry(self):
        response=self.send(1,action='admin:payments:all:0')
        self.assertIn('Пока нет операций',response['text'])
        self.assertIsInstance(response['reply_markup'],dict)
        with patch.object(main,'db',return_value=self.c):legacy=main.farm_admin_star_orders(1)
        self.assertIn('История оплат',legacy['text'])
        self.assertIsInstance(legacy['reply_markup'],dict)
        with patch.object(main,'db',return_value=self.c):root=main.farm_admin_panel(1)
        self.assertIn('Панель управления',root['text'])

    def test_journal_covers_wallet_stars_card_bank_and_archived_farm(self):
        tid=self.card_request()
        invoice=self.invoice();self.checkout(invoice);self.payment(invoice)
        self.credit(value='2',ref='other-bank-transfer')
        self.c.execute("INSERT INTO star_orders VALUES(%s,99,7,14,'paid',%s)",('a'*32,time.time()))
        self.c.raw.commit()
        response=self.send(1,action='admin:payments:all:0')
        for label in ('Квитанции','Stars · баланс бота','Ручной учёт','Stars · ферма','7 монет · 14 ⭐'):
            self.assertIn(label,response['text'])
        self.assertIn('bot:admin:cardview:'+tid,str(response['reply_markup']))
        self.assertIn('adm:refund:'+'a'*32,str(response['reply_markup']))
        filtered=self.send(1,action='admin:payments:card:0')
        self.assertNotIn('Stars · ферма',filtered['text'])
        self.assertIn('Квитанция на проверке',filtered['text'])
        self.assertIn('Доступ',self.send(3,action='admin:payments:all:0')['text'])

    def test_approved_receipt_counted_once_and_old_alert_still_opens_status(self):
        tid=self.card_request();self.confirm_card(tid)
        result=self.send(1,action='admin:payments:all:0')
        self.assertEqual(result['text'].count('10,00 грн'),1)
        status=self.send(1,action='admin:cardview:'+tid)
        self.assertIn('Зачислено',status['text'])
        self.assertNotIn('admin:cardapprove:',str(status))
        before=self.balance(3)
        self.send(1,action='admin:cardapprove:'+tid)
        self.assertEqual(self.balance(3),before)

    def test_history_pagination_keeps_all_entries(self):
        for i in range(10):self.credit(value='1',ref='bank-entry-'+str(i))
        first=self.send(1,action='admin:payments:bank:0');second=self.send(1,action='admin:payments:bank:1')
        self.assertEqual(first['text'].count('Учтено вручную'),8)
        self.assertEqual(second['text'].count('Учтено вручную'),2)
        self.assertIn('bot:admin:payments:bank:1',str(first['reply_markup']))
        self.assertNotIn('Далее',str(second['reply_markup']))

    def test_card_intent_and_receipt_notify_owner_without_credit_or_pan(self):
        self.configure_card();self.send(3,action='topup:card');self.send(3,'10')
        self.dispatch()
        self.assertEqual(len(self.delivered),1)
        self.assertIn('Квитанции пока нет',self.delivered[0]['text'])
        self.assertEqual(self.balance(3),0)
        self.receipt();self.dispatch()
        self.assertEqual(len(self.delivered),2)
        self.assertIn('квитанция',self.delivered[1]['text'])
        self.assertIn('admin:cardview:',str(self.delivered[1]))
        self.assertTrue(all(x['chat_id']==1 for x in self.delivered))
        self.assertNotIn('4242',str(self.delivered))
        self.assertEqual(self.balance(3),0)

    def test_stars_created_and_paid_are_separate_and_duplicate_payment_does_not_notify_twice(self):
        invoice=self.invoice();self.dispatch()
        self.assertIn('ещё не оплачен',self.delivered[0]['text'])
        self.assertEqual(self.balance(3),0)
        self.checkout(invoice);self.payment(invoice);self.payment(invoice);self.dispatch()
        self.assertEqual(len(self.delivered),2)
        self.assertIn('оплачено',self.delivered[1]['text'])
        self.assertEqual(self.balance(3),1000)

    def test_withdrawal_notification_once_and_failed_send_cannot_repeat_reserve(self):
        pid=self.payout();before=self.balance(2)
        self.send(2,action='confirm_payout',event=555)
        def fails(method,payload):raise TimeoutError()
        notices.dispatch(lambda:self.c,fails)
        self.assertEqual(self.balance(2),before)
        row=self.c.execute('SELECT * FROM bot_notifications WHERE id=%s',('payout:'+pid,)).fetchone()
        self.assertEqual(row['status'],'pending')
        self.assertEqual(row['attempts'],1)
        self.c.execute('UPDATE bot_notifications SET next_at=0');self.c.raw.commit()
        self.dispatch();self.dispatch()
        self.assertEqual(len(self.delivered),1)
        self.assertIn('admin:payview:'+pid,str(self.delivered[0]))
        self.assertEqual(self.balance(2),500)

    def test_customer_receives_decision_once(self):
        tid=self.card_request();self.confirm_card(tid);self.dispatch()
        user=[n for n in self.delivered if n['chat_id']==3]
        self.assertEqual(len(user),1)
        self.assertIn('зачислено',user[0]['text'])
        self.dispatch();self.assertEqual(len(self.delivered),3)

    def test_no_owner_keeps_admin_queue_and_allows_user_notifications(self):
        self.c.execute('DELETE FROM farm_admin_identity')
        notices.enqueue(self.c,'owner-test','Owner event')
        notices.enqueue(self.c,'user-test','User event',recipient=3)
        self.c.raw.commit();self.dispatch()
        self.assertEqual([r['chat_id'] for r in self.delivered],[3])
        self.assertEqual(self.c.execute("SELECT status FROM bot_notifications WHERE id='owner-test'").fetchone()['status'],'pending')
        self.c.execute('INSERT INTO farm_admin_identity VALUES(1,1,0)');self.c.raw.commit();self.dispatch()
        self.assertEqual([r['chat_id'] for r in self.delivered],[3,1])

    def test_transaction_rollback_removes_notification_and_stale_lease_recovers(self):
        try:
            with self.c as c:
                notices.enqueue(c,'rolled-back','must not send')
                raise ValueError()
        except ValueError:pass
        self.dispatch();self.assertFalse(self.delivered)
        notices.enqueue(self.c,'recovered','Saved event')
        self.c.execute("UPDATE bot_notifications SET status='sending',next_at=0")
        self.c.raw.commit();self.dispatch()
        self.assertEqual(len(self.delivered),1)

    def test_quick_queue_buttons_and_back_navigation(self):
        self.card_request();self.payout()
        root=self.send(1,action='admin')
        for action in ('bot:admin:cardtopups','bot:admin:payouts'):self.assertIn(action,str(root['reply_markup']))
        for action in ('admin:cardtopups','admin:payouts','admin:topupsettings'):
            markup=self.send(1,action=action)['reply_markup']
            self.assertIn('bot:admin:section:finance',str(markup))
            self.assertNotIn('keyboard',markup)
        self.assertIn('bot:admin:section:tasks',str(self.send(1,action='admin:tasks')['reply_markup']))
