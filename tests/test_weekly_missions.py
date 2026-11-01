import unittest
from weekly_missions import complete


class WeeklyMissionTests(unittest.TestCase):
    def test_original_route_still_works(self):
        self.assertTrue(complete(10, 0, 10, 0, 3, 0))

    def test_alternatives(self):
        self.assertTrue(complete(0, 5, 0, 3, 0, 3))
        self.assertTrue(complete(10, 0, 0, 3, 0, 3))
        self.assertTrue(complete(0, 5, 10, 0, 3, 0))

    def test_each_requirement_is_mandatory(self):
        self.assertFalse(complete(9, 4, 10, 3, 3, 3))
        self.assertFalse(complete(10, 5, 9, 2, 3, 3))
        self.assertFalse(complete(10, 5, 10, 3, 2, 2))

    def test_zero_progress(self):
        self.assertFalse(complete(0, 0, 0, 0, 0, 0))


if __name__ == "__main__":
    unittest.main()
