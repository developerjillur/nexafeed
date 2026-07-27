#!/usr/bin/env python3
"""Focused structural verification for the NexaFeed static application."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
errors = []


def fail(message: str) -> None:
    errors.append(message)


required_files = [
    "index.html",
    "style.css",
    "app.js",
    "config.json",
    "data/channels.csv",
    "data/original-channel-categories.csv",
    "data/videos.json",
    "data/discovery-log.json",
]
for relative in required_files:
    if not (ROOT / relative).is_file():
        fail(f"missing {relative}")

with (ROOT / "data/channels.csv").open(encoding="utf-8-sig", newline="") as handle:
    channels = list(csv.DictReader(handle))
handles = {(row.get("Handle") or "").lower() for row in channels}
if len(channels) != 33:
    fail(f"expected 33 supplied channels, found {len(channels)}")
if len(handles) != len(channels):
    fail("duplicate channel handles found")
if sum(1 for row in channels if (row.get("Monitor Long") or "").lower() == "no") != 7:
    fail("expected 7 Shorts-only channels")

feed = json.loads((ROOT / "data/videos.json").read_text(encoding="utf-8"))
items = feed.get("items") or []
ids = [item.get("id") for item in items]
if not items:
    fail("feed has no video items")
if len(ids) != len(set(ids)):
    fail("duplicate video IDs found")
if feed.get("primaryChannels") != 33:
    fail("feed primaryChannels is not 33")

required_item_fields = {"id", "type", "title", "channel", "thumbnail", "publishedAt", "source", "url", "firstSeenAt"}
for index, item in enumerate(items):
    missing = required_item_fields - set(item)
    if missing:
        fail(f"item {index} missing {sorted(missing)}")
    if item.get("type") not in {"long", "short"}:
        fail(f"item {item.get('id')} has invalid type")
    if item.get("source") not in {"primary", "secondary"}:
        fail(f"item {item.get('id')} has invalid source")
    if item.get("source") == "primary" and (item.get("handle") or "").lower() not in handles:
        fail(f"primary item came from an unsupplied handle: {item.get('handle')}")
    if not isinstance(item.get("id"), str) or len(item["id"]) != 11:
        fail(f"invalid YouTube video id: {item.get('id')}")

stats = feed.get("stats") or {}
if stats.get("total") != len(items):
    fail("stats.total does not match item count")
if stats.get("longVideos") != sum(1 for item in items if item.get("type") == "long"):
    fail("long video stat does not match")
if stats.get("shorts") != sum(1 for item in items if item.get("type") == "short"):
    fail("Shorts stat does not match")

index_html = (ROOT / "index.html").read_text(encoding="utf-8")
app_js = (ROOT / "app.js").read_text(encoding="utf-8")
for needle in ["style.css", "app.js", "youtube.com/iframe_api"]:
    if needle not in index_html:
        fail(f"index missing {needle}")
for needle in ["WATCHED_KEY", "PROGRESS_KEY", "autoplayToggle", "nextShort", "data/videos.json"]:
    if needle not in app_js:
        fail(f"app missing behavior marker {needle}")

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
    "channelsChecked": (feed.get("health") or {}).get("channelsChecked"),
}, ensure_ascii=False))
