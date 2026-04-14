# Upstox Auto-Trading Bot

Real-time F&O options trading bot for NSE using Upstox API, with multi-strategy support, AI assistant (Groq), and intelligent candle caching.

---

## Strategies

- **R3/S3 Breakout** — trades pivot level breakouts
- **Box Theory** — range breakout / breakdown
- **Range Trading** — support bounce / resistance rejection
- **Gap Trading** — gap-up and gap-down plays
- **Fast Trading** — Bollinger squeeze + pullback (5min/15min)
- **ORB** — Opening Range Breakout at 09:20
- **Klinger Oscillator** — confirms signals across all strategies
- **AI Assistant** — Groq LLM monitors positions, warns on reversals, can auto-exit

---

## Files

| File | Purpose |
|---|---|
| `Both4withcache10_headless.py` | Main bot — all strategies, order management, monitoring loop |
| `ai_assistant.py` | Background AI thread (Groq / llama-3.3-70b) |
| `requirements.txt` | Python package dependencies |
| `.gitignore` | Excludes tokens, logs, and cache from git |

---

## Setup

### 1. Install Python packages

```bash
pip install -r requirements.txt
```

### 2. Chrome + ChromeDriver

The bot uses Selenium for headless Upstox login. Chrome must be installed.
`webdriver-manager` handles ChromeDriver automatically.

### 3. Configure credentials

Open `Both4withcache10_headless.py` and fill in your details near the top:

```python
EMAIL            = "your_email@gmail.com"
EMAIL_PASSWORD   = "your_gmail_app_password"   # Gmail App Password, not your login password
MOBILE_NUMBER    = "9999999999"
PASSCODE         = "your_upstox_passcode"

UPSTOX_API_KEY      = "your_client_id"         # from Upstox Developer Portal
UPSTOX_API_SECRET   = "your_client_secret"
UPSTOX_REDIRECT_URI = "http://127.0.0.1:8080/" # must match your app settings exactly
```

> ⚠️ **Never commit real credentials to GitHub.** Use environment variables or a `.env` file for production.

### 4. (Optional) Set your Upstox token directly

If you already have a valid token, set it to skip the OAuth flow:

```python
HARDCODED_TOKEN    = "eyJ..."   # paste your token
USE_HARDCODED_TOKEN = True
```

### 5. (Optional) AI Assistant — Groq

Get a free API key from [console.groq.com](https://console.groq.com), then set it in `ai_assistant.py`:

```python
GROQ_API_KEY = "gsk_..."
```

Or set it as an environment variable:

```bash
export GROQ_API_KEY="gsk_..."
```

### 6. (Optional) Update Chartink cookies

If 5-minute candle data fails, refresh the cookies in `Both4withcache10_headless.py`:

1. Go to `chartink.com/stocks-new` in Chrome
2. Open DevTools → Network → refresh the page → click any `chartink.com` request
3. Copy `XSRF-TOKEN` and `ci_session` from Request Headers → Cookies into `CHARTINK_COOKIES`

---

## Running

```bash
python Both4withcache10_headless.py
```

The bot will:
1. Acquire an Upstox access token (hardcoded → refresh token → full OAuth login, in that order)
2. Load all F&O equity instruments
3. Initialize R3/S3/Box/Range levels with historical data
4. Start the real-time monitoring loop (scans every 30 seconds)

---

## Key Configuration Flags

| Flag | Default | Description |
|---|---|---|
| `TEST_MODE` | `True` | Bypasses market-hours checks — bot runs at any time |
| `WAIT_FOR_ORDER_WINDOW` | `False` | `False` = start scanning immediately, no 05:30 wait |
| `ENABLE_AUTO_TRADING` | `True` | Place real orders via Upstox API |
| `ENABLE_FAST_TRADING` | `True` | Bollinger squeeze / pullback strategy |
| `ENABLE_ORB_STRATEGY` | `True` | Opening Range Breakout |
| `ENABLE_FII_DII_FILTER` | `True` | Filter signals by institutional flow |
| `DEBUG_MODE` | `True` | Verbose console output |

> **Orders are always blocked outside 05:30–23:59 IST** — this is an Upstox/exchange hard limit and cannot be overridden.

---

## Runtime-generated files (auto-created, not in git)

| File/Folder | Contents |
|---|---|
| `candle_cache/` | Cached OHLCV candle data per symbol |
| `upstox_token.txt` | Saved access token |
| `upstox_refresh_token.txt` | OAuth refresh token |
| `r3_live_alerts.csv` | R3/S3 signal log |
| `gap_trading_alerts.csv` | Gap signal log |
| `box_trading_alerts.csv` | Box signal log |
| `range_trading_alerts.csv` | Range signal log |
| `fast_trades_entries/exits.csv` | Fast trade log |
| `positions_tracking.csv` | Position P&L log |
| `fii_dii_cache.json` | FII/DII data cache |

---

## Security notes

- Add `upstox_token.txt`, `upstox_refresh_token.txt`, and any file containing credentials to `.gitignore` (already done).
- Consider moving hardcoded credentials to environment variables before sharing or deploying.
