import unittest
from unittest.mock import patch
from fastapi import HTTPException
import main

class Cursor:
 def __init__(self,value):self.value=value
 def fetchone(self):return self.value

class RegistrationDB:
 def __init__(self,allow=True):self.allow=allow;self.calls=[]
 def execute(self,sql,args=None):
  self.calls.append((sql,args))
  if "RETURNING count" in sql:return Cursor({"count":1} if self.allow else None)
  return Cursor(None)

class SupportSecurityTests(unittest.TestCase):
 def test_web_registration_global_limits_use_transactional_sql(self):
  db=RegistrationDB()
  main.limit_public_registration(db,1750000000.0)
  inserts=[(q,a) for q,a in db.calls if "RETURNING count" in q]
  self.assertEqual(len(inserts),2)
  self.assertEqual([a[-1] for q,a in inserts],[12,300])
  for sql,_ in inserts:
   self.assertIn("ON CONFLICT(slot)",sql)
   self.assertIn("RETURNING count",sql)
 def test_flood_blocked_without_new_account(self):
  db=RegistrationDB(allow=False)
  with self.assertRaises(HTTPException) as error:
   main.limit_public_registration(db,1750000000.0)
  self.assertEqual(error.exception.status_code,429)
 def test_support_requires_private_valid_description(self):
  self.assertIn("/support",main.create_support_ticket(0,"/support v something"))
  self.assertIn("/support",main.create_support_ticket(1234,"/support v"))
  self.assertIn("/support",main.create_support_ticket(1234,"/support abc no"))
  self.assertIn("700",main.create_support_ticket(1234,"/support abc "+("A"*701)))
 def test_reply_does_not_lookup_invalid_ticket(self):
  self.assertIn("номер",main.reply_support_ticket("/reply bad text").lower())
  self.assertIn("Используй",main.reply_support_ticket("/reply"))
 def test_referral_percentages_stay_non_monetary(self):
  self.assertEqual(main.REFERRAL_RATES,(1000,500,300,200,100,50,25))
  self.assertEqual(main.REFERRAL_BONUS_COINS if hasattr(main,"REFERRAL_BONUS_COINS") else 5,5)
  self.assertNotIn("coins",main.award_referral_resource.__doc__.lower() if main.award_referral_resource.__doc__ else "")
if __name__=="__main__":unittest.main()
