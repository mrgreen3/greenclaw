---
type: BundleIndex
okf_version: "0.1"
title: Greenclaw OKF Knowledge Bundle
description: Complete knowledge graph of the Greenclaw Telegram→AI bridge architecture, configuration, and operations.
---

# Greenclaw Knowledge Bundle

**Greenclaw** is a lean Telegram→AI bridge running on an Arch Linux box. It routes messages between Telegram and two AI inference engines (Claude Code CLI and Google Gemini), with persistent memory, scheduled jobs, and a web dashboard.

This OKF (Open Knowledge Format) bundle documents the complete system: what it does, how it's architected, what services it uses, what to configure, and how to operate it.

## Quick navigation

### For operators / deployers

1. **Getting started**: Read [config/environment](config/environment.md) to set up `.env`
2. **Storage**: See [config/storage](config/storage.md) for where state lives
3. **Tasks**: Check [tasks/](tasks/index.md) to understand always-on connectors
4. **Services**: See [services/](services/index.md) for external integrations

### For developers / maintainers

1. **Architecture**: Start with [Main Overview](#architecture) below
2. **Tasks**: Read [tasks/telegram.md](tasks/telegram.md) and [tasks/dashboard.md](tasks/dashboard.md)
3. **Services**: See [services/](services/index.md) for how external APIs are called
4. **Skills**: Browse [skills/](skills/index.md) for what commands are available
5. **Config**: Check [config/constants.md](config/constants.md) for tunables

### For users

- **Telegram interface**: Message @greenclaw_bot or start a Telegram chat
- **Commands**: Type `/cheat` in Telegram for available commands and syntax
- **Dashboard**: Visit `http://<server>:7070/` to see system status
- **Skills**: Available as `/<trigger>` commands (see [skills/](skills/index.md))

## Architecture

```
┌─────────────────────┐
│  Telegram          │
│  (user messages)   │
└──────────┬──────────┘
           │
      ┌────▼─────────────────────────┐
      │  greenclaw.py                │
      │  Message router + inference  │
      │                              │
      │  ┌────────────────────────┐  │
      │  │ converse()             │  │
      │  │ - Parse message        │  │
      │  │ - Route by prefix      │  │
      │  │ - Invoke skills        │  │
      │  │ - Call inference       │  │
      │  └────────┬──────┬────┬───┘  │
      └───────────┼──────┼────┼──────┘
                  │      │    │
        ┌─────────▼──┐   │    │
        │  Claude    │   │    │
        │  Code CLI  │   │    │
        │  (cc)      │   │    │
        └────────────┘   │    │
                    ┌────▼──┐ │
                    │Gemini │ │
                    │(gg)   │ │
                    └───────┘ │
                    ┌─────────▼┐
                    │  Skills  │
                    │  /xyz    │
                    └──────────┘
```

## Core components

- **greenclaw.py** — Single-file router; loads tasks, skills, schedules at boot
- **tasks/** — Always-on connectors (Telegram bot, web dashboard)
- **skills/** — User-triggered recipes (system info, weather, notes, etc.)
- **schedules/** — Timed jobs (morning digest, memory maintenance, etc.)
- **.env** — Configuration (API keys, ports, secrets)

## Directory index

- **[config/](config/index.md)** — Configuration, environment variables, storage paths
- **[tasks/](tasks/index.md)** — Always-on connectors (Telegram, dashboard)
- **[services/](services/index.md)** — External APIs (Claude Code, Gemini, Telegram)
- **[skills/](skills/index.md)** — User-triggered recipes
- **[log.md](log.md)** — Change history

## Key facts

| Aspect | Detail |
|--------|--------|
| **Language** | Python 3 |
| **Single file** | `greenclaw.py` (~400 lines) |
| **Primary interface** | Telegram Bot API (long-polling) |
| **Inference paths** | Claude Code CLI (primary), Gemini (fallback) |
| **Storage** | JSON/JSONL logs, markdown notes, memory vault |
| **Deployment** | systemd user service (`greenclaw-bot.service`) |
| **Config** | `.env` (secrets, API keys, ports) |
| **Version** | 0.4.1 |

## How to...

- **Deploy**: Copy `.env.example` to `.env`, fill in secrets, run `systemctl --user start greenclaw-bot.service`
- **Add a skill**: Create a `.md` or `.py` file in `skills/` with `TRIGGER` and `DESCRIPTION` metadata
- **Add a task**: Create a `.py` file in `tasks/` with `start(on_message)` function
- **View logs**: `journalctl --user -u greenclaw-bot.service -f`
- **Restart**: `systemctl --user restart greenclaw-bot.service`

## See also

- GitHub: https://github.com/mrgreen3/greenclaw
- CLAUDE.md in repo root for project-specific developer instructions
