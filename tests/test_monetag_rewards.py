"""No real ads, credentials or production writes. Exercise real reward SQL and API."""
import os
import asyncio
import importlib.util
import sqlite3
import time
import unittest
from unittest.mock import patch
from fastapi import HTTPException
import monetag_ads as ads
import ad_inventory
import main
from test_task_bot import Database

SECRET='test-postback-secret-not-a-real-key-1234'

class AdDB(Database):
 def __init__(self):
  super().__init__();self.raw.close();self.raw=sqlite3.connect(':memory:',check_same_thread=False);self.raw.row_factory=sqlite3.Row
 def execute(self,sql,params=()):return super().execute(sql.replace('::int',''),params)

def schema(c):
 c.execute('CREATE TABLE players(id text PRIMARY KEY,telegram_id bigint,coins int,grain int,eggs int,milk int,feathers int,chickens int,fed_hens int,geese int,coop_level int,storage_level int)')
 c.execute("INSERT INTO players VALUES('p',7,100,0,0,0,0,0,0,0,1,1)")
 c.execute("INSERT INTO players VALUES('other',8,100,0,0,0,0,0,0,0,1,1)")
 for key in ad_inventory.INTS:c.execute('ALTER TABLE players ADD COLUMN '+key+' integer NOT NULL DEFAULT '+('1' if key=='ad_stock_version' else '0'))
 for key in ad_inventory.FLOATS:c.execute('ALTER TABLE players ADD COLUMN '+key+' double precision NOT NULL DEFAULT 0')
 c.execute('CREATE TABLE farm_ad_money(log_id text PRIMARY KEY,amount integer)')
 c.execute('CREATE TABLE farm_ad_listings(id text PRIMARY KEY,quantity integer)')
 c.execute('CREATE TABLE farm_ad_incubations(id text PRIMARY KEY)')
 for key,default in (('cows',0),('fed_cows',0),('fed_geese',0),('cowshed_level',1),('farmer_level',3)):
  c.execute('ALTER TABLE players ADD COLUMN '+key+' integer NOT NULL DEFAULT '+str(default))
 c.execute('CREATE TABLE money_log(id text PRIMARY KEY,player_id text,kind text,delta int,details text,created double precision)')
 c.execute('CREATE TABLE reward_emission(id int PRIMARY KEY,total_minted int)')
 c.execute('INSERT INTO reward_emission VALUES(1,0)')
 c.execute('CREATE TABLE farm_money_sources(log_id text PRIMARY KEY,bonus int,purchased int,earned int)')
 c.execute('CREATE TABLE monetag_ad_attempts(ymid text PRIMARY KEY,player_id text,created_at double precision,rewarded_at double precision,zone_id int,placement text,'+','.join(k+' '+v for k,v in ads.FIELDS.items())+')')
 c.execute('CREATE TABLE monetag_reward_grants(id text PRIMARY KEY,player_id text,item text,quantity int,created real,claimed_at real)')
 c.execute('CREATE TABLE monetag_postback_events(ymid text,event_type text,sub_zone_id int,reward_event_type text,estimated_usd numeric,received_at real,PRIMARY KEY(ymid,event_type,sub_zone_id,reward_event_type))')

class AdFixture(unittest.TestCase):
 def setUp(self):
  self.c=AdDB();schema(self.c);self.c.raw.commit();self.env=patch.dict(os.environ,{'MONETAG_POSTBACK_SECRET':SECRET,'MONETAG_REWARDS_ENABLED':'1','MONETAG_WEB_ZONE_ID':'22334455','MONETAG_WEB_REWARDED_ENABLED':'1'});self.env.start();self.addCleanup(self.env.stop)
  self.now=time.time()
 def p(self,pid='p'):return self.c.execute('SELECT * FROM players WHERE id=%s',(pid,)).fetchone()
 def prepare(self,item='grain',platform='telegram',now=None):
  with self.c:return ads.prepare(self.c,self.p(),item,platform,self.now if now is None else now)
 def report(self,a,event='completed',**kw):
  with self.c:return ads.report(self.c,self.p(),a['ymid'],event,now=self.now,**kw)
 def post(self,a,**changes):
  args=dict(secret=SECRET,ymid=a['ymid'],zone_id=a['zone_id'],sub_zone_id=999,event_type='impression',reward_event_type='valued',request_var=str(a['zone_id'])+'_grain_reward',telegram_id='7',estimated_price='0.0037000',now=self.now)
  args.update(changes)
  with self.c:return ads.postback(self.c,**args)
 def deliver(self):
  with self.c:return ads.deliver(self.c,self.p(),lambda c,p:p,lambda p:10*p['coop_level'],lambda p:100*p['storage_level'])

class MonetagRewardsTests(AdFixture):
 def test_popup_subzone_and_prefixed_placement_are_valid_and_duplicate_safe(self):
  a=self.prepare();self.assertTrue(self.post(a)['rewarded']);self.assertFalse(self.post(a)['rewarded'])
  self.assertEqual(self.deliver()['granted'],[{'item':'grain','quantity':1}]);self.assertEqual(self.deliver()['granted'],[])
  self.assertEqual((self.p()['grain'],self.p()['coins']),(1,100))
  self.assertEqual(self.c.execute('SELECT count(*) AS n FROM monetag_postback_events').fetchone()['n'],1)
  s=ads.statistics(self.c);self.assertEqual(s['estimated_usd'],'0.0037');self.assertIsNone(s['settled_revenue'])
 def test_sdk_valued_completion_never_credits_without_postback(self):
  a=self.prepare();self.report(a,result='valued');self.assertEqual(self.deliver()['granted'],[])
  self.assertEqual(ads.status(self.c,self.p(),'telegram',self.now)['rewards']['grain']['progress'],0)
  self.assertEqual(self.p()['grain'],0)
 def test_unpaid_and_missing_confirmation_have_finite_history_states(self):
  a=self.prepare();self.report(a,result='valued')
  s=ads.status(self.c,self.p(),'telegram',self.now+121);self.assertEqual(s['history'][0]['state'],'unconfirmed')
  self.post(a,reward_event_type='non_valued',estimated_price='0')
  self.assertEqual(ads.status(self.c,self.p(),'telegram',self.now)['history'][0]['state'],'credited')
  self.assertEqual(self.deliver()['granted'],[{'item':'grain','quantity':1}])
  self.assertFalse(self.post(a)['rewarded'])
 def test_undefined_sdk_result_does_not_wait_forever(self):
  a=self.prepare();self.report(a)
  self.assertEqual(ads.status(self.c,self.p(),'telegram',self.now)['history'][0]['state'],'unconfirmed')
 def test_bad_secret_zone_placement_and_account_are_rejected(self):
  a=self.prepare()
  for changes in ({'secret':'wrong'},{'zone_id':456},{'request_var':'milk_reward'},{'telegram_id':'999'}):
   with self.subTest(changes=changes),self.assertRaises(HTTPException):self.post(a,**changes)
  self.assertEqual(self.c.execute('SELECT count(*) AS n FROM monetag_postback_events').fetchone()['n'],0)
 def test_click_and_multiple_subzones_never_duplicate_reward_or_revenue(self):
  a=self.prepare();self.post(a,event_type='click');self.assertEqual(self.deliver()['granted'],[{'item':'grain','quantity':1}])
  self.post(a);self.post(a,sub_zone_id=1000);self.deliver()
  self.assertEqual(self.p()['grain'],1)
  self.assertEqual(ads.statistics(self.c)['estimated_usd'],'0.0037')
 def test_progress_is_persistent_and_shared_between_platforms(self):
  a=self.prepare('eggs');self.post(a,request_var='eggs_reward')
  s=ads.status(self.c,self.p(),'web',self.now);self.assertEqual(s['rewards']['eggs']['progress'],1)
  b=self.prepare('eggs','web',self.now+31);self.post(b,request_var='22334455_eggs_reward',now=self.now+31)
  self.assertEqual(self.deliver()['granted'],[{'item':'eggs','quantity':2}])
  self.assertEqual(ads.status(self.c,self.p(),'telegram',self.now+31)['rewards']['eggs']['progress'],0)
 def test_stock_capacity_defers_instead_of_losing_or_overflowing_rewards(self):
  a=self.prepare();self.post(a)
  self.c.execute("UPDATE players SET milk=100 WHERE id='p'");self.c.raw.commit()
  self.assertEqual(self.deliver()['pending'],1);self.assertEqual(self.p()['grain'],0)
  self.c.execute("UPDATE players SET milk=99 WHERE id='p'");self.c.raw.commit();self.deliver();self.assertEqual(self.p()['grain'],1)
 def test_all_thresholds_and_animal_housing_and_fed_state(self):
  for item,(views,qty) in ads.REWARDS.items():
   for i in range(views):
    # At most 10 per hour; spread genuine mock impressions in test time.
    self.now+=4000
    a=self.prepare(item,now=self.now);self.post(a,request_var=item+'_reward')
    pending=self.c.execute('SELECT count(*) AS n FROM monetag_reward_grants WHERE item=%s',(item,)).fetchone()['n']
    self.assertEqual(pending,int(i+1==views))
   self.deliver();self.assertEqual(self.p()[item],100+qty if item=='coins' else qty)
  self.assertEqual(self.p()['fed_hens'],1);self.assertEqual(self.p()['coins'],102)
 def test_deliver_catches_up_before_adding_hen_and_preserves_full_coop(self):
  self.c.execute("INSERT INTO monetag_reward_grants VALUES('hen','p','chickens',1,1,NULL)")
  self.c.execute("UPDATE players SET geese=10 WHERE id='p'");self.c.raw.commit()
  self.assertEqual(self.deliver()['pending'],1)
  self.c.execute("UPDATE players SET geese=0 WHERE id='p'");self.c.raw.commit();seen=[]
  def advance(c,p):seen.append(p['chickens']);return p
  with self.c:ads.deliver(self.c,self.p(),advance,lambda p:10,lambda p:100)
  self.assertEqual(seen,[0]);self.assertEqual((self.p()['chickens'],self.p()['fed_hens']),(1,1))
 def test_attempt_rate_cooldown_and_reservation_idempotency(self):
  a=self.prepare();b=self.prepare();self.assertEqual(a['ymid'],b['ymid'])
  self.report(a,event='started')
  for i in range(1,5):
   attempt=self.prepare(now=self.now+i)
   ads.report(self.c,self.p(),attempt['ymid'],'started',now=self.now+i)
  with self.assertRaises(HTTPException):self.prepare(now=self.now+5)
  self.assertNotEqual(self.prepare(now=self.now+35)['ymid'],a['ymid'])
 def test_daily_cap_cannot_be_bypassed_by_a_forged_callback(self):
  for i in range(ads.DAY_LIMIT):
   self.c.execute('INSERT INTO monetag_ad_attempts(ymid,player_id,created_at,launched_at,zone_id,placement) VALUES(%s,%s,%s,%s,%s,%s)',('old'+str(i),'p',self.now-60,self.now-60,ads.TMA_ZONE,'grain_reward'))
  self.c.raw.commit()
  with self.assertRaises(HTTPException):self.prepare()
 def test_reports_cannot_mutate_another_account_attempt(self):
  a=self.prepare()
  with self.c:
   with self.assertRaises(HTTPException):ads.report(self.c,self.p('other'),a['ymid'],'completed',result='valued',now=self.now)
  self.assertIsNone(self.c.execute('SELECT sdk_completed_at FROM monetag_ad_attempts WHERE ymid=%s',(a['ymid'],)).fetchone()['sdk_completed_at'])
 def test_late_postback_after_ui_timeout_is_still_credited_once(self):
  a=self.prepare();self.report(a,event='failed',error='verification_failed')
  self.assertTrue(self.post(a,now=self.now+37*3600)['rewarded']);self.deliver();self.assertEqual(self.p()['grain'],1)
 def test_nan_negative_and_unbounded_prices_rejected(self):
  a=self.prepare()
  for price in ('NaN','Infinity','-1','1001','1'*100):
   with self.assertRaises(HTTPException):self.post(a,estimated_price=price)
 def test_web_zone_never_silently_reuses_tma_zone(self):
  with patch.dict(os.environ,{'MONETAG_WEB_ZONE_ID':'','MONETAG_WEB_REWARDED_ENABLED':'0'}):
   self.assertFalse(ads.config('web')['enabled'])
   with self.assertRaises(HTTPException):self.prepare(platform='web')
 def test_delivery_rolls_back_if_recording_claim_fails(self):
  a=self.prepare();self.post(a);execute=self.c.execute
  def fail(sql,params=()):
   if sql.startswith('UPDATE monetag_reward_grants SET'):raise RuntimeError('storage failure')
   return execute(sql,params)
  with patch.object(self.c,'execute',side_effect=fail):
   with self.assertRaises(RuntimeError):self.deliver()
  self.assertEqual(self.p()['grain'],0);self.assertEqual(self.deliver()['granted'],[{'item':'grain','quantity':1}])

class ExpandedAdvertisingRewards(AdFixture):
 def test_goods_value_is_between_one_and_three_game_coins_per_paid_event(self):
  prices={'grain':2,'eggs':1,'milk':11,'chickens':40,'geese':160,'cows':500,'coins':1}
  self.assertNotIn('feathers',ads.REWARDS)
  for item,(views,qty) in ads.REWARDS.items():
   self.assertGreaterEqual(prices[item]*qty/views,1);self.assertLessEqual(prices[item]*qty/views,3)
 def test_credit_is_bonus_tagged_and_idempotent_without_storage_requirement(self):
  import farm_wallet
  import ad_inventory
  a=self.prepare('coins');self.post(a,request_var='coins_reward');self.deliver();self.deliver()
  self.assertEqual(self.p()['coins'],102)
  self.assertEqual(farm_wallet.available(self.c,self.p()),0)
  self.assertEqual(ad_inventory.balance(self.c,self.p()),2)
  self.assertEqual(self.c.execute('SELECT total_minted FROM reward_emission WHERE id=1').fetchone()['total_minted'],2)
 def test_new_animal_grants_wait_for_housing_or_required_level(self):
  self.c.execute("INSERT INTO monetag_reward_grants VALUES('cow','p','cows',1,1,NULL)")
  self.c.execute("INSERT INTO monetag_reward_grants VALUES('goose','p','geese',1,2,NULL)")
  self.c.execute("UPDATE players SET cows=2,farmer_level=1 WHERE id='p'");self.c.raw.commit()
  self.assertEqual(self.deliver()['pending'],2)
  with self.assertRaises(HTTPException):self.prepare('geese')
  self.c.execute("UPDATE players SET cowshed_level=2,farmer_level=3 WHERE id='p'");self.c.raw.commit()
  self.assertEqual(len(self.deliver()['granted']),2)
  self.assertEqual((self.p()['ad_cows'],self.p()['ad_geese'],self.p()['fed_cows'],self.p()['fed_geese']),(1,1,1,1))

class UnpaidImpressionRewards(AdFixture):
 def test_unpaid_impression_earns_goods_once_but_never_counts_as_paid_income(self):
  a=self.prepare();self.assertTrue(self.post(a,reward_event_type='non_valued',estimated_price='0')['rewarded'])
  self.assertFalse(self.post(a,reward_event_type='non_valued',estimated_price='0')['rewarded'])
  self.deliver();self.deliver();self.assertEqual(self.p()['grain'],1)
  stats=ads.statistics(self.c);self.assertEqual((stats['total']['credited'],stats['total']['paid'],stats['total']['unpaid']),(1,0,1));self.assertIsNone(stats['estimated_usd'])
  self.assertFalse(self.post(a)['rewarded']);self.deliver();self.assertEqual(self.p()['grain'],1)
  self.assertEqual(ads.statistics(self.c)['total']['paid'],1)
 def test_unpaid_click_is_not_a_view_and_sdk_cannot_forge_a_reward(self):
  a=self.prepare();self.post(a,event_type='click',reward_event_type='non_valued',estimated_price='0')
  self.report(a,result='non_valued');self.assertEqual(self.deliver()['granted'],[])
  self.assertEqual(ads.statistics(self.c)['total']['paid'],0)
 def test_unpaid_views_keep_threshold_progress_across_reload(self):
  for i in range(2):
   self.now+=4000;a=self.prepare('eggs');self.post(a,request_var='eggs_reward',reward_event_type='non_valued',estimated_price='0')
   self.assertEqual(ads.status(self.c,self.p(),'telegram',self.now)['rewards']['eggs']['progress'],(i+1)%2)
  self.deliver();self.assertEqual(self.p()['eggs'],2)

@unittest.skipUnless(importlib.util.find_spec('httpx'),'Install requirements-test.txt for API tests')
class AdsApiTests(AdFixture):
 def setUp(self):
  super().setUp()
  from fastapi.testclient import TestClient
  self.client=TestClient(main.app)
  def person(c,auth,lock=False):
   if auth!='Bearer test-user':raise HTTPException(401,'Login required')
   return self.p()
  self.mocks=patch.multiple(main,db=lambda:self.c,person=person,advance=lambda c,p:p)
  self.mocks.start();self.addCleanup(self.mocks.stop)
 def test_http_authorization_and_callback_secret_redaction(self):
  self.assertEqual(self.client.post('/api/ads/monetag/prepare',json={'item':'grain'}).status_code,401)
  a=self.prepare()
  params=dict(secret=SECRET,ymid=a['ymid'],zone_id=ads.TMA_ZONE,sub_zone_id=444,event_type='impression',reward_event_type='valued',request_var=str(ads.TMA_ZONE)+'_grain_reward',estimated_price='0.01')
  response=self.client.get('/api/ads/monetag/postback',params=params)
  self.assertEqual(response.status_code,200,response.text)
  self.assertEqual(self.p()['grain'],1)
  self.assertEqual(self.client.get('/api/ads/monetag/postback',params={**params,'secret':'wrong'}).status_code,403)
 def test_http_web_prepare_and_claim_recover_after_reload(self):
  response=self.client.post('/api/ads/monetag/prepare',headers={'Authorization':'Bearer test-user'},json={'item':'grain'})
  self.assertEqual(response.status_code,200,response.text);a=response.json();self.assertEqual(a['zone_id'],22334455)
  self.post(a,request_var='grain_reward');response=self.client.get('/api/ads/monetag/status',headers={'Authorization':'Bearer test-user'})
  self.assertEqual(response.status_code,200,response.text);self.assertEqual(self.p()['grain'],1)
  self.client.get('/api/ads/monetag/status',headers={'Authorization':'Bearer test-user'});self.assertEqual(self.p()['grain'],1)
 def test_admin_ads_requires_owner(self):
  self.assertEqual(self.client.get('/api/admin/ads').status_code,403)

class PostbackRedactionTests(unittest.TestCase):
 def test_secret_removed_before_downstream_access_logging_and_duplicates_rejected(self):
  seen=[]
  async def downstream(scope,receive,send):seen.append(scope)
  app=main.PostbackSecretRedaction(downstream)
  for query in (b'secret=private-test-key&ymid=abc',b'secret=first&secret=second&ymid=abc'):
   scope={'type':'http','path':'/api/ads/monetag/postback','query_string':query}
   asyncio.run(app(scope,None,None))
  self.assertEqual(seen[0]['query_string'],b'ymid=abc')
  self.assertEqual(seen[0]['state']['monetag_secret'],'private-test-key')
  self.assertEqual(seen[1]['query_string'],b'ymid=abc')
  self.assertEqual(seen[1]['state']['monetag_secret'],'')
