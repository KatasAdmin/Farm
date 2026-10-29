"""v29 PostgreSQL integration tests. Refuses every database except the existing
local farm_visual_regression_test on :5543. Never resets/deletes data. Fixtures
modify only freshly created qa_ accounts; fixture credits are explicitly added
to the local test reward ledger. No production credentials are used.
"""
import hashlib
import hmac
import json
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode, urlparse

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row
import main


@pytest.fixture(scope='module')
def client():
    url=os.getenv('FARM_VISUAL_TEST_DATABASE_URL')
    if not url:
        pytest.skip('Dedicated local PostgreSQL required')
    parsed=urlparse(url)
    assert parsed.hostname in {'127.0.0.1','localhost'} and parsed.port==5543
    assert parsed.path=='/farm_visual_regression_test'
    original=os.environ.get('DATABASE_URL')
    os.environ['DATABASE_URL']=url
    with TestClient(main.app) as c:
        yield c
    if original is None:os.environ.pop('DATABASE_URL',None)
    else:os.environ['DATABASE_URL']=original


def sql(query,args=()):
    with psycopg.connect(os.environ['DATABASE_URL'],row_factory=dict_row) as c:
        result=c.execute(query,args)
        return result.fetchall() if result.description else []


def state(c,h):
    r=c.get('/api/state',headers=h)
    assert r.status_code==200,r.text
    return r.json()


def post(c,h,path,data=None):
    r=c.post(path,headers=h,json=data or {})
    assert r.status_code==200,r.text
    return r.json()


def account(c,credit=0):
    name='qa29_'+uuid.uuid4().hex[:12]
    r=c.post('/api/join',json={'name':name,'password':'QaFarmPass29!'})
    assert r.status_code==200,r.text
    h={'Authorization':'Bearer '+r.json()['token']}
    p=state(c,h)['me']
    if credit:
        with psycopg.connect(os.environ['DATABASE_URL']) as db:
            assert db.execute('UPDATE players SET coins=coins+%s WHERE id=%s AND name=%s RETURNING id',(credit,p['id'],name)).fetchone()
            db.execute('UPDATE reward_emission SET total_minted=total_minted+%s WHERE id=1',(credit,))
    return h


def fixture(c,h,**values):
    p=state(c,h)['me']
    assert p['name'].startswith('qa29_')
    allowed={'chickens','grain','eggs','fed_hens','feed_phase','satiety','last_tick','created_at','bundle_uses','coop_level','storage_level','incubator_level'}
    assert values.keys()<=allowed
    sql('UPDATE players SET '+','.join(k+'=%s' for k in values)+' WHERE id=%s AND name=%s',tuple(values.values())+(p['id'],p['name']))
    return p


def signed(uid):
    fields={'auth_date':str(int(time.time())),'user':json.dumps({'id':uid})}
    check='\n'.join(k+'='+v for k,v in sorted(fields.items()))
    secret=hmac.new(b'WebAppData',b'qa29-only-bot',hashlib.sha256).digest()
    fields['hash']=hmac.new(secret,check.encode(),hashlib.sha256).hexdigest()
    return urlencode(fields)


def test_start_resources_login_and_secret_redaction(client):
    h=account(client)
    s=state(client,h)
    assert [s['me'][k] for k in ('coins','chickens','grain','eggs')]==[10,1,5,0]
    assert not {'token','password_hash','recovery_hash'} & s['me'].keys()
    name=s['me']['name']
    r=post(client,{},'/api/login',{'name':name,'password':'QaFarmPass29!'})
    restored=state(client,{'Authorization':'Bearer '+r['token']})
    assert restored['me']['id']==s['me']['id']
    assert restored['me']['coins']==10
    assert client.get('/api/state',headers=h).status_code==401
    assert client.post('/api/join',json={'name':name.upper(),'password':'QaFarmPass29!'}).status_code==409


def test_health_no_duplicate_routes(client):
    assert client.get('/health').json()=={'ok':True}
    routes=[(m,r.path) for r in main.app.routes for m in getattr(r,'methods',[])]
    assert len(routes)==len(set(routes))


@pytest.mark.parametrize('hens,grain,fed,phase,eggs,auto,credit',[
    (1,5,1,0,0,False,0),(5,30,5,0,0,False,0),
    (5,2,5,2,0,False,0),(1,0,1,2,0,False,0),
    (0,5,0,0,0,False,0),(1,1,1,2,99,False,0),
    (5,0,5,2,0,True,100),(5,0,5,2,0,False,100),
    (5,2,2,2,0,True,0),(1,0,1,2,80,True,100),
])
def test_forecast_matches_real_database_production(client,hens,grain,fed,phase,eggs,auto,credit):
    h=account(client,credit)
    fixture(client,h,chickens=hens,grain=grain,fed_hens=fed,feed_phase=phase,eggs=eggs,last_tick=time.time()-100)
    post(client,h,'/api/autobuy',{'item':'on' if auto else 'off','amount':20})
    s=state(client,h)
    for hours in (6,12):
        # Do not persist the first horizon: each horizon starts from identical data.
        with psycopg.connect(os.environ['DATABASE_URL'],row_factory=dict_row) as db:
            p=main.person(db,h['Authorization'],True)
            actual=main.advance(db,p,s['now']+hours*3600)
            assert actual['eggs']-s['me']['eggs']==s['farm'][f'eggs_next_{hours}h']
            db.rollback()
    assert state(client,h)['me']['eggs']==s['me']['eggs']


def test_production_return_and_no_double_credit(client):
    h=account(client)
    fixture(client,h,last_tick=time.time()-13*3600)
    a=state(client,h)
    assert a['me']['eggs']==2
    assert a['me']['grain']==5
    assert state(client,h)['me']['eggs']==2
    assert a['farm']['seconds_to_next_feed']>0


def test_shop_capacity_prices_and_failed_operations_preserve_resources(client):
    h=account(client,100)
    before=state(client,h)
    post(client,h,'/api/shop',{'item':'chickens','amount':1,'price':1})
    after=state(client,h)
    assert after['me']['coins']==before['me']['coins']-40
    for path,payload in [('/api/shop',{'item':'grain','amount':1000}),('/api/sell',{'item':'eggs','amount':500}),('/api/shop',{'item':'grain','amount':-1}),('/api/shop',{'item':'eggs','amount':1})]:
        assert client.post(path,headers=h,json=payload).status_code==400
    again=state(client,h)
    assert [again['me'][k] for k in ('coins','grain','eggs','chickens')]==[after['me'][k] for k in ('coins','grain','eggs','chickens')]


def test_market_proportional_sales_and_self_exclusion(client):
    sellers=[account(client) for _ in range(2)]
    buyer=account(client)
    for h,q in zip(sellers,(2,4)):
        fixture(client,h,eggs=q)
        post(client,h,'/api/sell',{'item':'eggs','amount':q,'price':999})
    before=[state(client,h) for h in sellers]
    post(client,buyer,'/api/buy',{'item':'eggs','amount':3,'price':0})
    after=[state(client,h) for h in sellers]
    assert [a['me']['coins']-b['me']['coins'] for a,b in zip(after,before)]==[1,2]
    assert state(client,buyer)['me']['coins']==7
    assert all(a['my_listings'][0]['price']==1 for a in after)
    for h,s in zip(sellers,after):
        post(client,h,'/api/cancel/'+s['my_listings'][0]['id'])
    own=account(client)
    fixture(client,own,eggs=1)
    post(client,own,'/api/sell',{'item':'eggs','amount':1})
    mine=state(client,own)
    assert mine['available_eggs']==0
    assert client.post('/api/buy',headers=own,json={'item':'eggs','amount':1}).status_code==400
    assert client.post('/api/cancel/'+mine['my_listings'][0]['id'],headers=buyer,json={}).status_code==404
    post(client,own,'/api/cancel/'+mine['my_listings'][0]['id'])
    assert state(client,own)['me']['eggs']==1


def test_concurrent_reward_and_purchase_are_serialized(client):
    h=account(client)
    with ThreadPoolExecutor(2) as pool:
        responses=list(pool.map(lambda _:client.post('/api/claim',headers=h,json={'item':'bonus'}),range(2)))
    assert sorted(r.status_code for r in responses)==[200,409]
    assert state(client,h)['me']['coins']==12
    with ThreadPoolExecutor(2) as pool:
        responses=list(pool.map(lambda _:client.post('/api/shop',headers=h,json={'item':'grain','amount':5}),range(2)))
    assert sorted(r.status_code for r in responses)==[200,400]
    assert state(client,h)['me']['coins']==2
    assert state(client,h)['me']['grain']==10


def test_tasks_achievements_and_profile_save(client):
    h=account(client)
    post(client,h,'/api/shop',{'item':'grain','amount':5})
    post(client,h,'/api/claim',{'item':'grain'})
    fixture(client,h,last_tick=time.time()-12*21600-1)
    s=state(client,h)
    assert 'first_egg' in s['progression']['achievements']
    assert s['progression']['xp']>0
    post(client,h,'/api/claim',{'item':'eggs'})
    assert client.post('/api/claim',headers=h,json={'item':'eggs'}).status_code==409
    post(client,h,'/api/profile',{'gender':'female','age':29,'avatar':'chicken'})
    p=state(client,h)['me']
    assert (p['gender'],p['age'],p['avatar'])==('female',29,'chicken')


def test_incubator_no_early_hen_and_full_coop_wait(client):
    h=account(client,300)
    fixture(client,h,eggs=12)
    post(client,h,'/api/incubator',{'item':'buy'})
    post(client,h,'/api/incubator',{'item':'start','amount':1})
    s=state(client,h)
    job=s['incubator']['jobs'][0]
    assert s['me']['chickens']==1 and s['me']['eggs']==0
    assert client.post('/api/incubator',headers=h,json={'item':'start'}).status_code==409
    sql('UPDATE incubation_jobs SET hatch_at=%s,mature_at=%s WHERE id=%s AND player_id=%s',(time.time()-1,time.time()+60,job['id'],s['me']['id']))
    assert state(client,h)['me']['chickens']==1
    fixture(client,h,chickens=10,fed_hens=1)
    sql('UPDATE incubation_jobs SET mature_at=%s WHERE id=%s AND player_id=%s',(time.time()-1,job['id'],s['me']['id']))
    waiting=state(client,h)
    assert waiting['me']['chickens']==10 and waiting['incubator']['active']==1
    post(client,h,'/api/upgrade',{'item':'coop'})
    done=state(client,h)
    assert done['me']['chickens']==11 and done['incubator']['active']==0
    assert state(client,h)['me']['chickens']==11


def test_promotion_contents_limits_and_expiry(client):
    h=account(client,600)
    before=state(client,h)
    post(client,h,'/api/bundle')
    after=state(client,h)
    assert after['me']['coins']==before['me']['coins']-300
    assert after['me']['chickens']==11 and after['me']['grain']==105
    assert after['promotion']['value']==600
    fixture(client,h,bundle_uses=5)
    assert client.post('/api/bundle',headers=h,json={}).json()['detail']=='Акция завершена'
    fixture(client,h,bundle_uses=0,created_at=time.time()-72*3600-1)
    assert client.post('/api/bundle',headers=h,json={}).json()['detail']=='Акция завершена'
    assert state(client,h)['me']['coins']==after['me']['coins']


def test_telegram_both_link_directions_and_rejection(client,monkeypatch):
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN','qa29-only-bot')
    uid=int(uuid.uuid4().int%1000000000)+9000000000
    h=account(client)
    initial=state(client,h)['me']['id']
    post(client,h,'/api/telegram/link',{'telegram_data':signed(uid)})
    token=post(client,{},'/api/telegram/login',{'telegram_data':signed(uid)})['token']
    assert state(client,{'Authorization':'Bearer '+token})['me']['id']==initial
    outsider=account(client)
    assert client.post('/api/telegram/link',headers=outsider,json={'telegram_data':signed(uid)}).status_code==409
    assert client.post('/api/telegram/login',json={'telegram_data':signed(uid)+'bad'}).status_code==401
    uid+=1
    token=post(client,{},'/api/telegram/login',{'telegram_data':signed(uid)})['token']
    th={'Authorization':'Bearer '+token}
    telegram_id=state(client,th)['me']['id']
    name='qa29_'+uuid.uuid4().hex[:12]
    post(client,th,'/api/nickname/set',{'name':name})
    post(client,th,'/api/password/set',{'password':'QaFarmPass29!'})
    token=post(client,{},'/api/login',{'name':name,'password':'QaFarmPass29!'})['token']
    assert state(client,{'Authorization':'Bearer '+token})['me']['id']==telegram_id


def test_wallet_ownership_and_concurrent_manual_requests(client,monkeypatch):
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN','qa29-only-bot')
    h=account(client,200)
    uid=int(uuid.uuid4().int%1000000000)+11000000000
    post(client,h,'/api/telegram/link',{'telegram_data':signed(uid)})
    with ThreadPoolExecutor(2) as pool:
        responses=list(pool.map(lambda _:client.post('/api/withdraw/request',headers=h,json={'amount':100}),range(2)))
    assert sorted(r.status_code for r in responses)==[200,409]
    status=client.get('/api/withdraw/status',headers=h).json()
    assert status['payouts_enabled'] is False and status['request']['status']=='pending'
    assert state(client,h)['me']['coins']==210
    other=account(client)
    assert client.get('/api/withdraw/status',headers=other).json()['request'] is None
    assert client.get('/api/finance',headers=other).json()['entries']==[]


def test_concurrent_promotion_limit_is_server_enforced(client):
    h=account(client,600)
    fixture(client,h,bundle_uses=4)
    with ThreadPoolExecutor(2) as pool:
        responses=list(pool.map(lambda _:client.post('/api/bundle',headers=h,json={}),range(2)))
    assert sorted(r.status_code for r in responses)==[200,400]
    after=state(client,h)
    assert after['promotion']['used']==5
    assert after['me']['coins']==310 and after['me']['chickens']==11
