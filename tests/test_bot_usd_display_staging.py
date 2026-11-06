"""USD display staging is disabled in normal UAH production tests."""
import unittest
from decimal import Decimal
from unittest.mock import patch
import task_bot
import bot_copy
from bot_usd_currency import uah_kopecks_to_usd_micro, USD_SCALE

class StagedDollarDisplayTests(unittest.TestCase):
    def test_usd_mode_maps_historical_value_not_one_to_one(self):
        with patch.dict(task_bot.os.environ, {"FARM_DOLLAR_UI_STAGING": "1"}):
            self.assertEqual(task_bot.money(100), "$0.022005")
            self.assertEqual(task_bot.amount("1.00"), 4544)
            rendered=task_bot.money(task_bot.amount("1.00"))
            self.assertTrue(rendered.startswith("$0.9999"))
            self.assertIn("в долларах США",bot_copy.tr("Введи сумму в гривнах"))
            self.assertNotIn("грн",bot_copy.tr("Перевод: 5 грн"))

    def test_default_legacy_mode_is_preserved(self):
        with patch.dict(task_bot.os.environ, {"FARM_DOLLAR_UI_STAGING":"0"}):
            self.assertEqual(task_bot.money(100), "1,00 грн")
            self.assertEqual(task_bot.amount("1.00"),100)

    def test_small_usd_amount_never_mints_free_credit(self):
        with patch.dict(task_bot.os.environ, {"FARM_DOLLAR_UI_STAGING":"1"}):
            with self.assertRaises(task_bot.UserError):
                task_bot.amount("0.000001")
            with self.assertRaises(task_bot.UserError):
                task_bot.amount("-1")
            with self.assertRaises(task_bot.UserError):
                task_bot.amount("NaN")

if __name__=="__main__":
    unittest.main()
