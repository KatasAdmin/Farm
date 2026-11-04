"""Rewarded Monetag events. Only authenticated server postbacks earn goods.
Client reports are telemetry, never payment evidence. Only goods or restricted purchasing credit.
"""
import hmac
import ad_inventory
import os
import re
import secrets
import time
import uuid
from decimal import Decimal, InvalidOperation
from fastapi import HTTPException

REWARDS={'grain':(1,1),'eggs':(2,2),'milk':(5,1),'chickens':(20,1),'geese':(80,1),'cows':(250,1),'coins':(1,2)}
TMA_ZONE=12193261
LOCK=1984533
DAY_LIMIT=40
HOUR_LIMIT=10
COOLDOWN=30
PREPARE_TTL=600
CONFIRM_WAIT=120
POSTBACK_TTL=48*3600
FIELDS={
 'platform':"text NOT NULL DEFAULT 'legacy'",'ad_format':"text NOT NULL DEFAULT 'rewarded_popup'",
 'launched_at':'double precision','sdk_completed_at':'double precision','sdk_result':'text',
 'sdk_error':'text','confirmed_at':'double precision','non_valued_at':'double precision',
 'blocked_at':'double precision','valued_at':'double precision'
}

def initialize(c):
 for name,definition in FIELDS.items():
  c.execute('ALTER TABLE monetag_ad_attempts ADD COLUMN IF NOT EXISTS '+name+' '+definition)
 c.execute('CREATE TABLE IF NOT EXISTS monetag_postback_events(ymid text NOT NULL,event_type text NOT NULL,sub_zone_id integer NOT NULL,reward_event_type text NOT NULL,estimated_usd numeric(20,7),received_at double precision NOT NULL,PRIMARY KEY(ymid,event_type,sub_zone_id,reward_event_type))')

def enabled():return os.getenv('MONETAG_REWARDS_ENABLED')=='1' and len(os.getenv('MONETAG_POSTBACK_SECRET',''))>=24

def zone(platform):
 if platform=='telegram':return TMA_ZONE
 raw=os.getenv('MONETAG_WEB_ZONE_ID','')
 if platform=='web' and os.getenv('MONETAG_WEB_REWARDED_ENABLED')=='1' and raw.isdecimal() and int(raw)>0 and int(raw)!=TMA_ZONE:return int(raw)
 return None

def config(platform):
 z=zone(platform)
 return dict(enabled=enabled() and bool(z),platform=platform,zone_id=z,sdk_url='https://libtl.com/sdk.js',ad_format='pop',daily_limit=DAY_LIMIT,hourly_limit=HOUR_LIMIT,cooldown=COOLDOWN,reason='' if z else 'Для браузера ещё не подключена отдельная rewarded-зона Monetag')

def lock(c):c.execute('SELECT pg_advisory_xact_lock(%s)',(LOCK,))

def limits(c,pid,now):
 rows=c.execute('SELECT created_at,launched_at FROM monetag_ad_attempts WHERE player_id=%s AND launched_at IS NOT NULL AND created_at>=%s',(pid,now//86400*86400-3600)).fetchall()
 day=sum(r['created_at']>=now//86400*86400 for r in rows)
 hour=sum(r['launched_at']>=now-3600 for r in rows)
 last=max((r['launched_at'] for r in rows),default=0)
 wait=max(0,int(last+COOLDOWN-now+0.999))
 return dict(remaining_today=max(0,DAY_LIMIT-day),remaining_hour=max(0,HOUR_LIMIT-hour),retry_after=wait)

def prepare(c,p,item,platform,now=None):
 now=time.time() if now is None else now
 cfg=config(platform)
 if item=='geese' and p.get('farmer_level',1)<3:raise HTTPException(403,'Гуси доступны с 3-го уровня')
 if item not in REWARDS:raise HTTPException(400,'Награда не найдена')
 if not cfg['enabled']:raise HTTPException(503,cfg['reason'] or 'Рекламные награды пока настраиваются')
 quota=limits(c,p['id'],now)
 if not quota['remaining_today'] or not quota['remaining_hour'] or quota['retry_after']:raise HTTPException(429,'Лимит рекламы. Попробуйте позже')
 old=c.execute('SELECT * FROM monetag_ad_attempts WHERE player_id=%s AND placement=%s AND platform=%s AND zone_id=%s AND launched_at IS NULL AND blocked_at IS NULL AND created_at>%s ORDER BY created_at DESC LIMIT 1',(p['id'],item+'_reward',platform,cfg['zone_id'],now-PREPARE_TTL)).fetchone()
 if old:return dict(ymid=old['ymid'],expires_at=old['created_at']+PREPARE_TTL,**cfg)
 # Bound reservation spam as well as genuine launches; unused preparations are not impressions.
 n=c.execute('SELECT count(*) AS n FROM monetag_ad_attempts WHERE player_id=%s AND created_at>=%s',(p['id'],now-3600)).fetchone()['n']
 if n>=60:raise HTTPException(429,'Слишком много запросов рекламы. Попробуйте позже')
 ymid='farm_'+secrets.token_hex(20)
 c.execute('INSERT INTO monetag_ad_attempts(ymid,player_id,created_at,zone_id,placement,platform) VALUES(%s,%s,%s,%s,%s,%s)',(ymid,p['id'],now,cfg['zone_id'],item+'_reward',platform))
 return dict(ymid=ymid,expires_at=now+PREPARE_TTL,**cfg)

def report(c,p,ymid,event,result='',error='',now=None):
 now=time.time() if now is None else now
 if event not in ('started','completed','failed'):raise HTTPException(400,'Неизвестный результат рекламы')
 row=c.execute('SELECT * FROM monetag_ad_attempts WHERE ymid=%s AND player_id=%s FOR UPDATE',(ymid,p['id'])).fetchone()
 if not row:raise HTTPException(404,'Запуск рекламы не найден')
 if row['blocked_at'] is not None:return {'ok':False,'state':'rate_limited'}
 if row['launched_at'] is None:
  quota=limits(c,p['id'],now)
  if now-row['created_at']>PREPARE_TTL or not quota['remaining_today'] or not quota['remaining_hour'] or quota['retry_after']:
   c.execute('UPDATE monetag_ad_attempts SET blocked_at=%s WHERE ymid=%s',(now,ymid))
   return {'ok':False,'state':'rate_limited'}
  c.execute('UPDATE monetag_ad_attempts SET launched_at=%s WHERE ymid=%s',(now,ymid))
 if event=='completed':
  result=result if result in ('valued','non_valued') else 'no_event_data'
  c.execute('UPDATE monetag_ad_attempts SET sdk_completed_at=COALESCE(sdk_completed_at,%s),sdk_result=COALESCE(sdk_result,%s) WHERE ymid=%s',(now,result,ymid))
 if event=='failed':
  code=error if error in ('unavailable','verification_failed','blocked','timeout','network','sdk_error') else 'sdk_error'
  c.execute('UPDATE monetag_ad_attempts SET sdk_error=COALESCE(sdk_error,%s) WHERE ymid=%s',(code,ymid))
 return {'ok':True,'rewarded':False}

def money(value):
 if value=='':return None
 if len(value)>64:raise HTTPException(400,'Invalid estimated price')
 try:v=Decimal(value)
 except (InvalidOperation,ValueError):raise HTTPException(400,'Invalid estimated price')
 if not v.is_finite() or v<0 or v>1000:raise HTTPException(400,'Invalid estimated price')
 return v.quantize(Decimal('0.0000001'))

def postback(c,secret,ymid,zone_id,sub_zone_id,event_type,reward_event_type,request_var,telegram_id,estimated_price,now=None):
 now=time.time() if now is None else now
 configured=os.getenv('MONETAG_POSTBACK_SECRET','')
 if len(configured)<24 or not secret or not hmac.compare_digest(secret.encode(),configured.encode()):raise HTTPException(403,'Forbidden')
 if not re.fullmatch(r'farm_[0-9a-f]{40}',ymid):raise HTTPException(400,'Invalid event')
 if event_type not in ('impression','click') or reward_event_type not in ('valued','non_valued'):raise HTTPException(400,'Invalid event')
 price=money(estimated_price)
 row=c.execute('SELECT * FROM monetag_ad_attempts WHERE ymid=%s FOR UPDATE',(ymid,)).fetchone()
 if not row:return {'ok':True,'reason':'unknown_attempt'}
 if zone_id!=row['zone_id'] or sub_zone_id<0:raise HTTPException(400,'Wrong zone')
 # Popup sub-zones differ from the main SDK zone. Validate main zone and placement,
 # not equality of zone_id/sub_zone_id. Both prefixed popup and interstitial forms are valid.
 placement=request_var.removeprefix(str(zone_id)+'_')
 if placement!=row['placement'] or placement not in [x+'_reward' for x in REWARDS]:raise HTTPException(400,'Wrong placement')
 p=c.execute('SELECT telegram_id FROM players WHERE id=%s FOR UPDATE',(row['player_id'],)).fetchone()
 if telegram_id and (not telegram_id.isdecimal() or str(p.get('telegram_id'))!=telegram_id):raise HTTPException(400,'Wrong account')
 c.execute('INSERT INTO monetag_postback_events VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',(ymid,event_type,sub_zone_id,reward_event_type,str(price) if price is not None else None,now))
 c.execute('UPDATE monetag_ad_attempts SET confirmed_at=COALESCE(confirmed_at,%s),launched_at=COALESCE(launched_at,%s) WHERE ymid=%s',(now,now,ymid))
 if reward_event_type=='non_valued':
  c.execute('UPDATE monetag_ad_attempts SET non_valued_at=COALESCE(non_valued_at,%s) WHERE ymid=%s',(now,ymid))
  return {'ok':True,'rewarded':False,'reason':'non_valued'}
 c.execute('UPDATE monetag_ad_attempts SET valued_at=COALESCE(valued_at,%s) WHERE ymid=%s',(now,ymid))
 # Monetag's popup contract: one reward per ymid for ANY valued event.
 if row['rewarded_at'] is not None:return {'ok':True,'rewarded':False,'reason':'duplicate'}
 if row['blocked_at'] is not None or now-row['created_at']>POSTBACK_TTL:return {'ok':True,'rewarded':False,'reason':'expired_or_limited'}
 # A forged SDK callback cannot bypass these limits. Late legitimate postbacks
 # use the attempt's original UTC day, rather than resetting yesterday's budget.
 day=row['created_at']//86400*86400
 count_day=c.execute('SELECT count(*) AS n FROM monetag_ad_attempts WHERE player_id=%s AND rewarded_at IS NOT NULL AND created_at>=%s AND created_at<%s',(row['player_id'],day,day+86400)).fetchone()['n']
 count_hour=c.execute('SELECT count(*) AS n FROM monetag_ad_attempts WHERE player_id=%s AND rewarded_at IS NOT NULL AND created_at>=%s AND created_at<%s',(row['player_id'],row['created_at']//3600*3600,row['created_at']//3600*3600+3600)).fetchone()['n']
 if count_day>=DAY_LIMIT or count_hour>=HOUR_LIMIT:return {'ok':True,'rewarded':False,'reason':'reward_limit'}
 kind=row['placement'][:-7];views,qty=REWARDS[kind]
 count=c.execute('SELECT count(*) AS n FROM monetag_ad_attempts WHERE player_id=%s AND placement=%s AND rewarded_at IS NOT NULL',(row['player_id'],row['placement'])).fetchone()['n']
 c.execute('UPDATE monetag_ad_attempts SET rewarded_at=%s WHERE ymid=%s',(now,ymid))
 if (count+1)%views==0:c.execute('INSERT INTO monetag_reward_grants(id,player_id,item,quantity,created) VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',(ymid,row['player_id'],kind,qty,now))
 return {'ok':True,'rewarded':True,'player_id':row['player_id'],'progress':(count+1)%views}

def deliver(c,p,advance,coop_limit,storage_limit):
 # Catch up before adding a hen so it cannot lay eggs retroactively.
 p=advance(c,p)
 rewards=c.execute('SELECT * FROM monetag_reward_grants WHERE player_id=%s AND claimed_at IS NULL ORDER BY created,id FOR UPDATE',(p['id'],)).fetchall()
 granted=[]
 for r in rewards:
  if not ad_inventory.active(p):raise RuntimeError('Advertising provenance migration is required before delivery')
  item=r['item'];n=r['quantity']
  if item in ('chickens','geese'):
   if item=='geese' and p.get('farmer_level',1)<3:continue
   if p['chickens']+p.get('geese',0)+n>coop_limit(p):continue
   fed='fed_hens' if item=='chickens' else 'fed_geese'
   c.execute('UPDATE players SET '+item+'='+item+'+%s,'+fed+'='+fed+'+%s WHERE id=%s',(n,n,p['id']))
  elif item=='cows':
   if p.get('cows',0)+n>2*p.get('cowshed_level',1):continue
   c.execute('UPDATE players SET cows=cows+%s,fed_cows=fed_cows+%s WHERE id=%s',(n,n,p['id']))
  elif item=='coins':
   log_id=uuid.uuid4().hex
   c.execute('UPDATE players SET coins=coins+%s WHERE id=%s',(n,p['id']))
   c.execute('INSERT INTO money_log VALUES(%s,%s,%s,%s,%s,%s)',(log_id,p['id'],'ad_reward',n,'Рекламные монеты: только для покупок',time.time()))
   c.execute('INSERT INTO farm_money_sources VALUES(%s,%s,0,0)',(log_id,n))
   ad_inventory.credit(c,log_id,n)
   c.execute('UPDATE reward_emission SET total_minted=total_minted+%s WHERE id=1',(n,))
  elif item in ('grain','eggs','milk'):
   if sum(p.get(k,0) for k in ('grain','eggs','milk','feathers'))+n>storage_limit(p):continue
   c.execute('UPDATE players SET '+item+'='+item+'+%s WHERE id=%s',(n,p['id']))
  else:continue
  if item!='coins':ad_inventory.add(c,p,item,n)
  p={**p,item:p.get(item,0)+n}
  c.execute('UPDATE monetag_reward_grants SET claimed_at=%s WHERE id=%s AND claimed_at IS NULL',(time.time(),r['id']))
  granted.append({'item':item,'quantity':n})
 return {'ok':True,'granted':granted,'pending':len(rewards)-len(granted)}

def state_of(row,now):
 if row['rewarded_at'] is not None:return 'credited'
 if row['non_valued_at'] is not None:return 'non_valued'
 if row['blocked_at'] is not None:return 'rate_limited'
 if row['sdk_completed_at'] is not None and row['sdk_result'] in ('non_valued','no_event_data'):return 'unconfirmed'
 if row['sdk_error'] is not None:return 'unconfirmed' if row['sdk_error']=='verification_failed' else 'sdk_error'
 if row['launched_at'] is not None:return 'unconfirmed' if now-row['launched_at']>CONFIRM_WAIT else 'pending'
 return 'prepared'

def status(c,p,platform,now=None):
 now=time.time() if now is None else now
 rows=c.execute('SELECT * FROM monetag_ad_attempts WHERE player_id=%s ORDER BY created_at DESC',(p['id'],)).fetchall()
 totals={k:dict(views=v[0],quantity=v[1],progress=0,confirmed=0,completed=0,non_valued=0) for k,v in REWARDS.items()}
 for row in rows:
  item=row['placement'][:-7]
  if item not in totals:continue
  n=totals[item];n['confirmed']+=row['rewarded_at'] is not None;n['completed']+=row['sdk_completed_at'] is not None;n['non_valued']+=row['non_valued_at'] is not None
 for n in totals.values():n['progress']=n['confirmed']%n['views']
 grants={r['id']:r for r in c.execute('SELECT id,item,quantity,claimed_at FROM monetag_reward_grants WHERE player_id=%s',(p['id'],)).fetchall()}
 history=[dict(reward_quantity=grants.get(r['ymid'],{}).get('quantity',0),reward_claimed=grants.get(r['ymid'],{}).get('claimed_at') is not None,ymid=r['ymid'],item=r['placement'][:-7],state=state_of(r,now),platform=r['platform'],created_at=r['created_at']) for r in rows if r['launched_at'] is not None or r['confirmed_at'] is not None][:15]
 return dict(config(platform),rewards=totals,history=history,**limits(c,p['id'],now))

def statistics(c):
 attempts=c.execute('SELECT * FROM monetag_ad_attempts').fetchall()
 grants=c.execute('SELECT item,quantity,claimed_at FROM monetag_reward_grants').fetchall()
 events=c.execute("SELECT ymid,estimated_usd FROM monetag_postback_events WHERE reward_event_type='valued'").fetchall()
 # Once per show; do not double count retry, click, or multiple popup sub-zones.
 prices={}
 for e in events:
  if e['estimated_usd'] is not None:prices[e['ymid']]=max(prices.get(e['ymid'],Decimal(0)),Decimal(str(e['estimated_usd'])))
 def aggregate(rows):return dict(prepared=len(rows),starts=sum(r['launched_at'] is not None for r in rows),completed=sum(r['sdk_completed_at'] is not None for r in rows),paid=sum(r['valued_at'] is not None or r['rewarded_at'] is not None for r in rows),unpaid=sum(r['non_valued_at'] is not None for r in rows),sdk_errors=sum(r['sdk_error'] is not None for r in rows),unconfirmed=sum(state_of(r,time.time())=='unconfirmed' for r in rows))
 return dict(total=aggregate(attempts),platforms={k:aggregate([r for r in attempts if r['platform']==k]) for k in ('telegram','web','legacy')},items={k:dict(aggregate([r for r in attempts if r['placement']==k+'_reward']),granted=sum(r['quantity'] for r in grants if r['item']==k and r['claimed_at'] is not None),pending=sum(r['quantity'] for r in grants if r['item']==k and r['claimed_at'] is None)) for k in REWARDS},estimated_usd=str(sum(prices.values(),Decimal(0))) if prices else None,events_with_estimate=len(prices),settled_revenue=None)


def admin_text(c,platform=None):
 stats=statistics(c);n=stats['platforms'].get(platform,stats['total'])
 labels={'telegram':'Telegram','web':'Браузер','legacy':'До обновления'}
 text='🎬 <b>Реклама Monetag</b> · '+labels.get(platform,'Все платформы')+'\n\n'
 for key,label in [('starts','Запусков'),('completed','Завершений SDK'),('paid','Оплаченных подтверждений'),('unpaid','Неоплаченных событий'),('sdk_errors','Ошибок SDK'),('unconfirmed','Без подтверждения')]:text+=label+': <b>'+str(n[key])+'</b>\n'
 text+='\n<b>Товары · все платформы</b>\n'
 for item,title in [('grain','Зерно'),('eggs','Яйца'),('milk','Молоко'),('chickens','Куры'),('geese','Гуси'),('cows','Коровы'),('coins','Монеты для покупок')]:
  row=stats['items'][item];text+=title+': '+str(row['starts'])+' запусков · '+str(row['paid'])+' оплаченных · выдано '+str(row['granted'])+' · ждёт места '+str(row['pending'])+'\n'
 text+='\nОценка Monetag по postback: '+('$'+stats['estimated_usd'] if stats['estimated_usd'] is not None else 'нет данных')+' ('+str(stats['events_with_estimate'])+' событий с ценой).\nЭто estimated_price, не окончательный доход. Фактический доход и расчёты — в кабинете Monetag. Данные старых неподтверждённых попыток восстановить нельзя.'
 return text
