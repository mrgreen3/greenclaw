---
name: example
description: Template skill — copy this file to get started. Describe when the assistant should use it.
exposes: cc             # cc (Claude Code) | gg (cloud model)
trigger: /example       # the command that runs it
locked: false           # true = must be armed in skills.allow before it runs
source: owner           # who wrote it — for auditing
---

Everything below the front matter is the recipe: plain-language instructions
for what the assistant should do when this skill runs. Anything typed after
the trigger (e.g. `/example do the thing`) is passed straight through as
input.

Keep it specific — what to check, what to report, what NOT to do (especially
for anything with reach: shell commands, external accounts, destructive
actions). See README.md's "Skills" section for the full format, and
skills/paper-trade.py for a Python skill example.
