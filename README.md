# NexaFeed

NexaFeed is a static, YouTube-style personal watch dashboard for the 33 channels in `data/channels.csv`. It separates Shorts and long videos, plays through the YouTube iframe API, automatically advances queues, and hides watched videos from Home on the current browser.

**Live site:** https://developerjillur.github.io/nexafeed/

## What is included

- Responsive YouTube-inspired Home, Shorts, Long Videos, History, Search, and Settings views
- Separate Shorts and long-video playlists
- Embedded YouTube playback and autoplay-next for long videos
- Shorts navigation by arrows, keyboard, mouse wheel, touch swipe, and automatic next after playback ends
- 80% watch threshold, partial progress bars, resume position, and watched/unwatched/new color states
- Watched videos hidden from Home and retained in Watch History
- JSON watch-history export/import for moving browser-local state
- User-supplied 33-channel CSV only, with 26 long+Shorts and 7 Shorts-only sources
- Primary channels before secondary keyword/topic/category discoveries
- Key-free public RSS/channel-page collector (no YouTube Data API secret required)
- Compact 10:00 AM and 12:00 AM email reports with counts and the live link, not a full video dump

## Data files

- `data/channels.csv`: normalized monitoring controls
- `data/original-channel-categories.csv`: the supplied source CSV, preserved verbatim
- `data/videos.json`: current public feed consumed by the site
- `data/channel-cache.json`: public handle-to-channel-ID resolution cache
- `data/discovery-log.json`: bounded discovery/run history used for count-only emails
- `config.json`: keywords, topics, categories, limits, and live URL

`Monitor Long` and `Monitor Shorts` accept `yes` or `no`. Priority channel content always sorts before secondary discovery results.

## Refresh the feed

```bash
python3 scripts/nexafeed_update.py
```

To refresh, commit generated data, and push the live site:

```bash
python3 scripts/nexafeed_update.py --publish
```

The Hermes hourly job runs the publish command. A GitHub Pages workflow deploys every push to `main`.

## Email report commands

Dry-run previews:

```bash
python3 scripts/nexafeed_digest_email.py --period morning --dry-run
python3 scripts/nexafeed_digest_email.py --period midnight --dry-run
```

Actual scheduled sends use `EMAIL_HOME_ADDRESS` (or `NEXAFEED_EMAIL_RECIPIENTS`) from `~/.hermes/.env`, with Resend first and Brevo SMTP fallback.

## Verify

```bash
node --check app.js
python3 -m py_compile scripts/nexafeed_update.py scripts/nexafeed_digest_email.py scripts/verify_nexafeed.py
python3 scripts/verify_nexafeed.py
```

## Important static-site limitation

Watch history and progress use browser `localStorage`. That means watched items stay hidden on the same browser/device, but do not automatically synchronize between devices. Use **Settings → Export history JSON / Import history JSON** when moving state. A future login/backend can provide cross-device history if needed.

Embedded playback also depends on each video owner allowing third-party embedding. When embedding is disabled, NexaFeed shows an **Open on YouTube** fallback.
