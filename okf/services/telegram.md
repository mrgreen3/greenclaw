---
type: Service
title: Telegram Bot API
description: Telegram messaging platform; primary input/output channel for greenclaw.
tags: [messaging, api, communication, bot]
resource: https://core.telegram.org/bots/api
---

## Overview

Greenclaw communicates with the user via Telegram. The `telegram.py` task uses the official Telegram Bot API to receive messages (long-polling) and send responses.

## Authentication

Bots authenticate with a **Bot Token** obtained from @BotFather:

```
TELEGRAM_BOT_TOKEN=<numeric>:<alphanumeric>
```

## Message flow

### Incoming

1. User sends message to Telegram chat
2. Greenclaw long-polls `getUpdates` endpoint
3. New updates arrive with `message.text` and `message.chat.id`
4. Greenclaw filters by `TELEGRAM_CHAT_ID` (security)
5. Text routed to `converse()` in greenclaw.py
6. Response computed and sent back via `sendMessage`

### Outgoing

Responses are sent to the authorized chat using `sendMessage`:

- Max 4000 chars per message (Telegram limit)
- Longer responses split into multiple messages
- Timeout: 30 seconds per send

## Endpoints

- **Long-polling**: `GET https://api.telegram.org/bot<TOKEN>/getUpdates?offset=<N>`
- **Send message**: `POST https://api.telegram.org/bot<TOKEN>/sendMessage`
  - Body: `{"chat_id": <ID>, "text": <message>}`

## Configuration

All in `.env`:

| Variable | Purpose |
|----------|---------|
| `TELEGRAM_BOT_TOKEN` | Bot authentication token |
| `TELEGRAM_CHAT_ID` | Numeric chat ID to authorize |

If `TELEGRAM_BOT_TOKEN` is unset, the task skips initialization.
If `TELEGRAM_CHAT_ID` is unset, the task runs in read-only discovery mode (logs incoming chat IDs).

## Security model

Single-user, single-chat. No multi-user support. Chat ID validation is the only access control.

## See also

- [[telegram]] task that implements the polling/sending logic
- [[Gemini]] service for alternative/enrichment inference
