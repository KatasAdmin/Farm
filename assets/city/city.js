"use strict";
const $=id=>document.getElementById(id);
const root="/api/city";
const names={eggs:"🥚 Яйца",grain:"🌾 Зерно",milk:"🥛 Молоко",feathers:"🪶 Перья",wool:"🧶 Шерсть"};
const icons={pancakes:"🥞",pie:"🥧",omelet:"🍳",cheese:"🧀",bread:"🍞",pillow:"🛏️",scarf:"🧣",breakfast_set:"🍱",dessert_box:"🍰",home_set:"🎁",lunch_box:"🥡",yogurt:"🥣"};
let token="",data=null,activeView="map",activeBusiness=null,working=false,lastShoppingRecipe=null;
let loading=null,jobTimer,marketCategory="raw",walletDetails=null,warehouseTab="raw";
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
let telegramPhoto="",photoLookup="";
const avatarSource=()=>data?.avatar_photo?.startsWith("data:image/jpeg;base64,")?data.avatar_photo:
 telegramPhoto||"/assets/city/tab-icon-0.webp";

async function loadTelegramPhoto(){
 const signed=tgData();
 if(!data||!signed||data.avatar_photo||photoLookup===signed)return;
 photoLookup=signed;
 try{
  const result=await api("/telegram-avatar",{telegram_data:signed});
  telegramPhoto=result.photo||"";
  $("district-avatar").querySelector("img").src=avatarSource();
  const profile=$("city-profile-photo");
  if(profile)profile.src=avatarSource();
 }catch{photoLookup=""}
}

async function changeAvatar(event){
 const field=event.target;
 const file=field.files[0];
 if(!file)return;
 field.value="";
 const url=URL.createObjectURL(file);
 try{
  const img=new Image();
  img.src=url;
  await img.decode();
  const canvas=document.createElement("canvas");
  canvas.width=canvas.height=256;
  const size=Math.min(img.naturalWidth,img.naturalHeight);
  canvas.getContext("2d").drawImage(img,(img.naturalWidth-size)/2,(img.naturalHeight-size)/2,size,size,0,0,256,256);
  await api("/avatar",{avatar_photo:canvas.toDataURL("image/jpeg",.72)});
  await load();
  toast("Фото профиля обновлено");
 }catch(error){toast(error.message||"Не удалось загрузить фото")}
 finally{URL.revokeObjectURL(url)}
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
 $("grain-count").textContent=number(data.stock?.grain||0);
 $("unread").textContent=number(data.progress?.unread);
 $("business-count").textContent=data.businesses.length+" / "+Object.keys(data.business_catalog).length;
 $("products-count").textContent=number(Object.values(data.products).reduce((a,b)=>a+b,0));
 $("orders-count").textContent=data.resident_orders.filter(order=>!order.done).length;
 $("completed-count").textContent=number(data.progress?.orders||0);
 document.body.classList.toggle("city-low-effects",data.preferences?.effects===false);
 $("district-profile").dataset.cosmetic=data.preferences?.cosmetic||"";
 $("district-name").textContent=data.name+(data.preferences?.cosmetic==="founder"?" ★":"");
 $("district-level").textContent="Ур. "+number(data.progress?.level)+" · "+number(data.progress?.xp)+" XP";
 document.querySelectorAll(".district-target[data-business]").forEach(button=>{
  const level=data.business_levels[button.dataset.business];
  button.classList.toggle("upgraded",level>1);
  button.querySelector("small").textContent=level?"Ур. "+level:"🔒";
 });
 const avatar=$("district-avatar");
 avatar.querySelector("img").src=avatarSource();
 loadTelegramPhoto();
 loadHomeSeason();
 const xp=$("district-xp");
 xp.max=data.progress?.next_xp||Math.max(1,data.progress?.xp||0);
 xp.value=data.progress?.xp||0;
 if(activeView!=="map")refreshPanel();
 clearTimeout(jobTimer);
 if(data.jobs.length)jobTimer=setTimeout(()=>{if(!working&&document.visibilityState==="visible")load().catch(()=>{})},Math.max(1000,secondsLeft(data.jobs[0])*1000+300));
}
const mainScreens=new Set(["profile","season","events","market","businesses","ranking","business","warehouse","residents"]);
let parentScreen="map",seasonSection="rewards",eventSection="current";

function openPanel(title,html){
 const body=$("panel-body");
 const samePanel=$("panel-heading").textContent===title;
 const values=new Map(samePanel?Array.from(body.querySelectorAll("input[id]"),el=>[el.id,el.value]):[]);
 const focused=document.activeElement?.id;
 const scrollTop=samePanel?body.scrollTop:0;
 $("panel-heading").textContent=title;
 body.dataset.scene=activeView;
 body.innerHTML=html;
 for(const input of body.querySelectorAll("input[id]")){
  if(values.has(input.id))input.value=values.get(input.id);
  if(samePanel&&input.id===focused)input.focus({preventScroll:true});
 }
 const primary=mainScreens.has(activeView);
 const page=$("city-page");
 $("city-home").hidden=primary;
 page.hidden=!primary;
 $("page-heading").textContent=title;
 (primary?page:document.querySelector(".city-panel")).append(body);
 $("panel-overlay").classList.toggle("hidden",primary);
 body.scrollTop=scrollTop;
}
function closePanel(){
 const target=mainScreens.has(parentScreen)?parentScreen:"map";
 parentScreen="map";
 activeBusiness=null;
 if(target!=="map"){view(target);return}
 activeView="map";
 $("panel-overlay").classList.add("hidden");
 $("city-page").hidden=true;
 $("city-home").hidden=false;
 document.querySelectorAll(".bottom-nav button").forEach(x=>x.classList.toggle("nav-active",x.dataset.view==="map"));
}
function row(name,details,actions){return '<div class="item-card"><div><strong>'+name+'</strong><small>'+details+'</small></div><div class="item-actions">'+actions+'</div></div>'}
function input(id,value=1,max=500){return '<input class="number-input" aria-label="Количество" id="'+id+'" type="number" min="1" max="'+max+'" value="'+value+'">'}
function quantityStep(id,max){
 return '<span class="quantity-step"><button type="button" data-action="quantity" data-item="-1" data-amount-id="'+id+'" aria-label="Уменьшить">−</button>'+
  input(id,1,Math.max(1,max))+'<button type="button" data-action="quantity" data-item="1" data-amount-id="'+id+'" aria-label="Увеличить">+</button></span>';
}
function getAmount(id){const field=$(id),n=Number(field?.value),max=Number(field?.max)||500;if(!Number.isSafeInteger(n)||n<1||n>max){toast("Введи количество от 1 до "+max);return null}return n}
function view(tab){
 if(!data)return;
 if(tab==="map"||mainScreens.has(tab))parentScreen="map";
 else if(mainScreens.has(activeView))parentScreen=activeView;
 const changed=activeView!==tab;
 activeView=tab;activeBusiness=null;
 if(changed&&mainScreens.has(tab))window.scrollTo(0,0);
 document.querySelectorAll(".bottom-nav button").forEach(x=>x.classList.toggle("nav-active",x.dataset.view===tab));
 if(tab==="map")closePanel();
 else if(["season","events","daily"].includes(tab))showGoals(tab);
 else if(tab==="ranking")showRanking("reputation");
 else if(tab==="wallet")showWallet(true);
 else refreshPanel();
}
function refreshPanel(){
 if(activeBusiness)return showBusiness(activeBusiness);
 if(activeView==="market")return showMarket();
 if(activeView==="jobs")return openPanel("⏱️ В производстве",jobRows(data.jobs));
 if(activeView==="businesses")return showBusinessDirectory();
 if(activeView==="warehouse")return showWarehouse();
 if(activeView==="profile")return showProfile();
 if(activeView==="wallet")return showWallet();
 if(activeView==="residents")return showResidents();
 if(activeView==="achievements")return showAchievements();
 if(activeView==="nutrition")return showNutrition();
 if(activeView==="settings")return showSettings();
 if(activeView==="promo")return openPanel("🎁 Промокод",promoForm);
 if(activeView==="help")return showHelp();
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
 if(data?.simple_economy){
  return row((icons[item]||"📦")+" "+esc(recipe.name),
    number(quantity)+" шт. · Продажа за "+data.system_prices.product[item].sell+" 🪙/шт.",
    input("qty-list-"+item,1,Math.min(quantity,500))+
    '<button class="btn gold" data-action="list" data-item="'+item+'">Продать сразу</button>');
 }
 return row((icons[item]||"📦")+" "+esc(recipe.name),number(quantity)+" шт. на складе",
  '<div class="sale-fields"><label>Количество'+input("qty-list-"+item)+'</label><label>Цена за штуку<input class="number-input" aria-label="Цена за штуку" id="price-'+item+'" type="number" min="1" max="100000" value="10"></label></div>'+
  '<button class="btn gold" data-action="list" data-item="'+item+'">Продать</button>');
}
function businessArt(kind,name,level){
 return '<div class="business-art"><img src="/assets/city/building-'+kind+'.webp" alt=""><div><strong>'+esc(name)+'</strong><small>'+
  (level?"Работает · уровень "+number(level):"Закрыто")+'</small></div></div>';
}
function showBusinessDirectory(){
 const entries=Object.entries(data.business_catalog);
 openPanel("Мои предприятия",'<div class="business-gallery">'+entries.map(([kind,b])=>
  '<button type="button" class="business-tile" data-action="business" data-item="'+kind+'">'+
  businessArt(kind,b.name,data.business_levels[kind])+
  '<span>'+ (data.business_levels[kind]?"Войти ›":data.simple_economy?number(b.open_cost)+" 🪙":number(b.min_reputation)+" репутации"+(b.feather_cost?" · "+b.feather_cost+" перьев":""))+
  '</span></button>').join("")+'</div>');
}
function showBusiness(kind){
 if(activeView!=="business")window.scrollTo(0,0);
 if(!data?.business_catalog[kind])return;
 activeView="business";
 activeBusiness=kind;
 const b=data.business_catalog[kind],level=data.business_levels[kind];
 const recipes=Object.entries(data.recipes).filter(([,recipe])=>recipe.business===kind);
 let body="";
 if(!level && data.simple_economy){
  const cost=b.open_cost;
  body='<div class="empty">🏢 Открытие '+esc(b.name)+' стоит '+number(cost)+' 🪙. Плата однократная; после открытия бизнес твой навсегда.</div>'+
   '<button class="btn gold" data-action="open" data-item="'+kind+'" '+(data.coins<cost?'disabled':'')+'>Открыть · '+number(cost)+' 🪙</button>';
 }else if(!level){
  const required=b.min_reputation;
  const feathers=b.feather_cost||0;
  const ready=data.reputation>=required&&(data.farm_feathers||0)>=feathers;
  body='<div class="empty">'+(ready?'✨ Условия выполнены — предприятие готово к открытию':'🔒 Нужно '+required+' ⭐ репутации'+(feathers?' и '+feathers+' 🪶 на ферме':'')+'. Сейчас '+data.reputation+' ⭐ и '+(data.farm_feathers||0)+' 🪶')+'</div>'+
   '<button class="btn gold" data-action="open" data-item="'+kind+'" '+(ready?'':'disabled')+'>🏙️ Открыть предприятие</button>'+(feathers?'<p class="city-help">🪶 Перья автоматически спишутся с фермы при открытии.</p>':'');
 }else{
  const price=data.business_upgrade_prices[kind];
  const capacity=data.business_batch_limits[kind];
  if(price!==undefined)body+=row("Улучшение до уровня "+(level+1),
   "Вместимость: "+capacity+" → "+Math.min(20,2*(level+1))+" партий · "+number(price)+" 🪙",
   '<button class="btn gold" data-action="upgrade" data-item="'+kind+'">Улучшить</button>');
  body+='<div class="badge-line"><span class="pill">Уровень '+level+'</span><span class="pill">Рецепты · '+recipes.length+'</span></div>';
 }
 body+=recipes.map(([item,recipe])=>{
  const needs=[
   ...Object.entries(recipe.needs).map(([key,n])=>[names[key],n,data.stock[key]||0]),
   ...Object.entries(recipe.needs_products||{}).map(([key,n])=>[data.recipes[key].name,n,data.products[key]||0])
  ];
  const max=Math.min(data.business_batch_limits[kind]||1,...needs.map(([,n,stock])=>Math.floor(stock/n)));
  const details=needs.map(([name,n,stock])=>esc(name)+' <b>'+stock+'/'+n+'</b>').join(" · ");
  const actions=level?(max?input("qty-craft-"+item,1,max)+'<button class="btn" data-action="produce" data-item="'+item+'">Произвести</button>':'')+
    '<button class="btn ghost" data-action="shopping" data-item="'+item+'">'+(max?'Сырьё':'Закупить')+'</button>':'';
  return row((icons[item]||"📦")+" "+esc(recipe.name),
   details+'<br>Партия '+recipe.output+' шт. · '+formatTime(recipe.seconds)
   +'<br>Оценка сырья: '+number(data.price_guides[item]?.batch_input_cost)+' 🪙 за партию · Рекомендация: '+number(data.price_guides[item]?.suggested_unit_price)+' 🪙/шт.' ,actions);
 }).join("");
 if(level){
  const jobs=data.jobs.filter(job=>data.recipes[job.recipe]?.business===kind);
  if(jobs.length)body+='<h3 class="section-subtitle">В работе</h3>'+jobRows(jobs);
  const ready=recipes.filter(([item])=>data.products[item]>0);
  if(ready.length)body+='<h3 class="section-subtitle">Готовая продукция</h3>'+
   ready.map(([item])=>saleRow(item,data.products[item])).join("");
 }
 openPanel(b.name,businessArt(kind,b.name,level)+body);
}
function simpleShoppingList(recipeId){
 const recipe=data.recipes[recipeId];if(!recipe)return;
 activeBusiness=null;activeView="shopping";
 let html='<p class="panel-note">🌾 С фермы в предприятие бесплатно. Если своих запасов мало, докупи у системы по фиксированной цене.</p>';
 html+=Object.entries(recipe.needs||{}).map(([item,required])=>{
  const stock=data.stock?.[item]||0,fromFarm=data.farm_stock?.[item]||0,short=Math.max(0,required-stock);
  const controls=short?
    (fromFarm?input("qty-transfer-"+item,Math.min(short,fromFarm),Math.min(500,fromFarm))+
     '<button class="btn ghost" data-action="transfer-to-city" data-item="'+item+'" data-amount-id="qty-transfer-'+item+'">Со своей фермы</button>':'')+
    input("qty-shop-"+item,short,500)+
    '<button class="btn" data-action="raw" data-item="'+item+'" data-amount-id="qty-shop-'+item+'">Купить · '+data.system_prices.raw_buy[item]+' 🪙/шт.</button>':
    '<span class="pill">✅ Хватает</span>';
  return row(names[item],'Для одной партии: '+required+' · В городе: '+stock+' · На ферме: '+fromFarm,controls);
 }).join("");
 html+=Object.entries(recipe.needs_products||{}).map(([item,required])=>row(
    (icons[item]||"📦")+" "+esc(data.recipes[item].name),
    'Нужно: '+required+' · На складе: '+(data.products[item]||0),
    input("qty-shop-"+item,required,500)+
    '<button class="btn" data-action="product" data-item="'+item+'" data-amount-id="qty-shop-'+item+'">Купить · '+data.system_prices.product[item].buy+' 🪙/шт.</button>'
 )).join("");
 html+='<button class="btn ghost" data-action="business" data-item="'+recipe.business+'">← Вернуться в '+esc(data.business_catalog[recipe.business].name)+'</button>';
 openPanel("🌾 Ингредиенты · "+recipe.name,html);
}
function simpleMarket(){
 const categories={raw:"Сырьё",materials:"Материалы",food:"Еда",products:"Товары",animals:"Животные"};
 let html='<div class="city-market-tabs">'+Object.entries(categories).map(([k,label])=>
  '<button class="btn ghost" data-action="category" data-item="'+k+'" aria-pressed="'+(marketCategory===k)+'">'+label+'</button>').join("")+'</div>'+
  '<p class="panel-note">🏪 Обычный магазин. Никаких продавцов и ожидания выкупа. Цена фиксирована, операция происходит сразу.</p>';
 if(marketCategory==="animals"){
  html+='<p class="panel-note">🐔 Животных можно сразу купить на ферме. Окупаемость зависит от кормления и использования продукции.</p>'+
  '<a class="btn city-link" href="/?market=chickens">Купить животных на ферме</a>';
 } else if(["raw","materials"].includes(marketCategory)){
  const keys=marketCategory==="materials"?["feathers","wool"]:["eggs","grain","milk"];
  html+=keys.map(item=>{
   const price=data.system_prices.raw_buy[item],payout=data.system_prices.raw_sell[item];
   const owned=data.stock?.[item]||0;
   return row(names[item],`Купить: '+price+' 🪙 · Продать: '+payout+' 🪙 · В городе: '+owned,
     input("qty-market-"+item,1,500)+
     '<button class="btn" data-action="raw" data-item="'+item+'" data-amount-id="qty-market-'+item+'">Купить</button>'+
     (owned?'<button class="btn gold" data-action="sell-raw" data-item="'+item+'" data-amount-id="qty-market-'+item+'">Продать сразу</button>':''));
  }).join("");
 }else{
  const food=marketCategory==="food";
  html+=Object.entries(data.recipes).filter(([item])=>data.food_items.includes(item)===food).map(([item,recipe])=>{
   const v=data.system_prices.product[item],owned=data.products[item]||0;
   return row((icons[item]||"📦")+" "+esc(recipe.name),
    'Купить: '+v.buy+' 🪙 · Продать: '+v.sell+' 🪙 · На складе: '+owned,
    input("qty-market-"+item,1,500)+
    '<button class="btn" data-action="product" data-item="'+item+'" data-amount-id="qty-market-'+item+'">Купить</button>'+
    (owned?'<button class="btn gold" data-action="sell-market-product" data-item="'+item+'" data-amount-id="qty-market-'+item+'">Продать сразу</button>':''));
  }).join("");
 }
 openPanel("🏪 Магазин",html);
}
function simpleWarehouse(){
 const tabs={raw:"Сырьё",products:"Продукция"};
 let html='<div class="city-market-tabs">'+Object.entries(tabs).map(([key,label])=>
  '<button class="btn ghost" aria-pressed="'+(warehouseTab===key)+'" data-action="warehouse-tab" data-item="'+key+'">'+label+'</button>').join("")+'</div>';
 if(warehouseTab==="raw"){
  html+='<p class="panel-note">Ресурсы бесплатно переходят между складами. Покупать собственные яйца, зерно или молоко больше не нужно.</p>';
  html+=Object.entries(data.system_prices.raw_buy).map(([item,price])=>{
   const farm=data.farm_stock[item]||0,city=data.stock[item]||0;
   return row(names[item],
     'Ферма: '+farm+' шт. · Город: '+city+' шт.',
     input("qty-move-"+item,1,500)+
     (farm?'<button class="btn" data-action="transfer-to-city" data-item="'+item+'" data-amount-id="qty-move-'+item+'">→ В город</button>':'')+
     (city?'<button class="btn ghost" data-action="transfer-to-farm" data-item="'+item+'" data-amount-id="qty-move-'+item+'">← На ферму</button>':'')+
     (city?'<button class="btn gold" data-action="sell-raw" data-item="'+item+'" data-amount-id="qty-move-'+item+'">Продать · '+data.system_prices.raw_sell[item]+' 🪙</button>':''));
  }).join("");
 }else{
  html+='<p class="panel-note">Готовый товар продаётся сразу. Еду можно переносить на ферму для сытости и ускорения производства.</p>';
  const goods=Object.entries(data.products).filter(([key,n])=>n>0&&data.recipes[key]);
  html+=goods.length?goods.map(([item,n])=>{
   const v=data.system_prices.product[item];
   return row((icons[item]||"📦")+" "+esc(data.recipes[item].name),
    'В городе: '+n+' шт. · Продажа: '+v.sell+' 🪙/шт.',
    input("qty-list-"+item,1,500)+
    '<button class="btn gold" data-action="list" data-item="'+item+'">Продать сразу</button>'+
    (data.food_items.includes(item)?'<button class="btn ghost" data-action="food-to-farm" data-item="'+item+'">→ На ферму</button>':''));
  }).join(""):'<div class="empty">Пока нет готовой продукции</div>';
  const farm=Object.entries(data.farm_food||{}).filter(([item,n])=>n>0&&data.food_items.includes(item));
  if(farm.length){
   html+='<h3 class="section-subtitle">🍽️ На фермерском складе</h3>';
   html+=farm.map(([item,n])=>row((icons[item]||"🍽️")+" "+esc(data.recipes[item].name),
    'На ферме: '+n+' шт.',input("qty-farm-food-"+item,1,500)+
    '<button class="btn ghost" data-action="food-to-city" data-item="'+item+'">← В город</button>')).join("");
  }
 }
 openPanel("📦 Мои склады",html);
}
function showShoppingList(recipeId){
 if(data?.simple_economy)return simpleShoppingList(recipeId);
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
 if(data?.simple_economy)return simpleMarket();
 const categories={raw:["Сырьё","resource-1"],food:["Еда","product-pancakes"],products:["Готовая продукция","profile-icon-1"],materials:["Материалы","resource-4"],animals:["Животные","resource-2"]};
 let html='<div class="city-scene market-scene"><img class="market-sign" src="/assets/city/market-sign.webp" alt="Рынок"><button class="btn ghost" data-action="market-lots">📦 Мои лоты</button></div><div class="city-market-tabs" aria-label="Категории">' +Object.entries(categories).map(([key,[label,art]])=>
   '<button type="button" class="btn ghost" aria-pressed="'+(key===marketCategory)+'" data-action="category" data-item="'+key+'"><img src="/assets/city/'+art+'.webp" alt="">'+label+'</button>').join("")+'</div>';
 if(marketCategory==="animals"){
  const animals={chickens:"🐔 Курица",geese:"🪿 Гусыня",cows:"🐄 Корова",sheep:"🐑 Овца"};
  html+=Object.entries(animals).map(([item,label])=>{
   const offer=data.animal_catalog[item];
   return row(label,offer?number(offer.quantity)+' шт. у игроков · от '+number(offer.min_price)+' 🪙':"У игроков пока нет",
    '<a class="btn ghost city-link" href="/?market='+item+'">На ферму →</a>');
  }).join("");
  return openPanel("🧺 Рынок",html);
 }
 if(marketCategory==="food")html+='<a class="btn ghost city-link city-food-link" href="/?food=1">🍽️ Купить еду на ферму →</a>';
 const raw=["raw","materials"].includes(marketCategory);
 const catalog=raw?Object.fromEntries((marketCategory==='materials'?['feathers','wool']:['eggs','grain','milk','feathers','wool']).map(item=>[item,data.raw_catalog[item]||{quantity:0,min_price:item==='grain'?data.system_grain_price:0}])):data.city_catalog;
 const resourceArt={eggs:0,grain:1,milk:2,feathers:3,wool:4};
 const listed=raw?Object.entries(catalog):Object.keys(data.recipes)
  .filter(item=>data.food_items.includes(item)===(marketCategory==="food"))
  .map(item=>[item,catalog[item]||{quantity:0}]);
 html+=listed.map(([item,offer])=>{
  const art=raw?"resource-"+resourceArt[item]:"product-"+item;
  const label=raw?names[item].split(" ").slice(1).join(" "):data.recipes[item].name;
  const available=offer.quantity>0||item==="grain";
  const count=offer.quantity?number(offer.quantity)+" шт. · "+number(offer.offers)+" лот.":item==="grain"?"Зерно системы":"Нет предложений";
  const price=available?'<span class="market-price"><img src="/assets/redesign/coin.webp" alt="">'+number(offer.min_price)+'</span>':"";
  return '<article class="market-line"><img class="product-art" src="/assets/city/'+art+'.webp" alt=""><div class="market-description"><strong>'+esc(label)+'</strong><small>'+count+'</small></div>'+price+
   '<div class="market-controls">'+quantityStep("qty-market-"+item,item==="grain"?500:Math.min(offer.quantity,500))+
   '<button class="btn market-buy" data-action="'+(raw?"raw":"product")+'" data-item="'+item+'" data-amount-id="qty-market-'+item+'" '+(available?"":"disabled")+'><img src="/assets/city/menu-0.webp" alt="">Купить</button>'+
   (!raw&&data.products[item]?'<button class="btn ghost market-sell" data-action="sell-product" data-item="'+item+'"><img src="/assets/city/menu-4.webp" alt="">Продать</button>':"")+'</div></article>';
 }).join("");
 const offerCount=listed.reduce((sum,[,offer])=>sum+Number(offer.offers||0),0);
 html+='<div class="market-summary"><img src="/assets/city/profile-icon-1.webp" alt=""><span><strong>Сводка рынка</strong><small>Предложения игроков · '+number(offerCount)+' лот.'+'</small></span><b aria-hidden="true">›</b></div>';
 openPanel("🧺 Рынок",html);
}
function showResidents(){
 const html=data.resident_orders.map(order=>{
  const owned=data.products[order.recipe]||0;
  return row((icons[order.recipe]||"📦")+" "+esc(data.recipes[order.recipe].name),
   'Нужно '+order.quantity+' · Есть '+owned+' · +'+order.reputation+' ⭐',
   order.done?'<span class="pill">Выполнен</span>':
   owned<order.quantity?'<button class="btn ghost" data-action="order-market" data-item="'+esc(order.recipe)+'">Купить недостающее</button>':
   '<button class="btn gold" data-action="fulfill" data-item="'+esc(order.id)+'">Выполнить</button>');
 }).join("");
 openPanel("👥 Заказы жителей",html);
}
async function showWallet(fetchDetails=false){
 const quote=walletDetails?.quote,history=walletDetails?.history;
 const balance='<div class="wallet-hero"><img src="/assets/redesign/coin.webp" alt="" class="wallet-hero-coin"><span>Единый баланс TREVIXO</span><strong>'+number(data.coins)+' <small>монет</small></strong></div>';
 const actions='<div class="profile-links"><a class="btn gold city-link" href="/?wallet=1">Пополнение</a><a class="btn city-link" href="/?wallet=1">Вывод</a></div>';
 const details=quote?row("Курс монеты",esc(quote.nominal_coin_price_uah)+" грн","")+
  row("Капитализация",number(quote.capitalization_kopeks/100)+" грн · "+number(quote.total_coins)+" монет в обращении","")+
  row("Бонусные монеты",number(quote.bonus_coins),""):"";
 const logs=history?'<h3>Последние операции</h3>'+(history.entries.length?history.entries.map(entry=>
  row(esc(entry.details||entry.kind),new Date(entry.created*1000).toLocaleString("ru-RU"),
   '<span class="pill">'+(entry.delta>0?"+":"")+number(entry.delta)+' 🪙</span>')).join(""):'<p class="empty">Операций пока нет</p>'):"";
 openPanel("🪙 Мой кошелёк",balance+actions+details+logs);
 if(!fetchDetails)return;
 try{
  const [quote,history]=await Promise.all([api("/api/farm/exchange/quote"),api("/api/finance?limit=10")]);
  if(activeView!=="wallet")return;
  walletDetails={quote,history};
  showWallet();
 }catch(error){if(activeView==="wallet")toast(error.message)}
}

function showNutrition(){
 const nutrition=data.nutrition;
 const html=row("Сытость",nutrition.fullness+"% · Бонус фермы +"+nutrition.bonus_percent+"%","")+
  '<p class="city-help">Сытость снижается на '+nutrition.decay_per_hour+' п. п. в час.</p>'+
  '<div class="profile-links"><button class="btn gold" data-action="order-market" data-item="bread">Рынок еды</button>'+
  '<a class="btn city-link" href="/?food=1">Питание на ферме</a></div>';
 openPanel("🍽️ Питание",html);
}
const progressNames={production:"Производство завершено",production_xp:"Первая партия дня",
 upgrade:"Улучшение предприятия",order:"Заказ жителя выполнен",achievement:"Достижение открыто",sale:"Товар продан"};

async function showProgressLog(reputationOnly){
 view(reputationOnly?"reputation":"notifications");
 const current=activeView;
 const title=reputationOnly?"⭐ Репутация":"🔔 Уведомления";
 openPanel(title,'<p class="city-help" role="status">Загрузка…</p>');
 try{
  const events=await api("/progress-log");
  if(activeView!==current)return;
  const visible=reputationOnly?events.filter(event=>event.reputation>0):events;
  const businesses=reputationOnly?Object.entries(data.business_catalog).map(([key,business])=>
   row(esc(business.name),data.business_levels[key]?"Открыто":
    business.min_reputation+" ⭐"+(business.feather_cost?" · "+business.feather_cost+" 🪶":""),"")).join(""):"";
  openPanel(title,businesses+(visible.length?visible.map(event=>
   row(esc(progressNames[event.kind]||event.kind),
    new Date(event.created*1000).toLocaleString("ru-RU")+(event.xp?" · +"+event.xp+" XP":"")+
     (event.reputation?" · +"+event.reputation+" ⭐":""),"")).join(""):
   '<p class="empty">История пока пуста</p>'));
  const unread=visible.filter(event=>!event.read);
  if(!reputationOnly&&unread.length){
   await api("/read-progress-log",unread.map(event=>event.source));
   $("unread").textContent=number(Math.max(0,(data.progress?.unread||0)-unread.length));
  }
 }catch(error){if(activeView===current)openPanel(title,'<p class="empty">'+esc(error.message)+'</p>')}
}

const goalTitles={season:"Сезон",events:"События",daily:"Ежедневные задания"};

let homeSeasonRequested=false;
async function loadHomeSeason(){
 if(homeSeasonRequested)return;
 homeSeasonRequested=true;
 try{
  const {campaigns}=await api("/goals");
  const season=campaigns.find(period=>period.kind==="season"&&period.active);
  if(!season){$("district-pass-progress").hidden=true;return;}
  const milestones=season.rewards||[];
  const target=milestones.find(goal=>goal.goal>season.xp)?.goal||milestones.at(-1)?.goal||1;
  const meter=$("district-pass-progress");
  meter.innerHTML='<progress aria-label="Сезонный опыт" max="'+target+'" value="'+season.xp+'"></progress><small>'+number(season.xp)+' / '+number(target)+' XP</small>';
  meter.hidden=false;
 }catch{homeSeasonRequested=false}
}

async function showGoals(tab){
 const title=goalTitles[tab];
 if(!title)return;
 openPanel(title,'<p class="city-help" role="status">Загрузка…</p>');
 try{
  const snapshot=await api("/goals");
  if(activeView!==tab)return;
  const now=Date.now()/1000;
  let periods=tab==="daily"?[snapshot.daily]:snapshot.campaigns.filter(period=>
   period.kind===(tab==="season"?"season":"event"));
  const dailyCount=snapshot.daily.goals.filter(goal=>goal.claimed).length;
  let html="";
  if(tab==="events"){
   const featured=periods.find(period=>period.active);
   periods=periods.filter(period=>eventSection==="history"?period.ends<=now:period.active&&period!==featured);
   html='<div class="event-intro">Временные активности и особые задания</div>'+
    '<div class="event-feature"><img src="/assets/city/event-gift.webp" alt=""><div><small>'+(featured?"Главное событие":"Афиша города")+'</small><strong>'+
    (featured?esc(featured.name):"Скоро новые события")+'</strong>'+
    (featured?'<button class="btn" data-action="featured-event">Участвовать ›</button>':"")+'</div></div>'+
    '<div class="season-switch"><button class="btn" data-action="event-section" data-item="current" aria-pressed="'+(eventSection==="current")+'">Текущие</button><button class="btn" data-action="event-section" data-item="history" aria-pressed="'+(eventSection==="history")+'">Завершённые</button></div>';
   if(featured&&eventSection==="current")periods.unshift(featured);
  }
  html+=periods.map(period=>{
   const hours=Math.max(0,Math.ceil((period.ends-Date.now()/1000)/3600));
   const date=Math.floor(hours/24)+" дн. "+hours%24+" ч.";
   const heading='<div class="campaign-hero city-scene"><strong>'+esc(period.name||"Цели дня")+'</strong><small>'+
    (period.active?"До "+date:period.starts*1000>Date.now()?"Скоро":"Завершено")+'</small>'+
    (period.description?'<p>'+esc(period.description)+'</p>':"")+
    (period.kind==="season"?'<p>Уровень '+period.level+' · '+number(period.xp)+' сезонного XP</p>':"")+'</div>';
   const item=(goal,details)=>row(esc(goal.name),details,goal.claimed?'<span class="pill">Получено</span>':
    goal.available?'<button class="btn" data-action="claim-goal" data-item="'+esc(goal.key)+'" data-listing-id="'+esc(period.id)+'">Получить</button>':"");
   const goals=period.goals.map(goal=>item(goal,number(Math.min(goal.value,goal.goal))+" / "+number(goal.goal)+" · +"+goal.xp+" XP")).join("");
   if(tab==="events"){
    const metric=period.goals[0]?.key;
    const art=metric==="raw"?"harvest":metric==="upgrades"?"building":metric==="pancakes"||metric==="batches"?"cooking":"gift";
    return '<article class="event-entry"><img src="/assets/city/event-'+art+'.webp" alt=""><div><strong>'+esc(period.name)+'</strong><small>'+
     (period.active?"До конца: "+date:"Завершено")+'</small>'+(period.description?'<p>'+esc(period.description)+'</p>':"")+'</div><div class="event-goals">'+goals+'</div></article>';
   }
   if(!period.rewards)return heading+goals;
   const premiumRewards=Array.isArray(period.premium)?period.premium:[];
   const premiumCards=Array.from({length:5},(_,index)=>premiumRewards[index]?
    '<article><img src="/assets/city/'+(index?"profile-icon-5":"tab-icon-1")+'.webp" alt=""><strong>'+esc(premiumRewards[index])+'</strong><small>Закрыто</small></article>':
    '<article class="reward-placeholder"><span class="reward-threshold">Ур. '+(Number(period.level||1)+index-1)+'</span><strong>Награда сезона</strong><small>Закрыто</small></article>').join("");
   const freeCards=Array.from({length:5},(_,index)=>{
    const goal=period.rewards[index];
    if(!goal)return '<article class="reward-placeholder"><span class="reward-threshold">Ур. '+(Number(period.level||1)+index-1)+'</span><strong>Награда сезона</strong><small>Откроется позже</small></article>';
    return '<article><span class="reward-threshold">'+number(goal.goal)+' XP</span><img src="/assets/city/'+["profile-icon-5","profile-icon-4","ref-chest"][index%3]+'.webp" alt="">'+
     item(goal,goal.available||goal.claimed?"":"Закрыто")+'</article>';
   }).join("");
   const rewards='<div class="reward-board"><div class="reward-rail premium-track"><header><img src="/assets/city/tab-icon-1.webp" alt=""><strong>Премиум</strong><small>Закрыто</small></header>'+premiumCards+
    '</div><div class="reward-rail free-track"><header><img src="/assets/city/profile-icon-4.webp" alt=""><strong>Бесплатно</strong></header>'+freeCards+'</div></div>';
   const next=period.rewards.find(goal=>goal.goal>period.xp)?.goal||period.rewards.at(-1)?.goal||1;
   const tabs='<div class="season-switch"><button class="btn" data-action="season-section" data-item="rewards" aria-pressed="'+(seasonSection==="rewards")+'">Награды сезона</button><button class="btn" data-action="season-section" data-item="tasks" aria-pressed="'+(seasonSection==="tasks")+'">Задания сезона</button></div>';
   const feature=period.rewards.at(-1);
   const lead='<div class="season-lead"><img src="/assets/city/tab-icon-1.webp" alt=""><strong>'+esc(period.name)+'</strong><small>'+
    (period.active?"До конца сезона: "+date:period.ends<=now?"Завершён":"Скоро")+'</small></div>'+
    (feature?'<div class="season-feature"><small>Главная награда сезона</small><strong>'+esc(feature.name)+'</strong></div>':"");
   return lead+'<div class="season-meter"><strong>Ур. '+period.level+'</strong><progress aria-label="Опыт сезона" value="'+period.xp+'" max="'+next+'"></progress><small>'+period.xp+' / '+next+' XP</small></div>'+tabs+(seasonSection==="tasks"?goals:rewards);
  }).join("");
  if(tab==="events"){
   if(!periods.length&&eventSection==="history")html+='<p class="empty">Завершённых событий пока нет</p>';
   const dailyGoals=snapshot.daily.goals||[];
   html+='<section class="daily-event-card"><img src="/assets/city/evening-chest.webp" alt=""><div><small>Обновление каждый день</small><strong>Ежедневные события</strong><p>Выполни задания дня и получи сундук!</p><div class="daily-event-progress"><progress max="'+Math.max(1,dailyGoals.length)+'" value="'+dailyCount+'" aria-label="Прогресс дня"></progress><b>'+dailyCount+' / '+dailyGoals.length+'</b></div></div><button class="btn" data-action="navigate" data-item="daily">Смотреть задания ›</button></section>'+
    (dailyGoals.length?'<div class="daily-goals">'+dailyGoals.map(goal=>row(esc(goal.name),number(Math.min(goal.value,goal.goal))+' / '+number(goal.goal)+' · +'+number(goal.xp)+' XP',goal.claimed?'<span class="pill">Получено</span>':goal.available?'<button class="btn" data-action="claim-goal" data-item="'+esc(goal.key)+'" data-listing-id="'+esc(snapshot.daily.id)+'">Получить</button>':'')).join('')+'</div>':'');
  }
  openPanel(title,html||'<div class="empty">Скоро новый сезон</div>');
 }catch(error){if(activeView===tab)openPanel(title,'<p class="empty">'+esc(error.message)+'</p>')}
}

function showAchievements(){
 const entries=data.achievements||[];
 openPanel("🏆 Достижения",entries.map(entry=>row(esc(entry.name),
  esc(entry.description)+" · "+number(Math.min(entry.value,entry.goal))+" / "+number(entry.goal),
  '<span class="pill">'+(entry.done?"Получено":"+"+entry.xp+" XP")+'</span>')).join(""));
}

const rankingLabels={reputation:"Репутация",orders:"Заказы",production:"Производство",sales:"Продажи",level:"Уровень"};

async function showRanking(category){
 const tabs='<div class="city-market-tabs">'+Object.entries(rankingLabels).map(([key,label])=>
  '<button class="btn ghost" aria-pressed="'+(category===key)+'" data-action="ranking" data-item="'+key+'">'+label+'</button>').join("")+'</div>';
 openPanel("📈 Рейтинг города",tabs+'<p role="status">Загрузка…</p>');
 try{
  const entries=await api("/ranking?category="+category);
  if(activeView!=="ranking"||!document.querySelector('[data-item="'+category+'"][aria-pressed="true"]'))return;
  openPanel("📈 Рейтинг города",tabs+(entries.length?entries.map((entry,index)=>
   row((index+1)+". "+esc(entry.name),number(entry.score),"")).join(""):'<p class="empty">В этой категории пока нет результатов</p>'));
 }catch(error){if(activeView==="ranking")toast(error.message)}
}

function showSettings(){
 const settings=data.preferences||{effects:true,cosmetic:""};
 openPanel("⚙️ Настройки",'<form id="city-settings"><p><label><input id="city-effects" type="checkbox" '+
  (settings.effects?"checked":"")+'> Визуальные эффекты</label></p><p><label>Оформление профиля <select id="city-cosmetic">'+
  [{id:"",name:"Стандартное"},...(data.cosmetics||[])].map(item=>'<option value="'+esc(item.id)+'" '+
  (item.id===settings.cosmetic?"selected":"")+'>'+esc(item.name)+'</option>').join("")+
  '</select></label></p><button class="btn" type="submit">Сохранить</button></form>');
}

async function saveSettings(event){
 event.preventDefault();
 if(working)return;
 working=true;
 try{
  await api("/preferences",{effects:$("city-effects").checked,cosmetic:$("city-cosmetic").value});
  await load();toast("Настройки сохранены");
 }catch(error){toast(error.message)}finally{working=false}
}

function showHelp(){
 openPanel("❔ Первые шаги",'<ol class="city-tutorial"><li><button class="btn ghost" data-action="navigate" data-item="businesses">Открой пекарню</button></li><li><button class="btn ghost" data-action="navigate" data-item="market">Купи сырьё</button></li><li>Выбери рецепт на предприятии, запусти партию и дождись её завершения.</li><li><button class="btn ghost" data-action="navigate" data-item="warehouse">Выставь готовый товар со склада</button></li><li><button class="btn ghost" data-action="navigate" data-item="residents">Выполни заказ жителя</button></li><li>Заказы дают репутацию для открытия предприятий. XP повышает уровень города.</li></ol>');
}

const promoForm='<form id="city-promo-form" class="city-promo-form"><input id="city-promo-input" aria-label="Промокод" autocomplete="off" spellcheck="false" maxlength="64" placeholder="FARM-…" required><button class="btn gold" type="submit">Получить награду</button></form>';

function showProfile(){
 const avatar='<button type="button" class="profile-avatar avatar-picker" data-action="avatar-picker" aria-label="Сменить фото профиля"><img id="city-profile-photo" src="'+esc(avatarSource())+'" alt=""></button>';
 const progress=data.progress||{};
 const stats=[
  [5,"Репутация",number(data.reputation),"reputation"],
  [1,"Бизнесы",number(data.businesses.length),"businesses"],
  [2,"Выполнено заказов",number(progress.orders),"residents"],
  [6,"Рейтинг города","# 112","ranking"]
 ];
 const links=[["businesses","🏪","Мои бизнесы"],["warehouse","📦","Склад"],
  ["residents","📋","Заказы жителей"],["market","🧺","Магазин"],
  ["promo","🎁","Промокод"],["achievements","🏆","Достижения"],["settings","⚙️","Настройки"],["help","❔","Помощь"]];
 const card=(target,icon,label,value="",index=null)=>'<button class="stat" data-action="navigate" data-item="'+target+'"><i aria-hidden="true"><img src="/assets/city/profile-icon-'+(index===null?icon:index)+'.webp" alt=""></i><span>'+label+'</span>'+(value?'<strong>'+value+'</strong>':"")+'</button>';
 const hero='<div class="profile-hero"><button type="button" class="profile-edit" data-action="avatar-picker" aria-label="Сменить фото профиля">✎</button>'+avatar+'<div><strong>'+esc(data.name)+'</strong><span>Горожанин · Ур. '+number(progress.level)+'</span>'+
  '<progress aria-label="Опыт города" max="'+(progress.next_xp||Math.max(1,progress.xp||0))+'" value="'+(progress.xp||0)+'"></progress><small>'+number(progress.xp)+(progress.next_xp?" / "+number(progress.next_xp):"")+' XP</small></div></div>';
 const wallet='<div class="profile-balance"><img src="/assets/city/ref-wallet.webp" alt=""><span>Баланс<strong>'+number(data.coins)+'</strong></span><button class="btn" data-action="wallet">Кошелёк ›</button></div>';
 openPanel("Кабинет",hero+'<div class="profile-stats">'+stats.map(([icon,label,value,target])=>card(target,icon,label,value)).join("")+'</div>'+
  wallet+'<div class="profile-menu">'+links.map(([target,icon,label],index)=>card(target,icon,label,"",index)).join("")+'</div>'+
  '<button class="season-banner" data-action="navigate" data-item="season"><img class="banner-treasure" src="/assets/city/ref-chest.webp" alt=""><span>Сезон города<small>Выполняй задания, получай награды<br>и развивай свой город!</small></span><b>К сезону ›</b></button>');
}
function showWarehouse(){
 if(data?.simple_economy)return simpleWarehouse();
 const tabs={raw:"Сырьё",products:"Готовая продукция",lots:"Мои объявления"};
 let html='<div class="city-market-tabs">'+Object.entries(tabs).map(([key,label])=>
  '<button class="btn ghost" aria-pressed="'+(warehouseTab===key)+'" data-action="warehouse-tab" data-item="'+key+'">'+label+'</button>').join("")+'</div>';
 if(warehouseTab==="raw"){
  html+='<div class="mini-grid">'+Object.entries(names).map(([key,name])=>
   '<div class="mini-box"><small>'+name+'</small><strong>'+number(data.stock[key]||0)+'</strong></div>').join("")+'</div>';
 }else if(warehouseTab==="products"){
  const products=Object.entries(data.products).filter(([key,n])=>n>0&&data.recipes[key]);
  html+=products.length?products.map(([key,n])=>saleRow(key,n)).join(""):'<div class="empty">Склад пока пуст</div>';
 }else{
  html+=data.my_city_offers.length?data.my_city_offers.map(lot=>row(
   (icons[lot.item]||"📦")+" "+esc(data.recipes[lot.item]?.name||lot.item),
   "Осталось "+number(lot.quantity)+" шт. · "+number(lot.price)+" 🪙/шт."+
    (lot.sold!==null?" · Продано "+number(lot.sold)+" шт. · Выручка "+number(lot.revenue)+" 🪙":""),
   '<button class="btn danger" data-action="cancel" data-listing-id="'+esc(lot.id)+'">Снять</button>'
  )).join(""):'<div class="empty">Активных объявлений пока нет</div>';
 }
 openPanel("📦 Склад бизнеса",html);
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
 if(action==="quantity"){
  const field=$(amountId);
  field.value=Math.max(1,Math.min(Number(field.max),Number(field.value||1)+Number(item)));
  return;
 }
 const amount=amountId?getAmount(amountId):null;
 if(amountId&&amount===null)return;
 let path,body={item};
 if(action==="claim-goal"){
  working=true;
  try{await api("/claim-goal",{scope:listingId,key:item});homeSeasonRequested=false;await load();await showGoals(activeView)}
  catch(error){toast(error.message)}finally{working=false}
  return;
 }
 if(action==="avatar-picker"){$("city-avatar-file").click();return}
 if(action==="featured-event"){document.querySelector(".event-entry")?.scrollIntoView({block:"start"});return}
 if(action==="event-section"){eventSection=item;return showGoals("events")}
 if(action==="season-section"){seasonSection=item;return showGoals("season")}
 if(action==="market-lots"){warehouseTab="lots";return view("warehouse")}
 if(action==="warehouse-tab"){warehouseTab=item;return showWarehouse()}
 if(action==="sell-product"){warehouseTab="products";view("warehouse");$("qty-list-"+item)?.focus();return}
 if(action==="ranking")return showRanking(item);
 if(action==="navigate"){if(item==="reputation")return showProgressLog(true);return view(item)}
 if(action==="order-market"){
  marketCategory=data.food_items.includes(item)?"food":"products";
  view("market");
  $("qty-market-"+item)?.focus();
  return;
 }
 if(action==="wallet")return view("wallet");
 if(action==="category"){marketCategory=item;return showMarket()}
 if(action==="market")return view("market");
 if(action==="shopping"){lastShoppingRecipe=item;return showShoppingList(item)}
 if(action==="business"){return showBusiness(item)}
 if(action==="upgrade"){
  const price=data.business_upgrade_prices[item],level=data.business_levels[item];
  if(price===undefined||!confirm("Улучшить до уровня "+(level+1)+" за "+number(price)+" монет?"))return;
  path="/upgrade-business";body.expected_cost=price;
 }
 else if(action==="open")path="/open";
 else if(action==="produce"){path="/produce";body.amount=getAmount("qty-craft-"+item);if(!body.amount)return}
 else if(action==="raw"){path="/buy-ingredient";body.amount=amount}
 else if(action==="product"){path="/buy-product";body.amount=amount}
 else if(action==="list"){path="/list-product";body.amount=getAmount("qty-list-"+item);body.price=Number($("price-"+item)?.value);if(!body.amount||!Number.isSafeInteger(body.price)||body.price<1||body.price>100000){toast("Укажи количество и цену");return}if(!confirm("Выставить "+body.amount+" шт. на "+number(body.amount*body.price)+" монет?"))return}
 else if(action==="cancel"){if(!confirm("Снять объявление и вернуть остаток на склад?"))return;path="/cancel-product";body.listing_id=listingId}
 else if(action==="fulfill"){path="/fulfill-order";body.order_day=data.resident_orders.find(order=>order.id===item)?.day}
 else return;
 working=true;
 if(["raw","product","produce","list","cancel","fulfill","upgrade"].includes(action)){
  body.request_id=(globalThis.crypto?.randomUUID?.()||(Date.now().toString(16)+Math.floor(Math.random()*1e15).toString(16)).padEnd(32,"a")).replaceAll("-","").slice(0,32);
 }
 if(action==="raw"||action==="product"){
  try{
   const quote=await api(action==="raw"?"/quote-ingredient":"/quote-product",{item,amount:body.amount});
   body.expected_cost=quote.cost;
   if(!confirm("Купить "+body.amount+" шт. за "+number(quote.cost)+" монет?")){working=false;return}
  }catch(e){toast(e.message);working=false;return}
 }
 try{await api(path,body);toast(action==="fulfill"?"Заказ выполнен! Репутация начислена.":action==="raw"?"Сырьё куплено на склад бизнеса!":action==="produce"?"Производство запущено!":action==="list"?"Товар на рынке · смотри в «Мои лоты»":action==="open"?"Предприятие открыто!":"Готово!");
 await load();
 }catch(e){toast(e.message)}
 finally{working=false}
}
document.querySelectorAll(".district-target[data-business]").forEach(x=>x.addEventListener("click",()=>{if(data){activeView="business";showBusiness(x.dataset.business)}}));
document.querySelectorAll(".bottom-nav button").forEach(x=>x.addEventListener("click",()=>view(x.dataset.view)));
document.querySelectorAll("[data-city-screen]").forEach(button=>button.addEventListener("click",()=>view(button.dataset.cityScreen)));
$("district-profile").addEventListener("click",()=>view("profile"));
$("district-pass").addEventListener("click",()=>view("season"));
$("map-warehouse").addEventListener("click",()=>view("warehouse"));
$("view-reputation").addEventListener("click",()=>showProgressLog(true));
$("view-notifications").addEventListener("click",()=>showProgressLog(false));
$("view-grain-market").addEventListener("click",()=>{marketCategory="raw";view("market")});
$("view-businesses").addEventListener("click",()=>view("businesses"));
$("view-orders").addEventListener("click",()=>view("warehouse"));
$("view-jobs").addEventListener("click",()=>view("jobs"));
$("view-residents").addEventListener("click",()=>view("residents"));
$("view-market").addEventListener("click",()=>view("market"));
$("view-store").addEventListener("click",()=>view("store"));
$("open-city-wallet").addEventListener("click",()=>view("wallet"));
$("close-panel").addEventListener("click",closePanel);
$("panel-backdrop").addEventListener("click",closePanel);
document.addEventListener("keydown",e=>{if(e.key==="Escape")closePanel()});
$("panel-body").addEventListener("submit",e=>{
 if(e.target.id==="city-promo-form")redeemPromo(e);
 if(e.target.id==="city-settings")saveSettings(e);
});
$("panel-body").addEventListener("click",e=>{
 const button=e.target.closest("button[data-action]");if(!button)return;
 action(button.dataset.action,button.dataset.item,button.dataset.amountId,button.dataset.listingId)
});
$("city-avatar-file").addEventListener("change",changeAvatar);
$("auth-form").addEventListener("submit",loginPassword);
$("telegram-login").addEventListener("click",loginTelegram);
window.addEventListener("telegram-sdk-ready",()=>{
 if(data){loadTelegramPhoto();window.CityEntryAds?.maybeStart?.();}
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
