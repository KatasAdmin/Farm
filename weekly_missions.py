"""Weekly mission conditions shared by state and reward validation."""


def complete(grain, feeding, eggs, milk, listed, sales):
    return (
        (grain >= 10 or feeding >= 5)
        and (eggs >= 10 or milk >= 3)
        and (listed >= 3 or sales >= 3)
    )
