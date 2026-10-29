import unittest
from production_v4 import simulate,forecast

def farm(hens,grain=100,eggs=0,fed=None):
 t=100000.0
 return dict(id="farmer",production_model=4,last_tick=t,egg_at=t,egg_progress=0.0,
             feed_phase=0,chickens=hens,fed_hens=hens if fed is None else fed,
             grain=grain,eggs=eggs,coins=200,satiety=100,critical_cycles=0,
             storage_level=5,autobuy_enabled=False,autobuy_amount=20)

class ContinuousProductionTests(unittest.TestCase):
 def test_one_hen_six_hours(self):
  p=farm(1)
  self.assertEqual(simulate(p,100000+21600)[1],1)
 def test_two_hens_one_egg_after_three_hours(self):
  p=farm(2)
  self.assertEqual(simulate(p,100000+10800)[1],1)
 def test_twelve_hens_one_egg_every_half_hour(self):
  p=farm(12)
  self.assertEqual(simulate(p,100000+1800)[1],1)
 def test_fourteen_hens_produce_fourteen_in_six_hours(self):
  p=farm(14)
  f=forecast(p,100000)
  self.assertEqual(f["eggs_next_6h"],14)
  self.assertEqual(f["eggs_next_12h"],28)
  self.assertAlmostEqual(f["seconds_to_next_egg"],21600/14)
 def test_continuous_advance_no_double_claim(self):
  p=farm(14)
  p,a,_=simulate(p,100000+3600)
  p,b,_=simulate(p,100000+21600)
  self.assertEqual(a+b,14)
  self.assertEqual(simulate(p,100000+21600)[1],0)
 def test_independent_feeding_after_eighteen_hours(self):
  p=farm(12,grain=30)
  p,n,_=simulate(p,100000+64800)
  self.assertEqual(n,36)
  self.assertEqual(p["grain"],18)
  self.assertEqual(p["fed_hens"],12)
 def test_unfed_hens_do_not_lay(self):
  p=farm(14,fed=1)
  self.assertEqual(forecast(p,100000)["eggs_next_6h"],1)
 def test_storage_capacity_stops_overflow(self):
  p=farm(14,grain=0,eggs=99)
  p["storage_level"]=1
  self.assertEqual(simulate(p,100000+21600)[1],1)

class SimulatedReleaseLoad(unittest.TestCase):
 def test_500_independent_farms_week_of_production(self):
  # CPU-only load test; never connects to production PostgreSQL.
  for index in range(500):
   hens=(index%50)+1
   p=farm(hens,grain=500,eggs=index%25)
   p["storage_level"]=6
   p["coins"]=1000
   start=p["eggs"]
   p,produced,_=simulate(p,100000+7*86400)
   self.assertGreaterEqual(produced,0)
   self.assertEqual(p["eggs"]-start,produced)
   self.assertGreaterEqual(p["grain"],0)
   self.assertGreaterEqual(p["coins"],0)
   self.assertLessEqual(p["grain"]+p["eggs"],600)
   self.assertEqual(simulate(p,100000+7*86400)[1],0)
 def test_chunked_simulation_does_not_mint_extra_eggs(self):
  for hens in [1,2,10,50]:
   p=farm(hens,grain=500)
   p["storage_level"]=6
   whole,all_eggs,_=simulate(p,100000+2*86400)
   part=p
   combined=0
   for hours in [3,9,18,24,30,39,48]:
    part,n,_=simulate(part,100000+hours*3600)
    combined+=n
   self.assertEqual(combined,all_eggs)
   self.assertEqual(part["eggs"],whole["eggs"])
   self.assertEqual(part["grain"],whole["grain"])

if __name__=="__main__":unittest.main()
