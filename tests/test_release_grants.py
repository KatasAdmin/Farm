import unittest
from unittest.mock import patch
import task_bot as bot
import release_grants as grants
from test_task_bot import Database

class GrantTests(unittest.TestCase):
    def setUp(self):
        self.c=Database();bot.initialize(self.c);self.c.raw.commit()
    def test_exact_target_amount_and_one_credit_across_restarts(self):
        with self.c:self.assertTrue(grants.apply(self.c,bot))
        with self.c:self.assertFalse(grants.apply(self.c,bot))
        row=self.c.execute('SELECT uid,available FROM bot_accounts').fetchone()
        self.assertEqual(row,{'uid':8385663990,'available':100000})
        self.assertEqual(len(self.c.execute('SELECT * FROM bot_ledger').fetchall()),1)
        self.assertEqual(len(self.c.execute('SELECT * FROM bot_notifications').fetchall()),1)
    def test_failed_credit_rolls_back_deduplication_reference(self):
        with patch.object(bot,'change',side_effect=RuntimeError('unavailable')):
            with self.assertRaises(RuntimeError):
                with self.c:grants.apply(self.c,bot)
        self.assertFalse(self.c.execute('SELECT * FROM bot_deposits').fetchall())
        with self.c:self.assertTrue(grants.apply(self.c,bot))
        self.assertEqual(self.c.execute('SELECT available FROM bot_accounts WHERE uid=%s',(grants.UID,)).fetchone()['available'],100000)
    def test_conflicting_reference_cannot_credit_someone_else(self):
        self.c.execute('INSERT INTO bot_deposits VALUES(%s,7,100000,0)',(grants.REFERENCE,))
        with self.assertRaises(RuntimeError):grants.apply(self.c,bot)
        self.assertFalse(self.c.execute('SELECT * FROM bot_ledger').fetchall())
