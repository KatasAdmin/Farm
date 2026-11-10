"""A dashboard GET must not retain player FOR UPDATE while computing analytics.

This avoids one slow ranking / market / achievement query blocking Telegram
Mini App startup for the same player in another WebView session.
"""
import unittest
from pathlib import Path

class StateLockScopeTests(unittest.TestCase):
 def test_state_advancement_is_committed_before_snapshot_queries(self):
  source=(Path(__file__).resolve().parents[1]/"main.py").read_text(encoding="utf-8")
  start=source.index('@app.get("/api/state")')
  end=source.index('@app.post(',start)
  state=source[start:end]
  advance=state.index('p=advance(c,person(c,authorization,True))')
  snapshot=state.index('p=person(c,authorization)',advance)
  market=state.index('listings=c.execute(',snapshot)
  self.assertLess(advance,snapshot)
  self.assertLess(snapshot,market)
  self.assertIn('p=advance(c,person(c,authorization,True))',state)
  self.assertIn("SET LOCAL lock_timeout = '700ms'",state)
  self.assertIn('except psycopg.errors.LockNotAvailable:',state)
  self.assertIn(' with dashboard_db() as c:\n  p=person(c,authorization)',state)
  self.assertIn('c.autocommit=True',source)
  self.assertIn('c.autocommit=False',source)
  self.assertNotIn('p=advance(c,person(c,authorization,True))\n  listings=',state)

if __name__=='__main__':unittest.main()
