NAME = "weather"
TRIGGER = "/weather"
DESCRIPTION = "Current weather for a location (default: London)"
SAFE = True

import httpx

DEFAULT_LOCATION = "London"

def run(args: str) -> str:
    location = args.strip() or DEFAULT_LOCATION
    try:
        r = httpx.get(
            f"https://wttr.in/{location}",
            params={"format": "%l: %C, %t (feels %f) 💨 %w 💧 %h"},
            headers={"User-Agent": "curl/7.0"},
            timeout=10,
            follow_redirects=True,
        )
        r.raise_for_status()
        return r.text.strip()
    except Exception as e:  # noqa: BLE001
        return f"[weather] {e}"
