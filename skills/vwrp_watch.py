NAME = "vwrp_watch"
TRIGGER = "/vwrp"
DESCRIPTION = "Watch VWRP.L (Vanguard FTSE All-World ETF) price against threshold (read-only)"
SAFE = True

import json
import subprocess
import sys
from pathlib import Path

# ---- config ----------------------------------------------------------------
TICKER = "VWRP.L"
THRESHOLD_GBP = 138.00      # alert when price is at/below this
REALERT_DROP = 2.00         # re-alert when price drops this much further from last alert
STATE = Path.home() / ".local/share/greenclaw/vwrp-watch.json"
VENV_PYTHON = Path(__file__).resolve().parent.parent / ".venv/bin/python"  # ~/greenclaw/.venv


def _fetch_price() -> float:
    """Invoke yfinance in the venv via subprocess to avoid import conflicts."""
    code = (
        "import yfinance as yf, json; "
        f"t = yf.Ticker('{TICKER}'); "
        "print(t.fast_info.last_price)"
    )
    result = subprocess.run(
        [str(VENV_PYTHON), "-c", code],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "yfinance failed")
    return float(result.stdout.strip())


def _load() -> dict:
    try:
        return json.loads(STATE.read_text())
    except Exception:  # noqa: BLE001
        return {"alerted_price": None}


def _save(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2))


def run(args: str) -> str:
    try:
        price = _fetch_price()
    except Exception as e:  # noqa: BLE001
        return f"[vwrp] {e}"

    state = _load()
    prev = state.get("alerted_price")

    below_threshold = price <= THRESHOLD_GBP
    fresh = below_threshold and prev is None
    cheaper = below_threshold and prev is not None and prev - price >= REALERT_DROP

    if fresh or cheaper:
        tag = "first alert" if fresh else f"↓ was £{prev:.2f}"
        state["alerted_price"] = price
        _save(state)
        return f"ALERT: VWRP.L at £{price:.2f} [{tag}] — below £{THRESHOLD_GBP:.2f} threshold"

    if not below_threshold and prev is not None:
        # Price recovered above threshold — reset so we alert again if it drops back
        state["alerted_price"] = None
        _save(state)

    return ""


if __name__ == "__main__":
    result = run("")
    if result:
        print(result)
