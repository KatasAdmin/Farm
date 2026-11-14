"""Season passes are cosmetic entitlements paid in Stars, never coin credits."""
import os
import time
import uuid

from fastapi import HTTPException

import stars_validation

PREFIX = "citypass:"


def price():
    value = os.environ.get("CITY_SEASON_PASS_STARS", "")
    return int(value) if value.isascii() and value.isdecimal() and len(value) <= 5 and int(value) > 0 else 0


def initialize(c):
    c.execute("""CREATE TABLE IF NOT EXISTS city_pass_orders(
        id text PRIMARY KEY, player_id text NOT NULL, season text NOT NULL,
        telegram_id bigint NOT NULL, stars integer NOT NULL CHECK(stars>0),
        status text NOT NULL, created double precision NOT NULL,
        checkout_id text, charge_id text UNIQUE)""")
    c.execute("""CREATE UNIQUE INDEX IF NOT EXISTS city_pass_one_order
        ON city_pass_orders(player_id,season) WHERE status IN ('created','paid')""")


def active(c, season, now):
    return c.execute("""SELECT id FROM city_campaigns WHERE id=%s AND kind='season'
        AND enabled AND starts<=%s AND ends>%s""", (season,now,now)).fetchone()


def invoice(c, player, season, now):
    stars=price()
    if not stars:
        raise HTTPException(503,"Продажа пропуска пока закрыта")
    if not player.get("telegram_id"):
        raise HTTPException(403,"Привяжи Telegram для оплаты")
    if not active(c,season,now):
        raise HTTPException(409,"Сезон недоступен")
    old=c.execute("""SELECT * FROM city_pass_orders WHERE player_id=%s AND season=%s
        AND status IN ('created','paid') FOR UPDATE""",(player["id"],season)).fetchone()
    if old:
        if old["status"]=="paid":
            raise HTTPException(409,"Пропуск уже активирован")
        if old["checkout_id"]:
            raise HTTPException(409,"Платёж проверяется. Если Stars списались, обратись в поддержку.")
        if old["created"]+86400>now and old["stars"]==stars and old["telegram_id"]==player["telegram_id"]:
            return old["id"],stars
        c.execute("UPDATE city_pass_orders SET status='expired' WHERE id=%s",(old["id"],))
    key=PREFIX+uuid.uuid4().hex
    c.execute("""INSERT INTO city_pass_orders(id,player_id,season,telegram_id,stars,status,created)
        VALUES(%s,%s,%s,%s,%s,'created',%s)""",(key,player["id"],season,player["telegram_id"],stars,now))
    return key,stars


def precheckout(c,query):
    key=query.get("invoice_payload")
    order=c.execute("SELECT * FROM city_pass_orders WHERE id=%s FOR UPDATE",(key,)).fetchone()
    now=time.time()
    if not (order and order["status"]=="created" and order["telegram_id"]==(query.get("from") or {}).get("id")
            and query.get("currency")=="XTR" and type(query.get("total_amount")) is int
            and order["stars"]==query["total_amount"] and order["created"]+86400>now
            and active(c,order["season"],now)):
        return False
    if order["checkout_id"] not in (None,query["id"]):
        return False
    c.execute("UPDATE city_pass_orders SET checkout_id=%s WHERE id=%s",(query["id"],key))
    return True


def settle(c,message):
    payment=message.get("successful_payment") or {}
    order=c.execute("SELECT * FROM city_pass_orders WHERE id=%s FOR UPDATE",
                    (payment.get("invoice_payload"),)).fetchone()
    if not order or not order["checkout_id"] or not stars_validation.matches_order(order,message):
        return False
    charge=payment["telegram_payment_charge_id"]
    if c.execute("SELECT 1 FROM star_orders WHERE charge_id=%s",(charge,)).fetchone():
        return False
    c.execute("UPDATE city_pass_orders SET status='paid',charge_id=%s WHERE id=%s",(charge,order["id"]))
    return True


def entitlement(c,pid,season):
    return bool(c.execute("""SELECT 1 FROM city_pass_orders WHERE player_id=%s
        AND season=%s AND status='paid'""",(pid,season)).fetchone())


def refund(c,message):
    payment=message.get("refunded_payment") or {}
    row=c.execute("""UPDATE city_pass_orders SET status='refunded'
        WHERE id=%s AND charge_id=%s AND stars=%s
        AND status='paid' AND %s='XTR' RETURNING player_id,season""",
        (payment.get("invoice_payload"),payment.get("telegram_payment_charge_id"),
         payment.get("total_amount"),payment.get("currency"))).fetchone()
    if not row:
        return False
    c.execute("""DELETE FROM city_goal_claims WHERE player_id=%s AND scope=%s
        AND goal IN ('reward:night','reward:patron')""",(row["player_id"],row["season"]))
    c.execute("""UPDATE city_preferences p SET cosmetic=''
        WHERE player_id=%s AND cosmetic IN ('night','patron') AND NOT EXISTS (
          SELECT 1 FROM city_goal_claims g WHERE g.player_id=p.player_id AND g.goal='reward:'||p.cosmetic
        )""",(row["player_id"],))
    return True
