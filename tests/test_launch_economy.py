import unittest
from unittest.mock import patch
from fastapi import HTTPException
import main

class Cursor:
    def __init__(self, row=None):
        self.row = row
    def fetchone(self):
        return self.row

class FakeDB:
    def __init__(self):
        self.calls = []
    def __enter__(self):
        return self
    def __exit__(self, kind, value, tb):
        return False
    def execute(self, sql, args=None):
        self.calls.append((sql, args))
        if "SELECT treasury FROM economy" in sql:
            return Cursor({"treasury": 100})
        return Cursor(None)

class LaunchEconomyTests(unittest.TestCase):
    def test_price_and_thirty_day_break_even(self):
        self.assertEqual((main.HEN_PRICE, main.GRAIN_PRICE, main.EGG_PRICE), (40, 2, 1))
        self.assertEqual(main.CYCLE, 6 * 3600)
        self.assertEqual(main.FEED_EVERY, 3)
        eggs = 30 * 24 * 3600 // main.CYCLE
        feed = 30 * 24 * 3600 // (main.CYCLE * main.FEED_EVERY)
        self.assertEqual(eggs * main.EGG_PRICE - feed * main.GRAIN_PRICE, main.HEN_PRICE)

    def test_nickname_registration_ten_coins(self):
        database = FakeDB()
        with patch.object(main, "db", return_value=database):
            result = main.join(main.Request(name="NewFarmer", password="securePassword123"))
        self.assertTrue(result["token"])
        inserts = [s for s, _ in database.calls if s.startswith("INSERT INTO players")]
        self.assertEqual(len(inserts), 1)
        self.assertIn("token,coins,last_tick", inserts[0])
        self.assertIn("VALUES(%s,%s,%s,10,", inserts[0])
        self.assertTrue(any("treasury=treasury-10" in s for s, _ in database.calls))

    def test_telegram_registration_ten_coins(self):
        database = FakeDB()
        with patch.object(main, "db", return_value=database), patch.object(main, "telegram_identity", return_value=12345):
            result = main.login_telegram(main.Request(telegram_data="mock"))
        self.assertTrue(result["token"])
        self.assertTrue(any("VALUES(%s,%s,%s,10," in s for s, _ in database.calls if s.startswith("INSERT INTO players")))
        self.assertTrue(any("treasury=treasury-10" in s for s, _ in database.calls))

    def test_withdrawal_minimum(self):
        with self.assertRaises(HTTPException) as e:
            main.request_withdrawal(main.Request(amount=99))
        self.assertEqual(e.exception.status_code, 403)

    def test_withdrawal_requires_linked_telegram(self):
        database = FakeDB()
        p = {"id": "id", "coins": 200, "telegram_id": None}
        with patch.object(main, "db", return_value=database), patch.object(main, "person", return_value=p), patch.object(main, "advance", return_value=p):
            with self.assertRaises(HTTPException) as e:
                main.request_withdrawal(main.Request(amount=100), authorization="Bearer fake")
        self.assertEqual(e.exception.status_code, 403)

    def test_withdrawal_disabled_before_any_balance_change(self):
        database = FakeDB()
        with patch.object(main, "db", return_value=database):
            with self.assertRaises(HTTPException) as e:
                main.request_withdrawal(main.Request(amount=100), authorization="Bearer fake")
        self.assertEqual(e.exception.status_code, 403)
        self.assertFalse(database.calls)

if __name__ == "__main__":
    unittest.main()
