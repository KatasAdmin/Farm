"""Leaderboard uses the same persisted main farmer level as the profile.
farm_score is a compatibility alias of that SAME level for already-open clients.
Equal levels are ordered by nickname, then immutable id; exact ordinal places.
"""
def snapshot(c,pid):
 rows=c.execute('SELECT id,name,farmer_level,coins,chickens,geese,cows,sheep,avatar,avatar_photo,gender FROM players ORDER BY farmer_level DESC,name ASC,id ASC LIMIT 5').fetchall()
 p=c.execute('SELECT id,name,farmer_level FROM players WHERE id=%s',(pid,)).fetchone()
 ahead=c.execute('SELECT count(*) AS n FROM players WHERE farmer_level>%s OR (farmer_level=%s AND name<%s) OR (farmer_level=%s AND name=%s AND id<%s)',(p['farmer_level'],p['farmer_level'],p['name'],p['farmer_level'],p['name'],pid)).fetchone()['n']
 return [{'name':r['name'],'farmer_level':r['farmer_level'],'farm_score':r['farmer_level'],'place':i+1,'is_me':r['id']==pid,'coins':r['coins'],'animals':sum(int(r.get(k) or 0) for k in ('chickens','geese','cows','sheep')),'avatar':r['avatar'],'avatar_photo':r['avatar_photo'],'gender':r['gender']} for i,r in enumerate(rows)],ahead+1
