"""Sequential achievement stage definitions and pure progression helpers.

This module has no database side effects. Claiming rewards must be done in a
transaction with a unique (player, track, stage) constraint.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class Stage:
    threshold: int
    xp: int

TRACKS = {
    "eggs": (1, 3, 10, 25, 50, 100),
    "feathers": (1, 3, 10, 25, 50, 100),
    "milk": (1, 3, 10, 25, 50, 100),
    "chickens_bought": (1, 3, 10, 25, 50),
    "geese_bought": (1, 3, 10, 25, 50),
    "cows_bought": (1, 3, 10, 25, 50),
    "market_sales": (1, 3, 10, 25, 50, 100),
    "market_purchases": (1, 3, 10, 25, 50, 100),
    "feeding": (1, 3, 10, 25, 50, 100),
}

def stages(track):
    """Return immutable cumulative milestones for an achievement track."""
    return tuple(Stage(n, 10 * (i + 1)) for i, n in enumerate(TRACKS[track]))

def current_stage(track, total, claimed_thresholds=()):
    """Only the first unclaimed stage is visible; progress never resets."""
    if total < 0:
        raise ValueError("total cannot be negative")
    claimed = set(claimed_thresholds)
    for stage in stages(track):
        if stage.threshold not in claimed:
            return {
                "track": track,
                "threshold": stage.threshold,
                "progress": min(total, stage.threshold),
                "total": total,
                "xp": stage.xp,
                "claimable": total >= stage.threshold,
            }
    return None
