"""Manual task drafts: advertiser gross price, photo albums and atomic money reservation."""
import unittest
from unittest.mock import patch
import task_bot as bot
import bot_manual as manual
import test_task_bot as base


class ManualTaskTests(unittest.TestCase):
    setUp=base.TaskBotTests.setUp
    api=base.TaskBotTests.api
    send=base.TaskBotTests.send
    credit=base.TaskBotTests.credit
    balance=base.TaskBotTests.balance

    def draft(self,price='10',count='2',link=None):
        self.credit(2,'100','manual-funding')
        self.send(2,action='new:manual');self.send(2,'Custom assignment')
        self.send(2,'Complete the instructions and send proof of your result')
        self.send(2,action='manual:skip_url') if link is None else self.send(2,link)
        self.send(2,price);self.send(2,count)
        self.assertEqual(bot.state(self.c,2)['state'],'manual_photos')

    def photo(self,uid=2,unique='image-one',album=None,caption='',event=None):
        self.serial+=1
        message={'message_id':event or self.serial,'chat':{'id':uid,'type':'private'},'from':{'id':uid},
                 'photo':[{'file_id':'small-'+unique,'file_unique_id':unique+'-small'},{'file_id':'big-'+unique,'file_unique_id':unique,'file_size':1000}]}
        if album:message['media_group_id']=album
        if caption:message['caption']=caption
        return bot.handle({'message':message},lambda:self.c,self.api,lambda u,c:u==1)

    def create(self):
        preview=self.send(2,action='manual:photos_done')
        self.send(2,action='confirm_task')
        t=self.c.execute('SELECT * FROM bot_tasks ORDER BY created DESC LIMIT 1').fetchone()
        self.assertIsNotNone(t)
        return t,preview

    def test_gross_price_includes_fee_no_fixed_manual_price(self):
        self.draft()
        self.assertEqual(self.balance(2),10000)
        t,preview=self.create()
        self.assertIn('Награда исполнителю: 8,00 грн',preview['text'])
        self.assertIn('В том числе комиссия: 2,00 грн',preview['text'])
        self.assertIn('ИТОГО С БАЛАНСА: 20,00 грн',preview['text'])
        self.assertEqual((t['reward'],t['remaining']),(800,2000))
        self.assertEqual(self.balance(2),8000)
        self.assertEqual(self.c.execute('SELECT cost FROM bot_task_terms').fetchone()['cost'],1000)
        self.send(2,action='confirm_task')
        self.assertEqual(self.balance(2),8000)
        self.assertEqual(self.c.execute('SELECT count(*) AS n FROM bot_tasks').fetchone()['n'],1)

    def test_price_rounding_and_changed_tariff_snapshot(self):
        for n in (2,3,7,99,101,1000,7777):
            q=manual.price_quote(self.c,n)
            self.assertEqual(q['cost'],n)
            self.assertEqual(q['reward'],n*80//100)
        self.c.raw.commit()
        self.draft(price='3.17',count='1')
        q=bot.state(self.c,2)['data']['terms']
        self.c.execute('UPDATE bot_economics SET fee=3000');self.c.raw.commit()
        t,_=self.create()
        self.assertEqual(t['reward'],253)
        self.assertEqual(bot.bot_economy.cost(self.c,t),q['cost'])

    def test_optional_link_and_photos_never_create_empty_url_buttons(self):
        self.draft();t,_=self.create();self.send(1,action='admin:approve:'+t['id'])
        response=self.send(3,action='task:'+t['id'])
        self.assertNotIn("'url': ''",str(response))
        self.assertNotIn('Примеры',str(response['reply_markup']))
        self.send(3,action='take:'+t['id']);self.send(3,action='check:'+t['id']);self.send(3,'Proof of completion')
        self.send(2,action='accept:'+t['id']+':3')
        self.assertEqual(self.balance(3),800)
        self.assertEqual(self.c.execute('SELECT remaining FROM bot_tasks').fetchone()['remaining'],1000)

    def test_album_and_individual_photo_deduplicate_and_store_largest_variant(self):
        self.draft()
        self.assertEqual(self.photo(unique='a',album='group',event=1234),{'ok':True})
        self.photo(unique='b',album='group');self.photo(unique='c')
        self.photo(unique='a',album='group',event=1234)
        self.photo(unique='a',album='another-group')
        self.assertEqual(len(bot.state(self.c,2)['data']['images']),3)
        t,preview=self.create()
        self.assertIn('Фотографий: 3',preview['text'])
        rows=manual.photo_rows(self.c,t['id'])
        self.assertEqual([r['file_id'] for r in rows],['big-a','big-b','big-c'])
        self.assertEqual([r['position'] for r in rows],[0,1,2])
        self.assertEqual(self.balance(2),8000)

    def test_description_with_album_caption_and_later_items_do_not_advance_link(self):
        self.credit(2,'100','description-fund')
        self.send(2,action='new:manual');self.send(2,'Photo instructions')
        self.photo(unique='a',album='g',caption='Follow this screenshot and send proof')
        self.photo(unique='b',album='g')
        self.assertEqual(bot.state(self.c,2)['state'],'manual_url')
        self.assertEqual(len(bot.state(self.c,2)['data']['images']),2)
        self.send(2,action='manual:skip_url');self.send(2,'1');self.send(2,'1')
        t,_=self.create();self.assertEqual(len(manual.photo_rows(self.c,t['id'])),2)

    def test_photo_examples_private_until_moderation_then_browse_without_payment(self):
        self.draft();self.photo(unique='first');self.photo(unique='second');t,_=self.create()
        response=self.send(3,action='manual:photo:'+t['id']+':0')
        self.assertIn('недоступны',response['text'])
        mod=self.send(1,action='admin:tasks')
        self.assertIn('manual:photo:'+t['id'],str(mod['reply_markup']))
        self.assertEqual(self.send(1,action='manual:photo:'+t['id']+':0')['photo'],'big-first')
        self.send(1,action='admin:approve:'+t['id'])
        public=self.send(3,action='manual:photo:'+t['id']+':1')
        self.assertEqual(public['photo'],'big-second')
        self.assertIn('2/2',public['caption'])
        self.assertEqual(self.balance(3),0)
        self.assertEqual(self.c.execute('SELECT remaining FROM bot_tasks').fetchone()['remaining'],2000)

    def test_late_album_photo_invalidates_previous_confirmation(self):
        self.draft();self.send(2,action='manual:photos_done')
        old=bot.state(self.c,2)['data']['nonce']
        self.photo(unique='late',album='g')
        self.assertEqual(bot.state(self.c,2)['state'],'manual_photos')
        self.send(2,action='confirm_task:'+old)
        self.assertEqual(self.c.execute('SELECT count(*) AS n FROM bot_tasks').fetchone()['n'],0)
        self.assertEqual(self.balance(2),10000)
        t,_=self.create()
        self.assertEqual(len(manual.photo_rows(self.c,t['id'])),1)

    def test_draft_gallery_old_nonce_and_other_user_cannot_read_photos(self):
        self.draft();self.photo(unique='secret')
        nonce=bot.state(self.c,2)['data']['draft']
        self.assertEqual(self.send(2,action='manual:draft:'+nonce+':0')['photo'],'big-secret')
        self.assertIn('закрыт',self.send(3,action='manual:draft:'+nonce+':0')['text'])
        self.send(2,action='new:manual')
        self.assertIn('другому',self.send(2,action='manual:draft:'+nonce+':0')['text'])
        self.assertEqual(self.c.execute('SELECT count(*) AS n FROM bot_task_photos').fetchone()['n'],0)

    def test_photo_limit_clear_and_cancel_do_not_reserve_money(self):
        self.draft()
        for i in range(10):self.photo(unique=str(i),album='group')
        self.assertIn('до 10',self.photo(unique='eleventh')['text'])
        self.assertEqual(len(bot.state(self.c,2)['data']['images']),10)
        self.send(2,action='manual:clear_photos')
        self.assertFalse(bot.state(self.c,2)['data']['images'])
        self.send(2,action='cancel_input')
        self.assertEqual(self.balance(2),10000)
        self.assertEqual(self.c.execute('SELECT count(*) AS n FROM bot_tasks').fetchone()['n'],0)

    def test_confirmation_photo_failure_rolls_back_money_and_order(self):
        self.draft();self.photo();self.send(2,action='manual:photos_done')
        with patch.object(manual,'save',side_effect=bot.UserError('Temporary media storage failure')):
            self.assertIn('Temporary',self.send(2,action='confirm_task')['text'])
        self.assertEqual(self.balance(2),10000)
        for table in ('bot_tasks','bot_task_photos','bot_task_terms','bot_ad_orders'):
            self.assertEqual(self.c.execute('SELECT count(*) AS n FROM '+table).fetchone()['n'],0)
        self.send(2,action='confirm_task')
        self.assertEqual(self.balance(2),8000)

    def test_arbitrary_https_link_saved_and_unsafe_links_do_not_advance(self):
        self.credit(2,'100','links-fund')
        self.send(2,action='new:manual');self.send(2,'Open a website');self.send(2,'Read instructions and provide the requested result')
        for bad in ('http://example.com','https://user:password@example.com','https://example.com:notaport','https://[oops','javascript:alert(1)'):
            self.send(2,bad);self.assertEqual(bot.state(self.c,2)['state'],'manual_url')
        self.send(2,'https://example.com/path?step=2');self.send(2,'2');self.send(2,'1')
        t,_=self.create();self.assertEqual(t['url'],'https://example.com/path?step=2')
