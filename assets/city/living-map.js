(() => {
  const stage = document.getElementById("city-life");
  const home = document.getElementById("city-home");
  const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
  const stops = {
    farm: [31, 43], bakery: [51, 42], restaurant: [76, 51],
    dairy: [24, 66], atelier: [75, 65], store: [31, 55], warehouse: [56, 73],
  };
  const roads = {
    farm: [[38, 44], [44, 46]], bakery: [[46, 44]],
    restaurant: [[65, 58], [60, 60]], dairy: [[33, 63], [40, 62]],
    atelier: [[65, 64], [58, 63]], store: [[36, 54], [39, 58]],
    warehouse: [[57, 70], [53, 65]],
  };
  const suppliers = {bakery: "farm", restaurant: "bakery", dairy: "farm", atelier: "farm", store: "bakery"};
  const cargo = {farm: "grain", bakery: "bread", dairy: "milk", atelier: "scarf", restaurant: "bread"};
  const unlocked = new Set(["farm", "warehouse"]);
  const arrivals = [];
  let ready = false;
  let effects = true;
  let timer = 0;
  let routeIndex = 0;

  function active() {
    return ready && effects && !reducedMotion.matches && !home.hidden && !document.hidden;
  }

  function move(kind, points, seconds, product) {
    const sprite = document.createElement("span");
    sprite.className = "city-life-sprite city-life-" + kind;
    if (product) sprite.dataset.cargo = product;
    stage.append(sprite);
    const distance = [0];
    for (let i = 1; i < points.length; ++i) {
      distance.push(distance[i - 1] + Math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1]));
    }
    const frames = points.map(([x, y], i) => {
      const next = points[i + 1];
      const prev = points[i - 1];
      const direction = next ? next[0] - x : x - prev[0];
      return {
        offset: distance[i] / distance.at(-1),
        left: x + "%", top: y + "%", "--direction": direction < 0 ? "-1" : "1",
      };
    });
    const motion = sprite.animate(frames, {duration: seconds * 1000, easing: "linear"});
    motion.onfinish = () => sprite.remove();
  }

  function route(from, to) {
    const points = [stops[from], ...roads[from], [49, 48], [59, 55], [52, 62], ...roads[to].slice().reverse(), stops[to]];
    // Use the upper road for deliveries between the farm and bakery.
    return [from,to].every(name => name === "farm" || name === "bakery")
      ? [stops[from], ...roads[from], ...roads[to].slice().reverse(), stops[to]]
      : points;
  }

  function tick() {
    timer = 0;
    if (!active()) return;
    const businesses = Object.keys(suppliers).filter(name => unlocked.has(name));
    const next = arrivals.shift();
    const to = next || (businesses.length ? businesses[routeIndex % businesses.length] : "farm");
    const supplier = unlocked.has(suppliers[to]) ? suppliers[to] : "farm";
    const from = to === "farm" ? "warehouse" : supplier;
    const returning = !next && routeIndex % 3 === 2;
    ++routeIndex;
    move("truck", returning ? route(to, "warehouse") : route(from,to), 8, cargo[returning ? to : from] || "grain");
    move("walker", [[29,47],[31,48],[34,48],[36,47]], 6);
    if (to !== "farm" && to !== "restaurant") {
      const [x, y] = stops[to];
      move("walker", [[x - 3, y + 3], [x - 1, y + 2], [x, y + 1]], 5);
    }
    if (unlocked.has("restaurant")) move("walker", [[65,55],[69,54],[72,54]], 7);
    timer = window.setTimeout(tick, businesses.length ? 8500 : 12500);
  }

  function reconcile() {
    stage.hidden = !active();
    if (!active()) {
      clearTimeout(timer);
      timer = 0;
      stage.querySelectorAll(".city-life-sprite").forEach(sprite => {
        sprite.getAnimations().forEach(animation => animation.cancel());
        sprite.remove();
      });
    } else if (!timer) timer = window.setTimeout(tick, arrivals.length ? 250 : 1300);
  }

  window.TrevixoCityLife = {
    update(levels, showEffects) {
      for (const name of Object.keys(suppliers)) {
        const opened = Number(levels?.[name]) > 0;
        if (opened && !unlocked.has(name) && ready) arrivals.push(name);
        if (opened) unlocked.add(name);
        else unlocked.delete(name);
        stage.classList.toggle("has-" + name, opened);
      }
      effects = showEffects;
      ready = true;
      reconcile();
    },
    delivery(name) {
      if (Object.hasOwn(suppliers, name) && unlocked.has(name) && !arrivals.includes(name)) arrivals.push(name);
    },
  };
  new MutationObserver(reconcile).observe(home, {attributes:true, attributeFilter:["hidden"]});
  document.addEventListener("visibilitychange", reconcile);
  reducedMotion.addEventListener?.("change", reconcile);
})();
