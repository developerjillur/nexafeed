# Changelog

## v1.0.0 - YourTube public release

Public release name:

- **YourTube - A personal YouTube Package**
- Tagline: **Watch only those valuable for you**

### Added

- Public-release README with live demo, screenshots, features, use cases, scheduling, GitHub Actions, Hermes Agent, Claude Code, Codex, and AI setup prompt.
- `docs/AI_SETUP_PROMPT.md` so users can paste one prompt into any coding agent and get their own fork deployed.
- `docs/SCHEDULING.md` for Hermes cron, normal cron, GitHub Actions, Claude Code, and Codex setup.
- `docs/screenshots/` with home, Shorts, and Feed Settings screenshots.
- `LICENSE`, `SECURITY.md`, and `CONTRIBUTING.md` for public GitHub release readiness.
- SEO/social metadata with Open Graph and Twitter cards.
- `repositoryUrl` config so forked copies can open Feed Settings issues in the user's own repository.
- URL deep links for `?view=shorts` and `?view=settings`.

### Preserved

- Current default feed setup: 33 monitored channels, long-video feed, Shorts feed, local watch history, local liked videos, NotebookLM helper, floating player, watched filtering, and automation wrappers.
- Provider-agnostic env setup through `.env`, GitHub Secrets, Hermes Agent, Claude Code, Codex, or regular cron.
- Secret-free static GitHub Pages frontend.

### Verified

- Feature regression tests.
- Python compile checks.
- JavaScript syntax check.
- Structural/data verifier.
- Public leak scan.
- Local browser smoke for YourTube branding, Shorts deep link, and Feed Settings deep link.
