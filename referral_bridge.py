"""Project existing referrals across verified Telegram identities, without rewards.
All callers hold the common referral transaction lock before locking identities.
Existing parents are immutable; conflicting legacy records are left untouched.
"""
import time


def initialize(c):
    c.execute('CREATE TABLE IF NOT EXISTS referrals(child_id text PRIMARY KEY,parent_id text NOT NULL,created double precision NOT NULL,qualified boolean NOT NULL DEFAULT false)')


def acyclic(c, child, parent):
    pending=[parent]; seen=set()
    while pending:
        node=pending.pop()
        if node==child:return False
        if node in seen:continue
        seen.add(node)
        if len(seen)>1000:return False
        row=c.execute('SELECT referrer FROM bot_accounts WHERE uid=%s',(node,)).fetchone()
        if row and row['referrer']:pending.append(row['referrer'])
        rows=c.execute('SELECT p.telegram_id FROM referrals r JOIN players ch ON ch.id=r.child_id JOIN players p ON p.id=r.parent_id WHERE ch.telegram_id=%s',(node,)).fetchall()
        pending.extend(r['telegram_id'] for r in rows if r['telegram_id'])
    return True


def sync(c, uid):
    # Include children when their inviter links/opens the other product later.
    pairs=c.execute('SELECT b.uid AS child,b.referrer AS parent FROM bot_accounts b WHERE b.referrer IS NOT NULL AND (b.uid=%s OR b.referrer=%s)',(uid,uid)).fetchall()
    pairs+=c.execute('SELECT ch.telegram_id AS child,p.telegram_id AS parent FROM referrals r JOIN players ch ON ch.id=r.child_id JOIN players p ON p.id=r.parent_id WHERE ch.telegram_id IS NOT NULL AND p.telegram_id IS NOT NULL AND (ch.telegram_id=%s OR p.telegram_id=%s)',(uid,uid)).fetchall()
    for pair in pairs:
        child,parent=pair['child'],pair['parent']
        if not acyclic(c,child,parent):continue
        cp=c.execute('SELECT id FROM players WHERE telegram_id=%s',(child,)).fetchone()
        pp=c.execute('SELECT id FROM players WHERE telegram_id=%s',(parent,)).fetchone()
        br=c.execute('SELECT referrer FROM bot_accounts WHERE uid=%s',(child,)).fetchone()
        gr=c.execute('SELECT parent_id FROM referrals WHERE child_id=%s',(cp['id'],)).fetchone() if cp else None
        if br and br['referrer'] and br['referrer']!=parent:continue
        if gr and (not pp or gr['parent_id']!=pp['id']):continue
        if cp and pp:
            c.execute('INSERT INTO referrals(child_id,parent_id,created) VALUES(%s,%s,%s) ON CONFLICT(child_id) DO NOTHING',(cp['id'],pp['id'],time.time()))
        # Parent account may not exist yet: its verified game identity is enough.
        if cp and pp and br:
            c.execute('INSERT INTO bot_accounts(uid,name,created) VALUES(%s,%s,%s) ON CONFLICT(uid) DO NOTHING',(parent,'Игрок',time.time()))
            c.execute('UPDATE bot_accounts SET referrer=%s WHERE uid=%s AND referrer IS NULL',(parent,child))
