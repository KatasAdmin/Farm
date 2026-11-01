"""Resource referral fields and progress from committed farm events only."""
REFERRAL_FIELDS={
 'eggs':('earned_units','claimed_eggs'),
 'grain':('earned_grain_units','claimed_grain'),
 'chickens':('earned_chickens_units','claimed_chickens'),
 **{item:('earned_'+item+'_units','claimed_'+item) for item in ('geese','cows','milk','feathers')}
}
EXTRA_MISSIONS={'milk':('milk_produced',1),'milk_listing':('milk_listed',1),'feather':('feathers_collected',1)}
def initialize(c):
 for item in ('geese','cows','milk','feathers'):
  for field in REFERRAL_FIELDS[item]:
   c.execute('ALTER TABLE referral_rewards ADD COLUMN IF NOT EXISTS '+field+' bigint NOT NULL DEFAULT 0')
 c.execute('CREATE INDEX IF NOT EXISTS farm_events_player_kind_created ON farm_events(player_id,kind,created)')

def resources(row):
 return {item:{'available':max(0,row.get(earned,0)//10000-row.get(claimed,0)),
               'fraction':row.get(earned,0)%10000,'total':row.get(earned,0)//10000}
         for item,(earned,claimed) in REFERRAL_FIELDS.items()}

def progress(c,pid,since=0,until=float('inf')):
 rows=c.execute("SELECT kind,COALESCE(SUM(amount),0) AS n FROM farm_events WHERE player_id=%s AND created>=%s AND created<%s AND kind IN ('milk_produced','feathers_collected','milk_listed') GROUP BY kind",(pid,since,until)).fetchall()
 return {r['kind']:r['n'] for r in rows}

def achievement_rows(p,counts):
 return [
  ('first_goose','goose-v2.png','Первый гусь',p.get('geese',0),1),
  ('first_cow','cow-v1.webp','Первая корова',p.get('cows',0),1),
  ('first_milk','milk-v1.webp','Первое молоко',counts.get('milk_produced',0),1),
  ('milk_hundred','milk-v1.webp','100 единиц молока',counts.get('milk_produced',0),100),
  ('first_feather','goose-v2.png','Первое перо',counts.get('feathers_collected',0),1),
  ('feather_five','goose-v2.png','Пять перьев',counts.get('feathers_collected',0),5),
  ('storage_five','redesign/storage','Склад пятого уровня',p.get('storage_level',1),5),
 ]
