#!/usr/bin/env python3
"""Public-release readiness checks for YourTube setup and provider env."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[0]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from nexafeed_env import load_env_files, resolve_llm_config  # noqa: E402

REQUIRED_FILES = [
    "index.html",
    "style.css",
    "app.js",
    "float.html",
    "config.json",
    ".env.example",
    ".github/workflows/deploy-pages.yml",
    ".github/workflows/apply-feed-settings.yml",
    ".github/workflows/update-feed.yml",
    "scripts/nexafeed_env.py",
    "scripts/nexafeed_update.py",
    "scripts/nexafeed_automation.py",
    "scripts/nexafeed_digest_email.py",
    "scripts/verify_nexafeed.py",
    "data/channels.csv",
    "data/videos.json",
    "data/video-details.json",
]


def run_git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(ROOT), *args],
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def git_status() -> dict[str, Any]:
    if not (ROOT / ".git").is_dir():
        return {"available": False, "clean": None, "branch": None}
    status = run_git("status", "--short")
    branch = run_git("branch", "--show-current")
    return {
        "available": True,
        "clean": status.returncode == 0 and not status.stdout.strip(),
        "branch": branch.stdout.strip() if branch.returncode == 0 else None,
        "status": status.stdout.strip().splitlines()[:30],
    }


def executable_status(command: str) -> dict[str, Any]:
    path = shutil.which(command)
    return {"available": bool(path), "path": path or ""}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check YourTube public/standalone setup readiness")
    parser.add_argument("--env-file", type=Path, help="Optional .env file to load before checking")
    parser.add_argument("--require-llm", action="store_true", help="Fail if no LLM provider/API key is configured")
    parser.add_argument("--allow-missing-yt-dlp", action="store_true", help="Warn instead of failing when yt-dlp is unavailable")
    args = parser.parse_args(argv)

    loaded_env_files = load_env_files(args.env_file)
    missing_files = [relative for relative in REQUIRED_FILES if not (ROOT / relative).is_file()]
    yt_dlp = executable_status("yt-dlp")
    python = {"executable": sys.executable, "version": sys.version.split()[0]}
    llm = resolve_llm_config(required=args.require_llm)
    git = git_status()

    checks = {
        "requiredFiles": {"ok": not missing_files, "missing": missing_files},
        "ytDlp": {"ok": yt_dlp["available"] or args.allow_missing_yt_dlp, **yt_dlp},
        "llm": {"ok": not llm["missing"], **llm},
        "git": git,
    }
    ok = checks["requiredFiles"]["ok"] and checks["ytDlp"]["ok"] and checks["llm"]["ok"]
    result = {
        "ok": ok,
        "repo": str(ROOT),
        "envFilesLoaded": loaded_env_files,
        "python": python,
        "checks": checks,
        "notes": [
            "The current feed collector does not require an LLM key; --require-llm is for optional AI/provider setup checks.",
            "Secrets are reported as configured/not-configured only; values are never printed.",
        ],
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
