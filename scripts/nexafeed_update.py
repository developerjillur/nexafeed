#!/usr/bin/env python3
"""Refresh NexaFeed from public YouTube pages and optionally publish it.

The collector intentionally uses public RSS/channel/search pages instead of a
YouTube Data API key. Primary channels come only from data/channels.csv.
Keyword/topic/category discovery is secondary and rotated once per run.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import csv
import datetime as dt
import fcntl
import html
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
CONFIG_PATH = ROOT / "config.json"
CHANNELS_PATH = DATA_DIR / "channels.csv"
VIDEOS_PATH = DATA_DIR / "videos.json"
DETAILS_PATH = DATA_DIR / "video-details.json"
SETTINGS_PATH = DATA_DIR / "feed-settings.json"
CACHE_PATH = DATA_DIR / "channel-cache.json"
DISCOVERY_PATH = DATA_DIR / "discovery-log.json"
LOCK_PATH = Path("/tmp/nexafeed-update.lock")

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36 "
    "NexaFeed/2.0"
)
ATOM = "{http://www.w3.org/2005/Atom}"
YT = "{http://www.youtube.com/xml/schemas/2015}"
MEDIA = "{http://search.yahoo.com/mrss/}"
UTC = dt.timezone.utc
BD_TZ = dt.timezone(dt.timedelta(hours=6))
DETAIL_PROBE_LOCK = threading.Lock()
DETAIL_LAST_STARTED = 0.0


def utc_now() -> dt.datetime:
    return dt.datetime.now(UTC)


def iso_utc(value: dt.datetime | None = None) -> str:
    value = value or utc_now()
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_datetime(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = dt.datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except Exception:
        return None


def load_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def fetch_text(url: str, timeout: int = 45, attempts: int = 3) -> str:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": UA,
                    "Accept-Language": "en-US,en;q=0.9,bn;q=0.7",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = response.read()
                charset = response.headers.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace")
        except Exception as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Fetch failed for {url}: {last_error}")


def extract_channel_id(text: str) -> str | None:
    patterns = [
        r'"externalId"\s*:\s*"(UC[0-9A-Za-z_-]{20,})"',
        r'"channelId"\s*:\s*"(UC[0-9A-Za-z_-]{20,})"',
        r'"browseId"\s*:\s*"(UC[0-9A-Za-z_-]{20,})"',
        r'<meta\s+itemprop="channelId"\s+content="(UC[0-9A-Za-z_-]{20,})"',
        r'youtube\.com/channel/(UC[0-9A-Za-z_-]{20,})',
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return None


def initial_data(text: str) -> dict[str, Any]:
    match = re.search(r"(?:var\s+)?ytInitialData\s*=\s*", text)
    if not match:
        raise RuntimeError("ytInitialData was not found")
    value, _ = json.JSONDecoder().raw_decode(text[match.end() :])
    if not isinstance(value, dict):
        raise RuntimeError("ytInitialData was not an object")
    return value


def collect_key(value: Any, key: str) -> list[Any]:
    output: list[Any] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for name, child in node.items():
                if name == key:
                    output.append(child)
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)
    return output


def nested(value: Any, *keys: Any, default: Any = None) -> Any:
    current = value
    try:
        for key in keys:
            current = current[key]
        return current
    except (KeyError, IndexError, TypeError):
        return default


def first_json_field(text: str, fields: list[str]) -> str | None:
    for field in fields:
        match = re.search(
            r'"' + re.escape(field) + r'"\s*:\s*"((?:\\.|[^"\\])*)"',
            text,
            flags=re.S,
        )
        if match:
            try:
                return json.loads('"' + match.group(1) + '"')
            except Exception:
                return match.group(1)
    return None


def meta_content(text: str, name: str) -> str | None:
    safe = re.escape(name)
    for pattern in [
        rf'<meta\s+(?:property|name)="{safe}"\s+content="([^"]*)"',
        rf'<meta\s+content="([^"]*)"\s+(?:property|name)="{safe}"',
    ]:
        match = re.search(pattern, text, flags=re.I | re.S)
        if match:
            return html.unescape(match.group(1)).strip()
    return None


def parse_count(text: str | None) -> int | None:
    if not text:
        return None
    cleaned = html.unescape(text).lower().replace(",", "").strip()
    if "no views" in cleaned:
        return 0
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(billion|million|thousand|b|m|k)?", cleaned)
    if not match:
        return None
    number = float(match.group(1))
    unit = match.group(2) or ""
    multipliers = {
        "billion": 1_000_000_000,
        "b": 1_000_000_000,
        "million": 1_000_000,
        "m": 1_000_000,
        "thousand": 1_000,
        "k": 1_000,
    }
    return int(number * multipliers.get(unit, 1))


def format_views(value: int | None) -> str:
    if value is None:
        return "Views unavailable"
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}B views"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M views"
    if value >= 1_000:
        return f"{value / 1_000:.1f}K views"
    return f"{value:,} views"


def duration_seconds(text: str | None) -> int | None:
    if not text:
        return None
    parts = text.strip().split(":")
    if not all(part.isdigit() for part in parts):
        return None
    total = 0
    for part in parts:
        total = total * 60 + int(part)
    return total


def format_duration(seconds: int | None, is_short: bool = False) -> str:
    if seconds is None:
        return "Short" if is_short else "Video"
    hours, remainder = divmod(max(0, int(seconds)), 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def relative_time_to_iso(label: str | None, now: dt.datetime) -> str | None:
    if not label:
        return None
    text = label.lower().replace("streamed", "").replace("premiered", "").strip()
    if text in {"just now", "now"}:
        return iso_utc(now)
    match = re.search(r"(\d+)\s+(second|minute|hour|day|week|month|year)s?\s+ago", text)
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2)
    seconds = {
        "second": 1,
        "minute": 60,
        "hour": 3600,
        "day": 86400,
        "week": 604800,
        "month": 2592000,
        "year": 31536000,
    }[unit]
    return iso_utc(now - dt.timedelta(seconds=amount * seconds))


def thumbnail_url(sources: Any, fallback_id: str) -> str:
    if isinstance(sources, list) and sources:
        best = max(
            (source for source in sources if isinstance(source, dict) and source.get("url")),
            key=lambda source: int(source.get("width") or 0),
            default=None,
        )
        if best:
            return html.unescape(str(best["url"]))
    return f"https://i.ytimg.com/vi/{fallback_id}/hqdefault.jpg"


def parse_video_tab(text: str, now: dt.datetime, limit: int) -> list[dict[str, Any]]:
    data = initial_data(text)
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for model in collect_key(data, "lockupViewModel"):
        if not isinstance(model, dict) or model.get("contentType") != "LOCKUP_CONTENT_TYPE_VIDEO":
            continue
        video_id = str(model.get("contentId") or "")
        if not re.fullmatch(r"[0-9A-Za-z_-]{11}", video_id) or video_id in seen:
            continue
        seen.add(video_id)
        title = nested(model, "metadata", "lockupMetadataViewModel", "title", "content", default="Untitled video")
        metadata_rows = nested(
            model,
            "metadata",
            "lockupMetadataViewModel",
            "metadata",
            "contentMetadataViewModel",
            "metadataRows",
            default=[],
        )
        metadata_parts: list[str] = []
        for row in metadata_rows or []:
            for part in row.get("metadataParts", []):
                content = nested(part, "text", "content")
                if content:
                    metadata_parts.append(str(content))
        view_label = next((part for part in metadata_parts if "view" in part.lower()), "")
        published_label = next((part for part in metadata_parts if "ago" in part.lower()), "")
        image_sources = nested(model, "contentImage", "thumbnailViewModel", "image", "sources", default=[])
        badge_models = collect_key(model.get("contentImage", {}), "thumbnailBadgeViewModel")
        duration_label = ""
        for badge in badge_models:
            candidate = str((badge or {}).get("text") or "")
            if re.fullmatch(r"\d+(?::\d+){1,2}", candidate):
                duration_label = candidate
                break
        seconds = duration_seconds(duration_label)
        output.append(
            {
                "id": video_id,
                "title": html.unescape(str(title)),
                "thumbnail": thumbnail_url(image_sources, video_id),
                "durationSeconds": seconds,
                "viewCount": parse_count(view_label),
                "publishedAt": relative_time_to_iso(published_label, now),
                "publishedLabel": published_label,
            }
        )
        if len(output) >= limit:
            break
    return output


def parse_short_accessibility(text: str) -> tuple[str, int | None]:
    cleaned = html.unescape(text or "").strip()
    match = re.search(r",\s*([^,]*?views?)\s*-\s*play Short\s*$", cleaned, flags=re.I)
    if match:
        return cleaned[: match.start()].strip(), parse_count(match.group(1))
    return re.sub(r"\s*-\s*play Short\s*$", "", cleaned, flags=re.I).strip(), None


def parse_shorts_tab(text: str, limit: int) -> list[dict[str, Any]]:
    data = initial_data(text)
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for model in collect_key(data, "shortsLockupViewModel"):
        if not isinstance(model, dict):
            continue
        video_id = str(nested(model, "onTap", "innertubeCommand", "reelWatchEndpoint", "videoId", default=""))
        if not video_id:
            match = re.search(r"([0-9A-Za-z_-]{11})$", str(model.get("entityId") or ""))
            video_id = match.group(1) if match else ""
        if not re.fullmatch(r"[0-9A-Za-z_-]{11}", video_id) or video_id in seen:
            continue
        seen.add(video_id)
        title, views = parse_short_accessibility(str(model.get("accessibilityText") or ""))
        image_sources = nested(
            model,
            "onTap",
            "innertubeCommand",
            "reelWatchEndpoint",
            "thumbnail",
            "thumbnails",
            default=[],
        )
        output.append(
            {
                "id": video_id,
                "title": title or "Untitled Short",
                "thumbnail": thumbnail_url(image_sources, video_id),
                "viewCount": views,
                "publishedAt": None,
                "durationSeconds": None,
            }
        )
        if len(output) >= limit:
            break
    return output


def parse_search_results(text: str, now: dt.datetime, limit: int) -> list[dict[str, Any]]:
    data = initial_data(text)
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for model in collect_key(data, "videoRenderer"):
        if not isinstance(model, dict):
            continue
        video_id = str(model.get("videoId") or "")
        if not re.fullmatch(r"[0-9A-Za-z_-]{11}", video_id) or video_id in seen:
            continue
        seen.add(video_id)
        title = nested(model, "title", "runs", 0, "text", default="Untitled video")
        channel = nested(model, "longBylineText", "runs", 0, "text", default="Unknown channel")
        channel_id = nested(
            model,
            "longBylineText",
            "runs",
            0,
            "navigationEndpoint",
            "browseEndpoint",
            "browseId",
            default="",
        )
        handle_path = nested(
            model,
            "longBylineText",
            "runs",
            0,
            "navigationEndpoint",
            "browseEndpoint",
            "canonicalBaseUrl",
            default="",
        )
        published_label = nested(model, "publishedTimeText", "simpleText", default="")
        duration_label = nested(model, "lengthText", "simpleText", default="")
        seconds = duration_seconds(duration_label)
        if seconds is None:
            continue
        view_label = nested(model, "viewCountText", "simpleText", default="")
        image_sources = nested(model, "thumbnail", "thumbnails", default=[])
        output.append(
            {
                "id": video_id,
                "title": html.unescape(str(title)),
                "channel": html.unescape(str(channel)),
                "channelId": channel_id,
                "handle": handle_path if str(handle_path).startswith("@") else str(handle_path).lstrip("/"),
                "thumbnail": thumbnail_url(image_sources, video_id),
                "durationSeconds": seconds,
                "viewCount": parse_count(str(view_label)),
                "publishedAt": relative_time_to_iso(str(published_label), now),
                "publishedLabel": str(published_label),
            }
        )
        if len(output) >= limit:
            break
    return output


def parse_rss(text: str) -> dict[str, dict[str, Any]]:
    root = ET.fromstring(text)
    output: dict[str, dict[str, Any]] = {}
    for entry in root.findall(ATOM + "entry"):
        video_id = (entry.findtext(YT + "videoId") or "").strip()
        if not video_id:
            continue
        media_group = entry.find(MEDIA + "group")
        thumbnail = ""
        views = None
        if media_group is not None:
            thumb_node = media_group.find(MEDIA + "thumbnail")
            if thumb_node is not None:
                thumbnail = thumb_node.attrib.get("url", "")
            community = media_group.find(MEDIA + "community")
            if community is not None:
                statistics = community.find(MEDIA + "statistics")
                if statistics is not None:
                    views = parse_count(statistics.attrib.get("views"))
        output[video_id] = {
            "id": video_id,
            "title": (entry.findtext(ATOM + "title") or "Untitled video").strip(),
            "publishedAt": (entry.findtext(ATOM + "published") or "").strip() or None,
            "thumbnail": thumbnail or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
            "viewCount": views,
        }
    return output


def fetch_video_metadata(video_id: str) -> dict[str, Any]:
    url = f"https://www.youtube.com/watch?v={video_id}"
    text = fetch_text(url, timeout=35, attempts=2)
    raw_duration = first_json_field(text, ["lengthSeconds"])
    raw_views = first_json_field(text, ["viewCount"])
    duration = int(raw_duration) if raw_duration and raw_duration.isdigit() else None
    views = int(raw_views) if raw_views and raw_views.isdigit() else parse_count(raw_views)
    return {
        "title": meta_content(text, "og:title") or first_json_field(text, ["title"]),
        "thumbnail": meta_content(text, "og:image"),
        "publishedAt": first_json_field(text, ["uploadDate", "publishDate", "datePublished"]),
        "durationSeconds": duration,
        "viewCount": views,
        "channel": first_json_field(text, ["ownerChannelName", "author"]),
        "channelId": first_json_field(text, ["channelId"]),
    }


def yt_dlp_path() -> str:
    configured = os.getenv("NEXAFEED_YT_DLP", "").strip()
    candidates = [
        configured,
        shutil.which("yt-dlp") or "",
        str(Path.home() / ".local/bin/yt-dlp"),
        "/opt/homebrew/bin/yt-dlp",
        "/usr/local/bin/yt-dlp",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    raise RuntimeError("yt-dlp is required for embed checks and Shorts details")


def build_yt_dlp_command(
    video_id: str,
    include_comments: bool,
    comment_limit: int,
    client: str = "web_embedded",
) -> list[str]:
    command = [
        yt_dlp_path(),
        "--skip-download",
        "--no-playlist",
        "--no-warnings",
        "--socket-timeout",
        "25",
        "--retries",
        "0",
        "--dump-single-json",
    ]
    extractor_options = [f"player_client={client}"]
    if include_comments:
        command.append("--write-comments")
        extractor_options.append(f"max_comments={max(0, int(comment_limit))},all,all,0")
    command.extend(["--extractor-args", "youtube:" + ";".join(extractor_options)])
    command.append(f"https://www.youtube.com/watch?v={video_id}")
    return command


def parse_yt_dlp_json(text: str) -> dict[str, Any]:
    """Parse yt-dlp output while tolerating raw control characters in comments."""
    payload = json.loads(text, strict=False)
    if not isinstance(payload, dict):
        raise ValueError("yt-dlp output must be a JSON object")
    return payload


def pace_detail_probe(config: dict[str, Any]) -> None:
    """Globally pace yt-dlp process starts to reduce YouTube bot challenges."""
    global DETAIL_LAST_STARTED
    delay = max(0.0, min(10.0, float(config.get("richMetadataRequestDelaySeconds", 0.8))))
    with DETAIL_PROBE_LOCK:
        wait_for = delay - (time.monotonic() - DETAIL_LAST_STARTED)
        if wait_for > 0:
            time.sleep(wait_for)
        DETAIL_LAST_STARTED = time.monotonic()


def plan_detail_probes(
    items: list[dict[str, Any]],
    details: dict[str, Any],
    now: dt.datetime,
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    """Plan bounded yt-dlp checks for embed status and fresh Short comments."""
    cached_items = details.get("items", {}) if isinstance(details, dict) else {}
    metadata_ttl = int(config.get("richMetadataTtlHours", 168))
    blocked_ttl = int(config.get("blockedEmbedTtlHours", 24))
    comments_ttl = int(config.get("commentsTtlHours", 24))
    comments_max = int(config.get("commentsMaxVideos", 40))
    max_probes = int(config.get("richMetadataMaxPerRun", 340))
    comment_ids = {
        item.get("id")
        for item in [entry for entry in items if entry.get("type") == "short"][:comments_max]
    }

    def stale(value: str | None, hours: int) -> bool:
        stamp = parse_datetime(value)
        return stamp is None or now - stamp >= dt.timedelta(hours=hours)

    plan: list[dict[str, Any]] = []
    for video in items:
        video_id = video.get("id")
        cached = cached_items.get(video_id, {})
        ttl = blocked_ttl if cached.get("embedAllowed") is False else metadata_ttl
        metadata_due = not cached or stale(cached.get("checkedAt"), ttl)
        comments_due = video_id in comment_ids and stale(cached.get("commentsFetchedAt"), comments_ttl)
        if metadata_due or comments_due:
            plan.append({"video": video, "includeComments": comments_due})
        if len(plan) >= max_probes:
            break
    return plan


def normalize_yt_dlp_details(
    raw: dict[str, Any],
    checked_at: str,
    comment_limit: int = 8,
) -> dict[str, Any]:
    """Convert yt-dlp metadata into the bounded public detail schema."""
    output: dict[str, Any] = {"checkedAt": checked_at}
    if isinstance(raw.get("playable_in_embed"), bool):
        output["embedAllowed"] = raw["playable_in_embed"]
    if raw.get("availability"):
        output["availability"] = str(raw["availability"])
    output["description"] = str(raw.get("description") or "")[:12000]
    comment_count = raw.get("comment_count")
    output["commentCount"] = int(comment_count) if isinstance(comment_count, (int, float)) else 0
    like_count = raw.get("like_count")
    output["likeCount"] = int(like_count) if isinstance(like_count, (int, float)) else 0
    if "comments" in raw:
        comments: list[dict[str, Any]] = []
        for comment in (raw.get("comments") or [])[: max(0, int(comment_limit))]:
            if not isinstance(comment, dict) or not comment.get("text"):
                continue
            timestamp = comment.get("timestamp")
            published_at = None
            if isinstance(timestamp, (int, float)):
                published_at = iso_utc(dt.datetime.fromtimestamp(timestamp, UTC))
            comments.append(
                {
                    "id": str(comment.get("id") or ""),
                    "author": str(comment.get("author") or "YouTube viewer"),
                    "text": str(comment.get("text") or "")[:4000],
                    "likeCount": int(comment.get("like_count") or 0),
                    "publishedAt": published_at,
                    "authorThumbnail": str(comment.get("author_thumbnail") or ""),
                    "isPinned": bool(comment.get("is_pinned")),
                    "isUploader": bool(comment.get("author_is_uploader")),
                }
            )
        output["comments"] = comments
        output["commentsFetchedAt"] = checked_at
    return output


def classify_yt_dlp_failure(message: str, checked_at: str) -> dict[str, Any] | None:
    """Classify only clear permanent/public-playback failures.

    Rate limits, bot challenges, network failures, and extractor breakage remain
    unknown so a valid video is never deleted because of a transient condition.
    """
    text = str(message or "").lower().replace("’", "'")
    permanent_rules = [
        ("private video", "private", "private"),
        ("this video is private", "private", "private"),
        ("has been removed", "removed", "removed"),
        ("video has been removed", "removed", "removed"),
        ("account associated with this video has been terminated", "removed", "removed"),
        ("copyright grounds", "removed", "copyright"),
        ("not available in your country", "region_restricted", "region"),
        ("not available in your region", "region_restricted", "region"),
        ("members-only content", "members_only", "members_only"),
        ("members only", "members_only", "members_only"),
        ("age-restricted", "age_restricted", "age_restricted"),
        ("confirm your age", "age_restricted", "age_restricted"),
        ("playback on other websites has been disabled", "public", "embed_disabled"),
        ("embedding disabled", "public", "embed_disabled"),
        ("video unavailable", "unavailable", "unavailable"),
        ("this video is unavailable", "unavailable", "unavailable"),
    ]
    for needle, availability, reason in permanent_rules:
        if needle in text:
            return {
                "checkedAt": checked_at,
                "embedAllowed": False,
                "availability": availability,
                "failureReason": reason,
            }
    return None


def probe_video_detail(
    video: dict[str, Any],
    include_comments: bool,
    config: dict[str, Any],
    checked_at: str,
) -> dict[str, Any]:
    configured_clients = config.get("richMetadataClients") or ["web_embedded", "mweb", "tv_embedded"]
    if isinstance(configured_clients, str):
        configured_clients = [value.strip() for value in configured_clients.split(",")]
    clients = [
        str(value).strip()
        for value in configured_clients
        if re.fullmatch(r"[A-Za-z0-9_-]{2,40}", str(value).strip())
    ] or ["web_embedded"]
    comment_limit = int(config.get("commentsPerVideo", 8))
    timeout = int(config.get("richMetadataTimeoutSeconds", 90))
    attempt_modes = [include_comments] + ([False] if include_comments else [])
    failures: list[str] = []

    for with_comments in attempt_modes:
        for client in clients:
            pace_detail_probe(config)
            command = build_yt_dlp_command(
                str(video["id"]),
                include_comments=with_comments,
                comment_limit=comment_limit,
                client=client,
            )
            completed = subprocess.run(
                command,
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
            if completed.returncode != 0:
                message = (completed.stderr or completed.stdout or "yt-dlp failed").strip()
                permanent = classify_yt_dlp_failure(message, checked_at)
                if permanent is not None:
                    return permanent
                failures.append(f"{client}: {message[-240:]}")
                continue
            try:
                raw = parse_yt_dlp_json(completed.stdout)
            except (ValueError, json.JSONDecodeError) as exc:
                failures.append(f"{client}: invalid yt-dlp JSON ({exc})")
                continue
            detail = normalize_yt_dlp_details(raw, checked_at, comment_limit=comment_limit)
            if include_comments and (not with_comments or "comments" not in raw):
                detail["commentsFetchedAt"] = checked_at
                detail["commentsStatus"] = "unavailable"
            elif include_comments:
                detail["commentsStatus"] = "cached"
            detail["probeClient"] = client
            return detail

    summary = " | ".join(failures[-len(clients):]) or "all yt-dlp clients failed"
    raise RuntimeError(summary[-900:])


def refresh_video_details(
    items: list[dict[str, Any]],
    previous: dict[str, Any],
    now: dt.datetime,
    config: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    checked_at = iso_utc(now)
    plan = plan_detail_probes(items, previous, now, config)
    active_ids = {str(item.get("id")) for item in items if item.get("id")}
    previous_items = previous.get("items", {}) if isinstance(previous, dict) else {}
    cached: dict[str, dict[str, Any]] = {
        video_id: dict(detail)
        for video_id, detail in previous_items.items()
        if video_id in active_ids and isinstance(detail, dict)
    }
    errors: list[dict[str, str]] = []
    workers = min(max(1, int(config.get("richMetadataWorkers", 8))), max(1, len(plan)))
    if plan:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            future_map = {
                executor.submit(
                    probe_video_detail,
                    entry["video"],
                    bool(entry["includeComments"]),
                    config,
                    checked_at,
                ): entry
                for entry in plan
            }
            for future in concurrent.futures.as_completed(future_map):
                entry = future_map[future]
                video_id = str(entry["video"]["id"])
                try:
                    detail = future.result()
                    cached[video_id] = {**cached.get(video_id, {}), **detail}
                except Exception as exc:
                    errors.append({"id": video_id, "error": str(exc)[:500]})
    output = {
        "schemaVersion": 1,
        "updatedAt": checked_at,
        "items": cached,
    }
    status = {
        "planned": len(plan),
        "checked": len(plan) - len(errors),
        "warnings": len(errors),
        "errors": errors[:25],
    }
    return output, status


def enrich_and_filter_items(
    items: list[dict[str, Any]],
    details: dict[str, Any],
) -> tuple[list[dict[str, Any]], int]:
    """Attach cached embed status and remove videos explicitly blocked from embeds."""
    detail_items = details.get("items", {}) if isinstance(details, dict) else {}
    output: list[dict[str, Any]] = []
    blocked = 0
    for item in items:
        detail = detail_items.get(item.get("id"), {})
        if detail.get("embedAllowed") is False:
            blocked += 1
            continue
        enriched = dict(item)
        if detail.get("embedAllowed") is True:
            enriched["embedAllowed"] = True
        output.append(enriched)
    return output, blocked


def read_channels() -> list[dict[str, Any]]:
    with CHANNELS_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    output = []
    seen: set[str] = set()
    for row in rows:
        handle = (row.get("Handle") or "").strip()
        if not handle:
            continue
        if not handle.startswith("@"):
            handle = "@" + handle
        key = handle.lower()
        if key in seen:
            continue
        seen.add(key)
        output.append(
            {
                "name": (row.get("Channel Name") or handle).strip(),
                "handle": handle,
                "url": (row.get("Channel URL") or f"https://www.youtube.com/{handle}").strip(),
                "monitorLong": (row.get("Monitor Long") or "yes").strip().lower() == "yes",
                "monitorShorts": (row.get("Monitor Shorts") or "yes").strip().lower() == "yes",
                "priority": int((row.get("Priority") or "1").strip() or 1),
                "category": (row.get("Category") or "Long + Shorts").strip(),
            }
        )
    return output


def merge_item(
    candidate: dict[str, Any],
    rss: dict[str, dict[str, Any]],
    previous: dict[str, dict[str, Any]],
    channel: dict[str, Any],
    channel_id: str,
    item_type: str,
    now: dt.datetime,
    bootstrap: bool,
) -> dict[str, Any] | None:
    video_id = candidate["id"]
    rss_item = rss.get(video_id, {})
    old = previous.get(video_id, {})
    published = rss_item.get("publishedAt") or candidate.get("publishedAt") or old.get("publishedAt")
    parsed_published = parse_datetime(published)
    if parsed_published:
        published = iso_utc(parsed_published)
    title = rss_item.get("title") or candidate.get("title") or old.get("title") or "Untitled video"
    thumbnail = candidate.get("thumbnail") or rss_item.get("thumbnail") or old.get("thumbnail")
    view_count = candidate.get("viewCount")
    if view_count is None:
        view_count = rss_item.get("viewCount")
    if view_count is None:
        view_count = old.get("viewCount")
    seconds = candidate.get("durationSeconds")
    if seconds is None:
        seconds = old.get("durationSeconds")
    first_seen = old.get("firstSeenAt")
    if not first_seen:
        first_seen = published if bootstrap and published else iso_utc(now)
    if not published and not old:
        return None
    return {
        "id": video_id,
        "type": item_type,
        "title": html.unescape(str(title)),
        "channel": channel["name"],
        "channelId": channel_id,
        "handle": channel["handle"],
        "channelUrl": channel["url"],
        "category": channel["category"],
        "thumbnail": thumbnail or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
        "duration": format_duration(seconds, item_type == "short"),
        "durationSeconds": seconds,
        "views": format_views(view_count),
        "viewCount": view_count,
        "publishedAt": published or old.get("publishedAt") or iso_utc(now),
        "publishedLabel": candidate.get("publishedLabel") or old.get("publishedLabel") or "",
        "firstSeenAt": first_seen,
        "source": "primary",
        "priority": channel["priority"],
        "url": f"https://www.youtube.com/{'shorts/' if item_type == 'short' else 'watch?v='}{video_id}",
    }


def collect_channel(
    channel: dict[str, Any],
    config: dict[str, Any],
    cache: dict[str, Any],
    previous: dict[str, dict[str, Any]],
    now: dt.datetime,
    bootstrap: bool,
) -> dict[str, Any]:
    handle_key = channel["handle"].lower()
    cached = cache.get(handle_key) or {}
    channel_id = cached.get("channelId")
    failures: list[str] = []
    base_url = channel["url"].rstrip("/")
    if not channel_id:
        try:
            base_text = fetch_text(base_url)
            channel_id = extract_channel_id(base_text)
        except Exception as exc:
            failures.append(f"resolve: {exc}")
    if not channel_id:
        return {"channel": channel, "items": [], "failures": failures + ["channel id unavailable"]}

    cache_entry = {
        "channelId": channel_id,
        "channelName": channel["name"],
        "handle": channel["handle"],
        "resolvedAt": cached.get("resolvedAt") or iso_utc(now),
        "lastCheckedAt": iso_utc(now),
    }
    rss: dict[str, dict[str, Any]] = {}
    try:
        rss = parse_rss(fetch_text(f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"))
    except Exception as exc:
        failures.append(f"rss: {exc}")

    output: list[dict[str, Any]] = []
    if channel["monitorLong"]:
        try:
            text = fetch_text(base_url + "/videos")
            candidates = parse_video_tab(text, now, int(config.get("primaryLongPerChannel", 5)))
            for candidate in candidates:
                item = merge_item(candidate, rss, previous, channel, channel_id, "long", now, bootstrap)
                if item:
                    output.append(item)
        except Exception as exc:
            failures.append(f"videos tab: {exc}")
            output.extend(
                item
                for item in previous.values()
                if item.get("source") == "primary"
                and item.get("handle", "").lower() == handle_key
                and item.get("type") == "long"
            )

    if channel["monitorShorts"]:
        try:
            text = fetch_text(base_url + "/shorts")
            candidates = parse_shorts_tab(text, int(config.get("primaryShortsPerChannel", 5)))
            metadata_budget = int(config.get("shortsMetadataPerChannel", 2))
            for candidate in candidates:
                video_id = candidate["id"]
                old = previous.get(video_id, {})
                if not rss.get(video_id, {}).get("publishedAt") and not old.get("publishedAt") and metadata_budget > 0:
                    try:
                        details = fetch_video_metadata(video_id)
                        for key, value in details.items():
                            if value is not None and (not candidate.get(key) or key in {"viewCount", "durationSeconds"}):
                                candidate[key] = value
                        metadata_budget -= 1
                    except Exception as exc:
                        failures.append(f"short {video_id}: {exc}")
                item = merge_item(candidate, rss, previous, channel, channel_id, "short", now, bootstrap)
                if item:
                    output.append(item)
        except Exception as exc:
            failures.append(f"shorts tab: {exc}")
            output.extend(
                item
                for item in previous.values()
                if item.get("source") == "primary"
                and item.get("handle", "").lower() == handle_key
                and item.get("type") == "short"
            )

    deduped: dict[str, dict[str, Any]] = {}
    for item in output:
        deduped[item["id"]] = item
    return {
        "channel": channel,
        "channelId": channel_id,
        "cache": cache_entry,
        "items": list(deduped.values()),
        "failures": failures,
    }


def collect_secondary(
    config: dict[str, Any],
    previous_items: list[dict[str, Any]],
    primary_channel_ids: set[str],
    now: dt.datetime,
    bootstrap: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    terms = [
        str(term).strip()
        for group in ("keywords", "topics", "categories")
        for term in config.get(group, [])
        if str(term).strip()
    ]
    previous_secondary = [item for item in previous_items if item.get("source") == "secondary"]
    cutoff = now - dt.timedelta(hours=int(config.get("secondaryRetentionHours", 168)))
    retained = [
        item
        for item in previous_secondary
        if (parse_datetime(item.get("publishedAt")) or dt.datetime.min.replace(tzinfo=UTC)) >= cutoff
    ]
    if not terms:
        return retained, {"query": None, "newResults": 0, "error": None}
    hour_index = int(now.timestamp() // 3600) % len(terms)
    query = terms[hour_index]
    params = urllib.parse.urlencode(
        {
            "search_query": query,
            "sp": config.get("secondarySearchFilter", "EgIIAg=="),
        }
    )
    try:
        text = fetch_text("https://www.youtube.com/results?" + params, timeout=60)
        results = parse_search_results(text, now, int(config.get("secondaryResultsPerQuery", 8)))
    except Exception as exc:
        return retained, {"query": query, "newResults": 0, "error": str(exc)}

    previous_by_id = {item["id"]: item for item in previous_secondary if item.get("id")}
    short_max = int(config.get("shortMaxSeconds", 180))
    new_items: list[dict[str, Any]] = []
    for candidate in results:
        if candidate.get("channelId") in primary_channel_ids:
            continue
        published = candidate.get("publishedAt")
        if not published:
            continue
        old = previous_by_id.get(candidate["id"], {})
        item_type = "short" if int(candidate.get("durationSeconds") or 0) <= short_max else "long"
        first_seen = old.get("firstSeenAt") or (published if bootstrap else iso_utc(now))
        view_count = candidate.get("viewCount")
        new_items.append(
            {
                "id": candidate["id"],
                "type": item_type,
                "title": candidate["title"],
                "channel": candidate["channel"],
                "channelId": candidate.get("channelId") or "",
                "handle": candidate.get("handle") or "",
                "channelUrl": f"https://www.youtube.com/channel/{candidate.get('channelId')}" if candidate.get("channelId") else "",
                "category": "Topic discovery",
                "thumbnail": candidate["thumbnail"],
                "duration": format_duration(candidate.get("durationSeconds"), item_type == "short"),
                "durationSeconds": candidate.get("durationSeconds"),
                "views": format_views(view_count),
                "viewCount": view_count,
                "publishedAt": published,
                "publishedLabel": candidate.get("publishedLabel") or "",
                "firstSeenAt": first_seen,
                "source": "secondary",
                "priority": 99,
                "topic": query,
                "url": f"https://www.youtube.com/{'shorts/' if item_type == 'short' else 'watch?v='}{candidate['id']}",
            }
        )

    merged: dict[str, dict[str, Any]] = {item["id"]: item for item in retained if item.get("id")}
    for item in new_items:
        merged[item["id"]] = item
    ordered = sorted(
        merged.values(),
        key=lambda item: parse_datetime(item.get("publishedAt")) or dt.datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )[: max(40, int(config.get("secondaryResultsPerQuery", 8)) * 5)]
    return ordered, {"query": query, "newResults": len(new_items), "error": None}


def build_settings_document(
    channels: list[dict[str, Any]],
    config: dict[str, Any],
    updated_at: str,
) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "updatedAt": updated_at,
        "channels": channels,
        "keywords": [str(value) for value in config.get("keywords", [])],
        "topics": [str(value) for value in config.get("topics", [])],
        "categories": [str(value) for value in config.get("categories", [])],
    }


def update_discovery_log(
    previous: dict[str, Any],
    items: list[dict[str, Any]],
    now: dt.datetime,
    run_stats: dict[str, Any],
    retention_days: int,
) -> dict[str, Any]:
    discoveries = {
        item["id"]: item
        for item in previous.get("items", [])
        if isinstance(item, dict) and item.get("id")
    }
    for item in items:
        if item["id"] not in discoveries:
            discoveries[item["id"]] = {
                "id": item["id"],
                "type": item.get("type"),
                "source": item.get("source"),
                "channel": item.get("channel"),
                "publishedAt": item.get("publishedAt"),
                "firstSeenAt": item.get("firstSeenAt") or iso_utc(now),
            }
    cutoff = now - dt.timedelta(days=retention_days)
    kept = [
        item
        for item in discoveries.values()
        if (parse_datetime(item.get("firstSeenAt")) or now) >= cutoff
    ]
    kept.sort(key=lambda item: parse_datetime(item.get("firstSeenAt")) or now, reverse=True)
    runs = [run for run in previous.get("runs", []) if isinstance(run, dict)]
    runs.append(run_stats)
    run_cutoff = now - dt.timedelta(days=14)
    runs = [
        run
        for run in runs
        if (parse_datetime(run.get("runAt")) or now) >= run_cutoff
    ][-400:]
    return {"schemaVersion": 1, "updatedAt": iso_utc(now), "items": kept, "runs": runs}


def git_publish(root: Path, now: dt.datetime) -> dict[str, Any]:
    def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            text=True,
            capture_output=True,
            timeout=120,
            check=check,
        )

    run(
        "add",
        "data/videos.json",
        "data/video-details.json",
        "data/feed-settings.json",
        "data/discovery-log.json",
        "data/channel-cache.json",
    )
    diff = run("diff", "--cached", "--quiet", check=False)
    if diff.returncode == 0:
        return {"changed": False, "committed": False, "pushed": False}
    if diff.returncode not in {0, 1}:
        raise RuntimeError(diff.stderr or "git diff failed")
    stamp = now.astimezone(BD_TZ).strftime("%Y-%m-%d %H:%M BDT")
    commit = run("commit", "-m", f"chore(feed): refresh {stamp}")
    push = run("push", "origin", "main")
    return {
        "changed": True,
        "committed": True,
        "pushed": True,
        "commit": (commit.stdout or "").strip().splitlines()[0] if commit.stdout else "",
        "push": (push.stdout or push.stderr or "").strip()[-500:],
    }


def run_update(args: argparse.Namespace) -> dict[str, Any]:
    started = time.monotonic()
    now = utc_now()
    config = load_json(CONFIG_PATH, {})
    channels = read_channels()
    previous_feed = load_json(VIDEOS_PATH, {"items": []})
    previous_details = load_json(DETAILS_PATH, {"schemaVersion": 1, "items": {}})
    previous_items = [item for item in previous_feed.get("items", []) if isinstance(item, dict)]
    previous_by_id = {item["id"]: item for item in previous_items if item.get("id")}
    bootstrap = not bool(previous_by_id)
    cache = load_json(CACHE_PATH, {"channels": {}})
    cache_channels = cache.setdefault("channels", {})

    results: list[dict[str, Any]] = []
    worker_count = min(max(1, args.workers), max(1, len(channels)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_map = {
            executor.submit(
                collect_channel,
                channel,
                config,
                cache_channels,
                previous_by_id,
                now,
                bootstrap,
            ): channel
            for channel in channels
        }
        for future in concurrent.futures.as_completed(future_map):
            channel = future_map[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {"channel": channel, "items": [], "failures": [f"worker: {exc}"]}
            results.append(result)

    primary_items: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    checked = 0
    primary_channel_ids: set[str] = set()
    for result in results:
        handle = result["channel"]["handle"]
        if result.get("channelId"):
            checked += 1
            primary_channel_ids.add(result["channelId"])
        if result.get("cache"):
            cache_channels[handle.lower()] = result["cache"]
        primary_items.extend(result.get("items", []))
        if result.get("failures"):
            failures.append({"handle": handle, "errors": result["failures"]})

    if args.no_secondary:
        secondary_items = [item for item in previous_items if item.get("source") == "secondary"]
        secondary_status = {"query": None, "newResults": 0, "error": "disabled for this run"}
    else:
        secondary_items, secondary_status = collect_secondary(
            config,
            previous_items,
            primary_channel_ids,
            now,
            bootstrap,
        )

    deduped: dict[str, dict[str, Any]] = {}
    for item in primary_items + secondary_items:
        current = deduped.get(item["id"])
        if current is None or (current.get("source") == "secondary" and item.get("source") == "primary"):
            deduped[item["id"]] = item

    def sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
        published = parse_datetime(item.get("publishedAt")) or dt.datetime.min.replace(tzinfo=UTC)
        return (
            0 if item.get("source") == "primary" else 1,
            int(item.get("priority") or 99),
            -published.timestamp(),
        )

    candidate_items = sorted(deduped.values(), key=sort_key)[: int(config.get("maxFeedItems", 340))]
    if args.no_details:
        details = previous_details
        detail_status = {"planned": 0, "checked": 0, "warnings": 0, "errors": [], "disabled": True}
    else:
        details, detail_status = refresh_video_details(candidate_items, previous_details, now, config)
    items, embed_blocked = enrich_and_filter_items(candidate_items, details)
    previous_ids = set(previous_by_id)
    new_ids = [item["id"] for item in items if item["id"] not in previous_ids]
    new_items = [item for item in items if item["id"] in set(new_ids)]
    type_counts = Counter(item.get("type") for item in items)
    source_counts = Counter(item.get("source") for item in items)
    new_type_counts = Counter(item.get("type") for item in new_items)

    health = {
        "channelsRequested": len(channels),
        "channelsChecked": checked,
        "channelsWithWarnings": len(failures),
        "failures": failures[:25],
        "secondary": secondary_status,
        "richMetadata": {**detail_status, "embedBlocked": embed_blocked},
        "runSeconds": round(time.monotonic() - started, 2),
    }
    feed = {
        "schemaVersion": 3,
        "updatedAt": iso_utc(now),
        "siteName": config.get("siteName", "NexaFeed"),
        "siteUrl": config.get("siteUrl", ""),
        "primaryChannels": len(channels),
        "freshHours": int(config.get("freshHours", 24)),
        "stats": {
            "total": len(items),
            "longVideos": type_counts.get("long", 0),
            "shorts": type_counts.get("short", 0),
            "primary": source_counts.get("primary", 0),
            "secondary": source_counts.get("secondary", 0),
            "newThisRun": len(new_ids),
            "newLongThisRun": new_type_counts.get("long", 0),
            "newShortsThisRun": new_type_counts.get("short", 0),
        },
        "health": health,
        "items": items,
    }

    run_stats = {
        "runAt": iso_utc(now),
        "new": len(new_ids),
        "long": new_type_counts.get("long", 0),
        "shorts": new_type_counts.get("short", 0),
        "channelsChecked": checked,
        "warnings": len(failures),
        "secondaryQuery": secondary_status.get("query"),
    }
    discovery = update_discovery_log(
        load_json(DISCOVERY_PATH, {"items": [], "runs": []}),
        items,
        now,
        run_stats,
        int(config.get("discoveryRetentionDays", 90)),
    )
    cache_output = {
        "schemaVersion": 1,
        "updatedAt": iso_utc(now),
        "channels": cache_channels,
    }

    settings_output = build_settings_document(channels, config, feed["updatedAt"])
    if not args.dry_run:
        write_json(VIDEOS_PATH, feed)
        write_json(DETAILS_PATH, details)
        write_json(SETTINGS_PATH, settings_output)
        write_json(DISCOVERY_PATH, discovery)
        write_json(CACHE_PATH, cache_output)

    publish = None
    if args.publish and not args.dry_run:
        publish = git_publish(ROOT, now)

    return {
        "ok": checked > 0,
        "updatedAt": feed["updatedAt"],
        "channels": {"requested": len(channels), "checked": checked, "warnings": len(failures)},
        "feed": feed["stats"],
        "secondaryQuery": secondary_status.get("query"),
        "secondaryError": secondary_status.get("error"),
        "richMetadata": {**detail_status, "embedBlocked": embed_blocked},
        "durationSeconds": round(time.monotonic() - started, 2),
        "dryRun": args.dry_run,
        "publish": publish,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh and publish the NexaFeed static feed")
    parser.add_argument("--publish", action="store_true", help="Commit generated data and push origin/main")
    parser.add_argument("--dry-run", action="store_true", help="Collect and report without writing files")
    parser.add_argument("--no-secondary", action="store_true", help="Skip this run's topic search")
    parser.add_argument("--no-details", action="store_true", help="Reuse cached embed/comment details without probing")
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args(argv)

    LOCK_PATH.touch(exist_ok=True)
    with LOCK_PATH.open("r+") as lock_handle:
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({"ok": True, "skipped": True, "reason": "another NexaFeed update is running"}))
            return 0
        try:
            result = run_update(args)
            print(json.dumps(result, ensure_ascii=False))
            return 0 if result.get("ok") else 2
        except Exception as exc:
            print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
