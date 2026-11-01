import unittest
import task_bot as bot
import bot_account_controls as controls
import test_task_bot as base
import test_farm_wallet as farm_tests
import farm_wallet as wallet
from fastapi import HTTPException


class AccountControlTests(unittest.TestCase):
    setUp=base.TaskBotTests.setUp
    api=base.TaskBotTests.api
    send=base.TaskBotTests.send
    credit=base.TaskBotTests.credit
    balance=base.TaskBotTests.balance

    def control(self,op,reason='Проверка происхождения средств'):
        self.send(1,action='admin:accountcontrol:'+op+':2')
        self.send(1,reason)
        data=bot.state(self.c,1)['data']
        action='admin:accountcontrolconfirm:'+data['nonce']
        self.send(1,action=action)
        return action

    def prepare_payout(self):
        self.send(2,action='withdraw');self.send(2,'5');self.send(2,'4441111056522018')

    def test_block_rechecks_open_form_and_does_not_debit_or_cancel_funds(self):
        self.credit();self.prepare_payout()
        self.control('block')
        self.assertIn('заблокирован',self.send(2,action='confirm_payout')['text'])
        self.assertIn('Проверка происхождения',self.send(2,action='withdraw')['text'])
        self.assertEqual(self.balance(2),1000)
        self.assertEqual(self.c.execute('SELECT count(*) AS n FROM bot_payouts').fetchone()['n'],0)
        self.control('unblock','Проверка успешно завершена')
        self.prepare_payout();self.send(2,action='confirm_payout')
        self.assertEqual(self.balance(2),500)

    def test_existing_transfer_can_be_confirmed_and_cannot_be_replayed(self):
        self.credit();self.prepare_payout();self.send(2,action='confirm_payout')
        pid=self.c.execute('SELECT id FROM bot_payouts').fetchone()['id']
        self.send(1,action='admin:payref:'+pid)
        self.control('block')
        self.assertIn('Вывод заблокирован',self.send(1,action='admin:payview:'+pid)['text'])
        self.send(1,action='admin:payrecord:'+pid);self.send(1,'paid-before-hold')
        self.send(1,action='admin:payconfirm');self.send(1,action='admin:payconfirm')
        self.assertEqual(self.c.execute('SELECT status FROM bot_payouts').fetchone()['status'],'paid')
        self.assertEqual(self.balance(2),500)
        self.assertEqual(self.c.execute("SELECT count(*) AS n FROM bot_ledger WHERE kind='payout_paid'").fetchone()['n'],1)

    def test_private_flag_is_independent_of_block_and_is_audited_once(self):
        self.credit();action=self.control('flag','Приватная заметка MULTI-TEST')
        self.send(1,action=action)
        row=controls.get(self.c,2)
        self.assertEqual((row['suspicious'],row['withdraw_blocked']),(1,0))
        self.assertEqual(self.c.execute('SELECT count(*) AS n FROM bot_account_control_audit').fetchone()['n'],1)
        self.assertNotIn('MULTI-TEST',str(self.c.execute('SELECT * FROM bot_ledger').fetchall()))
        self.assertIn('MULTI-TEST',self.send(1,action='admin:accountaudit:2')['text'])
        self.assertIn('bot:admin:account:2',str(self.send(1,action='admin:accountreviews:0')))
        self.prepare_payout();self.send(2,action='confirm_payout')
        self.assertEqual(self.balance(2),500)
        self.control('block');self.control('unflag','Проверка отметки завершена')
        self.assertTrue(controls.get(self.c,2)['withdraw_blocked'])

    def test_reasons_cancel_and_foreign_owner_protection(self):
        self.send(1,action='admin:accountcontrol:block:2')
        self.assertIn('Причина',self.send(1,'a')['text'])
        self.send(1,'Проверка пользователя');data=bot.state(self.c,1)['data']
        action='admin:accountcontrolconfirm:'+data['nonce']
        self.send(1,action='admin:account:2')
        self.assertIn('устарело',self.send(1,action=action)['text'])
        for a in ('admin:accountcontrol:block:2',action,'admin:accountaudit:2','admin:accountreviews:0'):
            self.assertIn('Доступ',self.send(3,action=a)['text'])
        self.assertFalse(controls.get(self.c,2)['withdraw_blocked'])


class BlockedFarmTransfers(unittest.TestCase):
    def test_block_stops_new_transfer_but_preserves_successful_retry(self):
        f=farm_tests.FarmWalletTests();f.setUp();c=f.c
        f.add('market_sale',300);c.raw.commit()
        with c:wallet.transfer(c,f.player(),100,f.key,bot)
        with c:controls.set_control(c,55,1,'block','Проверка аккаунта игрока')
        with c:self.assertTrue(wallet.transfer(c,f.player(),100,f.key,bot)['repeated'])
        with self.assertRaises(HTTPException) as error:
            with c:wallet.transfer(c,f.player(),100,'new-transfer-key',bot)
        self.assertEqual(error.exception.status_code,403)
        self.assertEqual(f.player()['coins'],210)
        self.assertEqual(c.execute('SELECT available FROM bot_accounts WHERE uid=55').fetchone()['available'],10000)
