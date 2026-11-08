"""Read-only proposed coin capitalization; NOT a redeemable cash reserve.

All amounts in integer kopeks. Advertising impressions and publisher dashboard
estimates must not be presented as bank funds available for withdrawal.
"""
from decimal import Decimal, ROUND_FLOOR
import time

SEED_USD=Decimal('1.00')
GAME_VIEW_SUPPORT_KOPEKS=5


def initialize(c):
    c.execute("""CREATE TABLE IF NOT EXISTS farm_capitalization_baseline(
      id integer PRIMARY KEY CHECK(id=1),
      started_at double precision NOT NULL,
      seed_usd numeric(14,2) NOT NULL DEFAULT 1 CHECK(seed_usd>=0))""")
    c.execute("""INSERT INTO farm_capitalization_baseline(id,started_at,seed_usd)
      VALUES(1,%s,1) ON CONFLICT(id) DO NOTHING""",(time.time(),))


def calculate(seed_kopeks, game_views, approved_game_deposits_kopeks,
              historical_bot_transfers_kopeks, circulating_coins):
    values=(seed_kopeks,game_views,approved_game_deposits_kopeks,
            historical_bot_transfers_kopeks,circulating_coins)
    if any(type(v) is not int or v<0 for v in values):
        raise ValueError('Capitalization inputs must be nonnegative integers')
    advertising_support=game_views*GAME_VIEW_SUPPORT_KOPEKS
    nominal=max(0,seed_kopeks+advertising_support+
                approved_game_deposits_kopeks-historical_bot_transfers_kopeks)
    # Small coins are never rounded up into an unsupported payout.
    price=(Decimal(nominal)/Decimal(circulating_coins)/Decimal(100)
           if circulating_coins else Decimal(0))
    return {'seed_kopeks':seed_kopeks,
            'game_views':game_views,
            'game_views_kopeks':advertising_support,
            'approved_deposits_kopeks':approved_game_deposits_kopeks,
            'historical_transfers_kopeks':historical_bot_transfers_kopeks,
            'total_coins':circulating_coins,
            'nominal_capitalization_kopeks':nominal,
            'nominal_coin_price_uah':str(price),
            'payout_enabled':False,
            'reason':'Nominal capitalization is not verified available cash'}


def preview(c,usd_uah):
    rate=Decimal(str(usd_uah))
    if not rate.is_finite() or rate<=0 or rate>Decimal(1000):
        raise ValueError('Unreliable USD rate')
    baseline=c.execute("SELECT started_at,seed_usd FROM farm_capitalization_baseline WHERE id=1").fetchone()
    if not baseline:raise ValueError('Capitalization baseline not initialized')
    seed=int((Decimal(str(baseline['seed_usd']))*rate*100).to_integral_value(rounding=ROUND_FLOOR))
    since=float(baseline['started_at'])
    confirmed_farm=c.execute("""SELECT count(*) AS n
      FROM bot_adsgram_farm_attempts
      WHERE state='confirmed' AND confirmed_at>=%s""",(since,)).fetchone()['n']
    monetag=c.execute("""SELECT count(*) AS n FROM monetag_ad_attempts
      WHERE valued_at IS NOT NULL AND rewarded_at IS NOT NULL
        AND rewarded_at>=%s""",(since,)).fetchone()['n']
    deposits=c.execute("""SELECT COALESCE(SUM(t.amount),0) AS n FROM bot_card_topups t
      JOIN farm_card_topup_targets f ON f.topup_id=t.id
      WHERE t.status='approved' AND t.approved_at>=%s""",(since,)).fetchone()['n']
    transfers=c.execute("""SELECT COALESCE(SUM(amount),0) AS n FROM farm_bot_transfers
      WHERE created>=%s""",(since,)).fetchone()['n']
    players=c.execute("""SELECT COALESCE(SUM(coins),0) AS n FROM players""").fetchone()['n']
    treasury=c.execute("""SELECT COALESCE(treasury,0) AS n FROM economy WHERE id=1""").fetchone()
    # The treasury may later credit players; it is also part of coin circulation.
    coins=int(players)+int(treasury['n'] if treasury else 0)
    redeemed=c.execute("""SELECT COALESCE(SUM(credited_kopeks),0) AS n
      FROM farm_coin_redemptions WHERE created_at>=%s""",(since,)).fetchone()['n']
    result=calculate(seed,int(confirmed_farm)+int(monetag),int(deposits),
                     int(transfers)*100+int(redeemed),coins)
    result['usd_seed']=str(baseline['seed_usd'])
    result['started_at']=since
    result['usd_uah_reference']=str(rate)
    return result
