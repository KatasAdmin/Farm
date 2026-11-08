"""Media delivery preserves account snapshots and never repeats wallet actions."""
from io import BytesIO
import unittest
from unittest.mock import patch
from PIL import Image
import bot_visuals as visuals
import bot_notifications
import task_bot as bot
import test_task_bot as base


class VisualTests(unittest.TestCase):
    setUp = base.TaskBotTests.setUp
    send = base.TaskBotTests.send
    api = base.TaskBotTests.api

    def tearDown(self):
        for cache in (visuals._images, visuals._avatars, visuals._files):
            cache.clear()

    def production(self, uid, text='', action='', mid=777, photo=False):
        message={'message_id':mid,'chat':{'id':uid,'type':'private'},
                 'from':{'id':uid,'first_name':'Test'},'text':text}
        if photo:message['photo']=[{'file_id':'old'}]
        payload={'callback_query':{'id':'cb'+str(mid),'data':'bot:'+action,
                 'from':message['from'],'message':message}} if action else {'message':message}
        return bot.handle(payload,lambda:self.c,self.api,lambda u,c:u==1,deliver_posts_inline=False)

    def test_snapshot_and_duplicate_are_atomic(self):
        self.c.execute('UPDATE bot_accounts SET available=125075 WHERE uid=2')
        self.c.raw.commit()
        result=self.production(2,action='cabinet')
        self.assertEqual(result,{'ok':True})
        row=self.c.execute("SELECT payload FROM bot_notifications WHERE kind='visual'").fetchone()
        import json
        payload=json.loads(row['payload'])
        self.assertEqual(payload['_visual']['balance'],125075)
        self.assertEqual(payload['_visual']['uid'],2)
        self.assertIn(bot.money(125075),payload['text'])
        self.production(2,action='cabinet')
        self.assertEqual(self.c.execute("SELECT count(*) AS n FROM bot_notifications WHERE kind='visual'").fetchone()['n'],1)
        self.assertEqual(self.c.execute('SELECT available FROM bot_accounts WHERE uid=2').fetchone()['available'],125075)

    def test_render_handles_long_names_and_avatars_and_cache(self):
        snapshot={'kind':'profile','uid':2,'name':'Длинное имя 👑 '*30,'balance':125075,'created':1700000000}
        key,data=visuals.render(snapshot)
        self.assertEqual(Image.open(BytesIO(data)).size,(1200,650))
        self.assertLess(len(data),180000)
        self.assertIs(visuals.render(snapshot)[1],data)
        self.assertNotEqual(visuals.render(dict(snapshot,balance=125076))[0],key)
        avatar=BytesIO();Image.new('RGB',(100,100),'purple').save(avatar,'PNG')
        self.assertNotEqual(visuals.render(snapshot,avatar.getvalue())[0],key)

    def test_fallback_retains_buttons(self):
        payload=visuals.attach(bot.say(2,'Баланс 12,50 грн',[[bot.button('Вывести','withdraw')]]),'profile',uid=2,name='Test',balance=1250)
        calls=[]
        def api(method,args):
            calls.append((method,args));return {'message_id':1,'chat':{'id':2}}
        with patch.object(visuals,'render',side_effect=RuntimeError),patch.object(visuals,'avatar',return_value=b''):
            visuals.deliver(2,payload,api)
        self.assertEqual(calls[-1][0],'sendMessage')
        self.assertEqual(calls[-1][1]['reply_markup'],payload['reply_markup'])
        self.assertNotIn('_visual',calls[-1][1])

    def test_edit_media_and_reuse_file_id(self):
        payload=visuals.attach(bot.say(2,'Баланс',[[bot.button('Обновить','cabinet')]]),'profile',uid=2,name='Test',balance=0)
        calls=[]
        def api(method,args):
            calls.append((method,args))
            return {'message_id':55,'chat':{'id':2},'photo':[{'file_id':'cached-photo'}]}
        with patch.object(visuals,'avatar',return_value=b''):
            visuals.deliver(2,payload,api)
            payload['_visual']['edit_message_id']=55
            visuals.deliver(2,payload,api)
        self.assertEqual([x[0] for x in calls],['sendPhoto','editMessageMedia'])
        self.assertEqual(calls[-1][1]['media']['media'],'cached-photo')
        self.assertNotIn('_photo_bytes',calls[-1][1])

    def test_partner_and_welcome_cards_are_reachable(self):
        self.production(2,action='friends')
        self.production(2,'/start',mid=778)
        import json
        rows=self.c.execute("SELECT payload FROM bot_notifications WHERE kind='visual'").fetchall()
        snapshots=[json.loads(r['payload'])['_visual'] for r in rows]
        self.assertEqual([s['kind'] for s in snapshots],['partners','welcome'])
        self.assertLess(len(snapshots[0]['caption'].encode('utf-16-le'))//2,1024)
        details=self.send(2,action='friends:details')
        self.assertIn('уровней',details['text'])

    def test_cache_is_bounded(self):
        for i in range(30):visuals.remember(visuals._files,i,str(i),100,5)
        self.assertEqual(len(visuals._files),5)
        self.assertIsNone(visuals.cached(visuals._files,0))

    def test_worker_delivers_card_after_commit(self):
        self.production(2,action='cabinet')
        calls=[]
        def api(method,args):
            calls.append((method,args))
            return {'message_id':5,'chat':{'id':2},'photo':[{'file_id':'profile-id'}]}
        with patch.object(visuals,'avatar',return_value=b''):
            bot_notifications.dispatch(lambda:self.c,api,limit=1)
        self.assertEqual(calls[0][0],'sendPhoto')
        self.assertIn('_photo_bytes',calls[0][1])
        self.assertEqual(self.c.execute("SELECT status FROM bot_notifications WHERE kind='visual'").fetchone()['status'],'sent')

    def test_different_recipient_is_rejected_without_delivery(self):
        calls=[]
        response=visuals.attach(bot.say(3,'Private balance'),'profile',uid=3,name='Private',balance=100)
        with self.assertRaises(ValueError):
            visuals.deliver(2,response,lambda *a:calls.append(a))
        self.assertFalse(calls)

    def test_visual_lane_cannot_consume_financial_notifications(self):
        self.production(2,action='cabinet')
        bot_notifications.enqueue(self.c,'finance-test','Выплата',recipient=2)
        self.c.raw.commit()
        calls=[]
        def api(method,args):
            calls.append(method)
            return {'message_id':5,'chat':{'id':2},'photo':[{'file_id':'profile-id'}]}
        with patch.object(visuals,'avatar',return_value=b''):
            bot_notifications.dispatch(lambda:self.c,api,limit=2,visuals=True)
        self.assertEqual(calls,['sendPhoto'])
        self.assertEqual(self.c.execute("SELECT status FROM bot_notifications WHERE id='finance-test'").fetchone()['status'],'pending')
        bot_notifications.dispatch(lambda:self.c,api,limit=2,visuals=False)
        self.assertEqual(calls,['sendPhoto','sendMessage'])

    def test_slow_callback_ack_does_not_delay_screen_transaction(self):
        import threading,time
        entered=threading.Event();release=threading.Event()
        def api(method,args):
            if method=='answerCallbackQuery':
                entered.set();release.wait(3)
            return True
        try:
            started=time.monotonic()
            with patch.object(self,'api',api):
                result=self.production(2,action='cabinet')
            elapsed=time.monotonic()-started
            self.assertEqual(result,{'ok':True})
            self.assertTrue(entered.wait(1))
            self.assertLess(elapsed,1)
        finally:
            release.set()

    def test_cold_avatar_never_blocks_card_and_is_cached_for_refresh(self):
        import threading,time
        entered=threading.Event();release=threading.Event()
        def api(method,args):
            if method=='getUserProfilePhotos':
                entered.set();release.wait(3)
                return {'photos':[[{'file_id':'avatar'}]]}
            return b'avatar-data'
        try:
            start=time.monotonic()
            self.assertEqual(visuals.avatar(2,api),b'')
            self.assertLess(time.monotonic()-start,0.5)
            self.assertTrue(entered.wait(1))
            self.assertEqual(visuals.avatar(2,api),b'')
        finally:
            release.set()
            deadline=time.monotonic()+2
            while 2 in visuals._avatar_jobs and time.monotonic()<deadline:
                time.sleep(0.005)
        self.assertEqual(visuals.avatar(2,api),b'avatar-data')

    def test_sections_are_static_distinct_and_small(self):
        keys=set()
        for section in visuals.SECTIONS:
            key,data=visuals.render({'kind':'section','section':section,'version':visuals.VERSION})
            keys.add(key)
            self.assertEqual(Image.open(BytesIO(data)).size,(1200,440))
            self.assertLess(len(data),90000)
        self.assertEqual(len(keys),len(visuals.SECTIONS))

    def test_cached_section_responds_directly_with_current_caption(self):
        response=visuals.decorate(bot.say(2,'Баланс: 10 грн',[[bot.button('Назад','cabinet')]]),'','deposit')
        self.assertEqual(response['_visual']['section'],'deposit')
        def api(method,args):
            return {'message_id':55,'chat':{'id':2},'photo':[{'file_id':'deposit-banner'}]}
        visuals.deliver(2,response,api)
        # The same shared banner remains valid for another user's live text.
        other=visuals.decorate(bot.say(3,'Баланс: 500 грн',[[bot.button('Назад','cabinet')]]),'','deposit')
        ready=visuals.ready_response(other)
        self.assertEqual(ready['method'],'sendPhoto')
        self.assertEqual(ready['chat_id'],3)
        self.assertEqual(ready['photo'],'deposit-banner')
        self.assertEqual(ready['caption'],'Баланс: 500 грн')
        self.assertNotIn('_visual',ready)
        other['_visual']['edit_message_id']=99
        self.assertEqual(visuals.ready_response(other)['method'],'editMessageMedia')

    def test_payment_input_and_confirmations_stay_lightweight(self):
        response=bot.input_prompt(2,'Введи сумму')
        for action in ('topup:card','topup:crypto','confirm_payout:nonce','confirm_task:nonce','daily'):
            self.assertNotIn('_visual',visuals.decorate(dict(response),'',action))

    def test_ordinary_navigation_does_not_rescan_referral_tree(self):
        with patch.object(bot.referral_bridge,'sync',side_effect=AssertionError('Unnecessary tree scan')):
            self.send(2,action='cabinet')
            self.send(2,action='earn')
        with patch.object(bot.referral_bridge,'sync',wraps=bot.referral_bridge.sync) as sync:
            self.send(4,'/start partner_2')
            sync.assert_called_once()
        self.assertEqual(self.c.execute('SELECT referrer FROM bot_accounts WHERE uid=4').fetchone()['referrer'],2)
