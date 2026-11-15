(() => {
  const key = "trevixo.gameMusic";
  function readPreferences() {
    try { return JSON.parse(localStorage.getItem(key)) || {}; } catch { return {}; }
  }
  const preferences = readPreferences();
  const audio = new Audio("/assets/trevixo-evening.mp3");
  audio.loop = true;
  audio.preload = "none";
  audio.volume = Number.isFinite(preferences.volume) ? Math.max(0, Math.min(1, preferences.volume)) : 0.24;
  let enabled = preferences.enabled !== false;
  let position = Number(preferences.position) || 0;

  function save() {
    try {
      localStorage.setItem(key, JSON.stringify({
        enabled, volume: audio.volume, position: audio.readyState ? audio.currentTime : position,
      }));
    } catch {}
  }

  function play() {
    if (enabled && !document.hidden && audio.paused) audio.play().catch(() => {});
  }

  audio.addEventListener("loadedmetadata", () => {
    if (position > 0 && Number.isFinite(audio.duration)) audio.currentTime = position % audio.duration;
  }, {once: true});
  document.addEventListener("pointerup", play);
  document.addEventListener("keydown", play);
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) { save(); audio.pause(); }
    else play();
  });
  window.addEventListener("pagehide", () => { save(); audio.pause(); });
  window.addEventListener("pageshow", event => {
    if (event.persisted) {
      const saved = readPreferences();
      enabled = saved.enabled !== false;
      if (Number.isFinite(saved.volume)) audio.volume = Math.max(0, Math.min(1, saved.volume));
      position = Number(saved.position) || 0;
      if (audio.readyState && Number.isFinite(audio.duration)) audio.currentTime = position % audio.duration;
      sync();
    }
    play();
  });

  function sync() {
    document.querySelectorAll("[data-music-enabled]").forEach(input => { input.checked = enabled; });
    document.querySelectorAll("[data-music-volume]").forEach(input => { input.value = Math.round(audio.volume * 100); });
  }

  document.addEventListener("input", event => {
    const input = event.target;
    if (input.matches("[data-music-enabled]")) {
      enabled = input.checked;
      if (enabled) play();
      else audio.pause();
    } else if (input.matches("[data-music-volume]")) {
      audio.volume = Number(input.value) / 100;
    } else return;
    save();
    sync();
  });

  window.TrevixoMusic = { sync };
  sync();
})();
