---
type: Index
title: Skills Index
description: Greenclaw skill recipes and utilities.
---

Greenclaw skills are user-triggered recipes that perform specific actions. This directory documents Python-implemented skills; markdown-based recipe skills are also available but not individually documented.

## Python skills (always available)

- [vault](vault.md) — Read, search, or write notes in the personal knowledge vault (`greenbrain/`)
- [sysinfo](sysinfo.md) — Report server vitals (disk, RAM, CPU, uptime)
- [weather](weather.md) — Current weather for a location (default: London)
- [check_updates](check_updates.md) — Check for pending Arch Linux package updates

## Markdown recipe skills

Available in `~/Projects/greenclaw/skills/`:

- `blog-post.md` — Template for drafting blog posts
- `datetime.md` — Date/time formatting reference
- `github.md` — GitHub operations (issues, PRs, etc.)
- `llm-bench.md` — LLM benchmarking utilities
- `mail.md` — Email utilities
- `morning-digest.md` — Morning summary generation
- `note.md`, `notes.md` — Quick note taking
- `search.md` — Web/codebase search
- `system-health.md` — System health diagnostics

## Built-in commands

These are not skills but are available as commands:

- `/watch` — Show scheduled jobs and their last run times
- `/usage` — CC invocation count today
- `/calls` — Same as `/usage`
- `/version` — Show greenclaw version
- `/cheat` — Built-in cheat sheet (prefixes, commands, skills)

## How to trigger a skill

```
/<trigger>              # Run skill with no arguments
/<trigger> <args>       # Run skill with arguments
```

Example:
```
/weather London
/sysinfo
/vault my-topic
```

## See also

- [[tasks]] — Always-on connectors (Telegram, dashboard)
- [[services]] — External service integrations
