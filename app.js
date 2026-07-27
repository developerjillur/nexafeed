const app = document.querySelector("#app");
const overlayRoot = document.querySelector("#overlayRoot");
const sidebar = document.querySelector("#sidebar");
const scrim = document.querySelector("#scrim");
const searchInput = document.querySelector("#searchInput");
const updatedLabel = document.querySelector("#updatedLabel");
const historyCount = document.querySelector("#historyCount");

const WATCHED_KEY = "nexafeed-watched-v1";
const PROGRESS_KEY = "nexafeed-progress-v1";
const THEME_KEY = "nexafeed-theme-v1";
const AUTOPLAY_KEY = "nexafeed-autoplay-v1";

const state = {
  feed: null,
  view: "home",
  query: "",
  watched: readJson(WATCHED_KEY, {}),
  progress: readJson(PROGRESS_KEY, {}),
  theme: localStorage.getItem(THEME_KEY) || "dark",
  activeVideo: null,
  shortQueue: [],
  shortIndex: 0,
  autoplay: localStorage.getItem(AUTOPLAY_KEY) !== "false",
};

let player = null;
let progressTimer = null;
let wheelLocked = false;
let touchStartY = null;

document.documentElement.dataset.theme = state.theme;
document.querySelector("#themeButton").textContent = state.theme === "dark" ? "☀" : "☾";
updateHistoryCount();

function readJson(key, fallback) {
  try {
    return JSON.parse(localStorage.getItem(key)) || fallback;
  } catch {
    localStorage.removeItem(key);
    return fallback;
  }
}

function escapeHtml(value = "") {
  return String(value)
    .replaceAll("\uFFFD", "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function initials(name = "") {
  return name
    .split(/\s+/)
    .slice(0, 2)
    .map((word) => word[0] || "")
    .join("")
    .toUpperCase();
}

function isWatched(id) {
  return Boolean(state.watched[id]);
}

function progressFor(id) {
  const value = state.progress[id];
  if (typeof value === "number") return Math.max(0, Math.min(1, value));
  return Math.max(0, Math.min(1, Number(value?.ratio || 0)));
}

function saveProgress(id, seconds, duration) {
  if (!id || !duration || duration <= 0) return;
  const ratio = Math.max(0, Math.min(1, seconds / duration));
  state.progress[id] = {
    seconds: Math.floor(seconds),
    duration: Math.floor(duration),
    ratio,
    updatedAt: Date.now(),
  };
  localStorage.setItem(PROGRESS_KEY, JSON.stringify(state.progress));
  if (ratio >= 0.8) markWatched(id);
}

function markWatched(id) {
  if (!id) return;
  if (!state.watched[id]) {
    state.watched[id] = Date.now();
    localStorage.setItem(WATCHED_KEY, JSON.stringify(state.watched));
    updateHistoryCount();
  }
  const current = state.progress[id] || {};
  state.progress[id] = { ...current, ratio: 1, updatedAt: Date.now() };
  localStorage.setItem(PROGRESS_KEY, JSON.stringify(state.progress));
}

function updateHistoryCount() {
  historyCount.textContent = Object.keys(state.watched).length;
}

function isFresh(video) {
  if (isWatched(video.id)) return false;
  const firstSeen = new Date(video.firstSeenAt || video.publishedAt).getTime();
  const freshHours = Number(state.feed?.freshHours || 24);
  return Number.isFinite(firstSeen) && Date.now() - firstSeen <= freshHours * 3600000;
}

function timeAgo(value) {
  const stamp = new Date(value).getTime();
  if (!Number.isFinite(stamp)) return "Recently";
  const seconds = Math.max(1, Math.floor((Date.now() - stamp) / 1000));
  const units = [
    ["year", 31536000],
    ["month", 2592000],
    ["week", 604800],
    ["day", 86400],
    ["hour", 3600],
    ["minute", 60],
  ];
  for (const [label, size] of units) {
    const amount = Math.floor(seconds / size);
    if (amount >= 1) return `${amount} ${label}${amount === 1 ? "" : "s"} ago`;
  }
  return "just now";
}

function sourceBadge(source) {
  return `<span class="source-badge ${source === "primary" ? "primary" : "secondary"}">${
    source === "primary" ? "Priority channel" : "Topic discovery"
  }</span>`;
}

function statusOverlay(video) {
  if (isWatched(video.id)) return '<span class="watched-pill">✓ Watched</span>';
  if (isFresh(video)) return '<span class="fresh-pill">New</span>';
  return '<span class="unwatched-dot" title="Unwatched"></span>';
}

function progressBar(video) {
  const ratio = progressFor(video.id);
  if (ratio <= 0 || ratio >= 1) return "";
  return `<span class="watch-progress"><i style="width:${Math.round(ratio * 100)}%"></i></span>`;
}

function videoCard(video) {
  const watched = isWatched(video.id);
  return `
    <button class="video-card ${watched ? "watched-card" : ""}" data-video-id="${escapeHtml(video.id)}">
      <span class="video-thumb">
        <img src="${escapeHtml(video.thumbnail)}" alt="" loading="lazy" referrerpolicy="no-referrer">
        <span class="duration">${escapeHtml(video.duration || "Video")}</span>
        <span class="play-hover">▶</span>
        ${statusOverlay(video)}
        ${progressBar(video)}
      </span>
      <span class="video-body">
        <span class="avatar">${escapeHtml(initials(video.channel))}</span>
        <span>
          <span class="video-title">${escapeHtml(video.title)}</span>
          <span class="video-channel">${escapeHtml(video.channel)}</span>
          <span class="video-stats">${escapeHtml(video.views || "Views unavailable")} • ${escapeHtml(timeAgo(video.publishedAt))}</span>
          ${sourceBadge(video.source)}
        </span>
      </span>
    </button>`;
}

function shortCard(video) {
  const watched = isWatched(video.id);
  return `
    <button class="short-card ${watched ? "watched-card" : ""}" data-short-id="${escapeHtml(video.id)}">
      <span class="short-thumb">
        <img src="${escapeHtml(video.thumbnail)}" alt="" loading="lazy" referrerpolicy="no-referrer">
        <span class="play-hover">▶</span>
        ${statusOverlay(video)}
        ${progressBar(video)}
      </span>
      <span class="short-title">${escapeHtml(video.title)}</span>
      <span class="short-meta">${escapeHtml(video.views || "Views unavailable")} • ${escapeHtml(video.channel)}</span>
    </button>`;
}

function toolbar() {
  const options = [
    ["home", "All"],
    ["shorts", "Shorts"],
    ["long", "Long videos"],
    ["history", "Watch history"],
  ];
  const feedItems = state.feed?.items || [];
  const unwatched = feedItems.filter((item) => !isWatched(item.id)).length;
  const fresh = feedItems.filter(isFresh).length;
  return `
    <div class="toolbar">
      <div class="chips">
        ${options.map(([id, label]) => `<button class="chip ${state.view === id ? "active" : ""}" data-view="${id}">${label}</button>`).join("")}
        <span class="chip unwatched-count">${unwatched} unwatched</span>
        <span class="chip fresh-count">${fresh} new</span>
      </div>
      ${state.query ? `<button class="chip" id="clearSearch">“${escapeHtml(state.query)}” ×</button>` : ""}
    </div>`;
}

function emptyState(title, description) {
  return `<div class="empty"><span>✓</span><h2>${escapeHtml(title)}</h2><p>${escapeHtml(description)}</p></div>`;
}

function settingsView() {
  const health = state.feed?.health || {};
  const secondary = health.secondary || {};
  return `
    <section class="settings">
      <div class="settings-hero">
        <p class="eyebrow">Feed control</p>
        <h1>NexaFeed monitoring</h1>
        <p>Supplied channels are ranked first. Rotating keyword, topic, and category matches stay in the secondary discovery feed.</p>
      </div>
      <div class="settings-grid">
        <article class="settings-card"><strong>${state.feed?.primaryChannels || 0}</strong><h2>Primary channels</h2><p>Edit <code>data/channels.csv</code> to control long video and Shorts monitoring.</p></article>
        <article class="settings-card"><strong>${state.feed?.stats?.total || 0}</strong><h2>Current feed items</h2><p>${state.feed?.stats?.longVideos || 0} long videos and ${state.feed?.stats?.shorts || 0} Shorts are available now.</p></article>
        <article class="settings-card"><strong>${Object.keys(state.watched).length}</strong><h2>Watched on this device</h2><p>Watched items stay hidden from Home and remain available in Watch history.</p></article>
      </div>
      <div class="settings-grid health-grid">
        <article class="settings-card"><strong>${health.channelsChecked || 0}/${health.channelsRequested || 0}</strong><h2>Source health</h2><p>${health.channelsWithWarnings || 0} channel(s) returned partial warnings on the latest refresh.</p></article>
        <article class="settings-card"><strong>${escapeHtml(secondary.query || "Rotation idle")}</strong><h2>Latest discovery query</h2><p>One configured secondary term rotates on each hourly update.</p></article>
        <article class="settings-card"><strong>${escapeHtml(state.feed?.stats?.newThisRun || 0)}</strong><h2>New this refresh</h2><p>Feed data last refreshed ${escapeHtml(timeAgo(state.feed?.updatedAt))}.</p></article>
      </div>
      <article class="settings-card history-tools">
        <h2>Watch-state backup</h2>
        <p>History is private to this browser. Export it as JSON to move your watched/progress state to another browser or device.</p>
        <div class="settings-actions">
          <button id="exportHistory" class="action-button">Export history JSON</button>
          <button id="importHistory" class="action-button">Import history JSON</button>
          <button id="clearHistory" class="danger">Clear history</button>
          <input id="historyFile" type="file" accept="application/json,.json" hidden>
        </div>
      </article>
    </section>`;
}

function filteredItems() {
  if (!state.feed) return [];
  let items = [...state.feed.items];
  if (state.query) {
    const query = state.query.toLowerCase();
    items = items.filter((item) =>
      `${item.title} ${item.channel} ${item.handle || ""} ${item.topic || ""} ${item.category || ""}`
        .toLowerCase()
        .includes(query),
    );
  }
  if (state.view === "history") {
    return items
      .filter((item) => isWatched(item.id))
      .sort((a, b) => state.watched[b.id] - state.watched[a.id]);
  }
  items = items.filter((item) => !isWatched(item.id));
  if (state.view === "shorts") items = items.filter((item) => item.type === "short");
  if (state.view === "long") items = items.filter((item) => item.type === "long");
  return items;
}

function feedView() {
  const items = filteredItems();
  if (!items.length) {
    return toolbar() + emptyState(
      state.view === "history" ? "No watched videos yet" : "You're all caught up",
      state.view === "history"
        ? "Videos appear here after you watch at least 80% or mark them watched."
        : "Watched videos stay hidden. New uploads will arrive on the next hourly refresh.",
    );
  }

  const shorts = items.filter((item) => item.type === "short");
  const longVideos = items.filter((item) => item.type === "long");
  const shortsSection = shorts.length && state.view !== "long"
    ? `<section class="section">
        <div class="section-head">
          <div class="section-title"><span class="section-icon">ϟ</span><div><p class="eyebrow">Vertical playlist</p><h1>${state.view === "history" ? "Watched Shorts" : "Latest Shorts"}</h1></div></div>
          <span>${shorts.length} videos</span>
        </div>
        <div class="shorts-row">${shorts.map(shortCard).join("")}</div>
      </section>`
    : "";
  const longSection = longVideos.length && state.view !== "shorts"
    ? `<section class="section">
        <div class="section-head">
          <div class="section-title"><span class="section-icon">▶</span><div><p class="eyebrow">${state.view === "history" ? "Previously played" : "Priority channels first"}</p><h1>${state.view === "history" ? "Watch history" : state.query ? "Search results" : "Latest long videos"}</h1></div></div>
          <span>${longVideos.length} videos</span>
        </div>
        <div class="video-grid">${longVideos.map(videoCard).join("")}</div>
      </section>`
    : "";
  return toolbar() + shortsSection + longSection;
}

function render() {
  setActiveNav();
  if (state.activeVideo) renderPlayer();
  else if (state.view === "settings") app.innerHTML = settingsView();
  else app.innerHTML = feedView();
}

function setActiveNav() {
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === state.view);
  });
}

function queueFor(currentId) {
  const longs = state.feed?.items.filter((item) => item.type === "long" && item.id !== currentId) || [];
  return longs.filter((item) => !isWatched(item.id));
}

function renderPlayer() {
  const video = state.activeVideo;
  const queue = queueFor(video.id);
  app.innerHTML = `
    <section class="player-layout">
      <div>
        <div class="player-frame"><div id="youtubePlayer"></div></div>
        <div class="player-heading">
          <div>${sourceBadge(video.source)}<h1>${escapeHtml(video.title)}</h1></div>
          <button class="icon-button close-player" id="closePlayer" aria-label="Close player">×</button>
        </div>
        <div class="author-row">
          <div class="author-info"><span class="avatar">${escapeHtml(initials(video.channel))}</span><div><strong>${escapeHtml(video.channel)}</strong><small>${escapeHtml(video.handle || "")}</small></div></div>
          <div class="player-actions">
            <span class="video-stats">${escapeHtml(video.views || "Views unavailable")} • ${escapeHtml(timeAgo(video.publishedAt))}</span>
            <button class="action-button compact" id="markCurrentWatched">✓ Mark watched</button>
          </div>
        </div>
      </div>
      <aside class="up-next">
        <div class="queue-head">
          <div><strong>Up next</strong><small>${queue.length} unwatched videos</small></div>
          <label class="autoplay"><input id="autoplayToggle" type="checkbox" ${state.autoplay ? "checked" : ""}>Autoplay</label>
        </div>
        <div class="queue-list">
          ${queue.map((item) => `
            <button class="queue-card" data-video-id="${escapeHtml(item.id)}">
              <span class="queue-thumb"><img src="${escapeHtml(item.thumbnail)}" alt=""><span class="duration">${escapeHtml(item.duration || "Video")}</span>${progressBar(item)}</span>
              <span><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.channel)}</small><small>${escapeHtml(item.views || "")}</small></span>
            </button>`).join("") || '<div class="queue-empty">No unwatched long videos left.</div>'}
        </div>
      </aside>
    </section>`;
  createYoutubePlayer("youtubePlayer", video, {
    onEnded() {
      if (state.autoplay && queue[0]) openLong(queue[0]);
      else render();
    },
  });
}

function waitForYoutube() {
  return new Promise((resolve, reject) => {
    let attempts = 0;
    const timer = setInterval(() => {
      attempts += 1;
      if (window.YT?.Player) {
        clearInterval(timer);
        resolve(window.YT);
      } else if (attempts > 120) {
        clearInterval(timer);
        reject(new Error("YouTube player did not load."));
      }
    }, 100);
  });
}

function renderPlayerError(elementId, video) {
  const node = document.getElementById(elementId);
  if (!node) return;
  node.outerHTML = `
    <div id="${escapeHtml(elementId)}" class="player-error">
      <strong>This video could not be embedded.</strong>
      <span>The owner may have disabled playback outside YouTube.</span>
      <a href="${escapeHtml(video.url || `https://www.youtube.com/watch?v=${video.id}`)}" target="_blank" rel="noopener">Open on YouTube</a>
    </div>`;
}

async function createYoutubePlayer(elementId, video, options = {}) {
  destroyPlayer();
  try {
    const YT = await waitForYoutube();
    player = new YT.Player(elementId, {
      videoId: video.id,
      width: "100%",
      height: "100%",
      playerVars: { autoplay: 1, rel: 0, playsinline: 1, enablejsapi: 1, modestbranding: 1 },
      events: {
        onReady(event) {
          const saved = state.progress[video.id];
          if (saved?.seconds > 5 && Number(saved.ratio || 0) < 0.8) {
            event.target.seekTo(saved.seconds, true);
          }
          event.target.playVideo();
          progressTimer = setInterval(() => {
            try {
              const duration = event.target.getDuration();
              const current = event.target.getCurrentTime();
              if (duration > 0) saveProgress(video.id, current, duration);
            } catch {
              // The iframe may be transitioning between videos.
            }
          }, 1500);
        },
        onStateChange(event) {
          if (event.data === YT.PlayerState.ENDED) {
            markWatched(video.id);
            options.onEnded?.();
          }
        },
        onError() {
          destroyPlayer();
          renderPlayerError(elementId, video);
          options.onError?.();
        },
      },
    });
  } catch {
    const node = document.getElementById(elementId);
    if (node) {
      node.innerHTML = `<iframe src="https://www.youtube.com/embed/${encodeURIComponent(video.id)}?autoplay=1&rel=0&playsinline=1" allow="autoplay; encrypted-media; picture-in-picture" allowfullscreen title="${escapeHtml(video.title)}"></iframe>`;
    }
  }
}

function destroyPlayer() {
  if (progressTimer) clearInterval(progressTimer);
  progressTimer = null;
  if (player?.destroy) {
    try { player.destroy(); } catch { /* already removed */ }
  }
  player = null;
}

function openLong(video) {
  state.activeVideo = video;
  destroyPlayer();
  render();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function openShort(video) {
  const allShorts = state.feed.items.filter((item) => item.type === "short");
  state.shortQueue = [
    video,
    ...allShorts.filter((item) => item.id !== video.id && !isWatched(item.id)),
    ...allShorts.filter((item) => item.id !== video.id && isWatched(item.id)),
  ];
  state.shortIndex = 0;
  renderShort();
}

function renderShort() {
  const video = state.shortQueue[state.shortIndex];
  if (!video) return closeShort();
  overlayRoot.innerHTML = `
    <div class="short-overlay" id="shortOverlay">
      <button id="shortClose" class="icon-button short-close" aria-label="Close Shorts">×</button>
      <div class="short-stage">
        <div class="short-player">
          <div id="shortYoutubePlayer"></div>
          <div class="short-info">
            <div class="author-info"><span class="avatar">${escapeHtml(initials(video.channel))}</span><strong>${escapeHtml(video.channel)}</strong></div>
            <p>${escapeHtml(video.title)}</p>
            <small>${escapeHtml(video.views || "Views unavailable")} • ${state.shortIndex + 1} of ${state.shortQueue.length}</small>
          </div>
        </div>
        <div class="short-controls">
          <button id="shortPrevious" aria-label="Previous Short" ${state.shortIndex === 0 ? "disabled" : ""}>↑</button>
          <button id="shortNext" aria-label="Next Short" ${state.shortIndex === state.shortQueue.length - 1 ? "disabled" : ""}>↓</button>
        </div>
      </div>
    </div>`;
  createYoutubePlayer("shortYoutubePlayer", video, { onEnded: nextShort });
}

function nextShort() {
  if (state.shortIndex < state.shortQueue.length - 1) {
    state.shortIndex += 1;
    renderShort();
  }
}

function previousShort() {
  if (state.shortIndex > 0) {
    state.shortIndex -= 1;
    renderShort();
  }
}

function closeShort() {
  destroyPlayer();
  state.shortQueue = [];
  state.shortIndex = 0;
  overlayRoot.innerHTML = "";
  render();
}

function selectView(view) {
  state.view = view;
  state.activeVideo = null;
  state.query = "";
  searchInput.value = "";
  destroyPlayer();
  sidebar.classList.remove("open");
  scrim.classList.remove("open");
  render();
}

function exportHistory() {
  const payload = {
    schemaVersion: 1,
    exportedAt: new Date().toISOString(),
    watched: state.watched,
    progress: state.progress,
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `nexafeed-history-${new Date().toISOString().slice(0, 10)}.json`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}

async function importHistory(file) {
  if (!file) return;
  const data = JSON.parse(await file.text());
  state.watched = { ...state.watched, ...(data.watched || {}) };
  state.progress = { ...state.progress, ...(data.progress || {}) };
  localStorage.setItem(WATCHED_KEY, JSON.stringify(state.watched));
  localStorage.setItem(PROGRESS_KEY, JSON.stringify(state.progress));
  updateHistoryCount();
  render();
}

async function loadFeed() {
  app.innerHTML = '<div class="loading-grid"><i></i><i></i><i></i></div>';
  try {
    const response = await fetch(`data/videos.json?time=${Date.now()}`);
    if (!response.ok) throw new Error("Feed request failed");
    state.feed = await response.json();
    state.feed.items = Array.isArray(state.feed.items) ? state.feed.items : [];
    state.feed.items.sort((a, b) => {
      if (a.source !== b.source) return a.source === "primary" ? -1 : 1;
      if ((a.priority || 1) !== (b.priority || 1)) return (a.priority || 1) - (b.priority || 1);
      return new Date(b.publishedAt) - new Date(a.publishedAt);
    });
    const updated = new Date(state.feed.updatedAt);
    updatedLabel.innerHTML = Number.isFinite(updated.getTime())
      ? `<i></i>Updated ${updated.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}`
      : "<i></i>Waiting for first refresh";
    render();
  } catch {
    app.innerHTML = emptyState("Feed could not load", "Run this website through GitHub Pages or a local web server. Opening index.html directly cannot load JSON in some browsers.");
  }
}

document.querySelector("#menuButton").addEventListener("click", () => {
  sidebar.classList.toggle("open");
  scrim.classList.toggle("open");
});
scrim.addEventListener("click", () => {
  sidebar.classList.remove("open");
  scrim.classList.remove("open");
});
document.querySelector("#brandButton").addEventListener("click", () => selectView("home"));
document.querySelector("#refreshButton").addEventListener("click", loadFeed);
document.querySelector("#themeButton").addEventListener("click", (event) => {
  state.theme = state.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = state.theme;
  localStorage.setItem(THEME_KEY, state.theme);
  event.currentTarget.textContent = state.theme === "dark" ? "☀" : "☾";
});
document.querySelector("#searchForm").addEventListener("submit", (event) => {
  event.preventDefault();
  state.query = searchInput.value.trim();
  state.view = "home";
  state.activeVideo = null;
  render();
});
document.querySelector("#mainNav").addEventListener("click", (event) => {
  const button = event.target.closest("[data-view]");
  if (button) selectView(button.dataset.view);
});
app.addEventListener("click", (event) => {
  const viewButton = event.target.closest("[data-view]");
  if (viewButton) return selectView(viewButton.dataset.view);

  const shortButton = event.target.closest("[data-short-id]");
  if (shortButton) {
    const video = state.feed.items.find((item) => item.id === shortButton.dataset.shortId);
    if (video) openShort(video);
    return;
  }

  const videoButton = event.target.closest("[data-video-id]");
  if (videoButton) {
    const video = state.feed.items.find((item) => item.id === videoButton.dataset.videoId);
    if (video) openLong(video);
    return;
  }

  if (event.target.closest("#closePlayer")) {
    state.activeVideo = null;
    destroyPlayer();
    render();
  }
  if (event.target.closest("#markCurrentWatched") && state.activeVideo) {
    const currentId = state.activeVideo.id;
    markWatched(currentId);
    const queue = queueFor(currentId);
    if (state.autoplay && queue[0]) openLong(queue[0]);
    else {
      state.activeVideo = null;
      render();
    }
  }
  if (event.target.closest("#clearSearch")) {
    state.query = "";
    searchInput.value = "";
    render();
  }
  if (event.target.closest("#exportHistory")) exportHistory();
  if (event.target.closest("#importHistory")) document.querySelector("#historyFile")?.click();
  if (event.target.closest("#clearHistory")) {
    state.watched = {};
    state.progress = {};
    localStorage.removeItem(WATCHED_KEY);
    localStorage.removeItem(PROGRESS_KEY);
    updateHistoryCount();
    render();
  }
});
app.addEventListener("change", (event) => {
  if (event.target.id === "autoplayToggle") {
    state.autoplay = event.target.checked;
    localStorage.setItem(AUTOPLAY_KEY, String(state.autoplay));
  }
  if (event.target.id === "historyFile") {
    importHistory(event.target.files?.[0]).catch(() => window.alert("The selected history JSON could not be imported."));
  }
});
overlayRoot.addEventListener("click", (event) => {
  if (event.target.closest("#shortClose")) closeShort();
  if (event.target.closest("#shortNext")) nextShort();
  if (event.target.closest("#shortPrevious")) previousShort();
});
overlayRoot.addEventListener("wheel", (event) => {
  if (!state.shortQueue.length || wheelLocked || Math.abs(event.deltaY) < 20) return;
  wheelLocked = true;
  event.deltaY > 0 ? nextShort() : previousShort();
  setTimeout(() => { wheelLocked = false; }, 550);
}, { passive: true });
overlayRoot.addEventListener("touchstart", (event) => {
  touchStartY = event.touches[0]?.clientY ?? null;
}, { passive: true });
overlayRoot.addEventListener("touchend", (event) => {
  if (touchStartY === null) return;
  const distance = touchStartY - (event.changedTouches[0]?.clientY ?? touchStartY);
  if (Math.abs(distance) > 45) distance > 0 ? nextShort() : previousShort();
  touchStartY = null;
}, { passive: true });
window.addEventListener("keydown", (event) => {
  if (!state.shortQueue.length) return;
  if (event.key === "Escape") closeShort();
  if (event.key === "ArrowDown") nextShort();
  if (event.key === "ArrowUp") previousShort();
});

loadFeed();
