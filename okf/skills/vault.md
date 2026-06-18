---
type: Skill
title: Vault — read/write notes in greenbrain
description: Read, search, or persist notes in the greenbrain personal knowledge vault.
tags: [knowledge-vault, notes, persistence, markdown]
resource: skills/vault.py
trigger: /vault
---

## Overview

Manages notes in the greenbrain personal knowledge vault (`~/greenbrain`). All writes are auto-committed and pushed to GitHub (via git). Greenbrain is a structured markdown directory synced to a private repo.

The vault is used by:
- `save_memory()` in greenclaw.py to persist long-term knowledge
- Manual `/vault` commands to read or search notes

## Configuration

No environment variables; all paths are hardcoded:

| Variable | Value |
|----------|-------|
| `VAULT_DIR` | `~/greenbrain` (private GitHub repo) |
| `GREENCLAW_DIR` | `~/greenbrain/greenclaw/` (greenclaw's namespace) |

## Functions

### `write_note(topic: str, content: str) -> str`

Writes or appends to a vault note.

- **Creates** a new file at `greenclaw/{slug}.md` if not found (with header + timestamp)
- **Appends** to existing file with new timestamp divider
- **Auto-commits** with message: `"{action}: {slug}"`
- **Auto-pushes** to GitHub (gracefully skips if git fails)
- Returns status string: `"vault: {created|updated} greenclaw/{slug}.md"`

Parameters:
- `topic` (str): Human-readable note title; converted to slug (lowercased, spaces → hyphens)
- `content` (str): Note body; leading/trailing whitespace stripped

### Internal: `_git_commit(msg: str)`

Commits and pushes changes. Silently continues if git fails (vault write succeeded regardless).

## Examples

```python
write_note("async runtime", "Tokio is good for..."
  → creates: ~/greenbrain/greenclaw/async-runtime.md
  → commits: "created: async-runtime"
  → pushes to GitHub

write_note("async runtime", "Tried Async-Std once, too..."
  → appends to same file
  → commits: "updated: async-runtime"
  → pushes to GitHub
```

## Dependencies

- `git` command (for commit/push)
- GitHub repo at `~/greenbrain` with write access
