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
   const art=document.createElement("img");
   art.src="/assets/field-plot.svg";
   art.alt="";
   art.loading="lazy";
   tile.appendChild(art);
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
  combine.disabled=pending||f.combines>=100||state.me.coins<f.combine_price;
  combine.textContent=f.combines>=100?"Максимум":"Купить · "+numberText(f.combine_price)+" 🪙";
 }
 if(plot){
  plot.disabled=pending||f.plots>=500||state.me.coins<f.field_price;
  plot.textContent=f.plots>=500?"Все поля куплены":"Расширить хозяйство · "+numberText(f.field_price)+" монет";
 }
}
function fieldPurchaseCelebration(item,result){
 const old=document.getElementById("field-purchase-celebration");
 if(old)old.remove();
 const overlay=document.createElement("div");
 overlay.id="field-purchase-celebration";
 overlay.className="field-purchase-overlay";
 const card=document.createElement("div");
 card.className="field-purchase-popup";
 card.setAttribute("role","alertdialog");
 card.setAttribute("aria-modal","true");
 const title=document.createElement("h2");
 title.textContent="🎉 Поздравляем!";
 const art=document.createElement("img");
 art.src=item==="field"?"/assets/field-plot.svg":"/assets/combine.svg";
 art.alt="";
 const message=document.createElement("p");
 const remaining=result.needs_combine
  ?"Чтобы получать зерно, купи комбайн в Рынке. Один комбайн обслуживает 5 полей."
  :result.needs_field
  ?"Теперь купи поле — тогда комбайн начнёт собирать зерно."
  :"Отлично! Твоё хозяйство производит "+result.grain_per_day+" зерна в сутки.";
 message.textContent=(item==="field"?"Поле приобретено! ":"Комбайн приобретён! ")+remaining;
 const button=document.createElement("button");
 button.className="btn";
 button.textContent="Отлично!";
 button.onclick=()=>overlay.remove();
 card.append(art,title,message,button);
 overlay.append(card);
 document.body.append(overlay);
 button.focus();
}
async function buyFieldItem(item){
 if(pending||!state?.fields)return;
 const cost=item==="field"?state.fields.field_price:state.fields.combine_price;
 if(state.me.coins<cost)return toast("Недостаточно монет");
 if(!confirm("Купить "+(item==="field"?"поле":"комбайн")+" за "+cost+" монет?"))return;
 if(pending)return;
 busy(true);
 try{
  const result=await api("/api/fields/buy",{item});
  try{await refresh();}catch(e){console.warn("Field purchase refresh failed",e);}
  fieldPurchaseCelebration(item,result);
 }catch(e){toast(e.message);}
 finally{busy(false);}
}
