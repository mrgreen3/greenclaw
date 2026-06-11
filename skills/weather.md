---
name: weather
description: Current weather and short forecast for London.
exposes: local
trigger: /weather
locked: false
source: owner
---

Run this command and summarise the output in 2-3 lines:

  curl -s "wttr.in/London?format=v2"

Report current conditions (temperature, feels-like if notably different, and a one-word description like "overcast" or "sunny"). Add today's high/low and mention rain if it's likely. Keep it short — no bullet points, no headers, just plain sentences.
