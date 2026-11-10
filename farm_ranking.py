"""Main farmer level leaderboard with optional public profile highlights.
Older small test databases only store name/level, so supplementary details
are optional; the ranking order and exact position remain unchanged.
"""
import sqlite3

def snapshot(c,pid):
    try:
        rows=c.execute('SELECT id,name,farmer_level,coins,chickens,geese,cows,sheep,avatar,avatar_photo,gender FROM players ORDER BY farmer_level DESC,name ASC,id ASC LIMIT 5').fetchall()
    except sqlite3.OperationalError as exc:
        if 'no such column' not in str(exc):
            raise
        rows=c.execute('SELECT id,name,farmer_level FROM players ORDER BY farmer_level DESC,name ASC,id ASC LIMIT 5').fetchall()
    p=c.execute('SELECT id,name,farmer_level FROM players WHERE id=%s',(pid,)).fetchone()
    ahead=c.execute('SELECT count(*) AS n FROM players WHERE farmer_level>%s OR (farmer_level=%s AND name<%s) OR (farmer_level=%s AND name=%s AND id<%s)',(p['farmer_level'],p['farmer_level'],p['name'],p['farmer_level'],p['name'],pid)).fetchone()['n']
    return [{
        'name':r['name'],'farmer_level':r['farmer_level'],
        'farm_score':r['farmer_level'],'place':i+1,'is_me':r['id']==pid,
        'coins':r.get('coins',0),
        'animals':sum(int(r.get(k) or 0) for k in ('chickens','geese','cows','sheep')),
        'avatar':r.get('avatar','default'),'avatar_photo':r.get('avatar_photo'),
        'gender':r.get('gender','unspecified')
    } for i,r in enumerate(rows)],ahead+1
