#!/usr/bin/env python3
"""Structural and data-integrity verification for the NexaFeed static application."""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []


def fail(message: str) -> None:
    errors.append(message)


def load_json(relative: str) -> dict:
    try:
        value = json.loads((ROOT / relative).read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"invalid {relative}: {exc}")
        return {}
    if not isinstance(value, dict):
        fail(f"{relative} root must be an object")
        return {}
    return value


required_files = [
    "index.html",
    "style.css",
    "app.js",
    "config.json",
    ".env.example",
    ".github/workflows/deploy-pages.yml",
    ".github/workflows/apply-feed-settings.yml",
    ".github/workflows/update-feed.yml",
    "data/channels.csv",
    "data/original-channel-categories.csv",
    "data/videos.json",
    "data/video-details.json",
    "data/feed-settings.json",
    "data/discovery-log.json",
    "scripts/nexafeed_env.py",
    "scripts/nexafeed_automation.py",
    "scripts/nexafeed_doctor.py",
]
for relative in required_files:
    if not (ROOT / relative).is_file():
        fail(f"missing {relative}")

config = load_json("config.json")
with (ROOT / "data/channels.csv").open(encoding="utf-8-sig", newline="") as handle:
    channels = list(csv.DictReader(handle))
handles = {(row.get("Handle") or "").strip().lower() for row in channels}
if not 1 <= len(channels) <= 100:
    fail(f"configured channel count must be 1-100, found {len(channels)}")
if "" in handles:
    fail("blank channel handle found")
if len(handles) != len(channels):
    fail("duplicate channel handles found")
for row in channels:
    monitor_long = (row.get("Monitor Long") or "yes").lower() == "yes"
    monitor_shorts = (row.get("Monitor Shorts") or "yes").lower() == "yes"
    if not monitor_long and not monitor_shorts:
        fail(f"channel monitors neither content type: {row.get('Handle')}")

feed = load_json("data/videos.json")
details = load_json("data/video-details.json")
settings = load_json("data/feed-settings.json")
items = feed.get("items") or []
ids = [item.get("id") for item in items if isinstance(item, dict)]
if not items:
    fail("feed has no video items")
if len(ids) != len(set(ids)):
    fail("duplicate video IDs found")
if feed.get("primaryChannels") != len(channels):
    fail("feed primaryChannels does not match configured channels")
health = feed.get("health") or {}
if health.get("channelsRequested") != len(channels):
    fail("feed health channelsRequested does not match configured channels")

required_item_fields = {"id", "type", "title", "channel", "thumbnail", "publishedAt", "source", "url", "firstSeenAt"}
video_id_re = re.compile(r"^[0-9A-Za-z_-]{11}$")
for index, item in enumerate(items):
    if not isinstance(item, dict):
        fail(f"item {index} is not an object")
        continue
    missing = required_item_fields - set(item)
    if missing:
        fail(f"item {index} missing {sorted(missing)}")
    if item.get("type") not in {"long", "short"}:
        fail(f"item {item.get('id')} has invalid type")
    if item.get("source") not in {"primary", "secondary"}:
        fail(f"item {item.get('id')} has invalid source")
    if item.get("source") == "primary" and (item.get("handle") or "").lower() not in handles:
        fail(f"primary item came from an unconfigured handle: {item.get('handle')}")
    if not video_id_re.fullmatch(str(item.get("id") or "")):
        fail(f"invalid YouTube video id: {item.get('id')}")
    if item.get("embedAllowed") is False:
        fail(f"explicitly blocked video leaked into feed: {item.get('id')}")

stats = feed.get("stats") or {}
if stats.get("total") != len(items):
    fail("stats.total does not match item count")
if stats.get("longVideos") != sum(1 for item in items if item.get("type") == "long"):
    fail("long video stat does not match")
if stats.get("shorts") != sum(1 for item in items if item.get("type") == "short"):
    fail("Shorts stat does not match")

settings_channels = settings.get("channels") or []
if len(settings_channels) != len(channels):
    fail("feed-settings channel count does not match channels.csv")
settings_handles = {(row.get("handle") or "").lower() for row in settings_channels if isinstance(row, dict)}
if settings_handles != handles:
    fail("feed-settings handles do not match channels.csv")
for name in ("keywords", "topics", "categories"):
    if settings.get(name, []) != config.get(name, []):
        fail(f"feed-settings {name} do not match config.json")

detail_items = details.get("items") or {}
if not isinstance(detail_items, dict):
    fail("video-details items must be an object")
    detail_items = {}
if items:
    covered = sum(1 for item in items if item.get("id") in detail_items)
    coverage = covered / len(items)
    if coverage < 0.80:
        fail(f"rich metadata coverage too low: {covered}/{len(items)}")
for video_id, detail in detail_items.items():
    if not video_id_re.fullmatch(str(video_id)) or not isinstance(detail, dict):
        fail(f"invalid video-details entry: {video_id}")
        continue
    comments = detail.get("comments")
    if comments is not None and (not isinstance(comments, list) or len(comments) > int(config.get("commentsPerVideo", 8))):
        fail(f"invalid bounded comments for {video_id}")

index_html = (ROOT / "index.html").read_text(encoding="utf-8")
app_js = (ROOT / "app.js").read_text(encoding="utf-8")
readme = (ROOT / "README.md").read_text(encoding="utf-8")
env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
update_workflow = (ROOT / ".github/workflows/update-feed.yml").read_text(encoding="utf-8")
for needle in ["style.css", "app.js", "youtube.com/iframe_api"]:
    if needle not in index_html:
        fail(f"index missing {needle}")
for needle in [
    "WATCHED_KEY",
    "PROGRESS_KEY",
    "autoplayToggle",
    "nextShort",
    "data/videos.json",
    "data/video-details.json",
    "data/feed-settings.json",
    "shortCommentsButton",
    "applyFeedSettings",
]:
    if needle not in app_js:
        fail(f"app missing behavior marker {needle}")

for needle in [".env", ".env.*", "!.env.example"]:
    if needle not in gitignore:
        fail(f"gitignore missing env guard {needle}")
for needle in ["NEXAFEED_LLM_PROVIDER", "NEXAFEED_LLM_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"]:
    if needle not in env_example:
        fail(f"env example missing provider key {needle}")
for needle in ["scripts/nexafeed_automation.py", "scripts/nexafeed_doctor.py", "workflow_dispatch", "deploy-pages"]:
    if needle not in update_workflow:
        fail(f"update workflow missing {needle}")
for needle in ["Hermes cron", "normal cron", "Codex", "Claude", "GitHub Actions", "NEXAFEED_LLM_PROVIDER"]:
    if needle not in readme:
        fail(f"README missing public setup marker {needle}")

public_text = "\n".join([index_html, app_js, json.dumps(config), readme, env_example, update_workflow])
for suspicious in ["ghp_", "github_pat_", "smtp_password", "/Volumes/T7 Shield", "/Users/developerjillur"]:
    if suspicious in public_text:
        fail(f"possible private marker in public files: {suspicious}")
for pattern in [r"AIza[0-9A-Za-z_-]{20,}", r"sk-[0-9A-Za-z_-]{20,}", r"xox[baprs]-[0-9A-Za-z-]{20,}"]:
    if re.search(pattern, public_text):
        fail(f"possible credential pattern in public files: {pattern}")

if errors:
    print("NexaFeed verification failed:", file=sys.stderr)
    for error in errors:
        print(f"- {error}", file=sys.stderr)
    raise SystemExit(1)

print(json.dumps({
    "ok": True,
    "channels": len(channels),
    "items": len(items),
    "longVideos": stats.get("longVideos"),
    "shorts": stats.get("shorts"),
    "primary": stats.get("primary"),
    "secondary": stats.get("secondary"),
    "details": len(detail_items),
    "channelsChecked": health.get("channelsChecked"),
}, ensure_ascii=False))
