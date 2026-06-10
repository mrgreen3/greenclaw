---
name: note
description: Append a timestamped note to ~/notes.md. Use when the user says remember, note, jot, or add to notes.
exposes: local
trigger: /note
locked: false
source: owner
---

Append the user's text to ~/notes.md using run_shell. Format it as a single line:
`- [YYYY-MM-DD HH:MM] <text>`

Get the timestamp with: `date '+%Y-%m-%d %H:%M'`
Append with: `echo "- [$(date '+%Y-%m-%d %H:%M')] <text>" >> ~/notes.md`

Confirm what was noted in your reply.
