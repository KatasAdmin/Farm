"""Direct web bank receipts are never credited before owner confirmation."""
import base64
import unittest
from unittest.mock import patch

import farm_card_web
import test_bot_topups as topup_tests
import task_bot as bot


class FarmCardWebTests(unittest.TestCase):
    setUp=topup_tests.TopupTests.setUp
    send=topup_tests.TopupTests.send
    api=topup_tests.TopupTests.api
    configure_card=topup_tests.TopupTests.configure_card
    confirm_card=topup_tests.TopupTests.confirm_card
    balance=topup_tests.TopupTests.balance

    def test_direct_card_receipt_one_credit_after_owner_approval(self):
        self.configure_card()
        self.c.execute('INSERT INTO players(id,telegram_id,coins) VALUES(%s,%s,%s)',('farmer-3',3,10))
        self.c.raw.commit()
        player={'id':'farmer-3','telegram_id':3}
        data=b'\x89PNG\r\n\x1a\n'+b'x'*200
        encoded=base64.b64encode(data).decode()
        with patch.object(farm_card_web,'_telegram_document',return_value={'file_id':'file-1','file_unique_id':'file-unique-1'}):
            result=farm_card_web.submit(self.c,player,10,encoded,'image/png')
        self.assertEqual(result['status'],'pending')
        self.assertEqual(self.c.execute('SELECT coins FROM players WHERE id=%s',('farmer-3',)).fetchone()['coins'],10)
        target=self.c.execute('SELECT player_id FROM farm_card_topup_targets WHERE topup_id=%s',(result['id'],)).fetchone()
        self.assertEqual(target['player_id'],'farmer-3')
        with patch.object(farm_card_web,'_telegram_document',side_effect=AssertionError('Duplicate upload')):
            with self.assertRaisesRegex(ValueError,'уже отправлена'):
                farm_card_web.submit(self.c,player,10,encoded,'image/png')
        self.c.raw.commit()
        self.confirm_card(result['id'])
        self.assertEqual(self.c.execute('SELECT coins FROM players WHERE id=%s',('farmer-3',)).fetchone()['coins'],20)
        self.assertEqual(self.balance(3),0)
        self.assertEqual(self.c.execute('SELECT COUNT(*) AS n FROM farm_money_sources WHERE purchased=10').fetchone()['n'],1)

    def test_reject_unlinked_and_fake_file(self):
        self.configure_card()
        self.assertFalse(farm_card_web.settings(self.c,{'id':'no-tg'})['enabled'])
        with self.assertRaisesRegex(ValueError,'Привяжи Telegram'):
            farm_card_web.submit(self.c,{'id':'no-tg'},10,'abc','image/png')
        with self.assertRaisesRegex(ValueError,'Повреждённый'):
            farm_card_web.submit(self.c,{'id':'farmer','telegram_id':3},10,
                base64.b64encode(b'a'*200).decode(),'image/png')
        with self.assertRaisesRegex(ValueError,'целую сумму'):
            farm_card_web.submit(self.c,{'id':'farmer','telegram_id':3},10.5,
                base64.b64encode(b'a'*200).decode(),'image/png')


if __name__=='__main__':
    unittest.main()
