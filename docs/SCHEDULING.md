# Scheduling YourTube

YourTube can be refreshed by Hermes Agent, normal cron, GitHub Actions, Codex, Claude Code, or a plain terminal. Use only one active publisher at a time.

## Recommended publisher command

```bash
python3 scripts/nexafeed_automation.py --pull-first --require-clean --publish
```

`--pull-first` keeps owner-applied Feed Settings in sync before collecting. `--require-clean` refuses to publish over local edits.

If your default branch is not `main`, set `NEXAFEED_BRANCH` in `.env.local`, Hermes env, cron env, or GitHub Actions Variables before publishing.

## Normal cron

Hourly refresh:

```cron
53 * * * * cd /path/to/nexafeed && /usr/bin/python3 scripts/nexafeed_automation.py --pull-first --require-clean --publish >> "$HOME/.yourtube/update.log" 2>&1
```

With a private env file:

```cron
53 * * * * cd /path/to/nexafeed && /usr/bin/python3 scripts/nexafeed_automation.py --env-file "$HOME/.config/yourtube.env" --pull-first --require-clean --publish >> "$HOME/.yourtube/update.log" 2>&1
```

Morning email:

```cron
0 10 * * * cd /path/to/nexafeed && /usr/bin/python3 scripts/nexafeed_digest_email.py --period morning --env-file "$HOME/.config/yourtube.env" >> "$HOME/.yourtube/email.log" 2>&1
```

Midnight email:

```cron
0 0 * * * cd /path/to/nexafeed && /usr/bin/python3 scripts/nexafeed_digest_email.py --period midnight --env-file "$HOME/.config/yourtube.env" >> "$HOME/.yourtube/email.log" 2>&1
```

## Hermes Agent

Ask Hermes to create these scheduled jobs from inside the repo:

```text
Create a Hermes cron job named "YourTube hourly refresh" that runs every hour at minute 53 from this workdir and executes:
python3 scripts/nexafeed_automation.py --pull-first --require-clean --publish

Create a Hermes cron job named "YourTube morning email" that runs daily at 10:00 Asia/Dhaka and executes:
python3 scripts/nexafeed_digest_email.py --period morning

Create a Hermes cron job named "YourTube midnight email" that runs daily at 00:00 Asia/Dhaka and executes:
python3 scripts/nexafeed_digest_email.py --period midnight
```

After creating jobs, verify the gateway:

```bash
hermes cron status
```

The gateway must be running for scheduled jobs to fire automatically.

## GitHub Actions

Run **Update YourTube feed** manually from the Actions tab.

If GitHub Actions should own the schedule, add:

```yaml
on:
  schedule:
    - cron: "53 * * * *"
  workflow_dispatch:
```

Then pause Hermes/local cron so two publishers do not push generated data at the same time.

## Codex or Claude Code

Prompt:

```text
From this repo, run the YourTube doctor, perform a dry-run refresh, run verification, and if clean run:
python3 scripts/nexafeed_automation.py --pull-first --require-clean --publish
Do not print or commit secrets.
```
