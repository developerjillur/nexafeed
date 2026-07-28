#!/usr/bin/env python3
"""Validate and apply owner-authorized YourTube settings issue payloads."""
from __future__ import annotations

import argparse
import base64
import csv
import datetime as dt
import gzip
import io
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
CHANNELS_PATH = ROOT / "data/channels.csv"
CONFIG_PATH = ROOT / "config.json"
SETTINGS_PATH = ROOT / "data/feed-settings.json"
ISSUE_TITLE = "[YourTube Config] Apply feed settings"
MARKER_RE = re.compile(r"<!--\s*NEXAFEED_CONFIG_V1:GZIP_BASE64URL:([A-Za-z0-9_-]+)\s*-->")
HANDLE_RE = re.compile(r"^@[A-Za-z0-9._-]{3,100}$")


class SettingsValidationError(ValueError):
    pass


def dedupe_terms(values: Any, label: str) -> list[str]:
    if not isinstance(values, list):
        raise SettingsValidationError(f"{label} must be a list")
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            raise SettingsValidationError(f"{label} values must be strings")
        text = value.strip()
        if not text:
            continue
        if len(text) > 100:
            raise SettingsValidationError(f"{label} value is too long")
        key = text.casefold()
        if key not in seen:
            seen.add(key)
            output.append(text)
    if len(output) > 50:
        raise SettingsValidationError(f"{label} supports at most 50 values")
    return output


def validate_settings_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise SettingsValidationError("settings payload must be an object")
    raw_channels = payload.get("channels")
    if not isinstance(raw_channels, list) or not raw_channels:
        raise SettingsValidationError("at least one channel is required")
    if len(raw_channels) > 100:
        raise SettingsValidationError("at most 100 channels are supported")

    channels: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_channels, start=1):
        if not isinstance(raw, dict):
            raise SettingsValidationError(f"channel {index} must be an object")
        handle = str(raw.get("handle") or "").strip()
        if handle and not handle.startswith("@"):
            handle = "@" + handle
        if not HANDLE_RE.fullmatch(handle):
            raise SettingsValidationError(f"channel {index} has an invalid YouTube handle")
        key = handle.casefold()
        if key in seen:
            raise SettingsValidationError(f"duplicate channel handle: {handle}")
        seen.add(key)

        name = str(raw.get("name") or handle).strip()[:120]
        category = str(raw.get("category") or "Long + Shorts").strip()[:100]
        url = str(raw.get("url") or f"https://www.youtube.com/{handle}").strip()
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
            raise SettingsValidationError(f"channel {index} must use an https://youtube.com URL")
        monitor_long = raw.get("monitorLong") is True
        monitor_shorts = raw.get("monitorShorts") is True
        if not monitor_long and not monitor_shorts:
            raise SettingsValidationError(f"channel {handle} must monitor long videos, Shorts, or both")
        try:
            priority = int(raw.get("priority", 1))
        except (TypeError, ValueError):
            raise SettingsValidationError(f"channel {handle} has an invalid priority")
        if priority < 1 or priority > 99:
            raise SettingsValidationError(f"channel {handle} priority must be 1-99")
        channels.append(
            {
                "name": name,
                "handle": handle,
                "url": url,
                "category": category,
                "monitorLong": monitor_long,
                "monitorShorts": monitor_shorts,
                "priority": priority,
            }
        )

    return {
        "channels": channels,
        "keywords": dedupe_terms(payload.get("keywords", []), "keywords"),
        "topics": dedupe_terms(payload.get("topics", []), "topics"),
        "categories": dedupe_terms(payload.get("categories", []), "categories"),
    }


def decode_issue_payload(body: str) -> dict[str, Any]:
    match = MARKER_RE.search(body or "")
    if not match:
        raise SettingsValidationError("YourTube settings marker was not found")
    token = match.group(1)
    if len(token) > 60_000:
        raise SettingsValidationError("settings payload is too large")
    token += "=" * (-len(token) % 4)
    try:
        compressed = base64.urlsafe_b64decode(token.encode("ascii"))
        if len(compressed) > 50_000:
            raise SettingsValidationError("compressed settings payload is too large")
        with gzip.GzipFile(fileobj=io.BytesIO(compressed), mode="rb") as archive:
            decoded = archive.read(1_000_001)
        if len(decoded) > 1_000_000:
            raise SettingsValidationError("decoded settings payload is too large")
        payload = json.loads(decoded.decode("utf-8"))
    except SettingsValidationError:
        raise
    except Exception as exc:
        raise SettingsValidationError(f"settings payload could not be decoded: {exc}")
    return validate_settings_payload(payload)


def atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def write_settings(payload: dict[str, Any]) -> dict[str, Any]:
    payload = validate_settings_payload(payload)
    rows = []
    for channel in payload["channels"]:
        rows.append(
            {
                "Channel Name": channel["name"],
                "Handle": channel["handle"],
                "Channel URL": channel["url"],
                "Category": channel["category"],
                "Monitor Long": "yes" if channel["monitorLong"] else "no",
                "Monitor Shorts": "yes" if channel["monitorShorts"] else "no",
                "Priority": channel["priority"],
            }
        )
    headers = ["Channel Name", "Handle", "Channel URL", "Category", "Monitor Long", "Monitor Shorts", "Priority"]
    temporary = CHANNELS_PATH.with_suffix(".csv.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(CHANNELS_PATH)

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    for name in ("keywords", "topics", "categories"):
        config[name] = payload[name]
    atomic_text(CONFIG_PATH, json.dumps(config, ensure_ascii=False, indent=2) + "\n")

    updated_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    settings_document = {"schemaVersion": 1, "updatedAt": updated_at, **payload}
    atomic_text(SETTINGS_PATH, json.dumps(settings_document, ensure_ascii=False, indent=2) + "\n")
    return settings_document


def payload_from_event(event_path: Path) -> dict[str, Any]:
    event = json.loads(event_path.read_text(encoding="utf-8"))
    issue = event.get("issue") or {}
    if issue.get("title") != ISSUE_TITLE:
        raise SettingsValidationError("issue title is not a YourTube settings request")
    owner = os.getenv("GITHUB_REPOSITORY_OWNER", "").casefold()
    actor = str((issue.get("user") or {}).get("login") or "").casefold()
    association = str(issue.get("author_association") or "").upper()
    if association != "OWNER" and (not owner or actor != owner):
        raise SettingsValidationError("only the repository owner can apply feed settings")
    return decode_issue_payload(str(issue.get("body") or ""))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply owner-authorized YourTube settings")
    parser.add_argument("--event", type=Path, help="GitHub event JSON path")
    parser.add_argument("--payload", type=Path, help="Validated local payload JSON path")
    args = parser.parse_args(argv)
    try:
        if args.event:
            payload = payload_from_event(args.event)
        elif args.payload:
            payload = validate_settings_payload(json.loads(args.payload.read_text(encoding="utf-8")))
        else:
            raise SettingsValidationError("--event or --payload is required")
        result = write_settings(payload)
        print(json.dumps({"ok": True, "channels": len(result["channels"]), "updatedAt": result["updatedAt"]}))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
