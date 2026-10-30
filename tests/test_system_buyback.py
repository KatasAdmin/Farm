import unittest
from unittest.mock import patch
from fastapi import HTTPException
import main

class Result:
 def __init__(self, row=None):self.row=row
 def fetchone(self):return self.row

class FakeDB:
 def __init__(self,treasury=10000):
  self.treasury=treasury
  self.statements=[]
 def __enter__(self):return self
 def __exit__(self,*args):return False
 def execute(self,sql,args=None):
  self.statements.append((sql,args))
  if "SELECT treasury FROM economy" in sql:return Result({"treasury":self.treasury})
  return Result()

class SystemBuybackTests(unittest.TestCase):
 def player(self):
  return {"id":"p1","chickens":5,"fed_hens":5,"grain":18,"eggs":2,"coins":40}
 def test_system_buyback_prices(self):
  self.assertEqual(main.SYSTEM_GRAIN_BUYBACK,1)
  self.assertEqual(main.SYSTEM_HEN_BUYBACK,20)
  self.assertLess(main.SYSTEM_HEN_BUYBACK,main.HEN_PRICE)
  self.assertLess(main.SYSTEM_GRAIN_BUYBACK,main.GRAIN_PRICE)
 def run_sale(self,item,qty,treasury=10000,p=None):
  db=FakeDB(treasury)
  with patch.object(main,"db",return_value=db),patch.object(main,"person",return_value=p or self.player()),patch.object(main,"advance",side_effect=lambda c,p:p):
   result=main.sell_to_system(main.Request(item=item,amount=qty))
  return result,db.statements
 def test_grain_sale_is_instant(self):
  result,statements=self.run_sale("grain",5)
  self.assertEqual(result["received"],5)
  self.assertTrue(any("UPDATE players SET grain=grain-" in sql for sql,_ in statements))
  self.assertTrue(any("UPDATE economy SET treasury=treasury-" in sql for sql,_ in statements))
 def test_hen_sale_reduces_satiated_hens_safely(self):
  result,statements=self.run_sale("chickens",2)
  self.assertEqual(result["received"],40)
  sql,args=next((sql,args) for sql,args in statements if "UPDATE players SET chickens=" in sql)
  self.assertIn("fed_hens=LEAST(fed_hens,%s)",sql)
  self.assertEqual(args[:3],(3,3,40))
 def test_no_overselling(self):
  with self.assertRaises(HTTPException) as exc:
   self.run_sale("chickens",6)
  self.assertEqual(exc.exception.status_code,400)
 def test_no_unfunded_buyback(self):
  with self.assertRaises(HTTPException) as exc:
   self.run_sale("chickens",3,treasury=0)
  self.assertEqual(exc.exception.status_code,409)
 def test_market_eggs_cannot_use_system_buyback(self):
  with self.assertRaises(HTTPException):
   self.run_sale("eggs",2)

if __name__=="__main__":unittest.main()
