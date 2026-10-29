import unittest
from unittest.mock import patch
from fastapi import HTTPException
import main

SAMPLE = "FARM-AAAAA-BBBBB-CCCCC-DDDDD"

class FakeCursor:
 def __init__(self,row=None): self.row=row
 def fetchone(self):return self.row

class FakeDB:
 def __init__(self,available=True):
  self.available=available
  self.queries=[]
 def __enter__(self):return self
 def __exit__(self,*args):return False
 def execute(self,sql,params=None):
  self.queries.append((sql,params))
  if "UPDATE promo_codes SET redeemed_by" in sql:
   return FakeCursor({"amount":1000} if self.available else None)
  return FakeCursor(None)

class PromoTests(unittest.TestCase):
 def test_redeem_credits_once_and_audits(self):
  db=FakeDB()
  with patch.object(main,"db",return_value=db), patch.object(main,"person",return_value={"id":"farmer"}):
   result=main.redeem_promo(main.Request(code=SAMPLE),authorization="Bearer test")
  self.assertEqual(result,{"ok":True,"awarded":1000})
  self.assertEqual(sum("UPDATE players SET coins=coins+" in q for q,_ in db.queries),1)
  self.assertTrue(any("INSERT INTO money_log" in q for q,_ in db.queries))
  self.assertTrue(any("UPDATE reward_emission" in q for q,_ in db.queries))
  self.assertEqual(next(v for q,v in db.queries if "UPDATE promo_codes SET" in q)[0],"farmer")

 def test_used_code_cannot_credit_or_log(self):
  db=FakeDB(available=False)
  with patch.object(main,"db",return_value=db),patch.object(main,"person",return_value={"id":"other"}):
   with self.assertRaises(HTTPException) as err:
    main.redeem_promo(main.Request(code=SAMPLE),authorization="Bearer test")
  self.assertEqual(err.exception.status_code,409)
  self.assertFalse(any("UPDATE players SET coins" in q for q,_ in db.queries))
  self.assertFalse(any("INSERT INTO money_log" in q for q,_ in db.queries))

 def test_invalid_code_rejected_before_db(self):
  with self.assertRaises(HTTPException) as err:
   main.redeem_promo(main.Request(code="FARM-123"),authorization="Bearer test")
  self.assertEqual(err.exception.status_code,400)

 def test_uppercase_and_whitespace_normalization(self):
  db=FakeDB()
  with patch.object(main,"db",return_value=db),patch.object(main,"person",return_value={"id":"farmer"}):
   self.assertTrue(main.redeem_promo(main.Request(code="  "+SAMPLE.lower()+"  "),authorization="Bearer test")["ok"])

 def test_public_code_is_not_in_schema_or_tests(self):
  from pathlib import Path
  source=(Path(__file__).resolve().parents[1]/"main.py").read_text()
  self.assertIn("hashlib.sha256(code.encode",source)
  self.assertIn("redeemed_by IS NULL RETURNING amount",source)
  self.assertNotIn("FARM-3ELUP",source)

if __name__=="__main__":unittest.main()
