"""Deployment probes identify the source actually serving traffic without mutations."""
import unittest
from unittest.mock import patch
from fastapi import HTTPException
import main
from bot_release import RELEASE
import test_bot_admin as admin_tests
import test_task_bot as base


class ReleaseReadinessTests(unittest.TestCase):
    def test_probe_rejects_a_different_release_without_touching_database(self):
        with patch.object(main,'db') as database:
            self.assertEqual(main.revision_health(RELEASE),{'ok':True,'release':RELEASE})
            with self.assertRaises(HTTPException) as error:main.revision_health('old-release')
            self.assertEqual(error.exception.status_code,409)
            database.assert_not_called()

    def test_legacy_bonus_screen_and_new_owner_entry_stay_button_based(self):
        fixture=admin_tests.AdminTests();fixture.setUp()
        with fixture.c as c:
            result=main.task_bot.bot_extras.administration(c,1,'','admin:bonus',fixture.api)
        self.assertNotIn('/botbonus',result['text'])
        self.assertNotIn('/botchannel',result['text'])
        self.assertIn('admin:field:daily',str(result['reply_markup']))
        with patch.object(main,'db',return_value=fixture.c):
            dashboard=main.farm_admin_panel(1)
        self.assertIn(RELEASE,dashboard['text'])
