import unittest
from pathlib import Path

HTML = Path(__file__).resolve().parents[1] / "index.html"

class FarmNavigationTests(unittest.TestCase):
    def test_farm_has_only_unique_shortcuts(self):
        page = HTML.read_text(encoding="utf-8")
        farm = page.split('<section id="farm"', 1)[1].split("</section>", 1)[0]
        shortcuts = farm.split('class="quicknav farm-quicknav"', 1)[1].split("</div>", 1)[0]
        self.assertEqual(shortcuts.count('class="quick"'), 2)
        self.assertIn("tab('coop')", shortcuts)
        self.assertIn("tab('upgrades')", shortcuts)
        self.assertNotIn("tab('shop')", shortcuts)
        self.assertNotIn("tab('tasks')", shortcuts)

    def test_bottom_navigation_retains_shop_tasks(self):
        page = HTML.read_text(encoding="utf-8")
        bottom = page.split('<nav id="nav"', 1)[1].split("</nav>", 1)[0]
        self.assertIn("tab('shop')", bottom)
        self.assertIn("tab('tasks')", bottom)

if __name__ == "__main__":
    unittest.main()
