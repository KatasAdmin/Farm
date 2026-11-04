"""Leaderboard uses the same persisted main farmer level as the profile.
Equal levels are ordered by nickname, then immutable id; exact ordinal places.
"""
def snapshot(c,pid):
 rows=c.execute('SELECT id,name,farmer_level FROM players ORDER BY farmer_level DESC,name ASC,id ASC LIMIT 5').fetchall()
 p=c.execute('SELECT id,name,farmer_level FROM players WHERE id=%s',(pid,)).fetchone()
 ahead=c.execute('SELECT count(*) AS n FROM players WHERE farmer_level>%s OR (farmer_level=%s AND name<%s) OR (farmer_level=%s AND name=%s AND id<%s)',(p['farmer_level'],p['farmer_level'],p['name'],p['farmer_level'],p['name'],pid)).fetchone()['n']
 return [{'name':r['name'],'farmer_level':r['farmer_level'],'place':i+1,'is_me':r['id']==pid} for i,r in enumerate(rows)],ahead+1
