---
name: vwrp-watch
description: Daily watch for VWRP.L (Vanguard FTSE All-World ETF). Alerts when the price drops at or below £138.00, and re-alerts each further £2.00 drop.
exposes: cc
trigger: /vwrp
locked: false
source: owner
---

Watch the VWRP.L ETF price via yfinance and alert when it crosses the threshold.

Run the watcher:

    python skills/vwrp_watch.py

It fetches the current price for VWRP.L, compares against the £138.00 threshold and
the last alerted price, and prints an alert if the price has dropped to a new low.

Then decide what to send Kev:

- If the output has an `ALERT:` line, send it — price and tag (first alert or how
  much further it has dropped).
- If the output is empty, **stay silent**. Don't message.
  No news is fine; only ping when the price crosses a new low.
- If the output starts with `[vwrp]`, that's an error (network or yfinance issue).
  Pass that line through so Kev knows the watcher needs attention.

UK date format. Keep it terse. Read-only — never trade or place orders.
