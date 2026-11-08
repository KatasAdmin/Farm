"""Immediate UAH cash credits backed by an owner's advance reserve.

Only called for authenticated, Monetag-valued impressions. Monetary credits
use real integer kopeks, with fractional kopeks accumulated per recipient.
This intentionally makes the publisher carry estimate/reconciliation risk.
"""
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.request import Request, urlopen
import json
import time
import uuid

MAX_FX_AGE_DAYS=5

class FxUnavailable(Exception):
    """A trusted provider callback should retry when conversion is unavailable."""

def initialize(c):
    c.execute("""CREATE TABLE IF NOT EXISTS bot_cash_ad_fx(
       day text PRIMARY KEY, rate numeric(14,6) NOT NULL CHECK(rate>0),
       source_date text NOT NULL, fetched_at double precision NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS bot_cash_ad_fraction(
       uid bigint PRIMARY KEY, remainder numeric(38,18) NOT NULL DEFAULT 0
       CHECK(remainder>=0 AND remainder<1))""")
    c.execute("""CREATE TABLE IF NOT EXISTS bot_cash_ad_credits(
       ymid text NOT NULL REFERENCES bot_monetag_cash_events(ymid),
       uid bigint NOT NULL, role text NOT NULL CHECK(role IN ('viewer','referral')),
       level integer NOT NULL CHECK(level BETWEEN 0 AND 7),
       earned_usd numeric(28,18) NOT NULL CHECK(earned_usd>0),
       uah_rate numeric(14,6) NOT NULL,
       credited_kopeks bigint NOT NULL CHECK(credited_kopeks>=0),
       created_at double precision NOT NULL,
       PRIMARY KEY(ymid,uid,role,level))""")
    c.execute("""CREATE INDEX IF NOT EXISTS bot_cash_ad_credits_uid
       ON bot_cash_ad_credits(uid,created_at)""")

def nbu_usd_uah(c):
    # Save daily currency snapshot; never accept exchange values from user clients.
    day=datetime.now(ZoneInfo("Europe/Kyiv")).date().isoformat()
    row=c.execute("SELECT rate FROM bot_cash_ad_fx WHERE day=%s",(day,)).fetchone()
    if row:return Decimal(str(row["rate"]))
    req=Request("https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange?valcode=USD&date="+day.replace("-","")+"&json",
        headers={"User-Agent":"Farm-Rewards/1.0"})
    with urlopen(req,timeout=4) as response: data=json.load(response)
    if not isinstance(data,list) or len(data)!=1:raise ValueError("NBU USD rate unavailable")
    record=data[0]
    if record.get("cc")!="USD":raise ValueError("NBU currency mismatch")
    rate=Decimal(str(record["rate"]))
    if not rate.is_finite() or not (Decimal("1")<rate<Decimal("1000")):
        raise ValueError("Invalid NBU rate")
    published=datetime.strptime(str(record["exchangedate"]),"%d.%m.%Y").date()
    today=datetime.now(ZoneInfo("Europe/Kyiv")).date()
    if not 0<=(today-published).days<=MAX_FX_AGE_DAYS:
        raise ValueError("Outdated NBU rate")
    rate=rate.quantize(Decimal("0.000001"))
    c.execute("""INSERT INTO bot_cash_ad_fx(day,rate,source_date,fetched_at)
      VALUES(%s,%s,%s,%s) ON CONFLICT(day) DO NOTHING""",
      (day,rate,published.isoformat(),time.time()))
    row=c.execute("SELECT rate FROM bot_cash_ad_fx WHERE day=%s",(day,)).fetchone()
    return Decimal(str(row["rate"]))

def credit_verified_event(c,ymid):
    """Exactly-once event allocation and immediate credits to UAH wallet.

    Must be called inside same transaction as verified event INSERT. This is
    not final publisher reconciliation: cash is advanced by the bot owner.
    """
    row=c.execute("""SELECT viewer_uid,allocation,reward_event_type,event_type,
      estimated_usd FROM bot_monetag_cash_events WHERE ymid=%s FOR UPDATE""",(ymid,)).fetchone()
    if not row or row["reward_event_type"]!="valued" or row["event_type"]!="impression":
        return {"credited":False,"reason":"not_valued"}
    if Decimal(str(row["estimated_usd"]))<=0:return {"credited":False,"reason":"zero"}
    # Monetag and AdsGram both pay the bot's owner-configured FIXED reward
    # per valued impression. Old per-impression USD allocations are historical
    # records only: never issue cash referral payouts from advertising revenue.
    from bot_admin import adsgram_view_reward
    uid=int(row["viewer_uid"])
    kopeks=adsgram_view_reward(c)
    c.execute("SELECT pg_advisory_xact_lock(%s)",(125492051,))
    if not c.execute("SELECT 1 FROM bot_accounts WHERE uid=%s",(uid,)).fetchone():
        raise ValueError("Viewer account missing")
    inserted=c.execute("""INSERT INTO bot_cash_ad_credits
      (ymid,uid,role,level,earned_usd,uah_rate,credited_kopeks,created_at)
      VALUES(%s,%s,'viewer',0,%s,1,%s,%s)
      ON CONFLICT DO NOTHING RETURNING uid""",
      (ymid,uid,Decimal(str(row["estimated_usd"])),kopeks,time.time())).fetchone()
    if not inserted:
        return {"credited":False,"reason":"duplicate","credited_kopeks":0}
    if kopeks:
        updated=c.execute("""UPDATE bot_accounts
          SET available=available+%s WHERE uid=%s RETURNING uid""",(kopeks,uid)).fetchone()
        if not updated:raise ValueError("Cash recipient missing")
        c.execute("""INSERT INTO bot_ledger(id,uid,delta,kind,details,created)
          VALUES(%s,%s,%s,'cash_ad_viewer',%s,%s)""",
          (uuid.uuid4().hex,uid,kopeks,
           'Monetag verified view: fixed bonus · '+ymid,time.time()))
    return {"credited":True,"credited_kopeks":kopeks,"fixed_reward":True}
