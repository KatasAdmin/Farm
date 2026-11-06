"""Cash ad cooldown unit tests; no DB, network, or payments."""
import unittest
from bot_monetag_cash import cash_cooldown

class CashCooldownTests(unittest.TestCase):
    def test_ten_fast_views(self):
        self.assertEqual(cash_cooldown(list(range(10)),9)['retry_after'],21)

    def test_elapsed_five_seconds_reduces_wait(self):
        self.assertEqual(cash_cooldown([0]*9+[5],5)['retry_after'],25)

    def test_thirty_seconds_already_elapsed(self):
        self.assertEqual(cash_cooldown([0]*9+[5],30)['retry_after'],0)

    def test_one_view_per_day_never_accumulates(self):
        self.assertEqual(cash_cooldown([86400*i for i in range(10)],86400*9)['retry_after'],0)
        self.assertEqual(cash_cooldown([86400*i for i in range(10)],86400*9)['block_launches'],1)

    def test_failed_preparations_not_counted(self):
        self.assertEqual(cash_cooldown([],100)['retry_after'],0)

if __name__=='__main__':
    unittest.main()
