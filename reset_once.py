"""One-time prelaunch reset. Existing real Telegram Stars receipts remain in star_orders.
Requires a verified off-database snapshot; refuses to run for a grown player base.
A marker in PostgreSQL guarantees that this cannot run twice.
"""
import os
import logging
import psycopg
import boto3
from botocore.config import Config
logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
log=logging.getLogger("prelaunch_reset")
RUN_ID="prelaunch-2026-10-30-final"
CODE_HASH="2fd7af1234b12ab6eea8f3317fedea22d7d579ec4ca6a88ec021c6a985374ca8"
def main():
    if os.environ.get("RESET_CONFIRMATION")!="RESET_ONLY_PRELAUNCH_GAMEPLAY_2026_10_30":
        raise RuntimeError("Reset disabled without explicit confirmation")
    key=os.environ.get("VERIFIED_BACKUP_KEY","")
    if not key.startswith("postgres/daily/") or not key.endswith(".dump"):
        raise RuntimeError("Verified backup key missing")
    s3=boto3.client("s3",endpoint_url=os.environ["BACKUP_ENDPOINT"],
        region_name=os.environ.get("BACKUP_REGION","auto"),
        aws_access_key_id=os.environ["BACKUP_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["BACKUP_SECRET_ACCESS_KEY"],
        config=Config(s3={"addressing_style":"virtual"}))
    metadata=s3.head_object(Bucket=os.environ["BACKUP_BUCKET"],Key=key)
    if metadata["ContentLength"]<1024 or len(metadata.get("Metadata",{}).get("sha256",""))!=64:
        raise RuntimeError("S3 verified backup missing or incomplete")
    log.info("Verified pre-reset archive present: %s bytes",metadata["ContentLength"])
    with psycopg.connect(os.environ["DATABASE_URL"]) as c:
        c.execute("SELECT pg_advisory_xact_lock(1984533)")
        c.execute("""CREATE TABLE IF NOT EXISTS farm_launch_resets
           (run_id text PRIMARY KEY, reset_at timestamptz NOT NULL DEFAULT now(),
             prior_player_count integer NOT NULL, preserved_payment_count integer NOT NULL)""")
        if c.execute("SELECT 1 FROM farm_launch_resets WHERE run_id=%s",(RUN_ID,)).fetchone():
            log.info("RESET_ALREADY_COMPLETED")
            return
        count=c.execute("SELECT COUNT(*) FROM players").fetchone()[0]
        if count>10:
            raise RuntimeError("Found more than 10 players; refuse to erase possible real players")
        orders=c.execute("SELECT COUNT(*) FROM star_orders").fetchone()[0]
        log.info("Resetting %d prelaunch players, preserving %d Stars payment records",count,orders)
        # Reject outstanding unpaid invoices. Preserve real paid/refunded charge IDs and
        # Telegram IDs in star_orders for financial audit and customer support.
        c.execute("UPDATE star_orders SET status='cancelled' WHERE status='created'")
        for table in (
            "market","incubation_jobs","daily_activity","daily_claims",
            "weekly_claims","player_achievements","farm_events","money_log",
            "withdrawal_requests","trade_risk_events","market_trade_audit",
            "telegram_link_codes","login_failures"):
            c.execute("DELETE FROM "+table)
        c.execute("DELETE FROM players")
        c.execute("DELETE FROM promo_codes")
        c.execute("INSERT INTO promo_codes(code_hash,amount) VALUES(%s,1000)",(CODE_HASH,))
        c.execute("UPDATE economy SET treasury=10000 WHERE id=1")
        c.execute("UPDATE reward_emission SET total_minted=0 WHERE id=1")
        c.execute("INSERT INTO farm_launch_resets(run_id,prior_player_count,preserved_payment_count) VALUES(%s,%s,%s)",(RUN_ID,count,orders))
    log.info("RESET_OK prior_players=%d preserved_payment_receipts=%d",count,orders)
if __name__=="__main__":
    main()
