"""PostgreSQL USD micro-dollar wallet primitives (isolated staging subsystem).

Not initialized by the existing app; existing UAH balances are NOT changed.
Every mutation must run inside one database transaction. Provider settlement
verification and account-level eligibility checks belong to the caller.
"""
import time
import uuid

EARNED = {"task_reward", "confirmed_ad_reward", "confirmed_referral"}
NON_WITHDRAWABLE = {"stars_purchase", "card_purchase", "promo", "daily_bonus", "game_purchase"}

def initialize(c):
    c.execute("""CREATE TABLE IF NOT EXISTS bot_usd_wallets(
        uid bigint PRIMARY KEY CHECK(uid>0),
        spend_only_micro bigint NOT NULL DEFAULT 0 CHECK(spend_only_micro>=0),
        earned_micro bigint NOT NULL DEFAULT 0 CHECK(earned_micro>=0),
        reserved_micro bigint NOT NULL DEFAULT 0 CHECK(reserved_micro>=0),
        CHECK(reserved_micro<=earned_micro))""")
    c.execute("""CREATE TABLE IF NOT EXISTS bot_usd_cashouts(
        id text PRIMARY KEY,
        uid bigint NOT NULL,
        amount_micro bigint NOT NULL CHECK(amount_micro>0),
        state text NOT NULL CHECK(state IN ('pending','paid','cancelled')),
        created double precision NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS bot_usd_wallet_operations(
        id text PRIMARY KEY,
        uid bigint NOT NULL,
        kind text NOT NULL,
        amount_micro bigint NOT NULL,
        created double precision NOT NULL)""")

def snapshot(c,uid):
    if type(uid) is not int or uid<=0:
        raise ValueError("Invalid Telegram user id")
    c.execute("INSERT INTO bot_usd_wallets(uid) VALUES(%s) ON CONFLICT DO NOTHING",(uid,))
    return c.execute("SELECT * FROM bot_usd_wallets WHERE uid=%s FOR UPDATE",(uid,)).fetchone()

def _amount(micro):
    if type(micro) is not int or micro<=0 or micro>10**17:
        raise ValueError("Invalid micro-USD amount")

def _event(c, uid, key, kind, micro):
    if not isinstance(key,str) or not 6<=len(key)<=128:
        raise ValueError("Stable unique payment or operation id required")
    return bool(c.execute("""INSERT INTO bot_usd_wallet_operations VALUES(%s,%s,%s,%s,%s)
      ON CONFLICT DO NOTHING RETURNING id""",(key,uid,kind,micro,time.time())).fetchone())

def credit_verified(c,uid,key,source,micro):
    """Caller must first verify external receipt/referral/task settlement."""
    _amount(micro)
    if source not in EARNED|NON_WITHDRAWABLE:
        raise ValueError("Unsupported USD funds source")
    snapshot(c,uid)
    if not _event(c,uid,key,source,micro):
        return False
    column="earned_micro" if source in EARNED else "spend_only_micro"
    c.execute("UPDATE bot_usd_wallets SET "+column+"="+column+"+%s WHERE uid=%s",(micro,uid))
    return True

def reserve_cashout(c,uid,payout_id,micro):
    _amount(micro)
    row=snapshot(c,uid)
    if row['earned_micro']-row['reserved_micro']<micro:
        raise ValueError("Not enough verified earnings")
    if not _event(c,uid,"reserve:"+payout_id,"cashout_reserve",micro):
        return False
    c.execute("INSERT INTO bot_usd_cashouts VALUES(%s,%s,%s,'pending',%s)",
              (payout_id,uid,micro,time.time()))
    c.execute("UPDATE bot_usd_wallets SET reserved_micro=reserved_micro+%s WHERE uid=%s",(micro,uid))
    return True

def finalize_cashout(c,uid,payout_id,paid):
    if type(paid) is not bool:
        raise ValueError("Cashout decision must be explicit")
    row=snapshot(c,uid)
    intent=c.execute("""UPDATE bot_usd_cashouts SET state=%s WHERE id=%s AND uid=%s AND state='pending'
                      RETURNING amount_micro""",('paid' if paid else 'cancelled',payout_id,uid)).fetchone()
    if not intent:return False
    n=intent['amount_micro']
    if n>row['reserved_micro']:raise RuntimeError("Ledger reservation invariant violated")
    if not _event(c,uid,("paid:" if paid else "cancel:")+payout_id,
                  "cashout_paid" if paid else "cashout_cancelled",n):
        raise RuntimeError("Ledger payout replay invariant violated")
    if paid:
        c.execute("""UPDATE bot_usd_wallets
          SET earned_micro=earned_micro-%s,reserved_micro=reserved_micro-%s
          WHERE uid=%s""",(n,n,uid))
    else:
        c.execute("UPDATE bot_usd_wallets SET reserved_micro=reserved_micro-%s WHERE uid=%s",(n,uid))
    return True
