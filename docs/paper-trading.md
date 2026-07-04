# Paper Trading ETF Tracker

A zero-risk ETF buy-trigger simulator. Tracks price dips against configurable thresholds, logs simulated buys to CSV. No real orders, no financial exposure — pure data collection for validating trigger logic.

## Setup

### 1. Get Alpha Vantage API Key (Optional)

Price data comes from **Alpha Vantage** — a free market data API. No broker account needed.

**Free tier**: 5 API calls/min, unlimited daily (no key required)
**With API key**: 500 calls/min

1. (Optional) Get a free API key at https://www.alphavantage.co/api/
2. Add to `.env`:

```bash
ALPHA_VANTAGE_API_KEY=<your-key-here>
```

3. Restart greenclaw:
```bash
systemctl --user restart greenclaw-bot.service
```

**Note**: The skill works fine without an API key — you'll just be limited to 5 calls/min.

### 2. Configure ETFs

Edit `etfs.json` to add/remove ETFs and set trigger thresholds:

```json
{
  "etfs": [
    {
      "ticker": "VWRP",
      "trigger_pct": -2.0,
      "notional": 100.0,
      "description": "Vanguard FTSE World ETF"
    }
  ],
  "csv_file": "~/Projects/greenclaw/etfs-trades.csv"
}
```

- **ticker**: ETF symbol (e.g., VWRP)
- **trigger_pct**: % drop threshold (e.g., -2.0 = buy if drops 2% from previous close)
- **notional**: Simulated buy amount in £ (e.g., 100.0 = £100 per trigger)
- **description**: Optional note

### 3. Run Manually

```
/paper-trade
```

Returns summary of checked ETFs and any triggers.

### 4. Schedule Daily Checks

Already configured in `schedules/paper-trade.md` to run at **16:30 UTC (market close)** on weekdays.

Modify the schedule if you prefer a different time:

```yaml
---
name: paper-trade
schedule: 16:30      # HH:MM UTC
days: weekdays       # weekdays or daily
skill: paper-trade
---
```

## Output

### CSV Format

All triggered buys logged to `etfs-trades.csv`:

```
date,ticker,previous_close,trigger_price,pct_drop,notional,simulated_shares,current_price,unrealised_pnl
2026-07-04T15:30:00,VWRP,100.00,98.00,-2.00%,100.00,1.0000,98.00,-2.00
```

**Columns:**
- **date**: ISO timestamp of the check
- **ticker**: ETF symbol
- **previous_close**: Price at previous market close
- **trigger_price**: Current price (when trigger fired)
- **pct_drop**: % change from previous close
- **notional**: Simulated investment amount (£)
- **simulated_shares**: Calculated shares bought at previous close price
- **current_price**: Current price (for tracking)
- **unrealised_pnl**: Simulated P&L from previous close to current

## Examples

### Scenario: VWRP drops 2%

Config:
```json
{
  "ticker": "VWRP",
  "trigger_pct": -2.0,
  "notional": 100.0
}
```

Market data:
- Previous close: £100
- Current: £98 (-2%)

Result:
- Trigger fires ✓
- Logged: £100 invested → 1.0000 shares @ £100 entry
- Current P&L: -£2.00

### Scenario: VMID drops 1.8% (below -2.5% threshold)

Config:
```json
{
  "ticker": "VMID",
  "trigger_pct": -2.5,
  "notional": 100.0
}
```

Market data:
- Previous close: £100
- Current: £98.20 (-1.8%)

Result:
- Trigger does NOT fire ✗ (only -1.8%, need -2.5%+)
- No log entry

## API Notes

- **Endpoint**: Alpha Vantage Global Quote (`https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol=...`)
- **Auth**: Optional API key (free tier works without it)
- **Rate limit**: 5 calls/min free tier; 500 calls/min with API key
- **Data**: Real-time market prices (delayed 15-20 min for stocks/ETFs)
- **Coverage**: 6000+ instruments including major stock exchanges and ETFs

## Limitations

**Out of scope for now:**
- No sell/exit logic
- No P&L calculation beyond simple unrealised PnL
- No autonomous order execution
- No backtesting

**Future enhancements:**
- Trailing stop-loss tracking
- Sell triggers (take-profit, stop-loss)
- Performance analysis across multiple triggers
- Integration with actual order placement (when risk assessment complete)

## Troubleshooting

### "Symbol not found"

- Confirm ticker is valid and available on Alpha Vantage
- Try a common ETF: VWRP, VMID, VUKE
- Check Alpha Vantage coverage at https://www.alphavantage.co/

### "Rate limit reached"

- Free tier: 5 calls/min. Wait a minute or add an API key for higher limits.
- With API key: 500 calls/min. Get key at https://www.alphavantage.co/api/

### "Missing price fields"

- Some tickers may not have previous close data
- Try a different ticker or check Alpha Vantage docs for data availability

### CSV not created

- Check CSV path in `etfs.json`
- Ensure directory exists (`~/Projects/greenclaw/`)
- Check file permissions

### "Invalid price data (not numeric)"

- Alpha Vantage may have returned non-numeric values
- Try again in a moment; this is usually a transient API issue

## See Also

- Issue #42 (GitHub)
- CLAUDE.md for project structure
- `etfs.json` for configuration
- `schedules/paper-trade.md` for scheduling
