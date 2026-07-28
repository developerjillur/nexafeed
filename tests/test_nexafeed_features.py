#!/usr/bin/env python3
"""Regression tests for YourTube rich metadata and owner-managed settings."""
from __future__ import annotations

import base64
import gzip
import importlib.util
import json
import os
import re
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
            "class=\"card-open\" type=\"button\"",
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
            "const MINIMUM_MANUAL_SWITCH_WATCH_SECONDS = 5;",
            "function watchedSecondsFor",
            "function markVideoWatchedAfterMinimum",
            "markVideoWatchedAfterMinimum(state.activeVideo)",
            "markVideoWatchedAfterMinimum(current)",
            "function shortPlaybackQueue",
            "function pruneWatchedShortQueue",
            "function nextUnwatchedShortAfter",
            "const selectedVideo = allShorts.find((item) => item.id === video?.id);",
            "const currentAfterPrune = state.shortQueue[state.shortIndex];",
            "All available Shorts are already watched",
            "return playableLongVideos().filter((item) => item.id === currentId || !isWatched(item.id));",
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
        self.assertIn("style.css?v=20260728-yourtube-release", index_html)
        self.assertIn("app.js?v=20260728-yourtube-release", index_html)
        self.assertIn('aria-label="YourTube home"', index_html)
        self.assertIn('data-view="liked"', index_html)
        self.assertIn('id="likedCount"', index_html)
        for marker in ["YourTube Float", "floatingYoutubePlayer", "onYouTubeIframeAPIReady", "new YT.Player", "widget_referrer", "strict-origin-when-cross-origin"]:
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
            for match in re.finditer(r"uses:\s+([^\s#]+)", workflow):
                self.assertRegex(match.group(1), r"@[0-9a-f]{40}$")
        self.assertIn("cp index.html style.css app.js float.html config.json _site/", deploy_workflow)
        self.assertIn("if [ -d docs ]; then cp -R docs _site/docs; fi", deploy_workflow)
        self.assertIn("cp index.html style.css app.js float.html config.json _site/", settings_workflow)
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
