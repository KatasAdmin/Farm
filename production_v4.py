"""Continuous eggs for production model 4, with feed events every 18 hours."""
import math
from production import CYCLE, FEED_EVERY, GRAIN_PRICE
GOOSE_CYCLE=2*3600
GOOSE_FEED=2
FEATHER_INTERVAL=7*24*3600

def simulate(p, now):
 p=dict(p)
 cursor=min(now,p.get("egg_at") or now)
 progress=float(p.get("egg_progress") or 0)
 feather_progress=float(p.get("feather_progress") or 0)
 feathers=p.get("feathers",0)
 tick=p["last_tick"]
 phase=p["feed_phase"]
 hens=p["chickens"]
 fed=min(hens,p["fed_hens"])
 geese=p.get("geese",0)
 fed_geese=min(geese,p.get("fed_geese",0))
 grain=p["grain"]
 eggs=p["eggs"]
 coins=p["coins"]
 capacity=100*p["storage_level"]
 sat=p["satiety"]
 critical=p["critical_cycles"]
 produced=0
 refills=[]
 def accrue(until):
  nonlocal cursor,progress,eggs,produced,feathers,feather_progress
  # Interleave feather events and egg production by time, so polling cannot
  # change which resource occupies the last warehouse slot. Eggs win ties.
  while until>cursor:
   step=min(until,cursor+(FEATHER_INTERVAL-feather_progress)/fed_geese) if fed_geese else until
   elapsed=max(0,step-cursor)
   total=progress+(fed/CYCLE+fed_geese/GOOSE_CYCLE)*elapsed
   whole=math.floor(total+1e-10)
   progress=max(0,min(.999999999,total-whole))
   laid=min(whole,max(0,capacity-grain-eggs-feathers))
   eggs+=laid
   produced+=laid
   feather_progress+=fed_geese*elapsed
   cursor=step
   if feather_progress>=FEATHER_INTERVAL-1e-7:
    feather_progress=max(0,feather_progress-FEATHER_INTERVAL)
    if grain+eggs+feathers<capacity:feathers+=1

 feed_at=tick+(FEED_EVERY-phase)*CYCLE
 for _ in range(146000):
  if feed_at>now:break
  accrue(feed_at)
  refill=p["autobuy_amount"]
  if p["autobuy_enabled"] and grain<hens+GOOSE_FEED*geese and coins>=GRAIN_PRICE*refill and grain+eggs+feathers+refill<=capacity:
   coins-=GRAIN_PRICE*refill
   grain+=refill
   refills.append(refill)
  fed=min(grain,hens)
  grain-=fed
  fed_geese=min(geese,grain//GOOSE_FEED)
  grain-=GOOSE_FEED*fed_geese
  if fed==hens and fed_geese==geese:
   sat=min(100,sat+3)
   critical=0
  else:
   sat=max(0,sat-max(1,math.ceil(3*(hens-fed+GOOSE_FEED*(geese-fed_geese))/max(1,hens+GOOSE_FEED*geese))))
   critical=critical+1 if sat==0 else 0
   if critical>=48 and (hens or geese):
    if geese>fed_geese:geese-=1
    elif hens:hens-=1
    else:geese-=1
    fed=min(fed,hens)
    fed_geese=min(fed_geese,geese)
    critical=0
    sat=20 if hens or geese else 0
  tick=feed_at
  phase=0
  feed_at+=FEED_EVERY*CYCLE
 accrue(min(now,feed_at))
 p.update(egg_at=cursor,egg_progress=progress,last_tick=tick,feed_phase=phase,
          eggs=eggs,feathers=feathers,feather_progress=feather_progress,grain=grain,coins=coins,chickens=hens,fed_hens=fed,geese=geese,fed_geese=fed_geese,
          satiety=sat,critical_cycles=critical)
 return p,produced,refills

def forecast(p,now,jobs=()):
 six,n6,r6=simulate(p,now+CYCLE)
 twelve,n12,r12=simulate(p,now+2*CYCLE)
 fed=min(p["chickens"],p["fed_hens"])
 progress=p.get("egg_progress") or 0
 goose_fed=min(p.get("geese",0),p.get("fed_geese",0))
 rate=fed/CYCLE+goose_fed/GOOSE_CYCLE
 required=p["chickens"]+GOOSE_FEED*p.get("geese",0)
 next_egg=(1-progress)/rate if rate else 0
 feed_at=p["last_tick"]+(FEED_EVERY-p["feed_phase"])*CYCLE
 next_feed=max(0,feed_at-now)
 after,_,rf=simulate(p,feed_at)
 missing=max(0,after["chickens"]+GOOSE_FEED*after.get("geese",0)-after["fed_hens"]-GOOSE_FEED*after.get("fed_geese",0))
 notes=[]
 if fed<p["chickens"] or goose_fed<p.get("geese",0):notes.append(f"Сейчас несутся {fed+goose_fed} из {p['chickens']+p.get('geese',0)} птиц.")
 if six["grain"]+six["eggs"]+six.get("feathers",0)>=100*p["storage_level"]:notes.append("Склад может ограничить сбор.")
 if missing:notes.append("Зерна не хватит на полное следующее кормление.")
 if r6 or r12 or rf:notes.append("Учтена автозакупка корма.")
 future=sum(j["mature_at"]<=now+2*CYCLE for j in jobs)
 if future:notes.append("Вывод цыплят не включён в прогноз.")
 notes.append("При неизменных настройках и запасах.")
 full=required and fed==p["chickens"] and goose_fed==p.get("geese",0)
 return dict(eggs_next_6h=n6,eggs_next_12h=n12,seconds_to_next_egg=max(0,next_egg),
             seconds_to_next_feed=next_feed,grain_required_next_feed=required,
             grain_shortage=max(0,required-p["grain"]),effective_grain_shortage=missing,
             autobuy_expected=bool(r6 or r12 or rf),forecast_approximate=bool(future),
             forecast_note=" ".join(notes),feed_stock_seconds=next_feed+18*3600*(p["grain"]//required) if full else 0,
             fed_hens=fed,fed_geese=goose_fed,known_maturing=future,
             feathers_next_6h=six["feathers"]-p.get("feathers",0),
             seconds_to_next_feather=(FEATHER_INTERVAL-p.get("feather_progress",0))/goose_fed if goose_fed else 0)
