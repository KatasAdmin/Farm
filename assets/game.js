"use strict";
const el = (id) => document.getElementById(id);
const art = {
  grain: "redesign/grain",
  eggs: "redesign/egg",
  chickens: "redesign/hen",
};
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
  if (state.incubator?.owned) return tab("upgrades");
  await perform("/api/incubator",{item:"buy"});
}
async function incubatorAction() {
  if (!state || pending) return;
  const i = state.incubator || {};
  if (!i.owned) return perform("/api/incubator",{item:"buy"});
  if (i.incubation_started != null || i.chick_ready_at != null) return toast("Инкубатор занят");
  await perform("/api/incubator",{item:"start"});
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
    const result = await api("/api/join", { name: el("name").value.trim(), gender: el("join-gender").value });
    token = result.token;
    localStorage.setItem("farm_token", token);
    await refresh();
  } catch (error) {
    toast(error.message);
  } finally {
    busy(false);
  }
});
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
  if (id === "wallet") loadHistory();
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
    return {cost:5*n,remaining:Math.max(0,n-available)};
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
    price: item === "eggs" ? 5 : Math.min(...rows.map((x) => x.price)),
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
function sellType() {
  el("grainPriceWrap").hidden = el("sellitem").value !== "grain";
  sellQuote();
}
function sellQuote() {
  if (!state) return;
  const item = el("sellitem").value,
    n = Number(el("sellnum").value),
    price = item === "eggs" ? 5 : Number(el("sellprice").value);
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
      price: item === "eggs" ? 5 : amount("sellprice"),
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
async function loadHistory() {
  try {
    const value = await api("/api/finance");
    el("history").innerHTML = value.entries.length
      ? value.entries
          .map(
            (x) =>
              `<div class="ledger-row ${x.delta > 0 ? "income" : ""}"><span aria-hidden="true">${x.delta >= 0 ? "↗" : "↙"}</span><div><strong>${safe(details(x.details))}</strong><small>${new Date(x.created * 1000).toLocaleString("ru-RU")}</small></div><b>${x.delta > 0 ? "+" : ""}${number(x.delta)}</b></div>`,
          )
          .join("")
      : '<p class="empty">Пока нет операций. Здесь появятся покупки и продажи.</p>';
  } catch (error) {
    el("history").textContent = error.message;
  }
}
function render() {
  const p = state.me;
  const pr = state.progression || {};
  const xp = Number(pr.xp || 0), lvl = Number(pr.level || 1);
  const prev = 25*(lvl-1)*(lvl-1), next = Number(pr.next_level_xp || 25);
  const percent = Math.max(0,Math.min(100,100*(xp-prev)/Math.max(1,next-prev)));
  if (el("identity-level")) el("identity-level").textContent = "Уровень " + lvl + " · " + xp + " XP";
  if (el("identity-xp-fill")) el("identity-xp-fill").style.width = percent + "%";
  if (el("profile-level")) el("profile-level").textContent = "Уровень " + lvl + " · " + xp + " XP";
  for (const img of document.querySelectorAll(".identity .avatar, .profile-avatar")) img.src = avatarSource(p);
  const promo = state.promotion || {};
  document.querySelectorAll("[data-promo-value]").forEach(x => x.textContent = number(promo.value));
  document.querySelectorAll("[data-promo-price]").forEach(x => x.textContent = number(promo.price));
  const inc = state.incubator || {};
  document.querySelectorAll("[data-incubator-capacity]").forEach(x => x.textContent = number(inc.capacity));
  document.querySelectorAll("[data-incubator-price]").forEach(x => x.textContent = number(inc.incubator_price));
  document.querySelectorAll("[data-incubate-duration]").forEach(x => x.textContent = formatDuration(inc.incubate_seconds));
  document.querySelectorAll("[data-grow-duration]").forEach(x => x.textContent = formatDuration(inc.grow_seconds));
  const button = el("incubator-action");
  if (button) {
    const occupied = inc.incubation_started != null || inc.chick_ready_at != null;
    button.textContent = !inc.owned ? `Купить · ${number(inc.incubator_price)} монет`
      : occupied ? "Инкубатор занят" : "Заложить 1 яйцо";
    button.disabled = pending || (!inc.owned ? p.coins < inc.incubator_price
      : occupied || p.eggs < 1 || p.chickens >= state.buildings.coop_capacity);
  }
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
    ["ten_eggs","redesign/egg","10 произведённых яиц",total.eggs_produced || 0,10],
    ["three_hens","redesign/hen","Три несушки",p.chickens || 0,3],
    ["first_sale","redesign/shop-icon","Первая продажа яйца",total.eggs_sold || 0,1],
    ["hundred_sales","redesign/achievement","100 проданных яиц",total.eggs_sold || 0,100]
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
    ["eggs", "Получить яйцо от кур", daily.eggs_produced || 0, 1],
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
  if (summary) summary.textContent = "Свободно: " + p.eggs + " яиц, " + p.grain + " зерна. На продаже: " + listed.eggs + " яиц, " + listed.grain + " зерна. Выставленный товар хранится отдельно, пока его не купят или ты не снимешь объявление.";
  const nextEggs = state.farm.expected_eggs;
  const harvestText = p.chickens <= 0 ? "Пока нет кур — купи несушку в Торговле."
    : `Ожидается +${number(nextEggs)} яиц · −${number(nextEggs)} зерна` + (state.farm.autobuy_expected ? " · с автозакупкой" : "");
  for (const id of ["next-harvest", "coop-harvest"]) el(id).textContent = harvestText;
  const storageWarning = el("storage-warning");
  const free = buildings.storage_capacity - buildings.storage_used;
  storageWarning.hidden = free > 0;
  storageWarning.textContent = `Склад заполнен: ${number(buildings.storage_used)} / ${number(buildings.storage_capacity)}. Для покупок расширь склад или продай товары. При кормлении зерно заменяется яйцами — сбор не пропадёт.`;
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
  const cycles = p.chickens > 0 ? Math.floor(p.grain / p.chickens) : 0;
  el("feedstock").textContent = p.chickens
    ? `${cycles} дн. (${p.chickens} кур × 1 зерно/сутки)`
    : "Пока нет куриц";
  el("warning").textContent = !p.chickens
    ? "Купи несушку в магазине."
    : state.farm.expected_eggs < p.chickens
      ? "Корма на следующий сбор не хватит. Докупи зерно или проверь автозакупку."
      : "Кормление и производство — автоматически, раз в сутки.";
  el("warning").dataset.alert = String(p.chickens > 0 && state.farm.expected_eggs < p.chickens);
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
  for (const [key, target] of Object.entries({
    grain: 10,
    chickens: 3,
    eggs: 10,
  })) {
    const progress = Math.min(target, p[key]);
    document.querySelector(`[data-goal="${key}"]`).textContent =
      `${progress} / ${target}`;
    document.querySelector(`[data-goal-bar="${key}"]`).style.width =
      Math.min(100, (100 * progress) / target) + "%";
    document.querySelector(`[data-goal-status="${key}"]`).textContent =
      progress >= target ? "Достигнуто" : "В процессе";
  }
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
  const inc = state.incubator;
  const now = state.now + elapsed;
  const remaining = inc.incubation_started != null
    ? inc.incubation_started + inc.incubate_seconds - now
    : inc.chick_ready_at != null ? inc.chick_ready_at - now : null;
  const full = state.me.chickens >= state.buildings.coop_capacity;
  let status = !inc.owned ? "Можно купить один раз"
    : remaining == null ? "Готов к работе · нужно 1 яйцо"
    : inc.chick_ready_at != null && remaining <= 0 && full
      ? "Цыплёнок вырос. Расширь курятник — он ждёт свободное место."
      : remaining <= 0 ? "Проверяем завершение на сервере…"
      : (inc.incubation_started != null ? "До цыплёнка: " : "До взрослой курицы: ") + formatDuration(remaining);
  el("incubation-status").textContent = status;
  document.querySelectorAll("[data-incubator-summary]").forEach(x => x.textContent = status);
  document.querySelectorAll("[data-stage]").forEach(x => x.classList.toggle("active", inc.owned && x.dataset.stage === (inc.chick_ready_at != null ? "chick" : "egg")));
  const seconds = Math.max(0,state.farm.seconds_to_next - elapsed);
  document.querySelectorAll("[data-next-tick]").forEach(x => x.textContent = formatDuration(seconds));
  // Reconcile completed timers with the server; the browser never grants resources.
  const expired = seconds <= 0 || (remaining != null && remaining <= 0 && !(inc.chick_ready_at != null && full));
  if (expired && !pending && !refreshPromise && elapsed >= 2 && document.visibilityState === "visible") refresh();
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
      "Выйти? Локальный ключ доступа будет удалён. Восстановление входа сервером пока не поддерживается.",
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
