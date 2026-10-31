import unittest
from unittest.mock import patch
import main
import task_bot as bot
import test_task_bot as base

class AdditionalAdminTests(unittest.TestCase):
    def setUp(self):
        self.case=base.TaskBotTests();self.case.setUp();self.c=self.case.c
        self.c.execute('INSERT INTO farm_admin_identity VALUES(1,1,0)');self.c.raw.commit()
    def test_second_admin_keeps_owner_and_does_not_grant_others(self):
        with patch.object(main,'db',return_value=self.c):
            self.assertTrue(main.farm_admin_telegram(936533052,936533052))
            self.assertTrue(main.farm_admin_telegram(1,1))
            self.assertFalse(main.farm_admin_telegram(3,3))
            for uid,chat in [('936533052',936533052),(936533052,1),(936533052.0,936533052),(True,True)]:
                self.assertFalse(main.farm_admin_telegram(uid,chat))
        self.assertEqual(self.c.execute('SELECT telegram_id FROM farm_admin_identity').fetchone()['telegram_id'],1)
    def test_second_admin_cannot_claim_primary_owner_identity(self):
        self.c.execute('DELETE FROM farm_admin_identity');self.c.raw.commit()
        with patch.object(main,'db',return_value=self.c):
            self.assertTrue(main.farm_admin_telegram(936533052,936533052))
        self.assertIsNone(self.c.execute('SELECT * FROM farm_admin_identity').fetchone())
    def test_secondary_admin_opens_panel_and_revocation_blocks_cached_privileges(self):
        payload={'callback_query':{'id':'secondary-panel','from':{'id':936533052},'data':'bot:admin','message':{'chat':{'id':936533052,'type':'private'}}}}
        with patch.object(main,'db',return_value=self.c):
            panel=bot.handle(payload,lambda:self.c,self.case.api,main.farm_admin_telegram)
            self.assertIn('Панель',panel['text'])
            with patch.object(main,'FARM_ADDITIONAL_ADMIN_SHA256',frozenset()):
                denied=bot.handle(payload,lambda:self.c,self.case.api,main.farm_admin_telegram)
                self.assertIn('Доступ',denied['text'])
                self.assertNotIn('bot:admin',str(denied))
