"""Public Telegram profile copy for the multi-game task platform."""
import json
import logging
from urllib.request import Request, urlopen

NAME="Farm — задания и игры"
DESCRIPTION=("🎮 Задания, продвижение и игры в одном боте. "
             "Зарабатывай на доступных заданиях и подтверждённой рекламе, "
             "продвигай свои проекты, приглашай друзей и проходи квесты. "
             "🌾 Ферма — наша первая игра. В будущем появятся другие. "
             "Денежные операции учитываются в гривнах; условия наград и выплат указаны внутри бота.")
ABOUT="🎮 Заработок, продвижение, квесты и игры. 🌾 Ферма — первая игра платформы."
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
