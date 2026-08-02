export function buildShortPlaybackQueue({
  videos = [],
  requestedVideo = null,
  isHidden = () => false,
  allowHiddenRequested = false,
} = {}) {
  const playable = Array.isArray(videos) ? videos.filter((video) => video?.id) : [];
  const requestedId = requestedVideo?.id;
  const requestedIndex = playable.findIndex((video) => video.id === requestedId);
  const selectedVideo = requestedIndex >= 0 ? playable[requestedIndex] : null;
  const afterRequested = requestedIndex >= 0 ? playable.slice(requestedIndex + 1) : playable;
  const firstVisible = afterRequested.find((video) => !isHidden(video.id))
    || playable.find((video) => !isHidden(video.id))
    || null;
  const startVideo = selectedVideo && (!isHidden(selectedVideo.id) || allowHiddenRequested)
    ? selectedVideo
    : firstVisible;
  if (!startVideo) return [];
  return [
    startVideo,
    ...playable.filter((video) => video.id !== startVideo.id && !isHidden(video.id)),
  ];
}

export function createTransientDirectionalHistory({
  ttlMs = 10_000,
  maxEntries = 8,
  now = () => Date.now(),
} = {}) {
  let backStack = [];
  let forwardStack = [];

  const playableByDefault = () => true;

  function isValid(entry, currentId, isPlayable, at) {
    if (!entry?.id || entry.id === currentId) return false;
    if (!Number.isFinite(entry.stamp) || at - entry.stamp > ttlMs) return false;
    return isPlayable(entry.id);
  }

  function prune(stack, currentId, isPlayable = playableByDefault, at = now()) {
    return stack.filter((entry) => isValid(entry, currentId, isPlayable, at));
  }

  function push(stack, id, at = now()) {
    if (!id) return stack;
    const next = stack.filter((entry) => entry.id !== id);
    next.push({ id, stamp: at });
    return next.slice(-maxEntries);
  }

  function reset() {
    backStack = [];
    forwardStack = [];
  }

  function pushForNext(currentId) {
    const at = now();
    backStack = prune(backStack, currentId, playableByDefault, at);
    backStack = push(backStack, currentId, at);
    forwardStack = [];
  }

  function peekBack(currentId, isPlayable = playableByDefault) {
    backStack = prune(backStack, currentId, isPlayable);
    return backStack.length ? { ...backStack[backStack.length - 1] } : null;
  }

  function peekForward(currentId, isPlayable = playableByDefault) {
    forwardStack = prune(forwardStack, currentId, isPlayable);
    return forwardStack.length ? { ...forwardStack[forwardStack.length - 1] } : null;
  }

  function back(currentId, isPlayable = playableByDefault) {
    const target = peekBack(currentId, isPlayable);
    if (!target) return null;
    backStack.pop();
    forwardStack = push(forwardStack, currentId);
    return target;
  }

  function forward(currentId, isPlayable = playableByDefault) {
    const target = peekForward(currentId, isPlayable);
    if (!target) return null;
    forwardStack.pop();
    backStack = push(backStack, currentId);
    return target;
  }

  function nextExpiryAt(currentId, isPlayable = playableByDefault) {
    const at = now();
    backStack = prune(backStack, currentId, isPlayable, at);
    forwardStack = prune(forwardStack, currentId, isPlayable, at);
    const expiries = [...backStack, ...forwardStack].map((entry) => entry.stamp + ttlMs);
    return expiries.length ? Math.min(...expiries) : null;
  }

  function snapshot() {
    return {
      back: backStack.map((entry) => ({ ...entry })),
      forward: forwardStack.map((entry) => ({ ...entry })),
    };
  }

  return {
    reset,
    pushForNext,
    peekBack,
    peekForward,
    back,
    forward,
    nextExpiryAt,
    snapshot,
  };
}
