"""Pure incubation capacity rules shared by purchase and maturity processing."""


def available_maturity_slots(coop_capacity, chickens, geese, ready_jobs):
    if min(coop_capacity, chickens, geese, ready_jobs) < 0:
        raise ValueError("negative incubator capacity or counts")
    return min(ready_jobs, max(0, coop_capacity - chickens - geese))


def can_start_incubation(coop_capacity, chickens, geese, active_jobs, incubator_level):
    if min(coop_capacity, chickens, geese, active_jobs, incubator_level) < 0:
        return False
    return (active_jobs < incubator_level
            and chickens + geese + active_jobs < coop_capacity)
