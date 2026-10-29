"use strict";
const el = (id) => document.getElementById(id);
const art = {
  grain: "illustrated/wheat",
  eggs: "illustrated/egg",
  chickens: "illustrated/hen",
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
  return `<img src="/assets/${path}.webp" class="${cls}" alt="" decoding="sync">`;
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
    const result = await api("/api/join", { name: el("name").value.trim() });
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
    const active = x.dataset.tab === id;
    x.classList.toggle("active", active);
    if (active) x.setAttribute("aria-current", "page");
    else x.removeAttribute("aria-current");
  });
  window.scrollTo({ top: 0, behavior: "instant" });
  if (id === "wallet") loadHistory();
}
function marketTab(mode) {
  el("buyPane").classList.toggle("active", mode === "buy");
  el("sellPane").classList.toggle("active", mode === "sell");
  for (const [id, active] of [
    ["mbuy", mode === "buy"],
    ["msell", mode === "sell"],
  ]) {
    el(id).classList.toggle("active", active);
    el(id).setAttribute("aria-pressed", String(active));
  }
}
function openSell(item) {
  tab("market");
  marketTab("sell");
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
  const items = chosenFilter === "all" ? ["eggs", "grain"] : [chosenFilter];
  el("pool").innerHTML =
    items
      .map((item) => {
        const rows = marketRows(item),
          count = rows.reduce((a, x) => a + x.quantity, 0);
        const prices = rows.map((x) => x.price),
          min = prices.length ? Math.min(...prices) : item === "eggs" ? 5 : 2;
        const priceText = prices.some((x) => x !== min) ? `от ${min}` : min;
        return `<div class="product">${image(art[item], "product-image")}<div><h3>${item === "eggs" ? "Яйца" : "Зерно"}</h3><small>В пуле: ${number(count)} шт.</small><small>Цена: <b class="gold">${priceText}</b> ${image("illustrated/coin")} / шт.</small></div>${count ? `<button class="btn small" onclick="selectBuy('${item}')">Купить</button>` : '<span class="empty-label">Нет в наличии</span>'}</div>`;
      })
      .join("") +
    '<p class="muted">Твои объявления не включены в доступный для покупки пул.</p>';
}
function selectBuy(item) {
  tab("market");
  marketTab("buy");
  const rows = marketRows(item);
  if (!rows.length) {
    toast("Пока нет предложений фермеров");
    return;
  }
  openPurchase({
    kind: "market",
    item,
    price: Math.min(...rows.map((x) => x.price)),
  });
}
function showShop(item) {
  if (!state) return;
  const price = state.shop[item];
  if (!price) return;
  openPurchase({ kind: "shop", item, price });
}
function showBundle() {
  openPurchase({ kind: "bundle", item: "chickens", price: 150 });
}
function openPurchase(data) {
  if (pending) return;
  purchase = data;
  el("purchase-title").textContent =
    data.kind === "market"
      ? "Покупка у фермеров"
      : data.kind === "bundle"
        ? "Набор фермера"
        : "Покупка товара";
  el("purchase-name").textContent =
    data.kind === "bundle" ? "3 курицы + 30 зерна" : itemNames[data.item];
  el("purchase-price").textContent =
    data.kind === "bundle"
      ? "150 монет за набор"
      : `Цена: ${data.price} монет / шт.`;
  const img = el("purchase-dialog").querySelector(".purchase-art");
  img.src =
    "/assets/" +
    (data.kind === "bundle" ? "illustrated/wallet" : art[data.item]) +
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
      ? "Недостаточно товара в доступном пуле"
      : result.cost > state.me.coins
        ? "Недостаточно монет на балансе"
        : market
          ? "Выкуп делится между продавцами. Комиссия 0%."
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
        `<div class="ledger-row"><b>${i + 1}</b><div><strong>${safe(x.name)}</strong><small>${number(x.chickens)} куриц</small></div><b>${number(x.coins)} ${image("illustrated/coin")}</b></div>`,
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
