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
 active=min(plots,combines*5)
 return 6*active + 5*min(combines, (active+4)//5) if active else 0

def snapshot(c, player_id):
 cursor=c.execute("SELECT plots,combines,produced_progress,updated_at FROM farm_fields WHERE player_id=%s",(player_id,))
 # Lightweight simulation test doubles do not implement SELECT cursors.
 if not hasattr(cursor,"fetchone"):return dict(plots=0,combines=0,produced_progress=0.0,updated_at=0.0)
 row=cursor.fetchone()
 if not row:return dict(plots=0,combines=0,produced_progress=0.0,updated_at=0.0)
 return dict(row)

def status(c,p):
 row=snapshot(c,p["id"])
 plots=row["plots"];combines=row["combines"]
 return dict(plots=plots,combines=combines,max_fields=MAX_FIELDS,max_combines=MAX_COMBINES,
             plots_per_combine=5,field_price=FIELD_PRICE,combine_price=COMBINE_PRICE,
             grain_per_day=rate(plots,combines),grain_per_day_at_max=3500,
             invested=plots*FIELD_PRICE+combines*COMBINE_PRICE,
             inactive_fields=max(0,plots-combines*5),active_fields=min(plots,combines*5),
             next_field_requires_combine=False,
             next_grain_seconds=(SECONDS_PER_DAY/rate(plots,combines))*(1-row["produced_progress"]) if rate(plots,combines) else None)

def harvest(c,p,now=None):
 """Accrue server-side, respecting shared storage. Keep uncollected progress if full."""
 now=time.time() if now is None else now
 row=snapshot(c,p["id"])
 if not row["plots"] or not row["combines"]:
  if row["plots"]:
   c.execute("UPDATE farm_fields SET updated_at=%s WHERE player_id=%s",(now,p["id"]))
  return p
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

def purchase(c,p,item,now=None,quantity=1):
 if item not in ("field","combine"):raise HTTPException(400,"Неизвестная покупка")
 if not isinstance(quantity,int) or isinstance(quantity,bool) or quantity<1 or quantity>MAX_FIELDS:
  raise HTTPException(400,"Некорректное количество полей")
 if item=="combine" and quantity!=1:raise HTTPException(400,"Комбайны покупаются по одному")
 now=time.time() if now is None else now
 c.execute("INSERT INTO farm_fields(player_id,updated_at) VALUES(%s,%s) ON CONFLICT(player_id) DO NOTHING",(p["id"],now))
 row=snapshot(c,p["id"])
 plots=row["plots"];combines=row["combines"]
 if item=="field":
  if plots+quantity>MAX_FIELDS:raise HTTPException(400,"Нельзя превысить лимит в 500 полей")
  cost=FIELD_PRICE*quantity
 else:
  if combines>=MAX_COMBINES:raise HTTPException(400,"Все 100 комбайнов уже куплены")
  cost=COMBINE_PRICE
 if p["coins"]<cost:raise HTTPException(400,"Недостаточно монет")
 c.execute("UPDATE players SET coins=coins-%s WHERE id=%s",(cost,p["id"]))
 field_count=quantity if item=="field" else 0
 combine_count=1 if item=="combine" else 0
 c.execute("UPDATE farm_fields SET plots=plots+%s,combines=combines+%s,updated_at=%s WHERE player_id=%s",
           (field_count,combine_count,now,p["id"]))
 c.execute("UPDATE economy SET treasury=treasury+%s WHERE id=1",(cost,))
 newplots=plots+field_count;newcombines=combines+combine_count
 return dict(ok=True,spent=cost,fields=newplots,combines=newcombines,
             purchased=quantity,
             grain_per_day=rate(newplots,newcombines),
             needs_combine=newplots>newcombines*5,needs_field=newcombines>0 and newplots==0)
