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
  self.assertIn("/assets/game.js?v=37",html)
 def test_entrypoints_and_app_present(self):
  html=(Path(__file__).resolve().parents[1]/"index.html").read_text(encoding="utf-8")
  for value in ['id="app"','id="login"','id="nav"','id="farm"']:
   self.assertIn(value,html)
if __name__=="__main__":unittest.main()
