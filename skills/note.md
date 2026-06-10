---
name: note
description: Append a timestamped note to the user's notes file. Use when the user says remember, note, jot, or add to notes.
exposes: local
trigger: /note
locked: false
source: owner
---

Call the `add_note` tool with the user's text exactly as given (do not paraphrase
or edit). Do NOT use run_shell for this — `add_note` writes the file safely and
handles the timestamp.

Confirm what was noted in a one-line reply.
