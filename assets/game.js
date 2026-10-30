"use strict";
const el = (id) => document.getElementById(id);
const art = {
  grain: "redesign/grain",
  eggs: "redesign/egg",
  chickens: "redesign/hen",
};
function eggQuantity(n) {
  const v=Math.abs(n)%100, last=v%10;
  return `${number(n)} ${v>=11 && v<=14 ? "яиц" : last===1 ? "яйцо" : last>=2 && last<=4 ? "яйца" : "яиц"}`;
}
const itemNames = { grain: "Зерно", eggs: "Яйцо", chickens: "Курица" };
const number = (n) => new Intl.NumberFormat("ru-RU").format(n);
let token = localStorage.getItem("farm_token");
let state = null,
  pending = false,
  chosenFilter = "all",
  currentTab = "farm",
  purchase = null;
let refreshPromise = null,
  refreshedAt = 0;
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
  return `<img src="/assets/${path}.webp" class="${cls}" alt="" decoding="async">`;
}
function toast(message) {
  el("toast").textContent = message;
  el("toast").hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (el("toast").hidden = true), 4500);
}
async function api(path, payload) {
  const response = await fetch(path, {
    method: payload === undefined ? "GET" : "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: "Bearer " + (token || ""),
    },
    body: payload === undefined ? undefined : JSON.stringify(payload),
    cache: "no-store",
  });
  const value = await response.json();
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
async function claimDaily(key) {
  if (pending) return;
  const completed = await perform("/api/claim", {item:key});
  if (completed) toast("Награда получена! Монеты начислены.");
}
async function upgradeBuilding(kind) {
  if (pending || !state || !["coop","storage"].includes(kind)) return;
  const values = state.buildings || {};
  const price = values[kind + "_next_cost"];
  if (price == null) return;
  const name = kind === "coop" ? "курятник" : "склад";
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
function tgInitData() {return window.Telegram?.WebApp?.initData || "";}
async function useLoginResult(result) {
  token=result.token;
  localStorage.setItem("farm_token",token);
  await refresh();
}
async function telegramLogin() {
  if(pending)return;
  try{busy(true);await useLoginResult(await api("/api/telegram/login",{telegram_data:tgInitData()}));}
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
  localStorage.removeItem("farm_token");
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
    const result = await api("/api/join", { name: el("name").value.trim(), gender: el("join-gender").value, password: el("register-password").value });
    token = result.token;
    localStorage.setItem("farm_token", token);
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
    localStorage.setItem("farm_token",token);
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
  if (!el(id)?.classList.contains("panel")) return;
  currentTab = id;
  document.body.dataset.screen = id;
  document
    .querySelectorAll(".panel")
    .forEach((x) => x.classList.toggle("active", x.id === id));
  document.querySelectorAll("[data-tab]").forEach((x) => {
    const active = x.dataset.tab === (id === "market" ? "shop" : id);
    x.classList.toggle("active", active);
    if (active) x.setAttribute("aria-current", "page");
    else x.removeAttribute("aria-current");
  });
  window.scrollTo({ top: 0, behavior: "instant" });
  if (id === "wallet") { loadHistory(); loadWithdrawalStatus(); }
}
function dismissLaunchGuide(){
 if(!state?.me?.id)return;
 localStorage.setItem("farm_guide_dismissed_"+state.me.id,"1");
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
  const achievements = which === "achievements";
  const achievementsPane = el("achievement-pane");
  const goalsPane = el("goals-pane");
  if (!achievementsPane || !goalsPane) return;
  achievementsPane.hidden = !achievements;
  goalsPane.hidden = achievements;
  for (const [id, active] of [["tasks-switch",!achievements],["achievements-switch",achievements]]) {
    const button = el(id);
    if (button) {
      button.classList.toggle("active",active);
      button.setAttribute("aria-pressed",String(active));
    }
  }
}
function marketTab(mode) {
  if (mode === "buy") tab("shop");
  else tab("market");
}
function openSell(item) {
  tab("market");
  el("sellitem").value = item;
  sellType();
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
  if (item === "eggs") {
    const available = Number(state?.available_eggs ?? 0);
    return {cost:(state.shop.eggs||1)*n,remaining:Math.max(0,n-available)};
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
  const available = Number(state.available_eggs ?? 0);
  const label = el("eggs-available");
  const buy = el("eggs-buy-button");
  if (label) label.textContent = "Доступно для покупки: " + number(available) + " шт.";
  if (buy) {
    buy.disabled = available <= 0;
    buy.textContent = available > 0 ? "Купить" : "Нет в наличии";
  }
}
function selectBuy(item) {
  const rows = marketRows(item);
  const available = item === "eggs" ? Number(state?.available_eggs ?? 0) : rows.reduce((sum,row) => sum + row.quantity, 0);
  if (!available) {
    toast("Сейчас нет яиц в продаже");
    return;
  }
  openPurchase({
    kind: "market",
    item,
    price: item === "eggs" ? (state.shop.eggs||1) : Math.min(...rows.map((x) => x.price)),
  });
}
function showShop(item) {
  if (!state) return;
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
      ? "Покупка яиц"
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
    ".webp";
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
  const result = market
    ? quote(purchase.item, n)
    : { cost: purchase.price * n, remaining: 0 };
  el("purchase-total").textContent = valid ? number(result.cost) : "—";
  const room = purchase.item === "chickens"
    ? state.buildings.coop_capacity - state.me.chickens
    : state.buildings.storage_capacity - state.buildings.storage_used;
  const noRoom = purchase.kind !== "bundle" && n > room;
  const expired = purchase.kind === "bundle" && !promotionActive();
  let info = expired ? "Акция завершена"
    : noRoom ? (purchase.item === "chickens" ? "В курятнике нет места. Улучши курятник." : "На складе нет места. Улучши склад.")
    : !valid
    ? "Введите целое количество от 1 до 10 000"
    : result.remaining > 0
      ? "Доступного количества недостаточно"
      : result.cost > state.me.coins
        ? "Недостаточно монет на балансе"
        : market
          ? "Покупка яиц у других игроков."
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
      });
  } catch (error) {
    toast(error.message);
  }
}
function sellMaximum() {
  if(!state)return;
  const eggs=Math.min(10000,Math.max(0,Number(state.me.eggs)||0));
  if(!eggs){toast("Пока нет яиц для продажи");return;}
  el("sellnum").value=eggs;
  sellQuote();
}
function sellType() {
  el("grainPriceWrap").hidden = el("sellitem").value !== "grain";
  sellQuote();
}
function sellQuote() {
  if (!state) return;
  const item = el("sellitem").value,
    n = Number(el("sellnum").value),
    price = item === "eggs" ? (state.shop.eggs||1) : Number(el("sellprice").value);
  el("myStock").textContent = `На складе: ${number(state.me[item])} шт.`;
  el("sellquote").textContent =
    n > 0 && n <= state.me[item] && price > 0
      ? number(n * price) + " монет"
      : "Недостаточно товара";
}
function sellNow() {
  try {
    const item = el("sellitem").value,
      n = amount("sellnum");
    if (!state || n > state.me[item]) throw Error("Недостаточно товара");
    perform("/api/sell", {
      item,
      amount: n,
      price: item === "eggs" ? (state.shop.eggs||1) : amount("sellprice"),
    });
  } catch (error) {
    toast(error.message);
  }
}
function cancelLot(id) {
  if (confirm("Вернуть непроданный остаток на склад?"))
    perform("/api/cancel/" + id, {});
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
      amount: amount(id, 2000),
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
const logNames = { grain: "Зерно", chickens: "Курицы", eggs: "Яйца" };
function details(text) {
  return text.replace(/grain|chickens|eggs/g, (x) => logNames[x]);
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
   `<div class="ledger-row ${x.delta>0?"income":""}"><span aria-hidden="true">${x.delta>=0?"↗":"↙"}</span><div><strong>${safe(details(x.details))}</strong><small>${new Date(x.created*1000).toLocaleString("ru-RU")}</small></div><b>${x.delta>0?"+":""}${number(x.delta)}</b></div>`
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
    note.textContent=request
      ? "Последняя заявка: "+number(request.amount)+" монет · "+
        (request.status==="pending"?"ожидает ручной проверки":request.status==="rejected"?"отклонена":"статус: "+request.status)
      : "Заявок на вывод пока нет.";
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
function openWithdrawalRequest() {
  if(!state)return toast("Сначала войдите в игру");
  if(!state.me.telegram_id){
    tab("profile");
    const settings=document.querySelector("#profile details.profile-settings");
    if(settings){settings.open=true;setTimeout(()=>settings.scrollIntoView({behavior:"smooth",block:"start"}),100);}
    toast("Откройте настройки ниже: там показано, как привязать Telegram. Реальные выплаты пока отключены.");
    return;
  }
  if(state.me.coins<100)return toast("Для заявки нужно минимум 100 монет");
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
    if(!confirm("Отправить заявку на "+number(n)+" монет? Это не автоматическая выплата: сначала потребуется проверка."))return;
    busy(true);
    await api("/api/withdraw/request",{amount:n});
    el("withdrawal-dialog").close();
    await refresh();
    await loadWithdrawalStatus();
    await loadHistory();
    toast("Заявка принята: "+number(n)+" монет списано с баланса в резерв. Реальная выплата не выполнена.");
  }catch(error){toast(error.message);}
  finally{busy(false);}
}
function render() {
  const p = state.me;
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
  assignStat("stat-sales",farmDailyStats.sales_coins);
  assignStat("stat-feed",farmDailyStats.feed_spent_coins);
  assignStat("stat-margin",farmDailyStats.feed_margin_coins);
  const pr = state.progression || {};
  const xp = Number(pr.xp || 0), lvl = Number(pr.level || 1);
  const prev = 25*(lvl-1)*(lvl-1), next = Number(pr.next_level_xp || 25);
  const percent = Math.max(0,Math.min(100,100*(xp-prev)/Math.max(1,next-prev)));
  if (el("identity-level")) el("identity-level").textContent = "Уровень " + lvl + " · " + xp + " XP";
  if (el("identity-xp-fill")) el("identity-xp-fill").style.width = percent + "%";
  if (el("profile-level")) el("profile-level").textContent = "Уровень " + lvl + " · " + xp + " XP";
  for (const img of document.querySelectorAll(".identity .avatar, .profile-avatar")) img.src = avatarSource(p);
  const promo = state.promotion || {};
  document.querySelectorAll("[data-promo-discount]").forEach(x => x.textContent = `−${Math.round(100*(1-promo.price/promo.value))}%`);
  document.querySelectorAll("[data-promo-value]").forEach(x => x.textContent = number(promo.value));
  document.querySelectorAll("[data-promo-price]").forEach(x => x.textContent = number(promo.price));
  const inc=state.incubator||{};
  const jobs=inc.jobs||[];
  document.querySelectorAll("[data-incubator-capacity]").forEach(x=>x.textContent=number(inc.capacity||1));
  document.querySelectorAll("[data-incubator-price]").forEach(x=>x.textContent=number(inc.incubator_price||120));
  document.querySelectorAll("[data-incubate-duration]").forEach(x=>x.textContent=formatDuration(inc.incubate_seconds||43200));
  document.querySelectorAll("[data-grow-duration]").forEach(x=>x.textContent=formatDuration(inc.grow_seconds||43200));
  if (el("incubator-level"))el("incubator-level").textContent=number(inc.level||1);
  if (el("incubator-free"))el("incubator-free").textContent=number(Math.max(0,(inc.capacity||1)-jobs.length));
  const up=el("incubator-upgrade");
  if (up){up.hidden=!inc.owned;up.disabled=pending||inc.next_upgrade_cost==null||p.coins<inc.next_upgrade_cost;up.textContent=inc.next_upgrade_cost==null?"Максимальный уровень":"Улучшить · "+number(inc.next_upgrade_cost)+" монет";}
  const button=el("incubator-action");
  if(button){const full=jobs.length>=(inc.capacity||1);
    button.textContent=!inc.owned?"Купить · "+number(inc.incubator_price)+" монет":"Заложить 12 яиц + 15 монет";
    button.disabled=pending||(!inc.owned?p.coins<inc.incubator_price:full||p.eggs<12||p.coins<15||p.chickens+jobs.length>=state.buildings.coop_capacity);}
  const guide=el("launch-guide");
  if(guide)guide.hidden=!(Date.now()/1000<(p.created_at||0)+3600 && !localStorage.getItem("farm_guide_dismissed_"+p.id));
  const tutorial=state.tutorial||{};
  const step=Math.min(3,tutorial.step||0), card=el("tutorial-card");
  if(card){card.hidden=step>=3;if(step<3){el("tutorial-progress").textContent="Шаг "+(step+1)+" из 3";el("tutorial-instruction").textContent=["Посмотри, где живут твои курицы и когда они несут яйца.","Зерно можно купить в Торговле. Куры едят автоматически раз в 18 часов.","Из яиц можно вырастить кур в инкубаторе или продать их игрокам."][step];el("tutorial-next").textContent=["Посмотреть курятник","Где купить зерно?","Понятно · получить 5 монет"][step];}}
  const history = el("production-history");
  if (history) history.innerHTML = state.production_history?.length
    ? state.production_history.map(event => `<div class="ledger-row income">${image("redesign/egg")}<div><strong>+${number(event.amount)} яиц</strong><small>${new Date(event.created * 1000).toLocaleString("ru-RU")}</small></div></div>`).join("")
    : '<p class="empty">Сборов пока не было. Здесь появятся яйца, произведённые твоими курами.</p>';
  const buildings = state.buildings || {};
  document.querySelectorAll("[data-building]").forEach((node) => {
    const value = buildings[node.dataset.building];
    node.textContent = typeof value === "number" ? number(value) : "—";
  });
  for (const kind of ["coop","storage"]) {
    const button = el("upgrade-"+kind);
    if (!button) continue;
    const price = buildings[kind+"_next_cost"];
    button.disabled = price == null || price > p.coins || pending;
    button.textContent = price == null ? "Максимальный уровень" : "Улучшить · "+number(price)+" монет";
  }
  const shopIncubator = el("incubator-shop-button");
  if (shopIncubator) {
    shopIncubator.textContent = inc.owned ? "Открыть инкубатор" : "Купить · " + number(inc.incubator_price);
    shopIncubator.disabled = pending || (!inc.owned && p.coins < inc.incubator_price);
  }
  const last = state.last_farm_event;
  if (last && (last.kind === "eggs_produced" || last.kind === "chick_matured")) {
    const seenKey = "farm_seen_event_" + p.id;
    if (localStorage.getItem(seenKey) !== last.id) {
      localStorage.setItem(seenKey, last.id);
      toast(last.kind === "chick_matured" ? "Цыплёнок вырос! +1 курица." : "Куры снесли " + number(last.amount) + " яиц! Они уже на складе.");
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
  const earned = new Set(progression.achievements || []);
  const total = progression.totals || {};
  const achievements = [
    ["first_egg","redesign/egg","Первое яйцо",total.eggs_produced || 0,1],
    ["ten_eggs","redesign/egg","120 произведённых яиц",total.eggs_produced || 0,120],
    ["three_hens","redesign/hen","Три несушки",p.chickens || 0,3],
    ["first_sale","redesign/shop-icon","Первая продажа яйца",total.eggs_sold || 0,1],
    ["hundred_sales","redesign/achievement","1200 проданных яиц",total.eggs_sold || 0,1200]
  ];
  const achievementList = el("achievements-list");
  if (achievementList) achievementList.innerHTML = achievements.map(([key,icon,title,current,target]) => {
    const done = earned.has(key);
    return '<div class="achievement-row' + (done?' achievement-done':'') + '"><span class="achievement-emoji">'+image(icon)+'</span><div><strong>'+title+'</strong><small>'+(done?'Получено ✓':number(Math.min(current,target))+' / '+target)+'</small></div><span class="achievement-status">'+(done?'★':'—')+'</span></div>';
  }).join("");
  const daily = state.daily || {};
  const claimed = new Set(state.claimed_rewards || []);
  const dailyMissions = [
    ["grain", "Купить 5 зерна", daily.grain_bought || 0, 5],
    ["eggs", "Получить 3 яйца от кур", daily.eggs_produced || 0, 3],
    ["listing", "Выставить яйцо на продажу", daily.eggs_listed || 0, 1]
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
  const listed = {grain:0,eggs:0};
  for (const item of state.my_listings || []) if (item.item in listed) listed[item.item] += item.quantity;
  const summary = el("storage-summary");
  el("storage-listed").textContent = `${number(listed.eggs)} яиц · ${number(listed.grain)} зерна`;
  const f = state.farm;
  const approx = f.forecast_approximate ? "~" : "";
  document.querySelectorAll("[data-eggs-6h]").forEach(x => x.textContent = `${approx}+${eggQuantity(f.eggs_next_6h)}`);
  document.querySelectorAll("[data-eggs-12h]").forEach(x => x.textContent = `${approx}+${eggQuantity(f.eggs_next_12h)}`);
  document.querySelectorAll("[data-feed-required]").forEach(x => x.textContent = number(f.grain_required_next_feed));
  document.querySelectorAll("[data-fed-hens]").forEach(x => x.textContent = number(f.fed_hens));
  document.querySelectorAll("[data-forecast-note]").forEach(x => x.textContent = f.forecast_note);
  const brief=el("forecast-brief"); brief.hidden=!f.forecast_approximate; brief.textContent="Есть взрослеющие цыплята — оценка для нынешних несушек.";
  const feedStatus = f.effective_grain_shortage > 0 ? "Недостаточно зерна для следующего кормления."
    : f.grain_shortage > 0 ? "Запас пополнит автозакупка, если хватит монет и места." : "Зерна для следующего кормления достаточно.";
  document.querySelectorAll("[data-feed-status]").forEach(x => {x.textContent = feedStatus;x.dataset.alert = String(f.effective_grain_shortage > 0);});
  document.querySelectorAll("[data-buy-feed]").forEach(x => x.classList.toggle("needs-feed", f.effective_grain_shortage > 0));
  const storageWarning = el("storage-warning");
  storageWarning.hidden = buildings.storage_used < buildings.storage_capacity;
  storageWarning.textContent = `Склад заполнен: ${number(buildings.storage_used)} / ${number(buildings.storage_capacity)}. Новые яйца не поместятся. Продай товары или улучши склад.`;
  el("login").hidden = true;
  el("app").hidden = false;
  el("nav").hidden = false;
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
  el("feedstock").textContent = p.chickens
    ? "~"+Math.max(0,Math.floor(state.farm.feed_stock_seconds/3600))+" часов"
    : "— (нет кур)";
  el("warning").textContent = state.farm.effective_grain_shortage > 0 ? "Недостаточно зерна для следующего кормления." : "Кормление раз в 18 часов · 1 зерно на курицу.";
  el("warning").dataset.alert = String(state.farm.effective_grain_shortage > 0);
  el("warning").hidden=state.farm.effective_grain_shortage<=0;
  el("treasury").textContent = number(state.economy.treasury) + " монет";
  document.querySelectorAll(".auto-card").forEach((card) => {
    const input = card.querySelector("input");
    if (document.activeElement !== input) input.value = p.autobuy_amount;
    autoQuote(input);
    card
      .querySelector(".auto-toggle")
      .setAttribute("aria-pressed", String(p.autobuy_enabled));
    card.querySelector(".auto-toggle").disabled = pending;
    card.querySelector("[data-auto-status]").textContent = p.autobuy_enabled
      ? `Включена · ${p.autobuy_amount} зерна при нехватке корма`
      : "Автозакупка выключена";
  });
  const weekly=state.weekly||{}, targets=weekly.targets||{};
  let weeklyDone=true;
  for (const key of ["grain","eggs","listed"]) {
    const target=targets[key]||1,value=Math.min(target,weekly[key]||0);
    weeklyDone=weeklyDone&&value>=target;
    const count=el("weekly-count-"+key)||document.querySelector(`[data-weekly="${key}"]`);
    const bar=document.querySelector(`[data-weekly-bar="${key}"]`);
    const status=document.querySelector(`[data-weekly-status="${key}"]`);
    if(count)count.textContent=value+" / "+target;
    if(bar)bar.style.width=(100*value/target)+"%";
    if(status)status.textContent=value>=target?"Готово":"В процессе";
  }
  const claim=el("weekly-claim");
  if(claim){claim.disabled=pending||!weeklyDone||weekly.claimed;claim.textContent=weekly.claimed?"🏆 Награда получена ✓":"🏆 Забрать награду: +"+(weekly.reward||30)+" монет";}
  const dead=el("weekly-deadline");
  if(dead&&weekly.ends_at){const hours=Math.max(0,Math.ceil((weekly.ends_at-Date.now()/1000)/3600));dead.textContent="До конца недели: "+Math.floor(hours/24)+" дн. "+hours%24+" ч";}

  el("leaders").innerHTML = state.top
    .map(
      (x, i) =>
        `<div class="ledger-row"><b>${i + 1}</b><div><strong>${safe(x.name)}</strong><small>${number(x.chickens)} куриц</small></div><b>${number(x.coins)} ${image("redesign/coin")}</b></div>`,
    )
    .join("");
  el("mylist").innerHTML = state.my_listings.length
    ? state.my_listings
        .map(
          (x) =>
            `<div class="product">${image(art[x.item], "product-image")}<div><h3>${itemNames[x.item]}</h3><small>${number(x.quantity)} шт. · ${number(x.price)} монет/шт.</small></div><button class="btn alt small" onclick="cancelLot('${safe(x.id)}')">Вернуть</button></div>`,
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
  const promo = state.promotion;
  const promoActive = promotionActive();
  el("promo-status").textContent = promoActive
    ? `До конца: ${formatDuration(promo.seconds_left - elapsed)} · осталось покупок: ${Math.max(0,promo.limit-promo.used)} / ${promo.limit}`
    : "Акция завершена";
  el("bundle-buy").disabled = pending || !promoActive || state.me.coins < promo.price;
  const inc=state.incubator||{}, now=state.now+elapsed;
  const jobs=inc.jobs||[];
  const full=state.me.chickens>=state.buildings.coop_capacity;
  const status=!inc.owned?"Инкубатор ещё не куплен":jobs.length===0?"Свободен · заложи яйцо":jobs.length+" из "+inc.capacity+" мест занято";
  if(el("incubation-status"))el("incubation-status").textContent=status;
  document.querySelectorAll("[data-incubator-summary]").forEach(x=>x.textContent=status);
  const list=el("incubator-jobs");
  if(list)list.innerHTML=jobs.map((j,i)=>{
    const hatch=now<j.hatch_at;
    const remaining=(hatch?j.hatch_at:j.mature_at)-now;
    const label=remaining<=0&&full?"Нужно место в курятнике":remaining<=0?"Завершается…":formatDuration(remaining);
    return '<div class="incubator-job"><strong>'+(hatch?'🥚 Яйцо':'🐣 Цыплёнок')+' №'+(i+1)+'</strong><span>'+safe(label)+'</span></div>';
  }).join("") || '<p class="muted">Все ячейки свободны.</p>';
  document.querySelectorAll("[data-stage]").forEach(x=>x.classList.toggle("active",inc.owned&&jobs.length>0&&x.dataset.stage===(now<jobs[0].hatch_at?"egg":"chick")));
  const seconds = Math.max(0,state.farm.seconds_to_next_egg - elapsed);
  document.querySelectorAll("[data-next-tick]").forEach(x => x.textContent = clockDuration(seconds));
  const nextFeed = Math.max(0,state.farm.seconds_to_next_feed-elapsed);
  document.querySelectorAll("[data-feed-tick]").forEach(x => x.textContent=clockDuration(nextFeed));
  // Reconcile completed timers with the server; the browser never grants resources.
  const completedJobs = jobs.some(j => now >= j.mature_at) && !full;
  const expired = seconds <= 0 || nextFeed <= 0 || completedJobs;
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
    } catch (error) {
      if (error.status === 401) showLogin();
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
if (token) refresh();
else el("login").hidden = false;

document.addEventListener("DOMContentLoaded",async ()=>{
  const init=Boolean(tgInitData());
  let enabled=false;
  if(init) {
    try{const config=await api("/api/auth/config");enabled=Boolean(config.telegram_enabled);}
    catch(e){enabled=false;}
  }
  document.querySelectorAll(".telegram-entry").forEach(x=>x.hidden=!(init&&enabled));
});
