"""Draft client for AdsGram's separate Telegram Bot placement.

Unwired until the owner approves a chat rollout and the claim protocol is
verified. The client requests and formats an ad. It never issues rewards.
"""
import json
import re
from urllib.parse import urlencode, urlsplit
from urllib.request import urlopen


def chat_ad(telegram_id, block_id, language, token, *, fetch=urlopen):
    numeric_block = block_id.removeprefix('bot-')
    if not token or not re.fullmatch(r'[0-9]+', numeric_block):
        return None
    query = urlencode(dict(tgid=telegram_id, blockid=numeric_block, language=language, token=token))
    try:
        with fetch('https://api.adsgram.ai/advbot?' + query, timeout=5) as response:
            ad = json.load(response)
    except (ValueError, OSError):
        return None
    if not isinstance(ad, dict):
        return None
    fields = ('text_html', 'click_url', 'button_name', 'reward_url', 'button_reward_name')
    if not all(isinstance(ad.get(field), str) and ad[field] for field in fields):
        return None
    try:
        links = [urlsplit(ad[field]) for field in ('click_url', 'reward_url')]
    except ValueError:
        return None
    if any(link.scheme != 'https' or link.netloc != 'api.adsgram.ai' for link in links):
        return None
    return {
        'method': 'sendMessage', 'chat_id': telegram_id, 'parse_mode': 'HTML',
        'text': ad['text_html'], 'protect_content': True,
        'reply_markup': {'inline_keyboard': [
            [{'text': ad['button_name'], 'url': ad['click_url']}],
            [{'text': ad['button_reward_name'], 'url': ad['reward_url']}],
        ]},
    }
