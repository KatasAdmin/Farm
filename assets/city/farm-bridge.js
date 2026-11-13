"use strict";
// Farm ↔ City trade bridge: a single authenticated wallet, with separate city
// product inventory. No direct farm-to-business inventory transfers.
(() => {
 const marketButton=document.getElementById("farm-city-products-toggle");
 const marketContainer=document.getElementById("farm-city-products");
 const catalog=document.getElementById("farm-city-catalog-list");
 const inventory=document.getElementById("farm-city-inventory");
 const orders=document.getElementById("farm-city-orders");
 if(!catalog || !inventory || !orders)return;
 const icons={pancakes:"🥞",pie:"🥧",omelet:"🍳",cheese:"🧀",bread:"🍞",pillow:"🛏️",scarf:"🧣",breakfast_set:"🍱",dessert_box:"🍰",home_set:"🎁",lunch_box:"🥡"};
 const benefits={
  pancakes:"Сдать жителям, получить репутацию или приготовить десертный набор",
  pie:"Заказы жителей и десертные наборы ресторана",
  omelet:"Заказы жителей и обеденные наборы магазина",
  cheese:"Заказы жителей и фирменные завтраки ресторана",
  bread:"Заказы жителей, завтраки и готовые обеды",
  pillow:"Заказы на уют и производство домашних наборов",
  scarf:"Заказы жителей и товары для дома",
  breakfast_set:"Готовый завтрак для жителей города",
  dessert_box:"Десерт для вечернего заказа жителей",
  home_set:"Готовый набор для домашних заказов",
  lunch_box:"Городской обед и заказы жителей"
 };
 let info=null,busy=false;
 const fmt=n=>new Intl.NumberFormat("ru-RU").format(Number(n)||0);
 const esc=s=>String(s).replace(/[&<>"']/g,ch=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
 function tokenValue(){
   try{if(typeof token==="string"&&token)return token}catch(_){}
   try{return localStorage.getItem("farm_token")||""}catch(_){return ""}
 }
 function message(s){if(typeof toast==="function")toast(s);else alert(s)}
 function operationId(){
  return (globalThis.crypto?.randomUUID?.() || (Date.now().toString(16)+Math.floor(Math.random()*1e15).toString(16)).padEnd(32,"a")).replaceAll("-","").slice(0,32);
 }
 async function call(path,body){
  const controller=new AbortController();
  const timeout=setTimeout(()=>controller.abort(),18000);
  try{
   const response=await fetch("/api/city/"+path,{
    method:body===undefined?"GET":"POST",
    headers:{"Content-Type":"application/json","Authorization":"Bearer "+tokenValue()},
    body:body===undefined?undefined:JSON.stringify(body),cache:"no-store",signal:controller.signal
   });
   let result;
   try{result=await response.json()}catch{throw Error("Сервер временно недоступен")}
   if(!response.ok)throw Error(result.detail||"Операция недоступна");
   return result;
  }catch(error){
   if(error?.name==="AbortError" || error instanceof TypeError){
    throw Error("Связь прервалась. Проверь баланс и склад перед повтором действия.");
   }
   throw error;
  }finally{clearTimeout(timeout)}
 }
 const card=(item,{meta="",description="",actions="",accent=""}={})=>{
  const recipe=info?.recipes?.[item];
  return '<article class="farm-city-product '+accent+'"><div class="farm-city-product-top"><span class="farm-city-icon">'+(icons[item]||"📦")+'</span><div><strong>'+esc(recipe?.name||item)+'</strong><small>Из городских предприятий</small></div></div>'+
  '<div class="farm-city-description">'+esc(description||benefits[item]||"Городская продукция")+'</div>'+
  '<div class="farm-city-meta">'+meta+'</div>'+
  '<div class="farm-city-trade-row">'+actions+'</div></article>';
 };
 function renderShop(target){
  const groups=Object.entries(info.city_catalog||{}).filter(([item,r])=>info.recipes[item]&&r.quantity>0);
  if(!groups.length){
   target.innerHTML='<div class="farm-city-blank">🏪 Другие игроки ещё не выставили продукцию. Как только появятся товары, они будут здесь.</div>';
   return;
  }
  target.innerHTML='<div class="farm-city-grid">'+groups.map(([item,r])=>card(item,{
    meta:"От "+fmt(r.min_price)+" 🪙 за шт. · "+fmt(r.quantity)+" шт. · Продавцов: "+r.sellers,
    description:benefits[item],
    actions:'<input type="number" min="1" max="500" value="1" aria-label="Количество '+esc(item)+'" data-city-qty="'+esc(item)+'">'+
    '<button type="button" data-city-buy="'+esc(item)+'">Купить</button>'
   })).join("")+'</div>';
 }
 function renderInventory(){
  const mine=Object.entries(info.products||{}).filter(([k,n])=>n>0&&info.recipes[k]);
  const food=info.nutrition||{};
  const header='<div class="farm-food-status">🍽️ <strong>Сытость фермера: '+fmt(food.fullness||0)+'%</strong> · Бонус к яйцам, молоку, шерсти и перьям: <strong>+'+fmt(food.bonus_percent||0)+'%</strong><span>После еды сытость постепенно уменьшается на 5% в час. При нуле ферма работает с обычной скоростью.</span></div>';
  inventory.innerHTML=header+(mine.length?mine.map(([item,n])=>card(item,{
   meta:"На твоём городском складе: "+fmt(n)+" шт.",
   description:benefits[item],
   actions:(["pancakes","pie","omelet","cheese","bread","breakfast_set","dessert_box","lunch_box"].includes(item)?
     '<button type="button" class="farm-city-use" data-city-eat="'+esc(item)+'">🍽️ Съесть</button>':'')+
     '<button type="button" data-city-use="'+esc(item)+'">⭐ +5 репутации</button>'
  })).join(""):'<div class="farm-city-blank">🍽️ Пока нет готовой еды. Купи блюда выше — они сразу появятся здесь и на складе города.</div>');
 }
 function renderOrders(){
  const pending=info.resident_orders||[];
  orders.innerHTML=pending.length?pending.map(order=>{
   const owned=info.products?.[order.recipe]||0;
   return card(order.recipe,{
    meta:order.done?"✅ Выполнено сегодня":"Нужно "+order.quantity+" шт. · Есть "+owned+" · Награда +"+order.reputation+" ⭐",
    description:"Ежедневный заказ жителей. Полученная репутация открывает новые городские предприятия.",
    actions:order.done?'<span>Заказ выполнен</span>':
     '<button type="button" class="farm-city-use" data-city-order="'+esc(order.id)+'" '+(owned<order.quantity?'disabled':'')+'>Сдать жителям</button>',
    accent:order.done?"ordered":""
   });
  }).join(""):'<div class="farm-city-blank">Сегодня заказов пока нет. Открой город, чтобы развивать бизнес.</div>';
 }
 async function load(silent=false){
  if(!tokenValue()){
   if(!silent)message("Войди в аккаунт фермы, чтобы открыть товары");
   return;
  }
  if(!silent){
    catalog.innerHTML='<div class="farm-city-blank">⏳ Загружаем предложения игроков…</div>';
    inventory.innerHTML='<div class="farm-city-blank">Загружаем твой склад…</div>';
    orders.innerHTML='<div class="farm-city-blank">Получаем заказы жителей…</div>';
  }
  try{
   info=await call("state");
   renderShop(catalog);renderInventory();renderOrders();
   if(marketContainer && !marketContainer.hidden)renderShop(marketContainer);
  }catch(error){
   if(!silent)catalog.innerHTML='<div class="farm-city-blank">'+esc(error.message)+'</div>';
   if(!silent)message(error.message);
  }
 }
 async function execute(kind,item,source){
  if(busy)return;
  const amountInput=source.closest(".farm-city-product")?.querySelector('input[data-city-qty]');
  const quantity=Number(amountInput?.value);
  if(kind==="buy" && (!Number.isSafeInteger(quantity)||quantity<1||quantity>500)){message("Укажи количество от 1 до 500");return}
  busy=true;
  source.disabled=true;
  try{
   if(kind==="buy"){
    const quote=await call("quote-product",{item,amount:quantity});
    if(!confirm("Купить "+quantity+" шт. за "+fmt(quote.cost)+" монет у "+quote.sellers+" продавцов?"))return;
    await call("buy-product",{item,amount:quantity,expected_cost:quote.cost,request_id:operationId()});
    message("🛍️ Покупка совершена. Товар на складе города.");
   }else if(kind==="eat"){
    if(!confirm("Съесть 1 блюдо? Сытость увеличится, ускоряя производство фермы."))return;
    await call("eat",{item,amount:1,request_id:operationId()});
    message("🍽️ Сытость повышена! Бонус к производству фермы включён.");
   }else if(kind==="use"){
    if(!confirm("Использовать 1 шт. и получить +5 репутации города?"))return;
    await call("consume",{item,amount:1,request_id:operationId()});
    message("⭐ Товар использован. +5 репутации города.");
   }else if(kind==="order"){
    const order=info.resident_orders?.find(o=>o.id===item);
    if(!order||order.done)return;
    if(!confirm("Сдать жителям "+(info.recipes[order.recipe]?.name||order.recipe)+" за +"+order.reputation+" репутации?"))return;
    await call("fulfill-order",{item:order.id,request_id:operationId()});
    message("👥 Заказ выполнен! Репутация города увеличилась.");
   }
   if(typeof refresh==="function")await refresh();
   await load();
  }catch(error){message(error.message)}
  finally{busy=false;source.disabled=false}
 }
 function click(event){
  const target=event.target.closest("button");
  if(!target)return;
  if(target.dataset.cityBuy)return execute("buy",target.dataset.cityBuy,target);
  if(target.dataset.cityUse)return execute("use",target.dataset.cityUse,target);
  if(target.dataset.cityEat)return execute("eat",target.dataset.cityEat,target);
  if(target.dataset.cityOrder)return execute("order",target.dataset.cityOrder,target);
 }
 catalog.addEventListener("click",click);
 inventory.addEventListener("click",click);
 orders.addEventListener("click",click);
 marketContainer?.addEventListener("click",click);
 marketButton?.addEventListener("click",()=>{
  // Route both shop and Farm enterprise buttons to the same full product UI.
  if(typeof tab==="function")tab("production");
 });
 document.getElementById("farm-city-refresh")?.addEventListener("click",()=>load());
 window.farmCityProducts={load};
})();
