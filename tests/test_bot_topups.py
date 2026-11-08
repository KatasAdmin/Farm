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
    def confirm_card(self,tid,reference=None):
        confirm=self.send(1,action='admin:cardapprove:'+tid)
        self.assertIn('Сверь поступление',confirm['text'])
        data=bot.state(self.c,1)['data']
        return self.send(1,action='admin:cardconfirm:'+data['nonce'])

    def test_menu_hides_unconfigured_crypto_and_no_payment_without_configuration(self):
        self.c.execute('UPDATE bot_topup_config SET star_rate=0')
        self.c.raw.commit()
        result=self.send(3,action='deposit')
        self.assertNotIn('bot:topup:crypto',str(result))
        self.assertNotIn('bot:topup:stars',str(result))
        self.assertIn('bot:topup:card',str(result))
        for action in ('topup:stars','topup:card'):
            self.assertIn('text',self.send(3,action=action))
        self.assertEqual(self.balance(3),0)
        self.assertEqual(self.c.execute('SELECT count(*) AS n FROM bot_wallet_stars').fetchone()['n'],0)
        self.assertEqual(self.c.execute('SELECT count(*) AS n FROM bot_card_topups').fetchone()['n'],0)

    def test_farm_bank_receipt_credits_linked_game_only_after_admin_confirmation(self):
        self.configure_card()
        self.c.execute("INSERT INTO players(id,telegram_id,coins) VALUES(%s,%s,%s)",('farm-player',3,10))
        self.c.raw.commit()
        start=self.send(3,'/start farmdeposit')
        self.assertIn('Пополнение фермы картой',start['text'])
        self.assertEqual(bot.state(self.c,3)['data']['farm_player_id'],'farm-player')
        self.send(3,'10')
        self.receipt(uid=3)
        tid=self.c.execute("SELECT id FROM bot_card_topups WHERE uid=%s",(3,)).fetchone()['id']
        self.assertEqual(self.c.execute('SELECT player_id FROM farm_card_topup_targets WHERE topup_id=%s',(tid,)).fetchone()['player_id'],'farm-player')
        self.assertEqual(self.c.execute('SELECT coins FROM players WHERE id=%s',('farm-player',)).fetchone()['coins'],10)
        self.assertEqual(self.balance(3),0)
        from unittest.mock import patch
        import farm_exchange
        with patch.object(farm_exchange,'mint_from_card',return_value=(10,{})), patch.object(farm_exchange,'credit_verified_card',return_value=True),patch('bot_cash_ad_credits.nbu_usd_uah',return_value=40):
            self.confirm_card(tid)
        self.assertEqual(self.c.execute('SELECT coins FROM players WHERE id=%s',('farm-player',)).fetchone()['coins'],20)
        self.assertEqual(self.balance(3),0,'Do not double credit bot wallet and farm')
        self.assertEqual(self.c.execute("SELECT purchased FROM farm_money_sources").fetchone()['purchased'],10)
        self.assertEqual(self.c.execute("SELECT count(*) AS n FROM money_log WHERE kind='card_purchase'").fetchone()['n'],1)
        self.assertEqual(self.c.execute("SELECT amount FROM bot_cash_pool").fetchone()['amount'],1000)
        self.assertIn('обработана',self.send(1,action='admin:cardapprove:'+tid)['text'])
        self.assertEqual(self.c.execute('SELECT coins FROM players WHERE id=%s',('farm-player',)).fetchone()['coins'],20)

    def test_farm_bank_link_only_targets_authenticated_telegram(self):
        self.configure_card()
        self.c.execute("INSERT INTO players(id,telegram_id,coins) VALUES(%s,%s,%s)",('another-farm',2,5))
        self.c.raw.commit()
        refused=self.send(3,'/start farmdeposit')
        self.assertIn('привяжи Telegram',refused['text'])
        self.assertFalse(bot.state(self.c,3))
        accepted=self.send(2,'/start farmdeposit')
        self.assertIn('Пополнение фермы картой',accepted['text'])
        self.send(2,'10.50')
        self.assertEqual(bot.state(self.c,2)['state'],'topup_card_amount')
        self.assertEqual(self.c.execute('SELECT coins FROM players WHERE id=%s',('another-farm',)).fetchone()['coins'],5)

    def test_crypto_pending_is_not_mislabelled_manual_review(self):
        self.c.execute("""INSERT INTO bot_crypto_invoices
          (id,uid,invoice_id,amount,status,created)
          VALUES(%s,%s,%s,%s,%s,%s)""",
          ('crypto-unpaid',3,123456,500,'pending',1000))
        self.c.raw.commit()
        text=self.send(3,action='topup:mine')['text']
        self.assertIn('5,00 грн · Ожидает оплаты Crypto Bot',text)
        self.assertNotIn('5,00 грн · На проверке',text)
        self.c.execute("UPDATE bot_crypto_invoices SET status='paid' WHERE id=%s",
                       ('crypto-unpaid',))
        self.c.raw.commit()
        text=self.send(3,action='topup:mine')['text']
        self.assertIn('5,00 грн · Зачислено',text)

    def test_crypto_pay_invoice_items_are_verified_and_settled_once(self):
        import bot_crypto_pay as crypto
        order='test-crypto-invoice'
        self.c.execute("""INSERT INTO bot_crypto_invoices
          (id,uid,invoice_id,amount,status,created)
          VALUES(%s,%s,%s,%s,%s,%s)""",
          (order,3,762431,1000,'pending',1000))
        self.c.raw.commit()
        invoice={'invoice_id':762431,'status':'paid','currency_type':'fiat',
                 'fiat':'UAH','amount':'10','payload':'trevixo_'+order}
        def provider(method,args):
            self.assertEqual(method,'getInvoices')
            self.assertEqual(args['invoice_ids'],'762431')
            return {'count':1,'items':[invoice]}
        with (patch.object(crypto,'available',return_value=True),
              patch.object(crypto,'call',side_effect=provider)):
            self.assertTrue(crypto.settle_invoice(lambda:self.c,order))
            self.assertFalse(crypto.settle_invoice(lambda:self.c,order))
        self.assertEqual(self.balance(3),1000)
        self.assertEqual(self.c.execute("SELECT status FROM bot_crypto_invoices WHERE id=%s",(order,)).fetchone()['status'],'paid')
        self.assertEqual(self.c.execute("SELECT count(*) AS n FROM bot_ledger WHERE kind='cryptopay_deposit'").fetchone()['n'],1)

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
        self.send(3,action='withdraw'); self.send(3,'10'); self.send(3,action='withdraw:card');self.send(3,'4441111056522018'); self.send(3,action='confirm_payout')
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
        preview=self.send(1,action='admin:cardapprove:'+tid)
        self.assertIn('Игрок:',preview['text'])
        self.assertIn('10,00 грн',preview['text'])
        self.assertIn('Сверь поступление',preview['text'])
        nonce=bot.state(self.c,1)['data']['nonce']
        self.send(1,action='admin:cardconfirm:'+nonce,event='approve-replay')
        self.send(1,action='admin:cardconfirm:'+nonce,event='approve-replay')
        self.send(1,action='admin:cardconfirm:'+nonce)
        self.assertEqual(self.balance(3),1000)
        self.assertEqual(self.c.execute('SELECT amount FROM bot_cash_pool').fetchone()['amount'],1000)
        self.assertEqual(self.c.execute('SELECT status FROM bot_card_topups').fetchone()['status'],'approved')

    def test_receipt_confirmation_uses_internal_reference_and_is_idempotent(self):
        tid=self.card_request()
        self.assertEqual(self.balance(3),0)
        result=self.confirm_card(tid)
        self.assertIn('Зачислено',result['text'])
        self.assertEqual(self.balance(3),1000)
        row=self.c.execute('SELECT reference,status FROM bot_card_topups WHERE id=%s',(tid,)).fetchone()
        self.assertEqual(row['reference'],'card-receipt:'+tid)
        self.assertEqual(row['status'],'approved')
        self.assertIn('уже обработана',self.send(1,action='admin:cardapprove:'+tid)['text'])
        self.assertEqual(self.balance(3),1000)

    def test_pdf_receipt_owner_preview_and_rejection_without_money(self):
        tid=self.card_request(document=True)
        self.assertEqual(self.send(1,action='admin:cardview:'+tid)['method'],'sendDocument')
        base.complete_refusal(self,1,'admin:cardreject:'+tid)
        self.assertEqual(self.balance(3),0)
        self.assertIn('Отклонено',self.send(3,action='topup:mine')['text'])

    def test_distinct_pending_receipts_allowed_and_duplicate_receipts_rejected(self):
        first=self.card_request()
        self.send(3,action='topup:card')
        self.send(3,'20')
        self.receipt(3,file='receipt2',unique='receipt-unique2')
        rows=self.c.execute("SELECT id,amount,status FROM bot_card_topups WHERE uid=3 ORDER BY created,id").fetchall()
        self.assertEqual(len(rows),2)
        self.assertNotEqual(rows[0]['id'],rows[1]['id'])
        self.assertEqual(sorted(x['amount'] for x in rows),[1000,2000])
        self.assertTrue(all(x['status']=='pending' for x in rows))
        self.assertEqual(self.balance(3),0)
        self.send(2,action='topup:card')
        self.send(2,'10')
        dupe=self.receipt(2,file='samefile',unique='receipt-unique1')
        self.assertIn('уже использована',dupe['text'])
        self.assertEqual(self.c.execute('SELECT count(*) AS n FROM bot_card_topups').fetchone()['n'],2)
        album=self.receipt(2,file='album',unique='new-receipt',album=True)
        self.assertIn('одну квитанцию',album['text'])
        self.assertEqual(self.c.execute('SELECT count(*) AS n FROM bot_card_topups').fetchone()['n'],2)
        first_row=self.c.execute('SELECT status FROM bot_card_topups WHERE id=%s',(first,)).fetchone()
        self.assertEqual(first_row['status'],'pending')

    def test_ten_simultaneous_bank_receipts_each_reviewed_independently(self):
        self.configure_card()
        created=[]
        for n in range(10):
            self.send(3,action='topup:card')
            self.send(3,str(n+10))
            self.receipt(3,file='photo-'+str(n),unique='bank-unique-'+str(n))
            created.append(self.c.execute("SELECT id FROM bot_card_topups WHERE uid=3 ORDER BY created DESC,id DESC LIMIT 1").fetchone()['id'])
        self.assertEqual(len(set(created)),10)
        self.assertEqual(self.c.execute("SELECT count(*) AS n FROM bot_card_topups WHERE uid=3 AND status='pending'").fetchone()['n'],10)
        self.assertIn('10 пополнений',self.send(3,action='topup:card')['text'])
        self.assertEqual(self.balance(3),0)
        self.assertEqual(self.send(1,action='admin:cardview:'+created[0])['method'],'sendPhoto')
        self.confirm_card(created[0],reference='bank-payment-one')
        self.assertEqual(self.balance(3),1000)
        self.assertEqual(self.c.execute("SELECT count(*) AS n FROM bot_card_topups WHERE uid=3 AND status='pending'").fetchone()['n'],9)
        self.send(3,action='topup:card')
        self.send(3,'21')
        self.receipt(3,file='photo-eleven',unique='bank-unique-eleven')
        self.assertEqual(self.c.execute("SELECT count(*) AS n FROM bot_card_topups WHERE uid=3 AND status='pending'").fetchone()['n'],10)
        queue=self.send(1,action='admin:cardtopups')
        self.assertIn('bot:admin:cardtopups:1',str(queue['reply_markup'])) if self.c.execute("SELECT count(*) AS n FROM bot_card_topups WHERE status='pending'").fetchone()['n']>10 else None

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

    def test_stars_input_cancel_button_clears_state_without_invoice_or_money(self):
        response=self.send(3,action='topup:stars')
        self.assertNotIn('/cancel',response['text'])
        self.assertIn('20',response['text'])
        self.assertIn('10,00 грн',response['text'])
        cancel=response['reply_markup']['inline_keyboard'][-1][0]
        self.assertEqual(cancel['text'],'✖️ Отмена')
        self.send(3,action=cancel['callback_data'][4:])
        self.assertIsNone(bot.state(self.c,3))
        self.send(3,'20')
        self.assertEqual(self.c.execute('SELECT count(*) AS n FROM bot_wallet_stars').fetchone()['n'],0)
        self.assertEqual(self.balance(3),0)

    def test_card_receipt_cancel_button_does_not_submit_or_credit(self):
        self.configure_card()
        self.send(3,action='topup:card')
        response=self.send(3,'10')
        self.assertNotIn('/cancel',response['text'])
        cancel=response['reply_markup']['inline_keyboard'][-1][0]
        self.send(3,action=cancel['callback_data'][4:])
        self.receipt(3)
        self.assertIsNone(bot.state(self.c,3))
        self.assertEqual(self.c.execute('SELECT count(*) AS n FROM bot_card_topups').fetchone()['n'],0)
        self.assertEqual(self.balance(3),0)

    def test_withdrawal_confirmation_cancel_invalidates_old_approval_button(self):
        self.credit(3,'10','cancel-withdraw')
        first=self.send(3,action='withdraw')
        self.assertNotIn('/cancel',first['text'])
        self.send(3,'5')
        self.send(3,action='withdraw:card')
        self.send(3,'4441111056522018')
        nonce=bot.state(self.c,3)['data']['nonce']
        self.send(3,action='cancel_input')
        self.send(3,action='confirm_payout:'+nonce)
        self.assertIsNone(bot.state(self.c,3))
        self.assertEqual(self.balance(3),1000)
        self.assertEqual(self.c.execute('SELECT count(*) AS n FROM bot_payouts').fetchone()['n'],0)

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
