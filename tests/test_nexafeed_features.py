#!/usr/bin/env python3
"""Regression tests for NexaFeed rich metadata and owner-managed settings."""
from __future__ import annotations

import base64
import gzip
import importlib.util
import json
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
        workflow_path = ROOT / ".github/workflows/apply-feed-settings.yml"

        for marker in [
            "data/video-details.json",
            "data/feed-settings.json",
            "shortCommentsButton",
            "shortDescriptionButton",
            "addChannelRow",
            "applyFeedSettings",
            "NEXAFEED_CONFIG_V1:GZIP_BASE64URL",
            "applySearchInput",
            "data-quick-filter",
            "shortsCarousel",
            "data-carousel-scroll",
            "collapseRepeatedItems",
        ]:
            self.assertIn(marker, app_js)
        for marker in [".short-drawer", ".short-action-stack", ".channel-editor-row", ".short-carousel", ".carousel-nav", "sidebar-collapsed"]:
            self.assertIn(marker, style_css)
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
