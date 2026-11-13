"use strict";
(()=> {
 const btn=document.getElementById("farm-city-products-toggle");
 const container=document.getElementById("farm-city-products");
 if(!btn||!container)return;
 const icons={pancakes:"🥞",pie:"🥧",omelet:"🍳",cheese:"🧀",bread:"🍞",pillow:"🛏️",scarf:"🧣"};
 const names={pancakes:"Блины",pie:"Пирог",omelet:"Омлет",cheese:"Сыр",bread:"Хлеб",pillow:"Подушка",scarf:"Шарф"};
 let offers=[],busy=false;
 const esc=s=>String(s).replace(/[&<>"']/g,k=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[k]));
 const getToken=()=>{
   try{if(typeof token==="string"&&token)return token;}catch(_){}
   try{return localStorage.getItem("farm_token")||""}catch(_){return ""}
 };
 async function call(path,body){
  const response=await fetch("/api/city/"+path,{
    method:body?"POST":"GET",
    headers:{"Content-Type":"application/json",Authorization:"Bearer "+getToken()},
    body:body?JSON.stringify(body):undefined,cache:"no-store"});
  const result=await response.json();
  if(!response.ok)throw Error(result.detail||"Не удалось получить товары");
  return result;
 }
 async function load(){
  container.innerHTML='<p style="opacity:.8">Загружаем товары городских бизнесов…</p>';
  try{
   const info=await call("state");
   offers=info.city_offers.filter(x=>names[x.item]&&x.seller!==info.name);
   container.innerHTML=offers.length?offers.map(x=>
    '<div style="display:flex;align-items:center;justify-content:space-between;gap:8px;border-radius:12px;padding:10px;margin:7px 0;background:#ffffff17"><div><strong>'+icons[x.item]+' '+names[x.item]+'</strong><small style="display:block;opacity:.8">'+esc(x.seller)+' · '+x.quantity+' шт. · '+x.price+' мон./шт.</small></div><div style="display:flex;gap:5px;align-items:center"><input aria-label="Количество" type="number" min="1" max="500" value="1" data-qty="'+esc(x.id)+'" style="width:52px;background:#092b45;color:white;border:1px solid #a1c5df;border-radius:8px;padding:9px 3px"><button class="btn" data-city-buy="'+esc(x.id)+'">Купить</button></div></div>'
   ).join(""):'<p style="opacity:.85">Товаров пока нет. Первые пекарни и рестораны смогут выставить их в городе.</p>';
  }catch(e){container.textContent=e.message}
 }
 btn.addEventListener("click",async()=>{
  container.hidden=!container.hidden;
  if(!container.hidden)await load();
 });
 container.addEventListener("click",async event=>{
  const button=event.target.closest("button[data-city-buy]");
  if(!button||busy)return;
  const offer=offers.find(x=>x.id===button.dataset.cityBuy);
  const input=container.querySelector('input[data-qty="'+button.dataset.cityBuy+'"]');
  const n=Number(input?.value);
  if(!offer||!Number.isSafeInteger(n)||n<1||n>500)return alert("Количество от 1 до 500");
  const request_id=(globalThis.crypto?.randomUUID?.()||(Date.now().toString(16)+Math.floor(Math.random()*1e15).toString(16)).padEnd(32,"a")).replaceAll("-","").slice(0,32);
  busy=true;button.disabled=true;
  try{
   const quote=await call("quote-product",{item:offer.item,amount:n});
   if(!confirm("Купить "+n+" шт. за "+quote.cost+" монет у "+quote.sellers+" продавцов?"))return;
   await call("buy-product",{item:offer.item,amount:n,request_id,expected_cost:quote.cost});
   if(typeof refresh==="function")await refresh();
   await load();
   if(typeof toast==="function")toast("🏙️ Товар куплен! Он поступил на склад города.");
  }catch(e){if(typeof toast==="function")toast(e.message);else alert(e.message)}
  finally{busy=false;button.disabled=false}
 });
})();
