---
name: note
description: Append a timestamped note to the user's notes file. Use when the user says remember, note, jot, or add to notes.
exposes: cc
trigger: /note
locked: false
source: owner
---

Append a timestamped note to ~/notes.md. Format the line exactly as:

  - [YYYY-MM-DD HH:MM] <user's text verbatim>

Do not paraphrase or edit the user's text. Use the current date/time for the timestamp.
Confirm what was noted in a one-line reply.
