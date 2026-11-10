"""One-time, idempotent FARM-only general test reset.
Never deletes bot accounts, external payments, or global monetary accounting.
Executed explicitly as a Railway pre-deploy task, not at import/startup.
"""
import os
import psycopg
from psycopg import sql

RUN_ID = "general-test-farm-2026-11-10"
EXACT = {
    "players", "market", "incubation_jobs", "trade_risk_events",
    "market_trade_audit", "daily_activity", "farm_events", "daily_claims",
    "weekly_claims", "referral_codes", "referrals", "referral_rewards",
    "staged_achievement_claims", "player_achievements",
    "telegram_link_codes", "login_failures", "registration_limits",
}
PROTECTED = {
    "economy", "reward_emission", "farm_launch_resets",
    "farm_admin_identity", "money_log", "star_orders",
    "stars_refund_intents", "withdrawal_requests", "support_tickets",
    "telegram_processed_updates", "telegram_processed_messages",
    "promo_codes",
}
with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
    with conn.cursor() as c:
        c.execute("SELECT pg_advisory_xact_lock(1984533)")
        c.execute("SET LOCAL statement_timeout='120s'")
        c.execute("SELECT to_regclass('public.farm_launch_resets')")
        if c.fetchone()[0] is None:
            raise RuntimeError("Expected reset audit table absent; refusing to wipe")
        c.execute("SELECT 1 FROM farm_launch_resets WHERE run_id=%s", (RUN_ID,))
        if c.fetchone():
            print("Farm reset already completed; no changes")
        else:
            c.execute("SELECT count(*) FROM players")
            players_before = c.fetchone()[0]
            c.execute("SELECT count(*) FROM star_orders")
            payments_before = c.fetchone()[0]
            c.execute("""
                SELECT table_name, column_name
                FROM information_schema.columns
                WHERE table_schema='public'
            """)
            columns = {}
            for table, column in c.fetchall():
                columns.setdefault(table, set()).add(column)
            target = set()
            for table, cols in columns.items():
                if table in PROTECTED or table.startswith(("bot_", "task_", "star_", "telegram_processed_")):
                    continue
                if table in EXACT or ("player_id" in cols and (table.startswith(("farm_", "field_", "incubat", "monetag_", "ad_", "referral_", "daily_", "weekly_")) or table in {"achievement_claims","reward_grants"})):
                    target.add(table)
            # Never extend to other tables through CASCADE; fail atomically instead.
            if "players" not in target or "market" not in target:
                raise RuntimeError("Farm schema not as expected; refusing to wipe")
            c.execute(sql.SQL("TRUNCATE TABLE {} RESTRICT").format(
                sql.SQL(", ").join(sql.Identifier("public", t) for t in sorted(target))
            ))
            c.execute("""
                INSERT INTO farm_launch_resets(run_id, prior_player_count, preserved_payment_count)
                VALUES (%s, %s, %s)
            """, (RUN_ID, players_before, payments_before))
            c.execute("SELECT count(*) FROM players")
            if c.fetchone()[0] != 0:
                raise RuntimeError("Reset verification failed; rolling back")
            print("FARM GENERAL TEST RESET COMPLETE", "prior_players=", players_before,
                  "preserved_payment_records=", payments_before, "tables=", sorted(target))
