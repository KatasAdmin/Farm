// Mock SDK only: no network, no real impressions, no production accounts.
const {JSDOM}=require('jsdom');
const fs=require('fs'),assert=require('node:assert/strict');
const source=fs.readFileSync('assets/monetag-rewards.js','utf8');
const tick=()=>new Promise(r=>setImmediate(r));
async function scenario(result,configured=true){
 const dom=new JSDOM(`<div><p id="warning"></p></div><section id="shop"><div class="product"><div class="trade-dual-actions"><button onclick="showShop('milk')">Buy</button></div></div></section><section id="wallet"></section><button id="incubator-action">Buy incubator</button><dialog id="purchase-dialog"></dialog>`,{url:'https://farm.test',runScripts:'outside-only'});
 const w=dom.window,calls=[],notes=[];let sdkCalls=0,credited=false;
 w.setInterval=()=>0;
 const cfg={enabled:configured,zone_id:12193261,sdk_url:'https://libtl.com/sdk.js',remaining_today:40,remaining_hour:10,retry_after:0,rewards:{grain:{progress:0},eggs:{progress:0},milk:{progress:3},chickens:{progress:0}},history:[],granted:[]};
 w.api=async(path,payload,headers)=>{calls.push({path,payload,headers});if(path.endsWith('/status'))return {...cfg,history:credited?[{ymid:'mock-milk',item:'milk',created_at:1,state:'credited'}]:[]};if(path.endsWith('/prepare'))return {ymid:'mock-'+payload.item,zone_id:12193261,expires_at:Date.now()/1000+600};if(payload?.event==='completed'&&result==='paid'){credited=true;}return {ok:true};};
 w.show_12193261=options=>{sdkCalls++;calls.push({sdk:options});if(result==='error')return Promise.reject(Error('SDK unavailable'));return Promise.resolve(result==='undefined'?undefined:{reward_event_type:'valued'});};
 w.toast=x=>notes.push(x);w.refresh=async()=>{};w.el=id=>w.document.getElementById(id);
 w.eval(`var token='test-account',pending=false,selectedResource='grain',purchase={item:'milk',kind:'buy'},state={farm:{effective_grain_shortage:2}},adProgress={},adRewards={grain:[1,2],eggs:[2,2],milk:[5,1],chickens:[20,1],geese:[80,1],cows:[250,1],coins:[1,2]}; function tgInitData(){return 'signed-telegram-data';}`);
 w.eval(source);await tick();await tick();
 const milk=w.document.querySelector('#shop [data-ad-free="milk"]');assert.ok(milk);assert.equal(milk.disabled,!configured);
 assert.ok(w.document.getElementById('free-grain-shortage'));assert.ok(w.document.getElementById('ad-history'));assert.equal(w.document.querySelector('#incubator-action + [data-ad-free]').dataset.adFree,'coins');assert.equal(w.document.querySelectorAll('[data-ad-free=feathers]').length,0);
 if(configured){
  const before=calls.length;milk.click();assert.equal(sdkCalls,1,'SDK executes in original click, before any await');assert.ok(calls[before].sdk,'SDK must be first action');
  await tick();await tick();
  const sdk=calls.find(x=>x.sdk).sdk;assert.equal(sdk.type,'pop');assert.equal(sdk.requestVar,'milk_reward');assert.equal(sdk.ymid,'mock-milk');
  assert.ok(calls.some(x=>x.payload?.event==='started'));assert.ok(calls.every(x=>x.sdk||x.headers['X-Telegram-Init-Data']==='signed-telegram-data'));
  if(result==='error')assert.ok(calls.some(x=>x.payload?.event==='failed'));
  else assert.ok(calls.some(x=>x.payload?.event==='completed'));
  if(result==='paid')assert.ok(notes.some(x=>x.includes('3/5')));
  if(result==='undefined')assert.ok(calls.some(x=>x.payload?.event==='completed'&&x.payload.result===''));
  // Purchase dialog's dynamic button must use its current item, not captured grain.
  w.eval(`purchase.item='eggs'`);w.document.getElementById('purchase-dialog').setAttribute('open','');await tick();
  assert.equal(w.document.getElementById('purchase-ad-free').dataset.adFree,'eggs');
 }else assert.equal(sdkCalls,0,'Unconfigured browser must never reuse TMA zone');
 dom.window.close();
}
(async()=>{for(const result of ['paid','undefined','error'])await scenario(result);await scenario('undefined',false);console.log('4 mock SDK scenarios passed: gesture, progress, failure, unconfigured zone; dynamic buttons and auth headers verified.');})().catch(e=>{console.error(e);process.exitCode=1;});
