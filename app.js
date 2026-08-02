import { createTransientDirectionalHistory } from "./short-history.mjs?v=20260802-player-controls";

const app = document.querySelector("#app");
const overlayRoot = document.querySelector("#overlayRoot");
const sidebar = document.querySelector("#sidebar");
const scrim = document.querySelector("#scrim");
const searchInput = document.querySelector("#searchInput");
const updatedLabel = document.querySelector("#updatedLabel");
const historyCount = document.querySelector("#historyCount");
const likedCount = document.querySelector("#likedCount");
const ignoredCount = document.querySelector("#ignoredCount");

const WATCHED_KEY = "nexafeed-watched-v1";
const PROGRESS_KEY = "nexafeed-progress-v1";
const IGNORED_KEY = "nexafeed-ignored-v1";
const THEME_KEY = "nexafeed-theme-v1";
const AUTOPLAY_KEY = "nexafeed-autoplay-v1";
const LIKED_KEY = "nexafeed-liked-v1";
const NOTEBOOKLM_NEW_NOTEBOOK_URL = "https://notebooklm.google.com/notebook/new";
const GEMINI_CHAT_URL = "https://gemini.google.com/app";
const GEMINI_VIDEO_PROMPT = "For this video, give me a full A to Z summary with topic-by-topic transcription from beginning to end.";
const PLAYER_WHEEL_THRESHOLD = 420;
const SHORT_WHEEL_THRESHOLD = 220;
const WHEEL_RESET_MS = 420;
const WATCHED_SKIP_THRESHOLD_SECONDS = 30;
const RECENT_PLAYER_BACKTRACK_MS = 10 * 1000;
const STATE_RETENTION_BUFFER_DAYS = 1;
const DAY_MS = 24 * 60 * 60 * 1000;
const DEFAULT_STATE_RETENTION_DAYS = 8;
const VALID_VIEWS = new Set(["home", "shorts", "long", "liked", "history", "ignored", "settings"]);

function initialViewFromUrl() {
  const params = new URLSearchParams(window.location.search);
  const view = params.get("view") || window.location.hash.replace(/^#/, "");
  return VALID_VIEWS.has(view) ? view : "home";
}

const state = {
  feed: null,
  details: { items: {} },
  feedSettings: { channels: [], keywords: [], topics: [], categories: [] },
  settingsDraft: null,
  view: initialViewFromUrl(),
  query: "",
  quickFilter: "all",
  watched: readJson(WATCHED_KEY, {}),
  progress: readJson(PROGRESS_KEY, {}),
  ignored: readJson(IGNORED_KEY, {}),
  liked: readJson(LIKED_KEY, {}),
  theme: localStorage.getItem(THEME_KEY) || "dark",
  activeVideo: null,
  shortQueue: [],
  shortIndex: 0,
  shortPanel: null,
  recentPlayerHistory: [],
  shortHistory: createTransientDirectionalHistory({ ttlMs: RECENT_PLAYER_BACKTRACK_MS, maxEntries: 8 }),
  unavailableVideos: new Set(),
  autoplay: localStorage.getItem(AUTOPLAY_KEY) !== "false",
};

let player = null;
let progressTimer = null;
let shortWheelLocked = false;
let shortWheelDelta = 0;
let shortWheelResetTimer = null;
let shortHistoryExpiryTimer = null;
let playerWheelLocked = false;
let playerWheelDelta = 0;
let playerWheelResetTimer = null;
let touchStartY = null;
let floatingPopup = null;
let floatingPipWindow = null;
let floatingPlayer = null;
let floatingProgressTimer = null;

document.documentElement.dataset.theme = state.theme;
document.querySelector("#themeButton").textContent = state.theme === "dark" ? "☀" : "☾";
updateHistoryCount();
updateLikedCount();
updateIgnoredCount();

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

function isIgnored(id) {
  return Boolean(state.ignored[id]) && !isWatched(id);
}

function isHiddenFromPlayback(id) {
  return isWatched(id) || isIgnored(id);
}

function isLiked(id) {
  return Boolean(state.liked[id]);
}

function saveWatched() {
  localStorage.setItem(WATCHED_KEY, JSON.stringify(state.watched));
  updateHistoryCount();
}

function saveLiked() {
  localStorage.setItem(LIKED_KEY, JSON.stringify(state.liked));
  updateLikedCount();
}

function saveIgnored() {
  localStorage.setItem(IGNORED_KEY, JSON.stringify(state.ignored));
  updateIgnoredCount();
}

function playbackStateTimestamp(value) {
  if (typeof value === "number") return value;
  if (typeof value === "string") return Number(value) || 0;
  return Number(value?.watchedAt || value?.ignoredAt || value?.updatedAt || value?.createdAt || 0);
}

function feedStateRetentionMs(feed = state.feed) {
  const fallback = DEFAULT_STATE_RETENTION_DAYS * DAY_MS;
  const items = Array.isArray(feed?.items) ? feed.items : [];
  const reference = new Date(feed?.updatedAt || Date.now()).getTime();
  if (!items.length || !Number.isFinite(reference)) return fallback;
  const oldest = items.reduce((minimum, item) => {
    const stamp = new Date(item.publishedAt || item.firstSeenAt || 0).getTime();
    if (!Number.isFinite(stamp) || stamp <= 0) return minimum;
    return Math.min(minimum, stamp);
  }, reference);
  const feedWindowMs = Math.max(0, reference - oldest);
  return Math.max(STATE_RETENTION_BUFFER_DAYS * DAY_MS, feedWindowMs + STATE_RETENTION_BUFFER_DAYS * DAY_MS);
}

function currentFeedVideoIds(feed = state.feed) {
  const items = Array.isArray(feed?.items) ? feed.items : [];
  return new Set(items.map((item) => item.id).filter(Boolean));
}

function pruneTimedStateMap(map, retentionMs, now = Date.now(), protectedIds = new Set()) {
  let changed = false;
  Object.entries(map || {}).forEach(([id, value]) => {
    // A watched/ignored active feed ID is never pruned while it is still present in data/videos.json.
    if (protectedIds.has(id)) return;
    const stamp = playbackStateTimestamp(value);
    if (!stamp || now - stamp > retentionMs) {
      delete map[id];
      changed = true;
    }
  });
  return changed;
}

function prunePlaybackStateRetention() {
  const retentionMs = feedStateRetentionMs();
  const now = Date.now();
  const protectedIds = currentFeedVideoIds();
  const watchedChanged = pruneTimedStateMap(state.watched, retentionMs, now, protectedIds);
  let ignoredChanged = pruneTimedStateMap(state.ignored, retentionMs, now, protectedIds);
  Object.keys(state.ignored).forEach((id) => {
    if (isWatched(id)) {
      delete state.ignored[id];
      ignoredChanged = true;
    }
  });
  const progressChanged = pruneTimedStateMap(state.progress, retentionMs, now, protectedIds);
  if (watchedChanged) saveWatched();
  if (ignoredChanged) saveIgnored();
  if (progressChanged) localStorage.setItem(PROGRESS_KEY, JSON.stringify(state.progress));
  return { retentionMs, watchedChanged, ignoredChanged, progressChanged };
}

function progressFor(id) {
  const value = state.progress[id];
  if (typeof value === "number") return Math.max(0, Math.min(1, value));
  return Math.max(0, Math.min(1, Number(value?.ratio || 0)));
}

function videoForPlaybackState(videoId) {
  return (state.activeVideo?.id === videoId && state.activeVideo)
    || state.shortQueue.find((item) => item.id === videoId)
    || state.feed?.items?.find((item) => item.id === videoId)
    || { id: videoId, type: "long" };
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
  const video = videoForPlaybackState(id);
  const watchedSeconds = Math.floor(seconds);
  if (watchedSeconds >= watchedThresholdSeconds(video, duration)) markWatched(id);
}

function watchedSecondsFor(videoId) {
  let currentSeconds = 0;
  try {
    const current = player?.getCurrentTime?.();
    if (Number.isFinite(current) && current >= 0) currentSeconds = current;
  } catch {
    // Fall back to saved progress when the iframe is between states.
  }
  const saved = state.progress[videoId];
  const persisted = readJson(PROGRESS_KEY, {})[videoId];
  const savedSeconds = Number(saved?.seconds || 0);
  const persistedSeconds = Number(persisted?.seconds || 0);
  return Math.max(currentSeconds, savedSeconds, persistedSeconds);
}

function markWatched(id) {
  if (!id) return;
  if (!state.watched[id]) {
    state.watched[id] = Date.now();
    saveWatched();
  }
  if (state.ignored[id]) {
    delete state.ignored[id];
    saveIgnored();
  }
  const current = state.progress[id] || {};
  state.progress[id] = { ...current, ratio: 1, updatedAt: Date.now() };
  localStorage.setItem(PROGRESS_KEY, JSON.stringify(state.progress));
}

function markIgnored(id, reason = "manual-skip") {
  if (!id || isWatched(id)) return false;
  state.ignored[id] = Date.now();
  const current = state.progress[id] || {};
  state.progress[id] = { ...current, ignoredAt: state.ignored[id], ignoredReason: reason, updatedAt: Date.now() };
  localStorage.setItem(PROGRESS_KEY, JSON.stringify(state.progress));
  saveIgnored();
  return true;
}

function parseDurationSeconds(value) {
  if (typeof value !== "string" || !value.includes(":")) return 0;
  const parts = value.split(":").map((part) => Number(part));
  if (parts.some((part) => !Number.isFinite(part) || part < 0)) return 0;
  return parts.reduce((total, part) => total * 60 + part, 0);
}

function durationSecondsFor(video, fallbackDuration = 0) {
  const direct = Number(video?.durationSeconds || detailFor(video?.id)?.durationSeconds || 0);
  if (direct > 0) return direct;
  const progressDuration = Number(state.progress[video?.id]?.duration || readJson(PROGRESS_KEY, {})[video?.id]?.duration || 0);
  if (progressDuration > 0) return progressDuration;
  const parsed = parseDurationSeconds(video?.duration);
  return parsed > 0 ? parsed : Number(fallbackDuration || 0);
}

function watchedThresholdSeconds(video, fallbackDuration = 0) {
  const duration = durationSecondsFor(video, fallbackDuration);
  if (video?.type === "short" && duration > 0) {
    return Math.max(1, Math.min(WATCHED_SKIP_THRESHOLD_SECONDS, Math.ceil(duration / 2)));
  }
  return WATCHED_SKIP_THRESHOLD_SECONDS;
}

function videoQualifiesAsWatched(video) {
  if (!video?.id) return false;
  if (isWatched(video.id)) return true;
  return watchedSecondsFor(video.id) >= watchedThresholdSeconds(video);
}

function finalizeVideoBeforeLeaving(video, { reason = "manual-skip" } = {}) {
  if (!video?.id) return "none";
  if (isWatched(video.id)) return "watched";
  if (videoQualifiesAsWatched(video)) {
    markWatched(video.id);
    return "watched";
  }
  markIgnored(video.id, reason);
  return "ignored";
}

function toggleCurrentPlayback() {
  try {
    const playing = player?.getPlayerState?.() === window.YT?.PlayerState?.PLAYING;
    if (playing) player.pauseVideo?.();
    else player?.playVideo?.();
  } catch {
    // The iframe may still be booting. Wheel navigation remains available.
  }
}

function verticalWheelIntent(event) {
  return Math.abs(event.deltaY) >= 8 && Math.abs(event.deltaY) >= Math.abs(event.deltaX || 0);
}

function bindWheelCaptureOverlay(kind, handler) {
  document.querySelectorAll(`[data-wheel-capture="${kind}"]`).forEach((overlay) => {
    overlay.addEventListener("wheel", handler, { passive: false });
  });
}

function handlePlayerWheel(event) {
  const overCaptureOverlay = event.target.closest("[data-wheel-capture]");
  if (!state.activeVideo || (!overCaptureOverlay && !event.target.closest(".player-main")) || event.target.closest("button:not([data-wheel-capture]), a, input, textarea, select")) return;
  if (!verticalWheelIntent(event)) return;
  event.preventDefault();
  event.stopPropagation();
  if (playerWheelLocked) return;
  playerWheelDelta += event.deltaY;
  clearTimeout(playerWheelResetTimer);
  playerWheelResetTimer = setTimeout(() => { playerWheelDelta = 0; }, WHEEL_RESET_MS);
  if (Math.abs(playerWheelDelta) < PLAYER_WHEEL_THRESHOLD) return;
  const direction = playerWheelDelta > 0 ? 1 : -1;
  playerWheelDelta = 0;
  playerWheelLocked = true;
  navigatePlayer(direction);
  setTimeout(() => { playerWheelLocked = false; }, 700);
}

function handleShortWheel(event) {
  const overCaptureOverlay = event.target.closest("[data-wheel-capture]");
  if (!overCaptureOverlay && event.target.closest(".short-drawer")) return;
  if (!state.shortQueue.length || !verticalWheelIntent(event)) return;
  event.preventDefault();
  event.stopPropagation();
  if (shortWheelLocked) return;
  shortWheelDelta += event.deltaY;
  clearTimeout(shortWheelResetTimer);
  shortWheelResetTimer = setTimeout(() => { shortWheelDelta = 0; }, WHEEL_RESET_MS);
  if (Math.abs(shortWheelDelta) < SHORT_WHEEL_THRESHOLD) return;
  shortWheelLocked = true;
  shortWheelDelta > 0 ? nextShort() : previousShort();
  shortWheelDelta = 0;
  setTimeout(() => { shortWheelLocked = false; }, 550);
}

function updateHistoryCount() {
  historyCount.textContent = Object.keys(state.watched).length;
}

function updateLikedCount() {
  likedCount.textContent = Object.keys(state.liked).length;
}

function updateIgnoredCount() {
  if (ignoredCount) ignoredCount.textContent = Object.keys(state.ignored).filter((id) => !isWatched(id)).length;
}

function isFresh(video) {
  if (isHiddenFromPlayback(video.id)) return false;
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
  if (isIgnored(video.id)) return '<span class="ignored-pill">⊘ Ignored</span>';
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

function floatButton(video, context = "player") {
  return `<button class="action-button compact float-button ${context}-float" type="button" data-float-id="${escapeHtml(video.id)}" aria-label="Open ${escapeHtml(video.title)} in floating player">⧉ Float</button>`;
}

function notebookLmButton(video, context = "player") {
  return `
    <button class="action-button compact notebooklm-button ${context}-notebooklm" type="button" data-notebooklm-id="${escapeHtml(video.id)}" aria-label="Chat with ${escapeHtml(video.title)} in NotebookLM">
      <span class="notebooklm-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24" focusable="false">
          <path d="M6.2 3.7h8.9l3 3v13.6H6.2z" />
          <path d="M15.1 3.7v3h3" />
          <path d="M8.7 9.5h6.6M8.7 12.4h6.6M8.7 15.3h4.7" />
          <path class="notebooklm-spark" d="M18.4 11.2l.5 1.3 1.3.5-1.3.5-.5 1.3-.5-1.3-1.3-.5 1.3-.5z" />
        </svg>
      </span>
      <span data-action-label>Chat With NBLM</span>
    </button>`;
}

function geminiButton(video, context = "player") {
  const shortButton = context === "short";
  const id = shortButton ? ' id="shortGeminiButton"' : "";
  const classes = shortButton ? "gemini-button short-gemini" : `action-button compact gemini-button ${context}-gemini`;
  const label = shortButton ? "Gemini" : "Ask Gemini";
  const labelTag = shortButton ? "small" : "span";
  return `
    <button${id} class="${classes}" type="button" data-gemini-id="${escapeHtml(video.id)}" aria-label="Ask Gemini for a full A to Z summary of ${escapeHtml(video.title)}">
      <span class="gemini-icon" aria-hidden="true">AI</span>
      <${labelTag} data-action-label>${label}</${labelTag}>
    </button>`;
}

function playerNavButton(direction, video) {
  const label = direction > 0 ? "Next" : "Previous";
  const key = direction > 0 ? "→" : "←";
  const disabled = video ? "" : "disabled";
  const title = video
    ? `${label}: ${video.title}`
    : `${label} video unavailable`;
  return `<button class="action-button compact player-nav-button" type="button" data-player-nav="${direction}" ${disabled} title="${escapeHtml(title)}" aria-label="${escapeHtml(title)}">${direction > 0 ? `${label} ${key}` : `${key} ${label}`}</button>`;
}

function videoWatchUrl(video) {
  return video?.url || `https://www.youtube.com/watch?v=${video?.id || ""}`;
}

function notebookLmImportUrl(video) {
  const target = new URL(NOTEBOOKLM_NEW_NOTEBOOK_URL);
  target.searchParams.set("source", "youtube");
  target.searchParams.set("url", videoWatchUrl(video));
  target.searchParams.set("title", video?.title || "YouTube video");
  return target.toString();
}

function geminiPromptForVideo(video) {
  return [
    GEMINI_VIDEO_PROMPT,
    "",
    `Video title: ${video?.title || "YouTube video"}`,
    `Channel: ${video?.channel || "Unknown channel"}`,
    `Video URL: ${videoWatchUrl(video)}`,
  ].join("\n");
}

function geminiChatUrl(prompt) {
  const target = new URL(GEMINI_CHAT_URL);
  target.searchParams.set("q", prompt);
  target.searchParams.set("prompt", prompt);
  return target.toString();
}

async function copyText(value) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value);
    return true;
  }
  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  document.body.appendChild(textarea);
  textarea.select();
  const copied = document.execCommand("copy");
  textarea.remove();
  if (!copied) throw new Error("Copy failed");
  return true;
}

function temporaryActionLabel(button, text) {
  const label = button?.querySelector("[data-action-label]");
  if (!label) return;
  const original = label.dataset.originalLabel || label.textContent;
  label.dataset.originalLabel = original;
  label.textContent = text;
  setTimeout(() => { label.textContent = original; }, 1800);
}

async function openNotebookLm(video, button) {
  if (!video) return;
  const sourceUrl = videoWatchUrl(video);
  const notebookUrl = notebookLmImportUrl(video);
  const opened = window.open(notebookUrl, "_blank");
  if (opened) opened.opener = null;
  try {
    await copyText(sourceUrl);
    temporaryActionLabel(button, "URL copied");
  } catch {
    temporaryActionLabel(button, "Paste URL");
    window.alert(`NotebookLM opened. If the YouTube source is not imported automatically, paste this URL in Add source > YouTube:\n\n${sourceUrl}`);
  }
  if (!opened) window.location.href = notebookUrl;
}

async function openGemini(video, button) {
  if (!video) return;
  const prompt = geminiPromptForVideo(video);
  const opened = window.open(geminiChatUrl(prompt), "_blank");
  if (opened) opened.opener = null;
  try {
    await copyText(prompt);
    temporaryActionLabel(button, "Gemini opened");
  } catch {
    temporaryActionLabel(button, "Paste prompt");
    window.alert(`Gemini opened. If the prompt is not filled automatically, paste this copied-style prompt into Gemini:\n\n${prompt}`);
  }
  if (!opened) window.location.href = geminiChatUrl(prompt);
}

function floatingSize(video) {
  return video.type === "short"
    ? { width: 390, height: 700 }
    : { width: 760, height: 470 };
}

function youtubeOrigin() {
  return window.location.origin && window.location.origin !== "null"
    ? window.location.origin
    : "https://developerjillur.github.io";
}

function youtubeWidgetReferrer() {
  return window.location.href.split("#")[0];
}

function youtubeEmbedSrc(video, autoplay = true) {
  const params = new URLSearchParams({
    autoplay: autoplay ? "1" : "0",
    rel: "0",
    playsinline: "1",
    modestbranding: "1",
    enablejsapi: "1",
    origin: youtubeOrigin(),
    widget_referrer: youtubeWidgetReferrer(),
  });
  const saved = state.progress[video.id];
  if (saved?.seconds > 0 && Number(saved.ratio || 0) < 1) params.set("start", String(Math.floor(saved.seconds)));
  return `https://www.youtube.com/embed/${encodeURIComponent(video.id)}?${params.toString()}`;
}

function floatingPopupUrl(video) {
  const popupUrl = new URL("float.html", window.location.href);
  const params = new URLSearchParams({
    v: "20260802-player-controls",
    id: video.id,
    title: String(video.title || "YourTube video").slice(0, 180),
    type: video.type === "short" ? "short" : "long",
    channel: String(video.channel || "").slice(0, 100),
    url: video.url || `https://www.youtube.com/watch?v=${video.id}`,
  });
  const saved = state.progress[video.id];
  if (saved?.seconds > 0 && Number(saved.ratio || 0) < 1) params.set("start", String(Math.floor(saved.seconds)));
  popupUrl.search = params.toString();
  return popupUrl.toString();
}

function floatingPlayerCss() {
  return `
    :root { color-scheme: dark; }
    * { box-sizing: border-box; }
    body { margin: 0; overflow: hidden; background: #05070c; color: #fff; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    .float-window { display: grid; grid-template-rows: 42px minmax(0, 1fr); width: 100vw; height: 100vh; background: #05070c; }
    .float-titlebar { display: flex; align-items: center; justify-content: space-between; gap: 12px; min-width: 0; padding: 0 10px 0 12px; border-bottom: 1px solid rgba(255,255,255,.12); background: linear-gradient(135deg, rgba(17,24,39,.96), rgba(8,11,18,.96)); }
    .float-brand { display: flex; min-width: 0; align-items: center; gap: 9px; font-size: 12px; font-weight: 750; }
    .float-dot { display: grid; width: 18px; height: 18px; place-items: center; border-radius: 50%; background: #ff0033; font-size: 9px; }
    .float-title { overflow: hidden; color: rgba(255,255,255,.82); text-overflow: ellipsis; white-space: nowrap; }
    .float-actions { display: flex; align-items: center; gap: 7px; }
    .float-actions button, .float-actions a { display: grid; width: 28px; height: 28px; place-items: center; cursor: pointer; border: 1px solid rgba(255,255,255,.16); border-radius: 8px; background: rgba(255,255,255,.09); color: #fff; font-size: 15px; text-decoration: none; }
    .float-actions button:hover, .float-actions a:hover { background: rgba(255,255,255,.18); }
    .float-frame { overflow: hidden; background: #000; }
    .float-frame > div, .float-frame iframe { display: block; width: 100%; height: 100%; border: 0; }
  `;
}

function floatingPlayerFrame(video, apiMount = false) {
  if (apiMount) return '<div class="float-frame"><div id="floatingYoutubePlayer"></div></div>';
  return `<div class="float-frame"><iframe src="${escapeHtml(youtubeEmbedSrc(video))}" title="${escapeHtml(video.title)}" allow="autoplay; encrypted-media; picture-in-picture" allowfullscreen referrerpolicy="strict-origin-when-cross-origin"></iframe></div>`;
}

function floatingPlayerBody(video, { draggable = false, apiMount = false } = {}) {
  return `
    <section class="float-window ${video.type === "short" ? "short-float" : "long-float"}" id="inlineFloatingPlayer" aria-label="Floating player">
      <header class="float-titlebar" ${draggable ? 'data-float-drag="true"' : ""}>
        <div class="float-brand"><span class="float-dot">▶</span><span>${video.type === "short" ? "YourTube Short" : "YourTube Float"}</span><small class="float-title">${escapeHtml(video.title)}</small></div>
        <div class="float-actions">
          <a class="float-youtube" href="${escapeHtml(video.url || `https://www.youtube.com/watch?v=${video.id}`)}" target="_blank" rel="noopener" aria-label="Open on YouTube">↗</a>
          <button type="button" data-close-float aria-label="Close floating player">×</button>
        </div>
      </header>
      ${floatingPlayerFrame(video, apiMount)}
    </section>`;
}

function pauseInlinePlayer() {
  try { player?.pauseVideo?.(); } catch { /* iframe may not be ready */ }
}

function renderFloatingPlayerError(elementId, video) {
  const node = document.getElementById(elementId);
  if (!node) return;
  node.outerHTML = `
    <div id="${escapeHtml(elementId)}" class="player-error floating-error">
      <strong>This floating player could not start.</strong>
      <span>YouTube refused this embed configuration. The main player may still work.</span>
      <a href="${escapeHtml(video.url || `https://www.youtube.com/watch?v=${video.id}`)}" target="_blank" rel="noopener">Watch video on YouTube</a>
    </div>`;
}

function destroyFloatingPlayer(clearRoot = true) {
  if (floatingProgressTimer) clearInterval(floatingProgressTimer);
  floatingProgressTimer = null;
  if (floatingPlayer?.destroy) {
    try { floatingPlayer.destroy(); } catch { /* already removed */ }
  }
  floatingPlayer = null;
  if (clearRoot) {
    const root = document.querySelector("#floatingRoot");
    if (root) root.innerHTML = "";
  }
}

async function createFloatingYoutubePlayer(elementId, video) {
  destroyFloatingPlayer(false);
  try {
    const YT = await waitForYoutube();
    const playerVars = {
      autoplay: 1,
      rel: 0,
      playsinline: 1,
      enablejsapi: 1,
      modestbranding: 1,
      origin: youtubeOrigin(),
      widget_referrer: youtubeWidgetReferrer(),
    };
    const saved = state.progress[video.id];
    if (saved?.seconds > 0 && Number(saved.ratio || 0) < 1) playerVars.start = Math.floor(saved.seconds);
    floatingPlayer = new YT.Player(elementId, {
      videoId: video.id,
      width: "100%",
      height: "100%",
      playerVars,
      events: {
        onReady(event) {
          pauseInlinePlayer();
          event.target.playVideo();
          floatingProgressTimer = setInterval(() => {
            try {
              const duration = event.target.getDuration();
              const current = event.target.getCurrentTime();
              if (duration > 0) saveProgress(video.id, current, duration);
            } catch {
              // The floating iframe may be closing or switching videos.
            }
          }, 1500);
        },
        onStateChange(event) {
          if (event.data === YT.PlayerState.ENDED) markWatched(video.id);
        },
        onError() {
          if (floatingProgressTimer) clearInterval(floatingProgressTimer);
          floatingProgressTimer = null;
          floatingPlayer = null;
          renderFloatingPlayerError(elementId, video);
        },
      },
    });
  } catch {
    const node = document.getElementById(elementId);
    if (node) {
      node.innerHTML = `<iframe src="${escapeHtml(youtubeEmbedSrc(video))}" allow="autoplay; encrypted-media; picture-in-picture" allowfullscreen referrerpolicy="strict-origin-when-cross-origin" title="${escapeHtml(video.title)}"></iframe>`;
    }
  }
}

async function openDocumentPictureInPicture(video) {
  if (!window.documentPictureInPicture?.requestWindow) return false;
  // YouTube raw iframes inside Document Picture-in-Picture can render as Error 153
  // because the PiP document has an unreliable referrer. Keep this capability
  // detectable, but use the real same-origin popup page / in-page API player instead.
  void video;
  return false;
}

function openPopupFloatingPlayer(video) {
  const size = floatingSize(video);
  const left = Math.max(0, Math.round((window.screenX || 0) + (window.outerWidth - size.width) / 2));
  const top = Math.max(0, Math.round((window.screenY || 0) + 90));
  const features = `popup=yes,width=${size.width},height=${size.height},left=${left},top=${top},resizable=yes,scrollbars=no`;
  const popup = window.open(floatingPopupUrl(video), "nexafeedFloatingPlayer", features);
  if (!popup) return false;
  floatingPopup = popup;
  popup.focus();
  pauseInlinePlayer();
  return true;
}

function ensureFloatingRoot() {
  let root = document.querySelector("#floatingRoot");
  if (!root) {
    root = document.createElement("div");
    root.id = "floatingRoot";
    document.body.appendChild(root);
  }
  return root;
}

function closeInlineFloatingPlayer() {
  destroyFloatingPlayer();
}

function startInlineFloatDrag(event) {
  const panel = event.target.closest("#inlineFloatingPlayer");
  if (!panel || event.target.closest("button, a")) return;
  event.preventDefault();
  const rect = panel.getBoundingClientRect();
  const shiftX = event.clientX - rect.left;
  const shiftY = event.clientY - rect.top;
  const move = (moveEvent) => {
    const maxLeft = Math.max(0, window.innerWidth - panel.offsetWidth);
    const maxTop = Math.max(0, window.innerHeight - panel.offsetHeight);
    panel.style.left = `${Math.max(0, Math.min(maxLeft, moveEvent.clientX - shiftX))}px`;
    panel.style.top = `${Math.max(0, Math.min(maxTop, moveEvent.clientY - shiftY))}px`;
    panel.style.right = "auto";
    panel.style.bottom = "auto";
  };
  const stop = () => {
    document.removeEventListener("pointermove", move);
    document.removeEventListener("pointerup", stop);
  };
  document.addEventListener("pointermove", move);
  document.addEventListener("pointerup", stop, { once: true });
}

function openInlineFloatingPlayer(video) {
  destroyFloatingPlayer(false);
  const root = ensureFloatingRoot();
  root.innerHTML = floatingPlayerBody(video, { draggable: true, apiMount: true });
  const panel = root.querySelector("#inlineFloatingPlayer");
  panel?.classList.add("in-page-float");
  panel?.querySelector("[data-float-drag]")?.addEventListener("pointerdown", startInlineFloatDrag);
  panel?.querySelector("[data-close-float]")?.addEventListener("click", closeInlineFloatingPlayer);
  createFloatingYoutubePlayer("floatingYoutubePlayer", video);
}

async function openFloatingVideo(video) {
  if (!video) return;
  // Prefer a real same-origin popup page. The earlier about:blank/Document-PiP
  // raw iframe path can trigger YouTube Error 153 even when the main API player works.
  if (openPopupFloatingPlayer(video)) return;
  openInlineFloatingPlayer(video);
}

function videoCard(video) {
  const watched = isWatched(video.id);
  const ignored = isIgnored(video.id);
  return `
    <article class="video-card ${watched ? "watched-card" : ""} ${ignored ? "ignored-card" : ""}">
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
  const ignored = isIgnored(video.id);
  return `
    <article class="short-card ${watched ? "watched-card" : ""} ${ignored ? "ignored-card" : ""}">
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
    ["ignored", "Ignored"],
  ];
  const feedItems = state.feed?.items || [];
  const unwatched = feedItems.filter((item) => !isWatched(item.id) && !isIgnored(item.id)).length;
  const ignored = feedItems.filter((item) => isIgnored(item.id)).length;
  const fresh = feedItems.filter(isFresh).length;
  return `
    <div class="toolbar">
      <div class="chips">
        ${options.map(([id, label]) => `<button class="chip ${state.view === id && state.quickFilter === "all" ? "active" : ""}" data-view="${id}">${label}</button>`).join("")}
        <button class="chip count-chip unwatched-count ${state.quickFilter === "unwatched" ? "active" : ""}" data-quick-filter="unwatched">${unwatched} unwatched</button>
        <button class="chip count-chip ignored-count ${state.view === "ignored" ? "active" : ""}" data-view="ignored">${ignored} ignored</button>
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

function ignoredItems() {
  return collapseRepeatedItems((state.feed?.items || []).filter((item) => isIgnored(item.id)));
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

function ignoredTools() {
  if (state.view !== "ignored") return "";
  const count = ignoredItems().length;
  return `
    <article class="settings-card history-tools ignored-tools">
      <div>
        <h2>Ignored videos saved locally</h2>
        <p>${count ? `${count} ignored item${count === 1 ? "" : "s"}. Ignored videos stay hidden from Home, Shorts, Long videos, and Up Next until you clear this list.` : "Skipped videos that do not meet the watch threshold will appear here."}</p>
        <small>Watched and ignored records are kept for the current feed window plus 1 extra day, then pruned locally.</small>
      </div>
      <div class="settings-actions">
        <button id="clearIgnored" class="danger" type="button" ${count ? "" : "disabled"}>Clear ignored</button>
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

function repositoryIssuesNewUrl() {
  const fallback = "https://github.com/developerjillur/nexafeed";
  const raw = String(state.feed?.repositoryUrl || fallback).trim().replace(/\/+$/, "");
  try {
    const url = new URL(raw);
    if (url.hostname !== "github.com") throw new Error("Only GitHub repository URLs are supported");
    const [owner, repo] = url.pathname.split("/").filter(Boolean);
    if (!owner || !repo) throw new Error("Repository URL must include owner and repo");
    return new URL(`https://github.com/${owner}/${repo.replace(/\.git$/, "")}/issues/new`);
  } catch {
    return new URL(`${fallback}/issues/new`);
  }
}

async function applyFeedSettings() {
  const popup = window.open("about:blank", "_blank");
  if (popup) popup.opener = null;
  try {
    const draft = validateSettingsDraft(readSettingsDraftFromDom());
    state.settingsDraft = draft;
    const token = await gzipBase64Url(JSON.stringify(draft));
    const body = [
      "This owner-authorized issue applies the Feed Settings currently shown in YourTube.",
      "Review the summary below, then submit without editing the hidden marker.",
      "",
      "## Change summary",
      ...settingsChangeSummary(draft).map((line) => `- ${line}`),
      "",
      "GitHub Actions will validate, commit, deploy, and close this issue.",
      "",
      `<!-- NEXAFEED_CONFIG_V1:GZIP_BASE64URL:${token} -->`,
    ].join("\n");
    const issueUrl = repositoryIssuesNewUrl();
    issueUrl.searchParams.set("title", "[YourTube Config] Apply feed settings");
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
        <p>History and ignored videos remain private to this browser. Export JSON to move watched/progress/ignored state to another browser or device.</p>
        <small>Watched and ignored records are kept for the current feed window plus 1 extra day, so refreshed videos do not return as new while they are still in the feed.</small>
        <div class="settings-actions">
          <button id="exportHistory" class="action-button">Export history JSON</button>
          <button id="importHistory" class="action-button">Import history JSON</button>
          <button id="clearHistory" class="danger">Clear history</button>
          <button id="clearIgnored" class="danger">Clear ignored</button>
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
      .sort((a, b) => playbackStateTimestamp(state.watched[b.id]) - playbackStateTimestamp(state.watched[a.id]));
  } else if (state.view === "liked") {
    items = items
      .filter((item) => isLiked(item.id))
      .sort((a, b) => state.liked[b.id] - state.liked[a.id]);
  } else if (state.view === "ignored") {
    items = items
      .filter((item) => isIgnored(item.id))
      .sort((a, b) => playbackStateTimestamp(state.ignored[b.id]) - playbackStateTimestamp(state.ignored[a.id]));
  } else {
    items = items.filter((item) => !isWatched(item.id) && !isIgnored(item.id));
  }
  if (state.quickFilter === "unwatched") items = items.filter((item) => !isWatched(item.id) && !isIgnored(item.id));
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
        : state.view === "ignored"
          ? "No ignored videos yet"
        : searchEmpty ? "No matching videos" : "You're all caught up";
    const emptyDescription = state.view === "history"
      ? "Videos appear here after you watch enough of them, finish them, or mark them watched."
      : state.view === "liked"
        ? "Tap the heart on any Short to save it here. Liked videos are saved locally in this browser."
        : state.view === "ignored"
          ? "Skip a running video before the watch threshold and it will stay hidden here until the feed-window retention expires or you clear ignored."
        : searchEmpty
          ? "Try a channel name, title keyword, topic, or category. Search updates live as you type."
          : "Watched and ignored videos stay hidden. New uploads will arrive on the next hourly refresh.";
    return toolbar() + likedTools() + ignoredTools() + emptyState(
      emptyTitle,
      emptyDescription,
    );
  }

  const shorts = items.filter((item) => item.type === "short");
  const longVideos = items.filter((item) => item.type === "long");
  const shortsTitle = state.view === "history" ? "Watched Shorts" : state.view === "liked" ? "Liked Shorts" : state.view === "ignored" ? "Ignored Shorts" : "Latest Shorts";
  const longEyebrow = state.view === "history" ? "Previously played" : state.view === "liked" ? "Saved locally" : state.view === "ignored" ? "Skipped manually" : "Priority channels first";
  const longTitle = state.view === "history" ? "Watch history" : state.view === "liked" ? "Liked long videos" : state.view === "ignored" ? "Ignored long videos" : state.query ? "Search results" : "Latest long videos";
  const shortsSection = shorts.length && state.view !== "long"
    ? `<section class="section">
        <div class="section-head">
          <div class="section-title"><span class="section-icon">ϟ</span><div><p class="eyebrow">${state.view === "liked" ? "Saved Shorts" : state.view === "ignored" ? "Skipped Shorts" : "Vertical playlist"}</p><h1>${shortsTitle}</h1></div></div>
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
  return toolbar() + likedTools() + ignoredTools() + shortsSection + longSection;
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
  const longs = playlistLongVideos(currentId);
  const index = longs.findIndex((item) => item.id === currentId);
  const candidates = index >= 0 ? longs.slice(index + 1) : longs;
  return candidates.filter((item) => item.id !== currentId);
}

function playableLongVideos() {
  return state.feed?.items.filter((item) => item.type === "long" && item.embedAllowed !== false && !state.unavailableVideos.has(item.id)) || [];
}

function pruneRecentPlayerHistory(now = Date.now()) {
  state.recentPlayerHistory = state.recentPlayerHistory.filter((recent) => (
    recent.stamp && now - recent.stamp <= RECENT_PLAYER_BACKTRACK_MS
  ));
}

function rememberRecentPlayerVideo(video) {
  if (!video?.id || video.type !== "long") return;
  pruneRecentPlayerHistory();
  state.recentPlayerHistory = state.recentPlayerHistory.filter((recent) => recent.id !== video.id);
  state.recentPlayerHistory.unshift({ id: video.id, stamp: Date.now() });
  state.recentPlayerHistory = state.recentPlayerHistory.slice(0, 8);
}

function recentPlayerBacktrackVideo(currentId) {
  pruneRecentPlayerHistory();
  const recent = state.recentPlayerHistory.find((recent) => (
    recent.id !== currentId && recent.stamp && Date.now() - recent.stamp <= RECENT_PLAYER_BACKTRACK_MS
  ));
  if (!recent) return null;
  return playableLongVideos().find((item) => item.id === recent.id) || null;
}

function playlistLongVideos(currentId) {
  return playableLongVideos().filter((item) => item.id === currentId || (!isWatched(item.id) && !isIgnored(item.id)));
}

function playerNeighbor(currentId, direction) {
  const recentBacktrack = direction < 0 ? recentPlayerBacktrackVideo(currentId) : null;
  if (recentBacktrack) return recentBacktrack;
  const longs = playlistLongVideos(currentId);
  const index = longs.findIndex((item) => item.id === currentId);
  if (direction > 0) return queueFor(currentId)[0] || null;
  return index > 0 ? longs[index - 1] : null;
}

function navigatePlayer(direction) {
  if (!state.activeVideo) return;
  const target = playerNeighbor(state.activeVideo.id, direction);
  if (target) {
    rememberRecentPlayerVideo(state.activeVideo);
    finalizeVideoBeforeLeaving(state.activeVideo, { reason: "player-nav" });
    openLong(target, { finalizeCurrent: false });
  }
}

function isTypingTarget(target) {
  return Boolean(target?.closest?.("input, textarea, select, [contenteditable='true']"));
}

function renderPlayer() {
  const video = state.activeVideo;
  const queue = queueFor(video.id);
  const previousVideo = playerNeighbor(video.id, -1);
  const nextVideo = playerNeighbor(video.id, 1);
  app.innerHTML = `
    <section class="player-layout">
      <div class="player-main">
        <div class="player-frame">
          <div id="youtubePlayer"></div>
          <button class="wheel-capture-overlay" type="button" data-wheel-capture="long" data-wheel-side="left" tabindex="-1" aria-label="Scroll on the left video edge to switch long videos. Click to pause or resume."></button>
          <button class="wheel-capture-overlay" type="button" data-wheel-capture="long" data-wheel-side="right" tabindex="-1" aria-label="Scroll on the right video edge to switch long videos. Click to pause or resume."></button>
        </div>
        <div class="player-heading">
          <div>${sourceBadge(video.source)}<h1>${escapeHtml(video.title)}</h1></div>
          <button class="icon-button close-player" id="closePlayer" aria-label="Close player">×</button>
        </div>
        <div class="author-row">
          <div class="author-info"><span class="avatar">${escapeHtml(initials(video.channel))}</span><div><strong>${escapeHtml(video.channel)}</strong><small>${escapeHtml(video.handle || "")}</small></div></div>
          <div class="player-actions">
            <span class="video-stats">${escapeHtml(video.views || "Views unavailable")} • ${escapeHtml(timeAgo(video.publishedAt))}</span>
            <span class="player-nav-actions" aria-label="Video navigation">
              ${playerNavButton(-1, previousVideo)}
              ${playerNavButton(1, nextVideo)}
            </span>
            ${saveButton(video, "player")}
            ${floatButton(video, "player")}
            ${geminiButton(video, "player")}
            ${notebookLmButton(video, "player")}
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
  bindWheelCaptureOverlay("long", handlePlayerWheel);
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
      playerVars: {
        autoplay: 1,
        rel: 0,
        playsinline: 1,
        enablejsapi: 1,
        modestbranding: 1,
        origin: youtubeOrigin(),
        widget_referrer: youtubeWidgetReferrer(),
      },
      events: {
        onReady(event) {
          const saved = state.progress[video.id];
          if (saved?.seconds > 0 && Number(saved.ratio || 0) < 1) {
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
      node.innerHTML = `<iframe src="${escapeHtml(youtubeEmbedSrc(video))}" allow="autoplay; encrypted-media; picture-in-picture" allowfullscreen referrerpolicy="strict-origin-when-cross-origin" title="${escapeHtml(video.title)}"></iframe>`;
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

function openLong(video, { finalizeCurrent = true, reason = "player-replace" } = {}) {
  const previousVideo = state.activeVideo;
  if (finalizeCurrent && previousVideo?.id && previousVideo.id !== video?.id) {
    rememberRecentPlayerVideo(previousVideo);
    finalizeVideoBeforeLeaving(previousVideo, { reason });
  }
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
  if (!state.shortQueue.length) return closeShort({ finalize: false });
  state.shortIndex = Math.min(currentIndex, state.shortQueue.length - 1);
  renderShort();
}

function playableShortVideos() {
  return state.feed.items.filter(
    (item) => item.type === "short" && item.embedAllowed !== false && !state.unavailableVideos.has(item.id),
  );
}

function shortVideoById(videoId) {
  return playableShortVideos().find((item) => item.id === videoId) || null;
}

function isPlayableShortId(videoId) {
  return Boolean(shortVideoById(videoId));
}

function shortQueueForTransientTarget(video, leavingVideoId) {
  return [
    video,
    ...playableShortVideos().filter((item) => (
      item.id !== video.id
      && item.id !== leavingVideoId
      && !isHiddenFromPlayback(item.id)
    )),
  ];
}

function canPreviousShort() {
  const current = state.shortQueue[state.shortIndex];
  if (!current) return false;
  return Boolean(state.shortHistory.peekBack(current.id, isPlayableShortId));
}

function canNextShort() {
  const current = state.shortQueue[state.shortIndex];
  if (!current) return false;
  return (
    Boolean(state.shortHistory.peekForward(current.id, isPlayableShortId))
    || state.shortIndex < state.shortQueue.length - 1
  );
}

function clearShortHistoryExpiryTimer() {
  clearTimeout(shortHistoryExpiryTimer);
  shortHistoryExpiryTimer = null;
}

function scheduleShortHistoryExpiry() {
  clearShortHistoryExpiryTimer();
  const current = state.shortQueue[state.shortIndex];
  if (!current) return;
  const expiresAt = state.shortHistory.nextExpiryAt(current.id, isPlayableShortId);
  if (!Number.isFinite(expiresAt)) return;
  const delay = Math.max(1, expiresAt - Date.now() + 25);
  shortHistoryExpiryTimer = setTimeout(refreshShortNavigationControls, delay);
}

function refreshShortNavigationControls() {
  const previousButton = document.querySelector("#shortPrevious");
  const nextButton = document.querySelector("#shortNext");
  if (previousButton) previousButton.disabled = !canPreviousShort();
  if (nextButton) nextButton.disabled = !canNextShort();
  scheduleShortHistoryExpiry();
}

function nextUnwatchedShortAfter(video, allShorts) {
  const startIndex = allShorts.findIndex((item) => item.id === video?.id);
  const afterCurrent = startIndex >= 0 ? allShorts.slice(startIndex + 1) : allShorts;
  return afterCurrent.find((item) => !isHiddenFromPlayback(item.id)) || allShorts.find((item) => !isHiddenFromPlayback(item.id)) || null;
}

function shortPlaybackQueue(video) {
  const allShorts = playableShortVideos();
  const selectedVideo = allShorts.find((item) => item.id === video?.id);
  const canReplayIgnoredSelection = state.view === "ignored" && selectedVideo && isIgnored(selectedVideo.id);
  const startVideo = selectedVideo && (!isHiddenFromPlayback(selectedVideo.id) || canReplayIgnoredSelection)
    ? selectedVideo
    : nextUnwatchedShortAfter(video, allShorts);
  if (!startVideo) return [];
  return [
    startVideo,
    ...allShorts.filter((item) => item.id !== startVideo.id && !isHiddenFromPlayback(item.id)),
  ];
}

function pruneWatchedShortQueue(keepVideoId) {
  state.shortQueue = state.shortQueue.filter((item) => item.id === keepVideoId || !isHiddenFromPlayback(item.id));
  if (keepVideoId) state.shortIndex = Math.max(0, state.shortQueue.findIndex((item) => item.id === keepVideoId));
}

function openShort(video) {
  clearShortHistoryExpiryTimer();
  state.shortHistory.reset();
  state.shortQueue = shortPlaybackQueue(video);
  if (!state.shortQueue.length) {
    window.alert("All available Shorts are already watched. Clear Watch history if you want to replay them.");
    return;
  }
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
            <button class="wheel-capture-overlay" type="button" data-wheel-capture="short" data-wheel-side="left" tabindex="-1" aria-label="Scroll on the left Short edge to switch Shorts. Click to pause or resume."></button>
            <button class="wheel-capture-overlay" type="button" data-wheel-capture="short" data-wheel-side="right" tabindex="-1" aria-label="Scroll on the right Short edge to switch Shorts. Click to pause or resume."></button>
          </div>
          <div class="short-action-stack">
            <button id="shortLikeButton" class="short-like ${liked ? "active" : ""}" aria-label="Save this Short to local likes" aria-pressed="${liked}"><span>${liked ? "♥" : "♡"}</span><small data-default-label="${escapeHtml(likeLabel)}">${liked ? "Liked" : escapeHtml(likeLabel)}</small></button>
            <button id="shortCommentsButton" class="${state.shortPanel === "comments" ? "active" : ""}" aria-label="Show comments"><span>▤</span><small>${compactMetric(commentCount, "Comments")}</small></button>
            <button id="shortShareButton" aria-label="Share this Short"><span>↗</span><small>Share</small></button>
            ${geminiButton(video, "short")}
            <button id="shortFloatButton" aria-label="Open this Short in floating player"><span>⧉</span><small>Float</small></button>
            <button id="shortDescriptionButton" class="${state.shortPanel === "description" ? "active" : ""}" aria-label="Show description"><span>i</span><small>About</small></button>
            <a href="${escapeHtml(video.channelUrl || video.url)}" target="_blank" rel="noopener" aria-label="Open ${escapeHtml(video.channel)} on YouTube"><span class="action-avatar">${escapeHtml(initials(video.channel))}</span><small>Channel</small></a>
          </div>
          <aside id="shortDrawer" class="short-drawer ${state.shortPanel ? "open" : ""}">${state.shortPanel ? shortDrawerContent(video) : ""}</aside>
        </div>
        <div class="short-controls">
          <button id="shortPrevious" aria-label="Previous Short" ${!canPreviousShort() ? "disabled" : ""}>↑</button>
          <button id="shortNext" aria-label="Next Short" ${!canNextShort() ? "disabled" : ""}>↓</button>
        </div>
      </div>
    </div>`;
  bindWheelCaptureOverlay("short", handleShortWheel);
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
  scheduleShortHistoryExpiry();
}

function nextShort() {
  const current = state.shortQueue[state.shortIndex];
  if (!current) return closeShort();
  pruneWatchedShortQueue(current.id);
  const currentAfterPrune = state.shortQueue[state.shortIndex];
  if (!currentAfterPrune || currentAfterPrune.id !== current.id) return renderShort();

  const forwardEntry = state.shortHistory.forward(current.id, isPlayableShortId);
  const forwardVideo = shortVideoById(forwardEntry?.id);
  if (forwardVideo) {
    finalizeVideoBeforeLeaving(current, { reason: "short-forward" });
    state.shortQueue = shortQueueForTransientTarget(forwardVideo, current.id);
    state.shortIndex = 0;
    return renderShort();
  }

  if (state.shortIndex < state.shortQueue.length - 1) {
    const currentIndex = state.shortIndex;
    state.shortHistory.pushForNext(current.id);
    finalizeVideoBeforeLeaving(current, { reason: "short-next" });
    if (isHiddenFromPlayback(current.id)) {
      state.shortQueue = state.shortQueue.filter((item) => item.id !== current.id && !isHiddenFromPlayback(item.id));
      if (!state.shortQueue.length) return closeShort();
      state.shortIndex = Math.min(currentIndex, state.shortQueue.length - 1);
      return renderShort();
    }
    state.shortIndex += 1;
    return renderShort();
  }

  finalizeVideoBeforeLeaving(current, { reason: "short-next" });
  if (!isHiddenFromPlayback(current.id)) return refreshShortNavigationControls();
  state.shortQueue = state.shortQueue.filter((item) => item.id !== current.id && !isHiddenFromPlayback(item.id));
  if (!state.shortQueue.length) return closeShort();
  state.shortIndex = Math.min(state.shortIndex, state.shortQueue.length - 1);
  return renderShort();
}

function previousShort() {
  const current = state.shortQueue[state.shortIndex];
  if (!current) return closeShort();
  const backEntry = state.shortHistory.back(current.id, isPlayableShortId);
  const backVideo = shortVideoById(backEntry?.id);
  if (!backVideo) return refreshShortNavigationControls();

  finalizeVideoBeforeLeaving(current, { reason: "short-previous" });
  state.shortQueue = shortQueueForTransientTarget(backVideo, current.id);
  state.shortIndex = 0;
  return renderShort();
}

function closeShort({ finalize = true } = {}) {
  if (finalize) finalizeVideoBeforeLeaving(state.shortQueue[state.shortIndex], { reason: "short-close" });
  clearShortHistoryExpiryTimer();
  state.shortHistory.reset();
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
  finalizeVideoBeforeLeaving(state.activeVideo, { reason: "home" });
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
  finalizeVideoBeforeLeaving(state.activeVideo, { reason: `view-${view}` });
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

function openCard(card, playbackOptions = {}) {
  if (!card) return;
  if (card.dataset.shortId) {
    const video = state.feed.items.find((item) => item.id === card.dataset.shortId);
    if (video) openShort(video);
    return;
  }
  if (card.dataset.videoId) {
    const video = state.feed.items.find((item) => item.id === card.dataset.videoId);
    if (video) openLong(video, playbackOptions);
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
    schemaVersion: 2,
    exportedAt: new Date().toISOString(),
    retention: {
      policy: "current feed window plus 1 extra day",
      retentionDays: Math.ceil(feedStateRetentionMs() / DAY_MS),
    },
    watched: state.watched,
    progress: state.progress,
    ignored: state.ignored,
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
  state.ignored = { ...state.ignored, ...(data.ignored || {}) };
  state.liked = { ...state.liked, ...(data.liked || {}) };
  localStorage.setItem(WATCHED_KEY, JSON.stringify(state.watched));
  localStorage.setItem(PROGRESS_KEY, JSON.stringify(state.progress));
  localStorage.setItem(IGNORED_KEY, JSON.stringify(state.ignored));
  localStorage.setItem(LIKED_KEY, JSON.stringify(state.liked));
  prunePlaybackStateRetention();
  updateHistoryCount();
  updateIgnoredCount();
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
    prunePlaybackStateRetention();
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
  finalizeVideoBeforeLeaving(state.activeVideo, { reason: "search" });
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
  const wheelCapture = event.target.closest("[data-wheel-capture]");
  if (wheelCapture) {
    event.preventDefault();
    event.stopPropagation();
    toggleCurrentPlayback();
    return;
  }

  const viewButton = event.target.closest("[data-view]");
  if (viewButton) return selectView(viewButton.dataset.view);

  const quickFilterButton = event.target.closest("[data-quick-filter]");
  if (quickFilterButton) {
    finalizeVideoBeforeLeaving(state.activeVideo, { reason: "quick-filter" });
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

  const floatButtonElement = event.target.closest("[data-float-id]");
  if (floatButtonElement) {
    event.preventDefault();
    event.stopPropagation();
    const video = state.feed.items.find((item) => item.id === floatButtonElement.dataset.floatId) || state.activeVideo;
    openFloatingVideo(video);
    return;
  }

  const notebookButtonElement = event.target.closest("[data-notebooklm-id]");
  if (notebookButtonElement) {
    event.preventDefault();
    event.stopPropagation();
    const video = state.feed.items.find((item) => item.id === notebookButtonElement.dataset.notebooklmId) || state.activeVideo;
    openNotebookLm(video, notebookButtonElement);
    return;
  }

  const geminiButtonElement = event.target.closest("[data-gemini-id]");
  if (geminiButtonElement) {
    event.preventDefault();
    event.stopPropagation();
    const video = state.feed.items.find((item) => item.id === geminiButtonElement.dataset.geminiId) || state.activeVideo;
    openGemini(video, geminiButtonElement);
    return;
  }

  const playerNavElement = event.target.closest("[data-player-nav]");
  if (playerNavElement) {
    event.preventDefault();
    event.stopPropagation();
    navigatePlayer(Number(playerNavElement.dataset.playerNav || 1));
    return;
  }

  const shortButton = event.target.closest("[data-short-id]");
  if (shortButton) {
    openCard(shortButton);
    return;
  }

  const videoButton = event.target.closest("[data-video-id]");
  if (videoButton) {
    if (state.activeVideo?.id && videoButton.dataset.videoId !== state.activeVideo.id) {
      finalizeVideoBeforeLeaving(state.activeVideo, { reason: "card-open" });
    }
    openCard(videoButton, { finalizeCurrent: false });
    return;
  }

  if (event.target.closest("#closePlayer")) {
    finalizeVideoBeforeLeaving(state.activeVideo, { reason: "player-close" });
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
  if (event.target.closest("#clearIgnored")) {
    state.ignored = {};
    Object.values(state.progress).forEach((entry) => {
      if (entry && typeof entry === "object") {
        delete entry.ignoredAt;
        delete entry.ignoredReason;
      }
    });
    localStorage.removeItem(IGNORED_KEY);
    localStorage.setItem(PROGRESS_KEY, JSON.stringify(state.progress));
    updateIgnoredCount();
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
app.addEventListener("wheel", handlePlayerWheel, { passive: false });
overlayRoot.addEventListener("click", (event) => {
  const wheelCapture = event.target.closest("[data-wheel-capture]");
  if (wheelCapture) {
    event.preventDefault();
    event.stopPropagation();
    toggleCurrentPlayback();
    return;
  }

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
  if (event.target.closest("#shortGeminiButton")) {
    event.preventDefault();
    event.stopPropagation();
    return openGemini(state.shortQueue[state.shortIndex], event.target.closest("#shortGeminiButton"));
  }
  if (event.target.closest("#shortFloatButton")) {
    event.preventDefault();
    event.stopPropagation();
    return openFloatingVideo(state.shortQueue[state.shortIndex]);
  }
  if (event.target.closest("#shortDescriptionButton")) return toggleShortPanel("description");
  if (event.target.closest("#shortDrawerClose")) return toggleShortPanel(state.shortPanel);
});
overlayRoot.addEventListener("wheel", handleShortWheel, { passive: false });
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
  if (isTypingTarget(event.target) || event.metaKey || event.ctrlKey || event.altKey) return;
  if (state.shortQueue.length) {
    if (event.key === "Escape") {
      event.preventDefault();
      closeShort();
    }
    if (event.key === "ArrowDown" || event.key === "ArrowRight" || event.key.toLowerCase() === "n") {
      event.preventDefault();
      nextShort();
    }
    if (event.key === "ArrowUp" || event.key === "ArrowLeft" || event.key.toLowerCase() === "p") {
      event.preventDefault();
      previousShort();
    }
    return;
  }
  if (!state.activeVideo) return;
  if (event.key === "ArrowRight" || event.key === "PageDown" || event.key.toLowerCase() === "n") {
    event.preventDefault();
    navigatePlayer(1);
  }
  if (event.key === "ArrowLeft" || event.key === "PageUp" || event.key.toLowerCase() === "p") {
    event.preventDefault();
    navigatePlayer(-1);
  }
});

loadFeed();
