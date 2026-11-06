import hashlib
import unittest
from unittest.mock import patch
import main
import task_bot as bot
import bot_moderation as mod
import test_task_bot as base

class ModerationTests(unittest.TestCase):
    setUp=base.TaskBotTests.setUp
    api=base.TaskBotTests.api
    send=base.TaskBotTests.send
    credit=base.TaskBotTests.credit
    balance=base.TaskBotTests.balance
    task=base.TaskBotTests.task
    invariant=base.TaskBotTests.invariant

    def control(self,op,tid,reason='Stopped at the advertiser request'):
        self.send(1,action='admin:taskop:'+op+':'+tid)
        if op=='archive':self.send(1,reason)
        nonce=bot.state(self.c,1)['data']['nonce']
        return self.send(1,action='admin:taskcontrol:'+nonce),nonce

    def test_same_owner_root_start_button_and_command(self):
        a=self.send(1,'/start');b=self.send(1,action='admin');c=self.send(1,'/botadmin')
        self.assertEqual(a,b);self.assertEqual(b,c)
        with patch.object(main,'db',return_value=self.c):self.assertEqual(main.farm_admin_panel(1),a)
        rows=a['reply_markup']['inline_keyboard']
        self.assertEqual([r['callback_data'] for r in rows[0]],['bot:admin:section:manage','bot:admin:payouts'])
        self.assertNotIn('/bot',str(self.send(1,action='admin:section:manage')))
        self.assertNotIn('bot:admin',str(self.send(2,action='cabinet')))

    def test_foreign_admin_actions_and_forged_form_have_no_money_effect(self):
        tid=self.task();before=self.balance(2)
        for uid in (2,3):
            for action in ('admin','admin:task:'+tid,'admin:taskop:pause:'+tid,'admin:taskop:archive:'+tid,'admin:approve:'+tid,'admin:payconfirm:fake','admin:field:daily','admin:taskcontrol:fake'):
                self.assertIn('Доступ',self.send(uid,action=action)['text'])
        bot.state(self.c,3,'admin_task_control_confirm',{'id':tid,'op':'archive','nonce':'fake'});self.c.raw.commit()
        self.assertIn('Доступ',self.send(3,action='admin:taskcontrol:fake')['text'])
        self.assertIn('Доступ',self.send(3,'some input')['text'])
        self.assertFalse(mod.paused(self.c,tid));self.assertEqual(self.balance(2),before)
        self.assertEqual(self.c.execute('SELECT count(*) AS n FROM bot_task_admin_audit').fetchone()['n'],0)

    def test_paused_task_hidden_and_direct_completion_blocked_until_resume(self):
        tid=self.task(count='1');before=self.balance(2)
        self.send(3,action='take:'+tid)
        _,nonce=self.control('pause',tid)
        self.assertTrue(mod.paused(self.c,tid));self.assertEqual(self.balance(2),before)
        self.assertNotIn('Test task',str(self.send(4,action='list:channel:0')))
        self.joined=True
        self.assertIn('остановлено',self.send(3,action='check:'+tid)['text'])
        self.assertEqual(self.balance(3),0)
        self.send(1,action='admin:taskcontrol:'+nonce)
        self.assertEqual(self.c.execute('SELECT count(*) AS n FROM bot_task_admin_audit').fetchone()['n'],1)
        self.control('resume',tid)
        self.send(3,action='check:'+tid);self.assertEqual(self.balance(3),56)
        self.send(3,action='check:'+tid);self.assertEqual(self.balance(3),56)
        self.invariant()

    def test_archive_refunds_owner_once_and_keeps_order_and_paid_claims(self):
        tid=self.task();self.send(3,action='take:'+tid);self.joined=True;self.send(3,action='check:'+tid)
        before=self.balance(2);_,nonce=self.control('archive',tid)
        self.assertEqual(self.balance(2),before+70)
        t=self.c.execute('SELECT * FROM bot_tasks WHERE id=%s',(tid,)).fetchone()
        self.assertEqual((t['status'],t['remaining']),('closed',0))
        self.send(1,action='admin:taskcontrol:'+nonce);self.assertEqual(self.balance(2),before+70)
        self.assertEqual(self.balance(3),56)
        self.assertEqual(self.c.execute('SELECT count(*) AS n FROM bot_ad_orders').fetchone()['n'],1)
        self.assertIn('Подписаться на ChannelTest',str(self.send(1,action='admin:tasklist:closed:0')))
        self.invariant()

    def test_archive_waits_for_manual_reviews_and_uncertain_publication(self):
        tid=self.task('manual','1');self.send(3,action='take:'+tid);self.send(3,action='check:'+tid);self.send(3,'Proof of completion')
        before=self.balance(2)
        self.assertIn('проверь',self.send(1,action='admin:taskop:archive:'+tid)['text'])
        self.assertEqual(self.balance(2),before)
        self.send(1,action='admin:taskop:pause:'+tid);nonce=bot.state(self.c,1)['data']['nonce'];self.send(1,action='admin:taskcontrol:'+nonce)
        self.send(2,action='accept:'+tid+':3');self.assertEqual(self.balance(3),0)
        self.control('resume',tid);self.send(2,action='accept:'+tid+':3');self.assertEqual(self.balance(3),80)

    def test_search_cards_claims_and_bad_input(self):
        tid=self.task();self.send(1,action='admin:tasksearch')
        response=self.send(1,tid)
        for text in (tid,'ID автора','0,70 грн','0,56 грн'):self.assertIn(text,response['text'])
        self.assertIn('Подписаться на ChannelTest',str(self.send(1,action='admin:tasklist:active:0')))
        self.send(3,action='take:'+tid)
        self.assertIn('3',self.send(1,action='admin:taskclaims:'+tid+':0')['text'])
        self.assertIn('Исполнитель',self.send(1,action='admin:taskwork:'+tid+':3')['text'])
        self.send(1,action='admin:tasksearch');self.assertIn('ID задания',self.send(1,"' OR 1=1")['text'])

    def test_paged_queue_and_search_do_not_mix_orders(self):
        self.credit(2,'100','paged-orders')
        for i in range(9):
            self.send(2,action='new:manual');self.send(2,'Queued task '+str(i))
            self.send(2,'Send a screenshot of the completed instructions')
            self.send(2,action='manual:skip_url');self.send(2,'1');self.send(2,'1')
            self.send(2,action='manual:photos_done');self.send(2,action='confirm_task')
        first=self.send(1,action='admin:tasklist:active:0');second=self.send(1,action='admin:tasklist:active:1')
        def ids(response):return [x['callback_data'] for row in response['reply_markup']['inline_keyboard'] for x in row if x.get('callback_data','').startswith('bot:admin:task:')]
        self.assertEqual(len(ids(first)),8);self.assertEqual(len(ids(second)),1)
        self.assertFalse(set(ids(first))&set(ids(second)))
        self.assertNotIn('/bot',first['text'])
        self.assertIn('Далее',str(first['reply_markup']))

    def test_archive_requires_new_confirmation_when_budget_changes(self):
        tid=self.task();self.send(1,action='admin:taskop:archive:'+tid);self.send(1,'Closing the rest of this order')
        nonce=bot.state(self.c,1)['data']['nonce']
        self.send(3,action='take:'+tid);self.joined=True;self.send(3,action='check:'+tid)
        before=self.balance(2)
        preview=self.send(1,action='admin:taskcontrol:'+nonce)
        self.assertIn('0,70 грн',preview['text']);self.assertEqual(self.balance(2),before)
        new=bot.state(self.c,1)['data']['nonce'];self.assertNotEqual(nonce,new)
        self.send(1,action='admin:taskcontrol:'+nonce);self.assertEqual(self.balance(2),before)
        self.send(1,action='admin:taskcontrol:'+new);self.assertEqual(self.balance(2),before+70)
        self.invariant()

    def test_revoked_owner_cannot_replay_cached_panel(self):
        payload={'message':{'message_id':999999,'chat':{'id':1,'type':'private'},'from':{'id':1},'text':'/start'}}
        a=bot.handle(payload,lambda:self.c,self.api,lambda u,c:True)
        self.assertIn('Панель',a['text'])
        b=bot.handle(payload,lambda:self.c,self.api,lambda u,c:False)
        self.assertIn('Доступ',b['text'])
        self.assertNotIn('bot:admin',str(b))

    def test_identity_is_not_claimed_by_first_caller_or_invalid_types(self):
        self.c.execute('DELETE FROM farm_admin_identity');self.c.raw.commit()
        with patch.object(main,'db',return_value=self.c),patch.dict(main.os.environ,{'FARM_ADMIN_TELEGRAM_ID':''}):
            self.assertFalse(main.farm_admin_telegram(3,3))
            self.assertIsNone(self.c.execute('SELECT * FROM farm_admin_identity').fetchone())
            for uid in (True,1.0,'1',None,-1):self.assertFalse(main.farm_admin_telegram(uid,uid))
            with patch.object(main,'FARM_OWNER_ID_SHA256',hashlib.sha256(b'1').hexdigest()):
                self.assertTrue(main.farm_admin_telegram(1,1))
            self.assertFalse(main.farm_admin_telegram(3,3));self.assertFalse(main.farm_admin_telegram(1,3))

    def test_spoofed_sender_chat_group_and_bot_are_ignored(self):
        for sender,chat in [({'id':3},{'id':1,'type':'private'}),({'id':1},{'id':1,'type':'group'}),({'id':1,'is_bot':True},{'id':1,'type':'private'})]:
            payload={'callback_query':{'id':'spoof','from':sender,'data':'bot:admin','message':{'chat':chat}}}
            self.assertIsNone(bot.handle(payload,lambda:self.c,self.api,lambda u,c:True))
