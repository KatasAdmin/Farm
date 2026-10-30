"""Exercise real wallet/task SQL on SQLite; PostgreSQL lock concurrency is separate."""
import json
import sqlite3
import unittest
from contextlib import contextmanager
import task_bot as bot


class Result:
    def __init__(self, cursor):
        self.cursor = cursor
    def convert(self, row):
        if row is None:
            return None
        row = dict(row)
        for key in ('data', 'response'):
            if key in row:
                row[key] = json.loads(row[key])
        return row
    def fetchone(self):
        return self.convert(self.cursor.fetchone())
    def fetchall(self):
        return [self.convert(row) for row in self.cursor.fetchall()]


class Database:
    def __init__(self):
        self.raw = sqlite3.connect(':memory:')
        self.raw.row_factory = sqlite3.Row
        self.depth = 0
    def execute(self, sql, params=()):
        if 'pg_advisory_xact_lock' in sql:
            sql, params = 'SELECT 1', ()
        params = tuple(json.dumps(p.obj) if isinstance(p, bot.Jsonb) else p for p in params)
        return Result(self.raw.execute(sql.replace('%s', '?').replace(' FOR UPDATE', ''), params))
    def __enter__(self):
        self.raw.execute('BEGIN')
        return self
    def __exit__(self, kind, value, tb):
        self.raw.rollback() if kind else self.raw.commit()
    @contextmanager
    def transaction(self):
        self.depth += 1
        name = 'nested' + str(self.depth)
        self.raw.execute('SAVEPOINT ' + name)
        try:
            yield self
        except Exception:
            self.raw.execute('ROLLBACK TO SAVEPOINT ' + name)
            raise
        finally:
            self.raw.execute('RELEASE SAVEPOINT ' + name)
            self.depth -= 1


class TaskBotTests(unittest.TestCase):
    def setUp(self):
        self.c = Database()
        bot.initialize(self.c)
        self.c.execute('CREATE TABLE players(id text,telegram_id bigint UNIQUE,coins int)')
        self.c.execute('CREATE TABLE support_tickets(id text,telegram_id bigint,nickname text,message text,created float)')
        self.c.execute('CREATE TABLE money_log(id text,player_id text,kind text,delta int,details text,created float)')
        self.c.raw.commit()
        self.serial = 0
        self.joined = False
        self.errors = False
        for uid in (1, 2, 3):
            self.send(uid, '/start')
    def api(self, method, args):
        if self.errors:
            raise RuntimeError('test network error')
        if method == 'getMe':
            return {'id': 99}
        if method == 'getChat':
            return {'id': -10012, 'type': 'channel', 'username': 'ChannelTest'}
        if method == 'getChatMember':
            return {'status': 'administrator' if args['user_id'] == 99 else ('member' if self.joined else 'left')}
        return True
    def send(self, uid, text='', action='', photo=False, event=None):
        if action in ('confirm_task', 'confirm_payout', 'admin:payconfirm'):
            current = bot.state(self.c, uid)
            action += ':' + (current['data'].get('nonce', 'expired') if current else 'expired')
        self.serial += 1
        message = {'message_id': self.serial, 'chat': {'id': uid, 'type': 'private'},
                   'from': {'id': uid, 'first_name': 'Test'}, 'text': text}
        if photo:
            message['photo'] = [{'file_id': 'test-photo-id'}]
        payload = {'message': message, 'update_id': self.serial}
        if action:
            payload = {'callback_query': {'id': str(event or self.serial), 'from': message['from'],
                       'message': message, 'data': 'bot:' + action}}
        elif event:
            message['message_id'] = event
        return bot.handle(payload, lambda: self.c, self.api, lambda u, c: u == 1)
    def balance(self, uid):
        return self.c.execute('SELECT available FROM bot_accounts WHERE uid=%s', (uid,)).fetchone()['available']
    def credit(self, uid=2, value='10', ref='payment001'):
        return self.send(1, f'/botcredit {uid} {value} {ref}')
    def task(self, kind='channel', count='2'):
        self.credit()
        self.send(2, action='new:' + kind)
        for text in ('Test task', 'Join the channel please', 'https://t.me/ChannelTest', '1', count):
            self.send(2, text)
        result = self.send(2, action='confirm_task')
        self.assertIn('ожидает модерации', result['text'])
        tid = self.c.execute('SELECT id FROM bot_tasks').fetchone()['id']
        self.send(1, action='admin:approve:' + tid)
        return tid
    def invariant(self):
        pool = self.c.execute('SELECT amount FROM bot_cash_pool').fetchone()['amount']
        self.assertGreaterEqual(pool, bot.liability(self.c))
    def test_menu_and_no_deferred_games(self):
        reply = self.send(3, '/start')
        self.assertEqual(reply['reply_markup']['keyboard'], bot.MENU)
        reply = self.send(3, '🎮 Игры')
        self.assertEqual(len(reply['reply_markup']['inline_keyboard']), 1)
        self.assertIn('🌾 Ферма', str(reply))
    def test_money_exact_and_invalid(self):
        self.assertEqual(bot.amount('0,50'), 50)
        self.assertEqual(bot.amount('12.34'), 1234)
        for raw in ('-1', '0', 'nan', '1e5', '0.001', '1000001', '1.234'):
            with self.assertRaises(bot.UserError):
                bot.amount(raw)
    def test_credit_role_and_reference_dedup(self):
        self.send(3, '/botcredit 3 100 hacked')
        self.assertEqual(self.balance(3), 0)
        self.credit()
        self.credit()
        self.assertEqual(self.balance(2), 1000)
        self.invariant()
    def test_channel_reward_only_after_membership_once(self):
        tid = self.task()
        self.send(3, action='check:' + tid)
        self.assertEqual(self.balance(3), 0)
        self.send(3, action='take:' + tid)
        self.send(3, action='check:' + tid)
        self.assertEqual(self.balance(3), 0)
        self.joined = True
        self.send(3, action='check:' + tid)
        self.send(3, action='check:' + tid)
        self.assertEqual(self.balance(3), 100)
        self.assertEqual(self.balance(2), 800)
        self.invariant()
    def test_old_member_cannot_take(self):
        tid = self.task()
        self.joined = True
        result = self.send(3, action='take:' + tid)
        self.assertIn('уже состоишь', result['text'])
        self.assertIsNone(self.c.execute('SELECT * FROM bot_claims').fetchone())
    def test_manual_proof_owner_review_and_close(self):
        tid = self.task('manual')
        self.send(3, action='take:' + tid)
        self.send(3, action='check:' + tid)
        self.send(3, 'Done', photo=True)
        result = self.send(2, action='close:' + tid)
        self.assertIn('Сначала проверь', result['text'])
        result = self.send(3, action=f'accept:{tid}:3')
        self.assertIn('другого', result['text'])
        self.assertEqual(self.balance(3), 0)
        self.send(2, action=f'accept:{tid}:3')
        self.assertEqual(self.balance(3), 100)
        self.send(2, action='close:' + tid)
        self.send(2, action='close:' + tid)
        self.assertEqual(self.balance(2), 900)
        self.invariant()
    def test_task_rejected_budget_returned_once(self):
        self.task()
        # Approved tasks cannot be rejected via stale moderation controls.
        tid = self.c.execute('SELECT id FROM bot_tasks').fetchone()['id']
        self.send(1, action='admin:rejecttask:' + tid)
        self.assertEqual(self.balance(2), 800)
        self.invariant()
    def test_withdrawal_reservation_confirmation_and_cancel(self):
        self.credit()
        self.send(2, action='withdraw')
        self.send(2, '5')
        self.send(2, 'UA123456789 Test User')
        self.assertEqual(self.balance(2), 1000)
        self.send(2, action='confirm_payout', event='same-confirm')
        self.send(2, action='confirm_payout', event='same-confirm')
        self.assertEqual(self.balance(2), 500)
        self.invariant()
        self.send(2, action='cancelpayout')
        self.send(2, action='cancelpayout')
        self.assertEqual(self.balance(2), 1000)
        self.invariant()
    def test_paid_requires_admin_and_confirmation(self):
        self.credit()
        for action, text in [('withdraw',''), ('','5'), ('','UA123456789 User'), ('confirm_payout','')]:
            self.send(2, text, action)
        pid = self.c.execute('SELECT id FROM bot_payouts').fetchone()['id']
        self.send(3, f'/botpaid {pid} bank123')
        self.send(1, f'/botpaid {pid} bank123')
        self.assertEqual(self.c.execute('SELECT status FROM bot_payouts').fetchone()['status'], 'pending')
        self.send(1, action='admin:payconfirm')
        self.send(1, action='admin:payconfirm')
        self.assertEqual(self.c.execute('SELECT status FROM bot_payouts').fetchone()['status'], 'paid')
        self.assertEqual(self.c.execute('SELECT amount FROM bot_cash_pool').fetchone()['amount'], 500)
        self.invariant()
    def test_farm_exchange_needs_reserve_and_conserves_value(self):
        self.c.execute("INSERT INTO players VALUES('p',3,20)")
        self.c.raw.commit()
        self.send(3, action='fromfarm')
        result = self.send(3, '5')
        self.assertIn('резерва', result['text'])
        self.assertEqual(self.balance(3), 0)
        self.send(1, '/botfund 10 reserve001')
        self.send(3, '5', event=7000)
        self.send(3, '5', event=7000)
        self.assertEqual(self.balance(3), 500)
        self.assertEqual(self.c.execute('SELECT coins FROM players').fetchone()['coins'], 15)
        self.send(3, action='tofarm')
        self.send(3, '3')
        self.assertEqual(self.balance(3), 200)
        self.assertEqual(self.c.execute('SELECT coins FROM players').fetchone()['coins'], 18)
        self.invariant()
    def test_error_rolls_back_claim_and_receipt_can_retry(self):
        tid = self.task()
        self.errors = True
        with self.assertRaises(RuntimeError):
            self.send(3, action='take:' + tid, event='network-error')
        self.assertIsNone(self.c.execute('SELECT * FROM bot_claims').fetchone())
        self.errors = False
        self.send(3, action='take:' + tid, event='network-error')
        self.assertEqual(self.c.execute('SELECT status FROM bot_claims').fetchone()['status'], 'started')
    def test_legacy_payment_and_link_handlers_preserved(self):
        self.assertIsNone(bot.handle({'pre_checkout_query': {'id': 1}}, lambda: self.c, self.api, lambda *_: False))
        self.assertIsNone(self.send(3, '/start link_secret'))
        self.assertIsNone(self.send(1, '/admin'))
        self.assertIsNone(self.send(3, '/paysupport'))
    def test_resolve_chat_rejects_external_urls(self):
        for url in ('http://t.me/hello', 'https://evil.test/foo', 'https://t.me/+secret', 'https://t.me/foo/bar'):
            with self.assertRaises(bot.UserError):
                bot.resolve_chat(self.api, url, 'channel')

if __name__ == '__main__':
    unittest.main()
