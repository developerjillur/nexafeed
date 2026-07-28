#!/usr/bin/env python3
"""Send a compact NexaFeed update email without listing every video."""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import smtplib
import subprocess
import sys
import tempfile
from collections import Counter
from email.message import EmailMessage
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from nexafeed_env import load_env_files

ROOT = Path(__file__).resolve().parents[1]
FEED_PATH = ROOT / "data" / "videos.json"
DISCOVERY_PATH = ROOT / "data" / "discovery-log.json"
CONFIG_PATH = ROOT / "config.json"
BD_TZ = dt.timezone(dt.timedelta(hours=6))
UTC = dt.timezone.utc


def load_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def report_output_dir() -> Path:
    configured = os.getenv("NEXAFEED_REPORT_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()
    if os.getenv("HERMES_HOME"):
        return Path(os.environ["HERMES_HOME"]) / "reports" / "nexafeed"
    return Path.home() / ".nexafeed" / "reports"


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
        return parsed.astimezone(BD_TZ)
    except Exception:
        return None


def parse_recipients(raw: str | None) -> list[str]:
    if not raw:
        return []
    output: list[str] = []
    for part in re.split(r"[,;\s]+", raw):
        value = part.strip()
        if "@" in value and value not in output:
            output.append(value)
    return output


def report_window(period: str, now: dt.datetime) -> tuple[dt.datetime, dt.datetime, str, str]:
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "morning":
        start, end = midnight, now
        label = "সকালের আপডেট"
        subject_label = "Morning Update"
    else:
        end = midnight
        start = end - dt.timedelta(days=1)
        label = "দিনশেষের আপডেট"
        subject_label = "Daily Wrap"
    return start, end, label, subject_label


def stat_cell(value: Any, label: str, color: str = "#ffffff") -> str:
    return f"""
      <td width="25%" valign="top" style="width:25%;padding:5px;vertical-align:top;">
        <div style="min-height:78px;padding:15px 11px;border:1px solid #343434;border-radius:14px;background:#1d1d1d;text-align:center;box-sizing:border-box;">
          <div style="font-size:26px;line-height:1;font-weight:900;color:{color};">{html.escape(str(value))}</div>
          <div style="margin-top:7px;font-size:11px;font-weight:700;color:#b8b8b8;">{html.escape(label)}</div>
        </div>
      </td>"""


def build_report(period: str, site_url: str) -> dict[str, Any]:
    now = dt.datetime.now(BD_TZ)
    start, end, label, subject_label = report_window(period, now)
    discovery = load_json(DISCOVERY_PATH, {"items": []})
    feed = load_json(FEED_PATH, {"health": {}, "stats": {}, "primaryChannels": 0})
    items = []
    for item in discovery.get("items", []):
        published = parse_datetime(item.get("publishedAt"))
        if published and start <= published < end:
            items.append(item)

    type_counts = Counter(item.get("type") for item in items)
    source_counts = Counter(item.get("source") for item in items)
    channel_counts = Counter(item.get("channel") or "Unknown channel" for item in items)
    top_channels = channel_counts.most_common(6)
    total = len(items)
    longs = type_counts.get("long", 0)
    shorts = type_counts.get("short", 0)
    primary = source_counts.get("primary", 0)
    secondary = source_counts.get("secondary", 0)
    health = feed.get("health") or {}
    secondary_health = health.get("secondary") or {}
    checked = health.get("channelsChecked", 0)
    requested = health.get("channelsRequested", feed.get("primaryChannels", 0))
    warnings = health.get("channelsWithWarnings", 0)
    generated = parse_datetime(feed.get("updatedAt"))

    top_rows = "".join(
        f'<tr><td style="padding:9px 0;border-bottom:1px solid #ececec;color:#222;font-size:13px;">{html.escape(name)}</td>'
        f'<td align="right" style="padding:9px 0;border-bottom:1px solid #ececec;color:#111;font-size:13px;font-weight:800;">{count}</td></tr>'
        for name, count in top_channels
    )
    if not top_rows:
        top_rows = '<tr><td colspan="2" style="padding:14px 0;color:#777;font-size:13px;">এই সময়ের মধ্যে নতুন upload পাওয়া যায়নি।</td></tr>'

    window_text = f"{start.strftime('%d %b, %I:%M %p')} – {end.strftime('%d %b, %I:%M %p')} BDT"
    updated_text = generated.strftime("%d %b %Y, %I:%M %p BDT") if generated else "Not available"
    subject = f"NexaFeed {subject_label}: {total} new ({shorts} Shorts + {longs} Long)"
    text_body = f"""NexaFeed — {label}

Period: {window_text}
New videos: {total}
Long videos: {longs}
Shorts: {shorts}
Priority channels: {primary}
Topic discovery: {secondary}
Sources checked: {checked}/{requested}
Warnings: {warnings}

Open NexaFeed: {site_url}

ভিডিওর full list email-এ রাখা হয়নি। Page-এ Shorts এবং Long Videos আলাদা playlist-এ পাওয়া যাবে।
"""

    html_body = f"""<!doctype html>
<html><body style="margin:0;padding:0;background:#eeeeee;font-family:Arial,sans-serif;color:#111;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:#eeeeee;">
    <tr><td align="center" style="padding:24px 10px;">
      <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="max-width:680px;background:#ffffff;border-radius:18px;overflow:hidden;box-shadow:0 12px 38px rgba(0,0,0,.10);">
        <tr><td style="padding:27px 28px;background:#0f0f0f;color:#fff;">
          <div style="font-size:12px;font-weight:800;letter-spacing:.12em;text-transform:uppercase;color:#ff4b67;">Hourly YouTube Monitor</div>
          <h1 style="margin:8px 0 5px;font-size:28px;line-height:1.15;">NexaFeed · {html.escape(label)}</h1>
          <p style="margin:0;color:#bcbcbc;font-size:13px;line-height:1.6;">{html.escape(window_text)}</p>
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="margin-top:18px;">
            <tr>
              {stat_cell(total, "নতুন ভিডিও", "#ff4b67")}
              {stat_cell(longs, "Long videos")}
              {stat_cell(shorts, "Shorts")}
              {stat_cell(primary, "Priority source")}
            </tr>
          </table>
        </td></tr>
        <tr><td style="padding:28px;">
          <h2 style="margin:0 0 8px;font-size:18px;">আজ কী এসেছে</h2>
          <p style="margin:0;color:#616161;font-size:14px;line-height:1.65;">Priority channel থেকে <strong>{primary}</strong>টি এবং keyword/topic/category discovery থেকে <strong>{secondary}</strong>টি relevant video পাওয়া গেছে। Full video list email-এ intentionally রাখা হয়নি।</p>

          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="margin-top:22px;">
            <tr>
              <td valign="top" width="52%" style="padding-right:16px;">
                <h3 style="margin:0 0 8px;font-size:14px;">Top active channels</h3>
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">{top_rows}</table>
              </td>
              <td valign="top" width="48%" style="padding:16px;border-radius:14px;background:#f6f6f6;">
                <h3 style="margin:0 0 11px;font-size:14px;">Source health</h3>
                <p style="margin:0 0 7px;font-size:13px;color:#444;"><strong>{checked}/{requested}</strong> channels checked</p>
                <p style="margin:0 0 7px;font-size:13px;color:#444;"><strong>{warnings}</strong> partial warnings</p>
                <p style="margin:0 0 7px;font-size:13px;color:#444;">Discovery: <strong>{html.escape(str(secondary_health.get('query') or 'rotation idle'))}</strong></p>
                <p style="margin:0;font-size:11px;color:#777;">Feed updated {html.escape(updated_text)}</p>
              </td>
            </tr>
          </table>

          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="margin-top:26px;">
            <tr><td align="center">
              <a href="{html.escape(site_url)}" style="display:inline-block;padding:14px 24px;border-radius:24px;background:#ff0033;color:#fff;text-decoration:none;font-size:14px;font-weight:800;">Open Shorts & Long Video Playlists</a>
            </td></tr>
          </table>
          <p style="margin:22px 0 0;padding-top:18px;border-top:1px solid #ededed;color:#777;font-size:11px;line-height:1.6;text-align:center;">Watched videos Home থেকে automatically hide হবে। Watch state এই browser/device-এ private localStorage-এ থাকে।</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""
    return {
        "subject": subject,
        "html": html_body,
        "text": text_body,
        "summary": {
            "period": period,
            "windowStart": start.isoformat(),
            "windowEnd": end.isoformat(),
            "total": total,
            "longVideos": longs,
            "shorts": shorts,
            "primary": primary,
            "secondary": secondary,
            "channelsChecked": checked,
            "channelsRequested": requested,
            "warnings": warnings,
            "siteUrl": site_url,
        },
    }


def send_resend(recipient: str, subject: str, html_body: str, text_body: str) -> dict[str, Any]:
    api_key = os.getenv("RESEND_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("RESEND_API_KEY is missing")
    payload = {
        "from": os.getenv("RESEND_FROM", "NexaFeed <onboarding@resend.dev>"),
        "to": [recipient],
        "subject": subject,
        "html": html_body,
        "text": text_body,
    }
    payload_path = ""
    config_path = ""
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as payload_file:
            json.dump(payload, payload_file, ensure_ascii=False)
            payload_path = payload_file.name
        with tempfile.NamedTemporaryFile("w", suffix=".curl", delete=False) as config_file:
            os.chmod(config_file.name, 0o600)
            config_file.write('url = "https://api.resend.com/emails"\n')
            config_file.write('request = "POST"\n')
            config_file.write('silent\nshow-error\n')
            config_file.write('header = "Authorization: Bearer ' + api_key.replace('"', '') + '"\n')
            config_file.write('header = "Content-Type: application/json"\n')
            config_file.write('data-binary = "@' + payload_path.replace('"', '') + '"\n')
            config_path = config_file.name
        process = subprocess.run(["curl", "--config", config_path], capture_output=True, text=True, timeout=45)
        if process.returncode != 0:
            raise RuntimeError((process.stderr or process.stdout)[:500])
        result = json.loads(process.stdout)
        if not result.get("id"):
            raise RuntimeError(f"Unexpected Resend response: {result}")
        return {"provider": "resend", "accepted": True, "id": result["id"]}
    finally:
        for path in (payload_path, config_path):
            if path:
                try:
                    Path(path).unlink()
                except OSError:
                    pass


def send_smtp(recipient: str, subject: str, html_body: str, text_body: str) -> dict[str, Any]:
    host = os.getenv("EMAIL_SMTP_HOST", "").strip()
    port = int(os.getenv("EMAIL_SMTP_PORT", "587"))
    username = (os.getenv("EMAIL_SMTP_USERNAME") or os.getenv("EMAIL_ADDRESS") or "").strip()
    password = os.getenv("EMAIL_PASSWORD", "")
    from_addr = (os.getenv("EMAIL_FROM_ADDRESS") or os.getenv("EMAIL_ADDRESS") or username).strip()
    if not all([host, username, password, from_addr]):
        raise RuntimeError("SMTP configuration is incomplete")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = from_addr
    message["To"] = recipient
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")
    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=45) as smtp:
            smtp.login(username, password)
            rejected = smtp.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=45) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(username, password)
            rejected = smtp.send_message(message)
    return {"provider": "smtp", "accepted": rejected == {}, "host": host}


def deliver(recipient: str, report: dict[str, Any]) -> dict[str, Any]:
    errors = []
    if os.getenv("RESEND_API_KEY"):
        try:
            return send_resend(recipient, report["subject"], report["html"], report["text"])
        except Exception as exc:
            errors.append(f"Resend: {exc}")
    try:
        result = send_smtp(recipient, report["subject"], report["html"], report["text"])
        if errors:
            result["fallbackAfter"] = errors
        return result
    except Exception as exc:
        errors.append(f"SMTP: {exc}")
        raise RuntimeError("; ".join(errors))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Send a compact NexaFeed count-and-link email")
    parser.add_argument("--period", choices=["morning", "midnight"], required=True)
    parser.add_argument("--email", default="")
    parser.add_argument("--site-url", default="")
    parser.add_argument("--env-file", type=Path, help="Optional .env file to load before sending")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    load_env_files(args.env_file)
    config = load_json(CONFIG_PATH, {})
    site_url = args.site_url or config.get("siteUrl") or "https://developerjillur.github.io/nexafeed/"
    report = build_report(args.period, site_url)
    recipients = parse_recipients(args.email) or parse_recipients(
        os.getenv("NEXAFEED_EMAIL_RECIPIENTS") or os.getenv("EMAIL_HOME_ADDRESS") or ""
    )
    if not recipients and not args.dry_run:
        raise RuntimeError("No email recipient configured")

    report_dir = report_output_dir()
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(BD_TZ).strftime("%Y-%m-%d_%H-%M-%S")
    html_path = report_dir / f"{stamp}_{args.period}.html"
    json_path = report_dir / f"{stamp}_{args.period}.json"
    html_path.write_text(report["html"], encoding="utf-8")
    json_path.write_text(json.dumps(report["summary"], ensure_ascii=False, indent=2), encoding="utf-8")

    deliveries = {}
    if not args.dry_run:
        for recipient in recipients:
            try:
                deliveries[recipient] = deliver(recipient, report)
            except Exception as exc:
                deliveries[recipient] = {"accepted": False, "error": str(exc)}
    result = {
        "ok": args.dry_run or any(value.get("accepted") for value in deliveries.values()),
        "dryRun": args.dry_run,
        "period": args.period,
        "recipients": recipients,
        "summary": report["summary"],
        "deliveries": deliveries,
        "renderedHtml": str(html_path),
        "summaryJson": str(json_path),
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
