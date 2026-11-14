import unittest
from pathlib import Path

HTML = Path(__file__).resolve().parents[1] / "index.html"

class FarmNavigationTests(unittest.TestCase):
    def test_farm_has_only_unique_shortcuts(self):
        page = HTML.read_text(encoding="utf-8")
        farm = page.split('<section id="farm"', 1)[1].split("</section>", 1)[0]
        shortcuts = farm.split('class="farm-tiles-v2"', 1)[1].split("</div>", 1)[0]
        self.assertEqual(shortcuts.count("<button"), 4)
        self.assertIn("tab('fields')", shortcuts)
        self.assertIn("Еда и бонусы", shortcuts)
        self.assertNotIn("Предприятия", shortcuts)
        self.assertIn("tab(\'production\')", shortcuts)
        self.assertNotIn("Скоро", shortcuts)
        self.assertIn("tab('coop')", shortcuts)
        self.assertIn("tab('storage')", shortcuts)
        self.assertNotIn("tab('shop')", shortcuts)
        self.assertNotIn("tab('tasks')", shortcuts)

    def test_city_link_only_on_farm_banner_and_no_duplicate_nutrition(self):
        page = HTML.read_text(encoding="utf-8")
        farm = page.split('<section id="farm"', 1)[1].split("</section>", 1)[0]
        self.assertEqual(page.count('href="/city"'), 1)
        self.assertEqual(farm.count('href="/city"'), 1)
        self.assertIn('class="farm-hero-city-link"', farm)
        self.assertNotIn('class="farm-food-summary"', farm)
        self.assertIn('class="farm-food-utensils"', farm)
        self.assertIn("Еда и бонусы", farm)

    def test_bottom_navigation_retains_shop_tasks(self):
        page = HTML.read_text(encoding="utf-8")
        bottom = page.split('<nav id="nav"', 1)[1].split("</nav>", 1)[0]
        self.assertIn("tab('shop')", bottom)
        self.assertIn("tab('tasks')", bottom)
        self.assertEqual(bottom.count('class="nav-button"'), 3)
        self.assertNotIn('data-tab="wallet"', bottom)
        self.assertNotIn('data-tab="profile"', bottom)
        # City links still resolve the hidden account/finance screens.
        app = (HTML.parent / "assets" / "game.js").read_text(encoding="utf-8")
        city = (HTML.parent / "assets" / "city" / "city.js").read_text(encoding="utf-8")
        self.assertIn('entryParams.get("profile")==="1"', app)
        self.assertIn('href="/?profile=1"', city)
        self.assertIn('href="/?wallet=1"', city)

    def test_food_dashboard_is_module_specific(self):
        page = HTML.read_text(encoding="utf-8")
        food = page.split('<section id="production"', 1)[1].split("</section>", 1)[0]
        self.assertIn('class="farm-city-header farm-food-dashboard card"', food)
        self.assertIn('class="farm-food-progress"', food)
        self.assertIn('data-farmer-fullness', food)
        self.assertIn('data-farmer-bonus', food)
        self.assertIn("Выбрать еду", food)

    def test_market_categories_keep_real_equipment_and_trade_controls(self):
        page = HTML.read_text(encoding="utf-8")
        for category in ("animals", "equipment", "resources"):
            self.assertIn('data-market-tab="' + category + '"', page)
        self.assertIn('id="fields-buy-combine-market"', page)
        self.assertIn('id="incubator-shop-button"', page)
        self.assertIn("onclick=\"openSell('eggs')\"", page)
        self.assertIn("onclick=\"showShop('grain')\"", page)

    def test_fields_have_bulk_quantity_and_direct_combine_purchase(self):
        page = HTML.read_text(encoding="utf-8")
        fields = page.split('<section id="fields"', 1)[1].split("</section>", 1)[0]
        self.assertIn('data-field-quantity="12"', fields)
        self.assertIn('id="fields-quantity-custom"', fields)
        self.assertIn('id="fields-buy-combine"', fields)

if __name__ == "__main__":
    unittest.main()
