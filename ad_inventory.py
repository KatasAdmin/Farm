"""Advertising provenance, independent of ordinary quantities/prices.
Counters tag a subset of inventory. Restricted units are spent first and the tag
survives trades, feeding, incubation and purchases funded by restricted receipts.
"""
ITEMS=('grain','eggs','milk','feathers','chickens','geese','cows')
INTS=tuple('ad_'+k for k in ITEMS)+('ad_fed_hens','ad_fed_geese','ad_fed_cows','ad_stock_version')
FLOATS=('ad_egg_progress','ad_milk_progress','ad_feather_progress')
FIELDS=INTS+FLOATS

def initialize(c):
 for key in INTS:c.execute('ALTER TABLE players ADD COLUMN IF NOT EXISTS '+key+' integer NOT NULL DEFAULT '+('1' if key=='ad_stock_version' else '0'))
 for key in FLOATS:c.execute('ALTER TABLE players ADD COLUMN IF NOT EXISTS '+key+' double precision NOT NULL DEFAULT 0')
 c.execute('CREATE TABLE IF NOT EXISTS farm_ad_money(log_id text PRIMARY KEY,amount integer NOT NULL CHECK(amount>0))')
 c.execute('CREATE TABLE IF NOT EXISTS farm_ad_listings(id text PRIMARY KEY,quantity integer NOT NULL CHECK(quantity>=0))')
 c.execute('CREATE TABLE IF NOT EXISTS farm_ad_incubations(id text PRIMARY KEY)')

def active(p):return p.get('ad_stock_version')==1

def save(c,p):
 if active(p):c.execute('UPDATE players SET '+','.join(k+'=%s' for k in FIELDS)+' WHERE id=%s',tuple(p.get(k,0) for k in FIELDS)+(p['id'],))

def add(c,p,item,n):
 if n<=0 or not active(p):return
 p['ad_'+item]=p.get('ad_'+item,0)+n
 if item in ('chickens','geese','cows'):
  field={'chickens':'ad_fed_hens','geese':'ad_fed_geese','cows':'ad_fed_cows'}[item]
  p[field]=p.get(field,0)+n
 save(c,p)

def take(c,p,item,n):
 if not active(p):return 0
 tagged=min(n,p.get('ad_'+item,0));p['ad_'+item]=p.get('ad_'+item,0)-tagged
 if item in ('chickens','geese','cows'):
  field={'chickens':'ad_fed_hens','geese':'ad_fed_geese','cows':'ad_fed_cows'}[item]
  # Normal animals fed with ad grain stay tagged for the current ration.
  p[field]=max(0,p.get(field,0)-min(n,p.get(field,0)))
 save(c,p);return tagged

def credit(c,log_id,amount):
 if amount:c.execute('INSERT INTO farm_ad_money VALUES(%s,%s)',(log_id,amount))

def balance(c,p):
 """Subset of bonus balance from advertising; ordinary bonus remains unchanged.
 Spending order is restricted bonus, ordinary bonus, deposits, earnings.
 """
 if not active(p):return 0
 rows=c.execute('SELECT m.kind,m.delta,s.bonus,s.purchased,s.earned,a.amount AS ad FROM money_log m LEFT JOIN farm_money_sources s ON s.log_id=m.id LEFT JOIN farm_ad_money a ON a.log_id=m.id WHERE m.player_id=%s ORDER BY m.created,m.id',(p['id'],)).fetchall()
 buckets={'ad':0,'bonus':max(0,p['coins']-sum(r['delta'] for r in rows)),'purchased':0,'earned':0}
 for r in rows:
  d=r['delta'];kind=r['kind']
  if d>0:
   tagged=r['ad'] or 0
   if r['bonus'] is not None:
    if tagged>r['bonus']:raise RuntimeError('Invalid ad money provenance')
    parts={'ad':tagged,'bonus':r['bonus']-tagged,'purchased':r['purchased'],'earned':r['earned']}
   else:parts={'ad':0,'bonus':0,'purchased':0,'earned':0};parts['earned' if kind in ('market_sale','system_sale','withdraw_release') else 'purchased' if kind=='stars_purchase' else 'bonus']=d
   for k,v in parts.items():buckets[k]+=v
  elif d<0:
   order=('earned','ad','bonus','purchased') if kind in ('farm_to_bot','withdraw_reserve') else ('purchased','ad','bonus','earned') if kind=='stars_refund' else ('ad','bonus','purchased','earned')
   remaining=-d
   for k in order:used=min(remaining,buckets[k]);buckets[k]-=used;remaining-=used
 excess=max(0,sum(buckets.values())-p['coins'])
 return max(0,buckets['ad']-excess)

def funded_units(credit,cost,quantity):
 return min(quantity,(min(credit,cost)*quantity+cost-1)//cost) if cost and credit else 0

def restricted_receipt(parts,amount):
 """Retain total receipt, make ad-funded goods purchasing credit only."""
 result=dict(parts);remaining=amount
 for key in ('earned','purchased','bonus'):
  used=min(remaining,result[key]);result[key]-=used;remaining-=used
 if remaining:raise RuntimeError('Ad receipt exceeds payment')
 result['bonus']+=amount;return result
