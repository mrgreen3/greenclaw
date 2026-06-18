---
type: Config
title: Environment variables (.env)
description: Configuration for external services, API keys, and runtime behavior.
tags: [configuration, secrets, environment]
resource: .env, .env.example
---

## Overview

All configuration is in `.env` (git-ignored). Kept separate from code to protect secrets and allow per-machine customization.

A `.env.example` template is checked in; copy and fill before first run.

## Required variables

### Telegram

| Variable | Purpose | Example |
|----------|---------|---------|
| `TELEGRAM_BOT_TOKEN` | Bot API token from @BotFather | `123456:ABCDEFghijklmnop` |
| `TELEGRAM_CHAT_ID` | Authorized chat ID (numeric) | `12345678` |

If `TELEGRAM_BOT_TOKEN` is unset, the Telegram task does not start.

### Anthropic

| Variable | Purpose |
|----------|---------|
| `ANTHROPIC_API_KEY` | Claude API key from Anthropic dashboard |

Optional but needed for CC (primary inference). If unset, CC invocations fail.

## Optional variables

### Dashboard

| Variable | Default | Purpose |
|----------|---------|---------|
| `DASHBOARD_PORT` | `7070` | HTTP port to listen on |
| `DASHBOARD_HOST` | `0.0.0.0` | Bind address (LAN-accessible if 0.0.0.0) |
| `GITHUB_TOKEN` | unset | GitHub API key; raises rate limit to 5000/hr (optional) |
| `GITHUB_REPO` | `mrgreen3/greenclaw` | Repo to display issues for |

### Gemini

| Variable | Default | Purpose |
|----------|---------|---------|
| `GEMINI_API_KEY` | unset | Google AI Studio API key (free tier) |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Gemini model name |

If `GEMINI_API_KEY` is unset, Gemini is disabled.

## File location

`.env` is in the project root:
```
~/Projects/greenclaw/.env
```

Must be mode `0600` (readable only by owner) to protect secrets.

## Template

See `.env.example` for the template with all available variables and their defaults.
