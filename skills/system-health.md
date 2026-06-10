---
name: system-health
description: Check disk, memory, load, and the bot service. Use when the user asks how the box or server is doing.
exposes: local
trigger: /health
locked: false
source: owner
---

Run these and summarise in a few lines, flagging anything that looks off:
- `df -h /`            disk usage on root
- `free -h`            memory
- `uptime`             load average
- `systemctl --user is-active greenclaw-bot.service`   is the bot up

Keep it terse. Don't suggest fixes unless something is actually wrong.
