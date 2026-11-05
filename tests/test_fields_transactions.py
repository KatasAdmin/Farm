import unittest
import fields
from fastapi import HTTPException
from test_task_bot import Database

class FieldsTransactions(unittest.TestCase):
 def setUp(self):
  self.c=Database()
  self.c.execute('CREATE TABLE players(id text PRIMARY KEY,coins int,grain int,eggs int,milk int,feathers int,storage_level int)')
  self.c.execute("INSERT INTO players VALUES('p',1000,0,0,0,0,10)")
  self.c.execute('CREATE TABLE economy(id int,treasury int)')
  self.c.execute('INSERT INTO economy VALUES(1,0)')
  fields.migrate(self.c)
 def p(self):return dict(self.c.execute("SELECT * FROM players WHERE id='p'").fetchone())
 def test_either_purchase_order_and_exact_spending(self):
  result=fields.purchase(self.c,self.p(),'field',100)
  self.assertTrue(result['needs_combine'])
  self.assertEqual(result['grain_per_day'],0)
  self.assertEqual(self.p()['coins'],760)
  fields.purchase(self.c,self.p(),'combine',100)
  self.assertEqual(self.p()['coins'],560)
  self.assertEqual(fields.status(self.c,self.p())['grain_per_day'],11)
 def test_combine_first_is_idle(self):
  result=fields.purchase(self.c,self.p(),'combine',100)
  self.assertTrue(result['needs_field']);self.assertEqual(result['grain_per_day'],0)
  fields.harvest(self.c,self.p(),86500)
  self.assertEqual(self.p()['grain'],0)
 def test_offline_harvest_is_not_duplicated(self):
  fields.purchase(self.c,self.p(),'field',100)
  fields.purchase(self.c,self.p(),'combine',100)
  fields.harvest(self.c,self.p(),86500)
  self.assertEqual(self.p()['grain'],11)
  fields.harvest(self.c,self.p(),86500)
  self.assertEqual(self.p()['grain'],11)
 def test_shared_storage_and_insufficient_funds(self):
  fields.purchase(self.c,self.p(),'field',100)
  fields.purchase(self.c,self.p(),'combine',100)
  self.c.execute("UPDATE players SET storage_level=1,eggs=99,coins=0 WHERE id='p'")
  fields.harvest(self.c,self.p(),86500)
  self.assertEqual(self.p()['grain'],1)
  with self.assertRaises(HTTPException):fields.purchase(self.c,self.p(),'field',86500)
  self.assertEqual(fields.status(self.c,self.p())['plots'],1)
  self.assertEqual(self.p()['coins'],0)
 def test_bulk_field_price_is_server_calculated_and_respects_cap(self):
  self.c.execute("UPDATE players SET coins=10000 WHERE id='p'")
  result=fields.purchase(self.c,self.p(),'field',100,quantity=12)
  self.assertEqual(result['spent'],2880)
  self.assertEqual(result['fields'],12)
  self.assertEqual(self.p()['coins'], 7120)
  with self.assertRaises(HTTPException):fields.purchase(self.c,self.p(),'field',101,quantity=489)
  self.assertEqual(fields.status(self.c,self.p())['plots'],12)
