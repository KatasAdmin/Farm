import unittest
from unittest.mock import patch
from fastapi import HTTPException
import main

class Cursor:
 def __init__(self,row=None): self.row=row
 def fetchone(self): return self.row

class DB:
 def __init__(self,player): self.player=player;self.queries=[]
 def __enter__(self):return self
 def __exit__(self,*args):return False
 def execute(self,sql,args=None):
  self.queries.append((sql,args))
  if "SELECT id FROM players WHERE telegram_id" in sql:return Cursor(None)
  return Cursor()

class LinkingTests(unittest.TestCase):
 def test_first_password_can_be_set_for_telegram_account(self):
  player={"id":"p","password_hash":None}
  d=DB(player)
  with patch.object(main,"db",return_value=d),patch.object(main,"person",return_value=player):
   self.assertEqual(main.set_password(main.Request(password="StrongPass123"),authorization="Bearer test"),{"ok":True})
  self.assertTrue(any("UPDATE players SET password_hash" in sql for sql,_ in d.queries))

 def test_existing_password_requires_correct_old_password(self):
  old=main.password_hash("OriginalPass123")
  player={"id":"p","password_hash":old}
  d=DB(player)
  with patch.object(main,"db",return_value=d),patch.object(main,"person",return_value=player):
   with self.assertRaises(HTTPException) as err:
    main.set_password(main.Request(password="DifferentPass123",current_password="wrong"),authorization="Bearer test")
  self.assertEqual(err.exception.status_code,403)
  self.assertFalse(any("UPDATE players SET password_hash" in sql for sql,_ in d.queries))

 def test_link_telegram_preserves_same_player(self):
  player={"id":"p","telegram_id":None}
  d=DB(player)
  with patch.object(main,"db",return_value=d),patch.object(main,"person",return_value=player),patch.object(main,"telegram_identity",return_value=12345):
   self.assertEqual(main.link_telegram(main.Request(telegram_data="signed"),authorization="Bearer test"),{"ok":True})
  self.assertTrue(any("UPDATE players SET telegram_id" in sql for sql,_ in d.queries))
  self.assertFalse(any("INSERT INTO players" in sql for sql,_ in d.queries))

 def test_duplicate_telegram_owner_is_rejected(self):
  player={"id":"p","telegram_id":None}
  class Existing(DB):
   def execute(self,sql,args=None):
    self.queries.append((sql,args))
    if "SELECT id FROM players WHERE telegram_id" in sql:return Cursor({"id":"different_player"})
    return Cursor()
  d=Existing(player)
  with patch.object(main,"db",return_value=d),patch.object(main,"person",return_value=player),patch.object(main,"telegram_identity",return_value=12345):
   with self.assertRaises(HTTPException) as ex:
    main.link_telegram(main.Request(telegram_data="signed"),authorization="Bearer test")
  self.assertEqual(ex.exception.status_code,409)
  self.assertFalse(any("UPDATE players SET telegram_id" in q for q,_ in d.queries))

 def test_existing_telegram_login_does_not_create_new_player(self):
  class Linked(DB):
   def execute(self,sql,args=None):
    self.queries.append((sql,args))
    if "SELECT id FROM players WHERE telegram_id" in sql:return Cursor({"id":"existing_player"})
    return Cursor()
  d=Linked(None)
  with patch.object(main,"db",return_value=d),patch.object(main,"telegram_identity",return_value=12345):
   result=main.login_telegram(main.Request(telegram_data="signed"))
  self.assertTrue(result["token"])
  self.assertTrue(any("UPDATE players SET token=" in q for q,_ in d.queries))
  self.assertFalse(any("INSERT INTO players" in q for q,_ in d.queries))

if __name__=="__main__": unittest.main()
