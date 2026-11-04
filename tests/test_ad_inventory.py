"""Advertising goods cannot be laundered through resale, feeding or incubation."""
import math
import unittest
from unittest.mock import patch
import ad_inventory as inv
import main
import production_v4 as production
from test_monetag_rewards import AdDB,schema

class AdvertisingFixture:

 def setUp(self):
  self.c=AdDB();schema(self.c)
  self.c.execute('CREATE TABLE money_log(id text PRIMARY KEY,player_id text,kind text,delta int,details text,created real)')
  self.c.execute('CREATE TABLE farm_money_sources(log_id text PRIMARY KEY,bonus int,purchased int,earned int)')
  self.c.raw.commit()
 def player(self):return self.c.execute("SELECT * FROM players WHERE id='p'").fetchone()
 def log(self,id,kind,amount,parts=None,ad=0):
  self.c.execute('INSERT INTO money_log VALUES(%s,%s,%s,%s,%s,%s)',(id,'p',kind,amount,'',len(id)))
  if parts:self.c.execute('INSERT INTO farm_money_sources VALUES(%s,%s,%s,%s)',(id,*parts))
  if ad:inv.credit(self.c,id,ad)
  self.c.execute("UPDATE players SET coins=coins+%s WHERE id='p'",(amount,))
 def farm(self,**changes):
  p=dict(id='p',chickens=2,geese=1,cows=1,fed_hens=2,fed_geese=1,fed_cows=1,grain=100,eggs=0,feathers=0,milk=0,coins=100,storage_level=10,last_tick=1000,egg_at=1000,egg_progress=0,feather_progress=0,milk_progress=0,feed_phase=0,satiety=100,critical_cycles=0,autobuy_enabled=False,autobuy_amount=10,**{k:0 for k in inv.FIELDS});p['ad_stock_version']=1;p.update(changes);return p

class AdvertisingEconomy(AdvertisingFixture,unittest.TestCase):
 def test_grants_tag_inventory_and_consumption_keeps_normal_stock(self):
  p=self.player();inv.add(self.c,p,'eggs',2);self.assertEqual(self.player()['ad_eggs'],2)
  self.assertEqual(inv.take(self.c,p,'eggs',1),1);self.assertEqual(self.player()['ad_eggs'],1)
  self.assertEqual(inv.take(self.c,p,'eggs',5),1);self.assertEqual(self.player()['ad_eggs'],0)
 def test_ad_receipt_never_becomes_earned_and_total_is_preserved(self):
  for parts in ({'bonus':0,'purchased':0,'earned':20},{'bonus':7,'purchased':8,'earned':5}):
   r=inv.restricted_receipt(parts,12);self.assertEqual(sum(r.values()),20);self.assertGreaterEqual(r['bonus'],12);self.assertEqual(r['earned'],max(0,parts['earned']-12))
  self.assertEqual(inv.restricted_receipt({'bonus':0,'purchased':0,'earned':20},0)['earned'],20)
 def test_ad_credit_is_spent_before_other_bonus_and_cannot_be_washed_by_shop(self):
  self.log('1','market_sale',20,(20,0,0),20)
  self.assertEqual(inv.balance(self.c,self.player()),20)
  self.assertEqual(inv.funded_units(inv.balance(self.c,self.player()),40,1),1)
  self.log('22','shop',-10);self.assertEqual(inv.balance(self.c,self.player()),10)
  self.log('33','system_sale',10,(0,0,10))
  self.log('333','farm_to_bot',-5);self.assertEqual(inv.balance(self.c,self.player()),10)
  self.log('4444','shop',-40);self.assertEqual(inv.balance(self.c,self.player()),0)
 def test_only_ad_animals_production_is_restricted_and_quantities_unchanged(self):
  p=self.farm(ad_chickens=1,ad_fed_hens=1)
  normal={k:v for k,v in p.items() if not k.startswith('ad_')}
  a,_,_=production.simulate(p,1000+6*3600);b,_,_=production.simulate(normal,1000+6*3600)
  for k in normal:self.assertEqual(a[k],b[k],k)
  self.assertEqual(a['eggs'],5);self.assertEqual(a['ad_eggs'],1);self.assertEqual(a['ad_milk'],0)
 def test_ad_feed_restricts_production_of_fed_animals(self):
  p=self.farm(grain=7,ad_grain=7)
  after,_,_=production.simulate(p,1000+18*3600)
  self.assertEqual((after['ad_grain'],after['ad_fed_hens'],after['ad_fed_geese'],after['ad_fed_cows']),(0,2,1,1))
  later,_,_=production.simulate(after,1000+26*3600)
  self.assertEqual(later['ad_milk'],1);self.assertGreater(later['ad_eggs'],0)
 def test_autobuy_with_ad_credit_tags_grain_then_feed(self):
  p=self.farm(grain=0,autobuy_enabled=True,autobuy_amount=10,_ad_credit_balance=20)
  a,_,refills=production.simulate(p,1000+18*3600)
  self.assertEqual(refills,[10]);self.assertEqual(a['ad_grain'],3);self.assertEqual(a['ad_fed_cows'],1)
 def test_polling_frequency_does_not_change_ad_production(self):
  p=self.farm(ad_chickens=1,ad_fed_hens=1,ad_grain=40)
  direct,_,_=production.simulate(p,1000+72*3600)
  for hours in range(1,73):p,_,_=production.simulate(p,1000+hours*3600)
  for key in inv.FIELDS:self.assertAlmostEqual(p[key],direct[key],places=6,msg=key)
 def test_full_storage_does_not_bank_restricted_production(self):
  p=self.farm(grain=100,storage_level=1,ad_chickens=2,ad_fed_hens=2)
  p,_,_=production.simulate(p,1000+6*3600);self.assertEqual(p['ad_eggs'],0)
  p['grain']=0;p,_,_=production.simulate(p,1000+12*3600);self.assertEqual(p['ad_eggs'],2)
 def test_proportional_receipts_preserve_money_and_no_negative_sources(self):
  for bonus in range(10):
   for purchased in range(10-bonus):
    for qty in range(11):
     r=inv.restricted_receipt({'bonus':bonus,'purchased':purchased,'earned':10-bonus-purchased},qty)
     self.assertEqual(sum(r.values()),10);self.assertTrue(all(v>=0 for v in r.values()));self.assertGreaterEqual(r['bonus'],qty)

class AdvertisingPollingBoundaries(AdvertisingFixture,unittest.TestCase):
 def test_capacity_boundary_does_not_allow_polling_to_untag_goods(self):
  for slots in range(1,12):
   for ad_hens in range(1,4):
    initial=self.farm(chickens=5,fed_hens=5,geese=0,fed_geese=0,cows=0,fed_cows=0,storage_level=1,grain=100-slots,ad_chickens=ad_hens,ad_fed_hens=ad_hens)
    direct,_,_=production.simulate(initial,1000+12*3600)
    incremental=initial
    for minutes in range(7,721,7):incremental,_,_=production.simulate(incremental,1000+minutes*60)
    incremental,_,_=production.simulate(incremental,1000+12*3600)
    for key in ('eggs','ad_eggs','ad_egg_progress'):
     self.assertAlmostEqual(direct[key],incremental[key],places=6,msg=str((slots,ad_hens,key)))

class AdvertisingTradeRoutes(AdvertisingFixture,unittest.TestCase):
 def setUp(self):
  super().setUp()
  for sql in (
   'CREATE TABLE market(id text PRIMARY KEY,seller text,item text,quantity int,price int)',
   'CREATE TABLE economy(id int,treasury int)',
   'INSERT INTO economy VALUES(1,10000)',
   'CREATE TABLE stars_refund_intents(order_id text,status text)',
   'CREATE TABLE star_orders(id text,player_id text)',
   'CREATE TABLE daily_activity(player_id text,day text,grain_bought int DEFAULT 0,eggs_listed int DEFAULT 0,PRIMARY KEY(player_id,day))',
   'CREATE TABLE farm_events(id text,player_id text,kind text,amount int,created real)',
   'CREATE TABLE market_trade_audit(id text,buyer_id text,seller_id text,item text,quantity int,coins int,created real)',
   'CREATE TABLE trade_risk_events(id text,buyer_id text,seller_id text,item text,quantity int,coins int,reason text,created real)',
   'CREATE TABLE incubation_jobs(id text PRIMARY KEY,player_id text,started real,hatch_at real,mature_at real)'
  ):self.c.execute(sql)
  self.c.raw.commit()
  def person(c,auth,lock=False):return c.execute('SELECT * FROM players WHERE id=%s',(auth,)).fetchone()
  self.mocks=patch.multiple(main,db=lambda:self.c,person=person,advance=lambda c,p:p,award_referral_resource=lambda *args:None)
  self.mocks.start();self.addCleanup(self.mocks.stop)
 def request(self,item,amount=1,**kw):return main.Request(item=item,amount=amount,**kw)
 def other(self):return self.c.execute("SELECT * FROM players WHERE id='other'").fetchone()
 def test_earned_buyer_cannot_make_ad_goods_withdrawable_and_resale_keeps_tag(self):
  self.c.execute("UPDATE players SET eggs=2,ad_eggs=2 WHERE id='p'")
  self.c.execute("INSERT INTO money_log VALUES('buyer-earnings','other','system_sale',100,'',0)")
  self.c.raw.commit()
  main.sell(self.request('eggs',2),'p');main.buy(self.request('eggs',2),'other')
  self.assertEqual(main.farm_wallet.available(self.c,self.player()),0)
  self.assertEqual(inv.balance(self.c,self.player()),2)
  self.assertEqual((self.other()['eggs'],self.other()['ad_eggs']),(2,2))
  main.sell(self.request('eggs',2),'other');main.buy(self.request('eggs',2),'p')
  self.assertEqual(main.farm_wallet.available(self.c,self.other()),98)
  self.assertEqual(inv.balance(self.c,self.other()),2)
  self.assertEqual(self.player()['ad_eggs'],2)
 def test_partial_listing_cancel_restores_only_remaining_ad_units(self):
  self.c.execute("UPDATE players SET milk=4,ad_milk=2 WHERE id='p'");self.c.raw.commit()
  main.sell(self.request('milk',4),'p');main.buy(self.request('milk',1),'other')
  listing=self.c.execute("SELECT id FROM market WHERE seller='p'").fetchone()['id']
  main.cancel_listing(listing,'p')
  self.assertEqual((self.player()['milk'],self.player()['ad_milk']),(3,1))
  self.assertEqual(self.other()['ad_milk'],1)
 def test_ad_sale_credit_buying_chicken_keeps_production_restriction(self):
  self.c.execute("UPDATE players SET grain=40,ad_grain=40 WHERE id='p'");self.c.raw.commit()
  main.sell_to_system(self.request('grain',40),'p');self.assertEqual(inv.balance(self.c,self.player()),40)
  main.shop(self.request('chickens'),'p')
  self.assertEqual((self.player()['chickens'],self.player()['ad_chickens'],self.player()['ad_fed_hens']),(1,1,1))
  self.assertEqual(inv.balance(self.c,self.player()),0);self.assertEqual(main.farm_wallet.available(self.c,self.player()),0)
 def test_ad_eggs_incubation_and_maturity_preserve_tag(self):
  for field,default in [('incubator_owned','1'),('incubator_level','1')]:self.c.execute('ALTER TABLE players ADD COLUMN '+field+' int DEFAULT '+default)
  self.c.execute("UPDATE players SET eggs=12,ad_eggs=1 WHERE id='p'");self.c.raw.commit()
  main.incubator_action(self.request('start'),'p')
  job=self.c.execute('SELECT * FROM incubation_jobs').fetchone()
  main.update_incubation(self.c,self.player(),job['mature_at'])
  self.assertEqual((self.player()['ad_eggs'],self.player()['ad_chickens']),(0,1))
 def test_ordinary_inventory_with_earned_funding_keeps_ordinary_receipt(self):
  self.c.execute("UPDATE players SET eggs=2 WHERE id='p'")
  self.c.execute("INSERT INTO money_log VALUES('buyer-earnings','other','system_sale',100,'',0)");self.c.raw.commit()
  main.sell(self.request('eggs',2),'p');main.buy(self.request('eggs',2),'other')
  self.assertEqual(main.farm_wallet.available(self.c,self.player()),2)
  self.assertEqual(self.other()['ad_eggs'],0)

 def test_ad_money_keeps_its_tag_when_buying_ordinary_goods_from_another_account(self):
  self.log('ad-credit','market_sale',40,(40,0,0),40)
  self.c.execute("UPDATE players SET eggs=2 WHERE id='other'");self.c.raw.commit()
  main.sell(self.request('eggs',2),'other');main.buy(self.request('eggs',2),'p')
  self.assertEqual(inv.balance(self.c,self.other()),2)
  self.assertEqual(main.farm_wallet.available(self.c,self.other()),0)
  main.shop(self.request('grain'),'other')
  self.assertEqual(self.other()['ad_grain'],1)
