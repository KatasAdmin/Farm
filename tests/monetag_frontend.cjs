// Mock AdsGram Reward URL frontend. No real impressions or payout credits.
const {JSDOM}=require('jsdom');
const fs=require('fs'),assert=require('node:assert/strict');
const source=fs.readFileSync('assets/monetag-rewards.js','utf8');
const tick=()=>new Promise(resolve=>setImmediate(resolve));

async function scenario(configured=true, fail=false){
 const dom=new JSDOM('<p id="warning"></p><section id="shop"><div class="product"><div class="trade-dual-actions"><button onclick="showShop(\'milk\')">Купить молоко</button></div></div></section><section id="coop"><div data-animal-card="cows"><div class="buttons"><button onclick="showShop(\'cows\')">Купить корову</button></div></div></section><section id="wallet"><button id="harvest-ad-eggs" data-ad-free="eggs" hidden>Eggs</button><button id="harvest-ad-milk" data-ad-free="milk" hidden>Milk</button></section><dialog id="purchase-dialog"></dialog>',{url:'https://farm.test',runScripts:'outside-only'});
 const w=dom.window,requests=[],notifications=[];let shows=0,confirmed=false;
 w.Telegram={WebApp:{initDataUnsafe:{user:{id:12345}}}};
 w.setInterval=()=>0;
 w.setTimeout=(f)=>{Promise.resolve().then(f);return 0;};
 const cfg={enabled:configured,adsgram_block_id:'mock-adsgram',rewards:{grain:{progress:0},eggs:{progress:0},milk:{progress:3},cows:{progress:0}},history:[],granted:[]};
 w.api=async(path,payload,headers)=>{
  requests.push({path,payload,headers});
  if(path.endsWith('/status'))return {...cfg,history:confirmed?[{ymid:'mock-id',item:'milk',created_at:1,state:'credited'}]:[]};
  if(path.endsWith('/prepare'))return {attempt_id:'mock-id'};
  return {ok:true};
 };
 w.FarmAdsgramFallback={show:async()=>{shows++;if(fail)throw Error('SDK unavailable');confirmed=true;}};
 w.toast=message=>notifications.push(message);w.refresh=async()=>{};w.el=id=>w.document.getElementById(id);
 w.eval("var token='token',pending=false,selectedResource='grain',purchase={item:'milk',kind:'market'},state={me:{telegram_id:12345},farm:{effective_grain_shortage:2}},adProgress={},adRewards={grain:[1,2],eggs:[2,2],milk:[5,1],cows:[250,1],coins:[1,2]};function tgInitData(){return 'signed-data';}");
 w.eval(source);await tick();await tick();
 assert.ok(w.document.querySelector('#shop [data-ad-free="milk"]'));
 assert.ok(w.document.querySelector('#coop [data-ad-free="cows"]'));
 assert.equal(w.document.getElementById('harvest-ad-eggs').hidden,!configured);
 assert.equal(w.document.getElementById('harvest-ad-milk').hidden,!configured);
 // The current confirmed-goods reward flow intentionally does not mint cash coins.
 assert.equal(w.document.querySelector('[data-ad-free="coins"]'),null);
 assert.ok(w.document.getElementById('free-grain-shortage'));
 assert.ok(w.document.getElementById('ad-history'));
 if(configured){
  await w.FarmAds.watch('milk');
  assert.equal(shows,1);
  assert.ok(requests.some(r=>r.path.endsWith('/prepare')&&r.payload.item==='milk'));
  assert.ok(requests.some(r=>r.path.endsWith('/status')&&r.headers['X-Telegram-Init-Data']==='signed-data'));
  if(fail)assert.ok(notifications.some(x=>x.includes('SDK unavailable')));
  else assert.ok(notifications.some(x=>x.includes('подтверждён')));
 }else{
  await w.FarmAds.watch('milk');
  assert.equal(shows,0,'Disabled ad provider cannot show an ad');
 }
 dom.window.close();
}
(async()=>{await scenario(true,false);await scenario(true,true);await scenario(false,false);console.log('3 AdsGram mock scenarios passed: verified-goods UI, SDK error, disabled provider.');})().catch(e=>{console.error(e);process.exitCode=1;});
