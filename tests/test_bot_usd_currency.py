"""Staged USD denomination arithmetic must preserve historical UAH value."""
import unittest
from decimal import Decimal

from bot_usd_currency import (
    MIGRATION_RATE_UAH_PER_USD, USD_SCALE, format_usd,
    parse_usd_micro, uah_kopecks_to_usd_micro, usd_micro_to_uah_kopecks,
    farm_coins_to_usd_micro, legacy_stars_rate_to_usd_micro,
)

class USDConversionTests(unittest.TestCase):
    def test_one_dollar_at_snapshot_rate(self):
        amount = uah_kopecks_to_usd_micro(4544)
        self.assertLess(abs(Decimal(amount)/USD_SCALE-Decimal(1)), Decimal("0.0002"))

    def test_one_hryvnia_not_one_dollar(self):
        self.assertEqual(format_usd(uah_kopecks_to_usd_micro(100)), "$0.022005")
        self.assertNotEqual(uah_kopecks_to_usd_micro(100), USD_SCALE)

    def test_fractional_task_kopeck_kept(self):
        self.assertGreater(uah_kopecks_to_usd_micro(1), 0)
        self.assertNotEqual(format_usd(uah_kopecks_to_usd_micro(1)), "$0.00")

    def test_large_and_negative_for_accounting(self):
        self.assertEqual(uah_kopecks_to_usd_micro(-1000), -uah_kopecks_to_usd_micro(1000))

    def test_roundtrip_within_one_kopeck(self):
        for kopecks in (1, 3, 50, 100, 4544, 100000000):
            micro = uah_kopecks_to_usd_micro(kopecks)
            self.assertLessEqual(abs(usd_micro_to_uah_kopecks(micro, MIGRATION_RATE_UAH_PER_USD)-kopecks), 1)

    def test_farm_coin_is_legacy_uah_not_a_dollar(self):
        self.assertEqual(farm_coins_to_usd_micro(1), uah_kopecks_to_usd_micro(100))
        self.assertEqual(farm_coins_to_usd_micro(100), uah_kopecks_to_usd_micro(10000))
        self.assertNotEqual(farm_coins_to_usd_micro(1), USD_SCALE)

    def test_existing_stars_rate_keeps_historical_value(self):
        self.assertEqual(legacy_stars_rate_to_usd_micro(50), uah_kopecks_to_usd_micro(50))

    def test_format_and_parse(self):
        for text in ("1", "1.20", "0,000001", "999999999.999999"):
            self.assertEqual(parse_usd_micro(text), parse_usd_micro(format_usd(parse_usd_micro(text))[1:]))
        self.assertEqual(format_usd(1), "$0.000001")
        self.assertEqual(format_usd(10000), "$0.01")
        for text in ("-1", "1e4", "NaN", "0", "1.0000001", "1,2,3"):
            with self.assertRaises(ValueError):
                parse_usd_micro(text)

if __name__ == "__main__":
    unittest.main()
