import unittest
import task_bot as bot
import bot_identity as identity
import test_task_bot as base

class IdentitySearchTests(unittest.TestCase):
    api=base.TaskBotTests.api
    send=base.TaskBotTests.send
    def setUp(self):
        base.TaskBotTests.setUp(self)
        self.c.execute('ALTER TABLE players ADD COLUMN name text');self.c.raw.commit()
    def message(self,uid,mid,username=None,contact=None):
        sender={'id':uid,'first_name':'Tester'}
        if username:sender['username']=username
        m={'message_id':mid,'chat':{'id':uid,'type':'private'},'from':sender,'text':'/start'}
        if contact:m['contact']=contact;m['text']=''
        return bot.handle({'update_id':mid,'message':m},lambda:self.c,self.api,lambda u,c:u==1)
    def search(self,query):
        self.send(1,action='admin:accountsearch');return self.send(1,query)
    def test_links_username_phone_and_game_nickname_resolve_same_account(self):
        self.message(2,800,'FarmTester',{'user_id':2,'phone_number':'380671234567'})
        self.c.execute("INSERT INTO players VALUES('farm-uuid',2,100,'MyFarm')");self.c.raw.commit()
        for query in ('@FarmTester','farmtester','https://t.me/FarmTester','t.me/FarmTester','tg://user?id=2','2','+380671234567','+38 (067) 123-45-67','0671234567','380671234567','MyFarm','farm-uuid'):
            with self.subTest(query=query):self.assertIn('bot:admin:account:2',str(self.search(query)))
        card=self.send(1,action='admin:account:2')
        self.assertIn('@farmtester',card['text']);self.assertIn('+380671234567',card['text'])
    def test_cannot_index_third_party_contact_or_resolve_unknown_phone(self):
        r=self.message(3,801,contact={'user_id':2,'phone_number':'380671234567'})
        self.assertIn('только свой номер',r['text'])
        self.assertIn('не найдены',self.search('+380671234567')['text'])
        self.assertEqual(self.c.execute('SELECT phone FROM bot_identities WHERE uid=3').fetchone()['phone'],'')
    def test_username_reassignment_does_not_return_previous_account(self):
        self.message(2,802,'CurrentName');self.message(3,803,'CurrentName')
        result=str(self.search('@CurrentName'))
        self.assertIn('bot:admin:account:3',result);self.assertNotIn('bot:admin:account:2',result)
    def test_contact_share_is_optional_and_has_a_real_telegram_contact_button(self):
        result=self.send(2,action='identity:share')
        self.assertTrue(result['reply_markup']['keyboard'][0][0]['request_contact'])
        self.assertEqual(identity.parse_query('https://example.com/SomeUser'),('invalid',''))
        self.assertIn('Доступ',self.send(3,action='admin:accountsearch')['text'])
