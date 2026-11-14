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
 const baseXp=data.progress?.level_xp||0;
 xp.max=Math.max(1,(data.progress?.next_xp||baseXp)-baseXp);
 xp.value=Math.max(0,(data.progress?.xp||0)-baseXp);
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
 $("panel-overlay").dataset.scene=activeView;
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
 syncCityBack();
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
 syncCityBack();
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
 else if(["season","events","daily","story"].includes(tab))showGoals(tab);
 else if(tab==="bonus")showBonus();
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
 if(activeView==="status")return showCityStatus();
 if(activeView==="settings")return showSettings();
 if(activeView==="account")return showAccount();
 if(activeView==="promo")return openPanel("Промокод",promoForm);
 if(activeView==="help")return showHelp();
 if(activeView==="store")return showBundles();
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
    '<button class="btn gold" data-action="list" data-item="'+item+'">Продать</button>');
 }
 return row((icons[item]||"📦")+" "+esc(recipe.name),number(quantity)+" шт. на складе",
  '<div class="sale-fields"><label>Количество'+input("qty-list-"+item)+'</label><label>Цена за штуку<input class="number-input" aria-label="Цена за штуку" id="price-'+item+'" type="number" min="1" max="100000" value="10"></label></div>'+
  '<button class="btn gold" data-action="list" data-item="'+item+'">Продать</button>');
}
function businessArt(kind,name,level){
 const stage=kind==="bakery"?Math.min(level,4):
  ["restaurant","dairy","atelier"].includes(kind)?(level>=5?3:level>=3?2:1):0;
 const art=level&&stage?"scenes/"+kind+"-"+stage:"building-"+kind;
 return '<div class="business-art'+(level&&stage&&kind!=="bakery"?' business-painted':'')+'"><img src="/assets/city/'+art+'.webp" alt=""><div><strong>'+esc(name)+'</strong><small>'+
  (level?"Работает · уровень "+number(level):"Закрыто")+'</small></div></div>';
}
function citySectionArt(title,description,art){
 return '<header class="city-section-art" data-art="'+art+'"><h3>'+title+'</h3><p>'+description+'</p></header>';
}
function showBusinessDirectory(){
 const entries=Object.entries(data.business_catalog);
 openPanel("Мои предприятия",citySectionArt("Предприятия","Развивай город от пекарни до ателье.","district")+'<div class="business-gallery">'+entries.map(([kind,b])=>
  '<button type="button" class="business-tile" data-action="business" data-item="'+kind+'">'+
  businessArt(kind,b.name,data.business_levels[kind])+
  '<span>'+ (data.business_levels[kind]?"Войти ›":data.simple_economy?(data.reputation<b.min_reputation?"🔒 "+number(b.min_reputation)+" статуса":number(b.open_cost)+" 🪙"):number(b.min_reputation)+" репутации"+(b.feather_cost?" · "+b.feather_cost+" перьев":""))+
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
  const requirement=b.min_reputation||0;
  const predecessor=b.requires_business;
  const missing=Math.max(0,requirement-data.reputation);
  const prerequisite=predecessor&&!data.business_levels[predecessor];
  if(missing||prerequisite){
   const locked='<section class="city-lock"><h3>Предприятие недоступно</h3>'+
    (requirement?'<p>Доступно с '+number(requirement)+' городского статуса</p><progress aria-label="Городской статус" max="'+requirement+'" value="'+Math.min(data.reputation,requirement)+'"></progress><p>Ваш статус: '+number(data.reputation)+' / '+number(requirement)+' · Осталось: '+number(missing)+'</p>':'')+
    (prerequisite?'<p>Сначала открой: '+esc(data.business_catalog[predecessor].name)+'</p>':'')+
    '<button class="p3-button" data-action="navigate" data-item="status">Как повысить статус</button></section>';
   return openPanel(b.name,businessArt(kind,b.name,level)+locked);
  }
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
 let html='<p class="panel-note">Предприятие берёт ингредиенты с общего склада.</p>';
 html+=Object.entries(recipe.needs||{}).map(([item,required])=>{
  const stock=data.stock?.[item]||0,short=Math.max(0,required-stock);
  const controls=short?
    input("qty-shop-"+item,short,500)+
    '<button class="btn" data-action="raw" data-item="'+item+'" data-amount-id="qty-shop-'+item+'">Купить · '+data.system_prices.raw_buy[item]+' 🪙/шт.</button>':
    '<span class="pill">✅ Хватает</span>';
  return row(names[item],'Для одной партии: '+required+' · На складе: '+stock,controls);
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
const tradeArt={eggs:"/assets/redesign/egg.webp",grain:"/assets/redesign/grain.webp",
 milk:"/assets/milk-v1.webp",feathers:"/assets/illustrations/feather-icon-v3.webp"};
function illustratedTradeRow(name,item,details,actions){
 const art=tradeArt[item]||"/assets/city/product-"+encodeURIComponent(item)+".webp";
 return '<article class="city-trade-art"><img src="'+art+'" alt="" loading="lazy" onerror="this.onerror=null;this.src=\'/assets/city/profile-icon-1.webp\'"><div><strong>'+name+'</strong><small>'+details+'</small></div><div class="item-actions">'+actions+'</div></article>';
}
function simpleMarket(){
 const categories={raw:"Сырьё",materials:"Материалы",food:"Еда",products:"Товары",animals:"Животные"};
 let html='<div class="city-market-tabs">'+Object.entries(categories).map(([k,label])=>
  '<button class="btn ghost" data-action="category" data-item="'+k+'" aria-pressed="'+(marketCategory===k)+'">'+label+'</button>').join("")+'</div>'+
  '';
 if(marketCategory==="animals"){
  html+='<p class="panel-note">🐔 Животных можно сразу купить на ферме. Окупаемость зависит от кормления и использования продукции.</p>'+
  '<a class="btn city-link" href="/?market=chickens">Купить животных на ферме</a>';
 } else if(["raw","materials"].includes(marketCategory)){
  const keys=marketCategory==="materials"?["feathers","wool"]:["eggs","grain","milk"];
  html+=keys.map(item=>{
   const price=data.system_prices.raw_buy[item],payout=data.system_prices.raw_sell[item];
   const owned=data.stock?.[item]||0;
   return illustratedTradeRow(names[item],item,'Купить: '+price+' 🪙 · Продать: '+payout+' 🪙 · На складе: '+owned,
     input("qty-market-"+item,1,500)+
     '<button class="btn" data-action="raw" data-item="'+item+'" data-amount-id="qty-market-'+item+'">Купить</button>'+
     (owned?'<button class="btn gold" data-action="sell-raw" data-item="'+item+'" data-amount-id="qty-market-'+item+'">Продать</button>':''));
  }).join("");
 }else{
  const food=marketCategory==="food";
  html+=Object.entries(data.recipes).filter(([item])=>data.food_items.includes(item)===food)
   .sort(([keyA],[keyB])=>data.system_prices.product[keyA].buy-data.system_prices.product[keyB].buy||
     keyA.localeCompare(keyB,"ru")).map(([item,recipe])=>{
   const v=data.system_prices.product[item],owned=data.products[item]||0;
   return illustratedTradeRow(esc(recipe.name),item,
    'Купить: '+v.buy+' 🪙 · Продать: '+v.sell+' 🪙 · На складе: '+owned,
    input("qty-market-"+item,1,500)+
    '<button class="btn" data-action="product" data-item="'+item+'" data-amount-id="qty-market-'+item+'">Купить</button>'+
    (owned?'<button class="btn gold" data-action="sell-market-product" data-item="'+item+'" data-amount-id="qty-market-'+item+'">Продать</button>':''));
  }).join("");
 }
 openPanel("Рынок",citySectionArt("Рынок","Покупай и продавай по фиксированным ценам.","market")+html);
}
function simpleWarehouse(){
 const tabs={raw:"Сырьё",materials:"Материалы",food:"Еда",products:"Товары"};
 let html='<div class="city-market-tabs">'+Object.entries(tabs).map(([key,label])=>
  '<button class="btn ghost" aria-pressed="'+(warehouseTab===key)+'" data-action="warehouse-tab" data-item="'+key+'">'+label+'</button>').join("")+'</div>';
 if(warehouseTab==="raw"||warehouseTab==="materials"){
  html+=Object.keys(data.system_prices.raw_buy).filter(item=>["feathers","wool"].includes(item)===(warehouseTab==="materials")).map(item=>{
   const stock=data.stock[item]||0;
   return illustratedTradeRow(names[item],item,'В наличии: '+stock+' шт.',stock?
     input("qty-stock-"+item,1,Math.min(stock,500))+
     '<button class="btn gold" data-action="sell-raw" data-item="'+item+'" data-amount-id="qty-stock-'+item+'">Продать · '+data.system_prices.raw_sell[item]+' 🪙</button>':'');
  }).join("");
 }else{
  html+='<p class="panel-note">Один общий запас еды и продукции для города и фермы. Покупки, производство и продажи сразу меняют количество в обоих разделах.</p>';
  const goods=Object.entries(data.products).filter(([key,n])=>n>0&&data.recipes[key]&&Boolean(data.food_items?.includes(key))===(warehouseTab==="food"))
    .sort(([a],[b])=>data.system_prices.product[a].buy-data.system_prices.product[b].buy||
      a.localeCompare(b,"ru"));
  html+=goods.length?goods.map(([item,n])=>{
   const v=data.system_prices.product[item];
   return illustratedTradeRow(esc(data.recipes[item].name),item,
    'В наличии: '+n+' шт. · Продажа: '+v.sell+' 🪙/шт.',
    input("qty-list-"+item,1,500)+
    '<button class="btn gold" data-action="list" data-item="'+item+'">Продать</button>');
  }).join(""):'<div class="empty">Пока нет готовой продукции</div>';
 }
 openPanel("Общий склад",citySectionArt("Склад","Ресурсы фермы и города в одном месте.","warehouse")+html);
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

const goalTitles={season:"Сезон",events:"События",daily:"Ежедневные задания",story:"Развитие города"};

let homeGoalsRequest;
function loadGoals(){
 if(!homeGoalsRequest)homeGoalsRequest=api("/goals").then(snapshot=>{
  const ready=snapshot.daily.goals.some(goal=>goal.available&&!goal.claimed);
  $("city-task-alert").hidden=!ready;
  return snapshot;
 }).finally(()=>{homeGoalsRequest=null});
 return homeGoalsRequest;
}
const premiumArt="/assets/city/premium3/";
const illustratedIcon=(name, fallback)=>'<img class="p3-icon" src="'+premiumArt+name+'.webp" alt="" onerror="this.onerror=null;this.src=\'/assets/city/'+fallback+'.webp\'">';
const paintedButton=(label,action,item,active)=>'<button class="p3-button" data-action="'+action+'" data-item="'+item+'"'+(active===undefined?'':' aria-pressed="'+active+'"')+'>'+label+'</button>';
async function showBundles(){
 const title="Лавка наборов";
 openPanel(title,'<p class="city-help" role="status">Загрузка…</p>');
 try{
  const {offers}=await api("/bundles");
  if(activeView!=="store")return;
  openPanel(title,citySectionArt("Лавка наборов","Покупки за игровые монеты.","festival")+
   (offers.length?offers.map(offer=>row(esc(offer.name),
    number(offer.chickens)+" кур · "+number(offer.grain)+" зерна · Осталось покупок: "+number(offer.remaining),
    '<button class="p3-button p3-gold" data-action="buy-bundle" data-item="'+esc(offer.id)+'" data-price="'+Number(offer.price)+'">Купить · '+number(offer.price)+' 🪙</button>')).join(""):'<p class="empty">Сейчас доступных наборов нет</p>'));
 }catch(error){if(activeView==="store")openPanel(title,'<p class="empty">'+esc(error.message)+'</p>')}
}
async function buySeasonPass(season){
 const telegram=window.Telegram?.WebApp;
 if(!telegram?.openInvoice){toast("Открой оплату в Telegram");return}
 working=true;
 try{
  const {url}=await api("/pass-invoice",{item:season});
  const status=await new Promise(resolve=>telegram.openInvoice(url,resolve));
  if(status==="paid"||status==="pending"){
   for(let attempt=0;attempt<5;attempt++){
    const snapshot=await loadGoals();
    if(snapshot.campaigns.find(period=>period.id===season)?.pass_owned){
     toast("Городской пропуск активирован");
     if(activeView==="season")await showGoals("season");
     return;
    }
    await new Promise(resolve=>setTimeout(resolve,1200));
   }
   toast("Ожидаем подтверждение от Telegram. Пропуск появится в сезоне после оплаты.");
  }else if(status==="failed")toast("Telegram не подтвердил оплату");
 }catch(error){toast(error.message)}finally{working=false}
}
function showBonus(){
 openPanel("Бонусы",'<section class="p3-scene-art p3-painted-bonus"><div class="scene-copy"><h3>Награды города</h3><p>Забери награды сезона или введи промокод.</p></div><div class="p3-painted-actions">'+
 paintedButton("Награды сезона","navigate","season")+paintedButton("Ввести промокод","navigate","promo")+'</div></section><button class="p3-button" data-action="navigate" data-item="store">Лавка наборов</button>');
}
const goalDestinations={batches:["factory","businesses"],raw:["supplies","market"],sales:["stall","warehouse"],orders:["resident","residents"],upgrades:["factory","businesses"]};
function illustratedGoal(goal,period,painted=false){
 const [art,destination]=goalDestinations[goal.key]||["scroll",period.id==="story"?"businesses":null];
 const ready=goal.available&&!goal.claimed;
 const next=goal.claimed?'<span class="p3-claimed">Получено</span>':ready?
 '<button class="p3-button p3-gold" data-action="claim-goal" data-item="'+esc(goal.key)+'" data-listing-id="'+esc(period.id)+'">Получить</button>':
 goal.business&&period.active?'<button class="p3-arrow" aria-label="Открыть предприятие" data-action="business" data-item="'+esc(goal.business)+'">›</button>':
 destination&&period.active?'<button class="p3-arrow" aria-label="Перейти к заданию: '+esc(goal.name)+'" data-action="navigate" data-item="'+destination+'">›</button>':'';
 return '<article class="p3-goal">'+(painted?"":illustratedIcon(art,"menu-2"))+'<div><strong>'+esc(goal.name)+'</strong><small>'+number(Math.min(goal.value,goal.goal))+" / "+number(goal.goal)+" · +"+number(goal.xp)+' XP'+(goal.status?' · +'+number(goal.status)+' статуса':'')+'</small></div>'+next+'</article>';
}
function periodTimer(period,prefix){
 if(!period.active)return '<span class="p3-time">'+(period.ends<=Date.now()/1000?"Завершено":"Скоро")+'</span>';
 return '<time class="p3-time" data-period-end="'+Number(period.ends)+'" data-period-prefix="'+prefix+'">'+periodTime(period.ends,prefix)+'</time>';
}
function periodTime(end,prefix){
 const minutes=Math.max(0,Math.ceil((end-Date.now()/1000)/60));
 const days=Math.floor(minutes/1440),hours=Math.floor(minutes%1440/60);
 return minutes?prefix+(days?days+" дн. ":"")+(days||hours?hours+" ч. ":minutes+" мин."):"Завершено";
}
function illustratedSeason(period){
 const onRewards=seasonSection==="rewards";
 const tabs='<div class="p3-season-tabs">'+paintedButton("Награды сезона","season-section","rewards",onRewards)+paintedButton("Задания сезона","season-section","tasks",!onRewards)+'</div>';
 const feature=period.rewards.at(-1);
 const rewardArt=key=>key==="reward:gold"?"frame":key==="reward:violet"?"violet-frame":"trophy";
 const next=period.rewards.find(goal=>goal.goal>period.xp)?.goal||feature?.goal||1;
 const rewardStatus=goal=>goal.claimed?"Получено":goal.available?"Доступно":"Закрыто";
 const rewards='<div class="p3-rewards"><div class="p3-reward-track p3-premium-track"><header>'+illustratedIcon("crown","tab-icon-1")+'<strong>Премиум</strong></header>'+
 (period.premium||[]).map((goal,index)=>typeof goal==="string"?'<article><strong>'+esc(goal)+'</strong><small>Закрыто</small></article>':
 '<article>'+illustratedIcon(index?"trophy":"frame","tab-icon-1")+'<b>'+number(goal.goal)+' XP</b><strong>'+esc(goal.name)+'</strong><small>'+rewardStatus(goal)+'</small>'+
 (goal.available&&!goal.claimed?'<button class="p3-button p3-gold" data-action="claim-goal" data-item="'+esc(goal.key)+'" data-listing-id="'+esc(period.id)+'">Забрать</button>':'')+'</article>').join("")+
 (period.pass_owned?'<p class="pass-state">Пропуск активен</p>':period.pass_stars?'<button class="p3-button p3-gold pass-state" data-action="season-pass" data-item="'+esc(period.id)+'">Купить пропуск · '+number(period.pass_stars)+' ⭐</button>':'')+
 '</div><div class="p3-reward-track"><header>'+illustratedIcon("season-gift","event-gift")+'<strong>Бесплатно</strong></header>'+period.rewards.map(goal=>
 '<article><b>'+number(goal.goal)+' XP</b>'+illustratedIcon(rewardArt(goal.key),"event-gift")+'<strong>'+esc(goal.name)+'</strong><small>'+rewardStatus(goal)+'</small>'+
 (goal.available&&!goal.claimed?'<button class="p3-button p3-gold" data-action="claim-goal" data-item="'+esc(goal.key)+'" data-listing-id="'+esc(period.id)+'">Забрать</button>':'')+
 '</article>').join("")+'</div></div>';
 return '<section class="p3-season"><div class="p3-scene-art p3-painted-season"><h2 class="scene-title">Сезон</h2><h3 class="scene-name">'+esc(period.name)+'</h3>'+periodTimer(period,"До конца: ")+
 (feature?'<div class="scene-reward"><small>Главная награда сезона</small><h3>'+esc(feature.name)+'</h3></div>':"")+
 '<div class="p3-meter"><b>Ур. '+number(period.level)+'</b><progress aria-label="Опыт сезона" value="'+Number(period.xp)+'" max="'+Number(next)+'"></progress><span>'+number(period.xp)+' / '+number(next)+' XP</span></div>'+tabs+
 '</div>'+(onRewards?rewards:'<div class="p3-goals">'+period.goals.map(goal=>illustratedGoal(goal,period)).join("")+'</div>')+'</section>';
}
async function loadHomeSeason(){
 try{
  const {campaigns}=await loadGoals();
  const season=campaigns.find(period=>period.kind==="season"&&period.active);
  if(!season){$("district-pass-progress").hidden=true;return;}
  const milestones=season.rewards||[];
  const target=milestones.find(goal=>goal.goal>season.xp)?.goal||milestones.at(-1)?.goal||1;
  const meter=$("district-pass-progress");
  meter.innerHTML='<progress aria-label="Сезонный опыт" max="'+target+'" value="'+season.xp+'"></progress><small>'+number(season.xp)+' / '+number(target)+' XP</small>';
  meter.hidden=false;
 }catch{}
}

async function showGoals(tab){
 const title=goalTitles[tab];
 if(!title)return;
 openPanel(title,'<p class="city-help" role="status">Загрузка…</p>');
 try{
  const snapshot=await loadGoals();
  if(activeView!==tab)return;
  const now=Date.now()/1000;
  let periods=tab==="daily"?[snapshot.daily]:snapshot.campaigns.filter(period=>
   period.kind===(tab==="season"?"season":"event"));
  const dailyCount=snapshot.daily.goals.filter(goal=>goal.claimed).length;
  let html="";
  if(tab==="events"){
   const featured=periods.find(period=>period.active);
   periods=periods.filter(period=>eventSection==="history"?period.ends<=now:period.active&&period!==featured);
   html=citySectionArt("События","Временные активности и особые задания.","festival")+
    '<div class="event-feature"><img src="/assets/city/event-gift.webp" alt=""><div><small>'+(featured?"Главное событие":"Афиша города")+'</small><strong>'+
    (featured?esc(featured.name):"Скоро новые события")+'</strong>'+
    (featured?'<button class="btn" data-action="featured-event">Участвовать ›</button>':"")+'</div></div>'+
    '<div class="season-switch"><button class="btn" data-action="event-section" data-item="current" aria-pressed="'+(eventSection==="current")+'">Текущие</button><button class="btn" data-action="event-section" data-item="history" aria-pressed="'+(eventSection==="history")+'">Завершённые</button></div>';
   if(featured&&eventSection==="current")periods.unshift(featured);
  }
  if(tab==="story"){
   const period=snapshot.story;
   if(!period)return openPanel(title,'<p class="empty">Развитие города недоступно</p>');
   return openPanel(title,citySectionArt("Развитие города","Открывай предприятия, выпускай товары и получай городской статус.","district")+
    '<div class="p3-goals">'+period.goals.map(goal=>illustratedGoal(goal,period)).join("")+'</div>');
  }
  if(tab==="daily"){
   const tabs=snapshot.story?'<div class="city-task-links">'+paintedButton("Сюжетные","navigate","story")+
    '<a class="p3-button" href="/?tasks=1">Недельные</a>'+paintedButton("Особые","navigate","events")+'</div>':'';
   const period=snapshot.daily;
   const painted=period.goals.length===4&&period.goals.every((goal,index)=>goal.key===["batches","raw","sales","orders"][index]);
   if(painted)return openPanel(title,'<div class="p3-scene-art p3-painted-daily"><div class="scene-copy"><h3>Цели дня</h3>'+periodTimer(period,"До ")+'</div><div class="p3-goals">'+period.goals.map(goal=>illustratedGoal(goal,period,true)).join("")+'</div></div>'+tabs);
   return openPanel(title,'<div class="p3-banner p3-daily"><h3>Цели дня</h3>'+periodTimer(period,"До ")+'</div><div class="p3-goals">'+period.goals.map(goal=>illustratedGoal(goal,period)).join("")+'</div>'+tabs);
  }
  if(tab==="season"){
   const season=periods.find(period=>period.active)||periods[0];
   return openPanel(title,season?[season,...periods.filter(period=>period!==season)].map(illustratedSeason).join(''):'<div class="empty">Скоро новый сезон</div>');
  }
  html+=periods.map(period=>{
   const hours=Math.max(0,Math.ceil((period.ends-now)/3600));
   const date=Math.floor(hours/24)+" дн. "+hours%24+" ч.";
   const metric=period.goals[0]?.key;
   const art=metric==="raw"?"harvest":metric==="upgrades"?"building":metric==="pancakes"||metric==="batches"?"cooking":"gift";
   return '<article class="event-entry"><img src="/assets/city/event-'+art+'.webp" alt=""><div><strong>'+esc(period.name)+'</strong><small>'+
    (period.active?"До конца: "+date:"Завершено")+'</small>'+(period.description?'<p>'+esc(period.description)+'</p>':"")+'</div><div class="event-goals">'+period.goals.map(goal=>illustratedGoal(goal,period)).join("")+'</div></article>';
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

function showAccount(){
 const current=data.account||{};
 openPanel("Настройки игрового аккаунта",'<div class="city-account-forms">'+
  '<form id="city-name-form"><label>Ник<input name="name" minlength="2" maxlength="22" autocomplete="nickname" value="'+esc(data.name)+'" required></label><button class="p3-button">Сохранить ник</button></form>'+
  '<form id="city-password-form">'+(current.has_password?'<label>Текущий пароль<input name="current_password" type="password" autocomplete="current-password" required></label>':'')+
  '<label>Новый пароль<input name="password" type="password" minlength="8" maxlength="128" autocomplete="new-password" required></label><button class="p3-button">Сохранить пароль</button></form>'+
  (current.telegram_linked?'<p>Telegram привязан ✓</p>':'<button class="p3-button" data-action="link-account">Привязать Telegram</button>')+
  '<button class="p3-button" data-action="avatar-picker">Сменить фото</button></div>');
}
async function saveAccount(event){
 event.preventDefault();
 if(working)return;
 const form=event.target;
 const changingName=form.id==="city-name-form";
 working=true;
 try{
  const values=Object.fromEntries(new FormData(form));
  await api(changingName?"/api/nickname/set":"/api/password/set",changingName?{name:values.name.trim()}:values);
  form.reset();
  await load();
  toast(changingName?"Ник изменён":"Пароль сохранён");
 }catch(error){toast(error.message)}finally{working=false}
}
async function linkCityAccount(){
 working=true;
 try{
  const signed=tgData();
  if(signed){
   await api("/api/telegram/link",{telegram_data:signed});
   await load();
   toast("Telegram привязан");
  }else{
   const result=await api("/api/telegram/link/start",{});
   if(result.linked){await load();return}
   if(window.Telegram?.WebApp?.openTelegramLink)window.Telegram.WebApp.openTelegramLink(result.url);
   else location.assign(result.url);
   toast("Подтверди привязку в боте командой Start");
  }
 }catch(error){toast(error.message)}finally{working=false}
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

const promoForm='<div class="p3-scene-art p3-painted-promo"><form id="city-promo-form" class="city-promo-form"><input id="city-promo-input" aria-label="Промокод" autocomplete="off" spellcheck="false" maxlength="64" placeholder="FARM-…" required><button class="p3-button p3-gold" type="submit">Получить награду</button></form></div>';

function showCityStatus(){
 const next=Object.values(data.business_catalog).filter(b=>b.min_reputation>data.reputation).sort((a,b)=>a.min_reputation-b.min_reputation)[0];
 openPanel("Городской статус",'<section class="city-lock"><h3>'+number(data.reputation)+' статуса</h3>'+
  (next?'<p>Следующий порог: '+esc(next.name)+' · '+number(next.min_reputation)+'</p>':'')+
  '<p>Выполняй заказы жителей: за каждый заказ начисляется статус, а список обновляется ежедневно. Товары для первых заказов можно купить на рынке.</p>'+
  '<button class="p3-button" data-action="navigate" data-item="residents">Заказы жителей</button></section>');
}
function showProfile(){
 const avatar='<button type="button" class="profile-avatar avatar-picker" data-action="avatar-picker" aria-label="Сменить фото профиля"><img id="city-profile-photo" src="'+esc(avatarSource())+'" alt=""></button>';
 const progress=data.progress||{};
 const stats=[
  [5,"Городской статус",number(data.reputation),"status"],
  [1,"Бизнесы",number(data.businesses.length),"businesses"],
  [2,"Выполнено заказов",number(progress.orders),"residents"],
  [6,"Рейтинг города","","ranking"]
 ];
 const links=[["businesses","🏪","Мои бизнесы"],["warehouse","📦","Склад"],
  ["residents","📋","Заказы жителей"],["market","🧺","Рынок"],
  ["promo","🎁","Промокод"],["achievements","🏆","Достижения"],["settings","⚙️","Настройки"],["help","❔","Помощь"]];
 const card=(target,icon,label,value="",index=null)=>'<button class="stat" data-action="navigate" data-item="'+target+'"><i aria-hidden="true"><img src="/assets/city/profile-icon-'+(index===null?icon:index)+'.webp" alt=""></i><span>'+label+'</span>'+(value?'<strong>'+value+'</strong>':"")+'</button>';
 const hero='<div class="profile-hero" data-cosmetic="'+esc(data.preferences?.cosmetic||"")+'"><span class="profile-edit-mark" aria-hidden="true">✎</span>'+avatar+'<div class="profile-live"><strong>'+esc(data.name)+'</strong><span>Горожанин · Ур. '+number(progress.level)+'</span>'+
  '<progress aria-label="Опыт аккаунта" max="'+Math.max(1,(progress.next_xp||0)-(progress.level_xp||0))+'" value="'+Math.max(0,(progress.xp||0)-(progress.level_xp||0))+'"></progress><small>'+number(progress.xp)+(progress.next_xp?" / "+number(progress.next_xp):"")+' XP</small></div></div>';
 const wallet='<div class="profile-balance"><img src="/assets/city/ref-wallet.webp" alt=""><span>Баланс<strong>'+number(data.coins)+'</strong></span><button class="btn" data-action="wallet">Кошелёк ›</button></div>';
 openPanel("Кабинет",'<section class="city-profile-art">'+hero+'<div class="profile-stats">'+stats.map(([icon,label,value,target])=>card(target,icon,label,value)).join("")+'</div>'+
  wallet+'<div class="profile-menu">'+links.map(([target,icon,label],index)=>card(target,icon,label,"",index)).join("")+'</div>'+
  '<div class="profile-links"><button class="p3-button" data-action="navigate" data-item="account">Настройки игрового аккаунта</button></div>'+
  '<button class="season-banner" data-action="navigate" data-item="season"><img class="banner-treasure" src="/assets/city/ref-chest.webp" alt=""><span>Сезон города<small>Выполняй задания, получай награды<br>и развивай свой город!</small></span><b>К сезону ›</b></button></section>');
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
 event.target.querySelector('button').disabled=true;
 try{
   const result=await api("/api/promo/redeem",{code});
   toast("🎁 Промокод принят! +"+number(result.awarded)+" монет");
   await load();
 }catch(error){toast(error.message||"Не удалось активировать промокод")}
 finally{working=false;event.target.querySelector('button').disabled=false}
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
 if(action==="season-pass")return buySeasonPass(item);
 if(action==="buy-bundle"){
  const price=Number(document.querySelector('[data-action="buy-bundle"]')?.dataset.price);
  if(!Number.isSafeInteger(price)||price<=0||!confirm("Купить набор за "+number(price)+" монет?"))return;
  working=true;
  try{
   await api("/api/bundle",{item,request_id:crypto.randomUUID().replaceAll("-","")});
   await load();
   toast("Набор получен. Животные и зерно уже на ферме.");
  }catch(error){toast(error.message)}finally{working=false}
  return;
 }
 if(action==="claim-goal"){
  working=true;
  try{await api("/claim-goal",{scope:listingId,key:item});await load();await showGoals(activeView)}
  catch(error){toast(error.message)}finally{working=false}
  return;
 }
 if(action==="link-account")return linkCityAccount();
 if(action==="avatar-picker"){$("city-avatar-file").click();return}
 if(action==="featured-event"){document.querySelector(".event-entry")?.scrollIntoView({block:"start"});return}
 if(action==="event-section"){eventSection=item;return showGoals("events")}
 if(action==="season-section"){seasonSection=item;return showGoals("season")}
 if(action==="market-lots"){warehouseTab="lots";return view("warehouse")}
 if(action==="warehouse-tab"){warehouseTab=item;return showWarehouse()}
 if(action==="sell-product"){warehouseTab=data.simple_economy&&data.food_items?.includes(item)?"food":"products";view("warehouse");$("qty-list-"+item)?.focus();return}
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
 else if(action==="open"){
  path="/open";
  if(data.simple_economy){
   const price=data.business_catalog[item].open_cost;
   if(!confirm("Открыть предприятие за "+number(price)+" монет?"))return;
   body.expected_cost=price;
  }
 }
 else if(action==="produce"){path="/produce";body.amount=getAmount("qty-craft-"+item);if(!body.amount)return}
 else if(action==="raw"){path="/buy-ingredient";body.amount=amount}
 else if(action==="product"){path="/buy-product";body.amount=amount}
 else if(action==="list"){
  path="/list-product";body.amount=getAmount("qty-list-"+item);
  if(!body.amount)return;
  if(data.simple_economy){
   const unit=data.system_prices.product[item].sell;
   if(!confirm("Продать системе "+body.amount+" шт. сразу за "+number(body.amount*unit)+" монет?"))return;
  }else{
   body.price=Number($("price-"+item)?.value);
   if(!Number.isSafeInteger(body.price)||body.price<1||body.price>100000){toast("Укажи цену");return}
   if(!confirm("Выставить "+body.amount+" шт. на "+number(body.amount*body.price)+" монет?"))return;
  }
 }
 else if(action==="food-to-farm"||action==="food-to-city"){
  path="/transfer-product";
  body.amount=getAmount(action==="food-to-farm"?"qty-list-"+item:"qty-farm-food-"+item);
  body.destination=action==="food-to-farm"?"to_farm":"to_city";
  if(!body.amount)return;
 }
 else if(action==="sell-raw"||action==="sell-market-product"){
  path=action==="sell-raw"?"/sell-ingredient":"/list-product";
  body.amount=amount;
  if(!body.amount)return;
  const price=action==="sell-raw"?data.system_prices.raw_sell[item]:data.system_prices.product[item].sell;
  if(!confirm("Продать "+body.amount+" шт. сразу за "+number(body.amount*price)+" монет?"))return;
 }
 else if(action==="cancel"){if(!confirm("Снять объявление и вернуть остаток на склад?"))return;path="/cancel-product";body.listing_id=listingId}
 else if(action==="fulfill"){path="/fulfill-order";body.order_day=data.resident_orders.find(order=>order.id===item)?.day}
 else return;
 working=true;
 if(["raw","product","produce","list","cancel","fulfill","upgrade","food-to-farm","food-to-city","sell-raw","sell-market-product"].includes(action)){
  body.request_id=(globalThis.crypto?.randomUUID?.()||(Date.now().toString(16)+Math.floor(Math.random()*1e15).toString(16)).padEnd(32,"a")).replaceAll("-","").slice(0,32);
 }
 if(action==="raw"||action==="product"){
  try{
   const quote=await api(action==="raw"?"/quote-ingredient":"/quote-product",{item,amount:body.amount});
   body.expected_cost=quote.cost;
   if(!confirm("Купить "+body.amount+" шт. за "+number(quote.cost)+" монет?")){working=false;return}
  }catch(e){toast(e.message);working=false;return}
 }
 try{await api(path,body);toast(action==="fulfill"?"Заказ выполнен! Репутация начислена.":action==="raw"?"Сырьё поступило на общий склад!":action==="produce"?"Производство запущено!":["list","sell-raw","sell-market-product"].includes(action)?(data.simple_economy?"Продано! Монеты начислены.":"Товар выставлен на рынок"):action==="open"?"Предприятие открыто!":"Готово!");
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
 if(["city-name-form","city-password-form"].includes(e.target.id))saveAccount(e);
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
function cityBack(){
 if(working||activeView==="map")return;
 closePanel();
}
let telegramBack;
function syncCityBack(){
 const back=window.Telegram?.WebApp?.BackButton;
 if(!back)return;
 if(telegramBack!==back){
  telegramBack?.offClick?.(cityBack);
  back.onClick?.(cityBack);
  telegramBack=back;
 }
 if(activeView==="map")back.hide?.();
 else back.show?.();
}
window.addEventListener("telegram-sdk-ready",()=>{
 syncCityBack();
 if(data){loadTelegramPhoto();window.CityEntryAds?.maybeStart?.();}
 else if(!token&&!$("city-auth").classList.contains("hidden"))loginTelegram();
});
setInterval(()=>{
 for(const timer of document.querySelectorAll("[data-period-end]"))timer.textContent=periodTime(Number(timer.dataset.periodEnd),timer.dataset.periodPrefix);
 for(const timer of document.querySelectorAll("[data-job-ready]")){
  const remaining=secondsLeft({ready_at:Number(timer.dataset.jobReady)});
  timer.textContent=formatTime(remaining);
 }
},1000);
window.addEventListener("pageshow",event=>{
 if(event.persisted&&data&&!working)load().catch(()=>{});
});
document.addEventListener("visibilitychange",()=>{
 if(data&&!working&&document.visibilityState==="visible")load().catch(()=>{});
});
setInterval(()=>{if(data&&!working&&!$("panel-body").contains(document.activeElement)&&document.visibilityState==="visible")load().catch(()=>{})},60000);
function sizeCitySheet(){
 const viewport=window.visualViewport;
 if(!viewport)return;
 const overlay=$("panel-overlay");
 const bottom=Math.max(0,window.innerHeight-viewport.height-viewport.offsetTop);
 overlay.style.setProperty("--p3-keyboard",bottom+"px");
 overlay.style.setProperty("--p3-viewport",viewport.height+"px");
}
window.visualViewport?.addEventListener("resize",sizeCitySheet);
window.visualViewport?.addEventListener("scroll",sizeCitySheet);
sizeCitySheet();
syncCityBack();
entry();
