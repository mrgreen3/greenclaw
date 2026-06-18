---
type: Skill
title: Sysinfo — server stats snapshot
description: Reports disk, RAM, CPU load, and uptime.
tags: [monitoring, system-stats, diagnostics]
resource: skills/sysinfo.py
trigger: /sysinfo
---

## Overview

One-shot query that returns current system vitals: uptime, CPU load, RAM usage, and disk utilization across all major mount points. No arguments required.

## Invocation

```
/sysinfo
```

## Output format

```
⬆ <uptime>  |  load: <1m>, <5m>, <15m>
RAM: <used> / <total> (<available> free)
Disk:
  / <size> <used> <available> <percent>
  /home <size> <used> <available> <percent>
  /mnt/sata <size> <used> <available> <percent>
```

## Implementation details

- **Uptime**: `uptime -p` (human-readable)
- **Load**: parsed from `uptime` output
- **RAM**: `free -h --si` (totals, used, available in SI units)
- **Disk**: `df -h` filtered to real mount points (skips tmpfs, devtmpfs, overlay)
  - Includes `/` (root), `/home`, `/mnt/sata` if they exist
  - Formats output for readability

## Error handling

If any command fails, returns `[error: <exception>]` for that section. Timeout: 10 seconds per command.
