"""Authenticated in-game card receipts, reviewed through the existing bot admin inbox.

The browser never certifies a bank transfer. An administrator must check bank funds.
"""
import base64
import hashlib
import json
import os
import secrets
import time
import uuid
from urllib.request import Request, urlopen

MAX_RECEIPT_BYTES = 4 * 1024 * 1024
ALLOWED = {"image/jpeg": ("jpg", b"\xff\xd8\xff"),
           "image/png": ("png", b"\x89PNG\r\n\x1a\n"),
           "application/pdf": ("pdf", b"%PDF-")}


def settings(c, player):
    import bot_topups
    row=bot_topups.config(c)
    if not player.get("telegram_id"):
        return {"enabled":False,"reason":"Привяжи Telegram в профиле перед пополнением."}
    if not row or not row["card"]:
        return {"enabled":False,"reason":"Администратор ещё не указал карту для пополнения."}
    return {"enabled":True,"card":row["card"],"recipient":row["recipient"],
            "coin_rate_uah":1,"max_receipt_bytes":MAX_RECEIPT_BYTES}


def _telegram_document(uid, payload, kind):
    token=os.environ.get("TELEGRAM_BOT_TOKEN","")
    if not token:
        raise ValueError("Telegram bot is not configured")
    suffix, _ = ALLOWED[kind]
    boundary="FarmReceipt"+secrets.token_hex(16)
    def field(name,value):
        return (("--"+boundary+"\r\nContent-Disposition: form-data; name=\""+name+"\"\r\n\r\n"+str(value)+"\r\n").encode())
    raw=(field("chat_id",uid)+
         ("--"+boundary+"\r\nContent-Disposition: form-data; name=\"document\"; filename=\"receipt."+suffix+"\"\r\nContent-Type: "+kind+"\r\n\r\n").encode()+
         payload+b"\r\n--"+boundary.encode()+b"--\r\n")
    req=Request("https://api.telegram.org/bot"+token+"/sendDocument",data=raw,
                headers={"Content-Type":"multipart/form-data; boundary="+boundary},method="POST")
    try:
        with urlopen(req,timeout=20) as response:
            data=json.load(response)
    except Exception as exc:
        raise ValueError("Не удалось передать чек. Убедись, что ты запустил Telegram-бота через /start.") from exc
    info=(data.get("result") or {}).get("document") or {}
    if not data.get("ok") or not info.get("file_id") or not info.get("file_unique_id"):
        raise ValueError("Telegram не подтвердил получение квитанции.")
    return info


def submit(c, player, amount, image_b64, mime):
    import bot_topups
    import task_bot
    import bot_notifications
    if not player.get("telegram_id"):
        raise ValueError("Привяжи Telegram к ферме для отправки квитанции.")
    config=bot_topups.config(c)
    if not config or not config["card"]:
        raise ValueError("Карта для пополнения ещё не указана.")
    if type(amount) is not int or not 1 <= amount <= 100000:
        raise ValueError("Укажи целую сумму от 1 до 100000 грн.")
    if mime not in ALLOWED or not isinstance(image_b64,str) or len(image_b64)>MAX_RECEIPT_BYTES*2:
        raise ValueError("Загрузи JPG, PNG или PDF размером до 4 МБ.")
    try:
        contents=base64.b64decode(image_b64,validate=True)
    except Exception as exc:
        raise ValueError("Неверный формат квитанции.") from exc
    if not 100 <= len(contents) <= MAX_RECEIPT_BYTES or not contents.startswith(ALLOWED[mime][1]):
        raise ValueError("Повреждённый или неподдерживаемый файл.")
    uid=int(player["telegram_id"])
    account=c.execute("SELECT uid FROM bot_accounts WHERE uid=%s",(uid,)).fetchone()
    if not account:
        raise ValueError("Открой @Farmlife2026bot, нажми /start один раз и затем повтори отправку здесь.")
    limits=task_bot.bot_admin.limits(c)
    kopeks=amount*100
    if not limits["card_min"]<=kopeks<=limits["card_max"]:
        raise ValueError("Сумма выходит за разрешённые лимиты пополнения.")
    c.execute("SELECT pg_advisory_xact_lock(%s)",(1940127001,))
    pending=c.execute("SELECT count(*) AS n FROM bot_card_topups WHERE uid=%s AND status='pending'",(uid,)).fetchone()["n"]
    if pending>=10:
        raise ValueError("У тебя уже 10 квитанций на проверке.")
    checksum=hashlib.sha256(contents).hexdigest()
    c.execute("""CREATE TABLE IF NOT EXISTS farm_card_receipt_checksums(
      checksum text PRIMARY KEY,topup_id text NOT NULL UNIQUE)""")
    if c.execute("SELECT 1 FROM farm_card_receipt_checksums WHERE checksum=%s",(checksum,)).fetchone():
        raise ValueError("Эта квитанция уже отправлена.")
    doc=_telegram_document(uid,contents,mime)
    if c.execute("SELECT 1 FROM bot_card_topups WHERE receipt_key=%s",(doc["file_unique_id"],)).fetchone():
        raise ValueError("Эта квитанция уже использована.")
    tid=uuid.uuid4().hex[:16]
    c.execute("""INSERT INTO bot_card_topups(id,uid,amount,card,recipient,file_id,receipt_key,media,status,reference,created)
      VALUES(%s,%s,%s,%s,%s,%s,%s,'document','pending','',%s)""",
      (tid,uid,kopeks,config["card"],config["recipient"],doc["file_id"],doc["file_unique_id"],time.time()))
    c.execute("INSERT INTO farm_card_topup_targets(topup_id,player_id,telegram_id) VALUES(%s,%s,%s)",
              (tid,player["id"],uid))
    c.execute("INSERT INTO farm_card_receipt_checksums(checksum,topup_id) VALUES(%s,%s)",(checksum,tid))
    bot_notifications.enqueue(c,"card-receipt:"+tid,
       "📨 Новая квитанция на проверке\n\nИгрок: "+str(uid)+
       "\nК зачислению в ферму: "+str(amount)+" монет"+
       "\nСумма: "+str(amount)+" грн\nЗаявка: "+tid+
       "\nСверь поступление в банке перед подтверждением.",
       "admin:cardview:"+tid,subject=uid)
    return {"ok":True,"id":tid,"amount_uah":amount,"status":"pending"}
