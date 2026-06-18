---
type: Index
title: Configuration Index
description: Environment variables, storage paths, constants, and runtime parameters.
---

Greenclaw's behavior is controlled by configuration in three areas: environment variables, file paths, and hardcoded constants.

## Configuration files

- [environment](environment.md) — API keys, service authentication, port bindings (`.env`)
- [storage](storage.md) — Persistent state locations, logs, history, memory vault paths
- [constants](constants.md) — Runtime limits, thresholds, model selection, hardcoded parameters

## Quick reference: what to configure

| Task | What | Where | How |
|------|------|-------|-----|
| Use Telegram | Set bot token and chat ID | `.env` | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |
| Use Claude Code | Set API key | `.env` | `ANTHROPIC_API_KEY` |
| Use Gemini | Set API key | `.env` | `GEMINI_API_KEY` |
| Access dashboard | Set port and host | `.env` | `DASHBOARD_PORT`, `DASHBOARD_HOST` |
| View GitHub issues | Set token (optional) | `.env` | `GITHUB_TOKEN` |
| Tune output limits | Edit constants | `greenclaw.py` | `SHELL_MAX_OUTPUT`, `HISTORY_MAX_TURNS`, etc. |

## Per-environment customization

- **Development**: Create `.env` with test API keys; use `python greenclaw.py` to run locally
- **Production**: Create `.env` on the server; use `systemctl --user start greenclaw-bot.service`
- **Secrets management**: `.env` is git-ignored; never commit it

## File layout

```
~/Projects/greenclaw/
├── .env                       # Configuration (secrets, git-ignored)
├── .env.example               # Template
├── greenclaw.py               # Core (contains constants)
├── tasks/
│   ├── telegram.py
│   └── dashboard.py
├── skills/
│   ├── vault.py
│   ├── sysinfo.py
│   ├── weather.py
│   ├── check_updates.py
│   └── *.md                   # Recipe skills
├── schedules/
│   ├── morning-digest.md
│   └── memory-maintenance.md
└── okf/                       # This knowledge bundle
    ├── config/
    ├── tasks/
    ├── services/
    ├── skills/
    └── index.md
```

## Environment variables (summary)

**Required**:
- `TELEGRAM_BOT_TOKEN` — Bot API token
- `TELEGRAM_CHAT_ID` — Authorized chat ID

**Optional but recommended**:
- `ANTHROPIC_API_KEY` — Claude Code API (primary inference)
- `GEMINI_API_KEY` — Gemini API (free fallback)

**Optional for dashboard**:
- `DASHBOARD_PORT` — HTTP port (default 7070)
- `DASHBOARD_HOST` — Bind address (default 0.0.0.0)
- `GITHUB_TOKEN` — GitHub API key (raises rate limit)

## See also

- [[tasks]] — Services that consume this configuration
- [[services]] — External APIs and their auth requirements
