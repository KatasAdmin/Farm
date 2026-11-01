import time
import unittest
from unittest.mock import patch
import main
import farm_wallet
import farm_expansion as feature
from test_task_bot import Database

class ExpansionTests(unittest.TestCase):
 def setUp(self):
  class C(Database):
   def execute(self,sql,args=()):return super().execute(sql.replace('::int','').replace('::bigint',''),args)
  self.c=C();c=self.c
  cols=dict(id='p',telegram_id=7,coins=0,chickens=0,geese=0,cows=0,fed_hens=0,fed_geese=0,fed_cows=0,eggs=0,grain=0,milk=0,feathers=0,coop_level=1,cowshed_level=1,storage_level=1,farmer_level=3)
  c.execute('CREATE TABLE players('+','.join(k+(' text PRIMARY KEY' if k=='id' else ' int') for k in cols)+')')
  c.execute('INSERT INTO players VALUES('+','.join('%s' for k in cols)+')',tuple(cols.values()))
  c.execute('CREATE TABLE referrals(child_id text,parent_id text)')
  fields=[name for pair in feature.REFERRAL_FIELDS.values() for name in pair]
  c.execute('CREATE TABLE referral_rewards(player_id text PRIMARY KEY,'+','.join(name+' bigint DEFAULT 0' for name in fields)+')')
  c.execute("INSERT INTO referral_rewards(player_id) VALUES('p')")
  c.execute('CREATE TABLE farm_events(id text,player_id text,kind text,amount int,created real)')
  c.execute('CREATE TABLE daily_claims(player_id text,day text,claim text,amount int,PRIMARY KEY(player_id,day,claim))')
  c.execute('CREATE TABLE weekly_claims(player_id text,week text,claimed_at real,amount int,PRIMARY KEY(player_id,week))')
  c.execute('CREATE TABLE daily_activity(player_id text,day text,grain_bought int,eggs_produced int,eggs_listed int)')
  c.execute('CREATE TABLE reward_emission(id int,total_minted int)');c.execute('INSERT INTO reward_emission VALUES(1,0)')
  c.execute('CREATE TABLE money_log(id text,player_id text,kind text,delta int,details text,created real)')
  farm_wallet.initialize_sources(c);c.raw.commit()
 def p(self):return self.c.execute("SELECT * FROM players WHERE id='p'").fetchone()
 def context(self):
  return patch.multiple(main,db=lambda:self.c,person=lambda *a:self.p(),advance=lambda c,p:p)
 def event(self,kind,n=1,at=None,pid='p'):
  self.c.execute('INSERT INTO farm_events VALUES(%s,%s,%s,%s,%s)',(kind+str(time.time()),pid,kind,n,at if at is not None else time.time()));self.c.raw.commit()
 def grant(self,item,n):
  field=feature.REFERRAL_FIELDS[item][0]
  self.c.execute('UPDATE referral_rewards SET '+field+'=%s WHERE player_id=%s',(n,'p'));self.c.raw.commit()
 def test_all_seven_resources_preserve_fraction_and_never_credit_coins(self):
  for item in feature.REFERRAL_FIELDS:
   self.grant(item,25000)
   data=feature.resources(self.c.execute("SELECT * FROM referral_rewards WHERE player_id='p'").fetchone())[item]
   self.assertEqual(data,{'available':2,'fraction':5000,'total':2})
   with self.context():
    self.assertEqual(main.referral_claim(main.Request(item=item),'Bearer p')['amount'],2)
    with self.assertRaises(main.HTTPException):main.referral_claim(main.Request(item=item),'Bearer p')
  p=self.p();self.assertEqual(p['coins'],0)
  for k in ('fed_hens','fed_geese','fed_cows'):self.assertEqual(p[k],2)
 def test_cow_capacity_partial_claim_keeps_unclaimed_balance(self):
  self.grant('cows',50000)
  with self.context():
   self.assertEqual(main.referral_claim(main.Request(item='cows'),'')['amount'],2)
   with self.assertRaises(main.HTTPException):main.referral_claim(main.Request(item='cows'),'')
  row=self.c.execute("SELECT * FROM referral_rewards WHERE player_id='p'").fetchone()
  self.assertEqual(feature.resources(row)['cows']['available'],3)
 def test_milk_and_feathers_share_warehouse_with_all_other_resources(self):
  self.c.execute("UPDATE players SET grain=98,milk=1 WHERE id='p'");self.grant('feathers',30000)
  with self.context():self.assertEqual(main.referral_claim(main.Request(item='feathers'),'')['amount'],1)
  self.assertEqual(self.p()['feathers'],1)
  self.grant('milk',10000)
  with self.context():
   with self.assertRaises(main.HTTPException):main.referral_claim(main.Request(item='milk'),'')
 def test_goose_level_gate_and_advance_before_adding_animals(self):
  self.grant('geese',10000);self.c.execute("UPDATE players SET farmer_level=1 WHERE id='p'");self.c.raw.commit()
  with self.context():
   with self.assertRaises(main.HTTPException):main.referral_claim(main.Request(item='geese'),'')
  self.c.execute("UPDATE players SET farmer_level=3 WHERE id='p'");self.c.raw.commit()
  seen=[]
  def catchup(c,p):seen.append(p['geese']);return p
  with self.context(),patch.object(main,'advance',side_effect=catchup):main.referral_claim(main.Request(item='geese'),'')
  self.assertEqual(seen,[0]);self.assertEqual(self.p()['geese'],1)
 def test_new_resource_fractional_commissions_are_exact_through_seven_levels(self):
  for i in range(8):self.c.execute('INSERT INTO referrals VALUES(%s,%s)',('child' if i==0 else str(i),str(i+1)))
  self.c.raw.commit()
  for item in ('cows','geese','milk','feathers'):
   main.award_referral_resource(self.c,{'id':'child','telegram_id':7},item,1)
   field=feature.REFERRAL_FIELDS[item][0]
   for i,rate in enumerate(main.REFERRAL_RATES,1):
    self.assertEqual(self.c.execute('SELECT '+field+' AS n FROM referral_rewards WHERE player_id=%s',(str(i),)).fetchone()['n'],rate)
   self.assertIsNone(self.c.execute("SELECT * FROM referral_rewards WHERE player_id='8'").fetchone())
 def test_claimed_resources_do_not_immediately_pay_upline(self):
  self.c.execute("INSERT INTO referrals VALUES('p','parent')");self.grant('cows',10000)
  with self.context():main.referral_claim(main.Request(item='cows'),'')
  self.assertIsNone(self.c.execute("SELECT * FROM referral_rewards WHERE player_id='parent'").fetchone())
 def test_only_organic_today_events_unlock_new_daily_tasks_once(self):
  for key,(kind,target) in feature.EXTRA_MISSIONS.items():
   self.event('referral_milk',100);self.event(kind,1,at=time.time()//86400*86400-1);self.event(kind,1,pid='other')
   with self.context():
    with self.assertRaises(main.HTTPException):main.claim_reward(main.Request(item=key),'')
   self.event(kind)
   with self.context():
    self.assertEqual(main.claim_reward(main.Request(item=key),'')['awarded'],1)
    with self.assertRaises(main.HTTPException):main.claim_reward(main.Request(item=key),'')
  self.assertEqual(self.p()['coins'],3)
  self.assertEqual(farm_wallet.available(self.c,self.p()),0)
 def test_milk_can_complete_weekly_production_and_listing_without_eggs(self):
  self.c.execute('INSERT INTO daily_activity VALUES(%s,%s,10,0,0)',('p',time.strftime('%Y-%m-%d',time.gmtime())))
  self.event('milk_produced',3);self.event('milk_listed',3)
  with self.context():
   self.assertEqual(main.claim_weekly('')['awarded'],30)
   with self.assertRaises(main.HTTPException):main.claim_weekly('')
  self.assertEqual(self.p()['coins'],30);self.assertEqual(farm_wallet.available(self.c,self.p()),0)
 def test_achievements_require_actual_production_not_bought_or_referral_stock(self):
  p=dict(self.p(),milk=1000,feathers=1000)
  rows={row[0]:row for row in feature.achievement_rows(p,{})}
  self.assertEqual(rows['first_milk'][3],0);self.assertEqual(rows['first_feather'][3],0)
 def test_failed_claim_rolls_back_animals_and_claim_counter(self):
  self.grant('cows',10000);execute=self.c.execute
  def fail(sql,args=()):
   if sql.startswith('INSERT INTO farm_events'):raise RuntimeError('event failure')
   return execute(sql,args)
  with self.context(),patch.object(self.c,'execute',side_effect=fail):
   with self.assertRaises(RuntimeError):main.referral_claim(main.Request(item='cows'),'')
  self.assertEqual(self.p()['cows'],0)
  self.assertEqual(feature.resources(self.c.execute("SELECT * FROM referral_rewards WHERE player_id='p'").fetchone())['cows']['available'],1)
 def test_real_milk_and_feather_production_pay_commission_once_per_gain(self):
  from test_cows import dairy
  from production_v4 import FEATHER_INTERVAL
  class C:
   def __init__(self):self.calls=[];self.row=None
   def execute(self,sql,args=()):
    self.calls.append((sql,args));self.row={'parent_id':'parent'} if 'SELECT parent_id FROM referrals' in sql and args[0]=='farmer' else None;return self
   def fetchone(self):return self.row
  for item,p,end in [('milk',dairy(telegram_id=7),100000+8*3600),('feathers',dairy(telegram_id=7,cows=0,fed_cows=0,geese=1,fed_geese=1,feather_progress=FEATHER_INTERVAL-3600),100000+3600)]:
   c=C()
   with patch.object(main,'update_incubation',side_effect=lambda c,p,now:p):
    q=main.advance(c,p,end);main.advance(c,q,end)
   credits=[args for sql,args in c.calls if 'INSERT INTO referral_rewards' in sql]
   self.assertEqual(credits,[('parent',1000)],item)
