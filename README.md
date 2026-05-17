# ORB (Opening Range Breakout) Trading Bot

Standalone ORB trading bot extracted from [Final](https://github.com/frzkhn155-ai/Final).

## Features

- Opening Range Breakout (ORB) strategy for NSE F&O
- FII/DII institutional flow filter
- Klinger Oscillator quality gate
- RSI momentum confirmation
- Volume spike confirmation
- Paper trading mode (default)
- CSV logging for signals and trades

## Setup

```bash
pip install -r requirements.txt
```

## Configuration

Edit `orb_standalone.py` and set your credentials:

```python
HARDCODED_TOKEN = "your_upstox_token"
USE_HARDCODED_TOKEN = True
```

Or use environment variables:

```bash
set UPSTOX_TOKEN=your_token_here
```

## Run

```bash
python orb_standalone.py
```

## Files

| File | Description |
|------|-------------|
| `orb_standalone.py` | Main trading bot |
| `requirements.txt` | Python dependencies |

## Logs

- `orb_signals.csv` - All generated ORB signals
- `orb_trades.csv` - Trade entries/exits
- `orb_trading_log.txt` - Detailed text log

## Disclaimer

Use at your own risk. This is for educational purposes only.
