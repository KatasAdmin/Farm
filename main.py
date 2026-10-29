import os,time,uuid,secrets,hashlib,hmac,json,logging
logger=logging.getLogger("farm.security")
from urllib.parse import parse_qsl
import psycopg
from psycopg.rows import dict_row
from fastapi import FastAPI,HTTPException,Header
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from contextlib import asynccontextmanager
from production import CYCLE, FEED_EVERY, GRAIN_PRICE, simulate, forecast
def db():return psycopg.connect(os.environ["DATABASE_URL"],row_factory=dict_row)
@asynccontextmanager
async def lifespan(app):
 with db() as c:
  c.execute("CREATE TABLE IF NOT EXISTS players(id text primary key,name text unique,token text unique,coins int default 10,grain int default 5,chickens int default 1,eggs int default 0,last_feed float default 0)")
  c.execute("CREATE TABLE IF NOT EXISTS market(id text primary key,seller text,item text,quantity int,price int)")
  c.execute("CREATE TABLE IF NOT EXISTS economy(id int primary key,treasury int not null check(treasury>=0))")
  c.execute("INSERT INTO economy(id,treasury) SELECT 1,GREATEST(0,10000-(SELECT COALESCE(SUM(coins),0)::int FROM players)) WHERE NOT EXISTS(SELECT 1 FROM economy)")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS satiety integer NOT NULL DEFAULT 100")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS last_tick double precision")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS production_model integer NOT NULL DEFAULT 1")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS fed_hens integer NOT NULL DEFAULT 0")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS feed_phase integer NOT NULL DEFAULT 0")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS xp_legacy_eggs integer")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS xp_legacy_listed integer")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS xp_legacy_sold integer")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS critical_cycles integer NOT NULL DEFAULT 0")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS autobuy_enabled boolean NOT NULL DEFAULT false")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS autobuy_min integer NOT NULL DEFAULT 5")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS autobuy_amount integer NOT NULL DEFAULT 20")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS coop_level integer NOT NULL DEFAULT 1")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS storage_level integer NOT NULL DEFAULT 1")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS created_at double precision")
  c.execute("UPDATE players SET created_at=%s WHERE created_at IS NULL",(time.time(),))
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS bundle_uses integer NOT NULL DEFAULT 0")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS welcome_granted boolean NOT NULL DEFAULT false")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS game_status text NOT NULL DEFAULT 'farmer'")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS gender text NOT NULL DEFAULT 'unspecified'")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS age integer")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS avatar text NOT NULL DEFAULT 'default'")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS avatar_photo text")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS incubator_owned boolean NOT NULL DEFAULT false")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS incubation_started double precision")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS chick_ready_at double precision")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS incubator_level integer NOT NULL DEFAULT 1")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS tutorial_step integer NOT NULL DEFAULT 0")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS recovery_hash text")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS password_hash text")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS telegram_id bigint UNIQUE")
  c.execute("CREATE TABLE IF NOT EXISTS login_failures(name text PRIMARY KEY,attempts int NOT NULL DEFAULT 0,locked_until double precision NOT NULL DEFAULT 0)")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS tutorial_rewarded boolean NOT NULL DEFAULT false")
  c.execute("CREATE TABLE IF NOT EXISTS incubation_jobs(id text PRIMARY KEY,player_id text NOT NULL,started double precision NOT NULL,hatch_at double precision NOT NULL,mature_at double precision NOT NULL)")
  c.execute("INSERT INTO incubation_jobs(id,player_id,started,hatch_at,mature_at) SELECT 'legacy-'||id,id,COALESCE(incubation_started,chick_ready_at-86400),COALESCE(incubation_started+43200,chick_ready_at-43200),COALESCE(chick_ready_at,incubation_started+86400) FROM players WHERE incubation_started IS NOT NULL OR chick_ready_at IS NOT NULL ON CONFLICT(id) DO NOTHING")
  c.execute("UPDATE players SET incubation_started=NULL,chick_ready_at=NULL WHERE incubation_started IS NOT NULL OR chick_ready_at IS NOT NULL")
  c.execute("CREATE TABLE IF NOT EXISTS money_log(id text primary key,player_id text,kind text,delta int,details text,created double precision)")
  c.execute("CREATE TABLE IF NOT EXISTS withdrawal_requests(id text PRIMARY KEY,player_id text NOT NULL,amount integer NOT NULL CHECK(amount>=100),status text NOT NULL DEFAULT 'pending',created double precision NOT NULL)")
  c.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_pending_withdrawal_per_player ON withdrawal_requests(player_id) WHERE status='pending'")
  c.execute("CREATE TABLE IF NOT EXISTS daily_activity(player_id text NOT NULL,day text NOT NULL,grain_bought int NOT NULL DEFAULT 0,eggs_listed int NOT NULL DEFAULT 0,eggs_produced int NOT NULL DEFAULT 0,PRIMARY KEY(player_id,day))")
  c.execute("""UPDATE players p SET
    xp_legacy_eggs=COALESCE((SELECT SUM(eggs_produced)::int FROM daily_activity d WHERE d.player_id=p.id),0),
    xp_legacy_listed=COALESCE((SELECT SUM(eggs_listed)::int FROM daily_activity d WHERE d.player_id=p.id),0),
    xp_legacy_sold=COALESCE((SELECT SUM((split_part(details,' x',2))::int)::int FROM money_log m WHERE m.player_id=p.id AND m.kind='market_sale' AND m.details ~ '^eggs x[0-9]+$'),0)
   WHERE p.xp_legacy_eggs IS NULL""")
  c.execute("CREATE TABLE IF NOT EXISTS farm_events(id text primary key,player_id text NOT NULL,kind text NOT NULL,amount int NOT NULL,created double precision NOT NULL)")
  c.execute("CREATE TABLE IF NOT EXISTS daily_claims(player_id text NOT NULL,day text NOT NULL,claim text NOT NULL,amount int NOT NULL,PRIMARY KEY(player_id,day,claim))")
  c.execute("CREATE TABLE IF NOT EXISTS player_achievements(player_id text NOT NULL,achievement text NOT NULL,unlocked_at double precision NOT NULL,PRIMARY KEY(player_id,achievement))")
  c.execute("CREATE TABLE IF NOT EXISTS promo_codes(code_hash text PRIMARY KEY,amount integer NOT NULL CHECK(amount>0),redeemed_by text,redeemed_at double precision)")
  c.execute("INSERT INTO promo_codes(code_hash,amount) VALUES(%s,1000) ON CONFLICT(code_hash) DO NOTHING",("1cd3835191d5f622563ac4dbb45c7a568a16b6d5cd471eb21f76e98479126598",))
  c.execute("CREATE TABLE IF NOT EXISTS reward_emission(id int PRIMARY KEY,total_minted bigint NOT NULL DEFAULT 0)")
  c.execute("INSERT INTO reward_emission(id,total_minted) VALUES(1,0) ON CONFLICT(id) DO NOTHING")
  c.execute("UPDATE players SET last_tick=%s WHERE last_tick IS NULL",(time.time(),))
  c.execute("UPDATE market SET price=1 WHERE item='eggs' AND price<>1")
  # Preserve resources and balances; reset only the clock on the new production schedule.
  c.execute("UPDATE players SET production_model=3,last_tick=%s WHERE production_model<3",(time.time(),))
 yield
app=FastAPI(lifespan=lifespan)
app.mount("/assets", StaticFiles(directory="assets"), name="assets")
class Request(BaseModel):
 name:str=""
 item:str=""
 amount:int=1
 price:int=1
 gender:str="unspecified"
 age:int|None=None
 avatar:str="default"
 avatar_photo:str=""
 code:str=""
 password:str=""
 current_password:str=""
 telegram_data:str=""
def password_hash(password):
 if not 8<=len(password)<=128:raise HTTPException(400,"Пароль должен содержать от 8 до 128 символов")
 salt=secrets.token_bytes(16)
 key=hashlib.pbkdf2_hmac("sha256",password.encode(),salt,350000)
 return salt.hex()+":"+key.hex()

def password_verify(password,stored):
 if not stored or len(password)>128:return False
 try:
  salt,value=stored.split(":")
  key=hashlib.pbkdf2_hmac("sha256",password.encode(),bytes.fromhex(salt),350000)
  return hmac.compare_digest(key,bytes.fromhex(value))
 except (ValueError,TypeError):return False

def telegram_identity(raw):
 bot_token=os.environ.get("TELEGRAM_BOT_TOKEN","")
 if not bot_token:raise HTTPException(503,"Вход через Telegram пока не настроен")
 if not raw or len(raw)>12000:raise HTTPException(401,"Откройте игру через Telegram")
 pairs=dict(parse_qsl(raw,keep_blank_values=True))
 supplied=pairs.pop("hash","")
 pairs.pop("signature",None)
 try:issued=int(pairs.get("auth_date","0"))
 except ValueError:raise HTTPException(401,"Неверные данные Telegram")
 if issued>time.time()+60 or issued<time.time()-3600:raise HTTPException(401,"Откройте Telegram Mini App заново")
 check="\n".join(k+"="+v for k,v in sorted(pairs.items()))
 secret=hmac.new(b"WebAppData",bot_token.encode(),hashlib.sha256).digest()
 calculated=hmac.new(secret,check.encode(),hashlib.sha256).hexdigest()
 if not hmac.compare_digest(calculated,supplied):
  logger.warning("telegram_invalid_signature")
  raise HTTPException(401,"Не удалось проверить Telegram")
 try:user=json.loads(pairs["user"]);uid=int(user["id"])
 except (KeyError,ValueError,TypeError,json.JSONDecodeError):raise HTTPException(401,"Не найден пользователь Telegram")
 if uid<=0:raise HTTPException(401,"Неверный Telegram ID")
 return uid

def person(c,h,lock=False):
 p=c.execute("SELECT * FROM players WHERE token=%s"+(" FOR UPDATE" if lock else ""),(h.replace("Bearer ",""),)).fetchone()
 if not p:raise HTTPException(401,"Войдите в игру")
 return p
def check(n):
 if n<1 or n>10000:raise HTTPException(400,"Некорректное количество")
HEN_PRICE=40
EGG_PRICE=1
MAX_BUILDING_LEVEL=10
PROMO_SECONDS=3*86400
PROMO_PRICE=300
INCUBATOR_PRICE=120
INCUBATE_SECONDS=12*3600
GROW_SECONDS=12*3600
INCUBATOR_LEVEL_HOURS={1:24,2:24,3:20,4:18,5:16}
INCUBATOR_UPGRADE_COST={1:100,2:160,3:240,4:340}
def incubation_stages(level):
 seconds=INCUBATOR_LEVEL_HOURS[level]*3600
 return seconds//2,seconds-seconds//2
def coop_limit(p):return 10*p["coop_level"]
def storage_limit(p):return 100*p["storage_level"]
def upgrade_cost(kind,level):return (40 if kind=="coop" else 30)*level
def update_incubation(c,p,now):
 jobs=c.execute("SELECT id FROM incubation_jobs WHERE player_id=%s AND mature_at<=%s ORDER BY mature_at,id FOR UPDATE",(p["id"],now)).fetchall()
 free=max(0,coop_limit(p)-p["chickens"])
 matured=min(len(jobs),free)
 if matured:
  for row in jobs[:matured]:c.execute("DELETE FROM incubation_jobs WHERE id=%s",(row["id"],))
  c.execute("UPDATE players SET chickens=chickens+%s WHERE id=%s",(matured,p["id"]))
  c.execute("INSERT INTO farm_events(id,player_id,kind,amount,created) VALUES(%s,%s,%s,%s,%s)",(uuid.uuid4().hex,p["id"],"chick_matured",matured,now))
  p={**p,"chickens":p["chickens"]+matured}
 return p
def advance(c,p,now=None):
 """Process 6h egg ticks and 18h feeding ticks server-side without retroactive production."""
 now=time.time() if now is None else now
 start=p["last_tick"] if p["last_tick"] is not None else now
 due=max(0,int((now-start)//CYCLE))
 if due<=0:return update_incubation(c,p,now)
 result,produced,refills=simulate(p,now)
 for refill in refills:
  c.execute("UPDATE economy SET treasury=treasury+%s WHERE id=1",(GRAIN_PRICE*refill,))
  c.execute("INSERT INTO money_log VALUES(%s,%s,%s,%s,%s,%s)",(uuid.uuid4().hex,p["id"],"auto_grain",-GRAIN_PRICE*refill,"Зерно: "+str(refill),now))
 if produced:
  day=time.strftime("%Y-%m-%d",time.gmtime(now))
  c.execute("INSERT INTO daily_activity(player_id,day,eggs_produced) VALUES(%s,%s,%s) ON CONFLICT(player_id,day) DO UPDATE SET eggs_produced=daily_activity.eggs_produced+EXCLUDED.eggs_produced",(p["id"],day,produced))
  c.execute("INSERT INTO farm_events(id,player_id,kind,amount,created) VALUES(%s,%s,%s,%s,%s)",(uuid.uuid4().hex,p["id"],"eggs_produced",produced,now))
 c.execute("UPDATE players SET coins=%s,grain=%s,eggs=%s,chickens=%s,satiety=%s,critical_cycles=%s,fed_hens=%s,feed_phase=%s,last_tick=%s WHERE id=%s",tuple(result[k] for k in ("coins","grain","eggs","chickens","satiety","critical_cycles","fed_hens","feed_phase","last_tick"))+(p["id"],))
 return update_incubation(c,result,now)
@app.get("/",response_class=HTMLResponse)
def index():return open("index.html",encoding="utf8").read()
@app.get("/health")
def health():return {"ok":True}
@app.post("/api/join")
def join(q:Request):
 name=q.name.strip()[:22]
 if len(name)<2:raise HTTPException(400,"Ник должен содержать от 2 до 22 символов")
 if q.gender not in ("male","female","unspecified"):raise HTTPException(400,"Некорректный пол")
 stored=password_hash(q.password)
 token=secrets.token_hex(24)
 try:
  with db() as c:
   # Serialize sign-ups to avoid duplicate nicknames differing only by case.
   c.execute("SELECT pg_advisory_xact_lock(1984532)")
   if c.execute("SELECT 1 FROM players WHERE lower(name)=lower(%s)",(name,)).fetchone():
    raise HTTPException(409,"Ник уже занят")
   treasury=c.execute("SELECT treasury FROM economy WHERE id=1 FOR UPDATE").fetchone()["treasury"]
   if treasury<10:raise HTTPException(409,"Стартовый фонд исчерпан")
   c.execute("INSERT INTO players(id,name,token,coins,last_tick,created_at,gender,password_hash,production_model,fed_hens,feed_phase,xp_legacy_eggs,xp_legacy_listed,xp_legacy_sold) VALUES(%s,%s,%s,10,%s,%s,%s,%s,3,1,0,0,0,0)",(uuid.uuid4().hex,name,token,time.time(),time.time(),q.gender,stored))
   c.execute("UPDATE economy SET treasury=treasury-10 WHERE id=1")
   c.execute("INSERT INTO money_log VALUES(%s,%s,%s,%s,%s,%s)",(uuid.uuid4().hex,None,"new_player",-10,"Начальный баланс: "+name,time.time()))
 except psycopg.errors.UniqueViolation:raise HTTPException(409,"Ник уже занят")
 return {"token":token}

@app.post("/api/login")
def password_login(q:Request):
 name=q.name.strip()
 if not name or not q.password:raise HTTPException(400,"Укажите ник и пароль")
 now=time.time()
 failure=None
 token=None
 with db() as c:
  c.execute("INSERT INTO login_failures(name,attempts,locked_until) VALUES(%s,0,0) ON CONFLICT DO NOTHING",(name.lower(),))
  fail=c.execute("SELECT * FROM login_failures WHERE name=%s FOR UPDATE",(name.lower(),)).fetchone()
  if fail["locked_until"]>now:
   failure=429
  else:
   p=c.execute("SELECT id,password_hash FROM players WHERE lower(name)=lower(%s) FOR UPDATE",(name,)).fetchone()
   if not p or not password_verify(q.password,p["password_hash"]):
    attempts=fail["attempts"]+1
    blocked=now+900 if attempts>=5 else 0
    c.execute("UPDATE login_failures SET attempts=%s,locked_until=%s WHERE name=%s",(0 if blocked else attempts,blocked,name.lower()))
    failure=401
   else:
    c.execute("UPDATE login_failures SET attempts=0,locked_until=0 WHERE name=%s",(name.lower(),))
    token=secrets.token_hex(24)
    c.execute("UPDATE players SET token=%s WHERE id=%s",(token,p["id"]))
 if failure==429:raise HTTPException(429,"Слишком много попыток. Попробуйте через 15 минут")
 if failure:
  logger.warning("password_login_failed")
  raise HTTPException(401,"Неверный ник или пароль")
 return {"token":token}

@app.post("/api/password/set")
def set_password(q:Request,authorization:str=Header(default="")):
 stored=password_hash(q.password)
 with db() as c:
  p=person(c,authorization,True)
  if p["password_hash"] and not password_verify(q.current_password,p["password_hash"]):
   raise HTTPException(403,"Чтобы изменить пароль, введите действующий пароль")
  c.execute("UPDATE players SET password_hash=%s WHERE id=%s",(stored,p["id"]))
 return {"ok":True}

@app.get("/api/auth/config")
def auth_config():
 return {"telegram_enabled":bool(os.environ.get("TELEGRAM_BOT_TOKEN"))}

@app.post("/api/telegram/link")
def link_telegram(q:Request,authorization:str=Header(default="")):
 uid=telegram_identity(q.telegram_data)
 with db() as c:
  c.execute("SELECT pg_advisory_xact_lock(%s)",(uid,))
  p=person(c,authorization,True)
  if p["telegram_id"] is not None and p["telegram_id"]!=uid:raise HTTPException(409,"Сначала отвяжите прежний Telegram через поддержку")
  other=c.execute("SELECT id FROM players WHERE telegram_id=%s",(uid,)).fetchone()
  if other and other["id"]!=p["id"]:raise HTTPException(409,"Этот Telegram уже привязан к другой ферме")
  c.execute("UPDATE players SET telegram_id=%s WHERE id=%s",(uid,p["id"]))
 return {"ok":True}

@app.post("/api/telegram/login")
def login_telegram(q:Request):
 uid=telegram_identity(q.telegram_data)
 with db() as c:
  c.execute("SELECT pg_advisory_xact_lock(%s)",(uid,))
  p=c.execute("SELECT id FROM players WHERE telegram_id=%s FOR UPDATE",(uid,)).fetchone()
  if not p:
   treasury=c.execute("SELECT treasury FROM economy WHERE id=1 FOR UPDATE").fetchone()["treasury"]
   if treasury<10:raise HTTPException(409,"Новые регистрации временно закрыты")
   name="tg_"+str(uid)
   if c.execute("SELECT 1 FROM players WHERE lower(name)=lower(%s)",(name,)).fetchone():
    raise HTTPException(409,"Выберите другой способ входа")
   pid=uuid.uuid4().hex
   c.execute("INSERT INTO players(id,name,token,coins,last_tick,created_at,telegram_id,production_model,fed_hens,feed_phase,xp_legacy_eggs,xp_legacy_listed,xp_legacy_sold) VALUES(%s,%s,%s,10,%s,%s,%s,3,1,0,0,0,0)",(pid,name,secrets.token_hex(24),time.time(),time.time(),uid))
   c.execute("UPDATE economy SET treasury=treasury-10 WHERE id=1")
   c.execute("INSERT INTO money_log VALUES(%s,%s,%s,%s,%s,%s)",(uuid.uuid4().hex,None,"new_player",-10,"Начальный баланс: "+name,time.time()))
   p={"id":pid}
  token=secrets.token_hex(24)
  c.execute("UPDATE players SET token=%s WHERE id=%s",(token,p["id"]))
 return {"token":token}

@app.post("/api/nickname/set")
def set_nickname(q:Request,authorization:str=Header(default="")):
 name=q.name.strip()[:22]
 if len(name)<2:raise HTTPException(400,"Ник должен содержать от 2 до 22 символов")
 with db() as c:
  c.execute("SELECT pg_advisory_xact_lock(1984532)")
  p=person(c,authorization,True)
  if not p["name"].startswith("tg_"):raise HTTPException(409,"Ник уже установлен")
  if c.execute("SELECT 1 FROM players WHERE lower(name)=lower(%s) AND id<>%s",(name,p["id"])).fetchone():
   raise HTTPException(409,"Ник уже занят")
  c.execute("UPDATE players SET name=%s WHERE id=%s",(name,p["id"]))
 return {"ok":True}

@app.get("/api/state")
def state(authorization:str=Header(default="")):
 with db() as c:
  p=advance(c,person(c,authorization,True))
  # New accounts start with 10 coins; previous balances remain untouched.
  if not p["welcome_granted"]:
   c.execute("UPDATE players SET welcome_granted=true WHERE id=%s",(p["id"],))
   p={**p,"welcome_granted":True}
  listings=c.execute("SELECT m.item,m.price,m.quantity,p.name AS seller FROM market m JOIN players p ON p.id=m.seller WHERE m.quantity>0 ORDER BY m.price LIMIT 40").fetchall()
  available_eggs=c.execute("SELECT COALESCE(SUM(quantity),0)::int AS total FROM market WHERE item=%s AND seller<>%s AND quantity>0",("eggs",p["id"])).fetchone()["total"]
  mine=c.execute("SELECT id,item,quantity,price FROM market WHERE seller=%s AND quantity>0 ORDER BY item,price,id",(p["id"],)).fetchall()
  top=c.execute("SELECT name,coins,chickens FROM players ORDER BY coins DESC LIMIT 8").fetchall()
  day=time.strftime("%Y-%m-%d",time.gmtime())
  activity=c.execute("SELECT grain_bought,eggs_listed,eggs_produced FROM daily_activity WHERE player_id=%s AND day=%s",(p["id"],day)).fetchone() or {"grain_bought":0,"eggs_listed":0,"eggs_produced":0}
  event=c.execute("SELECT id,kind,amount FROM farm_events WHERE player_id=%s ORDER BY created DESC,id DESC LIMIT 1",(p["id"],)).fetchone()
  claims=[x["claim"] for x in c.execute("SELECT claim FROM daily_claims WHERE player_id=%s AND day=%s",(p["id"],day)).fetchall()]
  minted=c.execute("SELECT total_minted FROM reward_emission WHERE id=1").fetchone()["total_minted"]
  totals=c.execute("SELECT COALESCE(SUM(grain_bought),0)::int AS grain_bought,COALESCE(SUM(eggs_listed),0)::int AS eggs_listed,COALESCE(SUM(eggs_produced),0)::int AS eggs_produced FROM daily_activity WHERE player_id=%s",(p["id"],)).fetchone()
  sold=c.execute("SELECT COALESCE(SUM((split_part(details,' x',2))::int),0)::int AS amount FROM money_log WHERE player_id=%s AND kind='market_sale' AND details ~ '^eggs x[0-9]+$'",(p["id"],)).fetchone()["amount"]
  hens_bought=c.execute("SELECT COALESCE(SUM((split_part(details,' x',2))::int),0)::int AS n FROM money_log WHERE player_id=%s AND kind='shop' AND details ~ '^chickens x[0-9]+$'",(p["id"],)).fetchone()["n"]
  missions=c.execute("SELECT COUNT(*)::int AS n FROM daily_claims WHERE player_id=%s AND claim<>%s",(p["id"],"bonus")).fetchone()["n"]
  upgrades=c.execute("SELECT COUNT(*)::int AS n FROM money_log WHERE player_id=%s AND kind='upgrade'",(p["id"],)).fetchone()["n"]
  hatched=c.execute("SELECT COUNT(*)::int AS n FROM farm_events WHERE player_id=%s AND kind='chick_matured'",(p["id"],)).fetchone()["n"]
  packs=c.execute("SELECT COUNT(*)::int AS n FROM money_log WHERE player_id=%s AND kind='bundle'",(p["id"],)).fetchone()["n"]
  old_eggs=p["xp_legacy_eggs"] or 0
  old_listed=p["xp_legacy_listed"] or 0
  old_sold=p["xp_legacy_sold"] or 0
  egg_xp=5*old_eggs+5*((max(0,totals["eggs_produced"]-old_eggs)+11)//12)
  listing_xp=2*old_listed+2*((max(0,totals["eggs_listed"]-old_listed)+11)//12)
  sales_xp=3*old_sold+3*((max(0,sold-old_sold)+11)//12)
  xp=totals["grain_bought"]+egg_xp+listing_xp+sales_xp+10*hens_bought+15*missions+20*upgrades+25*hatched+20*packs
  import math
  level=1+math.isqrt(xp//25)
  next_xp=25*level*level
  unlocked={
   "first_egg":totals["eggs_produced"]>=1,
   "ten_eggs":totals["eggs_produced"]>=120,
   "three_hens":p["chickens"]>=3,
   "first_sale":sold>=1,
   "hundred_sales":sold>=1200
  }
  for key,yes in unlocked.items():
   if yes:c.execute("INSERT INTO player_achievements(player_id,achievement,unlocked_at) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING",(p["id"],key,time.time()))
  achievements=[x["achievement"] for x in c.execute("SELECT achievement FROM player_achievements WHERE player_id=%s",(p["id"],)).fetchall()]
  promotion={"active":time.time()<p["created_at"]+PROMO_SECONDS and p["bundle_uses"]<5,"seconds_left":max(0,int(p["created_at"]+PROMO_SECONDS-time.time())),"used":p["bundle_uses"],"limit":5,"price":PROMO_PRICE,"value":600}
  jobs=c.execute("SELECT id,started,hatch_at,mature_at FROM incubation_jobs WHERE player_id=%s ORDER BY started,id",(p["id"],)).fetchall()
  stage_seconds=incubation_stages(p["incubator_level"])
  incubation={"owned":p["incubator_owned"],"level":p["incubator_level"],"capacity":p["incubator_level"],"jobs":jobs,"active":len(jobs),"next_upgrade_cost":INCUBATOR_UPGRADE_COST.get(p["incubator_level"]),"incubator_price":INCUBATOR_PRICE,"incubate_seconds":stage_seconds[0],"grow_seconds":stage_seconds[1]}
  tutorial={"step":p["tutorial_step"],"completed":p["tutorial_step"]>=3,"rewarded":p["tutorial_rewarded"]}

  observed_at=time.time()
  prediction=forecast(p,observed_at,jobs)
  expected_eggs=min(p["fed_hens"],max(0,storage_limit(p)-p["grain"]-p["eggs"]))
  production_history=c.execute("SELECT id,amount,created FROM farm_events WHERE player_id=%s AND kind='eggs_produced' ORDER BY created DESC,id DESC LIMIT 10",(p["id"],)).fetchall()
  return {"tutorial":tutorial,"production_history":production_history,"promotion":promotion,"incubator":incubation,"buildings":{"coop_level":p["coop_level"],"storage_level":p["storage_level"],"coop_capacity":coop_limit(p),"storage_capacity":storage_limit(p),"storage_used":p["grain"]+p["eggs"],"max_level":MAX_BUILDING_LEVEL,"coop_next_cost":upgrade_cost("coop",p["coop_level"]) if p["coop_level"]<MAX_BUILDING_LEVEL else None,"storage_next_cost":upgrade_cost("storage",p["storage_level"]) if p["storage_level"]<MAX_BUILDING_LEVEL else None},"progression":{"xp":xp,"level":level,"next_level_xp":next_xp,"achievements":achievements,"totals":{**totals,"eggs_sold":sold}},"available_eggs":available_eggs,"daily":activity,"daily_day":day,"claimed_rewards":claims,"reward_minted_total":minted,"reward_values":{"bonus":2,"grain":1,"eggs":1,"listing":1},"last_farm_event":event,"shop":{"grain":GRAIN_PRICE,"chickens":HEN_PRICE,"eggs":EGG_PRICE},"economy":{"treasury":c.execute("SELECT treasury FROM economy WHERE id=1").fetchone()["treasury"]},"farm":{**prediction,"expected_eggs":expected_eggs,"cycle_seconds":CYCLE,"seconds_to_next":max(0,int(CYCLE-(time.time()-p["last_tick"]))),"feeding_per_cycle":p["chickens"],"feed_cycles_available":3*p["grain"]//max(1,p["chickens"]),"feed_seconds_to_next":(FEED_EVERY-p["feed_phase"])*CYCLE-max(0,time.time()-p["last_tick"]),"feed_interval_seconds":FEED_EVERY*CYCLE,"fed_hens":p["fed_hens"]},"has_password":bool(p["password_hash"]),"me":{k:v for k,v in p.items() if k not in ("token","password_hash","recovery_hash")},"market":listings,"my_listings":mine,"top":top,"now":observed_at}
@app.post("/api/shop")
def shop(q:Request,authorization:str=Header(default="")):
 check(q.amount)
 if q.item not in ("grain","chickens"):raise HTTPException(400,"Товар не найден")
 cost=q.amount*(GRAIN_PRICE if q.item=="grain" else HEN_PRICE)
 with db() as c:
  p=advance(c,person(c,authorization,True))
  if p["coins"]<cost:raise HTTPException(400,"Недостаточно монет")
  if q.item=="chickens" and p["chickens"]+q.amount>coop_limit(p):raise HTTPException(400,"В курятнике нет места. Улучшите курятник")
  if q.item=="grain" and p["grain"]+p["eggs"]+q.amount>storage_limit(p):raise HTTPException(400,"На складе нет места. Улучшите склад")
  c.execute("UPDATE players SET coins=coins-%s,"+q.item+"="+q.item+"+%s WHERE id=%s",(cost,q.amount,p["id"]))
  if q.item=="grain":
   day=time.strftime("%Y-%m-%d",time.gmtime())
   c.execute("INSERT INTO daily_activity(player_id,day,grain_bought) VALUES(%s,%s,%s) ON CONFLICT(player_id,day) DO UPDATE SET grain_bought=daily_activity.grain_bought+EXCLUDED.grain_bought",(p["id"],day,q.amount))
  c.execute("UPDATE economy SET treasury=treasury+%s WHERE id=1",(cost,))
  c.execute("INSERT INTO money_log VALUES(%s,%s,%s,%s,%s,%s)",(uuid.uuid4().hex,p["id"],"shop",-cost,q.item+" x"+str(q.amount),time.time()))
 return {"ok":True}
@app.post("/api/bundle")
def buy_bundle(authorization:str=Header(default="")):
 now=time.time()
 with db() as c:
  p=advance(c,person(c,authorization,True))
  if now>=p["created_at"]+PROMO_SECONDS or p["bundle_uses"]>=5:raise HTTPException(400,"Акция завершена")
  if p["coins"]<PROMO_PRICE:raise HTTPException(400,"Недостаточно монет")
  hens=p["chickens"]+10
  items=p["grain"]+p["eggs"]+100
  coop=max(p["coop_level"],(hens+9)//10)
  storage=max(p["storage_level"],(items+99)//100)
  if coop>MAX_BUILDING_LEVEL or storage>MAX_BUILDING_LEVEL:raise HTTPException(400,"Достигнута максимальная вместимость построек")
  c.execute("UPDATE players SET coins=coins-%s,chickens=%s,grain=grain+100,coop_level=%s,storage_level=%s,bundle_uses=bundle_uses+1 WHERE id=%s",(PROMO_PRICE,hens,coop,storage,p["id"]))
  c.execute("UPDATE economy SET treasury=treasury+%s WHERE id=1",(PROMO_PRICE,))
  c.execute("INSERT INTO money_log VALUES(%s,%s,%s,%s,%s,%s)",(uuid.uuid4().hex,p["id"],"bundle",-PROMO_PRICE,"Акция: 10 кур + 100 зерна (стоимость товаров 600)",now))
 return {"ok":True,"spent":PROMO_PRICE}

@app.post("/api/feed")
def feed_disabled():
 raise HTTPException(410,"Кормление теперь автоматическое: положите зерно на склад")

@app.post("/api/sell")
def sell(q:Request,authorization:str=Header(default="")):
 check(q.amount);check(q.price)
 if q.item not in ("grain","eggs"):raise HTTPException(400,"Товар не найден")
 with db() as c:
  p=advance(c,person(c,authorization,True))
  if p[q.item]<q.amount:raise HTTPException(400,"Недостаточно товара")
  c.execute("UPDATE players SET "+q.item+"="+q.item+"-%s WHERE id=%s",(q.amount,p["id"]))
  price=EGG_PRICE if q.item=="eggs" else q.price
  c.execute("INSERT INTO market VALUES(%s,%s,%s,%s,%s)",(uuid.uuid4().hex,p["id"],q.item,q.amount,price))
  if q.item=="eggs":
   day=time.strftime("%Y-%m-%d",time.gmtime())
   c.execute("INSERT INTO daily_activity(player_id,day,eggs_listed) VALUES(%s,%s,%s) ON CONFLICT(player_id,day) DO UPDATE SET eggs_listed=daily_activity.eggs_listed+EXCLUDED.eggs_listed",(p["id"],day,q.amount))
 return {"ok":True}
@app.post("/api/buy")
def buy(q:Request,authorization:str=Header(default="")):
 check(q.amount)
 if q.item not in ("grain","eggs"):raise HTTPException(400,"Товар не найден")
 with db() as c:
  p=advance(c,person(c,authorization,True))
  rows=c.execute("SELECT * FROM market WHERE item=%s AND seller<>%s AND quantity>0 ORDER BY price,id FOR UPDATE",(q.item,p["id"])).fetchall()
  if sum(x["quantity"] for x in rows)<q.amount:raise HTTPException(400,"Недостаточно товара на рынке")
  remaining=q.amount;chosen=[]
  for price in sorted(set(x["price"] for x in rows)):
   group=[x for x in rows if x["price"]==price]
   available=sum(x["quantity"] for x in group)
   target=min(remaining,available)
   weights=[(x,target*x["quantity"]//available,(target*x["quantity"])%available) for x in group]
   extra=target-sum(z[1] for z in weights)
   weights.sort(key=lambda z:(-z[2],z[0]["id"]))
   for x,n,_ in weights:
    allocated=n+(1 if extra>0 else 0)
    if extra>0:extra-=1
    if allocated:chosen.append((x,allocated))
   remaining-=target
   if remaining==0:break
  cost=sum(x["price"]*n for x,n in chosen)
  if p["coins"]<cost:raise HTTPException(400,"Недостаточно монет")
  if p["grain"]+p["eggs"]+q.amount>storage_limit(p):raise HTTPException(400,"На складе нет места. Улучшите склад")
  c.execute("UPDATE players SET coins=coins-%s,"+q.item+"="+q.item+"+%s WHERE id=%s",(cost,q.amount,p["id"]))
  for x,n in chosen:
   c.execute("UPDATE market SET quantity=quantity-%s WHERE id=%s",(n,x["id"]))
   c.execute("UPDATE players SET coins=coins+%s WHERE id=%s",(x["price"]*n,x["seller"]))
   c.execute("INSERT INTO money_log VALUES(%s,%s,%s,%s,%s,%s)",(uuid.uuid4().hex,x["seller"],"market_sale",x["price"]*n,q.item+" x"+str(n),time.time()))
  c.execute("INSERT INTO money_log VALUES(%s,%s,%s,%s,%s,%s)",(uuid.uuid4().hex,p["id"],"market_buy",-cost,q.item+" x"+str(q.amount),time.time()))
 return {"ok":True,"spent":cost}

@app.post("/api/cancel/{listing_id}")
def cancel_listing(listing_id:str,authorization:str=Header(default="")):
 if len(listing_id)!=32:raise HTTPException(400,"Неверный номер объявления")
 with db() as c:
  p=advance(c,person(c,authorization,True))
  entry=c.execute("SELECT * FROM market WHERE id=%s AND seller=%s FOR UPDATE",(listing_id,p["id"])).fetchone()
  if not entry or entry["quantity"]<=0:raise HTTPException(404,"Объявление уже закрыто")
  if entry["item"] not in ("grain","eggs"):raise HTTPException(400,"Некорректный товар")
  if p["grain"]+p["eggs"]+entry["quantity"]>storage_limit(p):raise HTTPException(409,"На складе не хватает места для возврата. Освободите или расширьте склад")
  c.execute("UPDATE players SET "+entry["item"]+"="+entry["item"]+"+%s WHERE id=%s",(entry["quantity"],p["id"]))
  c.execute("UPDATE market SET quantity=0 WHERE id=%s",(listing_id,))
 return {"ok":True,"returned":entry["quantity"]}

@app.post("/api/withdraw/request")
def request_withdrawal(q:Request,authorization:str=Header(default="")):
 if q.amount<100:raise HTTPException(400,"Минимальная заявка — 100 монет")
 if q.amount>1000000:raise HTTPException(400,"Сумма заявки слишком большая")
 with db() as c:
  p=advance(c,person(c,authorization,True))
  if not p["telegram_id"]:raise HTTPException(403,"Для заявки на вывод сначала привяжите Telegram в профиле")
  if p["coins"]<q.amount:raise HTTPException(400,"Недостаточно монет")
  if c.execute("SELECT 1 FROM withdrawal_requests WHERE player_id=%s AND status='pending'",(p["id"],)).fetchone():
   raise HTTPException(409,"Предыдущая заявка ещё ожидает проверки")
  request_id=uuid.uuid4().hex
  c.execute("INSERT INTO withdrawal_requests(id,player_id,amount,status,created) VALUES(%s,%s,%s,'pending',%s)",(request_id,p["id"],q.amount,time.time()))
 return {"ok":True,"id":request_id,"status":"pending"}

@app.get("/api/withdraw/status")
def withdrawal_status(authorization:str=Header(default="")):
 with db() as c:
  p=person(c,authorization)
  last=c.execute("SELECT id,amount,status,created FROM withdrawal_requests WHERE player_id=%s ORDER BY created DESC LIMIT 1",(p["id"],)).fetchone()
 return {"minimum":100,"request":last,"payouts_enabled":False}

@app.post("/api/promo/redeem")
def redeem_promo(q:Request,authorization:str=Header(default="")):
 # Code is never stored as plaintext. The initial code has 20 random characters.
 code=q.code.strip().upper()
 if len(code)>64 or not code.startswith("FARM-") or len(code)!=28:
  raise HTTPException(400,"Неверный формат бонусного кода")
 digest=hashlib.sha256(code.encode("utf-8")).hexdigest()
 with db() as c:
  p=person(c,authorization,True)
  row=c.execute("UPDATE promo_codes SET redeemed_by=%s,redeemed_at=%s WHERE code_hash=%s AND redeemed_by IS NULL RETURNING amount",(p["id"],time.time(),digest)).fetchone()
  if row is None:
   raise HTTPException(409,"Код неверный или уже использован")
  amount=row["amount"]
  c.execute("UPDATE players SET coins=coins+%s WHERE id=%s",(amount,p["id"]))
  c.execute("UPDATE reward_emission SET total_minted=total_minted+%s WHERE id=1",(amount,))
  c.execute("INSERT INTO money_log(id,player_id,kind,delta,details,created) VALUES(%s,%s,%s,%s,%s,%s)",(uuid.uuid4().hex,p["id"],"promo_reward",amount,"Одноразовый бонусный код",time.time()))
 return {"ok":True,"awarded":amount}

@app.get("/api/finance")
def finance(authorization:str=Header(default="")):
 with db() as c:
  p=person(c,authorization)
  logs=c.execute("SELECT kind,delta,details,created FROM money_log WHERE player_id=%s ORDER BY created DESC LIMIT 25",(p["id"],)).fetchall()
  return {"entries":logs}
@app.post("/api/autobuy")
def autobuy(q:Request,authorization:str=Header(default="")):
 if q.item not in ("on","off"):raise HTTPException(400,"Неверное действие")
 check(q.amount)
 if q.amount>2000:raise HTTPException(400,"Слишком большая автозакупка")
 with db() as c:
  p=advance(c,person(c,authorization,True))
  c.execute("UPDATE players SET autobuy_enabled=%s,autobuy_amount=%s WHERE id=%s",(q.item=="on",q.amount,p["id"]))
 return {"ok":True}

# Small fixed daily grants. Minted rewards are recorded separately from the original 10,000-coin treasury.
REWARD_AMOUNTS={"bonus":2,"grain":1,"eggs":1,"listing":1}
@app.post("/api/claim")
def claim_reward(q:Request,authorization:str=Header(default="")):
 key=q.item
 if key not in REWARD_AMOUNTS:raise HTTPException(400,"Неизвестная награда")
 day=time.strftime("%Y-%m-%d",time.gmtime())
 with db() as c:
  p=advance(c,person(c,authorization,True))
  if key!="bonus":
   activity=c.execute("SELECT grain_bought,eggs_listed,eggs_produced FROM daily_activity WHERE player_id=%s AND day=%s",(p["id"],day)).fetchone()
   if not activity:raise HTTPException(400,"Задание ещё не выполнено")
   field={"grain":"grain_bought","eggs":"eggs_produced","listing":"eggs_listed"}[key]
   target=5 if key=="grain" else (3 if key=="eggs" else 1)
   if activity[field]<target:raise HTTPException(400,"Задание ещё не выполнено")
  amount=REWARD_AMOUNTS[key]
  saved=c.execute("INSERT INTO daily_claims(player_id,day,claim,amount) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING amount",(p["id"],day,key,amount)).fetchone()
  if saved is None:raise HTTPException(409,"Сегодня награда уже получена")
  c.execute("UPDATE players SET coins=coins+%s WHERE id=%s",(amount,p["id"]))
  c.execute("UPDATE reward_emission SET total_minted=total_minted+%s WHERE id=1",(amount,))
  c.execute("INSERT INTO money_log VALUES(%s,%s,%s,%s,%s,%s)",(uuid.uuid4().hex,p["id"],"daily_reward",amount,"Ежедневный бонус" if key=="bonus" else "Награда за задание: "+key,time.time()))
 return {"ok":True,"awarded":amount,"day":day}
@app.post("/api/upgrade")
def upgrade(q:Request,authorization:str=Header(default="")):
 if q.item not in ("coop","storage"):raise HTTPException(400,"Неизвестная постройка")
 key="coop_level" if q.item=="coop" else "storage_level"
 with db() as c:
  p=advance(c,person(c,authorization,True))
  level=p[key]
  if level>=MAX_BUILDING_LEVEL:raise HTTPException(400,"Максимальный уровень уже достигнут")
  cost=upgrade_cost(q.item,level)
  if p["coins"]<cost:raise HTTPException(400,"Недостаточно монет")
  c.execute("UPDATE players SET coins=coins-%s,"+key+"="+key+"+1 WHERE id=%s",(cost,p["id"]))
  c.execute("UPDATE economy SET treasury=treasury+%s WHERE id=1",(cost,))
  c.execute("INSERT INTO money_log VALUES(%s,%s,%s,%s,%s,%s)",(uuid.uuid4().hex,p["id"],"upgrade",-cost,"Улучшение "+("курятника" if q.item=="coop" else "склада")+" до уровня "+str(level+1),time.time()))
 return {"ok":True,"spent":cost,"level":level+1}

@app.post("/api/profile")
def save_profile(q:Request,authorization:str=Header(default="")):
 if q.gender not in ("male","female","unspecified"):raise HTTPException(400,"Некорректный пол")
 if q.age is not None and not 1<=q.age<=120:raise HTTPException(400,"Возраст должен быть от 1 до 120")
 if q.avatar not in ("default","farmer","flower","chicken","egg","custom"):raise HTTPException(400,"Выберите доступный аватар")
 if q.avatar_photo and (len(q.avatar_photo)>140000 or not q.avatar_photo.startswith("data:image/jpeg;base64,")):raise HTTPException(400,"Фото должно быть JPEG до 100 КБ")
 with db() as c:
  p=person(c,authorization,True)
  if q.avatar=="custom" and not (q.avatar_photo or p["avatar_photo"]):raise HTTPException(400,"Сначала выберите фотографию")
  c.execute("UPDATE players SET gender=%s,age=%s,avatar=%s,avatar_photo=COALESCE(%s,avatar_photo) WHERE id=%s",(q.gender,q.age,q.avatar,q.avatar_photo or None,p["id"]))
 return {"ok":True}

@app.post("/api/incubator")
def incubator_action(q:Request,authorization:str=Header(default="")):
 if q.item not in ("buy","start","upgrade"):raise HTTPException(400,"Некорректное действие")
 with db() as c:
  p=advance(c,person(c,authorization,True))
  if q.item=="buy":
   if p["incubator_owned"]:raise HTTPException(409,"Инкубатор уже куплен")
   if p["coins"]<INCUBATOR_PRICE:raise HTTPException(400,"Недостаточно монет")
   c.execute("UPDATE players SET coins=coins-%s,incubator_owned=true WHERE id=%s",(INCUBATOR_PRICE,p["id"]))
   c.execute("UPDATE economy SET treasury=treasury+%s WHERE id=1",(INCUBATOR_PRICE,))
   c.execute("INSERT INTO money_log VALUES(%s,%s,%s,%s,%s,%s)",(uuid.uuid4().hex,p["id"],"incubator",-INCUBATOR_PRICE,"Покупка инкубатора",time.time()))
   return {"ok":True,"spent":INCUBATOR_PRICE}
  if not p["incubator_owned"]:raise HTTPException(400,"Сначала купите инкубатор")
  if q.item=="upgrade":
   cost=INCUBATOR_UPGRADE_COST.get(p["incubator_level"])
   if cost is None:raise HTTPException(400,"Максимальный уровень")
   if p["coins"]<cost:raise HTTPException(400,"Недостаточно монет")
   c.execute("UPDATE players SET coins=coins-%s,incubator_level=incubator_level+1 WHERE id=%s",(cost,p["id"]))
   c.execute("UPDATE economy SET treasury=treasury+%s WHERE id=1",(cost,))
   c.execute("INSERT INTO money_log VALUES(%s,%s,%s,%s,%s,%s)",(uuid.uuid4().hex,p["id"],"incubator_upgrade",-cost,"Инкубатор: уровень "+str(p["incubator_level"]+1),time.time()))
   return {"ok":True,"spent":cost}
  active=c.execute("SELECT COUNT(*)::int AS n FROM incubation_jobs WHERE player_id=%s",(p["id"],)).fetchone()["n"]
  if active>=p["incubator_level"]:raise HTTPException(409,"Все места инкубатора заняты")
  if p["eggs"]<12:raise HTTPException(400,"Для выведения курицы нужно 12 яиц")
  if p["coins"]<15:raise HTTPException(400,"Для инкубации нужно 15 монет")
  if p["chickens"]+active>=coop_limit(p):raise HTTPException(400,"Расширьте курятник")
  now=time.time()
  egg_seconds,grow_seconds=incubation_stages(p["incubator_level"])
  c.execute("UPDATE players SET eggs=eggs-12,coins=coins-15 WHERE id=%s",(p["id"],))
  c.execute("UPDATE economy SET treasury=treasury+15 WHERE id=1")
  c.execute("INSERT INTO money_log VALUES(%s,%s,%s,%s,%s,%s)",(uuid.uuid4().hex,p["id"],"incubation",-15,"Выведение курицы: 12 яиц",now))
  c.execute("INSERT INTO incubation_jobs(id,player_id,started,hatch_at,mature_at) VALUES(%s,%s,%s,%s,%s)",(uuid.uuid4().hex,p["id"],now,now+egg_seconds,now+egg_seconds+grow_seconds))
 return {"ok":True}

@app.post("/api/tutorial")
def tutorial_action(q:Request,authorization:str=Header(default="")):
 if q.item not in ("coop","grain","eggs"):raise HTTPException(400,"Неверный шаг")
 steps=("coop","grain","eggs")
 with db() as c:
  p=advance(c,person(c,authorization,True))
  step=p["tutorial_step"]
  if step>=3:raise HTTPException(409,"Обучение уже завершено")
  if steps[step]!=q.item:raise HTTPException(409,"Сначала выполните текущий шаг")
  new_step=step+1
  reward=5 if new_step==3 and not p["tutorial_rewarded"] else 0
  c.execute("UPDATE players SET tutorial_step=%s,tutorial_rewarded=CASE WHEN %s>0 THEN true ELSE tutorial_rewarded END,coins=coins+%s WHERE id=%s",(new_step,reward,reward,p["id"]))
  if reward:
   c.execute("UPDATE reward_emission SET total_minted=total_minted+%s WHERE id=1",(reward,))
   c.execute("INSERT INTO money_log VALUES(%s,%s,%s,%s,%s,%s)",(uuid.uuid4().hex,p["id"],"tutorial",reward,"Обучение начинающего фермера",time.time()))
 return {"ok":True,"step":new_step,"awarded":reward}

@app.post("/api/recovery/create")
def create_recovery_code(authorization:str=Header(default="")):
 code=secrets.token_urlsafe(24)
 hashed=hashlib.sha256(code.encode()).hexdigest()
 with db() as c:
  p=person(c,authorization,True)
  c.execute("UPDATE players SET recovery_hash=%s WHERE id=%s",(hashed,p["id"]))
 return {"recovery_code":code}

@app.post("/api/recovery/login")
def recover_login(q:Request):
 name=q.name.strip()
 if len(q.code)<24 or len(q.code)>100:raise HTTPException(400,"Неверный код восстановления")
 hashed=hashlib.sha256(q.code.encode()).hexdigest()
 with db() as c:
  p=c.execute("SELECT id,recovery_hash FROM players WHERE name=%s FOR UPDATE",(name,)).fetchone()
  # A uniform rejection conceals whether this player account exists.
  actual=p["recovery_hash"] if p and p["recovery_hash"] else "0"*64
  if not hmac.compare_digest(actual,hashed):raise HTTPException(403,"Неверное имя или код восстановления")
  token=secrets.token_hex(24)
  c.execute("UPDATE players SET token=%s WHERE id=%s",(token,p["id"]))
 return {"token":token}
