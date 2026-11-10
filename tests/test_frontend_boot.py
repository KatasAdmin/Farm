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
 def test_expanded_missions_are_wired_to_server_and_ui(self):
  root=Path(__file__).resolve().parents[1]
  main=(root/"main.py").read_text(encoding="utf-8")
  js=(root/"assets"/"game.js").read_text(encoding="utf-8")
  html=(root/"index.html").read_text(encoding="utf-8")
  for key in ("market_buy","buy_chicken","buy_goose","buy_cow"):
   self.assertIn('"'+key+'":1',main)
   self.assertIn('"'+key+'"',js)
  self.assertIn('id="weekly-extra"',html)
  self.assertIn('weekly.market_purchases',js)
  self.assertIn('weekly.feathers',js)
 def test_nominal_price_shows_sub_kopeck_precision(self):
  root=Path(__file__).resolve().parents[1]
  js=(root/"assets"/"game.js").read_text(encoding="utf-8")
  main=(root/"main.py").read_text(encoding="utf-8")
  self.assertIn('maximumFractionDigits:18',js)
  self.assertIn('el("wallet-coin-rate")',js)
  self.assertIn('el("wallet-transfer-value")',js)
  self.assertIn('formatRate(rate)',js)
  self.assertIn('nominal_coin_price_uah',main)
  self.assertIn('nominal_rate',main)
 def test_polished_farm_panels_and_safe_transfer_controls(self):
  root=Path(__file__).resolve().parents[1]
  html=(root/"index.html").read_text(encoding="utf-8")
  css=(root/"assets"/"farm-ui-finish.css").read_text(encoding="utf-8")
  js=(root/"assets"/"game.js").read_text(encoding="utf-8")
  for element in ("production-types","production-timers","production-forecast","payback-grid","wallet-rate-grid","wallet-coin-rate","wallet-transfer-value"):
   self.assertIn(element,html)
  self.assertIn("/assets/farm-ui-finish.css?v=3",html)
  self.assertIn("#farm .bird-resources",css)
  for heading in ("🐾 Животные","📦 Продукция"):
   self.assertIn(heading,html)
  for selector in ("farm-resource-grid farm-resource-animals","farm-resource-grid farm-resource-products"):
   self.assertIn(selector,html)
  self.assertIn("#shop .market-product-grid>.catalog-row>.trade-dual-actions",css)
  feather_row=html[html.index('<h3>Перо</h3>'):html.index('class="equipment incubator-shop"') if 'class="equipment incubator-shop"' in html else html.index('class="product catalog-row market-card equipment incubator-shop"')]
  self.assertLess(feather_row.index("selectBuy('feathers')"),feather_row.index("openSell('feathers')"))
  self.assertIn('coins<minimum',js)
  self.assertIn("minimum||100",js)
  self.assertIn('id="withdrawal-amount" type="number" inputmode="numeric" min="100"',html)

 def test_stadnik_is_shared_for_cows_and_sheep(self):
  root=Path(__file__).resolve().parents[1]
  html=(root/"index.html").read_text(encoding="utf-8")
  main=(root/"main.py").read_text(encoding="utf-8")
  ads=(root/"monetag_ads.py").read_text(encoding="utf-8")
  self.assertIn("🏡 Стадник",html)
  self.assertIn("Общие места для коров и овец",html)
  self.assertEqual(html.count('id="upgrade-cowshed"'),1)
  self.assertIn('def cowshed_limit(p):return 4*p.get("cowshed_level",1)',main)
  self.assertIn("def livestock_used(p):return p.get(\"cows\",0)+p.get(\"sheep\",0)",main)
  self.assertIn("4*p.get('cowshed_level',1)",ads)
 def test_weekly_market_purchases_include_system_supply(self):
  main=(Path(__file__).resolve().parents[1]/"main.py").read_text(encoding="utf-8")
  start=main.index('weekly_stats["market_purchases"]=')
  fragment=main[start:start+420]
  self.assertIn("FROM money_log",fragment)
  self.assertIn("kind='market_buy'",fragment)
  self.assertIn("SUM((split_part(details,' x',2))::bigint)",fragment)
  self.assertNotIn("FROM market_trade_audit",fragment)
 def test_script_cache_version_is_current(self):
  html=(Path(__file__).resolve().parents[1]/"index.html").read_text(encoding="utf-8")
  self.assertRegex(html,r'/assets/game\.js\?v=[1-9][0-9]*')
  self.assertEqual(len(re.findall(r'/assets/game\.js\?v=[0-9]+',html)),1)
 def test_launch_help_and_placeholder_polish(self):
  root=Path(__file__).resolve().parents[1]
  html=(root/"index.html").read_text(encoding="utf-8")
  css=(root/"assets"/"stars-mobile.css").read_text(encoding="utf-8")
  self.assertIn('id="launch-guide"',html)
  self.assertIn('class="card support-guide"',html)
  self.assertIn('class="gems" hidden',html)
  self.assertIn('Задания недели',html)
  self.assertIn('id="weekly-claim"',html)
  self.assertIn('/assets/stars-mobile.css?v=13',html)
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
  self.assertIn('onclick="openSell(\'chickens\')"',html)
  self.assertIn('onclick="openSell(\'grain\')"',html)
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
  self.assertIn('<summary class="forecast-summary">🌾 Ближайший сбор</summary>',html)
  self.assertIn('id="egg-sale-dialog"',html)
  self.assertEqual(html.count('id="egg-sale-form"'),1)
  self.assertIn("function openSell(item)",js)
  self.assertIn('el("egg-sale-dialog")',js)
  self.assertNotIn('tab("market");return openSystemSell',js)
  self.assertIn('#shop .compact-trade-scene,#market .compact-trade-scene',css)
  self.assertIn('#shop .product .trade-dual-actions',css)
  for item in ("eggs","grain","chickens"):
   self.assertIn("openSell('"+item+"')",html)
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
 def test_miniapp_startup_recovers_from_busy_server_and_script_error(self):
  root=Path(__file__).resolve().parents[1]
  js=(root/"assets"/"game.js").read_text(encoding="utf-8")
  html=(root/"index.html").read_text(encoding="utf-8")
  self.assertIn("[500,502,503,504,423,429]",js)
  self.assertIn("showStartupError(error)",js)
  self.assertIn("retryTransientStartup(error)",js)
  self.assertIn("window.Telegram?.WebApp?.ready?.();",js)
  self.assertIn("Перезапустить приложение",html)
  self.assertIn("Не загрузился файл игры",html)
 def test_login_is_available_without_auth_config_fetch(self):
  root=Path(__file__).resolve().parents[1]
  js=(root/"assets"/"game.js").read_text(encoding="utf-8")
  html=(root/"index.html").read_text(encoding="utf-8")
  start=js.index("function configureTelegramEntry()")
  stop=js.index("configureTelegramEntry();",start)
  setup=js[start:stop]
  self.assertNotIn("/api/auth/config",setup)
  self.assertIn("Boolean(tgInitData())",setup)
  self.assertIn("window.retryFarmStartup=retryFarmStartup",js)
  self.assertIn("window.chooseFarmLogin=chooseFarmLogin",js)
  self.assertIn("Войти другим способом",html)
  self.assertIn("Продолжить через Telegram",html)
  self.assertIn("STARTUP_RETRIES = 3",js)
  self.assertIn('if(el("boot-screen"))el("boot-screen").hidden=false',js)
  self.assertIn('if(requestToken!==token)return;',js)
  self.assertNotIn('if(!state||el("app")?.hidden)throw Error',js)

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
