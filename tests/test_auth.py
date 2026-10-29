import unittest, os, hashlib, hmac, json, time
from urllib.parse import urlencode
from unittest.mock import patch
from fastapi import HTTPException
from main import password_hash,password_verify,telegram_identity

class AuthTests(unittest.TestCase):
    def test_password_hash_salted(self):
        a=password_hash("FarmStrong987!")
        b=password_hash("FarmStrong987!")
        self.assertNotEqual(a,b)
        self.assertTrue(password_verify("FarmStrong987!",a))
        self.assertFalse(password_verify("wrong",a))
        self.assertNotIn("FarmStrong987!",a)
    def test_password_minimum_length(self):
        with self.assertRaises(HTTPException):
            password_hash("short")
    def test_telegram_signed_data_and_tamper(self):
        bot="123456:testBotTokenForUnitTesting"
        pairs={"auth_date":str(int(time.time())),"user":json.dumps({"id":12345,"first_name":"Farm"})}
        check="\n".join(k+"="+v for k,v in sorted(pairs.items()))
        key=hmac.new(b"WebAppData",bot.encode(),hashlib.sha256).digest()
        pairs["hash"]=hmac.new(key,check.encode(),hashlib.sha256).hexdigest()
        with patch.dict(os.environ,{"TELEGRAM_BOT_TOKEN":bot}):
            self.assertEqual(telegram_identity(urlencode(pairs)),12345)
            pairs["user"]=json.dumps({"id":99999})
            with self.assertRaises(HTTPException):
                telegram_identity(urlencode(pairs))
    def test_no_telegram_without_bot_token(self):
        with patch.dict(os.environ,{"TELEGRAM_BOT_TOKEN":""}):
            with self.assertRaises(HTTPException) as err:
                telegram_identity("user=123")
            self.assertEqual(err.exception.status_code,503)

if __name__=="__main__":
    unittest.main()
