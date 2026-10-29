"""Continuous eggs for production model 4, with feed events every 18 hours."""
import math
from production import CYCLE, FEED_EVERY, GRAIN_PRICE

def simulate(p, now):
 p=dict(p)
 cursor=min(now,p.get("egg_at") or now)
 progress=float(p.get("egg_progress") or 0)
 tick=p["last_tick"]
 phase=p["feed_phase"]
 hens=p["chickens"]
 fed=min(hens,p["fed_hens"])
 grain=p["grain"]
 eggs=p["eggs"]
 coins=p["coins"]
 capacity=100*p["storage_level"]
 sat=p["satiety"]
 critical=p["critical_cycles"]
 produced=0
 refills=[]
 def accrue(until):
  nonlocal cursor,progress,eggs,produced
  if until<=cursor:return
  total=progress+fed*(until-cursor)/CYCLE
  whole=math.floor(total+1e-10)
  progress=max(0,min(.999999999,total-whole))
  laid=min(whole,max(0,capacity-grain-eggs))
  eggs+=laid
  produced+=laid
  cursor=until
 feed_at=tick+(FEED_EVERY-phase)*CYCLE
 for _ in range(146000):
  if feed_at>now:break
  accrue(feed_at)
  refill=p["autobuy_amount"]
  if p["autobuy_enabled"] and grain<hens and coins>=GRAIN_PRICE*refill and grain+eggs+refill<=capacity:
   coins-=GRAIN_PRICE*refill
   grain+=refill
   refills.append(refill)
  fed=min(grain,hens)
  grain-=fed
  if fed==hens:
   sat=min(100,sat+3)
   critical=0
  else:
   sat=max(0,sat-max(1,math.ceil(3*(hens-fed)/max(1,hens))))
   critical=critical+1 if sat==0 else 0
   if critical>=48 and hens:
    hens-=1
    fed=min(fed,hens)
    critical=0
    sat=20 if hens else 0
  tick=feed_at
  phase=0
  feed_at+=FEED_EVERY*CYCLE
 accrue(min(now,feed_at))
 p.update(egg_at=cursor,egg_progress=progress,last_tick=tick,feed_phase=phase,
          eggs=eggs,grain=grain,coins=coins,chickens=hens,fed_hens=fed,
          satiety=sat,critical_cycles=critical)
 return p,produced,refills

def forecast(p,now,jobs=()):
 six,n6,r6=simulate(p,now+CYCLE)
 twelve,n12,r12=simulate(p,now+2*CYCLE)
 fed=min(p["chickens"],p["fed_hens"])
 progress=p.get("egg_progress") or 0
 next_egg=CYCLE*(1-progress)/fed if fed else 0
 feed_at=p["last_tick"]+(FEED_EVERY-p["feed_phase"])*CYCLE
 next_feed=max(0,feed_at-now)
 after,_,rf=simulate(p,feed_at)
 missing=max(0,p["chickens"]-after["fed_hens"])
 notes=[]
 if fed<p["chickens"]:notes.append(f"Сейчас несутся {fed} из {p['chickens']} кур.")
 if six["grain"]+six["eggs"]>=100*p["storage_level"]:notes.append("Склад может ограничить сбор.")
 if missing:notes.append("Зерна не хватит на полное следующее кормление.")
 if r6 or r12 or rf:notes.append("Учтена автозакупка корма.")
 future=sum(j["mature_at"]<=now+2*CYCLE for j in jobs)
 if future:notes.append("Вывод цыплят не включён в прогноз.")
 notes.append("При неизменных настройках и запасах.")
 full=p["chickens"] and fed==p["chickens"]
 return dict(eggs_next_6h=n6,eggs_next_12h=n12,seconds_to_next_egg=max(0,next_egg),
             seconds_to_next_feed=next_feed,grain_required_next_feed=p["chickens"],
             grain_shortage=max(0,p["chickens"]-p["grain"]),effective_grain_shortage=missing,
             autobuy_expected=bool(r6 or r12 or rf),forecast_approximate=bool(future),
             forecast_note=" ".join(notes),feed_stock_seconds=next_feed+18*3600*(p["grain"]//p["chickens"]) if full else 0,
             fed_hens=fed,known_maturing=future)
