/* Cash ads SDK integration, dormant until backend explicitly enables.
 * Does not modify the farm's existing Rewarded Popup flow.
 * Never award money on a browser callback.
 */
(function(){
  'use strict';
  const ZONE=12193261;
  const SDK_URL='https://libtl.com/sdk.js';
  const API='/api/ads/cash/';
  let busy=false;
  const unavailable=()=>Object.assign(new Error('Сейчас нет доступной рекламы Monetag'),{code:'monetag_unavailable'});
  const post=async(endpoint,telegramData,payload={})=>{
    const response=await fetch(API+endpoint,{
      method:'POST',credentials:'same-origin',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({telegram_data:telegramData,...payload})
    });
    const result=await response.json().catch(()=>({}));
    if(!response.ok)throw new Error(result.detail||'Сервис временно недоступен');
    return result;
  };
  function loadSdk(){
    if(typeof window['show_'+ZONE]==='function')return Promise.resolve();
    return new Promise((resolve,reject)=>{
      const script=document.createElement('script');
      script.src=SDK_URL;
      script.dataset.zone=String(ZONE);
      script.dataset.sdk='show_'+ZONE;
      script.async=true;
      script.onload=()=>typeof window['show_'+ZONE]==='function'
        ?resolve():reject(unavailable());
      script.onerror=()=>reject(unavailable());
      document.head.appendChild(script);
    });
  }
  async function showCashAd(telegramData,handlers={}){
    if(busy)throw new Error('Просмотр уже выполняется');
    if(!telegramData)throw new Error('Откройте страницу через Telegram');
    busy=true;
    let attempt=null,launched=false;
    try{
      const status=await post('status',telegramData);
      if(!status.enabled)throw new Error('Просмотр рекламы пока недоступен');
      if(status.active_attempt||status.retry_after>0)
        throw new Error('Подождите перед следующим просмотром');
      // SDK must be loaded before preparing a server-side attempt.
      await loadSdk();
      attempt=await post('prepare',telegramData);
      if(!attempt.ymid||attempt.zone_id!==ZONE)throw new Error('Invalid ad attempt');
      await post('launch',telegramData,{ymid:attempt.ymid});
      launched=true;
      // No "pop": this is the separate Rewarded Interstitial placement.
      // request_var/ymid are supplied by the server, never trusted from client.
      try{
        await window['show_'+ZONE]({
          type:'end',
          timeout:8,
          ymid:attempt.ymid,
          requestVar:attempt.request_var
        });
      }catch(error){
        // Release the active slot without counting an unsuccessful SDK call.
        // A late provider postback still resolves against the original attempt.
        await post('abandon',telegramData,{ymid:attempt.ymid});
        if(/^(empty feed|network error|timeout|ad is not ready)$/i.test(String(error?.message||error).trim()))throw unavailable();
        throw error;
      }
      await post('finish',telegramData,{ymid:attempt.ymid});
      handlers.onFinished?.();
      return {ok:true,ymid:attempt.ymid,payable:false,pending_postback:true};
    }catch(error){
      if(attempt){
        try{if(!launched)await post('cancel',telegramData,{ymid:attempt.ymid});}
        catch(_){/* No client-side credits on error. */}
      }
      handlers.onError?.(error);
      throw error;
    }finally{busy=false}
  }
  window.FarmCashAds={showCashAd,zone:ZONE};
})();
