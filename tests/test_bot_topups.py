"""Idempotent wallet invoices, manual receipt verification and private admin access."""
import unittest
from unittest.mock import patch
import task_bot as bot
import bot_topups as top
import test_task_bot as base


class TopupTests(unittest.TestCase):
    setUp=base.TaskBotTests.setUp
    api=base.TaskBotTests.api
    send=base.TaskBotTests.send
    balance=base.TaskBotTests.balance
    credit=base.TaskBotTests.credit

    def configure_rate(self,rate='0.50'):
        self.send(1,action='admin:topupedit:rate')
        self.send(1,rate)
    def configure_card(self):
        self.send(1,action='admin:topupedit:card')
        self.send(1,'4242 4242 4242 4242\nTest recipient')
    def invoice(self,n='20'):
        self.configure_rate()
        self.send(3,action='topup:stars')
        invoice=self.send(3,n)
        self.assertEqual(invoice['method'],'sendInvoice')
        return invoice
    def checkout(self,invoice,uid=3,amount=None,event='checkout1',currency='XTR'):
        return bot.handle({'pre_checkout_query':{'id':event,'from':{'id':uid},'currency':currency,
                          'invoice_payload':invoice['payload'],'total_amount':amount if amount is not None else invoice['prices'][0]['amount']}},
                          lambda:self.c,self.api,lambda u,c:u==1)
    def payment(self,invoice,uid=3,amount=None,charge='charge1',refund=False,currency='XTR'):
        key='refunded_payment' if refund else 'successful_payment'
        return bot.handle({'message':{'chat':{'id':uid,'type':'private'},'from':{'id':uid},key:{
                          'currency':currency,'invoice_payload':invoice['payload'],'total_amount':amount if amount is not None else invoice['prices'][0]['amount'],
                          'telegram_payment_charge_id':charge}}},lambda:self.c,self.api,lambda u,c:u==1)
    def receipt(self,uid=3,file='receipt1',unique='receipt-unique1',document=False,album=False):
        self.serial+=1
        media={'file_id':file,'file_unique_id':unique,'file_size':5000}
        message={'message_id':self.serial,'from':{'id':uid},'chat':{'id':uid,'type':'private'}}
        if document:
            message['document']={**media,'mime_type':'application/pdf'}
        else:
            message['photo']=[media]
        if album:
            message['media_group_id']='album'
        return bot.handle({'message':message},lambda:self.c,self.api,lambda u,c:u==1)
    def card_request(self,uid=3,document=False):
        self.configure_card()
        self.send(uid,action='topup:card')
        self.send(uid,'10')
        self.receipt(uid,document=document)
        return self.c.execute('SELECT id FROM bot_card_topups WHERE uid=%s',(uid,)).fetchone()['id']
    def confirm_card(self,tid,reference='bank-real-transaction'):
        self.send(1,action='admin:cardapprove:'+tid)
        self.send(1,reference)
        data=bot.state(self.c,1)['data']
        return self.send(1,action='admin:cardconfirm:'+data['nonce'])

    def test_menu_has_three_methods_and_no_payment_without_configuration(self):
        self.c.execute('UPDATE bot_topup_config SET star_rate=0')
        self.c.raw.commit()
        result=self.send(3,action='deposit')
        for action in ('topup:stars','topup:crypto','topup:card'):
            self.assertIn('bot:'+action,str(result))
            self.assertIn('text',self.send(3,action=action))
        self.assertEqual(self.balance(3),0)
        self.assertEqual(self.c.execute('SELECT count(*) AS n FROM bot_wallet_stars').fetchone()['n'],0)
        self.assertEqual(self.c.execute('SELECT count(*) AS n FROM bot_card_topups').fetchone()['n'],0)

    def test_invoice_never_credits_before_verified_payment_and_deduplicates(self):
        invoice=self.invoice()
        self.assertEqual(self.balance(3),0)
        self.assertTrue(self.checkout(invoice)['ok'])
        self.assertTrue(self.checkout(invoice)['ok'])
        self.assertFalse(self.checkout(invoice,event='different-query')['ok'])
        self.payment(invoice)
        self.payment(invoice)
        self.assertEqual(self.balance(3),1000)
        self.assertEqual(self.c.execute("SELECT count(*) AS n FROM bot_ledger WHERE kind='stars_wallet_deposit'").fetchone()['n'],1)
        self.assertEqual(self.c.execute('SELECT amount FROM bot_cash_pool').fetchone()['amount'],0)

    def test_wrong_user_amount_currency_and_unapproved_payment_rejected(self):
        invoice=self.invoice()
        self.assertFalse(self.checkout(invoice,uid=2)['ok'])
        self.assertFalse(self.checkout(invoice,amount=19)['ok'])
        self.assertFalse(self.checkout(invoice,currency='USD')['ok'])
        self.payment(invoice)  # no accepted precheckout
        self.assertEqual(self.balance(3),0)
        self.checkout(invoice)
        self.payment(invoice,uid=2)
        self.payment(invoice,amount=19)
        self.payment(invoice,currency='USD')
        self.assertEqual(self.balance(3),0)
        self.payment(invoice)
        self.assertEqual(self.balance(3),1000)

    def test_rate_snapshot_survives_admin_change_and_delayed_success(self):
        invoice=self.invoice()
        self.checkout(invoice)
        self.configure_rate('2')
        with patch('bot_topups.time.time',return_value=10**10):
            self.payment(invoice)
        self.assertEqual(self.balance(3),1000)
        self.assertEqual(self.c.execute('SELECT amount FROM bot_wallet_stars').fetchone()['amount'],1000)

    def test_expired_checkout_and_malformed_star_counts_rejected(self):
        self.configure_rate()
        self.send(3,action='topup:stars')
        for n in ('0','-1','0.5','10001','nan'):
            self.assertIn('text',self.send(3,n))
            self.assertEqual(bot.state(self.c,3)['state'],'topup_stars')
        invoice=self.send(3,'20')
        self.c.execute('UPDATE bot_wallet_stars SET created=0')
        self.c.raw.commit()
        self.assertFalse(self.checkout(invoice)['ok'])

    def test_charge_identifier_cannot_credit_two_orders(self):
        first=self.invoice(); self.checkout(first); self.payment(first)
        second=self.invoice(); self.checkout(second,event='checkout2'); self.payment(second)
        self.assertEqual(self.balance(3),1000)
        self.payment(second,charge='charge2')
        self.assertEqual(self.balance(3),2000)

    def test_stars_refund_reverses_once_and_cancels_pending_withdrawal(self):
        invoice=self.invoice(); self.checkout(invoice); self.payment(invoice)
        self.send(3,action='withdraw'); self.send(3,'10'); self.send(3,'UA123456789 recipient'); self.send(3,action='confirm_payout')
        self.payment(invoice,refund=True)
        self.payment(invoice,refund=True)
        self.assertEqual(self.balance(3),0)
        self.assertEqual(self.c.execute('SELECT amount FROM bot_debts WHERE uid=3').fetchone()['amount'],0)
        self.assertEqual(self.c.execute('SELECT status FROM bot_payouts').fetchone()['status'],'cancelled')
        self.assertEqual(self.c.execute('SELECT status FROM bot_wallet_stars').fetchone()['status'],'refunded')

    def test_refund_of_spent_credit_becomes_debt_and_does_not_create_cash(self):
        invoice=self.invoice(); self.checkout(invoice); self.payment(invoice)
        with self.c:
            bot.change(self.c,3,-700,'task_budget','spent elsewhere')
        self.payment(invoice,refund=True)
        self.assertEqual(self.balance(3),0)
        self.assertEqual(self.c.execute('SELECT amount FROM bot_debts WHERE uid=3').fetchone()['amount'],700)
        self.assertEqual(self.c.execute('SELECT amount FROM bot_cash_pool').fetchone()['amount'],0)

    def test_out_of_order_refund_prevents_later_credit(self):
        invoice=self.invoice(); self.checkout(invoice)
        self.payment(invoice,refund=True)
        self.payment(invoice)
        self.assertEqual(self.balance(3),0)
        self.assertEqual(self.c.execute('SELECT status FROM bot_wallet_stars').fetchone()['status'],'refunded')
        self.assertEqual(self.c.execute("SELECT count(*) AS n FROM bot_ledger WHERE kind='stars_wallet_deposit'").fetchone()['n'],0)

    def test_farm_payment_payloads_still_use_legacy_handler(self):
        payload={'pre_checkout_query':{'id':'farm','from':{'id':3},'invoice_payload':'a'*32,'currency':'XTR','total_amount':20}}
        self.assertIsNone(bot.handle(payload,lambda:self.c,self.api,lambda *_:False))

    def test_card_receipt_waits_for_real_bank_reference_and_only_owner_can_credit(self):
        tid=self.card_request()
        self.assertEqual(self.balance(3),0)
        self.assertEqual(self.c.execute('SELECT amount FROM bot_cash_pool').fetchone()['amount'],0)
        self.send(3,action='admin:cardview:'+tid)
        self.send(3,action='admin:cardapprove:'+tid)
        self.assertEqual(self.balance(3),0)
        view=self.send(1,action='admin:cardview:'+tid)
        self.assertEqual(view['method'],'sendPhoto')
        self.send(1,action='admin:cardapprove:'+tid)
        self.assertEqual(self.balance(3),0)
        preview=self.send(1,'bank-confirmed')
        self.assertIn('Пользователь: 3',preview['text'])
        self.assertIn('Сумма: 10,00 грн',preview['text'])
        nonce=bot.state(self.c,1)['data']['nonce']
        self.send(1,action='admin:cardconfirm:'+nonce,event='approve-replay')
        self.send(1,action='admin:cardconfirm:'+nonce,event='approve-replay')
        self.send(1,action='admin:cardconfirm:'+nonce)
        self.assertEqual(self.balance(3),1000)
        self.assertEqual(self.c.execute('SELECT amount FROM bot_cash_pool').fetchone()['amount'],1000)
        self.assertEqual(self.c.execute('SELECT status FROM bot_card_topups').fetchone()['status'],'approved')

    def test_existing_bank_reference_prevents_double_credit_via_old_manual_command(self):
        tid=self.card_request()
        self.credit(3,'10','same-bank-operation')
        result=self.confirm_card(tid,'same-bank-operation')
        self.assertIn('уже учтена',result['text'])
        self.assertEqual(self.balance(3),1000)
        self.assertEqual(self.c.execute('SELECT status FROM bot_card_topups').fetchone()['status'],'pending')

    def test_pdf_receipt_owner_preview_and_rejection_without_money(self):
        tid=self.card_request(document=True)
        self.assertEqual(self.send(1,action='admin:cardview:'+tid)['method'],'sendDocument')
        self.send(1,action='admin:cardreject:'+tid)
        self.assertEqual(self.balance(3),0)
        self.assertIn('Отклонено',self.send(3,action='topup:mine')['text'])

    def test_duplicate_receipt_and_album_cannot_create_duplicate_requests(self):
        tid=self.card_request()
        self.send(2,action='topup:card'); self.send(2,'10'); self.receipt(2)
        self.assertEqual(self.c.execute('SELECT count(*) AS n FROM bot_card_topups').fetchone()['n'],1)
        self.receipt(2,unique='new-receipt',album=True)
        self.assertEqual(self.c.execute('SELECT count(*) AS n FROM bot_card_topups').fetchone()['n'],1)
        self.assertIn('уже на проверке',self.send(3,action='topup:card')['text'])

    def test_card_and_rate_configuration_owner_only_and_invalid_card_rejected(self):
        self.send(3,action='admin:topupedit:rate'); self.send(3,'100')
        self.assertEqual(top.config(self.c)['star_rate'],50)
        self.send(1,action='admin:topupedit:card'); self.send(1,'1234567890123456\nNot valid')
        self.assertEqual(top.config(self.c)['card'],'')
        self.configure_card()
        self.assertEqual(top.config(self.c)['card'],'4242424242424242')
        bot.state(self.c,3,'topup_config',{'field':'rate'}); self.c.raw.commit()
        self.send(3,'100')
        self.assertEqual(top.config(self.c)['star_rate'],50)

    def test_default_rate_two_stars_per_hryvnia_and_later_admin_edits_preserved(self):
        self.assertEqual(top.config(self.c)['star_rate'],50)
        reply=self.send(3,action='topup:stars')
        self.assertIn('2 Stars = 1,00 грн',reply['text'])
        invoice=self.send(3,'20')
        self.assertIn('10,00 грн',invoice['description'])
        self.assertEqual(self.balance(3),0)
        self.configure_rate('0.75')
        bot.initialize(self.c)
        self.c.raw.commit()
        self.assertEqual(top.config(self.c)['star_rate'],75)

    def test_card_snapshot_and_user_list_are_private(self):
        tid=self.card_request()
        self.send(1,action='admin:topupedit:card'); self.send(1,'-')
        row=self.c.execute('SELECT card,recipient FROM bot_card_topups').fetchone()
        self.assertEqual(row['card'],'4242424242424242')
        self.assertNotIn(tid,self.send(2,action='topup:mine')['text'])
        self.assertIn(tid[:8],self.send(3,action='topup:mine')['text'])
        self.assertIn('ещё не указаны',self.send(2,action='topup:card')['text'])


if __name__=='__main__':
    unittest.main()
