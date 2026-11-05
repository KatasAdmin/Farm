/* Field landscape and purchasing: data always comes from /api/state. */
function renderFields(){
 const f=state?.fields;
 if(!f)return;
 const numberText=n=>Number(n||0).toLocaleString("ru-RU");
 for(const node of document.querySelectorAll("[data-fields-count]"))node.textContent=numberText(f.plots);
 for(const node of document.querySelectorAll("[data-fields-rate]"))node.textContent=numberText(f.grain_per_day);
 const count=document.getElementById("fields-combines");
 if(count)count.textContent=numberText(f.combines);
 const invested=document.getElementById("fields-invested");
 if(invested)invested.textContent=numberText(f.invested);
 const area=document.getElementById("fields-landscape");
 if(area){
  area.replaceChildren();
  const shown=Math.min(f.plots,25);
  for(let i=0;i<shown;i++){
   const tile=document.createElement("span");
   tile.className="wheat-plot";
   tile.textContent="🌾";
   tile.setAttribute("aria-label","Поле "+(i+1));
   area.appendChild(tile);
  }
  if(!shown){
   const empty=document.createElement("div");
   empty.className="fields-empty";
   empty.textContent="🌱 Здесь появится твоё первое поле";
   area.appendChild(empty);
  }
  if(f.plots>shown){
   const more=document.createElement("span");
   more.className="fields-more";
   more.textContent="+"+numberText(f.plots-shown)+" полей";
   area.appendChild(more);
  }
 }
 const info=document.getElementById("fields-info");
 if(info)info.textContent=f.plots
   ?"Автоматический сбор · "+numberText(f.grain_per_day)+" зерна в сутки · "+f.combines+" комбайнов"
   :"Начни с комбайна, затем купи первое поле. Урожай поступает на общий склад автоматически.";
 const combine=document.getElementById("fields-buy-combine");
 const plot=document.getElementById("fields-buy-plot");
 if(combine){
  combine.disabled=pending||f.combines>=100||f.combines*5>f.plots||state.me.coins<f.combine_price;
  combine.textContent=f.combines>=100?"Максимум":f.combines*5>f.plots?"Уже есть свободный комбайн":"Купить · "+numberText(f.combine_price)+" 🪙";
 }
 if(plot){
  plot.disabled=pending||f.plots>=500||f.next_field_requires_combine||state.me.coins<f.field_price;
  plot.textContent=f.plots>=500?"Все поля куплены":f.next_field_requires_combine?"Сначала купи комбайн в Рынке":"Расширить хозяйство · "+numberText(f.field_price)+" монет";
 }
}
async function buyFieldItem(item){
 if(pending||!state?.fields)return;
 const cost=item==="field"?state.fields.field_price:state.fields.combine_price;
 const label=item==="field"?"поле":"комбайн";
 if(!confirm("Купить "+label+" за "+cost+" монет?"))return;
 await perform("/api/fields/buy",{item});
}
