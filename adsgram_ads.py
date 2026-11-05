"""AdsGram Rewarded SDK diagnostics for isolated Telegram Mini App tests."""
import os
import re
import time
import uuid

from fastapi import HTTPException

import monetag_ads

SDK_URL = 'https://sad.adsgram.ai/js/sad.min.js'
PROVIDERS = {'adsgram', 'monetag', 'disabled'}
RESULTS = {'completed', 'no_fill', 'skipped', 'sdk_error', 'timeout'}
ATTEMPT_TTL = 120


def provider(platform):
    if platform != 'telegram':
        return 'disabled'
    selected = os.getenv('FARM_ADS_PROVIDER', 'monetag').strip().lower()
    return selected if selected in PROVIDERS else 'disabled'


def config(platform):
    block = os.getenv('ADSGRAM_BLOCK_ID', '')
    enabled = (
        provider(platform) == 'adsgram'
        and os.getenv('FARM_STAGING') == '1'
        and bool(re.fullmatch(r'[0-9]{1,20}', block))
    )
    # Reward URL has no documented event ID or per-attempt correlation.
    # A retry for the same Telegram ID cannot authorize a later attempt.
    return dict(
        enabled=enabled, block_id=block if enabled else None,
        sdk_url=SDK_URL, test_mode=True,
        reason='' if enabled else 'AdsGram доступен только в тестовом Telegram Mini App',
    )


def initialize(c):
    c.execute("""
        CREATE TABLE IF NOT EXISTS adsgram_test_attempts(
            id text PRIMARY KEY, player_id text NOT NULL, item text NOT NULL,
            started_at double precision NOT NULL, finished_at double precision,
            result text
        )
    """)
    c.execute("""
        CREATE INDEX IF NOT EXISTS adsgram_test_attempts_player_started
        ON adsgram_test_attempts(player_id, started_at DESC)
    """)


def recent(c, player_id, now):
    return c.execute("""
        SELECT * FROM adsgram_test_attempts
        WHERE player_id=%s AND started_at>=%s ORDER BY started_at DESC
    """, (player_id, min(now // 86400 * 86400, now - 3600))).fetchall()


def quota(rows, now):
    day = sum(row['started_at'] >= now // 86400 * 86400 for row in rows)
    hour = sum(row['started_at'] >= now - 3600 for row in rows)
    wait = 0
    if rows:
        elapsed = now - rows[0]['started_at']
        if rows[0]['result'] is None:
            wait = max(0, int(ATTEMPT_TTL - elapsed + 0.999))
        if hour and hour % monetag_ads.ADS_PER_BREAK == 0:
            wait = max(wait, int(monetag_ads.COOLDOWN - elapsed + 0.999))
    return dict(
        remaining_today=max(0, monetag_ads.DAY_LIMIT - day),
        remaining_hour=max(0, monetag_ads.HOUR_LIMIT - hour),
        retry_after=wait,
    )


def start(c, player, item, platform, now=None):
    if not config(platform)['enabled']:
        raise HTTPException(503, 'Тест AdsGram недоступен')
    if item not in monetag_ads.REWARDS:
        raise HTTPException(400, 'Награда не найдена')
    if item == 'geese' and player.get('farmer_level', 1) < 3:
        raise HTTPException(403, 'Гуси доступны с 3-го уровня')
    now = time.time() if now is None else now
    limits = quota(recent(c, player['id'], now), now)
    if not limits['remaining_today'] or not limits['remaining_hour'] or limits['retry_after']:
        raise HTTPException(429, 'Лимит рекламы. Попробуйте позже')
    attempt_id = uuid.uuid4().hex
    c.execute("""
        INSERT INTO adsgram_test_attempts(id,player_id,item,started_at)
        VALUES(%s,%s,%s,%s)
    """, (attempt_id, player['id'], item, now))
    return {'ymid': attempt_id}


def finish(c, player, attempt_id, result, platform, now=None):
    if not config(platform)['enabled']:
        raise HTTPException(503, 'Тест AdsGram недоступен')
    if result not in RESULTS:
        raise HTTPException(400, 'Неизвестный результат рекламы')
    now = time.time() if now is None else now
    row = c.execute("""
        SELECT * FROM adsgram_test_attempts WHERE id=%s AND player_id=%s FOR UPDATE
    """, (attempt_id, player['id'])).fetchone()
    if not row:
        raise HTTPException(404, 'Запуск рекламы не найден')
    if row['result'] is None and now - row['started_at'] < ATTEMPT_TTL:
        c.execute("""
            UPDATE adsgram_test_attempts SET result=%s,finished_at=%s WHERE id=%s
        """, (result, now, attempt_id))
    return {'ok': True, 'rewarded': False}


def status(c, player, data):
    now = time.time()
    rows = c.execute("""
        SELECT * FROM adsgram_test_attempts WHERE player_id=%s ORDER BY started_at DESC LIMIT 15
    """, (player['id'],)).fetchall()
    history = [
        dict(ymid=row['id'], item=row['item'], created_at=row['started_at'],
             state='test_' + (row['result'] or ('pending' if now - row['started_at'] < ATTEMPT_TTL else 'timeout')))
        for row in rows
    ]
    combined_history = sorted(history + data['history'], key=lambda row: row['created_at'], reverse=True)
    return dict(data, **{
        **config('telegram'), **quota(recent(c, player['id'], now), now),
        'history': combined_history[:15],
    })


def statistics(c):
    row = c.execute("""
        SELECT count(*) AS starts,
               count(CASE WHEN result='completed' THEN 1 END) AS completed,
               count(CASE WHEN result IN ('no_fill','skipped','sdk_error','timeout')
                           OR (result IS NULL AND started_at<=%s) THEN 1 END) AS sdk_errors
        FROM adsgram_test_attempts
    """, (time.time() - ATTEMPT_TTL,)).fetchone()
    return dict(row, paid=0, unpaid=0, granted=0,
                estimated_usd=None, settled_revenue=None)


def admin_text(c):
    data = statistics(c)
    return (
        '🎬 <b>Реклама AdsGram</b> · тестовый режим\n\n'
        f"Запусков: <b>{data['starts']}</b>\n"
        f"Тестовых завершений SDK: <b>{data['completed']}</b>\n"
        f"Ошибок, пропусков и истечений времени: <b>{data['sdk_errors']}</b>\n"
        'Оплаченных и неоплаченных событий сети: <b>0</b>\nВыдано наград: <b>0</b>\n'
        'Оценочный и подтверждённый доход: данных нет.'
    )
