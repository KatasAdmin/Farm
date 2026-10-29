"""v29 real-browser QA. Local FastAPI :8090 and existing local QA DB only.
No API mocks, production connections or database resets. Only this new qa29_
account's clock is aged to exercise server timers and resume synchronization.
"""
import json
import re
import time
import uuid
from pathlib import Path

import httpx
import psycopg
from playwright.sync_api import sync_playwright

BASE='http://127.0.0.1:8090'
DB='postgresql://farm:farm@127.0.0.1:5543/farm_visual_test'
OUT=Path(__file__).parent/'update29'


def main():
    OUT.mkdir(exist_ok=True)
    assert httpx.get(BASE+'/health').json()=={'ok':True}
    errors,broken,layouts=[],[],[]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox'])
        context=browser.new_context(viewport={'width':390,'height':844},is_mobile=True,has_touch=True,reduced_motion='reduce')
        page=context.new_page()
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('response',lambda r:broken.append(r.url) if '/assets/' in r.url and r.status>=400 else None)
        page.on('dialog',lambda d:d.accept())
        page.goto(BASE)
        name='qa29_'+uuid.uuid4().hex[:8]
        page.locator('#name').fill(name)
        page.locator('#register-password').fill('QaFarmPass29!')
        page.locator('#join-gender').select_option('male')
        page.locator('#join-form button').click()
        page.wait_for_function('state && state.me.coins === 10')
        pid=page.evaluate('state.me.id')
        if page.locator('#recovery-dialog').evaluate('(x)=>x.open'):
            page.locator('#recovery-dialog button[onclick="closeRecoveryCode()"]').click()
        # Complete existing onboarding via the real UI/API.
        for _ in range(3):
            page.evaluate("tab('farm')")
            page.locator('#tutorial-next').click()
            page.wait_for_function('!pending')
        page.wait_for_function('state.tutorial.completed')
        token=page.evaluate("localStorage.getItem('farm_token')")
        headers={'Authorization':'Bearer '+token}

        def ready():
            page.wait_for_function('!pending')
            page.wait_for_function('Array.from(document.images).every(x=>x.complete && x.naturalWidth>0)')
            page.evaluate('document.fonts.ready')

        def go(screen):
            if screen in {'farm','shop','tasks','wallet','profile'}:
                page.locator(f'#nav [data-tab="{screen}"]').click()
            elif screen in {'coop','storage'}:
                page.locator('#nav [data-tab="farm"]').click()
                page.locator(f'#farm .quick[onclick="tab(\'{screen}\')"]').click()
            else:page.evaluate('(x)=>tab(x)',screen)
            ready()

        def shot(screen):
            ready()
            page.wait_for_function("document.getElementById('toast').hidden",timeout=8000)
            page.evaluate('window.scrollTo(0,0)')
            page.screenshot(path=str(OUT/(screen+'.png')))

        def clock(value):
            with psycopg.connect(DB) as c:
                assert c.execute('UPDATE players SET last_tick=%s WHERE id=%s AND name=%s RETURNING id',(value,pid,name)).fetchone()
            page.evaluate('refresh()')

        go('farm')
        assert page.locator('#farm .quick').count()==2
        assert re.match(r'^\d\d:\d\d:\d\d$',page.locator('#farm [data-next-tick]').inner_text())
        assert '+1' in page.locator('#next-harvest').inner_text()
        assert '+2' in page.locator('#farm [data-eggs-12h]').inner_text()
        assert '18 часов' in page.locator('#warning').inner_text()
        # Let an actual timer expire. Count real /state calls, never fake API data.
        clock(time.time()-21600+2)
        page.wait_for_function('state.farm.seconds_to_next_egg <= 3')
        before=page.evaluate('state.me.eggs')
        requests=[]
        page.on('request',lambda r:requests.append(r.url) if r.url.endswith('/api/state') else None)
        page.wait_for_function('(n)=>state.me.eggs === n+1',arg=before,timeout=10000)
        page.wait_for_timeout(2100)
        assert page.evaluate('state.me.eggs')==before+1
        assert len(requests)==1,requests
        # Resume after absence: the server catches up, repeated sync does not mint twice.
        clock(time.time()-12*3600-1)
        page.wait_for_function('(n)=>state.me.eggs === n+3',arg=before)
        page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
        ready()
        assert page.evaluate('state.me.eggs')==before+3
        go('farm');shot('farm')
        go('coop')
        assert page.locator('#coop [data-eggs-6h]').inner_text()==page.locator('#farm [data-eggs-6h]').inner_text()
        shot('coop')
        page.locator('#coop-tab-incubator').click();shot('incubator')
        page.locator('#coop-tab-birds').click()
        go('storage');shot('storage')
        for filter_name in ('grain','eggs','chickens','all'):
            page.locator(f'#storage .pills button[onclick="storageFilter(\'{filter_name}\',this)"]').click()
            assert page.locator('#storage [data-storage]:visible').count()==(3 if filter_name=='all' else 1)
        go('shop');shot('trade-buy')
        page.evaluate("openSell('eggs')")
        page.get_by_role('button',name='Все',exact=True).click()
        assert int(page.locator('#sellnum').input_value())==before+3
        page.get_by_role('button',name='Выставить на продажу',exact=True).click()
        page.wait_for_function('state.my_listings.length === 1 && state.me.eggs === 0')
        if not page.locator('details.trade-listings').evaluate('(x)=>x.open'):page.locator('details.trade-listings summary').click()
        shot('trade-sell')
        page.locator('#mylist button').click()
        page.wait_for_function('(n)=>state.me.eggs === n+3',arg=before)
        go('shop')
        page.locator('#shop [onclick="showShop(\'grain\')"]').click()
        page.locator('#purchase-amount').fill('2')
        assert page.locator('#purchase-total').inner_text()=='4'
        page.set_viewport_size({'width':390,'height':500})
        page.locator('#purchase-amount').focus()
        page.locator('#purchase-confirm').scroll_into_view_if_needed()
        assert page.locator('#purchase-confirm').is_visible()
        page.locator('#purchase-confirm').click()
        page.wait_for_function('!pending && !document.getElementById("purchase-dialog").open')
        page.set_viewport_size({'width':390,'height':844})
        go('tasks');shot('tasks')
        page.locator('#achievements-switch').click()
        assert page.locator('#achievement-pane').is_visible();shot('achievements')
        page.locator('#tasks-switch').click()
        go('profile');shot('profile')
        go('wallet');shot('wallet')
        for width in (320,360,375,390,430):
            page.set_viewport_size({'width':width,'height':844})
            for screen in ('farm','coop','storage','shop','market','tasks','profile','wallet','upgrades'):
                go(screen)
                assert not page.evaluate('document.documentElement.scrollWidth > innerWidth'),(width,screen)
                controls=page.locator(f'#{screen} button:visible:not([disabled])')
                if controls.count():
                    controls.last.scroll_into_view_if_needed();page.evaluate('scrollBy(0,180)')
                    r=controls.last.bounding_box();nav=page.locator('#nav').bounding_box()
                    assert r['y']+r['height']<=nav['y']+1,(width,screen)
                layouts.append({'width':width,'screen':screen,'result':'PASS'})
        page.reload();page.wait_for_function('state !== null')
        assert page.evaluate('state.me.id')==pid
        assert not errors,errors
        assert not broken,broken
        browser.close()
    report={'result':'PASS','engine':'Chromium mobile/touch','layouts':layouts,'javascript_errors':errors,'image_errors':broken,'timer_expiry_state_requests':1,'checks':['registration/password','onboarding','forecast 6/12h','separate timers','server-only expiry','resume idempotency','identical coop forecast','storage filters','sell all','cancel restores eggs','purchase total','modal at 500px height','achievements','session reload']}
    (OUT/'browser-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='layouts'},ensure_ascii=False))
    print('Layout checks:',len(layouts))


if __name__=='__main__':main()
