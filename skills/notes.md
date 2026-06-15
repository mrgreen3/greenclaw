---
name: notes
description: Read back saved notes from the user's notes file. Use when the user asks to see, list, or read their notes.
exposes: cc
trigger: /notes
locked: false
source: owner
---

Read ~/notes.md and show the most recent 40 lines as-is. If the file doesn't exist or is empty, say so plainly.
