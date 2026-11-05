import fields
import farm_expansion
import achievement_stages
import achievement_counters
import weekly_missions
import market_allocation
import incubation_rules
import stars_validation
import monetag_ads
import ad_inventory
import farm_ranking
import release_grants
import farm_wallet
import referral_bridge
from bot_copy import tr
import os,time,uuid,secrets,hashlib,hmac,json,logging,base64
import mimetypes
mimetypes.add_type("image/webp",".webp")
import task_bot
from bot_release import RELEASE
import threading
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.exceptions import InvalidSignature
logger=logging.getLogger("farm.security")
from urllib.parse import parse_qsl
from urllib.request import Request as URLRequest, urlopen
import psycopg
from psycopg.rows import dict_row
from fastapi import FastAPI,HTTPException,Header,Request as HTTPRequest
from fastapi.responses import HTMLResponse,JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from contextlib import asynccontextmanager
from production import CYCLE, FEED_EVERY, GRAIN_PRICE, simulate, forecast
from production_v4 import simulate as simulate_v4, forecast as forecast_v4, feed_required, COW_PRICE, COW_FEED, MILK_PRICE, MILK_INTERVAL
def db():return psycopg.connect(os.environ["DATABASE_URL"],row_factory=dict_row,connect_timeout=10,options="-c statement_timeout=30000 -c lock_timeout=10000 -c idle_in_transaction_session_timeout=30000 -c transaction_timeout=60000")
@asynccontextmanager
async def lifespan(app):
 logger.warning("farm_startup_database_connecting release=%s",RELEASE)
 with db() as c:
  logger.warning("farm_startup_database_connected")
  # Match request lock order before DDL takes exclusive table locks.
  # Otherwise a live webhook can hold this lock while waiting on our tables.
  c.execute("SELECT pg_advisory_xact_lock(1984533)")
  logger.warning("farm_startup_migration_lock_acquired")
  c.execute("CREATE TABLE IF NOT EXISTS players(id text primary key,name text unique,token text unique,coins int default 10,grain int default 5,chickens int default 1,eggs int default 0,last_feed float default 0)")
  c.execute("CREATE TABLE IF NOT EXISTS market(id text primary key,seller text,item text,quantity int,price int)")
  c.execute("CREATE TABLE IF NOT EXISTS monetag_ad_attempts(ymid text primary key,player_id text not null,created_at double precision not null,rewarded_at double precision,zone_id int not null,placement text not null)")
  c.execute("CREATE INDEX IF NOT EXISTS monetag_ad_attempts_player_idx ON monetag_ad_attempts(player_id,created_at)")
  c.execute("CREATE TABLE IF NOT EXISTS monetag_reward_grants(id text PRIMARY KEY,player_id text NOT NULL,item text NOT NULL,quantity integer NOT NULL CHECK(quantity>0),created double precision NOT NULL,claimed_at double precision)")
  c.execute("CREATE INDEX IF NOT EXISTS monetag_reward_grants_player_idx ON monetag_reward_grants(player_id,claimed_at)")
  monetag_ads.initialize(c)
  ad_inventory.initialize(c)
  c.execute("CREATE TABLE IF NOT EXISTS economy(id int primary key,treasury int not null check(treasury>=0))")
  c.execute("INSERT INTO economy(id,treasury) SELECT 1,GREATEST(0,10000-(SELECT COALESCE(SUM(coins),0)::int FROM players)) WHERE NOT EXISTS(SELECT 1 FROM economy)")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS satiety integer NOT NULL DEFAULT 100")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS last_tick double precision")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS production_model integer NOT NULL DEFAULT 1")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS egg_at double precision")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS egg_progress double precision NOT NULL DEFAULT 0")
  for column,definition in (("cows","integer NOT NULL DEFAULT 0 CHECK(cows>=0)"),("fed_cows","integer NOT NULL DEFAULT 0"),("milk","integer NOT NULL DEFAULT 0 CHECK(milk>=0)"),("milk_progress","double precision NOT NULL DEFAULT 0"),("cowshed_level","integer NOT NULL DEFAULT 1"),("cow_xp","integer NOT NULL DEFAULT 0")):
   c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS "+column+" "+definition)
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS feathers integer NOT NULL DEFAULT 0 CHECK(feathers>=0)")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS feather_progress double precision NOT NULL DEFAULT 0 CHECK(feather_progress>=0)")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS geese integer NOT NULL DEFAULT 0 CHECK(geese>=0)")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS fed_geese integer NOT NULL DEFAULT 0 CHECK(fed_geese>=0)")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS goose_xp integer NOT NULL DEFAULT 0 CHECK(goose_xp>=0)")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS farmer_level integer NOT NULL DEFAULT 1 CHECK(farmer_level>=0)")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS fed_hens integer NOT NULL DEFAULT 0")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS feed_phase integer NOT NULL DEFAULT 0")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS xp_legacy_eggs integer")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS xp_legacy_listed integer")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS xp_legacy_sold integer")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS critical_cycles integer NOT NULL DEFAULT 0")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS autobuy_enabled boolean NOT NULL DEFAULT false")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS autobuy_min integer NOT NULL DEFAULT 5")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS autobuy_amount integer NOT NULL DEFAULT 20")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS coop_level integer NOT NULL DEFAULT 1")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS storage_level integer NOT NULL DEFAULT 1")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS created_at double precision")
  c.execute("UPDATE players SET created_at=%s WHERE created_at IS NULL",(time.time(),))
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS bundle_uses integer NOT NULL DEFAULT 0")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS welcome_granted boolean NOT NULL DEFAULT false")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS game_status text NOT NULL DEFAULT 'farmer'")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS gender text NOT NULL DEFAULT 'unspecified'")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS age integer")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS avatar text NOT NULL DEFAULT 'default'")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS avatar_photo text")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS incubator_owned boolean NOT NULL DEFAULT false")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS incubation_started double precision")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS chick_ready_at double precision")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS incubator_level integer NOT NULL DEFAULT 1")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS tutorial_step integer NOT NULL DEFAULT 0")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS recovery_hash text")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS password_hash text")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS telegram_id bigint UNIQUE")
  c.execute("CREATE TABLE IF NOT EXISTS telegram_processed_updates(update_id bigint PRIMARY KEY,received_at double precision NOT NULL)")
  c.execute("CREATE TABLE IF NOT EXISTS telegram_processed_messages(chat_id bigint NOT NULL,message_id bigint NOT NULL,received_at double precision NOT NULL,PRIMARY KEY(chat_id,message_id))")
  c.execute("CREATE TABLE IF NOT EXISTS star_orders(id text PRIMARY KEY,player_id text NOT NULL,telegram_id bigint NOT NULL,coins integer NOT NULL CHECK(coins>0),stars integer NOT NULL CHECK(stars>0),status text NOT NULL DEFAULT 'created',created double precision NOT NULL,charge_id text UNIQUE)")
  c.execute("CREATE TABLE IF NOT EXISTS stars_refund_intents(order_id text PRIMARY KEY,charge_id text NOT NULL,telegram_id bigint NOT NULL,status text NOT NULL CHECK(status IN ('calling','confirmed','needs_review')),created double precision NOT NULL,updated double precision NOT NULL)")
  c.execute("CREATE TABLE IF NOT EXISTS farm_launch_resets(run_id text PRIMARY KEY,reset_at timestamptz NOT NULL DEFAULT now(),prior_player_count integer NOT NULL,preserved_payment_count integer NOT NULL)")
  c.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS purchased_coins bigint NOT NULL DEFAULT 0")
  c.execute("CREATE INDEX IF NOT EXISTS star_orders_player ON star_orders(player_id,created)")
  c.execute("CREATE TABLE IF NOT EXISTS farm_admin_identity(slot integer PRIMARY KEY CHECK(slot=1),telegram_id bigint NOT NULL UNIQUE,claimed_at double precision NOT NULL)")
  c.execute("CREATE TABLE IF NOT EXISTS telegram_link_codes(code_hash text PRIMARY KEY, player_id text NOT NULL, expires double precision NOT NULL)")
  c.execute("CREATE INDEX IF NOT EXISTS telegram_link_player ON telegram_link_codes(player_id)")
  c.execute("CREATE TABLE IF NOT EXISTS login_failures(name text PRIMARY KEY,attempts int NOT NULL DEFAULT 0,locked_until double precision NOT NULL DEFAULT 0)")
  c.execute("CREATE TABLE IF NOT EXISTS support_tickets(id text PRIMARY KEY,telegram_id bigint NOT NULL,nickname text NOT NULL,message text NOT NULL,status text NOT NULL DEFAULT 'open',created double precision NOT NULL,answered_at double precision)")
  c.execute("CREATE INDEX IF NOT EXISTS support_tickets_sender ON support_tickets(telegram_id,created)")
  c.execute("CREATE TABLE IF NOT EXISTS registration_limits(slot text PRIMARY KEY,count integer NOT NULL,updated double precision NOT NULL)")

  c.execute("ALTER TABLE players ADD 