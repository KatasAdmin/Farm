"use strict";
const $=id=>document.getElementById(id);
const root="/api/city";
const names={eggs:"🥚 Яйца",grain:"🌾 Зерно",milk:"🥛 Молоко",feathers:"🪶 Перья",wool:"🧶 Шерсть"};
const icons={pancakes:"🥞",pie:"🥧",omelet:"🍳",cheese:"🧀",bread:"🍞",pillow:"🛏️",scarf:"🧣"};
let token="",data=null,activeView="map",activeBusiness=null,working=false;
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
 $("eggs-on-market").textContent=number(data.farm_offers.filter(x=>x.item==="eggs").reduce((n,x)=>n+x.quantity,0));
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
 if(activeView==="residents")return showResidents();
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
   const need=Object.entries(v.needs).map(([k,n])=>esc(names[k])+' ×'+n+' (есть '+(data.stock[k]||0)+')').join(" · ");
   return row((icons[key]||"📦")+" "+esc(v.name),need+" · "+v.seconds+" сек. · результат ×"+v.output,
    input("qty-craft-"+key)+ '<button class="btn" data-action="produce" data-item="'+key+'">Готовить</button>');
  }).join("");
  body+='<h3 class="section-subtitle">Задания в работе</h3>';
  const jobs=data.jobs.filter(x=>data.recipes[x.recipe]?.business===kind);
  body+=jobs.length?jobs.map(x=>row(esc(data.recipes[x.recipe].name)+' ×'+x.quantity,
   x.ready_at*1000<=Date.now()?"Готово, обнови склад":"Готово: "+new Date(x.ready_at*1000).toLocaleTimeString("ru-RU"),"⏳")).join(""):'<div class="empty">Очередь производства свободна</div>';
  body+='<p><button class="btn ghost" data-action="market">🧺 Закупить ингредиенты</button></p>';
 }
 openPanel(b.emoji+" "+b.name,body);
}
function showMarket(){
 const offers=data.farm_offers.filter(x=>names[x.item]);
 let s='<p class="panel-note">Здесь настоящий рынок фермы, а не магазин с бесконечными товарами. Продавец получает монеты. Свои объявления для закупки скрыты.</p>';
 s+='<div class="badge-line">'+Object.entries(names).map(([key,name])=>'<span class="pill">'+name+': '+number(offers.filter(r=>r.item===key).reduce((n,r)=>n+r.quantity,0))+'</span>').join("")+'</div>';
 s+=offers.length?offers.map(x=>row(esc(names[x.item]),'Фермер: '+esc(x.seller)+' · '+x.quantity+' шт. · '+x.price+' мон./шт.',
  input('qty-raw-'+x.id)+ '<button class="btn" data-action="raw" data-item="'+esc(x.item)+'" data-amount-id="qty-raw-'+x.id+'">Купить</button>')).join(""):'<div class="empty">На общем рынке пока нет сырья от других игроков. Фермеры могут выставить яйца через игру «Ферма».</div>';
 openPanel("🧺 Сырьевой рынок",s);
}
function showProducts(){
 let s='<p class="panel-note">Готовые блюда и изделия продают реальные бизнесы игроков. Оплата списывается с того же монетного счёта, что используется в ферме. Монеты за продукцию в первой версии не становятся автоматически выводимыми.</p>';
 const offers=data.city_offers.filter(x=>data.recipes[x.item]);
 s+=offers.length?offers.map(x=>row((icons[x.item]||"📦")+" "+esc(data.recipes[x.item].name),
   esc(x.seller)+' · '+x.quantity+' шт. · '+x.price+' мон./шт.',
   input("qty-product-"+x.id)+'<button class="btn" data-action="product" data-item="'+esc(x.item)+'" data-amount-id="qty-product-'+x.id+'">Купить</button>')).join(""):'<div class="empty">Готовых товаров пока нет. Открой производство и первым выставь свой товар!</div>';
 openPanel("🛍️ Товары города",s);
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
function showWarehouse(){
 let s='<p class="panel-note">Склад бизнеса отделён от фермерского склада. Он пополняется только закупками на общем рынке. Готовые товары можно продавать или использовать для развития репутации.</p>';
 s+='<h3 class="section-subtitle">Ингредиенты бизнеса</h3><div class="mini-grid">';
 s+=Object.entries(names).map(([key,name])=>'<div class="mini-box"><small>'+name+'</small><strong>'+number(data.stock[key]||0)+'</strong></div>').join("")+'</div>';
 s+='<h3 class="section-subtitle">Произведённые товары</h3>';
 const products=Object.entries(data.products).filter(([key,n])=>n>0&&data.recipes[key]);
 s+=products.length?products.map(([key,n])=>row((icons[key]||"📦")+" "+esc(data.recipes[key].name),
   'На складе: '+n+' шт.',input("qty-list-"+key)+'<input class="number-input" aria-label="Цена" id="price-'+key+'" type="number" min="1" value="10"><button class="btn gold" data-action="list" data-item="'+key+'">Продать</button><button class="btn ghost" data-action="consume" data-item="'+key+'">Использовать</button>')).join(""):'<div class="empty">Пока нет готовой продукции. Закупи ингредиенты и начни производство.</div>';
 s+='<h3 class="section-subtitle">Мои объявления</h3>';
 s+=(data.my_city_offers||[]).length?data.my_city_offers.map(x=>
  row((icons[x.item]||"📦")+" "+esc(data.recipes[x.item]?.name||x.item),
  x.quantity+" шт. · "+x.price+" мон./шт.",
  '<button class="btn ghost" data-action="cancel" data-listing-id="'+esc(x.id)+'">Снять</button>'
 )).join(""):'<div class="empty">Активных предложений пока нет</div>';
 openPanel("📦 Склад бизнеса",s);
}
async function action(action,item,amountId,listingId){
 if(working)return;
 const amount=amountId?getAmount(amountId):null;
 if(amountId&&amount===null)return;
 let path,body={item};
 if(action==="market")return view("market");
 if(action==="open")path="/open";
 else if(action==="produce"){path="/produce";body.amount=getAmount("qty-craft-"+item);if(!body.amount)return}
 else if(action==="raw"){path="/buy-ingredient";body.amount=amount}
 else if(action==="product"){path="/buy-product";body.amount=amount}
 else if(action==="list"){path="/list-product";body.amount=getAmount("qty-list-"+item);body.price=Number($("price-"+item)?.value);if(!body.amount||!Number.isSafeInteger(body.price)||body.price<1){toast("Укажи количество и цену");return}}
 else if(action==="consume"){path="/consume";body.amount=getAmount("qty-list-"+item);if(!body.amount)return}
 else if(action==="cancel"){path="/cancel-product";body.listing_id=listingId}
 else if(action==="fulfill"){path="/fulfill-order"}
 else return;
 working=true;
 if(action==="raw"||action==="product"){
  try{
   const quote=await api(action==="raw"?"/quote-ingredient":"/quote-product",{item,amount:body.amount});
   body.expected_cost=quote.cost;
   if(!confirm("Покупка "+body.amount+" шт. за "+number(quote.cost)+" монет у "+quote.sellers+" продавцов. Подтвердить?")){working=false;return}
  }catch(e){toast(e.message);working=false;return}
 }
 if(action==="raw"||action==="product"){
  body.request_id=(globalThis.crypto?.randomUUID?.()||(["a",Date.now().toString(16),Math.floor(Math.random()*1e9).toString(16)].join(""))).replaceAll("-","").slice(0,32);
 }
 try{const result=await api(path,body);toast(action==="fulfill"?"Заказ выполнен! Репутация начислена.":action==="raw"?"Сырьё куплено на склад бизнеса!":action==="produce"?"Производство запущено!":action==="list"?"Товар выставлен в городе":action==="open"?"Предприятие открыто!":"Готово!");
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
$("refresh").addEventListener("click",async()=>{try{await load();toast("Данные обновлены")}catch(e){toast(e.message)}});
$("close-panel").addEventListener("click",closePanel);
$("panel-backdrop").addEventListener("click",closePanel);
document.addEventListener("keydown",e=>{if(e.key==="Escape")closePanel()});
$("panel-body").addEventListener("click",e=>{
 const button=e.target.closest("button[data-action]");if(!button)return;
 action(button.dataset.action,button.dataset.item,button.dataset.amountId,button.dataset.listingId)
});
$("auth-form").addEventListener("submit",loginPassword);
$("telegram-login").addEventListener("click",loginTelegram);
window.addEventListener("telegram-sdk-ready",()=>{if(!data&&!token)loginTelegram()});
setInterval(()=>{if(data&&document.visibilityState==="visible")load().catch(()=>{})},30000);
entry();
