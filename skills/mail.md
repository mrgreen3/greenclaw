---
name: mail
description: Check Gmail for recent or relevant messages and summarise them. Use when Kev asks about email, his inbox, or whether someone has been in touch.
exposes: cc
trigger: /mail
locked: true
source: kev
---

Check Kev's Gmail. If the request below names a sender, topic or timeframe, filter
to that; otherwise summarise anything from the last day or so that looks worth his
attention. One line each: sender — subject — the gist. If nothing's notable, say so
plainly. Read-only: do not reply, archive, label, or delete anything.
