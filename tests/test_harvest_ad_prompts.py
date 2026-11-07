"""Regression checks for optional AdsGram offers in the farm UI."""
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

class HarvestAdPromptTests(unittest.TestCase):
    def test_harvest_ad_buttons_are_optional_not_forced(self):
        html=(ROOT/'index.html').read_text(encoding='utf-8')
        js=(ROOT/'assets'/'monetag-rewards.js').read_text(encoding='utf-8')
        for item in ('eggs','milk'):
            self.assertIn('id="harvest-ad-'+item+'"',html)
            self.assertIn("window.FarmAds?.watch('"+item+"')",html)
            self.assertIn("const prompt=el('harvest-ad-'+item);",js.replace("for(const item of ['eggs','milk']){","for(const item of ['eggs','milk']){"))
        self.assertIn("cfg?.enabled&&!!tgInitData()",js)
        self.assertIn("/assets/monetag-rewards.js?v=9",html)
        self.assertNotIn('onclick="submitTopup()"',html)

if __name__=='__main__':
    unittest.main()
