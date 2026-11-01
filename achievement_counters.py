"""Server-authoritative cumulative achievement counters.

Only persisted events are counted; inventory balances are never used as
historical totals. Feeding is deliberately excluded until a durable feeding
event exists.
"""

SUPPORTED = ("eggs", "feathers", "milk", "chickens_bought", "geese_bought",
             "cows_bought", "market_sales", "market_purchases", "feeding")


def count(c, player_id, track):
    if track not in SUPPORTED:
        raise ValueError("Unsupported achievement counter: " + str(track))
    if track == "eggs":
        sql = "SELECT COALESCE(SUM(eggs_produced),0)::bigint AS n FROM daily_activity WHERE player_id=%s"
        return c.execute(sql, (player_id,)).fetchone()["n"]
    if track in ("feathers", "milk", "feeding"):
        kind = {"feathers": "feathers_collected", "milk": "milk_produced", "feeding": "grain_fed"}[track]
        sql = "SELECT COALESCE(SUM(amount),0)::bigint AS n FROM farm_events WHERE player_id=%s AND kind=%s"
        return c.execute(sql, (player_id, kind)).fetchone()["n"]
    if track in ("chickens_bought", "geese_bought", "cows_bought"):
        item = track.removesuffix("_bought")
        sql = """SELECT COALESCE(SUM((split_part(details,' x',2))::bigint),0)::bigint AS n
            FROM money_log WHERE player_id=%s AND kind='shop'
            AND details ~ %s"""
        return c.execute(sql, (player_id, "^" + item + r" x[0-9]+$")).fetchone()["n"]
    if track == "market_sales":
        return c.execute("SELECT COALESCE(SUM(quantity),0)::bigint AS n FROM market_trade_audit WHERE seller_id=%s", (player_id,)).fetchone()["n"]
    return c.execute("SELECT COALESCE(SUM(quantity),0)::bigint AS n FROM market_trade_audit WHERE buyer_id=%s", (player_id,)).fetchone()["n"]
