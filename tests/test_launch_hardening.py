import unittest
from unittest.mock import patch
import main
from fastapi import HTTPException

class Result:
 def __init__(self,row=None):self.row=row
 def fetchone(self):return self.row

class DB:
 def __init__(self,row=None):self.row=row;self.calls=[]
 def __enter__(self):return self
 def __exit__(self,*args):return False
 def execute(self,sql,args=None):
  self.calls.append((sql,args))
  if "UPDATE withdrawal_requests SET status='cancelled'" in sql:return Result(self.row)
  if "SELECT 1 FROM withdrawal_requests" in sql:return Result(None)
  return Result(None)

class LaunchHardeningTests(unittest.TestCase):
 def test_new_withdrawal_reserves_balance(self):
  d=DB();p={"id":"p","coins":250,"telegram_id":123}
  with patch.object(main,"db",return_value=d),patch.object(main,"person",return_value=p),patch.object(main,"advance",return_value=p):
   out=main.request_withdrawal(main.Request(amount=100),authorization="Bearer x")
  self.assertEqual(out["status"],"pending")
  self.assertTrue(any("UPDATE players SET coins=coins-%s" in q for q,a in d.calls))
  self.assertTrue(any("reserved) VALUES" in q for q,a in d.calls))
 def test_cancel_reserved_request_refunds_once(self):
  d=DB({"amount":100,"reserved":True})
  with patch.object(main,"db",return_value=d),patch.object(main,"person",return_value={"id":"p"}):
   res=main.cancel_withdrawal(authorization="Bearer x")
  self.assertEqual(res["returned"],100)
  self.assertEqual(sum("UPDATE players SET coins=coins+%s" in q for q,a in d.calls),1)
 def test_cancel_legacy_unreserved_does_not_mint(self):
  d=DB({"amount":100,"reserved":False})
  with patch.object(main,"db",return_value=d),patch.object(main,"person",return_value={"id":"p"}):
   res=main.cancel_withdrawal(authorization="Bearer x")
  self.assertEqual(res["returned"],0)
  self.assertFalse(any("UPDATE players SET coins=coins+%s" in q for q,a in d.calls))
 def test_missing_pending_request_cannot_refund(self):
  d=DB()
  with patch.object(main,"db",return_value=d),patch.object(main,"person",return_value={"id":"p"}):
   with self.assertRaises(HTTPException) as ex:main.cancel_withdrawal(authorization="Bearer x")
  self.assertEqual(ex.exception.status_code,404)
 def test_daily_dashboard_no_extra_currency_creation(self):
  from pathlib import Path
  source=(Path(__file__).resolve().parents[1]/"main.py").read_text()
  self.assertIn('day_stats={"eggs":activity["eggs_produced"]',source)
  self.assertIn("market_trade_audit",source)
  self.assertIn("trade_risk_events",source)
if __name__=="__main__":unittest.main()
