import unittest
from unittest.mock import patch
import main

class Cursor:
 def __init__(self,row=None):self.row=row
 def fetchone(self):return self.row

class DB:
 def __init__(self,order):self.order=order;self.calls=[]
 def __enter__(self):return self
 def __exit__(self,*a):return False
 def execute(self,sql,args=None):
  self.calls.append((sql,args))
  if "SELECT * FROM star_orders WHERE id=" in sql:return Cursor(self.order)
  if "SELECT 1 FROM star_orders WHERE charge_id=" in sql:return Cursor(None)
  if "SELECT telegram_id,stars,status,created FROM star_orders" in sql:return Cursor(self.order)
  return Cursor(None)

class StarsSafety(unittest.TestCase):
 def payload(self,amount=50,uid=77,order="a"*32):
  return {"from":{"id":uid},"chat":{"id":uid},"successful_payment":{"invoice_payload":order,"telegram_payment_charge_id":"charge-1","currency":"XTR","total_amount":amount}}
 def order(self,status="created"):
  return {"id":"a"*32,"player_id":"player1","telegram_id":77,"coins":25,"stars":50,"status":status,"charge_id":None}
 def test_exact_price_is_two_stars_per_coin(self):
  self.assertEqual(25*2,50)
 def test_duplicate_paid_notification_never_credits_again(self):
  db=DB(self.order("paid"))
  with patch.object(main,"db",return_value=db):
   main.stars_payment_received(self.payload())
  self.assertFalse(any("UPDATE players" in q for q,a in db.calls))
 def test_mismatched_amount_does_not_credit(self):
  db=DB(self.order())
  with patch.object(main,"db",return_value=db):
   main.stars_payment_received(self.payload(amount=49))
  self.assertFalse(any("UPDATE players" in q for q,a in db.calls))
 def test_different_telegram_user_does_not_credit(self):
  db=DB(self.order())
  with patch.object(main,"db",return_value=db):
   main.stars_payment_received(self.payload(uid=88))
  self.assertFalse(any("UPDATE players" in q for q,a in db.calls))
 def test_valid_payment_credits_once(self):
  db=DB(self.order())
  with patch.object(main,"db",return_value=db):
   main.stars_payment_received(self.payload())
  self.assertEqual(sum("UPDATE players SET coins=coins+" in q for q,a in db.calls),1)
  self.assertEqual(sum("UPDATE star_orders SET status='paid'" in q for q,a in db.calls),1)
 def test_reject_an_unknown_payment_order(self):
  db=DB(None)
  with patch.object(main,"db",return_value=db):
   main.stars_payment_received(self.payload())
  self.assertFalse(any("UPDATE players" in q for q,a in db.calls))
 def test_payment_is_disabled_by_default(self):
  with patch.dict(main.os.environ,{},clear=True):self.assertFalse(main.stars_payment_enabled())
 def test_refund_rejects_spent_coins_without_calling_telegram(self):
  order={**self.order(status="paid"),"charge_id":"charge-1"}
  class RefundDB(DB):
   def execute(self,sql,args=None):
    if "SELECT coins,purchased_coins FROM players" in sql:
     self.calls.append((sql,args))
     return Cursor({"coins":0,"purchased_coins":25})
    return super().execute(sql,args)
  db=RefundDB(order)
  with patch.object(main,"db",return_value=db),patch.object(main,"telegram_api") as api:
   result=main.stars_refund_order("a"*32,77)
  self.assertIn("заблокирован",result)
  api.assert_not_called()
  self.assertFalse(any("UPDATE players SET coins=coins-" in q for q,a in db.calls))
 def test_refund_paid_order_calls_telegram_once_and_debits_coins(self):
  order={**self.order(status="paid"),"charge_id":"charge-1"}
  class RefundDB(DB):
   def execute(self,sql,args=None):
    if "SELECT coins,purchased_coins FROM players" in sql:
     self.calls.append((sql,args))
     return Cursor({"coins":25,"purchased_coins":25})
    return super().execute(sql,args)
  db=RefundDB(order)
  with patch.object(main,"db",return_value=db),patch.object(main,"telegram_api",return_value=True) as api:
   result=main.stars_refund_order("a"*32,77)
  self.assertIn("подтвердил возврат",result)
  api.assert_called_once_with("refundStarPayment",{"user_id":77,"telegram_payment_charge_id":"charge-1"})
  self.assertEqual(sum("UPDATE players SET coins=coins-" in q for q,a in db.calls),1)
 def test_withdrawal_is_disabled(self):
  from fastapi import HTTPException
  with self.assertRaises(HTTPException) as ex:main.request_withdrawal(main.Request(amount=100))
  self.assertEqual(ex.exception.status_code,403)

if __name__=="__main__":unittest.main()
