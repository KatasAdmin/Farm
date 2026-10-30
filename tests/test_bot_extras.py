import time
import datetime as dt
import unittest
from unittest.mock import patch
import task_bot as bot
import bot_extras as extra
import test_task_bot as base


class ExtendedBotTests(unittest.TestCase):
    send = base.TaskBotTests.send
    balance = base.TaskBotTests.balance
    ads_balance = base.TaskBotTests.ads_balance
    credit = base.TaskBotTests.credit
    task = base.TaskBotTests.task
    invariant = base.TaskBotTests.invariant
    def setUp(self):
        self.sent = []
        self.rights = True
        self.target_type = 'channel'
        self.send_failure = False
        base.TaskBotTests.setUp(self)
    def api(self, method, args):
        if method == 'getChat' and not self.errors:
            return {'id': -10012, 'type': self.target_type, 'username': 'ChannelTest'}
        result = base.TaskBotTests.api(self, method, args)
        if method == 'getChatMember' and args['user_id'] == 99:
            return {'status': 'administrator' if self.rights else 'member', 'can_post_messages': self.rights}
        if method == 'sendMessage':
            self.sent.append(args)
            if self.send_failure:
                raise RuntimeError('ambiguous transport failure')
            return {'message_id': 42, 'chat': {'id': args['chat_id'], 'username': 'ChannelTest'}}
        return result
    def forward(self, uid, bid=999, username='TargetBot', date=None, origin_type='user', text='Welcome'):
        self.serial += 1
        message = {'message_id': self.serial, 'chat': {'id': uid, 'type': 'private'}, 'from': {'id': uid},
                   'text': text, 'forward_origin': {'type': origin_type, 'date': int(time.time()) if date is None else date,
                   'sender_user': {'id': bid, 'is_bot': True, 'username': username}}}
        return bot.handle({'message': message}, lambda: self.c, self.api, lambda u, c: u == 1)
    def create_bot_task(self):
        self.credit()
        self.send(2, action='new:bot')
        for text in ('Target bot', 'Start and forward a new response', 'https://t.me/TargetBot'):
            self.send(2, text)
        self.assertEqual(bot.state(self.c, 2)['state'], 'task_count')
        self.send(2, '2')
        self.send(2, action='confirm_task')
        tid = self.c.execute("SELECT id FROM bot_tasks WHERE kind='bot'").fetchone()['id']
        self.send(1, action='admin:approve:' + tid)
        return tid
    def create_post_task(self):
        self.send(1, '/botchannel @ChannelTest')
        self.credit()
        self.send(2, action='new:post')
        for text in ('Test advertisement', 'This is the content of the paid post', '-', '2'):
            self.send(2, text)
        self.send(2, action='confirm_task')
        tid = self.c.execute("SELECT id FROM bot_tasks WHERE kind='post'").fetchone()['id']
        self.send(1, action='admin:approve:' + tid)
        return tid
    def channel_claim(self, uid, tid, mid=42, chat=-10012, event=None):
        self.serial += 1
        payload = {'callback_query': {'id': event or str(self.serial), 'from': {'id': uid},
                   'data': 'bot:postclaim:' + tid,
                   'message': {'message_id': mid, 'chat': {'id': chat, 'type': 'channel'}}}}
        return bot.handle(payload, lambda: self.c, self.api, lambda u, c: u == 1)
    def configure_bonus(self, daily='0.10'):
        return self.send(1, f'/botbonus {daily}')
    def test_channel_admin_rights_checked_before_accepting_link(self):
        self.send(2, action='new:channel')
        self.send(2, 'A channel')
        self.send(2, 'Subscribe to this channel')
        self.rights = False
        reply = self.send(2, 'https://t.me/ChannelTest')
        self.assertIn('администратором', reply['text'])
        self.assertEqual(bot.state(self.c, 2)['state'], 'task_url')
        self.assertEqual(self.c.execute('SELECT count(*) AS n FROM bot_tasks').fetchone()['n'], 0)
    def test_group_membership_and_admin_checks(self):
        self.target_type = 'supergroup'
        tid = self.task('group')
        self.send(3, action='take:' + tid)
        self.assertEqual(self.balance(3), 0)
        self.joined = True
        self.send(3, action='check:' + tid)
        self.assertEqual(self.balance(3), 48)
        self.invariant()
    def test_bot_creation_needs_only_link_and_does_not_request_admin_or_token(self):
        self.credit()
        self.send(2, action='new:bot')
        for text in ('Bot promotion', 'Start and forward answer'):
            self.send(2, text)
        self.send(2, 'https://evil.test/TargetBot')
        self.assertEqual(bot.state(self.c, 2)['state'], 'task_url')
        reply = self.send(2, 'https://t.me/TargetBot')
        self.assertEqual(bot.state(self.c, 2)['state'], 'task_count')
        self.assertNotIn('токен', reply['text'])
        with self.assertRaises(bot.UserError):
            extra.forwarded_bot({'forward_origin': {'type': 'hidden_user'}})
    def test_bot_reward_requires_fresh_correct_forward_and_pays_once(self):
        tid = self.create_bot_task()
        self.send(3, action='take:' + tid)
        self.assertIn('другого бота', self.forward(3, bid=998, username='WrongBot')['text'])
        self.assertIn('свежий', self.forward(3, date=1)['text'])
        self.assertEqual(self.balance(3), 0)
        self.forward(3)
        self.forward(3)
        self.send(3, action='take:' + tid)
        self.assertEqual(self.balance(3), 32)
        self.invariant()
    def test_bot_id_binding_rejects_changed_bot_with_same_name(self):
        tid = self.create_bot_task()
        self.send(3, action='take:' + tid)
        self.forward(3)
        self.send(1, action='take:' + tid)
        reply = self.forward(1, bid=998)
        self.assertIn('Источник пересылки', reply['text'])
        self.assertEqual(self.balance(1), 0)
        self.assertEqual(self.balance(3), 32)
        self.invariant()
    def test_same_bot_not_paid_twice_across_campaigns(self):
        tid = self.create_bot_task()
        self.send(3, action='take:' + tid)
        self.forward(3)
        with self.c:
            bot.change(self.c, 2, -100, 'task_budget', 'Second campaign')
            self.c.execute("INSERT INTO bot_tasks SELECT 'anothercampaign',owner,kind,title,description,url,NULL,reward,100,'active',created FROM bot_tasks WHERE id=%s", (tid,))
        self.send(3, action='take:anothercampaign')
        reply = self.forward(3)
        self.assertIn('уже получал', reply['text'])
        self.assertEqual(self.balance(3), 32)
        self.assertEqual(self.c.execute("SELECT remaining FROM bot_tasks WHERE id='anothercampaign'").fetchone()['remaining'], 100)
        self.invariant()
    def test_forwarded_admin_command_is_evidence_not_execution(self):
        before = self.balance(3)
        self.forward(1, text='/botcredit 3 100 forged-payment')
        self.assertEqual(self.balance(3), before)
    def test_post_published_after_moderation_with_money_button(self):
        tid = self.create_post_task()
        self.assertEqual(len(self.sent), 1)
        self.assertIn('paid post', self.sent[0]['text'])
        self.assertEqual(self.sent[0]['reply_markup']['inline_keyboard'][0][0]['callback_data'], 'bot:postclaim:' + tid)
        self.assertEqual(self.c.execute('SELECT status FROM bot_post_publications').fetchone()['status'], 'posted')
        self.assertIn('ChannelTest', str(self.send(3, action='list:post:0')))
        self.invariant()
    def test_post_claim_origin_budget_and_repeat_guards(self):
        tid = self.create_post_task()
        self.channel_claim(3, tid, mid=41)
        self.channel_claim(3, tid, chat=-10013)
        self.send(3, action='postclaim:' + tid)
        self.assertEqual(self.balance(3), 0)
        result = self.channel_claim(3, tid, event='replay')
        self.assertIn('Начислено', result['text'])
        self.channel_claim(3, tid, event='replay')
        self.channel_claim(3, tid)
        self.assertEqual(self.balance(3), 3)
        self.channel_claim(1, tid)
        self.send(4, '/start')
        self.channel_claim(4, tid)
        self.assertEqual(self.balance(4), 0)
        self.assertEqual(self.balance(1), 3)
        self.invariant()
    def test_post_claim_requires_account_and_owner_cannot_claim(self):
        tid = self.create_post_task()
        reply = self.channel_claim(4000, tid)
        self.assertIn('/start', reply['text'])
        self.channel_claim(2, tid)
        self.assertEqual(self.balance(2), 992)
        self.invariant()
    def test_uncertain_post_never_automatically_resent(self):
        self.send_failure = True
        tid = self.create_post_task()
        self.assertEqual(self.c.execute('SELECT status FROM bot_post_publications').fetchone()['status'], 'uncertain')
        self.send(1, '/botadmin')
        self.send(1, '/botadmin')
        self.assertEqual(len(self.sent), 1)
        reply = self.send(2, action='close:' + tid)
        self.assertIn('проверить результат', reply['text'])
    def test_daily_bonus_is_unconditional_and_once_per_kyiv_day(self):
        self.send(3, action='daily')
        self.send(3, action='daily')
        self.assertEqual(self.balance(3), 50)
        self.assertEqual(self.c.execute('SELECT amount FROM bot_cash_pool').fetchone()['amount'], 0)
        self.assertEqual(self.c.execute('SELECT count(*) AS n FROM bot_daily_claims').fetchone()['n'], 1)
        self.assertEqual(bot.liability(self.c), 50)
    def test_bonus_does_not_debit_advertiser_or_cash_pool(self):
        self.credit()
        self.configure_bonus('0.10')
        self.send(3, action='daily')
        self.assertEqual(self.balance(2), 1000)
        self.assertEqual(self.balance(3), 10)
        self.assertEqual(self.c.execute('SELECT amount FROM bot_cash_pool').fetchone()['amount'], 1000)
        self.assertEqual(bot.liability(self.c), 1010)
    def test_admin_can_disable_or_change_daily_without_funding(self):
        self.configure_bonus('0')
        self.send(3, action='daily')
        self.assertEqual(self.balance(3), 0)
        self.configure_bonus('1')
        self.send(3, action='daily')
        self.assertEqual(self.balance(3), 100)
    def test_daily_replay_and_next_day_by_kyiv_calendar(self):
        first = dt.datetime(2026,10,31,23,59,tzinfo=extra.ZoneInfo('Europe/Kyiv'))
        with patch('bot_extras.dt.datetime', wraps=dt.datetime) as clock:
            clock.now.return_value = first
            self.send(3, action='daily', event='daily-replay')
            self.send(3, action='daily', event='daily-replay')
            self.send(3, action='daily')
            self.assertEqual(self.balance(3),50)
            clock.now.return_value = first + dt.timedelta(minutes=2)
            self.send(3, action='daily')
            self.send(3, action='daily')
        self.assertEqual(self.balance(3),100)
        self.assertEqual(self.c.execute('SELECT count(*) AS n FROM bot_daily_claims').fetchone()['n'],2)
    def test_old_bonus_budget_is_ignored_and_removed_from_admin_screen(self):
        self.c.execute('UPDATE bot_settings SET budget=12345')
        self.c.raw.commit()
        self.send(3, action='daily')
        self.assertEqual(self.balance(3),50)
        self.assertEqual(bot.liability(self.c),50)
        self.assertEqual(self.c.execute('SELECT budget FROM bot_settings').fetchone()['budget'],12345)
        self.assertNotIn('бюджет',self.send(1,action='admin:bonus')['text'].lower())
        before=self.c.execute('SELECT daily FROM bot_settings').fetchone()['daily']
        self.send(1,'/botbonus 10 100')
        self.assertEqual(self.c.execute('SELECT daily FROM bot_settings').fetchone()['daily'],before)
    def test_daily_reward_can_be_reserved_for_manual_withdrawal(self):
        self.send(3,action='daily')
        self.send(3,action='withdraw')
        self.send(3,'0.50')
        self.send(3,'UA123456789 Daily recipient')
        self.send(3,action='confirm_payout')
        self.assertEqual(self.balance(3),0)
        payout=self.c.execute('SELECT amount,status FROM bot_payouts WHERE uid=3').fetchone()
        self.assertEqual((payout['amount'],payout['status']),(50,'pending'))
        self.assertEqual(bot.liability(self.c),50)
    def test_referral_after_paid_task_and_no_duplicate_claim(self):
        self.configure_bonus()
        self.send(4, '/start partner_1')
        self.assertEqual(self.balance(1), 0)
        tid = self.task()
        self.send(4, action='take:' + tid)
        self.joined = True
        self.send(4, action='check:' + tid)
        self.assertEqual(self.balance(1), 3)
        self.assertEqual(self.balance(4), 56)
        self.send(1, action='friends')
        self.send(1, action='friends')
        self.assertEqual(self.balance(1), 3)
        self.invariant()
    def test_bonus_commands_are_admin_only(self):
        self.send(3, '/botbonus 100')
        self.send(3, '/botchannel @ChannelTest')
        cfg = extra.settings(self.c)
        self.c.raw.commit()
        self.assertEqual(cfg['daily'], 50)
        self.assertIsNone(cfg['channel_id'])

if __name__ == '__main__':
    unittest.main()
