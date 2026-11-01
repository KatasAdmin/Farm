"""Owner-only, paged account dossier. Farm forecasts are pure read-only previews."""
import math
import time
from production_v4 import simulate,forecast

TITLES={'farm':'🐔 Ферма и производство','finance':'💰 Сводка денег','payments':'💳 Пополнения','payouts':'💸 Все выплаты','referrals':'👥 Рефералы','tasks':'📝 Задания и подписки','farmledger':'🪙 Операции фермы','activity':'📊 События фермы','market':'🛒 Рынок и сделки','incubator':'🥚 Инкубатор','support':'🆘 Обращения'}


def core():
    import task_bot
    return task_bot


def duration(seconds):
    if seconds is None:return 'не запланировано'
    seconds=max(0,math.ceil(seconds));days,rest=divmod(seconds,86400)
    return (str(days)+' д ' if days else '')+f'{rest//3600:02d}:{rest//60%60:02d}:{rest%60:02d}'


def farm_preview(p,now):
    # Do not call main.advance: inspecting another player must never change money,
    # grant eggs, pay referrals or mature birds in the real database.
    if p.get('production_model',0)>=4:
        q=simulate(p,now)[0];f=forecast(q,now)
        return q,f
    return dict(p),None


def screen(c,uid,target,section,page=0):
    import bot_accounts_admin as accounts
    import farm_wallet
    b=core();a=accounts.get(c,target);b.state(c,uid,'clear')
    if section not in TITLES or not 0<=page<=100000:raise b.UserError('Неизвестная страница.')
    esc=b.bot_ui.esc;stamp=accounts.date;now=time.time();farm=c.execute('SELECT * FROM players WHERE telegram_id=%s',(target,)).fetchone()
    title=TITLES[section];lines=['<b>'+title+'</b>\n'+esc(a['name'])+' · <code>'+str(target)+'</code>'];buttons=[];rows=[];more=False
    pid=farm['id'] if farm else ''
    if section=='farm':
        if not farm:lines.append('Привязанной фермы нет.')
        else:
            q,f=farm_preview(farm,now);hens=q.get('chickens',0);geese=q.get('geese',0)
            fed=q.get('fed_hens',0);fed_geese=q.get('fed_geese',0);rate=fed/6+fed_geese/2;ideal=hens/6+geese/2
            used=q.get('grain',0)+q.get('eggs',0)+q.get('feathers',0)+q.get('milk',0);cap=100*q.get('storage_level',1)
            lines.extend(['Ник: <b>'+esc(q.get('name','—'))+'</b>\nID фермы: <code>'+esc(pid)+'</code>\nСоздана: '+(stamp(q['created_at']) if q.get('created_at') else '—'),
              'Уровень: '+str(q.get('farmer_level',1))+'\nСтатус: '+esc({'farmer':'Фермер','president':'Президент'}.get(q.get('game_status'),q.get('game_status','Фермер')))+'\nПол: '+esc({'male':'Мужской','female':'Женский','unspecified':'Не указан'}.get(q.get('gender'),'Не указан'))+' · Возраст: '+str(q.get('age') or '—')+'\nПароль: '+('задан' if q.get('password_hash') else 'не задан'),
              f'🐔 Куры: <b>{hens}</b> · 🪿 Гуси: <b>{geese}</b>\nСытых: {fed} кур и {fed_geese} гусей\nСытость: {q.get("satiety",0)}%\nПтичник: {hens+geese} / {10*q.get("coop_level",1)}',
              f'🥚 Яйца: <b>{q.get("eggs",0)}</b> · 🪶 Перья: <b>{q.get("feathers",0)}</b>\n🌾 Зерно: {q.get("grain",0)}\nСклад: {used} / {cap}\nСвободно: {max(0,cap-used)}',
              f'📈 Скорость сытых птиц: <b>{rate:g} яиц/ч</b>\nПри сытом стаде: {ideal:g}/ч · {ideal*6:g} за 6 ч · {ideal*24:g} за сутки\nОдно яйцо: примерно каждые {duration(3600/rate) if rate else "—"}\nЭто скорость производства; корм и заполненный склад ограничивают сбор.'])
            if q.get('cows',0):
                lines.append('🐄 Коровы: '+str(q['cows'])+' · Сытых: '+str(q.get('fed_cows',0))+'\nКоровник: '+str(q['cows'])+' / '+str(2*q.get('cowshed_level',1))+'\n🥛 Молоко: '+str(q.get('milk',0))+'\nСкорость при кормлении: '+str(3*q['cows'])+' ед./сутки · цена 11 монет\nКорм: '+str(3*q['cows'])+' зерна раз в 18 часов')
                if f:lines.append('Следующее молоко: '+duration(f['seconds_to_next_milk'] if f.get('next_milk_scheduled') else None)+'\nМолоко за 12 ч: '+str(f.get('milk_next_12h',0)))
            if f:
                lines.append('Прогноз: <b>'+str(f['eggs_next_6h'])+' яиц за 6 ч</b> · '+str(f['eggs_next_12h'])+' за 12 ч\nСледующее яйцо: '+duration(f['seconds_to_next_egg'] if f['next_egg_scheduled'] else None)+'\nКормление через '+duration(f['seconds_to_next_feed'])+'\nНа кормление нужно: '+str(f['grain_required_next_feed'])+' зерна\nНе хватает на следующее кормление: '+str(f['effective_grain_shortage']))
                if geese:lines.append('🪶 Следующее перо при постоянном корме: '+(duration(f['seconds_to_next_feather']) if fed_geese else 'нужен корм'))
            lines.append('Автозакупка: '+('включена' if q.get('autobuy_enabled') else 'выключена')+'\nОбъём закупки: '+str(q.get('autobuy_amount',0))+' зерна\nПрогноз на '+stamp(now)+'. Новые ресурсы в БД не начислялись.')
            buttons.extend([[b.button(TITLES[k],'admin:accountdetail:'+k+':'+str(target)+':0') for k in ('market','incubator')]])
    elif section=='finance':
        debt=c.execute('SELECT amount FROM bot_debts WHERE uid=%s',(target,)).fetchone()
        lines.append('Баланс бота: <b>'+b.money(a['available'])+'</b>\nДолг: '+b.money(debt['amount'] if debt else 0))
        for r in c.execute('SELECT status,count(*) AS n,sum(amount) AS total FROM bot_payouts WHERE uid=%s GROUP BY status',(target,)).fetchall():
            lines.append('Выплаты · '+esc(r['status'])+': '+str(r['n'])+' шт. / '+b.money(r['total'])+' с баланса')
        if farm:
            sources=farm_wallet.balances(c,farm)
            lines.append('Монеты фермы: <b>'+str(farm['coins'])+'</b>\nБонусные: '+str(sources['bonus'])+'\nПополненные: '+str(sources['purchased'])+'\nВыручка к переводу: '+str(sources['earned'])+' монет')
            groups=c.execute('SELECT kind,count(*) AS n,sum(delta) AS total FROM money_log WHERE player_id=%s GROUP BY kind ORDER BY kind',(pid,)).fetchall()
            lines.append('Категории операций фермы:\n'+('\n'.join(esc(r['kind'])+': '+str(r['total'])+' монет · '+str(r['n'])+' оп.' for r in groups[:16]) or 'Нет операций.'))
        buttons.append([b.button('🧾 Баланс бота','admin:accountledger:'+str(target)+':0'),b.button(TITLES['farmledger'],'admin:accountdetail:farmledger:'+str(target)+':0')])
    elif section=='payments':
        sql="""SELECT id,uid,amount,0 AS stars,status,created,'card' AS kind FROM bot_card_topups WHERE uid=%s
        UNION ALL SELECT id,uid,amount,stars,status,created,'stars' AS kind FROM bot_wallet_stars WHERE uid=%s
        UNION ALL SELECT id,telegram_id,coins,stars,status,created,'farm' AS kind FROM star_orders WHERE telegram_id=%s
        UNION ALL SELECT reference,uid,amount,0,'recorded',created,'manual' FROM bot_deposits d WHERE uid=%s
          AND NOT EXISTS(SELECT 1 FROM bot_card_topups t WHERE t.status='approved' AND t.reference=d.reference)"""
        rows=c.execute('SELECT * FROM ('+sql+') x ORDER BY created DESC,id LIMIT 4 OFFSET %s',(target,target,target,target,page*3)).fetchall()
        labels={'card':'Карта','stars':'Stars → бот','farm':'Stars → ферма','manual':'Ручная запись / начисление'}
        for r in rows[:3]:
            value=(str(r['amount'])+' монет' if r['kind']=='farm' else b.money(r['amount']))+(' · '+str(r['stars'])+' ⭐' if r['stars'] else '')
            lines.append(stamp(r['created'])+' · '+labels[r['kind']]+'\n<b>'+value+'</b> · '+esc(r['status'])+'\nID: <code>'+esc(r['id'])+'</code>')
        lines.append('Созданный счёт и отправленная квитанция ещё не означают оплату.')
    elif section=='payouts':
        rows=c.execute('SELECT * FROM bot_payouts WHERE uid=%s ORDER BY created DESC,id LIMIT 4 OFFSET %s',(target,page*3)).fetchall()
        for r in rows[:3]:
            lines.append(stamp(r['created'])+' · <b>'+b.money(r['amount'])+'</b>\n'+esc(r['status'])+' · К переводу: '+b.money(b.bot_admin.net(c,r))+'\nРеквизиты: '+esc(r['destination'][:100])+'\nБанковская операция: '+esc((r['reference'] or '—')[:80]))
            buttons.append([b.button('💸 '+r['id'],'admin:payview:'+r['id'])])
    elif section=='referrals':
        if a['referrer']:buttons.append([b.button('👤 Кто пригласил · '+str(a['referrer']),'admin:account:'+str(a['referrer']))])
        total=c.execute('SELECT count(*) AS n FROM bot_accounts WHERE referrer=%s',(target,)).fetchone()['n']
        lines.append('Прямых рефералов в боте: <b>'+str(total)+'</b>')
        rows=c.execute('SELECT uid,name,created FROM bot_accounts WHERE referrer=%s ORDER BY created DESC,uid LIMIT 4 OFFSET %s',(target,page*3)).fetchall()
        for r in rows[:3]:buttons.append([b.button(r['name'][:28]+' · '+str(r['uid']),'admin:account:'+str(r['uid']))])
        if farm:
            total_game=c.execute('SELECT count(*) AS n FROM referrals WHERE parent_id=%s',(pid,)).fetchone()['n']
            lines.append('Прямых рефералов в игре: '+str(total_game))
            parent=c.execute('SELECT p.id,p.name,p.telegram_id FROM referrals r JOIN players p ON p.id=r.parent_id WHERE r.child_id=%s',(pid,)).fetchone()
            if parent:lines.append('Пригласил в игру: '+esc(parent['name'])+' · ID '+esc(parent['id']))
    elif section=='tasks':
        sql="""SELECT t.id,t.title,t.status,t.created,'order' AS kind FROM bot_tasks t WHERE t.owner=%s
          UNION ALL SELECT t.id,t.title,x.status,x.created,'work' AS kind FROM bot_claims x JOIN bot_tasks t ON t.id=x.task WHERE x.uid=%s"""
        rows=c.execute('SELECT * FROM ('+sql+') x ORDER BY created DESC,id LIMIT 4 OFFSET %s',(target,target,page*3)).fetchall()
        for r in rows[:3]:
            lines.append(stamp(r['created'])+' · '+('Заказ' if r['kind']=='order' else 'Выполнение')+'\n'+esc(r['title'])+' · '+esc(r['status']))
            buttons.append([b.button('📝 '+r['title'][:36],'admin:task:'+r['id'])])
        watch=c.execute('SELECT state,count(*) AS n FROM bot_retention WHERE uid=%s GROUP BY state',(target,)).fetchall()
        lines.append('Контроль подписок:\n'+('\n'.join(esc(r['state'])+': '+str(r['n']) for r in watch) or 'Нет записей.'))
    elif section in ('farmledger','activity'):
        if farm:
            table='money_log' if section=='farmledger' else 'farm_events'
            if section=='farmledger':
                rows=c.execute('SELECT m.*,s.bonus AS source_bonus,s.earned AS source_earned FROM money_log m LEFT JOIN farm_money_sources s ON s.log_id=m.id WHERE m.player_id=%s ORDER BY m.created DESC,m.id DESC LIMIT 4 OFFSET %s',(pid,page*3)).fetchall()
            else:rows=c.execute('SELECT * FROM '+table+' WHERE player_id=%s ORDER BY created DESC,id LIMIT 4 OFFSET %s',(pid,page*3)).fetchall()
            for r in rows[:3]:
                value=r['delta'] if section=='farmledger' else r['amount']
                lines.append(stamp(r['created'])+' · <b>'+('+' if value>0 else '')+str(value)+'</b>\n'+esc(r['kind'])+('\n'+esc(r['details'][:180]) if section=='farmledger' else '')+('\nБонусные: '+str(r['source_bonus'])+' · Выручка: '+str(r['source_earned']) if r.get('source_bonus') is not None else ''))
        else:lines.append('Привязанной фермы нет.')
    elif section=='market':
        if farm:
            listed=c.execute('SELECT item,sum(quantity) AS n FROM market WHERE seller=%s GROUP BY item',(pid,)).fetchall()
            lines.append('Выставлено на рынок:\n'+('\n'.join(esc(r['item'])+': '+str(r['n']) for r in listed) or 'Нет предложений.'))
            rows=c.execute('SELECT * FROM market_trade_audit WHERE buyer_id=%s OR seller_id=%s ORDER BY created DESC,id LIMIT 4 OFFSET %s',(pid,pid,page*3)).fetchall()
            for r in rows[:3]:lines.append(stamp(r['created'])+' · '+('Купил у '+esc(r['seller_id']) if r['buyer_id']==pid else 'Продал '+esc(r['buyer_id']))+'\n'+esc(r['item'])+' × '+str(r['quantity'])+' · '+str(r['coins'])+' монет')
        else:lines.append('Привязанной фермы нет.')
    elif section=='incubator':
        if farm:
            lines.append('Куплен: '+('да' if farm.get('incubator_owned') else 'нет')+'\nУровень / вместимость: '+str(farm.get('incubator_level',1)))
            rows=c.execute('SELECT * FROM incubation_jobs WHERE player_id=%s ORDER BY mature_at,id LIMIT 4 OFFSET %s',(pid,page*3)).fetchall()
            for r in rows[:3]:lines.append('ID: <code>'+esc(r['id'])+'</code>\nЗаложено: '+stamp(r['started'])+'\nВылупление: '+stamp(r['hatch_at'])+'\nВзросление: '+stamp(r['mature_at'])+'\n'+('Готов к зачислению при обновлении фермы' if r['mature_at']<=now else 'Осталось: '+duration(r['mature_at']-now)))
        else:lines.append('Привязанной фермы нет.')
    elif section=='support':
        rows=c.execute('SELECT * FROM support_tickets WHERE telegram_id=%s ORDER BY created DESC,id LIMIT 4 OFFSET %s',(target,page*3)).fetchall()
        for r in rows[:3]:
            lines.append(stamp(r['created'])+' · '+esc(r.get('status','open'))+'\n'+esc(r['message'][:180]))
            buttons.append([b.button('🆘 '+r['id'],'admin:ticketview:'+r['id'])])
    if section not in ('farm','finance'):
        more=len(rows)>3
        if not rows:lines.append('Записей на этой странице нет.')
        nav=[]
        if page:nav.append(b.button('⬅️ Назад','admin:accountdetail:'+section+':'+str(target)+':'+str(page-1)))
        if more:nav.append(b.button('Далее ➡️','admin:accountdetail:'+section+':'+str(target)+':'+str(page+1)))
        if nav:buttons.append(nav)
    buttons.extend([[b.button('🔄 Обновить','admin:accountdetail:'+section+':'+str(target)+':'+str(page))],[b.button('⬅️ Карточка игрока','admin:account:'+str(target))]])
    text='\n\n'.join(lines)
    # Short pages stay below Telegram's message limit, even for long
    # user-controlled names and destinations. Escape content before rendering.
    return b.bot_ui.screen(uid,text,buttons)
