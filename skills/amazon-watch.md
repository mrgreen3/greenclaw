---
name: amazon-watch
description: Daily watch for Amazon UK products against price thresholds. Pings only when a price drops below threshold for the first time, or falls a further £1.00 from the last alerted price.
exposes: cc
trigger: /amazon
locked: false
source: owner
---

Watch Amazon UK product prices against configured thresholds.

Run the watcher:

    python skills/amazon_watch.py

It fetches each product page, extracts the current price, compares against
the threshold and last-alerted price, and prints any new alerts.

Then decide what to send Kev:

- If the output has one or more `ALERT:` lines, send them — one product per
  line: price, title, and the Amazon link.
- If the output is empty or has nothing to report, **stay silent**. Don't message.
  No news is fine; only ping when there's something worth a look.
- If the output starts with `[amazon:`, that's an error (layout change or
  network). Pass that line through so Kev knows the watcher needs attention.

UK date format. Keep it terse. Read-only — never add to basket, buy, or interact with the page.
