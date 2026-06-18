---
type: Skill
title: Check Updates — Arch Linux package updates
description: Check for pending Arch Linux package updates (read-only).
tags: [arch-linux, package-management, diagnostics]
resource: skills/check_updates.py
trigger: /updates
---

## Overview

One-shot query that reports available Arch Linux package updates. Read-only; no installation performed. Uses `checkupdates` if available (faster, syncs remote db), falls back to `pacman -Qu` (local db only, slower).

## Invocation

```
/updates
```

## Output format

If updates are available:
```
<N> update<s> available:
  <package1> <old-version> -> <new-version>
  <package2> <old-version> -> <new-version>
  ...
```

If system is up to date:
```
System is up to date.
```

## Exit codes

- **Exit 0**: Updates available (stdout printed)
- **Exit 2**: No updates available
- **Non-0 (other)**: Error; returns exception message

## Fallback behavior

| Scenario | Tool | Behavior |
|----------|------|----------|
| `checkupdates` available | pacman-contrib | Fast; syncs remote db first |
| `checkupdates` not found | pacman | Slower; uses local db only; note added to output |
| pacman command fails | error | Returns `[updates] {exception}` |

## Timeout

30 seconds for pacman, 60 seconds for checkupdates.

## Dependencies

- Arch Linux with `pacman`
- Optional: `pacman-contrib` (provides `checkupdates` for faster checks)
