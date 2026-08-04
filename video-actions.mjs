const VIDEO_ID_PATTERN = /^[A-Za-z0-9_-]{11}$/;
const CHANNEL_ID_PATTERN = /^UC[A-Za-z0-9_-]{22}$/;
const CHANNEL_HANDLE_PATTERN = /^@[A-Za-z0-9._-]{3,100}$/;
const VIDEO_TYPES = new Set(["long", "short"]);
const APP_VIEWS = new Set(["home", "shorts", "long", "liked", "history", "ignored"]);

function normalizedVideoId(value) {
  const videoId = String(value || "").trim();
  return VIDEO_ID_PATTERN.test(videoId) ? videoId : "";
}

export function buildYouTubeWatchUrl(videoId) {
  const safeVideoId = normalizedVideoId(videoId);
  return safeVideoId
    ? `https://www.youtube.com/watch?v=${encodeURIComponent(safeVideoId)}`
    : "https://www.youtube.com/";
}

export function buildYouTubeChannelUrl({ channelId = "", handle = "" } = {}) {
  const safeChannelId = String(channelId || "").trim();
  if (CHANNEL_ID_PATTERN.test(safeChannelId)) {
    return `https://www.youtube.com/channel/${encodeURIComponent(safeChannelId)}`;
  }
  const safeHandle = String(handle || "").trim();
  if (CHANNEL_HANDLE_PATTERN.test(safeHandle)) {
    return `https://www.youtube.com/@${encodeURIComponent(safeHandle.slice(1))}`;
  }
  return "https://www.youtube.com/";
}

export function buildPlaybackUrl(baseHref, { videoId, type = "long", view = "home" } = {}) {
  const normalizedId = normalizedVideoId(videoId);
  if (!normalizedId) throw new TypeError("A valid video ID is required.");
  if (!VIDEO_TYPES.has(type)) throw new TypeError("A valid video type is required.");
  if (!APP_VIEWS.has(view)) throw new TypeError("A valid app view is required.");

  const target = new URL(baseHref);
  target.search = "";
  target.hash = "";
  target.searchParams.set("play", normalizedId);
  target.searchParams.set("type", type);
  target.searchParams.set("view", view);
  return target.toString();
}

export function readPlaybackRequest(href) {
  let target;
  try {
    target = new URL(href);
  } catch {
    return null;
  }

  const videoId = normalizedVideoId(target.searchParams.get("play"));
  if (!videoId) return null;
  const requestedType = target.searchParams.get("type");
  const requestedView = target.searchParams.get("view");
  if (requestedType !== null && !VIDEO_TYPES.has(requestedType)) return null;
  if (requestedView !== null && !APP_VIEWS.has(requestedView)) return null;
  return {
    videoId,
    type: VIDEO_TYPES.has(requestedType) ? requestedType : null,
    view: APP_VIEWS.has(requestedView) ? requestedView : null,
  };
}
