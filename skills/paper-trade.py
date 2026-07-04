NAME = "paper-trade"
TRIGGER = "/paper-trade"
DESCRIPTION = "Paper-trading ETF trigger tracker (no real orders; simulated % dip buys logged to CSV)"
SAFE = True

import csv
import json
import os
from datetime import datetime

import httpx


ALPHA_VANTAGE_URL = "https://www.alphavantage.co/query"
ETFS_CONFIG = os.path.expanduser("~/Projects/greenclaw/etfs.json")


def _load_config() -> dict:
    """Load ETFs config from JSON."""
    if not os.path.exists(ETFS_CONFIG):
        # Create default config if missing
        default = {
            "etfs": [
                {"ticker": "VWRP", "trigger_pct": -2.0, "notional": 100.0},
            ],
            "csv_file": "~/Projects/greenclaw/etfs-trades.csv",
        }
        return default

    try:
        with open(ETFS_CONFIG) as f:
            return json.load(f) or {"etfs": []}
    except Exception as e:
        return {"error": f"Config load failed: {e}", "etfs": []}


def _get_alpha_vantage_key() -> str:
    """Fetch API key from .env (optional for free tier)."""
    return os.environ.get("ALPHA_VANTAGE_API_KEY", "").strip()


def _fetch_price(ticker: str, api_key: str = "") -> dict:
    """Fetch current and previous close price from Alpha Vantage.

    Returns: {ticker, current, previous_close, error?}
    """
    try:
        params = {
            "function": "GLOBAL_QUOTE",
            "symbol": ticker,
        }
        if api_key:
            params["apikey"] = api_key

        resp = httpx.get(ALPHA_VANTAGE_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        if "Note" in data:
            return {"ticker": ticker, "error": "Alpha Vantage rate limit reached"}

        if "Error Message" in data:
            return {"ticker": ticker, "error": f"Symbol not found: {ticker}"}

        quote = data.get("Global Quote", {})
        if not quote:
            return {"ticker": ticker, "error": "No quote data returned"}

        current = float(quote.get("05. price", 0))
        prev_close = float(quote.get("08. previous close", 0))

        if not current or not prev_close:
            return {"ticker": ticker, "error": "Missing price fields in API response"}

        return {"ticker": ticker, "current": current, "previous_close": prev_close}

    except httpx.HTTPStatusError as e:
        return {"ticker": ticker, "error": f"API error {e.status_code}"}
    except ValueError:
        return {"ticker": ticker, "error": "Invalid price data (not numeric)"}
    except Exception as e:
        return {"ticker": ticker, "error": f"Price fetch failed: {e}"}


def _check_trigger(current: float, previous_close: float, trigger_pct: float) -> bool:
    """Check if % dip from previous close triggers a buy.

    trigger_pct: e.g., -2.0 means "buy if dropped 2% or more from previous close"
    """
    if previous_close == 0:
        return False
    pct_change = ((current - previous_close) / previous_close) * 100
    return pct_change <= trigger_pct


def _log_trade(csv_file: str, trade_record: dict) -> None:
    """Append simulated trade to CSV."""
    csv_file = os.path.expanduser(csv_file)
    os.makedirs(os.path.dirname(csv_file), exist_ok=True)

    fieldnames = [
        "date",
        "ticker",
        "previous_close",
        "trigger_price",
        "pct_drop",
        "notional",
        "simulated_shares",
        "current_price",
        "unrealised_pnl",
    ]

    file_exists = os.path.exists(csv_file)
    try:
        with open(csv_file, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerow(trade_record)
    except Exception as e:
        print(f"CSV write error: {e}")


def run(args: str) -> str:
    """Main entry point: fetch prices, check triggers, log trades."""
    api_key = _get_alpha_vantage_key()
    if not api_key:
        import sys
        print(
            "⚠ ALPHA_VANTAGE_API_KEY not set in .env (optional, but recommended)\n"
            "Free tier works without API key (5 calls/min), but with key: 500/min.\n"
            "Get a free key: https://www.alphavantage.co/api/\n"
            "Then add to .env: ALPHA_VANTAGE_API_KEY=<key>\n",
            file=sys.stderr,
        )

    config = _load_config()
    if "error" in config:
        return f"Config error: {config['error']}"

    etfs = config.get("etfs", [])
    if not etfs:
        return "No ETFs configured in etfs.yaml"

    csv_file = config.get("csv_file", "~/Projects/greenclaw/etfs-trades.csv")
    triggered = []
    errors = []

    now = datetime.now()

    for etf in etfs:
        ticker = etf.get("ticker")
        trigger_pct = etf.get("trigger_pct", -2.0)
        notional = etf.get("notional", 100.0)

        if not ticker:
            continue

        # Fetch prices (try live, fallback to demo if key issues)
        prices = _fetch_price(ticker, api_key, use_demo=False)

        if "error" in prices:
            errors.append(f"{ticker}: {prices['error']}")
            continue

        current = prices.get("current")
        previous_close = prices.get("previous_close")

        if current is None or previous_close is None:
            errors.append(f"{ticker}: Invalid price data")
            continue

        pct_drop = ((current - previous_close) / previous_close) * 100

        # Check trigger
        if _check_trigger(current, previous_close, trigger_pct):
            simulated_shares = notional / previous_close  # Bought at previous close
            unrealised_pnl = (current - previous_close) * simulated_shares

            trade_record = {
                "date": now.isoformat(),
                "ticker": ticker,
                "previous_close": f"{previous_close:.2f}",
                "trigger_price": f"{current:.2f}",
                "pct_drop": f"{pct_drop:.2f}%",
                "notional": f"{notional:.2f}",
                "simulated_shares": f"{simulated_shares:.4f}",
                "current_price": f"{current:.2f}",
                "unrealised_pnl": f"{unrealised_pnl:.2f}",
            }

            _log_trade(csv_file, trade_record)
            triggered.append(ticker)

    # Summary
    lines = []
    lines.append(f"📊 Paper trading check @ {now.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Checked {len(etfs)} ETFs")

    if triggered:
        lines.append(f"\n✓ Triggers: {', '.join(triggered)}")
        lines.append(f"Logged to: {csv_file}")
    else:
        lines.append("\nNo triggers today.")

    if errors:
        lines.append(f"\n⚠ Errors:\n" + "\n".join(f"  - {e}" for e in errors))

    return "\n".join(lines)
