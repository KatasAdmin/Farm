import unittest
from stars_validation import matches_order


class StarsValidationTests(unittest.TestCase):
    def setUp(self):
        self.order={"id":"abc123","status":"created","telegram_id":123,"stars":20}
        self.message={"from":{"id":123},"successful_payment":{
            "invoice_payload":"abc123","telegram_payment_charge_id":"charge1",
            "currency":"XTR","total_amount":20}}

    def test_valid(self):
        self.assertTrue(matches_order(self.order,self.message))

    def test_replay_after_paid(self):
        self.assertFalse(matches_order({**self.order,"status":"paid"},self.message))

    def test_rejects_wrong_sender(self):
        self.assertFalse(matches_order(self.order,{**self.message,"from":{"id":999}}))

    def test_rejects_wrong_currency_or_amount(self):
        for changes in ({"currency":"USD"},{"total_amount":21},{"total_amount":20.0}):
            with self.subTest(changes=changes):
                m={**self.message,"successful_payment":{**self.message["successful_payment"],**changes}}
                self.assertFalse(matches_order(self.order,m))

    def test_rejects_wrong_order_or_missing_charge(self):
        for changes in ({"invoice_payload":"wrong"},{"telegram_payment_charge_id":""}):
            with self.subTest(changes=changes):
                m={**self.message,"successful_payment":{**self.message["successful_payment"],**changes}}
                self.assertFalse(matches_order(self.order,m))


if __name__ == "__main__":
    unittest.main()
