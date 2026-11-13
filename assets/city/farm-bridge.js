"use strict";
(() => {
 const catalog=document.getElementById("farm-city-catalog-list");
 const inventory=document.getElementById("farm-city-inventory");
 const market=document.getElementById("farm-city-products");
 if(!catalog||!inventory||!market)return;

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
 function shop(target,category){
  const food=category==="food";
  const offers=Object.entries(info.city_catalog).filter(([item,r])=>
   r.quantity>0&&info.recipes[item]&&Boolean(info.food_restore[item])===food);
  target.innerHTML=offers.length?offers.map(([item,offer])=>card(item,
   fmt(offer.quantity)+' шт. · от '+fmt(offer.min_price)+' 🪙'+(food?' · +'+info.food_restore[item]+' п. п.':''),
   '<input type="number" min="1" max="'+Math.min(500,offer.quantity)+'" value="1" aria-label="Количество">'+
   '<button type="button" data-city-buy="'+item+'" data-destination="'+(food?'farm':'city')+'">Купить</button>'
  )).join(""):'<p class="farm-city-blank">Пока нет предложений</p>';
 }
 function renderStatus(food){
  if(!food)return;
  for(const el of document.querySelectorAll("[data-farmer-fullness]"))el.textContent=fmt(food.fullness)+"%";
  for(const el of document.querySelectorAll("[data-farmer-bonus]"))el.textContent="+"+fmt(food.bonus_percent)+"%";
 }
 function renderInventory(){
  const owned=Object.entries(info.food).filter(([item,n])=>n>0&&info.food_restore[item]);
  const onFarm=owned.map(([item,n])=>card(item,
   fmt(n)+' шт. · +'+info.food_restore[item]+' п. п.',
   '<button type="button" data-city-eat="'+item+'">Съесть</button>'
  )).join("");
  const inCity=Object.entries(info.city_food).map(([item,n])=>card(item,
   fmt(n)+' шт. на складе города',
   '<input type="number" min="1" max="'+Math.min(500,n)+'" value="1" aria-label="Количество">'+
   '<button type="button" data-city-move="'+item+'">Перенести</button>'
  )).join("");
  inventory.innerHTML=onFarm+inCity||'<p class="farm-city-blank">На складе фермы пока нет еды</p>';
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
  const source=event.target.closest("button[data-city-buy],button[data-city-eat],button[data-city-move]");
  if(!source||busy)return;
  const buying=Boolean(source.dataset.cityBuy);
  const moving=Boolean(source.dataset.cityMove);
  const item=source.dataset.cityBuy||source.dataset.cityEat||source.dataset.cityMove;
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
    const quote=await call("quote-product",{item,amount});
    if(!confirm("Купить "+amount+" шт. за "+fmt(quote.cost)+" монет?"))return;
    body.expected_cost=quote.cost;
   }
   const result=await call(buying?"buy-product":moving?"move-food":"eat",body);
   if(result.nutrition)renderStatus(result.nutrition);
   toast(buying?(body.destination==="farm"?"Еда на складе фермы":"Товар на складе города"):moving?"Еда перенесена на ферму":"Сытность обновлена");
   await load();
   void refresh();
  }catch(error){
   toast(error.name==="AbortError"||error instanceof TypeError?
    "Связь прервалась. Проверь склад и баланс.":error.message);
   await load();
  }finally{busy=false;source.disabled=false}
 }
 for(const target of [catalog,inventory,market])target.addEventListener("click",execute);
 document.getElementById("farm-city-refresh")?.addEventListener("click",load);
 window.farmCityProducts={load,showMarket,renderStatus};
})();
