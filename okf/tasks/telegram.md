---
type: Task
title: Telegram bot (long-polling connector)
description: Telegram Bot API long-polling connector; receives messages and dispatches to router.
tags: [connector, telegram, communication, bot]
resource: tasks/telegram.py
---

## Overview

Receives messages from a single authorized Telegram chat via long-polling, hands them to the core message router (greenclaw.py), and sends responses back through the Telegram Bot API.

## How it works

- Implements the standard task contract: `start(on_message)` runs forever in a dedicated thread
- Long-polls the Telegram Bot API (`getUpdates`) with offset-based deduplication
- Validates incoming chat_id against `TELEGRAM_CHAT_ID` for security
- Splits outgoing replies >4000 chars into multiple messages (Telegram limit)
- Gracefully handles network errors; logs to stdout

## Configuration

All config comes from `.env`:

| Variable | Purpose | Example |
|----------|---------|---------|
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather | `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11` |
| `TELEGRAM_CHAT_ID` | Single authorized chat (numeric ID) | `12345678` |

If `TELEGRAM_BOT_TOKEN` is unset, the task does not start (logs a message and returns).
If `TELEGRAM_CHAT_ID` is unset, the task runs in **discovery mode**: logs incoming chat IDs and refuses to execute anything until the env var is set.

## Interface

### Callback

```python
on_message(text: str, reply: Callable, chat_id: str) -> None
```

Called once per incoming Telegram message. The caller (greenclaw.py) processes `text`, computes a response, and calls `reply(response_text)` to send it back.

## Entry points

- **Telegram Bot API**: `https://api.telegram.org/bot<TOKEN>/getUpdates` (incoming messages)
- **Telegram Bot API**: `https://api.telegram.org/bot<TOKEN>/sendMessage` (outgoing replies)
