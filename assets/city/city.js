"use strict";
const $=id=>document.getElementById(id);
const root="/api/city";
const names={eggs:"🥚 Яйца",grain:"🌾 Зерно",milk:"🥛 Молоко",feathers:"🪶 Перья",wool:"🧶 Шерсть"};
const icons={pancakes:"🥞",pie:"🥧",omelet:"🍳",cheese:"🧀",bread:"🍞",pillow:"🛏️",scarf:"🧣",breakfast_set:"🍱",dessert_box:"🍰",home_set:"🎁",lunch_box:"🥡",yogurt:"🥣"};
let token="",data=null,activeView="map",activeBusiness=null,working=false,lastShoppingRecipe=null;
let loading=null,jobTimer,marketCategory="raw";
const statePath="/state?compact=true";
let receivedAt=0;
const secondsLeft=job=>Math.max(0,Math.ceil(job.ready_at-data.now-(performance.now()-receivedAt)/1000));
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
  if(token){try{data=await api(statePath)}catch(e){if(e.status!==401)throw e;token="";}}
  if(!data&&tgData())return loginTelegram();
  if(data){$("city-auth").classList.add("hidden");paint();window.CityEntryAds?.maybeStart?.();return}
  showLogin();
 }catch(e){showLogin();$("auth-status").textContent="Не удалось подключиться: "+e.message}
}
function showLogin(){
 $("city-auth").classList.remove("hidden");
 $("telegram-login").hidden=!tgData();
 $("auth-status").textContent="Войди через аккаунт своей фермы";
}
let telegramLoginPending=false;
async function loginTelegram(){
 if(telegramLoginPending||data)return;
 if(!tgData()){toast("Открой игру через Telegram");return}
 telegramLoginPending=true;
 $("auth-status").textContent="Проверяем Telegram…";
 try{const x=await api("/api/telegram/login",{telegram_data:tgData()});token=x.token;store.set(token);data=await api(statePath);$("city-auth").classList.add("hidden");paint();window.CityEntryAds?.maybeStart?.()}
 catch(e){showLogin();$("auth-status").textContent=e.message}
 finally{telegramLoginPending=false}
}
async function loginPassword(ev){
 ev.preventDefault();
 $("auth-status").textContent="Проверяем данные…";
 try{const x=await api("/api/login",{name:$("auth-name").value.trim(),password:$("auth-password").value});
 token=x.token;store.set(token);data=await api(statePath);$("city-auth").classList.add("hidden");paint();window.CityEntryAds?.maybeStart?.()}
 catch(e){$("auth-status").textContent=e.message}
}
function load(){
 if(loading)return loading;
 loading=api(statePath).then(snapshot=>{data=snapshot;paint()}).finally(()=>{loading=null});
 return loading;
}
window.cityReload=load;
function paint(){
 receivedAt=performance.now();
 $("coins").textContent=number(data.coins);
 $("reputation").textContent=number(data.reputation);
 $("business-count").textContent=data.businesses.filter(kind=>kind!=="store").length+" / 4";
 $("products-count").textContent=number(Object.values(data.products).reduce((a,b)=>a+b,0));
 $("jobs-count").textContent=data.jobs.length;
 $("orders-count").textContent=data.resident_orders.filter(order=>!order.done).length;
 document.querySelectorAll(".building").forEach(x=>x.classList.toggle("unlocked",data.businesses.includes(x.dataset.business)));
 if(!$("panel-overlay").classList.contains("hidden"))refreshPanel();
 clearTimeout(jobTimer);
 if(data.jobs.length)jobTimer=setTimeout(()=>{if(!working&&document.visibilityState==="visible")load().catch(()=>{})},Math.max(1000,secondsLeft(data.jobs[0])*1000+300));
}
function openPanel(title,html){
 const body=$("panel-body");
 const samePanel=$("panel-heading").textContent===title;
 const values=new Map(samePanel?Array.from(body.querySelectorAll("input[id]"),el=>[el.id,el.value]):[]);
 const focused=document.activeElement?.id;
 const scrollTop=samePanel?body.scrollTop:0;
 $("panel-heading").textContent=title;
 body.innerHTML=html;
 for(const input of body.querySelectorAll("input[id]")){
  if(values.has(input.id))input.value=values.get(input.id);
  if(samePanel&&input.id===focused)input.focus({preventScroll:true});
 }
 $("panel-overlay").classList.remove("hidden");
 body.scrollTop=scrollTop;
}
function closePanel(){
 activeBusiness=null;activeView="map";
 $("panel-overlay").classList.add("hidden");
 document.querySelectorAll(".bottom-nav button").forEach(x=>x.classList.toggle("nav-active",x.dataset.view==="map"));
}
function row(name,details,actions){return '<div class="item-card"><div><strong>'+name+'</strong><small>'+details+'</small></div><div class="item-actions">'+actions+'</div></div>'}
function input(id,value=1,max=500){return '<input class="number-input" aria-label="Количество" id="'+id+'" type="number" min="1" max="'+max+'" value="'+value+'">'}
function getAmount(id){const field=$(id),n=Number(field?.value),max=Number(field?.max)||500;if(!Number.isSafeInteger(n)||n<1||n>max){toast("Введи количество от 1 до "+max);return null}return n}
function view(tab){
 if(!data)return;
 activeView=tab;activeBusiness=null;
 document.querySelectorAll(".bottom-nav button").forEach(x=>x.classList.toggle("nav-active",x.dataset.view===tab));
 if(tab==="map")closePanel();else refreshPanel();
}
function refreshPanel(){
 if(activeBusiness)return showBusiness(activeBusiness);
 if(activeView==="market")return showMarket();
 if(activeView==="jobs")return openPanel("⏱️ В производстве",jobRows(data.jobs));
 if(activeView==="businesses")return showBusinessDirectory();
 if(activeView==="warehouse")return showWarehouse();
 if(activeView==="profile")return showProfile();
 if(activeView==="residents")return showResidents();
 if(activeView==="store")return showBusiness("store");
 if(activeView==="shopping")return showShoppingList(lastShoppingRecipe);
}
function jobRows(jobs){
 return jobs.length?jobs.map(job=>row((icons[job.recipe]||"📦")+" "+esc(data.recipes[job.recipe].name),
   number(job.quantity*data.recipes[job.recipe].output)+" шт.",
   '<time class="pill" data-job-ready="'+job.ready_at+'">'+formatTime(secondsLeft(job))+'</time>')).join(""):
   '<div class="empty">Производство пока не запущено</div>';
}
function formatTime(seconds){
 return seconds?Math.floor(seconds/60)+":"+String(seconds%60).padStart(2,"0"):"Готово";
}
function saleRow(item,quantity){
 const recipe=data.recipes[item];
 return row((icons[item]||"📦")+" "+esc(recipe.name),number(quantity)+" шт. на складе",
  input("qty-list-"+item)+'<input class="number-input" aria-label="Цена за штуку" id="price-'+item+'" type="number" min="1" max="100000" value="10">'+
  '<button class="btn gold" data-action="list" data-item="'+item+'">Продать</button>');
}
function showBusinessDirectory(){
 const entries=Object.entries(data.business_catalog).filter(([kind])=>kind!=="store");
 openPanel("🏢 Предприятия",entries.map(([kind,b])=>row(b.emoji+" "+esc(b.name),
  data.business_levels[kind]?"Уровень "+data.business_levels[kind]:b.min_reputation+" ⭐ для открытия",
  '<button class="btn" data-action="business" data-item="'+kind+'">Открыть карточку</button>')).join(""));
}
function showBusiness(kind){
 if(!data?.business_catalog[kind])return;
 activeBusiness=kind;
 const b=data.business_catalog[kind],level=data.business_levels[kind];
 const recipes=Object.entries(data.recipes).filter(([,recipe])=>recipe.business===kind);
 let body="";
 if(!level){
  const required=b.min_reputation;
  const ready=data.reputation>=required;
  body='<div class="empty">'+(ready?'Можно открыть бесплатно':'🔒 Репутация '+data.reputation+' / '+required)+'</div>'+
   '<button class="btn gold" data-action="open" data-item="'+kind+'" '+(ready?'':'disabled')+'>Открыть предприятие</button>';
 }else{
  body='<div class="badge-line"><span class="pill">Уровень '+level+'</span><span class="pill">Рецепты · '+recipes.length+'</span></div>';
 }
 body+=recipes.map(([item,recipe])=>{
  const needs=[
   ...Object.entries(recipe.needs).map(([key,n])=>[names[key],n,data.stock[key]||0]),
   ...Object.entries(recipe.needs_products||{}).map(([key,n])=>[data.recipes[key].name,n,data.products[key]||0])
  ];
  const max=Math.min(20,...needs.map(([,n,stock])=>Math.floor(stock/n)));
  const details=needs.map(([name,n,stock])=>esc(name)+' <b>'+stock+'/'+n+'</b>').join(" · ");
  const actions=level?(max?input("qty-craft-"+item,1,max)+'<button class="btn" data-action="produce" data-item="'+item+'">Произвести</button>':'')+
    '<button class="btn ghost" data-action="shopping" data-item="'+item+'">'+(max?'Сырьё':'Закупить')+'</button>':'';
  return row((icons[item]||"📦")+" "+esc(recipe.name),
   details+'<br>Партия '+recipe.output+' шт. · '+recipe.seconds+' сек.',actions);
 }).join("");
 if(level){
  const jobs=data.jobs.filter(job=>data.recipes[job.recipe]?.business===kind);
  if(jobs.length)body+='<h3 class="section-subtitle">В работе</h3>'+jobRows(jobs);
  const ready=recipes.filter(([item])=>data.products[item]>0);
  if(ready.length)body+='<h3 class="section-subtitle">Готовая продукция</h3>'+
   ready.map(([item])=>saleRow(item,data.products[item])).join("");
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
 let html="";
 html+=items.map((entry,i)=>{
  const missing=Math.max(0,entry.need-entry.stock);
  const name=entry.type==="raw"?esc(names[entry.item]):(icons[entry.item]||"📦")+" "+esc(data.recipes[entry.item]?.name||entry.item);
  const catalog=entry.type==="raw"?data.raw_catalog:data.city_catalog;
  const available=catalog?.[entry.item]?.quantity||0;
  const systemGrain=entry.type==="raw"&&entry.item==="grain";
  return row(name,"Нужно "+entry.need+" · На складе "+entry.stock+" · На рынке "+available+(systemGrain?" + запас системы":""),
  !missing?'<span class="pill">✅ Достаточно</span>':
  input("shopping-"+i,missing)+
  '<button class="btn" data-action="'+entry.type+'" data-item="'+esc(entry.item)+'" data-amount-id="shopping-'+i+'" '+(!systemGrain&&available<missing?'disabled':'')+'>Купить</button>');
 }).join("");
 html+='<p><button class="btn ghost" data-action="business" data-item="'+recipe.business+'">← Вернуться в '+esc(data.business_catalog[recipe.business].name)+'</button></p>';
 openPanel("🧺 Закупка для "+recipe.name,html);
}
function showMarket(){
 const categories={raw:"Сырьё",food:"Еда",products:"Готовая продукция",materials:"Материалы",animals:"Животные"};
 let html='<div class="city-market-tabs" aria-label="Категории">'+Object.entries(categories).map(([key,label])=>
   '<button type="button" class="btn ghost" aria-pressed="'+(key===marketCategory)+'" data-action="category" data-item="'+key+'">'+label+'</button>').join("")+'</div>';
 if(marketCategory==="animals"){
  const animals={chickens:"🐔 Курица",geese:"🪿 Гусыня",cows:"🐄 Корова",sheep:"🐑 Овца"};
  html+=Object.entries(animals).map(([item,label])=>{
   const offer=data.animal_catalog[item];
   return row(label,offer?number(offer.quantity)+' шт. у игроков · от '+number(offer.min_price)+' 🪙':"У игроков пока нет",
    '<a class="btn ghost city-link" href="/?market='+item+'">На ферму →</a>');
  }).join("");
  return openPanel("🧺 Рынок",html);
 }
 const raw=["raw","materials"].includes(marketCategory);
 const catalog=raw?{...data.raw_catalog,grain:data.raw_catalog.grain||{quantity:0,min_price:data.system_grain_price}}:data.city_catalog;
 const listed=Object.entries(catalog).filter(([item,offer])=>(offer.quantity>0||(raw&&item==="grain"))&&(raw?
  data.materials.includes(item)===(marketCategory==="materials"):
  data.food_items.includes(item)===(marketCategory==="food")));
 html+=listed.length?listed.map(([item,offer])=>row(raw?esc(names[item]):(icons[item]||"📦")+" "+esc(data.recipes[item].name),
   number(offer.quantity)+' шт. у игроков · от '+number(offer.min_price)+' 🪙'+(raw&&item==="grain"?' · запас системы':''),
   input("qty-market-"+item,1,raw&&item==="grain"?500:Math.min(offer.quantity,500))+'<button class="btn" data-action="'+(raw?"raw":"product")+'" data-item="'+item+'" data-amount-id="qty-market-'+item+'">Купить</button>')).join(""):
   '<div class="empty">Пока нет предложений</div>';
 openPanel("🧺 Рынок",html);
}
function showResidents(){
 const html=data.resident_orders.map(order=>{
  const owned=data.products[order.recipe]||0;
  return row((icons[order.recipe]||"📦")+" "+esc(data.recipes[order.recipe].name),
   'Нужно '+order.quantity+' · Есть '+owned+' · +'+order.reputation+' ⭐',
   order.done?'<span class="pill">Выполнен</span>':
   '<button class="btn gold" data-action="fulfill" data-item="'+esc(order.id)+'" '+(owned<order.quantity?'disabled':'')+'>'+(owned<order.quantity?'Не хватает товара':'Сдать')+'</button>');
 }).join("");
 openPanel("👥 Заказы жителей",html);
}
function showProfile(){
 activeBusiness=null;
 let html='<div class="badge-line"><span class="pill">👤 '+esc(data.name)+'</span><span class="pill">⭐ '+number(data.reputation)+'</span></div>';
 const finance=data.cashflow||{};
 html+='<h3 class="section-subtitle">📊 Финансы городских бизнесов</h3>';
 html+='<div class="mini-grid"><div class="mini-box"><small>📦 Закупки сырья</small><strong>'+number(finance.ingredient_spend||0)+' 🪙</strong></div><div class="mini-box"><small>🛍️ Покупки товаров</small><strong>'+number(finance.goods_purchases||0)+' 🪙</strong></div><div class="mini-box"><small>💰 Продажи товаров</small><strong>'+number(finance.goods_sales||0)+' 🪙</strong></div><div class="mini-box"><small>📈 Денежный поток</small><strong>'+number(finance.net||0)+' 🪙</strong></div></div>';
 html+='<h3 class="section-subtitle">🎁 Активировать промокод</h3>';
 html+='<form id="city-promo-form" class="city-promo-form"><input id="city-promo-input" aria-label="Промокод" autocomplete="off" spellcheck="false" maxlength="64" placeholder="FARM-…" required><button class="btn gold" type="submit">Получить награду</button></form>';
 html+='<p><a href="/" class="btn ghost" style="display:inline-block;text-decoration:none">🌾 Вернуться на ферму</a></p>';
 openPanel("👤 Мой профиль",html);
}
function showWarehouse(){
 let s='<h3 class="section-subtitle">Сырьё</h3><div class="mini-grid">';
 s+=Object.entries(names).map(([key,name])=>'<div class="mini-box"><small>'+name+'</small><strong>'+number(data.stock[key]||0)+'</strong></div>').join("")+'</div>';
 s+='<h3 class="section-subtitle">Готовая продукция</h3>';
 const products=Object.entries(data.products).filter(([key,n])=>n>0&&data.recipes[key]);
 s+=products.length?products.map(([key,n])=>saleRow(key,n)).join(""):'<div class="empty">Склад пока пуст</div>';
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
 if(action==="category"){marketCategory=item;return showMarket()}
 if(action==="market")return view("market");
 if(action==="shopping"){lastShoppingRecipe=item;return showShoppingList(item)}
 if(action==="business"){return showBusiness(item)}
 if(action==="open")path="/open";
 else if(action==="produce"){path="/produce";body.amount=getAmount("qty-craft-"+item);if(!body.amount)return}
 else if(action==="raw"){path="/buy-ingredient";body.amount=amount}
 else if(action==="product"){path="/buy-product";body.amount=amount}
 else if(action==="list"){path="/list-product";body.amount=getAmount("qty-list-"+item);body.price=Number($("price-"+item)?.value);if(!body.amount||!Number.isSafeInteger(body.price)||body.price<1||body.price>100000){toast("Укажи количество и цену");return}}
 else if(action==="cancel"){path="/cancel-product";body.listing_id=listingId}
 else if(action==="fulfill"){path="/fulfill-order";body.order_day=data.resident_orders.find(order=>order.id===item)?.day}
 else return;
 working=true;
 if(["raw","product","produce","list","cancel","fulfill"].includes(action)){
  body.request_id=(globalThis.crypto?.randomUUID?.()||(Date.now().toString(16)+Math.floor(Math.random()*1e15).toString(16)).padEnd(32,"a")).replaceAll("-","").slice(0,32);
 }
 if(action==="raw"||action==="product"){
  try{
   const quote=await api(action==="raw"?"/quote-ingredient":"/quote-product",{item,amount:body.amount});
   body.expected_cost=quote.cost;
   if(!confirm("Купить "+body.amount+" шт. за "+number(quote.cost)+" монет?")){working=false;return}
  }catch(e){toast(e.message);working=false;return}
 }
 try{await api(path,body);toast(action==="fulfill"?"Заказ выполнен! Репутация начислена.":action==="raw"?"Сырьё куплено на склад бизнеса!":action==="produce"?"Производство запущено!":action==="list"?"Товар выставлен в городе":action==="open"?"Предприятие открыто!":"Готово!");
 await load();
 }catch(e){toast(e.message)}
 finally{working=false}
}
document.querySelectorAll(".building").forEach(x=>x.addEventListener("click",()=>{if(data){activeView="business";showBusiness(x.dataset.business)}}));
document.querySelectorAll(".bottom-nav button").forEach(x=>x.addEventListener("click",()=>view(x.dataset.view)));
$("view-businesses").addEventListener("click",()=>view("businesses"));
$("view-orders").addEventListener("click",()=>view("warehouse"));
$("view-jobs").addEventListener("click",()=>view("jobs"));
$("view-residents").addEventListener("click",()=>view("residents"));
$("view-store").addEventListener("click",()=>view("store"));
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
window.addEventListener("telegram-sdk-ready",()=>{
 if(data)window.CityEntryAds?.maybeStart?.();
 else if(!token&&!$("city-auth").classList.contains("hidden"))loginTelegram();
});
setInterval(()=>{
 for(const timer of document.querySelectorAll("[data-job-ready]")){
  const remaining=secondsLeft({ready_at:Number(timer.dataset.jobReady)});
  timer.textContent=formatTime(remaining);
 }
},1000);
document.addEventListener("visibilitychange",()=>{
 if(data&&!working&&document.visibilityState==="visible")load().catch(()=>{});
});
setInterval(()=>{if(data&&!working&&!$("panel-body").contains(document.activeElement)&&document.visibilityState==="visible")load().catch(()=>{})},60000);
entry();
