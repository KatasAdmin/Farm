(() => {
"use strict";
const button=document.getElementById("city-watch-ad");
const output=document.getElementById("city-ad-status");
const signed=()=>window.Telegram?.WebApp?.initData||"";
const token=()=>{try{return localStorage.getItem("farm_token")||""}catch{return ""}};
let config,busy=false,offered=false,messageTimer;
function report(text){
 output.textContent=text;
 output.hidden=false;
 clearTimeout(messageTimer);
 messageTimer=setTimeout(()=>{output.hidden=true},4200);
}
async function request(endpoint,body){
 const response=await fetch("/api/ads/adsgram/farm/"+endpoint,{
  method:body===undefined?"GET":"POST",
  headers:{"Authorization":"Bearer "+token(),
           "X-Telegram-Init-Data":signed(),"Content-Type":"application/json"},
  body:body===undefined?undefined:JSON.stringify(body),cache:"no-store"
 });
 const result=await response.json();
 if(!response.ok)throw Error("Реклама пока недоступна");
 return result;
}
async function maybeStart(){
 if(offered||!signed()||!token())return;
 offered=true;
 try{
  config=await request("status");
  button.hidden=!config.enabled;
 }catch{offered=false}
}
async function play(){
 if(busy||!config?.enabled)return;
 busy=true;
 button.disabled=true;
 let attempt,completed=false;
 try{
  if(!window.FarmAdsgramFallback?.show)throw Error("Реклама пока недоступна");
  attempt=(await request("prepare",{item:"coins"})).attempt_id;
  await window.FarmAdsgramFallback.show(config.adsgram_block_id);
  completed=true;
  for(const delay of [0,800,1800]){
   if(delay)await new Promise(resolve=>setTimeout(resolve,delay));
   const status=await request("status");
   if(status.history?.some(event=>event.ymid===attempt&&event.state==="credited")){
    report("+3 монеты");
    await window.cityReload?.();
    return;
   }
  }
  report("Награда ожидается");
 }catch{
  if(attempt&&!completed)try{await request("cancel",{attempt_id:attempt})}catch{}
  report(completed?"Награда ожидается":"Реклама пока недоступна");
 }finally{busy=false;button.disabled=false}
}
button.addEventListener("click",play);
window.CityEntryAds={maybeStart};
})();
