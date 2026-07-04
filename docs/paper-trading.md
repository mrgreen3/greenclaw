# Paper Trading ETF Tracker

A zero-risk ETF buy-trigger simulator. Tracks price dips against configurable thresholds, logs simulated buys to CSV. No real orders, no financial exposure — pure data collection for validating trigger logic.

## Setup

### 1. Get Trading 212 API Key

1. Log in to Trading 212 app
2. Go to Settings → API → Create new key
3. **Important**: Request **read-only** access only. No order-placing permissions.
4. Copy the key and add to `.env`:

```bash
TRADING212_API_KEY=<your-key-here>
```

5. Restart greenclaw:
```bash
systemctl --user restart greenclaw-bot.service
```

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

- **Endpoint**: Trading 212 live API (`https://live.trading212.com/api/v0/...`)
- **Auth**: Bearer token (from API key)
- **Rate limit**: Check Trading 212 docs for free/demo tier limits
- **Demo mode**: Falls back to demo API if live API fails (for testing)

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

### "TRADING212_API_KEY not set"

Add the key to `.env` and restart:
```bash
echo "TRADING212_API_KEY=<key>" >> .env
systemctl --user restart greenclaw-bot.service
```

### "API error 401"

- Check that API key is valid (not expired)
- Ensure read-only access is enabled in Trading 212 settings
- Verify Bearer token format in code

### "No data for ticker"

- Confirm ticker is valid and available on Trading 212
- Check Trading 212 API docs for supported instruments
- Try a common ETF (VWRP, VMID, VUKE) first to isolate the issue

### CSV not created

- Check CSV path in `etfs.json`
- Ensure directory exists (`~/Projects/greenclaw/`)
- Check file permissions

## See Also

- Issue #42 (GitHub)
- CLAUDE.md for project structure
- `etfs.json` for configuration
- `schedules/paper-trade.md` for scheduling
