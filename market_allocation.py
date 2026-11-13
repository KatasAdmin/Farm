"""Deterministic proportional allocation among same-price listings.

No floating point; ties favor smaller lots, then older lots when timestamps are available.
The caller must hold the market transaction lock.
"""


def allocate(rows, quantity):
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    if any(int(row["quantity"]) <= 0 for row in rows):
        raise ValueError("all listings must have positive quantities")
    if sum(int(row["quantity"]) for row in rows) < quantity:
        raise ValueError("insufficient listed quantity")
    remaining = quantity
    chosen = []
    for price in sorted({row["price"] for row in rows}):
        group = [row for row in rows if row["price"] == price]
        available = sum(int(row["quantity"]) for row in group)
        target = min(remaining, available)
        weights = [(row, target * int(row["quantity"]) // available,
                    target * int(row["quantity"]) % available) for row in group]
        extras = target - sum(base for _, base, _ in weights)
        weights.sort(key=lambda entry: (-entry[2], int(entry[0]["quantity"]), entry[0].get("created",0), entry[0]["id"]))
        for row, base, _ in weights:
            amount = base + int(extras > 0)
            if extras:
                extras -= 1
            if amount:
                chosen.append((row, amount))
        remaining -= target
        if not remaining:
            break
    assert sum(amount for _, amount in chosen) == quantity
    assert all(amount <= row["quantity"] for row, amount in chosen)
    return chosen
