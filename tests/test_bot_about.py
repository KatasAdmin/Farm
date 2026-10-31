"""Public statistics reflect paid operations; links and dates are owner-controlled."""
import datetime as dt
import unittest
from zoneinfo import ZoneInfo
from unittest.mock import patch
import task_bot as bot
import bot_about as about
import test_task_bot as base
import test_bot_ui as screens


class AboutTests(unittest.TestCase):
    setUp=base.TaskBotTests.setUp
    api=base.TaskBotTests.api
    send=base.TaskBotTests.send
    balance=base.TaskBotTests.balance
    credit=base.TaskBotTests.credit
    task=base.TaskBotTests.task
    assert_valid_html=screens.BotScreenTests.assert_valid_html

    def test_about_buttons_follow_reference_and_do_not_change_wallet(self):
        self.credit()
        response=self.send(2,'📚 О боте')
        self.assert_valid_html(response)
        rows=response['reply_markup']['inline_keyboard']
        self.assertEqual([[b['callback_data'] for b in row] for row in rows],
            [['bot:about:stats'],['bot:about:news','bot:about:payouts'],['bot:about:chat','bot:about:rules'],['bot:about:admin_url']])
        self.assertEqual(self.balance(2),1000)
        self.assertNotIn('Хочу такого',response['text'])

    def test_empty_stats_do_not_copy_reference_numbers(self):
        response=self.send(3,action='about:stats')
        self.assert_valid_html(response)
        self.assertIn('Всего пользователей: <b>3</b>',response['text'])
        self.assertIn('Подписок на каналы: <b>0</b>',response['text'])
        self.assertIn('Выплачено всего: <b>0,00 грн</b>',response['text'])
        self.assertIn('Квесты: <i>готовятся</i>',response['text'])
        self.assertNotIn('344002',response['text'])
        self.assertNotIn('Всего просмотров',response['text'])

    def test_stats_only_paid_executions_and_posted_funded_active_orders(self):
        tid=self.task(count='2')
        self.send(3,action='take:'+tid)
        self.joined=True
        self.send(3,action='check:'+tid)
        self.send(3,action='check:'+tid)
        with self.c:
            for key,kind,status,remaining,reward in [
                ('pending','channel','pending',100,100),('closed','channel','closed',0,100),
                ('unfunded','group','active',0,50),('postbad','post','active',4,3),
                ('postok','post','active',4,3),('reviewing','manual','active',100,80)]:
                if remaining:
                    bot.change(self.c,2,-remaining,'task_budget','fixture '+key)
                self.c.execute('INSERT INTO bot_tasks VALUES(%s,2,%s,%s,%s,%s,-10012,%s,%s,%s,0)',
                               (key,kind,key,'Test description','https://t.me/test',reward,remaining,status))
            self.c.execute("INSERT INTO bot_post_publications VALUES('postbad',-10012,NULL,'uncertain','')")
            self.c.execute("INSERT INTO bot_post_publications VALUES('postok',-10012,1,'posted','https://t.me/test/1')")
            self.c.execute("INSERT INTO bot_claims(task,uid,status,created) VALUES('reviewing',1,'review',0)")
        response=self.send(2,action='about:stats')['text']
        self.assertIn('Подписок на каналы: <b>1</b>',response)
        self.assertIn('На каналы: <b>1</b>',response)  # includes own funded campaign globally
        self.assertIn('На посты: <b>1</b>',response)
        self.assertIn('На группы: <b>0</b>',response)
        self.assertIn('Ручные задания: <b>0</b>',response)

    def test_paid_payouts_aggregate_without_exposing_destinations(self):
        with self.c:
            for key,status,n,uid in [('paid','paid',125,2),('pending','pending',1000,3),('cancel','cancelled',700,2)]:
                self.c.execute('INSERT INTO bot_payouts VALUES(%s,%s,%s,%s,%s,%s,0)',
                               (key,uid,n,'secret-bank-recipient',status,'secret-operation'))
            self.c.execute('INSERT INTO bot_daily_claims VALUES(1,%s,50)',('2026-10-30',))
            self.c.execute('INSERT INTO bot_daily_claims VALUES(2,%s,50)',('2026-10-30',))
        response=self.send(3,action='about:stats')
        self.assertIn('Выплачено всего: <b>1,25 грн</b>',response['text'])
        self.assertIn('Ежедневных наград начислено: <b>1,00 грн</b>',response['text'])
        public=self.send(3,action='about:payouts')
        self.assertIn('Выполнено выплат: <b>1</b>',public['text'])
        self.assertIn('Выплачено: <b>1,25 грн</b>',public['text'])
        self.assertNotIn('secret',str(response)+str(public))

    def test_new_today_uses_same_kyiv_calendar_bounds(self):
        self.c.execute('UPDATE bot_accounts SET created=50 WHERE uid=1')
        self.c.execute('UPDATE bot_accounts SET created=100 WHERE uid=2')
        self.c.execute('UPDATE bot_accounts SET created=200 WHERE uid=3')
        self.c.raw.commit()
        with patch('bot_ui.today_bounds',return_value=(100,200)):
            result=self.send(3,action='about:stats')['text']
        self.assertIn('Новых за сегодня: <b>1</b>',result)

    def test_links_are_editable_only_by_owner_and_switch_to_url_buttons(self):
        for field,url in [('news','@NewsTest'),('payouts','https://t.me/PayoutTest'),('chat','https://t.me/+Private123'),('admin_url','@OwnerTest')]:
            self.send(3,action='admin:aboutedit:'+field)
            self.send(3,url)
            self.assertEqual(about.settings(self.c)[field],'')
            self.send(1,action='admin:aboutedit:'+field)
            self.send(1,url)
        self.assertEqual(about.settings(self.c)['news'],'https://t.me/NewsTest')
        self.assertEqual(about.settings(self.c)['admin_url'],'https://t.me/OwnerTest')
        rows=self.send(3,'📚 О боте')['reply_markup']['inline_keyboard']
        self.assertEqual(rows[1][0]['url'],'https://t.me/NewsTest')
        self.assertEqual(rows[1][1]['url'],'https://t.me/PayoutTest')
        self.assertEqual(rows[2][0]['url'],'https://t.me/+Private123')
        self.assertEqual(rows[3][0]['url'],'https://t.me/OwnerTest')
        self.assertIsNone(bot.state(self.c,3))

    def test_invalid_link_does_not_replace_previous_link(self):
        self.send(1,action='admin:aboutedit:news')
        self.send(1,'@NewsTest')
        for url in ['javascript:alert(1)','http://t.me/NewsTest','https://evil.test/NewsTest','https://t.me:bad/NewsTest','https://name:password@t.me/NewsTest']:
            self.send(1,action='admin:aboutedit:news')
            self.send(1,url)
            self.assertEqual(about.settings(self.c)['news'],'https://t.me/NewsTest')
        self.send(1,action='admin:aboutedit:news')
        self.send(1,'-')
        self.assertEqual(about.settings(self.c)['news'],'')

    def test_forged_admin_edit_state_does_not_grant_access(self):
        bot.state(self.c,3,'about_edit',{'field':'admin_url'})
        self.c.raw.commit()
        self.send(3,'@Intruder')
        self.assertEqual(about.settings(self.c)['admin_url'],'')

    def test_support_button_creates_one_ticket_on_replayed_message(self):
        self.send(3,action='about:admin_url')
        self.assertEqual(bot.state(self.c,3)['state'],'public_support')
        response=self.send(3,'Не могу выполнить задание',event=123456)
        self.send(3,'Не могу выполнить задание',event=123456)
        self.assert_valid_html(response)
        self.assertIsNone(bot.state(self.c,3))
        rows=self.c.execute('SELECT * FROM support_tickets').fetchall()
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['telegram_id'],3)
        self.assertEqual(rows[0]['message'],'Не могу выполнить задание')
        self.assertEqual(self.balance(3),0)

    def test_support_can_be_cancelled_by_back_or_menu_and_rejects_photos(self):
        self.send(3,action='about:admin_url')
        self.send(3,'Screenshot',photo=True)
        self.assertEqual(bot.state(self.c,3)['state'],'public_support')
        self.send(3,action='about')
        self.assertIsNone(bot.state(self.c,3))
        self.send(3,action='about:admin_url')
        self.send(3,'/cancel')
        self.assertIsNone(bot.state(self.c,3))
        self.assertEqual(self.c.execute('SELECT count(*) AS n FROM support_tickets').fetchone()['n'],0)

    def test_statistics_origin_is_stable_and_owner_can_correct_it(self):
        self.send(1,action='admin:aboutedit:started')
        self.send(1,'2026-10-30')
        first=about.settings(self.c)['started']
        bot.initialize(self.c)
        self.c.raw.commit()
        self.assertEqual(about.settings(self.c)['started'],first)
        fixed=dt.datetime(2026,10,31,0,30,tzinfo=ZoneInfo('Europe/Kyiv')).timestamp()
        with patch('bot_about.time.time',return_value=fixed):
            text=self.send(3,action='about:stats')['text']
        self.assertIn('Работаем дней: <b>2</b>',text)
        self.assertIn('Отсчёт с: <b>30.10.2026</b>',text)
        for bad in ['20261031','2099-01-01','not a date']:
            self.send(1,action='admin:aboutedit:started')
            self.send(1,bad)
            self.assertEqual(about.settings(self.c)['started'],first)

    def test_rules_and_all_unconfigured_about_actions_work(self):
        response=self.send(3,action='about:rules')
        self.assert_valid_html(response)
        self.assertIn('условия сохраняются',response['text'])
        self.assertIn('CVV',response['text'])
        self.assertIn('один раз за календарный день',response['text'])
        for action in ['about:news','about:payouts','about:chat','about:admin_url','about:stats','about']:
            self.assertIn('text',self.send(3,action=action))
        self.assertIn('admin:about',str(self.send(1,'/botadmin')['reply_markup']))


if __name__=='__main__':
    unittest.main()
