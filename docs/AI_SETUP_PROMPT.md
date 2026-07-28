# AI setup prompt for YourTube

Use this prompt with Hermes Agent, Claude Code, Codex, Cursor, Aider, or any coding agent that can read a GitHub repo and run shell commands.

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
   - tagline: Watch only those valuable for you
   - siteUrl: https://MY_GITHUB_USERNAME.github.io/MY_REPO/
   - repositoryUrl: https://github.com/MY_GITHUB_USERNAME/MY_REPO
3. Keep the default 33-channel AI/web-development feed unless I provide my own channels.
4. If I provide channels, update data/channels.csv and discovery terms in config.json.
5. Run:
   python3 -m pip install --upgrade yt-dlp
   python3 scripts/nexafeed_doctor.py
   python3 scripts/nexafeed_automation.py --dry-run --no-details --no-secondary --workers 6
6. Run verification:
   python3 tests/test_nexafeed_features.py -v
   python3 -m py_compile scripts/*.py
   node --check app.js
   python3 scripts/verify_nexafeed.py
   git diff --check
7. Commit and push.
8. Enable GitHub Pages and run the Update YourTube feed workflow manually.
9. Wait for deploy success and fetch the live URL.
10. Return: repo URL, live URL, what changed, how to refresh, how to edit Feed Settings, and any warnings.
```

## Short prompt

```text
Set up this YourTube repo for my GitHub account: https://github.com/developerjillur/nexafeed. Make it public, configure GitHub Pages, update config.json with my siteUrl and repositoryUrl, keep secrets out of git, run the doctor/dry-run/verifier, push, run the Update YourTube feed workflow, wait for deploy, and give me the live URL.
```
