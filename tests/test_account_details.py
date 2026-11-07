import unittest
from unittest.mock import patch
import task_bot as bot
import bot_account_details as details
import test_task_bot as base
from test_continuous_production import farm


class AccountDetailsTests(unittest.TestCase):
    setUp=base.TaskBotTests.setUp
    api=base.TaskBotTests.api
    send=base.TaskBotTests.send

    def prepare_farm(self):
        p=dict(farm(84,grain=1000),name='Фермер 84',telegram_id=2,coop_level=9,storage_level=50,geese=0,fed_geese=0,feathers=0,feather_progress=0,created_at=100000)
        columns={r[1] for r in self.c.raw.execute('PRAGMA table_info(players)')}
        for key,value in p.items():
            if key not in columns:self.c.execute('ALTER TABLE players ADD COLUMN '+key+(' text' if isinstance(value,str) else ' integer' if isinstance(value,int) else ' real'))
        keys=list(p)
        self.c.execute('INSERT INTO players('+','.join(keys)+') VALUES('+','.join(['%s']*len(keys))+')',tuple(p.values()))
        for sql in [
          'CREATE TABLE IF NOT EXISTS market(id text,seller text,item text,quantity int,price int)',
          'CREATE TABLE IF NOT EXISTS farm_events(id text,player_id text,kind text,amount int,created real)',
          'CREATE TABLE IF NOT EXISTS star_orders(id text,player_id text,telegram_id bigint,coins int,stars int,status text,created real)',
          'CREATE TABLE IF NOT EXISTS incubation_jobs(id text,player_id text,started real,hatch_at real,mature_at real)',
          'CREATE TABLE IF NOT EXISTS market_trade_audit(id text,buyer_id text,seller_id text,item text,quantity int,coins int,created real)']:
            self.c.execute(sql)
        self.c.raw.commit()
        return p

    def test_all_sections_are_button_accessible_and_empty_pages_work(self):
        self.prepare_farm()
        overview=str(self.send(1,action='admin:account:2'))
        for section in details.TITLES:
            self.assertIn('bot:admin:accountdetail:'+section+':2:0',overview)
            with patch.object(details.time,'time',return_value=100000):r=self.send(1,action='admin:accountdetail:'+section+':2:0')
            self.assertIn(details.TITLES[section],r['text'])
            self.assertLessEqual(len(r['text']),4096)
            self.assertIn('bot:admin:account:2',str(r))

    def test_84_hens_rate_actual_forecast_and_readonly_snapshot(self):
        p=self.prepare_farm()
        before=dict(self.c.execute('SELECT * FROM players WHERE telegram_id=2').fetchone())
        with patch.object(details.time,'time',return_value=100000):r=self.send(1,action='admin:accountdetail:farm:2:0')
        text=r['text'];self.assertIn('14 яиц/ч',text);self.assertIn('84 за 6 ч',text);self.assertIn('336 за сутки',text)
        self.assertIn('84 / 90',text);self.assertIn('00:04:18',text)
        after=dict(self.c.execute('SELECT * FROM players WHERE telegram_id=2').fetchone())
        self.assertEqual(before,after)
        self.assertEqual(self.c.execute('SELECT count(*) AS n FROM money_log').fetchone()['n'],0)
        p.update(grain=0,eggs=99,storage_level=1)
        q,f=details.farm_preview(p,100000)
        self.assertEqual(f['eggs_next_6h'],1)
        self.assertEqual(p['eggs'],99)

    def test_all_paid_and_cancelled_payouts_paginate_and_link(self):
        self.prepare_farm()
        for i in range(5):self.c.execute("INSERT INTO bot_payouts(id,uid,amount,destination,status,reference,created) VALUES(%s,2,500,%s,%s,%s,%s)",(str(i),'Карта <recipient>','paid' if i%2 else 'cancelled','ref-'+str(i),100+i))
        self.c.raw.commit()
        r=self.send(1,action='admin:accountdetail:payouts:2:0')
        self.assertIn('bot:admin:accountdetail:payouts:2:1',str(r))
        self.assertIn('Карта &lt;recipient&gt;',r['text'])
        s=self.send(1,action='admin:accountdetail:payouts:2:1')
        for i in (0,1):self.assertIn('bot:admin:payview:'+str(i),str(s))

    def test_nonowner_cannot_read_dossier_or_identifiers(self):
        self.prepare_farm()
        for section in details.TITLES:
            r=self.send(3,action='admin:accountdetail:'+section+':2:0')
            self.assertIn('Доступ',r['text']);self.assertNotIn('Фермер 84',r['text'])
        self.assertIn('Неизвестная страница',self.send(1,action='admin:accountdetail:nope:2:0')['text'])
        self.assertIn('Неизвестная страница',self.send(1,action='admin:accountdetail:farm:2:-1')['text'])

    def test_find_player_by_farm_nickname_id_and_flock_without_commands(self):
        self.prepare_farm()
        self.c.execute("UPDATE players SET name='Farmer 84' WHERE telegram_id=2");self.c.raw.commit()
        for query in ('Farmer 84','farmer'):
            self.send(1,action='admin:accountsearch')
            self.assertIn('bot:admin:account:2',str(self.send(1,query)))
        r=self.send(1,action='admin:accountflock:0')
        self.assertIn('84 птиц',str(r))
        self.assertIn('bot:admin:account:2',str(r))
        self.assertIn('Доступ',self.send(3,action='admin:accountflock:0')['text'])
