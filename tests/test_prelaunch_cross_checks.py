"""Fast cross-area regression gates; not a substitute for staging E2E tests."""
import pathlib
import unittest

import achievement_stages
import farm_missions
import farm_wallet

ROOT = pathlib.Path(__file__).resolve().parents[1]


class PrelaunchCrossChecks(unittest.TestCase):
    def test_achievement_tracks_are_monotonic_and_xp_positive(self):
        for track in achievement_stages.TRACKS:
            steps = achievement_stages.stages(track)
            thresholds = [step.threshold for step in steps]
            self.assertEqual(thresholds, sorted(set(thresholds)))
            self.assertTrue(all(step.xp > 0 for step in steps))
            claimed = set()
            for step in steps:
                current = achievement_stages.current_stage(track, thresholds[-1], claimed)
                self.assertEqual(current["threshold"], step.threshold)
                self.assertTrue(current["claimable"])
                claimed.add(step.threshold)
            self.assertIsNone(achievement_stages.current_stage(track, thresholds[-1], claimed))

    def test_daily_weekly_missions_require_owned_producers(self):
        for period in ("daily", "weekly"):
            empty = {m.key for m in farm_missions.available(period)}
            self.assertFalse({"eggs_produced", "milk_produced", "feathers_collected"} & empty)
            cow = {m.key for m in farm_missions.available(period, cows=1)}
            self.assertIn("milk_produced", cow)
            self.assertNotIn("feathers_collected", cow)
            goose = {m.key for m in farm_missions.available(period, geese=1)}
            self.assertIn("eggs_produced", goose)
            self.assertNotIn("milk_produced", goose)

    def test_bonus_and_stars_cannot_become_withdrawable_through_market(self):
        for source in ("bonus", "purchased"):
            wallet = {"bonus": 0, "purchased": 0, "earned": 0}
            wallet[source] = 100
            for i in range(7):
                wallet = farm_wallet.split_market_sources([(str(i), 100)], wallet, 100)[str(i)]
                self.assertEqual(wallet["earned"], 0)

    def test_harvest_ui_has_single_generic_heading_and_animal_sections(self):
        html = (ROOT / "index.html").read_text(encoding="utf8")
        self.assertEqual(html.count('id="nearest-harvest"'), 1)
        self.assertIn("Ближайший сбор", html)
        self.assertIn('data-egg-forecast', html)
        self.assertIn('data-milk-card', html)
        self.assertIn('data-feather-card', html)

    def test_staged_claims_have_database_uniqueness_and_xp_is_counted(self):
        server = (ROOT / "main.py").read_text(encoding="utf8")
        self.assertIn("PRIMARY KEY(player_id,track,threshold)", server)
        self.assertIn("ON CONFLICT DO NOTHING RETURNING threshold", server)
        self.assertIn("SUM(xp)", server)
        self.assertIn("pg_advisory_xact_lock(1984533)", server)


    def test_actual_achievement_claim_endpoint_rejects_replay(self):
        from unittest.mock import patch
        import main
        class Cursor:
            def __init__(self, row=None, rows=None):
                self.row = row
                self.rows = rows or []
            def fetchone(self):
                return self.row
            def fetchall(self):
                return self.rows
        class DB:
            def __init__(self):
                self.claimed = set()
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def execute(self, sql, args=()):
                if "SELECT id FROM players" in sql:
                    return Cursor({"id": "p"})
                if "SELECT threshold FROM staged_achievement_claims" in sql:
                    return Cursor(rows=[{"threshold": t} for t in self.claimed])
                if "INSERT INTO staged_achievement_claims" in sql:
                    threshold = args[2]
                    if threshold in self.claimed:
                        return Cursor()
                    self.claimed.add(threshold)
                    return Cursor({"threshold": threshold})
                raise AssertionError("Unexpected query: " + sql)
        db = DB()
        with patch.object(main, "db", return_value=db), patch.object(main, "person", return_value={"id": "p"}), patch.object(main, "advance", side_effect=lambda c,p:p), patch.object(main.achievement_counters, "count", return_value=1):
            result = main.claim_staged_achievement(main.Request(item="feathers"), "Bearer p")
            self.assertEqual((result["threshold"], result["xp_awarded"]), (1, 10))
            with self.assertRaises(main.HTTPException):
                main.claim_staged_achievement(main.Request(item="feathers"), "Bearer p")
        self.assertEqual(db.claimed, {1})

    def test_prelaunch_requires_staging_and_backup(self):
        checklist = (ROOT / "PRELAUNCH_CHECKLIST.md").read_text(encoding="utf8")
        self.assertIn("backup", checklist.lower())
        self.assertIn("staging", checklist.lower())
        self.assertIn("Do not merge", checklist)


if __name__ == "__main__":
    unittest.main()
