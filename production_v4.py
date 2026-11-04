"""Continuous eggs for production model 4, with feed events every 18 hours."""
import math
import ad_inventory
from production import CYCLE, FEED_EVERY, GRAIN_PRICE
GOOSE_CYCLE=2*3600
GOOSE_FEED=2
FEATHER_INTERVAL=7*24*3600
COW_FEED=3
MILK_INTERVAL=8*3600
MILK_PRICE=11
COW_PRICE=500

def feed_required(p):
 """Whole grain needed by every animal at a shared 18-hour feeding."""
 return p["chickens"]+GOOSE_FEED*p.get("geese",0)+COW_FEED*p.get("cows",0)

def simulate(p, now):
 p=dict(p)
 tagged=ad_inventory.active(p)
 ad_hens=p.get("ad_chickens",0);ad_geese=p.get("ad_geese",0);ad_cows=p.get("ad_cows",0)
 ad_fed=min(p.get("ad_fed_hens",0),p["fed_hens"]);ad_goose_fed=min(p.get("ad_fed_geese",0),p.get("fed_geese",0));ad_cow_fed=min(p.get("ad_fed_cows",0),p.get("fed_cows",0))
 ad_grain=p.get("ad_grain",0);ad_eggs=p.get("ad_eggs",0);ad_milk=p.get("ad_milk",0);ad_feathers=p.get("ad_feathers",0)
 ad_ep=p.get("ad_egg_progress",0.0);ad_mp=p.get("ad_milk_progress",0.0);ad_fp=p.get("ad_feather_progress",0.0);ad_credit=p.get("_ad_credit_balance",0)
 cursor=min(now,p.get("egg_at") or now)
 progress=float(p.get("egg_progress") or 0)
 feather_progress=float(p.get("feather_progress") or 0)
 feathers=p.get("feathers",0)
 milk=p.get("milk",0)
 milk_progress=float(p.get("milk_progress") or 0)
 cows=p.get("cows",0)
 fed_cows=min(cows,p.get("fed_cows",0))
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
  nonlocal cursor,progress,eggs,produced,feathers,feather_progress,milk,milk_progress,ad_ep,ad_mp,ad_fp,ad_eggs,ad_milk,ad_feathers
  # Interleave feather events and egg production by time, so polling cannot
  # change which resource occupies the last warehouse slot. Eggs win ties.
  while until>cursor:
   step=min(until,cursor+(FEATHER_INTERVAL-feather_progress)/fed_geese) if fed_geese else until
   if fed_cows:step=min(step,cursor+(MILK_INTERVAL-milk_progress)/fed_cows)
   elapsed=max(0,step-cursor)
   before_progress=progress
   rate=fed/CYCLE+fed_geese/GOOSE_CYCLE
   total=progress+rate*elapsed
   whole=math.floor(total+1e-10)
   progress=max(0,min(.999999999,total-whole))
   laid=min(whole,max(0,capacity-grain-eggs-feathers-milk))
   eggs+=laid
   produced+=laid
   if tagged:
    ad_rate=ad_fed/CYCLE+ad_goose_fed/GOOSE_CYCLE
    # Classify at each egg's creation time, not at the end of a polling span.
    # The closed form counts restricted units among the first storable eggs.
    at_last=lambda count:ad_ep+ad_rate*max(0,(count-before_progress)/rate) if rate and count else ad_ep
    stored_ad=min(laid,max(0,math.ceil(at_last(laid)-1e-10))) if laid else 0
    generated_ad=min(whole,max(0,math.ceil(at_last(whole)-1e-10))) if whole else 0
    ad_ep+=ad_rate*elapsed-generated_ad
    ad_eggs+=stored_ad
    ad_mp+=ad_cow_fed*elapsed;ad_fp+=ad_goose_fed*elapsed
   feather_progress+=fed_geese*elapsed
   milk_progress+=fed_cows*elapsed
   cursor=step
   if feather_progress>=FEATHER_INTERVAL-1e-7:
    feather_progress=max(0,feather_progress-FEATHER_INTERVAL)
    if grain+eggs+feathers+milk<capacity:
     feathers+=1
     if tagged and ad_fp>1e-7:ad_feathers+=1
    if tagged and ad_fp>1e-7:ad_fp-=FEATHER_INTERVAL
   if milk_progress>=MILK_INTERVAL-1e-7:
    milk_progress=max(0,milk_progress-MILK_INTERVAL)
    if grain+eggs+feathers+milk<capacity:
     milk+=1
     if tagged and ad_mp>1e-7:ad_milk+=1
    if tagged and ad_mp>1e-7:ad_mp-=MILK_INTERVAL

 feed_at=tick+(FEED_EVERY-phase)*CYCLE
 for _ in range(146000):
  if feed_at>now:break
  accrue(feed_at)
  refill=p["autobuy_amount"]
  if p["autobuy_enabled"] and refill>0 and grain<hens+GOOSE_FEED*geese+COW_FEED*cows and coins>=GRAIN_PRICE*refill and grain+eggs+feathers+milk+refill<=capacity:
   coins-=GRAIN_PRICE*refill
   grain+=refill
   refills.append(refill)
   if tagged:
    ad_grain+=ad_inventory.funded_units(ad_credit,GRAIN_PRICE*refill,refill)
    ad_credit=max(0,ad_credit-GRAIN_PRICE*refill)
  grain_before_feed=grain
  fed=min(grain,hens)
  grain-=fed
  fed_geese=min(geese,grain//GOOSE_FEED)
  grain-=GOOSE_FEED*fed_geese
  fed_cows=min(cows,grain//COW_FEED)
  grain-=COW_FEED*fed_cows
  if tagged:
   used=min(ad_grain,grain_before_feed-grain);ad_grain-=used
   hen_feed=min(used,fed);used-=hen_feed
   goose_feed=min(used,GOOSE_FEED*fed_geese);used-=goose_feed
   ad_fed=min(fed,max(ad_hens,hen_feed))
   ad_goose_fed=min(fed_geese,max(ad_geese,math.ceil(goose_feed/GOOSE_FEED)))
   ad_cow_fed=min(fed_cows,max(ad_cows,math.ceil(used/COW_FEED)))
  if fed==hens and fed_geese==geese and fed_cows==cows:
   sat=min(100,sat+3)
   critical=0
  else:
   sat=max(0,sat-max(1,math.ceil(3*(hens-fed+GOOSE_FEED*(geese-fed_geese)+COW_FEED*(cows-fed_cows))/max(1,hens+GOOSE_FEED*geese+COW_FEED*cows))))
   critical=critical+1 if sat==0 else 0
   if critical>=48 and (hens or geese or cows):
    if geese>fed_geese:geese-=1
    elif hens>fed:hens-=1
    elif cows>fed_cows:cows-=1
    elif hens:hens-=1
    elif geese:geese-=1
    else:cows-=1
    fed=min(fed,hens)
    fed_geese=min(fed_geese,geese)
    fed_cows=min(fed_cows,cows)
    critical=0
    sat=20 if hens or geese or cows else 0
    if tagged:
     ad_hens=min(ad_hens,hens);ad_geese=min(ad_geese,geese);ad_cows=min(ad_cows,cows)
     ad_fed=min(ad_fed,fed);ad_goose_fed=min(ad_goose_fed,fed_geese);ad_cow_fed=min(ad_cow_fed,fed_cows)
  tick=feed_at
  phase=0
  feed_at+=FEED_EVERY*CYCLE
 accrue(min(now,feed_at))
 p.update(egg_at=cursor,egg_progress=progress,last_tick=tick,feed_phase=phase,
          eggs=eggs,milk=milk,milk_progress=milk_progress,cows=cows,fed_cows=fed_cows,feathers=feathers,feather_progress=feather_progress,grain=grain,coins=coins,chickens=hens,fed_hens=fed,geese=geese,fed_geese=fed_geese,
          satiety=sat,critical_cycles=critical)
 if tagged:p.update(ad_grain=ad_grain,ad_eggs=ad_eggs,ad_milk=ad_milk,ad_feathers=ad_feathers,ad_chickens=ad_hens,ad_geese=ad_geese,ad_cows=ad_cows,ad_fed_hens=ad_fed,ad_fed_geese=ad_goose_fed,ad_fed_cows=ad_cow_fed,ad_egg_progress=ad_ep,ad_milk_progress=ad_mp,ad_feather_progress=ad_fp)
 return p,produced,refills

def next_egg_delay(p,now):
 """First actually storable egg, including future feeds and warehouse space.
 Pure simulation: opening the forecast never grants resources or rerolls drops.
 Two feed intervals cover even goose rations accumulated by one-grain autobuys.
 """
 feed_at=p["last_tick"]+(FEED_EVERY-p["feed_phase"])*CYCLE
 rate=min(p["chickens"],p["fed_hens"])/CYCLE+min(p.get("geese",0),p.get("fed_geese",0))/GOOSE_CYCLE
 if rate:
  started=min(now,p.get("egg_at") or now)
  candidate=max(0,started+(1-(p.get("egg_progress") or 0))/rate-now)
  if now+candidate<=feed_at and simulate(p,now+candidate)[1]>0:return candidate
 high=math.ceil(max(0,feed_at-now)+2*FEED_EVERY*CYCLE+CYCLE)
 if simulate(p,now+high)[1]<=0:return None
 low=0
 while low<high:
  middle=(low+high)//2
  if simulate(p,now+middle)[1]>0:high=middle
  else:low=middle+1
 return low

def next_milk_delay(p,now):
 if not p.get("cows",0):return None
 fed=min(p.get("cows",0),p.get("fed_cows",0))
 if fed:
  candidate=max(0,(MILK_INTERVAL-p.get("milk_progress",0))/fed)
  if simulate(p,now+candidate)[0].get("milk",0)>p.get("milk",0):return candidate
 feed_at=p["last_tick"]+(FEED_EVERY-p["feed_phase"])*CYCLE
 high=math.ceil(max(0,feed_at-now)+4*FEED_EVERY*CYCLE+MILK_INTERVAL)
 if simulate(p,now+high)[0].get("milk",0)<=p.get("milk",0):return None
 low=0
 while low<high:
  mid=(low+high)//2
  if simulate(p,now+mid)[0].get("milk",0)>p.get("milk",0):high=mid
  else:low=mid+1
 return low

def next_feather_delay(p, now):
 """First feather that actually fits in storage, including future feeding."""
 if not p.get("geese", 0):
  return None
 fed=min(p.get("geese",0),p.get("fed_geese",0))
 if fed:
  candidate=max(0,(FEATHER_INTERVAL-p.get("feather_progress",0))/fed)
  if simulate(p,now+candidate)[0].get("feathers",0)>p.get("feathers",0):
   return candidate
 feed_at=p["last_tick"]+(FEED_EVERY-p["feed_phase"])*CYCLE
 high=math.ceil(max(0,feed_at-now)+2*FEATHER_INTERVAL+FEED_EVERY*CYCLE)
 if simulate(p,now+high)[0].get("feathers",0)<=p.get("feathers",0):
  return None
 low=0
 while low<high:
  mid=(low+high)//2
  if simulate(p,now+mid)[0].get("feathers",0)>p.get("feathers",0):
   high=mid
  else:
   low=mid+1
 return low

def forecast(p,now,jobs=()):
 six,n6,r6=simulate(p,now+CYCLE)
 next_milk=next_milk_delay(p,now)
 next_feather=next_feather_delay(p,now)
 twelve,n12,r12=simulate(p,now+2*CYCLE)
 fed=min(p["chickens"],p["fed_hens"])
 goose_fed=min(p.get("geese",0),p.get("fed_geese",0))
 required=feed_required(p)
 next_egg=next_egg_delay(p,now)
 egg_status="scheduled" if next_egg is not None else "empty" if not (p["chickens"]+p.get("geese",0)) else "storage_full" if p["grain"]+p["eggs"]+p.get("feathers",0)+p.get("milk",0)>=100*p["storage_level"] else "needs_feed"
 feed_at=p["last_tick"]+(FEED_EVERY-p["feed_phase"])*CYCLE
 next_feed=max(0,feed_at-now)
 after,_,rf=simulate(p,feed_at)
 missing=max(0,feed_required(after)-after["fed_hens"]-GOOSE_FEED*after.get("fed_geese",0)-COW_FEED*after.get("fed_cows",0)-after["grain"])
 notes=[]
 if fed<p["chickens"] or goose_fed<p.get("geese",0):notes.append(f"Сейчас несутся {fed+goose_fed} из {p['chickens']+p.get('geese',0)} птиц.")
 if six["grain"]+six["eggs"]+six.get("feathers",0)+six.get("milk",0)>=100*p["storage_level"]:notes.append("Склад может ограничить сбор.")
 if missing:notes.append("Зерна не хватит на полное следующее кормление.")
 if r6 or r12 or rf:notes.append("Учтена автозакупка корма.")
 future=sum(j["mature_at"]<=now+2*CYCLE for j in jobs)
 if future:notes.append("Вывод цыплят не включён в прогноз.")
 notes.append("При неизменных настройках и запасах.")
 full=required and fed==p["chickens"] and goose_fed==p.get("geese",0) and p.get("fed_cows",0)==p.get("cows",0)
 return dict(eggs_next_6h=n6,eggs_next_12h=n12,seconds_to_next_egg=next_egg if next_egg is not None else 0,
             next_egg_scheduled=next_egg is not None,next_egg_status=egg_status,
             seconds_to_next_feed=next_feed,grain_required_next_feed=required,
             grain_shortage=max(0,required-p["grain"]),effective_grain_shortage=missing,
             complete_feeds_available=p["grain"]//required if required else 0,
             autobuy_expected=bool(r6 or r12 or rf),forecast_approximate=bool(future),
             forecast_note=" ".join(notes),feed_stock_seconds=(next_feed+18*3600*(p["grain"]//required) if required and p["grain"]>=required else 0),
             fed_hens=fed,fed_geese=goose_fed,fed_cows=p.get("fed_cows",0),known_maturing=future,
             milk_next_6h=six.get("milk",0)-p.get("milk",0),milk_next_12h=twelve.get("milk",0)-p.get("milk",0),
             next_milk_scheduled=next_milk is not None,seconds_to_next_milk=next_milk or 0,
             next_milk_status="scheduled" if next_milk is not None else "empty" if not p.get("cows",0) else "storage_full" if p["grain"]+p["eggs"]+p.get("feathers",0)+p.get("milk",0)>=100*p["storage_level"] else "needs_feed",
             feathers_next_6h=six["feathers"]-p.get("feathers",0),
             seconds_to_next_feather=next_feather or 0,next_feather_scheduled=next_feather is not None,
             next_feather_status="scheduled" if next_feather is not None else "empty" if not p.get("geese",0) else "storage_full" if p["grain"]+p["eggs"]+p.get("feathers",0)+p.get("milk",0)>=100*p["storage_level"] else "needs_feed")
