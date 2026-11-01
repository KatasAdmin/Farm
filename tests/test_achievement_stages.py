import unittest
from achievement_stages import current_stage, stages

class AchievementStagesTest(unittest.TestCase):
    def test_first_feather(self):
        self.assertEqual(current_stage("feathers", 0)["threshold"], 1)
        self.assertFalse(current_stage("feathers", 0)["claimable"])

    def test_next_stage_preserves_cumulative_progress(self):
        s = current_stage("feathers", 10, {1})
        self.assertEqual((s["threshold"], s["progress"]), (3, 3))
        self.assertTrue(s["claimable"])

    def test_next_stages_require_claim(self):
        self.assertEqual(current_stage("feathers", 100, {1, 3})["threshold"], 10)

    def test_all_claimed(self):
        self.assertIsNone(current_stage("feathers", 100, {s.threshold for s in stages("feathers")}))

    def test_invalid_progress(self):
        with self.assertRaises(ValueError):
            current_stage("eggs", -1)

if __name__ == "__main__":
    unittest.main()
