/* AdsGram-only rewards for farm resources. Rewards are granted exclusively
 * by the protected AdsGram server Reward URL, never by the SDK callback. */
(()=>{
'use strict';
let cfg=null,working=false,recovering=null,lastRecover=0;
const labels={grain:'зерно',eggs:'яйца',milk:'молоко',chickens:'курицу',geese:'гусыню',cows:'корову',coins:'монеты для покупок'};
const adApi=(path,payload)=>api('/api/ads/adsgram/farm/'+path,payload,tgInitData()?{'X-Telegram-Init-Data':tgInitData()}:{});
function notify(message){toast(message);const node=el('ad-inline-status');if(node)node.textContent=message;}
function itemButton(item){
 const button=document.createElement('button');button.type='button';button.className='btn alt small ad-free-button';button.dataset.adFree=item;
 button.addEventListener('click',()=>watch(button.dataset.adFree));return button;
}
function decorate(){
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
 document.querySelectorAll('[data-ad-free="coins"]').forEach(button=>button.remove());
 document.querySelectorAll('[data-ad-free]').forEach(button=>{
  const item=button.dataset.adFree;const r=adRewards[item];if(!r)return;
  const ready=cfg?.enabled&&!!tgInitData();
  const reason=!tgInitData()?'Только в Telegram':!cfg?.enabled?'AdsGram недоступен':working?'Реклама открывается':pending?'Дождитесь завершения действия':'';
  button.disabled=!!reason;
  button.title=reason||('Награда: '+r[1]+' '+labels[item]+' за '+r[0]+' подтверждённых просмотров');
  const compactReason=reason?.includes('rewarded-зона')?'Скоро':reason?.includes('лимит')||reason?.includes('Лимит')?'Лимит':reason?.includes('через')?'Таймер':reason?.includes('Загружается')?'Загрузка':reason?.includes('открывается')?'Открывается':reason?.includes('Дождитесь')?'Ожидание':reason==='Гуси доступны с 3-го уровня'?'С 3 уровня':reason?'Недоступно':'';
  button.textContent=reason?'🎬 '+compactReason:item==='coins'?'🎬 +2 монеты':'🎬 Бесплатно · '+(adProgress[item]||0)+'/'+r[0];
 });
}

async function recover(force=false){
 if(!token||!tgInitData())return;
 if(recovering)return recovering;
 if(!force&&Date.now()-lastRecover<15000){decorate();return;}
 lastRecover=Date.now();
 recovering=(async()=>{
  try{
   const data=await adApi('status');
   cfg=data;
   adProgress=Object.fromEntries(Object.entries(data.rewards||{}).map(([k,v])=>[k,v.progress]));
   decorate();
   if(data.granted?.length){notify('Награда за рекламу получена!');await refresh();}
   if(data.pending)notify('Награда ожидает свободного места в хозяйстве.');
   const wallet=el('wallet');
   if(wallet){
    let holder=el('ad-history');
    if(!holder){holder=document.createElement('details');holder.id='ad-history';holder.className='card';holder.innerHTML='<summary>🎬 История рекламы AdsGram</summary><div class="ad-history-rows"></div>';wallet.appendChild(holder);}
    const body=holder.querySelector('.ad-history-rows');body.replaceChildren();
    for(const row of data.history||[]){const p=document.createElement('p');p.className='muted';p.textContent=new Date(row.created_at*1000).toLocaleString('ru-RU')+' · '+(labels[row.item]||row.item)+' · '+(row.state==='credited'?'Подтверждено':'Ожидается подтверждение');body.appendChild(p);}
   }
  }catch(e){if(force)notify('Статистика AdsGram недоступна: '+String(e.message||e));}
  finally{recovering=null;decorate();}
 })();
 return recovering;
}
async function watch(item){
 if(working||pending||!adRewards[item])return;
 if(!tgInitData()){notify('AdsGram доступен только в Telegram Mini App');return;}
 if(!cfg?.enabled){notify('Подключаем AdsGram…');await recover(true);if(!cfg?.enabled)return;}
 working=true;decorate();
 let prepared=null;
 try{
  prepared=await adApi('prepare',{item});
  if(!window.FarmAdsgramFallback?.show)throw new Error('SDK AdsGram ещё загружается');
  await window.FarmAdsgramFallback.show(cfg.adsgram_block_id);
  notify('✅ Просмотр завершён. Проверяем серверное подтверждение AdsGram…');
  // Reward URL may arrive asynchronously. Check later without trusting the SDK.
  for(let i=0;i<5;i++){
   await new Promise(resolve=>setTimeout(resolve,1800));
   await recover(true);
   const row=cfg?.history?.find(x=>x.ymid===prepared.attempt_id);
   if(row?.state==='credited'){notify('✅ Просмотр подтверждён AdsGram');break;}
  }
 }catch(e){
  if(prepared?.attempt_id){try{await adApi('cancel',{attempt_id:prepared.attempt_id})}catch(_){}}
  const err=String(e?.message||'Недоступно');
  notify(/previous|pending|active/i.test(err)?'Предыдущий просмотр ещё обрабатывается. Попробуй через несколько минут.':/did not complete/i.test(err)?'Реклама не завершена. Награды нет.':err);
 }finally{working=false;await recover(true);decorate();}
}
window.FarmAds={recover,watch};
new MutationObserver(()=>decorate()).observe(document.body,{subtree:true,attributes:true,attributeFilter:['open']});
document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible')recover(true);});
window.addEventListener('telegram-sdk-ready',()=>recover(true));
setInterval(()=>{if(token&&document.visibilityState==='visible')recover();},30000);
decorate();recover(true);
})();
