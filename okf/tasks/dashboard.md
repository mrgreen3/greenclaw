---
type: Task
title: Web dashboard (HTTP status page)
description: Read-only HTTP server exposing system stats, CC invocations, recent prompts, vault info, and open issues.
tags: [http, dashboard, monitoring, status-page]
resource: tasks/dashboard.py
---

## Overview

Serves a single-page HTML dashboard at `http://localhost:PORT` (default 7070). Displays real-time snapshots of:

- System vitals (uptime, load, RAM, disk)
- Memory vault stats (greenbrain directory)
- Claude Code invocations and recent prompts
- Open GitHub issues (for the repo)
- Scheduled jobs and their last run times
- Recent notes (from `~/notes.md`)

All content is read-only; the dashboard has no mutation endpoints.

## Configuration

All config comes from `.env`:

| Variable | Purpose | Default |
|----------|---------|---------|
| `DASHBOARD_PORT` | TCP port to listen on | `7070` |
| `DASHBOARD_HOST` | Bind address (0.0.0.0 = LAN-accessible) | `0.0.0.0` |
| `GITHUB_TOKEN` | Optional; raises GitHub API rate limit | unset (60 req/hr) |
| `GITHUB_REPO` | GitHub repo to display issues for | `mrgreen3/greenclaw` |

## Interface

Implements the standard task contract:

```python
def start(on_message):
    ...  # on_message is unused; task is standalone HTTP server
```

## Data sources

| Panel | Source | Location |
|-------|--------|----------|
| System vitals | shell commands | `df`, `free`, `uptime` |
| Memory vault | filesystem walk | `~/.claude/projects/-home-mrgreen/memory/` |
| CC calls | JSONL log | `~/greenclaw/cc_calls.jsonl` |
| Issues | GitHub REST API | `GET /repos/{owner}/{repo}/issues?state=open` |
| Schedules | JSON state file | `~/.local/share/greenclaw/schedule.json` |
| Notes | markdown file | `~/notes.md` |

## Ports

- **HTTP**: `DASHBOARD_HOST:DASHBOARD_PORT` (default `0.0.0.0:7070`)

## Static assets

Served from `static/` directory if present.
