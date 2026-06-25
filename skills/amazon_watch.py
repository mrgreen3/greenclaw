NAME = "amazon_watch"
TRIGGER = "/amazon"
DESCRIPTION = "Watch Amazon UK product prices against thresholds (read-only)"
SAFE = True

import json
import re
from pathlib import Path

from curl_cffi import requests as cffi_requests
from bs4 import BeautifulSoup

# ---- config ----------------------------------------------------------------
WATCHLIST = [
    # (ASIN, threshold_gbp)
    ("B0FJG8R8SL", 9.50),
]
REALERT_DROP = 1.00   # re-alert if price drops this much further from last alert
STATE = Path.home() / ".local/share/greenclaw/amazon-watch.json"


def _fetch(asin: str) -> str:
    url = f"https://www.amazon.co.uk/dp/{asin}"
    r = cffi_requests.get(url, impersonate="chrome", timeout=20)
    r.raise_for_status()
    return r.text


def _parse(html: str) -> tuple[str, float]:
    soup = BeautifulSoup(html, "html.parser")

    if "captcha" in html.lower() and not soup.find(id="productTitle"):
        raise ValueError("CAPTCHA block — try again later or from a home IP")

    title_tag = soup.find(id="productTitle")
    title = title_tag.get_text(strip=True) if title_tag else "Unknown title"

    price_block = soup.select_one("span.a-price span.a-offscreen")
    if not price_block:
        raise ValueError("price not found — page layout may have changed")

    raw = price_block.get_text(strip=True)
    match = re.search(r"[\d,]+\.\d{2}", raw.replace("£", ""))
    if not match:
        raise ValueError(f"could not parse price from {raw!r}")

    price = float(match.group(0).replace(",", ""))
    return title, price


def _load() -> dict:
    try:
        return json.loads(STATE.read_text())
    except Exception:  # noqa: BLE001
        return {"alerted": {}}


def _save(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2))


def run(args: str) -> str:
    state = _load()
    alerted = state.get("alerted", {})
    lines = []
    errors = []

    for asin, threshold in WATCHLIST:
        try:
            title, price = _parse(_fetch(asin))
        except Exception as e:  # noqa: BLE001
            errors.append(f"[amazon:{asin}] {e}")
            continue

        if price > threshold:
            continue

        prev = alerted.get(asin)
        fresh = prev is None
        cheaper = prev is not None and prev - price >= REALERT_DROP

        if fresh or cheaper:
            tag = "new" if fresh else f"↓ was £{prev:.2f}"
            lines.append(
                f"ALERT: £{price:.2f} — {title} [{tag}] "
                f"— https://www.amazon.co.uk/dp/{asin}"
            )
            alerted[asin] = price

    state["alerted"] = alerted
    _save(state)

    parts = lines + errors
    if not parts:
        return ""
    return "\n".join(parts)


if __name__ == "__main__":
    result = run("")
    if result:
        print(result)
