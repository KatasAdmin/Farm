"""User-facing catalog accuracy, safe referral welcome flows and real leaderboards."""
import datetime as dt
import unittest
from html.parser import HTMLParser
from unittest.mock import patch
import task_bot as bot
import bot_ui as ui
import test_bot_extras as extended
import test_task_bot as base


class TelegramHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack=[]
        self.tags=[]
    def handle_starttag(self,tag,attrs):
        self.tags.append(tag)
        self.stack.append(tag)
    def handle_endtag(self,tag):
        if not self.stack or self.stack.pop()!=tag:
            raise AssertionError('Unbalanced HTML')


class BotScreenTests(unittest.TestCase):
    setUp=extended.ExtendedBotTests.setUp
    api=extended.ExtendedBotTests.api
    send=base.TaskBotTests.send
    credit=base.TaskBotTests.credit
    balance=base.TaskBotTests.balance
    ads_balance=base.TaskBotTests.ads_balance
    task=base.TaskBotTests.task
    invariant=base.TaskBotTests.invariant
    create_bot_task=extended.ExtendedBotTests.create_bot_task
    create_post_task=extended.ExtendedBotTests.create_post_task
    channel_claim=extended.ExtendedBotTests.channel_claim
    forward=extended.ExtendedBotTests.forward

    def save_welcome(self,uid,body):
        self.send(uid,action='welcome:edit')
        self.send(uid,body)
        data=bot.state(self.c,uid)['data']
        return self.send(uid,action='welcome:save:'+data['nonce'])

    def assert_valid_html(self,response):
        self.assertEqual(response['parse_mode'],'HTML')
        parser=TelegramHTML()
        parser.feed(response['text'])
        self.assertFalse(parser.stack)
        self.assertTrue(set(parser.tags)<=set(['b','i','code']))
        self.assertLessEqual(len(response['text'].encode('utf-16-le'))//2,4096)
        for row in response['reply_markup'].get('inline_keyboard',[]):
            for button in row:
                if 'callback_data' in button:
                    self.assertLessEqual(len(button['callback_data'].encode()),64)

    def test_cabinet_actions_reordered_and_no_unwanted_sentence(self):
        self.credit()
        response=self.send(2,action='cabinet')
        self.assert_valid_html(response)
        actions=[[b['callback_data'] for b in row] for row in response['reply_markup']['inline_keyboard']]
        self.assertEqual(actions,[['bot:deposit','bot:withdraw'],['bot:claims'],['bot:payouts','bot:history']])
        self.assertNotIn('Эти деньги можно',response['text'])
        self.assertNotIn('Долг по штрафам: 0',response['text'])
        self.assertEqual(self.balance(2),1000)

    def test_empty_earn_screen_uses_our_rates_and_zero_real_total(self):
        response=self.send(3,'🚀 Заработать')
        self.assert_valid_html(response)
        self.assertIn('Награды в доступных заданиях: 0,00 грн',response['text'])
        buttons=str(response['reply_markup'])
        for value in ('0,32 грн','0,56 грн','0,48 грн','0,03 грн','0,50 грн'):
            self.assertIn(value,buttons)
        self.assertNotIn('0.75',buttons)
        self.assertNotIn('₽',str(response))
        self.assertEqual(self.balance(3),0)

    def test_earn_total_is_one_reward_per_available_task_not_entire_order_budget(self):
        tid=self.task(count='10')
        # Cost 7 UAH reserved for 10 workers; this worker can receive only 0.56 UAH.
        response=self.send(3,action='earn')
        self.assertIn('Подписаться на канал: <b>1</b>',response['text'])
        self.assertIn('Награды в доступных заданиях: 0,56 грн',response['text'])
        owner=self.send(2,action='earn')
        self.assertIn('Награды в доступных заданиях: 0,00 грн',owner['text'])
        self.send(3,action='take:'+tid)
        self.joined=True
        self.send(3,action='check:'+tid)
        self.assertIn('Награды в доступных заданиях: 0,00 грн',self.send(3,action='earn')['text'])
        self.assertNotIn('Test task',str(self.send(3,action='list:channel:0')))
        self.assertEqual(self.balance(3),56)

    def test_funded_manual_slots_on_review_are_not_advertised_as_available(self):
        tid=self.task('manual','1')
        self.send(3,action='take:'+tid)
        self.send(3,action='check:'+tid)
        self.send(3,'A real proof')
        response=self.send(1,action='earn')
        self.assertIn('Выполнить задание: <b>0</b>',response['text'])
        base.complete_refusal(self,2,f'rejectwork:{tid}:3')
        response=self.send(1,action='earn')
        self.assertIn('Выполнить задание: <b>1</b>',response['text'])

    def test_unpublished_post_is_excluded_from_overview_and_catalog(self):
        tid=self.create_post_task()
        self.c.execute("UPDATE bot_post_publications SET status='uncertain' WHERE task=%s",(tid,))
        self.c.raw.commit()
        response=self.send(3,action='earn')
        self.assertIn('Посмотреть пост: <b>0</b>',response['text'])
        rows=self.c.execute('SELECT t.id FROM bot_tasks t WHERE '+ui.catalog_filter()+' AND t.kind=%s',(3,3,3,'post')).fetchall()
        self.assertEqual(rows,[])

    def test_known_completed_bot_hidden_from_other_campaigns(self):
        tid=self.create_bot_task()
        self.send(3,action='take:'+tid)
        self.forward(3)
        with self.c:
            bot.change(self.c,2,-40,'task_budget','another bot campaign')
            self.c.execute("INSERT INTO bot_tasks SELECT 'duplicate-bot',owner,kind,title,description,url,chat_id,reward,40,'active',created FROM bot_tasks WHERE id=%s",(tid,))
        self.assertNotIn('Target bot',str(self.send(3,action='list:bot:0')))
        self.assertIn('Перейти в бота: <b>0</b>',self.send(3,action='earn')['text'])
        self.assertEqual(self.balance(3),32)

    def test_top_lists_real_first_level_invites_and_no_fake_members(self):
        self.send(4,'/start partner_2')
        self.send(5,'/start partner_2')
        self.send(6,'/start partner_3')
        self.send(7,'/start partner_1')
        self.c.execute("UPDATE bot_accounts SET name='Team A' WHERE uid=2")
        self.c.execute("UPDATE bot_accounts SET name='Team B' WHERE uid=3")
        self.c.raw.commit()
        result=self.send(1,action='top:all')
        self.assert_valid_html(result)
        self.assertIn('🥇 <b>Team A</b> — 2 чел.',result['text'])
        self.assertIn('Team B</b> — 1 чел.',result['text'])
        # Reopening the same invitation never creates another referral or changes sponsor.
        self.send(4,'/start partner_3')
        self.assertIn('Team A</b> — 2 чел.',self.send(1,action='top:all')['text'])
        self.assertEqual(self.c.execute('SELECT referrer FROM bot_accounts WHERE uid=4').fetchone()['referrer'],2)

    def test_today_top_filters_inclusive_start_exclusive_end(self):
        for uid,parent,created in [(4,2,100),(5,2,200),(6,3,99),(7,1,199)]:
            self.send(uid,f'/start partner_{parent}')
            self.c.execute('UPDATE bot_accounts SET created=%s WHERE uid=%s',(created,uid))
            self.c.raw.commit()
        self.c.execute("UPDATE bot_accounts SET name='Team A' WHERE uid=2")
        self.c.execute("UPDATE bot_accounts SET name='Team B' WHERE uid=3")
        self.c.raw.commit()
        with patch('bot_ui.today_bounds',return_value=(100,200)):
            result=self.send(1,action='top:today')
        self.assertIn('Team A</b> — 1 чел.',result['text'])
        self.assertNotIn('Team B',result['text'])
        self.assertIn('Твоих приглашений: <b>1</b>',result['text'])

    def test_kyiv_bounds_handle_daylight_saving_transition(self):
        now=dt.datetime(2026,10,25,12,tzinfo=ui.ZoneInfo('Europe/Kyiv'))
        with patch('bot_ui.dt.datetime',wraps=dt.datetime) as clock:
            clock.now.return_value=now
            start,end=ui.today_bounds()
        self.assertEqual(end-start,25*3600)

    def test_partners_show_active_counts_rates_and_no_flat_friend_bonus(self):
        self.send(4,'/start partner_3')
        self.send(5,'/start partner_4')
        tid=self.task()
        self.send(5,action='take:'+tid)
        self.joined=True
        self.send(5,action='check:'+tid)
        result=self.send(3,'👥 Партнёры')
        self.assert_valid_html(result)
        self.assertIn('Приглашено в команду: <b>2</b>',result['text'])
        self.assertIn('Активных: <b>1</b>',result['text'])
        self.assertIn('Пока без выполнений: <b>1</b>',result['text'])
        self.assertIn('Уровень 1: 1 чел. · <b>5%',result['text'])
        self.assertIn('Уровень 2: 1 чел. · <b>2,5%',result['text'])
        self.assertIn('Доход от команды: 0,01 грн',result['text'])
        self.assertEqual(self.balance(3),1)

    def test_welcome_is_free_and_draft_must_be_confirmed(self):
        self.credit(2,'10','welcome-cash')
        self.send(2,action='welcome:edit')
        preview=self.send(2,'Добро пожаловать в мою команду!')
        self.assert_valid_html(preview)
        self.assertEqual(self.c.execute('SELECT count(*) AS n FROM bot_ref_welcomes').fetchone()['n'],0)
        nonce=bot.state(self.c,2)['data']['nonce']
        self.send(3,action='welcome:save:'+nonce)
        self.assertEqual(self.c.execute('SELECT count(*) AS n FROM bot_ref_welcomes').fetchone()['n'],0)
        self.send(2,action='welcome:save:'+nonce,event='save-replay')
        self.send(2,action='welcome:save:'+nonce,event='save-replay')
        self.assertEqual(self.balance(2),1000)
        self.assertEqual(self.c.execute('SELECT count(*) AS n FROM bot_ref_welcomes').fetchone()['n'],1)

    def test_welcome_is_delivered_on_first_referral_start_only_and_sponsor_is_immutable(self):
        self.save_welcome(2,'Только для новых участников команды 🐣')
        result=self.send(4,'/start partner_2')
        self.assert_valid_html(result)
        self.assertIn('Только для новых участников команды',result['text'])
        self.assertNotIn('Только для новых участников команды',self.send(4,'/start partner_2')['text'])
        self.assertNotIn('Только для новых участников команды',self.send(3,'/start partner_2')['text'])
        self.assertIsNone(self.c.execute('SELECT referrer FROM bot_accounts WHERE uid=3').fetchone()['referrer'])
        self.assertEqual(self.c.execute('SELECT referrer FROM bot_accounts WHERE uid=4').fetchone()['referrer'],2)

    def test_welcome_cancel_and_old_nonce_do_not_overwrite_saved_content(self):
        self.save_welcome(2,'Original welcome')
        self.send(2,action='welcome:edit')
        self.send(2,'Discard this draft')
        old=bot.state(self.c,2)['data']['nonce']
        self.send(2,'/cancel')
        self.send(2,action='welcome:save:'+old)
        self.assertEqual(self.c.execute('SELECT body FROM bot_ref_welcomes WHERE uid=2').fetchone()['body'],'Original welcome')
        self.send(3,action='welcome:delete')
        self.assertIsNotNone(self.c.execute('SELECT body FROM bot_ref_welcomes WHERE uid=2').fetchone())
        self.send(2,action='welcome:delete')
        self.assertIsNone(self.c.execute('SELECT body FROM bot_ref_welcomes WHERE uid=2').fetchone())

    def test_user_markup_escaped_and_welcome_respects_telegram_message_limit(self):
        body="'"*500
        self.save_welcome(2,body)
        self.c.execute('UPDATE bot_accounts SET name=%s WHERE uid=2',('&'*100,))
        self.c.raw.commit()
        self.serial+=1
        result=bot.handle({'message':{'message_id':self.serial,'chat':{'id':4,'type':'private'},
                          'from':{'id':4,'first_name':'<'*100},'text':'/start partner_2'}},
                          lambda:self.c,self.api,lambda u,c:u==1)
        self.assert_valid_html(result)
        self.assertIn('&lt;',result['text'])
        self.assertNotIn('<'*20,result['text'])
        self.assertIn('&#x27;',result['text'])
        self.save_welcome(2,'<b>not markup</b> & https://example.com')
        preview=self.send(2,action='welcome:preview')
        self.assertIn('&lt;b&gt;not markup&lt;/b&gt;',preview['text'])

    def test_invalid_welcome_text_and_forward_are_not_saved(self):
        self.send(2,action='welcome:edit')
        for text in ('a'*501,'\x00'):
            self.send(2,text)
            self.assertEqual(bot.state(self.c,2)['state'],'welcome_edit')
        self.forward(2,text='Forwarded reply')
        self.assertEqual(bot.state(self.c,2)['state'],'welcome_edit')
        self.assertEqual(self.c.execute('SELECT count(*) AS n FROM bot_ref_welcomes').fetchone()['n'],0)

    def test_new_navigation_clears_drafts_and_preserves_wallet(self):
        self.credit()
        self.send(2,action='welcome:edit')
        self.send(2,action='earn')
        self.assertIsNone(bot.state(self.c,2))
        self.send(2,action='deposit')
        self.send(2,action='history')
        self.assertIsNone(bot.state(self.c,2))
        self.assertEqual(self.balance(2),1000)
        self.assertIn('Мой кабинет',self.send(2,'/start wallet')['text'])
        self.assertEqual(self.send(2,'/start')['reply_markup']['keyboard'],bot.MENU)

    def test_new_earn_buttons_and_promotion_reach_working_routes_without_mutations(self):
        response=self.send(3,action='earn')
        actions=[button['callback_data'][4:] for row in response['reply_markup']['inline_keyboard'] for button in row]
        for action in actions:
            if action=='daily':
                continue
            answer=self.send(3,action=action)
            self.assertIn('text',answer)
        promotion=self.send(3,'📣 Продвижение')
        self.assert_valid_html(promotion)
        self.assertEqual(self.balance(3),0)
        self.assertEqual(self.c.execute('SELECT count(*) AS n FROM bot_tasks').fetchone()['n'],0)

    def test_posts_button_opens_connected_channel_directly(self):
        self.send(1,'/botchannel @ChannelTest')
        response=self.send(3,action='earn')
        posts=response['reply_markup']['inline_keyboard'][3][0]
        self.assertEqual(posts['url'],'https://t.me/ChannelTest')
        self.assertNotIn('callback_data',posts)

    def test_existing_order_reward_used_in_overview_instead_of_new_default_rate(self):
        self.credit()
        with self.c:
            bot.change(self.c,2,-100,'task_budget','old rate')
            self.c.execute("INSERT INTO bot_tasks VALUES('old-rate',2,'channel','Legacy channel','Join this legacy order','https://t.me/test',-10012,100,100,'active',0)")
        response=self.send(3,action='earn')
        self.assertIn('Награды в доступных заданиях: 1,00 грн',response['text'])
        self.assertIn('+1,00 грн',response['reply_markup']['inline_keyboard'][1][0]['text'])
        self.assertEqual(self.balance(2),900)


if __name__=='__main__':
    unittest.main()
