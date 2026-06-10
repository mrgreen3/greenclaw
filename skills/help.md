---
name: help
description: Show available commands, prefixes, and loaded skills. Use when the user asks what you can do, for a command list, or for help.
exposes: local
trigger: /help
locked: false
source: owner
---

Use run_shell to list loaded skills (parses front matter properly via python):

  python3 -c "
  import os, re
  for fn in sorted(os.listdir(os.path.expanduser('~/greenclaw/skills'))):
      if not fn.endswith('.md'): continue
      with open(os.path.expanduser('~/greenclaw/skills/' + fn)) as f:
          text = f.read(4096)
      m = dict(re.findall(r'^(\w+):\s*(.+?)\s*$', text, re.M))
      t = m.get('trigger') or '(no trigger)'
      d = m.get('description', '')
      print(f'  {t:<12} {d}')
  "

Then reply with this cheat sheet, with the skill list below dropped in from the
command output:

**Prefixes**
- `cc <prompt>` — force Claude Code (email, web, GitHub, full reach)
- `gc <prompt>` — force local Qwen (free, on-device)
- _(no prefix)_ — Qwen first; escalates to CC when needed

**Commands**
- `usage` / `calls` — Claude Code call count today

**Skills**
[insert run_shell output here]
