# NexaFeed

NexaFeed is a static, YouTube-style personal video dashboard for monitored channels and secondary topic discovery. It separates Shorts and long videos, plays through the YouTube iframe API, advances playable queues, and hides watched videos from Home in the current browser.

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
- Watched videos removed from Home and autoplay queues but retained in Watch History
- JSON watch-state export/import for moving browser-local history
- Compact 10:00 AM and 12:00 AM email summaries

The initial source set contains 33 supplied channels: 26 Long + Shorts and 7 Shorts-only. Feed Settings can safely manage between 1 and 100 channels.

## Data architecture

- `data/channels.csv`: monitored sources, type flags, categories, and priorities
- `data/original-channel-categories.csv`: original supplied CSV preserved for reference
- `data/videos.json`: filtered feed consumed by the frontend
- `data/video-details.json`: bounded embed status, descriptions, likes, and cached comments
- `data/feed-settings.json`: public editable settings model consumed by the manager
- `data/channel-cache.json`: handle-to-channel-ID resolution cache
- `data/discovery-log.json`: bounded run and discovery history used by aggregate emails
- `config.json`: collection limits, metadata TTLs, discovery terms, timezone, and live URL

No YouTube, GitHub, email, or SMTP credential is stored in the public frontend or generated data.

## Feed Settings workflow

The static GitHub Pages frontend cannot safely write repository files directly. NexaFeed therefore uses an owner-controlled workflow:

1. Open **Feed Settings**.
2. Add, edit, remove, filter, or reset channel rows.
3. Edit keywords, topics, and categories.
4. Select **Review and apply on GitHub**.
5. Review the readable change summary and submit the prefilled issue while signed in as the repository owner.
6. `.github/workflows/apply-feed-settings.yml` validates the compressed payload, updates the CSV/config, commits, deploys, comments on the issue, and closes it.
7. The next clean hourly local refresh pulls the approved settings and rebuilds the feed.

Only an issue opened by `github.repository_owner` with the exact settings title can run the apply job. The server validator limits channel counts, term counts, URL hosts, priorities, payload size, and decompression size.

## Refresh the feed

Refresh locally without publishing:

```bash
/usr/bin/python3 scripts/nexafeed_update.py
```

Refresh, commit generated data, and push:

```bash
/usr/bin/python3 scripts/nexafeed_update.py --publish
```

Useful diagnostics:

```bash
/usr/bin/python3 scripts/nexafeed_update.py --dry-run
/usr/bin/python3 scripts/nexafeed_update.py --dry-run --no-details
```

The Hermes hourly wrapper refuses to pull or publish over a dirty working tree. On a clean production tree it runs `git pull --ff-only origin main` before collection so owner-applied web settings are synchronized safely.

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

Scheduled sends use `EMAIL_HOME_ADDRESS` or `NEXAFEED_EMAIL_RECIPIENTS` from `~/.hermes/.env`, with Resend first and Brevo SMTP fallback. Reports contain aggregate counts and the live link, not a full video dump.

## Verification

```bash
node --check app.js
/usr/bin/python3 -m py_compile scripts/*.py
python3 tests/test_nexafeed_features.py -v
python3 scripts/verify_nexafeed.py
```

`verify_nexafeed.py` checks dynamic channel consistency, feed stats, source ownership, video IDs, blocked-video leakage, rich metadata coverage, bounded comments, settings parity, required frontend markers, and common credential signatures.

## Static-site limitations

### Watch history

History and progress use browser `localStorage`. They persist on the same browser/device but do not automatically synchronize between devices. Use **Feed Settings → Export history JSON / Import history JSON** to move state. Automatic cross-device synchronization requires an authenticated backend such as Supabase or Firebase.

### YouTube interactions

NexaFeed can display cached public metadata and open the original YouTube page. It cannot post comments, replies, likes, or subscriptions as the user. Those actions require authenticated YouTube OAuth/API access and are intentionally redirected to YouTube.

### Availability

Collector filtering reduces dead embeds but cannot guarantee permanent playback. A video can become private, removed, age-restricted, region-restricted, or embedding-disabled after a refresh. Runtime handling removes that video from the current browser session and advances to the next playable item.

### Local scheduler dependency

The hourly collector project lives on `/Volumes/T7 Shield/Hermes-Agent/NexaFeed`. If the external drive is not mounted, the wrapper fails visibly rather than publishing stale data.
