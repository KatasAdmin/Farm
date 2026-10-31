import hashlib
import re
import unittest
import test_task_bot as base
import main
from unittest.mock import patch
from fastapi import HTTPException

class BotPromoTests(unittest.TestCase):
    setUp=base.TaskBotTests.setUp
    api=base.TaskBotTests.api
    send=base.TaskBotTests.send
    def test_amounts_single_use_and_audit(self):
        self.c.execute('CREATE TABLE reward_emission(id int,total_minted int)')
        self.c.execute('INSERT INTO reward_emission VALUES(1,0)')
        self.c.execute("INSERT INTO players VALUES('redeemer',44,10)")
        self.c.raw.commit()
        for command,n in [('/bonus1000',1000),('/bonus100',100),('/bonus 75',75),('/bonus50@Farmlife2026bot',50)]:
            result=self.send(1,command)
            code=re.search(r'FARM-[A-Z0-9-]{23}',result['text']).group()
            digest=hashlib.sha256(code.encode()).hexdigest()
            self.assertEqual(self.c.execute('SELECT amount FROM promo_codes WHERE code_hash=%s',(digest,)).fetchone()['amount'],n)
            self.assertEqual(self.c.execute('SELECT created_by FROM farm_promo_issuance WHERE code_hash=%s',(digest,)).fetchone()['created_by'],1)
            with patch.object(main,'db',return_value=self.c),patch.object(main,'person',return_value={'id':'redeemer'}):
                self.assertEqual(main.redeem_promo(main.Request(code=code))['awarded'],n)
                with self.assertRaises(HTTPException):main.redeem_promo(main.Request(code=code))
        self.assertEqual(self.c.execute("SELECT coins FROM players WHERE id='redeemer'").fetchone()['coins'],1235)
    def test_repeated_update_returns_same_code_without_new_issuance(self):
        a=self.send(1,'/bonus1000',event=99901)
        b=self.send(1,'/bonus1000',event=99901)
        self.assertEqual(a,b)
        self.assertEqual(len(self.c.execute('SELECT * FROM promo_codes').fetchall()),1)
    def test_unauthorized_and_invalid_commands_never_issue(self):
        self.assertIn('Доступ',self.send(2,'/bonus1000')['text'])
        for text in ('/bonus','/bonus0','/bonus-5','/bonus1000001','/bonus1.5','/bonus100 extra'):
            self.assertNotIn('FARM-',self.send(1,text)['text'])
        self.assertFalse(self.c.execute('SELECT * FROM promo_codes').fetchall())
