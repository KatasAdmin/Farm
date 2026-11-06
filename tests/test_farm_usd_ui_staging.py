"""Regression guard for the staged farm-to-bot USD preview.

Does not mean USD settlements are live: transfer remains denominated in UAH.
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class FarmUsdUiStagingTests(unittest.TestCase):
    def test_farm_wallet_discloses_quote_only(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "assets" / "game.js").read_text(encoding="utf-8")
        self.assertIn('id="usd-wallet-preview"', html)
        self.assertNotIn("перевод в бот: 1 монета = 1 грн", html)
        self.assertIn("future_usd_preview", js)
        self.assertIn("НЕ сумма текущего зачисления", js)
        self.assertIn("временно отключён", js)
        self.assertIn("disabled title=", html)

    def test_legacy_wallet_not_mislabeled_usd(self):
        farm = (ROOT / "farm_wallet.py").read_text(encoding="utf-8")
        self.assertIn("amount*100", farm)
        self.assertNotIn("usd_micro_to_", farm)
        # This check deliberately prevents flipping only the displayed currency.
        usd_math = (ROOT / "bot_usd_currency.py").read_text(encoding="utf-8")
        self.assertIn("farm_coins_to_usd_micro", usd_math)

if __name__ == "__main__":
    unittest.main()
