"""Read-only Stars payment reconciliation for prelaunch/staging.

Never repairs balances automatically: external Telegram refunds require
independent confirmation before any financial ledger mutation.
"""
import os
import sys
import psycopg
from psycopg.rows import dict_row


QUERIES = {
    "paid_without_charge": """
        SELECT id,player_id,stars,coins,status
        FROM star_orders WHERE status='paid' AND (charge_id IS NULL OR charge_id='')
        ORDER BY created DESC LIMIT 100
    """,
    "duplicate_charge": """
        SELECT charge_id,COUNT(*) AS n FROM star_orders
        WHERE charge_id IS NOT NULL GROUP BY charge_id HAVING COUNT(*)>1
        LIMIT 100
    """,
    "paid_without_credit_log": """
        SELECT o.id,o.player_id,o.coins,o.stars FROM star_orders o
        WHERE o.status='paid' AND NOT EXISTS (
          SELECT 1 FROM money_log m WHERE m.player_id=o.player_id
            AND m.kind='stars_purchase'
            AND m.details='Покупка за '||o.stars::text||' Stars'
            AND m.delta=o.coins
            AND m.created BETWEEN o.created AND o.created+86400
        ) ORDER BY o.created DESC LIMIT 100
    """,
    "refunded_without_debit_log": """
        SELECT o.id,o.player_id,o.coins,o.stars FROM star_orders o
        WHERE o.status='refunded'
          AND EXISTS (SELECT 1 FROM players p WHERE p.id=o.player_id)
          AND NOT EXISTS (
            SELECT 1 FROM money_log m WHERE m.player_id=o.player_id
              AND m.kind='stars_refund'
              AND m.details='Возврат покупки — '||o.stars::text||' ⭐'
              AND m.delta=-o.coins
          ) ORDER BY o.created DESC LIMIT 100
    """,
}


def run(url):
    with psycopg.connect(url, row_factory=dict_row, connect_timeout=10) as conn:
        with conn.cursor() as c:
            c.execute("BEGIN READ ONLY")
            for label, sql in QUERIES.items():
                rows=c.execute(sql).fetchall()
                print(label + ": " + str(len(rows)) + " flagged")
                for row in rows:
                    print("  " + repr(dict(row)))
            conn.rollback()


if __name__ == "__main__":
    url=os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL required; this script never writes")
    run(url)
