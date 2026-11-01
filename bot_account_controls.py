"""Owner-managed withdrawal holds and private review flags, with an audit trail."""
import time
import uuid


def initialize(c):
    c.execute('''CREATE TABLE IF NOT EXISTS bot_account_controls(
      uid bigint PRIMARY KEY,withdraw_blocked integer NOT NULL DEFAULT 0 CHECK(withdraw_blocked IN (0,1)),
      suspicious integer NOT NULL DEFAULT 0 CHECK(suspicious IN (0,1)),
      block_reason text NOT NULL DEFAULT '',flag_reason text NOT NULL DEFAULT '',
      actor bigint NOT NULL,updated double precision NOT NULL)''')
    c.execute('CREATE TABLE IF NOT EXISTS bot_account_control_audit(id text PRIMARY KEY,uid bigint NOT NULL,actor bigint NOT NULL,operation text NOT NULL,reason text NOT NULL,created double precision NOT NULL)')
    c.execute('CREATE INDEX IF NOT EXISTS bot_account_audit_user ON bot_account_control_audit(uid,created)')


def get(c,uid):
    return c.execute('SELECT * FROM bot_account_controls WHERE uid=%s',(uid,)).fetchone() or {
        'withdraw_blocked':0,'suspicious':0,'block_reason':'','flag_reason':''}


def withdrawal_error(c,uid):
    row=get(c,uid)
    return 'Вывод временно заблокирован администратором. Причина: '+row['block_reason'] if row['withdraw_blocked'] else None


def require_withdrawal(c,uid):
    error=withdrawal_error(c,uid)
    if error:
        import task_bot
        raise task_bot.UserError(error)


def set_control(c,uid,actor,op,reason):
    import task_bot as b
    if op not in ('block','unblock','flag','unflag'):raise b.UserError('Неизвестное действие.')
    if not 5<=len(reason.strip())<=300:raise b.UserError('Причина: от 5 до 300 символов.')
    if not c.execute('SELECT 1 FROM bot_accounts WHERE uid=%s',(uid,)).fetchone():raise b.UserError('Аккаунт не найден.')
    row=get(c,uid);field='withdraw_blocked' if op in ('block','unblock') else 'suspicious'
    value=int(op in ('block','flag'))
    if row[field]==value:raise b.UserError('Статус уже изменён. Обнови аккаунт.')
    row[field]=value
    row['block_reason' if field=='withdraw_blocked' else 'flag_reason']=reason.strip()
    c.execute('''INSERT INTO bot_account_controls VALUES(%s,%s,%s,%s,%s,%s,%s)
      ON CONFLICT(uid) DO UPDATE SET withdraw_blocked=EXCLUDED.withdraw_blocked,suspicious=EXCLUDED.suspicious,
      block_reason=EXCLUDED.block_reason,flag_reason=EXCLUDED.flag_reason,actor=EXCLUDED.actor,updated=EXCLUDED.updated''',
      (uid,row['withdraw_blocked'],row['suspicious'],row['block_reason'],row['flag_reason'],actor,time.time()))
    c.execute('INSERT INTO bot_account_control_audit VALUES(%s,%s,%s,%s,%s,%s)',
              (uuid.uuid4().hex,uid,actor,op,reason.strip(),time.time()))
