---
type: Config
title: Constants and limits
description: Hardcoded runtime parameters, buffer limits, and thresholds.
tags: [configuration, limits, performance]
resource: greenclaw.py (lines 30–85)
---

## Overview

Runtime parameters and limits that control greenclaw's behavior. Most are defined as constants at the top of `greenclaw.py`; some are environment-dependent.

## Message and output limits

| Constant | Value | Purpose |
|----------|-------|---------|
| `SHELL_MAX_OUTPUT` | 6000 chars | Max characters returned from shell commands (prevents context bloat) |
| Telegram split | 4000 chars | Telegram's max message length; longer replies split automatically |

## History and context

| Constant | Value | Purpose |
|----------|-------|---------|
| `HISTORY_MAX_TURNS` | 10 | Conversation history: keep last 10 user+assistant pairs per chat |
| `HISTORY_TTL_DAYS` | 7 | Discard history older than this on load |

## Memory management

| Constant | Value | Purpose |
|----------|-------|---------|
| `MEMORY_SIZE_THRESHOLD` | 50,000 bytes | Trigger memory compaction when exceeds this |
| `MEMORY_COMPACTION_COOLDOWN` | 86,400 sec (24h) | Minimum interval between auto-compactions |

## Gemini limits

| Constant | Value | Purpose |
|----------|-------|---------|
| `GEMINI_MAX_STEPS` | 8 | Max tool-call loop iterations (prevent runaway agentic calls) |

## Model selection

| Constant | Value | Purpose |
|----------|-------|---------|
| `MODEL` | `claude-sonnet-4-6` | Default Claude model for CC invocations |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Gemini model (overridable via env) |

## File paths (core constants)

| Constant | Default | Purpose |
|----------|---------|---------|
| `SKILLS_DIR` | `./skills/` | Where to load skill recipes |
| `TASKS_DIR` | `./tasks/` | Where to load task connectors |
| `SCHEDULES_DIR` | `./schedules/` | Where to load scheduled jobs |
| `CC_LOG_FILE` | `~/greenclaw/cc_calls.jsonl` | CC invocation log |
| `HISTORY_FILE` | `~/.local/share/greenclaw/history.json` | Conversation history |
| `NOTES_FILE` | `~/notes.md` | Quick notes file |

## Version

| Constant | Value | Purpose |
|----------|-------|---------|
| `__version__` | (from greenclaw.py) | Current version string |

See `greenclaw.py` line 30 for the exact version.

## Tuning

Most limits can be increased if needed:
- Raise `SHELL_MAX_OUTPUT` for verbose command output
- Raise `HISTORY_MAX_TURNS` for longer conversation context
- Raise `MEMORY_SIZE_THRESHOLD` to trigger compaction less often
- Lower `GEMINI_MAX_STEPS` to exit agentic loops faster

Changes require editing `greenclaw.py` and restarting the service.
