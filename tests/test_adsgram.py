import hashlib
import hmac
import importlib.util
import io
import json
import os
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit

from fastapi import HTTPException

import adsgram_ads as ads
import adsgram_bot
import main
import monetag_ads
import test_monetag_postgres
from test_monetag_rewards import AdFixture

STAGING = {'FARM_STAGING': '1', 'FARM_ADS_PROVIDER': 'adsgram', 'ADSGRAM_BLOCK_ID': '123'}
BOT_TOKEN = '123456:adsgram-unit-test-token'


@unittest.skipUnless(importlib.util.find_spec('httpx'), 'Install requirements-test.txt for API tests')
class AdsGramApiTests(AdFixture):
    def setUp(self):
        super().setUp()
        from fastapi.testclient import TestClient
        ads.initialize(self.c)
        self.c.raw.commit()
        self.client = TestClient(main.app)
        mocks = patch.multiple(main, db=lambda: self.c, person=self.person)
        mocks.start()
        self.addCleanup(mocks.stop)
        env = patch.dict(os.environ, {**STAGING, 'TELEGRAM_BOT_TOKEN': BOT_TOKEN})
        env.start()
        self.addCleanup(env.stop)

    def person(self, db, auth, lock=False):
        if auth != 'Bearer player':
            raise HTTPException(401, 'Login required')
        return self.p()

    def headers(self, telegram_id=7):
        fields = {'auth_date': str(int(time.time())), 'user': json.dumps({'id': telegram_id})}
        signed = '\n'.join(f'{k}={v}' for k, v in sorted(fields.items()))
        key = hmac.new(b'WebAppData', BOT_TOKEN.encode(), hashlib.sha256).digest()
        fields['hash'] = hmac.new(key, signed.encode(), hashlib.sha256).hexdigest()
        return {'Authorization': 'Bearer player', 'X-Telegram-Init-Data': urlencode(fields)}

    def test_staging_show_persists_telemetry_without_rewards(self):
        headers = self.headers()
        status = self.client.get('/api/ads/status', headers=headers).json()
        self.assertTrue(status['visible'])
        self.assertTrue(status['test_mode'])
        self.assertEqual(status['block_id'], '123')
        start = self.client.post('/api/ads/adsgram/start', headers=headers, json={'item': 'coins'})
        self.assertEqual(start.status_code, 200, start.text)
        payload = {**start.json(), 'result': 'completed'}
        for _ in range(2):
            reply = self.client.post('/api/ads/adsgram/finish', headers=headers, json=payload)
            self.assertEqual(reply.json(), {'ok': True, 'rewarded': False})
        restored = self.client.get('/api/ads/status', headers=headers).json()
        self.assertEqual(restored['history'][0]['state'], 'test_completed')
        self.assertEqual(restored['rewards']['coins']['confirmed'], 0)
        self.assertEqual(self.p()['coins'], 100)
        self.assertEqual(self.c.execute('SELECT count(*) AS n FROM monetag_reward_grants').fetchone()['n'], 0)
        self.assertIsNone(ads.statistics(self.c)['settled_revenue'])
        self.assertEqual(ads.statistics(self.c)['completed'], 1)

    def test_web_forged_and_mismatched_telegram_requests_are_rejected(self):
        path = '/api/ads/adsgram/start'
        data = {'item': 'grain'}
        good = self.headers()
        cases = [
            ({}, 401),
            ({'Authorization': 'Bearer player'}, 503),
            ({**good, 'X-Telegram-Init-Data': good['X-Telegram-Init-Data'] + '1'}, 401),
            (self.headers(8), 403),
        ]
        for headers, code in cases:
            self.assertEqual(self.client.post(path, headers=headers, json=data).status_code, code)
        self.assertEqual(self.client.get('/api/ads/adsgram/postback?userid=7').status_code, 404)
        self.assertEqual(ads.statistics(self.c)['starts'], 0)

    def test_provider_switch_and_production_guard(self):
        headers = self.headers()
        with patch.dict(os.environ, {'FARM_STAGING': '0'}):
            data = self.client.get('/api/ads/status', headers=headers).json()
            self.assertEqual(data['provider'], 'adsgram')
            self.assertFalse(data['enabled'])
            self.assertIsNone(data['block_id'])
        for provider in ('adsgram', 'disabled'):
            with patch.dict(os.environ, {'FARM_ADS_PROVIDER': provider}):
                result = self.client.post('/api/ads/monetag/prepare', headers=headers, json={'item': 'grain'})
                self.assertEqual(result.status_code, 503)
        with patch.dict(os.environ, {'FARM_ADS_PROVIDER': 'monetag'}):
            result = self.client.post('/api/ads/monetag/prepare', headers=headers, json={'item': 'grain'})
            self.assertEqual(result.status_code, 200, result.text)

    def test_expired_attempt_cannot_mutate_history_or_progress(self):
        with self.c:
            attempt = ads.start(self.c, self.p(), 'eggs', 'telegram', 10)
            result = ads.finish(self.c, self.p(), attempt['ymid'], 'completed', 'telegram', 10 + ads.ATTEMPT_TTL)
        self.assertFalse(result['rewarded'])
        self.assertEqual(ads.statistics(self.c)['completed'], 0)
        self.assertEqual(ads.statistics(self.c)['sdk_errors'], 1)

    def test_old_monetag_progress_visible_in_adsgram(self):
        a = self.prepare('eggs')
        self.assertTrue(self.post(a, request_var='eggs_reward')['rewarded'])
        status = self.client.get('/api/ads/status', headers=self.headers()).json()
        self.assertEqual(status['rewards']['eggs']['progress'], 1)
        self.assertEqual(status['history'][0]['state'], 'credited')


@unittest.skipUnless(os.getenv('TEST_DATABASE_URL'), 'Set TEST_DATABASE_URL to isolated local PostgreSQL')
class AdsGramPostgresTests(unittest.TestCase):
    def test_parallel_start_and_duplicate_finish(self):
        database = test_monetag_postgres.MonetagPostgres(methodName='test_duplicate_postbacks_and_claims_are_serialized')
        database.setUp()
        self.addCleanup(database.doCleanups)
        self.addCleanup(database.tearDown)
        with database.connect() as c:
            ads.initialize(c)
        now = time.time()

        def start(_):
            try:
                with database.connect() as c:
                    p = c.execute("SELECT * FROM players WHERE id='p' FOR UPDATE").fetchone()
                    return ads.start(c, p, 'coins', 'telegram', now)
            except HTTPException as error:
                self.assertEqual(error.status_code, 429)
                return None

        def finish(_):
            with database.connect() as c:
                p = c.execute("SELECT * FROM players WHERE id='p' FOR UPDATE").fetchone()
                return ads.finish(c, p, attempt['ymid'], 'completed', 'telegram', now + 1)

        with patch.dict(os.environ, STAGING), ThreadPoolExecutor(max_workers=6) as pool:
            attempts = [a for a in pool.map(start, range(12)) if a]
            self.assertEqual(len(attempts), 1)
            attempt = attempts[0]
            self.assertTrue(all(not r['rewarded'] for r in pool.map(finish, range(12))))
        with database.connect() as c:
            self.assertEqual(ads.statistics(c)['completed'], 1)
            self.assertEqual(c.execute("SELECT coins FROM players WHERE id='p'").fetchone()['coins'], 100)
            self.assertEqual(monetag_ads.statistics(c)['total']['credited'], 0)


class AdsGramBotTests(unittest.TestCase):
    def test_chat_ad_has_separate_claim_and_protected_content(self):
        ad = {
            'text_html': '<b>Тест</b>', 'click_url': 'https://api.adsgram.ai/short/ad',
            'button_name': 'Open', 'reward_url': 'https://api.adsgram.ai/short/reward',
            'button_reward_name': 'Claim',
        }

        def fetch(url, timeout):
            parsed = urlsplit(url)
            self.assertEqual((parsed.netloc, parsed.path), ('api.adsgram.ai', '/advbot'))
            self.assertEqual(parse_qs(parsed.query)['blockid'], ['123'])
            return io.BytesIO(json.dumps(ad).encode())

        result = adsgram_bot.chat_ad(7, 'bot-123', 'ru', 'test-token', fetch=fetch)
        self.assertTrue(result['protect_content'])
        self.assertEqual(result['chat_id'], 7)
        self.assertEqual(result['reply_markup']['inline_keyboard'][1][0]['url'], ad['reward_url'])
        ad['reward_url'] = 'https://untrusted.invalid/reward'
        self.assertIsNone(adsgram_bot.chat_ad(7, 'bot-123', 'ru', 'test-token', fetch=fetch))
