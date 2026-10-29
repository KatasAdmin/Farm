"""Capture each real screen in a fresh Chromium page after functional QA.

Reads only generated QA accounts from the dedicated LOCAL database. Never use
production credentials. No inventories/balances are assigned or mocked.
"""
import os
from pathlib import Path

import psycopg
from playwright.sync_api import sync_playwright

OUTPUT = Path(os.environ.get('FARM_VISUAL_OUTPUT', '/workspace/artifacts/illustrated-world'))
DATABASE = 'postgresql://farm:farm@127.0.0.1:5543/farm_visual_test'
BASE = 'http://127.0.0.1:8085'
SCREENS = ['farm', 'coop', 'market-buy', 'market-sell', 'shop', 'wallet',
           'profile', 'storage', 'tasks', 'upgrades', 'purchase']


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with psycopg.connect(DATABASE) as db:
        row = db.execute("SELECT token FROM players WHERE name LIKE 'qa_Фермер_%' "
                         "ORDER BY last_tick DESC LIMIT 1").fetchone()
        assert row, 'Run browser_qa.py first to create a dedicated QA player'
        token = row[0]
    with sync_playwright() as p:
        for name in SCREENS:
            browser = p.chromium.launch(executable_path='/usr/bin/chromium',
                                        args=['--no-sandbox', '--disable-gpu'])
            page = browser.new_page(viewport={'width': 390, 'height': 844},
                                    is_mobile=True, reduced_motion='reduce')
            page.add_init_script('localStorage.setItem("farm_token", ' + repr(token) + ')')
            page.goto(BASE)
            page.locator('#app').wait_for(state='visible')
            page.evaluate('document.fonts.ready')
            page.evaluate('Promise.all([...document.images].map(x => x.decode()))')
            screen = 'market' if name.startswith('market-') else 'shop' if name == 'purchase' else name
            page.evaluate('tab', screen)
            if name.startswith('market-'):
                page.evaluate('marketTab', name.split('-')[1])
            if name == 'purchase':
                page.evaluate("showShop('chickens')")
            page.wait_for_timeout(1500)
            page.screenshot(path=str(OUTPUT / (name + '.png')))
            browser.close()
            print(name)


if __name__ == '__main__':
    main()
