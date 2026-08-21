#!/usr/bin/env python3
"""Regression tests for YourTube rich metadata and owner-managed settings."""
from __future__ import annotations

import base64
import gzip
import importlib.util
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FrontendFeatureTests(unittest.TestCase):
    def test_manual_skip_uses_ignored_list_and_watch_thresholds(self):
        app_js = (ROOT / "app.js").read_text(encoding="utf-8")
        index_html = (ROOT / "index.html").read_text(encoding="utf-8")
        style_css = (ROOT / "style.css").read_text(encoding="utf-8")

        for marker in [
            'const IGNORED_KEY = "nexafeed-ignored-v1";',
            "const STATE_RETENTION_BUFFER_DAYS = 1;",
            "ignoredCount",
            "state.ignored",
            "function isIgnored",
            "function saveIgnored",
            "function markIgnored",
            "function playbackStateTimestamp",
            "function feedStateRetentionMs",
            "function prunePlaybackStateRetention",
            "function watchedThresholdSeconds",
            "function videoQualifiesAsWatched",
            "function finalizeVideoBeforeLeaving",
            "function openLong(video, { finalizeCurrent = true",
            "previousVideo.id !== video?.id",
            'openLong(target, { finalizeCurrent: false })',
            'finalizeVideoBeforeLeaving(state.activeVideo, { reason: "player-nav" })',
            'finalizeVideoBeforeLeaving(current, { reason: "short-next" })',
            'finalizeVideoBeforeLeaving(current, { reason: "short-previous" })',
            'state.view === "ignored"',
            "!isWatched(item.id) && !isIgnored(item.id)",
            "watched: state.watched",
            "ignored: state.ignored",
            "Ignored videos stay hidden from Home, Shorts, Long videos, and Up Next until you clear this list.",
            "Watched and ignored records are kept for the current feed window plus 1 extra day, then pruned locally.",
            "Clear ignored",
            "nexafeed-history-",
        ]:
            self.assertIn(marker, app_js)

        for marker in [
            'data-view="ignored"',
            'id="ignoredCount"',
            "Ignored videos",
            "app.js?v=20260821-gemini-brief",
            "style.css?v=20260821-gemini-brief",
        ]:
            self.assertIn(marker, index_html)

        for marker in [".ignored-pill", ".ignored-count", ".ignored-tools"]:
            self.assertIn(marker, style_css)

        self.assertNotIn("MINIMUM_MANUAL_SWITCH_WATCH_SECONDS", app_js)
        self.assertNotIn("markVideoWatchedAfterMinimum", app_js)

    def test_watch_state_retention_protects_current_feed_ids(self):
        app_js = (ROOT / "app.js").read_text(encoding="utf-8")
        index_html = (ROOT / "index.html").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        for marker in [
            "function currentFeedVideoIds",
            "new Set(items.map((item) => item.id).filter(Boolean))",
            "protectedIds = new Set()",
            "if (protectedIds.has(id)) return;",
            "const protectedIds = currentFeedVideoIds();",
            "pruneTimedStateMap(state.watched, retentionMs, now, protectedIds)",
            "pruneTimedStateMap(state.ignored, retentionMs, now, protectedIds)",
            "pruneTimedStateMap(state.progress, retentionMs, now, protectedIds)",
            "active feed ID is never pruned while it is still present in data/videos.json",
        ]:
            self.assertIn(marker, app_js)

        self.assertIn("app.js?v=20260821-gemini-brief", index_html)
        self.assertIn("style.css?v=20260821-gemini-brief", index_html)
        self.assertIn("still present in the active feed is protected from pruning", readme)

    def test_skip_thresholds_do_not_recreate_old_five_second_watch_rule(self):
        app_js = (ROOT / "app.js").read_text(encoding="utf-8")
        float_html = (ROOT / "float.html").read_text(encoding="utf-8")

        self.assertIn('if (video?.type === "short" && duration > 0)', app_js)
        self.assertIn('if (item?.type === "short" && duration > 0)', float_html)
        for source in [app_js, float_html]:
            self.assertIn("Math.ceil(duration / 2)", source)
            self.assertIn("return WATCHED_SKIP_THRESHOLD_SECONDS;", source)
            self.assertNotIn("duration > 0 && duration < WATCHED_SKIP_THRESHOLD_SECONDS", source)

        self.assertIn("function videoForPlaybackState", app_js)
        self.assertIn("watchedSeconds >= watchedThresholdSeconds(video, duration)", app_js)
        self.assertIn("state.progress[video?.id]?.duration", app_js)
        self.assertIn("readJson(PROGRESS_KEY, {})[video?.id]?.duration", app_js)
        self.assertNotIn("if (ratio >= 0.8) markWatched(id);", app_js)
        self.assertNotIn("saved?.seconds > 5", app_js)
        self.assertNotIn("video.start > 5", float_html)

    def test_playback_deep_links_round_trip_and_replay_the_exact_requested_video(self):
        app_js = (ROOT / "app.js").read_text(encoding="utf-8")
        actions_module = ROOT / "video-actions.mjs"
        self.assertTrue(actions_module.exists(), "Playback URL helpers must be isolated for behavioral testing")

        module_url = json.dumps(actions_module.as_uri())
        script = f"""
          import {{ buildPlaybackUrl, buildYouTubeChannelUrl, buildYouTubeWatchUrl, readPlaybackRequest }} from {module_url};
          const expect = (condition, message) => {{ if (!condition) throw new Error(message); }};
          const href = buildPlaybackUrl("https://developerjillur.github.io/nexafeed/?stale=1#shorts", {{
            videoId: "00kEcNby86c",
            type: "short",
            view: "history",
          }});
          const url = new URL(href);
          expect(url.origin === "https://developerjillur.github.io", "origin must stay same-origin");
          expect(url.pathname === "/nexafeed/", "app pathname must be preserved");
          expect(url.searchParams.get("play") === "00kEcNby86c", "clicked video ID must be encoded");
          expect(url.searchParams.get("type") === "short", "video type must be encoded");
          expect(url.searchParams.get("view") === "history", "collection view must be preserved");
          expect(!url.searchParams.has("stale") && !url.hash, "stale query/hash state must not leak");

          const request = readPlaybackRequest(href);
          expect(request?.videoId === "00kEcNby86c", "playback request must recover exact ID");
          expect(request?.type === "short", "playback request must recover type");
          expect(request?.view === "history", "playback request must recover view");
          expect(readPlaybackRequest("https://example.test/?play=<script>") === null, "invalid IDs must be rejected");
          expect(readPlaybackRequest("https://example.test/?play=00kEcNby86c&type=bogus&view=history") === null, "an explicitly invalid type must reject the whole request");
          expect(readPlaybackRequest("https://example.test/?play=00kEcNby86c&type=short&view=bogus") === null, "an explicitly invalid view must reject the whole request");
          let rejectedInvalidType = false;
          try {{ buildPlaybackUrl("https://example.test/", {{ videoId: "00kEcNby86c", type: "bogus", view: "home" }}); }} catch (error) {{ rejectedInvalidType = error instanceof TypeError; }}
          expect(rejectedInvalidType, "the URL builder must reject an invalid explicit type");
          let rejectedInvalidView = false;
          try {{ buildPlaybackUrl("https://example.test/", {{ videoId: "00kEcNby86c", type: "short", view: "bogus" }}); }} catch (error) {{ rejectedInvalidView = error instanceof TypeError; }}
          expect(rejectedInvalidView, "the URL builder must reject an invalid explicit view");
          expect(buildYouTubeWatchUrl("00kEcNby86c") === "https://www.youtube.com/watch?v=00kEcNby86c", "YouTube links must be canonical");
          expect(buildYouTubeWatchUrl("<script>") === "https://www.youtube.com/", "invalid feed IDs must not become active URLs");
          expect(buildYouTubeWatchUrl("too-short") === "https://www.youtube.com/", "YouTube IDs must be exactly eleven characters");
          expect(buildYouTubeChannelUrl({{ channelId: "UC501J-qOwU_7-EVlZK84lng" }}) === "https://www.youtube.com/channel/UC501J-qOwU_7-EVlZK84lng", "channel IDs must be canonical");
          expect(buildYouTubeChannelUrl({{ handle: "@vdmsocial1" }}) === "https://www.youtube.com/@vdmsocial1", "safe handles may be canonicalized");
          expect(buildYouTubeChannelUrl({{ handle: "javascript:alert(1)" }}) === "https://www.youtube.com/", "untrusted channel URLs must never survive");
        """
        result = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        for marker in [
            'import { buildPlaybackUrl, buildYouTubeChannelUrl, buildYouTubeWatchUrl, readPlaybackRequest } from "./video-actions.mjs?v=20260821-gemini-brief";',
            "initialPlaybackRequest: readPlaybackRequest(window.location.href)",
            "function openInitialPlaybackRequest",
            "openShort(video, { allowHiddenRequested: true })",
            "function shortPlaybackQueue(video, { allowHiddenRequested = false } = {})",
            "function openShort(video, { allowHiddenRequested = false } = {})",
        ]:
            self.assertIn(marker, app_js)

    def test_daily_archive_groups_by_bangladesh_date_and_builds_ai_ready_exports(self):
        archive_module = ROOT / "daily-archive.mjs"
        self.assertTrue(archive_module.exists(), "Daily archive behavior must be isolated for behavioral testing")
        module_url = json.dumps(archive_module.as_uri())
        script = f"""
          import {{
            archiveDateOptions,
            archiveStateRetentionMs,
            buildDailyExport,
            dailyAnalysisPrompt,
            dailyExportMarkdown,
            dailyExportUrls,
            dateKeyInTimeZone,
            itemsForArchiveDate,
            resolveArchiveDate,
          }} from {module_url};
          const expect = (condition, message) => {{ if (!condition) throw new Error(message); }};
          const now = new Date("2026-08-19T19:30:00Z");
          const options = archiveDateOptions({{ now, days: 30, timeZone: "Asia/Dhaka" }});
          expect(options.length === 30, "exactly thirty calendar dates must be selectable");
          expect(archiveDateOptions({{ now, days: 2 }}).length === 30, "archive date count must not be runtime-overridable");
          expect(archiveStateRetentionMs() === 31 * 24 * 60 * 60 * 1000, "local playback state must use the fixed 30-day archive plus one-day buffer");
          expect(options[0] === "2026-08-20", "Bangladesh Today must be the first date");
          expect(options[29] === "2026-07-22", "the thirtieth inclusive day must be retained");
          expect(resolveArchiveDate("2026-07-21", {{ now }}) === "2026-08-20", "out-of-range dates must fail closed to Today");
          expect(dateKeyInTimeZone("2026-08-19T18:00:00Z") === "2026-08-20", "Bangladesh midnight must start at 18:00 UTC");

          const items = [
            {{ id: "00kEcNby86c", type: "short", title: "AI Agent Update", channel: "Nexa", channelId: "UC501J-qOwU_7-EVlZK84lng", handle: "@vdmsocial1", publishedAt: "2026-08-19T17:00:00Z", firstSeenAt: "2026-08-19T18:00:00Z", duration: "0:42", views: "1.2K views", source: "primary", priority: 1, url: "javascript:alert(1)", channelUrl: "data:text/html,bad" }},
            {{ id: "Gx2QN7FvKAM", type: "long", title: "AI Long Update", channel: "Nexa", publishedAt: "2026-08-20T01:00:00Z", firstSeenAt: "2026-08-20T01:05:00Z", source: "primary" }},
            {{ id: "Ut0i-SSEXY4", type: "long", title: "Previous day", channel: "Nexa", publishedAt: "2026-08-20T01:30:00Z", firstSeenAt: "2026-08-19T17:59:59Z", source: "primary" }},
          ];
          const selected = itemsForArchiveDate(items, "2026-08-20");
          expect(selected.length === 2 && selected.every((item) => item.id !== "Ut0i-SSEXY4"), "only the selected Bangladesh day may be exported");
          const payload = buildDailyExport({{
            items: selected,
            details: {{ items: {{ "00kEcNby86c": {{ description: "Detailed AI notes", commentCount: 1, comments: [{{ author: "Jillur", text: "Useful insight", likeCount: 3 }}] }} }} }},
            selectedDate: "2026-08-20",
            exportedAt: "2026-08-20T03:00:00Z",
            baseHref: "https://developerjillur.github.io/nexafeed/",
          }});
          expect(payload.summary.total === 2 && payload.summary.shorts === 1 && payload.summary.longVideos === 1, "daily totals must be included");
          expect(payload.contentTrust === "untrusted-public-data", "AI exports must label public video content as untrusted data");
          expect(payload.videos[0].description === "Detailed AI notes", "cached description must be included");
          expect(payload.videos[0].comments[0].text === "Useful insight", "cached comments must be included");
          expect(payload.videos[0].youtubeUrl === "https://www.youtube.com/watch?v=00kEcNby86c", "raw feed URLs must be replaced with canonical YouTube URLs");
          expect(payload.videos[0].yourTubeUrl.includes("view=archive") && payload.videos[0].yourTubeUrl.includes("date=2026-08-20"), "YourTube export links must preserve archive date replay");
          expect(!JSON.stringify(payload).includes("javascript:"), "malicious raw feed destinations must not survive export");
          const markdown = dailyExportMarkdown(payload);
          expect(markdown.includes("# YourTube Daily Feed — 2026-08-20"), "Markdown must have a dated heading");
          expect(markdown.includes("Detailed AI notes") && markdown.includes("Useful insight"), "Markdown must contain analysis context");
          const urls = dailyExportUrls(payload).trim().split("\\n");
          expect(urls.length === 2, "all selected-day Long and Short URLs must be copied");
          expect(urls.includes("https://www.youtube.com/watch?v=00kEcNby86c") && urls.includes("https://www.youtube.com/watch?v=Gx2QN7FvKAM"), "URL copy must contain canonical Long and Short destinations");
          expect(!urls.some((url) => url.includes("Ut0i-SSEXY4")), "another day's URL must not leak into the copied list");
          const analysisPrompt = dailyAnalysisPrompt(payload);
          for (const marker of [
            "You are a senior YouTube research analyst",
            "Selected YourTube date: 2026-08-20",
            "Topics and main ideas",
            "What is taught",
            "What is demonstrated",
            "New updates",
            "Cross-video synthesis",
            "Do not invent",
            "Respond in clear Bangla",
            "https://www.youtube.com/watch?v=00kEcNby86c",
            "https://www.youtube.com/watch?v=Gx2QN7FvKAM",
          ]) expect(analysisPrompt.includes(marker), `analysis prompt missing: ${{marker}}`);
          expect(!analysisPrompt.includes("Ut0i-SSEXY4"), "analysis prompt must contain only the selected day's URLs");
        """
        result = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_video_cards_are_real_links_and_preserve_modified_click_navigation(self):
        app_js = (ROOT / "app.js").read_text(encoding="utf-8")

        for marker in [
            "function videoPlaybackHref",
            "const href = buildPlaybackUrl(window.location.href, {",
            '<a class="card-open" href="${escapeHtml(videoPlaybackHref(video))}"',
            '<a class="queue-card" href="${escapeHtml(videoPlaybackHref(item))}"',
            "function shouldOpenCardInCurrentPage(event)",
            "event.button === 0",
            "!event.metaKey",
            "!event.ctrlKey",
            "!event.shiftKey",
            "!event.altKey",
            "if (!shouldOpenCardInCurrentPage(event)) return;",
            "event.preventDefault();\n    openCard(shortLink);",
            "event.preventDefault();\n    if (state.activeVideo?.id",
        ]:
            self.assertIn(marker, app_js)

        self.assertNotIn('class="card-open" type="button"', app_js)
        self.assertNotIn('<button class="queue-card"', app_js)

    def test_video_action_menu_exposes_open_ai_copy_and_local_state_actions(self):
        app_js = (ROOT / "app.js").read_text(encoding="utf-8")
        style_css = (ROOT / "style.css").read_text(encoding="utf-8")

        for marker in [
            "function videoActionsButton",
            "data-open-video-menu-id",
            'id="shortVideoActionsButton"',
            "function openVideoActionMenu",
            "function closeVideoActionMenu",
            "function runVideoAction",
            "function handleVideoActionMenuKeydown",
            'role="menu"',
            'data-video-action="open-tab"',
            'data-video-action="open-window"',
            'data-video-action="open-youtube"',
            'data-video-action="copy-yourtube"',
            'data-video-action="copy-youtube"',
            'data-video-action="toggle-like"',
            'data-video-action="gemini"',
            'data-video-action="notebooklm"',
            'data-video-action="float"',
            'data-video-action="toggle-watched"',
            'data-video-action="toggle-ignored"',
            "Open in new tab",
            "Open in new window",
            "Open on YouTube",
            "Copy YourTube link",
            "Copy YouTube link",
            "Ask Gemini",
            "Chat with NotebookLM",
            "Float player",
            'document.addEventListener("contextmenu"',
            "if (event.shiftKey) return;",
            'event.target.closest("[data-video-context-id]")',
            'document.addEventListener("keydown", handleVideoActionMenuKeydown)',
            "function openInNewTab",
            "function openInNewWindow",
            "function toggleWatchedFromMenu",
            "function toggleIgnoredFromMenu",
        ]:
            self.assertIn(marker, app_js)

        for marker in [
            "#videoActionMenuRoot",
            ".video-action-menu",
            ".video-action-item",
            ".video-action-separator",
            "z-index: 300",
            "pointer-events: none",
            "pointer-events: auto",
        ]:
            self.assertIn(marker, style_css)

        self.assertNotIn("video-context-overlay", app_js)
        self.assertNotIn("video-context-overlay", style_css)

    def test_video_actions_are_private_keyboard_isolated_and_mobile_safe(self):
        app_js = (ROOT / "app.js").read_text(encoding="utf-8")
        style_css = (ROOT / "style.css").read_text(encoding="utf-8")
        verifier = (ROOT / "scripts/verify_nexafeed.py").read_text(encoding="utf-8")

        for marker in [
            "buildYouTubeWatchUrl",
            'return `${target.origin}${target.pathname}`;',
            "VIDEO_ACTION_MENU_BLOCKED_SHORTCUTS",
            "VIDEO_ACTION_MENU_BLOCKED_SHORTCUTS.has(event.key)",
            'data-close-video-menu',
            "isVideoActionMenuOpenFor(video.id, openButton)",
            "closeVideoActionMenu({ restoreFocus: true })",
            "function refreshActivePlayerQueue",
            'data-up-next-count',
        ]:
            self.assertIn(marker, app_js)

        self.assertNotIn('return video?.url ||', app_js)
        self.assertNotIn('return window.location.href.split("#")[0];', app_js)
        self.assertIn("@media (max-width: 680px) and (max-height: 780px)", style_css)
        self.assertIn("overflow-y: auto", style_css)
        for module in ['"short-history.mjs"', '"video-actions.mjs"', '"daily-archive.mjs"']:
            self.assertIn(module, verifier)

    def test_external_video_surfaces_popup_and_backtrack_are_hardened(self):
        app_js = (ROOT / "app.js").read_text(encoding="utf-8")
        float_html = (ROOT / "float.html").read_text(encoding="utf-8")
        style_css = (ROOT / "style.css").read_text(encoding="utf-8")
        verifier = (ROOT / "scripts/verify_nexafeed.py").read_text(encoding="utf-8")

        for marker in [
            "buildYouTubeChannelUrl",
            "popup.opener = null",
            "function openExternalWithoutOpener",
            'window.open("about:blank", "_blank")',
            "opened.location.replace(url)",
            'if (event.key === "Tab")',
            'rememberRecentPlayerVideo(state.activeVideo);',
            "function leaveExplicitlyIgnoredVideo",
            "if (leaveExplicitlyIgnoredVideo(video)) return;",
        ]:
            self.assertIn(marker, app_js)
        self.assertNotIn('window.open(notebookUrl, "_blank")', app_js)
        self.assertNotIn('window.open(geminiChatUrl(prompt), "_blank")', app_js)
        self.assertNotIn("video.url", app_js)
        self.assertNotIn("video.channelUrl", app_js)

        for marker in [
            "function safeWidgetReferrer",
            'return `${target.origin}${target.pathname}`;',
            "widget_referrer: safeWidgetReferrer()",
            "window.opener = null",
        ]:
            self.assertIn(marker, float_html)
        self.assertNotIn("document.referrer || window.location.href", float_html)
        self.assertNotIn("item.url", float_html)

        self.assertIn("@media (max-width: 680px) and (max-height: 780px)", style_css)
        self.assertIn('"float.html"', verifier)
        self.assertIn("float_html", verifier)

    def test_recent_watched_video_can_be_reopened_with_previous_for_ten_seconds(self):
        app_js = (ROOT / "app.js").read_text(encoding="utf-8")

        for marker in [
            "const RECENT_PLAYER_BACKTRACK_MS = 10 * 1000;",
            "recentPlayerHistory: []",
            "function rememberRecentPlayerVideo",
            "function recentPlayerBacktrackVideo",
            "function pruneRecentPlayerHistory",
            "let playerHistoryExpiryTimer = null;",
            "function schedulePlayerHistoryExpiry",
            "playerHistoryExpiryTimer = setTimeout",
            "direction < 0 ? recentPlayerBacktrackVideo(currentId) : null",
            "rememberRecentPlayerVideo(state.activeVideo)",
            "recent.stamp && Date.now() - recent.stamp <= RECENT_PLAYER_BACKTRACK_MS",
            "item.id === currentId || (!isWatched(item.id) && !isIgnored(item.id))",
        ]:
            self.assertIn(marker, app_js)

        self.assertNotIn("RECENT_PLAYER_BACKTRACK_MS = 60", app_js)

    def test_short_navigation_history_is_directional_transient_and_skips_unavailable(self):
        app_js = (ROOT / "app.js").read_text(encoding="utf-8")
        history_module = ROOT / "short-history.mjs"
        self.assertTrue(history_module.exists(), "Short history must be isolated for behavioral testing")

        module_url = json.dumps(history_module.as_uri())
        script = f"""
          import {{ createTransientDirectionalHistory }} from {module_url};
          let now = 100;
          const playable = new Set(["A", "B", "C", "D", "X"]);
          const isPlayable = (id) => playable.has(id);
          const expect = (condition, message) => {{ if (!condition) throw new Error(message); }};
          const history = createTransientDirectionalHistory({{ ttlMs: 10_000, maxEntries: 8, now: () => now }});

          history.pushForNext("A");
          now += 1_000;
          history.pushForNext("B");
          expect(history.peekBack("C", isPlayable)?.id === "B", "C should go back to B");
          expect(history.back("C", isPlayable)?.id === "B", "first Up should open B");
          expect(history.back("B", isPlayable)?.id === "A", "second Up should open A, not toggle to C");
          expect(history.forward("A", isPlayable)?.id === "B", "Down after back should return to B");
          expect(history.forward("B", isPlayable)?.id === "C", "second Down should return to C");

          history.reset();
          history.pushForNext("A");
          now += 100;
          history.pushForNext("X");
          playable.delete("X");
          expect(history.peekBack("C", isPlayable)?.id === "A", "unavailable newest entry must not mask A");

          history.reset();
          now = 500;
          history.pushForNext("A");
          now += 10_001;
          expect(history.peekBack("B", isPlayable) === null, "back entry must expire after ten seconds");
          expect(history.back("B", isPlayable) === null, "expired Up must be a no-op");

          history.pushForNext("B");
          history.reset();
          expect(history.peekBack("C", isPlayable) === null, "new Short sessions must not inherit old history");
        """
        result = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        self.assertIn(
            'import { buildShortPlaybackQueue, createTransientDirectionalHistory } from "./short-history.mjs?v=20260821-gemini-brief";',
            app_js,
        )
        self.assertIn("shortHistory: createTransientDirectionalHistory", app_js)
        for marker in [
            "state.shortHistory.pushForNext(current.id)",
            "state.shortHistory.back(current.id, isPlayableShortId)",
            "state.shortHistory.forward(current.id, isPlayableShortId)",
            "state.shortHistory.nextExpiryAt(current.id, isPlayableShortId)",
            "function shortQueueForTransientTarget",
            "function refreshShortNavigationControls",
            "!canPreviousShort() ? \"disabled\" : \"\"",
            "!canNextShort() ? \"disabled\" : \"\"",
        ]:
            self.assertIn(marker, app_js)
        self.assertNotIn("recentShortHistory", app_js)
        self.assertNotIn("rememberRecentShortVideo", app_js)
        self.assertNotIn("recentShortBacktrackVideo", app_js)

    def test_watched_short_selected_from_history_opens_itself_and_can_be_backtracked(self):
        app_js = (ROOT / "app.js").read_text(encoding="utf-8")
        history_module = ROOT / "short-history.mjs"
        module_url = json.dumps(history_module.as_uri())
        script = f"""
          import {{ buildShortPlaybackQueue, createTransientDirectionalHistory }} from {module_url};
          const videos = [{{ id: "A" }}, {{ id: "B" }}, {{ id: "C" }}, {{ id: "D" }}];
          const hiddenIds = new Set(["A", "C"]);
          const isHidden = (id) => hiddenIds.has(id);
          const expect = (condition, message) => {{ if (!condition) throw new Error(message); }};

          const historyQueue = buildShortPlaybackQueue({{
            videos,
            requestedVideo: videos[0],
            isHidden,
            allowHiddenRequested: true,
          }});
          expect(historyQueue.map((item) => item.id).join(",") === "A,B,D", "History must open the watched Short that was clicked without leaking another hidden Short");

          const transient = createTransientDirectionalHistory({{ ttlMs: 10_000 }});
          transient.pushForNext(historyQueue[0].id);
          expect(transient.back(historyQueue[1].id)?.id === "A", "Previous immediately after Next must return to the clicked watched Short");

          const ignoredQueue = buildShortPlaybackQueue({{
            videos,
            requestedVideo: videos[2],
            isHidden,
            allowHiddenRequested: true,
          }});
          expect(ignoredQueue.map((item) => item.id).join(",") === "C,B,D", "Ignored view must replay its clicked Short without leaking watched items");

          const normalQueue = buildShortPlaybackQueue({{
            videos,
            requestedVideo: videos[0],
            isHidden,
            allowHiddenRequested: false,
          }});
          expect(normalQueue.map((item) => item.id).join(",") === "B,D", "Normal playback must keep watched and ignored Shorts hidden");
        """
        result = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        self.assertIn("buildShortPlaybackQueue", app_js)
        self.assertIn('state.view === "history" && isWatched(selectedVideo.id)', app_js)
        self.assertIn('state.view === "ignored" && isIgnored(selectedVideo.id)', app_js)
        self.assertIn("allowHiddenRequested", app_js)

    def test_ask_gemini_button_copies_prompt_and_opens_chat(self):
        app_js = (ROOT / "app.js").read_text(encoding="utf-8")
        index_html = (ROOT / "index.html").read_text(encoding="utf-8")
        style_css = (ROOT / "style.css").read_text(encoding="utf-8")

        for marker in [
            'const GEMINI_CHAT_URL = "https://gemini.google.com/app";',
            "const GEMINI_VIDEO_PROMPT",
            "full A to Z summary with topic-by-topic transcription from beginning to end",
            "function geminiPromptForVideo",
            "function geminiChatUrl",
            "target.searchParams.set(\"q\", prompt);",
            "target.searchParams.set(\"prompt\", prompt);",
            "function geminiButton",
            "data-gemini-id",
            "Ask Gemini",
            "shortGeminiButton",
            "function openGemini",
            "await copyText(prompt)",
            "const targetUrl = geminiChatUrl(prompt);",
            "openExternalWithoutOpener(targetUrl)",
            "event.target.closest(\"#shortGeminiButton\")",
            "openGemini(state.shortQueue[state.shortIndex]",
            "const geminiButtonElement = event.target.closest(\"[data-gemini-id]\")",
            "openGemini(video, geminiButtonElement)",
            "Gemini opened",
        ]:
            self.assertIn(marker, app_js)

        self.assertIn("gemini-button", style_css)
        self.assertIn("gemini-icon", style_css)
        self.assertIn("app.js?v=20260821-gemini-brief", index_html)
        self.assertIn("style.css?v=20260821-gemini-brief", index_html)

    def test_wheel_scroll_over_youtube_iframe_is_captured(self):
        app_js = (ROOT / "app.js").read_text(encoding="utf-8")
        style_css = (ROOT / "style.css").read_text(encoding="utf-8")

        for marker in [
            "function bindWheelCaptureOverlay",
            "function handlePlayerWheel",
            "function handleShortWheel",
            'data-wheel-capture="long"',
            'data-wheel-capture="short"',
            'data-wheel-side="left"',
            'data-wheel-side="right"',
            'bindWheelCaptureOverlay("long", handlePlayerWheel)',
            'bindWheelCaptureOverlay("short", handleShortWheel)',
            'event.target.closest("[data-wheel-capture]")',
            "Scroll on the left video edge",
            "Scroll on the right Short edge",
        ]:
            self.assertIn(marker, app_js)

        for marker in [
            ".wheel-capture-overlay",
            ".player-frame .wheel-capture-overlay",
            ".short-player .wheel-capture-overlay",
            "pointer-events: auto;",
            "touch-action: none;",
            'data-wheel-side="left"',
            'data-wheel-side="right"',
            "transform: translateY(-50%);",
        ]:
            self.assertIn(marker, style_css)

    def test_youtube_native_controls_are_not_covered_by_full_player_overlay(self):
        app_js = (ROOT / "app.js").read_text(encoding="utf-8")
        style_css = (ROOT / "style.css").read_text(encoding="utf-8")

        self.assertEqual(app_js.count('data-wheel-capture="long"'), 2)
        self.assertEqual(app_js.count('data-wheel-capture="short"'), 2)
        self.assertEqual(app_js.count('data-wheel-side="left"'), 2)
        self.assertEqual(app_js.count('data-wheel-side="right"'), 2)
        self.assertIn("document.querySelectorAll(`[data-wheel-capture=", app_js)
        for marker in [
            'id="shortPrevious"',
            'id="shortNext"',
            'event.target.closest("#shortPrevious")',
            'event.target.closest("#shortNext")',
        ]:
            self.assertIn(marker, app_js)

        overlay_rule = re.search(r"\.wheel-capture-overlay\s*\{(?P<body>.*?)\n\}", style_css, re.DOTALL)
        self.assertIsNotNone(overlay_rule)
        assert overlay_rule is not None
        overlay_css = overlay_rule.group("body")
        self.assertNotIn("inset: 0", overlay_css)
        self.assertNotIn("width: 100%", overlay_css)
        self.assertNotIn("height: 100%", overlay_css)
        self.assertIn("top: 50%", overlay_css)
        self.assertIn("transform: translateY(-50%)", overlay_css)
        self.assertRegex(overlay_css, r"width:\s*(?:2[0-9]|3[0-9]|4[0-4])px")
        self.assertIn("z-index: 2", overlay_css)
        self.assertIn('.wheel-capture-overlay[data-wheel-side="left"]', style_css)
        self.assertIn('.wheel-capture-overlay[data-wheel-side="right"]', style_css)
        self.assertRegex(
            style_css,
            r"\.short-action-stack\s*\{[^}]*position:\s*absolute;[^}]*z-index:\s*5;",
        )
        self.assertRegex(
            style_css,
            r"\.short-controls\s*\{[^}]*position:\s*absolute;[^}]*z-index:\s*6;",
        )

    def test_shorts_details_and_feed_manager_are_wired(self):
        app_js = (ROOT / "app.js").read_text(encoding="utf-8")
        style_css = (ROOT / "style.css").read_text(encoding="utf-8")
        index_html = (ROOT / "index.html").read_text(encoding="utf-8")
        float_html = (ROOT / "float.html").read_text(encoding="utf-8")
        workflow_path = ROOT / ".github/workflows/apply-feed-settings.yml"

        for marker in [
            "data/video-details.json",
            "data/feed-settings.json",
            "shortCommentsButton",
            "shortDescriptionButton",
            "addChannelRow",
            "function applyFeedSettings",
            "function repositoryIssuesNewUrl",
            "function initialViewFromUrl",
            "VALID_VIEWS",
            "repositoryUrl",
            "NEXAFEED_CONFIG_V1:GZIP_BASE64URL",
            "[YourTube Config] Apply feed settings",
            "applySearchInput",
            "data-quick-filter",
            "shortsCarousel",
            "data-carousel-scroll",
            "collapseRepeatedItems",
            "function goHome",
            "scrollToTop",
            "addEventListener(\"click\", goHome)",
            "nexafeed-liked-v1",
            "shortLikeButton",
            "toggleLikeCurrentShort",
            "aria-pressed",
            "updateLikedCount",
            "[\"liked\", \"Liked\"]",
            "state.view === \"liked\"",
            "No liked videos yet",
            "Liked Shorts",
            "function saveButton",
            "data-like-id",
            "function toggleLikeVideo",
            "function openCard",
            "function likedTools",
            "function exportLiked",
            "Export likes JSON",
            "Clear liked",
            "<a class=\"card-open\" href=",
            "function floatButton",
            "data-float-id",
            "function openFloatingVideo",
            "function floatingPopupUrl",
            "float.html",
            "function openDocumentPictureInPicture",
            "documentPictureInPicture?.requestWindow",
            "function openPopupFloatingPlayer",
            "nexafeedFloatingPlayer",
            "function openInlineFloatingPlayer",
            "floatingYoutubePlayer",
            "function createFloatingYoutubePlayer",
            "function destroyFloatingPlayer",
            "function youtubeOrigin",
            "widget_referrer",
            "referrerpolicy=\"strict-origin-when-cross-origin\"",
            "data-float-drag",
            "shortFloatButton",
            "NOTEBOOKLM_NEW_NOTEBOOK_URL",
            "function notebookLmButton",
            "data-notebooklm-id",
            "Chat With NBLM",
            "function notebookLmImportUrl",
            "function openNotebookLm",
            "function copyText",
            "function playerNavButton",
            "data-player-nav",
            "function navigatePlayer",
            "function playerNeighbor",
            "function playlistLongVideos",
            "PLAYER_WHEEL_THRESHOLD",
            "SHORT_WHEEL_THRESHOLD",
            "WATCHED_SKIP_THRESHOLD_SECONDS",
            "function watchedSecondsFor",
            "function finalizeVideoBeforeLeaving",
            "finalizeVideoBeforeLeaving(state.activeVideo",
            "finalizeVideoBeforeLeaving(current",
            "function shortPlaybackQueue",
            "function pruneWatchedShortQueue",
            "return buildShortPlaybackQueue({",
            "const selectedVideo = allShorts.find((item) => item.id === video?.id);",
            "const currentAfterPrune = state.shortQueue[state.shortIndex];",
            "All available Shorts are already watched",
            "return playableLongVideos().filter((item) => item.id === currentId || (!isWatched(item.id) && !isIgnored(item.id)));",
            "readJson(PROGRESS_KEY, {})[videoId]",
            "playerWheelDelta",
            "shortWheelDelta",
            "ArrowRight",
            "ArrowLeft",
        ]:
            self.assertIn(marker, app_js)
        self.assertNotIn("Like this Short on YouTube", app_js)
        for marker in [".short-drawer", ".short-action-stack", ".short-like.active", ".save-button", ".card-open", ".card-save", ".player-save", ".float-button", ".notebooklm-button", ".notebooklm-icon", ".player-nav-actions", ".player-nav-button", "#floatingRoot", ".in-page-float", ".float-titlebar", ".float-frame", ".float-frame > div", ".liked-tools", ".channel-editor-row", ".short-carousel", ".carousel-nav", "sidebar-collapsed", "text-decoration: none"]:
            self.assertIn(marker, style_css)
        self.assertIn("grid-template-columns: minmax(0, 1fr) minmax(340px, 380px);", style_css)
        self.assertIn("max-width: none;", style_css)
        self.assertNotIn("max-width: 1580px;", style_css)
        self.assertIn('id="brandButton" class="brand" href="./"', index_html)
        self.assertIn("YourTube - A personal YouTube Package", index_html)
        self.assertIn("Watch only those valuable for you", index_html)
        self.assertIn("style.css?v=20260821-gemini-brief", index_html)
        self.assertIn("app.js?v=20260821-gemini-brief", index_html)
        self.assertIn('aria-label="YourTube home"', index_html)
        self.assertIn('data-view="liked"', index_html)
        self.assertIn('id="likedCount"', index_html)
        for marker in [
            "YourTube Float",
            "floatingYoutubePlayer",
            "onYouTubeIframeAPIReady",
            "new YT.Player",
            "widget_referrer",
            "strict-origin-when-cross-origin",
            'id="previousButton"',
            'id="nextButton"',
            "function loadFloatingQueue",
            "function playRelative",
            "function updateNavigationButtons",
            "YT.PlayerState.ENDED",
            "loadVideoById",
            "float-next",
            "float-previous",
            "data/videos.json",
            ".float-nav",
        ]:
            self.assertIn(marker, float_html)
        self.assertTrue(workflow_path.is_file())
        workflow = workflow_path.read_text(encoding="utf-8")
        self.assertIn("issues:", workflow)
        self.assertIn("github.event.issue.author_association == 'OWNER'", workflow)
        self.assertIn("close-unauthorized", workflow)
        self.assertNotIn("github.event.issue.user.login == github.repository_owner", workflow)


class FeedSettingsTests(unittest.TestCase):
    def test_valid_settings_payload_is_normalized(self):
        settings = load_module("apply_feed_settings", ROOT / "scripts/apply_feed_settings.py")
        payload = {
            "channels": [
                {
                    "name": "New Channel",
                    "handle": "newchannel",
                    "url": "https://www.youtube.com/@newchannel",
                    "category": "AI",
                    "monitorLong": True,
                    "monitorShorts": False,
                    "priority": 2,
                }
            ],
            "keywords": [" AI agents ", "AI agents", "automation"],
            "topics": ["Artificial Intelligence"],
            "categories": ["AI coding"],
        }

        normalized = settings.validate_settings_payload(payload)

        self.assertEqual(normalized["channels"][0]["handle"], "@newchannel")
        self.assertEqual(normalized["channels"][0]["priority"], 2)
        self.assertEqual(normalized["keywords"], ["AI agents", "automation"])

    def test_rejects_non_string_discovery_terms(self):
        settings = load_module("apply_feed_settings_term_types", ROOT / "scripts/apply_feed_settings.py")
        payload = {
            "channels": [{"handle": "@validchannel", "monitorLong": True, "monitorShorts": False}],
            "keywords": [{"bad": "object"}],
        }
        with self.assertRaisesRegex(settings.SettingsValidationError, "keywords values must be strings"):
            settings.validate_settings_payload(payload)

    def test_rejects_duplicate_channels_and_oversized_compressed_payloads(self):
        settings = load_module("apply_feed_settings_security", ROOT / "scripts/apply_feed_settings.py")
        duplicate = {
            "channels": [
                {"handle": "@same", "monitorLong": True, "monitorShorts": False},
                {"handle": "@same", "monitorLong": False, "monitorShorts": True},
            ]
        }
        with self.assertRaisesRegex(settings.SettingsValidationError, "duplicate"):
            settings.validate_settings_payload(duplicate)

        oversized = json.dumps({"channels": [], "padding": "x" * 1_000_100}).encode("utf-8")
        token = base64.urlsafe_b64encode(gzip.compress(oversized)).decode("ascii").rstrip("=")
        marker = f"<!-- NEXAFEED_CONFIG_V1:GZIP_BASE64URL:{token} -->"
        with self.assertRaisesRegex(settings.SettingsValidationError, "decoded settings payload is too large"):
            settings.decode_issue_payload(marker)


class EnvironmentConfigTests(unittest.TestCase):
    def test_env_loader_keeps_shell_precedence_and_resolves_provider(self):
        env = load_module("nexafeed_env_test", ROOT / "scripts/nexafeed_env.py")
        keys = [
            "NEXAFEED_LLM_PROVIDER",
            "NEXAFEED_LLM_MODEL",
            "OPENROUTER_API_KEY",
            "NEXAFEED_LLM_API_KEY",
            "NEXAFEED_LLM_BASE_URL",
            "NEXAFEED_ENV_FILE",
        ]
        previous = {key: os.environ.get(key) for key in keys}
        try:
            for key in keys:
                os.environ.pop(key, None)
            os.environ["NEXAFEED_LLM_PROVIDER"] = "openrouter"
            with tempfile.TemporaryDirectory() as tmpdir:
                env_file = Path(tmpdir) / "nexafeed.env"
                env_file.write_text(
                    "NEXAFEED_LLM_PROVIDER=openai\n"
                    "NEXAFEED_LLM_MODEL=openrouter/test-model\n"
                    "OPENROUTER_API_KEY=private-test-value\n",
                    encoding="utf-8",
                )
                loaded = env.load_env_files(env_file, include_project=False, include_hermes=False)
                resolved = env.resolve_llm_config(required=True)

            self.assertEqual(loaded, [str(env_file)])
            self.assertEqual(os.environ["NEXAFEED_LLM_PROVIDER"], "openrouter")
            self.assertEqual(resolved["provider"], "openrouter")
            self.assertEqual(resolved["apiKeyName"], "OPENROUTER_API_KEY")
            self.assertTrue(resolved["apiKeyConfigured"])
            self.assertEqual(resolved["missing"], [])
            self.assertNotIn("private-test-value", json.dumps(resolved))
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_public_setup_files_are_wired(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        update_workflow = (ROOT / ".github/workflows/update-feed.yml").read_text(encoding="utf-8")
        deploy_workflow = (ROOT / ".github/workflows/deploy-pages.yml").read_text(encoding="utf-8")
        settings_workflow = (ROOT / ".github/workflows/apply-feed-settings.yml").read_text(encoding="utf-8")

        for marker in [
            "YourTube - A personal YouTube Package",
            "Watch only those valuable for you",
            "Hermes cron",
            "normal cron",
            "Codex",
            "Claude",
            "GitHub Actions",
            "NEXAFEED_LLM_PROVIDER",
            "NEXAFEED_REPOSITORY_URL",
            "NEXAFEED_TAGLINE",
            "NEXAFEED_BRANCH",
            "docs/AI_SETUP_PROMPT.md",
            "docs/screenshots/yourtube-home.png",
            "scripts/nexafeed_automation.py --pull-first --require-clean --publish",
        ]:
            self.assertIn(marker, readme)
        for marker in ["NEXAFEED_LLM_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "NEXAFEED_YT_DLP", "NEXAFEED_REPOSITORY_URL", "NEXAFEED_TAGLINE", "NEXAFEED_BRANCH"]:
            self.assertIn(marker, env_example)
        for marker in [".env", ".env.*", "!.env.example"]:
            self.assertIn(marker, gitignore)
        for marker in ["workflow_dispatch", "scripts/nexafeed_doctor.py", "scripts/nexafeed_automation.py", "deploy-pages"]:
            self.assertIn(marker, update_workflow)
        for marker in ["nexafeed-main-write", "nexafeed-pages"]:
            self.assertIn(marker, update_workflow)
        for marker in ["NEXAFEED_SITE_NAME", "NEXAFEED_TAGLINE", "NEXAFEED_REPOSITORY_URL", "NEXAFEED_TIMEZONE", "NEXAFEED_BRANCH", "OLLAMA_HOST", "WORKERS: ${{ inputs.workers }}", '--workers "$WORKERS"']:
            self.assertIn(marker, update_workflow)
        self.assertNotIn('--workers "${{ inputs.workers }}"', update_workflow)
        for email_secret in ["RESEND_API_KEY", "EMAIL_PASSWORD", "EMAIL_SMTP_HOST", "NEXAFEED_EMAIL_RECIPIENTS"]:
            self.assertNotIn(email_secret, update_workflow)
        for workflow in [update_workflow, deploy_workflow, settings_workflow]:
            self.assertIn("cp index.html style.css app.js short-history.mjs video-actions.mjs daily-archive.mjs float.html config.json _site/", workflow)
            for match in re.finditer(r"uses:\s+([^\s#]+)", workflow):
                self.assertRegex(match.group(1), r"@[0-9a-f]{40}$")
        self.assertIn("if [ -d docs ]; then cp -R docs _site/docs; fi", deploy_workflow)
        self.assertIn("if [ -d docs ]; then cp -R docs _site/docs; fi", settings_workflow)

        for public_file in ["LICENSE", "SECURITY.md", "docs/AI_SETUP_PROMPT.md", "docs/SCHEDULING.md"]:
            self.assertTrue((ROOT / public_file).is_file(), public_file)
        for screenshot in ["docs/screenshots/yourtube-home.png", "docs/screenshots/yourtube-shorts.png", "docs/screenshots/yourtube-settings.png"]:
            path = ROOT / screenshot
            self.assertTrue(path.is_file(), screenshot)
            self.assertGreater(path.stat().st_size, 1000, screenshot)


class EmailDeliveryTests(unittest.TestCase):
    def test_resend_uses_bearer_header_without_putting_secret_in_command_args(self):
        emailer = load_module("nexafeed_digest_email_resend_test", ROOT / "scripts/nexafeed_digest_email.py")
        secret = "private-resend-test-key"
        previous_env = {key: os.environ.get(key) for key in ["RESEND_API_KEY", "RESEND_FROM"]}
        captured = {}

        class FakeProcess:
            returncode = 0
            stdout = '{"id":"email-test-id"}'
            stderr = ""

        def fake_run(command, capture_output, text, timeout):
            captured["command"] = command
            config_path = Path(command[2])
            captured["config"] = config_path.read_text(encoding="utf-8")
            return FakeProcess()

        original_run = emailer.subprocess.run
        try:
            os.environ["RESEND_API_KEY"] = secret
            os.environ["RESEND_FROM"] = "YourTube <reports@example.com>"
            emailer.subprocess.run = fake_run
            result = emailer.send_resend("owner@example.com", "Subject", "<p>HTML</p>", "Text")
        finally:
            emailer.subprocess.run = original_run
            for key, value in previous_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        self.assertEqual(result, {"provider": "resend", "accepted": True, "id": "email-test-id"})
        self.assertIn(f'header = "Authorization: Bearer {secret}"', captured["config"])
        self.assertNotIn("Authorization: ***", captured["config"])
        self.assertNotIn(secret, " ".join(captured["command"]))

    def test_email_report_uses_configurable_timezone(self):
        emailer = load_module("nexafeed_digest_email_timezone_test", ROOT / "scripts/nexafeed_digest_email.py")
        previous = os.environ.get("NEXAFEED_TIMEZONE")
        try:
            os.environ["NEXAFEED_TIMEZONE"] = "UTC"
            timezone = emailer.configured_timezone({"timezone": "Asia/Dhaka"})
            report = emailer.build_report("morning", "https://example.com/", timezone)
        finally:
            if previous is None:
                os.environ.pop("NEXAFEED_TIMEZONE", None)
            else:
                os.environ["NEXAFEED_TIMEZONE"] = previous

        self.assertEqual(emailer.timezone_label(timezone), "UTC")
        self.assertEqual(report["summary"]["timezone"], "UTC")


class ProbePlanningTests(unittest.TestCase):
    def test_daily_archive_retains_all_items_from_thirty_bangladesh_calendar_days(self):
        updater = load_module("nexafeed_update_archive", ROOT / "scripts/nexafeed_update.py")
        now = updater.parse_datetime("2026-08-20T02:00:00Z")  # 08:00 in Asia/Dhaka
        self.assertEqual(updater.ARCHIVE_RETENTION_DAYS, 30)
        updater_source = (ROOT / "scripts/nexafeed_update.py").read_text(encoding="utf-8")
        self.assertNotIn("NEXAFEED_FEED_RETENTION_DAYS", updater_source)
        previous = [
            {"id": "keep-start", "title": "old", "publishedAt": "2026-06-01T00:00:00Z", "firstSeenAt": "2026-07-21T18:00:00Z", "source": "primary"},
            {"id": "drop-before", "publishedAt": "2026-08-20T01:00:00Z", "firstSeenAt": "2026-07-21T17:59:59Z", "source": "primary"},
            {"id": "keep-seen", "publishedAt": None, "firstSeenAt": "2026-07-22T00:00:00Z", "thumbnail": "https://i.ytimg.com/vi/keep-seen00/frame0.jpg?bad=1", "source": "secondary"},
        ]
        current = [
            {"id": "keep-start", "title": "fresh", "publishedAt": "2026-06-01T00:00:00Z", "firstSeenAt": "2026-07-21T18:00:00Z", "source": "primary"},
            {"id": "today-item", "publishedAt": "2025-01-01T00:00:00Z", "firstSeenAt": "2026-08-20T01:00:00Z", "source": "primary"},
            {"id": "future-item", "publishedAt": "2026-08-20T01:00:00Z", "firstSeenAt": "2026-08-20T18:00:00Z", "source": "primary"},
        ]

        retained = updater.merge_daily_archive_items(
            current,
            previous,
            now=now,
        )
        by_id = {item["id"]: item for item in retained}

        self.assertEqual(set(by_id), {"keep-start", "keep-seen", "today-item"})
        self.assertEqual(by_id["keep-start"]["title"], "fresh")
        self.assertEqual(by_id["keep-seen"]["thumbnail"], "https://i.ytimg.com/vi/keep-seen00/hqdefault.jpg")
        with self.assertRaises(TypeError):
            updater.merge_daily_archive_items(current, previous, now=now, retention_days=1)
        self.assertEqual(updater.bangladesh_date_key("2026-07-21T18:00:00Z"), "2026-07-22")
        self.assertEqual(updater.bangladesh_date_key("2026-08-20T01:00:00Z"), "2026-08-20")

        repeated_title_items = [
            {"id": "repeat-one", "title": "Same upload title", "channel": "Nexa", "publishedAt": "2026-08-20T01:00:00Z", "source": "primary", "priority": 1},
            {"id": "repeat-two", "title": "Same upload title", "channel": "Nexa", "publishedAt": "2026-08-20T00:00:00Z", "source": "primary", "priority": 1},
        ]
        ordered = updater.order_daily_archive_items(repeated_title_items)
        self.assertEqual([item["id"] for item in ordered], ["repeat-one", "repeat-two"])

    def test_thumbnail_urls_are_normalized_for_every_refresh(self):
        updater = load_module("nexafeed_update_thumbnails", ROOT / "scripts/nexafeed_update.py")
        self.assertEqual(
            updater.thumbnail_url(
                [{"url": "https://i.ytimg.com/vi/00kEcNby86c/frame0.jpg?usqp=bad", "width": 720}],
                "00kEcNby86c",
            ),
            "https://i.ytimg.com/vi/00kEcNby86c/hqdefault.jpg",
        )

    def test_comment_probe_command_is_opt_in(self):
        updater = load_module("nexafeed_update", ROOT / "scripts/nexafeed_update.py")
        setattr(updater, "yt_dlp_path", lambda: "yt-dlp")

        basic = updater.build_yt_dlp_command("dUHpFuUIyi0", include_comments=False, comment_limit=5)
        rich = updater.build_yt_dlp_command("dUHpFuUIyi0", include_comments=True, comment_limit=5)

        self.assertNotIn("--write-comments", basic)
        self.assertIn("--write-comments", rich)
        self.assertIn("youtube:player_client=web_embedded;max_comments=5,all,all,0", rich)
        self.assertIn("youtube:player_client=web_embedded", basic)
        self.assertTrue(rich[-1].endswith("dUHpFuUIyi0"))

    def test_yt_dlp_json_allows_raw_control_characters(self):
        updater = load_module("nexafeed_update_json", ROOT / "scripts/nexafeed_update.py")
        parsed = updater.parse_yt_dlp_json('{"description":"line one\u0001line two"}')
        self.assertEqual(parsed["description"], "line one\u0001line two")

    def test_missing_metadata_and_stale_short_comments_are_planned(self):
        updater = load_module("nexafeed_update", ROOT / "scripts/nexafeed_update.py")
        now = updater.parse_datetime("2026-07-27T12:00:00Z")
        items = [
            {"id": "newshort001", "type": "short"},
            {"id": "cachedshort", "type": "short"},
            {"id": "newlong0001", "type": "long"},
        ]
        details = {
            "items": {
                "cachedshort": {
                    "embedAllowed": True,
                    "checkedAt": "2026-07-27T11:00:00Z",
                    "commentsFetchedAt": "2026-07-25T11:00:00Z",
                }
            }
        }
        config = {
            "richMetadataTtlHours": 168,
            "commentsTtlHours": 24,
            "commentsMaxVideos": 10,
            "richMetadataMaxPerRun": 20,
        }

        plan = updater.plan_detail_probes(items, details, now, config)

        self.assertEqual(
            [(entry["video"]["id"], entry["includeComments"]) for entry in plan],
            [("newshort001", True), ("cachedshort", True), ("newlong0001", False)],
        )


class RichMetadataTests(unittest.TestCase):
    def test_normalizes_description_comments_and_embed_status(self):
        updater = load_module("nexafeed_update", ROOT / "scripts/nexafeed_update.py")
        raw = {
            "playable_in_embed": True,
            "availability": "public",
            "description": "A useful description\n#ai",
            "comment_count": 12,
            "like_count": 319,
            "comments": [
                {
                    "id": "comment-1",
                    "author": "Viewer",
                    "text": "Very useful!",
                    "like_count": 7,
                    "timestamp": 1_700_000_000,
                    "author_thumbnail": "https://example.com/avatar.jpg",
                    "is_pinned": True,
                }
            ],
        }

        detail = updater.normalize_yt_dlp_details(raw, "2026-07-27T12:00:00Z")

        self.assertTrue(detail["embedAllowed"])
        self.assertEqual(detail["description"], "A useful description\n#ai")
        self.assertEqual(detail["commentCount"], 12)
        self.assertEqual(detail["likeCount"], 319)
        self.assertEqual(detail["comments"][0]["author"], "Viewer")
        self.assertEqual(detail["comments"][0]["likeCount"], 7)
        self.assertEqual(detail["comments"][0]["publishedAt"], "2023-11-14T22:13:20Z")
        self.assertTrue(detail["comments"][0]["isPinned"])
        self.assertEqual(detail["checkedAt"], "2026-07-27T12:00:00Z")

    def test_comment_payload_is_bounded_even_if_extractor_returns_more(self):
        updater = load_module("nexafeed_update_bounded", ROOT / "scripts/nexafeed_update.py")
        raw = {
            "playable_in_embed": True,
            "comments": [
                {"id": f"c-{index}", "author": "Viewer", "text": f"Comment {index}"}
                for index in range(25)
            ],
        }

        detail = updater.normalize_yt_dlp_details(raw, "2026-07-27T12:00:00Z", comment_limit=8)

        self.assertEqual(len(detail["comments"]), 8)

    def test_only_permanent_yt_dlp_failures_are_marked_unavailable(self):
        updater = load_module("nexafeed_update_failures", ROOT / "scripts/nexafeed_update.py")
        permanent = updater.classify_yt_dlp_failure(
            "ERROR: [youtube] abc123: Private video. Sign in if you have been granted access.",
            "2026-07-27T12:00:00Z",
        )
        transient = updater.classify_yt_dlp_failure(
            "ERROR: HTTP Error 429: Too Many Requests",
            "2026-07-27T12:00:00Z",
        )

        self.assertFalse(permanent["embedAllowed"])
        self.assertEqual(permanent["availability"], "private")
        self.assertIsNone(transient)


class EmbedFilteringTests(unittest.TestCase):
    def test_explicitly_unembeddable_items_are_removed(self):
        updater = load_module("nexafeed_update", ROOT / "scripts/nexafeed_update.py")
        items = [
            {"id": "blocked0001", "title": "Blocked Short", "type": "short"},
            {"id": "allowed0001", "title": "Allowed Short", "type": "short"},
            {"id": "unknown0001", "title": "Unknown Short", "type": "short"},
        ]
        details = {
            "items": {
                "blocked0001": {"embedAllowed": False},
                "allowed0001": {"embedAllowed": True},
            }
        }

        filtered, blocked = updater.enrich_and_filter_items(items, details)

        self.assertEqual([item["id"] for item in filtered], ["allowed0001", "unknown0001"])
        self.assertEqual(blocked, 1)
        self.assertTrue(filtered[0]["embedAllowed"])
        self.assertNotIn("embedAllowed", filtered[1])

    def test_repeated_titles_from_same_channel_are_collapsed(self):
        updater = load_module("nexafeed_update_duplicate_collapse", ROOT / "scripts/nexafeed_update.py")
        items = [
            {
                "id": "lowviews001",
                "type": "short",
                "title": "The World's First AI Coding Keyboard? #AI #OpenAI #Coding",
                "channelId": "UC-test",
                "channel": "BPro Club",
                "viewCount": 15,
                "source": "primary",
                "priority": 1,
                "publishedAt": "2026-07-27T09:00:00Z",
            },
            {
                "id": "highviews01",
                "type": "short",
                "title": "The World's First AI Coding Keyboard? #AI #OpenAI #Coding",
                "channelId": "UC-test",
                "channel": "BPro Club",
                "viewCount": 399,
                "source": "primary",
                "priority": 1,
                "publishedAt": "2026-07-27T08:00:00Z",
            },
            {
                "id": "different01",
                "type": "short",
                "title": "A different AI coding update",
                "channelId": "UC-test",
                "channel": "BPro Club",
                "viewCount": 1,
                "source": "primary",
                "priority": 1,
                "publishedAt": "2026-07-27T08:00:00Z",
            },
        ]

        collapsed = updater.collapse_repeated_items(items)

        self.assertEqual([item["id"] for item in collapsed], ["highviews01", "different01"])


if __name__ == "__main__":
    unittest.main()
