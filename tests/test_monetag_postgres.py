"""Run in CI's isolated local PostgreSQL, never against Railway production."""
import os
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse
from unittest.mock import patch
import psycopg
from psycopg.rows import dict_row
import monetag_ads as ads
import ad_inventory
from test_monetag_rewards import schema,SECRET

DSN=os.getenv('TEST_DATABASE_URL')
@unittest.skipUnless(DSN,'Set TEST_DATABASE_URL to isolated local PostgreSQL')
class MonetagPostgres(unittest.TestCase):
 def setUp(self):
  parsed=urlparse(DSN)
  if parsed.hostname not in ('localhost','127.0.0.1','postgres'):raise RuntimeError('Refusing non-local ad test database')
  self.name='farm_ads_'+uuid.uuid4().hex
  with psycopg.connect(DSN,autocommit=True) as c:c.execute('CREATE SCHEMA '+self.name)
  self.env=patch.dict(os.environ,{'MONETAG_POSTBACK_SECRET':SECRET,'MONETAG_REWARDS_ENABLED':'1'});self.env.start();self.addCleanup(self.env.stop)
  with self.connect() as c:schema(c)
 def connect(self):return psycopg.connect(DSN,row_factory=dict_row,options='-c search_path='+self.name)
 def tearDown(self):
  with psycopg.connect(DSN,autocommit=True) as c:c.execute('DROP SCHEMA '+self.name+' CASCADE')
 def assert_parallel_rewards(self,reward_type):
  now=time.time()
  with self.connect() as c:
   ads.lock(c);p=c.execute("SELECT * FROM players WHERE id='p'").fetchone();a=ads.prepare(c,p,'grain','telegram',now)
  def callback(_):
   with self.connect() as c:
    ads.lock(c);return ads.postback(c,SECRET,a['ymid'],ads.TMA_ZONE,999,'impression',reward_type,str(ads.TMA_ZONE)+'_grain_reward','7','0.0037' if reward_type=='valued' else '0',now)
  with ThreadPoolExecutor(max_workers=6) as pool:results=list(pool.map(callback,range(12)))
  self.assertEqual(sum(x['rewarded'] for x in results),int(reward_type=='valued'))
  def claim(_):
   with self.connect() as c:
    ads.lock(c);p=c.execute("SELECT * FROM players WHERE id='p' FOR UPDATE").fetchone();return ads.deliver(c,p,lambda c,p:p,lambda p:10,lambda p:100)
  with ThreadPoolExecutor(max_workers=5) as pool:results=list(pool.map(claim,range(10)))
  self.assertEqual(sum(len(x['granted']) for x in results),int(reward_type=='valued'))
  with self.connect() as c:
   p=c.execute("SELECT * FROM players WHERE id='p'").fetchone();expected=int(reward_type=='valued');self.assertEqual((p['grain'],p['coins'],p['ad_grain']),(expected,100,expected));self.assertEqual(ads.statistics(c)['estimated_usd'],'0.0037000' if reward_type=='valued' else None)
   self.assertEqual(ads.statistics(c)['total']['paid'],int(reward_type=='valued'))
 def test_duplicate_postbacks_and_claims_are_serialized(self):self.assert_parallel_rewards('valued')
 def test_unpaid_parallel_postbacks_reward_once_without_paid_income(self):self.assert_parallel_rewards('non_valued')
 def test_schema_upgrade_preserves_legacy_progress_and_grants(self):
  with self.connect() as c:
   for field in ads.FIELDS:c.execute('ALTER TABLE monetag_ad_attempts DROP COLUMN '+field)
   c.execute("INSERT INTO monetag_ad_attempts VALUES('farm_1111111111111111111111111111111111111111','p',1,2,12193261,'eggs_reward')")
   c.execute("INSERT INTO monetag_reward_grants VALUES('saved','p','grain',2,1,NULL)")
   ads.initialize(c);ads.initialize(c)
   p=c.execute("SELECT * FROM players WHERE id='p'").fetchone();s=ads.status(c,p,'web')
   self.assertEqual(s['rewards']['eggs']['progress'],1)
   self.assertEqual(ads.deliver(c,p,lambda c,p:p,lambda p:10,lambda p:100)['granted'],[{'item':'grain','quantity':2}])

 def test_ad_provenance_migration_is_repeatable_and_preserves_ordinary_and_tagged_stock(self):
  with self.connect() as c:
   c.execute("UPDATE players SET grain=20,ad_grain=2 WHERE id='p'")
   ad_inventory.initialize(c);ad_inventory.initialize(c)
   p=c.execute("SELECT * FROM players WHERE id='p'").fetchone()
   self.assertEqual((p['grain'],p['ad_grain'],p['coins']),(20,2,100))
