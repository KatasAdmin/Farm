"""Cash ad cooldown unit tests; no DB, network, or payments."""
import unittest
from bot_monetag_cash import cash_cooldown, lookup_cash_attempt_for_postback

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

    def test_break_expires_without_new_launches(self):
        self.assertEqual(cash_cooldown([0]*9+[5],29)['retry_after'],1)
        self.assertEqual(cash_cooldown([0]*9+[5],30)['retry_after'],0)

    def test_sparse_launches_reset_block(self):
        self.assertEqual(cash_cooldown([i*35 for i in range(10)],315)['block_launches'],1)

    def test_no_pause_before_tenth_launch(self):
        self.assertEqual(cash_cooldown([0]*9,1)['retry_after'],0)

    def test_failed_preparations_not_counted(self):
        self.assertEqual(cash_cooldown([],100)['retry_after'],0)

class FakePostbackCursor:
    def __init__(self, row):
        self.row=row
    def execute(self, query, params):
        self.query=query
        self.params=params
        return self
    def fetchone(self):
        return self.row


class PostbackAttemptTests(unittest.TestCase):
    def lookup(self, row):
        return lookup_cash_attempt_for_postback(
            FakePostbackCursor(row),ymid='cash_test',telegram_uid=123,
            zone_id=12193261,request_var='cash_rewarded_interstitial',now=100)

    def test_prepared_attempt_cannot_stage_income(self):
        self.assertIsNone(self.lookup({
            'state':'prepared','launched_at':None,'created_at':10,
            'zone_id':12193261,'viewer_uid':123,
            'request_var':'cash_rewarded_interstitial'}))

    def test_launched_attempt_matches(self):
        row={'state':'launched','launched_at':50,'created_at':10,
             'zone_id':12193261,'viewer_uid':123,
             'request_var':'cash_rewarded_interstitial'}
        self.assertEqual(self.lookup(row),row)

    def test_sdk_finish_does_not_block_verified_postback(self):
        # Finished display is recorded separately; payout still requires postback.
        row={'state':'launched','launched_at':50,'finished_at':70,
             'created_at':10,'zone_id':12193261,'viewer_uid':123,
             'request_var':'cash_rewarded_interstitial'}
        self.assertEqual(self.lookup(row),row)

    def test_confirmed_attempt_cannot_be_reused(self):
        self.assertIsNone(self.lookup({
            'state':'confirmed','launched_at':50,'created_at':10,
            'zone_id':12193261,'viewer_uid':123,
            'request_var':'cash_rewarded_interstitial'}))

    def test_expired_postback_rejected(self):
        from bot_monetag_cash import CASH_POSTBACK_TTL
        cursor=FakePostbackCursor({
            'state':'launched','launched_at':1,'created_at':1,
            'zone_id':12193261,'viewer_uid':123,
            'request_var':'cash_rewarded_interstitial'})
        self.assertIsNone(lookup_cash_attempt_for_postback(
            cursor,ymid='cash_test',telegram_uid=123,
            zone_id=12193261,request_var='cash_rewarded_interstitial',
            now=CASH_POSTBACK_TTL+2))

    def test_wrong_viewer_rejected(self):
        self.assertIsNone(self.lookup({
            'state':'launched','launched_at':50,'created_at':10,
            'zone_id':12193261,'viewer_uid':999,
            'request_var':'cash_rewarded_interstitial'}))


if __name__=='__main__':
    unittest.main()
