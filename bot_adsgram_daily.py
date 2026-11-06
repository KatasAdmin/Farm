"""AdsGram Reward URL confirmations and owner-approved daily publisher allocation.

The AdsGram Reward URL provides Telegram user ID but no per-impression price
or unique event ID. Credit ONLY publisher-reconciled day totals, never browser
SDK success. Wallet risk remains with the owner.
"""
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_FLOOR

from bot_economy import monetag_cash_allocation
from bot_cash_ad_credits import nbu_usd_uah, FxUnavailable


def initialize(c):
    c.execute("""CREATE TABLE IF NOT EXISTS bot_adsgram_attempts(
      id text PRIMARY KEY, uid bigint NOT NULL, started_at double precision NOT NULL,
      confirmed_at double precision, state text NOT NULL CHECK(state IN ('pending','confirmed','cancelled','expired')),
      referral_chain jsonb NOT NULL DEFAULT '[]'::jsonb)""")
    c.execute("""CREATE INDEX IF NOT EXISTS bot_adsgram_attempt_uid
      ON bot_adsgram_attempts(uid,state,started_at DESC)""")
    c.execute("""CREATE TABLE IF NOT EXISTS bot_adsgram_farm_attempts(
      id text PRIMARY KEY,uid bigint NOT NULL,player_id text NOT NULL,
      item text NOT NULL,started_at double precision NOT NULL,
      confirmed_at double precision,state text NOT NULL CHECK(state IN ('pending','confirmed','cancelled','expired')) )""")
    c.execute("""CREATE INDEX IF NOT EXISTS bot_adsgram_farm_attempt_uid
      ON bot_adsgram_farm_attempts(uid,state,started_at DESC)""")
    c.execute("""CREATE TABLE IF NOT EXISTS bot_adsgram_daily_settlements(
      utc_day text PRIMARY KEY, publisher_usd numeric(25,12) NOT NULL CHECK(publisher_usd>=0),
      impressions integer NOT NULL CHECK(impressions>0), credited_kopeks bigint NOT NULL DEFAULT 0,
      nbu_rate numeric(14,6) NOT NULL, created_at double precision NOT NULL,
      owner_uid bigint NOT NULL, details text NOT NULL DEFAULT '')""")
    c.execute("""CREATE TABLE IF NOT EXISTS bot_adsgram_daily_credits(
      utc_day text NOT NULL REFERENCES bot_adsgram_daily_settlements(utc_day),
      uid bigint NOT NULL, role text NOT NULL CHECK(role IN ('viewer','referral')),
      level integer NOT NULL, earned_usd numeric(28,18) NOT NULL,
      credited_kopeks bigint NOT NULL,
      PRIMARY KEY(utc_day,uid,role,level))""")


def prepare(c,uid):
    from psycopg.types.json import Jsonb
    from bot_monetag_cash import verified_bot_referral_chain
    now=time.time()
    c.execute("SELECT pg_advisory_xact_lock(%s)",(125492051,))
    if not c.execute("SELECT 1 FROM bot_accounts WHERE uid=%s",(uid,)).fetchone():
        raise ValueError("Player account missing")
    c.execute("""UPDATE bot_adsgram_attempts SET state='expired'
      WHERE uid=%s AND state='pending' AND started_at<%s""",(uid,now-600))
    existing=c.execute("""SELECT id FROM bot_adsgram_attempts WHERE uid=%s
      AND state='pending' LIMIT 1""",(uid,)).fetchone()
    if not existing:
        existing=c.execute("""SELECT id FROM bot_adsgram_farm_attempts WHERE uid=%s
          AND state='pending' AND started_at>%s LIMIT 1""",(uid,now-600)).fetchone()
    if existing:raise ValueError("Previous AdsGram attempt is still pending")
    attempt=uuid.uuid4().hex
    chain=verified_bot_referral_chain(c,uid)
    c.execute("""INSERT INTO bot_adsgram_attempts(id,uid,started_at,state,referral_chain)
      VALUES(%s,%s,%s,'pending',%s)""",(attempt,uid,now,Jsonb(chain)))
    return {"ok":True,"attempt_id":attempt}


def cancel(c,uid,attempt_id):
    c.execute("""UPDATE bot_adsgram_attempts SET state='cancelled'
      WHERE id=%s AND uid=%s AND state='pending'""",(attempt_id,uid))


def confirm(c,uid):
    # Reward URL has no unique event ID. Match exactly one fresh prepared attempt.
    # A duplicate callback cannot confirm the same attempt again.
    now=time.time()
    c.execute("SELECT pg_advisory_xact_lock(%s)",(125492051,))
    cash=c.execute("""SELECT id,started_at FROM bot_adsgram_attempts
      WHERE uid=%s AND state='pending' AND started_at BETWEEN %s AND %s
      ORDER BY started_at LIMIT 1 FOR UPDATE""",(uid,now-600,now)).fetchone()
    farm=c.execute("""SELECT id,player_id,item,started_at FROM bot_adsgram_farm_attempts
      WHERE uid=%s AND state='pending' AND started_at BETWEEN %s AND %s
      ORDER BY started_at LIMIT 1 FOR UPDATE""",(uid,now-600,now)).fetchone()
    if cash and farm:
        # Ambiguous callbacks cannot be safely assigned.
        return {"ok":True,"confirmed":False,"reason":"ambiguous_active_attempts"}
    if farm:return _confirm_farm(c,farm,now)
    if not cash:return {"ok":True,"confirmed":False,"reason":"no_fresh_attempt"}
    c.execute("""UPDATE bot_adsgram_attempts SET state='confirmed',confirmed_at=%s
      WHERE id=%s AND state='pending'""",(now,cash["id"]))
    return {"ok":True,"confirmed":True,"reward":"cash"}



def prepare_farm(c,uid,player_id,item):
    # Both cash and farm AdsGram placements use one Reward URL per block.
    from monetag_ads import REWARDS
    if item not in REWARDS:raise ValueError("Unknown farm ad resource")
    now=time.time()
    c.execute("SELECT pg_advisory_xact_lock(%s)",(125492051,))
    c.execute("""UPDATE bot_adsgram_farm_attempts SET state='expired'
      WHERE uid=%s AND state='pending' AND started_at<%s""",(uid,now-600))
    existing=c.execute("""SELECT id FROM bot_adsgram_farm_attempts
      WHERE uid=%s AND state='pending' LIMIT 1""",(uid,)).fetchone()
    if not existing:
        existing=c.execute("""SELECT id FROM bot_adsgram_attempts
          WHERE uid=%s AND state='pending' AND started_at>%s LIMIT 1""",(uid,now-600)).fetchone()
    if existing:raise ValueError("Previous AdsGram attempt still active")
    aid=uuid.uuid4().hex
    c.execute("""INSERT INTO bot_adsgram_farm_attempts
      (id,uid,player_id,item,started_at,state)
      VALUES(%s,%s,%s,%s,%s,'pending')""",(aid,uid,player_id,item,now))
    return {"ok":True,"attempt_id":aid}


def cancel_farm(c,uid,attempt_id):
    c.execute("""UPDATE bot_adsgram_farm_attempts SET state='cancelled'
      WHERE id=%s AND uid=%s AND state='pending'""",(attempt_id,uid))


def farm_status(c,player_id):
    from monetag_ads import REWARDS
    totals={}
    for item,(views,quantity) in REWARDS.items():
        row=c.execute("""SELECT COUNT(*) AS n FROM bot_adsgram_farm_attempts
           WHERE player_id=%s AND item=%s AND state='confirmed'""",(player_id,item)).fetchone()
        confirmed=int(row["n"])
        totals[item]={"views":views,"quantity":quantity,
                      "progress":confirmed%views,"confirmed":confirmed}
    history=c.execute("""SELECT id,item,state,started_at FROM bot_adsgram_farm_attempts
      WHERE player_id=%s ORDER BY started_at DESC LIMIT 12""",(player_id,)).fetchall()
    return {"rewards":totals,"history":[{"ymid":r["id"],"item":r["item"],
            "state":"credited" if r["state"]=="confirmed" else r["state"],
            "created_at":r["started_at"]} for r in history]}


def _confirm_farm(c,row,now):
    from monetag_ads import REWARDS
    # Only invoked by protected AdsGram Reward URL endpoint.
    item=row["item"]
    views,qty=REWARDS[item]
    count=c.execute("""SELECT COUNT(*) AS n FROM bot_adsgram_farm_attempts
      WHERE player_id=%s AND item=%s AND state='confirmed'""",(row["player_id"],item)).fetchone()["n"]
    c.execute("""UPDATE bot_adsgram_farm_attempts SET state='confirmed',confirmed_at=%s
      WHERE id=%s AND state='pending'""",(now,row["id"]))
    if (int(count)+1)%views==0:
        c.execute("""INSERT INTO monetag_reward_grants
          (id,player_id,item,quantity,created)
          VALUES(%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING""",
          ("adsgram-"+row["id"],row["player_id"],item,qty,now))
    return {"ok":True,"confirmed":True,"reward":"farm","item":item}


def _day(date_text):
    if not isinstance(date_text,str):raise ValueError("Date must be YYYY-MM-DD")
    try: day=datetime.strptime(date_text,"%Y-%m-%d").date()
    except ValueError:raise ValueError("Date must be YYYY-MM-DD")
    if day.isoformat()!=date_text:raise ValueError("Invalid date")
    if day>=datetime.now(timezone.utc).date():raise ValueError("Only completed UTC dates can settle")
    return date_text


def settle_day(c,day,revenue_usd,provider_impressions,owner_uid):
    """Owner-reconciled daily USD total allocated by matched confirmed views.

    Checks CSV/dashboard total vs tracked callbacks. Transaction must commit
    atomically, and cannot ever distribute the same day's revenue twice.
    """
    day=_day(day)
    try: revenue=Decimal(str(revenue_usd))
    except (ValueError,TypeError,InvalidOperation):raise ValueError("Invalid publisher revenue")
    if not revenue.is_finite() or revenue<=0 or revenue>Decimal("100000"):
        raise ValueError("Invalid positive publisher USD revenue")
    if not isinstance(provider_impressions,int) or isinstance(provider_impressions,bool) or provider_impressions<1:
        raise ValueError("Invalid publisher impressions")
    c.execute("SELECT pg_advisory_xact_lock(%s)",(125492051,))
    old=c.execute("SELECT 1 FROM bot_adsgram_daily_settlements WHERE utc_day=%s",(day,)).fetchone()
    if old:raise ValueError("Day already reconciled; never pay twice")
    start=datetime.strptime(day,"%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
    rows=c.execute("""SELECT uid,referral_chain FROM bot_adsgram_attempts
      WHERE state='confirmed' AND confirmed_at>=%s AND confirmed_at<%s
      ORDER BY confirmed_at,id FOR UPDATE""",(start,start+86400)).fetchall()
    if len(rows)!=provider_impressions:
        raise ValueError("Publisher impressions do not match confirmed user events; review before credit")
    rate=nbu_usd_uah(c)
    per_view=revenue/Decimal(provider_impressions)
    ledger={}
    for r in rows:
        alloc=monetag_cash_allocation(per_view,tuple(r["referral_chain"]))
        uid=int(r["uid"])
        for key,who,level,usd in [("viewer",uid,0,Decimal(alloc["viewer_usd"]))]+[
           ("referral",int(ref["uid"]),int(ref["level"]),Decimal(ref["usd"]))
           for ref in alloc["referrals"]]:
            tup=(who,key,level)
            ledger[tup]=ledger.get(tup,Decimal(0))+usd
    c.execute("""INSERT INTO bot_adsgram_daily_settlements
      (utc_day,publisher_usd,impressions,nbu_rate,created_at,owner_uid)
      VALUES(%s,%s,%s,%s,%s,%s)""",(day,revenue,provider_impressions,rate,time.time(),owner_uid))
    credited_total=0
    for (uid,role,level),earned in sorted(ledger.items()):
        if earned<=0:continue
        if not c.execute("SELECT 1 FROM bot_accounts WHERE uid=%s",(uid,)).fetchone():
            raise ValueError("Referrer account missing; settlement requires reconciliation")
        c.execute("""INSERT INTO bot_cash_ad_fraction(uid,remainder) VALUES(%s,0)
          ON CONFLICT(uid) DO NOTHING""",(uid,))
        fraction=c.execute("""SELECT remainder FROM bot_cash_ad_fraction
          WHERE uid=%s FOR UPDATE""",(uid,)).fetchone()
        amount=Decimal(str(fraction["remainder"]))+earned*rate*100
        whole=int(amount.to_integral_value(rounding=ROUND_FLOOR))
        if whole<0 or whole>9223372036854775807:raise ValueError("Amount out of range")
        c.execute("UPDATE bot_cash_ad_fraction SET remainder=%s WHERE uid=%s",
                  (amount-Decimal(whole),uid))
        c.execute("""INSERT INTO bot_adsgram_daily_credits
          (utc_day,uid,role,level,earned_usd,credited_kopeks)
          VALUES(%s,%s,%s,%s,%s,%s)""",(day,uid,role,level,earned,whole))
        if whole:
            c.execute("UPDATE bot_accounts SET available=available+%s WHERE uid=%s",(whole,uid))
            c.execute("""INSERT INTO bot_ledger(id,uid,delta,kind,details,created)
              VALUES(%s,%s,%s,%s,%s,%s)""",(
               uuid.uuid4().hex,uid,whole,"adsgram_daily_"+role,
               "AdsGram "+day+" level "+str(level)+" NBU="+str(rate),time.time()))
        credited_total+=whole
    c.execute("UPDATE bot_adsgram_daily_settlements SET credited_kopeks=%s WHERE utc_day=%s",
              (credited_total,day))
    return {"ok":True,"day":day,"provider_impressions":provider_impressions,
            "publisher_usd":str(revenue),"credited_kopeks":credited_total,
            "platform_usd_at_least":str(revenue*Decimal("0.35"))}
