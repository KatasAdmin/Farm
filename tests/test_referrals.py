import unittest
from unittest.mock import patch
import main

class Cursor:
 def __init__(self,row=None):self.row=row
 def fetchone(self):return self.row

class ReferralDB:
 def __init__(self,parents):
  self.parents=parents
  self.calls=[]
 def execute(self,sql,args=None):
  self.calls.append((sql,args))
  if "SELECT parent_id FROM referrals" in sql:
   return Cursor({"parent_id":self.parents.get(args[0])} if args[0] in self.parents else None)
  if "UPDATE referrals SET qualified=true" in sql:return Cursor(None)
  if "SELECT player_id FROM referral_codes" in sql:return Cursor({"player_id":"parent1"})
  return Cursor(None)

class ReferralsSafety(unittest.TestCase):
 def child(self,linked=7):return {"id":"child","created_at":0,"telegram_id":linked}
 def test_all_seven_percentages_are_exact(self):
  self.assertEqual(main.REFERRAL_RATES,(1000,500,300,200,100,50,25))
  self.assertEqual(main.referral_units(5,0),5000) # half an egg
  self.assertEqual(main.referral_units(5,1),2500)
  self.assertEqual(main.referral_units(5,6),125)
 def test_seven_levels_and_no_eighth_level(self):
  names=["child","parent1","parent2","parent3","parent4","parent5","parent6","parent7","parent8"]
  db=ReferralDB({names[i]:names[i+1] for i in range(8)})
  main.award_referrals(db,self.child(),5,0)
  credits=[args[1] for sql,args in db.calls if "INSERT INTO referral_rewards" in sql]
  self.assertEqual(credits,[5000,2500,1500,1000,500,250,125])
 def test_unverified_friend_earns_no_commissions(self):
  db=ReferralDB({"child":"parent1"})
  main.award_referrals(db,self.child(linked=None),100,100000)
  self.assertEqual(db.calls,[])
 def test_claims_do_not_trigger_referral_production(self):
  # Eggs credited in a claim have a separate farm event kind.
  import inspect
  source=inspect.getsource(main.referral_claim)
  self.assertIn("'referral_eggs'",source)
  self.assertNotIn("award_referrals",source)
 def test_invite_cannot_be_assigned_to_self(self):
  db=ReferralDB({})
  self.assertFalse(main.register_referral(db,"parent1","a"*16,100))
  self.assertFalse(any("INSERT INTO referrals" in sql for sql,args in db.calls))
 def test_invite_format_must_be_unpredictable_token(self):
  db=ReferralDB({})
  for code in ["abc","x"*16,"a"*17,""]:
   self.assertFalse(main.register_referral(db,"child",code,100))
  self.assertFalse(db.calls)
