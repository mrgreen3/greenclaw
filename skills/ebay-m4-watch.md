---
name: ebay-m4-watch
description: Daily watch for a base M4 Mac mini (16GB/256GB) on eBay UK. Pings only when a listing lands at or under the price threshold.
exposes: cc
trigger: /ebay
locked: false
source: owner
---

Watch eBay UK for a base-spec Apple Mac mini M4 (16GB / 256GB) at a good price.

Run the watcher:

    python skills/ebay_watch.py

It fetches the current listings for that exact config, compares them against
what it has already flagged, and prints any listing at or under the price
threshold (default £640, set at the top of the script).

Then decide what to send Kev:

- If the output has one or more `ALERT:` lines, send them — one listing per
  line, cheapest first: price, title, and the eBay link.
- If the output says nothing new was found, **stay silent**. Don't message.
  No news is fine; only ping when there's something worth a look.
- If the output starts with `[ebay]`, that's an error (layout change or
  network). Pass that line through so Kev knows the watcher needs attention.

UK date format. Keep it terse. Read-only — never bid, buy, watch, or message a seller.
