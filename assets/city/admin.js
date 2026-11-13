"use strict";
const authForm=document.querySelector("#city-admin-auth");
const form=document.querySelector("#city-admin-form");
const statusLine=document.querySelector("#city-admin-status");
const selector=document.querySelector("#city-admin-campaign");
let key="",campaigns=[];
const endpoint="/api/admin/city/";

async function request(path,body){
 const response=await fetch(endpoint+path,{method:body?"POST":"GET",
  headers:{Authorization:"Bearer "+key,"Content-Type":"application/json"},
  body:body?JSON.stringify(body):undefined});
 const result=await response.json();
 if(!response.ok)throw Error(typeof result.detail==="string"?result.detail:"Проверьте поля формы");
 return result;
}

async function refresh(selected=""){
 const [list,stats]=await Promise.all([request("campaigns"),request("stats")]);
 campaigns=list;
 selector.replaceChildren(new Option("Создать", ""),...campaigns.map(x=>new Option(x.name,x.id)));
 selector.value=selected;
 const labels={businesses:"Предприятия",production:"Произведено товаров",
  sales:"Продано другим игрокам",orders:"Выполнено заказов",meals:"Употреблений еды"};
 document.querySelector("#city-admin-stats").replaceChildren(...Object.entries(labels).flatMap(([key,label])=>{
  const term=document.createElement("dt"),value=document.createElement("dd");
  term.textContent=label;value.textContent=stats[key];return [term,value];
 }));
 document.querySelector("#city-admin-content").hidden=false;
}

function localDate(seconds){
 const date=new Date(seconds*1000);
 return new Date(date.getTime()-date.getTimezoneOffset()*60000).toISOString().slice(0,-1);
}

selector.addEventListener("change",()=>{
 const entry=campaigns.find(x=>x.id===selector.value);
 form.reset();
 for(const name of ["id","kind","starts"])form.elements[name].disabled=Boolean(entry);
 if(!entry)return;
 for(const name of ["id","kind","name","description","metric","goal","xp"])form.elements[name].value=entry[name];
 form.elements.starts.value=localDate(entry.starts);
 form.elements.ends.value=localDate(entry.ends);
 form.elements.enabled.checked=entry.enabled;
});

authForm.addEventListener("submit",async event=>{
 event.preventDefault();
 const input=document.querySelector("#city-admin-key");
 key=input.value;input.value="";
 document.querySelector("#city-admin-content").hidden=true;
 try{await refresh();selector.dispatchEvent(new Event("change"));statusLine.textContent="Доступ подтверждён"}
 catch(error){key="";statusLine.textContent=error.message}
});

form.addEventListener("submit",async event=>{
 event.preventDefault();
 const values=Object.fromEntries(new FormData(form));
 const current=campaigns.find(x=>x.id===selector.value);
 const campaign={...values,id:current?.id||values.id,kind:current?.kind||values.kind,
  starts:current?.starts??new Date(values.starts).getTime()/1000,
  ends:new Date(values.ends).getTime()/1000,
  goal:Number(values.goal),xp:Number(values.xp),enabled:form.elements.enabled.checked};
 try{
  await request("campaigns",campaign);await refresh(campaign.id);
  selector.dispatchEvent(new Event("change"));statusLine.textContent="Сохранено";
 }catch(error){statusLine.textContent=error.message}
});
