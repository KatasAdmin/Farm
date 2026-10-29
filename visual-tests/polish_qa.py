"""Run against local FastAPI :8086 + existing dedicated farm_visual_test DB.
Only creates unique qa_ accounts; no resets/deletions. Ages this account's clocks
for real production/incubation, with no API mocks or injected balances.
"""
import json
import time
import uuid
from pathlib import Path

import httpx
import psycopg
from playwright.sync_api import sync_playwright

BASE = 'http://127.0.0.1:8086'
DB = 'postgresql://farm:farm@127.0.0.1:5543/farm_visual_test'
OUT = Path(__file__).parent / 'polish'


def main():
    OUT.mkdir(exist_ok=True)
    assert httpx.get(BASE+'/health').json() == {'ok': True}
    errors, images, layouts = [], [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
        context = browser.new_context(viewport={'width':390,'height':844}, is_mobile=True, has_touch=True, reduced_motion='reduce')
        page = context.new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('response', lambda r: images.append(r.url) if '/assets/' in r.url and r.status>=400 else None)
        page.on('dialog', lambda d: d.accept())
        page.goto(BASE)
        name = 'qa_polish_'+uuid.uuid4().hex[:6]
        page.locator('#name').fill(name)
        page.locator('#join-gender').select_option('male')
        page.locator('#join-form button').click()
        page.wait_for_function('state && state.me.coins === 400')
        token = page.evaluate("localStorage.getItem('farm_token')")
        player_id = page.evaluate('state.me.id')

        def age(field, value):
            assert field in {'last_tick','incubation_started','chick_ready_at'}
            with psycopg.connect(DB) as c:
                assert c.execute(f'UPDATE players SET {field}=%s WHERE id=%s AND name=%s RETURNING id', (value,player_id,name)).fetchone()
            page.evaluate('refresh()')

        def ready():
            page.wait_for_function("!document.body.classList.contains('pending')")
            page.wait_for_function('Array.from(document.images).every(x => x.complete && x.naturalWidth > 0)')
            page.evaluate('document.fonts.ready')

        def go(screen):
            if screen in {'farm','shop','tasks','wallet','profile'}:
                page.locator(f'#nav [data-tab="{screen}"]').click()
            elif screen == 'coop':
                page.locator('#nav [data-tab="farm"]').click()
                page.locator('#farm .quick[onclick="tab(\'coop\')"]').click()
            else:
                page.evaluate('(id) => tab(id)',screen)
            ready()

        def capture(name):
            ready()
            page.wait_for_function("document.getElementById('toast').hidden",timeout=8000)
            page.evaluate('window.scrollTo(0,0)')
            page.screenshot(path=str(OUT/(name+'.png')))

        page.reload()
        page.wait_for_function('state && state.me.coins === 400')
        assert page.evaluate("localStorage.getItem('farm_token')") == token
        assert page.locator('#farm .flock img').count() == 2
        assert all('redesign/hen' in x for x in page.locator('#farm .flock img').evaluate_all('(nodes)=>nodes.map(x=>x.src)'))
        go('shop')
        page.locator('#shop [onclick="showShop(\'grain\')"]').click()
        page.locator('#purchase-amount').fill('5')
        assert page.locator('#purchase-total').inner_text() == '10'
        page.locator('#purchase-confirm').click()
        page.wait_for_function('state.me.coins === 390 && state.me.grain === 10')
        go('tasks')
        page.locator('#daily-tasks button[onclick="claimDaily(\'grain\')"]').click()
        page.wait_for_function('state.me.coins === 391 && state.claimed_rewards.includes("grain")')
        page.locator('#achievements-switch').click()
        assert page.locator('#achievement-pane').is_visible()
        assert page.locator('#tasks.active').count() == 1
        capture('achievements')
        page.locator('#tasks-switch').click()
        capture('tasks')
        age('last_tick',time.time()-86402)
        page.wait_for_function('state.me.eggs === 1')
        go('coop')
        page.locator('.production-history summary').click()
        assert '+1 яиц' in page.locator('#production-history').inner_text()
        capture('coop')
        go('shop')
        page.locator('#shop [onclick="openSell(\'eggs\')"]').click()
        page.locator('#sellnum').fill('1')
        assert '5' in page.locator('#sellquote').inner_text()
        page.get_by_role('button',name='Выставить на продажу',exact=True).click()
        page.wait_for_function('state.me.eggs === 0 && state.my_listings.length === 1')
        assert 'Товар выставлен на продажу' in page.locator('#toast').inner_text()
        capture('trade-sell')
        page.locator('#mylist button').click()
        page.wait_for_function('state.me.eggs === 1 && state.my_listings.length === 0')
        go('shop')
        page.locator('#incubator-shop-button').click()
        page.wait_for_function('state.incubator.owned && state.me.coins === 271')
        page.locator('#incubator-shop-button').click()
        page.locator('#incubator-action').click()
        page.wait_for_function('state.incubator.incubation_started !== null && state.me.eggs === 0')
        assert page.evaluate('state.me.chickens') == 1
        capture('incubator-egg')
        age('incubation_started',time.time()-43202)
        page.wait_for_function('state.incubator.chick_ready_at !== null')
        assert page.evaluate('state.me.chickens') == 1
        assert page.locator('[data-stage="chick"]').get_attribute('class') == 'active'
        capture('incubator-chick')
        age('chick_ready_at',time.time()-2)
        page.wait_for_function('state.me.chickens === 2 && state.incubator.chick_ready_at === null')
        go('farm')
        assert '+2' in page.locator('#next-harvest').inner_text()
        capture('farm')
        go('shop')
        assert 'осталось покупок: 5 / 5' in page.locator('#promo-status').inner_text()
        assert page.locator('#bundle-buy').is_disabled() # balance below 300
        capture('trade-buy')
        # Responsive screen fit and last control accessibility, using real API data.
        for width in (320,375,390,430):
            page.set_viewport_size({'width':width,'height':844})
            for screen in ('farm','coop','shop','market','tasks','upgrades','profile','storage','wallet'):
                go(screen)
                assert not page.evaluate('document.documentElement.scrollWidth > innerWidth'),(width,screen)
                buttons = page.locator(f'#{screen} button:visible:not([disabled])')
                if buttons.count():
                    buttons.last.scroll_into_view_if_needed()
                    page.evaluate('window.scrollBy(0,180)')
                    assert buttons.last.bounding_box()['y']+buttons.last.bounding_box()['height'] <= page.locator('#nav').bounding_box()['y']+1,(width,screen)
                layouts.append({'width':width,'screen':screen,'result':'PASS'})
        assert not errors,errors
        assert not images,images
        browser.close()
    report={'result':'PASS','browser':'Chromium mobile/touch','layout_checks':layouts,'javascript_errors':errors,'image_errors':images,'checks':['health','registration/reload','live purchase quote','grain purchase','daily reward','achievements tab','production history','sell notification','cancel restores egg','incubator purchase','egg/chick/hen timing','promotion remaining count','bottom navigation clearance']}
    (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False))


if __name__ == '__main__':
    main()
