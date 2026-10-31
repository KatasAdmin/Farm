import unittest
import referral_bridge as bridge
from test_task_bot import Database

class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.c=Database()
        self.c.execute('CREATE TABLE players(id text PRIMARY KEY,telegram_id bigint UNIQUE)')
        self.c.execute('CREATE TABLE bot_accounts(uid bigint PRIMARY KEY,referrer bigint,name text,created double precision)')
        bridge.initialize(self.c)
    def player(self,uid):
        self.c.execute('INSERT INTO players VALUES(%s,%s)',(str(uid),uid))
    def bot(self,uid,parent=None):
        self.c.execute('INSERT INTO bot_accounts VALUES(%s,%s,%s,0)',(uid,parent,'User'))
    def test_bot_first_and_inviter_opens_game_later(self):
        self.bot(1);self.bot(2,1);self.player(2)
        bridge.sync(self.c,2)
        self.assertIsNone(self.c.execute('SELECT * FROM referrals').fetchone())
        self.player(1);bridge.sync(self.c,1);bridge.sync(self.c,2)
        self.assertEqual(self.c.execute('SELECT parent_id FROM referrals WHERE child_id=%s',('2',)).fetchone()['parent_id'],'1')
        self.assertEqual(len(self.c.execute('SELECT * FROM referrals').fetchall()),1)
    def test_game_first_and_parent_has_not_opened_bot(self):
        self.player(1);self.player(2);self.bot(2)
        self.c.execute('INSERT INTO referrals VALUES(%s,%s,0,false)',('2','1'))
        bridge.sync(self.c,2)
        self.assertEqual(self.c.execute('SELECT referrer FROM bot_accounts WHERE uid=2').fetchone()['referrer'],1)
        self.assertIsNotNone(self.c.execute('SELECT uid FROM bot_accounts WHERE uid=1').fetchone())
    def test_conflicting_existing_parents_not_overwritten(self):
        for uid in (1,2,3):self.player(uid);self.bot(uid,1 if uid==2 else None)
        self.c.execute('INSERT INTO referrals VALUES(%s,%s,0,false)',('2','3'))
        bridge.sync(self.c,2)
        self.assertEqual(self.c.execute('SELECT referrer FROM bot_accounts WHERE uid=2').fetchone()['referrer'],1)
        self.assertEqual(self.c.execute('SELECT parent_id FROM referrals WHERE child_id=%s',('2',)).fetchone()['parent_id'],'3')
    def test_mixed_cycle_and_self_are_rejected(self):
        for uid in (1,2,3):self.player(uid);self.bot(uid,2 if uid==1 else None)
        self.c.execute('INSERT INTO referrals VALUES(%s,%s,0,false)',('2','3'))
        self.assertFalse(bridge.acyclic(self.c,3,1))
        self.assertFalse(bridge.acyclic(self.c,1,1))
        self.assertTrue(bridge.acyclic(self.c,3,4))

class BotEntryTests(unittest.TestCase):
    def test_existing_game_inviter_wins_over_new_bot_link(self):
        import test_task_bot as base
        case=base.TaskBotTests();case.setUp()
        case.c.execute('INSERT INTO players VALUES(%s,%s,10)',('parent',1))
        case.c.execute('INSERT INTO players VALUES(%s,%s,10)',('child',4))
        case.c.execute('INSERT INTO referrals(child_id,parent_id,created) VALUES(%s,%s,0)',('child','parent'))
        case.c.raw.commit()
        case.send(4,'/start partner_2')
        self.assertEqual(case.c.execute('SELECT referrer FROM bot_accounts WHERE uid=4').fetchone()['referrer'],1)
    def test_unlinked_game_inviter_is_not_replaced_by_bot_inviter(self):
        import test_task_bot as base
        case=base.TaskBotTests();case.setUp()
        case.c.execute('INSERT INTO players VALUES(%s,NULL,10)',('parent',))
        case.c.execute('INSERT INTO players VALUES(%s,%s,10)',('child',4))
        case.c.execute('INSERT INTO referrals(child_id,parent_id,created) VALUES(%s,%s,0)',('child','parent'))
        case.c.raw.commit()
        case.send(4,'/start partner_2')
        self.assertIsNone(case.c.execute('SELECT referrer FROM bot_accounts WHERE uid=4').fetchone()['referrer'])
        case.c.execute('UPDATE players SET telegram_id=1 WHERE id=%s',('parent',))
        bridge.sync(case.c,1)
        self.assertEqual(case.c.execute('SELECT referrer FROM bot_accounts WHERE uid=4').fetchone()['referrer'],1)
