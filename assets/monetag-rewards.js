/* Monetag SDK callbacks are telemetry only. Rewards come from authenticated postbacks. */
(()=>{
'use strict';
let cfg=null,owner='',working=false,recovering=null,lastRecover=0,sdkZone=null,adsgramController=null,adsgramBlock=null,cooldownUntil=0;
const prepared=new Map(),timers=new Set();
const labels={grain:'зерно',eggs:'яйца',milk:'молоко',chickens:'курицу',geese:'гусыню',cows:'корову',coins:'монеты для покупок'};
const states={test_completed:'Тестовый просмотр завершён',test_pending:'Тестовый просмотр запущен',test_no_fill:'Нет рекламы для показа',test_skipped:'Тестовая реклама пропущена',test_sdk_error:'Ошибка AdsGram',test_timeout:'Истекло время теста',pending:'Ожидается подтверждение Monetag',unconfirmed:'Подтверждение не получено. Попытка сохранена в истории',non_valued:'Событие сохранено. Для награды нужен подтверждённый показ',sdk_error:'Реклама недоступна, попробуйте позже',rate_limited:'Лимит рекламы, попробуйте позже'};
const contextKey=()=>String(token||'')+'|'+(tgInitData()?'telegram':'web');
const adApi=(path,payload)=>api('/api/ads/'+path,payload,tgInitData()?{'X-Telegram-Init-Data':tgInitData()}:{});
const safeReport=(ymid,event,extra={})=>adApi('monetag/event',{ymid,event,...extra});
function notify(message){toast(message);const node=el('ad-inline-status');if(node)node.textContent=message;}
function itemButton(item){
 const button=document.createElement('button');button.type='button';button.className='btn alt small ad-free-button';button.dataset.adFree=item;
 button.addEventListener('click',()=>watch(button.dataset.adFree));return button;
}
function decorate(){
 if(!cfg?.visible)return;
 // Advertising purchasing credit can pay for any existing purchase or upgrade.
 document.querySelectorAll('[onclick]').forEach(b=>{if(!(b.getAttribute('onclick')||'').startsWith('upgradeBuilding(')&&!['incubator-action','incubator-upgrade','bundle-buy'].includes(b.id))return;if(!b.nextElementSibling?.matches('[data-ad-free="coins"]'))b.insertAdjacentElement('afterend',itemButton('coins'));});

 document.querySelectorAll('[data-ad-progress]').forEach(n=>n.textContent=(adProgress[n.dataset.adProgress]||0)+'/'+(adRewards[n.dataset.adProgress]?.[0]||1));
 const rp=el('resource-action-ad-progress');if(rp&&adRewards[selectedResource])rp.textContent=(adProgress[selectedResource]||0)+'/'+adRewards[selectedResource][0]+' подтверждённых просмотров';
 document.querySelectorAll('#shop .product,#coop [data-animal-card]').forEach(card=>{
  const buy=[...card.querySelectorAll('[onclick]')].map(n=>(n.getAttribute('onclick')||'').match(/(?:showShop|selectBuy)\('([a-z]+)'\)/)).find(m=>m&&adRewards[m[1]]);
  if(buy&&!card.querySelector('[data-ad-free="'+buy[1]+'"]'))(card.querySelector('.trade-dual-actions,.buttons')||card).appendChild(itemButton(buy[1]));
 });
 const warning=el('warning');
 if(warning&&!el('free-grain-shortage')){const button=itemButton('grain');button.id='free-grain-shortage';warning.insertAdjacentElement('afterend',button);}
 if(!el('ad-inline-status')&&warning){const node=document.createElement('p');node.id='ad-inline-status';node.className='muted';node.setAttribute('role','status');warning.parentElement.appendChild(node);}
 const resource=el('resource-action-free');if(resource){resource.dataset.adFree=adRewards[selectedResource]?selectedResource:'grain';}
 const purchaseDialog=el('purchase-dialog');
 if(purchaseDialog&&!el('purchase-ad-free')){const button=itemButton('grain');button.id='purchase-ad-free';purchaseDialog.appendChild(button);}
 const purchaseFree=el('purchase-ad-free');
 if(purchaseFree){const item=purchase?.item;purchaseFree.hidden=false;purchaseFree.dataset.adFree=purchase?.kind==='bundle'?'coins':adRewards[item]?item:'coins';}
 const shortage=el('free-grain-shortage');if(shortage)shortage.hidden=!(state?.farm?.effective_grain_shortage>0);
 document.querySelectorAll('[data-ad-free]').forEach(button=>{
  const item=button.dataset.adFree;const r=adRewards[item];if(!r)return;
  const test=cfg.provider==='adsgram';
  const sdkReady=test?!!adsgramController:typeof window['show_'+cfg.zone_id]==='function';
  const reason=!cfg?.enabled?(cfg?.reason||'Реклама недоступна'):working?'Реклама открывается':pending?'Дождитесь завершения действия':cfg?.remaining_today===0?'Дневной лимит '+cfg.daily_limit+'/'+cfg.daily_limit:cfg?.remaining_hour===0?'Часовой лимит 10/10':cfg?.retry_after?'Следующая реклама через '+cfg.retry_after+' сек':!sdkReady?'Загружается реклама':!test&&!prepared.has(item)?'Подготавливаем рекламу':'';
  button.disabled=!!reason;
  button.title=reason||(test?'Тестовый просмотр без начислений':'Награда: '+r[1]+' '+labels[item]+' за '+r[0]+' подтверждённых просмотров');
  const compactReason=reason?.includes('rewarded-зона')?'Скоро':reason?.includes('лимит')||reason?.includes('Лимит')?'Лимит':reason?.includes('через')?'Таймер':reason?.includes('Загружается')?'Загрузка':reason?.includes('открывается')?'Открывается':reason?.includes('Дождитесь')?'Ожидание':reason?'Недоступно':'';
  button.textContent=reason?'🎬 '+compactReason:test?'🎬 Тест AdsGram':item==='coins'?'🎬 +2 монеты':'🎬 Бесплатно · '+(adProgress[item]||0)+'/'+r[0];
 });
}
async function sdk(config){
 if(typeof window['show_'+config.zone_id]==='function'){sdkZone=config.zone_id;return;}
 if(sdkZone===config.zone_id)return;
 sdkZone=config.zone_id;
 await new Promise((resolve,reject)=>{
  const script=document.createElement('script');script.src=config.sdk_url;script.dataset.zone=String(config.zone_id);script.dataset.sdk='show_'+config.zone_id;
  const timeout=setTimeout(()=>{sdkZone=null;script.remove();reject(Error('Реклама недоступна, попробуйте позже'));},10000);
  script.onload=()=>{clearTimeout(timeout);if(typeof window['show_'+config.zone_id]==='function')resolve();else{sdkZone=null;reject(Error('SDK рекламы не загрузился'));}};
  script.onerror=()=>{clearTimeout(timeout);sdkZone=null;script.remove();reject(Error('Реклама недоступна, попробуйте позже'));};document.head.appendChild(script);
 });
}
async function loadAdsGram(config){
 if(adsgramController&&adsgramBlock===config.block_id)return;
 if(!window.Adsgram?.init){
  await new Promise((resolve,reject)=>{
   const script=document.createElement('script');script.src=config.sdk_url;
   const failed=()=>{clearTimeout(timer);script.remove();reject(Error('SDK AdsGram не загрузился'));};
   const timer=setTimeout(failed,10000);
   script.onload=()=>{clearTimeout(timer);resolve();};script.onerror=failed;
   document.head.appendChild(script);
  });
 }
 if(!window.Adsgram?.init)throw Error('SDK AdsGram не загрузился');
 adsgramController=window.Adsgram.init({blockId:config.block_id,debug:true,debugConsole:false,debugBannerType:'RewardedVideo'});
 adsgramBlock=config.block_id;
}
async function reserve(){
 if(!cfg?.enabled||cfg.retry_after||!cfg.remaining_today||!cfg.remaining_hour)return;
 const session=owner;
 await Promise.all(Object.keys(adRewards).map(async item=>{
  if(prepared.get(item)?.expires_at>Date.now()/1000+20)return;
  prepared.delete(item);
  try{const value=await adApi('monetag/prepare',{item});if(owner===session)prepared.set(item,value);}catch(_){}
 }));decorate();
}
function historyUI(data){
 let holder=el('ad-history');
 if(!holder){const wallet=el('wallet');if(!wallet)return;holder=document.createElement('details');holder.id='ad-history';holder.className='card';const title=document.createElement('summary');title.textContent='🎬 История рекламы';holder.appendChild(title);const note=document.createElement('p');note.className='muted';note.textContent='Рекламные товары и доход от них — только для покупок, без вывода.';holder.appendChild(note);const body=document.createElement('div');body.className='ad-history-rows';holder.appendChild(body);wallet.appendChild(holder);}
 const body=holder.querySelector('.ad-history-rows');body.replaceChildren();
 (data.history||[]).forEach(row=>{const node=document.createElement('p');node.className='muted';node.textContent=new Date(row.created_at*1000).toLocaleString('ru-RU')+' · '+(labels[row.item]||row.item)+' · '+(row.state==='credited'?(row.reward_quantity?(row.reward_claimed?'Награда получена':'Награда сохранена, нужно свободное место'):'Просмотр засчитан'):states[row.state]||row.state);body.appendChild(node);});
 if(!data.history?.length){const node=document.createElement('p');node.textContent='Пока нет запусков рекламы';body.appendChild(node);}
}
async function recover(force=false){
 if(!token)return;
 if(recovering)return recovering;
 if(!force&&Date.now()-lastRecover<15000){decorate();return;}
 lastRecover=Date.now();
 const session=contextKey();if(owner!==session){owner=session;prepared.clear();cfg=null;}
 recovering=(async()=>{
  try{
   const data=await adApi('status');if(owner!==session)return;
   if(cfg?.provider!==data.provider)prepared.clear();
   cfg=data;
   const paused=el('rewarded-ads-ui-paused');if(paused)paused.media=data.visible?'not all':'all';
   if(!data.visible)return;
   cooldownUntil=Date.now()+Math.max(0,Number(data.retry_after)||0)*1000;if(!data.enabled){const note=el('ad-inline-status');if(note)note.textContent=data.reason||'Рекламные награды пока настраиваются';}
   adProgress=Object.fromEntries(Object.entries(data.rewards||{}).map(([k,v])=>[k,v.progress]));
   historyUI(data);const wallet=el('wallet');if(wallet&&!el('ad-purchase-credit')){const b=itemButton('coins');b.id='ad-purchase-credit';wallet.prepend(b);}decorate();
   if(data.granted?.length){notify('Награда получена');await refresh();}
   if(data.pending)notify('Награда сохранена. Освободите место на складе или для птицы');
   if(data.enabled){try{if(data.provider==='adsgram')await loadAdsGram(data);else{await sdk(data);await reserve();}}catch(error){notify(error.message);}}
  }catch(error){if(force)notify(error.message);}finally{recovering=null;decorate();}
 })();return recovering;
}
function schedulePoll(ymid,item,deadline){
 const timer=setTimeout(async()=>{
  timers.delete(timer);if(!token)return;
  try{
   await recover(true);const data=cfg;const row=data?.history?.find(r=>r.ymid===ymid);
   if(row?.state==='credited'){
    notify(row.reward_quantity?(row.reward_claimed?'Награда получена':'Награда сохранена. Нужно свободное место'):'Просмотр засчитан: '+(adProgress[item]||0)+'/'+adRewards[item][0]);return;
   }
   if(row?.state&&row.state!=='pending'){notify(states[row.state]||'Попытка сохранена в истории');return;}
   if(Date.now()<deadline)schedulePoll(ymid,item,deadline);
   else notify(states.unconfirmed);
  }catch(_){notify('Не удалось проверить результат. Попытка сохранена на сервере');}
 },5000);timers.add(timer);
}
async function watchAdsGram(item){
 if(!adsgramController)return;
 working=true;decorate();
 const session=owner,controller=adsgramController;
 let attempt,timer,result='sdk_error';
 const noFill=()=>{result='no_fill';};
 const skipped=()=>{result='skipped';};
 try{
  attempt=await adApi('adsgram/start',{item});
  if(owner!==session||contextKey()!==session)return;
  controller.addEventListener('onBannerNotFound',noFill);
  controller.addEventListener('onSkip',skipped);
  const answer=await Promise.race([
   controller.show(),
   new Promise((_,reject)=>{timer=setTimeout(()=>{result='timeout';reject(Error('timeout'));},90000);})
  ]);
  if(answer?.done&&!answer.error)result='completed';
 }catch(error){
  if(!attempt)notify(error.message||'Реклама недоступна, попробуйте позже');
 }finally{
  clearTimeout(timer);
  controller.removeEventListener('onBannerNotFound',noFill);
  controller.removeEventListener('onSkip',skipped);
  if(result==='timeout')controller.destroy();
  if(attempt&&owner===session&&contextKey()===session){
   try{await adApi('adsgram/finish',{ymid:attempt.ymid,result});notify(states['test_'+result]);}
   catch(_){notify('Не удалось сохранить результат теста');}
   await recover(true);
  }
  working=false;decorate();
 }
}
async function watch(item){
 if(working||pending||!adRewards[item])return;
 if(owner!==contextKey()){prepared.clear();recover(true);notify('Обновляем настройки рекламы');return;}
 if(cfg?.retry_after||cfg?.remaining_today===0||cfg?.remaining_hour===0){notify('Лимит рекламы, попробуйте позже');recover(true);return;}
 if(!cfg?.visible||!cfg.enabled)return;
 if(cfg.provider==='adsgram')return watchAdsGram(item);
 const attempt=prepared.get(item);
 if(!attempt||attempt.expires_at<=Date.now()/1000||!cfg?.enabled){notify(cfg?.reason||'Реклама подготавливается. Попробуйте через несколько секунд');recover(true);return;}
 const show=window['show_'+attempt.zone_id];if(typeof show!=='function'){notify('Реклама недоступна, попробуйте позже');return;}
 working=true;prepared.delete(item);decorate();
 const session=owner;let promise;
 try{
  // Keep the SDK call synchronous with the user's tap. All network preparation
  // happened beforehand. Do not replace advertiser URLs or await before show().
  promise=show({type:'pop',ymid:attempt.ymid,requestVar:item+'_reward'});
  const started=safeReport(attempt.ymid,'started').catch(()=>null);
  let sdkTimeout;let result;try{result=await Promise.race([promise,new Promise((_,reject)=>{sdkTimeout=setTimeout(()=>reject(Error('Failed to verify the ad show')),45000);})]);}finally{clearTimeout(sdkTimeout);}if(owner!==session)return;
  await started;
  await safeReport(attempt.ymid,'completed',{result:result?.reward_event_type||''});
  await recover(true);
  const row=cfg?.history?.find(r=>r.ymid===attempt.ymid);
  if(row?.state==='credited')notify(row.reward_quantity?(row.reward_claimed?'Награда получена':'Награда сохранена. Нужно свободное место'):'Просмотр засчитан: '+(adProgress[item]||0)+'/'+adRewards[item][0]);
  else if(row?.state&&row.state!=='pending')notify(states[row.state]||states.unconfirmed);
  else{notify(states.pending);schedulePoll(attempt.ymid,item,Date.now()+120000);}
 }catch(error){
  const verification=/verify|verification/i.test(error?.message||'');
  try{await safeReport(attempt.ymid,'failed',{error:verification?'verification_failed':'sdk_error'});}catch(_){}
  notify(verification?states.unconfirmed:'Реклама недоступна, попробуйте позже');await recover(true);
 }finally{working=false;decorate();}
}
window.FarmAds={recover,watch};
// Dialog changes add buttons without navigation. Timers contain no credentials;
// pending progress is recovered from the authenticated account, not localStorage.
new MutationObserver(()=>decorate()).observe(document.body,{subtree:true,attributes:true,attributeFilter:['open']});
document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible')recover(true);});
window.addEventListener('telegram-sdk-ready',()=>recover(true));
setInterval(()=>{
 if(!token||document.visibilityState!=='visible'||!cfg)return;
 if(cooldownUntil>0&&cfg.retry_after>0){
  const remaining=Math.max(0,Math.ceil((cooldownUntil-Date.now())/1000));
  if(remaining!==cfg.retry_after){cfg.retry_after=remaining;decorate();}
  if(remaining===0){cooldownUntil=0;recover(true);}
 }
},1000);
setInterval(()=>{if(token&&document.visibilityState==='visible')recover();},30000);
decorate();recover(true);
})();
