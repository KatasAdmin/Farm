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



    def test_achievement_api_unlocks_next_stage_without_resetting_total(self):
        from unittest.mock import patch
        import main
        class Cursor:
            def __init__(self, row=None, rows=()):
                self.row, self.rows = row, rows
            def fetchone(self): return self.row
            def fetchall(self): return self.rows
        class DB:
            claimed = set()
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def execute(self, sql, args=()):
                if "SELECT id FROM players" in sql:
                    return Cursor({"id": "p"})
                if "SELECT threshold FROM staged_achievement_claims" in sql:
                    return Cursor(rows=[{"threshold": t} for t in self.claimed])
                if "INSERT INTO staged_achievement_claims" in sql:
                    self.claimed.add(args[2])
                    return Cursor({"threshold": args[2]})
                raise AssertionError(sql)
        db = DB()
        with patch.object(main, "db", return_value=db), patch.object(main, "person", return_value={"id": "p"}), patch.object(main, "advance", side_effect=lambda c,p:p), patch.object(main.achievement_counters, "count", return_value=10):
            awards = [main.claim_staged_achievement(main.Request(item="feathers"), "Bearer p") for _ in range(3)]
            self.assertEqual([x["threshold"] for x in awards], [1, 3, 10])
            self.assertEqual([x["xp_awarded"] for x in awards], [10, 20, 30])
            with self.assertRaises(main.HTTPException):
                main.claim_staged_achievement(main.Request(item="feathers"), "Bearer p")
        self.assertEqual(db.claimed, {1, 3, 10})


    def test_bot_transfer_retry_does_not_double_credit(self):
        from unittest.mock import Mock
        from fastapi import HTTPException
        class Cursor:
            def __init__(self, row): self.row = row
            def fetchone(self): return self.row
        class DB:
            def __init__(self, record): self.record, self.queries = record, []
            def execute(self, sql, args=()):
                self.queries.append(sql)
                if "FROM farm_bot_transfers WHERE id=" in sql:
                    return Cursor(self.record)
                raise AssertionError("Unexpected write on retry: " + sql)
        player = {"id": "p", "telegram_id": 77}
        key = "00000000-0000-0000-0000-000000000001"
        db = DB({"player_id": "p", "telegram_id": 77, "amount": 100})
        bot = Mock()
        result = farm_wallet.transfer(db, player, 100, key, bot)
        self.assertTrue(result["repeated"])
        self.assertEqual(result["amount"], 100)
        bot.assert_not_called()
        self.assertEqual(len(db.queries), 1)
        for wrong in ({"player_id": "other", "telegram_id": 77, "amount": 100},
                      {"player_id": "p", "telegram_id": 77, "amount": 101},
                      {"player_id": "p", "telegram_id": 88, "amount": 100}):
            with self.subTest(wrong=wrong):
                with self.assertRaises(HTTPException) as error:
                    farm_wallet.transfer(DB(wrong), player, 100, key, bot)
                self.assertEqual(error.exception.status_code, 409)

    def test_withdrawal_api_rejects_invalid_amount_and_retry_key_before_db(self):
        from unittest.mock import patch
        import main
        with patch.object(main, "db", side_effect=AssertionError("DB must not be opened")):
            for amount, key in [(99, "00000000-0000-0000-0000-000000000001"),
                                (1000001, "00000000-0000-0000-0000-000000000001"),
                                (100, "not-a-uuid")]:
                with self.subTest(amount=amount, key=key):
                    with self.assertRaises(main.HTTPException):
                        main.request_withdrawal(main.Request(amount=amount, transfer_id=key), "Bearer p")

    def test_withdrawal_api_preserves_retry_key_for_transfer_ledger(self):
        from unittest.mock import patch
        import main
        from uuid import UUID
        key = "00000000-0000-0000-0000-000000000001"
        class DB:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def execute(self, sql, args=()):
                self.last_sql = sql
                return self
        db = DB()
        with patch.dict(main.os.environ,{"FARM_TRANSFER_TO_BOT_ENABLED":"1"}), patch.object(main, "db", return_value=db), patch.object(main, "person", return_value={"id": "p"}), patch.object(main, "advance", side_effect=lambda c,p:p), patch.object(main.farm_wallet, "transfer", return_value={"ok": True}) as transfer, patch.object(main.task_bot.bot_notifications, "wake"):
            self.assertEqual(main.request_withdrawal(main.Request(amount=100, transfer_id=key), "Bearer p"), {"ok": True})
            transfer.assert_called_once()
            args = transfer.call_args.args
            self.assertEqual(args[2], 100)
            self.assertEqual(args[3], str(UUID(key)))


    def test_staging_cannot_execute_production_owner_grant(self):
        from unittest.mock import patch
        import main
        import release_grants
        import inspect
        source = inspect.getsource(main.lifespan)
        self.assertIn('FARM_STAGING', source)
        self.assertIn('release_grants.apply', source)
        # Verify the grant call is guarded, not merely mentioned elsewhere.
        guard = source.index('if os.environ.get("FARM_STAGING"')
        grant = source.index('release_grants.apply')
        self.assertLess(guard, grant)

    def test_prelaunch_requires_staging_and_backup(self):
        checklist = (ROOT / "PRELAUNCH_CHECKLIST.md").read_text(encoding="utf8")
        self.assertIn("backup", checklist.lower())
        self.assertIn("staging", checklist.lower())
        self.assertIn("Do not merge", checklist)


if __name__ == "__main__":
    unittest.main()
