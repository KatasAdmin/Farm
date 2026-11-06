"use strict";
const el = (id) => document.getElementById(id);
// iOS WebViews may deny persistent storage. Keep this session usable regardless.
const storage = (() => {
  const memory = new Map();
  return {
    getItem(key) { if(memory.has(key))return memory.get(key); try { return window.localStorage.getItem(key); } catch (_) { return null; } },
    setItem(key,value) { memory.set(key,String(value)); try { window.localStorage.setItem(key,String(value)); } catch (_) {} },
    removeItem(key) { memory.delete(key); try { window.localStorage.removeItem(key); } catch (_) {} }
  };
})();
function showStartupError() {
  const screen=el("boot-screen");
  if(screen) {screen.hidden=false;el("boot-status").textContent="Не удалось загрузить ферму. Проверь соединение и повтори попытку.";}
}
function retryFarmStartup() {
  clearTimeout(startupRetryTimer);
  startupRetryTimer=null;
  startupRetryCount=0;
  if(el("boot-status"))el("boot-status").textContent="Загружаем ферму…";
  if(token)refresh();else showLogin();
}
function hideStartup() {
  clearTimeout(startupRetryTimer);
  startupRetryTimer=null;
  startupRetryCount=0;
  const screen=el("boot-screen");
  if(screen)screen.hidden=true;
}
function retryTransientStartup(error) {
  // Only transient server/database outages. Never retry bad credentials.
  const transient=error?.status===503||error?.status===502||error?.status===504||
    /Сервер не ответил вовремя|Failed to fetch|NetworkError|Load failed/i.test(String(error?.message||""));
  if(!transient||startupRetryCount>=STARTUP_RETRIES)return false;
  const delays=[1500,2500,4000,6000,8500,11000];
  const delay=delays[startupRetryCount++];
  const label=el("boot-status");
  if(label)label.textContent="Сервер занят. Подключаемся автоматически… ("+startupRetryCount+"/"+STARTUP_RETRIES+")";
  clearTimeout(startupRetryTimer);
  startupRetryTimer=setTimeout(()=>{
    startupRetryTimer=null;
    if(token&&el("app")?.hidden)refresh();
  },delay);
  return true;
}

const art = {
  grain: "redesign/grain",
  eggs: "redesign/egg",
  chickens: "redesign/hen",
  geese: "goose-v2.png",
  cows:"cow-v1.webp",milk:"milk-v1.webp",
};
function eggQuantity(n) {
  const v=Math.abs(n)%100, last=v%10;
  return `${number(n)} ${v>=11 && v<=14 ? "яиц" : last===1 ? "яйцо" : last>=2 && last<=4 ? "яйца" : "яиц"}`;
}
const referralItems=["eggs","grain","chickens","geese","cows","milk","feathers"];
const itemNames = { grain: "Зерно", eggs: "Яйцо", chickens: "Курица", geese:"Гусыня", cows:"Корова",milk:"Молоко", feathers:"Перо" };
const number = (n) => new Intl.NumberFormat("ru-RU").format(n);
let token = storage.getItem("farm_token");
let state = null,
  pending = false,
  chosenFilter = "all",
  currentTab = "farm",
  purchase = null;
let refreshPromise = null,
  refreshedAt = 0;
let startupRetryTimer = null;
let startupRetryCount = 0;
const STARTUP_RETRIES = 6;
let lastTimerRefresh = 0;
function safe(s) {
  return String(s).replace(
    /[&<>"']/g,
    (ch) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        ch
      ],
  );
}
function image(path, cls = "icon") {
  return `<img src="/assets/${path}${/\.(svg|png|webp)$/.test(path)?"":".webp"}" class="${cls}" alt="" decoding="async">`;
}
function toast(message) {
  el("toast").textContent = message;
  el("toast").hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (el("toast").hidden = true), 4500);
}
async function api(path, payload, extraHeaders={}) {
  const controller=new AbortController();
  const timer=setTimeout(()=>controller.abort(),payload===undefined?15000:45000);
  let response,value;
  try {
    response=await fetch(path, {
      method: payload === undefined ? "GET" : "POST",
      headers: {"Content-Type":"application/json",Authorization:"Bearer "+(token||""),...extraHeaders},
      body:payload===undefined?undefined:JSON.stringify(payload),cache:"no-store",signal:controller.signal
    });
    value=await response.json();
  } catch(error) {
    if(error.name==="AbortError")throw Error("Сервер не ответил вовремя. Обнови данные перед повтором действия.");
    throw error;
  } finally {clearTimeout(timer);}
  if (!response.ok) {
    const error = Error(
      typeof value.detail === "string"
        ? value.detail
        : "Проверь введённые данные",
    );
    error.status = response.status;
    throw error;
  }
  return value;
}
function amount(id, max = 10000) {
  const n = Number(el(id).value);
  if (!Number.isSafeInteger(n) || n < 1 || n > max)
    throw Error(`Введите целое количество от 1 до ${max}`);
  return n;
}
function busy(value) {
  pending = value;
  document.body.classList.toggle("pending", value);
  document.body.setAttribute("aria-busy", String(value));
  el("purchase-confirm").disabled = value;
  el("join-form").querySelector("button").disabled = value;
  document
    .querySelectorAll(".auto-toggle")
    .forEach((x) => (x.disabled = value));
  if (!value && state && token) render();
  if (!value && purchase && el("purchase-dialog").open) purchaseQuote();
}
async function perform(path, data) {
  if (pending) return false;
  busy(true);
  try {
    const result = await api(path, data);
    if (el("purchase-dialog").open) el("purchase-dialog").close();
    // The operation has committed; refresh failure must never encourage a repeated charge.
    const message = path === "/api/sell"
      ? "Товар выставлен на продажу. Монеты поступят после покупки другим игроком."
      : path.startsWith("/api/cancel/") ? `Возвращено на склад: ${number(result.returned)} шт.`
      : "Операция выполнена" + (result.spent ? ` · ${number(result.spent)} монет` : "");
    toast(message);
    await refresh();
    if (currentTab === "wallet") await loadHistory();
    return true;
  } catch (error) {
    toast(error.message);
    if (error.status === 401) showLogin();
    return false;
  } finally {
    busy(false);
  }
}
async function claimAchievement(track) {
  if (pending || !["eggs","feathers","milk","chickens_bought","geese_bought","cows_bought","market_sales","market_purchases","feeding"].includes(track)) return;
  try {
    busy(true);
    const result = await api("/api/achievements/claim",{item:track});
    toast("Достижение получено: +" + number(result.xp_awarded) + " XP");
    await refresh();
  } catch(error) {
    toast(error.message);
  } finally {
    busy(false);
  }
}
async function claimDaily(key) {
  if (pending) return;
  const completed = await perform("/api/claim", {item:key});
  if (completed) toast("Награда получена! Монеты начислены.");
}
async function upgradeBuilding(kind) {
  if (pending || !state || !["coop","storage","cowshed"].includes(kind)) return;
  const values = state.buildings || {};
  const price = values[kind + "_next_cost"];
  if (price == null) return;
  const name = kind === "coop" ? "места для птиц" : kind==="cowshed"?"места для коров":"склад";
  if (!confirm("Улучшить " + name + " за " + number(price) + " монет?")) return;
  await perform("/api/upgrade", {item:kind});
}
function emojiAvatar(emoji) {
  const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128"><rect width="128" height="128" rx="64" fill="#1285c9"/><text x="64" y="91" text-anchor="middle" font-size="78">'+emoji+'</text></svg>';
  return "data:image/svg+xml;charset=UTF-8," + encodeURIComponent(svg);
}
function avatarSource(p) {
  if (p.avatar === "custom" && p.avatar_photo) return p.avatar_photo;
  if (p.avatar === "chicken") return "/assets/redesign/hen.webp";
  if (p.avatar === "egg") return "/assets/redesign/egg.webp";
  if (p.avatar === "flower") return emojiAvatar("🌻");
  if (p.gender === "female" && p.avatar === "default") return emojiAvatar("👩‍🌾");
  if (p.gender === "unspecified" && p.avatar === "default") return emojiAvatar("🧑‍🌾");
  return "/assets/redesign/farmer.webp";
}
function toggleProfileEditor() {
  const editor = el("profile-editor");
  editor.hidden = !editor.hidden;
  if (!editor.hidden && state) {
    el("profile-gender").value = state.me.gender || "unspecified";
    el("profile-age").value = state.me.age == null ? "" : state.me.age;
    el("profile-avatar").value = state.me.avatar || "default";
  }
}
async function photoAsJpeg(file) {
  if (!file.type.startsWith("image/") || file.size > 8 * 1024 * 1024) throw Error("Выбери фото до 8 МБ");
  return new Promise((resolve,reject) => {
    const img = new Image();
    const url = URL.createObjectURL(file);
    img.onload = () => {
      try {
        const canvas = document.createElement("canvas");
        canvas.width = 256;canvas.height = 256;
        const ctx = canvas.getContext("2d");
        const side = Math.min(img.width,img.height);
        ctx.drawImage(img,(img.width-side)/2,(img.height-side)/2,side,side,0,0,256,256);
        const photo = canvas.toDataURL("image/jpeg",.72);
        URL.revokeObjectURL(url);
        if (photo.length > 140000) return reject(Error("Файл получился слишком большим"));
        resolve(photo);
      } catch(e) {URL.revokeObjectURL(url);reject(e);}
    };
    img.onerror = () => {URL.revokeObjectURL(url);reject(Error("Не удалось прочитать изображение"));};
    img.src = url;
  });
}
async function saveProfile() {
  const ageText = el("profile-age").value.trim();
  const age = ageText === "" ? null : Number(ageText);
  if (age !== null && (!Number.isSafeInteger(age) || age < 1 || age > 120)) return toast("Укажи возраст от 1 до 120");
  try {
    const file = el("profile-image-file").files[0];
    const avatar = file ? "custom" : el("profile-avatar").value;
    const avatar_photo = file ? await photoAsJpeg(file) : "";
    const ok = await perform("/api/profile",{gender:el("profile-gender").value,age,avatar,avatar_photo});
    if (ok) {el("profile-editor").hidden = true;el("profile-image-file").value = "";}
  } catch(error) {toast(error.message);}
}
async function shopIncubatorAction() {
  if (!state || pending) return;
  if (state.incubator?.owned) {tab("coop");coopSection("incubator");return;}
  await perform("/api/incubator",{item:"buy"});
}
async function incubatorAction() {
  if (!state || pending) return;
  const i=state.incubator||{};
  await perform("/api/incubator",{item:i.owned?"start":"buy"});
}
async function incubatorUpgrade() {
  if (!state || pending) return;
  const cost=state.incubator?.next_upgrade_cost;
  if (cost == null) return;
  if (!confirm("Улучшить инкубатор за "+number(cost)+" монет?")) return;
  await perform("/api/incubator",{item:"upgrade"});
}
function coopSection(mode) {
  const incubator=mode==="incubator";
  el("coop-incubator-pane").hidden=!incubator;
  el("coop-birds-pane").hidden=incubator;
  el("coop-tab-incubator").classList.toggle("active",incubator);
  el("coop-tab-birds").classList.toggle("active",!incubator);
}
async function completeTutorialStep() {
  if (!state || pending) return;
  const steps=["coop","grain","eggs"];
  const step=state.tutorial?.step||0;
  if (step>=3) return;
  const ok=await perform("/api/tutorial",{item:steps[step]});
  if (ok) {
    if (step===0){tab("coop");coopSection("birds");}
    else if (step===1)tab("shop");
    else toast("Обучение завершено! Получено 5 монет.");
  }
}
function tgInitData() {
 const sdk=window.Telegram?.WebApp?.initData;
 if(sdk)return sdk;
 return new URLSearchParams(location.hash.slice(1)).get("tgWebAppData") || "";
}
async function useLoginResult(result) {
  token=result.token;
  storage.setItem("farm_token",token);
  await refresh();
}
async function telegramLogin() {
  if(pending)return;
  try{busy(true);await useLoginResult(await api("/api/telegram/login",{telegram_data:tgInitData(),referral:incomingReferralCode()}));}
  catch(e){toast(e.message);}finally{busy(false);}
}
async function linkTelegram() {
  if(pending||!state)return;
  if(state.me.telegram_id)return toast("Telegram уже привязан ✓");
  if(tgInitData()){
    if(!confirm("Привязать Telegram к этой ферме?"))return;
    try{busy(true);await api("/api/telegram/link",{telegram_data:tgInitData()});await refresh();toast("Telegram привязан ✓");}
    catch(e){toast(e.message);}finally{busy(false);}
    return;
  }
  try{
    busy(true);
    const result=await api("/api/telegram/link/start",{});
    if(result.linked){await refresh();return;}
    const tg=window.Telegram?.WebApp;
    if(tg?.openTelegramLink)tg.openTelegramLink(result.url);
    else window.location.href=result.url;
    toast("Подтверди привязку в боте командой Start, затем вернись в ферму.");
    if(window.farmLinkPoll)clearInterval(window.farmLinkPoll);
    let attempts=0;
    window.farmLinkPoll=setInterval(async()=>{
      if(++attempts>60){clearInterval(window.farmLinkPoll);window.farmLinkPoll=null;return;}
      try{
        await refresh();
        if(state?.me?.telegram_id){
          clearInterval(window.farmLinkPoll);window.farmLinkPoll=null;
          toast("✅ Telegram успешно привязан!");
        }
      }catch(e){}
    },5000);
  }catch(e){toast(e.message);}finally{busy(false);}
}
async function setAccountPassword(){
  if(pending||!state)return;
  const input=el("settings-password"),current=el("settings-current-password");
  if(input.value.length<8)return toast("Пароль должен содержать минимум 8 символов");
  if(state.has_password&&!current.value)return toast("Введите текущий пароль");
  try{
    busy(true);
    await api("/api/password/set",{password:input.value,current_password:current.value});
    input.value="";current.value="";
    await refresh();
    toast("Пароль сохранён. Теперь оба способа входа ведут в эту ферму.");
  }catch(e){toast(e.message);}finally{busy(false);}
}
async function setAccountNickname(){
  const input=el("settings-nickname");
  const name=input.value.trim();
  if(name.length<2||name.length>22)return toast("Ник должен быть от 2 до 22 символов");
  try{busy(true);await api("/api/nickname/set",{name});await refresh();toast("Ник изменён ✓");}
  catch(e){toast(e.message);}finally{busy(false);}
}
function showLogin() {
  token = null;
  storage.removeItem("farm_token");
  hideStartup();
  el("login").hidden = false;
  el("app").hidden = true;
  el("nav").hidden = true;
  if (el("purchase-dialog").open) el("purchase-dialog").close();
}
el("join-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (pending) return;
  busy(true);
  try {
    const result = await api("/api/join", { name: el("name").value.trim(), gender: el("join-gender").value, password: el("register-password").value, referral: incomingReferralCode() });
    token = result.token;
    storage.setItem("farm_token", token);
    await refresh();
    el("register-password").value="";
  } catch (error) {
    toast(error.message);
  } finally {
    busy(false);
  }
});
el("password-login-form").addEventListener("submit",async event=>{
  event.preventDefault();
  if(pending)return;
  try{busy(true);await useLoginResult(await api("/api/login",{name:el("login-name").value.trim(),password:el("login-password").value}));el("login-password").value="";}
  catch(e){toast(e.message);}finally{busy(false);}
});
el("recover-form").addEventListener("submit",async event=>{
  event.preventDefault();
  if (pending) return;
  busy(true);
  try {
    const result=await api("/api/recovery/login",{name:el("recover-name").value.trim(),code:el("recover-code").value.trim()});
    token=result.token;
    storage.setItem("farm_token",token);
    el("recover-code").value="";
    await refresh();
    toast("Доступ к ферме восстановлен");
  } catch(error){toast(error.message);} finally{busy(false);}
});
function showRecoveryCode(code) {
  const dialog=el("recovery-dialog");
  el("recovery-shown-code").textContent=code;
  if(!dialog.open)dialog.showModal();
}
function closeRecoveryCode(){el("recovery-dialog").close();el("recovery-shown-code").textContent="";}
async function copyRecoveryCode(){
  try{await navigator.clipboard.writeText(el("recovery-shown-code").textContent);toast("Код скопирован. Сохрани его в надёжном месте.");}
  catch(error){toast("Выдели и скопируй код вручную.");}
}
async function generateRecoveryCode(){
  if(pending||!confirm("Создать новый код? Предыдущий перестанет работать."))return;
  busy(true);
  try{const result=await api("/api/recovery/create",{});showRecoveryCode(result.recovery_code);}
  catch(error){toast(error.message);} finally{busy(false);}
}
function tab(id) {
  if(id==="market")id="shop"; // old links
  if(id==="upgrades")id="storage"; // compatibility with older links
  if (!el(id)?.classList.contains("panel")) return;
  currentTab = id;
  document.body.dataset.screen = id;
  document
    .querySelectorAll(".panel")
    .forEach((x) => x.classList.toggle("active", x.id === id));
  document.querySelectorAll("[data-tab]").forEach((x) => {
    const active = x.dataset.tab === id;
    x.classList.toggle("active", active);
    if (active) x.setAttribute("aria-current", "page");
    else x.removeAttribute("aria-current");
  });
  window.scrollTo({ top: 0, behavior: "instant" });
  if (id === "wallet") { loadHistory(); loadWithdrawalStatus(); }
}
function dismissLaunchGuide(){
 if(!state?.me?.id)return;
 storage.setItem("farm_guide_dismissed_"+state.me.id,"1");
 const guide=el("launch-guide");
 if(guide)guide.hidden=true;
}
async function claimWeekly(){
 if(pending)return;
 try{
  busy(true);
  const result=await api("/api/weekly/claim",{});
  await refresh();
  toast("🏆 Недельное испытание пройдено! +"+number(result.awarded)+" монет");
 }catch(error){toast(error.message);}finally{busy(false);}
}
function taskSection(which) {
  const panes={goals:"goals-pane",achievements:"achievement-pane",referrals:"referrals-pane"};
  if(!panes[which])return;
  for(const [section,id] of Object.entries(panes)){
    if(el(id))el(id).hidden=section!==which;
  }
  for(const [id,section] of [["tasks-switch","goals"],["achievements-switch","achievements"],["referrals-switch","referrals"]]){
    const button=el(id);
    if(button){button.classList.toggle("active",section===which);button.setAttribute("aria-pressed",String(section===which));}
  }
  if(which==="referrals")loadReferrals();
}
function incomingReferralCode(){
  const signed=new URLSearchParams(tgInitData()).get("start_param")||"";
  const raw=signed.startsWith("ref_")?signed.slice(4):new URLSearchParams(window.location.search).get("ref")||"";
  return /^[0-9a-f]{16}$/.test(raw)?raw:"";
}
async function loadReferrals(){
  if(!token)return;
  try{
    const r=await api("/api/referrals");
    const link="https://t.me/Farmlife2026bot?startapp=ref_"+r.code;
    el("referral-link").value=link;
    el("referral-direct").textContent=number(r.counts["1"]||0);
    const resources=r.resources||{};
    for(const item of referralItems){
      const data=resources[item]||{available:0,fraction:0,total:0};
      el("referral-"+item+"-available").textContent=number(data.available);
      el("referral-"+item+"-fraction").textContent="В накоплении "+(data.fraction/10000).toLocaleString("ru-RU",{maximumFractionDigits:4})+" до следующего целого";
      el("referral-"+item+"-claim").disabled=!data.available;
    }
    el("referral-levels").innerHTML=r.rates.map((rate,i)=>`<div class="referral-level"><span>${i+1}-й уровень</span><b>${(rate/100).toLocaleString("ru-RU")}%</b><small>${number(r.counts[String(i+1)]||0)} друзей</small></div>`).join("");
  }catch(e){toast("Не удалось загрузить приглашения: "+e.message);}
}
function copyReferralLink(){
 const value=el("referral-link")?.value||"";
 if(!value.startsWith("https://"))return toast("Ссылка ещё не готова");
 if(navigator.clipboard?.writeText)navigator.clipboard.writeText(value).then(()=>toast("Приглашение скопировано ✓")).catch(()=>toast("Не удалось скопировать ссылку"));
 else{el("referral-link").select();document.execCommand("copy");toast("Приглашение скопировано ✓");}
}
async function claimReferralResource(item){
 if(pending)return;
 if(!referralItems.includes(item))return;
 try{
  busy(true);
  const result=await api("/api/referrals/claim",{item});
  await refresh();
  await loadReferrals();
  const labels={eggs:"яиц",grain:"зерна",chickens:"куриц",geese:"гусей",cows:"коров",milk:"молока",feathers:"перьев"};
  toast("Получено "+number(result.amount)+" "+labels[item]+" ✓");
 }catch(e){toast(e.message);}finally{busy(false);}
}
function marketTab(mode) {
  tab("shop");
}
let selectedResource="eggs";
let sellingResource=null;
const systemBuyback={grain:1,feathers:5};
function openResourceActions(item) {
  if (!state || !["grain","chickens","geese","cows","milk","feathers","eggs"].includes(item)) return;
  selectedResource=item;
  const title={grain:"🌾 Зерно",chickens:"🐔 Куры",geese:"🪿 Гуси",cows:"🐄 Коровы",milk:"🥛 Молоко",feathers:"🪶 Перья",eggs:"🥚 Яйца"}[item];
  el("resource-action-title").textContent=title;
  el("resource-action-buy").hidden=false;
  el("resource-action-free").hidden=!adRewards[item];
  const freeLabels={grain:"🌾 Получить бесплатно 2",eggs:"🥚 Получить бесплатно 2",milk:"🥛 Получить бесплатно 1",chickens:"🐔 Получить курицу бесплатно"};
  el("resource-action-free").textContent=freeLabels[item]||"🎬 Получить бесплатно";
  const progress=el("resource-action-ad-progress");
  if(progress){progress.hidden=!adRewards[item];progress.textContent=adRewards[item]?(adProgress[item]||0)+"/"+adRewards[item][0]+" подтверждённых просмотров":"";}
  el("resource-action-description").textContent="Купи товар у других фермеров или выставь свой на общий рынок.";
  el("resource-action-buy").textContent="Купить";
  el("resource-action-sell").textContent="Выставить на продажу";
  el("resource-actions-dialog").showModal();
}
const adRewards={grain:[1,1,"🌾"],eggs:[2,2,"🥚"],milk:[5,1,"🥛"],chickens:[20,1,"🐔"],geese:[80,1,"🪿"],cows:[250,1,"🐄"],coins:[1,2,"🪙"]};
let selectedAdReward="grain";
let adProgress={};
function selectAdReward(item){
 if(!adRewards[item])return;
 selectedAdReward=item;
 const [views,quantity,emoji]=adRewards[item];
 const label=el("ad-reward-selection");
 if(label)label.textContent=emoji+" "+(adProgress[item]||0)+" из "+views+" просмотров · награда "+quantity+" шт.";
}
function loadAdRewardStatus(){return window.FarmAds?.recover();}
function claimAdRewards(){return window.FarmAds?.recover(true);}
function watchAdReward(item){return window.FarmAds?.watch(item);}
function openFreeResourceReward(item){
 const dialog=el("resource-actions-dialog");if(dialog?.open)dialog.close();
 return watchAdReward(adRewards[item]?item:"grain");
}

function resourceAction(action){
 const item=selectedResource;
 el("resource-actions-dialog").close();
 // A quick action must not navigate away from the original screen.
 if(action==="buy"){
  if(["eggs","milk","feathers"].includes(item))selectBuy(item);
  else showShop(item);
 }else if(action==="sell"){
  openSell(item);
 }
}
function openSystemSell(item){
 if(!state||!["grain","feathers"].includes(item)||pending)return;
 sellingResource=item;
 el("system-sell-title").textContent=item==="cows"?"🐄 Продать корову":item==="grain"?"🌾 Продать зерно":item==="geese"?"🪿 Продать гусыню":item==="feathers"?"🪶 Продать перья":"🐔 Продать курицу";
 el("system-sell-amount").value="1";
 el("system-sell-amount").max=String(Math.min(10000,state.me[item]));
 systemSellQuote();
 el("system-sell-dialog").showModal();
}
function systemSellAll(){
 if(!state||!sellingResource)return;
 el("system-sell-amount").value=String(Math.min(10000,state.me[sellingResource]));
 systemSellQuote();
}
function systemSellQuote(){
 if(!state||!sellingResource)return;
 const stock=state.me[sellingResource];
 const qty=Number(el("system-sell-amount").value);
 const valid=Number.isSafeInteger(qty)&&qty>=1&&qty<=Math.min(10000,stock);
 const price=systemBuyback[sellingResource];
 el("system-sell-stock").textContent="У тебя: "+number(stock)+" шт. · выкуп: "+price+" монет / шт.";
 el("system-sell-total").textContent=valid?number(qty*price):"—";
 el("system-sell-feedback").textContent=valid?(sellingResource==="feathers"?"Монеты поступят сразу после продажи.":"Начислим бонусные монеты: на покупки, без вывода."):"Укажи целое количество в пределах своего запаса.";
 el("system-sell-confirm").disabled=pending||!valid;
}
async function confirmSystemSell(){
 if(!state||!sellingResource||pending)return;
 const item=sellingResource;
 const qty=Number(el("system-sell-amount").value);
 if(!Number.isSafeInteger(qty)||qty<1||qty>Math.min(10000,state.me[item]))return systemSellQuote();
 const success=await perform("/api/shop/sell",{item,amount:qty});
 if(success){
  el("system-sell-dialog").close();
  toast("Продано системе: "+qty+" шт. · +"+number(qty*systemBuyback[item])+(item==="feathers"?" монет":" бонусных монет"));
 }
}
function openSell(item) {
 if(!state||pending)return;
 el("sellitem").value=item;
 el("sellprice").value=String(state.shop[item]|| (item==="feathers"?5:1));
 el("egg-sale-title").textContent="Выставить на рынок: "+itemNames[item];
 document.querySelector('label[for="sellnum"]').textContent="Количество";
 el("sellnum").value="1";
 sellType();
 const dialog=el("egg-sale-dialog");
 if(dialog&&!dialog.open)dialog.showModal();
}
function filterMarket(filter) {
  chosenFilter = filter;
  document.querySelectorAll("[data-filter]").forEach((x) => {
    x.classList.toggle("active", x.dataset.filter === filter);
    x.setAttribute("aria-pressed", String(x.dataset.filter === filter));
  });
  drawPool();
}
function marketRows(item) {
  return state
    ? state.market.filter((x) => x.item === item && x.seller !== state.me.name)
    : [];
}
function quote(item, n) {
  if (["eggs","milk"].includes(item)) {
    const available = Number((item==="milk"?state?.available_milk:state?.available_eggs) ?? 0);
    return {cost:(state.shop[item]||1)*n,remaining:Math.max(0,n-available)};
  }
  let remaining = n,
    cost = 0;
  for (const row of [...marketRows(item)].sort((a, b) => a.price - b.price)) {
    const count = Math.min(remaining, row.quantity);
    cost += count * row.price;
    remaining -= count;
    if (remaining <= 0) break;
  }
  return { cost, remaining };
}
function drawPool() {
  if (!state) return;
  document.querySelectorAll("[data-market-available]").forEach(node=>{
    const item=node.dataset.marketAvailable;
    const qty=marketRows(item).reduce((sum,row)=>sum+row.quantity,0);
    node.textContent="У игроков: "+number(qty)+" шт.";
  });
  const available = Number(state.available_eggs ?? 0);
  const label = el("eggs-available");
  const buy = el("eggs-buy-button");
  if (label) label.textContent = "Доступно для покупки: " + number(available) + " шт.";
  const milkAvailable=Number(state.available_milk||0);
  if(el("milk-available"))el("milk-available").textContent="Доступно для покупки: "+number(milkAvailable)+" шт.";
  if(el("milk-buy-button")){el("milk-buy-button").disabled=pending;el("milk-buy-button").textContent="Купить";}
  if (buy) {
    buy.disabled = pending;
    buy.textContent = "Купить";
  }
}
function selectBuy(item) {
  if (!state || pending) return;
  const rows = marketRows(item);
  const available = ["eggs","milk"].includes(item) ? Number((item==="milk"?state?.available_milk:state?.available_eggs) ?? 0) : rows.reduce((sum,row) => sum + row.quantity, 0);
  if (!available && !["eggs","milk","grain","chickens","geese","cows"].includes(item)) {
    toast(item==="milk"?"Сейчас нет молока в продаже":"Сейчас нет яиц в продаже");
    return;
  }
  openPurchase({
    kind: "market",
    item,
    price: ["eggs","milk"].includes(item) ? (state.shop[item]||1) : (rows.length?Math.min(...rows.map((x) => x.price)):(state.shop[item]||5)),
  });
}
function showShop(item) {
  if (!state) return;
  if(item==="geese" && (state.progression?.level||1)<(state.shop.goose_min_level||3))return toast("Гуси открываются с 3-го уровня. Зарабатывай опыт и развивай ферму!");
  const price = state.shop[item];
  if (!price) return;
  openPurchase({ kind: "shop", item, price });
}
function showBundle() {
  if (!state?.promotion?.active) return toast("Акция завершена");
  openPurchase({ kind: "bundle", item: "chickens", price: state.promotion.price });
}
function openPurchase(data) {
  if (pending) return;
  purchase = data;
  el("purchase-title").textContent =
    data.kind === "market"
      ? "Покупка: "+itemNames[data.item]
      : data.kind === "bundle"
        ? "Набор фермера"
        : "Покупка товара";
  el("purchase-name").textContent =
    data.kind === "bundle" ? "10 куриц + 100 зерна" : itemNames[data.item];
  el("purchase-price").textContent =
    data.kind === "bundle"
      ? `${state.promotion.price} монет · обычная стоимость ${state.promotion.value}`
      : `Цена: ${data.price} монет / шт.`;
  const img = el("purchase-dialog").querySelector(".purchase-art");
  img.src =
    "/assets/" +
    (data.kind === "bundle" ? "redesign/wallet" : art[data.item]) +
    (/\.(png|webp|svg)$/.test(art[data.item]||"")?"":".webp");
  el("purchase-amount").value = 1;
  el("purchase-amount").closest(".stepper").hidden = data.kind === "bundle";
  purchaseQuote();
  el("purchase-dialog").showModal();
}
function stepAmount(delta) {
  const value = Number(el("purchase-amount").value) || 1;
  el("purchase-amount").value = Math.max(1, Math.min(10000, value + delta));
  purchaseQuote();
}
function purchaseQuote() {
  if (!purchase || !state) return;
  const n = purchase.kind === "bundle" ? 1 : Number(el("purchase-amount").value);
  const valid = Number.isSafeInteger(n) && n >= 1 && n <= 10000;
  const market = purchase.kind === "market";
  const result = purchase.kind==="bundle"
    ? {cost:purchase.price*n,remaining:0}
    : quote(purchase.item,n);
  if(["grain","chickens","geese","cows"].includes(purchase.item) && result.remaining>0){
    result.cost+=result.remaining*(state.shop[purchase.item]||purchase.price);
    result.remaining=0;
  }
  el("purchase-total").textContent = valid ? number(result.cost) : "—";
  const room = purchase.item==="cows"?state.buildings.cowshed_capacity-(state.me.cows||0):["chickens","geese"].includes(purchase.item)
    ? state.buildings.coop_capacity - state.me.chickens - (state.me.geese||0)
    : state.buildings.storage_capacity - state.buildings.storage_used;
  const noRoom = purchase.kind !== "bundle" && n > room;
  const expired = purchase.kind === "bundle" && !promotionActive();
  let info = expired ? "Акция завершена"
    : noRoom ? (purchase.item==="cows"?"В коровнике нет места. Расширь его.":["chickens","geese"].includes(purchase.item) ? "Нет места для птиц. Увеличь вместимость в разделе «Животные»." : "На складе нет места. Улучши склад.")
    : !valid
    ? "Введите целое количество от 1 до 10 000"
    : result.remaining > 0
      ? (market && ["eggs","milk"].includes(purchase.item) && Number(state[purchase.item==="milk"?"available_milk":"available_eggs"]||0)===0
          ? (purchase.item==="milk"?"Молока пока нет в продаже. Оно появится, когда другие фермеры выставят его на рынок.":"Яиц пока нет в продаже. Они появятся, когда другие фермеры выставят их на рынок.")
          : "Доступного количества недостаточно")
      : result.cost > state.me.coins
        ? "Недостаточно монет на балансе"
        : market
          ? (purchase.item==="milk"?"Покупка молока у других игроков.":"Покупка яиц у других игроков.")
          : "Монеты поступят в игровую казну.";
  el("purchase-availability").textContent = info;
  el("purchase-confirm").disabled =
    pending || !valid || expired || noRoom || result.remaining > 0 || result.cost > state.me.coins;
}
async function confirmPurchase() {
  if (!purchase || pending) return;
  try {
    const data = { ...purchase },
      count = amount("purchase-amount");
    if (data.kind === "bundle") await perform("/api/bundle", {});
    else
      await perform(data.kind === "shop" ? "/api/shop" : "/api/buy", {
        item: data.item,
        amount: count,
        expected_price: data.kind === "shop" ? data.price : undefined,
      });
  } catch (error) {
    toast(error.message);
  }
}
function sellMaximum() {
  if(!state)return;
  const eggs=Math.min(10000,Math.max(0,Number(state.me[el("sellitem").value])||0));
  if(!eggs){toast("Пока нет товара для продажи");return;}
  el("sellnum").value=eggs;
  sellQuote();
}
function sellType() {
  const grainPriceWrap=el("grainPriceWrap");
  if(grainPriceWrap)grainPriceWrap.hidden=el("sellitem").value!=="grain";
  sellQuote();
}
function sellQuote() {
  if (!state) return;
  const item = el("sellitem").value,
    n = Number(el("sellnum").value),
    price = ["eggs","milk","feathers","chickens","geese","cows"].includes(item) ? (state.shop[item]||(item==="feathers"?5:1)) : Number(el("sellprice").value);
  const reserved=["chickens","geese","cows"].includes(item)?state.my_listings.filter(x=>x.item===item).reduce((v,x)=>v+x.quantity,0):0;
  const free=state.me[item]-reserved;
  el("myStock").textContent = `Доступно для продажи: ${number(free)} шт.`;
  el("sellquote").textContent =
    n > 0 && n <= free && price > 0
      ? number(n * price) + " монет"
      : "Недостаточно товара";
  const submit=el("egg-sale-confirm");
  if(submit)submit.disabled=pending||!Number.isSafeInteger(n)||n<1||n>free;
}
async function sellNow() {
  if(pending)return;
  try {
    const item=el("sellitem").value,n=amount("sellnum");
    if(!state||!["eggs","milk","grain","feathers","chickens","geese","cows"].includes(item))throw Error("Недостаточно товара");
    const success=await perform("/api/sell",{
      item,amount:n,price:state.shop[item]||(item==="feathers"?5:1),
    });
    if(success&&el("egg-sale-dialog")?.open)el("egg-sale-dialog").close();
  } catch(error){toast(error.message);}
}
function cancelLot(id) {
  const lot=state?.my_listings?.find(x=>x.id===id);
  if(!lot)return;
  const value=prompt("Сколько снять с продажи? (от 1 до "+lot.quantity+")",String(lot.quantity));
  if(value===null)return;
  const count=Number(value);
  if(!Number.isSafeInteger(count)||count<1||count>lot.quantity)return toast("Укажи целое количество от 1 до "+lot.quantity);
  perform("/api/cancel/"+id+"?amount="+count,{});
}
function autoQuote(input) {
  const n = Number(input.value);
  input.closest(".auto-card").querySelector("[data-auto-cost]").textContent =
    Number.isSafeInteger(n) && n > 0 ? `${number(2 * n)} монет` : "—";
}
function toggleAuto(id) {
  if (state) autoBuy(!state.me.autobuy_enabled, id);
}
function autoBuy(on, id) {
  try {
    perform("/api/autobuy", {
      item: on ? "on" : "off",
      amount: amount(id, 10000),
    });
  } catch (error) {
    toast(error.message);
  }
}
function storageFilter(filter, button) {
  document
    .querySelectorAll("[data-storage]")
    .forEach(
      (x) => (x.hidden = filter !== "all" && x.dataset.storage !== filter),
    );
  button.parentElement
    .querySelectorAll("button")
    .forEach((x) => x.classList.toggle("active", x === button));
}
const logNames = { grain: "Зерно", chickens: "Курицы", geese:"Гуси",cows:"Коровы",milk:"Молоко", feathers:"Перья", eggs: "Яйца" };
function details(text) {
  return text.replace(/grain|chickens|geese|cows|milk|feathers|eggs/g, (x) => logNames[x]);
}
async function redeemPromoCode(event) {
  event.preventDefault();
  if(pending || !token)return;
  const input=el("promo-code-input"),status=el("promo-code-status");
  const code=input.value.trim().toUpperCase();
  if(!code)return;
  try{
    busy(true);
    const result=await api("/api/promo/redeem",{code});
    input.value="";
    status.textContent="✓ Начислено "+number(result.awarded)+" монет!";
    toast("Бонус активирован: +"+number(result.awarded)+" монет");
    await refresh();
    await loadHistory();
  }catch(error){
    status.textContent=error.message;
    toast(error.message);
  }finally{busy(false);}
}
let historyOffset=0;
let historyExpanded=false;
async function toggleWalletHistory(){
 historyExpanded=!historyExpanded;
 const card=el("history-card");
 if(card)card.hidden=!historyExpanded;
 const arrow=el("history-toggle-arrow");
 if(arrow)arrow.textContent=historyExpanded?"⌄":"›";
 if(historyExpanded){historyOffset=0;await loadHistory();card?.scrollIntoView({behavior:"smooth",block:"nearest"});}
}
async function loadOlderHistory(){
 historyOffset+=10;
 await loadHistory(true);
}
async function loadHistory(append=false) {
 if(!historyExpanded)return;
 try {
  const value=await api("/api/finance?offset="+historyOffset+"&limit=10");
  const rows=value.entries.map(x=>
   `<div class="ledger-row ${x.delta>0?"income":""}"><span aria-hidden="true">${x.delta>=0?"↗":"↙"}</span><div><strong>${safe(details(x.details))}</strong><small>${x.bonus!=null?"Бонусные: "+number(x.bonus)+" · Выручка: "+number(x.earned)+" · ":""}${new Date(x.created*1000).toLocaleString("ru-RU")}</small></div><b>${x.delta>0?"+":""}${number(x.delta)}</b></div>`
  ).join("");
  const holder=el("history");
  if(append)holder.insertAdjacentHTML("beforeend",rows);
  else holder.innerHTML=rows||'<p class="empty">Пока нет операций.</p>';
  const more=el("history-more");
  if(more)more.hidden=!value.has_more;
 }catch(error){
  if(!append)el("history").textContent=error.message;
  else toast(error.message);
 }
}
async function loadWithdrawalStatus() {
  const note=el("withdrawal-status");
  if(!note||!token)return;
  try{
    const value=await api("/api/withdraw/status");
    const request=value.request;
    const cancelButton=el("withdrawal-cancel");
    if(cancelButton)cancelButton.hidden=!request||request.status!=="pending";
    const sources=value.sources||{};
    const usdPreview=el("usd-wallet-preview");
    if(usdPreview){
      const quote=value.future_usd_preview;
      usdPreview.textContent=quote?.quote_only && quote?.quote_currency==="USD"
        ? "💵 Оценка доступной выручки в USD: ≈ "+quote.quote_display+" (расчёт по зафиксированному курсу "+quote.uah_per_usd+" ₴/$; это не подтверждение долларового зачисления)."
        : "";
    }
    note.textContent="Бонусные: "+number(sources.bonus||0)+" · Пополненные: "+number(sources.purchased||0)+" · Выручка: "+number(value.available||0)+" монет. "+(request
      ? "Последняя заявка: "+number(request.amount)+" монет · "+
        (request.status==="pending"?"ожидает ручной проверки":request.status==="rejected"?"отклонена":"статус: "+request.status)
      : "Бонусы и промокоды переводить нельзя.");
  }catch(error){note.textContent="Не удалось проверить заявки: "+error.message;}
}
async function cancelWithdrawalRequest(){
  if(!token||pending)return;
  if(!confirm("Отменить текущую заявку на вывод? Зарезервированные монеты вернутся в кошелёк."))return;
  try{
    busy(true);
    const result=await api("/api/withdraw/cancel",{});
    toast(result.returned>0?"Заявка отменена: +"+number(result.returned)+" монет":"Заявка отменена");
    await refresh();
    await loadWithdrawalStatus();
    await loadHistory();
  }catch(error){toast(error.message);}finally{busy(false);}
}
let gameTransferKey="";
function openWithdrawalRequest() {
  if(!state)return toast("Сначала войдите в игру");
  if(!state.me.telegram_id){
    tab("profile");
    const settings=document.querySelector("#profile details.profile-settings");
    if(settings){settings.open=true;setTimeout(()=>settings.scrollIntoView({behavior:"smooth",block:"start"}),100);}
    toast("Откройте настройки ниже: там показано, как привязать Telegram. Затем перевод поступит на ваш баланс в боте.");
    return;
  }
  if(state.me.coins<100)return toast("Для заявки нужно минимум 100 монет");
  if(!gameTransferKey)gameTransferKey=crypto.randomUUID();
  el("withdrawal-amount").value=100;
  el("withdrawal-dialog").showModal();
}
let starsMaxCoins=1;
function updateTopupTotal(){
 const n=Number(el("topup-amount")?.value);
 const total=el("topup-total");
 if(total)total.textContent=Number.isInteger(n)&&n>=1&&n<=starsMaxCoins?"К оплате: "+(n*2).toLocaleString("ru-RU")+" ⭐":"Введите от 1 до "+starsMaxCoins+" монет";
}
async function openTopup(){
 const dialog=el("topup-dialog");
 if(!dialog)return;
 dialog.showModal();
 const field=el("topup-amount");
 if(field){field.max=starsMaxCoins;field.value=String(Math.min(starsMaxCoins,Math.max(1,Number(field.value)||1)));}
 try{
  const config=await api("/api/stars/config");
  starsMaxCoins=config.max_coins||1;
  if(field){field.max=starsMaxCoins;field.value=String(Math.min(starsMaxCoins,Math.max(1,Number(field.value)||1)));}
  const status=el("topup-limit");
  if(status)status.textContent="Доступно от 1 до "+starsMaxCoins+" монет за одну покупку.";
 }catch(e){toast("Не удалось проверить лимит оплаты. Повторите попытку.");}
 updateTopupTotal();
}
document.addEventListener("input",event=>{if(event.target?.id==="topup-amount")updateTopupTotal();});
async function submitTopup(){
 if(pending)return;
 const n=Number(el("topup-amount")?.value);
 if(!Number.isInteger(n)||n<1||n>starsMaxCoins)return toast("Укажи от 1 до "+starsMaxCoins+" монет");
 try{
  busy(true);
  const order=await api("/api/stars/invoice",{amount:n});
  if(!order.url||!order.url.startsWith("https://"))throw Error("Telegram не вернул ссылку на счёт");
  const tg=window.Telegram?.WebApp;
  if(tg?.openInvoice)tg.openInvoice(order.url,async status=>{if(status==="paid"){await refresh();await loadHistory();await loadStarsOrders();toast("Оплата подтверждена!");}});
  else window.open(order.url,"_blank");
  el("topup-dialog").close();
 }catch(e){
  if(e.status===503)toast("Покупки Stars пока не активированы. Монеты не списаны.");
  else if(e.status===403)toast("Сначала привяжите Telegram в профиле фермы.");
  else toast(e.message);
 }finally{busy(false);}
}
async function loadStarsOrders(){
 if(!token)return;
 const list=el("stars-order-list");
 if(!list)return;
 try{
  const res=await api("/api/stars/orders");
  list.innerHTML=res.orders.length?res.orders.map(o=>
   `<div class="stars-order-row"><div><strong>${number(o.coins)} 🪙 за ${number(o.stars)} ⭐</strong><small>${new Date(o.created*1000).toLocaleString("ru-RU")} · ${o.status==="paid"?"Оплачено":o.status==="refunded"?"Возвращено":"Ожидает оплаты"}</small></div></div>`
  ).join(""):'<p class="muted">Покупок ещё нет.</p>';
 }catch(e){list.textContent="Не удалось загрузить историю покупок.";}
}
async function submitWithdrawalRequest() {
  if(pending)return;
  try{
    const n=amount("withdrawal-amount",1000000);
    if(n<100)throw Error("Минимальная заявка — 100 монет");
    const conversionStatus=await api("/api/withdraw/status");
    const fx=Number(conversionStatus.future_usd_preview?.uah_per_usd);
    const futureAmount=Number.isFinite(fx)&&fx>0 ? (n/fx).toFixed(6) : null;
    const confirmation="Перевести "+number(n)+" игровых монет на баланс бота? Сейчас зачисление работает по старым условиям ("+number(n)+" грн)."+(futureAmount?"\nОценка после долларового перехода: ≈ $"+futureAmount+" (это НЕ сумма текущего зачисления).":"");
    if(!confirm(confirmation))return;
    busy(true);
    await api("/api/withdraw/request",{amount:n,transfer_id:gameTransferKey});
    gameTransferKey="";
    el("withdrawal-dialog").close();
    await refresh();
    await loadWithdrawalStatus();
    await loadHistory();
    toast("✅ Перевод в бот выполнен. До завершения долларового перехода зачисление остаётся гривневым.");
  }catch(error){toast(error.message);}
  finally{busy(false);}
}
function render() {
  if (typeof renderFields === 'function') renderFields();
  const p = state.me;
  for(const node of document.querySelectorAll("[data-system-stock]")){
    const resource=node.dataset.systemStock;
    node.textContent=(["chickens","geese"].includes(resource)?"Птиц: ":"На складе: ")+number(p[resource]||0);
  }
  if(el("system-sell-dialog")?.open)systemSellQuote();
  const isLinked = Boolean(p.telegram_id);
  const hasPassword = Boolean(state.has_password);
  if(el("telegram-link-status"))el("telegram-link-status").textContent=isLinked?"Telegram привязан ✓ — вход в эту же ферму доступен из бота":"Telegram не привязан";
  if(el("account-password-status"))el("account-password-status").textContent=hasPassword?"Пароль установлен ✓ — можно входить по нику":"Пароль не установлен — создай его для входа через сайт";
  if(el("current-password-wrap"))el("current-password-wrap").hidden=!hasPassword;
  if(el("set-password-button"))el("set-password-button").textContent=hasPassword?"Изменить пароль":"Установить пароль";
  if(el("link-telegram-button"))el("link-telegram-button").hidden=isLinked;
  if(el("telegram-link-help"))el("telegram-link-help").hidden=isLinked;
  if(el("telegram-browser-warning"))el("telegram-browser-warning").hidden=isLinked||Boolean(tgInitData());
  if(el("nickname-settings"))el("nickname-settings").hidden=false;
  if(el("settings-nickname") && document.activeElement!==el("settings-nickname"))el("settings-nickname").value=p.name;

  const farmDailyStats=state.day_stats||{};
  const assignStat=(id,value)=>{const node=el(id);if(node)node.textContent=number(value||0);};
  assignStat("stat-produced",farmDailyStats.eggs);
  assignStat("stat-milk",farmDailyStats.milk);
  assignStat("stat-feathers",farmDailyStats.feathers);
  assignStat("stat-sales",farmDailyStats.sales_coins);
  assignStat("stat-feed",farmDailyStats.feed_spent_coins);
  assignStat("stat-margin",farmDailyStats.feed_margin_coins);
  const pr = state.progression || {};
  const xp = Number(pr.xp || 0), lvl = Number(pr.level || 1);
  celebrateLevel(p.id,lvl);
  const gooseBuy=el("goose-buy-button");
  if(gooseBuy){gooseBuy.disabled=pending||lvl<3;gooseBuy.textContent=lvl<3?"Ур. 3":"Купить";}
  document.querySelectorAll("[data-birds-total]").forEach(n=>n.textContent=number(p.chickens+(p.geese||0)));
  const prev = 25*(lvl-1)*(lvl-1), next = Number(pr.next_level_xp || 25);
  const percent = Math.max(0,Math.min(100,100*(xp-prev)/Math.max(1,next-prev)));
  if (el("identity-level")) el("identity-level").textContent = "Уровень " + lvl + " · " + xp + " XP";
  if (el("identity-xp-fill")) el("identity-xp-fill").style.width = percent + "%";
  if (el("profile-level")) el("profile-level").textContent = "Уровень " + lvl + " · " + xp + " XP";
  if(el("profile-status"))el("profile-status").textContent="Статус: "+farmerTitle(lvl);
  for (const img of document.querySelectorAll(".identity .avatar, .profile-avatar")) img.src = avatarSource(p);
  const promo = state.promotion || {};
  document.querySelectorAll("[data-promo-discount]").forEach(x => x.textContent = `−${Math.round(100*(1-promo.price/promo.value))}%`);
  document.querySelectorAll("[data-promo-value]").forEach(x => x.textContent = number(promo.value));
  document.querySelectorAll("[data-promo-price]").forEach(x => x.textContent = number(promo.price));
  const inc=state.incubator||{};
  const jobs=inc.jobs||[];
  document.querySelectorAll("[data-incubator-capacity]").forEach(x=>x.textContent=number(inc.capacity||1));
  document.querySelectorAll("[data-incubator-price]").forEach(x=>x.textContent="Бесплатно");
  document.querySelectorAll("[data-incubate-duration]").forEach(x=>x.textContent=formatDuration(inc.incubate_seconds||43200));
  document.querySelectorAll("[data-grow-duration]").forEach(x=>x.textContent=formatDuration(inc.grow_seconds||43200));
  if (el("incubator-level"))el("incubator-level").textContent=number(inc.level||1);
  if (el("incubator-free"))el("incubator-free").textContent=number(Math.max(0,(inc.capacity||1)-jobs.length));
  const up=el("incubator-upgrade");
  if (up){up.hidden=!inc.owned;up.disabled=pending||inc.next_upgrade_cost==null||p.coins<inc.next_upgrade_cost;up.textContent=inc.next_upgrade_cost==null?"Максимальный уровень":"Улучшить · "+number(inc.next_upgrade_cost)+" монет";}
  const button=el("incubator-action");
  if(button){const full=jobs.length>=(inc.capacity||1);
    button.textContent=!inc.owned?"Получить бесплатно":"Заложить 20 яиц";
    button.disabled=pending||(!inc.owned?p.coins<inc.incubator_price:full||p.eggs<20||p.chickens+(p.geese||0)+jobs.length>=state.buildings.coop_capacity);}
  const guide=el("launch-guide");
  if(guide)guide.hidden=!(Date.now()/1000<(p.created_at||0)+3600 && !storage.getItem("farm_guide_dismissed_"+p.id));
  const tutorial=state.tutorial||{};
  const step=Math.min(3,tutorial.step||0), card=el("tutorial-card");
  if(card){card.hidden=step>=3;if(step<3){el("tutorial-progress").textContent="Шаг "+(step+1)+" из 3";el("tutorial-instruction").textContent=["Посмотри своих животных и время до следующего яйца.","Зерно можно купить на Рынке. Животные едят автоматически раз в 18 часов.","Из яиц можно вырастить кур в инкубаторе или продать их игрокам."][step];el("tutorial-next").textContent=["Посмотреть животных","Где купить зерно?","Понятно · получить 5 монет"][step];}}
  const history = el("production-history");
  if (history) history.innerHTML = state.production_history?.length
    ? state.production_history.map(event => `<div class="ledger-row income">${image("redesign/egg")}<div><strong>+${number(event.amount)} яиц</strong><small>${new Date(event.created * 1000).toLocaleString("ru-RU")}</small></div></div>`).join("")
    : '<p class="empty">Сборов пока не было. Здесь появятся яйца, произведённые твоими курами.</p>';
  const buildings = state.buildings || {};
  document.querySelectorAll("[data-building]").forEach((node) => {
    const value = buildings[node.dataset.building];
    node.textContent = typeof value === "number" ? number(value) : "—";
  });
  for (const kind of ["coop","storage","cowshed"]) {
    const button = el("upgrade-"+kind);
    if (!button) continue;
    const price = buildings[kind+"_next_cost"];
    button.disabled = price == null || price > p.coins || pending;
    button.textContent = price == null ? "Максимальный уровень" : "Улучшить · "+number(price)+" монет";
  }
  const shopIncubator = el("incubator-shop-button");
  if (shopIncubator) {
    shopIncubator.textContent = inc.owned ? "Открыть" : "Купить";
    shopIncubator.disabled = pending || (!inc.owned && p.coins < inc.incubator_price);
  }
  const last = state.last_farm_event;
  if (last && ["eggs_produced","chick_matured","milk_produced","feathers_collected"].includes(last.kind)) {
    const seenKey = "farm_seen_event_" + p.id;
    if (storage.getItem(seenKey) !== last.id) {
      storage.setItem(seenKey, last.id);
      toast(last.kind === "chick_matured" ? "Цыплёнок вырос! +1 курица." : last.kind === "milk_produced" ? "🥛 Получено молока: "+number(last.amount)+". Оно на складе!" : last.kind === "feathers_collected" ? "🪶 Собрано перьев: "+number(last.amount)+". Они на складе!" : "Птицы снесли " + number(last.amount) + " яиц! Они уже на складе.");
    }
  }
  const progression = state.progression || {};
  const farmerLevel = el("farmer-level");
  const farmerXp = el("farmer-xp-caption");
  const xpBar = el("farmer-xp-bar");
  if (farmerLevel) farmerLevel.textContent = "Уровень " + number(progression.level || 1) + " · " + number(progression.xp || 0) + " XP";
  const totalXp = progression.xp || 0;
  const level = progression.level || 1;
  const baseXp = 25 * (level-1) * (level-1);
  const nextXp = progression.next_level_xp || 25;
  if (farmerXp) farmerXp.textContent = "До следующего уровня: " + number(Math.max(0,nextXp - totalXp)) + " XP";
  if (xpBar) xpBar.style.width = Math.min(100,100*Math.max(0,totalXp-baseXp)/Math.max(1,nextXp-baseXp)) + "%";
  // The legacy static achievement cards are intentionally not rendered here.
  // The server returns exactly the next unclaimed cumulative stage per track.
  const achievementList = el("achievements-list");
  const stageRows = progression.staged_achievements || [];
  if (achievementList) {
    const labels = {
      eggs:["🥚","яйцо","яйца","яиц"],
      feathers:["🪶","перо","пера","перьев"],
      milk:["🥛","единица молока","единицы молока","единиц молока"],
      chickens_bought:["🐔","курица","курицы","кур"],
      geese_bought:["🪿","гусь","гуся","гусей"],
      cows_bought:["🐄","корова","коровы","коров"],
      market_sales:["📦","продажа","продажи","продаж"],
      market_purchases:["🛒","покупка","покупки","покупок"],
      feeding:["🌾","кормление","кормления","кормлений"]
    };
    const stageTitle = stage => {
      const forms = labels[stage.track] || ["🏅","действие","действия","действий"];
      const n = Number(stage.threshold);
      const word = n%10===1 && n%100!==11 ? forms[1] : (n%10>=2 && n%10<=4 && (n%100<12 || n%100>14) ? forms[2] : forms[3]);
      return n===1 ? "Первое: " + forms[1] : number(n) + " " + word;
    };
    achievementList.innerHTML = stageRows.map(stage => {
      const [emoji] = labels[stage.track] || ["🏅"];
      const ready = Boolean(stage.claimable);
      return '<div class="achievement-row"><span class="achievement-emoji">'+emoji+'</span><div><strong>'+stageTitle(stage)+'</strong><small>'+number(stage.progress)+' / '+number(stage.threshold)+' · +'+number(stage.xp)+' XP</small></div><button class="btn small" '+(ready?'':'disabled')+' onclick="claimAchievement(\''+stage.track+'\')">'+(ready?'Получить XP':'Ещё не выполнено')+'</button></div>';
    }).join("");
  }
  const daily = state.daily || {};
  const claimed = new Set(state.claimed_rewards || []);
  const dailyMissions = [
    ["grain", "Купить 5 зерна", daily.grain_bought || 0, 5],
    ["eggs", "Получить 3 яйца от птиц", daily.eggs_produced || 0, 3],
    ["listing", "Выставить яйцо на продажу", daily.eggs_listed || 0, 1],
    ["market_sale", "Продать товар на рынке", daily.market_sale || 0, 1],
    ["market_buy", "Купить товар у другого игрока", daily.market_buy || 0, 1],
    ["buy_chicken", "Купить курицу", daily.buy_chicken || 0, 1],
    ...((p.farmer_level>=3||daily.buy_goose>0)?[["buy_goose", "Купить гуся", daily.buy_goose || 0, 1]]:[]),
    ...((p.cows>0||daily.buy_cow>0||p.coins>=500)?[["buy_cow", "Купить корову", daily.buy_cow || 0, 1]]:[]),
    ...(((p.chickens||0)+(p.geese||0)+(p.cows||0)>0||daily.feeding>0)?[["feeding","Покормить животных",daily.feeding||0,1]]:[]),
    ...((p.cows>0||daily.milk>0)?[["milk","Собрать молоко",daily.milk||0,1]]:[]),
    ...((p.cows>0||p.milk>0||daily.milk_listing>0)?[["milk_listing","Выставить молоко на рынок",daily.milk_listing||0,1]]:[]),
    ...((daily.feather>0||claimed.has("feather"))?[["feather","Собрать редкое перо",daily.feather||0,1]]:[])
  ];
  const dailyBox = el("daily-tasks");
  if (dailyBox) {
    const bonusDone = claimed.has("bonus");
    const rewards = state.reward_values;
    dailyBox.innerHTML = '<div class="daily-task"><div><strong>Бонус за вход</strong><small>+' + number(rewards.bonus) + ' монет · раз в сутки</small></div><button class="btn small" ' + (bonusDone ? 'disabled' : '') + ' onclick="claimDaily(\'bonus\')">' + (bonusDone ? 'Получено ✓' : 'Получить +' + number(rewards.bonus)) + '</button></div>' +
      dailyMissions.map(([key,name,value,target]) => {
        const n = Math.min(value,target);
        const done = n >= target;
        const isClaimed = claimed.has(key);
        return '<div class="daily-task"><div><strong>' + name + '</strong><small>' + number(n) + ' / ' + target + ' · +' + number(rewards[key]) + ' монет</small></div><div class="progress"><span style="width:' + (100*n/target) + '%"></span></div><button class="btn small" ' + (!done || isClaimed ? 'disabled' : '') + ' onclick="claimDaily(\'' + key + '\')">' + (isClaimed ? 'Получено ✓' : done ? 'Забрать +' + number(rewards[key]) : 'Выполни задание') + '</button></div>';
      }).join("");
  }
  const f = state.farm;
  const approx = f.forecast_approximate ? "~" : "";
  document.querySelectorAll("[data-eggs-6h]").forEach(x => x.textContent = `${approx}+${eggQuantity(f.eggs_next_6h)}`);
  document.querySelectorAll("[data-eggs-12h]").forEach(x => x.textContent = `${approx}+${eggQuantity(f.eggs_next_12h)}`);
  document.querySelectorAll("[data-feed-required]").forEach(x => x.textContent = number(f.grain_required_next_feed));
  document.querySelectorAll("[data-fed-hens]").forEach(x => x.textContent = number(f.fed_hens));
  document.querySelectorAll("[data-fed-birds]").forEach(x => x.textContent = number(f.fed_hens+(f.fed_geese||0)));
  document.querySelectorAll("[data-forecast-note]").forEach(x => x.textContent = f.forecast_note);
  const brief=el("forecast-brief"); brief.hidden=!f.forecast_approximate; brief.textContent="Есть взрослеющие цыплята — оценка для нынешних несушек.";
  const feedStatus = f.effective_grain_shortage > 0 ? "Недостаточно зерна для следующего кормления."
    : f.grain_shortage > 0 ? "Запас пополнит автозакупка, если хватит монет и места." : "Зерна для следующего кормления достаточно.";
  document.querySelectorAll("[data-feed-status]").forEach(x => {x.textContent = feedStatus;x.dataset.alert = String(f.effective_grain_shortage > 0);});
  document.querySelectorAll("[data-free-grain-shortage]").forEach(x=>x.hidden=!(f.effective_grain_shortage>0));
  document.querySelectorAll("[data-buy-feed]").forEach(x => x.classList.toggle("needs-feed", f.effective_grain_shortage > 0));
  const storageWarning = el("storage-warning");
  storageWarning.hidden = buildings.storage_used < buildings.storage_capacity;
  storageWarning.textContent = `Склад заполнен: ${number(buildings.storage_used)} / ${number(buildings.storage_capacity)}. Новые яйца, молоко и перья не поместятся. Продай товары или улучши склад.`;
  el("login").hidden = true;
  el("app").hidden = false;
  el("nav").hidden = false;
  hideStartup();
  document.querySelectorAll("[data-value]").forEach((x) => {
    const v = p[x.dataset.value];
    x.textContent = typeof v === "number" ? number(v) : v;
  });
  const sat = Math.max(0, Math.min(100, p.satiety ?? 100));
  document
    .querySelectorAll("[data-sat]")
    .forEach((x) => (x.textContent = sat + "%"));
  document.querySelectorAll("[data-sat-bar]").forEach((x) => {
    x.style.width = sat + "%";
    x.parentElement.setAttribute("aria-valuenow", sat);
    x.style.background = sat < 35 ? "linear-gradient(#ffb65d,#db3b29)" : "";
  });
  const ration=el("feed-ration");
  if(ration)ration.hidden=!(f.grain_required_next_feed>0);
  el("warning").textContent = state.farm.effective_grain_shortage > 0 ? "Недостаточно зерна для следующего кормления." : "Кормление раз в 18 часов · курица: 1 зерно, гусыня: 2, корова: 3.";
  el("warning").dataset.alert = String(state.farm.effective_grain_shortage > 0);
  el("warning").hidden=state.farm.effective_grain_shortage<=0;
  const feedAlert=el("feed-alert");
  if(feedAlert)feedAlert.hidden=!(state.farm.effective_grain_shortage>0);

  document.querySelectorAll(".auto-card").forEach((card) => {
    const input = card.querySelector("input");
    if (document.activeElement !== input) input.value = p.autobuy_amount;
    autoQuote(input);
    card
      .querySelector(".auto-toggle")
      .setAttribute("aria-pressed", String(p.autobuy_enabled));
    card.querySelector(".auto-toggle").disabled = pending;
    const shortAfterBuy=Math.max(0,f.grain_required_next_feed-p.grain-p.autobuy_amount);
    card.querySelector("[data-auto-status]").textContent = p.autobuy_enabled
      ? `Включена · ${p.autobuy_amount} зерна при нехватке корма`+(p.coins<2*p.autobuy_amount?" · не хватает монет на закупку":shortAfterBuy>0?" · для полного кормления не хватит ещё "+number(shortAfterBuy)+" зерна":"")
      : "Автозакупка выключена";
  });
  const weekly=state.weekly||{}, targets=weekly.targets||{};
  let weeklyDone=true;
  for (const key of ["grain","eggs","listed"]) {
    const target=targets[key]||1,value=key==="eggs"&&weekly.milk>=3?target:key==="grain"&&weekly.feeding>=5?target:key==="listed"&&weekly.market_sales>=3?target:Math.min(target,weekly[key]||0);
    weeklyDone=weeklyDone&&value>=target;
    const count=el("weekly-count-"+key)||document.querySelector(`[data-weekly="${key}"]`);
    const bar=document.querySelector(`[data-weekly-bar="${key}"]`);
    const status=document.querySelector(`[data-weekly-status="${key}"]`);
    if(count)count.textContent=key==="eggs"?Math.min(target,weekly.eggs||0)+" / "+target+" яиц · "+Math.min(3,weekly.milk||0)+" / 3 молока":key==="grain"?Math.min(10,weekly.grain||0)+" / 10 зерна · "+Math.min(5,weekly.feeding||0)+" / 5 скормлено":key==="listed"?Math.min(3,weekly.listed||0)+" / 3 выставлено · "+Math.min(3,weekly.market_sales||0)+" / 3 продано":value+" / "+target;
    if(bar)bar.style.width=(100*value/target)+"%";
    if(status)status.textContent=value>=target?"Готово":"В процессе";
  }
  const weeklyExtra=el("weekly-extra");
  if(weeklyExtra){
    const objectives=[
      ["🛒 Купить 3 товара на рынке",weekly.market_purchases||0,3],
      ["🥛 Собрать 5 единиц молока",weekly.milk||0,5,Boolean(p.cows||weekly.milk)],
      ["🪶 Получить редкое перо",weekly.feathers||0,1,Boolean(p.geese||weekly.feathers)]
    ].filter(row=>row.length<4||row[3]);
    weeklyExtra.innerHTML='<h3>Дополнительные цели недели</h3><p class="muted">Не обязательны для получения основной награды. Редкое перо — случайный дроп.</p>'+
      objectives.map(([name,value,target])=>'<div class="daily-task"><div><strong>'+name+'</strong><small>'+number(Math.min(value,target))+' / '+target+'</small></div><div class="progress"><span style="width:'+(100*Math.min(value,target)/target)+'%"></span></div></div>').join("");
  }
  const claim=el("weekly-claim");
  if(claim){claim.disabled=pending||!weeklyDone||weekly.claimed;claim.textContent=weekly.claimed?"🏆 Награда получена ✓":"🏆 Забрать награду: +"+(weekly.reward||30)+" монет";}
  const dead=el("weekly-deadline");
  if(dead&&weekly.ends_at){const hours=Math.max(0,Math.ceil((weekly.ends_at-Date.now()/1000)/3600));dead.textContent="До конца недели: "+Math.floor(hours/24)+" дн. "+hours%24+" ч";}

  el("leaders").innerHTML = state.top.slice(0,5)
    .map(
      (x, i) =>
        `<div class="ledger-row"><b>${i + 1}</b><div><strong>${safe(x.name)}</strong><small>Основной уровень</small></div><b>Ур. ${number(x.farmer_level||1)}</b></div>`,
    )
    .join("");
  if(el("my-rank"))el("my-rank").textContent="Ваше место: "+(state.my_rank?number(state.my_rank):"—");
  el("mylist").innerHTML = state.my_listings.length
    ? state.my_listings
        .map(
          (x) =>
            `<div class="product">${image(art[x.item], "product-image")}<div><h3>${logNames[x.item]||itemNames[x.item]}</h3><small>${number(x.quantity)} шт. · ${number(x.price)} монет/шт.</small></div><button class="btn alt small" onclick="cancelLot('${safe(x.id)}')">Вернуть</button></div>`,
        )
        .join("")
    : '<p class="empty">У тебя нет активных объявлений.</p>';
  drawPool();
  sellQuote();
  countdown();
  if (el("purchase-dialog").open) purchaseQuote();
}
function clockDuration(seconds) {
  const n = Math.max(0, Math.ceil(seconds));
  return [Math.floor(n/3600),Math.floor(n/60)%60,n%60].map(x=>String(x).padStart(2,"0")).join(":");
}
function formatDuration(seconds) {
  const n = Math.max(0, Math.ceil(seconds));
  return `${Math.floor(n / 3600)} ч ${String(Math.floor((n % 3600) / 60)).padStart(2,"0")} мин ${String(n % 60).padStart(2,"0")} с`;
}
function elapsedSeconds() { return Math.max(0, (Date.now() - refreshedAt) / 1000); }
function promotionActive() {
  return !!state?.promotion?.active && state.promotion.seconds_left > elapsedSeconds();
}
function countdown() {
  if (!state) return;
  const elapsed = elapsedSeconds();
  const reserve=Math.max(0,(state.farm.feed_stock_seconds||0)-elapsed);
  el("feedstock").textContent=state.farm.grain_required_next_feed>0
    ? (reserve>=3600?"~"+Math.floor(reserve/3600)+" часов":Math.ceil(reserve/60)+" мин")
    : "— (нет животных)";
  const promo = state.promotion;
  const promoActive = promotionActive();
  el("promo-status").textContent = promoActive
    ? `До конца: ${formatDuration(promo.seconds_left - elapsed)} · осталось покупок: ${Math.max(0,promo.limit-promo.used)} / ${promo.limit}`
    : "Акция завершена";
  el("bundle-buy").disabled = pending || !promoActive || state.me.coins < promo.price;
  const inc=state.incubator||{}, now=state.now+elapsed;
  const jobs=inc.jobs||[];
  const full=state.me.chickens+(state.me.geese||0)>=state.buildings.coop_capacity;
  const status=!inc.owned?"Инкубатор ещё не куплен":jobs.length===0?"Свободен · заложи 12 яиц":jobs.length+" из "+inc.capacity+" мест занято";
  if(el("incubation-status"))el("incubation-status").textContent=status;
  document.querySelectorAll("[data-incubator-summary]").forEach(x=>x.textContent=status);
  const list=el("incubator-jobs");
  if(list)list.innerHTML=jobs.map((j,i)=>{
    const hatch=now<j.hatch_at;
    const remaining=(hatch?j.hatch_at:j.mature_at)-now;
    const label=remaining<=0&&full?"Нужно свободное место для птицы":remaining<=0?"Завершается…":formatDuration(remaining);
    return '<div class="incubator-job"><strong>'+(hatch?'🥚 Яйцо':'🐣 Цыплёнок')+' №'+(i+1)+'</strong><span>'+safe(label)+'</span></div>';
  }).join("") || '<p class="muted">Все ячейки свободны.</p>';
  document.querySelectorAll("[data-stage]").forEach(x=>x.classList.toggle("active",inc.owned&&jobs.length>0&&x.dataset.stage===(now<jobs[0].hatch_at?"egg":"chick")));
  const eggScheduled=state.farm.next_egg_scheduled!==false;
  const seconds = Math.max(0,state.farm.seconds_to_next_egg - elapsed);
  const eggLabel=eggScheduled?clockDuration(seconds):({empty:"Нет птицы",storage_full:"Склад заполнен",needs_feed:"Нужен корм"}[state.farm.next_egg_status]||"Ожидаем условия");
  document.querySelectorAll("[data-next-tick]").forEach(x => x.textContent = eggLabel);
  const eggPart=document.querySelector('[data-egg-forecast]');if(eggPart)eggPart.hidden=!(state.me.chickens+(state.me.geese||0)>0);
  const emptyHarvest=el("harvest-empty");if(emptyHarvest)emptyHarvest.hidden=!!(state.me.chickens+(state.me.geese||0)+(state.me.cows||0));
  const gooseCount=state.me.geese||0, fedGeese=state.farm.fed_geese||0;
  const featherCard=document.querySelector('[data-feather-card]');
  if(featherCard)featherCard.hidden=!gooseCount;
  const featherRemaining=Math.max(0,(state.farm.seconds_to_next_feather||0)-elapsed);
  const warehouseFull=state.buildings.storage_used>=state.buildings.storage_capacity;
  const featherLabel=!gooseCount?"Нет гусей":!state.farm.next_feather_scheduled?(state.farm.next_feather_status==="storage_full"?"Склад заполнен":"Нет доступного сбора — проверь корм"):featherRemaining<=0?"Обновляем…":
    (featherRemaining>=86400?Math.floor(featherRemaining/86400)+" д ":"")+clockDuration(featherRemaining%86400);
  document.querySelectorAll('[data-feather-tick]').forEach(x=>x.textContent=featherLabel);
  const featherProgress=Math.min(100,100*((state.me.feather_progress||0)+fedGeese*elapsed)/(7*86400));
  document.querySelectorAll('[data-feather-progress]').forEach(x=>{x.setAttribute('aria-valuenow',Math.floor(featherProgress));x.firstElementChild.style.width=featherProgress+'%';});
  document.querySelectorAll('[data-feather-note]').forEach(x=>x.textContent=!gooseCount?'Перья дают гуси. Купи гусыню на рынке — здесь появится время до следующего пера.':warehouseFull?'Освободи место: новые перья не сохраняются.':!fedGeese?'Пока гуси голодны, прогресс пера приостановлен.':'Сытых гусей: '+fedGeese+' из '+gooseCount+'. Один гусь даёт перо за 7 дней сытости. Таймер предполагает постоянный корм.');
  const milkScheduled=Boolean(state.farm.next_milk_scheduled),milkSeconds=Math.max(0,(state.farm.seconds_to_next_milk||0)-elapsed);
  document.querySelectorAll('[data-next-milk]').forEach(x=>x.textContent=milkScheduled?clockDuration(milkSeconds):({empty:"Нет коров",needs_feed:"Нужен корм",storage_full:"Склад заполнен"}[state.farm.next_milk_status]||"Ожидаем условия"));
  document.querySelectorAll('[data-milk-12h]').forEach(x=>x.textContent="+"+number(state.farm.milk_next_12h||0)+" шт.");
  const milkCard=document.querySelector('[data-milk-card]');if(milkCard)milkCard.hidden=!(state.me.cows>0);
  const nextFeed = Math.max(0,state.farm.seconds_to_next_feed-elapsed);
  document.querySelectorAll("[data-feed-tick]").forEach(x => x.textContent=clockDuration(nextFeed));
  // Reconcile completed timers with the server; the browser never grants resources.
  const completedJobs = jobs.some(j => now >= j.mature_at) && !full;
  const featherDue=state.farm.seconds_to_next_feather>0&&elapsed>=state.farm.seconds_to_next_feather;
  const expired = (eggScheduled && seconds <= 0) || nextFeed <= 0 || completedJobs || featherDue || (milkScheduled&&milkSeconds<=0);
  if (expired && !pending && !refreshPromise && elapsed >= 1 && Date.now()-lastTimerRefresh >= 5000 && document.visibilityState === "visible") { lastTimerRefresh=Date.now(); refresh(); }
  if (el("purchase-dialog").open) purchaseQuote();
}
async function refresh() {
  if (refreshPromise) return refreshPromise;
  refreshPromise = (async () => {
    try {
      state = await api("/api/state");
      refreshedAt = Date.now();
      render();
      hideStartup();
      window.FarmAds?.recover();
    } catch (error) {
      if (error.status === 401) {hideStartup();showLogin();}
      else if(el("app").hidden){
        if(!retryTransientStartup(error))showStartupError();
      }
      else toast("Не удалось обновить данные: " + error.message);
    } finally {
      refreshPromise = null;
    }
  })();
  return refreshPromise;
}
function logout() {
  if (
    confirm(
      "Выйти из фермы? Для следующего входа понадобится ник и пароль либо привязанный Telegram.",
    )
  ) {
    showLogin();
    state = null;
  }
}
document.addEventListener("visibilitychange", () => {
  if (token && document.visibilityState === "visible") refresh();
});
setInterval(() => {
  if (
    token &&
    !pending &&
    document.visibilityState === "visible" &&
    !el("purchase-dialog").open
  )
    refresh();
}, 60000);
setInterval(countdown, 1000);
tab("farm");
if (token) {refresh();loadAdRewardStatus();}
else showLogin();

async function configureTelegramEntry(){
  const init=Boolean(tgInitData());
  let enabled=false;
  if(init) {
    try{const config=await api("/api/auth/config");enabled=Boolean(config.telegram_enabled);}
    catch(e){enabled=false;}
  }
  document.querySelectorAll(".telegram-entry").forEach(x=>x.hidden=!(init&&enabled));
  window.Telegram?.WebApp?.ready?.();
}
configureTelegramEntry();
window.addEventListener("telegram-sdk-ready",configureTelegramEntry);


function openBotWallet(){
 const url="https://t.me/Farmlife2026bot?start=wallet";
 const tg=window.Telegram?.WebApp;
 if(tg?.openTelegramLink)tg.openTelegramLink(url);
 else window.open(url,"_blank","noopener,noreferrer");
}

function celebrateLevel(playerId,level){
 if(!playerId)return;
 const key="farm_seen_level_"+playerId;
 let previous=0;
 try{previous=Number(storage.getItem(key)||0);storage.setItem(key,String(Math.max(previous,level)));}catch(e){return;}
 if(!previous||level<=previous)return;
 const dialog=el("level-up-dialog");
 if(!dialog)return;
 el("level-up-number").textContent=String(level);
 el("level-up-description").textContent=previous<3&&level>=3?"Теперь в магазине доступны гуси — больше яиц и новые возможности для фермы!":"Твоё хозяйство растёт! Продолжай производить, торговать и развивать ферму.";
 dialog.showModal();
}

function farmerTitle(level){return level>=15?"Хозяин фермы":level>=10?"Мастер фермы":level>=5?"Фермер":level>=3?"Птицевод":"Новичок";}

const farmAdButton=el("ad-reward-watch");
if(farmAdButton)farmAdButton.addEventListener("click",()=>watchAdReward(selectedAdReward));
