---
type: Service
title: Google Gemini 2.5 Flash
description: Free-tier generative model from Google AI Studio; second inference path after Claude Code CLI.
tags: [llm, generative-ai, google-ai, free-tier]
resource: https://ai.google.dev/
---

## Overview

Greenclaw routes `gg <query>` prompts to Gemini 2.5 Flash via Google AI Studio REST API. Used as a **free secondary inference path** (CC is the primary, fallback to local/Gemini if CC is down).

## Model

**Name**: `gemini-2.5-flash` (configurable via `GEMINI_MODEL` env var)

**Capabilities**:
- Text generation
- Tool calling (for actions like `run_shell`, `notes`, `delegate_to_cc`)
- Max steps: 8 (limit on tool invocation loops)

**Free tier**: 15 reqs/min, 1M tokens/month (per the free API tier as of June 2026)

## Authentication

API key from Google AI Studio (https://ai.google.dev/):

```
GEMINI_API_KEY=<key>  # stored in .env
```

## Invocation

Message route:
```
gg <query>              # Force Gemini
```

Routed by `converse()` in greenclaw.py → `converse_gemini()` → REST call.

## Endpoint

```
POST https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=<API_KEY>
```

Request body (simplified):
```json
{
  "contents": [
    {"parts": [{"text": "<user-prompt>"}]}
  ],
  "tools": [
    {"functionDeclarations": [
      {"name": "run_shell", "description": "...", "parameters": {...}},
      {"name": "notes", ...},
      ...
    ]}
  ],
  "system_instruction": "<system-prompt>"
}
```

## Tools Gemini can invoke

Gemini has a set of tools for autonomous action (tool calling):

- `run_shell` — execute shell commands (capped at `SHELL_MAX_OUTPUT` chars)
- `notes` — read/write persistent notes
- `memory` — interact with memory system
- `delegate_to_cc` — escalate to Claude Code CLI if needed

## Configuration

| Variable | Purpose | Default |
|----------|---------|---------|
| `GEMINI_API_KEY` | API authentication key | unset (service disabled) |
| `GEMINI_MODEL` | Model name | `gemini-2.5-flash` |

In greenclaw.py:
```python
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_MAX_STEPS = 8  # limit on tool invocation loops
```

## Error handling

If `GEMINI_API_KEY` is unset, the service gracefully skips (logs a note, doesn't error).
If the API returns an error, the error message is logged and the next fallback is tried.

## Rate limiting

Free tier: **15 requests per minute**. If you hit the limit, requests will fail with HTTP 429.

## See also

- [[claude-code-cli]] for the primary inference path
- [[telegram]] for the message input channel
- [[converse-routes]] for routing logic
