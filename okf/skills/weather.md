---
type: Skill
title: Weather — location lookup
description: Current weather for a location (default: London).
tags: [weather, location, api]
resource: skills/weather.py
trigger: /weather
---

## Overview

Fetches current weather conditions for a given location using wttr.in (free, no API key required). If no location is specified, defaults to London.

## Invocation

```
/weather [location]
/weather London         # explicit
/weather               # uses default (London)
```

## Output format

```
<location>: <conditions>, <temperature> (feels <feels-like>) 💨 <wind-speed> 💧 <humidity>
```

Example:
```
London: Partly cloudy, 15°C (feels 13°C) 💨 8 km/h 💧 72%
```

## Implementation

- **Endpoint**: `https://wttr.in/{location}` (wttr.in REST API)
- **Format string**: `%l: %C, %t (feels %f) 💨 %w 💧 %h`
- **Timeout**: 10 seconds
- **User-Agent**: spoofed as curl to avoid rate limiting

## Error handling

Returns `[weather] {exception}` if the request fails (network, timeout, unknown location, etc.).

## Dependencies

- `httpx` library for HTTP requests
