NAME = "paper-trade"
TRIGGER = "/paper-trade"
DESCRIPTION = "Paper-trading ETF trigger tracker (no real orders; simulated % dip buys logged to CSV)"
SAFE = True

import csv
import json
import os
from datetime import datetime

import yfinance as yf


_HERE = os.path.dirname(os.path.abspath(__file__))
ETFS_CONFIG = os.path.join(_HERE, "..", "etfs.json")


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


def _fetch_price(ticker: str) -> dict:
    """Fetch current and previous close price from Yahoo Finance.

    Returns: {ticker, current, previous_close, error?}
    """
    try:
        ticker_obj = yf.Ticker(ticker)
        hist = ticker_obj.history(period="5d")

        if hist.empty:
            return {"ticker": ticker, "error": f"No data found for {ticker}"}

        current = float(hist["Close"].iloc[-1])
        prev_close = float(hist["Close"].iloc[-2]) if len(hist) > 1 else current

        if not current or not prev_close:
            return {"ticker": ticker, "error": "Invalid price data"}

        return {"ticker": ticker, "current": current, "previous_close": prev_close}

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

        # Fetch prices from Yahoo Finance
        prices = _fetch_price(ticker)

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
