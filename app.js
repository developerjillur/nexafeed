const app = document.querySelector("#app");
const overlayRoot = document.querySelector("#overlayRoot");
const sidebar = document.querySelector("#sidebar");
const scrim = document.querySelector("#scrim");
const searchInput = document.querySelector("#searchInput");
const updatedLabel = document.querySelector("#updatedLabel");
const historyCount = document.querySelector("#historyCount");
const likedCount = document.querySelector("#likedCount");

const WATCHED_KEY = "nexafeed-watched-v1";
const PROGRESS_KEY = "nexafeed-progress-v1";
const THEME_KEY = "nexafeed-theme-v1";
const AUTOPLAY_KEY = "nexafeed-autoplay-v1";
const LIKED_KEY = "nexafeed-liked-v1";

const state = {
  feed: null,
  details: { items: {} },
  feedSettings: { channels: [], keywords: [], topics: [], categories: [] },
  settingsDraft: null,
  view: "home",
  query: "",
  quickFilter: "all",
  watched: readJson(WATCHED_KEY, {}),
  progress: readJson(PROGRESS_KEY, {}),
  liked: readJson(LIKED_KEY, {}),
  theme: localStorage.getItem(THEME_KEY) || "dark",
  activeVideo: null,
  shortQueue: [],
  shortIndex: 0,
  shortPanel: null,
  unavailableVideos: new Set(),
  autoplay: localStorage.getItem(AUTOPLAY_KEY) !== "false",
};

let player = null;
let progressTimer = null;
let wheelLocked = false;
let touchStartY = null;

document.documentElement.dataset.theme = state.theme;
document.querySelector("#themeButton").textContent = state.theme === "dark" ? "☀" : "☾";
updateHistoryCount();
updateLikedCount();

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

function isLiked(id) {
  return Boolean(state.liked[id]);
}

function saveLiked() {
  localStorage.setItem(LIKED_KEY, JSON.stringify(state.liked));
  updateLikedCount();
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

function updateLikedCount() {
  likedCount.textContent = Object.keys(state.liked).length;
}

function isFresh(video) {
  if (isWatched(video.id)) return false;
  const firstSeen = new Date(video.firstSeenAt || video.publishedAt).getTime();
  const freshHours = Number(state.feed?.freshHours || 24);
  return Number.isFinite(firstSeen) && Date.now() - firstSeen <= freshHours * 3600000;
}

function searchableText(item) {
  return `${item.title || ""} ${item.channel || ""} ${item.handle || ""} ${item.topic || ""} ${item.category || ""}`.toLowerCase();
}

function normalizedTitle(value = "") {
  return String(value)
    .toLowerCase()
    .replace(/#[\p{L}\p{N}_-]+/gu, "")
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .replace(/\b(shorts?|video|viral)\b/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function duplicateKey(item) {
  const title = normalizedTitle(item.title);
  if (title.length < 18 || ["untitled facebook", "untitled"].includes(title)) return "";
  const channel = String(item.channelId || item.handle || item.channel || "").toLowerCase();
  return `${item.type || "video"}|${channel}|${title}`;
}

function betterDuplicate(candidate, current) {
  if (!current) return candidate;
  if (current.source !== candidate.source) return candidate.source === "primary" ? candidate : current;
  if ((candidate.priority || 99) !== (current.priority || 99)) return (candidate.priority || 99) < (current.priority || 99) ? candidate : current;
  if ((candidate.viewCount || 0) !== (current.viewCount || 0)) return (candidate.viewCount || 0) > (current.viewCount || 0) ? candidate : current;
  const candidateDate = new Date(candidate.publishedAt || 0).getTime();
  const currentDate = new Date(current.publishedAt || 0).getTime();
  return candidateDate > currentDate ? candidate : current;
}

function collapseRepeatedItems(items) {
  const byId = new Set();
  const bySemantic = new Map();
  const orderedKeys = [];
  for (const item of items) {
    if (!item?.id || byId.has(item.id)) continue;
    byId.add(item.id);
    const key = duplicateKey(item) || `id:${item.id}`;
    if (!bySemantic.has(key)) orderedKeys.push(key);
    bySemantic.set(key, betterDuplicate(item, bySemantic.get(key)));
  }
  return orderedKeys.map((key) => bySemantic.get(key)).filter(Boolean);
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

function saveButton(video, context = "card") {
  const liked = isLiked(video.id);
  const label = liked ? "Remove from Liked videos" : "Save to Liked videos";
  return `<button class="save-button ${context}-save ${liked ? "active" : ""}" type="button" data-like-id="${escapeHtml(video.id)}" aria-label="${escapeHtml(label)}" aria-pressed="${liked}"><span>${liked ? "♥" : "♡"}</span></button>`;
}

function videoCard(video) {
  const watched = isWatched(video.id);
  return `
    <article class="video-card ${watched ? "watched-card" : ""}">
      <button class="card-open" type="button" data-video-id="${escapeHtml(video.id)}" aria-label="Play ${escapeHtml(video.title)}">
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
      </button>
      ${saveButton(video, "card")}
    </article>`;
}

function shortCard(video) {
  const watched = isWatched(video.id);
  return `
    <article class="short-card ${watched ? "watched-card" : ""}">
      <button class="card-open" type="button" data-short-id="${escapeHtml(video.id)}" aria-label="Open Short ${escapeHtml(video.title)}">
        <span class="short-thumb">
          <img src="${escapeHtml(video.thumbnail)}" alt="" loading="lazy" referrerpolicy="no-referrer">
          <span class="play-hover">▶</span>
          ${statusOverlay(video)}
          ${progressBar(video)}
        </span>
        <span class="short-title">${escapeHtml(video.title)}</span>
        <span class="short-meta">${escapeHtml(video.views || "Views unavailable")} • ${escapeHtml(video.channel)}</span>
      </button>
      ${saveButton(video, "card")}
    </article>`;
}

function toolbar() {
  const options = [
    ["home", "All"],
    ["shorts", "Shorts"],
    ["long", "Long videos"],
    ["liked", "Liked"],
    ["history", "Watch history"],
  ];
  const feedItems = state.feed?.items || [];
  const unwatched = feedItems.filter((item) => !isWatched(item.id)).length;
  const fresh = feedItems.filter(isFresh).length;
  return `
    <div class="toolbar">
      <div class="chips">
        ${options.map(([id, label]) => `<button class="chip ${state.view === id && state.quickFilter === "all" ? "active" : ""}" data-view="${id}">${label}</button>`).join("")}
        <button class="chip count-chip unwatched-count ${state.quickFilter === "unwatched" ? "active" : ""}" data-quick-filter="unwatched">${unwatched} unwatched</button>
        <button class="chip count-chip fresh-count ${state.quickFilter === "fresh" ? "active" : ""}" data-quick-filter="fresh">${fresh} new</button>
      </div>
      ${state.query ? `<button class="chip" id="clearSearch">“${escapeHtml(state.query)}” ×</button>` : ""}
    </div>`;
}

function emptyState(title, description) {
  return `<div class="empty"><span>✓</span><h2>${escapeHtml(title)}</h2><p>${escapeHtml(description)}</p></div>`;
}

function likedItems() {
  return collapseRepeatedItems((state.feed?.items || []).filter((item) => isLiked(item.id)));
}

function likedTools() {
  if (state.view !== "liked") return "";
  const count = likedItems().length;
  return `
    <article class="settings-card history-tools liked-tools">
      <div>
        <h2>Liked videos saved locally</h2>
        <p>${count ? `${count} saved item${count === 1 ? "" : "s"}. Export a backup before clearing browser data.` : "Tap any heart button to build your saved list in this browser."}</p>
      </div>
      <div class="settings-actions">
        <button id="exportLiked" class="action-button" type="button" ${count ? "" : "disabled"}>Export likes JSON</button>
        <button id="clearLiked" class="danger" type="button" ${count ? "" : "disabled"}>Clear liked</button>
      </div>
    </article>`;
}

function freshSettingsDraft() {
  const source = state.feedSettings || {};
  return {
    channels: (source.channels || []).map((channel) => ({ ...channel })),
    keywords: [...(source.keywords || [])],
    topics: [...(source.topics || [])],
    categories: [...(source.categories || [])],
  };
}

function channelEditorRow(channel, index) {
  return `
    <div class="channel-editor-row" data-channel-index="${index}">
      <label><span>Channel name</span><input data-field="name" value="${escapeHtml(channel.name || "")}" placeholder="Channel name"></label>
      <label><span>YouTube handle</span><input data-field="handle" value="${escapeHtml(channel.handle || "")}" placeholder="@handle"></label>
      <label class="channel-url"><span>Channel URL</span><input data-field="url" value="${escapeHtml(channel.url || "")}" placeholder="https://www.youtube.com/@handle"></label>
      <label><span>Category</span><input data-field="category" value="${escapeHtml(channel.category || "Long + Shorts")}" placeholder="AI automation"></label>
      <label><span>Priority</span><input data-field="priority" type="number" min="1" max="99" value="${escapeHtml(channel.priority || 1)}"></label>
      <label class="monitor-toggle"><input data-field="monitorLong" type="checkbox" ${channel.monitorLong ? "checked" : ""}><span>Long videos</span></label>
      <label class="monitor-toggle"><input data-field="monitorShorts" type="checkbox" ${channel.monitorShorts ? "checked" : ""}><span>Shorts</span></label>
      <button class="remove-channel danger" type="button" data-remove-channel="${index}" aria-label="Remove ${escapeHtml(channel.name || channel.handle || "channel")}">Remove</button>
    </div>`;
}

function splitSettingsTerms(value) {
  return String(value || "").split(/[\n,]/).map((term) => term.trim()).filter(Boolean);
}

function readSettingsDraftFromDom() {
  const rows = [...document.querySelectorAll(".channel-editor-row")];
  if (!rows.length) return state.settingsDraft || freshSettingsDraft();
  const channels = rows.map((row) => {
    const field = (name) => row.querySelector(`[data-field="${name}"]`);
    const handle = field("handle").value.trim();
    return {
      name: field("name").value.trim() || handle,
      handle,
      url: field("url").value.trim() || `https://www.youtube.com/${handle.startsWith("@") ? handle : `@${handle}`}`,
      category: field("category").value.trim() || "Long + Shorts",
      priority: Number(field("priority").value || 1),
      monitorLong: field("monitorLong").checked,
      monitorShorts: field("monitorShorts").checked,
    };
  });
  return {
    channels,
    keywords: splitSettingsTerms(document.querySelector("#settingsKeywords")?.value),
    topics: splitSettingsTerms(document.querySelector("#settingsTopics")?.value),
    categories: splitSettingsTerms(document.querySelector("#settingsCategories")?.value),
  };
}

function addChannelRow() {
  state.settingsDraft = readSettingsDraftFromDom();
  state.settingsDraft.channels.push({
    name: "",
    handle: "",
    url: "",
    category: "Long + Shorts",
    priority: 1,
    monitorLong: true,
    monitorShorts: true,
  });
  render();
  document.querySelector(".channel-editor-row:last-child input")?.focus();
}

function removeChannelRow(index) {
  state.settingsDraft = readSettingsDraftFromDom();
  state.settingsDraft.channels.splice(index, 1);
  render();
}

function validateSettingsDraft(draft) {
  if (!draft.channels.length) throw new Error("At least one channel is required.");
  const seen = new Set();
  for (const channel of draft.channels) {
    if (!/^@?[A-Za-z0-9._-]{3,100}$/.test(channel.handle)) throw new Error(`Invalid YouTube handle: ${channel.handle || "blank handle"}`);
    channel.handle = channel.handle.startsWith("@") ? channel.handle : `@${channel.handle}`;
    const key = channel.handle.toLowerCase();
    if (seen.has(key)) throw new Error(`Duplicate channel: ${channel.handle}`);
    seen.add(key);
    if (!channel.monitorLong && !channel.monitorShorts) throw new Error(`${channel.handle} must monitor Long videos, Shorts, or both.`);
  }
  return draft;
}

async function gzipBase64Url(value) {
  if (!("CompressionStream" in window)) throw new Error("This browser cannot create the secure compressed settings request. Use current Chrome, Edge, or Safari.");
  const stream = new Blob([new TextEncoder().encode(value)]).stream().pipeThrough(new CompressionStream("gzip"));
  const bytes = new Uint8Array(await new Response(stream).arrayBuffer());
  let binary = "";
  for (let index = 0; index < bytes.length; index += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(index, index + 0x8000));
  }
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}

function settingsChangeSummary(draft) {
  const current = state.feedSettings || { channels: [] };
  const before = new Set((current.channels || []).map((channel) => String(channel.handle || "").toLowerCase()));
  const after = new Set(draft.channels.map((channel) => channel.handle.toLowerCase()));
  const added = draft.channels.filter((channel) => !before.has(channel.handle.toLowerCase())).map((channel) => channel.handle);
  const removed = (current.channels || []).filter((channel) => !after.has(String(channel.handle || "").toLowerCase())).map((channel) => channel.handle);
  const longCount = draft.channels.filter((channel) => channel.monitorLong).length;
  const shortsCount = draft.channels.filter((channel) => channel.monitorShorts).length;
  return [
    `Channels: ${draft.channels.length} total (${longCount} Long-enabled, ${shortsCount} Shorts-enabled)`,
    `Added: ${added.length ? added.join(", ") : "None"}`,
    `Removed: ${removed.length ? removed.join(", ") : "None"}`,
    `Discovery: ${draft.keywords.length} keywords, ${draft.topics.length} topics, ${draft.categories.length} categories`,
  ];
}

async function applyFeedSettings() {
  const popup = window.open("about:blank", "_blank");
  if (popup) popup.opener = null;
  try {
    const draft = validateSettingsDraft(readSettingsDraftFromDom());
    state.settingsDraft = draft;
    const token = await gzipBase64Url(JSON.stringify(draft));
    const body = [
      "This owner-authorized issue applies the Feed Settings currently shown in NexaFeed.",
      "Review the summary below, then submit without editing the hidden marker.",
      "",
      "## Change summary",
      ...settingsChangeSummary(draft).map((line) => `- ${line}`),
      "",
      "GitHub Actions will validate, commit, deploy, and close this issue.",
      "",
      `<!-- NEXAFEED_CONFIG_V1:GZIP_BASE64URL:${token} -->`,
    ].join("\n");
    const issueUrl = new URL("https://github.com/developerjillur/nexafeed/issues/new");
    issueUrl.searchParams.set("title", "[NexaFeed Config] Apply feed settings");
    issueUrl.searchParams.set("body", body);
    if (popup) popup.location.href = issueUrl.toString();
    else window.location.href = issueUrl.toString();
  } catch (error) {
    popup?.close();
    window.alert(error.message || "Feed settings could not be prepared.");
  }
}

function settingsView() {
  const health = state.feed?.health || {};
  const secondary = health.secondary || {};
  if (!state.settingsDraft) state.settingsDraft = freshSettingsDraft();
  const draft = state.settingsDraft;
  return `
    <section class="settings">
      <div class="settings-hero">
        <p class="eyebrow">Feed control</p>
        <h1>Manage monitored channels and discovery</h1>
        <p>Add, edit, or remove YouTube channels and control whether each source contributes Long videos, Shorts, or both. Changes use an owner-only GitHub confirmation, so no token is stored in this website.</p>
      </div>
      <div class="settings-grid">
        <article class="settings-card"><strong>${draft.channels.length}</strong><h2>Primary channels</h2><p>These sources always rank before keyword and topic discovery.</p></article>
        <article class="settings-card"><strong>${state.feed?.stats?.total || 0}</strong><h2>Playable feed items</h2><p>${state.feed?.stats?.longVideos || 0} long videos and ${state.feed?.stats?.shorts || 0} Shorts after embed filtering.</p></article>
        <article class="settings-card"><strong>${health.richMetadata?.embedBlocked || 0}</strong><h2>Embedding blocked</h2><p>Videos explicitly unavailable in an iframe are removed during refresh.</p></article>
      </div>
      <article class="settings-card source-manager">
        <div class="manager-heading">
          <div><p class="eyebrow">Priority sources</p><h2>Channel manager</h2><small>${draft.channels.length} configured sources</small></div>
          <div class="manager-tools">
            <label class="channel-search"><span>⌕</span><input id="channelManagerSearch" type="search" placeholder="Filter channels" aria-label="Filter configured channels"></label>
            <button id="resetFeedSettings" class="action-button" type="button">Reset draft</button>
            <button id="addChannelRow" class="action-button" type="button">+ Add channel</button>
          </div>
        </div>
        <div class="channel-editor">${draft.channels.map(channelEditorRow).join("")}</div>
      </article>
      <article class="settings-card discovery-manager">
        <div class="manager-heading"><div><p class="eyebrow">Secondary discovery</p><h2>Keywords, topics, and categories</h2></div></div>
        <p>Enter one term per line. One term rotates through YouTube search on each hourly refresh.</p>
        <div class="discovery-fields">
          <label><span>Keywords</span><textarea id="settingsKeywords" rows="6">${escapeHtml(draft.keywords.join("\n"))}</textarea></label>
          <label><span>Topics</span><textarea id="settingsTopics" rows="6">${escapeHtml(draft.topics.join("\n"))}</textarea></label>
          <label><span>Categories</span><textarea id="settingsCategories" rows="6">${escapeHtml(draft.categories.join("\n"))}</textarea></label>
        </div>
        <div class="apply-settings-bar">
          <div><strong>Secure owner confirmation</strong><span>GitHub opens a prefilled issue. Submit once; Actions validates and applies it.</span></div>
          <button id="applyFeedSettings" class="apply-settings" type="button">Review and apply on GitHub</button>
        </div>
      </article>
      <div class="settings-grid health-grid">
        <article class="settings-card"><strong>${health.channelsChecked || 0}/${health.channelsRequested || 0}</strong><h2>Source health</h2><p>${health.channelsWithWarnings || 0} source warning(s) on the latest refresh.</p></article>
        <article class="settings-card"><strong>${escapeHtml(secondary.query || "Rotation idle")}</strong><h2>Latest discovery query</h2><p>Primary channels remain ranked first.</p></article>
        <article class="settings-card"><strong>${escapeHtml(state.feed?.stats?.newThisRun || 0)}</strong><h2>New this refresh</h2><p>Last refreshed ${escapeHtml(timeAgo(state.feed?.updatedAt))}.</p></article>
      </div>
      <article class="settings-card history-tools">
        <h2>Watch-state backup</h2>
        <p>History remains private to this browser. Export JSON to move watched/progress state to another browser or device.</p>
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
  let items = [...state.feed.items].filter(
    (item) => item.embedAllowed !== false && !state.unavailableVideos.has(item.id),
  );
  const hasQuery = Boolean(state.query);
  if (hasQuery) {
    const terms = state.query.toLowerCase().split(/\s+/).filter(Boolean);
    items = items.filter((item) => terms.every((term) => searchableText(item).includes(term)));
  }
  if (state.view === "history") {
    items = items
      .filter((item) => isWatched(item.id))
      .sort((a, b) => state.watched[b.id] - state.watched[a.id]);
  } else if (state.view === "liked") {
    items = items
      .filter((item) => isLiked(item.id))
      .sort((a, b) => state.liked[b.id] - state.liked[a.id]);
  } else if (!hasQuery) {
    items = items.filter((item) => !isWatched(item.id));
  }
  if (state.quickFilter === "unwatched") items = items.filter((item) => !isWatched(item.id));
  if (state.quickFilter === "fresh") items = items.filter(isFresh);
  if (state.view === "shorts") items = items.filter((item) => item.type === "short");
  if (state.view === "long") items = items.filter((item) => item.type === "long");
  return collapseRepeatedItems(items);
}

function feedView() {
  const items = filteredItems();
  if (!items.length) {
    const searchEmpty = Boolean(state.query);
    const emptyTitle = state.view === "history"
      ? "No watched videos yet"
      : state.view === "liked"
        ? "No liked videos yet"
        : searchEmpty ? "No matching videos" : "You're all caught up";
    const emptyDescription = state.view === "history"
      ? "Videos appear here after you watch at least 80% or mark them watched."
      : state.view === "liked"
        ? "Tap the heart on any Short to save it here. Liked videos are saved locally in this browser."
        : searchEmpty
          ? "Try a channel name, title keyword, topic, or category. Search updates live as you type."
          : "Watched videos stay hidden. New uploads will arrive on the next hourly refresh.";
    return toolbar() + likedTools() + emptyState(
      emptyTitle,
      emptyDescription,
    );
  }

  const shorts = items.filter((item) => item.type === "short");
  const longVideos = items.filter((item) => item.type === "long");
  const shortsTitle = state.view === "history" ? "Watched Shorts" : state.view === "liked" ? "Liked Shorts" : "Latest Shorts";
  const longEyebrow = state.view === "history" ? "Previously played" : state.view === "liked" ? "Saved locally" : "Priority channels first";
  const longTitle = state.view === "history" ? "Watch history" : state.view === "liked" ? "Liked long videos" : state.query ? "Search results" : "Latest long videos";
  const shortsSection = shorts.length && state.view !== "long"
    ? `<section class="section">
        <div class="section-head">
          <div class="section-title"><span class="section-icon">ϟ</span><div><p class="eyebrow">${state.view === "liked" ? "Saved Shorts" : "Vertical playlist"}</p><h1>${shortsTitle}</h1></div></div>
          <span>${shorts.length} videos</span>
        </div>
        <div class="short-carousel">
          <button class="carousel-nav prev" type="button" data-carousel-scroll="shorts" data-direction="-1" aria-label="Previous Shorts">‹</button>
          <div class="shorts-row" id="shortsCarousel" tabindex="0" aria-label="Shorts carousel">${shorts.map(shortCard).join("")}</div>
          <button class="carousel-nav next" type="button" data-carousel-scroll="shorts" data-direction="1" aria-label="Next Shorts">›</button>
        </div>
      </section>`
    : "";
  const longSection = longVideos.length && state.view !== "shorts"
    ? `<section class="section">
        <div class="section-head">
          <div class="section-title"><span class="section-icon">▶</span><div><p class="eyebrow">${longEyebrow}</p><h1>${longTitle}</h1></div></div>
          <span>${longVideos.length} videos</span>
        </div>
        <div class="video-grid">${longVideos.map(videoCard).join("")}</div>
      </section>`
    : "";
  return toolbar() + likedTools() + shortsSection + longSection;
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
  return longs.filter((item) => !isWatched(item.id) && item.embedAllowed !== false && !state.unavailableVideos.has(item.id));
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
            ${saveButton(video, "player")}
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
    onError() {
      state.unavailableVideos.add(video.id);
      if (queue[0]) {
        setTimeout(() => {
          if (state.activeVideo?.id === video.id) openLong(queue[0]);
        }, 1600);
      }
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
          if (progressTimer) clearInterval(progressTimer);
          progressTimer = null;
          player = null;
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

function detailFor(videoId) {
  return state.details?.items?.[videoId] || {};
}

function compactMetric(value, fallback = "—") {
  const number = Number(value || 0);
  if (!Number.isFinite(number) || number <= 0) return fallback;
  return new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(number);
}

async function shareCurrentShort(button) {
  const video = state.shortQueue[state.shortIndex];
  if (!video) return;
  try {
    if (navigator.share) {
      await navigator.share({ title: video.title, text: `${video.title} — ${video.channel}`, url: video.url });
      return;
    }
    await navigator.clipboard.writeText(video.url);
    const label = button?.querySelector("small");
    if (label) {
      const original = label.textContent;
      label.textContent = "Copied";
      setTimeout(() => { label.textContent = original; }, 1400);
    }
  } catch (error) {
    if (error?.name !== "AbortError") window.alert("The video link could not be shared. Open it on YouTube instead.");
  }
}

function updateLikeButton(button, liked) {
  button?.classList.toggle("active", liked);
  button?.setAttribute("aria-pressed", String(liked));
  button?.setAttribute("aria-label", liked ? "Remove from Liked videos" : "Save to Liked videos");
  const icon = button?.querySelector("span");
  const label = button?.querySelector("small");
  if (icon) icon.textContent = liked ? "♥" : "♡";
  if (label) label.textContent = liked ? "Liked" : label.dataset.defaultLabel || "Like";
}

function toggleLikeVideo(videoId, button) {
  if (!videoId) return false;
  if (isLiked(videoId)) delete state.liked[videoId];
  else state.liked[videoId] = Date.now();
  saveLiked();
  const liked = isLiked(videoId);
  updateLikeButton(button, liked);
  if (state.view === "liked" && !liked && !state.activeVideo && !state.shortQueue.length) render();
  return liked;
}

function toggleLikeCurrentShort(button) {
  const video = state.shortQueue[state.shortIndex];
  if (!video) return;
  toggleLikeVideo(video.id, button);
}

function commentCard(comment) {
  const author = escapeHtml(comment.author || "YouTube viewer");
  const avatar = comment.authorThumbnail
    ? `<img src="${escapeHtml(comment.authorThumbnail)}" alt="" referrerpolicy="no-referrer">`
    : `<span>${escapeHtml(initials(comment.author || "Viewer"))}</span>`;
  return `
    <article class="short-comment">
      <div class="comment-avatar">${avatar}</div>
      <div>
        <div class="comment-head"><strong>${author}${comment.isUploader ? " · Creator" : ""}</strong><span>${escapeHtml(timeAgo(comment.publishedAt))}</span></div>
        ${comment.isPinned ? '<small class="pinned-comment">▣ Pinned</small>' : ""}
        <p>${escapeHtml(comment.text || "").replaceAll("\n", "<br>")}</p>
        <small>♡ ${Number(comment.likeCount || 0).toLocaleString()}</small>
      </div>
    </article>`;
}

function shortDrawerContent(video) {
  const detail = detailFor(video.id);
  if (state.shortPanel === "description") {
    return `
      <div class="short-drawer-head"><div><p class="eyebrow">About this Short</p><h2>Description</h2></div><button id="shortDrawerClose" aria-label="Close details">×</button></div>
      <div class="short-description">
        <strong>${escapeHtml(video.title)}</strong>
        <p>${escapeHtml(detail.description || "Description is not available in the current metadata cache.").replaceAll("\n", "<br>")}</p>
        <dl><div><dt>Channel</dt><dd>${escapeHtml(video.channel)}</dd></div><div><dt>Published</dt><dd>${escapeHtml(timeAgo(video.publishedAt))}</dd></div><div><dt>Views</dt><dd>${escapeHtml(video.views || "Unavailable")}</dd></div></dl>
        <a href="${escapeHtml(video.url)}" target="_blank" rel="noopener">View original on YouTube ↗</a>
      </div>`;
  }
  const comments = detail.comments || [];
  const reportedCount = Number(detail.commentCount || 0);
  const visibleCount = Math.max(reportedCount, comments.length);
  return `
    <div class="short-drawer-head"><div><p class="eyebrow">Public YouTube discussion</p><h2>Comments <small>${visibleCount.toLocaleString()}</small></h2></div><button id="shortDrawerClose" aria-label="Close comments">×</button></div>
    <div class="short-comments">
      <div class="comments-cache-note">Showing ${comments.length} cached top comment${comments.length === 1 ? "" : "s"}</div>
      ${comments.length ? comments.map(commentCard).join("") : `<div class="drawer-empty"><span>◯</span><strong>No cached comments</strong><p>Comments may be disabled, unavailable, or waiting for the next metadata refresh.</p><a href="${escapeHtml(video.url)}" target="_blank" rel="noopener">Open comments on YouTube ↗</a></div>`}
    </div>
    <a class="comments-open-youtube" href="${escapeHtml(video.url)}" target="_blank" rel="noopener">Open YouTube to view all comments or reply ↗</a>`;
}

function toggleShortPanel(panel) {
  state.shortPanel = state.shortPanel === panel ? null : panel;
  const drawer = document.querySelector("#shortDrawer");
  if (drawer) {
    drawer.classList.toggle("open", Boolean(state.shortPanel));
    drawer.innerHTML = state.shortPanel ? shortDrawerContent(state.shortQueue[state.shortIndex]) : "";
  }
  document.querySelector("#shortCommentsButton")?.classList.toggle("active", state.shortPanel === "comments");
  document.querySelector("#shortDescriptionButton")?.classList.toggle("active", state.shortPanel === "description");
}

function skipUnavailableShort(videoId) {
  const currentIndex = state.shortIndex;
  state.shortQueue = state.shortQueue.filter((item) => item.id !== videoId);
  if (!state.shortQueue.length) return closeShort();
  state.shortIndex = Math.min(currentIndex, state.shortQueue.length - 1);
  renderShort();
}

function openShort(video) {
  const allShorts = state.feed.items.filter(
    (item) => item.type === "short" && item.embedAllowed !== false && !state.unavailableVideos.has(item.id),
  );
  state.shortQueue = [
    video,
    ...allShorts.filter((item) => item.id !== video.id && !isWatched(item.id)),
  ];
  state.shortIndex = 0;
  state.shortPanel = null;
  renderShort();
}

function renderShort() {
  const video = state.shortQueue[state.shortIndex];
  if (!video) return closeShort();
  const detail = detailFor(video.id);
  const commentCount = Number(detail.commentCount || detail.comments?.length || 0);
  const likeCount = Number(detail.likeCount || 0);
  const liked = isLiked(video.id);
  const likeLabel = compactMetric(likeCount, "Like");
  overlayRoot.innerHTML = `
    <div class="short-overlay" id="shortOverlay">
      <button id="shortClose" class="icon-button short-close" aria-label="Close Shorts">×</button>
      <div class="short-stage">
        <div class="short-shell">
          <div class="short-player">
            <div id="shortYoutubePlayer"></div>
          </div>
          <div class="short-action-stack">
            <button id="shortLikeButton" class="short-like ${liked ? "active" : ""}" aria-label="Save this Short to local likes" aria-pressed="${liked}"><span>${liked ? "♥" : "♡"}</span><small data-default-label="${escapeHtml(likeLabel)}">${liked ? "Liked" : escapeHtml(likeLabel)}</small></button>
            <button id="shortCommentsButton" class="${state.shortPanel === "comments" ? "active" : ""}" aria-label="Show comments"><span>▤</span><small>${compactMetric(commentCount, "Comments")}</small></button>
            <button id="shortShareButton" aria-label="Share this Short"><span>↗</span><small>Share</small></button>
            <button id="shortDescriptionButton" class="${state.shortPanel === "description" ? "active" : ""}" aria-label="Show description"><span>i</span><small>About</small></button>
            <a href="${escapeHtml(video.channelUrl || video.url)}" target="_blank" rel="noopener" aria-label="Open ${escapeHtml(video.channel)} on YouTube"><span class="action-avatar">${escapeHtml(initials(video.channel))}</span><small>Channel</small></a>
          </div>
          <aside id="shortDrawer" class="short-drawer ${state.shortPanel ? "open" : ""}">${state.shortPanel ? shortDrawerContent(video) : ""}</aside>
        </div>
        <div class="short-controls">
          <button id="shortPrevious" aria-label="Previous Short" ${state.shortIndex === 0 ? "disabled" : ""}>↑</button>
          <button id="shortNext" aria-label="Next Short" ${state.shortIndex === state.shortQueue.length - 1 ? "disabled" : ""}>↓</button>
        </div>
      </div>
    </div>`;
  createYoutubePlayer("shortYoutubePlayer", video, {
    onEnded: nextShort,
    onError() {
      state.unavailableVideos.add(video.id);
      setTimeout(() => {
        if (state.shortQueue[state.shortIndex]?.id === video.id) skipUnavailableShort(video.id);
        else state.shortQueue = state.shortQueue.filter((item) => item.id !== video.id);
      }, 900);
    },
  });
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
  state.shortPanel = null;
  overlayRoot.innerHTML = "";
  render();
}

function scrollToTop() {
  requestAnimationFrame(() => window.scrollTo({ top: 0, behavior: "smooth" }));
}

function goHome(event) {
  event?.preventDefault();
  state.view = "home";
  state.activeVideo = null;
  state.query = "";
  state.quickFilter = "all";
  searchInput.value = "";
  destroyPlayer();
  sidebar.classList.remove("open");
  scrim.classList.remove("open");
  render();
  scrollToTop();
}

function selectView(view) {
  state.view = view;
  state.activeVideo = null;
  state.query = "";
  state.quickFilter = "all";
  searchInput.value = "";
  destroyPlayer();
  sidebar.classList.remove("open");
  scrim.classList.remove("open");
  render();
  scrollToTop();
}

function openCard(card) {
  if (!card) return;
  if (card.dataset.shortId) {
    const video = state.feed.items.find((item) => item.id === card.dataset.shortId);
    if (video) openShort(video);
    return;
  }
  if (card.dataset.videoId) {
    const video = state.feed.items.find((item) => item.id === card.dataset.videoId);
    if (video) openLong(video);
  }
}

function downloadJson(payload, filename) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}

function exportHistory() {
  const payload = {
    schemaVersion: 1,
    exportedAt: new Date().toISOString(),
    watched: state.watched,
    progress: state.progress,
    liked: state.liked,
  };
  downloadJson(payload, `nexafeed-history-${new Date().toISOString().slice(0, 10)}.json`);
}

function exportLiked() {
  const items = likedItems().map((item) => ({
    id: item.id,
    type: item.type,
    title: item.title,
    channel: item.channel,
    url: item.url,
    likedAt: state.liked[item.id],
  }));
  downloadJson({ schemaVersion: 1, exportedAt: new Date().toISOString(), liked: state.liked, items }, `nexafeed-liked-${new Date().toISOString().slice(0, 10)}.json`);
}

async function importHistory(file) {
  if (!file) return;
  const data = JSON.parse(await file.text());
  state.watched = { ...state.watched, ...(data.watched || {}) };
  state.progress = { ...state.progress, ...(data.progress || {}) };
  state.liked = { ...state.liked, ...(data.liked || {}) };
  localStorage.setItem(WATCHED_KEY, JSON.stringify(state.watched));
  localStorage.setItem(PROGRESS_KEY, JSON.stringify(state.progress));
  localStorage.setItem(LIKED_KEY, JSON.stringify(state.liked));
  updateHistoryCount();
  updateLikedCount();
  render();
}

async function fetchJson(url, fallback = null) {
  try {
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) throw new Error(`${response.status} ${url}`);
    return await response.json();
  } catch (error) {
    if (fallback !== null) return fallback;
    throw error;
  }
}

async function loadFeed() {
  app.innerHTML = '<div class="loading-grid"><i></i><i></i><i></i></div>';
  try {
    const stamp = Date.now();
    const [feed, details, feedSettings] = await Promise.all([
      fetchJson(`data/videos.json?time=${stamp}`),
      fetchJson(`data/video-details.json?time=${stamp}`, { items: {} }),
      fetchJson(`data/feed-settings.json?time=${stamp}`, { channels: [], keywords: [], topics: [], categories: [] }),
    ]);
    state.feed = feed;
    state.details = details;
    state.feedSettings = feedSettings;
    state.settingsDraft = null;
    state.feed.items = Array.isArray(state.feed.items)
      ? collapseRepeatedItems(state.feed.items.filter((item) => item.embedAllowed !== false))
      : [];
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

function toggleSidebar() {
  const mobile = window.matchMedia("(max-width: 860px)").matches;
  if (mobile) {
    sidebar.classList.toggle("open");
    scrim.classList.toggle("open", sidebar.classList.contains("open"));
    return;
  }
  document.body.classList.toggle("sidebar-collapsed");
}

function applySearchInput() {
  state.query = searchInput.value.trim();
  state.view = state.view === "settings" ? "home" : state.view;
  state.quickFilter = "all";
  state.activeVideo = null;
  destroyPlayer();
  render();
}

function scrollShortCarousel(direction) {
  const row = document.querySelector("#shortsCarousel");
  if (!row) return;
  const step = Math.max(320, Math.floor(row.clientWidth * 0.82));
  row.scrollBy({ left: step * direction, behavior: "smooth" });
}

document.querySelector("#menuButton").addEventListener("click", toggleSidebar);
scrim.addEventListener("click", () => {
  sidebar.classList.remove("open");
  scrim.classList.remove("open");
});
document.querySelector("#brandButton").addEventListener("click", goHome);
document.querySelector("#refreshButton").addEventListener("click", loadFeed);
document.querySelector("#themeButton").addEventListener("click", (event) => {
  state.theme = state.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = state.theme;
  localStorage.setItem(THEME_KEY, state.theme);
  event.currentTarget.textContent = state.theme === "dark" ? "☀" : "☾";
});
document.querySelector("#searchForm").addEventListener("submit", (event) => {
  event.preventDefault();
  applySearchInput();
});
searchInput.addEventListener("input", applySearchInput);
document.querySelector("#mainNav").addEventListener("click", (event) => {
  const button = event.target.closest("[data-view]");
  if (button) selectView(button.dataset.view);
});
app.addEventListener("click", (event) => {
  const viewButton = event.target.closest("[data-view]");
  if (viewButton) return selectView(viewButton.dataset.view);

  const quickFilterButton = event.target.closest("[data-quick-filter]");
  if (quickFilterButton) {
    state.quickFilter = state.quickFilter === quickFilterButton.dataset.quickFilter ? "all" : quickFilterButton.dataset.quickFilter;
    state.view = state.view === "settings" ? "home" : state.view;
    state.activeVideo = null;
    destroyPlayer();
    render();
    return;
  }

  const carouselButton = event.target.closest("[data-carousel-scroll]");
  if (carouselButton) {
    scrollShortCarousel(Number(carouselButton.dataset.direction || 1));
    return;
  }

  const saveCardButton = event.target.closest("[data-like-id]");
  if (saveCardButton) {
    event.preventDefault();
    event.stopPropagation();
    toggleLikeVideo(saveCardButton.dataset.likeId, saveCardButton);
    return;
  }

  const shortButton = event.target.closest("[data-short-id]");
  if (shortButton) {
    openCard(shortButton);
    return;
  }

  const videoButton = event.target.closest("[data-video-id]");
  if (videoButton) {
    openCard(videoButton);
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
    state.quickFilter = "all";
    searchInput.value = "";
    render();
  }
  if (event.target.closest("#resetFeedSettings")) {
    state.settingsDraft = freshSettingsDraft();
    render();
    return;
  }
  if (event.target.closest("#addChannelRow")) {
    addChannelRow();
    return;
  }
  const removeChannel = event.target.closest("[data-remove-channel]");
  if (removeChannel) {
    removeChannelRow(Number(removeChannel.dataset.removeChannel));
    return;
  }
  if (event.target.closest("#applyFeedSettings")) {
    applyFeedSettings();
    return;
  }
  if (event.target.closest("#exportHistory")) exportHistory();
  if (event.target.closest("#exportLiked")) exportLiked();
  if (event.target.closest("#importHistory")) document.querySelector("#historyFile")?.click();
  if (event.target.closest("#clearLiked")) {
    state.liked = {};
    localStorage.removeItem(LIKED_KEY);
    updateLikedCount();
    render();
  }
  if (event.target.closest("#clearHistory")) {
    state.watched = {};
    state.progress = {};
    localStorage.removeItem(WATCHED_KEY);
    localStorage.removeItem(PROGRESS_KEY);
    updateHistoryCount();
    render();
  }
});
app.addEventListener("input", (event) => {
  if (event.target.id !== "channelManagerSearch") return;
  const query = event.target.value.trim().toLowerCase();
  document.querySelectorAll(".channel-editor-row").forEach((row) => {
    const values = [...row.querySelectorAll("input")].map((input) => input.value).join(" ");
    const haystack = `${row.textContent} ${values}`.toLowerCase();
    row.hidden = Boolean(query) && !haystack.includes(query);
  });
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
  const likeButton = event.target.closest("#shortLikeButton");
  if (likeButton) {
    event.preventDefault();
    event.stopPropagation();
    toggleLikeCurrentShort(likeButton);
    return;
  }
  if (event.target.closest("#shortClose")) return closeShort();
  if (event.target.closest("#shortNext")) return nextShort();
  if (event.target.closest("#shortPrevious")) return previousShort();
  if (event.target.closest("#shortCommentsButton")) return toggleShortPanel("comments");
  if (event.target.closest("#shortShareButton")) return shareCurrentShort(event.target.closest("#shortShareButton"));
  if (event.target.closest("#shortDescriptionButton")) return toggleShortPanel("description");
  if (event.target.closest("#shortDrawerClose")) return toggleShortPanel(state.shortPanel);
});
overlayRoot.addEventListener("wheel", (event) => {
  if (event.target.closest(".short-drawer")) return;
  if (!state.shortQueue.length || wheelLocked || Math.abs(event.deltaY) < 20) return;
  wheelLocked = true;
  event.deltaY > 0 ? nextShort() : previousShort();
  setTimeout(() => { wheelLocked = false; }, 550);
}, { passive: true });
overlayRoot.addEventListener("touchstart", (event) => {
  if (event.target.closest(".short-drawer")) {
    touchStartY = null;
    return;
  }
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
