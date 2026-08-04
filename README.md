# YourTube - A personal YouTube Package

**Watch only those valuable for you.**

YourTube is a forkable, static, YouTube-style personal feed dashboard. It helps you turn a noisy YouTube habit into a controlled watchlist: your priority channels first, Shorts and long videos separated, watched items hidden from normal queues, and refresh automation that can run from Hermes, Codex, Claude Code, GitHub Actions, normal cron, or a plain terminal.

[![Live demo](https://img.shields.io/badge/live-demo-red?style=for-the-badge)](https://developerjillur.github.io/nexafeed/)
[![GitHub Pages](https://img.shields.io/badge/deploy-GitHub%20Pages-111?style=for-the-badge&logo=github)](https://developerjillur.github.io/nexafeed/)
[![No backend required](https://img.shields.io/badge/backend-not%20required-0b8?style=for-the-badge)](#how-it-works)
[![AI agent friendly](https://img.shields.io/badge/AI%20agent-Hermes%20%7C%20Codex%20%7C%20Claude-blueviolet?style=for-the-badge)](#copy-paste-prompt-for-any-ai-agent)

**Live demo:** https://developerjillur.github.io/nexafeed/

> YourTube is not affiliated with YouTube or Google. It embeds public YouTube videos through the official YouTube iframe player and links back to YouTube for account-level actions.

## Screenshots

| Home feed | Shorts player | Feed Settings |
|---|---|---|
| ![YourTube home feed screenshot](docs/screenshots/yourtube-home.png) | ![YourTube Shorts screenshot](docs/screenshots/yourtube-shorts.png) | ![YourTube Feed Settings screenshot](docs/screenshots/yourtube-settings.png) |

## Why this exists

YouTube is good at keeping you watching. It is not always good at helping you watch intentionally.

YourTube was built for people who follow specific creators, topics, and research areas but do not want their feed controlled only by recommendations. The goal is simple: keep the videos that matter, separate Shorts from long videos, remove what you already watched, and make the whole thing easy to run on your own GitHub account.

The default public demo uses the current NexaLance AI/web-development source setup so you can see a real feed immediately. Fork users can replace the channels and discovery terms with their own.

## What you get

| Area | Features |
|---|---|
| Personal feed | Priority channel feed, topic/keyword discovery, category chips, fresh/new indicators |
| Shorts | Dedicated Shorts tab, YouTube-style overlay, exact History/Ignored replay, 10-second directional back/forward history, keyboard/wheel/swipe navigation |
| Long videos | Full-width watch layout, autoplay queue, incomplete-progress resume, next playable queue, 10-second transient Previous backtracking |
| Watch control | Manual skip sends under-threshold videos to an Ignored list, 30-second / half-Short threshold sends meaningful views to Watch History, normal queues hide watched and ignored items |
| Watch history | Browser-local watched/progress/ignored state, Watch History tab, Ignored videos tab, export/import history JSON |
| Local likes | Local favorite/liked state, Liked tab, export likes JSON, clear liked state |
| AI handoff | Ask Gemini copies a full A-to-Z summary/transcription prompt; NotebookLM opens a new notebook with the canonical YouTube source URL; neither action needs a frontend secret |
| Video actions | Right-click a card, Up Next item, or app-owned player surface for New Tab, New Window, YouTube, copy-link, local Like, Gemini, NotebookLM, Float, Mark watched, and Ignore actions; visible More buttons provide the same menu on touch devices |
| Floating playback | Validated same-origin pop-out player with in-page draggable fallback, canonical YouTube links, progress resume, and browser-local watched/progress updates |
| Feed Settings | Add/edit/remove channels, set long/Shorts monitoring per source, edit keywords/topics/categories, submit owner-reviewed GitHub issue |
| Automation | Runs from Hermes cron, normal cron, Codex, Claude Code, local terminal, or GitHub Actions |
| Provider config | Env-based LLM/provider settings for future AI steps: OpenAI, Anthropic, OpenRouter, Gemini, Groq, Mistral, DeepSeek, xAI, Z.ai/GLM, Ollama, or custom OpenAI-compatible endpoints |
| Static safety | No frontend API keys, exact YouTube ID/channel destination validation, isolated external popups, sanitized widget referrers, no backend required, GitHub Actions SHA-pinned |
| Email reports | Morning and midnight count/link digests through Resend or SMTP from private env only |

## Current default demo setup

The demo at `developerjillur.github.io/nexafeed` ships with the existing AI, automation, coding, marketing, and web-development source setup.

Release snapshot:

- 33 monitored channels
- 327 playable feed items
- 161 long videos
- 166 Shorts
- 287 primary channel items
- 40 topic/keyword/category discovery items
- Asia/Dhaka timezone

Files that define the default setup:

```text
data/channels.csv                         primary monitored channels
data/original-channel-categories.csv      original source/category reference
data/feed-settings.json                   public settings model used by the UI
config.json                               site name, live URL, discovery terms, limits, metadata TTLs
```

## How it works

YourTube is a static GitHub Pages app plus a Python collector.

```text
YouTube public pages/RSS/search
        ↓
scripts/nexafeed_update.py
        ↓
data/videos.json + data/video-details.json + data/feed-settings.json
        ↓
index.html + app.js + style.css
        ├── video-actions.mjs      validated deep links and YouTube destinations
        ├── short-history.mjs      transient directional Shorts history
        └── float.html             isolated same-origin pop-out player
        ↓
GitHub Pages
```

The browser only reads static JSON and embeds videos with the YouTube iframe API. Secrets stay outside the public site:

- local runs: `.env.local` or `--env-file`
- Hermes runs: `$HERMES_HOME/.env` or `~/.hermes/.env`
- GitHub Actions: repository Secrets and Variables
- public frontend: no secrets

The repository and runtime env names still use `nexafeed` / `NEXAFEED_*` for backward compatibility with the original package path and deployed URL. The public product name is YourTube.

The **Ask Gemini** action is frontend-only. It opens `gemini.google.com` with the selected YouTube video link and also copies the prompt to the clipboard, so it works without storing any Gemini API key or Google credential in the public site.

The **NotebookLM** action is also frontend-only. It opens a new notebook with the canonical YouTube watch URL as the source and copies the source URL as a manual fallback. Gemini and NotebookLM first create a blank browser tab, remove its `window.opener`, and only then navigate to the external service.

The **Float** action prefers the dedicated same-origin `float.html` pop-out and falls back to an in-page draggable player if popups are blocked. The pop-out accepts only a validated YouTube ID, builds its own canonical watch URL, resumes incomplete progress, strips query/hash data from the YouTube widget referrer, and disconnects itself from the opener window. It saves progress every 1.5 seconds and finalizes the watched/ignored threshold on Close or page exit. Both float modes stop without re-finalizing when the same video is explicitly ignored or removed from Watch History, so stale callbacks cannot reverse that action.

### Right-click and video actions

- Every feed card and **Up Next** item is a real same-origin link. Normal clicks stay inside YourTube, while Command/Ctrl-click, Shift-click, middle-click, and browser link behavior remain available.
- Right-click a real card or **Up Next** link to keep the browser's native link menu. Use the adjacent visible **More** button for YourTube actions. App-owned non-link player surfaces and narrow player edge rails can open YourTube's **Video actions** menu directly; Shift + right-click bypasses that custom handling. Shorts and long-video players also expose a visible **More** button for touch and keyboard users.
- The menu includes **Open in new tab**, **Open in new window**, **Open on YouTube**, **Copy YourTube link**, **Copy YouTube link**, local Like/Unlike, Ask Gemini, NotebookLM, Float player, Mark/Remove watched, and Ignore/Remove ignored actions.
- Keyboard users can open the menu with the Context Menu key or Shift + F10, move with Arrow Up/Down, jump with Home/End, and close with Escape or Tab. Closing restores focus to the trigger, and player navigation shortcuts do not leak through while the menu is open.
- On mobile and short-height screens, the action stack/menu scrolls so every action remains reachable.
- A copied/opened YourTube URL contains an exact playback deep link such as `?play=00kEcNby86c&type=short&view=history`. Requests are accepted only for a valid 11-character YouTube ID and a matching video already present in the feed. This allows exact watched/ignored replay without unhiding unrelated hidden items.
- The center of the embedded YouTube player is a cross-origin iframe owned by YouTube. YourTube deliberately does not place a pointer-active overlay over it, because that would block Play/Pause, timeline, volume, captions, settings, and fullscreen controls. Use YouTube's own context menu there, or use the adjacent **More** button for YourTube actions.

### Privacy and destination safety

- Like, watched, ignored, and progress changes affect only this browser's `localStorage`; they do not mutate the signed-in YouTube account.
- Video and channel destinations are rebuilt from validated IDs/handles instead of trusting URLs supplied by feed JSON. Invalid destinations fall back to the YouTube homepage.
- External actions use canonical HTTPS URLs. New external tabs are detached from the parent before cross-origin navigation.
- YouTube `widget_referrer` values include only the app origin and pathname, never the current deep-link query or hash.
- `video-actions.mjs` and `float.html` are required deployment artifacts in the Pages, feed-update, and owner-settings workflows, and both are included in the repository verifier/credential scan.

## Watched vs Ignored rules

YourTube keeps playback decisions private in browser `localStorage`:

- If a running video is skipped, closed, changed with keyboard arrows, changed with wheel/scroll, or replaced by another video before the watch threshold, it goes to **Ignored videos**.
- Choosing **Ignore** for the currently playing Long or Short stops/replaces that player first, so a still-running progress timer cannot immediately promote the explicitly ignored video to Watch History. Superseded YouTube player callbacks are generation-guarded for the same reason.
- Ignored videos stay out of Home, Shorts, Long videos, fresh/new filters, and Up Next queues.
- Long videos go to **Watch history** only after at least **30 seconds** of watch time, or after the video naturally finishes.
- For Shorts with a known duration, watching **half of the Short** is enough. Example: a 40-second Short counts as watched after 20 seconds.
- Manual skip/next/scroll never uses the old 5-second shortcut. Under-threshold exits stay **Ignored** even when some progress was saved.
- Inside the same long-video player session, the Previous button or upward wheel/scroll can reopen the just-left long video for **10 seconds**, even if that video has already moved into Watch history. The control refreshes when the window expires, so it cannot remain visibly enabled for a target that is no longer eligible. This is only a short backtracking grace window; watched videos still stay hidden from normal feeds and Up Next queues.
- Inside the same Shorts session, including a replay opened from Watch History, Up follows a directional back stack and Down can return through its forward stack for **10 seconds**. A watched Short selected from History opens itself rather than silently jumping to the next unwatched Short. After Next, Previous can immediately return to that selected Short. Expired or unavailable entries are skipped, the history resets when the Shorts overlay closes, and replayed history items remain hidden from normal feeds.
- Watched and ignored records are stored locally for the current feed window plus **1 extra day**, then pruned in the browser. Any watched/ignored video ID still present in the active feed is protected from pruning, so it cannot return as “new” while it remains in `data/videos.json`.
- Browser state is local only. Export history JSON if you want to move watched/progress/ignored state to another device.

## Quick start

```bash
git clone https://github.com/developerjillur/nexafeed.git
cd nexafeed
cp .env.example .env.local
python3 -m pip install --upgrade yt-dlp
python3 scripts/nexafeed_doctor.py
python3 scripts/nexafeed_automation.py --dry-run --no-details --no-secondary --workers 6
```

Preview locally:

```bash
python3 -m http.server 8765
# open http://127.0.0.1:8765/
```

Refresh without publishing:

```bash
python3 scripts/nexafeed_update.py
```

Refresh, commit generated data, and push:

```bash
python3 scripts/nexafeed_automation.py --pull-first --require-clean --publish
```

## Deploy your own live YourTube

1. Fork this repository.
2. Enable GitHub Pages for the repo.
3. Edit `config.json`:

```json
{
  "siteName": "YourTube",
  "tagline": "Watch only those valuable for you",
  "siteUrl": "https://YOUR_GITHUB_USERNAME.github.io/YOUR_REPO/",
  "repositoryUrl": "https://github.com/YOUR_GITHUB_USERNAME/YOUR_REPO"
}
```

4. Keep the default feed or edit `data/channels.csv` and the discovery terms in `config.json`.
5. Push to `main`.
6. Open the Actions tab and run **Update YourTube feed**.
7. Your live URL will be:

```text
https://YOUR_GITHUB_USERNAME.github.io/YOUR_REPO/
```

For this public demo, the live URL is:

```text
https://developerjillur.github.io/nexafeed/
```

## Personalize the feed

You can control the personal feed in two ways.

### Option A: use Feed Settings in the app

1. Open the live site.
2. Go to **Feed Settings**.
3. Add, edit, remove, filter, or reset channel rows.
4. Choose whether each source should monitor long videos, Shorts, or both.
5. Edit keywords, topics, and categories.
6. Click **Review and apply on GitHub**.
7. Submit the prefilled GitHub issue while signed in as the repository owner.
8. GitHub Actions validates the payload, commits the settings, deploys the site, and closes the issue.
9. The next clean refresh rebuilds the feed with your new setup.

The static app never stores a GitHub token in the browser. Settings are applied through an owner-only GitHub Actions workflow.

### Option B: edit files directly

Edit channels:

```text
data/channels.csv
```

Edit discovery terms:

```text
config.json
```

Then run:

```bash
python3 scripts/nexafeed_automation.py --pull-first --require-clean --publish
```

## Environment configuration

Copy the public-safe template:

```bash
cp .env.example .env.local
```

Useful runtime values:

```bash
NEXAFEED_SITE_NAME=YourTube
NEXAFEED_TAGLINE="Watch only those valuable for you"
NEXAFEED_SITE_URL=https://YOUR_GITHUB_USERNAME.github.io/YOUR_REPO/
NEXAFEED_REPOSITORY_URL=https://github.com/YOUR_GITHUB_USERNAME/YOUR_REPO
NEXAFEED_TIMEZONE=Asia/Dhaka
NEXAFEED_BRANCH=main
NEXAFEED_WORKERS=6
```

The current collector does not require an LLM key. Provider settings are included so future AI steps can run without code changes:

```bash
NEXAFEED_LLM_PROVIDER=openrouter
NEXAFEED_LLM_MODEL=openai/gpt-4o-mini
OPENROUTER_API_KEY=your-private-key
```

Generic OpenAI-compatible provider:

```bash
NEXAFEED_LLM_PROVIDER=custom
NEXAFEED_LLM_MODEL=your-model-name
NEXAFEED_LLM_BASE_URL=https://your-provider.example/v1
NEXAFEED_LLM_API_KEY=your-private-key
```

Local Ollama:

```bash
NEXAFEED_LLM_PROVIDER=ollama
NEXAFEED_LLM_MODEL=llama3.1
OLLAMA_HOST=http://127.0.0.1:11434/v1
```

Provider aliases supported by `scripts/nexafeed_env.py`:

```text
openai, anthropic, openrouter, google, gemini, groq, mistral, deepseek, xai, zai, glm, ollama, custom, none
```

Check setup without printing secrets:

```bash
python3 scripts/nexafeed_doctor.py
python3 scripts/nexafeed_doctor.py --require-llm
```

## Schedule recipes

Use only one publisher at a time. If GitHub Actions owns the refresh schedule, pause Hermes/local cron. If Hermes or local cron owns it, keep GitHub Actions manual.

### Normal cron, hourly refresh

```cron
53 * * * * cd /path/to/nexafeed && /usr/bin/python3 scripts/nexafeed_automation.py --pull-first --require-clean --publish >> "$HOME/.yourtube/update.log" 2>&1
```

With a private env file outside the repo:

```cron
53 * * * * cd /path/to/nexafeed && /usr/bin/python3 scripts/nexafeed_automation.py --env-file "$HOME/.config/yourtube.env" --pull-first --require-clean --publish >> "$HOME/.yourtube/update.log" 2>&1
```

### Email digest cron

Morning count/link digest:

```cron
0 10 * * * cd /path/to/nexafeed && /usr/bin/python3 scripts/nexafeed_digest_email.py --period morning --env-file "$HOME/.config/yourtube.env" >> "$HOME/.yourtube/email.log" 2>&1
```

Midnight count/link digest:

```cron
0 0 * * * cd /path/to/nexafeed && /usr/bin/python3 scripts/nexafeed_digest_email.py --period midnight --env-file "$HOME/.config/yourtube.env" >> "$HOME/.yourtube/email.log" 2>&1
```

### Hermes Agent schedule

Open Hermes in the repository and ask it to create these jobs:

```text
Create a Hermes cron job named "YourTube hourly refresh" that runs from this repo every hour at minute 53. It should execute:
python3 scripts/nexafeed_automation.py --pull-first --require-clean --publish

Create a Hermes cron job named "YourTube morning email" that runs daily at 10:00 Asia/Dhaka and executes:
python3 scripts/nexafeed_digest_email.py --period morning

Create a Hermes cron job named "YourTube midnight email" that runs daily at 00:00 Asia/Dhaka and executes:
python3 scripts/nexafeed_digest_email.py --period midnight

Verify with hermes cron status, run a dry-run first, and do not print or commit secrets.
```

Hermes must have its gateway running for scheduled cron jobs to fire automatically:

```bash
hermes cron status
```

### GitHub Actions schedule

The included workflow is manual by default to avoid conflicting with local/Hermes cron. To make GitHub Actions own the schedule, add this to `.github/workflows/update-feed.yml`:

```yaml
on:
  schedule:
    - cron: "53 * * * *"
  workflow_dispatch:
```

Then pause all other publishers.

### Codex, Claude Code, or another coding agent

Give the agent the repo and this command sequence:

```bash
git pull --ff-only origin main
python3 -m pip install --upgrade yt-dlp
python3 scripts/nexafeed_doctor.py
python3 scripts/nexafeed_automation.py --dry-run --no-details --no-secondary --workers 6
python3 scripts/nexafeed_automation.py --pull-first --require-clean --publish
```

## Copy-paste prompt for any AI agent

Paste this into Hermes, Claude Code, Codex, Cursor, or another coding agent after giving it the GitHub repo link:

```text
You are setting up YourTube - A personal YouTube Package.
Tagline: Watch only those valuable for you.

Source repo: https://github.com/developerjillur/nexafeed
Live demo to inspect first: https://developerjillur.github.io/nexafeed/

Goal:
Fork or clone this repo into my GitHub account, keep it public, enable GitHub Pages, and give me a live URL like https://MY_GITHUB_USERNAME.github.io/MY_REPO/.

Rules:
- Do not commit secrets, API keys, tokens, passwords, or local private paths.
- Keep real credentials only in .env.local, an explicit private env file, Hermes env, or GitHub Actions Secrets.
- Keep the NEXAFEED_* env names unless you update all scripts and tests.
- Keep the YouTube iframe/API approach. Do not download or rehost YouTube videos.
- Keep browser-local watch history and local likes unless I ask for a real backend.

Setup steps:
1. Inspect README.md, config.json, data/channels.csv, .env.example, scripts/nexafeed_doctor.py, scripts/nexafeed_automation.py, and .github/workflows/update-feed.yml.
2. Update config.json:
   - siteName: YourTube
   - siteUrl: https://MY_GITHUB_USERNAME.github.io/MY_REPO/
   - repositoryUrl: https://github.com/MY_GITHUB_USERNAME/MY_REPO
3. Keep the default 33-channel AI/web-development feed unless I provide my own channels.
4. If I provide channels, update data/channels.csv and discovery terms in config.json.
5. Run:
   python3 -m pip install --upgrade yt-dlp
   python3 scripts/nexafeed_doctor.py
   python3 scripts/nexafeed_automation.py --dry-run --no-details --no-secondary --workers 6
6. Run verification:
   npm ci
   npx playwright install chromium
   npm run test:browser
   python3 tests/test_nexafeed_features.py -v
   python3 -m py_compile scripts/*.py
   node --check app.js
   node --check short-history.mjs
   node --check video-actions.mjs
   python3 scripts/verify_nexafeed.py
   git diff --check
7. Commit and push.
8. Enable GitHub Pages and run the Update YourTube feed workflow manually.
9. Wait for deploy success and fetch the live URL.
10. Return: repo URL, live URL, what changed, how to refresh, how to edit Feed Settings, and any warnings.
```

Full prompt file: [`docs/AI_SETUP_PROMPT.md`](docs/AI_SETUP_PROMPT.md)

## Verification

```bash
npm ci
npx playwright install chromium
npm run test:browser
node --check app.js
node --check short-history.mjs
node --check video-actions.mjs
python3 -m py_compile scripts/*.py
python3 tests/test_nexafeed_features.py -v
python3 scripts/verify_nexafeed.py
python3 scripts/nexafeed_doctor.py --allow-missing-yt-dlp
git diff --check
```

The Playwright suite in `tests/browser_video_actions.spec.js` exercises desktop/mobile action reachability, native-link boundaries, exact backtracking, popup isolation, active Ignore/Watch-reset races, Float progress/finalization, and stale async initialization. `verify_nexafeed.py` checks dynamic channel consistency, feed stats, source ownership, video IDs, blocked-video leakage, rich metadata coverage, bounded comments, settings parity, required browser/deployment artifacts (including `video-actions.mjs` and `float.html`), public-release docs, screenshots, SHA-pinned Actions, env-template safety, and common credential signatures.

## What YourTube does not do

- It does not post YouTube likes, comments, replies, or subscriptions for you.
- It cannot customize or replace the context menu inside YouTube's cross-origin iframe; use the app-owned More button or edge/card surfaces for YourTube actions.
- It does not bypass YouTube ads or YouTube player policies.
- It does not sync watch history across devices without a backend.
- It does not store API keys in the browser.
- It does not guarantee a video stays playable forever. YouTube availability can change after a refresh.

## Good GitHub topics for discovery

```text
youtube, youtube-shorts, personal-dashboard, github-pages, static-site, ai-agents, hermes-agent, codex, claude-code, automation, yt-dlp, no-backend, localstorage, feed-reader, productivity, creator-tools, python, javascript, open-source
```

## Share copy

Short launch copy:

```text
I released YourTube - A personal YouTube Package.

Tagline: Watch only those valuable for you.

It gives you a forkable YouTube-style dashboard with priority channels, Shorts, long videos, local watch history, local likes, Feed Settings, and scheduled refresh through Hermes, Codex, Claude Code, cron, or GitHub Actions.

Live demo: https://developerjillur.github.io/nexafeed/
GitHub: https://github.com/developerjillur/nexafeed
```

Hashtags:

```text
#YourTube #YouTubeTools #AIAgents #OpenSource #GitHubPages #Automation #ClaudeCode #Codex #HermesAgent #PersonalDashboard #ProductivityTools #YouTubeShorts
```

## License

MIT License. See [`LICENSE`](LICENSE).
