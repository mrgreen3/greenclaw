---
name: system-health
description: Check disk, memory, load, and the bot service. Use when the user asks how the box or server is doing.
exposes: local
trigger: /health
locked: false
source: owner
---

Run these and summarise in a few lines, flagging anything that looks off:
- `df -h /`                        disk usage on root
- `df -h /mnt/storage 2>/dev/null || df -h /data 2>/dev/null || lsblk -o MOUNTPOINT,SIZE,USED,AVAIL | grep -v "^$\|loop"`  storage drive
- `free -h`                        memory
- `uptime`                         load average
- `systemctl --user is-active greenclaw.service`   is the bot up
- `sensors 2>/dev/null | grep -i 'temp\|core' | head -5`  temperatures (skip if sensors not installed)

Keep it terse. Flag anything that looks off. Don't suggest fixes unless something is actually wrong.
