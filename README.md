# NexaFeed

NexaFeed is a static, YouTube-style personal video dashboard for monitored channels and secondary topic discovery. It separates Shorts and long videos, plays through the YouTube iframe API, advances playable queues, and hides watched videos from normal playback after they are watched in the current browser.

**Live site:** https://developerjillur.github.io/nexafeed/

## Product behavior

- Responsive Home, Shorts, Long Videos, History, Search, and Feed Settings views
- Primary monitored channels ranked before keyword, topic, and category discovery
- Separate Shorts and long-video queues
- YouTube iframe playback with runtime error fallback and next-playable auto-skip
- Long-video autoplay, partial progress persistence, and resume position
- Shorts navigation by arrows, keyboard, mouse wheel, touch swipe, and playback-ended auto-next
- YouTube-style Shorts action rail with cached likes, comments, description, share, and channel links
- Bounded public comments and descriptions cached by the server-side collector
- 80% watch threshold plus watched, partially watched, unwatched, and new visual states
- Watched videos removed from Home, search results, long-video queues, and Shorts playback queues but retained in Watch History
- JSON watch-state export/import for moving browser-local history
- Compact morning and midnight email summaries

The initial source set contains 33 supplied channels: 26 Long + Shorts and 7 Shorts-only. Feed Settings can safely manage between 1 and 100 channels.

## Data architecture

- `data/channels.csv`: monitored sources, type flags, categories, and priorities
- `data/original-channel-categories.csv`: original supplied CSV preserved for reference
- `data/videos.json`: filtered feed consumed by the frontend
- `data/video-details.json`: bounded embed status, descriptions, likes, and cached comments
- `data/feed-settings.json`: public editable settings model consumed by the manager
- `data/channel-cache.json`: handle-to-channel-ID resolution cache
- `data/discovery-log.json`: bounded run and discovery history used by aggregate emails
- `config.json`: public collection limits, metadata TTLs, discovery terms, timezone, and live URL
- `.env.example`: private runtime/API/email/provider configuration template

No YouTube, GitHub, email, LLM, or SMTP credential is stored in the public frontend or generated data.

## Public setup model

NexaFeed is no longer tied to Hermes-only automation. The same repo can be refreshed from:

1. Hermes cron or Hermes Gateway
2. normal macOS/Linux cron
3. Codex, Claude Code, or any local coding-agent app that can run shell commands
4. GitHub Actions `workflow_dispatch`
5. a plain terminal

The current feed collector does **not** require an LLM key. It uses public YouTube pages/RSS plus `yt-dlp` for rich metadata and embed checks. LLM/provider configuration is still standardized in env so optional future AI steps can run with OpenAI, Anthropic, OpenRouter, Gemini, Groq, Mistral, DeepSeek, xAI, Z.ai/GLM, Ollama, or any OpenAI-compatible endpoint without code changes.

## Environment configuration

Copy the template and fill only what you need:

```bash
cp .env.example .env.local
```

Secrets must stay in one of these places:

- local/Codex/Claude/manual terminal: `.env.local` or an explicit `--env-file`
- Hermes cron: `$HERMES_HOME/.env` or `~/.hermes/.env`
- GitHub Actions: repository **Secrets** and non-secret **Variables**
- production server: system environment or a private env file outside the public checkout

`.env`, `.env.*`, and reports are gitignored. `.env.example` is safe to commit because it contains no real values.

### LLM/provider env keys

Use one generic key pair for OpenAI-compatible/custom providers:

```bash
NEXAFEED_LLM_PROVIDER=custom
NEXAFEED_LLM_MODEL=your-model-name
NEXAFEED_LLM_BASE_URL=https://your-provider.example/v1
NEXAFEED_LLM_API_KEY=your-private-key
```

Or use provider aliases:

```bash
NEXAFEED_LLM_PROVIDER=openai
NEXAFEED_LLM_MODEL=gpt-4o-mini
OPENAI_API_KEY=your-private-key

NEXAFEED_LLM_PROVIDER=anthropic
NEXAFEED_LLM_MODEL=claude-3-5-haiku-latest
ANTHROPIC_API_KEY=your-private-key

NEXAFEED_LLM_PROVIDER=openrouter
NEXAFEED_LLM_MODEL=openai/gpt-4o-mini
OPENROUTER_API_KEY=your-private-key
```

For Ollama/local models:

```bash
NEXAFEED_LLM_PROVIDER=ollama
NEXAFEED_LLM_MODEL=llama3.1
OLLAMA_HOST=http://127.0.0.1:11434/v1
```

Provider values supported by `scripts/nexafeed_env.py`: `openai`, `anthropic`, `openrouter`, `google`, `groq`, `mistral`, `deepseek`, `xai`, `zai`, `ollama`, `custom`, and `none`.

Check setup without printing secrets:

```bash
python3 scripts/nexafeed_doctor.py
python3 scripts/nexafeed_doctor.py --require-llm
```

## Install local dependencies

The static frontend has no build step. The collector needs Python 3 and `yt-dlp` for rich metadata:

```bash
python3 --version
python3 -m pip install --upgrade yt-dlp
```

If `yt-dlp` is installed in a non-standard place, set:

```bash
NEXAFEED_YT_DLP=/absolute/path/to/yt-dlp
```

## Refresh the feed

Refresh locally without publishing:

```bash
python3 scripts/nexafeed_update.py
```

Refresh, commit generated data, and push:

```bash
python3 scripts/nexafeed_update.py --publish
```

Recommended production-safe wrapper:

```bash
python3 scripts/nexafeed_automation.py --pull-first --require-clean --publish
```

Useful diagnostics:

```bash
python3 scripts/nexafeed_update.py --dry-run
python3 scripts/nexafeed_update.py --dry-run --no-details
python3 scripts/nexafeed_automation.py --dry-run --no-details
```

All commands also accept `--env-file /path/to/private.env`.

## Hermes cron mode

Keep Hermes cron simple and deterministic by calling the repo wrapper from the repo workdir:

```bash
cd /path/to/nexafeed
python3 scripts/nexafeed_automation.py --pull-first --require-clean --publish
```

The wrapper loads `$HERMES_HOME/.env` automatically when Hermes is running, but it also works outside Hermes. It refuses to publish over a dirty tree when `--require-clean` or `--pull-first` is used, then runs `git pull --ff-only origin main` before collection so owner-applied web settings are synchronized safely.

For Hermes scheduled jobs, the Gateway must be running for cron to fire automatically:

```bash
hermes cron status
```

## Normal cron mode

Example hourly cron entry:

```cron
53 * * * * cd /path/to/nexafeed && /usr/bin/python3 scripts/nexafeed_automation.py --pull-first --require-clean --publish >> "$HOME/.nexafeed/update.log" 2>&1
```

For a private env file outside the repo:

```cron
53 * * * * cd /path/to/nexafeed && /usr/bin/python3 scripts/nexafeed_automation.py --env-file "$HOME/.config/nexafeed.env" --pull-first --require-clean --publish >> "$HOME/.nexafeed/update.log" 2>&1
```

## Codex / Claude / other coding-agent mode

A coding-agent app only needs shell access to the checkout:

```bash
git clone https://github.com/<owner>/nexafeed.git
cd nexafeed
cp .env.example .env.local
python3 -m pip install --upgrade yt-dlp
python3 scripts/nexafeed_doctor.py
python3 scripts/nexafeed_automation.py --dry-run --no-details
```

If the agent should publish data, give it a normal Git remote/auth setup and run:

```bash
python3 scripts/nexafeed_automation.py --pull-first --require-clean --publish
```

## GitHub Actions mode

The workflow `.github/workflows/update-feed.yml` can refresh the feed manually from the Actions tab. Configure provider/site values in repository Secrets/Variables if needed, then run **Update NexaFeed feed**. Email delivery secrets are intentionally not exposed to this refresh workflow; use the separate digest script from a private scheduler for reports.

Important notes:

- The workflow installs `yt-dlp`, runs `scripts/nexafeed_doctor.py`, refreshes with `scripts/nexafeed_automation.py`, verifies the repo, commits generated data when `publish=true`, and deploys Pages in the same workflow.
- It does not rely on Hermes.
- It does not print API keys.
- It is manual by default to avoid double-refreshing when Hermes/local cron is already active. Add a `schedule:` block only after deciding GitHub Actions should own refresh timing.
- External GitHub Actions are pinned to commit SHAs, main-branch writers share one concurrency group, and Pages deployments queue in one deploy group to avoid publish collisions.

## Feed Settings workflow

The static GitHub Pages frontend cannot safely write repository files directly. NexaFeed therefore uses an owner-controlled workflow:

1. Open **Feed Settings**.
2. Add, edit, remove, filter, or reset channel rows.
3. Edit keywords, topics, and categories.
4. Select **Review and apply on GitHub**.
5. Review the readable change summary and submit the prefilled issue while signed in as the repository owner.
6. `.github/workflows/apply-feed-settings.yml` validates the compressed payload, updates the CSV/config, commits, deploys, comments on the issue, and closes it.
7. The next clean scheduled refresh pulls the approved settings and rebuilds the feed.

Only an exact-title settings issue opened by a GitHub account with repository `OWNER` author association can run the apply job. The server validator limits channel counts, term counts, URL hosts, priorities, payload size, and decompression size.

## Rich metadata policy

The collector uses `yt-dlp` server-side. The browser never receives a YouTube API key.

- Explicit `playable_in_embed: false` videos are removed before publishing.
- Unknown embed status is retained rather than incorrectly deleting a valid video.
- Missing/stale metadata is refreshed on a TTL instead of scraping every video every hour.
- Confirmed blocked videos are rechecked more frequently in case the owner changes embedding permissions.
- Comments are opt-in only for a bounded set of recent Shorts and are capped per video.
- Runtime iframe errors are still handled because availability can change after collection.

Public comment extraction is best-effort. Comments may be disabled, login-gated, rate-limited, or temporarily unavailable when YouTube changes its markup.

## Email reports

Dry-run previews:

```bash
python3 scripts/nexafeed_digest_email.py --period morning --dry-run
python3 scripts/nexafeed_digest_email.py --period midnight --dry-run
```

Scheduled sends use `NEXAFEED_EMAIL_RECIPIENTS` or `EMAIL_HOME_ADDRESS` from env, with Resend first and SMTP fallback. Reports contain aggregate counts and the live link, not a full video dump.

## Verification

```bash
node --check app.js
python3 -m py_compile scripts/*.py
python3 tests/test_nexafeed_features.py -v
python3 scripts/verify_nexafeed.py
python3 scripts/nexafeed_doctor.py --allow-missing-yt-dlp
```

`verify_nexafeed.py` checks dynamic channel consistency, feed stats, source ownership, video IDs, blocked-video leakage, rich metadata coverage, bounded comments, settings parity, required frontend/config markers, workflow files, SHA-pinned Actions, env-template safety, and common credential signatures.

## Static-site limitations

### Watch history

History and progress use browser `localStorage`. They persist on the same browser/device but do not automatically synchronize between devices. Use **Feed Settings → Export history JSON / Import history JSON** to move state. Automatic cross-device synchronization requires an authenticated backend such as Supabase or Firebase.

### YouTube interactions

NexaFeed can display cached public metadata and open the original YouTube page. It cannot post comments, replies, likes, or subscriptions as the user. Those actions require authenticated YouTube OAuth/API access and are intentionally redirected to YouTube.

### Availability

Collector filtering reduces dead embeds but cannot guarantee permanent playback. A video can become private, removed, age-restricted, region-restricted, or embedding-disabled after a refresh. Runtime handling removes that video from the current browser session and advances to the next playable item.

### Scheduling ownership

Use only one active publisher at a time. Hermes cron, normal cron, and GitHub Actions can all run the same wrapper, but two publishers running together may race to commit generated JSON. If moving from Hermes to GitHub Actions, pause the old scheduler first.
