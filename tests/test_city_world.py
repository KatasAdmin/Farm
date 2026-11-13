"""Safety checks for the isolated City MVP, independent of production accounts."""
from pathlib import Path
import unittest
import city_world

ROOT=Path(__file__).resolve().parents[1]

class CityWorldSafety(unittest.TestCase):
    def test_city_has_distinct_inventory(self):
        src=(ROOT/"city_world.py").read_text("utf8")
        self.assertIn("CREATE TABLE IF NOT EXISTS city_stock",src)
        self.assertIn("CREATE TABLE IF NOT EXISTS city_products",src)
        self.assertIn('seller<>%s',src)
        self.assertIn('q.item not in INGREDIENTS',src)
        self.assertNotIn('UPDATE players SET eggs=eggs-',src)
    def test_all_raw_resources_have_use(self):
        materials=set()
        for recipe in city_world.RECIPES.values():
            materials.update(recipe["needs"])
            self.assertGreater(recipe["output"],0)
            self.assertGreater(recipe["seconds"],0)
            self.assertIn(recipe["business"],city_world.BUSINESSES)
        self.assertEqual(materials,set(city_world.INGREDIENTS))
    def test_city_cannot_mint_withdrawable_currency(self):
        src=(ROOT/"city_world.py").read_text("utf8")
        self.assertIn("city_product_sale",src)
        self.assertIn("farm_money_sources VALUES(%s,%s,0,0)",src)
        self.assertNotIn('UPDATE economy SET treasury=treasury-',src)
    def test_user_can_buy_city_products_from_farm_interface(self):
        html=(ROOT/"index.html").read_text("utf8")
        js=(ROOT/"assets/city/farm-bridge.js").read_text("utf8")
        self.assertIn('id="farm-city-products"',html)
        self.assertIn('"/api/city/"+path',js)
        self.assertIn('buy-product',js)
    def test_farm_products_have_purchase_and_real_uses(self):
        html=(ROOT/"index.html").read_text("utf8")
        js=(ROOT/"assets/city/farm-bridge.js").read_text("utf8")
        farmjs=(ROOT/"assets/game.js").read_text("utf8")
        self.assertIn('id="production"',html)
        self.assertIn('id="farm-city-catalog-list"',html)
        self.assertIn('id="farm-city-inventory"',html)
        self.assertIn('id="farm-city-orders"',html)
        self.assertIn("tab('production')",html)
        self.assertIn('window.farmCityProducts?.load?.()',farmjs)
        self.assertIn('quote-product',js)
        self.assertIn('buy-product',js)
        self.assertIn('consume',js)
        self.assertIn('fulfill-order',js)
        self.assertIn('request_id:operationId()',js)
        self.assertIn('expected_cost:quote.cost',js)
        self.assertNotIn('UPDATE players SET coins=coins+',js)
        self.assertNotIn('city_stock',js)

    def test_city_profile_and_bonus_code_wired_to_shared_farm_wallet(self):
        html=(ROOT/"city.html").read_text("utf8")
        js=(ROOT/"assets/city/city.js").read_text("utf8")
        city=(ROOT/"city_world.py").read_text("utf8")
        self.assertIn('data-view="profile"',html)
        self.assertIn('id="city-promo-input"',js)
        self.assertIn('"/api/promo/redeem"',js)
        self.assertIn('INSERT INTO promo_codes(code_hash,amount)',city)
        self.assertNotIn('FARM-8892DB409F313BE04DFC0FB',city)
        self.assertIn('getItem("farm_token")',js)

    def test_production_city_has_only_real_account_entry(self):
        html=(ROOT/"city.html").read_text("utf8")
        js=(ROOT/"assets/city/city.js").read_text("utf8")
        backend=(ROOT/"city_world.py").read_text("utf8")
        farm=(ROOT/"index.html").read_text("utf8")
        bot=(ROOT/"task_bot.py").read_text("utf8")
        self.assertNotIn('demo-enter',html)
        self.assertNotIn('enterDemo',js)
        self.assertNotIn('demo:true',js)
        self.assertNotIn('@router.get("/catalog")',backend)
        self.assertIn('href="/city"',farm)
        self.assertIn('Предприятия',farm)
        self.assertIn("farm_url().rstrip('/') + '/city'",bot)
        self.assertIn("'web_app': {'url': farm_url()}",bot)

    def test_city_page_isolated(self):
        html=(ROOT/"city.html").read_text("utf8")
        js=(ROOT/"assets/city/city.js").read_text("utf8")
        self.assertIn('id="world"',html)
        self.assertIn('id="city-auth"',html)
        self.assertIn('root+path',js)
        self.assertIn('"/api/telegram/login"',js)
    def test_idempotency_and_market_provenance(self):
        src=(ROOT/"city_world.py").read_text("utf8")
        self.assertIn("CREATE TABLE IF NOT EXISTS city_requests",src)
        self.assertIn("def _request(",src)
        self.assertIn("def _finish_request(",src)
        self.assertIn("farm_wallet.split_market_sources",src)
        self.assertIn("ad_inventory.restricted_receipt",src)

if __name__=="__main__":unittest.main()
