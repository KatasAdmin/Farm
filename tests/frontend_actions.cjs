// Run with jsdom available: NODE_PATH=/path/to/node_modules node tests/frontend_actions.cjs
// Uses real HTML, handlers and renderer; network is stubbed, never charges accounts.
const {JSDOM,VirtualConsole}=require('jsdom');
const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),errors=[],requests=[];
const vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));
const html=fs.readFileSync(path.join(root,'index.html'),'utf8').replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi,'');
const dom=new JSDOM(html,{url:'https://farm.test',runScripts:'dangerously',virtualConsole:vc});
const w=dom.window,d=w.document;
w.scrollTo=()=>{};w.HTMLElement.prototype.scrollIntoView=()=>{};
w.HTMLDialogElement.prototype.showModal=function(){this.open=true};w.HTMLDialogElement.prototype.close=function(){this.open=false};
w.confirm=()=>true;w.open=()=>{};w.setInterval=()=>0;
w.AbortController=global.AbortController;Object.defineProperty(w.navigator,'clipboard',{value:{writeText:async()=>{}}});
const fixture={me:{id:'qa',name:'Tester',coins:10000,chickens:20,geese:2,cows:2,grain:100,eggs:177,milk:30,feathers:2,telegram_id:55,satiety:100,autobuy_amount:100,gender:'male',avatar:'default',created_at:1},buildings:{coop_capacity:1000,storage_capacity:10000,storage_used:309,cowshed_capacity:200,coop_level:4,storage_level:4,cowshed_level:1,coop_next_cost:160,storage_next_cost:120,cowshed_next_cost:50},shop:{grain:2,chickens:40,geese:160,cows:500,eggs:1,milk:11,goose_min_level:3},farm:{seconds_to_next_egg:1000,seconds_to_next_feed:60000,next_egg_scheduled:true,feed_stock_seconds:90000,eggs_next_6h:26,eggs_next_12h:52,grain_required_next_feed:30,fed_hens:20,fed_geese:2,fed_cows:2,seconds_to_next_feather:20000,next_milk_scheduled:true,seconds_to_next_milk:1000,milk_next_12h:3},promotion:{active:true,price:300,value:600,limit:5,used:0,seconds_left:600},progression:{level:4,xp:225,next_level_xp:400},tutorial:{step:0},incubator:{owned:true,level:1,capacity:3,jobs:[],next_upgrade_cost:100,incubator_price:120},weekly:{targets:{grain:10,eggs:10,listed:3},grain:10,eggs:10,listed:3,reward:30},reward_values:{bonus:2,grain:1,eggs:1,listing:1,milk:1,milk_listing:1,feather:1},daily:{grain_bought:5,eggs_produced:3,eggs_listed:1},claimed_rewards:[],market:[],my_listings:[{id:'a'.repeat(32),item:'milk',quantity:2,price:11}],top:[],available_eggs:100,available_milk:50,now:Date.now()/1000};
w.fixture=fixture;
w.fetch=async(url,options={})=>{requests.push({url,payload:options.body?JSON.parse(options.body):null});let value={ok:true,spent:11,amount:1,awarded:30,returned:1,recovery_code:'QA',url:'https://t.me/invoice-test',max_coins:1000,orders:[],entries:[],available:100,sources:{bonus:10,purchased:10,earned:100},code:'abcdef1234567890',counts:{},rates:[1000],resources:{}};if(url==='/api/state')value=JSON.parse(JSON.stringify(fixture));return {ok:true,status:200,json:async()=>value}};
const script=d.createElement('script');script.textContent=fs.readFileSync(path.join(root,'assets/game.js'),'utf8');d.body.appendChild(script);
const fieldsScript=d.createElement('script');fieldsScript.textContent=fs.readFileSync(path.join(root,'assets/fields.js'),'utf8');d.body.appendChild(fieldsScript);
const run=code=>w.eval(code),tick=()=>new Promise(r=>setImmediate(r));
const click=selector=>{const node=d.querySelector(selector);assert.ok(node,selector);assert.equal(node.disabled,false,selector+' disabled');node.click()};
function reset(){run('state=JSON.parse(JSON.stringify(window.fixture));token="qa-token";pending=false;refreshedAt=Date.now();render()');d.querySelectorAll('dialog').forEach(x=>x.close());}
(async()=>{
reset();
assert.deepEqual([...d.querySelectorAll('.bird-resources>button')].map(n=>n.querySelector('[data-value]')?.dataset.value||'storage'),['chickens','geese','cows','eggs','feathers','milk']);
for(const animal of ['chickens','geese','cows']){
 const card=d.querySelector(`[data-animal-card="${animal}"]`);assert.ok(card,animal+' card');
 const buttons=[...card.querySelectorAll('.buttons>button')];assert.equal(buttons.length,2);
 assert.equal(buttons[0].getAttribute('onclick'),`showShop('${animal}')`);
assert.equal(buttons[1].getAttribute('onclick'),`openSell('${animal}')`);
}
assert.equal(d.querySelectorAll('#farm details.forecast-card').length,1);
assert.equal(d.querySelector('.farm-footer-links'),null);
assert.ok(d.querySelector('#nearest-harvest [data-milk-card]'));
run('state.me.cows=0;state.me.geese=0;state.me.chickens=0;countdown()');
assert.equal(d.querySelector('[data-milk-card]').hidden,true);assert.equal(d.querySelector('[data-feather-card]').hidden,true);assert.equal(d.querySelector('[data-egg-forecast]').hidden,true);assert.equal(d.getElementById('harvest-empty').hidden,false);
run('state.me.cows=1;state.me.geese=1;state.me.chickens=1;countdown()');
for(const attr of ['milk-card','feather-card','egg-forecast'])assert.equal(d.querySelector('[data-'+attr+']').hidden,false);
for(const item of ['eggs','grain','chickens','geese','cows','milk','feathers'])assert.ok(d.getElementById('referral-'+item+'-claim'));
assert.equal(d.querySelector('#upgrade-coop').closest('section').id,'coop');
assert.equal(d.querySelector('#upgrade-cowshed').closest('section').id,'coop');
assert.equal(d.querySelector('#upgrade-storage').closest('section').id,'storage');
assert.equal(d.querySelectorAll('.auto-card').length,1);
assert.equal(d.querySelector('.auto-card').closest('section').id,'storage');
assert.equal(d.querySelectorAll('#upgrade-coop,#upgrade-cowshed,#upgrade-storage').length,3);
assert.equal(d.querySelector('#upgrades'),null);
run('tab("upgrades")');assert.equal(d.querySelector('.panel.active').id,'storage');
run('tab("coop");coopSection("incubator")');assert.equal(d.getElementById('coop-incubator-pane').hidden,false);assert.equal(d.getElementById('coop-birds-pane').hidden,true);
run('coopSection("birds")');assert.equal(d.getElementById('coop-birds-pane').hidden,false);
const ids=[...d.querySelectorAll('[id]')].map(x=>x.id);assert.equal(new Set(ids).size,ids.length,'duplicate IDs');
for(const item of ['eggs','milk']){
  reset();click('#'+item+'-buy-button');assert.ok(d.getElementById('purchase-dialog').open);assert.match(d.getElementById('purchase-title').textContent,item==='milk'?/молока/:/яиц/);
  assert.equal(d.getElementById('purchase-confirm').disabled,false);
  const before=requests.length;await run('confirmPurchase()');assert.ok(requests.slice(before).some(r=>r.url==='/api/buy'&&r.payload.item===item&&r.payload.amount===1));
  reset();run(`state.available_${item}=0;drawPool()`);click('#'+item+'-buy-button');assert.ok(d.getElementById('purchase-dialog').open);assert.equal(d.getElementById('purchase-confirm').disabled,true);assert.match(d.getElementById('purchase-availability').textContent,/пока нет в продаже/);
  reset();run(`openSell('${item}');sellMaximum()`);assert.equal(d.getElementById('sellitem').value,item);assert.equal(+d.getElementById('sellnum').value,fixture.me[item]);
  const start=requests.length;await run('sellNow()');assert.ok(requests.slice(start).some(r=>r.url==='/api/sell'&&r.payload.item===item));
}
for(const item of ['grain','chickens','geese','cows']){
  reset();run(`openResourceActions('${item}');resourceAction('buy')`);assert.ok(d.getElementById('purchase-dialog').open);const before=requests.length;await run('confirmPurchase()');assert.ok(requests.slice(before).some(r=>r.url==='/api/shop'&&r.payload.item===item&&r.payload.expected_price===fixture.shop[item]));
}
// Collapsed feeding panel retains the warning on its summary; level is the profile level.
reset();run('state.top=[{name:"Katas",farmer_level:8}];state.my_rank=167;state.farm.effective_grain_shortage=2;render()');
assert.match(d.getElementById('leaders').textContent,/Ур. 8/);assert.doesNotMatch(d.getElementById('leaders').textContent,/очков/);
assert.equal(d.getElementById('my-rank').textContent,'Ваше место: 167');
const feedDetails=d.getElementById('feed-details');assert.equal(feedDetails.open,false);
assert.equal(d.getElementById('feed-alert').hidden,false);assert.equal(d.getElementById('warning').hidden,false);
assert.ok(feedDetails.querySelector('#warning'));assert.ok(feedDetails.querySelector('#feed-ration'));
feedDetails.querySelector('summary').click();assert.equal(feedDetails.open,true);
run('state.farm.effective_grain_shortage=0;render()');assert.equal(d.getElementById('feed-alert').hidden,true);assert.equal(d.getElementById('warning').hidden,true);
assert.equal(feedDetails.open,true,'refresh preserves the user choice to expand');
// Exercise every declared click handler, including generated tasks/listing buttons.
reset();const handlers=[...d.querySelectorAll('[onclick]')].map(n=>({code:n.getAttribute('onclick'),id:n.id}));
for(const {code,id} of handlers){
 reset();const node=[...d.querySelectorAll('[onclick]')].find(x=>x.getAttribute('onclick')===code);if(!node)continue;
 try{const result=w.Function('event',code).call(node,new w.Event('click'));if(result?.then)await result;await tick();}catch(e){throw Error((id||code)+': '+e.stack)}
}
for(const key of ['coop','storage','cowshed']){reset();run(`state.buildings.${key}_next_cost=null;render()`);assert.equal(d.getElementById('upgrade-'+key).disabled,true)}
reset();run('state.me.coins=0;selectBuy("milk")');assert.equal(d.getElementById('purchase-confirm').disabled,true);
reset();run('state.buildings.storage_used=state.buildings.storage_capacity;selectBuy("milk")');assert.equal(d.getElementById('purchase-confirm').disabled,true);
reset();run('selectBuy("milk");el("purchase-amount").value="1.5";purchaseQuote()');assert.equal(d.getElementById('purchase-confirm').disabled,true);
reset();run('state.farm.feed_stock_seconds=3660;refreshedAt=Date.now()-120000;countdown()');assert.equal(d.getElementById('feedstock').textContent,'59 мин');
reset();run('state.farm.grain_required_next_feed=3;state.me.chickens=0;state.me.geese=0;state.me.cows=1;render()');assert.equal(d.getElementById('feed-ration').hidden,false);assert.match(d.getElementById('feed-ration').textContent,/3/);
reset();run('state.me.autobuy_enabled=true;state.me.grain=0;state.me.autobuy_amount=1;render()');assert.match(d.querySelector('[data-auto-status]').textContent,/не хватит ещё 29 зерна/);
await tick();assert.deepEqual(errors,[]);console.log(`OK: ${handlers.length} click handlers; milk/egg buy+sell, all animals/feed, empty market, balance/storage/quantity limits, level caps, DOM IDs.`);dom.window.close();
})().catch(e=>{console.error(e);dom.window.close();process.exitCode=1});
