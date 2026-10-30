import re
import unittest
from pathlib import Path

class FrontendBootSafety(unittest.TestCase):
 def test_render_has_no_duplicate_daily_binding(self):
  js=(Path(__file__).resolve().parents[1]/"assets"/"game.js").read_text(encoding="utf-8")
  start=js.index("function render() {")
  end=js.index("\nfunction ",start+1)
  fragment=js[start:end]
  self.assertEqual(len(re.findall(r"\b(?:const|let)\s+daily\b",fragment)),1)
  self.assertIn("const farmDailyStats=",fragment)
 def test_script_cache_version_is_current(self):
  html=(Path(__file__).resolve().parents[1]/"index.html").read_text(encoding="utf-8")
  self.assertIn("/assets/game.js?v=43",html)
 def test_entrypoints_and_app_present(self):
  html=(Path(__file__).resolve().parents[1]/"index.html").read_text(encoding="utf-8")
  for value in ['id="app"','id="login"','id="nav"','id="farm"']:
   self.assertIn(value,html)
class ProductionReleaseSafety(unittest.TestCase):
 def player(self,hens=1,grain=10,eggs=0):
  return dict(last_tick=100,egg_at=100,egg_progress=0,feed_phase=0,
              chickens=hens,fed_hens=hens,grain=grain,eggs=eggs,coins=100,
              storage_level=1,satiety=100,critical_cycles=0,
              autobuy_enabled=False,autobuy_amount=20)
 def test_single_hen_lays_one_egg_every_six_hours(self):
  from production_v4 import simulate
  state,produced,_=simulate(self.player(),21700)
  self.assertEqual((state["eggs"],produced),(1,1))
  state,produced,_=simulate(self.player(),86500)
  self.assertEqual((state["eggs"],produced),(4,4))
  self.assertEqual(state["grain"],9)
 def test_ten_hens_produce_ten_eggs_per_six_hours(self):
  from production_v4 import simulate
  state,produced,_=simulate(self.player(hens=10),21700)
  self.assertEqual((state["eggs"],produced),(10,10))
 def test_storage_prevents_unlimited_eggs(self):
  from production_v4 import simulate
  state,produced,_=simulate(self.player(hens=10,grain=10,eggs=89),21700)
  self.assertEqual((state["eggs"],produced),(90,1))
 def test_no_grain_means_no_new_fed_hens_after_feeding(self):
  from production_v4 import simulate
  state,_,_=simulate(self.player(hens=1,grain=0),64900)
  self.assertEqual(state["fed_hens"],0)
  later,produced,_=simulate(state,86500)
  self.assertEqual(produced,0)

if __name__=="__main__":unittest.main()
