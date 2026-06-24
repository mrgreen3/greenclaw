NAME = "ebay_watch"
TRIGGER = "/ebay"
DESCRIPTION = "Watch eBay UK for base M4 Mac mini (16GB/256GB) deals (read-only)"
SAFE = True

import json
import re
from pathlib import Path

import httpx

# ---- config -------------------------------------------------------------
# Apple Mac mini M4, base spec. EPID is eBay's catalogue id for the exact
# 16GB/256GB config, so the product listing page stays on-spec with no
# keyword noise (no Pro, no other RAM/SSD variants).
EPID = "23072688384"
THRESHOLD_GBP = 640.0          # alert on item price at/under this (postage extra)
REALERT_DROP = 10.0            # re-alert a known listing if it drops this much
SEARCH_URL = (
    f"https://www.ebay.co.uk/sch/i.html"
    f"?_productid={EPID}&LH_BIN=1&_sop=15"     # Buy-It-Now, price + postage asc
)
STATE = Path.home() / ".local/share/greenclaw/ebay-m4.json"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"


def _fetch() -> str:
    r = httpx.get(SEARCH_URL, headers={"User-Agent": UA},
                  timeout=20, follow_redirects=True)
    r.raise_for_status()
    return r.text


def _parse(html: str) -> list[dict]:
    """Pull (iid, title, price) from eBay search cards. Tolerant by design —
    if eBay reshapes its markup this returns [] rather than throwing."""
    items, seen = [], set()
    for chunk in re.split(r'class="s-item__(?:wrapper|info)', html)[1:]:
        iid = re.search(r"/itm/(\d+)", chunk)
        price = re.search(r"\u00a3\s?([\d,]+\.\d{2})", chunk)
        title = re.search(r's-item__title[^>]*>(?:<[^>]+>)*([^<]{6,140})', chunk)
        if not (iid and price and title):
            continue
        t = re.sub(r"\s+", " ", title.group(1)).strip()
        tl = t.lower()
        if tl.startswith("shop on ebay") or "pro" in tl:
            continue
        if "16gb" not in tl.replace(" ", "") or "256" not in tl:
            continue
        if iid.group(1) in seen:
            continue
        seen.add(iid.group(1))
        items.append({
            "iid": iid.group(1),
            "title": t,
            "price": float(price.group(1).replace(",", "")),
        })
    return items


def _load() -> dict:
    try:
        return json.loads(STATE.read_text())
    except Exception:  # noqa: BLE001
        return {"alerted": {}}


def _save(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2))


def run(args: str) -> str:
    try:
        items = _parse(_fetch())
    except Exception as e:  # noqa: BLE001
        return f"[ebay] {e}"

    if not items:
        return "[ebay] parsed 0 listings — eBay layout may have changed; "\
               "consider switching to the official Browse API."

    state = _load()
    alerted = state.get("alerted", {})
    lines = []
    for it in sorted(items, key=lambda x: x["price"]):
        if it["price"] > THRESHOLD_GBP:
            continue
        prev = alerted.get(it["iid"])
        fresh = prev is None
        cheaper = prev is not None and prev - it["price"] >= REALERT_DROP
        if fresh or cheaper:
            tag = "new" if fresh else f"↓ was £{prev:.2f}"
            lines.append(
                f"ALERT: £{it['price']:.2f} (+postage) — {it['title']} "
                f"[{tag}] — https://www.ebay.co.uk/itm/{it['iid']}"
            )
            alerted[it["iid"]] = it["price"]

    state["alerted"] = alerted
    _save(state)

    if not lines:
        return f"No new sub-£{THRESHOLD_GBP:.0f} listings ({len(items)} checked)."
    return "\n".join(lines)


if __name__ == "__main__":
    print(run(""))
