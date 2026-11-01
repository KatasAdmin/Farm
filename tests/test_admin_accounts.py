import unittest
import task_bot as bot
import test_task_bot as base


class AdminAccountsTests(unittest.TestCase):
    setUp=base.TaskBotTests.setUp
    api=base.TaskBotTests.api
    send=base.TaskBotTests.send
    credit=base.TaskBotTests.credit
    balance=base.TaskBotTests.balance

    def adjustment(self,op='credit',amount='2.25',reason='Исправление тестового начисления'):
        self.send(1,action='admin:accountop:'+op+':2')
        self.send(1,amount)
        self.send(1,reason)
        st=bot.state(self.c,1)
        self.assertEqual(st['state'],'admin_account_confirm')
        return 'admin:accountconfirm:'+st['data']['nonce']

    def test_owner_card_search_and_farm_identity(self):
        self.c.execute('ALTER TABLE players ADD COLUMN name text')
        self.c.execute("INSERT INTO players VALUES('farm-test',2,123,'<Katas>')")
        self.c.raw.commit()
        card=self.send(1,action='admin:account:2')
        self.assertIn('Telegram ID: <code>2</code>',card['text'])
        self.assertIn('farm-test',card['text'])
        self.assertIn('&lt;Katas&gt;',card['text'])
        self.assertIn('123',card['text'])
        self.send(1,action='admin:accountsearch')
        result=self.send(1,'2')
        self.assertIn('bot:admin:account:2',str(result))
        self.assertNotIn('bot:admin:account:3',str(result))
        self.send(1,action='admin:accountsearch')
        self.assertIn('не найдены',self.send(1,'%')['text'])
        self.assertIn('Неизвестная страница',self.send(1,action='admin:accounts:bad')['text'])

    def test_credit_is_reasoned_exactly_once_and_does_not_invent_bank_deposit(self):
        action=self.adjustment()
        self.assertEqual(self.balance(2),0)
        self.send(1,action=action);self.send(1,action=action)
        self.assertEqual(self.balance(2),225)
        rows=self.c.execute("SELECT * FROM bot_ledger WHERE kind='admin_adjustment'").fetchall()
        self.assertEqual(len(rows),1)
        self.assertIn('Админ 1',rows[0]['details'])
        self.assertIn('Исправление',rows[0]['details'])
        self.assertEqual(self.c.execute('SELECT count(*) AS n FROM bot_deposits').fetchone()['n'],0)
        self.assertEqual(self.c.execute('SELECT amount FROM bot_cash_pool').fetchone()['amount'],0)

    def test_debit_rechecks_balance_and_preserves_reserved_payout(self):
        self.credit()
        self.send(2,action='withdraw');self.send(2,'5');self.send(2,'4441111056522018');self.send(2,action='confirm_payout')
        self.assertEqual(self.balance(2),500)
        action=self.adjustment('debit','4.99')
        self.send(1,action=action)
        self.assertEqual(self.balance(2),1)
        self.assertEqual(self.c.execute("SELECT amount FROM bot_payouts WHERE status='pending'").fetchone()['amount'],500)
        self.assertIn('−4,99',self.send(1,action='admin:accountledger:2:0')['text'])
        self.send(1,action='admin:accountop:debit:2')
        self.assertIn('больше доступного',self.send(1,'0.02')['text'])
        self.assertEqual(self.balance(2),1)

    def test_stale_balance_and_cancellation_do_not_apply(self):
        self.credit()
        action=self.adjustment('debit','8')
        self.c.execute('UPDATE bot_accounts SET available=100 WHERE uid=2');self.c.raw.commit()
        self.assertIn('Недостаточно',self.send(1,action=action)['text'])
        self.assertEqual(self.balance(2),100)
        action=self.adjustment('credit','2')
        self.send(1,action='admin:account:2')
        self.assertIn('устарело',self.send(1,action=action)['text'])
        self.assertEqual(self.balance(2),100)

    def test_non_owner_cannot_inspect_or_adjust_even_forged_state(self):
        for action in ('admin:accounts:0','admin:account:2','admin:accountledger:2:0','admin:accountop:credit:2','admin:accountconfirm:fake'):
            self.assertIn('Доступ',self.send(3,action=action)['text'])
        bot.state(self.c,3,'admin_account_confirm',{'target':2,'op':'credit','amount':100,'reason':'fake reason','nonce':'fake'});self.c.raw.commit()
        self.assertIn('Доступ',self.send(3,'fake input')['text'])
        self.assertEqual(self.balance(2),0)

    def test_payout_identifies_and_links_to_recipient(self):
        self.credit()
        self.send(2,action='withdraw');self.send(2,'5');self.send(2,'4441111056522018');self.send(2,action='confirm_payout')
        pid=self.c.execute('SELECT id FROM bot_payouts').fetchone()['id']
        card=self.send(1,action='admin:payview:'+pid)
        self.assertIn('Telegram ID: <code>2</code>',card['text'])
        self.assertIn('Test',card['text'])
        self.assertIn('bot:admin:account:2',str(card))
        self.assertIn(pid[:6],str(self.send(1,action='admin:account:2')))
