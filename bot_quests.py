"""Sequential onboarding quests. No monetary awards or fake ad credit."""
import datetime as dt
from zoneinfo import ZoneInfo

QUESTS=[
 ("🎁 Забери первый ежедневный бонус","daily",1),
 ("🎬 Посмотри первую рекламу","ads_total",1),
 ("🎬 Заверши 5 просмотров рекламы","ads_total",5),
 ("✅ Выполни первое оплачиваемое задание","paid_jobs",1),
 ("🎬 Заверши 15 просмотров рекламы","ads_total",15),
 ("🤝 Пригласи первого друга","refs",1),
 ("📅 Забери бонус в 2 разных дня","daily",2),
 ("🎬 Заверши 30 просмотров рекламы","ads_total",30),
 ("✅ Выполни 3 оплачиваемых задания","paid_jobs",3),
 ("🤝 Пригласи 2 друзей","refs",2),
 ("🎬 Заверши 50 просмотров рекламы","ads_total",50),
 ("✅ Выполни 5 оплачиваемых заданий","paid_jobs",5),
 ("📅 Забери бонус в 4 разных дня","daily",4),
 ("🎬 Заверши 75 просмотров рекламы","ads_total",75),
 ("🤝 Пригласи 3 друзей","refs",3),
 ("✅ Выполни 10 оплачиваемых заданий","paid_jobs",10),
 ("🎬 Заверши 100 просмотров рекламы","ads_total",100),
 ("📅 Забери бонус в 7 разных дней","daily",7),
 ("🤝 Собери команду из 5 друзей","refs",5),
 ("🏆 Заверши 150 просмотров рекламы","ads_total",150),
]
TIPS={
 'daily':'Получай ежедневный бонус через раздел «Заработать». Возвращайся в разные дни.',
 'ads_total':'Открой «Смотреть рекламу» и заверши просмотр. Засчитываются только завершённые показы; доход начисляется отдельно после подтверждения сетью.',
 'paid_jobs':'Выбирай доступные задания в «Заработать», выполняй условия и проходи проверку, чтобы получить оплату.',
 'refs':'В разделе «Партнёры» скопируй личную ссылку и пригласи друзей. Будущие доходы команды зависят от её активности.',
}


def initialize(c):
 c.execute("""CREATE TABLE IF NOT EXISTS bot_monetag_cash_attempts(
    ymid text PRIMARY KEY,viewer_uid bigint NOT NULL,zone_id integer NOT NULL,
    placement text NOT NULL CHECK(placement='cash_rewarded_interstitial'),
    request_var text NOT NULL,created_at double precision NOT NULL,
    launched_at double precision,finished_at double precision,
    expires_at double precision NOT NULL,state text NOT NULL DEFAULT 'prepared'
    CHECK(state IN ('prepared','launched','confirmed','expired','rejected')),
    confirmed_at double precision)""")
 c.execute("CREATE TABLE IF NOT EXISTS bot_quest_progress(uid bigint PRIMARY KEY, completed integer NOT NULL DEFAULT 0 CHECK(completed>=0 AND completed<=20), updated_at double precision NOT NULL DEFAULT 0)")
 
def completed(c,uid):
 row=c.execute("SELECT completed FROM bot_quest_progress WHERE uid=%s",(uid,)).fetchone()
 return int(row['completed']) if row else 0

def vip(c,uid):
 return completed(c,uid)>=3

def metrics(c,uid):
 start=dt.datetime.now(ZoneInfo('Europe/Kyiv')).replace(hour=0,minute=0,second=0,microsecond=0)
 end=start+dt.timedelta(days=1)
 scalar=lambda sql,args: int((c.execute(sql,args).fetchone() or {}).get('n') or 0)
 return {
  'daily':scalar("SELECT count(*) AS n FROM bot_daily_claims WHERE uid=%s",(uid,)),
  'refs':scalar("SELECT count(*) AS n FROM bot_accounts WHERE referrer=%s AND uid<>%s",(uid,uid)),
  'paid_jobs':scalar("SELECT count(*) AS n FROM bot_claims WHERE uid=%s AND status='paid'",(uid,)),
  # SDK completion is activity only, not proof of advertiser payment.
  'ads_total':scalar("SELECT count(*) AS n FROM bot_monetag_cash_attempts WHERE viewer_uid=%s AND finished_at IS NOT NULL",(uid,)) + scalar("SELECT count(*) AS n FROM bot_adsgram_attempts WHERE uid=%s AND state='confirmed'",(uid,)),
  'ads_day':scalar("SELECT count(*) AS n FROM bot_monetag_cash_attempts WHERE viewer_uid=%s AND finished_at>=%s AND finished_at<%s",(uid,start.timestamp(),end.timestamp())) + scalar("SELECT count(*) AS n FROM bot_adsgram_attempts WHERE uid=%s AND state='confirmed' AND confirmed_at>=%s AND confirmed_at<%s",(uid,start.timestamp(),end.timestamp())),
 }

def show(c,uid):
 from task_bot import button
 level=completed(c,uid)
 m=metrics(c,uid)
 if level>=len(QUESTS):
  return ("🏆 <b>Все 20 квестов завершены!</b>\n💎 VIP активен.\n\nСпасибо за участие.",
          [[button('🤝 Партнёры','friends'),button('🎬 Реклама','watch_ads_info')],[button('⬅️ Заработать','earn')]])
 name,key,target=QUESTS[level]
 count=min(target,m[key])
 text=("⭐ <b>Квесты · Новая жизнь</b>\n"
       "🏅 Выполнено: <b>%s/20</b>\n💎 VIP: <b>%s</b>\n\n"
       "🎯 <b>Квест %s/20</b>\n%s\n"
       "Прогресс: <b>%s/%s</b>\n\n"
       "💡 %s\n\n"
       "Следующий этап откроется после нажатия «Завершить»." %
       (level,'активен ✅' if level>=3 else 'закрыт 🔒',level+1,name,count,target,TIPS[key]))
 buttons=[]
 if count>=target:buttons.append([button('✅ Завершить квест','quests:claim')])
 else:buttons.append([button('🔄 Проверить прогресс','quests')])
 if key=='refs':buttons.append([button('🤝 Моя ссылка','friends')])
 elif key=='daily':buttons.append([button('🎁 Получить бонус','daily')])
 elif key=='paid_jobs':buttons.append([button('🚀 Задания','earn')])
 elif key.startswith('ads'):buttons.append([button('🎬 Смотреть рекламу','watch_ads_info')])
 buttons.append([button('⬅️ Заработать','earn')])
 return text,buttons

def claim(c,uid):
 import time
 level=completed(c,uid)
 if level>=len(QUESTS):return False
 _,key,target=QUESTS[level]
 if metrics(c,uid)[key]<target:return False
 c.execute("INSERT INTO bot_quest_progress(uid,completed,updated_at) VALUES(%s,%s,%s) ON CONFLICT(uid) DO UPDATE SET completed=EXCLUDED.completed,updated_at=EXCLUDED.updated_at WHERE bot_quest_progress.completed=%s",(uid,level+1,time.time(),level))
 return True
