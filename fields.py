"""Automatic wheat fields. One combine serves five plots; 20-day payback at shop grain price."""
import math
import time
from fastapi import HTTPException

FIELD_PRICE = 240
COMBINE_PRICE = 200
MAX_FIELDS = 500
MAX_COMBINES = 100
SECONDS_PER_DAY = 86400

def migrate(c):
 c.execute("""CREATE TABLE IF NOT EXISTS farm_fields(
  player_id text PRIMARY KEY REFERENCES players(id) ON DELETE CASCADE,
  plots integer NOT NULL DEFAULT 0 CHECK(plots BETWEEN 0 AND 500),
  combines integer NOT NULL DEFAULT 0 CHECK(combines BETWEEN 0 AND 100),
  produced_progress double precision NOT NULL DEFAULT 0 CHECK(produced_progress >= 0),
  updated_at double precision NOT NULL DEFAULT 0
 )""")

def rate(plots, combines):
 return 6*plots + 5*min(combines, (plots+4)//5) if plots else 0

def snapshot(c, player_id):
 row=c.execute("SELECT plots,combines,produced_progress,updated_at FROM farm_fields WHERE player_id=%s",(player_id,)).fetchone()
 if not row:return dict(plots=0,combines=0,produced_progress=0.0,updated_at=0.0)
 return dict(row)

def status(c,p):
 row=snapshot(c,p["id"])
 plots=row["plots"];combines=row["combines"]
 return dict(plots=plots,combines=combines,max_fields=MAX_FIELDS,max_combines=MAX_COMBINES,
             plots_per_combine=5,field_price=FIELD_PRICE,combine_price=COMBINE_PRICE,
             grain_per_day=rate(plots,combines),grain_per_day_at_max=3500,
             invested=plots*FIELD_PRICE+combines*COMBINE_PRICE,
             next_field_requires_combine=plots>=combines*5,
             next_grain_seconds=(SECONDS_PER_DAY/rate(plots,combines))*(1-row["produced_progress"]) if rate(plots,combines) else None)

def harvest(c,p,now=None):
 """Accrue server-side, respecting shared storage. Keep uncollected progress if full."""
 now=time.time() if now is None else now
 row=snapshot(c,p["id"])
 if not row["plots"]:return p
 elapsed=max(0,now-row["updated_at"])
 # Avoid unbounded backlog after long absence: at most 24h worth of grain is waiting.
 progress=min(float(rate(row["plots"],row["combines"])),row["produced_progress"]+
              elapsed*rate(row["plots"],row["combines"])/SECONDS_PER_DAY)
 capacity=100*p["storage_level"]
 occupied=p["grain"]+p["eggs"]+p.get("milk",0)+p.get("feathers",0)
 gained=min(math.floor(progress+1e-9),max(0,capacity-occupied))
 c.execute("UPDATE farm_fields SET produced_progress=%s,updated_at=%s WHERE player_id=%s",
           (max(0,progress-gained),now,p["id"]))
 if gained:
  c.execute("UPDATE players SET grain=grain+%s WHERE id=%s",(gained,p["id"]))
  p={**p,"grain":p["grain"]+gained}
 return p

def purchase(c,p,item,now=None):
 if item not in ("field","combine"):raise HTTPException(400,"Неизвестная покупка")
 now=time.time() if now is None else now
 c.execute("INSERT INTO farm_fields(player_id,updated_at) VALUES(%s,%s) ON CONFLICT(player_id) DO NOTHING",(p["id"],now))
 row=snapshot(c,p["id"])
 plots=row["plots"];combines=row["combines"]
 if item=="field":
  if plots>=MAX_FIELDS:raise HTTPException(400,"Все 500 полей уже куплены")
  if plots>=combines*5:raise HTTPException(400,"Для следующего поля сначала купите комбайн")
  cost=FIELD_PRICE
 else:
  if combines>=MAX_COMBINES:raise HTTPException(400,"Все 100 комбайнов уже куплены")
  if combines*5>plots:raise HTTPException(400,"Этот комбайн пока не нужен: есть свободные места")
  cost=COMBINE_PRICE
 if p["coins"]<cost:raise HTTPException(400,"Недостаточно монет")
 c.execute("UPDATE players SET coins=coins-%s WHERE id=%s",(cost,p["id"]))
 c.execute("UPDATE farm_fields SET plots=plots+%s,combines=combines+%s,updated_at=%s WHERE player_id=%s",
           (int(item=="field"),int(item=="combine"),now,p["id"]))
 c.execute("UPDATE economy SET treasury=treasury+%s WHERE id=1",(cost,))
 return dict(ok=True,spent=cost,fields=plots+int(item=="field"),combines=combines+int(item=="combine"))
