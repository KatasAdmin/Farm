/* AdsGram rewarded fallback for confirmed unpaid Monetag impressions.
 * SDK success is a UI event, NEVER authoritative proof of publisher revenue.
 * In particular it does not create withdrawable UAH cash or referral rewards.
 */
(function(){
 'use strict';
 let busy=false,loaded=null,controller=null,currentBlock='';
 function load(){
  if(window.Adsgram?.init)return Promise.resolve();
  if(loaded)return loaded;
  loaded=new Promise((resolve,reject)=>{
   const script=document.createElement('script');
   script.src='https://sad.adsgram.ai/js/sad.min.js';
   script.async=true;
   script.onload=()=>window.Adsgram?.init?resolve():reject(new Error('AdsGram SDK unavailable'));
   script.onerror=()=>reject(new Error('AdsGram SDK could not load'));
   document.head.appendChild(script);
  });
  return loaded;
 }
 async function show(blockId){
  if(busy)throw new Error('AdsGram already showing');
  if(!/^\d{3,12}$/.test(String(blockId)))throw new Error('AdsGram block is not configured');
  busy=true;
  try{
   await load();
   if(!controller||currentBlock!==String(blockId)){
    currentBlock=String(blockId);
    controller=window.Adsgram.init({blockId:currentBlock,debug:false});
   }
   await controller.show();
   return {ok:true,provider:'adsgram',confirmed_cash:false,
     message:'Реклама AdsGram просмотрена; денежное вознаграждение не подтверждено'};
  }finally{busy=false}
 }
 window.FarmAdsgramFallback={show};
})();