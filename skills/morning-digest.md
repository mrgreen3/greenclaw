---
name: morning-digest
description: Morning system health check. Runs at 5am daily.
exposes: cc
trigger: /digest
locked: false
source: owner
---

Produce a morning system health check for Kev. Use UK date format (e.g. 14 June 2026). Keep it terse:

**System**
Run these and flag anything that looks off:
- `df -h /`
- `free -h`
- `uptime`
- `systemctl --user is-active greenclaw.service`
- `checkupdates 2>/dev/null | wc -l` (pending Arch updates — flag if 10 or more)
- `sensors 2>/dev/null | grep -i 'temp\|core' | head -5` (skip if not installed)

End with a single summary line: either "All good 🟢" or "Needs attention 🔴".
