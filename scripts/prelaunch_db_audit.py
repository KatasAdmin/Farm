"""Read-only prelaunch database checks. Requires DATABASE_URL. Never modifies data.

Run against a staging database first:
    python scripts/prelaunch_db_audit.py
"""
import os
import sys

import psycopg
from psycopg.rows import dict_row

CHECKS = {
    "players": "SELECT COUNT(*) AS n FROM players",
    "negative_coins": "SELECT COUNT(*) AS n FROM players WHERE coins < 0",
    "negative_inventory": """SELECT COUNT(*) AS n FROM players WHERE
        grain < 0 OR eggs < 0 OR chickens < 0 OR COALESCE(geese,0) < 0
        OR COALESCE(cows,0) < 0 OR COALESCE(milk,0) < 0
        OR COALESCE(feathers,0) < 0""",
    "invalid_market": "SELECT COUNT(*) AS n FROM market WHERE quantity <= 0 OR price <= 0",
    "duplicate_staged_claims": """SELECT COUNT(*) AS n FROM (
        SELECT player_id, track, threshold FROM staged_achievement_claims
        GROUP BY player_id,track,threshold HAVING COUNT(*) > 1
    ) duplicates""",
    "invalid_staged_xp": "SELECT COUNT(*) AS n FROM staged_achievement_claims WHERE xp <= 0",
    "negative_treasury": "SELECT COUNT(*) AS n FROM economy WHERE treasury < 0",
    "invalid_money_source_allocations": """SELECT COUNT(*) AS n
        FROM farm_money_sources s JOIN money_log m ON m.id=s.log_id
        WHERE s.bonus + s.purchased + s.earned <> m.delta""",
    "orphan_money_sources": """SELECT COUNT(*) AS n FROM farm_money_sources s
        LEFT JOIN money_log m ON m.id=s.log_id WHERE m.id IS NULL""",
    "orphan_farm_bot_transfers": """SELECT COUNT(*) AS n FROM farm_bot_transfers t
        LEFT JOIN players p ON p.id=t.player_id WHERE p.id IS NULL""",
    "invalid_farm_bot_transfers": """SELECT COUNT(*) AS n
        FROM farm_bot_transfers WHERE amount < 100""",
    "orphan_staged_claims": """SELECT COUNT(*) AS n FROM staged_achievement_claims a
        LEFT JOIN players p ON p.id=a.player_id WHERE p.id IS NULL""",
    "pending_withdrawals": "SELECT COUNT(*) AS n FROM withdrawal_requests WHERE status = 'pending'",
}

def main():
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is required", file=sys.stderr)
        return 2
    errors = []
    with psycopg.connect(url, row_factory=dict_row, connect_timeout=10) as conn:
        with conn.cursor() as cursor:
            cursor.execute("BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            for name, sql in CHECKS.items():
                try:
                    # A savepoint allows reporting other checks after a missing column/table.
                    cursor.execute("SAVEPOINT audit_check")
                    cursor.execute(sql)
                    count = cursor.fetchone()["n"]
                    cursor.execute("RELEASE SAVEPOINT audit_check")
                    print(f"{name}: {count}")
                    if name.startswith(("negative_", "invalid_", "duplicate_", "orphan_")) and count:
                        errors.append(f"{name}: {count}")
                except psycopg.Error as exc:
                    cursor.execute("ROLLBACK TO SAVEPOINT audit_check")
                    errors.append(f"{name}: {exc.__class__.__name__}")
                    print(f"{name}: CHECK FAILED", file=sys.stderr)
            cursor.execute("ROLLBACK")
    if errors:
        print("Audit failed: " + ", ".join(errors), file=sys.stderr)
        return 1
    print("Read-only database integrity checks passed; this is not a payment audit.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
