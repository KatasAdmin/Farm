"use strict";
(() => {
 const catalog=document.getElementById("farm-city-catalog-list");
 const inventory=document.getElementById("farm-city-inventory");
 const own=document.getElementById("farm-city-own");
 const ownList=document.getElementById("farm-city-own-list");
 const market=document.getElementById("farm-city-products");
 if(!catalog||!inventory||!own||!ownList||!market)return;

 const icons={pancakes:"🥞",pie:"🥧",omelet:"🍳",cheese:"🧀",bread:"🍞",yogurt:"🥣",
  pillow:"🛏️",scarf:"🧣",breakfast_set:"🍱",dessert_box:"🍰",home_set:"🎁",lunch_box:"🥡"};
 const number=new Intl.NumberFormat("ru-RU",{maximumFractionDigits:1});
 const fmt=n=>number.format(Number(n)||0);
 const esc=s=>String(s).replace(/[&<>"']/g,ch=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
 let info,loading,busy=false,marketCategory="food";

 function tokenValue(){
  if(typeof token==="string"&&token)return token;
  try{return localStorage.getItem("farm_token")||""}catch{return ""}
 }
 async function call(path,body){
  const controller=new AbortController();
  const timeout=setTimeout(()=>controller.abort(),18000);
  try{
   const response=await fetch("/api/city/"+path,{
    method:body===undefined?"GET":"POST",
    headers:{"Content-Type":"application/json",Authorization:"Bearer "+tokenValue()},
    body:body===undefined?undefined:JSON.stringify(body),cache:"no-store",signal:controller.signal
   });
   const result=await response.json();
   if(!response.ok)throw Error(result.detail||"Операция недоступна");
   return result;
  }finally{clearTimeout(timeout)}
 }
 function card(item,meta,actions){
  return '<article class="farm-city-product"><div class="farm-city-product-top"><span class="farm-city-icon">'+
   (icons[item]||"📦")+'</span><div><strong>'+esc(info.recipes[item].name)+'</strong><small>'+meta+
   '</small></div></div><div class="farm-city-trade-row">'+actions+'</div></article>';
 }
 function ownOffers(category){
  const food=category==="food";
  return (info.my_offers||[]).filter(offer=>info.recipes[offer.item]&&Boolean(info.food_restore[offer.item])===food);
 }
 function listingCard(offer){
  return card(offer.item,fmt(offer.quantity)+' шт. · '+fmt(offer.price)+' 🪙/шт.',
   '<button type="button" data-city-unlist="'+esc(offer.id)+'">Снять с продажи</button>');
 }
 function shop(target,category){
  const food=category==="food";
  if(info.simple_economy){
   const offers=Object.entries(info.city_catalog)
    .filter(([item])=>info.recipes[item]&&Boolean(info.food_restore[item])===food)
    .sort(([nameA,a],[nameB,b])=>a.buy_price-b.buy_price||
      (info.food_restore[nameA]||0)-(info.food_restore[nameB]||0)||
      nameA.localeCompare(nameB,"ru"));
   target.innerHTML=offers.map(([item,offer])=>card(item,
    '🏪 Купить '+fmt(offer.buy_price)+' 🪙 · Продать '+fmt(offer.sell_price)+' 🪙'+
    (food?' · +'+info.food_restore[item]+' сытости':''),
    '<input type="number" min="1" max="500" value="1" aria-label="Количество">'+
    '<button type="button" data-city-buy="'+item+'" data-destination="'+(food?'farm':'city')+'">Купить</button>'
   )).join("");
   return;
  }
  const offers=Object.entries(info.city_catalog).filter(([item,offer])=>
   offer.quantity>0&&info.recipes[item]&&Boolean(info.food_restore[item])===food)
   .sort(([nameA,a],[nameB,b])=>a.min_price-b.min_price||
     (info.food_restore[nameA]||0)-(info.food_restore[nameB]||0)||
     nameA.localeCompare(nameB,"ru"));
  target.innerHTML=offers.length?offers.map(([item,offer])=>
   card(item,fmt(offer.quantity)+' шт. на рынке · от '+fmt(offer.min_price)+' 🪙/шт.'+
    (food?' · +'+info.food_restore[item]+'% сытости':''),
    '<input type="number" min="1" max="'+Math.min(500,offer.quantity)+'" value="1" aria-label="Количество">'+
    '<button type="button" data-city-buy="'+item+'" data-destination="'+(food?'farm':'city')+'">Купить</button>')
  ).join(""):'<p class="farm-city-blank">Пока нет предложений</p>';
 }
 function renderStatus(food){
  if(!food)return;
  for(const el of document.querySelectorAll("[data-farmer-fullness]"))el.textContent=fmt(food.fullness)+"%";
  for(const el of document.querySelectorAll("[data-farmer-bonus]"))el.textContent="+"+fmt(food.bonus_percent)+"%";
 }
 function renderInventory(){
  const owned=Object.entries(info.food).filter(([item,n])=>n>0&&info.food_restore[item]);
  const onFarm=owned
   .sort(([a],[b])=>(info.system_prices[a]?.buy||0)-(info.system_prices[b]?.buy||0)||
      (info.food_restore[a]||0)-(info.food_restore[b]||0)||a.localeCompare(b,"ru"))
   .map(([item,n])=>card(item,
   fmt(n)+' шт. · +'+info.food_restore[item]+'% сытости'+
   (info.simple_economy?' · Продажа '+fmt(info.system_prices[item].sell)+' 🪙/шт.':''),
   '<button type="button" data-city-eat="'+item+'">Съесть</button>'+
   (info.simple_economy?'<button type="button" data-city-sell="'+item+'" data-destination="farm">Продать</button>':'')
  )).join("");
  // Food is a single stock for this account, not two separate warehouses.
  const cityFood="";
  inventory.innerHTML=(onFarm+cityFood)||'<p class="farm-city-blank">На складе пока нет еды</p>';
 }
 function load(){
  if(!tokenValue())return Promise.resolve();
  if(loading)return loading;
  loading=call("farm-goods").then(snapshot=>{
   info=snapshot;
   renderStatus(info.nutrition);
   if(document.body.dataset.screen==="production"){
    shop(catalog,"food");
    renderInventory();
    const listings=ownOffers("food");
    own.hidden=info.simple_economy||!listings.length;
    ownList.innerHTML=info.simple_economy?'':listings.map(listingCard).join("");
   }
   if(!market.hidden)shop(market,marketCategory);
  }).catch(error=>{
   const text='<p class="farm-city-blank">'+esc(error.name==="AbortError"?"Рынок временно недоступен":error.message)+'</p>';
   if(document.body.dataset.screen==="production"){catalog.innerHTML=text;inventory.innerHTML=text}
   if(!market.hidden)market.innerHTML=text;
  }).finally(()=>{loading=null});
  return loading;
 }
 function showMarket(category){
  marketCategory=category;
  market.hidden=false;
  market.innerHTML='<p class="farm-city-blank">Загрузка предложений…</p>';
  return load();
 }
 async function execute(event){
  const source=event.target.closest("button[data-city-buy],button[data-city-sell],button[data-city-eat],button[data-city-move],button[data-city-unlist]");
  if(!source||busy)return;
  const buying=Boolean(source.dataset.cityBuy);
  const moving=Boolean(source.dataset.cityMove);
  const selling=Boolean(source.dataset.citySell);
  const listing=source.dataset.cityUnlist;
  const item=source.dataset.cityBuy||source.dataset.cityEat||source.dataset.cityMove||source.dataset.citySell;
  const field=source.closest(".farm-city-product")?.querySelector("input");
  const amount=field?Number(field.value):1;
  if(!Number.isSafeInteger(amount)||amount<1||(field&&amount>Number(field.max))){
   toast("Проверь количество");return;
  }
  busy=true;
  source.disabled=true;
  try{
   const body={item,amount,destination:source.dataset.destination||"farm",
    request_id:Array.from(crypto.getRandomValues(new Uint8Array(16)),n=>n.toString(16).padStart(2,"0")).join("")};
   if(buying){
    const quote=await call("quote-product",{item,amount,destination:body.destination});
    const message=info.simple_economy?"Купить "+amount+" шт. за "+fmt(quote.cost)+" монет?"
    :quote.own_quantity===amount
     ?"Забрать на ферму "+amount+" шт. из своих лотов за 0 монет?"
     :"Купить "+(amount-(quote.own_quantity||0))+" шт. за "+fmt(quote.cost)+" монет?"+
      (quote.own_quantity?" Ещё "+quote.own_quantity+" шт. поступит из своих лотов за 0 монет.":"");
    if(!confirm(message))return;
    body.expected_cost=quote.cost;
   }
   if(listing)body.listing_id=listing;
   if(selling&&!confirm("Продать "+amount+" шт. системе за "+fmt(amount*info.system_prices[item].sell)+" монет?"))return;
   if(moving&&info.simple_economy&&!confirm("Перенести "+amount+" шт. бесплатно?"))return;
   const path=listing?"cancel-product":buying?"buy-product":selling?"list-product":
    moving?(info.simple_economy?"transfer-product":"move-food"):"eat";
   const result=await call(path,body);
   if(result.nutrition)renderStatus(result.nutrition);
   toast(listing?"Лот снят":selling?"Продано! Монеты начислены.":buying?(body.destination==="farm"?"Еда на складе фермы":"Товар на складе города"):moving?"Еда перенесена бесплатно":"Сытость обновлена");
   await load();
   void refresh();
  }catch(error){
   toast(error.name==="AbortError"||error instanceof TypeError?
    "Связь прервалась. Проверь склад и баланс.":error.message);
   await load();
  }finally{busy=false;source.disabled=false}
 }
 for(const target of [catalog,inventory,market,ownList])target.addEventListener("click",execute);
 document.getElementById("farm-city-refresh")?.addEventListener("click",load);
 window.addEventListener("pageshow",event=>{
  if(event.persisted&&["production","shop"].includes(document.body.dataset.screen))void load();
 });
 window.farmCityProducts={load,showMarket,renderStatus};
})();

