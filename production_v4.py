"""Continuous eggs for production model 4, with feed events every 18 hours."""
import math
import ad_inventory
import city_nutrition
from production import CYCLE, FEED_EVERY, GRAIN_PRICE
GOOSE_CYCLE=2*3600
GOOSE_FEED=2
FEATHER_INTERVAL=7*24*3600  # Predictable production: one feather per fed goose each 7 days.
COW_FEED=3
MILK_INTERVAL=8*3600
MILK_PRICE=11
COW_PRICE=500
SHEEP_PRICE=200
SHEEP_FEED=2
WOOL_INTERVAL=24*3600
WOOL_PRICE=12

def feed_required(p):
 """Whole grain needed by every animal at a shared 18-hour feeding."""
 return p["chickens"]+GOOSE_FEED*p.get("geese",0)+COW_FEED*p.get("cows",0)+SHEEP_FEED*p.get("sheep",0)

def simulate(p, now):
 p=dict(p)
 tagged=ad_inventory.active(p)
 ad_hens=p.get("ad_chickens",0);ad_geese=p.get("ad_geese",0);ad_cows=p.get("ad_cows",0);ad_sheep=p.get("ad_sheep",0)
 ad_fed=min(p.get("ad_fed_hens",0),p["fed_hens"]);ad_goose_fed=min(p.get("ad_fed_geese",0),p.get("fed_geese",0));ad_cow_fed=min(p.get("ad_fed_cows",0),p.get("fed_cows",0));ad_sheep_fed=min(p.get("ad_fed_sheep",0),p.get("fed_sheep",0))
 ad_grain=p.get("ad_grain",0);ad_eggs=p.get("ad_eggs",0);ad_milk=p.get("ad_milk",0);ad_feathers=p.get("ad_feathers",0);ad_wool=p.get("ad_wool",0)
 ad_ep=p.get("ad_egg_progress",0.0);ad_mp=p.get("ad_milk_progress",0.0);ad_fp=p.get("ad_feather_progress",0.0);ad_credit=p.get("_ad_credit_balance",0);ad_wp=p.get("ad_wool_progress",0.0)
 cursor=min(now,p.get("egg_at") or now)
 progress=float(p.get("egg_progress") or 0)
 feather_progress=float(p.get("feather_progress") or 0)
 feathers=p.get("feathers",0)
 milk=p.get("milk",0)
 milk_progress=float(p.get("milk_progress") or 0)
 cows=p.get("cows",0)
 fed_cows=min(cows,p.get("fed_cows",0))
 sheep=p.get("sheep",0)
 fed_sheep=min(sheep,p.get("fed_sheep",0))
 wool=p.get("wool",0)
 wool_progress=float(p.get("wool_progress") or 0)
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
 food=p.get("_city_food")
 bonus_progress=dict(food.get("bonus_progress",{})) if food else {}

 def bonus_yield(item, base):
  if not base:
   return 0,0
  carry=bonus_progress.get(item,0)
  extra=min(base,math.floor(carry+1e-9))
  bonus_progress[item]=max(0,carry-extra)
  restricted_key="ad_"+item
  restricted=bonus_progress.get(restricted_key,0)
  extra_ad=min(extra,math.ceil(max(0,restricted)-1e-9))
  if tagged:
   bonus_progress[restricted_key]=restricted-extra_ad
  return extra,extra_ad

 def accrue(until):
  nonlocal cursor,progress,eggs,produced,feathers,feather_progress,milk,milk_progress,wool,wool_progress,ad_ep,ad_mp,ad_fp,ad_wp,ad_eggs,ad_milk,ad_feathers,ad_wool
  # Interleave feather events and egg production by time, so polling cannot
  # change which resource occupies the last warehouse slot. Eggs win ties.
  while until>cursor:
   rate=fed/CYCLE+fed_geese/GOOSE_CYCLE
   ad_rate=ad_fed/CYCLE+ad_goose_fed/GOOSE_CYCLE
   def target_step(remaining, per_second):
    if per_second<=0:return until
    # Integrate satiety over time, so the same factor drives actual production
    # and the countdown, not a separate delayed "bonus item" lottery.
    maximum=cursor+remaining/per_second
    maximum=min(maximum,until)
    if not food:return maximum
    if per_second*((maximum-cursor)+city_nutrition.bonus_seconds(food,cursor,maximum))<remaining-1e-8:
     return maximum
    lo=cursor;hi=maximum
    for _ in range(28):
     mid=(lo+hi)/2
     progress_at=per_second*((mid-cursor)+city_nutrition.bonus_seconds(food,cursor,mid))
     if progress_at>=remaining:hi=mid
     else:lo=mid
    return hi
   step=until
   if fed_geese:step=min(step,target_step(max(0,FEATHER_INTERVAL-feather_progress),fed_geese))
   if fed_cows:step=min(step,target_step(max(0,MILK_INTERVAL-milk_progress),fed_cows))
   if fed_sheep:step=min(step,target_step(max(0,WOOL_INTERVAL-wool_progress),fed_sheep))
   if rate:step=min(step,target_step(max(0,1-progress),rate))
   if step<=cursor:step=min(until,cursor+1e-6)
   elapsed=max(0,step-cursor)
   bonus=city_nutrition.bonus_seconds(food,cursor,step)
   accelerated=elapsed+bonus
   before_progress=progress
   total=progress+rate*accelerated
   whole=math.floor(total+1e-10)
   progress=max(0,min(.999999999,total-whole))
   # No additional random or delayed bonus units: only elapsed production time accelerates.
   extra=extra_ad=0
   free=max(0,capacity-grain-eggs-feathers-milk-wool)
   laid=min(whole,free)
   bonus_laid=min(extra,free-laid)
   eggs+=laid+bonus_laid
   produced+=laid+bonus_laid
   if tagged:
    # Base units keep their existing provenance. Bonus units inherit the
    # provenance of the bonus production accumulated before the base event.
    at_last=lambda count:ad_ep+ad_rate*max(0,(count-before_progress)/rate) if rate and count else ad_ep
    stored_ad=min(laid,max(0,math.ceil(at_last(laid)-1e-10))) if laid else 0
    generated_ad=min(whole,max(0,math.ceil(at_last(whole)-1e-10))) if whole else 0
    ad_ep+=ad_rate*accelerated-generated_ad
    ad_eggs+=stored_ad+min(extra_ad,bonus_laid)
    ad_mp+=ad_cow_fed*accelerated;ad_fp+=ad_goose_fed*accelerated;ad_wp+=ad_sheep_fed*accelerated
   feather_progress+=fed_geese*accelerated
   milk_progress+=fed_cows*accelerated
   wool_progress+=fed_sheep*accelerated
   cursor=step
   if feather_progress>=FEATHER_INTERVAL-1e-7:
    feather_progress=max(0,feather_progress-FEATHER_INTERVAL)
    extra=extra_ad=0
    free=max(0,capacity-grain-eggs-feathers-milk-wool)
    if free:
     feathers+=1+min(extra,free-1)
     if tagged:ad_feathers+=int(ad_fp>1e-7)+min(extra_ad,free-1)
    if tagged and ad_fp>1e-7:ad_fp-=FEATHER_INTERVAL
   if milk_progress>=MILK_INTERVAL-1e-7:
    milk_progress=max(0,milk_progress-MILK_INTERVAL)
    extra=extra_ad=0
    free=max(0,capacity-grain-eggs-feathers-milk-wool)
    if free:
     milk+=1+min(extra,free-1)
     if tagged:ad_milk+=int(ad_mp>1e-7)+min(extra_ad,free-1)
    if tagged and ad_mp>1e-7:ad_mp-=MILK_INTERVAL
   if wool_progress>=WOOL_INTERVAL-1e-7:
    wool_progress=max(0,wool_progress-WOOL_INTERVAL)
    extra=extra_ad=0
    free=max(0,capacity-grain-eggs-feathers-milk-wool)
    if free:
     wool+=1+min(extra,free-1)
     if tagged:ad_wool+=int(ad_wp>1e-7)+min(extra_ad,free-1)
    if tagged and ad_wp>1e-7:ad_wp-=WOOL_INTERVAL

 feed_at=tick+(FEED_EVERY-phase)*CYCLE
 for _ in range(146000):
  if feed_at>now:break
  accrue(feed_at)
  refill=p["autobuy_amount"]
  if p["autobuy_enabled"] and refill>0 and grain<hens+GOOSE_FEED*geese+COW_FEED*cows+SHEEP_FEED*sheep and coins>=GRAIN_PRICE*refill and grain+eggs+feathers+milk+wool+refill<=capacity:
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
  fed_sheep=min(sheep,grain//SHEEP_FEED)
  grain-=SHEEP_FEED*fed_sheep
  if tagged:
   used=min(ad_grain,grain_before_feed-grain);ad_grain-=used
   hen_feed=min(used,fed);used-=hen_feed
   goose_feed=min(used,GOOSE_FEED*fed_geese);used-=goose_feed
   ad_fed=min(fed,max(ad_hens,hen_feed))
   ad_goose_fed=min(fed_geese,max(ad_geese,math.ceil(goose_feed/GOOSE_FEED)))
   cow_feed=min(used,COW_FEED*fed_cows);used-=cow_feed
   ad_cow_fed=min(fed_cows,max(ad_cows,math.ceil(cow_feed/COW_FEED)))
   ad_sheep_fed=min(fed_sheep,max(ad_sheep,math.ceil(used/SHEEP_FEED)))
  if fed==hens and fed_geese==geese and fed_cows==cows and fed_sheep==sheep:
   sat=min(100,sat+3)
   critical=0
  else:
   sat=max(0,sat-max(1,math.ceil(3*(hens-fed+GOOSE_FEED*(geese-fed_geese)+COW_FEED*(cows-fed_cows)+SHEEP_FEED*(sheep-fed_sheep))/max(1,hens+GOOSE_FEED*geese+COW_FEED*cows+SHEEP_FEED*sheep))))
   critical=critical+1 if sat==0 else 0
   # Hunger pauses production for unfed animals; livestock never dies.
   # Fed hens/geese/cows remain productive in proportion to the fed herd.
   critical=0

  tick=feed_at
  phase=0
  feed_at+=FEED_EVERY*CYCLE
 accrue(min(now,feed_at))
 p.update(egg_at=cursor,egg_progress=progress,last_tick=tick,feed_phase=phase,
          eggs=eggs,milk=milk,milk_progress=milk_progress,cows=cows,fed_cows=fed_cows,feathers=feathers,feather_progress=feather_progress,grain=grain,coins=coins,chickens=hens,fed_hens=fed,geese=geese,fed_geese=fed_geese,
          satiety=sat,critical_cycles=critical)
 if "sheep" in p:p.update(sheep=sheep,fed_sheep=fed_sheep,wool=wool,wool_progress=wool_progress)
 if tagged:p.update(ad_grain=ad_grain,ad_eggs=ad_eggs,ad_milk=ad_milk,ad_feathers=ad_feathers,ad_chickens=ad_hens,ad_geese=ad_geese,ad_cows=ad_cows,ad_fed_hens=ad_fed,ad_fed_geese=ad_goose_fed,ad_fed_cows=ad_cow_fed,ad_egg_progress=ad_ep,ad_milk_progress=ad_mp,ad_feather_progress=ad_fp,ad_sheep=ad_sheep,ad_fed_sheep=ad_sheep_fed,ad_wool=ad_wool,ad_wool_progress=ad_wp)
 if food:p["_city_bonus_progress"]=bonus_progress
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
  if now+candidate<=feed_at and simulate(p,now+candidate)[1]>0:
   if not p.get("_city_food"):return candidate
   low=0;high=math.ceil(candidate)
   while low<high:
    mid=(low+high)//2
    if simulate(p,now+mid)[1]>0:high=mid
    else:low=mid+1
   return low
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
  if simulate(p,now+candidate)[0].get("milk",0)>p.get("milk",0):
   if not p.get("_city_food"):return candidate
   low=0;high=math.ceil(candidate)
   while low<high:
    mid=(low+high)//2
    if simulate(p,now+mid)[0].get("milk",0)>p.get("milk",0):high=mid
    else:low=mid+1
   return low
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
   if not p.get("_city_food"):return candidate
   low=0;high=math.ceil(candidate)
   while low<high:
    mid=(low+high)//2
    if simulate(p,now+mid)[0].get("feathers",0)>p.get("feathers",0):high=mid
    else:low=mid+1
   return low
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
 egg_status="scheduled" if next_egg is not None else "empty" if not (p["chickens"]+p.get("geese",0)) else "storage_full" if p["grain"]+p["eggs"]+p.get("feathers",0)+p.get("milk",0)+p.get("wool",0)>=100*p["storage_level"] else "needs_feed"
 feed_at=p["last_tick"]+(FEED_EVERY-p["feed_phase"])*CYCLE
 next_feed=max(0,feed_at-now)
 after,_,rf=simulate(p,feed_at)
 missing=max(0,feed_required(after)-after["fed_hens"]-GOOSE_FEED*after.get("fed_geese",0)-COW_FEED*after.get("fed_cows",0)-SHEEP_FEED*after.get("fed_sheep",0)-after["grain"])
 notes=[]
 if fed<p["chickens"] or goose_fed<p.get("geese",0):notes.append(f"Сейчас несутся {fed+goose_fed} из {p['chickens']+p.get('geese',0)} птиц.")
 if six["grain"]+six["eggs"]+six.get("feathers",0)+six.get("milk",0)+six.get("wool",0)>=100*p["storage_level"]:notes.append("Склад может ограничить сбор.")
 if missing:notes.append("Зерна не хватит на полное следующее кормление.")
 if r6 or r12 or rf:notes.append("Учтена автозакупка корма.")
 future=sum(j["mature_at"]<=now+2*CYCLE for j in jobs)
 if future:notes.append("Вывод цыплят не включён в прогноз.")
 notes.append("При неизменных настройках и запасах.")
 full=required and fed==p["chickens"] and goose_fed==p.get("geese",0) and p.get("fed_cows",0)==p.get("cows",0) and p.get("fed_sheep",0)==p.get("sheep",0)
 return dict(eggs_next_6h=n6,eggs_next_12h=n12,seconds_to_next_egg=next_egg if next_egg is not None else 0,
             next_egg_scheduled=next_egg is not None,next_egg_status=egg_status,
             seconds_to_next_feed=next_feed,grain_required_next_feed=required,
             grain_shortage=max(0,required-p["grain"]),effective_grain_shortage=missing,
             complete_feeds_available=p["grain"]//required if required else 0,
             autobuy_expected=bool(r6 or r12 or rf),forecast_approximate=bool(future),
             forecast_note=" ".join(notes),feed_stock_seconds=(next_feed+18*3600*(p["grain"]//required) if required and p["grain"]>=required else 0),
             fed_hens=fed,fed_geese=goose_fed,fed_cows=p.get("fed_cows",0),fed_sheep=p.get("fed_sheep",0),known_maturing=future,
             wool_next_6h=six.get("wool",0)-p.get("wool",0),wool_next_12h=twelve.get("wool",0)-p.get("wool",0),
             milk_next_6h=six.get("milk",0)-p.get("milk",0),milk_next_12h=twelve.get("milk",0)-p.get("milk",0),
             next_milk_scheduled=next_milk is not None,seconds_to_next_milk=next_milk or 0,
             next_milk_status="scheduled" if next_milk is not None else "empty" if not p.get("cows",0) else "storage_full" if p["grain"]+p["eggs"]+p.get("feathers",0)+p.get("milk",0)+p.get("wool",0)>=100*p["storage_level"] else "needs_feed",
             feathers_next_6h=six["feathers"]-p.get("feathers",0),
             seconds_to_next_feather=next_feather or 0,next_feather_scheduled=next_feather is not None,
             next_feather_status="scheduled" if next_feather is not None else "empty" if not p.get("geese",0) else "storage_full" if p["grain"]+p["eggs"]+p.get("feathers",0)+p.get("milk",0)+p.get("wool",0)>=100*p["storage_level"] else "needs_feed")
