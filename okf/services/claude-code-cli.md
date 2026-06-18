---
type: Service
title: Claude Code CLI (cc command)
description: Command-line interface to Claude AI; primary inference path for greenclaw.
tags: [llm, claude, anthropic, cli, coding]
resource: https://claude.ai/code
---

## Overview

Greenclaw invokes Claude Code CLI (`claude` command) as a **subprocess for each message**. This is the primary inference path:
- Default fallback for any message without a prefix
- Explicitly requested with `cc <query>`
- Escalation path from Gemini tool-calling

Claude Code is a capable reasoning engine with access to external tools and file context.

## Model

**Default**: `claude-sonnet-4-6` (configured in greenclaw.py, constant `MODEL`)

Available alternatives: `claude-opus-4-8`, `claude-sonnet-4-6`, `claude-haiku-4-5`

## Authentication

API key from Anthropic (Claude.ai subscription or API):

```
ANTHROPIC_API_KEY=<key>  # stored in .env
```

## Invocation

Message routes:
```
<query>                 # Default (CC unless no key)
cc <query>              # Explicit CC
```

Routed by `converse()` in greenclaw.py → `ask_cc()` → subprocess call.

## Subprocess call

```bash
echo "<prompt>" | claude --model <MODEL> [--system "<system-prompt>"]
```

**Key details**:
- Per-message invocation (not persistent connection)
- Prompt passed via stdin to avoid shell escaping issues
- System prompt appended for context/instructions
- Stdout captured as the response
- Timeout: currently no explicit timeout (can be added)
- Logging: CC calls logged to `~/greenclaw/cc_calls.jsonl` for usage tracking

## Configuration

In greenclaw.py:

```python
MODEL = "claude-sonnet-4-6"       # Default inference model
CC_BIN = "~/.local/bin/claude"    # Path to claude CLI binary
```

In `.env`:
```
ANTHROPIC_API_KEY=<key>           # Anthropic API auth
```

## Logging

All CC invocations logged to `~/greenclaw/cc_calls.jsonl` with:
- Timestamp
- Prompt text
- Model used
- Response text (first 500 chars)
- Token/cost info

Enables usage tracking and debugging.

## Cost tracking

Responses are not explicitly token-counted by greenclaw, but Anthropic's API bills per token. Monitor usage via:
- Anthropic dashboard (web)
- `~/greenclaw/cc_calls.jsonl` (local log)
- `usage` command in Telegram (CC invocation count)

## Error handling

If `ANTHROPIC_API_KEY` is unset, CC invocations fail with a "no key" error.
If the subprocess fails (network, auth, timeout), the error is returned to the user.

## Compared to Gemini

| Aspect | CC | Gemini |
|--------|----|----|
| Cost | Paid (API) | Free (limited) |
| Reasoning | Better | Good |
| Tools | Yes (claude CLI) | Yes (REST API tools) |
| Latency | 2-30s | 1-10s |
| Primary? | Yes | Fallback/secondary |

## See also

- [[gemini]] for the secondary inference path
- [[converse-routes]] for routing logic
- [[Claude API]] skill for reference docs
