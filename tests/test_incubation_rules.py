import unittest
from incubation_rules import available_maturity_slots, can_start_incubation


class IncubationCapacityTests(unittest.TestCase):
    def test_matures_only_available_coop_slots(self):
        self.assertEqual(available_maturity_slots(10, 7, 1, 4), 2)
        self.assertEqual(available_maturity_slots(10, 10, 0, 4), 0)
        self.assertEqual(available_maturity_slots(10, 3, 1, 2), 2)

    def test_can_reserve_pending_chick_capacity(self):
        self.assertTrue(can_start_incubation(10, 7, 1, 1, 3))
        self.assertFalse(can_start_incubation(10, 7, 1, 2, 3))
        self.assertFalse(can_start_incubation(10, 1, 0, 2, 2))

    def test_invalid_counts_rejected(self):
        with self.assertRaises(ValueError):
            available_maturity_slots(10, -1, 0, 1)
        self.assertFalse(can_start_incubation(10, 1, 0, -1, 2))


if __name__ == "__main__":
    unittest.main()
