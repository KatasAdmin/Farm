"""Read-only simulation shared by committed production and the UI forecast.

Order intentionally matches the existing v25 engine: eggs, then (each third
cycle) feeding; incubation is reconciled by main.advance *after* catch-up.
No database, random values, network or wall clock is used here.
"""
CYCLE = 21600
FEED_EVERY = 3
GRAIN_PRICE = 2


def simulate(player, now):
    p = dict(player)
    start = p['last_tick'] if p['last_tick'] is not None else now
    due = max(0, int((now - start) // CYCLE))
    produced, refills = 0, []
    if not due:
        return p, produced, refills
    grain, eggs, hens, coins = (p[k] for k in ('grain', 'eggs', 'chickens', 'coins'))
    fed_hens = min(hens, p['fed_hens'])
    phase, satiety, critical = p['feed_phase'], p['satiety'], p['critical_cycles']
    capacity = 100 * p['storage_level']
    for _ in range(min(due, 438000)):
        if hens <= 0:
            break
        laid = min(fed_hens, max(0, capacity - grain - eggs))
        eggs += laid
        produced += laid
        phase = (phase + 1) % FEED_EVERY
        if phase:
            continue
        refill = p['autobuy_amount']
        if (p['autobuy_enabled'] and grain < hens
                and coins >= GRAIN_PRICE * max(1, refill)
                and grain + eggs + refill <= capacity):
            coins -= GRAIN_PRICE * refill
            grain += refill
            refills.append(refill)
        fed_hens = min(grain, hens)
        grain -= fed_hens
        if fed_hens == hens:
            satiety = min(100, satiety + 3)
            critical = 0
        else:
            missing = hens - fed_hens
            satiety = max(0, satiety - max(1, (3 * missing + hens - 1) // hens))
            critical = critical + 1 if satiety == 0 else 0
            if critical >= 48:
                hens -= 1
                fed_hens = min(fed_hens, hens)
                critical = 0
                satiety = 20 if hens else 0
    p.update(coins=coins, grain=grain, eggs=eggs, chickens=hens,
             satiety=satiety, critical_cycles=critical, fed_hens=fed_hens,
             feed_phase=phase, last_tick=start + due * CYCLE)
    return p, produced, refills


def forecast(player, now, jobs=()):
    """Forecast assumes no trades/upgrades/claims and unchanged settings.

    Pending chicks are not credited with speculative retroactive eggs. Their
    reconciliation depends on the next server visit in the existing engine, so
    a known maturity within the window is explicitly marked as an estimate.
    """
    p = player
    start = p['last_tick'] if p['last_tick'] is not None else now
    egg_at = start + CYCLE
    feed_at = start + (FEED_EVERY - p['feed_phase']) * CYCLE
    six, eggs6, refills6 = simulate(p, now + 6 * 3600)
    twelve, eggs12, refills12 = simulate(p, now + 12 * 3600)
    before_feed = dict(p)
    before_feed['last_tick'] = start
    ticks_before = FEED_EVERY - p['feed_phase'] - 1
    pre, _, _ = simulate(before_feed, start + ticks_before * CYCLE)
    # Feeding checks space *after* the egg tick on the feeding boundary.
    laid = min(pre['fed_hens'], max(0, 100*p['storage_level']-pre['grain']-pre['eggs']))
    can_buy = (p['autobuy_enabled'] and pre['grain'] < pre['chickens']
               and pre['coins'] >= GRAIN_PRICE * max(1, p['autobuy_amount'])
               and pre['grain'] + pre['eggs'] + laid + p['autobuy_amount'] <= 100*p['storage_level'])
    shortage = max(0, pre['chickens'] - pre['grain'])
    effective_shortage = max(0, shortage - (p['autobuy_amount'] if can_buy else 0))
    known_maturing = sum(j['mature_at'] <= now+12*3600 for j in jobs)
    notes = []
    if not p['chickens']:
        notes.append('Пока нет несушек.')
    if p['fed_hens'] < p['chickens']:
        notes.append('Яйца дают только накормленные куры; новое кормление — по отдельному таймеру.')
    if p['grain']+p['eggs'] >= 100*p['storage_level'] or six['grain']+six['eggs'] >= 100*p['storage_level']:
        notes.append('Вместимость склада ограничивает сбор. Освободи место или улучши склад.')
    if refills6 or refills12 or can_buy:
        notes.append('Учтена автозакупка при текущих монетах и свободном месте; она потратит монеты.')
    elif p['autobuy_enabled'] and shortage:
        notes.append('Автозакупке не хватает монет или места на складе.')
    if effective_shortage:
        notes.append('Зерна для полного следующего кормления недостаточно.')
    if known_maturing:
        notes.append('Оценка для нынешних несушек: '+str(known_maturing)+' цыплёнка могут вырасти; их новые яйца зависят от синхронизации и следующего кормления.')
    notes.append('При неизменных запасах и настройках, без новых покупок и продаж.')
    # Grain covers complete feeding events; time includes the already fed period.
    complete_feeds = p['grain']//p['chickens'] if p['chickens'] else 0
    return {
        'eggs_next_6h': eggs6, 'eggs_next_12h': eggs12,
        'seconds_to_next_egg': max(0, egg_at-now),
        'seconds_to_next_feed': max(0, feed_at-now),
        'grain_required_next_feed': pre['chickens'],
        'grain_shortage': shortage, 'effective_grain_shortage': effective_shortage,
        'autobuy_expected': bool(refills6 or refills12 or can_buy),
        'forecast_approximate': bool(known_maturing), 'forecast_note': ' '.join(notes),
        'feed_stock_seconds': (max(0, feed_at-now)+complete_feeds*FEED_EVERY*CYCLE) if p['chickens'] and p['fed_hens'] >= p['chickens'] else 0,
        'fed_hens': p['fed_hens'], 'known_maturing': known_maturing,
    }
