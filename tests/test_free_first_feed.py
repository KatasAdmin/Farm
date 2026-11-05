import unittest
from unittest.mock import patch
import main
from production_v4 import simulate

class DB:
 def __init__(self):self.calls=[]
 def __enter__(self):return self
 def __exit__(self,*args):return False
 def execute(self,sql,args=None):
  self.calls.append((sql,args))
  class Result:
   def fetchall(self):return []
  return Result()

class FeedTests(unittest.TestCase):
 def test_new_purchased_hens_are_fed_without_grain(self):
  from test_animal_market_transactions import AnimalMarketTransactions
  fixture=AnimalMarketTransactions();fixture.setUp()
  fixture.c.execute("UPDATE players SET chickens=2,fed_hens=1,grain=0 WHERE id='a'")
  fixture.c.raw.commit()
  fixture.base.credit('a','stars_purchase',120,'first-feed-purchase')
  fixture.buy('a','chickens',3)
  purchased=fixture.base.p('a')
  self.assertEqual((purchased['chickens'],purchased['fed_hens'],purchased['grain']),(5,4,0))

 def test_shared_feed_schedule(self):
  p=dict(chickens=5,fed_hens=5,grain=10,eggs=0,coins=100,
   storage_level=3,autobuy_enabled=False,autobuy_amount=20,
   satiety=100,critical_cycles=0,feed_phase=0,last_tick=100000.0,
   egg_at=100000.0,egg_progress=0)
  before,_,_=simulate(p,100000+36000)
  after,_,_=simulate(p,100000+64800)
  self.assertEqual(before["grain"],10)
  self.assertEqual(after["grain"],5)

 def test_old_hungry_hens_not_refed_for_free(self):
  p=dict(chickens=5,fed_hens=1,grain=0,eggs=0,coins=100,
   storage_level=3,autobuy_enabled=False,autobuy_amount=20,
   satiety=100,critical_cycles=0,feed_phase=0,last_tick=100000.0,
   egg_at=100000.0,egg_progress=0,production_model=4,id="p")
  db=DB()
  with patch.object(main,"update_incubation",side_effect=lambda c,p,now:p):
   out=main.advance(db,p,100100.0)
  self.assertEqual(out["fed_hens"],1)
  self.assertEqual(out["grain"],0)

if __name__=="__main__":unittest.main()
