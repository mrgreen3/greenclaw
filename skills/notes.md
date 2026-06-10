---
name: notes
description: Read back saved notes from the user's notes file. Use when the user asks to see, list, or read their notes.
exposes: local
trigger: /notes
locked: false
source: owner
---

Call the `list_notes` tool (no arguments needed, or pass `limit` for a different
count). Show the output as-is. If empty, say so plainly.
