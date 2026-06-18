---
type: Index
title: Tasks Index
description: Always-on greenclaw connectors (communication channels, servers).
---

Tasks are always-on background connectors that provide input/output channels and services. Each task implements a simple protocol: `start(on_message)` runs forever in a dedicated thread and calls `on_message(text, reply, chat_id)` per incoming message.

## Available tasks

- [telegram](telegram.md) — Telegram Bot API long-polling connector (primary input/output)
- [dashboard](dashboard.md) — Read-only HTTP status page (system vitals, recent prompts, issues)

## How tasks work

1. Greenclaw loads all `tasks/*.py` at boot
2. Each task registers a `start(on_message)` function and runs it in a background thread
3. When an incoming message arrives (Telegram text, dashboard request, etc.), the task calls `on_message(text, reply, chat_id)`
4. Greenclaw's core router processes the message and calls `reply(response_text)`
5. The task sends the response back on the same channel

## Architecture

```
┌─────────────────────────────────────┐
│  External service (Telegram, etc.)  │
└──────────────┬──────────────────────┘
               │
        ┌──────▼──────┐
        │   Task      │
        │  telegram   │ (runs in background thread)
        └──────┬──────┘
               │ on_message(text, reply)
        ┌──────▼──────────────────────┐
        │   Greenclaw core router     │
        │   converse()                │
        └──────┬──────────────────────┘
               │ reply(response)
        ┌──────▼──────┐
        │   Task      │
        │  telegram   │ (sends back)
        └──────┬──────┘
               │
        ┌──────▼──────────────────────┐
        │ External service (response) │
        └─────────────────────────────┘
```

## Configuration

Each task reads its configuration from `.env`:

| Task | Config variables |
|------|------------------|
| telegram | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |
| dashboard | `DASHBOARD_PORT`, `DASHBOARD_HOST`, `GITHUB_TOKEN`, `GITHUB_REPO` |

## See also

- [[services]] — External service integrations (Telegram API, etc.)
- [[skills]] — User-triggered recipes
- [[Main index]] — Overview
