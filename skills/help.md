---
name: help
description: Show available commands, prefixes, and loaded skills. Use when the user asks what you can do, for a command list, or for help.
exposes: local
trigger: /help
locked: false
source: owner
---

Run this command to list loaded skills with their triggers and descriptions:
  grep -rh "^trigger:\|^description:" ~/greenclaw/skills/*.md | paste - - | awk -F'\t' '{gsub(/trigger: */,"",$1); gsub(/description: */,"",$2); printf "  %-20s %s\n", $1, $2}'

Then reply with this cheat sheet, filling in the skill list from the command above:

**Prefixes**
- `cc <prompt>` — force Claude Code (email, web, GitHub, full reach)
- `gc <prompt>` — force local Qwen (free, on-device)
- _(no prefix)_ — Qwen first; escalates to CC when needed

**Commands**
- `usage` / `tokens` / `cost` — CC call count for today

**Skills**
[insert skill triggers and descriptions here]
