"""Time-limited city goals over the existing production and trade records."""
import time
import simple_economy

from fastapi import HTTPException
from pydantic import BaseModel, Field
from psycopg.types.json import Jsonb


METRICS = {
    "batches": ("city_production_history", "player_id", "ready_at", "COUNT(*)", ""),
    "pancakes": ("city_production_history", "player_id", "ready_at", "SUM(quantity)", "AND recipe='pancakes'"),
    "orders": ("city_daily_orders", "player_id", "completed_at", "COUNT(*)", ""),
    "sales": ("city_receipts", "seller", "created", "SUM(quantity)", "AND buyer<>seller"),
    "raw": ("city_raw_receipts", "buyer", "created", "SUM(quantity)", "AND seller NOT IN (buyer,'__system__')"),
    "upgrades": ("city_progress_log", "player_id", "created", "COUNT(*)", "AND kind='upgrade'"),
}

DAILY = (
    ("batches", "Завершить производственную партию", 1, 5),
    ("raw", "Купить сырьё у игроков", 3, 5),
    ("sales", "Продать готовые товары", 2, 5),
    ("orders", "Выполнить заказ жителя", 1, 5),
)
SEASON = (
    ("batches", "Завершить производственные партии", 5, 50),
    ("orders", "Выполнить заказы жителей", 3, 80),
    ("sales", "Продать готовые товары", 10, 60),
    ("raw", "Купить сырьё у игроков", 10, 40),
    ("upgrades", "Улучшить предприятие", 1, 100),
)
REWARDS = (("founder", "Значок «Горожанин»", 50), ("violet", "Фиолетовая рамка", 150),
           ("gold", "Золотая рамка", 300))
PREMIUM = ("Рамка «Ночной город»", "Значок «Меценат»")


class Campaign(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9_-]{1,40}$")
    kind: str = Field(pattern=r"^(season|event)$")
    name: str = Field(min_length=1, max_length=90)
    description: str = Field(default="", max_length=300)
    starts: float = Field(ge=0, le=4102444800)
    ends: float = Field(ge=0, le=4102444800)
    enabled: bool = True
    metric: str = Field(default="pancakes")
    goal: int = Field(default=10, ge=1, le=10000)
    xp: int = Field(default=25, ge=0, le=100)


def initialize(c):
    c.execute("""CREATE TABLE IF NOT EXISTS city_campaigns(
        id text PRIMARY KEY, kind text NOT NULL, starts double precision NOT NULL,
        ends double precision NOT NULL, enabled boolean NOT NULL, definition jsonb NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS city_goal_claims(
        player_id text NOT NULL, scope text NOT NULL, goal text NOT NULL,
        xp integer NOT NULL DEFAULT 0, PRIMARY KEY(player_id,scope,goal))""")
    c.execute("""CREATE TABLE IF NOT EXISTS city_preferences(
        player_id text PRIMARY KEY, effects boolean NOT NULL DEFAULT true,
        cosmetic text NOT NULL DEFAULT '')""")
    now = time.time()
    season = Campaign(id="city-development", kind="season", name="Городское развитие",
                      starts=now, ends=now+30*86400)
    c.execute("""INSERT INTO city_campaigns VALUES(%s,%s,%s,%s,%s,%s)
        ON CONFLICT(id) DO NOTHING""", campaign_values(season))


def campaign_values(campaign):
    return (campaign.id, campaign.kind, campaign.starts, campaign.ends,
            campaign.enabled, Jsonb(campaign.model_dump()))


def save(c, campaign):
    if campaign.ends <= campaign.starts or campaign.metric not in METRICS:
        raise HTTPException(400, "Проверьте период и тип задания")
    c.execute("SELECT pg_advisory_xact_lock(1984533)")
    if campaign.kind == "season" and campaign.enabled and c.execute("""
        SELECT 1 FROM city_campaigns WHERE kind='season' AND enabled AND id<>%s
        AND starts<%s AND ends>%s LIMIT 1""", (campaign.id, campaign.ends, campaign.starts)).fetchone():
        raise HTTPException(409, "В этот период уже есть сезон")
    current = c.execute("SELECT * FROM city_campaigns WHERE id=%s FOR UPDATE", (campaign.id,)).fetchone()
    if current and (current["kind"] != campaign.kind or current["starts"] != campaign.starts):
        raise HTTPException(409, "Для другого типа или даты запуска создайте новый период")
    c.execute("""INSERT INTO city_campaigns VALUES(%s,%s,%s,%s,%s,%s)
        ON CONFLICT(id) DO UPDATE SET ends=EXCLUDED.ends, enabled=EXCLUDED.enabled,
        definition=EXCLUDED.definition""", campaign_values(campaign))
    return {"ok": True}


def _metric(c, pid, metric, start, end):
    if simple_economy.enabled() and metric in ("raw", "sales"):
        kind, operator = ("buy", "= ANY") if metric == "raw" else ("sell", "<> ALL")
        excluded = list(simple_economy.RAW_BUY)
        if metric == "sales":
            excluded += list(simple_economy.ANIMAL_BUY)
        return c.execute(f"""SELECT COALESCE(SUM(quantity),0) AS n FROM simple_system_trades
            WHERE player_id=%s AND kind=%s AND created>=%s AND created<%s
            AND item {operator}(%s)""",(pid,kind,start,end,excluded)).fetchone()["n"]
    table, player, date, value, extra = METRICS[metric]
    return c.execute(f"""SELECT COALESCE({value},0) AS n FROM {table}
        WHERE {player}=%s AND {date}>=%s AND {date}<%s {extra}""",
        (pid, start, end)).fetchone()["n"]


def _state(c, pid, scope, start, end, now, specs, enabled=True):
    claims = {r["goal"]: r["xp"] for r in c.execute(
        "SELECT goal,xp FROM city_goal_claims WHERE player_id=%s AND scope=%s",
        (pid, scope)).fetchall()}
    active = enabled and start <= now < end
    goals = []
    for key, label, goal, xp in specs:
        value = _metric(c, pid, key, start, min(now, end))
        if key == "raw" and simple_economy.enabled():
            label = "Купить сырьё на рынке"
        goals.append({"key": key, "name": label, "goal": goal, "value": value,
                      "xp": xp, "claimed": key in claims, "available": active and value >= goal})
    return {"id": scope, "active": active, "starts": start, "ends": end,
            "xp": sum(claims.values()), "goals": goals, "claims": claims}


def story_state(c,pid):
    opened={row["kind"] for row in c.execute(
        "SELECT kind FROM city_businesses WHERE player_id=%s",(pid,)).fetchall()}
    claims={row["goal"] for row in c.execute(
        "SELECT goal FROM city_goal_claims WHERE player_id=%s AND scope='story'",(pid,)).fetchall()}
    goals=[]
    for kind,name in (("bakery","Открыть пекарню"),("restaurant","Открыть ресторан"),
                      ("dairy","Открыть молочную"),("atelier","Открыть ателье")):
        goals.append({"key":kind,"name":name,"goal":1,"value":int(kind in opened),
                      "available":kind in opened,"claimed":kind in claims,"xp":20,"status":10})
    return {"id":"story","active":True,"goals":goals}


def state(c, pid, now):
    start = now - now % 86400
    daily = _state(c, pid, "day:" + str(int(start // 86400)), start, start+86400, now, DAILY)
    campaigns = []
    for row in c.execute("SELECT * FROM city_campaigns ORDER BY starts DESC,id LIMIT 30").fetchall():
        spec = row["definition"]
        season = row["kind"] == "season"
        goals = SEASON if season else ((spec["metric"], "Выполнить цель события", spec["goal"], spec["xp"]),)
        result = _state(c, pid, row["id"], row["starts"], row["ends"], now, goals, row["enabled"])
        result.update(name=spec["name"], description=spec["description"], kind=row["kind"])
        if season:
            result["level"] = 1 + sum(result["xp"] >= threshold for _, _, threshold in REWARDS)
            result["premium"] = PREMIUM
            result["rewards"] = [{"key": "reward:"+key, "name": label, "goal": threshold,
                "claimed": "reward:"+key in result["claims"],
                "available": result["active"] and result["xp"] >= threshold}
                for key, label, threshold in REWARDS]
        campaigns.append(result)
    return {"daily": daily, "campaigns": campaigns,
            **({"story":story_state(c,pid)} if simple_economy.enabled() else {})}


def cosmetics(c, pid):
    claimed = {row["goal"] for row in c.execute("""SELECT DISTINCT claim.goal
        FROM city_goal_claims claim JOIN city_campaigns campaign ON campaign.id=claim.scope
        WHERE claim.player_id=%s AND campaign.kind='season'""", (pid,)).fetchall()}
    return [{"id": key, "name": label} for key, label, _ in REWARDS if "reward:"+key in claimed]



def claim(c, pid, scope, key, now, progress_event):
    if scope=="story" and simple_economy.enabled():
        period=story_state(c,pid)
    else:
        snapshot=state(c,pid,now)
        period=next((p for p in [snapshot["daily"],*snapshot["campaigns"]] if p["id"]==scope),None)
    if not period:
        raise HTTPException(404, "Период не найден")
    goal = next((g for g in period["goals"]+period.get("rewards", []) if g["key"] == key), None)
    if not goal:
        raise HTTPException(404, "Награда не найдена")
    if goal["claimed"]:
        return {"ok": True}
    if not goal["available"]:
        raise HTTPException(409, "Награда пока недоступна")
    season = period.get("kind") == "season"
    xp = goal.get("xp", 0)
    created = c.execute("""INSERT INTO city_goal_claims VALUES(%s,%s,%s,%s)
        ON CONFLICT DO NOTHING RETURNING goal""", (pid, scope, key, xp if season else 0)).fetchone()
    if created:
        status=goal.get("status",0)
        if status:
            c.execute("""INSERT INTO city_reputation(player_id,points) VALUES(%s,%s)
                ON CONFLICT(player_id) DO UPDATE SET points=city_reputation.points+EXCLUDED.points""",
                (pid,status))
            progress_event(c,pid,"goal:"+scope+":"+key,"goal",now,xp,status)
        else:
            progress_event(c,pid,"goal:"+scope+":"+key,"goal",now,0 if season else xp)
    return {"ok": True}
