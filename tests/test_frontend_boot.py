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
 def test_javascript_does_not_contain_duplicate_async_declaration(self):
  js=(Path(__file__).resolve().parents[1]/"assets"/"game.js").read_text(encoding="utf-8")
  self.assertNotRegex(js,r"\\basync\\s+async\\s+function\\b")
 def test_script_cache_version_is_current(self):
  html=(Path(__file__).resolve().parents[1]/"index.html").read_text(encoding="utf-8")
  self.assertIn("/assets/game.js?v=51",html)
 def test_launch_help_and_placeholder_polish(self):
  root=Path(__file__).resolve().parents[1]
  html=(root/"index.html").read_text(encoding="utf-8")
  css=(root/"assets"/"stars-mobile.css").read_text(encoding="utf-8")
  self.assertIn('id="launch-guide"',html)
  self.assertIn('class="card support-guide"',html)
  self.assertIn('class="gems" hidden',html)
  self.assertIn('Задания недели',html)
  self.assertIn('id="weekly-claim"',html)
  self.assertIn('/assets/stars-mobile.css?v=11',html)
  self.assertIn('.gems[hidden] {display:none!important;}',css)
 def test_nickname_editor_enabled_for_every_farmer(self):
  root=Path(__file__).resolve().parents[1]
  html=(root/"index.html").read_text(encoding="utf-8")
  js=(root/"assets"/"game.js").read_text(encoding="utf-8")
  self.assertIn('<div id="nickname-settings">',html)
  self.assertIn('el("nickname-settings").hidden=false',js)
  self.assertIn('Сохранить новый ник',html)
 def test_referral_tab_visible(self):
  root=Path(__file__).resolve().parents[1]
  html=(root/"index.html").read_text(encoding="utf-8")
  js=(root/"assets"/"game.js").read_text(encoding="utf-8")
  self.assertIn('id="referrals-pane"',html)
  self.assertIn("function loadReferrals()",js)
  self.assertIn("/api/referrals/claim",js)
  self.assertIn("incomingReferralCode()",js)
 def test_clickable_resources_and_symmetric_trading(self):
  root=Path(__file__).resolve().parents[1]
  html=(root/"index.html").read_text(encoding="utf-8")
  js=(root/"assets"/"game.js").read_text(encoding="utf-8")
  for resource in ("grain","chickens","eggs"):
   self.assertIn("openResourceActions('"+resource+"')",html)
  self.assertIn('id="system-sell-dialog"',html)
  self.assertIn('id="egg-sale-dialog"',html)
  self.assertIn('id="egg-sale-form"',html)
  self.assertIn('onclick="openSystemSell(\'chickens\')"',html)
  self.assertIn('onclick="openSystemSell(\'grain\')"',html)
  self.assertIn('id="incubator-shop-button"',html)
  self.assertIn("function confirmSystemSell()",js)
  self.assertIn("Зерна хватит на",html)
  self.assertIn("Следующее яйцо",html)
  self.assertIn("Как рассчитывается прогноз?",html)
  self.assertNotIn("Купить корм</button>",html)
 def test_trade_navigation_mobile_and_egg_dialog(self):
  root=Path(__file__).resolve().parents[1]
  html=(root/"index.html").read_text(encoding="utf-8")
  js=(root/"assets"/"game.js").read_text(encoding="utf-8")
  css=(root/"assets"/"stars-mobile.css").read_text(encoding="utf-8")
  self.assertIn('<summary class="forecast-summary">🥚 Ближайший сбор яиц</summary>',html)
  self.assertIn('id="egg-sale-dialog"',html)
  self.assertEqual(html.count('id="egg-sale-form"'),1)
  self.assertIn("if(grainPriceWrap)grainPriceWrap.hidden",js)
  self.assertIn('el("egg-sale-dialog")',js)
  self.assertNotIn('tab("market");return openSystemSell',js)
  self.assertIn('#shop .compact-trade-scene,#market .compact-trade-scene',css)
  self.assertIn('#shop .product .trade-dual-actions',css)
  for item in ("eggs","grain","chickens"):
   self.assertIn("openSell('"+item+"')" if item=="eggs" else "openSystemSell('"+item+"')",html)
 def test_single_market_screen(self):
  root=Path(__file__).resolve().parents[1]
  html=(root/"index.html").read_text(encoding="utf-8")
  js=(root/"assets"/"game.js").read_text(encoding="utf-8")
  self.assertIn('<section id="shop" class="panel" aria-label="Рынок">',html)
  self.assertNotIn('<section id="market"',html)
  self.assertNotIn('class="switch unified-switch"',html)
  self.assertEqual(html.count('id="mylist"'),1)
  self.assertIn("if(id===\"market\")id=\"shop\"",js)
  self.assertIn('<span>Рынок</span>',html)
  self.assertIn('Мои объявления',html)
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
