#!/usr/bin/env python3
"""Hermes, cron, Codex/Claude, and CI-friendly NexaFeed update wrapper."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[0]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from nexafeed_env import env_flag, env_int, load_env_files  # noqa: E402


def run(command: list[str], *, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def git_status_short() -> list[str]:
    completed = run(["git", "status", "--short"], timeout=30)
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "git status failed").strip())
    return completed.stdout.strip().splitlines()


def require_clean_tree(reason: str) -> None:
    dirty = git_status_short()
    if dirty:
        preview = "; ".join(dirty[:12])
        raise RuntimeError(f"refusing to {reason} with a dirty working tree: {preview}")


def git_pull_ff_only() -> dict[str, Any]:
    completed = run(["git", "pull", "--ff-only", "origin", "main"], timeout=120)
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "git pull failed").strip()[-1000:])
    return {"ok": True, "output": (completed.stdout or completed.stderr or "").strip()[-1000:]}


def parse_child_json(stdout: str) -> dict[str, Any]:
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return {"ok": False, "error": "child process did not print JSON", "stdoutTail": stdout[-1000:]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run NexaFeed update safely from Hermes cron, normal cron, local agents, or CI")
    parser.add_argument("--env-file", type=Path, help="Optional .env file to load before running")
    parser.add_argument("--publish", action="store_true", help="Commit generated data and push origin/main")
    parser.add_argument("--dry-run", action="store_true", help="Collect and report without writing files")
    parser.add_argument("--pull-first", action="store_true", help="Run git pull --ff-only origin main before collection")
    parser.add_argument("--require-clean", action="store_true", help="Refuse to run if the working tree is dirty")
    parser.add_argument("--no-secondary", action="store_true", help="Skip this run's topic search")
    parser.add_argument("--no-details", action="store_true", help="Reuse cached embed/comment details without probing")
    parser.add_argument("--workers", type=int, default=None)
    args = parser.parse_args(argv)

    started = time.monotonic()
    loaded_env_files = load_env_files(args.env_file)
    publish = args.publish or env_flag("NEXAFEED_PUBLISH", default=False)
    dry_run = args.dry_run or env_flag("NEXAFEED_DRY_RUN", default=False)
    pull_first = args.pull_first or env_flag("NEXAFEED_PULL_FIRST", default=False)
    require_clean = args.require_clean or env_flag("NEXAFEED_REQUIRE_CLEAN", default=False)
    no_secondary = args.no_secondary or env_flag("NEXAFEED_NO_SECONDARY", default=False)
    no_details = args.no_details or env_flag("NEXAFEED_NO_DETAILS", default=False)
    workers = args.workers if args.workers is not None else env_int("NEXAFEED_WORKERS", 6, minimum=1, maximum=30)

    result: dict[str, Any] = {
        "ok": False,
        "repo": str(ROOT),
        "envFilesLoaded": loaded_env_files,
        "mode": {
            "publish": publish,
            "dryRun": dry_run,
            "pullFirst": pull_first,
            "requireClean": require_clean,
            "noSecondary": no_secondary,
            "noDetails": no_details,
            "workers": workers,
        },
    }
    try:
        if require_clean or pull_first or publish:
            require_clean_tree("run NexaFeed automation")
        if pull_first:
            result["pull"] = git_pull_ff_only()
            if require_clean or publish:
                require_clean_tree("publish NexaFeed automation after pull")

        update_command = [sys.executable, str(SCRIPT_DIR / "nexafeed_update.py"), "--workers", str(workers)]
        if publish:
            update_command.append("--publish")
        if dry_run:
            update_command.append("--dry-run")
        if no_secondary:
            update_command.append("--no-secondary")
        if no_details:
            update_command.append("--no-details")
        child = run(update_command, timeout=1800)
        child_json = parse_child_json(child.stdout)
        result.update(
            {
                "ok": child.returncode == 0 and bool(child_json.get("ok")),
                "update": child_json,
                "returnCode": child.returncode,
                "stderrTail": child.stderr.strip()[-1000:],
                "durationSeconds": round(time.monotonic() - started, 2),
            }
        )
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["ok"] else child.returncode or 1
    except Exception as exc:
        result.update(
            {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "durationSeconds": round(time.monotonic() - started, 2),
            }
        )
        print(json.dumps(result, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
