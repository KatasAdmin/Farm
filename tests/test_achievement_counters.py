import unittest
from achievement_counters import SUPPORTED, count


class Cursor:
    def __init__(self, n):
        self.n = n
        self.sql = ""
        self.params = None

    def execute(self, sql, params):
        self.sql, self.params = sql, params
        return self

    def fetchone(self):
        return {"n": self.n}


class AchievementCounterTest(unittest.TestCase):
    def test_all_supported_tracks_have_persisted_queries(self):
        for track in SUPPORTED:
            with self.subTest(track=track):
                cursor = Cursor(7)
                self.assertEqual(count(cursor, "player-1", track), 7)
                self.assertIn("player-1", cursor.params)
                self.assertTrue(any(table in cursor.sql for table in
                                    ("daily_activity", "farm_events", "money_log", "market_trade_audit")))

    def test_livestock_item_is_parameterized(self):
        for track, item in (("chickens_bought", "chickens"),
                            ("geese_bought", "geese"), ("cows_bought", "cows")):
            cursor = Cursor(1)
            count(cursor, "p", track)
            self.assertEqual(cursor.params[1], "^" + item + r" x[0-9]+$")

    def test_unsupported_track_is_rejected(self):
        with self.assertRaises(ValueError):
            count(Cursor(1), "p", "feeding")


if __name__ == "__main__":
    unittest.main()
