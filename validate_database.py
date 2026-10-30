"""Restore only into a disposable local server, then exercise real market handlers.

Called by the backup job after upload/download checksum verification. No application
handler ever receives the production DATABASE_URL.
"""
import asyncio
import json
import logging
import os
import pathlib
import pwd
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode

log = logging.getLogger("farm_backup")


def run(args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, text=True,
                          timeout=180, **kwargs)


def validate_archive(archive):
    with tempfile.TemporaryDirectory(prefix="farm-restore-check-") as directory:
        root = pathlib.Path(directory)
        user = pwd.getpwnam("postgres")
        os.chown(root, user.pw_uid, user.pw_gid)
        data = root / "data"
        as_postgres = ["su-exec", "postgres"] if os.geteuid() == 0 else []
        run(as_postgres + ["initdb", "-D", str(data), "-U", "postgres", "--auth=trust"])
        # Unix socket only: this temporary server cannot receive public traffic.
        run(as_postgres + ["pg_ctl", "-D", str(data), "-l", str(root / "server.log"),
                          "-o", f"-h '' -k {directory} -p 55439 -c max_connections=40", "start"])
        try:
            def uri(database):
                return "postgresql:///" + database + "?" + urlencode(
                    {"host": directory, "port": 55439, "user": "postgres"})
            import psycopg
            with psycopg.connect(uri("postgres"), autocommit=True) as c:
                c.execute("CREATE DATABASE restored_backup")
                c.execute("CREATE DATABASE market_validation")
            run(["pg_restore", "--exit-on-error", "--no-owner", "--no-privileges",
                 "--dbname=" + uri("restored_backup"), str(archive)])
            # Run in a read-only transaction, even on the disposable restored copy.
            with psycopg.connect(uri("restored_backup")) as c:
                c.execute("SET TRANSACTION READ ONLY")
                players = c.execute("SELECT count(*) FROM players").fetchone()[0]
                c.execute("SELECT count(*) FROM star_orders").fetchone()
                c.execute("SELECT count(*) FROM market").fetchone()
                tables = c.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'").fetchone()[0]
            log.info("RESTORE_OK tables=%s players=%s", tables, players)
            # Isolate all game code and environment changes in a child process.
            env = {k: v for k, v in os.environ.items()
                   if not k.startswith(("BACKUP_", "TELEGRAM_", "FARM_", "RAILWAY_"))
                   and k != "DATABASE_URL"}
            env["DATABASE_URL"] = uri("market_validation")
            env["PYTHONUNBUFFERED"] = "1"
            result = run([os.sys.executable, __file__, "--market"], env=env)
            log.info(result.stdout.strip())
        finally:
            run(as_postgres + ["pg_ctl", "-D", str(data), "-m", "fast", "stop"])


def validate_market():
    # Reject any accidental production URL before importing application code.
    from psycopg.conninfo import conninfo_to_dict
    config = conninfo_to_dict(os.environ["DATABASE_URL"])
    assert config["dbname"] == "market_validation"
    assert config["host"].startswith("/tmp/farm-restore-check-")
    import main
    from fastapi import HTTPException

    async def initialize():
        async with main.lifespan(main.app):
            pass
    asyncio.run(initialize())
    now = time.time()

    def seed(name, coins=100, eggs=0):
        with main.db() as c:
            c.execute("""INSERT INTO players(id,name,token,coins,grain,chickens,eggs,
                last_tick,production_model,egg_at,fed_hens,created_at)
                VALUES(%s,%s,%s,%s,0,0,%s,%s,4,%s,0,%s)""",
                (name, name, name, coins, eggs, now, now + main.CYCLE, now))

    def totals():
        with main.db() as c:
            p = c.execute("SELECT sum(coins) AS coins,sum(eggs) AS eggs,min(coins) AS min_coins,min(eggs) AS min_eggs FROM players").fetchone()
            listed = c.execute("SELECT coalesce(sum(quantity),0) AS n,min(quantity) AS minimum FROM market").fetchone()
            treasury = c.execute("SELECT treasury FROM economy WHERE id=1").fetchone()["treasury"]
        assert p["min_coins"] >= 0 and p["min_eggs"] >= 0
        assert listed["minimum"] is None or listed["minimum"] >= 0
        return (p["coins"] + treasury, p["eggs"] + listed["n"])

    def buy(name):
        started = time.monotonic()
        try:
            main.buy(main.Request(item="eggs", amount=10), authorization="Bearer " + name)
            status = 200
        except HTTPException as error:
            assert error.status_code == 400
            status = 400
        return status, time.monotonic() - started

    for n in range(20):
        name = "seller" + str(n)
        seed(name, eggs=50)
        main.sell(main.Request(item="eggs", amount=50), authorization="Bearer " + name)
    buyers = ["buyer" + str(n) for n in range(100)]
    for name in buyers:
        seed(name)
    before = totals()
    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(buy, buyers))
    assert all(status == 200 for status, _ in results), results
    assert totals() == before
    with ThreadPoolExecutor(max_workers=20) as pool:
        rejected = list(pool.map(buy, buyers))
    assert all(status == 400 for status, _ in rejected)
    assert totals() == before

    # Concurrent requests for one wallet must not spend its last coins twice.
    seed("lastseller", eggs=100)
    seed("lastbuyer", coins=50)
    main.sell(main.Request(item="eggs", amount=100), authorization="Bearer lastseller")
    before = totals()
    with ThreadPoolExecutor(max_workers=20) as pool:
        shared = list(pool.map(buy, ["lastbuyer"] * 20))
    assert sum(status == 200 for status, _ in shared) == 5
    assert totals() == before
    with main.db() as c:
        assert c.execute("SELECT coins FROM players WHERE id='lastbuyer'").fetchone()["coins"] == 0
        assert c.execute("SELECT coalesce(sum(delta),0) AS n FROM money_log").fetchone()["n"] == 0
    durations = sorted(seconds for _, seconds in results)
    print("MARKET_LOAD_OK " + json.dumps({"players": 122, "workers": 20,
          "purchase_attempts": 220, "successful": 105, "expected_rejections": 115,
          "coins_and_goods_conserved": True, "p95_seconds": round(durations[94], 3)}))


if __name__ == "__main__":
    if os.sys.argv[1:] == ["--market"]:
        validate_market()
    else:
        raise SystemExit("Run from the backup job; production targets are not accepted.")
