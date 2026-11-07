"""Owner-managed visibility for public Telegram controls.

Hiding a feature never deletes payments or changes the settlement of invoices
already issued. Only entry to new actions is blocked.
"""
from bot_copy import tr

# key -> (human label, default visible, category, canonical Telegram actions)
FEATURES={
    'main_earn':('🚀 Заработать',1,'main',('🚀 Заработать',)),
    'main_promotion':('📣 Продвижение',1,'main',('📣 Продвижение',)),
    'main_games':('🎮 Игры',1,'main',('🎮 Игры',)),
    'main_cabinet':('👤 Кабинет',1,'main',('👤 Мой кабинет',)),
    'main_partners':('👥 Партнёры',1,'main',('👥 Партнёры',)),
    'main_about':('📚 О боте',1,'main',('📚 О боте',)),
    'stars':('⭐ Пополнение Stars',0,'finance',('topup:stars',)),
    'crypto_topup':('💎 Пополнение CryptoBot',1,'finance',('topup:crypto',)),
    'card_topup':('💳 Пополнение картой',1,'finance',('topup:card',)),
    'card_payout':('💳 Вывод на карту',1,'finance',('withdraw:card',)),
    'crypto_payout':('💎 Вывод через CryptoBot',1,'finance',('withdraw:crypto',)),
    'balance_history':('🧾 История баланса',1,'finance',('history',)),
    'topup_history':('📥 История пополнений',1,'finance',('topup:mine',)),
    'payout_history':('💸 История выплат',1,'finance',('payouts',)),
    'advertisement':('🎬 Смотреть рекламу',1,'earn',('ads:preview',)),
    'earn_bots':('🤖 Задания в ботах',1,'earn',('botclick:feed',)),
    'earn_channels':('📣 Подписки на каналы',1,'earn',('channel:feed',)),
    'earn_groups':('👥 Вступления в группы',1,'earn',('group:feed',)),
    'earn_quests':('⭐ Квесты',1,'earn',('quests',)),
    'earn_manual':('📝 Задания',1,'earn',('list:manual:0',)),
    'earn_bonus':('🎁 Ежедневный бонус',1,'earn',('daily',)),
    'earn_friends':('🤝 Пригласить друга',1,'earn',('friends',)),
    'orders':('📋 Мои заказы',1,'promotion',('mine:0',)),
    'proof_review':('✅ Проверить работы',1,'promotion',('reviews:0',)),
    'promo_topup':('➕ Пополнить из продвижения',1,'promotion',('deposit',)),
}
GROUPS=(('main','🏠 Главное меню'),('finance','💳 Деньги'),('earn','🚀 Заработок'),('promotion','📣 Продвижение'))
MENU_KEYS={name:key for key,(_,_,group,actions) in FEATURES.items() if group=='main' for name in actions}
ACTION_KEYS={action:key for key,(_,_,group,actions) in FEATURES.items() if group!='main' for action in actions}

def initialize(c):
    c.execute('CREATE TABLE IF NOT EXISTS bot_visibility_flags(key text PRIMARY KEY,visible integer NOT NULL CHECK(visible IN (0,1)))')
    for key,(_,default,_,_) in FEATURES.items():
        c.execute('INSERT INTO bot_visibility_flags(key,visible) VALUES(%s,%s) ON CONFLICT DO NOTHING',(key,default))

def enabled(c,key):
    if key not in FEATURES:
        return True
    row=c.execute('SELECT visible FROM bot_visibility_flags WHERE key=%s',(key,)).fetchone()
    return bool(row['visible']) if row else bool(FEATURES[key][1])

def key_for_action(action):
    if action.startswith('bot:'):
        action=action[4:]
    return ACTION_KEYS.get(action)

def filter_buttons(c,rows):
    if c is None or not rows:
        return rows
    out=[]
    for row in rows:
        kept=[]
        for button in row:
            action=button.get('callback_data','')
            key=key_for_action(action)
            # A web-app advertisement button has no callback_data.
            if key is None and button.get('web_app') and button.get('text','').startswith('🎬 Смотреть рекламу'):
                key='advertisement'
            if not key or enabled(c,key):
                kept.append(button)
        if kept:
            out.append(kept)
    return out

def filter_menu(c,rows,canonical):
    if c is None:
        return rows
    result=[]
    for custom,originals in zip(rows,canonical):
        kept=[name for name,original in zip(custom,originals)
              if enabled(c,MENU_KEYS[original])]
        if kept:
            result.append(kept)
    return result

def screen(c,uid,group=None):
    from task_bot import bot_ui,button,state
    state(c,uid,'clear')
    if group is None:
        text='👁 <b>Видимость кнопок</b>\\n\\nОтключённая функция исчезает из меню и не открывается по старой кнопке. Существующие платежи, чеки и история сохраняются.\\n\\nВыбери раздел:'
        rows=[]
        for section,label in GROUPS:
            count=sum(1 for key,(_,_,g,_) in FEATURES.items() if g==section and enabled(c,key))
            total=sum(1 for _,(_,_,g,_) in FEATURES.items() if g==section)
            rows.append([button(label+' · '+str(count)+'/'+str(total),'admin:visibility:'+section)])
        rows.append([button('⬅️ Админка','admin')])
        return bot_ui.screen(uid,text,rows)
    if group not in dict(GROUPS):
        from task_bot import UserError
        raise UserError('Неизвестный раздел видимости.')
    text=dict(GROUPS)[group]+'\\n\\n✅ видна · ⛔ скрыта\\nИзменения действуют сразу для новых действий.'
    rows=[]
    items=[(key,label) for key,(label,_,g,_) in FEATURES.items() if g==group]
    for idx in range(0,len(items),2):
        rows.append([button(('✅ ' if enabled(c,key) else '⛔ ')+label,'admin:visibility:toggle:'+key)
                     for key,label in items[idx:idx+2]])
    rows.append([button('⬅️ К разделам','admin:visibility')])
    return bot_ui.screen(uid,text,rows)

def route(c,uid,action):
    from task_bot import UserError
    if action=='admin:visibility':
        return screen(c,uid)
    if action.startswith('admin:visibility:toggle:'):
        key=action.split(':')[-1]
        if key not in FEATURES:
            raise UserError('Неизвестная кнопка.')
        c.execute('UPDATE bot_visibility_flags SET visible=%s WHERE key=%s',(0 if enabled(c,key) else 1,key))
        return screen(c,uid,FEATURES[key][2])
    if action.startswith('admin:visibility:'):
        return screen(c,uid,action.split(':')[-1])
    return None
