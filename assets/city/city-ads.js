/* City ads use the same verified AdsGram reward system as the Farm.
 * SDK completion is NOT payment evidence; only server-side AdsGram Reward URL
 * may credit the existing restricted +3-coin reward for purchases. */
(()=>{
"use strict";
let attempted=false,busy=false,config=null;
const $=id=>document.getElementById(id);
const signed=()=>window.Telegram?.WebApp?.initData||"";
const token=()=>{try{return localStorage.getItem("farm_token")||""}catch{return ""}};
function report(text){
 const output=$("city-ad-status");if(output)output.textContent=text;
}
async function request(endpoint,body){
 const response=await fetch("/api/ads/adsgram/farm/"+endpoint,{
  method:body===undefined?"GET":"POST",
  headers:{"Authorization":"Bearer "+token(),
           "X-Telegram-Init-Data":signed(),"Content-Type":"application/json"},
  body:body===undefined?undefined:JSON.stringify(body),cache:"no-store"
 });
 const result=await response.json();
 if(!response.ok)throw Error(result.detail||"Реклама сейчас недоступна");
 return result;
}
async function status(){
 if(!signed()||!token())return null;
 config=await request("status");
 return config;
}
async function play(){
 if(busy || !signed() || !token())return;
 busy=true;
 let attempt=null;
 try{
  const cfg=await status();
  if(!cfg?.enabled){report("Реклама пока недоступна");return}
  report("🎬 Открываем рекламный просмотр…");
  const prepared=await request("prepare",{item:"coins"});
  attempt=prepared.attempt_id;
  if(!window.FarmAdsgramFallback?.show)throw Error("Рекламный сервис ещё загружается");
  await window.FarmAdsgramFallback.show(cfg.adsgram_block_id);
  report("✅ Просмотр завершён. Награда будет начислена после подтверждения рекламной сети.");
  // We never promise an instant credit based on the SDK completion.
  await status();
  if(typeof window.cityReload==="function")await window.cityReload();
 }catch(error){
  if(attempt)try{await request("cancel",{attempt_id:attempt})}catch(_){}
  report(String(error.message||"Не удалось показать рекламу"));
 }finally{busy=false}
}
async function maybeStart(){
 if(attempted)return;
 attempted=true;
 // Only a verified, signed Telegram Mini App may see an automatic attempt.
 if(!signed()||!token())return;
 try{
  const cfg=await status();
  if(cfg?.enabled)await play();
 }catch(_){/* Never block city opening or give unverified coins. */}
}
$("city-watch-ad")?.addEventListener("click",()=>{attempted=true;play()});
window.CityEntryAds={maybeStart,play,status};
})();
