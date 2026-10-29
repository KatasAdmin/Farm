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
  if (!value && purchase && el("purchase-dialog").open) purchaseQuote();
}
async function perform(path, data) {
  if (pending) return false;
  busy(true);
  try {
    const result = await api(path, data);
    if (el("purchase-dialog").open) el("purchase-dialog").close();
    // The operation has committed; refresh failure must never encourage a repeated charge.
    toast(
      "Операция выполнена" +
        (result.spent ? ` · ${number(result.spent)} монет` : ""),
    );
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
  if (completed) toast("🎁 Награда получена! Монеты начислены.");
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
async function saveProfile() {
  const ageText = el("profile-age").value.trim();
  const age = ageText === "" ? null : Number(ageText);
  if (age !== null && (!Number.isSafeInteger(age) || age < 1 || age > 120)) return toast("Укажи возраст от 1 до 120");
  const ok = await perform("/api/profile", {gender:el("profile-gender").value,age,avatar:el("profile-avatar").value});
  if (ok) el("profile-editor").hidden = true;
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
  openPurchase({ kind: "bundle", item: "chickens", price: 300 });
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
      ? "300 монет · обычная стоимость 500"
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
  const n = Number(el("purchase-amount").value);
  const valid = Number.isSafeInteger(n) && n >= 1 && n <= 10000;
  const market = purchase.kind === "market";
  const result = market
    ? quote(purchase.item, n)
    : { cost: purchase.price * n, remaining: 0 };
  el("purchase-total").textContent = valid ? number(result.cost) : "—";
  let info = !valid
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
    pending || !valid || result.remaining > 0 || result.cost > state.me.coins;
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
  if (el("promo-status")) el("promo-status").textContent = promo.active ? "Осталось: "+Math.ceil(promo.seconds_left/3600)+" ч · покупок "+promo.used+" из 5" : "Акция завершена";
  if (el("bundle-buy")) {el("bundle-buy").disabled = !promo.active || p.coins < 300;el("bundle-buy").title = promo.active ? "До 5 покупок" : "Акция завершена";}
  const inc = state.incubator || {};
  const button = el("incubator-action");
  const info = el("incubation-status");
  if (button && info) {
    if (!inc.owned) {info.textContent = "Стоимость 120 монет · покупается один раз";button.textContent = "Купить · 120 монет";button.disabled = p.coins < 120;}
    else if (inc.incubation_started != null) {info.textContent = "🥚 Яйцо в инкубаторе";button.textContent = "Идёт инкубация";button.disabled = true;}
    else if (inc.chick_ready_at != null) {info.textContent = "🐣 Цыплёнок растёт; нужна свободная вместимость курятника";button.textContent = "Цыплёнок растёт";button.disabled = true;}
    else {info.textContent = "Инкубатор готов. Потрать 1 яйцо, чтобы вывести курицу";button.textContent = "Заложить 1 яйцо";button.disabled = p.eggs < 1 || p.chickens >= (state.buildings?.coop_capacity || 10);}
  }
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
  const last = state.last_farm_event;
  if (last && last.kind === "eggs_produced") {
    const seenKey = "farm_seen_event_" + p.id;
    if (localStorage.getItem(seenKey) !== last.id) {
      localStorage.setItem(seenKey, last.id);
      toast("🥚 Кури снесли " + number(last.amount) + " яиц! Они уже на складе.");
    }
  }
  const progression = state.progression || {};
  const farmerLevel = el("farmer-level");
  const farmerXp = el("farmer-xp-caption");
  const xpBar = el("farmer-xp-bar");
  if (farmerLevel) farmerLevel.textContent = "⭐ Уровень " + number(progression.level || 1) + " · " + number(progression.xp || 0) + " XP";
  const totalXp = progression.xp || 0;
  const level = progression.level || 1;
  const baseXp = 25 * (level-1) * (level-1);
  const nextXp = progression.next_level_xp || 25;
  if (farmerXp) farmerXp.textContent = "До следующего уровня: " + number(Math.max(0,nextXp - totalXp)) + " XP";
  if (xpBar) xpBar.style.width = Math.min(100,100*Math.max(0,totalXp-baseXp)/Math.max(1,nextXp-baseXp)) + "%";
  const earned = new Set(progression.achievements || []);
  const total = progression.totals || {};
  const achievements = [
    ["first_egg","🥚","Первое яйцо",total.eggs_produced || 0,1],
    ["ten_eggs","🐣","10 произведённых яиц",total.eggs_produced || 0,10],
    ["three_hens","🐔","Три несушки",p.chickens || 0,3],
    ["first_sale","🛍️","Первая продажа яйца",total.eggs_sold || 0,1],
    ["hundred_sales","🏅","100 проданных яиц",total.eggs_sold || 0,100]
  ];
  const achievementList = el("achievements-list");
  if (achievementList) achievementList.innerHTML = achievements.map(([key,icon,title,current,target]) => {
    const done = earned.has(key);
    return '<div class="achievement-row' + (done?' achievement-done':'') + '"><span class="achievement-emoji">'+icon+'</span><div><strong>'+title+'</strong><small>'+(done?'Получено ✓':number(Math.min(current,target))+' / '+target)+'</small></div><span class="achievement-status">'+(done?'★':'🔒')+'</span></div>';
  }).join("");
  const daily = state.daily || {};
  const claimed = new Set(state.claimed_rewards || []);
  const dailyMissions = [
    ["grain", "🌾 Купить 5 зерна", daily.grain_bought || 0, 5],
    ["eggs", "🥚 Получить яйцо от кур", daily.eggs_produced || 0, 1],
    ["listing", "📦 Выставить яйцо на продажу", daily.eggs_listed || 0, 1]
  ];
  const dailyBox = el("daily-tasks");
  if (dailyBox) {
    const bonusDone = claimed.has("bonus");
    dailyBox.innerHTML = '<div class="daily-task"><div><strong>🎁 Бонус за вход</strong><small>+2 монеты · раз в сутки</small></div><button class="btn small" ' + (bonusDone ? 'disabled' : '') + ' onclick="claimDaily(\'bonus\')">' + (bonusDone ? 'Получено ✓' : 'Получить +2') + '</button></div>' +
      dailyMissions.map(([key,name,value,target]) => {
        const n = Math.min(value,target);
        const done = n >= target;
        const isClaimed = claimed.has(key);
        return '<div class="daily-task"><div><strong>' + name + '</strong><small>' + number(n) + ' / ' + target + ' · +1 монета</small></div><div class="progress"><span style="width:' + (100*n/target) + '%"></span></div><button class="btn small" ' + (!done || isClaimed ? 'disabled' : '') + ' onclick="claimDaily(\'' + key + '\')">' + (isClaimed ? 'Получено ✓' : done ? 'Забрать +1' : 'Выполни задание') + '</button></div>';
      }).join("");
  }
  const listed = {grain:0,eggs:0};
  for (const item of state.my_listings || []) if (item.item in listed) listed[item.item] += item.quantity;
  const summary = el("storage-summary");
  if (summary) summary.textContent = "Свободно: " + p.eggs + " яиц, " + p.grain + " зерна. На продаже: " + listed.eggs + " яиц, " + listed.grain + " зерна. Выставленный товар хранится отдельно, пока его не купят или ты не снимешь объявление.";
  const nextEggs = Math.min(p.grain,p.chickens);
  const harvestText = p.chickens <= 0 ? "Нет кур — купи несушку в магазине." : (nextEggs ? "Следующий сбор: +" + number(nextEggs) + " яиц · −" + number(nextEggs) + " зерна." : "Зерна не хватает: без корма новые яйца не появятся.");
  const farmHarvest = el("next-harvest"), coopHarvest = el("coop-harvest");
  if (farmHarvest) farmHarvest.textContent = harvestText;
  if (coopHarvest) coopHarvest.textContent = harvestText;
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
    : p.grain < p.chickens
      ? "Корма на следующий день не хватит. Докупи зерно."
      : "Кормление и производство — автоматически, раз в сутки.";
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
function countdown() {
  if (!state) return;
  const seconds = Math.max(
    0,
    state.farm.seconds_to_next - Math.floor((Date.now() - refreshedAt) / 1000),
  );
  document
    .querySelectorAll("[data-next-tick]")
    .forEach(
      (x) =>
        (x.textContent = `${Math.floor(seconds / 3600)} ч ${Math.floor((seconds % 3600) / 60)} мин`),
    );
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
