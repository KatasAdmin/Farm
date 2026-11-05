"""Exact fixed-point accounting for fractional livestock market shares.

Player inventories stay whole integers. Fractions live only in this market
ledger and are represented as billionths, so every trade conserves units.
"""

SCALE = 1_000_000_000
ANIMALS = ("chickens", "geese", "cows")


def initialize(c):
    c.execute("""CREATE TABLE IF NOT EXISTS animal_market_balances(
        player_id text NOT NULL,
        item text NOT NULL CHECK(item IN ('chickens','geese','cows')),
        fraction_units bigint NOT NULL DEFAULT 0 CHECK(fraction_units>=0 AND fraction_units<1000000000),
        ad_units bigint NOT NULL DEFAULT 0 CHECK(ad_units>=0),
        coin_fraction_units bigint NOT NULL DEFAULT 0 CHECK(coin_fraction_units>=0 AND coin_fraction_units<1000000000),
        PRIMARY KEY(player_id,item)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS animal_market_listings(
        id text PRIMARY KEY,
        seller text NOT NULL,
        item text NOT NULL CHECK(item IN ('chickens','geese','cows')),
        quantity_units bigint NOT NULL CHECK(quantity_units>=0),
        ad_units bigint NOT NULL DEFAULT 0 CHECK(ad_units>=0),
        price integer NOT NULL CHECK(price>0),
        coins_received bigint NOT NULL DEFAULT 0 CHECK(coins_received>=0),
        created double precision NOT NULL
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS animal_market_item_idx ON animal_market_listings(item,price,id) WHERE quantity_units>0")
    c.execute("CREATE INDEX IF NOT EXISTS animal_market_seller_idx ON animal_market_listings(seller,item,id) WHERE quantity_units>0")
    c.execute("ALTER TABLE animal_market_balances ADD COLUMN IF NOT EXISTS coin_fraction_units bigint NOT NULL DEFAULT 0 CHECK(coin_fraction_units>=0 AND coin_fraction_units<1000000000)")
    c.execute("""CREATE TABLE IF NOT EXISTS animal_market_trades(
        id text PRIMARY KEY,
        order_id text NOT NULL,
        listing_id text NOT NULL,
        buyer_id text NOT NULL,
        seller_id text NOT NULL,
        item text NOT NULL CHECK(item IN ('chickens','geese','cows')),
        share_units bigint NOT NULL CHECK(share_units>0),
        coin_units bigint NOT NULL CHECK(coin_units>=0),
        coins integer NOT NULL CHECK(coins>=0),
        created double precision NOT NULL
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS animal_market_trade_buyer_idx ON animal_market_trades(buyer_id,created)")
    c.execute("CREATE INDEX IF NOT EXISTS animal_market_trade_seller_idx ON animal_market_trades(seller_id,created)")
    c.execute("CREATE TABLE IF NOT EXISTS animal_market_cash_escrow(id integer PRIMARY KEY CHECK(id=1),coins bigint NOT NULL CHECK(coins>=0))")
    c.execute("INSERT INTO animal_market_cash_escrow(id,coins) VALUES(1,0) ON CONFLICT(id) DO NOTHING")
    c.execute("ALTER TABLE animal_market_trades ADD COLUMN IF NOT EXISTS order_id text")
    c.execute("ALTER TABLE animal_market_trades ADD COLUMN IF NOT EXISTS coin_units bigint NOT NULL DEFAULT 0")
    c.execute("UPDATE animal_market_trades SET order_id=id WHERE order_id IS NULL")
    c.execute("ALTER TABLE animal_market_trades ALTER COLUMN order_id SET NOT NULL")
    for item, ad_column in (("chickens", "ad_chickens"), ("geese", "ad_geese"), ("cows", "ad_cows")):
        c.execute(
            "INSERT INTO animal_market_balances(player_id,item,fraction_units,ad_units) "
            "SELECT id,%s,0,GREATEST(0,COALESCE(" + ad_column + ",0))::bigint*%s FROM players "
            "ON CONFLICT(player_id,item) DO NOTHING",
            (item, SCALE),
        )


def balance(c, player_id, item, lock=False):
    if item not in ANIMALS:
        raise ValueError("unsupported animal")
    row = c.execute(
        "SELECT fraction_units,ad_units,coin_fraction_units FROM animal_market_balances WHERE player_id=%s AND item=%s" + (" FOR UPDATE" if lock else ""),
        (player_id, item),
    ).fetchone()
    if row:
        return {"fraction_units": int(row["fraction_units"]), "ad_units": int(row["ad_units"]),
                "coin_fraction_units": int(row.get("coin_fraction_units", 0))}
    c.execute("INSERT INTO animal_market_balances(player_id,item) VALUES(%s,%s) ON CONFLICT DO NOTHING", (player_id, item))
    return {"fraction_units": 0, "ad_units": 0, "coin_fraction_units": 0}


def set_balance(c, player_id, item, fraction_units, ad_units, coin_fraction_units=None):
    if not 0 <= fraction_units < SCALE or ad_units < 0 or (coin_fraction_units is not None and not 0 <= coin_fraction_units < SCALE):
        raise ValueError("invalid animal balance")
    if coin_fraction_units is None:
        c.execute(
            "INSERT INTO animal_market_balances(player_id,item,fraction_units,ad_units) VALUES(%s,%s,%s,%s) "
            "ON CONFLICT(player_id,item) DO UPDATE SET fraction_units=EXCLUDED.fraction_units,ad_units=EXCLUDED.ad_units",
            (player_id, item, fraction_units, ad_units),
        )
    else:
        c.execute(
            "INSERT INTO animal_market_balances(player_id,item,fraction_units,ad_units,coin_fraction_units) VALUES(%s,%s,%s,%s,%s) "
            "ON CONFLICT(player_id,item) DO UPDATE SET fraction_units=EXCLUDED.fraction_units,ad_units=EXCLUDED.ad_units,coin_fraction_units=EXCLUDED.coin_fraction_units",
            (player_id, item, fraction_units, ad_units, coin_fraction_units),
        )


def add_ad_units(c, player_id, item, units):
    if item not in ANIMALS or units <= 0:
        return
    c.execute(
        "INSERT INTO animal_market_balances(player_id,item,ad_units) VALUES(%s,%s,%s) "
        "ON CONFLICT(player_id,item) DO UPDATE SET ad_units=animal_market_balances.ad_units+EXCLUDED.ad_units",
        (player_id, item, units),
    )


def tagged_count(ad_units, whole_units):
    """Round restricted animal provenance up, capped to productive units."""
    return min(whole_units, (ad_units + SCALE - 1) // SCALE)


def allocate(rows, quantity_units):
    """Allocate share units proportionally, with deterministic remainders.

    Rows must have positive integer ``quantity_units`` and stable IDs. Price
    tiers are filled cheapest first, matching the ordinary market policy.
    """
    if type(quantity_units) is not int or quantity_units <= 0:
        raise ValueError("quantity must be positive integer share units")
    if any(type(row["quantity_units"]) is not int or row["quantity_units"] <= 0 for row in rows):
        raise ValueError("all listings must have positive integer share units")
    if sum(row["quantity_units"] for row in rows) < quantity_units:
        raise ValueError("insufficient listed share units")

    remaining = quantity_units
    chosen = []
    for price in sorted({row["price"] for row in rows}):
        group = [row for row in rows if row["price"] == price]
        available = sum(row["quantity_units"] for row in group)
        target = min(remaining, available)
        shares = [
            (row, target * row["quantity_units"] // available,
             target * row["quantity_units"] % available)
            for row in group
        ]
        extras = target - sum(base for _, base, _ in shares)
        shares.sort(key=lambda entry: (-entry[2], str(entry[0]["id"])))
        for index, (row, base, _) in enumerate(shares):
            amount = base + int(index < extras)
            if amount:
                chosen.append((row, amount))
        remaining -= target
        if not remaining:
            break
    if sum(amount for _, amount in chosen) != quantity_units:
        raise AssertionError("share allocation did not conserve quantity")
    if any(amount > row["quantity_units"] for row, amount in chosen):
        raise AssertionError("share allocation exceeded a listing")
    return chosen


def split_payment(rows, total_units, total_coins, units_key="units"):
    """Split integer coins by fractional share weights without losing coins."""
    if total_units <= 0 or total_coins < 0:
        raise ValueError("invalid payment totals")
    if sum(row[units_key] for row in rows) != total_units:
        raise ValueError("payment weights do not match total shares")
    amounts = [total_coins * row[units_key] // total_units for row in rows]
    extra = total_coins - sum(amounts)
    order = sorted(
        range(len(rows)),
        key=lambda i: (-(total_coins * rows[i][units_key] % total_units), str(rows[i]["id"])),
    )
    for index in order[:extra]:
        amounts[index] += 1
    if sum(amounts) != total_coins:
        raise AssertionError("coin allocation did not conserve payment")
    return [(row, amount) for row, amount in zip(rows, amounts)]


def transfer_tagged_units(tagged_units, listing_units, sold_units):
    """Move a conservative share of restricted provenance with a listing.

    Ceiling the partial transfer can over-restrict by at most one fixed-point
    unit, but cannot leave sold restricted value untagged. Selling the full
    listing always transfers its exact remaining tag balance.
    """
    if min(tagged_units, listing_units, sold_units) < 0 or tagged_units > listing_units or sold_units > listing_units:
        raise ValueError("invalid restricted share quantities")
    if not sold_units or not tagged_units:
        return 0
    if sold_units == listing_units:
        return tagged_units
    return min(tagged_units, (tagged_units * sold_units + listing_units - 1) // listing_units)


def reserve_tagged_units(tagged_units, available_units, listing_units):
    """Reserve a conservative share of existing provenance for a new listing."""
    if min(tagged_units, available_units, listing_units) < 0 or listing_units > available_units or tagged_units > available_units:
        raise ValueError("invalid listing provenance quantities")
    if not listing_units or not tagged_units:
        return 0
    if listing_units == available_units:
        return tagged_units
    return min(tagged_units, (tagged_units * listing_units + available_units - 1) // available_units)


def display_quantity(units):
    """Convert fixed-point shares to a JSON-friendly decimal quantity."""
    return units / SCALE


def apply_balance(whole_units, fraction_units, delta_units):
    """Apply a signed share delta to an integer inventory plus its fraction."""
    if type(whole_units) is not int or whole_units < 0:
        raise ValueError("whole inventory must be a nonnegative integer")
    if type(fraction_units) is not int or not 0 <= fraction_units < SCALE:
        raise ValueError("fraction must be in [0, SCALE)")
    total = whole_units * SCALE + fraction_units + delta_units
    if total < 0:
        raise ValueError("share debit exceeds owned animals")
    whole, fraction = divmod(total, SCALE)
    return whole, fraction
