"""Immediate UAH cash credits backed by an owner's advance reserve.

Only called for authenticated, Monetag-valued impressions. Monetary credits
use real integer kopeks, with fractional kopeks accumulated per recipient.
This intentionally makes the publisher carry estimate/reconciliation risk.
"""
from decimal import Decimal, ROUND_FLOOR
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from urllib.request import Request, urlopen
import json
import time
import uuid

CENT=Decimal("1")
MAX_FX_AGE_DAYS=5

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
    req=Request("https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange?valcode=USD&json",
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
    from psycopg.types.json import Jsonb
    row=c.execute("""SELECT viewer_uid,allocation,reward_event_type,event_type,
      estimated_usd FROM bot_monetag_cash_events WHERE ymid=%s FOR UPDATE""",(ymid,)).fetchone()
    if not row or row["reward_event_type"]!="valued" or row["event_type"]!="impression":
        return {"credited":False,"reason":"not_valued"}
    if Decimal(str(row["estimated_usd"]))<=0:return {"credited":False,"reason":"zero"}
    allocation=row["allocation"]
    recipients=[(int(row["viewer_uid"]),"viewer",0,Decimal(str(allocation["viewer_usd"])))]
    for ref in allocation.get("referrals",[]):
        recipients.append((int(ref["uid"]),"referral",int(ref["level"]),Decimal(str(ref["usd"]))))
    # Avoid a race between parallel postbacks for the same recipient by
    # locking a deterministic global credit sequence within transaction.
    c.execute("SELECT pg_advisory_xact_lock(%s)",(125492051,))
    rate=nbu_usd_uah(c)
    credited=0
    for uid,role,level,usd in recipients:
        if usd<=0:continue
        if not c.execute("SELECT 1 FROM bot_accounts WHERE uid=%s",(uid,)).fetchone():
            if role=="viewer":raise ValueError("Viewer account missing")
            continue
        inserted=c.execute("""INSERT INTO bot_cash_ad_credits
         (ymid,uid,role,level,earned_usd,uah_rate,credited_kopeks,created_at)
         VALUES(%s,%s,%s,%s,%s,%s,0,%s)
         ON CONFLICT DO NOTHING RETURNING uid""",
         (ymid,uid,role,level,usd,rate,time.time())).fetchone()
        if not inserted:continue
        c.execute("""INSERT INTO bot_cash_ad_fraction(uid,remainder)
          VALUES(%s,0) ON CONFLICT(uid) DO NOTHING""",(uid,))
        fraction=c.execute("""SELECT remainder FROM bot_cash_ad_fraction
          WHERE uid=%s FOR UPDATE""",(uid,)).fetchone()
        total=Decimal(str(fraction["remainder"]))+usd*rate*Decimal(100)
        whole=int(total.to_integral_value(rounding=ROUND_FLOOR))
        remainder=total-Decimal(whole)
        if whole>9223372036854775807:raise OverflowError("Credit exceeds bigint")
        c.execute("UPDATE bot_cash_ad_fraction SET remainder=%s WHERE uid=%s",(remainder,uid))
        c.execute("""UPDATE bot_cash_ad_credits SET credited_kopeks=%s
          WHERE ymid=%s AND uid=%s AND role=%s AND level=%s""",
          (whole,ymid,uid,role,level))
        if whole:
            account=c.execute("""UPDATE bot_accounts
              SET available=available+%s WHERE uid=%s
              RETURNING uid""",(whole,uid)).fetchone()
            if not account:raise ValueError("Cash recipient missing")
            c.execute("""INSERT INTO bot_ledger(id,uid,delta,kind,details,created)
              VALUES(%s,%s,%s,%s,%s,%s)""",
              (uuid.uuid4().hex,uid,whole,
               "cash_ad_viewer" if role=="viewer" else "cash_ad_referral",
               "Monetag "+ymid+"; "+role+"; level "+str(level)+"; NBU USD/UAH="+str(rate),
               time.time()))
            credited+=whole
    return {"credited":True,"credited_kopeks":credited,"fx_rate":str(rate)}
