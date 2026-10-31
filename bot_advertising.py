"""Immutable purchased execution count and advertiser-facing financial progress."""
from bot_copy import tr


def initialize(c):
    c.execute('CREATE TABLE IF NOT EXISTS bot_ad_orders(task text PRIMARY KEY,slots bigint NOT NULL CHECK(slots>0),budget bigint NOT NULL CHECK(budget>0),cost bigint NOT NULL CHECK(cost>0))')
    # Prior orders retain their original gross price and ledger-funded budget.
    c.execute("""INSERT INTO bot_ad_orders(task,slots,budget,cost)
      SELECT t.id,sum(-l.delta)/coalesce(q.cost,t.reward),sum(-l.delta),coalesce(q.cost,t.reward)
      FROM bot_tasks t LEFT JOIN bot_task_terms q ON q.task=t.id
      JOIN bot_ledger l ON l.uid=t.owner AND l.kind='task_budget' AND l.details='Бюджет задания ' || t.id
      WHERE l.delta<0 GROUP BY t.id,q.cost,t.reward
      HAVING sum(-l.delta)>=coalesce(q.cost,t.reward) ON CONFLICT DO NOTHING""")


def save(c,tid,data):
    cost=data.get('terms',{}).get('cost',data['reward'])
    c.execute('INSERT INTO bot_ad_orders VALUES(%s,%s,%s,%s)',(tid,data['budget']//cost,data['budget'],cost))


def order(c,t):
    row=c.execute('SELECT * FROM bot_ad_orders WHERE task=%s',(t['id'],)).fetchone()
    if row:return row
    # Cover an old-version order committed while a rolling deployment was starting.
    import task_bot as b
    cost=b.bot_economy.cost(c,t)
    funded=c.execute("SELECT coalesce(sum(-delta),0) AS n FROM bot_ledger WHERE uid=%s AND kind='task_budget' AND details=%s AND delta<0",(t['owner'],'Бюджет задания '+t['id'])).fetchone()['n']
    if funded>=cost:
        c.execute('INSERT INTO bot_ad_orders VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING',(t['id'],funded//cost,funded,cost))
        return c.execute('SELECT * FROM bot_ad_orders WHERE task=%s',(t['id'],)).fetchone()
    return None


def card(c,t):
    import task_bot as b
    purchased=order(c,t)
    stats={r['status']:r['n'] for r in c.execute('SELECT status,count(*) AS n FROM bot_claims WHERE task=%s GROUP BY status',(t['id'],)).fetchall()}
    cost=b.bot_economy.cost(c,t)
    status={'active':'🟢 Выполняется','pending':'⏳ На модерации','closed':'Закрыт','rejected':'❌ Отклонён'}[t['status']]
    if t['status']=='active' and t['remaining']<cost:status='✅ Все оплаченные места использованы'
    publication=c.execute('SELECT status,url FROM bot_post_publications WHERE task=%s',(t['id'],)).fetchone() if t['kind']=='post' else None
    publish_ready=t['kind']!='post' or bool(publication and publication['status']=='posted')
    if t['status']=='active' and not publish_ready:status='⏳ Проверяется публикация поста'
    slots=str(purchased['slots']) if purchased else 'не указан в старом заказе'
    text=tr('📣 <b>{v0}</b>\n\nСтатус: {v1}\nЗаказано выполнений: <b>{v2}</b>\n✅ Оплачено: {v3}\n⏳ На проверке: {v4}\nДоступно мест: {v5}\n\n<b>Финансы заказа</b>\nЦена выполнения: {v6}\nНаграда исполнителю: {v7}\nОстаток бюджета: <b>{v8}</b>',{'v0':b.bot_ui.esc(t['title']),'v1':status,'v2':slots,'v3':stats.get('paid',0),'v4':stats.get('review',0),'v5':max(0,t['remaining']//cost-stats.get('review',0)) if t['status']=='active' and publish_ready else 0,'v6':b.money(cost),'v7':b.money(t['reward']),'v8':b.money(t['remaining'])},html_mode=True,section='bot_advertising')
    rows=[]
    if stats.get('review',0):rows.append([b.button('📝 Проверить работы','reviews:0')])
    if t['status'] in ('pending','active'):rows.append([b.button('Закрыть и вернуть остаток','close:'+t['id'])])
    if t['kind']=='post':
        pub=c.execute("SELECT url FROM bot_post_publications WHERE task=%s AND status='posted'",(t['id'],)).fetchone()
        if pub:rows.append([{'text':'👁 Открыть пост','url':pub['url']}])
    rows.extend([[b.button('🔄 Обновить','own:'+t['id'])],[b.button('⬅️ Мои заказы','mine:0')]])
    return b.bot_ui.screen(t['owner'],text,rows)
