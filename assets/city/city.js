"use strict";
const $=id=>document.getElementById(id);
const root="/api/city";
const names={eggs:"🥚 Яйца",grain:"🌾 Зерно",milk:"🥛 Молоко",feathers:"🪶 Перья",wool:"🧶 Шерсть"};
const icons={pancakes:"🥞",pie:"🥧",omelet:"🍳",cheese:"🧀",bread:"🍞",pillow:"🛏️",scarf:"🧣",breakfast_set:"🍱",dessert_box:"🍰",home_set:"🎁",lunch_box:"🥡"};
let token="",data=null,activeView="map",activeBusiness=null,working=false,lastShoppingRecipe=null;
const store={get(){try{return localStorage.getItem("farm_token")||""}catch{return ""}},set(x){try{localStorage.setItem("farm_token",x)}catch{}}};
const number=n=>new Intl.NumberFormat("ru-RU").format(Number(n)||0);
const esc=v=>String(v).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const tgData=()=>window.Telegram?.WebApp?.initData||new URLSearchParams(location.hash.slice(1)).get("tgWebAppData")||"";
function toast(text){$("city-toast").textContent=text;$("city-toast").classList.remove("hidden");clearTimeout(toast.t);toast.t=setTimeout(()=>$("city-toast").classList.add("hidden"),4200)}
async function api(path,body){
 const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),18000);
 try{
  const response=await fetch(path.startsWith("/api/")?path:root+path,{
   method:body===undefined?"GET":"POST",
   headers:{"Content-Type":"application/json",Authorization:"Bearer "+token},
   body:body===undefined?undefined:JSON.stringify(body),
   signal:controller.signal,cache:"no-store"});
  const json=await response.json();
  if(!response.ok){const err=Error(json.detail||"Сервер отклонил запрос");err.status=response.status;throw err}
  return json;
 }catch(error){
  if(body!==undefined&&(error?.name==="AbortError"||error instanceof TypeError)){
   throw Error("Соединение прервалось. Результат действия неизвестен — проверь склад и баланс перед повтором.");
  }
  throw error;
 }finally{clearTimeout(timeout)}
}
async function entry(){
 window.Telegram?.WebApp?.ready?.();
 token=store.get();
 try{
  if(token){try{data=await api("/state")}catch(e){if(e.status!==401)throw e;token="";}}
  if(!data&&tgData()){
    const login=await api("/api/telegram/login",{telegram_data:tgData()});
    token=login.token;store.set(token);data=await api("/state");
  }
  if(data){$("city-auth").classList.add("hidden");paint();return}
  showLogin();
 }catch(e){showLogin();$("auth-status").textContent="Не удалось подключиться: "+e.message}
}
function showLogin(){
 $("city-auth").classList.remove("hidden");
 $("telegram-login").hidden=!tgData();
 $("auth-status").textContent="Войди через аккаунт своей фермы";
}
async function loginTelegram(){
 if(!tgData()){toast("Открой игру через Telegram");return}
 $("auth-status").textContent="Проверяем Telegram…";
 try{const x=await api("/api/telegram/login",{telegram_data:tgData()});token=x.token;store.set(token);data=await api("/state");$("city-auth").classList.add("hidden");paint()}
 catch(e){$("auth-status").textContent=e.message}
}
async function loginPassword(ev){
 ev.preventDefault();
 $("auth-status").textContent="Проверяем данные…";
 try{const x=await api("/api/login",{name:$("auth-name").value.trim(),password:$("auth-password").value});
 token=x.token;store.set(token);data=await api("/state");$("city-auth").classList.add("hidden");paint()}
 catch(e){$("auth-status").textContent=e.message}
}
async function load(){data=await api("/state");paint()}
function paint(){
 $("coins").textContent=number(data.coins);
 $("reputation").textContent=number(data.reputation);
 $("greeting").textContent="Привет, "+data.name+"! Выбирай свой бизнес";
 $("business-count").textContent=data.businesses.length;
 $("eggs-on-market").textContent=number(data.farm_market_totals?.eggs??data.farm_offers.filter(x=>x.item==="eggs").reduce((n,x)=>n+x.quantity,0));
 $("eggs-demand-today").textContent=number(data.city_demand_today?.eggs||0);
 $("products-count").textContent=number(Object.values(data.products).reduce((a,b)=>a+b,0));
 document.querySelectorAll(".building").forEach(x=>x.classList.toggle("unlocked",data.businesses.includes(x.dataset.business)));
 if(!$("panel-overlay").classList.contains("hidden"))refreshPanel();
}
function openPanel(title,html){
 $("panel-heading").textContent=title;
 $("panel-body").innerHTML=html;
 $("panel-overlay").classList.remove("hidden");
}
function closePanel(){
 $("panel-overlay").classList.add("hidden");
 document.querySelectorAll(".bottom-nav button").forEach(x=>x.classList.toggle("nav-active",x.dataset.view==="map"));
}
function row(name,details,actions){return '<div class="item-card"><div><strong>'+name+'</strong><small>'+details+'</small></div><div class="item-actions">'+actions+'</div></div>'}
function input(id,value=1){return '<input class="number-input" aria-label="Количество" id="'+id+'" type="number" min="1" max="500" value="'+value+'">'}
function getAmount(id){const n=Number($(id)?.value);if(!Number.isSafeInteger(n)||n<1||n>500){toast("Введи количество от 1 до 500");return null}return n}
function view(tab){
 activeView=tab;activeBusiness=null;
 document.querySelectorAll(".bottom-nav button").forEach(x=>x.classList.toggle("nav-active",x.dataset.view===tab));
 if(tab==="map")closePanel();else refreshPanel();
}
function refreshPanel(){
 if(activeBusiness)return showBusiness(activeBusiness);
 if(activeView==="market")return showMarket();
 if(activeView==="products")return showProducts();
 if(activeView==="warehouse")return showWarehouse();
 if(activeView==="profile")return showProfile();
 if(activeView==="residents")return showResidents();
 if(activeView==="store")return showBusiness("store");
 if(activeView==="shopping")return showShoppingList(lastShoppingRecipe);
}
function showBusiness(kind){
 activeBusiness=kind;
 const b=data.business_catalog[kind],opened=data.businesses.includes(kind);
 let body='<p class="panel-note">Предприятие закупает сырьё только через общий рынок фермы. Даже собственные яйца нельзя использовать без покупки из чужого лота.</p>';
 if(!opened){
 const required=b.min_reputation||0;
 const ready=(data.reputation||0)>=required;
 body+='<div class="empty">🔒 Для открытия нужно '+required+' репутации. У тебя '+data.reputation+'. Жители начисляют её за использование готовых товаров.</div><p><button class="btn gold" data-action="open" data-item="'+kind+'" '+(ready?'':'disabled')+'>✨ Открыть '+esc(b.name)+'</button></p>';
}
 else{
  body+='<div class="badge-line"><span class="pill">✅ Работает</span><span class="pill">Общий рынок фермы</span></div>';
  let recipes=Object.entries(data.recipes).filter(([k,v])=>v.business===kind);
  body+='<h3 class="section-subtitle">Производство</h3>';
  body+=recipes.map(([key,v])=>{
   const rawNeeds=Object.entries(v.needs).map(([k,n])=>esc(names[k])+' ×'+n+' (есть '+(data.stock[k]||0)+')');
   const productNeeds=Object.entries(v.needs_products||{}).map(([k,n])=>(icons[k]||"📦")+' '+esc(data.recipes[k]?.name||k)+' ×'+n+' (есть '+(data.products[k]||0)+')');
   const need=rawNeeds.concat(productNeeds).join(" · ");
   return row((icons[key]||"📦")+" "+esc(v.name),need+" · "+v.seconds+" сек. · результат ×"+v.output,
    input("qty-craft-"+key)+ '<button class="btn" data-action="produce" data-item="'+key+'">Готовить</button><button class="btn ghost" data-action="shopping" data-item="'+key+'">🧺 Ингредиенты</button>');
  }).join("");
  body+='<h3 class="section-subtitle">Задания в работе</h3>';
  const jobs=data.jobs.filter(x=>data.recipes[x.recipe]?.business===kind);
  body+=jobs.length?jobs.map(x=>row(esc(data.recipes[x.recipe].name)+' ×'+x.quantity,
   x.ready_at*1000<=Date.now()?"Готово, обнови склад":"Готово: "+new Date(x.ready_at*1000).toLocaleTimeString("ru-RU"),"⏳")).join(""):'<div class="empty">Очередь производства свободна</div>';
  body+='<p><button class="btn ghost" data-action="market">🧺 Закупить ингредиенты</button></p>';
 }
 openPanel(b.emoji+" "+b.name,body);
}
function showShoppingList(recipeId){
 const recipe=data.recipes[recipeId];
 if(!recipe)return;
 activeBusiness=null;
 activeView="shopping";
 const items=[
  ...Object.entries(recipe.needs||{}).map(([item,need])=>({item,need,stock:data.stock[item]||0,type:"raw"})),
  ...Object.entries(recipe.needs_products||{}).map(([item,need])=>({item,need,stock:data.products[item]||0,type:"product"}))
 ];
 let html='<p class="panel-note">Рецепт: '+esc(recipe.name)+'. Здесь показано, чего не хватает для одной партии. Любое сырьё покупается у других фермеров, а полуфабрикаты — у других городских бизнесов. Свои склады фермы в расчёт не входят.</p>';
 html+=items.map((entry,i)=>{
  const missing=Math.max(0,entry.need-entry.stock);
  const name=entry.type==="raw"?esc(names[entry.item]):(icons[entry.item]||"📦")+" "+esc(data.recipes[entry.item]?.name||entry.item);
  const catalog=entry.type==="raw"?data.raw_catalog:data.city_catalog;
  const available=catalog?.[entry.item]?.quantity||0;
  return row(name,"Нужно "+entry.need+" · На складе "+entry.stock+" · На рынке "+available,
  !missing?'<span class="pill">✅ Достаточно</span>':
  input("shopping-"+i,missing)+
  '<button class="btn" data-action="'+entry.type+'" data-item="'+esc(entry.item)+'" data-amount-id="shopping-'+i+'" '+(available<missing?'disabled':'')+'>Купить</button>');
 }).join("");
 html+='<p><button class="btn ghost" data-action="business" data-item="'+recipe.business+'">← Вернуться в '+esc(data.business_catalog[recipe.business].name)+'</button></p>';
 openPanel("🧺 Закупка для "+recipe.name,html);
}
function showMarket(){
 const groups=data.raw_catalog||{};
 let s='<p class="panel-note">🧺 Один товар — одна покупка. Количество автоматически распределяется между продавцами по правилам рынка фермы, в том числе пропорционально между лотами одинаковой цены.</p>';
 const listed=Object.entries(groups).filter(([item,o])=>names[item]&&o.quantity>0);
 s+=listed.length?listed.map(([item,o])=>row(esc(names[item]),
  'На рынке '+number(o.quantity)+' шт. · От '+number(o.min_price)+' 🪙 · Продавцов: '+o.sellers,
  input('qty-raw-'+item)+'<button class="btn" data-action="raw" data-item="'+item+'" data-amount-id="qty-raw-'+item+'">Купить</button>')).join(""):'<div class="empty">На рынке нет сырья от других игроков. Фермеры могут выставить яйца через ферму.</div>';
 openPanel("🧺 Общий рынок фермы",s);
}
function showProducts(){
 let s='<p class="panel-note">🛍️ Один товар — одна карточка. Внутри покупки система сама распределяет монеты между продавцами, а еда появляется на городском складе.</p>';
 const listed=Object.entries(data.city_catalog||{}).filter(([item,o])=>data.recipes[item]&&o.quantity>0);
 s+=listed.length?listed.map(([item,o])=>row((icons[item]||"📦")+" "+esc(data.recipes[item].name),
  'На рынке '+number(o.quantity)+' шт. · От '+number(o.min_price)+' 🪙 · Продавцов: '+o.sellers,
  input('qty-product-'+item)+'<button class="btn" data-action="product" data-item="'+item+'" data-amount-id="qty-product-'+item+'">Купить</button>')).join(""):'<div class="empty">Городских товаров пока нет. Открой производство и выставь первый товар!</div>';
 openPanel("🛍️ Рынок городских товаров",s);
}
function showResidents(){
 let s='<p class="panel-note">Каждый день жители города размещают три заказа на готовые товары. Купи их у других игроков или изготовь сам. За выполнение начисляется репутация — монеты из казны не создаются.</p>';
 const orders=data.resident_orders||[];
 s+=orders.map(o=>row((icons[o.recipe]||"📦")+" "+esc(data.recipes[o.recipe]?.name||o.recipe),
  'Заказ жителя · +'+o.reputation+' репутации · '+o.quantity+' шт.',
  o.done?'<span class="pill">✅ Выполнено</span>':
  '<button class="btn gold" data-action="fulfill" data-item="'+esc(o.id)+'">Отдать</button>')).join("");
 s+='<p class="panel-note">Новые заявки появляются ежедневно в 00:00 UTC. Количество заказов ограничено.</p>';
 openPanel("👥 Заказы жителей",s);
}
function showProfile(){
 activeBusiness=null;
 let html='<p class="panel-note">Один аккаунт для фермы и города. Монеты на общем балансе, промокоды одноразовые и бонусные монеты не выводятся.</p>';
 html+='<div class="mini-grid"><div class="mini-box"><small>👤 Игрок</small><strong style="font-size:16px">'+esc(data.name)+'</strong></div><div class="mini-box"><small>🪙 Общий баланс</small><strong>'+number(data.coins)+'</strong></div><div class="mini-box"><small>⭐ Репутация города</small><strong>'+number(data.reputation)+'</strong></div><div class="mini-box"><small>🏢 Предприятия</small><strong>'+number(data.businesses.length)+'</strong></div></div>';
 const finance=data.cashflow||{};
 html+='<h3 class="section-subtitle">📊 Финансы городских бизнесов</h3>';
 html+='<div class="mini-grid"><div class="mini-box"><small>📦 Закупки сырья</small><strong>'+number(finance.ingredient_spend||0)+' 🪙</strong></div><div class="mini-box"><small>🛍️ Покупки товаров</small><strong>'+number(finance.goods_purchases||0)+' 🪙</strong></div><div class="mini-box"><small>💰 Продажи товаров</small><strong>'+number(finance.goods_sales||0)+' 🪙</strong></div><div class="mini-box"><small>📈 Денежный поток</small><strong>'+number(finance.net||0)+' 🪙</strong></div></div>';
 html+='<p class="panel-note">Это учёт денег по сделкам города за всё время, а не второй кошелёк и не чистая прибыль: непроданные запасы и стоимость собственного производства ещё не учтены.</p>';
 html+='<div class="empty">🔗 Ферма и город используют один баланс. <strong>+1 000 по промокоду</strong> отображается в обеих играх, но начисляется только один раз. Склады и производственные ресурсы остаются раздельными.</div>';
 html+='<h3 class="section-subtitle">🎁 Активировать промокод</h3>';
 html+='<p class="panel-note">Введи код от TREVIXO или фермы. Награда поступит на тот же аккаунт. Один код можно использовать только один раз.</p>';
 html+='<form id="city-promo-form" class="city-promo-form"><input id="city-promo-input" aria-label="Промокод" autocomplete="off" spellcheck="false" maxlength="64" placeholder="FARM-…" required><button class="btn gold" type="submit">Получить награду</button></form>';
 html+='<p><a href="/" class="btn ghost" style="display:inline-block;text-decoration:none">🌾 Вернуться на ферму</a></p>';
 openPanel("👤 Мой профиль",html);
}
function showWarehouse(){
 let s='<p class="panel-note">Склад бизнеса отделён от фермерского склада. Он пополняется только закупками на общем рынке. Готовые товары можно продавать или использовать для развития репутации.</p>';
 s+='<h3 class="section-subtitle">Ингредиенты бизнеса</h3><div class="mini-grid">';
 s+=Object.entries(names).map(([key,name])=>'<div class="mini-box"><small>'+name+'</small><strong>'+number(data.stock[key]||0)+'</strong></div>').join("")+'</div>';
 s+='<h3 class="section-subtitle">🍽️ Питание фермера</h3>';
 const nutrition=data.nutrition||{};
 s+='<div class="nutrition-city-card">🍲 <strong>Сытость: '+(nutrition.fullness||0)+'%</strong><span>Бонус к производству фермы: +'+(nutrition.bonus_percent||0)+'% · Снижается на 5% в час. База всегда 100%.</span></div>';
 s+='<h3 class="section-subtitle">Произведённые товары</h3>';
 const products=Object.entries(data.products).filter(([key,n])=>n>0&&data.recipes[key]);
 s+=products.length?products.map(([key,n])=>row((icons[key]||"📦")+" "+esc(data.recipes[key].name),
   'На складе: '+n+' шт.',input("qty-list-"+key)+
   '<input class="number-input" aria-label="Цена" id="price-'+key+'" type="number" min="1" value="10">'+
   '<button class="btn gold" data-action="list" data-item="'+key+'">Продать</button>'+
   (["pancakes","pie","omelet","cheese","bread","breakfast_set","dessert_box","lunch_box"].includes(key)?'<button class="btn food" data-action="eat" data-item="'+key+'">🍽️ Съесть</button>':'')+
   '<button class="btn ghost" data-action="consume" data-item="'+key+'">⭐ Репутация</button>')).join(""):'<div class="empty">Пока нет готовой продукции. Закупи ингредиенты и начни производство.</div>';
 s+='<h3 class="section-subtitle">Мои объявления</h3>';
 s+=(data.my_city_offers||[]).length?data.my_city_offers.map(x=>
  row((icons[x.item]||"📦")+" "+esc(data.recipes[x.item]?.name||x.item),
  x.quantity+" шт. · "+x.price+" мон./шт.",
  '<button class="btn ghost" data-action="cancel" data-listing-id="'+esc(x.id)+'">Снять</button>'
 )).join(""):'<div class="empty">Активных предложений пока нет</div>';
 openPanel("📦 Склад бизнеса",s);
}
async function redeemPromo(event){
 event.preventDefault();
 if(working)return
 const code=$("city-promo-input")?.value.trim().toUpperCase();
 if(!code){toast("Введи промокод");return}
 working=true;
 try{
   const result=await api("/api/promo/redeem",{code});
   toast("🎁 Промокод принят! +"+number(result.awarded)+" монет");
   await load();
 }catch(error){toast(error.message||"Не удалось активировать промокод")}
 finally{working=false}
}
async function action(action,item,amountId,listingId){
 if(working)return;
 const amount=amountId?getAmount(amountId):null;
 if(amountId&&amount===null)return;
 let path,body={item};
 if(action==="market")return view("market");
 if(action==="shopping"){lastShoppingRecipe=item;return showShoppingList(item)}
 if(action==="business"){return showBusiness(item)}
 if(action==="open")path="/open";
 else if(action==="produce"){path="/produce";body.amount=getAmount("qty-craft-"+item);if(!body.amount)return}
 else if(action==="raw"){path="/buy-ingredient";body.amount=amount}
 else if(action==="product"){path="/buy-product";body.amount=amount}
 else if(action==="list"){path="/list-product";body.amount=getAmount("qty-list-"+item);body.price=Number($("price-"+item)?.value);if(!body.amount||!Number.isSafeInteger(body.price)||body.price<1){toast("Укажи количество и цену");return}}
 else if(action==="consume"){path="/consume";body.amount=getAmount("qty-list-"+item);if(!body.amount)return}
 else if(action==="eat"){path="/eat";body.amount=getAmount("qty-list-"+item);if(!body.amount||body.amount>20){toast("Можно съесть от 1 до 20 блюд");return}}
 else if(action==="cancel"){path="/cancel-product";body.listing_id=listingId}
 else if(action==="fulfill"){path="/fulfill-order"}
 else return;
 working=true;
 if(["raw","product","produce","list","consume","eat","fulfill"].includes(action)){
  body.request_id=(globalThis.crypto?.randomUUID?.()||(Date.now().toString(16)+Math.floor(Math.random()*1e15).toString(16)).padEnd(32,"a")).replaceAll("-","").slice(0,32);
 }
 if(action==="raw"||action==="product"){
  try{
   const quote=await api(action==="raw"?"/quote-ingredient":"/quote-product",{item,amount:body.amount});
   body.expected_cost=quote.cost;
   if(!confirm("Покупка "+body.amount+" шт. за "+number(quote.cost)+" монет у "+quote.sellers+" продавцов. Подтвердить?")){working=false;return}
  }catch(e){toast(e.message);working=false;return}
 }
 try{const result=await api(path,body);toast(action==="fulfill"?"Заказ выполнен! Репутация начислена.":action==="raw"?"Сырьё куплено на склад бизнеса!":action==="produce"?"Производство запущено!":action==="list"?"Товар выставлен в городе":action==="eat"?"🍽️ Ты поел! Производительность фермы выросла.":action==="open"?"Предприятие открыто!":"Готово!");
 await load();
 }catch(e){toast(e.message)}
 finally{working=false}
}
document.querySelectorAll(".building").forEach(x=>x.addEventListener("click",()=>{activeView="business";showBusiness(x.dataset.business)}));
document.querySelectorAll(".bottom-nav button").forEach(x=>x.addEventListener("click",()=>view(x.dataset.view)));
$("view-market").addEventListener("click",()=>view("market"));
$("view-products").addEventListener("click",()=>view("products"));
$("view-orders").addEventListener("click",()=>view("warehouse"));
$("view-residents").addEventListener("click",()=>view("residents"));
$("view-store").addEventListener("click",()=>{activeView="store";showBusiness("store")});
$("refresh").addEventListener("click",async()=>{
 try{await load();toast("Данные обновлены")}catch(e){toast(e.message)}
});
$("close-panel").addEventListener("click",closePanel);
$("panel-backdrop").addEventListener("click",closePanel);
document.addEventListener("keydown",e=>{if(e.key==="Escape")closePanel()});
$("panel-body").addEventListener("submit",e=>{
 if(e.target.id==="city-promo-form")redeemPromo(e);
});
$("panel-body").addEventListener("click",e=>{
 const button=e.target.closest("button[data-action]");if(!button)return;
 action(button.dataset.action,button.dataset.item,button.dataset.amountId,button.dataset.listingId)
});
$("auth-form").addEventListener("submit",loginPassword);
$("telegram-login").addEventListener("click",loginTelegram);
window.addEventListener("telegram-sdk-ready",()=>{if(!data&&!token)loginTelegram()});
setInterval(()=>{if(data&&document.visibilityState==="visible")load().catch(()=>{})},30000);
entry();
