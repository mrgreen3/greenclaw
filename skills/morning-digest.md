---
name: morning-digest
description: Morning system health check. Runs at 5am daily.
exposes: cc
trigger: /digest
locked: false
source: owner
---

Generate a brief morning digest for Kev (UK date format, e.g. 14 June 2026). Only include actionable items, skip noise:

**Scheduled jobs**
List any jobs from ~/.local/share/greenclaw/schedule.json that are due today or overdue.

**GitHub issues** (mrgreen3/greenclaw)
Fetch open issues. Count only; if >0, list them:
```
<N> open issues:
  - <title1>
  - <title2>
```

**Critical system issues only**
Check `systemctl --user is-active greenclaw.service` — flag if not "active".
Flag if disk / is >90% used (`df -h /`).

Skip routine health (uptime, load, RAM usage, update count) — those are on-demand via `/sysinfo`.

**Format:** Terse, one paragraph per section. No summary line unless critical issue found.
