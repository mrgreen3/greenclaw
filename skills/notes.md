---
name: notes
description: Read back saved notes from ~/notes.md. Use when the user asks to see, list, or read their notes.
exposes: local
trigger: /notes
locked: false
source: owner
---

Read the user's notes using run_shell: `tail -40 ~/notes.md 2>/dev/null || echo "(no notes yet)"`

Show the output as-is. If the file is empty or missing, say so plainly.
