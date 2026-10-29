import unittest
from unittest.mock import patch
from fastapi import HTTPException
import main

LISTING_ID="f"*32

class Result:
 def __init__(self,row=None):
  self.row=row
 def fetchone(self):
  return self.row

class FakeDatabase:
 def __init__(self):
  self.statements=[]
 def __enter__(self):
  return self
 def __exit__(self,exc_type,exc,tb):
  return False
 def execute(self,sql,params=None):
  self.statements.append((sql,params))
  if sql.startswith("SELECT * FROM market"):
   return Result({"item":"eggs","quantity":10,"seller":"player"})
  return Result()

class TradeSafetyTests(unittest.TestCase):
 def run_cancel(self,eggs):
  fake=FakeDatabase()
  player={"id":"player","grain":20,"eggs":eggs,"storage_level":1}
  with patch.object(main,"db",return_value=fake),patch.object(main,"person",return_value=player),patch.object(main,"advance",return_value=player):
   return fake,main.cancel_listing(LISTING_ID,authorization="Bearer test")

 def test_cancel_listing_rejects_warehouse_overflow(self):
  fake=FakeDatabase()
  player={"id":"player","grain":20,"eggs":75,"storage_level":1}
  with patch.object(main,"db",return_value=fake),patch.object(main,"person",return_value=player),patch.object(main,"advance",return_value=player):
   with self.assertRaises(HTTPException) as err:
    main.cancel_listing(LISTING_ID,authorization="Bearer test")
  self.assertEqual(err.exception.status_code,409)
  self.assertFalse(any(sql.startswith("UPDATE players SET eggs") for sql,_ in fake.statements))

 def test_cancel_listing_returns_only_available_quantity(self):
  fake,out=self.run_cancel(60)
  self.assertEqual(out["returned"],10)
  self.assertTrue(any(sql.startswith("UPDATE players SET eggs") for sql,_ in fake.statements))
  self.assertTrue(any(sql.startswith("UPDATE market SET quantity=0") for sql,_ in fake.statements))

if __name__=="__main__":
 unittest.main()
