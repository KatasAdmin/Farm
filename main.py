import os,time,uuid
import psycopg
from psycopg.rows import dict_row
from fastapi import FastAPI,HTTPException,Header
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from contextlib import asynccontextmanager
def db():return psycopg.connect(os.environ["DATABASE_URL"],row_factory=dict_row)
@asynccontextmanager
async def lifespan(app):
 with db() as c:
  c.execute("CREATE TABLE IF NOT EXISTS players(id text primary key,name text unique,token text unique,coins int default 100,grain int default 5,chickens int default 1,eggs int default 0,last_feed float default 0)")
  c.execute("CREATE TABLE IF NOT EXISTS market(id text primary key,seller text,item text,quantity int,price int)")
  c.execute("CREATE TABLE IF NOT EXISTS economy(id int primary key,treasury int not null check(treasury>=0))")
  c.execute("INSERT INTO economy(id,treasury) SELECT 1,GREATEST(0,10000-(SELECT COALESCE(SUM(coins),0)::int FROM players)) WHERE NOT EXISTS(SELECT 1 FROM economy)")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS satiety integer NOT NULL DEFAULT 100")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS last_tick double precision")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS critical_cycles integer NOT NULL DEFAULT 0")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS autobuy_enabled boolean NOT NULL DEFAULT false")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS autobuy_min integer NOT NULL DEFAULT 5")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS autobuy_amount integer NOT NULL DEFAULT 20")
  c.execute("CREATE TABLE IF NOT EXISTS money_log(id text primary key,player_id text,kind text,delta int,details text,created double precision)")
  c.execute("UPDATE players SET last_tick=%s WHERE last_tick IS NULL",(time.time(),))
  c.execute("UPDATE market SET price=5 WHERE item='eggs' AND price<>5")
 yield
app=FastAPI(lifespan=lifespan)
app.mount("/assets", StaticFiles(directory="assets"), name="assets")
class Request(BaseModel):
 name:str=""
 item:str=""
 amount:int=1
 price:int=1
def person(c,h,lock=False):
 p=c.execute("SELECT * FROM players WHERE token=%s"+(" FOR UPDATE" if lock else ""),(h.replace("Bearer ",""),)).fetchone()
 if not p:raise HTTPException(401,"Войдите в игру")
 return p
def check(n):
 if n<1 or n>10000:raise HTTPException(400,"Некорректное количество")
CYCLE=86400  # 1 real day, calibrated 10-day payback at full sales
def advance(c,p,now=None):
 """Simulate only completed feeding cycles; persist atomically with the locked player."""
 now=time.time() if now is None else now
 start=p["last_tick"] if p["last_tick"] is not None else now
 due=max(0,int((now-start)//CYCLE))
 if due<=0:return p
 grain,eggs,hens=p["grain"],p["eggs"],p["chickens"]
 satiety,critical=p["satiety"],p["critical_cycles"]
 # At most a century of steps, and stop after all birds have died.
 for _ in range(min(due,438000)):
  if hens<=0:break
  if p["autobuy_enabled"] and grain<hens and p["coins"]>=2*max(1,p["autobuy_amount"]):
   refill=p["autobuy_amount"]
   p["coins"]-=2*refill
   grain+=refill
   c.execute("UPDATE players SET coins=coins-%s WHERE id=%s",(2*refill,p["id"]))
   c.execute("UPDATE economy SET treasury=treasury+%s WHERE id=1",(2*refill,))
   c.execute("INSERT INTO money_log VALUES(%s,%s,%s,%s,%s,%s)",(uuid.uuid4().hex,p["id"],"auto_grain",-2*refill,"Зерно: "+str(refill),now))
  fed=min(grain,hens)
  grain-=fed
  eggs+=fed
  if fed==hens:
   satiety=min(100,satiety+10)
   critical=0
  else:
   missing=hens-fed
   satiety=max(0,satiety-max(1,(10*missing+hens-1)//hens))
   if satiety==0:critical+=1
   else:critical=0
   if critical>=12:
    hens-=1
    critical=0
    satiety=20 if hens else 0
 c.execute("UPDATE players SET grain=%s,eggs=%s,chickens=%s,satiety=%s,critical_cycles=%s,last_tick=%s WHERE id=%s",(grain,eggs,hens,satiety,critical,start+due*CYCLE,p["id"]))
 return {**p,"grain":grain,"eggs":eggs,"chickens":hens,"satiety":satiety,"critical_cycles":critical,"last_tick":start+due*CYCLE}
@app.get("/",response_class=HTMLResponse)
def index():return open("index.html",encoding="utf8").read()
@app.get("/health")
def health():return {"ok":True}
@app.post("/api/join")
def join(q:Request):
 name=q.name.strip()[:22]
 if len(name)<2:raise HTTPException(400,"Имя слишком короткое")
 token=uuid.uuid4().hex
 try:
  with db() as c:
   treasury=c.execute("SELECT treasury FROM economy WHERE id=1 FOR UPDATE").fetchone()["treasury"]
   if treasury<100:raise HTTPException(409,"Стартовый фонд исчерпан: новые регистрации временно закрыты")
   c.execute("INSERT INTO players(id,name,token,last_tick) VALUES(%s,%s,%s,%s)",(uuid.uuid4().hex,name,token,time.time()))
   c.execute("UPDATE economy SET treasury=treasury-100 WHERE id=1")
   c.execute("INSERT INTO money_log VALUES(%s,%s,%s,%s,%s,%s)",(uuid.uuid4().hex,None,"new_player",-100,"Начальный баланс: "+name,time.time()))
 except psycopg.errors.UniqueViolation:raise HTTPException(409,"Имя уже занято")
 return {"token":token}
@app.get("/api/state")
def state(authorization:str=Header(default="")):
 with db() as c:
  p=advance(c,person(c,authorization,True))
  listings=c.execute("SELECT m.item,m.price,m.quantity,p.name AS seller FROM market m JOIN players p ON p.id=m.seller WHERE m.quantity>0 ORDER BY m.price LIMIT 40").fetchall()
  mine=c.execute("SELECT id,item,quantity,price FROM market WHERE seller=%s AND quantity>0 ORDER BY item,price,id",(p["id"],)).fetchall()
  top=c.execute("SELECT name,coins,chickens FROM players ORDER BY coins DESC LIMIT 8").fetchall()
  return {"shop":{"grain":2,"chickens":30},"economy":{"treasury":c.execute("SELECT treasury FROM economy WHERE id=1").fetchone()["treasury"]},"farm":{"cycle_seconds":CYCLE,"seconds_to_next":max(0,int(CYCLE-(time.time()-p["last_tick"]))),"feeding_per_cycle":p["chickens"],"feed_cycles_available":p["grain"]//max(1,p["chickens"])},"me":p,"market":listings,"my_listings":mine,"top":top,"now":time.time()}
@app.post("/api/shop")
def shop(q:Request,authorization:str=Header(default="")):
 check(q.amount)
 if q.item not in ("grain","chickens"):raise HTTPException(400,"Товар не найден")
 cost=q.amount*(2 if q.item=="grain" else 30)
 with db() as c:
  p=advance(c,person(c,authorization,True))
  if p["coins"]<cost:raise HTTPException(400,"Недостаточно монет")
  c.execute("UPDATE players SET coins=coins-%s,"+q.item+"="+q.item+"+%s WHERE id=%s",(cost,q.amount,p["id"]))
  c.execute("UPDATE economy SET treasury=treasury+%s WHERE id=1",(cost,))
  c.execute("INSERT INTO money_log VALUES(%s,%s,%s,%s,%s,%s)",(uuid.uuid4().hex,p["id"],"shop",-cost,q.item+" x"+str(q.amount),time.time()))
 return {"ok":True}
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
  price=5 if q.item=="eggs" else q.price
  c.execute("INSERT INTO market VALUES(%s,%s,%s,%s,%s)",(uuid.uuid4().hex,p["id"],q.item,q.amount,price))
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
  c.execute("UPDATE players SET "+entry["item"]+"="+entry["item"]+"+%s WHERE id=%s",(entry["quantity"],p["id"]))
  c.execute("UPDATE market SET quantity=0 WHERE id=%s",(listing_id,))
 return {"ok":True,"returned":entry["quantity"]}

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
