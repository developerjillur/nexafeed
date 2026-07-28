# Security policy

## Secrets

Do not commit API keys, OAuth tokens, SMTP passwords, GitHub tokens, private env files, local private paths, or generated reports.

Allowed places for secrets:

- `.env.local` or another private env file outside the repo
- `$HERMES_HOME/.env` or `~/.hermes/.env` for Hermes Agent
- GitHub Actions Secrets
- deployment platform secret storage

The public frontend must stay secret-free.

## Static app limits

YourTube is a static GitHub Pages app. It cannot safely write directly to GitHub from browser JavaScript and it cannot perform authenticated YouTube account actions without OAuth and secure backend storage.

Feed Settings use an owner-reviewed GitHub Issue workflow. The workflow validates the payload server-side before committing settings.

## Report a vulnerability

Open a GitHub issue with a minimal reproduction. Do not include real secrets in the issue body. If a credential was exposed, rotate it first.
