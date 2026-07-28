# Contributing to YourTube

Thanks for helping improve **YourTube - A personal YouTube Package**.

YourTube is intentionally simple: static frontend, public JSON data, no frontend secrets, and automation that can run from GitHub Actions, Hermes Agent, Claude Code, Codex, or normal cron.

## Good contributions

- Better static UI and accessibility.
- Safer feed settings validation.
- Better documentation for new users and AI agents.
- New tests for watched filtering, Shorts, local likes, Feed Settings, scheduling, or provider config.
- Security hardening for GitHub Actions and generated public files.

## Before opening a PR

Run:

```bash
python3 tests/test_nexafeed_features.py -v
/usr/bin/python3 -m py_compile scripts/*.py
node --check app.js
python3 scripts/verify_nexafeed.py
git diff --check
```

## Security rules

- Never commit `.env`, `.env.*`, API keys, tokens, SMTP passwords, OAuth tokens, or private local paths.
- Keep frontend JavaScript secret-free.
- Keep provider config in environment variables, `.env` files, or GitHub Secrets.
- Keep workflow actions SHA-pinned when editing `.github/workflows/*.yml`.

## Product rules

- Do not download or rehost YouTube videos.
- Use YouTube embeds / YouTube IFrame API only.
- Account-level YouTube actions require OAuth/backend and must not be faked in the static app.
- Browser-local likes/history are okay as long as they are clearly local.

## Naming

The public product name is **YourTube**. The historical repo/script/env prefix is still `nexafeed` for backward compatibility with existing deployments and cron jobs.
