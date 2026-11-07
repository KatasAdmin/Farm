"""TREVIXO public Telegram bot profile (same existing bot identity)."""
import json
import logging
from urllib.request import Request, urlopen

NAME="TREVIXO"
DESCRIPTION=("🚀 Выполняй задания, получай награды за подтверждённую рекламу, "
             "продвигай свои проекты и приглашай друзей. "
             "🎮 Игры, квесты и новые возможности — в одном месте. "
             "Правила начислений и выплат доступны внутри бота.")
ABOUT="🚀 Задания, продвижение, награды и игры — всё в одном месте."
COMMANDS=[
 {"command":"start","description":"Главная и знакомство"},
 {"command":"menu","description":"Восстановить меню"},
 {"command":"farm","description":"Открыть ферму"},
 {"command":"quests","description":"20 квестов и VIP"},
 {"command":"friends","description":"Пригласить друзей"},
 {"command":"profile","description":"Мой кабинет"},
 {"command":"help","description":"Как пользоваться ботом"},
]
def configure(token,username):
 """Apply only to the expected bot; never log or print its secret token."""
 if username.lower()!="farmlife2026bot":return False
 logger=logging.getLogger("farm.branding")
 for method,payload in (
  ("setMyName",{"name":NAME}),
  ("setMyDescription",{"description":DESCRIPTION}),
  ("setMyShortDescription",{"short_description":ABOUT}),
  ("setMyCommands",{"commands":COMMANDS}),
 ):
  try:
   request=Request("https://api.telegram.org/bot"+token+"/"+method,
     data=json.dumps(payload,ensure_ascii=False).encode("utf-8"),
     headers={"Content-Type":"application/json"})
   with urlopen(request,timeout=6) as resp:ok=json.load(resp).get("ok")
   if not ok:logger.warning("farm_branding_update_rejected method=%s",method)
  except Exception:
   logger.warning("farm_branding_update_failed method=%s",method)
 return True
