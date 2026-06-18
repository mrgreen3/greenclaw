---
type: Config
title: Storage and file paths
description: Locations for persistent state, logs, history, and external data.
tags: [storage, paths, state, persistence]
resource: greenclaw.py (paths defined at top)
---

## Overview

Greenclaw persists various data to disk: conversation history, invocation logs, memory, schedule state, and notes. All paths are configurable via environment or hardcoded constants in greenclaw.py.

## Core directories

| Path | Purpose | Owner |
|------|---------|-------|
| `~/Projects/greenclaw/` | Project root | mrgreen (checked into git) |
| `~/.local/share/greenclaw/` | Runtime state (not in git) | greenclaw process |
| `~/.claude/projects/-home-mrgreen/memory/` | Persistent memory (Claude Code project) | greenclaw, Claude Code |
| `~/greenbrain/` | Personal knowledge vault (GitHub sync'd) | greenclaw, git |

## Logs and history

| File | Purpose | Format |
|------|---------|--------|
| `~/greenclaw/cc_calls.jsonl` | CC invocation log | JSON Lines (one call per line) |
| `~/.local/share/greenclaw/history.json` | Per-chat message history | JSON (rolling window) |
| `~/.local/share/greenclaw/schedule.json` | Schedule state (run times) | JSON |
| `~/.local/share/greenclaw/memory_compaction.json` | Memory compaction tracking | JSON |
| `~/.local/share/greenclaw/heartbeat.jsonl` | Periodic heartbeat/status | JSON Lines |
| `~/notes.md` | Quick notes (short-lived) | Markdown |

## Vault and memory

| Path | Purpose | Type |
|------|---------|------|
| `~/greenbrain/` | Personal knowledge vault (Obsidian-compatible) | Git repo |
| `~/greenbrain/greenclaw/` | Greenclaw-specific notes | Markdown files |
| `~/.claude/projects/-home-mrgreen/memory/` | Claude Code memory (long-term facts) | Markdown files with YAML |

Memory is auto-compacted when size exceeds `MEMORY_SIZE_THRESHOLD` (50 KB).

## Skills and schedules

| Path | Purpose |
|------|---------|
| `~/Projects/greenclaw/skills/` | Skill recipes (markdown + Python) |
| `~/Projects/greenclaw/skills.allow` | Allowlist for skill execution |
| `~/Projects/greenclaw/schedules/` | Scheduled job definitions (markdown) |

## Environment variables for customization

| Variable | Default | Purpose |
|----------|---------|---------|
| `CC_LOG_FILE` | `~/greenclaw/cc_calls.jsonl` | CC invocation log location |
| (others) | paths in code | (mostly hardcoded) |

## Permissions

- `~/.env` — `0600` (secrets only readable by owner)
- `~/greenclaw/` — created on first run by greenclaw process
- `~/.local/share/greenclaw/` — created on first run
- `~/greenbrain/` — must exist with git remote configured (external repo)

## Cleanup

No automatic cleanup of old logs. Manual rotation recommended:
```bash
cd ~/greenclaw
gzip cc_calls.jsonl
rm -f cc_calls.jsonl.*.gz  # keep last N
```

History is TTL'd: entries older than `HISTORY_TTL_DAYS` (7 days) are discarded on load.
