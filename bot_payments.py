"""Unified owner payment journal. Farm Stars remain separate from wallet UAH."""
import datetime as dt
from zoneinfo import ZoneInfo
from bot_copy import tr


def screen(c,uid,kind='all',page=0):
    import task_bot as b
    if kind not in ('all','card','stars','farm','bank') or not 0<=page<=100000:
        raise b.UserError('Неизвестная страница истории.')
    union="""SELECT id,uid,amount,0 AS stars,status,created,'card' AS kind FROM bot_card_topups
      UNION ALL SELECT id,uid,amount,stars,status,created,'stars' AS kind FROM bot_wallet_stars
      UNION ALL SELECT id,telegram_id AS uid,coins AS amount,stars,status,created,'farm' AS kind FROM star_orders
      UNION ALL SELECT reference AS id,uid,amount,0 AS stars,'credited' AS status,created,'bank' AS kind FROM bot_deposits d
        WHERE NOT EXISTS(SELECT 1 FROM bot_card_topups t WHERE t.status='approved' AND t.reference=d.reference)"""
    rows=c.execute('SELECT * FROM ('+union+') journal WHERE (%s=%s OR kind=%s) ORDER BY created DESC,kind,id LIMIT 9 OFFSET %s',(kind,'all',kind,page*8)).fetchall()
    labels={'pending':'⏳ Квитанция на проверке','approved':'✅ Зачислено','rejected':'❌ Отклонено','created':'🧾 Счёт создан, не оплачен','checkout':'⏳ Ожидаем оплату Telegram','paid':'✅ Оплачено','refunded':'↩️ Возвращено','credited':'✅ Учтено вручную'}
    titles={'all':'Все способы','card':'Квитанции','stars':'Stars · баланс бота','farm':'Stars · ферма','bank':'Ручной учёт'}
    lines=[tr('🧾 <b>История оплат</b>\n{v0}\n\n<i>Созданный счёт и квитанция ещё не означают зачисление.</i>',{'v0':titles[kind]},html_mode=True,section='bot_payments')]
    buttons=[]
    for r in rows[:8]:
        date=dt.datetime.fromtimestamp(r['created'],ZoneInfo('Europe/Kyiv')).strftime('%d.%m %H:%M')
        amount=(str(r['amount'])+' монет · '+str(r['stars'])+' ⭐') if r['kind']=='farm' else b.money(r['amount'])+(' · '+str(r['stars'])+' ⭐' if r['kind']=='stars' else '')
        lines.append('<b>'+b.bot_ui.esc(amount)+'</b> · '+titles[r['kind']]+'\n'+labels.get(r['status'],'Статус: '+b.bot_ui.esc(r['status']))+'\nID '+str(r['uid'])+' · '+date+' · <code>'+b.bot_ui.esc(r['id'][:12])+'</code>')
        if r['kind']=='card':
            buttons.append([b.button('💳 Заявка '+r['id'][:8],'admin:cardview:'+r['id'])])
        elif r['kind']=='farm' and r['status']=='paid':
            buttons.append([{'text':'↩️ Возврат Stars · '+r['id'][:8],'callback_data':'adm:refund:'+r['id']}])
    if not rows:lines.append('Пока нет операций по этому способу.')
    nav=[]
    if page:nav.append(b.button('⬅️ Назад','admin:payments:'+kind+':'+str(page-1)))
    if len(rows)>8:nav.append(b.button('Далее ➡️','admin:payments:'+kind+':'+str(page+1)))
    if nav:buttons.append(nav)
    buttons.extend([[b.button('Все','admin:payments:all:0'),b.button('💳 Карта','admin:payments:card:0')],
        [b.button('⭐ Бот','admin:payments:stars:0'),b.button('🐔 Ферма','admin:payments:farm:0')],
        [b.button('🔄 Обновить','admin:payments:'+kind+':'+str(page))],[b.button('⬅️ Финансы','admin:section:finance')]])
    return b.bot_ui.screen(uid,'\n\n'.join(lines),buttons)
