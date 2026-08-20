#!/usr/bin/env python3
"""Structural and data-integrity verification for the YourTube static application."""
from __future__ import annotations

import csv
import datetime as dt
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []
UTC = dt.timezone.utc
BD_TZ = dt.timezone(dt.timedelta(hours=6))


def fail(message: str) -> None:
    errors.append(message)


def parse_datetime(value: object) -> dt.datetime | None:
    try:
        text = str(value or "").strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = dt.datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except Exception:
        return None


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
    "short-history.mjs",
    "video-actions.mjs",
    "daily-archive.mjs",
    "float.html",
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
    "LICENSE",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "CHANGELOG.md",
    "docs/AI_SETUP_PROMPT.md",
    "docs/SCHEDULING.md",
    "docs/screenshots/yourtube-home.png",
    "docs/screenshots/yourtube-shorts.png",
    "docs/screenshots/yourtube-settings.png",
]
for relative in required_files:
    if not (ROOT / relative).is_file():
        fail(f"missing {relative}")

config = load_json("config.json")
if config.get("siteName") != "YourTube":
    fail("config.json siteName must be YourTube for the public release")
if config.get("tagline") != "Watch only those valuable for you":
    fail("config.json tagline must match the public release tagline")
if not str(config.get("repositoryUrl") or "").startswith("https://github.com/"):
    fail("config.json repositoryUrl must point to the GitHub repository")
if int(config.get("feedRetentionDays", 0)) != 30:
    fail("config.json feedRetentionDays must preserve exactly 30 calendar days")
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
if feed.get("schemaVersion") != 4:
    fail("feed schemaVersion must be 4 for the daily archive")
if feed.get("archiveRetentionDays") != 30:
    fail("feed archiveRetentionDays must be exactly 30")
if feed.get("archiveTimezone") != "Asia/Dhaka":
    fail("feed archiveTimezone must be Asia/Dhaka")
feed_updated_at = parse_datetime(feed.get("updatedAt"))
archive_end = feed_updated_at.astimezone(BD_TZ).date() if feed_updated_at else None
archive_cutoff = (archive_end - dt.timedelta(days=29)) if archive_end else None
if not items:
    fail("feed has no video items")
if len(ids) != len(set(ids)):
    fail("duplicate video IDs found")
if feed.get("primaryChannels") != len(channels):
    fail("feed primaryChannels does not match configured channels")
if feed.get("siteName") != config.get("siteName"):
    fail("feed siteName does not match config.json")
if feed.get("tagline") != config.get("tagline"):
    fail("feed tagline does not match config.json")
if feed.get("repositoryUrl") != config.get("repositoryUrl"):
    fail("feed repositoryUrl does not match config.json")
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
    thumbnail = str(item.get("thumbnail") or "")
    if "frame0.jpg" in thumbnail or "?" in thumbnail:
        fail(f"item {item.get('id')} has an unnormalized thumbnail URL")
    collected_at = parse_datetime(item.get("firstSeenAt")) or parse_datetime(item.get("publishedAt"))
    if not collected_at:
        fail(f"item {item.get('id')} has no valid collection timestamp")
    elif archive_cutoff and collected_at.astimezone(BD_TZ).date() < archive_cutoff:
        fail(f"item {item.get('id')} is older than the 30-day collection archive")
    elif archive_end and collected_at.astimezone(BD_TZ).date() > archive_end:
        fail(f"item {item.get('id')} is newer than the feed collection date")

stats = feed.get("stats") or {}
if stats.get("total") != len(items):
    fail("stats.total does not match item count")
if stats.get("longVideos") != sum(1 for item in items if item.get("type") == "long"):
    fail("long video stat does not match")
if stats.get("shorts") != sum(1 for item in items if item.get("type") == "short"):
    fail("Shorts stat does not match")
if stats.get("primary") != sum(1 for item in items if item.get("source") == "primary"):
    fail("primary source stat does not match")
if stats.get("secondary") != sum(1 for item in items if item.get("source") == "secondary"):
    fail("secondary source stat does not match")

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
    if coverage < 0.60:
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
short_history_js = (ROOT / "short-history.mjs").read_text(encoding="utf-8")
video_actions_js = (ROOT / "video-actions.mjs").read_text(encoding="utf-8")
daily_archive_js = (ROOT / "daily-archive.mjs").read_text(encoding="utf-8")
float_html = (ROOT / "float.html").read_text(encoding="utf-8")
readme = (ROOT / "README.md").read_text(encoding="utf-8")
ai_prompt_doc = (ROOT / "docs/AI_SETUP_PROMPT.md").read_text(encoding="utf-8")
scheduling_doc = (ROOT / "docs/SCHEDULING.md").read_text(encoding="utf-8")
security_doc = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
contributing_doc = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
changelog_doc = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
update_workflow = (ROOT / ".github/workflows/update-feed.yml").read_text(encoding="utf-8")
deploy_workflow = (ROOT / ".github/workflows/deploy-pages.yml").read_text(encoding="utf-8")
settings_workflow = (ROOT / ".github/workflows/apply-feed-settings.yml").read_text(encoding="utf-8")
digest_email = (ROOT / "scripts/nexafeed_digest_email.py").read_text(encoding="utf-8")
for needle in ["style.css", "app.js", "youtube.com/iframe_api", 'data-view="archive"']:
    if needle not in index_html:
        fail(f"index missing {needle}")
for needle in [
    "YourTube - A personal YouTube Package",
    "Watch only those valuable for you",
    "og:image",
    "twitter:card",
    "canonical",
    "docs/screenshots/yourtube-home.png",
]:
    if needle not in index_html:
        fail(f"index missing public-release marker {needle}")
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
    "repositoryIssuesNewUrl",
    "[YourTube Config] Apply feed settings",
    "archiveDateToolbar",
    "dailyExportPayload",
    "copyDailyExport",
]:
    if needle not in app_js:
        fail(f"app missing behavior marker {needle}")
for needle in ["ARCHIVE_RETENTION_DAYS = 30", "dailyExportUrls", 'contentTrust: "untrusted-public-data"']:
    if needle not in daily_archive_js:
        fail(f"daily archive module missing behavior marker {needle}")

for needle in [".env", ".env.*", "!.env.example"]:
    if needle not in gitignore:
        fail(f"gitignore missing env guard {needle}")
for needle in ["NEXAFEED_LLM_PROVIDER", "NEXAFEED_LLM_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "NEXAFEED_REPOSITORY_URL", "NEXAFEED_TAGLINE", "NEXAFEED_BRANCH"]:
    if needle not in env_example:
        fail(f"env example missing provider key {needle}")
for needle in [
    "scripts/nexafeed_automation.py",
    "scripts/nexafeed_doctor.py",
    "workflow_dispatch",
    "deploy-pages",
    "nexafeed-main-write",
    "nexafeed-pages",
    "if [ -d docs ]; then cp -R docs _site/docs; fi",
    "NEXAFEED_SITE_NAME",
    "NEXAFEED_TAGLINE",
    "NEXAFEED_REPOSITORY_URL",
    "NEXAFEED_TIMEZONE",
    "NEXAFEED_BRANCH",
    "OLLAMA_HOST",
    "WORKERS: ${{ inputs.workers }}",
    '--workers "$WORKERS"',
]:
    if needle not in update_workflow:
        fail(f"update workflow missing {needle}")
if '--workers "${{ inputs.workers }}"' in update_workflow:
    fail("update workflow interpolates workers input directly into shell")
for needle in ["RESEND_API_KEY", "EMAIL_PASSWORD", "EMAIL_SMTP_HOST", "NEXAFEED_EMAIL_RECIPIENTS"]:
    if needle in update_workflow:
        fail(f"update workflow exposes email-only secret {needle}")
for workflow_name, workflow in {
    "deploy-pages.yml": deploy_workflow,
    "apply-feed-settings.yml": settings_workflow,
    "update-feed.yml": update_workflow,
}.items():
    if "daily-archive.mjs" not in workflow:
        fail(f"{workflow_name} deployment artifact omits daily-archive.mjs")
    for match in re.finditer(r"uses:\s+([^\s#]+)", workflow):
        if not re.search(r"@[0-9a-f]{40}$", match.group(1)):
            fail(f"{workflow_name} action is not SHA pinned: {match.group(1)}")
for needle in [
    "YourTube - A personal YouTube Package",
    "Watch only those valuable for you",
    "docs/AI_SETUP_PROMPT.md",
    "docs/screenshots/yourtube-home.png",
    "Hermes cron",
    "normal cron",
    "Codex",
    "Claude",
    "GitHub Actions",
    "NEXAFEED_LLM_PROVIDER",
    "NEXAFEED_REPOSITORY_URL",
    "NEXAFEED_TAGLINE",
    "NEXAFEED_BRANCH",
]:
    if needle not in readme:
        fail(f"README missing public setup marker {needle}")

for needle in ["ZoneInfo", "configured_timezone", "NEXAFEED_TIMEZONE", "timezone"]:
    if needle not in digest_email:
        fail(f"digest email missing timezone marker {needle}")
if "Authorization: ***" in digest_email:
    fail("digest email keeps misleading literal Authorization mask")

for relative in ["docs/screenshots/yourtube-home.png", "docs/screenshots/yourtube-shorts.png", "docs/screenshots/yourtube-settings.png"]:
    path = ROOT / relative
    if path.is_file() and path.stat().st_size < 1000:
        fail(f"screenshot file looks too small: {relative}")

public_text = "\n".join([index_html, app_js, short_history_js, video_actions_js, daily_archive_js, float_html, json.dumps(config), readme, ai_prompt_doc, scheduling_doc, security_doc, contributing_doc, changelog_doc, env_example, update_workflow, deploy_workflow, settings_workflow])
for suspicious in ["ghp_", "github_pat_", "smtp_password"]:
    if suspicious in public_text:
        fail(f"possible private marker in public files: {suspicious}")
for pattern in [
    r"AIza[0-9A-Za-z_-]{20,}",
    r"sk-[0-9A-Za-z_-]{20,}",
    r"xox[baprs]-[0-9A-Za-z-]{20,}",
    r"/Users/[A-Za-z0-9._-]+",
    r"/Volumes/[A-Za-z0-9._ -]+",
]:
    if re.search(pattern, public_text):
        fail(f"possible credential pattern in public files: {pattern}")

if errors:
    print("YourTube verification failed:", file=sys.stderr)
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
