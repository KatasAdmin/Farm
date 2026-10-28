import os,time,uuid
import psycopg
from psycopg.rows import dict_row
from fastapi import FastAPI,HTTPException,Header
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from contextlib import asynccontextmanager
def db():return psycopg.connect(os.environ["DATABASE_URL"],row_factory=dict_row)
@asynccontextmanager
async def lifespan(app):
 with db() as c:
  c.execute("CREATE TABLE IF NOT EXISTS players(id text primary key,name text unique,token text unique,coins int default 100,grain int default 5,chickens int default 1,eggs int default 0,last_feed float default 0)")
  c.execute("CREATE TABLE IF NOT EXISTS market(id text primary key,seller text,item text,quantity int,price int)")
 yield
app=FastAPI(lifespan=lifespan)
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
  with db() as c:c.execute("INSERT INTO players(id,name,token) VALUES(%s,%s,%s)",(uuid.uuid4().hex,name,token))
 except psycopg.errors.UniqueViolation:raise HTTPException(409,"Имя уже занято")
 return {"token":token}
@app.get("/api/state")
def state(authorization:str=Header(default="")):
 with db() as c:
  p=person(c,authorization)
  listings=c.execute("SELECT m.item,m.price,m.quantity,p.name AS seller FROM market m JOIN players p ON p.id=m.seller WHERE m.quantity>0 ORDER BY m.price LIMIT 40").fetchall()
  top=c.execute("SELECT name,coins,chickens FROM players ORDER BY coins DESC LIMIT 8").fetchall()
  return {"me":p,"market":listings,"top":top,"now":time.time()}
@app.post("/api/shop")
def shop(q:Request,authorization:str=Header(default="")):
 check(q.amount)
 if q.item not in ("grain","chickens"):raise HTTPException(400,"Товар не найден")
 cost=q.amount*(2 if q.item=="grain" else 30)
 with db() as c:
  p=person(c,authorization,True)
  if p["coins"]<cost:raise HTTPException(400,"Недостаточно монет")
  c.execute("UPDATE players SET coins=coins-%s,"+q.item+"="+q.item+"+%s WHERE id=%s",(cost,q.amount,p["id"]))
 return {"ok":True}
@app.post("/api/feed")
def feed(q:Request,authorization:str=Header(default="")):
 check(q.amount)
 with db() as c:
  p=person(c,authorization,True)
  if time.time()-p["last_feed"]<60:raise HTTPException(429,"Курицам нужен отдых 60 секунд")
  n=min(q.amount,p["grain"],p["chickens"]*2)
  if n<1:raise HTTPException(400,"Нужно зерно и хотя бы одна курица")
  c.execute("UPDATE players SET grain=grain-%s,eggs=eggs+%s,last_feed=%s WHERE id=%s",(n,n,time.time(),p["id"]))
 return {"eggs":n}
@app.post("/api/sell")
def sell(q:Request,authorization:str=Header(default="")):
 check(q.amount);check(q.price)
 if q.item not in ("grain","eggs"):raise HTTPException(400,"Товар не найден")
 with db() as c:
  p=person(c,authorization,True)
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
  p=person(c,authorization,True)
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
 return {"ok":True,"spent":cost}
