import os
import sys
import pickle
import time
import imaplib
import email
import re
import json
import pyperclip
import requests
import pandas as pd
import csv
import numpy as np
import threading
from urllib.parse import urlparse, parse_qs
from http.server import HTTPServer, BaseHTTPRequestHandler

# ── AI Assistant (Groq free tier — see ai_assistant.py for setup) ─────────────
try:
    from ai_assistant import start_ai_assistant, ai_status, AI_ENABLED as _AI_ENABLED
    _AI_IMPORT_OK = True
except ImportError:
    _AI_IMPORT_OK = False
    def start_ai_assistant(*a, **kw): pass
    def ai_status(): return "AI Assistant: ai_assistant.py not found"
# ─────────────────────────────────────────────────────────────────────────────

# ── Reversal strategy (opening-range reversal — see reversal_strategy.py) ──────
try:
    from reversal_strategy import find_latest_reversal_signal
    _REVERSAL_IMPORT_OK = True
except ImportError:
    _REVERSAL_IMPORT_OK = False
    def find_latest_reversal_signal(*a, **kw): return None
# ─────────────────────────────────────────────────────────────────────────────
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo          # stdlib, Python 3.9+
from email.utils import parsedate_to_datetime

# ── IST helper ────────────────────────────────────────────────────────────────
_IST = ZoneInfo("Asia/Kolkata")

def now_ist() -> datetime:
    """Return the current wall-clock time in IST as a *naive* datetime.

    Every call to ``now_ist()`` in this file has been replaced with
    ``now_ist()`` so that market-hour checks, order-window guards, and log
    timestamps all reflect Indian Standard Time (UTC +5:30) regardless of
    the timezone configured on the host server.
    """
    return datetime.now(_IST).replace(tzinfo=None)
# ─────────────────────────────────────────────────────────────────────────────
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import TimeoutException, ElementClickInterceptedException
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup

# ============ FORCE UNBUFFERED OUTPUT (fixes Pydroid3 display freeze) ============
sys.stdout = os.fdopen(sys.stdout.fileno(), 'w', buffering=1)  # Line-buffered
sys.stderr = os.fdopen(sys.stderr.fileno(), 'w', buffering=1)

# ============ CREDENTIALS - ENV VARS (with hardcoded fallbacks) ============
EMAIL          = os.environ.get("UPSTOX_EMAIL",    "frzkhn155@gmail.com")
EMAIL_PASSWORD = os.environ.get("UPSTOX_PASSWORD", "vdeahogzvpsmfirv")
MOBILE_NUMBER  = os.environ.get("UPSTOX_MOBILE",   "7397408750")
PASSCODE       = os.environ.get("UPSTOX_PASSCODE", "952495")

# ── Upstox OAuth app credentials (for Android token refresh) ─────────────────
# Get these from https://account.upstox.com/developer/apps → your app
# API Key    = "Client ID" on the Upstox developer portal
# API Secret = "Client Secret"
# Redirect   = must match exactly what you set in the app (use the one below)
UPSTOX_API_KEY      = os.environ.get("UPSTOX_API_KEY",    "ea9b2ade-6720-4a0b-a8a5-6e1710f55844")
UPSTOX_API_SECRET   = os.environ.get("UPSTOX_API_SECRET", "csxmppf5zd")
UPSTOX_REDIRECT_URI = "http://127.0.0.1:8080/"        # must match your app settings

# ── Headless OAuth local server port ─────────────────────────────────────────
# A tiny HTTP server listens on this port to capture the OAuth redirect code.
# Must match UPSTOX_REDIRECT_URI above (port 8080).
HEADLESS_SERVER_PORT = 8080
UPSTOX_REFRESH_TOKEN_FILE = "upstox_refresh_token.txt"
# ─────────────────────────────────────────────────────────────────────────────

# ========== CHARTINK CONFIGURATION (for 5min data) ==========
CHARTINK_BASE_URL = "https://chartink.com/oapi"
CHARTINK_COOKIES = {
    "_ga": "GA1.2.1533223166.1742236648",
    "XSRF-TOKEN": "eyJpdiI6IjFkM21JUDJhSjI3eWxVRno5TnRIcVE9PSIsInZhbHVlIjoiRzRkRlh1THBGVTFoZE5Rbm5oSjhSdG84VUo1NFJLNUs1WmtIbXNOL2IxQkZWM016TkZFVE9KRk9Ed0Z3U1VTVCsvNUw1NzM2OHZxL2JoTEE3Mkx2U2x0Q0NzdEg1eThPakYwd2tvMEhsbGZlRENGbmFHalFGbGhyV2VHL2tMTEciLCJtYWMiOiJjZmY1YTc4NmQ5MTZhZTZkZjExN2YyMTc3M2QxNzIxODYyMzhkYzIwMmJkNWM3NmRkNTRmNWMwOWNmZTNmZTc1IiwidGFnIjoiIn0=",
    "ci_session": "eyJpdiI6Ik5yWkd3UTM1N0FYbjFJcmI4NTdxWlE9PSIsInZhbHVlIjoiVDZBazRrTFdIMlRFMW52d0JFU1pSempOTndnT09jNC9tRXoxZXZwamE2RUVIQWlzQTl3b3pEa2NTYXpzQk5ZWWxEcGViUmM2ZmRBQnQxMVFFZy9SOFBBaDNScmFER3BVUWE1V21URVN3bk5IMzBNWVIyaHhmWUVsT1VDelZQVjgiLCJtYWMiOiJmNWVkN2RlMzIzNDkzNDcyZDU5Y2RhODQ5YjZjYzI4M2I0YTA0YjBhYTA4YTFkNTgwYzFjZTc5YjlmZWJiMDZiIiwidGFnIjoiIn0="
}
# ⚠️  UPDATE CHARTINK_COOKIES FROM YOUR BROWSER if 5min data fails:
# 1. Go to chartink.com/stocks-new in Chrome
# 2. DevTools (F12) → Network → refresh → click any chartink.com request
# 3. Copy XSRF-TOKEN and ci_session from Request Headers → Cookies

# ========== HARDCODED TOKEN OPTION ==========
HARDCODED_TOKEN = "eyJ0eXAiOiJKV1QiLCJrZXlfaWQiOiJza192MS4wIiwiYWxnIjoiSFMyNTYifQ.eyJzdWIiOiIyMkM4REwiLCJqdGkiOiI2OWUxYTUxNmVhOTJhNTBmZTYwZjAwY2IiLCJpc011bHRpQ2xpZW50IjpmYWxzZSwiaXNQbHVzUGxhbiI6dHJ1ZSwiaWF0IjoxNzc2Mzk1NTQyLCJpc3MiOiJ1ZGFwaS1nYXRld2F5LXNlcnZpY2UiLCJleHAiOjE3NzY0NjMyMDB9.enP-ZbfL-q4JCJ78u-l9QVDUj71LOV2Ogi8QmeLXRDg"          # Intentionally blank — token is injected via UPSTOX_TOKEN secret
USE_HARDCODED_TOKEN = True   # Disabled — bot reads upstox_token.txt written by the workflow

# Token timestamp file
TOKEN_TIMESTAMP_FILE = "token_timestamp.json"
UPSTOX_TOKEN_FILE = "upstox_token.txt"

# ========== CONFIGURATION ==========
MARKET_OPEN_TIME = "09:15"
MARKET_CLOSE_TIME = "15:30"
MARKET_STABILIZATION_MINUTES = 5
EXIT_START_TIME = "15:20"

# Volume / Filter Settings
MIN_AVG_VOLUME = 500_000
VOLUME_SPIKE_THRESHOLD = 1.3
VOLUME_LOOKBACK_DAYS = 20
USE_DYNAMIC_VOLUME_THRESHOLD = True
MAX_WORKERS = 3
DEBUG_MODE = True                      # enables ⛔ ORB reversal rejection prints
BATCH_SIZE = 100
MAX_INSTRUMENTS_PER_BATCH = 500

# Logging
ALERT_LOG_FILE = "r3_live_alerts.txt"
ALERT_CSV_FILE = "r3_live_alerts.csv"
GAP_LOG_FILE = "gap_trading_alerts.txt"
GAP_CSV_FILE = "gap_trading_alerts.csv"
BOX_LOG_FILE = "box_trading_alerts.txt"
BOX_CSV_FILE = "box_trading_alerts.csv"
RANGE_LOG_FILE = "range_trading_alerts.txt"
RANGE_CSV_FILE = "range_trading_alerts.csv"
EXIT_LOG_FILE = "exits_log.txt"
EXIT_CSV_FILE = "exits_log.csv"
POSITION_LOG_FILE = "positions_tracking.csv"
FAST_TRADE_ENTRY_FILE = "fast_trades_entries.csv"
FAST_TRADE_EXIT_FILE = "fast_trades_exits.csv"

# AUTOMATED TRADING CONFIGURATION
ENABLE_AUTO_TRADING = True
ORDER_QUANTITY = 1
ORDER_PRODUCT = 'D'                   # <-- changed from 'I' to 'D' (NRML for options)
PLACE_STOPLOSS = True
STOPLOSS_PERCENTAGE = 15.0
MAX_ORDERS_PER_DAY = 10
MIN_ORDER_GAP_SECONDS = 300
ORDER_VERIFICATION_DELAY = 3

# TEST MODE (FALSE = normal market hours)
TEST_MODE = False
BYPASS_MARKET_CHECKS = TEST_MODE      # used in is_market_open / is_market_stabilized

# When TEST_MODE=True and the bot starts before 05:30 IST, wait until the
# Upstox order window opens rather than running and generating rejected orders.
# Set False to scan immediately without waiting (signals logged, orders blocked).
WAIT_FOR_ORDER_WINDOW = True

# EXIT STRATEGY CONFIGURATION
ENABLE_EXIT_MANAGEMENT = True
MAX_DAILY_LOSS = 50000
MAX_DAILY_PROFIT = 100000
ENABLE_TRAILING_STOP = True
TRAILING_STOP_ACTIVATION = 50.0
TRAILING_STOP_PERCENTAGE = 10.0
TARGET_PROFIT_MULTIPLIER = 2.0
ENABLE_TIME_BASED_EXIT = True
ENABLE_EXPIRY_DAY_EXIT = True
EXPIRY_EXIT_TIME = "15:00"
ENABLE_STRATEGY_EXITS = True
POSITION_MONITORING_INTERVAL = 30

# GAP TRADING CONFIGURATION
ENABLE_GAP_TRADING = True
GAP_THRESHOLD_PERCENT = 1.0
GAP_FILL_THRESHOLD = 0.3
MAX_GAP_PERCENT = 5.0
GAP_ENTRY_DELAY_MINUTES = 5
GAP_TRADING_WINDOW_MINUTES = 45
GAP_POSITION_SIZE_MULTIPLIER = 1.0
GAP_MIN_VOLUME_RATIO = 1.2
GAP_FILL_EXIT_PERCENT = 80

# BOX THEORY CONFIGURATION
ENABLE_BOX_TRADING = True
BOX_CONFIRMATION_CYCLES = 2
BOX_VOLUME_THRESHOLD_MULTIPLIER = 1.0
BOX_REENTRY_EXIT_PERCENT = 0.5

# MAX ENTRY DISTANCE FILTER
# If price has already moved MORE than this % from box level when signal confirms,
# skip the trade — the move is likely exhausted (e.g. BANDHANBNK was 2%+ above box top)
MAX_ENTRY_DISTANCE_PERCENT = 1.5  # Skip CE if price > 1.5% above box top at confirmation
                                   # Skip PE if price > 1.5% below box bottom at confirmation

# RANGE TRADING CONFIGURATION
ENABLE_RANGE_TRADING = True
RANGE_BOUNCE_THRESHOLD = 0.5
BOUNCE_VOLUME_MULTIPLIER = 1.2

# KLINGER OSCILLATOR CONFIGURATION
ENABLE_KLINGER_FILTER = True
KLINGER_FAST = 34
KLINGER_SLOW = 55
KLINGER_SIGNAL = 13
KLINGER_PAPER_MODE = False
ENABLE_KLINGER_FOR_BOX = True
ENABLE_KLINGER_FOR_RANGE = True

# ============ CANDLE CACHE CONFIGURATION ============
ENABLE_CANDLE_CACHE = True
CACHE_DIRECTORY = "candle_cache"
CACHE_EXPIRY_DAYS = 7  # Re-fetch if cache older than this
MIN_CANDLES_FOR_KLINGER = 60  # Minimum candles required (reduced from 90)
ADAPTIVE_KLINGER_LOOKBACK = True  # Use shorter periods for limited data
KLINGER_FAST_SHORT = 20  # For 60-89 days of data
KLINGER_SLOW_SHORT = 34
KLINGER_SIGNAL_SHORT = 9
CACHE_UPDATE_HOUR = 18  # Update cache after market close (6 PM)
CACHE_STATS_FILE = "cache_stats.json"

# ============ FAST TRADING CONFIGURATION ============
ENABLE_FAST_TRADING = True

# ── DUAL TIMEFRAME CONFIGURATION ─────────────────────────────────────────────
# SQUEEZE (LONG) signals use 15min candles — catches real breakouts with
# sustained momentum, avoids 5min noise getting stopped out by natural range.
# PULLBACK (SHORT) signals keep 5min candles — faster reaction to intraday
# reversals at the middle band.
FAST_TRADE_TIMEFRAME          = "5min"   # Legacy label — actual TF per signal type below
FAST_TRADE_SQUEEZE_TIMEFRAME  = "15min"  # LONG squeeze signals use 15min
FAST_TRADE_PULLBACK_TIMEFRAME = "5min"   # SHORT pullback signals use 5min

# Bollinger parameters — shared base, squeeze uses 15min bars
BOLLINGER_PERIOD               = 20       # periods (20×15min = 5hrs for squeeze; 20×5min=100min for short)
BOLLINGER_STD                  = 2
# Squeeze threshold: 15min candles are wider → need higher threshold to detect real squeeze
BOLLINGER_SQUEEZE_THRESHOLD    = 0.20     # 15min squeeze threshold (was 0.15 for 5min)
BOLLINGER_SQUEEZE_THRESHOLD_5M = 0.15     # 5min threshold for pullback short detection
# Volume: 15min breakout bar should show stronger volume accumulation
MIN_BREAKOUT_VOLUME_RATIO      = 1.8      # 15min squeeze (was 1.5 for 5min)
MIN_PULLBACK_VOLUME_RATIO      = 1.2      # 5min pullback short (unchanged)

FAST_TRADE_MAX_SYMBOLS         = 20
FAST_TRADE_CAPITAL_PER_TRADE   = 10000
FAST_TRADE_RISK_PER_TRADE      = 200
FAST_TRADE_CHECK_INTERVAL      = 30       # Keep 30s scan; 15min data fetched same way

# ── SECONDARY GATE: when Klinger is REJECTED on a LONG/SHORT squeeze signal ──
# If Klinger rejects, the signal is still allowed BUT only if ALL conditions
# are met — otherwise the trade is suppressed.
#
#   RSI_MIN  : RSI(14) on the 5-min chart must be >= this for LONG (raised to 65
#              to reduce low-quality Klinger-rejected LONG entries like IDFCFIRSTB)
#              For SHORT the RSI must be <= (100 - RSI_MIN) i.e. <= 35
#   CLOUD_PCT: Price must be above the Ichimoku cloud midline by at least this %
#              (set to 0.0 to skip the cloud check — useful if no Ichimoku data)
#
#   KO DIRECTION GUARD (new):
#   - For LONG  secondary gate: KO must NOT be strongly positive (KO > 0 with large
#     magnitude means Klinger is bullish and simply hasn't crossed — allow).
#     But if KO > +KO_STRONG_POSITIVE_THRESHOLD the signal is already confirmed
#     via the main gate path so secondary gate is irrelevant.
#   - For SHORT secondary gate: KO must be NEGATIVE (< 0). If KO is positive
#     (e.g. ONGC with KO = +1.086B) a short signal must NOT pass the secondary
#     gate — KO direction contradicts the short thesis.
FAST_TRADE_KLINGER_REJECTED_RSI_MIN        = 65    # Raised from 55 → 65 for LONG (reduces false entries)
FAST_TRADE_KLINGER_REJECTED_RSI_MAX_SHORT  = 35    # For SHORT: RSI must be <= this (100 - 65)
FAST_TRADE_KLINGER_REJECTED_CLOUD_PCT      = 0.0   # % above cloud midline (0 = disabled)
ENABLE_FAST_TRADE_SECONDARY_GATE           = True  # Master switch
# SHORT secondary gate KO guard: if KO > 0, block SHORT even if RSI is oversold
FAST_TRADE_SHORT_REQUIRE_NEGATIVE_KO       = True  # KO must be < 0 for SHORT secondary gate to pass

# ── SECOND-HALF SHORT RE-WATCH ────────────────────────────────────────────────
# Stocks that fired a LONG alert in the morning session are re-watched for
# a SHORT setup after SECOND_HALF_START. This captures reversal trades on
# stocks that already showed strong intraday moves (breakout → exhaustion).
ENABLE_SECOND_HALF_SHORT_REWATCH  = True    # master switch
SECOND_HALF_START                  = "12:30" # HH:MM — market mid-point
# ─────────────────────────────────────────────────────────────────────────────

# ── EARLY TOPPING REVERSAL CONFIG ────────────────────────────────────────────
# Allows SHORT (and LONG) reversal signals BEFORE 12:30 on fresh symbols.
# Uses stricter thresholds than the afternoon re-watch to suppress noise.
# Root problem solved: detect_fast_short_setup() has a hard exit when
# price > bb_middle (line ~4413), which blocks ALL topping candles because
# they sit at the UPPER band. detect_topping_reversal() handles that zone.
ENABLE_EARLY_REVERSAL            = True   # master switch
EARLY_REVERSAL_RSI_SHORT         = 63     # RSI >= this for early SHORT (overbought)
EARLY_REVERSAL_RSI_LONG          = 37     # RSI <= this for early LONG (oversold)
EARLY_REVERSAL_VOLUME_RATIO      = 1.5    # stricter vol spike (normal = 1.2–1.3)
EARLY_REVERSAL_BODY_MAX_PCT      = 0.45   # body/range < 45% → Doji / exhaustion candle
EARLY_REVERSAL_BAND_TOL_PCT      = 0.5    # candle HIGH within 0.5% below upper band
# ─────────────────────────────────────────────────────────────────────────────

# ========== FII/DII + ORB CONFIGURATION ==========
ENABLE_FII_DII_FILTER = True
FII_DII_URL = "https://munafasutra.com/nse/FIIDII/"
FII_DII_UPDATE_INTERVAL = 86400  # Fetch once per day — FII/DII data is published once after market close
FII_DII_CACHE_FILE = "fii_dii_cache.json"

# ── FII/DII MULTI-DAY TREND ANALYSIS ─────────────────────────────────────────
# Reads historical FII_DII_YYYYMMDD.csv files to detect institutional patterns:
#   STRONG_ACCUMULATION : Both FII cash + FNO bought (most bullish)
#   FII_BUY_DII_SELL    : FII cash bought, FNO sold (FII leading — bullish lean)
#   FII_SELL_DII_BUY    : FII cash sold, FNO bought (DII support — caution)
#   UNUSUAL_CHANGE      : Reversed from previous day (both sold -> both bought etc.)
ENABLE_FII_DII_TREND_FILTER  = True   # Master switch for trend-based adjustments
FII_DII_TREND_CACHE_FILE     = "fii_dii_trend_cache.json"
# Volume threshold relief for strong-accumulation stocks (10% easier to pass)
FII_DII_TREND_VOLUME_RELIEF  = 0.90   # multiply thr by this for strong accumulation
# Confidence score adjustments (added to base score for sorting/logging)
FII_DII_SCORE_STRONG_ACC     = +2     # both bought today
FII_DII_SCORE_FII_BUY        = +1     # FII cash bought, FNO sold
FII_DII_SCORE_FII_SELL       = -1     # FII cash sold, FNO bought
FII_DII_SCORE_UNUSUAL        = +2     # sudden reversal — high conviction move

# ORB STRATEGY CONFIGURATION
ENABLE_ORB_STRATEGY = True
ORB_TIMEFRAME_MINUTES = 5  # First 5 minutes (9:15-9:20)
ORB_MIN_CANDLE_BODY_PERCENT = 0.5  # Minimum 0.5% body size
ORB_VOLUME_CONFIRMATION = 1.5  # Raised: 1.5x average volume required (was 1.2x)
ORB_BREAKOUT_WINDOW_MINUTES = 30  # Tightened: only trade within 30 min of 9:20 (was 60)
ORB_TARGET_MULTIPLIER = 2.0  # Target = 2x candle body
ORB_STOP_MULTIPLIER = 1.0  # Stop at opposite end of candle
ORB_ENABLE_RR_GATE = True   # Reject ORB signals whose risk:reward is too poor
ORB_MIN_RISK_REWARD = 1.5   # Minimum reward:risk required before any ORB entry
ORB_MIN_VOLUME = 500000  # Minimum average volume
ORB_ENABLE_MARKET_ALIGNMENT = True  # Check Nifty direction
ORB_ENABLE_FII_DII_FILTER = True  # Only trade with FII/DII alignment

# ORB QUALITY GATE — Klinger + RSI secondary filter
ORB_ENABLE_KLINGER_GATE   = True   # Require Klinger alignment for ORB signals
ORB_ENABLE_RSI_GATE       = True   # Require RSI momentum confirmation
ORB_RSI_LONG_MIN          = 52     # LONG ORB: RSI must be >= this (momentum present)
ORB_RSI_SHORT_MAX         = 48     # SHORT ORB: RSI must be <= this (momentum present)
ORB_MIN_CANDLE_BODY_LONG  = 0.6    # LONG ORB: slightly higher body % required
ORB_MIN_CANDLE_BODY_SHORT = 0.6    # SHORT ORB: slightly higher body % required
ORB_REQUIRE_STRONG_FII_FOR_MEDIUM_RSI = True  # If RSI borderline, require STRONG FII/DII

# ── ORB Reversal (contra-trade) config ──────────────────────────────────────
# When the initial ORB signal reverses strongly, bot fires an OPPOSITE trade.
# Uses detect_topping_reversal (price at upper BB + doji/wick) AND
# check_ha_reversal_alerts (HA colour flip + Klinger) as dual confirmation.
ORB_ENABLE_REVERSAL_TRADE    = True    # Master toggle for contra-ORB trades
ORB_REVERSAL_MIN_MOVE_PCT    = 0.8    # Price must have moved ≥0.8% against signal before reversal fires (raised from 0.4 to avoid whipsaws)
ORB_REVERSAL_CANDLES_MIN     = 2      # Wait at least 2 candles after ORB signal before checking reversal
ORB_REVERSAL_COOLDOWN_MINUTES = 15    # Minimum minutes after the ORB signal before a reversal may fire (anti-whipsaw)
ORB_REVERSAL_REQUIRE_OR_BREAK = True  # Require price to break the actual opening-range low/high, not just a % move
ORB_REVERSAL_REQUIRE_HA      = True   # Require HA colour flip (via check_ha_reversal_alerts) for reversal
ORB_REVERSAL_REQUIRE_TOPPING = True   # Require detect_topping_reversal confirmation for bearish→bullish flip
ORB_REVERSAL_WINDOW_MINUTES  = 90     # Fire reversal up to 90 min after original ORB signal

# ========== SESSION-PHASE ENGINE CONFIG ==========
# The trading day is split into 3 phases, each with its own strategy logic.
#
#  Phase 1 | 09:15–10:30 | MOMENTUM ORB     — pure breakout, fast confirmation
#  Phase 2 | 10:30–13:00 | MIDDAY BOX       — detect tight consolidation range,
#                                             trade the eventual breakout
#  Phase 3 | 13:00–15:15 | AFTERNOON PIVOT  — R3/S3 rejection + VWAP + RSI gate
#                                             catches European-session volatility
#
# All three phases share the same Klinger + FII/DII + exit management stack.

# ── Phase 2: Midday Box ──────────────────────────────────────────────────────
ENABLE_MIDDAY_BOX           = True
MIDDAY_BOX_BUILD_START      = "10:30"   # start tracking the box
MIDDAY_BOX_BUILD_END        = "13:00"   # box is "sealed" — breakout watch begins
MIDDAY_BOX_MIN_RANGE_PCT    = 0.25      # ignore boxes tighter than 0.25% range (noise)
MIDDAY_BOX_MAX_RANGE_PCT    = 2.5       # ignore boxes wider than 2.5% (no consolidation)
MIDDAY_BOX_BREAKOUT_BUFFER  = 0.15      # price must clear box edge by 0.15% to confirm
MIDDAY_BOX_VOLUME_MIN       = 1.4       # breakout candle volume ratio vs 20-bar avg
MIDDAY_BOX_MAX_ORDERS       = 3         # max orders from midday box per day

# ── Phase 3: Afternoon Pivot Reversal ────────────────────────────────────────
ENABLE_AFTERNOON_PIVOT      = True
AFTERNOON_SESSION_START     = "13:00"
AFTERNOON_SESSION_END       = "15:15"
AFTERNOON_R3_BAND_PCT       = 0.40      # within 0.4% of R3/S3 counts as "at level"
AFTERNOON_RSI_OVERBOUGHT    = 65        # RSI threshold for R3 short signal
AFTERNOON_RSI_OVERSOLD      = 35        # RSI threshold for S3 long signal
AFTERNOON_VWAP_CONFIRM      = True      # require VWAP crossover confirmation
AFTERNOON_REQUIRE_KLINGER   = False     # Klinger preferred but not mandatory (noon)
AFTERNOON_MAX_ORDERS        = 3         # max orders from afternoon pivot per day
AFTERNOON_RISK_REWARD_MIN   = 1.8       # minimum R:R to take the trade

# File paths for new strategies
MIDDAY_BOX_LOG_FILE         = "box_midday_alerts.csv"
AFTERNOON_PIVOT_LOG_FILE    = "afternoon_pivot_alerts.csv"


ORB_SIGNALS_FILE = "orb_signals.csv"
ORB_TRADES_FILE  = "orb_trades.csv"
ORB_LOG_FILE     = "orb_trading_log.txt"

# ========== OPENING-RANGE REVERSAL STRATEGY CONFIG ==========
# Standalone reversal detector (reversal_strategy.py): fires when price breaks
# back through the opening range against its initial bias (exhaustion move).
# Selected via the STRATEGY env var ("reversal" or "all"); see apply_strategy_selection().
ENABLE_REVERSAL_STRATEGY      = False   # toggled on by STRATEGY=all/reversal
ENABLE_REVERSAL_AUTO_TRADING  = False   # default: signal-only (no live orders)
REVERSAL_OPENING_RANGE_BARS   = 3       # first 3 x 5min bars = ~15min opening range
REVERSAL_THRESHOLD_PERCENT    = 0.5     # % of OR range price must exceed to confirm
REVERSAL_MIN_VOLUME           = 0       # per-bar volume floor (0 = disabled)
REVERSAL_MIN_BARS             = REVERSAL_OPENING_RANGE_BARS + 5  # candles before scanning
REVERSAL_MAX_SYMBOLS          = 40      # cap symbols scanned per cycle
REVERSAL_SCAN_INTERVAL_SCANS  = 4       # run reversal scan every N main-loop scans
REVERSAL_SIGNALS_FILE         = "reversal_signals.csv"

# ========== FII TREND REVERSAL SHORT (Bearish) CONFIG ==========
ENABLE_FII_REVERSAL             = True
FII_REVERSAL_MAX_SYMBOLS        = 30
FII_REVERSAL_MIN_VOLUME_RATIO   = 1.3
FII_REVERSAL_EMA_FAST           = 9
FII_REVERSAL_EMA_SLOW           = 21
FII_REVERSAL_EMA_TREND          = 50
FII_REVERSAL_STRATEGY_NAME      = "FII_REVERSAL_SHORT"
FII_REVERSAL_ALERTED_STOCKS     = set()   # fired today (short side)

# ========== FII TREND REVERSAL LONG (Bullish) CONFIG ==========
ENABLE_FII_REVERSAL_LONG            = True
FII_REVERSAL_LONG_MAX_SYMBOLS       = 30
FII_REVERSAL_LONG_MIN_VOLUME_RATIO  = 1.3
FII_REVERSAL_LONG_EMA_FAST          = 9
FII_REVERSAL_LONG_EMA_SLOW          = 21
FII_REVERSAL_LONG_EMA_TREND         = 50
FII_REVERSAL_LONG_STRATEGY_NAME     = "FII_REVERSAL_LONG"
FII_REVERSAL_LONG_ALERTED_STOCKS    = set()   # fired today (long side)

# ========== STRATEGY 1: BIG OPENING CANDLE + RESISTANCE REVERSAL ==========
# Opening candle (first 15 min) spikes near 2-week resistance → next 15-min
# red candle fails to break high → SHORT (PE). Mirror for LONG (CE).
ENABLE_RESISTANCE_REVERSAL       = True
RES_REVERSAL_LOOKBACK_DAYS       = 14       # "2-week" previous high/low
RES_REVERSAL_BODY_MIN_PCT        = 1.5      # opening candle body must be ≥ 1.5%
RES_REVERSAL_BAND_PCT            = 0.40     # "near resistance" tolerance band
RES_REVERSAL_RSI_OVERBOUGHT      = 72       # skip if RSI > 72 (deep overbought, gap risk)
RES_REVERSAL_VOLUME_MIN          = 1.5      # reversal candle must have ≥ 1.5× avg volume
RES_REVERSAL_NOISE_MIN_BODY_PCT  = 0.30     # ignore tiny candles below this body size
RES_REVERSAL_MAX_ORDERS          = 4
RES_REVERSAL_ALERTED             = set()

# ========== STRATEGY 2: DUAL-TF BOLLINGER BAND MIDDLE CROSS ==========
# Price closes above/below middle BB on BOTH 5-min AND 1-hr simultaneously.
# Extra filters: band squeeze before cross, volume spike, FII/DII alignment.
ENABLE_DUAL_TF_BB               = True
DUAL_TF_BB_PERIOD               = 20       # BB period (same as main BOLLINGER_PERIOD)
DUAL_TF_BB_SQUEEZE_LOOKBACK     = 10       # bars to check for squeeze prior to cross
DUAL_TF_BB_VOLUME_MIN           = 1.6      # volume spike on cross candle
DUAL_TF_BB_NOISE_MIN_BODY_PCT   = 0.25     # ignore tiny doji-like candles
DUAL_TF_BB_MAX_ORDERS           = 4
DUAL_TF_BB_ALERTED              = set()

# ========== STRATEGY 3: FII/DII MULTI-CONFLUENCE BREAKOUT ==========
# Three sub-modes share the same scan function, controlled per call:
#   Mode A — General universe: first 1H high (with wick) + next TF break +
#             last-1-week weekly high (without wick) + volume spike
#   Mode B — FII/DII universe: same as A but 2-week lookback + 1H BB-middle
#             cross + next 1H candle must break previous high (2-candle confirm)
#   Both require: previous candle AND new candle both close above/below level,
#                 sudden volume (≥ 2× avg), and FII/DII alignment for mode B.
ENABLE_FIIDII_BREAKOUT          = True
ENABLE_FIIDII_BREAKOUT_V2       = True   # rolling-anchor + strong-close variant
FIIDII_BRK_LOOKBACK_DAYS_GEN    = 7        # Mode A: 1-week weekly high lookback
FIIDII_BRK_LOOKBACK_DAYS_FII    = 14       # Mode B: 2-week lookback
FIIDII_BRK_VOLUME_MIN           = 1.8      # volume spike threshold
FIIDII_BRK_NOISE_MIN_BODY_PCT   = 0.35     # ignore small reversal candles
FIIDII_BRK_2CANDLE_CONFIRM      = True     # require TWO consecutive closes above level
FIIDII_BRK_MAX_ORDERS           = 5
FIIDII_BRK_ALERTED              = set()    # (symbol, mode) tuples fired today

# CSV log files for new strategies
RES_REVERSAL_CSV      = "resistance_reversal_alerts.csv"
DUAL_TF_BB_CSV        = "dual_tf_bb_alerts.csv"
FIIDII_BREAKOUT_CSV   = "fiidii_breakout_alerts.csv"

# ========== STRATEGY 4: FII/DII BB-MID CROSS + LIVE CONTINUATION ==========
# Monitors FII/DII watchlist continuously (persists across days, not reset
# daily). When a completed 1H candle crosses the BB(20) middle, "arm" that
# candle's high/low. On EVERY scan afterwards (no waiting for next candle to
# close), check live LTP against the armed level with a small buffer.
#   Armed CE: live LTP > armed_high * (1 + buffer%) → ENTRY CE immediately
#   Armed PE: live LTP < armed_low  * (1 - buffer%) → ENTRY PE immediately
# Un-arm automatically after ENABLE_FII_BB_ARM_MAX_HOURS with no break.
ENABLE_FII_BB_CONTINUATION   = True
FII_BB_ARM_BUFFER_PCT        = 0.12     # live-break buffer above/below armed level
FII_BB_ARM_MAX_HOURS         = 2        # un-arm if no break within this many hours
FII_BB_NOISE_MIN_BODY_PCT    = 0.25     # ignore tiny BB-cross candles (indecisive)
FII_BB_MAX_ORDERS            = 5
FII_BB_CSV                   = "fii_bb_continuation_alerts.csv"
# State persists across the whole run (not reset daily) — the idea is to
# watch each FII/DII stock continuously for 2-3 days as specified.
FII_BB_ARMED: dict = {}   # symbol -> {direction, armed_high/low, armed_at, ikey}
FII_BB_ALERTED_TODAY: set = set()   # one entry per symbol per day (reset daily)


OPTION_PREMIUM_MIN_THRESHOLD = 1.0  # Minimum premium to consider
OPTION_PREMIUM_MAX_THRESHOLD = 500.0  # Maximum premium to consider
OPTION_LTP_RETRY_ATTEMPTS = 5  # Number of retries for LTP fetch
OPTION_FALLBACK_PREMIUM_ENABLED = True  # Use estimated premium if LTP fails

# Entry Types
ENTRY_BREAKOUT = "BREAKOUT"
ENTRY_PULLBACK = "PULLBACK"
ENTRY_SQUEEZE = "SQUEEZE"
ENTRY_ORB_BULLISH = "ORB_BULLISH"
ENTRY_ORB_BEARISH = "ORB_BEARISH"

# Exit Types
EXIT_TARGET = "TARGET"
EXIT_STOP = "STOP"
EXIT_TRAILING = "TRAILING"
EXIT_REVERSAL = "REVERSAL"

# ── ALERTED STOCK SETS ───────────────────────────────────────────────────────
# Direction-granular sets let each strategy re-watch a stock for the OPPOSITE
# side after SECOND_HALF_START.  Legacy aliases kept so all summary/CSV/order-
# limit code that reads them continues to work unchanged.

# R3/S3 breakout
R3_ALERTED_STOCKS         = set()   # fired R3 LONG today
S3_ALERTED_STOCKS         = set()   # fired S3 SHORT today
ALERTED_STOCKS            = set()   # legacy alias (R3 ∪ S3)

# Box Theory
BOX_TOP_ALERTED_STOCKS    = set()   # fired box-top breakout (LONG) today
BOX_BOTTOM_ALERTED_STOCKS = set()   # fired box-bottom breakdown (SHORT) today
BOX_ALERTED_STOCKS        = set()   # legacy alias (top ∪ bottom)

# Range Trading
RANGE_BOUNCE_ALERTED_STOCKS = set() # fired support-bounce (LONG) today
RANGE_REJECT_ALERTED_STOCKS = set() # fired resistance-rejection (SHORT) today
RANGE_ALERTED_STOCKS        = set() # legacy alias (bounce ∪ reject)

# Gap Trading
GAP_ALERTED_STOCKS        = set()   # legacy alias (UP ∪ DOWN)
GAP_UP_ALERTED_STOCKS     = set()   # fired gap-UP (LONG/CE) today
GAP_DOWN_ALERTED_STOCKS   = set()   # fired gap-DOWN (SHORT/PE) today
# GAP_UP stocks re-watched for gap-DOWN SHORT in 2nd half; vice versa

# Fast Trading
FAST_TRADE_ALERTED_STOCKS = set()   # legacy alias (LONG ∪ SHORT)
FAST_TRADE_LONG_ALERTED   = set()   # fired LONG fast-trade today
FAST_TRADE_SHORT_ALERTED  = set()   # fired SHORT fast-trade today
# Stocks in FAST_TRADE_LONG_ALERTED are re-watched for SHORT after SECOND_HALF_START
# ─────────────────────────────────────────────────────────────────────────────
R3_LEVELS = {}
SYMBOL_TO_ISIN = {}
ISIN_TO_SYMBOL = {}
SYMBOL_TO_FO_KEY = {}  # symbol -> NSE_FO instrument_key (fallback for Upstox 5min endpoints)
VOLUME_DATA = {}
INITIALIZATION_RETRIES = 0
OPTIONS_CACHE = {}
DAILY_ORDER_COUNT = 0
GAP_ORDER_COUNT = 0
BOX_ORDER_COUNT = 0
RANGE_ORDER_COUNT = 0
FAST_TRADE_ORDER_COUNT = 0
LAST_ORDER_TIME = {}
PLACED_ORDERS = {}
GAP_LEVELS = {}

# EXIT MANAGEMENT GLOBALS
ACTIVE_POSITIONS = {}
DAILY_PNL = 0.0
CLOSED_POSITIONS = []
TRADING_STOPPED = False
POSITION_PEAK_PRICES = {}
POSITION_TRAILING_SL  = {}   # Tracks the last SL trigger_price pushed to the broker per position

# FAST TRADING GLOBALS
FAST_TRADES = {}
ACTIVE_FAST_TRADES = {}
CLOSED_FAST_TRADES = []
BOLLINGER_DATA = {}

# ============ REAL-TIME 5MIN CANDLE BUILDER GLOBALS ============
from collections import defaultdict
import logging as _logging

# ── STRUCTURED LOGGER (replaces raw print for debug-level noise) ─────────────
# Set DEBUG_MODE=True  → logger emits DEBUG+INFO; set False → INFO only.
# All existing `if DEBUG_MODE: print(...)` blocks are preserved unchanged —
# they naturally suppress when DEBUG_MODE=False.  This logger is for new code.
_logger = _logging.getLogger("upstox_bot")
_handler = _logging.StreamHandler()
_handler.setFormatter(_logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))
_logger.addHandler(_handler)
_logger.setLevel(_logging.DEBUG)   # controlled at call site via DEBUG_MODE check
# ─────────────────────────────────────────────────────────────────────────────
REALTIME_CANDLES = defaultdict(list)      # symbol -> list of completed 5min candles
CURRENT_CANDLE = {}                        # symbol -> {open, high, low, close, volume, candle_start}
CANDLE_BUILDER_LOCK = threading.Lock()

# MARGIN CHECK CACHE (avoids excessive API calls; refreshed at most once per minute)
_CACHED_AVAILABLE_MARGIN = None
_MARGIN_CACHE_TIME = None
_MARGIN_CACHE_LOCK = threading.Lock()
_MARGIN_CACHE_TTL_SECONDS = 60  # seconds

# FII/DII GLOBALS
FII_DII_DATA = {}
FII_DII_LAST_UPDATE = None
FII_DII_STRONG_BUY = set()
FII_DII_STRONG_SELL = set()
FII_DII_MIXED = set()

# ── FII/DII MULTI-DAY TREND SETS ─────────────────────────────────────────────
FII_DII_TREND_STRONG_ACCUMULATION = set()   # Both bought today
FII_DII_TREND_FII_BUY_DII_SELL    = set()   # FII cash bought, FNO sold
FII_DII_TREND_FII_SELL_DII_BUY    = set()   # FII cash sold, FNO bought
FII_DII_TREND_UNUSUAL_CHANGE      = set()   # Reversed vs previous day
FII_DII_TREND_LOCK                = threading.RLock()  # Thread safety

# ORB GLOBALS
ORB_CANDLES = {}
ORB_SIGNALS = {}
ORB_LATE_CHECKED = set()   # symbols confirmed zero-volume at 09:20; retry until volume appears
ORB_ACTIVE_TRADES = {}
ORB_ALERTED_STOCKS = set()   # fired ORB signal today
ORB_ORDER_COUNT = 0
ORB_PROCESSED_TODAY = False
ORB_REVERSAL_ALERTED = set()   # symbols that already fired a reversal trade today (one per symbol)

# Opening-range reversal strategy (reversal_strategy.py) globals
REVERSAL_ALERTED = set()       # symbols that already fired an OR-reversal signal today
REVERSAL_SIGNAL_COUNT = 0
REVERSAL_ORDER_COUNT = 0

# ── Midday Box global state ───────────────────────────────────────────────────
# keyed by symbol; each entry tracks the live consolidation range 10:30–13:00
MIDDAY_BOX_STATE: dict = {}      # symbol → {box_high, box_low, candles, sealed}
MIDDAY_BOX_ORDER_COUNT = 0
MIDDAY_BOX_ALERTED: set = set()  # symbols that already traded via midday box today

# ── Afternoon Pivot global state ──────────────────────────────────────────────
AFTERNOON_ORDER_COUNT = 0
AFTERNOON_ALERTED: set = set()   # symbols already traded via afternoon pivot today


# ── PERSISTENT HTTP SESSIONS ─────────────────────────────────────────────────
# Reusing a Session keeps the TCP/TLS connection alive across calls.
# DNS + TLS handshake costs 200-400 ms per new connection; with a persistent
# session that drops to <5 ms on subsequent calls (40-60% total latency saving).
_UPSTOX_SESSION        = None   # requests.Session for Upstox API
_UPSTOX_SESSION_TOKEN  = ""     # tracks which Bearer token the session was built for
# _CHARTINK_SESSION is created near the ChartInk fetch helpers (further below)
# ─────────────────────────────────────────────────────────────────────────────

# CACHE GLOBALS
CANDLE_CACHE = {}
CACHE_STATS = {
    'cache_hits': 0,
    'cache_misses': 0,
    'api_calls_saved': 0,
    'total_cached_symbols': 0,
    'last_updated': None
}

# ── INTRADAY CANDLE CACHE (5min + 15min) ─────────────────────────────────────
# Prevents fetching the same candles twice within a single scan cycle.
# TTL is intentionally short (one scan cycle) — intraday data changes every bar.
# Structure: { symbol: {'df': DataFrame, 'fetched_at': datetime} }
_5MIN_CACHE:         dict = {}
_15MIN_CACHE:        dict = {}
_5MIN_CACHE_TTL_S    = 28   # seconds — slightly less than 30s scan interval
_15MIN_CACHE_TTL_S   = 58   # seconds — slightly less than 60s 15min bar duration
_INTRADAY_CACHE_LOCK = threading.Lock()

# ── PARALLEL FETCH CONFIG ────────────────────────────────────────────────────
# fast trading scans 20 symbols × ~2 fetches each = 40 network calls per cycle.
# Running them in parallel (ThreadPoolExecutor) cuts wall-clock time from ~6s
# down to ~400ms (limited by the slowest single fetch).
# NOTE: aiohttp is NOT used — it requires an event loop and fails on Android
#       ARM64 (Pydroid3). ThreadPoolExecutor achieves the same parallelism
#       without any additional dependencies.
FAST_TRADE_FETCH_WORKERS = 8   # parallel candle fetch threads (keep ≤10 on phone)
# ─────────────────────────────────────────────────────────────────────────────

# ORDER REJECTION TRACKING — tracks signals that fired but couldn't place (service hours, limits etc.)
REJECTED_ORDER_SIGNALS = []   # list of {'symbol', 'strategy', 'reason', 'timestamp'}

# ENHANCED FALSE ALERT PREVENTION VARIABLES
LAST_BREAKOUT_STATE = {}
LAST_BOX_STATE = {}
LAST_BOUNCE_STATE = {}
BREACH_CONFIRMATION_CYCLES = 2
BREACH_TIME_WINDOW = 180    # Extended: 90s too short (only 3 scans), now 6 scans to confirm
PRICE_SUSTAINABILITY_PERCENT = 0.5  # 0.2% was too tight (₹0.66 on ₹330 stock = noise level)

# Option cache
OPTION_CHAIN_CACHE = {}
OPTION_CHAIN_CACHE_EXPIRY = 300  # 5 minutes in seconds

# NSE Holidays 2025
NSE_HOLIDAYS_2025 = {
    '2025-01-26', '2025-02-26', '2025-03-14', '2025-03-31',
    '2025-04-10', '2025-04-14', '2025-04-18', '2025-05-01',
    '2025-08-15', '2025-08-27', '2025-10-02', '2025-10-21',
    '2025-10-22', '2025-11-05', '2025-12-25',
}

# NSE Holidays 2026
NSE_HOLIDAYS_2026 = {
    '2026-01-26',  # Republic Day
    '2026-03-03',  # Holi
    '2026-03-25',  # Gudi Padwa
    '2026-04-02',  # Mahavir Jayanti
    '2026-04-10',  # Good Friday
    '2026-04-14',  # Dr. Ambedkar Jayanti
    '2026-05-01',  # Maharashtra Day
    '2026-08-15',  # Independence Day
    '2026-09-02',  # Ganesh Chaturthi
    '2026-10-02',  # Gandhi Jayanti
    '2026-10-19',  # Dussehra
    '2026-11-08',  # Diwali
    '2026-11-09',  # Diwali Balipratipada
    '2026-11-19',  # Gurunanak Jayanti
    '2026-12-25',  # Christmas
}

# Combine both years
NSE_HOLIDAYS = NSE_HOLIDAYS_2025 | NSE_HOLIDAYS_2026

pd.options.mode.chained_assignment = None

# ============================================================================
# CANDLE CACHE MANAGEMENT SYSTEM
# ============================================================================

# ============ 5MIN DATA FAILURE TRACKING ============
# Instruments that persistently return 400 for 5min data are blacklisted after MAX_5MIN_FAILURES
FAST_TRADE_5MIN_FAILURES = {}          # instrument_key -> failure_count
MAX_5MIN_FAILURES = 3                   # blacklist after this many consecutive failures
FAST_TRADE_5MIN_BLACKLIST = set()       # instrument_keys permanently skipped for 5min data

# ── ChartInk historical base cache ───────────────────────────────────────────
# Fetched ONCE per symbol (on first call), cached in memory.
# Real-time LTP ticks from update_realtime_candle() are merged on top,
# giving a complete dataset from the very first scan at 09:15.
_CK_HIST_CACHE: dict = {}               # symbol -> DataFrame (historical OHLCV base)
_CK_HIST_CACHE_TS: dict = {}            # symbol -> datetime when cache was populated
_CK_HIST_CACHE_LOCK = threading.Lock()
_CK_HIST_CACHE_TTL = 3600              # refresh base cache after 1 hour (new session)

# ── ChartInk lag compensation ─────────────────────────────────────────────────
# ChartInk's /oapi endpoint has a known ~5–6 minute data pipeline delay.
# It also includes the *still-forming* current bar in its response, with stale
# OHLCV.  We strip the last N bars from ChartInk and rely on the real-time
# candle builder (Upstox LTP ticks) to supply those bars instead.
#
# CK_BARS_TO_DROP = 2  covers the ~5–6 min lag:
#   bar[-1] = current open bar   → stale partial bar, always drop
#   bar[-2] = last "closed" bar  → often also delayed 1 candle, drop to be safe
# The real-time builder fills these from live LTP ticks automatically.
CK_BARS_TO_DROP  = 2    # Drop this many trailing bars from every CK response
CK_LAG_WARN_MIN  = 7    # Print a warning if last kept CK bar is older than this

# ============ THREAD LOCKS FOR SHARED GLOBALS ============
THREAD_LOCKS = {
    'FAST_TRADE_ALERTED_STOCKS': threading.RLock(),
    'R3_ALERTED_STOCKS':          threading.RLock(),
    'S3_ALERTED_STOCKS':          threading.RLock(),
    'BOX_TOP_ALERTED_STOCKS':     threading.RLock(),
    'BOX_BOTTOM_ALERTED_STOCKS':  threading.RLock(),
    'RANGE_BOUNCE_ALERTED_STOCKS':threading.RLock(),
    'RANGE_REJECT_ALERTED_STOCKS':threading.RLock(),
    'FAST_TRADE_LONG_ALERTED':   threading.RLock(),
    'FAST_TRADE_SHORT_ALERTED':  threading.RLock(),
    'GAP_UP_ALERTED_STOCKS':     threading.RLock(),
    'GAP_DOWN_ALERTED_STOCKS':   threading.RLock(),
    'ACTIVE_POSITIONS': threading.RLock(),
    'DAILY_ORDER_COUNT': threading.RLock(),
    'BOX_ORDER_COUNT': threading.RLock(),
    'RANGE_ORDER_COUNT': threading.RLock(),
    'GAP_ORDER_COUNT': threading.RLock(),
    'FAST_TRADE_ORDER_COUNT': threading.RLock(),
    'LAST_ORDER_TIME': threading.RLock(),
    'PLACED_ORDERS': threading.RLock(),
    'ACTIVE_FAST_TRADES': threading.RLock(),
    'FAST_TRADES': threading.RLock(),
    'CLOSED_FAST_TRADES': threading.RLock(),
}

# New per-symbol locks for thread safety
CACHE_LOCKS = {}
CACHE_LOCK_MASTER = threading.Lock()

def get_cache_lock(symbol):
    """Get or create a per-symbol lock"""
    with CACHE_LOCK_MASTER:
        if symbol not in CACHE_LOCKS:
            CACHE_LOCKS[symbol] = threading.Lock()
        return CACHE_LOCKS[symbol]

def init_cache_directory():
    """Initialize cache directory structure"""
    if not os.path.exists(CACHE_DIRECTORY):
        os.makedirs(CACHE_DIRECTORY)
        print(f"✅ Created cache directory: {CACHE_DIRECTORY}")
    
    # Create subdirectories for organization
    subdirs = ['daily_candles', 'klinger_data', 'metadata']
    for subdir in subdirs:
        path = os.path.join(CACHE_DIRECTORY, subdir)
        if not os.path.exists(path):
            os.makedirs(path)

def get_cache_file_path(symbol, cache_type='daily_candles'):
    """Get cache file path for a symbol"""
    safe_symbol = symbol.replace('|', '_').replace(':', '_')
    return os.path.join(CACHE_DIRECTORY, cache_type, f"{safe_symbol}.csv")

def get_cache_metadata_path(symbol):
    """Get metadata file path for cache entry"""
    safe_symbol = symbol.replace('|', '_').replace(':', '_')
    return os.path.join(CACHE_DIRECTORY, 'metadata', f"{safe_symbol}_meta.json")

def load_candle_cache(symbol, _silent=False):
    """Load cached candles for a symbol.

    Two-level lookup:
      1. In-memory dict  (CANDLE_CACHE)  — zero I/O, no stat increment
      2. Disk CSV + metadata             — increments cache_hits / cache_misses
    Pass _silent=True (used internally by get_cached_or_fetch_candles) to skip
    the debug print on an in-memory hit so we don't log it twice.
    """
    global CACHE_STATS

    if not ENABLE_CANDLE_CACHE:
        return None

    # ── Level 1: in-memory cache (no I/O, no stat bump) ──────────────────────
    if symbol in CANDLE_CACHE:
        df = CANDLE_CACHE[symbol]
        if df is not None and len(df) > 0:
            if DEBUG_MODE and not _silent:
                print(f"✅ Cache hit: {symbol} ({len(df)} candles)")
            return df

    # ── Level 2: disk cache ───────────────────────────────────────────────────
    cache_file = get_cache_file_path(symbol)
    meta_file  = get_cache_metadata_path(symbol)

    if not os.path.exists(cache_file):
        CACHE_STATS['cache_misses'] += 1
        return None

    try:
        if os.path.exists(meta_file):
            with open(meta_file, 'r') as f:
                metadata = json.load(f)
            last_update = datetime.fromisoformat(metadata['last_updated'])
            days_old = (now_ist() - last_update).days
            if days_old > CACHE_EXPIRY_DAYS:
                if DEBUG_MODE:
                    print(f"⚠️ Cache expired for {symbol} ({days_old} days old)")
                CACHE_STATS['cache_misses'] += 1
                return None

        df = pd.read_csv(cache_file)
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date').reset_index(drop=True)

        if len(df) > 0:
            CACHE_STATS['cache_hits'] += 1
            # Keep only last 200 candles in RAM — enough for all indicators
            if len(df) > 200:
                df = df.tail(200).reset_index(drop=True)
            CANDLE_CACHE[symbol] = df          # ← populate in-memory layer
            if DEBUG_MODE and not _silent:
                print(f"✅ Cache hit: {symbol} ({len(df)} candles)")
            return df
        else:
            CACHE_STATS['cache_misses'] += 1
            return None

    except Exception as e:
        if DEBUG_MODE:
            print(f"⚠️ Cache load error for {symbol}: {e}")
        CACHE_STATS['cache_misses'] += 1
        return None

def save_candle_cache(symbol, df, instrument_key=None):
    """Save candles to disk cache and refresh in-memory layer"""
    global CACHE_STATS
    
    if not ENABLE_CANDLE_CACHE or df is None or len(df) == 0:
        return False
    
    try:
        cache_file = get_cache_file_path(symbol)
        meta_file = get_cache_metadata_path(symbol)
        
        # Save candles
        df.to_csv(cache_file, index=False)
        
        # Save metadata
        metadata = {
            'symbol': symbol,
            'instrument_key': instrument_key,
            'last_updated': now_ist().isoformat(),
            'candle_count': len(df),
            'date_range': {
                'start': df['date'].min().isoformat(),
                'end': df['date'].max().isoformat()
            }
        }
        
        with open(meta_file, 'w') as f:
            json.dump(metadata, f, indent=2)

        # ── Keep in-memory layer in sync ────────────────────────────────────
        # Trim to last 200 candles — enough for any indicator; saves 50-80% RAM
        if len(df) > 200:
            df = df.tail(200).copy()
        CANDLE_CACHE[symbol] = df.copy()
        
        if DEBUG_MODE:
            print(f"💾 Cached {len(df)} candles for {symbol}")
        
        return True
        
    except Exception as e:
        if DEBUG_MODE:
            print(f"⚠️ Cache save error for {symbol}: {e}")
        return False

def update_candle_cache_incremental(access_token, symbol, instrument_key):
    """Incrementally update cache with only new candles"""
    global CACHE_STATS
    
    # Load existing cache — _silent=True avoids a second "Cache hit" log line
    # when this is called from get_cached_or_fetch_candles after an in-memory hit.
    cached_df = load_candle_cache(symbol, _silent=True)
    
    if cached_df is None or len(cached_df) == 0:
        # No cache - fetch full history
        return fetch_and_cache_full_history(access_token, symbol, instrument_key)
    
    # Get last cached date
    last_cached_date = cached_df['date'].max()
    today = now_ist().date()
    
    # Check if we need to update
    if last_cached_date.date() >= today:
        if DEBUG_MODE:
            print(f"✅ Cache up-to-date for {symbol}")
        return cached_df
    
    # Fetch only new candles
    from_date = last_cached_date + timedelta(days=1)
    to_date = today
    
    if (to_date - from_date.date()).days < 1:
        return cached_df  # No new data needed
    
    try:
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}"
        }
        
        from_str = from_date.strftime('%Y-%m-%d')
        to_str = to_date.strftime('%Y-%m-%d')
        
        url = f"https://api.upstox.com/v2/historical-candle/{instrument_key}/day/{to_str}/{from_str}"
        
        resp = _get_upstox_session(access_token).get(url, timeout=15)
        
        if resp.status_code == 200:
            data = resp.json()
            new_candles = data.get("data", {}).get("candles", [])
            
            if new_candles:
                # Convert to DataFrame
                new_df = pd.DataFrame(new_candles, columns=['date', 'open', 'high', 'low', 'close', 'volume', 'oi'])
                new_df['date'] = pd.to_datetime(new_df['date'])
                
                # Merge with existing cache
                merged_df = pd.concat([cached_df, new_df], ignore_index=True)
                merged_df = merged_df.drop_duplicates(subset=['date'], keep='last')
                merged_df = merged_df.sort_values('date').reset_index(drop=True)
                
                # Save updated cache
                save_candle_cache(symbol, merged_df, instrument_key)
                
                CACHE_STATS['api_calls_saved'] += 1
                
                if DEBUG_MODE:
                    print(f"📈 Updated cache for {symbol}: +{len(new_candles)} candles")
                
                return merged_df
            else:
                return cached_df
        else:
            if DEBUG_MODE:
                print(f"⚠️ API error updating {symbol}: {resp.status_code}")
            return cached_df
            
    except Exception as e:
        if DEBUG_MODE:
            print(f"⚠️ Incremental update error for {symbol}: {e}")
        return cached_df

def fetch_and_cache_full_history(access_token, symbol, instrument_key, days=120):
    """Fetch full candle history and cache it"""
    global CACHE_STATS
    
    end_date = now_ist().date()
    start_date = end_date - timedelta(days=days)
    
    from_date_str = start_date.strftime('%Y-%m-%d')
    to_date_str = end_date.strftime('%Y-%m-%d')
    
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {access_token}"
    }
    
    url = f"https://api.upstox.com/v2/historical-candle/{instrument_key}/day/{to_date_str}/{from_date_str}"
    
    try:
        resp = _get_upstox_session(access_token).get(url, timeout=15)
        
        if resp.status_code == 200:
            data = resp.json()
            candles = data.get("data", {}).get("candles", [])
            
            if candles:
                df = pd.DataFrame(candles, columns=['date', 'open', 'high', 'low', 'close', 'volume', 'oi'])
                df['date'] = pd.to_datetime(df['date'])
                df = df.sort_values('date').reset_index(drop=True)
                
                # Save to cache
                save_candle_cache(symbol, df, instrument_key)
                
                if DEBUG_MODE:
                    print(f"📥 Fetched and cached {len(df)} candles for {symbol}")
                
                return df
            else:
                return None
        else:
            if DEBUG_MODE:
                print(f"⚠️ API error for {symbol}: {resp.status_code}")
            return None
            
    except Exception as e:
        if DEBUG_MODE:
            print(f"⚠️ Fetch error for {symbol}: {e}")
        return None

def get_cached_or_fetch_candles(access_token, symbol, instrument_key):
    """Get candles from in-memory cache, disk cache, or fetch from API if needed.

    Priority:
      1. In-memory CANDLE_CACHE  — instant, no I/O
      2. Disk CSV cache          — fast, incremental update if stale
      3. Full API fetch          — only when no cache exists at all
    """
    # ── Level 1: in-memory hit (skip disk entirely) ───────────────────────────
    if symbol in CANDLE_CACHE:
        df = CANDLE_CACHE[symbol]
        if df is not None and len(df) >= MIN_CANDLES_FOR_KLINGER:
            last_date = df['date'].max().date()
            today = now_ist().date()
            if last_date >= today:
                return df          # fully up-to-date, no I/O needed
            # Stale — do incremental update; update_candle_cache_incremental
            # internally calls load_candle_cache(_silent=True) which returns the
            # in-memory copy without re-reading disk or bumping stats again.
            return update_candle_cache_incremental(access_token, symbol, instrument_key)

    # ── Level 2/3: disk cache or full fetch ───────────────────────────────────
    cached_df = load_candle_cache(symbol)          # logs hit/miss once here

    if cached_df is not None and len(cached_df) >= MIN_CANDLES_FOR_KLINGER:
        last_date = cached_df['date'].max().date()
        today = now_ist().date()
        if last_date < today:
            return update_candle_cache_incremental(access_token, symbol, instrument_key)
        return cached_df
    else:
        return fetch_and_cache_full_history(access_token, symbol, instrument_key)

def calculate_klinger_adaptive(df, symbol=None):
    """Calculate Klinger with adaptive parameters based on data availability"""
    
    if df is None or len(df) < MIN_CANDLES_FOR_KLINGER:
        if DEBUG_MODE and symbol:
            print(f"⚠️ {symbol}: Insufficient data for Klinger ({len(df) if df is not None else 0} candles)")
        return None, None, None

    # Trim to last 200 candles — more than enough for any EMA window;
    # avoids re-processing the entire history on every scan.
    if len(df) > 200:
        df = df.tail(200).reset_index(drop=True)
    
    # Determine which parameters to use
    if ADAPTIVE_KLINGER_LOOKBACK and len(df) < 90:
        # Use shorter parameters for limited data
        fast = KLINGER_FAST_SHORT
        slow = KLINGER_SLOW_SHORT
        signal = KLINGER_SIGNAL_SHORT
        if DEBUG_MODE and symbol:
            print(f"📊 {symbol}: Using adaptive Klinger (fast={fast}, slow={slow}, {len(df)} candles)")
    else:
        # Use standard parameters
        fast = KLINGER_FAST
        slow = KLINGER_SLOW
        signal = KLINGER_SIGNAL
    
    try:
        if len(df) < max(fast, slow, signal) + 10:
            if DEBUG_MODE and symbol:
                print(f"⚠️ {symbol}: Still insufficient data ({len(df)} < {max(fast, slow, signal) + 10})")
            return None, None, None
        
        # Calculate HLC average
        hlc = (df['high'] + df['low'] + df['close']) / 3
        hlc_prev = hlc.shift(1)
        
        # Trend: +1 if up, -1 if down
        trend = ((hlc > hlc_prev).astype(int) * 2 - 1).fillna(0)
        
        # Daily measurement (high - low)
        dm = df['high'] - df['low']
        dm = dm.replace(0, 0.001)  # Avoid division by zero
        
        # Cumulative measurement
        cm = (dm * trend).cumsum()
        cm = cm.replace(0, 0.001).fillna(0.001)  # Avoid division by zero (replace + fillna)
        
        # Volume Force
        volume_force = df['volume'] * trend * (dm / cm) * 100
        # Clip before replacing inf/nan — prevents EWM from inheriting astronomically
        # large values that produce Klinger readings like 1.49e19 (PATANJALI, INDHOTEL etc.)
        volume_force = volume_force.clip(-1e12, 1e12)
        volume_force = volume_force.replace([float('inf'), float('-inf')], 0).fillna(0)
        
        # Apply EMAs to Volume Force
        vf_fast = volume_force.ewm(span=fast, adjust=False).mean()
        vf_slow = volume_force.ewm(span=slow, adjust=False).mean()
        
        # Klinger Oscillator line (clipped to sane range)
        klinger = (vf_fast - vf_slow).clip(-1e12, 1e12)
        
        # Signal line (EMA of Klinger)
        signal_line = klinger.ewm(span=signal, adjust=False).mean()
        
        # Histogram (difference)
        histogram = klinger - signal_line
        
        return klinger, signal_line, histogram
        
    except Exception as e:
        if DEBUG_MODE and symbol:
            print(f"❌ {symbol}: Klinger calculation error: {e}")
        return None, None, None

def fetch_klinger_data_cached(access_token, instrument_key, symbol):
    """Fetch Klinger data using cache system.

    Uses get_cached_or_fetch_candles() which checks the in-memory CANDLE_CACHE
    dict first — so background Klinger refreshes (every 5 scans) do NOT cause
    additional disk reads or bump cache_hits a second time for already-loaded symbols.
    """
    global CACHE_STATS
    
    if not ENABLE_KLINGER_FILTER:
        return None
    
    # get_cached_or_fetch_candles checks in-memory layer first (no I/O, no stat bump)
    df = get_cached_or_fetch_candles(access_token, symbol, instrument_key)
    
    if df is None or len(df) < MIN_CANDLES_FOR_KLINGER:
        candle_count = len(df) if df is not None else 0
        # Always print this — it explains why Klinger shows 0 stocks initialized
        print(f"⚠️ {symbol}: Insufficient candles for Klinger ({candle_count}/{MIN_CANDLES_FOR_KLINGER}) — CE/PE trades blocked for this stock")
        return None
    
    # Calculate Klinger with adaptive parameters
    klinger, signal_line, histogram = calculate_klinger_adaptive(df, symbol)
    
    if klinger is None or len(klinger) < 2:
        if DEBUG_MODE:
            print(f"⚠️ {symbol}: Klinger calculation failed")
        return None
    
    # Return last values for cross detection + history for soft confirmation
    # ko_history: last 5 KO values (oldest first) used for ONGC-type soft confirmation
    ko_history_len = min(5, len(klinger))
    ko_history = [float(klinger.iloc[-(ko_history_len - i)]) for i in range(ko_history_len - 1, -1, -1)]

    return {
        'klinger': float(klinger.iloc[-1]),
        'signal': float(signal_line.iloc[-1]),
        'histogram': float(histogram.iloc[-1]),
        'klinger_prev': float(klinger.iloc[-2]) if len(klinger) > 1 else float(klinger.iloc[-1]),
        'signal_prev': float(signal_line.iloc[-2]) if len(signal_line) > 1 else float(signal_line.iloc[-1]),
        'ko_history': ko_history,
        'last_update': now_ist(),
        'candle_count': len(df),
        'adaptive_params': len(df) < 90 if ADAPTIVE_KLINGER_LOOKBACK else False
    }

def cleanup_old_cache():
    """Remove cache files older than expiry period"""
    if not ENABLE_CANDLE_CACHE:
        return
    
    try:
        cleaned_count = 0
        expiry_date = now_ist() - timedelta(days=CACHE_EXPIRY_DAYS * 2)
        
        # Clean daily candles
        candle_dir = os.path.join(CACHE_DIRECTORY, 'daily_candles')
        if os.path.exists(candle_dir):
            for filename in os.listdir(candle_dir):
                filepath = os.path.join(candle_dir, filename)
                file_mtime = datetime.fromtimestamp(os.path.getmtime(filepath), tz=_IST).replace(tzinfo=None)
                
                if file_mtime < expiry_date:
                    os.remove(filepath)
                    cleaned_count += 1
        
        # Clean metadata
        meta_dir = os.path.join(CACHE_DIRECTORY, 'metadata')
        if os.path.exists(meta_dir):
            for filename in os.listdir(meta_dir):
                filepath = os.path.join(meta_dir, filename)
                file_mtime = datetime.fromtimestamp(os.path.getmtime(filepath), tz=_IST).replace(tzinfo=None)
                
                if file_mtime < expiry_date:
                    os.remove(filepath)
                    cleaned_count += 1
        
        if cleaned_count > 0:
            print(f"🧹 Cleaned {cleaned_count} old cache files")
            
    except Exception as e:
        if DEBUG_MODE:
            print(f"⚠️ Cache cleanup error: {e}")

def save_cache_stats():
    """Save cache statistics to file"""
    try:
        CACHE_STATS['last_updated'] = now_ist().isoformat()
        CACHE_STATS['total_cached_symbols'] = len([f for f in os.listdir(os.path.join(CACHE_DIRECTORY, 'daily_candles')) if f.endswith('.csv')])
        
        stats_file = os.path.join(CACHE_DIRECTORY, CACHE_STATS_FILE)
        with open(stats_file, 'w') as f:
            json.dump(CACHE_STATS, f, indent=2)
            
    except Exception as e:
        if DEBUG_MODE:
            print(f"⚠️ Error saving cache stats: {e}")

def load_cache_stats():
    """Load cache statistics from file"""
    global CACHE_STATS
    
    try:
        stats_file = os.path.join(CACHE_DIRECTORY, CACHE_STATS_FILE)
        if os.path.exists(stats_file):
            with open(stats_file, 'r') as f:
                loaded_stats = json.load(f)
                CACHE_STATS.update(loaded_stats)
                
    except Exception as e:
        if DEBUG_MODE:
            print(f"⚠️ Error loading cache stats: {e}")

def print_cache_statistics():
    """Print cache performance statistics"""
    if not ENABLE_CANDLE_CACHE:
        return
    
    total_requests = CACHE_STATS['cache_hits'] + CACHE_STATS['cache_misses']
    hit_rate = (CACHE_STATS['cache_hits'] / total_requests * 100) if total_requests > 0 else 0
    mem_symbols = len([s for s, df in CANDLE_CACHE.items() if df is not None and len(df) > 0])
    
    print(f"\n{'='*100}")
    print("💾 CACHE PERFORMANCE STATISTICS")
    print(f"{'='*100}")
    print(f"Cache Hits (disk reads):  {CACHE_STATS['cache_hits']}  ← unique symbols loaded from disk")
    print(f"Cache Misses:             {CACHE_STATS['cache_misses']}  ← symbols fetched fresh from API")
    print(f"Hit Rate:                 {hit_rate:.1f}%")
    print(f"In-Memory Symbols:        {mem_symbols}  ← serving from RAM (no disk I/O)")
    print(f"API Calls Saved:          {CACHE_STATS['api_calls_saved']}")
    print(f"Cached Symbols (disk):    {CACHE_STATS['total_cached_symbols']}")
    print(f"Cache Directory:          {CACHE_DIRECTORY}")
    print(f"{'='*100}\n")

# ============================================================================
# ORIGINAL FUNCTIONS - UPDATED TO USE CACHE
# ============================================================================

# Replace the original calculate_klinger with the adaptive version
def calculate_klinger(df, fast=34, slow=55, signal=13):
    """
    DEPRECATED: Use calculate_klinger_adaptive instead
    This is kept for backward compatibility
    """
    return calculate_klinger_adaptive(df)

# Replace the original fetch_klinger_data with cached version
def fetch_klinger_data(access_token, instrument_key, days=90):
    """
    Fetch Klinger data using cache (backward compatible wrapper)
    """
    # Extract symbol from instrument_key
    symbol = instrument_key.split('|')[-1] if '|' in instrument_key else instrument_key.split(':')[-1]
    return fetch_klinger_data_cached(access_token, instrument_key, symbol)

# ============ UPSTOX TOKEN GENERATION CLASS ============
class UpstoxLogin:
    # ... (unchanged from original both4) ...
    def __init__(self, mobile_number: str,
                 email_address: str,
                 email_password: str,
                 passcode: str = None,
                 cookies_file: str = "upstox_cookies.pkl",
                 login_url: str = "https://login.upstox.com",
                 target_url: str = "https://account.upstox.com/developer/apps",
                 max_retries: int = 3):
        self.mobile_number = mobile_number
        self.email_address = email_address
        self.email_password = email_password
        self.passcode = passcode
        self.login_url = login_url
        self.target_url = target_url
        self.cookies_file = cookies_file
        self.driver = None
        self.max_retries = max_retries

    # ... (rest of the class remains unchanged) ...
    # For brevity, the class is exactly as in the original both4.
    # Please keep all methods unchanged.
    def check_token_timestamp(self) -> bool:
        try:
            if not os.path.exists(TOKEN_TIMESTAMP_FILE):
                print("ℹ️ No token timestamp found")
                return False
            with open(TOKEN_TIMESTAMP_FILE, 'r') as f:
                data = json.load(f)
                token_timestamp = datetime.fromisoformat(data['timestamp'])
                token_date = token_timestamp.date()
            now = now_ist()
            today = now.date()
            cutoff_time = datetime.combine(today, datetime.strptime("09:00", "%H:%M").time())
            print(f"📅 Token generated on: {token_timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"📅 Today's date: {today}")
            print(f"⏰ Current time: {now.strftime('%H:%M:%S')}")
            print(f"⏰ Cutoff time: 09:00 AM")
            if token_date == today and token_timestamp < cutoff_time:
                print("✅ Token already generated today before 9:00 AM")
                print("✅ No need to regenerate - exiting script")
                return True
            elif token_date == today and token_timestamp >= cutoff_time:
                print("⚠️ Token generated today after 9:00 AM - will regenerate")
                return False
            else:
                print("⚠️ Token is from a previous date - will regenerate")
                return False
        except Exception as e:
            print(f"⚠️ Error reading token timestamp: {e}")
            return False

    def save_token_timestamp(self, token: str):
        try:
            data = {
                'timestamp': now_ist().isoformat(),
                'token': token,
                'date': now_ist().strftime('%Y-%m-%d'),
                'time': now_ist().strftime('%H:%M:%S')
            }
            with open(TOKEN_TIMESTAMP_FILE, 'w') as f:
                json.dump(data, f, indent=2)
            with open(UPSTOX_TOKEN_FILE, 'w') as f:
                f.write(token)
            print(f"✅ Token timestamp saved: {data['date']} {data['time']}")
            print(f"📁 Token saved to: {UPSTOX_TOKEN_FILE}")
        except Exception as e:
            print(f"⚠️ Error saving token timestamp: {e}")

    def setup_driver(self, headless: bool = False):
        chrome_options = webdriver.ChromeOptions()
        if headless:
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=1280,800")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        self.driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=chrome_options
        )
        self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

    # ── HEADLESS OAUTH FLOW ───────────────────────────────────────────────────
    def perform_oauth_headless(self) -> str:
        """
        Fully automated headless Selenium OAuth flow.

        Spins up a local HTTP server on HEADLESS_SERVER_PORT to capture the
        redirect code, then drives Chrome headlessly through:
          mobile number → OTP (via email) → PIN → consent → token exchange.

        No manual browser interaction needed — works on servers, GitHub Actions,
        and headless Linux/Windows environments.

        Returns the access_token string, or None on failure.
        """
        import urllib.parse as _urlparse

        # ── 1. Local redirect-capture server ─────────────────────────────────
        _captured_code = [None]
        _server_ready  = threading.Event()

        class _CodeHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                parsed = urlparse(self.path)
                code   = parse_qs(parsed.query).get("code", [None])[0]
                if code:
                    _captured_code[0] = code
                    self.send_response(200)
                    self.send_header("Content-type", "text/html")
                    self.end_headers()
                    self.wfile.write(b"<h1>Auth successful - you may close this tab.</h1>")
                    threading.Thread(target=lambda: (time.sleep(1), self.server.shutdown()), daemon=True).start()
                else:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b"Missing code")
            def log_message(self, *_):
                pass

        def _run_server():
            try:
                srv = HTTPServer(("127.0.0.1", HEADLESS_SERVER_PORT), _CodeHandler)
                _server_ready.set()
                print(f"✅ Headless redirect server on http://127.0.0.1:{HEADLESS_SERVER_PORT}")
                srv.serve_forever()
            except OSError as exc:
                print(f"❌ Cannot bind port {HEADLESS_SERVER_PORT}: {exc}")
                _server_ready.set()

        threading.Thread(target=_run_server, daemon=True).start()
        if not _server_ready.wait(timeout=5):
            print("❌ Redirect server failed to start.")
            return None

        # ── 2. Headless Chrome login ──────────────────────────────────────────
        print("\n🤖 HEADLESS OAUTH LOGIN")
        self.setup_driver(headless=True)
        try:
            auth_url = (
                "https://api.upstox.com/v2/login/authorization/dialog"
                f"?response_type=code"
                f"&client_id={UPSTOX_API_KEY}"
                f"&redirect_uri={_urlparse.quote(UPSTOX_REDIRECT_URI, safe='')}"
            )
            print("🌐 Opening login page (headless)…")
            self.driver.get(auth_url)
            time.sleep(2)

            # Clear old emails before requesting OTP
            self.delete_all_upstox_emails()

            # Mobile number
            mobile_input = WebDriverWait(self.driver, 10).until(
                EC.visibility_of_element_located((By.ID, "mobileNum"))
            )
            mobile_input.clear()
            mobile_input.send_keys(self.mobile_number)

            # Click "Get OTP"
            get_otp_btn = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Get OTP')]"))
            )
            otp_request_time = now_ist()
            get_otp_btn.click()
            print("📨 OTP requested.")

            # Fetch OTP from email (reuses existing method)
            otp = self.get_latest_otp_by_uid(max_wait=120, otp_request_time=otp_request_time)
            if not otp:
                print("❌ OTP not retrieved.")
                return None

            # Enter OTP
            otp_input = WebDriverWait(self.driver, 10).until(
                EC.visibility_of_element_located((By.ID, "otpNum"))
            )
            for digit in str(otp):
                otp_input.send_keys(digit)
                time.sleep(0.1)

            # Continue / Verify
            continue_btn = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable(
                    (By.XPATH, "//button[contains(text(), 'Continue') or contains(text(), 'Verify')]")
                )
            )
            continue_btn.click()
            print("✅ OTP submitted.")
            time.sleep(3)

            # PIN (optional — skipped gracefully if not present)
            if self.passcode:
                try:
                    pin_input = WebDriverWait(self.driver, 8).until(
                        EC.visibility_of_element_located((By.ID, "pinCode"))
                    )
                    pin_input.clear()
                    pin_input.send_keys(self.passcode)
                    try:
                        pin_continue = WebDriverWait(self.driver, 5).until(
                            EC.element_to_be_clickable((By.ID, "pinContinueBtn"))
                        )
                        pin_continue.click()
                    except Exception:
                        # Fall back to generic submit
                        for sel in [(By.XPATH, "//button[@type='submit']"),
                                    (By.XPATH, "//button[contains(text(), 'Continue')]")]:
                            try:
                                WebDriverWait(self.driver, 3).until(
                                    EC.element_to_be_clickable(sel)
                                ).click()
                                break
                            except Exception:
                                continue
                    print("✅ PIN submitted.")
                    time.sleep(3)
                except Exception as e:
                    print(f"ℹ️ PIN step skipped: {e}")

            # Consent / Allow button (some Upstox flows show this)
            try:
                allow_btn = WebDriverWait(self.driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Allow')]"))
                )
                allow_btn.click()
                print("✅ Consent granted.")
                time.sleep(2)
            except Exception:
                pass  # Not always shown

            # ── 3. Wait for redirect and capture auth code ────────────────────
            print("⏳ Waiting for OAuth redirect…")
            deadline = time.time() + 30
            while time.time() < deadline:
                cur = self.driver.current_url
                if "127.0.0.1" in cur:
                    parsed = urlparse(cur)
                    code   = parse_qs(parsed.query).get("code", [None])[0]
                    if code:
                        _captured_code[0] = code
                        print("✅ Auth code captured from browser URL.")
                        break
                if _captured_code[0]:
                    break
                time.sleep(1)

            if not _captured_code[0]:
                print("❌ No auth code received after 30 s.")
                return None

        except Exception as exc:
            print(f"❌ Headless login error: {exc}")
            return None
        finally:
            self.close()

        # ── 4. Exchange code for access token ─────────────────────────────────
        print("🔄 Exchanging auth code for access token…")
        try:
            resp = requests.post(
                "https://api.upstox.com/v2/login/authorization/token",
                headers={"accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "code":          _captured_code[0],
                    "client_id":     UPSTOX_API_KEY,
                    "client_secret": UPSTOX_API_SECRET,
                    "redirect_uri":  UPSTOX_REDIRECT_URI,
                    "grant_type":    "authorization_code",
                },
                timeout=20,
            )
            if resp.status_code != 200:
                print(f"❌ Token exchange failed ({resp.status_code}): {resp.text[:200]}")
                return None
            data          = resp.json()
            access_token  = data.get("access_token")
            refresh_token = data.get("refresh_token", "")
            if not access_token:
                print(f"❌ No access_token in response: {resp.text[:200]}")
                return None

            # Save refresh token for future runs
            try:
                with open(UPSTOX_REFRESH_TOKEN_FILE, "w") as rf:
                    rf.write(refresh_token)
                print(f"💾 Refresh token saved to {UPSTOX_REFRESH_TOKEN_FILE}")
            except Exception:
                pass

            print("✅ Headless OAuth complete!")
            return access_token
        except Exception as exc:
            print(f"❌ Token exchange error: {exc}")
            return None
    # ── END HEADLESS OAUTH FLOW ───────────────────────────────────────────────

    def load_cookies(self) -> bool:
        if not os.path.exists(self.cookies_file):
            return False
        try:
            self.driver.get(self.login_url)
            time.sleep(2)
            cookies = pickle.load(open(self.cookies_file, "rb"))
            for c in cookies:
                self.driver.add_cookie(c)
            print("✅ Cookies loaded")
            return True
        except Exception as e:
            print(f"⚠️ Failed to load cookies: {e}")
            return False

    def save_cookies(self):
        try:
            pickle.dump(self.driver.get_cookies(), open(self.cookies_file, "wb"))
            print("✅ Cookies saved")
        except Exception as e:
            print(f"⚠️ Failed to save cookies: {e}")

    def delete_all_upstox_emails(self):
        try:
            with imaplib.IMAP4_SSL("imap.gmail.com") as mail:
                mail.login(self.email_address, self.email_password)
                mail.select("inbox")
                search_patterns = [
                    'FROM "donotreply@transactions.upstox.com"',
                    'FROM "upstox"'
                ]
                deleted_count = 0
                for pattern in search_patterns:
                    try:
                        status, messages = mail.search(None, pattern)
                        if status == "OK" and messages[0]:
                            email_ids = messages[0].split()
                            for email_id in email_ids:
                                mail.store(email_id, '+FLAGS', '\\Deleted')
                                deleted_count += 1
                            mail.expunge()
                    except:
                        pass
                print(f"✅ Deleted {deleted_count} Upstox emails from inbox")
        except Exception as e:
            print(f"⚠️ Error deleting emails: {e}")

    def get_latest_otp_by_uid(self, max_wait: int = 90, otp_request_time: datetime = None) -> str:
        try:
            if otp_request_time is None:
                otp_request_time = now_ist()
            print(f"⏳ Waiting for NEW OTP email (checking every 3 seconds, max {max_wait}s)...")
            print(f"🕐 OTP requested at: {otp_request_time.strftime('%H:%M:%S')}")
            start_time = time.time()
            check_interval = 3
            print("⏱️ Waiting 8 seconds for email to arrive...")
            time.sleep(8)
            while time.time() - start_time < max_wait:
                try:
                    with imaplib.IMAP4_SSL("imap.gmail.com") as mail:
                        mail.login(self.email_address, self.email_password)
                        mail.select("inbox")
                        status, messages = mail.search(None, '(UNSEEN FROM "donotreply@transactions.upstox.com")')
                        if status != "OK" or not messages[0]:
                            # Fallback: Upstox sometimes sends from a different subdomain
                            status, messages = mail.search(None, '(UNSEEN FROM "upstox")')
                        if status != "OK" or not messages[0]:
                            elapsed = int(time.time() - start_time)
                            print(f"⏳ No unread Upstox emails yet... ({elapsed}s)")
                            time.sleep(check_interval)
                            continue
                        email_ids = messages[0].split()
                        print(f"📬 Found {len(email_ids)} unread email(s) from Upstox")
                        for email_id in reversed(email_ids):
                            try:
                                status, msg_data = mail.fetch(email_id, "(RFC822 INTERNALDATE)")
                                if status != "OK":
                                    continue
                                internaldate_pattern = rb'INTERNALDATE "([^"]+)"'
                                internaldate_match = re.search(internaldate_pattern, msg_data[0][0])
                                if internaldate_match:
                                    internaldate_str = internaldate_match.group(1).decode()
                                    try:
                                        email_received_time = datetime.strptime(internaldate_str, "%d-%b-%Y %H:%M:%S %z")
                                        email_received_time = email_received_time.replace(tzinfo=None)
                                        time_diff = (email_received_time - otp_request_time).total_seconds()
                                        if time_diff < -5:
                                            print(f"⏭️ Skipping old email (received {abs(int(time_diff))}s BEFORE request)")
                                            continue
                                        else:
                                            print(f"✅ Found FRESH email (received {int(time_diff) if time_diff > 0 else 0}s after request)")
                                    except Exception as e:
                                        print(f"⚠️ Could not parse INTERNALDATE: {e}")
                                        continue
                                msg = email.message_from_bytes(msg_data[0][1])
                                sender = msg.get("From", "")
                                subject = msg.get("Subject", "")
                                body = ""
                                if msg.is_multipart():
                                    for part in msg.walk():
                                        if part.get_content_type() == "text/plain":
                                            body = part.get_payload(decode=True).decode("utf-8", errors="replace")
                                            break
                                        elif part.get_content_type() == "text/html":
                                            body = part.get_payload(decode=True).decode("utf-8", errors="replace")
                                else:
                                    body = msg.get_payload(decode=True).decode("utf-8", errors="replace")
                                body = body.replace("\r", " ").replace("\n", " ").replace("\t", " ")
                                print(f"📄 Email body preview: {body[:200]}...")
                                otp_patterns = [
                                    r'OTP\s*(?:is)?\s*[:=]?\s*(\d{6})',
                                    r'one.?time.?password\s*(?:is)?\s*[:=]?\s*(\d{6})',
                                    r'verification.?code\s*(?:is)?\s*[:=]?\s*(\d{6})',
                                    r'code\s*(?:is)?\s*[:=]?\s*(\d{6})',
                                    r'(?:<b>|>)\s*(\d{6})\s*(?:</b>|<)',
                                    r'\b(\d{6})\b(?!.*\d{7,})',
                                ]
                                found_otp = None
                                for pattern in otp_patterns:
                                    otp_match = re.search(pattern, body, re.IGNORECASE)
                                    if otp_match:
                                        found_otp = otp_match.group(1)
                                        print(f"🎯 Pattern '{pattern}' matched OTP: {found_otp}")
                                        break
                                if not found_otp:
                                    all_numbers = re.findall(r'\b\d{6}\b', body)
                                    print(f"🔍 Found {len(all_numbers)} potential 6-digit numbers in email")
                                    for num in all_numbers:
                                        if len(num) == 6:
                                            context_start = max(body.find(num) - 20, 0)
                                            context_end = min(body.find(num) + 26, len(body))
                                            context = body[context_start:context_end].lower()
                                            otp_keywords = ['otp', 'one time password', 'verification code', 'code', 'password']
                                            if any(keyword in context for keyword in otp_keywords):
                                                found_otp = num
                                                print(f"🎯 Found OTP by context: {found_otp}")
                                                break
                                            elif context_start == 0:
                                                found_otp = num
                                                print(f"🎯 Found OTP at beginning: {found_otp}")
                                                break
                                if found_otp:
                                    print(f"\n✅ OTP EXTRACTED: {found_otp}")
                                    print(f"   📧 From: {sender}")
                                    print(f"   📋 Subject: {subject}")
                                    print(f"   ⏰ Received: {email_received_time.strftime('%H:%M:%S') if 'email_received_time' in locals() else 'N/A'}")
                                    mail.store(email_id, '+FLAGS', '\\Seen')
                                    mail.store(email_id, '+FLAGS', '\\Deleted')
                                    mail.expunge()
                                    return found_otp
                                else:
                                    print("❌ Could not extract OTP from email body")
                            except Exception as e:
                                print(f"⚠️ Error processing email: {e}")
                                continue
                except Exception as e:
                    print(f"⚠️ IMAP check failed: {e}")
                elapsed = int(time.time() - start_time)
                print(f"⏳ Still waiting for OTP... ({elapsed}s elapsed)")
                time.sleep(check_interval)
            print(f"❌ No OTP received after {max_wait} seconds")
            return None
        except Exception as e:
            print(f"❌ Error in OTP retrieval: {e}")
            return None

    def wait_for_cloudflare_checkbox(self, timeout: int = 20):
        print("🔍 Checking for Cloudflare verification...")
        selectors = [
            (By.CSS_SELECTOR, "input[type='checkbox']"),
            (By.XPATH, "//input[@type='checkbox']"),
            (By.XPATH, "//iframe[contains(@src, 'cloudflare')]"),
        ]
        for selector_type, selector_value in selectors:
            try:
                element = WebDriverWait(self.driver, 5).until(
                    EC.presence_of_element_located((selector_type, selector_value))
                )
                if selector_type == By.XPATH and "iframe" in selector_value:
                    self.driver.switch_to.frame(element)
                    checkbox = self.driver.find_element(By.CSS_SELECTOR, "input[type='checkbox']")
                    checkbox.click()
                    self.driver.switch_to.default_content()
                else:
                    self.driver.execute_script("arguments[0].scrollIntoView(true);", element)
                    time.sleep(0.5)
                    try:
                        element.click()
                    except:
                        self.driver.execute_script("arguments[0].click();", element)
                print("✅ Cloudflare verification handled")
                time.sleep(2)
                return True
            except TimeoutException:
                continue
            except Exception:
                continue
        print("ℹ️ No Cloudflare checkbox found")
        return False

    def revoke_token(self, app_name: str = "Feroz") -> bool:
        try:
            print(f"\n🔄 STEP 12: Revoking old token for '{app_name}'...")
            time.sleep(2)
            app_rows = self.driver.find_elements(By.XPATH, "//table//tbody//tr")
            print(f"📋 Found {len(app_rows)} app(s) in table")
            target_row = None
            for row in app_rows:
                try:
                    if app_name.lower() in row.text.lower():
                        target_row = row
                        print(f"✅ Found app row for '{app_name}'")
                        break
                except:
                    continue
            if not target_row:
                print(f"⚠️ App '{app_name}' not found, trying first connected app...")
                for row in app_rows:
                    try:
                        if "connected" in row.text.lower():
                            target_row = row
                            print(f"✅ Found connected app row")
                            break
                    except:
                        continue
            if not target_row:
                print("❌ No suitable app found")
                return False
            dropdown_buttons = target_row.find_elements(By.XPATH, ".//button")
            dropdown_clicked = False
            for btn in dropdown_buttons:
                try:
                    btn_html = btn.get_attribute('outerHTML')
                    if any(indicator in btn_html.lower() for indicator in ['chevron', 'arrow', 'expand', 'dropdown']):
                        self.driver.execute_script("arguments[0].scrollIntoView(true);", btn)
                        time.sleep(0.5)
                        btn.click()
                        print("✅ Clicked dropdown arrow")
                        dropdown_clicked = True
                        time.sleep(2)
                        break
                except:
                    continue
            if not dropdown_clicked and len(dropdown_buttons) > 0:
                try:
                    last_btn = dropdown_buttons[-1]
                    self.driver.execute_script("arguments[0].scrollIntoView(true);", last_btn)
                    time.sleep(0.5)
                    last_btn.click()
                    print("✅ Clicked dropdown button")
                    time.sleep(2)
                except Exception as e:
                    print(f"⚠️ Could not click dropdown: {e}")
            try:
                revoke_selectors = [
                    (By.XPATH, "//span[contains(text(), 'Revoke')]"),
                    (By.XPATH, "//button[contains(., 'Revoke')]"),
                    (By.CSS_SELECTOR, "span.dj.az.dl.ce.bc"),
                ]
                revoke_button = None
                for selector_type, selector_value in revoke_selectors:
                    try:
                        revoke_button = WebDriverWait(self.driver, 5).until(
                            EC.presence_of_element_located((selector_type, selector_value))
                        )
                        break
                    except:
                        continue
                if revoke_button:
                    self.driver.execute_script("arguments[0].scrollIntoView(true);", revoke_button)
                    time.sleep(0.5)
                    try:
                        revoke_button.click()
                    except:
                        parent_btn = revoke_button.find_element(By.XPATH, "./..")
                        parent_btn.click()
                    print("✅ Clicked Revoke button")
                    time.sleep(2)
                    print("⏳ Waiting for confirmation modal...")
                    try:
                        confirm_selectors = [
                            (By.XPATH, "//button[contains(., 'Confirm')]"),
                            (By.XPATH, "/html/body/div/div/div[2]/div[2]/div/button[2]"),
                            (By.CSS_SELECTOR, "button.cd.az.ba.dn.cf.a.ey.do.ez.av.c.dp.d.dq.dr.ds.fb.fc.fd.fe.ff.fg.fh.ea.fi.fj.fk"),
                        ]
                        confirm_button = None
                        for selector_type, selector_value in confirm_selectors:
                            try:
                                confirm_button = WebDriverWait(self.driver, 10).until(
                                    EC.element_to_be_clickable((selector_type, selector_value))
                                )
                                print(f"✅ Found Confirm button")
                                break
                            except:
                                continue
                        if confirm_button:
                            self.driver.execute_script("arguments[0].scrollIntoView(true);", confirm_button)
                            time.sleep(0.5)
                            try:
                                confirm_button.click()
                                print("✅ Clicked Confirm button (direct)")
                            except ElementClickInterceptedException:
                                self.driver.execute_script("arguments[0].click();", confirm_button)
                                print("✅ Clicked Confirm button (JavaScript)")
                            time.sleep(3)
                            print("⏳ Waiting for modal to close...")
                            time.sleep(2)
                            print("✅ Token revoked successfully")
                            return True
                        else:
                            print("⚠️ Confirm button not found")
                            return False
                    except Exception as e:
                        print(f"❌ Error handling confirmation modal: {e}")
                        return False
                else:
                    print("⚠️ Revoke button not found - token may already be revoked or not exist")
                    return False
            except Exception as e:
                print(f"❌ Error clicking Revoke button: {e}")
                return False
        except Exception as e:
            print(f"❌ Error revoking token: {e}")
            return False

    def generate_token(self, app_name: str = "Feroz") -> bool:
        try:
            print(f"\n🔄 STEP 12B: Generating new token for '{app_name}'...")
            time.sleep(3)
            generate_selectors = [
                (By.XPATH, "//button[contains(., 'Generate')]"),
                (By.XPATH, "//span[contains(text(), 'Generate')]"),
                (By.XPATH, "//button[.//span[contains(text(), 'Generate')]]"),
                (By.CSS_SELECTOR, "button[type='button']"),
                (By.XPATH, "//div[contains(text(), 'Generate')]"),
                (By.XPATH, "//*[contains(text(), 'Generate Token')]"),
            ]
            generate_button = None
            max_attempts = 3
            for attempt in range(max_attempts):
                print(f"🔍 Attempt {attempt + 1}/{max_attempts} to find Generate button...")
                for selector_type, selector_value in generate_selectors:
                    try:
                        elements = self.driver.find_elements(selector_type, selector_value)
                        for element in elements:
                            try:
                                element_text = element.text.strip().lower()
                                if "generate" in element_text and "revoke" not in element_text:
                                    generate_button = element
                                    print(f"✅ Found Generate button with text: {element.text}")
                                    break
                            except:
                                continue
                        if generate_button:
                            break
                    except:
                        continue
                if generate_button:
                    break
                if attempt < max_attempts - 1:
                    print("⚠️ Generate button not found, checking dropdowns...")
                    dropdown_arrows = self.driver.find_elements(By.XPATH, "//button[contains(@class, 'chevron') or contains(@aria-label, 'expand') or .//*[contains(text(), '▼') or contains(text(), '▾')]]")
                    for arrow in dropdown_arrows[:3]:
                        try:
                            arrow.click()
                            print("✅ Clicked dropdown arrow")
                            time.sleep(2)
                            break
                        except:
                            continue
                    time.sleep(2)
            if not generate_button:
                print("ℹ️ Generate button not found, checking if token already exists...")
                token_indicators = [
                    "eyJ",
                    "access token",
                    "bearer",
                    "token:"
                ]
                page_source = self.driver.page_source.lower()
                existing_token_detected = any(indicator.lower() in page_source for indicator in token_indicators)
                if existing_token_detected:
                    print("✅ Token appears to already exist")
                    return True
                else:
                    print("⚠️ No Generate button found and no existing token detected")
                    return False
            self.driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", generate_button)
            time.sleep(1)
            click_methods = [
                ("direct click", lambda: generate_button.click()),
                ("JavaScript click", lambda: self.driver.execute_script("arguments[0].click();", generate_button)),
                ("parent click", lambda: generate_button.find_element(By.XPATH, "./..").click()),
            ]
            click_success = False
            for method_name, click_func in click_methods:
                try:
                    click_func()
                    print(f"✅ Clicked Generate button ({method_name})")
                    click_success = True
                    break
                except Exception as e:
                    print(f"⚠️ {method_name} failed: {e}")
                    continue
            if not click_success:
                print("❌ All click methods failed")
                return False
            print("⏳ Waiting for confirmation modal to appear...")
            time.sleep(3)
            print("🔍 Looking for confirmation modal...")
            try:
                modal_selectors = [
                    (By.XPATH, "//*[contains(text(), 'Confirm generate?')]"),
                    (By.XPATH, "//*[contains(text(), 'Are you sure you want to generate')]"),
                    (By.XPATH, "//div[contains(@class, 'modal')]"),
                    (By.XPATH, "//div[@role='dialog']"),
                    (By.CSS_SELECTOR, "div[class*='modal']"),
                ]
                modal_found = False
                for selector_type, selector_value in modal_selectors:
                    try:
                        WebDriverWait(self.driver, 10).until(
                            EC.presence_of_element_located((selector_type, selector_value))
                        )
                        print(f"✅ Confirmation modal found")
                        modal_found = True
                        break
                    except:
                        continue
                if not modal_found:
                    print("⚠️ No confirmation modal found, proceeding...")
                else:
                    print("🔍 Looking for Confirm button in modal...")
                    confirm_selectors = [
                        (By.XPATH, "//button[contains(., 'Confirm') and not(contains(., 'Cancel'))]"),
                        (By.XPATH, "//button[text()='Confirm']"),
                        (By.XPATH, "//button[contains(text(), 'Confirm')]"),
                        (By.XPATH, "//button[@type='button' and contains(., 'Confirm')]"),
                        (By.CSS_SELECTOR, "button[class*='confirm']"),
                    ]
                    confirm_button = None
                    for selector_type, selector_value in confirm_selectors:
                        try:
                            confirm_button = WebDriverWait(self.driver, 5).until(
                                EC.element_to_be_clickable((selector_type, selector_value))
                            )
                            button_text = confirm_button.text.strip().lower()
                            if "cancel" not in button_text:
                                print(f"✅ Found Confirm button with text: {confirm_button.text}")
                                break
                            else:
                                confirm_button = None
                        except:
                            continue
                    if confirm_button:
                        self.driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", confirm_button)
                        time.sleep(1)
                        try:
                            confirm_button.click()
                            print("✅ Clicked Confirm button in modal")
                        except ElementClickInterceptedException:
                            self.driver.execute_script("arguments[0].click();", confirm_button)
                            print("✅ Clicked Confirm button (JavaScript)")
                        print("⏳ Waiting for token generation (10 seconds)...")
                        time.sleep(10)
                    else:
                        print("⚠️ Confirm button not found in modal")
                        print("⏳ Waiting for token generation anyway (10 seconds)...")
                        time.sleep(10)
            except Exception as e:
                print(f"⚠️ Error handling confirmation modal: {e}")
                print("⏳ Continuing with token generation (10 seconds)...")
                time.sleep(10)
            try:
                success_indicators = [
                    "Token generated successfully",
                    "successfully generated",
                    "access token",
                    "eyJ",
                ]
                page_source = self.driver.page_source.lower()
                if any(indicator.lower() in page_source for indicator in success_indicators):
                    print("✅ Token generation successful")
                    return True
                else:
                    error_indicators = ["error", "failed", "unable", "cannot"]
                    if any(indicator in page_source for indicator in error_indicators):
                        print("⚠️ Token generation may have failed - error detected")
                    else:
                        print("ℹ️ Token generation status unclear, but proceeding")
                    return True
            except Exception as e:
                print(f"⚠️ Error verifying token generation: {e}")
                return True
        except Exception as e:
            print(f"❌ Error generating token: {e}")
            import traceback
            traceback.print_exc()
            return False

    def copy_access_token(self, app_name: str = "Feroz") -> str:
        try:
            print(f"\n🔑 STEP 13: Copying new access token for '{app_name}'...")
            time.sleep(5)
            token = self._copy_access_token_specific()
            if token and len(token) > 100 and token.startswith('eyJ'):
                print(f"✅ Access Token found: {token[:20]}...{token[-10:]}")
                return token
            strategies = [
                self._copy_from_jwt_dom_elements,
                self._copy_from_token_field,
                self._copy_from_api_key_section,
            ]
            for i, strategy in enumerate(strategies):
                try:
                    print(f"🔍 Trying fallback strategy {i+1}/{len(strategies)}...")
                    token = strategy()
                    if token and len(token) > 100 and token.startswith('eyJ'):
                        print(f"✅ Access Token found using fallback {i+1}: {token[:20]}...{token[-10:]}")
                        return token
                except Exception as e:
                    print(f"⚠️ Strategy {i+1} failed: {e}")
                    continue
            print("❌ Could not retrieve Access Token using any method")
            return None
        except Exception as e:
            print(f"❌ Error copying token: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _copy_access_token_specific(self) -> str:
        try:
            access_token_labels = self.driver.find_elements(
                By.XPATH, 
                "//*[contains(text(), 'Access Token') or contains(text(), 'access_token') or contains(text(), 'Bearer')]"
            )
            print(f"🔍 Found {len(access_token_labels)} elements mentioning Access Token")
            for label in access_token_labels:
                try:
                    container = label.find_element(By.XPATH, "./ancestor::div[1]")
                    copy_buttons = container.find_elements(
                        By.XPATH, 
                        ".//button[.//img[@alt='copy']] | .//button[contains(@class, 'copy')] | .//img[@alt='copy']"
                    )
                    print(f"📋 Found {len(copy_buttons)} copy buttons near Access Token label")
                    for i, copy_btn in enumerate(copy_buttons):
                        try:
                            self.driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", copy_btn)
                            time.sleep(0.5)
                            print(f"🖱️ Clicking copy button #{i+1} near Access Token...")
                            try:
                                copy_btn.click()
                            except:
                                parent = copy_btn.find_element(By.XPATH, "./..")
                                parent.click()
                            time.sleep(1)
                            token = pyperclip.paste()
                            if token and len(token) > 100 and token.startswith('eyJ'):
                                print(f"✅ JWT Access Token found: {token[:20]}...")
                                return token
                            else:
                                if token:
                                    print(f"⚠️ Copied value is NOT a JWT token (length: {len(token)}): {token[:30] if len(token) > 30 else token}")
                                token_text = self._find_jwt_nearby(container)
                                if token_text and len(token_text) > 100 and token_text.startswith('eyJ'):
                                    print(f"✅ Found JWT token in nearby text: {token_text[:20]}...")
                                    return token_text
                        except Exception as e:
                            print(f"⚠️ Copy button #{i+1} failed: {e}")
                            continue
                except Exception as e:
                    print(f"⚠️ Container search failed: {e}")
                    continue
            print("🔍 Searching entire page for JWT tokens...")
            all_elements = self.driver.find_elements(By.XPATH, "//*")
            for element in all_elements:
                try:
                    text = element.text
                    if text and 'eyJ' in text and len(text) > 100:
                        import re
                        token_match = re.search(r'(eyJ[a-zA-Z0-9\-_]+?\.[a-zA-Z0-9\-_]+?\.[a-zA-Z0-9\-_]+)', text)
                        if token_match:
                            token = token_match.group(1)
                            print(f"✅ Found JWT token in page text: {token[:20]}...")
                            return token
                except:
                    continue
            return None
        except Exception as e:
            print(f"⚠️ Specific Access Token search failed: {e}")
            return None

    def _find_jwt_nearby(self, container):
        try:
            container_text = container.text
            import re
            token_match = re.search(r'(eyJ[a-zA-Z0-9\-_]+?\.[a-zA-Z0-9\-_]+?\.[a-zA-Z0-9\-_]+)', container_text)
            if token_match:
                return token_match.group(1)
            try:
                parent = container.find_element(By.XPATH, "./..")
                parent_text = parent.text
                token_match = re.search(r'(eyJ[a-zA-Z0-9\-_]+?\.[a-zA-Z0-9\-_]+?\.[a-zA-Z0-9\-_]+)', parent_text)
                if token_match:
                    return token_match.group(1)
            except:
                pass
        except Exception as e:
            print(f"⚠️ JWT search failed: {e}")
        return None

    def _copy_from_jwt_dom_elements(self) -> str:
        try:
            all_elements = self.driver.find_elements(By.XPATH, "//*")
            for element in all_elements:
                try:
                    text = element.text
                    if text and 'eyJ' in text and len(text) > 100:
                        import re
                        token_match = re.search(r'(eyJ[a-zA-Z0-9\-_]+?\.[a-zA-Z0-9\-_]+?\.[a-zA-Z0-9\-_]+)', text)
                        if token_match:
                            token = token_match.group(1)
                            print(f"✅ Found JWT token in DOM: {token[:20]}...")
                            return token
                except:
                    continue
            page_source = self.driver.page_source
            import re
            token_match = re.search(r'(eyJ[a-zA-Z0-9\-_]+?\.[a-zA-Z0-9\-_]+?\.[a-zA-Z0-9\-_]+)', page_source)
            if token_match:
                token = token_match.group(1)
                print(f"✅ Found JWT token in page source: {token[:20]}...")
                return token
            return None
        except Exception as e:
            print(f"⚠️ JWT DOM strategy failed: {e}")
            return None

    def _copy_from_token_field(self) -> str:
        try:
            input_fields = self.driver.find_elements(By.XPATH, "//input[@type='text' or @type='password' or @type='hidden']")
            for field in input_fields:
                try:
                    value = field.get_attribute('value')
                    if value and len(value) > 100 and value.startswith('eyJ'):
                        print(f"✅ Found token in input field: {value[:20]}...")
                        return value
                except:
                    continue
            return None
        except Exception as e:
            print(f"⚠️ Token field strategy failed: {e}")
            return None

    def _copy_from_api_key_section(self) -> str:
        try:
            sections = self.driver.find_elements(By.XPATH, "//div[contains(text(), 'API') or contains(text(), 'Token')]")
            for section in sections:
                try:
                    container = section.find_element(By.XPATH, "./ancestor::div[1]")
                    container_text = container.text
                    token_match = re.search(r'(eyJ[a-zA-Z0-9\-_]+?\.[a-zA-Z0-9\-_]+?\.[a-zA-Z0-9\-_]+)', container_text)
                    if token_match:
                        token = token_match.group(1)
                        print(f"✅ Found token in API section: {token[:20]}...")
                        return token
                except:
                    continue
            page_source = self.driver.page_source
            token_match = re.search(r'(eyJ[a-zA-Z0-9\-_]+?\.[a-zA-Z0-9\-_]+?\.[a-zA-Z0-9\-_]+)', page_source)
            if token_match:
                token = token_match.group(1)
                print(f"✅ Found token in page source: {token[:20]}...")
                return token
            return None
        except Exception as e:
            print(f"⚠️ API section strategy failed: {e}")
            return None

    def login_attempt(self) -> bool:
        print("🌐 Opening Upstox login page...")
        self.driver.get(self.login_url)
        time.sleep(3)
        print("\n📧 STEP 1: Clearing all Upstox emails...")
        self.delete_all_upstox_emails()
        time.sleep(2)
        try:
            print("\n📱 STEP 2: Entering mobile number...")
            mobile_input = WebDriverWait(self.driver, 10).until(
                EC.visibility_of_element_located((By.ID, "mobileNum"))
            )
            mobile_input.clear()
            mobile_input.send_keys(self.mobile_number)
            time.sleep(1)
            print("✅ Mobile number entered")
        except Exception as e:
            print(f"❌ Failed: {e}")
            return False
        print("\n🛡️ STEP 3: Checking Cloudflare...")
        self.wait_for_cloudflare_checkbox()
        time.sleep(2)
        try:
            print("\n📘 STEP 4: Requesting OTP...")
            get_otp_button = WebDriverWait(self.driver, 15).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Get OTP')]"))
            )
            otp_request_time = now_ist()
            print(f"🕐 Timestamp: {otp_request_time.strftime('%H:%M:%S.%f')[:-3]}")
            get_otp_button.click()
            print("✅ OTP requested")
            time.sleep(2)
        except Exception as e:
            print(f"❌ Failed: {e}")
            return False
        try:
            print("\n⏳ STEP 5: Waiting for OTP input field...")
            otp_input = WebDriverWait(self.driver, 10).until(
                EC.visibility_of_element_located((By.ID, "otpNum"))
            )
            print("✅ OTP field ready")
        except Exception as e:
            print(f"❌ Failed: {e}")
            return False
        print("\n📬 STEP 6: Retrieving OTP from email...")
        otp = self.get_latest_otp_by_uid(max_wait=90, otp_request_time=otp_request_time)
        if not otp:
            print("❌ No OTP received")
            return False
        try:
            print(f"\n📝 STEP 7: Entering OTP...")
            otp_input.clear()
            for char in str(otp):
                otp_input.send_keys(char)
                time.sleep(0.1)
            time.sleep(1)
            print(f"✅ Entered: {otp}")
        except Exception as e:
            print(f"❌ Failed: {e}")
            return False
        try:
            print("\n📘 STEP 8: Submitting OTP...")
            verify_button = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Continue') or contains(text(), 'Verify')]"))
            )
            verify_button.click()
            print("✅ Submitted")
            time.sleep(4)
        except Exception as e:
            print(f"❌ Failed: {e}")
            return False
        if self.passcode:
            try:
                print("\n🔐 STEP 9: Entering passcode...")
                passcode_selectors = [
                    (By.ID, "pinCode"),
                    (By.XPATH, "//input[@type='password']"),
                    (By.XPATH, "//input[@placeholder='Enter PIN']"),
                    (By.CSS_SELECTOR, "input[type='password']")
                ]
                passcode_input = None
                for selector_type, selector_value in passcode_selectors:
                    try:
                        passcode_input = WebDriverWait(self.driver, 5).until(
                            EC.visibility_of_element_located((selector_type, selector_value))
                        )
                        break
                    except:
                        continue
                if passcode_input:
                    passcode_input.clear()
                    passcode_input.send_keys(self.passcode)
                    time.sleep(1)
                    print("✅ Passcode entered")
                    submit_selectors = [
                        (By.XPATH, "//button[@type='submit']"),
                        (By.XPATH, "//button[contains(text(), 'Continue')]"),
                        (By.XPATH, "//button[contains(text(), 'Submit')]"),
                    ]
                    for selector_type, selector_value in submit_selectors:
                        try:
                            submit_button = WebDriverWait(self.driver, 3).until(
                                EC.element_to_be_clickable((selector_type, selector_value))
                            )
                            submit_button.click()
                            print("✅ Submitted")
                            time.sleep(3)
                            break
                        except:
                            continue
                else:
                    print("ℹ️ No passcode field found")
            except Exception as e:
                print(f"⚠️ Passcode step: {e}")
        try:
            print("\n⏳ STEP 10: Verifying login...")
            time.sleep(3)
            success_urls = [
                "account.upstox.com",
                "developer/apps",
                "pro.upstox.com",
                "app.upstox.com"
            ]
            current_url = self.driver.current_url
            print(f"📍 Current URL: {current_url}")
            if any(url in current_url for url in success_urls):
                print("✅ LOGIN SUCCESSFUL!")
                print(f"✅ Redirected to: {current_url}")
                self.save_cookies()
                print("\n🎯 STEP 11: Navigating to Developer Apps page...")
                self.driver.get(self.target_url)
                time.sleep(3)
                print(f"✅ Navigated to: {self.target_url}")
                return True
            if "login.upstox.com" not in current_url:
                print("✅ LOGIN SUCCESSFUL!")
                self.save_cookies()
                print("\n🎯 STEP 11: Navigating to Developer Apps page...")
                self.driver.get(self.target_url)
                time.sleep(3)
                print(f"✅ Navigated to: {self.target_url}")
                return True
            print("❌ Login verification failed")
            return False
        except Exception as e:
            print(f"❌ Error: {e}")
            return False

    def login(self) -> bool:
        if not self.driver:
            raise RuntimeError("Driver not initialized")
        if self.load_cookies():
            self.driver.refresh()
            time.sleep(3)
            try:
                current_url = self.driver.current_url
                success_urls = ["account.upstox.com", "developer/apps", "pro.upstox.com", "app.upstox.com"]
                if any(url in current_url for url in success_urls):
                    print("♻️ Session reused")
                    if self.target_url not in current_url:
                        print(f"🎯 Navigating to: {self.target_url}")
                        self.driver.get(self.target_url)
                        time.sleep(3)
                    return True
            except:
                print("⚠️ Session expired")
        for attempt in range(1, self.max_retries + 1):
            print("\n" + "=" * 60)
            print(f"🔄 LOGIN ATTEMPT {attempt}/{self.max_retries}")
            print("=" * 60)
            if self.login_attempt():
                print("\n🎉 SUCCESS!")
                return True
            else:
                if attempt < self.max_retries:
                    print(f"\n⚠️ Attempt {attempt} failed, retrying in 5s...")
                    time.sleep(5)
        print("\n❌ All attempts failed")
        return False

    def close(self):
        if self.driver:
            self.driver.quit()
            print("🚪 Browser closed")

# ========== UPSTOX TRADER CLASS ==========
class UpstoxTrader:
    """Enhanced trader class with option chain and order management capabilities"""
    def __init__(self, access_token):
        self.access_token = access_token
        self.base_url = "https://api.upstox.com/v2"
        self.headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}"
        }
        self.order_headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}"
        }
        # Persistent session — reuses TCP connection across all API calls
        self._session = requests.Session()
        self._session.headers.update(self.headers)
        self._order_session = requests.Session()
        self._order_session.headers.update(self.order_headers)

    # ... (all methods unchanged from original both4) ...
    def get_user_profile(self):
        endpoint = f"{self.base_url}/user/profile"
        try:
            response = self._session.get(endpoint, timeout=10)
            return response.json()
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def get_funds(self):
        endpoint = f"{self.base_url}/user/get-funds-and-margin"
        try:
            response = self._session.get(endpoint, timeout=10)
            return response.json()
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def get_positions(self):
        endpoint = f"{self.base_url}/portfolio/short-term-positions"
        try:
            response = self._session.get(endpoint, timeout=10)
            return response.json()
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def get_order_details(self, order_id):
        endpoint = f"{self.base_url}/order/history"
        params = {"order_id": order_id}
        try:
            response = self._session.get(endpoint, params=params, timeout=10)
            return response.json()
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def get_order_book(self):
        endpoint = f"{self.base_url}/order/retrieve-all"
        try:
            response = self._session.get(endpoint, timeout=10)
            return response.json()
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def cancel_order(self, order_id):
        endpoint = f"{self.base_url}/order/cancel"
        data = {"order_id": order_id}
        try:
            response = requests.delete(endpoint, headers=self.order_headers, json=data, timeout=10)
            return response.json()
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def modify_order(self, order_id, trigger_price, price=0, quantity=None, order_type=None):
        """Modify an existing SL order on Upstox (used to trail the stop loss).
        
        Parameters
        ----------
        order_id      : str   – the broker order-id of the live SL order
        trigger_price : float – new SL trigger price
        price         : float – new limit price (0 for SL-M / market execution)
        quantity      : int   – lot quantity (required by Upstox modify endpoint)
        order_type    : str   – e.g. 'SL_LIMIT' or 'SL' (keep original if None)
        """
        endpoint = f"{self.base_url}/order/modify"
        payload = {
            "order_id":      order_id,
            "trigger_price": round(trigger_price, 2),
            "price":         round(price, 2),
            "validity":      "DAY",
        }
        if quantity is not None:
            payload["quantity"] = quantity
        if order_type is not None:
            payload["order_type"] = order_type.upper()
        try:
            print(f"📝 MODIFY SL ORDER: id={order_id}  new_trigger=₹{trigger_price:.2f}")
            response = self._order_session.put(endpoint, json=payload, timeout=10)
            result = response.json() if response.text else {"status": "error", "message": "Empty response"}
            if response.status_code == 200:
                print(f"✅ SL Modified → trigger ₹{trigger_price:.2f}")
            else:
                print(f"⚠️ SL Modify failed ({response.status_code}): {result}")
            return {"status_code": response.status_code, "response": result}
        except Exception as e:
            print(f"❌ SL Modify exception: {e}")
            return {"status_code": 0, "response": {"status": "error", "message": str(e)}}

    def get_ltp(self, instrument_key, max_retries=3):
        endpoint = f"{self.base_url}/market-quote/ltp"
        params = {"instrument_key": instrument_key}
        for attempt in range(max_retries):
            try:
                response = self._session.get(endpoint, params=params, timeout=15)
                if response.status_code == 200:
                    data = response.json()
                    # Upstox normalises the key in the response (e.g. NSE_EQ|xxx → NSE_EQ:xxx)
                    # Try both the original key and the colon-normalised variant
                    inner = data.get('data', {})
                    ltp_data = (inner.get(instrument_key)
                                or inner.get(instrument_key.replace('|', ':'))
                                or inner.get(instrument_key.replace(':', '|'))
                                or (list(inner.values())[0] if inner else None))
                    if ltp_data:
                        ltp = ltp_data.get('last_price')
                        if ltp and ltp > 0:
                            return ltp
                    if DEBUG_MODE and attempt == 0:
                        print(f"⚠️ LTP 200 but no price found for {instrument_key}. "
                              f"Response keys: {list(inner.keys())[:3]}")
                elif response.status_code == 429:
                    if attempt < max_retries - 1:
                        time.sleep(3)
                        continue
                if attempt < max_retries - 1 and DEBUG_MODE:
                    print(f"⚠️ LTP fetch attempt {attempt + 1} failed (status: {response.status_code}), retrying...")
                    time.sleep(2)
            except Exception as e:
                if attempt < max_retries - 1 and DEBUG_MODE:
                    print(f"⚠️ LTP fetch error (attempt {attempt + 1}): {e}, retrying...")
                    time.sleep(2)
        return None

    def get_option_chain(self, underlying_key, expiry_date=None):
        endpoint = f"{self.base_url}/option/contract"
        params = {"instrument_key": underlying_key}
        if expiry_date:
            params["expiry_date"] = expiry_date
        try:
            response = self._session.get(endpoint, params=params, timeout=15)
            return response.json()
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def place_order(self, instrument_key, quantity, transaction_type, product, order_type, price=0, trigger_price=0):
        """Place an order with Upstox API - FIXED VERSION with proper validation"""
        endpoint = f"{self.base_url}/order/place"

        # ── Service-hours guard (HTTP 423 from Upstox outside 05:30–23:59 IST) ──
        if not is_order_time_allowed():
            REJECTED_ORDER_SIGNALS.append({
                'symbol': instrument_key,
                'strategy': 'UNKNOWN',
                'reason': 'Outside Upstox service hours (05:30–23:59 IST)',
                'timestamp': now_ist()
            })
            return {
                "status_code": 423,
                "response": {"status": "error",
                             "message": "Order blocked: outside Upstox service hours (05:30–23:59 IST)"}
            }

        # FIX 3: Validate instrument_key before placing order
        if not instrument_key or '|' not in instrument_key:
            print(f"❌ Invalid instrument_key: {instrument_key}")
            return {
                "status_code": 400,
                "response": {"status": "error", "message": f"Invalid instrument_key: {instrument_key}"}
            }
        
        payload = {
            "quantity": quantity,
            "product": product,
            "validity": "DAY",
            "price": price,
            "tag": "AUTO_BOT",
            "instrument_token": instrument_key,
            "order_type": order_type.upper(),
            "transaction_type": transaction_type.upper(),
            "disclosed_quantity": 0,
            "trigger_price": trigger_price,
            "is_amo": False
        }
        
        try:
            print(f"📤 ORDER REQUEST: {payload}")
            response = self._order_session.post(endpoint, json=payload, timeout=15)
            print(f"📥 ORDER RESPONSE ({response.status_code}): {response.text}")
            
            result = {
                "status_code": response.status_code,
                "response": response.json() if response.text else {"status": "error", "message": "Empty response"}
            }
            
            # FIX 2: Immediately show if order API failed
            if result["status_code"] != 200:
                print(f"❌ ORDER API FAILED: {result.get('response')}")
            
            return result
            
        except Exception as e:
            print(f"❌ ORDER EXCEPTION: {e}")
            return {
                "status_code": 0,
                "response": {"status": "error", "message": str(e)}
            }

# ========== HELPER FUNCTIONS ==========
def norm_key(k: str) -> str:
    """Normalize instrument keys to use pipe delimiter consistently."""
    if isinstance(k, str):
        k = k.replace(':', '|')
        if '|' in k:
            parts = k.split('|')
            if len(parts) == 2:
                return f"{parts[0]}|{parts[1]}"
    return k

def is_order_time_allowed():
    """
    Upstox API only accepts orders between 05:30 and 23:59 IST every day.
    This check is ALWAYS enforced regardless of TEST_MODE / BYPASS_MARKET_CHECKS,
    because it is an exchange-level restriction, not a market-hours restriction.
    Trying outside this window returns HTTP 423 (UDAPI100074).
    """
    now = now_ist()
    order_start = now.replace(hour=5, minute=30, second=0, microsecond=0)
    order_end   = now.replace(hour=23, minute=59, second=59, microsecond=0)
    allowed = order_start <= now <= order_end
    if not allowed:
        print(f"⏰ Order blocked: Upstox API only accepts orders 05:30–23:59 IST "
              f"(current time {now.strftime('%H:%M:%S')})")
    return allowed

def is_market_open():
    # FIX 4: Bypass check if TEST_MODE is enabled
    if BYPASS_MARKET_CHECKS:
        return True
    now = now_ist()
    if now.weekday() >= 5:
        return False
    current_time = now.strftime("%H:%M")
    return MARKET_OPEN_TIME <= current_time <= MARKET_CLOSE_TIME

def is_market_stabilized():
    # FIX 4: Bypass check if TEST_MODE is enabled
    if BYPASS_MARKET_CHECKS:
        return True
    now = now_ist()
    if now.weekday() >= 5:
        return False
    current_time = now.strftime("%H:%M")
    if current_time < MARKET_OPEN_TIME or current_time >= MARKET_CLOSE_TIME:
        return False
    market_open_dt = datetime.strptime(MARKET_OPEN_TIME, "%H:%M").replace(year=now.year, month=now.month, day=now.day)
    minutes_since_open = (now - market_open_dt).total_seconds() / 60
    return minutes_since_open >= MARKET_STABILIZATION_MINUTES

def is_exit_time():
    """Check if it's time to start exiting positions"""
    now = now_ist()
    current_time = now.strftime("%H:%M")
    return current_time >= EXIT_START_TIME

def is_gap_trading_window(now=None):
    """Check if current time is within gap trading window"""
    if now is None:
        now = now_ist()
    market_open = datetime.strptime(MARKET_OPEN_TIME, "%H:%M").replace(year=now.year, month=now.month, day=now.day)
    minutes_since_open = (now - market_open).total_seconds() / 60
    return GAP_ENTRY_DELAY_MINUTES <= minutes_since_open <= GAP_TRADING_WINDOW_MINUTES

def dynamic_volume_threshold():
    if not USE_DYNAMIC_VOLUME_THRESHOLD:
        return VOLUME_SPIKE_THRESHOLD
    now = now_ist()
    market_open_dt = datetime.strptime(MARKET_OPEN_TIME, "%H:%M").replace(year=now.year, month=now.month, day=now.day)
    minutes_since_open = (now - market_open_dt).total_seconds() / 60
    if minutes_since_open < 60:
        return 1.2
    elif minutes_since_open < 180:
        return 1.3
    else:
        return 1.5

def previous_trading_day(max_lookback_days=15):
    """Get the most recent trading day, skipping weekends and NSE holidays"""
    today = now_ist().date()
    
    print(f"🔍 Looking for previous trading day from {today} ({today.strftime('%A')})")
    
    for d in range(1, max_lookback_days + 1):
        target_date = today - timedelta(days=d)
        
        # Skip weekends
        if target_date.weekday() >= 5:
            continue
        
        # Skip NSE holidays (check both 2025 and 2026)
        date_str = target_date.strftime('%Y-%m-%d')
        if date_str in NSE_HOLIDAYS:
            print(f"   ⚠️ Skipping {target_date} ({target_date.strftime('%A')}) - NSE Holiday")
            continue
        
        print(f"   ✅ Found: {target_date} ({target_date.strftime('%A')})")
        return target_date
    
    # Fallback
    fallback = today - timedelta(days=7)
    print(f"   ⚠️ Using fallback: {fallback}")
    return fallback

def banner():
    print("\n" + "="*120)
    print("🚀 ADVANCED TRADING SYSTEM WITH INTELLIGENT CACHING 🚀")
    print("="*120)
    print("📈 Multi-Strategy Real-Time Trading System")
    print(f"Market Hours: {MARKET_OPEN_TIME}-{MARKET_CLOSE_TIME} | Stabilization: {MARKET_STABILIZATION_MINUTES}m")
    print(f"Volume: {VOLUME_SPIKE_THRESHOLD}x dynamic | Min Avg Vol: {MIN_AVG_VOLUME:,}")
    print()
    print("🎯 ACTIVE STRATEGIES:")
    print(f" • R3 Breakout (Buys CE): {'ENABLED ⚡' if ENABLE_AUTO_TRADING else 'DISABLED'}")
    print(f" • S3 Breakdown (Buys PE): {'ENABLED ⚡' if ENABLE_AUTO_TRADING else 'DISABLED'}")
    print(f" • Box Theory (Breakouts): {'ENABLED ⚡' if ENABLE_BOX_TRADING else 'DISABLED'}")
    print(f" • Range Trading (Bounces): {'ENABLED ⚡' if ENABLE_RANGE_TRADING else 'DISABLED'}")
    print(f" • Gap Trading (Options): {'ENABLED ⚡' if ENABLE_GAP_TRADING else 'DISABLED'}")
    print(f" • Fast Trading (Bollinger): {'ENABLED ⚡' if ENABLE_FAST_TRADING else 'DISABLED'}")
    print()
    print(f"🔥 KLINGER OSCILLATOR:")
    print(f" • Master Filter: {'ENABLED ✓' if ENABLE_KLINGER_FILTER else 'DISABLED ✗'}")
    if ENABLE_KLINGER_FILTER:
        print(f" • Box Trading: {'ENABLED ✓' if ENABLE_KLINGER_FOR_BOX else 'DISABLED'}")
        print(f" • Range Trading: {'ENABLED ✓' if ENABLE_KLINGER_FOR_RANGE else 'DISABLED'}")
        print(f" • Parameters: Fast={KLINGER_FAST}, Slow={KLINGER_SLOW}, Signal={KLINGER_SIGNAL}")
        print(f" • Adaptive Mode: {'ENABLED ✓' if ADAPTIVE_KLINGER_LOOKBACK else 'DISABLED'}")
        if ADAPTIVE_KLINGER_LOOKBACK:
            print(f"   - Short params: Fast={KLINGER_FAST_SHORT}, Slow={KLINGER_SLOW_SHORT}, Signal={KLINGER_SIGNAL_SHORT}")
        if KLINGER_PAPER_MODE:
            print(f" • ✗ PAPER MODE: Logging only, NOT filtering alerts")
    print()
    print(f"💾 CACHING SYSTEM:")
    if ENABLE_CANDLE_CACHE:
        print(f" • Status: ENABLED ✓")
        print(f" • Directory: {CACHE_DIRECTORY}")
        print(f" • Min Candles: {MIN_CANDLES_FOR_KLINGER}")
        print(f" • Cache Expiry: {CACHE_EXPIRY_DAYS} days")
        print(f" • Adaptive Klinger: {'ENABLED ✓' if ADAPTIVE_KLINGER_LOOKBACK else 'DISABLED'}")
    else:
        print(f" • Status: DISABLED ✗")
    print()
    print(f"⚡ FAST TRADING CONFIGURATION:")
    if ENABLE_FAST_TRADING:
        print(f" • Timeframe: {FAST_TRADE_TIMEFRAME}")
        print(f" • Bollinger: Period={BOLLINGER_PERIOD}, Std={BOLLINGER_STD}")
        print(f" • Squeeze Threshold: {BOLLINGER_SQUEEZE_THRESHOLD}%")
        print(f" • Max Symbols: {FAST_TRADE_MAX_SYMBOLS}")
        print(f" • Capital per Trade: ₹{FAST_TRADE_CAPITAL_PER_TRADE:,}")
    print()
    print(f"🚨 EXIT MANAGEMENT:")
    print(f" • Exit Management: {'ENABLED ✓' if ENABLE_EXIT_MANAGEMENT else 'DISABLED ✗'}")
    if ENABLE_EXIT_MANAGEMENT:
        print(f" • Max Daily Loss: ₹{MAX_DAILY_LOSS:,} | Max Daily Profit: ₹{MAX_DAILY_PROFIT:,}")
        print(f" • Trailing Stop: {'ON' if ENABLE_TRAILING_STOP else 'OFF'} @ {TRAILING_STOP_PERCENTAGE}% (activates at {TRAILING_STOP_ACTIVATION}% profit)")
        print(f" • Target Multiplier: {TARGET_PROFIT_MULTIPLIER}x risk")
        print(f" • Time-based Exit: {EXIT_START_TIME} | Expiry Exit: {EXPIRY_EXIT_TIME}")
        print(f" • Position Check Interval: {POSITION_MONITORING_INTERVAL}s")
    print()
    print(f"⚙️ SETTINGS:")
    print(f" Max Orders/Day: {MAX_ORDERS_PER_DAY} | Size: {ORDER_QUANTITY} LOTS")
    print(f" Product: {ORDER_PRODUCT} | Stop-Loss (Premium): {STOPLOSS_PERCENTAGE}%")
    print("="*120 + "\n")

def verify_token(token, verbose=True):
    """Verify API token and return validation status.

    HTTP response codes from /v2/user/profile:
      200 -> token valid
      401 -> token expired / invalid  (only case that means bad token)
      403 -> Upstox IP restriction (UDAPI1154) — the TOKEN IS VALID, but the
             app has static-IP whitelisting enabled. Do NOT reject the token;
             proceed and let order calls fail with their own 403 if needed.
      other -> unexpected; warn but still proceed so OAuth token is not wasted.

    JWT exp field (22:00 IST) is informational only — Upstox servers honour
    tokens until ~03:30 IST next day. Never block on it.
    """
    if verbose:
        print("\U0001f50d Verifying API token...")

    # Soft JWT decode — informational only, never fatal
    try:
        import base64 as _b64, json as _json
        parts = token.split(".")
        if len(parts) == 3:
            pad = parts[1] + "=" * (4 - len(parts[1]) % 4)
            payload = _json.loads(_b64.b64decode(pad).decode("utf-8"))
            exp_ts = payload.get("exp")
            if exp_ts and verbose:
                exp_dt = datetime.fromtimestamp(exp_ts, tz=_IST).replace(tzinfo=None)
                mins_left = int((exp_dt - now_ist()).total_seconds() / 60)
                hm = exp_dt.strftime("%H:%M")
                now_hm = now_ist().strftime("%H:%M")
                if mins_left < 0:
                    print(f"\u26a0\ufe0f  JWT exp field: {hm} IST (now {now_hm}) "
                          f"\u2014 Upstox servers stay live until ~03:30 IST; confirming via API...")
                else:
                    print(f"\u23f1  JWT exp: {hm} IST ({mins_left} min remaining)")
    except Exception:
        pass

    url = "https://api.upstox.com/v2/user/profile"
    try:
        response = _get_upstox_session(token).get(url, timeout=10)

        if response.status_code == 200:
            data = response.json()
            if verbose:
                print("\u2705 Token is VALID")
                if "data" in data:
                    uname = data["data"].get("user_name", "N/A")
                    uid   = data["data"].get("user_id", "N/A")
                    print(f" User: {uname} (ID: {uid})\n")
            return {"valid": True, "data": data.get("data", {}),
                    "message": "Token is valid"}

        elif response.status_code == 401:
            if verbose:
                print("\u274c Token REJECTED by Upstox API (401) \u2014 needs fresh login")
                print("   \u27a1 Update UPSTOX_TOKEN secret or re-run OAuth")
            return {"valid": False, "message": "Token is invalid or expired",
                    "status_code": 401}

        elif response.status_code == 403:
            # IP restriction (UDAPI1154): token is fine, IP is blocked.
            # Bot proceeds normally; order calls will also get 403 until
            # IP whitelisting is disabled in the Upstox developer portal.
            if verbose:
                print("\u2705 Token is VALID (profile blocked by Upstox IP restriction UDAPI1154)")
                print("   \u26a0\ufe0f  To fix: disable static-IP whitelist at "
                      "account.upstox.com/developer/apps")
            return {"valid": True, "data": {},
                    "message": "Token valid; IP restriction active (UDAPI1154)"}

        else:
            if verbose:
                print(f"\u26a0\ufe0f  Unexpected response {response.status_code} from profile "
                      f"API \u2014 proceeding with token anyway")
            return {"valid": True, "data": {},
                    "message": f"Unexpected status {response.status_code}; token assumed valid"}

    except requests.exceptions.Timeout:
        if verbose:
            print("\u26a0\ufe0f  Token verification timed out \u2014 proceeding with token")
        return {"valid": True, "data": {}, "message": "Verification timeout; token assumed valid"}
    except requests.exceptions.RequestException as e:
        if verbose:
            print(f"\u26a0\ufe0f  Token verification network error: {e} \u2014 proceeding")
        return {"valid": True, "data": {}, "message": f"Network error: {e}; token assumed valid"}
    except Exception as e:
        if verbose:
            print(f"\u26a0\ufe0f  Token verification unexpected error: {e} \u2014 proceeding")
        return {"valid": True, "data": {}, "message": f"Error: {e}; token assumed valid"}


def extract_fii_dii_data():
    global FII_DII_DATA, FII_DII_LAST_UPDATE, FII_DII_STRONG_BUY, FII_DII_STRONG_SELL, FII_DII_MIXED
    print(f"\n{'='*100}")
    print("🔍 EXTRACTING FII/DII DATA FROM MUNAFASUTRA")
    print(f"{'='*100}")
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    try:
        response = requests.get(FII_DII_URL, headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        container = soup.find('div', {'id': 'allFIIDII'})
        if not container:
            container = soup.find('div', {'class': 'wideTable'})
        table = container.find('table') if container else soup.find('table')
        if not table:
            print("❌ Table not found")
            return load_fii_dii_from_cache()
        stocks = []
        rows = table.find_all('tr')[1:]
        for row in rows:
            cols = row.find_all('td')
            if len(cols) >= 5:
                company_cell = cols[0]
                link = company_cell.find('a')
                text = link.get_text(strip=True) if link else company_cell.get_text(strip=True)
                if '(' in text and ')' in text:
                    symbol = text.split('(')[-1].replace(')', '').strip()
                    name = text.split('(')[0].strip()
                else:
                    name = text
                    symbol = ""
                if not symbol:
                    continue
                stock = {
                    'Date': now_ist().strftime('%Y-%m-%d'),
                    'Symbol': symbol,
                    'Stock_Name': name,
                    'FII_DII_Cash': cols[1].get_text(strip=True),
                    'FII_DII_FNO': cols[2].get_text(strip=True),
                    'Price_Change': cols[3].get_text(strip=True),
                    'Current_Price': cols[4].get_text(strip=True).replace(',', '')
                }
                stocks.append(stock)
        if not stocks:
            return load_fii_dii_from_cache()
        df = pd.DataFrame(stocks)
        filename = f"FII_DII_{now_ist().strftime('%Y%m%d')}.csv"
        df.to_csv(filename, index=False)
        FII_DII_DATA = {row['Symbol']: row for _, row in df.iterrows()}
        FII_DII_LAST_UPDATE = now_ist()
        FII_DII_STRONG_BUY = set(df[(df['FII_DII_Cash'] == 'Bought') & (df['FII_DII_FNO'] == 'Bought')]['Symbol'].values)
        FII_DII_STRONG_SELL = set(df[(df['FII_DII_Cash'] == 'Sold') & (df['FII_DII_FNO'] == 'Sold')]['Symbol'].values)
        FII_DII_MIXED = set(df['Symbol'].values) - FII_DII_STRONG_BUY - FII_DII_STRONG_SELL
        print(f"✅ Extracted {len(df)} stocks")
        print(f"💪 STRONG BUY: {len(FII_DII_STRONG_BUY)} stocks")
        print(f"🔴 STRONG SELL: {len(FII_DII_STRONG_SELL)} stocks")
        print(f"⚠️  MIXED: {len(FII_DII_MIXED)} stocks")
        if FII_DII_STRONG_BUY:
            print(f"\n📈 Top 10 Strong Buy Stocks:")
            strong_buy_df = df[df['Symbol'].isin(FII_DII_STRONG_BUY)].copy()
            strong_buy_df['PC'] = strong_buy_df['Price_Change'].str.replace('%', '').astype(float)
            for _, row in strong_buy_df.nlargest(10, 'PC').iterrows():
                print(f"   {row['Symbol']:12} | {row['Price_Change']:>7} | ₹{row['Current_Price']}")
        save_fii_dii_to_cache()
        # Run multi-day trend analysis after saving today's data
        if ENABLE_FII_DII_TREND_FILTER:
            analyze_fii_dii_trends()
        return df
    except Exception as e:
        print(f"❌ Error extracting FII/DII: {e}")
        return load_fii_dii_from_cache()

# FIXED: save_fii_dii_to_cache now handles pandas Series correctly
def save_fii_dii_to_cache():
    try:
        # Convert any Series/DataFrame values to plain dicts
        serializable_data = {}
        for k, v in FII_DII_DATA.items():
            if hasattr(v, 'to_dict'):
                serializable_data[k] = v.to_dict()
            elif isinstance(v, dict):
                serializable_data[k] = {
                    dk: (dv.item() if hasattr(dv, 'item') else dv) 
                    for dk, dv in v.items()
                }
            else:
                serializable_data[k] = v

        with open(FII_DII_CACHE_FILE, 'w') as f:
            json.dump({
                'data': serializable_data,
                'strong_buy': list(FII_DII_STRONG_BUY),
                'strong_sell': list(FII_DII_STRONG_SELL),
                'mixed': list(FII_DII_MIXED),
                'last_update': FII_DII_LAST_UPDATE.isoformat() if FII_DII_LAST_UPDATE else None
            }, f)
    except Exception as e:
        if DEBUG_MODE:
            print(f"⚠️ Cache save error: {e}")

def load_fii_dii_from_cache():
    global FII_DII_DATA, FII_DII_LAST_UPDATE, FII_DII_STRONG_BUY, FII_DII_STRONG_SELL, FII_DII_MIXED
    if os.path.exists(FII_DII_CACHE_FILE):
        try:
            print("📂 Loading FII/DII from cache...")
            with open(FII_DII_CACHE_FILE, 'r') as f:
                cache = json.load(f)
                FII_DII_DATA = cache.get('data', {})
                FII_DII_STRONG_BUY = set(cache.get('strong_buy', []))
                FII_DII_STRONG_SELL = set(cache.get('strong_sell', []))
                FII_DII_MIXED = set(cache.get('mixed', []))
                if cache.get('last_update'):
                    FII_DII_LAST_UPDATE = datetime.fromisoformat(cache['last_update'])
                print(f"✅ Loaded cache from {FII_DII_LAST_UPDATE}")
                # Also restore trend sets from their own cache file
                if ENABLE_FII_DII_TREND_FILTER:
                    _load_fii_dii_trend_cache()
                return pd.DataFrame(list(FII_DII_DATA.values())) if FII_DII_DATA else None
        except Exception as e:
            if DEBUG_MODE:
                print(f"❌ Cache load error: {e}")
    return None


def analyze_fii_dii_trends():
    """
    Load all historical FII_DII_YYYYMMDD.csv files and detect multi-day
    institutional patterns. Updates the four global trend sets.

    Patterns detected:
      STRONG_ACCUMULATION : Both FII cash + FNO bought today
      FII_BUY_DII_SELL    : FII cash bought, FNO sold (FII leading momentum)
      FII_SELL_DII_BUY    : FII cash sold, FNO bought (DII absorbing selling)
      UNUSUAL_CHANGE      : Today reversed vs previous day on both legs

    Also persists results to FII_DII_TREND_CACHE_FILE so they survive restarts.
    """
    global FII_DII_TREND_STRONG_ACCUMULATION, FII_DII_TREND_FII_BUY_DII_SELL
    global FII_DII_TREND_FII_SELL_DII_BUY, FII_DII_TREND_UNUSUAL_CHANGE

    import glob

    try:
        files = sorted(glob.glob("FII_DII_*.csv"))
        if len(files) < 1:
            if DEBUG_MODE:
                print("FII/DII trend: no CSV files found -- trends unavailable")
            _load_fii_dii_trend_cache()
            return

        df_list = []
        for fp in files:
            date_str = fp.replace('FII_DII_', '').replace('.csv', '')
            try:
                file_date = datetime.strptime(date_str, '%Y%m%d').date()
            except Exception:
                continue
            try:
                tmp = pd.read_csv(fp)
                tmp['Date'] = file_date
                df_list.append(tmp)
            except Exception:
                continue

        if not df_list:
            _load_fii_dii_trend_cache()
            return

        combined = pd.concat(df_list, ignore_index=True)

        # Fix 2: Drop duplicate (Date, Symbol) rows that appear when the bot is
        # run multiple times on the same day — keep the last occurrence (most recent).
        if 'Symbol' in combined.columns and 'Date' in combined.columns:
            combined = combined.drop_duplicates(subset=['Date', 'Symbol'], keep='last')

        # Fix 4: Price_Change conversion is not used downstream — only convert
        # if the column exists, inside a guard so missing column never raises.
        # (Conversion kept for completeness; result not currently referenced.)
        if 'Price_Change' in combined.columns:
            combined['Price_Change'] = pd.to_numeric(
                combined['Price_Change'].astype(str)
                    .str.replace('%', '', regex=False)
                    .str.strip(),
                errors='coerce'
            )

        dates = sorted(combined['Date'].unique())
        latest_date = dates[-1]
        prev_date   = dates[-2] if len(dates) >= 2 else None

        latest = combined[combined['Date'] == latest_date]
        prev   = combined[combined['Date'] == prev_date] if prev_date else pd.DataFrame()

        strong_acc   = set()
        fii_buy_sell = set()
        fii_sell_buy = set()
        unusual      = set()

        for _, row in latest.iterrows():
            symbol = row.get('Symbol', '')
            if not symbol:
                continue
            cash = str(row.get('FII_DII_Cash', '')).strip()
            fno  = str(row.get('FII_DII_FNO',  '')).strip()

            if cash == 'Bought' and fno == 'Bought':
                strong_acc.add(symbol)
            elif cash == 'Bought' and fno == 'Sold':
                fii_buy_sell.add(symbol)
            elif cash == 'Sold' and fno == 'Bought':
                fii_sell_buy.add(symbol)

            if not prev.empty:
                prev_row = prev[prev['Symbol'] == symbol]
                if not prev_row.empty:
                    prev_cash = str(prev_row.iloc[0].get('FII_DII_Cash', '')).strip()
                    prev_fno  = str(prev_row.iloc[0].get('FII_DII_FNO',  '')).strip()
                    # Pattern 1: Sudden institutional buy (both sold → both bought)
                    if (prev_cash, prev_fno) == ('Sold', 'Sold') and (cash, fno) == ('Bought', 'Bought'):
                        unusual.add(symbol)
                    # Pattern 2: FII flip to lead (FII sell/DII buy → FII buy/DII sell)
                    if (prev_cash, prev_fno) == ('Sold', 'Bought') and (cash, fno) == ('Bought', 'Sold'):
                        unusual.add(symbol)
                    # Pattern 3: Sudden institutional exit (both bought → both sold)
                    if (prev_cash, prev_fno) == ('Bought', 'Bought') and (cash, fno) == ('Sold', 'Sold'):
                        unusual.add(symbol)
                    # Pattern 4: DII flip to lead (FII buy/DII sell → FII sell/DII buy)
                    if (prev_cash, prev_fno) == ('Bought', 'Sold') and (cash, fno) == ('Sold', 'Bought'):
                        unusual.add(symbol)

        with FII_DII_TREND_LOCK:
            FII_DII_TREND_STRONG_ACCUMULATION = strong_acc
            FII_DII_TREND_FII_BUY_DII_SELL    = fii_buy_sell
            FII_DII_TREND_FII_SELL_DII_BUY    = fii_sell_buy
            FII_DII_TREND_UNUSUAL_CHANGE      = unusual

        _save_fii_dii_trend_cache()

        print(f"\n FII/DII TREND ANALYSIS (using {len(files)} days of data):")
        print(f"   Strong Accumulation : {len(strong_acc)} stocks"
              + (f" -- {', '.join(sorted(strong_acc)[:8])}" if strong_acc else ""))
        print(f"   FII Buy / DII Sell  : {len(fii_buy_sell)} stocks"
              + (f" -- {', '.join(sorted(fii_buy_sell)[:8])}" if fii_buy_sell else ""))
        print(f"   FII Sell / DII Buy  : {len(fii_sell_buy)} stocks"
              + (f" -- {', '.join(sorted(fii_sell_buy)[:8])}" if fii_sell_buy else ""))
        print(f"   Unusual Reversal    : {len(unusual)} stocks"
              + (f" -- {', '.join(sorted(unusual)[:8])}" if unusual else ""))

    except Exception as e:
        print(f"FII/DII trend analysis error: {e}")
        _load_fii_dii_trend_cache()


def _save_fii_dii_trend_cache():
    """Persist trend sets to JSON so they survive restarts."""
    try:
        with FII_DII_TREND_LOCK:
            payload = {
                'strong_accumulation': list(FII_DII_TREND_STRONG_ACCUMULATION),
                'fii_buy_dii_sell':    list(FII_DII_TREND_FII_BUY_DII_SELL),
                'fii_sell_dii_buy':    list(FII_DII_TREND_FII_SELL_DII_BUY),
                'unusual_change':      list(FII_DII_TREND_UNUSUAL_CHANGE),
                'saved_at':            now_ist().isoformat(),
            }
        with open(FII_DII_TREND_CACHE_FILE, 'w') as f:
            json.dump(payload, f)
    except Exception as e:
        if DEBUG_MODE:
            print(f"FII/DII trend cache save error: {e}")


def _load_fii_dii_trend_cache():
    """Load trend sets from JSON cache (fallback when CSV files unavailable)."""
    global FII_DII_TREND_STRONG_ACCUMULATION, FII_DII_TREND_FII_BUY_DII_SELL
    global FII_DII_TREND_FII_SELL_DII_BUY, FII_DII_TREND_UNUSUAL_CHANGE
    if not os.path.exists(FII_DII_TREND_CACHE_FILE):
        return
    try:
        with open(FII_DII_TREND_CACHE_FILE) as f:
            c = json.load(f)
        with FII_DII_TREND_LOCK:
            FII_DII_TREND_STRONG_ACCUMULATION = set(c.get('strong_accumulation', []))
            FII_DII_TREND_FII_BUY_DII_SELL    = set(c.get('fii_buy_dii_sell',    []))
            FII_DII_TREND_FII_SELL_DII_BUY    = set(c.get('fii_sell_dii_buy',    []))
            FII_DII_TREND_UNUSUAL_CHANGE      = set(c.get('unusual_change',      []))
        print(f"FII/DII trend cache loaded (saved: {c.get('saved_at','?')})")
    except Exception as e:
        if DEBUG_MODE:
            print(f"FII/DII trend cache load error: {e}")


def get_fii_dii_trend_score(symbol):
    """
    Return an integer score reflecting multi-day FII/DII institutional stance.
    Scores stack -- e.g. strong accumulation + unusual change = +4.

      +2 : Strong accumulation (both bought today)
      +2 : Unusual reversal (sudden buy after sell)
      +1 : FII leading buy (cash bought, FNO sold)
      -1 : FII distributing (cash sold, FNO bought)
       0 : No trend data / neutral
    """
    score = 0
    with FII_DII_TREND_LOCK:
        if symbol in FII_DII_TREND_STRONG_ACCUMULATION:
            score += FII_DII_SCORE_STRONG_ACC
        if symbol in FII_DII_TREND_FII_BUY_DII_SELL:
            score += FII_DII_SCORE_FII_BUY
        if symbol in FII_DII_TREND_FII_SELL_DII_BUY:
            score += FII_DII_SCORE_FII_SELL
        if symbol in FII_DII_TREND_UNUSUAL_CHANGE:
            score += FII_DII_SCORE_UNUSUAL
    return score


def get_fii_dii_signal(symbol):
    if symbol in FII_DII_STRONG_BUY:
        return 'STRONG_BUY'
    elif symbol in FII_DII_STRONG_SELL:
        return 'STRONG_SELL'
    elif symbol in FII_DII_DATA:
        data = FII_DII_DATA[symbol]
        if data['FII_DII_Cash'] == 'Bought' or data['FII_DII_FNO'] == 'Bought':
            return 'BUY'
        elif data['FII_DII_Cash'] == 'Sold' or data['FII_DII_FNO'] == 'Sold':
            return 'SELL'
    return 'NEUTRAL'

def calculate_orb_levels(symbol, open_price, close_price, high_price, low_price, volume,
                         candle_df=None, instrument_key=None):
    """
    Calculate ORB levels with Klinger + RSI quality gate.

    Args:
        candle_df:      optional DataFrame of recent 5-min candles (for RSI gate).
                        If None, the function tries get_realtime_5min_df(symbol).
        instrument_key: NSE_EQ instrument_key used to look up Klinger from R3_LEVELS.
                        If None, falls back to SYMBOL_TO_ISIN.get(symbol).
    """
    body_size = abs(close_price - open_price)
    body_percent = (body_size / open_price) * 100
    is_bullish = close_price > open_price
    is_bearish = close_price < open_price
    if not is_bullish and not is_bearish:
        return None

    # Directional body threshold (slightly higher to filter weak candles)
    min_body = ORB_MIN_CANDLE_BODY_LONG if is_bullish else ORB_MIN_CANDLE_BODY_SHORT
    if body_percent < min_body:
        return None

    if is_bullish:
        breakout_level = close_price
        stop_level     = low_price   # Use candle LOW (tighter, more accurate than open)
        target_level   = close_price + (body_size * ORB_TARGET_MULTIPLIER)
        direction      = 'BUY'
        signal_type    = 'BULLISH_ORB'
    else:
        breakout_level = close_price
        stop_level     = high_price  # Use candle HIGH for shorts
        target_level   = close_price - (body_size * ORB_TARGET_MULTIPLIER)
        direction      = 'SELL'
        signal_type    = 'BEARISH_ORB'

    fii_dii_signal = get_fii_dii_signal(symbol)

    # ── FII/DII confidence ──────────────────────────────────────────────────
    if is_bullish and fii_dii_signal == 'STRONG_BUY':
        confidence = 'VERY_HIGH'
    elif not is_bullish and fii_dii_signal == 'STRONG_SELL':
        confidence = 'VERY_HIGH'
    elif is_bullish and fii_dii_signal == 'BUY':
        confidence = 'HIGH'
    elif not is_bullish and fii_dii_signal == 'SELL':
        confidence = 'HIGH'
    else:
        confidence = 'MEDIUM'

    if ORB_ENABLE_FII_DII_FILTER and confidence == 'MEDIUM':
        return None

    # ── Resolve instrument_key for Klinger lookup ────────────────────────────
    # R3_LEVELS is keyed by instrument_key (e.g. NSE_EQ|INE...), not symbol.
    ikey = instrument_key or SYMBOL_TO_ISIN.get(symbol)

    # ── Klinger gate ────────────────────────────────────────────────────────
    if ORB_ENABLE_KLINGER_GATE:
        klinger_info = R3_LEVELS.get(ikey, {}).get('klinger') if ikey else None
        ko = klinger_info.get('klinger') if klinger_info else None
        if ko is not None:
            if is_bullish and ko < 0:
                # Klinger still negative — only allow VERY_HIGH (strong FII alignment)
                if confidence != 'VERY_HIGH':
                    if DEBUG_MODE:
                        print(f"⛔ ORB KLINGER gate: {symbol} LONG suppressed "
                              f"(KO={ko:,.0f} < 0, confidence={confidence})")
                    return None
            elif not is_bullish and ko > 0:
                if confidence != 'VERY_HIGH':
                    if DEBUG_MODE:
                        print(f"⛔ ORB KLINGER gate: {symbol} SHORT suppressed "
                              f"(KO={ko:,.0f} > 0, confidence={confidence})")
                    return None

    # ── RSI gate ─────────────────────────────────────────────────────────────
    # Use caller-supplied candle_df, or fall back to the real-time builder.
    rsi_value = None
    if ORB_ENABLE_RSI_GATE:
        df_for_rsi = candle_df
        if df_for_rsi is None:
            df_for_rsi = get_realtime_5min_df(symbol, min_bars=15)
        if df_for_rsi is not None and len(df_for_rsi) >= 15:
            try:
                rsi_value = calculate_rsi(df_for_rsi, period=14)
            except Exception:
                rsi_value = None

    if ORB_ENABLE_RSI_GATE and rsi_value is not None:
        if is_bullish and rsi_value < ORB_RSI_LONG_MIN:
            if confidence != 'VERY_HIGH':
                if DEBUG_MODE:
                    print(f"⛔ ORB RSI gate: {symbol} LONG suppressed "
                          f"(RSI={rsi_value:.1f} < {ORB_RSI_LONG_MIN}, confidence={confidence})")
                return None
        elif not is_bullish and rsi_value > ORB_RSI_SHORT_MAX:
            if confidence != 'VERY_HIGH':
                if DEBUG_MODE:
                    print(f"⛔ ORB RSI gate: {symbol} SHORT suppressed "
                          f"(RSI={rsi_value:.1f} > {ORB_RSI_SHORT_MAX}, confidence={confidence})")
                return None

    risk   = abs(breakout_level - stop_level)
    reward = abs(target_level   - breakout_level)
    if risk <= 0:
        return None

    # ── Risk:Reward gate ──────────────────────────────────────────────────────
    # Reject setups that risk more than they aim to make (e.g. the TVSMOTOR
    # 15-Jun ORB had R:R 0.98:1). Applies to every ORB entry regardless of
    # confidence — R:R is a risk constraint, not a momentum filter.
    if ORB_ENABLE_RR_GATE and (reward / risk) < ORB_MIN_RISK_REWARD:
        if DEBUG_MODE:
            print(f"⛔ ORB R:R gate: {symbol} R:R {reward / risk:.2f} < {ORB_MIN_RISK_REWARD}")
        return None

    # Snapshot Klinger KO value for logging (already resolved above)
    klinger_info_snap = R3_LEVELS.get(ikey, {}).get('klinger') if ikey else None
    ko_snap = klinger_info_snap.get('klinger') if klinger_info_snap else None

    result = {
        'symbol':          symbol,
        'instrument_key':  ikey,
        'timestamp':       now_ist(),
        'signal_type':     signal_type,
        'direction':       direction,
        'open':            open_price,
        'close':           close_price,
        'high':            high_price,
        'low':             low_price,
        'body_size':       body_size,
        'body_percent':    body_percent,
        'breakout_level':  breakout_level,
        'stop_level':      stop_level,
        'target_level':    target_level,
        'volume':          volume,
        'is_bullish':      is_bullish,
        'risk':            risk,
        'reward':          reward,
        'risk_reward':     reward / risk,
        'fii_dii_signal':  fii_dii_signal,
        'confidence':      confidence,
        'rsi_at_signal':   rsi_value,
        'klinger_at_signal': ko_snap,
        'signal_time':     now_ist(),   # used by check_orb_reversal window guard
    }
    return result

def process_first_candles(access_token, live_data, late_pass=False):
    """
    Build ORB signals from the first 5-minute candle.

    Called in two modes:
      1. Primary pass (late_pass=False) at 09:20–09:25 — processes all stocks.
         Symbols with zero volume are added to ORB_LATE_CHECKED for retry.
      2. Late pass (late_pass=True) at 09:25 until the breakout window closes —
         only retries symbols in ORB_LATE_CHECKED that still lack a signal and
         now have volume.  Once a symbol gets a signal (or volume stays zero all
         the way to the window close) it is removed from ORB_LATE_CHECKED.
    """
    global ORB_SIGNALS, ORB_PROCESSED_TODAY, ORB_LATE_CHECKED
    if not late_pass:
        print(f"\n{'='*100}")
        print("📊 PROCESSING FIRST 5-MINUTE CANDLES FOR ORB STRATEGY")
        print(f"{'='*100}\n")
        ORB_LATE_CHECKED.clear()          # fresh slate each trading day
    else:
        if not ORB_LATE_CHECKED:
            return                        # nothing left to retry — skip immediately
        print(f"\n🔄 ORB late-volume pass ({now_ist().strftime('%H:%M')}) — "
              f"retrying {len(ORB_LATE_CHECKED)} zero-volume symbols from 09:20")

    orb_count = 0
    very_high = 0
    high = 0

    # Late pass iterates only the small ORB_LATE_CHECKED set, not all 171 stocks
    candidates = (
        {sk: live_data[sk] for sk in list(ORB_LATE_CHECKED) if sk in live_data}
        if late_pass else live_data
    )

    for symbol_key, data in candidates.items():
        try:
            symbol = ISIN_TO_SYMBOL.get(symbol_key, symbol_key)
            ltp    = data.get('ltp', 0)
            volume = data.get('volume', 0)

            if volume == 0:
                if not late_pass:
                    ORB_LATE_CHECKED.add(symbol_key)   # remember for retry
                continue

            # Symbol now has volume — remove from retry set regardless of outcome
            ORB_LATE_CHECKED.discard(symbol_key)

            open_price  = data.get('open', ltp)
            close_price = ltp
            high_price  = data.get('high', ltp)
            low_price   = data.get('low', ltp)

            candle_df  = get_realtime_5min_df(symbol, min_bars=15)
            orb_signal = calculate_orb_levels(
                symbol, open_price, close_price, high_price, low_price, volume,
                candle_df=candle_df, instrument_key=symbol_key
            )
            if orb_signal:
                ORB_SIGNALS[symbol] = orb_signal
                orb_count += 1
                if orb_signal['confidence'] == 'VERY_HIGH':
                    very_high += 1
                elif orb_signal['confidence'] == 'HIGH':
                    high += 1
                log_orb_signal(orb_signal)
                if orb_signal['confidence'] in ['VERY_HIGH', 'HIGH']:
                    rsi_str = f"RSI={orb_signal['rsi_at_signal']:.1f}" if orb_signal['rsi_at_signal'] else "RSI=N/A"
                    ko      = orb_signal['klinger_at_signal']
                    ko_str  = f"KO={ko/1e6:.1f}M" if ko is not None else "KO=N/A"
                    tag     = " [LATE]" if late_pass else ""
                    print(f"✅{tag} {symbol:12} | {orb_signal['signal_type']:15} | "
                          f"{orb_signal['confidence']:10} | FII: {orb_signal['fii_dii_signal']:12} | "
                          f"R:R {orb_signal['risk_reward']:.2f}:1 | {rsi_str} | {ko_str}")
        except Exception as e:
            if DEBUG_MODE:
                print(f"ORB Error {symbol_key}: {e}")

    ORB_PROCESSED_TODAY = True
    if orb_count > 0 or not late_pass:
        print(f"\n✅ {'Late pass:' if late_pass else 'Processed'} {orb_count} ORB signals"
              f"{'' if late_pass else f' | VERY HIGH: {very_high} | HIGH: {high}'}"
              f"{f' | Still awaiting volume: {len(ORB_LATE_CHECKED)}' if late_pass and ORB_LATE_CHECKED else ''}")
    if not late_pass:
        if ORB_LATE_CHECKED:
            print(f"   ⏳ {len(ORB_LATE_CHECKED)} stocks had zero volume — will retry until breakout window closes")
        print(f"{'='*100}\n")

def check_orb_breakout(symbol, current_price, current_volume, live_data, access_token=''):
    if symbol not in ORB_SIGNALS or symbol in ORB_ALERTED_STOCKS:
        return None
    orb = ORB_SIGNALS[symbol]
    now = now_ist()
    market_open_920 = now.replace(hour=9, minute=20, second=0, microsecond=0)
    minutes_since_920 = (now - market_open_920).total_seconds() / 60
    if minutes_since_920 < 0 or minutes_since_920 > ORB_BREAKOUT_WINDOW_MINUTES:
        return None

    # ── Volume check: intraday 5-min relative volume (RVOL) ─────────────────
    ikey = orb.get('instrument_key') or SYMBOL_TO_ISIN.get(symbol, '')
    rvol, _, _ = compute_intraday_rvol(symbol, access_token, ikey)
    volume_ratio = rvol if rvol is not None else 0.0
    if rvol is not None and rvol < ORB_VOLUME_CONFIRMATION:
        if DEBUG_MODE:
            print(f"⛔ ORB breakout: {symbol} RVOL {rvol:.2f}x < {ORB_VOLUME_CONFIRMATION}x")
        return None

    # ── Live RSI re-check at breakout moment ────────────────────────────────
    if ORB_ENABLE_RSI_GATE:
        try:
            df = get_realtime_5min_df(symbol, min_bars=15)
            if df is not None and len(df) >= 15:
                live_rsi = calculate_rsi(df, period=14)
                if live_rsi is not None:
                    if orb['is_bullish'] and live_rsi < ORB_RSI_LONG_MIN:
                        if orb['confidence'] != 'VERY_HIGH':
                            if DEBUG_MODE:
                                print(f"⛔ ORB breakout RSI gate: {symbol} LONG "
                                      f"(RSI={live_rsi:.1f} < {ORB_RSI_LONG_MIN} at breakout)")
                            return None
                    elif not orb['is_bullish'] and live_rsi > ORB_RSI_SHORT_MAX:
                        if orb['confidence'] != 'VERY_HIGH':
                            if DEBUG_MODE:
                                print(f"⛔ ORB breakout RSI gate: {symbol} SHORT "
                                      f"(RSI={live_rsi:.1f} > {ORB_RSI_SHORT_MAX} at breakout)")
                            return None
        except Exception:
            pass

    breakout_signal = None
    if orb['is_bullish'] and current_price > orb['breakout_level'] * 1.001:
        breakout_signal = {
            'symbol':        symbol,
            'signal':        'ORB_BREAKOUT',
            'direction':     'BUY',
            'entry_price':   current_price,
            'stop_loss':     orb['stop_level'],
            'target':        orb['target_level'],
            'orb_data':      orb,
            'volume_ratio':  volume_ratio,
            'confidence':    orb['confidence'],
            'fii_dii_signal':orb['fii_dii_signal'],
            'risk':          orb['risk'],
            'reward':        orb['reward'],
            'risk_reward':   orb['risk_reward'],
            'entry_type':    ENTRY_ORB_BULLISH
        }
    elif not orb['is_bullish'] and current_price < orb['breakout_level'] * 0.999:
        breakout_signal = {
            'symbol':        symbol,
            'signal':        'ORB_BREAKDOWN',
            'direction':     'SELL',
            'entry_price':   current_price,
            'stop_loss':     orb['stop_level'],
            'target':        orb['target_level'],
            'orb_data':      orb,
            'volume_ratio':  volume_ratio,
            'confidence':    orb['confidence'],
            'fii_dii_signal':orb['fii_dii_signal'],
            'risk':          orb['risk'],
            'reward':        orb['reward'],
            'risk_reward':   orb['risk_reward'],
            'entry_type':    ENTRY_ORB_BEARISH
        }
    return breakout_signal

def log_orb_signal(signal):
    try:
        with open(ORB_SIGNALS_FILE, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                now_ist().strftime('%Y-%m-%d %H:%M:%S'),
                signal['symbol'],
                signal['signal_type'],
                signal['direction'],
                f"{signal['breakout_level']:.2f}",
                f"{signal['stop_level']:.2f}",
                f"{signal['target_level']:.2f}",
                f"{signal['body_percent']:.2f}",
                f"{signal['risk_reward']:.2f}",
                signal['fii_dii_signal'],
                signal['confidence']
            ])
    except:
        pass

def log_orb_trade(trade, action='ENTRY'):
    try:
        with open(ORB_TRADES_FILE, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                now_ist().strftime('%Y-%m-%d %H:%M:%S'),
                trade['symbol'],
                action,
                trade['direction'],
                f"{trade['entry_price']:.2f}",
                f"{trade['stop_loss']:.2f}",
                f"{trade['target']:.2f}",
                f"{trade.get('volume_ratio', 0):.2f}",
                trade['confidence'],
                trade['fii_dii_signal']
            ])
    except:
        pass

def send_orb_alert(signal, trader=None):
    global ORB_ALERTED_STOCKS, ORB_ORDER_COUNT
    ORB_ALERTED_STOCKS.add(signal['symbol'])
    print("\n" + "="*100)
    print(f"⚡ ORB SIGNAL: {signal['symbol']} ⚡")
    print("="*100)
    print(f"Signal:       {signal['signal']}")
    print(f"Direction:    {signal['direction']}")
    print(f"Confidence:   {signal['confidence']}")
    print(f"FII/DII:      {signal['fii_dii_signal']}")
    print(f"Entry Price:  ₹{signal['entry_price']:.2f}")
    print(f"Stop Loss:    ₹{signal['stop_loss']:.2f}")
    print(f"Target:       ₹{signal['target']:.2f}")
    print(f"Risk:         ₹{signal['risk']:.2f} per share")
    print(f"Reward:       ₹{signal['reward']:.2f} per share")
    print(f"R:R Ratio:    {signal['risk_reward']:.2f}:1")
    print(f"Volume:       {signal['volume_ratio']:.2f}x average")
    orb_d = signal.get('orb_data', {})
    rsi_val = orb_d.get('rsi_at_signal')
    ko_val  = orb_d.get('klinger_at_signal')
    if rsi_val is not None:
        print(f"RSI at entry: {rsi_val:.1f}")
    if ko_val is not None:
        print(f"Klinger (KO): {ko_val:,.0f}")
    print("="*100)
    log_orb_trade(signal, 'ENTRY')
    with open(ORB_LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(f"\n{'='*100}\n")
        f.write(f"ORB ALERT: {now_ist().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Symbol: {signal['symbol']}\n")
        f.write(f"Signal: {signal['signal']} ({signal['direction']})\n")
        f.write(f"Confidence: {signal['confidence']} | FII/DII: {signal['fii_dii_signal']}\n")
        f.write(f"Entry: ₹{signal['entry_price']:.2f} | Stop: ₹{signal['stop_loss']:.2f} | Target: ₹{signal['target']:.2f}\n")
        f.write(f"R:R: {signal['risk_reward']:.2f}:1 | Volume: {signal['volume_ratio']:.2f}x\n")
        f.write(f"{'='*100}\n")
    try:
        with open(ALERT_CSV_FILE, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                now_ist().strftime('%Y-%m-%d %H:%M:%S'),
                signal['symbol'],
                f"ORB_{signal['direction']}",
                signal['entry_price'],
                signal['volume_ratio'],
                '',
                signal['confidence'],
                signal['fii_dii_signal']
            ])
    except:
        pass
    if ENABLE_AUTO_TRADING and trader and ORB_ORDER_COUNT < MAX_ORDERS_PER_DAY:
        if not is_order_time_allowed():
            print(f"⏭️  ORB {signal['symbol']}: order skipped — outside Upstox service hours (05:30–23:59 IST)")
            return
        print(f"\n📤 Placing ORB {signal['direction']} order for {signal['symbol']}...")
        orb_breakout = {
            'symbol':        signal['symbol'],
            'instrument_key': signal.get('instrument_key', signal.get('orb_data', {}).get('instrument_key', '')),
            'breakout_type': 'CE' if signal['direction'] == 'BUY' else 'PE',
            'strategy':      'ORB',
            'entry_price':   signal['entry_price'],
            'stop_loss':     signal['stop_loss'],
            'target':        signal['target'],
            'klinger_status': signal.get('orb_data', {}).get('klinger_at_signal'),
        }
        order_id = place_breakout_order(orb_breakout, trader)
        if order_id:
            ORB_ORDER_COUNT += 1
            print(f"✅ ORB order placed: {order_id} | ORB orders today: {ORB_ORDER_COUNT}/{MAX_ORDERS_PER_DAY}")
        else:
            print(f"⚠️ ORB order failed for {signal['symbol']}")
    elif ORB_ORDER_COUNT >= MAX_ORDERS_PER_DAY:
        print(f"⚠️ ORB order limit reached ({ORB_ORDER_COUNT}/{MAX_ORDERS_PER_DAY}) — signal logged only")


def check_orb_reversal(symbol, ltp, volume, live_data, access_token, trader=None):
    """
    Detect a strong price reversal AFTER an ORB signal has been generated.

    WHY THIS EXISTS — MANKIND 03-Jun-2026 case study:
    The bot generated a BEARISH_ORB (SELL) signal at 09:20 with VERY_HIGH confidence
    and STRONG_SELL FII/DII. However the price reversed hard upward after the initial
    bearish candle. The original ORB machinery only looks for continuation of the
    initial signal; it has no mechanism to catch the reversal and take the opposite trade.

    HOW IT WORKS:
    1. A prior ORB signal must exist for the symbol (either direction).
    2. Price must have moved ≥ORB_REVERSAL_MIN_MOVE_PCT% AGAINST the original signal.
    3. The reversal window (ORB_REVERSAL_WINDOW_MINUTES) must not have expired.
    4. For BEARISH→BULLISH flip: detect_topping_reversal on the *inverted* scenario,
       i.e. the price is now bouncing off the LOWER band — use detect_fast_long_setup
       as a proxy, or directly check HA flip via _ha_analyse_symbol.
    5. For BULLISH→BEARISH flip: detect_topping_reversal at upper band.
    6. check_ha_reversal_alerts (HA colour flip + Klinger) is used as secondary gate.
    7. Each symbol fires at most ONE reversal trade per session (ORB_REVERSAL_ALERTED).

    Returns a reversal signal dict (same shape as breakout_signal) or None.
    """
    global ORB_REVERSAL_ALERTED

    if not ORB_ENABLE_REVERSAL_TRADE:
        return None

    if symbol not in ORB_SIGNALS:
        return None

    if symbol in ORB_REVERSAL_ALERTED:
        return None   # already fired reversal today

    orb = ORB_SIGNALS[symbol]
    original_direction = orb.get('direction', '')   # 'BUY' or 'SELL'
    signal_time = orb.get('signal_time')

    # ── Reversal window + cooldown checks ─────────────────────────────────────
    if signal_time is not None:
        elapsed = (now_ist() - signal_time).total_seconds() / 60
        if elapsed > ORB_REVERSAL_WINDOW_MINUTES:
            if DEBUG_MODE:
                print(f"⛔ ORB reversal window expired for {symbol} ({elapsed:.0f}min > {ORB_REVERSAL_WINDOW_MINUTES}min)")
            return None
        # Anti-whipsaw: do not flip the bias within minutes of the ORB signal.
        if elapsed < ORB_REVERSAL_COOLDOWN_MINUTES:
            if DEBUG_MODE:
                print(f"⛔ ORB reversal cooldown for {symbol} ({elapsed:.0f}min < {ORB_REVERSAL_COOLDOWN_MINUTES}min)")
            return None

    # ── Minimum adverse move check ────────────────────────────────────────────
    breakout_level = orb.get('breakout_level', ltp)
    or_level = orb.get('stop_level')   # bullish ORB → OR low; bearish ORB → OR high
    if original_direction == 'SELL':
        # Original signal: bearish. Reversal = price going UP above breakout level.
        adverse_move_pct = (ltp - breakout_level) / breakout_level * 100
        reversal_direction = 'BUY'
        reversal_signal_type = 'ORB_REVERSAL_LONG'
    else:
        # Original signal: bullish. Reversal = price going DOWN below breakout level.
        adverse_move_pct = (breakout_level - ltp) / breakout_level * 100
        reversal_direction = 'SELL'
        reversal_signal_type = 'ORB_REVERSAL_SHORT'

    if adverse_move_pct < ORB_REVERSAL_MIN_MOVE_PCT:
        if DEBUG_MODE:
            print(f"⛔ ORB reversal: {symbol} adverse move {adverse_move_pct:.2f}% < min {ORB_REVERSAL_MIN_MOVE_PCT}%")
        return None

    # ── Require a real break of the opening range, not just a % wobble ─────────
    # Bullish ORB → reversal only if price trades BELOW the OR low (stop_level).
    # Bearish ORB → reversal only if price trades ABOVE the OR high (stop_level).
    if ORB_REVERSAL_REQUIRE_OR_BREAK and or_level:
        if reversal_direction == 'SELL' and ltp >= or_level:
            if DEBUG_MODE:
                print(f"⛔ ORB reversal: {symbol} ltp {ltp:.2f} has not broken OR low {or_level:.2f}")
            return None
        if reversal_direction == 'BUY' and ltp <= or_level:
            if DEBUG_MODE:
                print(f"⛔ ORB reversal: {symbol} ltp {ltp:.2f} has not broken OR high {or_level:.2f}")
            return None

    # ── Resolve instrument key EARLY (needed for candle fetch + Klinger) ──────
    ikey = orb.get('instrument_key') or SYMBOL_TO_ISIN.get(symbol, '')
    klinger_info = R3_LEVELS.get(ikey, {}).get('klinger') if ikey else None

    # ── Fetch 5-min candle data (history + real-time merged) ─────────────────
    # CRITICAL: get_realtime_5min_df() reads ONLY from REALTIME_CANDLES (live
    # tick builder). It starts empty at 09:15 and adds 1 bar every 5 minutes.
    # Timeline vs requirements:
    #   09:20 → 0-1 bars  → returns None (min_bars=10 fails)
    #   10:05 → ~10 bars  → reversal window EXPIRES at this exact moment
    #   11:00 → ~25 bars  → Bollinger works, but window expired 55 min ago
    # Result: reversal can NEVER fire using get_realtime_5min_df.
    #
    # fetch_5min_cached() merges ChartInk historical base (~50 bars from
    # yesterday + today 09:15 onwards) with real-time bars. This gives
    # enough bars for Bollinger bands (needs 25) from market open.
    try:
        df = fetch_5min_cached(access_token, ikey, bars=60, symbol=symbol)
        n = len(df) if df is not None else 0
        if df is None or n < 5:
            if DEBUG_MODE:
                print(f"⛔ ORB reversal: {symbol} insufficient candle data "
                      f"(fetch_5min_cached returned {n} bars)")
            return None
    except Exception as e:
        if DEBUG_MODE:
            print(f"⛔ ORB reversal: {symbol} candle fetch error: {e}")
        return None

    if len(df) < ORB_REVERSAL_CANDLES_MIN:
        if DEBUG_MODE:
            print(f"⛔ ORB reversal: {symbol} too few candles "
                  f"({len(df)} < {ORB_REVERSAL_CANDLES_MIN})")
        return None

    # ── Gate 1: detect_topping_reversal (for BEARISH→BULLISH, check lower band bounce) ──
    # For a BULLISH→BEARISH reversal, detect_topping_reversal directly fits.
    # For BEARISH→BULLISH, we run detect_topping_reversal on the *inverted* df
    # (flip OHLC) to reuse the same upper-band-wick logic on the lower band.
    topping_confirmed = False
    if ORB_REVERSAL_REQUIRE_TOPPING:
        try:
            if reversal_direction == 'SELL':
                # Price rallied and is now potentially topping — standard detect_topping_reversal
                topping_result = detect_topping_reversal(df, klinger_data=klinger_info, strict=False)
                topping_confirmed = topping_result is not None
            else:
                # Price sold off and is now potentially bottoming — invert OHLC to reuse function
                df_inv = df.copy()
                df_inv['high']  = -df['low']
                df_inv['low']   = -df['high']
                df_inv['open']  = -df['open']
                df_inv['close'] = -df['close']
                topping_result = detect_topping_reversal(df_inv, klinger_data=klinger_info, strict=False)
                topping_confirmed = topping_result is not None
        except Exception as e:
            if DEBUG_MODE:
                print(f"⛔ ORB reversal: detect_topping_reversal error for {symbol}: {e}")
            topping_confirmed = False

    # ── Gate 2: HA reversal check via _ha_analyse_symbol ─────────────────────
    # check_ha_reversal_alerts is designed to work on ACTIVE_POSITIONS.
    # For ORB (alert-only), we directly call _ha_analyse_symbol which is the
    # underlying per-symbol analyser, and check for the required colour flip.
    ha_confirmed = False
    if ORB_REVERSAL_REQUIRE_HA:
        try:
            # 'LONG' means we hold a long and are checking for a bearish flip.
            # Here we want to detect the OPPOSITE: original signal direction went wrong.
            # e.g. original SELL went wrong → we now want a BULLISH HA flip (colour GREEN)
            ha_watch_signal = 'SHORT' if reversal_direction == 'BUY' else 'LONG'
            ha_result = _ha_analyse_symbol(access_token, symbol, ikey, ha_watch_signal)
            if ha_result is not None:
                ha_confirmed = ha_result.get('needs_alert', False)
                if DEBUG_MODE and ha_confirmed:
                    c2 = ha_result.get('c_prev2', '?')
                    c1 = ha_result.get('c_prev1', '?')
                    cl = ha_result.get('c_last', '?')
                    print(f"✅ ORB reversal HA flip confirmed for {symbol}: [{c2}]→[{c1}]→[{cl}]")
        except Exception as e:
            if DEBUG_MODE:
                print(f"⛔ ORB reversal: HA check error for {symbol}: {e}")
            ha_confirmed = False

    # ── Decision: both gates required (configurable) ──────────────────────────
    if ORB_REVERSAL_REQUIRE_TOPPING and not topping_confirmed:
        if DEBUG_MODE:
            print(f"⛔ ORB reversal: {symbol} topping/bottoming pattern not confirmed")
        return None

    if ORB_REVERSAL_REQUIRE_HA and not ha_confirmed:
        if DEBUG_MODE:
            print(f"⛔ ORB reversal: {symbol} HA colour flip not confirmed")
        return None

    # ── Volume check: intraday 5-min relative volume (RVOL) ─────────────────
    rvol, _, _ = compute_intraday_rvol(symbol, access_token, ikey)
    volume_ratio = rvol if rvol is not None else 0.0
    if rvol is not None and rvol < ORB_VOLUME_CONFIRMATION:
        if DEBUG_MODE:
            print(f"⛔ ORB reversal: {symbol} RVOL {rvol:.2f}x < {ORB_VOLUME_CONFIRMATION}x")
        return None

    # ── Build reversal signal ─────────────────────────────────────────────────
    last_candle = df.iloc[-1]
    if reversal_direction == 'BUY':
        entry_price = ltp
        stop_loss   = last_candle['low'] * 0.997   # just below the recent low
        risk        = entry_price - stop_loss
        if risk <= 0:
            return None
        target      = entry_price + 2.0 * risk
    else:
        entry_price = ltp
        stop_loss   = last_candle['high'] * 1.003  # just above the recent high
        risk        = stop_loss - entry_price
        if risk <= 0:
            return None
        target      = entry_price - 2.0 * risk

    risk_reward = abs(target - entry_price) / risk if risk > 0 else 0

    # Mark as alerted so this reversal only fires once per symbol per session
    ORB_REVERSAL_ALERTED.add(symbol)

    return {
        'symbol':           symbol,
        'signal':           reversal_signal_type,
        'direction':        reversal_direction,
        'entry_price':      entry_price,
        'stop_loss':        stop_loss,
        'target':           target,
        'volume_ratio':     volume_ratio,
        'risk':             risk,
        'reward':           abs(target - entry_price),
        'risk_reward':      risk_reward,
        'confidence':       orb.get('confidence', 'HIGH'),
        'fii_dii_signal':   orb.get('fii_dii_signal', 'NEUTRAL'),
        'orb_data':         orb,
        'adverse_move_pct': adverse_move_pct,
        'topping_confirmed': topping_confirmed,
        'ha_confirmed':     ha_confirmed,
        'entry_type':       'ORB_REVERSAL',
        'original_direction': original_direction,
    }


def send_orb_reversal_alert(signal, trader=None):
    """Print + log an ORB contra/reversal trade alert."""
    global ORB_ORDER_COUNT

    orig_dir = signal.get('original_direction', '?')
    arrow    = '🟢' if signal['direction'] == 'BUY' else '🔴'

    print("\n" + "=" * 100)
    print(f"{arrow} ORB REVERSAL SIGNAL: {signal['symbol']} {arrow}")
    print("=" * 100)
    print(f"  Original ORB direction : {orig_dir}  →  NOW REVERSING to {signal['direction']}")
    print(f"  Signal type            : {signal['signal']}")
    print(f"  Adverse move vs ORB    : {signal['adverse_move_pct']:.2f}%")
    print(f"  Topping/Bottoming patt : {'✅ YES' if signal['topping_confirmed'] else '⚠️ NO'}")
    print(f"  HA colour flip         : {'✅ YES' if signal['ha_confirmed'] else '⚠️ NO'}")
    print(f"  Confidence             : {signal['confidence']}")
    print(f"  FII/DII signal         : {signal['fii_dii_signal']}")
    print(f"  Entry Price            : ₹{signal['entry_price']:.2f}")
    print(f"  Stop Loss              : ₹{signal['stop_loss']:.2f}")
    print(f"  Target                 : ₹{signal['target']:.2f}")
    print(f"  Risk : Reward          : {signal['risk_reward']:.2f}:1")
    print(f"  Volume                 : {signal['volume_ratio']:.2f}x average")
    print("=" * 100)

    log_orb_trade(signal, 'REVERSAL_ENTRY')

    with open(ORB_LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(f"\n{'='*100}\n")
        f.write(f"ORB REVERSAL ALERT: {now_ist().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Symbol: {signal['symbol']} | Original: {orig_dir} → Reversal: {signal['direction']}\n")
        f.write(f"Adverse move: {signal['adverse_move_pct']:.2f}% | Topping: {signal['topping_confirmed']} | HA: {signal['ha_confirmed']}\n")
        f.write(f"Entry: ₹{signal['entry_price']:.2f} | Stop: ₹{signal['stop_loss']:.2f} | Target: ₹{signal['target']:.2f}\n")
        f.write(f"R:R: {signal['risk_reward']:.2f}:1 | Volume: {signal['volume_ratio']:.2f}x\n")
        f.write(f"{'='*100}\n")

    if ENABLE_AUTO_TRADING and trader and ORB_ORDER_COUNT < MAX_ORDERS_PER_DAY:
        if not is_order_time_allowed():
            print(f"⏭️  ORB Reversal {signal['symbol']}: order skipped — outside trading hours")
            return
        print(f"\n📤 Placing ORB REVERSAL {signal['direction']} order for {signal['symbol']}...")
        orb_breakout = {
            'symbol':         signal['symbol'],
            'instrument_key': signal.get('orb_data', {}).get('instrument_key', ''),
            'breakout_type':  'CE' if signal['direction'] == 'BUY' else 'PE',
            'strategy':       'ORB_REVERSAL',
            'entry_price':    signal['entry_price'],
            'stop_loss':      signal['stop_loss'],
            'target':         signal['target'],
            'klinger_status': signal.get('orb_data', {}).get('klinger_at_signal'),
        }
        order_id = place_breakout_order(orb_breakout, trader)
        if order_id:
            ORB_ORDER_COUNT += 1
            print(f"✅ ORB Reversal order placed: {order_id} | ORB orders today: {ORB_ORDER_COUNT}/{MAX_ORDERS_PER_DAY}")
        else:
            print(f"⚠️ ORB Reversal order failed for {signal['symbol']}")
    elif ORB_ORDER_COUNT >= MAX_ORDERS_PER_DAY:
        print(f"⚠️ ORB order limit reached ({ORB_ORDER_COUNT}/{MAX_ORDERS_PER_DAY}) — reversal signal logged only")


def initialize_orb_csv_files():
    """Create ORB signal and trade CSV files with headers if they don't exist."""
    csv_files = [
        (ORB_SIGNALS_FILE, ['Timestamp', 'Symbol', 'Signal_Type', 'Direction',
                            'Breakout_Level', 'Stop_Level', 'Target_Level',
                            'Body_Percent', 'Risk_Reward', 'FII_DII_Signal', 'Confidence']),
        (ORB_TRADES_FILE,  ['Timestamp', 'Symbol', 'Action', 'Direction', 'Price',
                            'Stop_Loss', 'Target', 'Volume_Ratio', 'Confidence', 'FII_DII_Signal'])
    ]
    for csv_file, headers in csv_files:
        if not os.path.exists(csv_file):
            with open(csv_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(headers)

def update_fii_dii_if_needed():
    global FII_DII_LAST_UPDATE
    if not ENABLE_FII_DII_FILTER:
        return
    if FII_DII_LAST_UPDATE is None:
        extract_fii_dii_data()
        return
    # FII/DII data is published once per day after market close.
    # Only re-fetch if the existing data is from a previous calendar day,
    # or if more than FII_DII_UPDATE_INTERVAL seconds have passed (safety net).
    last_date = FII_DII_LAST_UPDATE.date()
    today     = now_ist().date()
    if last_date < today:
        print(f"\n🔄 FII/DII data is from {last_date} — fetching today's data")
        extract_fii_dii_data()
    elif (now_ist() - FII_DII_LAST_UPDATE).total_seconds() > FII_DII_UPDATE_INTERVAL:
        print(f"\n🔄 FII/DII safety refresh (last: {FII_DII_LAST_UPDATE.strftime('%H:%M')})")
        extract_fii_dii_data()

def check_orb_time_and_process(access_token, live_data):
    global ORB_PROCESSED_TODAY, ORB_LATE_CHECKED
    if not ENABLE_ORB_STRATEGY:
        return
    now          = now_ist()
    current_time = now.strftime("%H:%M")
    market_920   = now.replace(hour=9, minute=20, second=0, microsecond=0)
    cutoff       = market_920 + timedelta(minutes=ORB_BREAKOUT_WINDOW_MINUTES)

    if current_time < "09:15":
        ORB_PROCESSED_TODAY = False
        ORB_LATE_CHECKED.clear()
        ORB_REVERSAL_ALERTED.clear()   # reset reversal tracker each morning
        REVERSAL_ALERTED.clear()       # reset OR-reversal tracker each morning
        MIDDAY_BOX_STATE.clear()       # fresh box each day
        MIDDAY_BOX_ALERTED.clear()
        AFTERNOON_ALERTED.clear()
        global MIDDAY_BOX_ORDER_COUNT, AFTERNOON_ORDER_COUNT
        MIDDAY_BOX_ORDER_COUNT = 0
        AFTERNOON_ORDER_COUNT  = 0
        RES_REVERSAL_ALERTED.clear()
        DUAL_TF_BB_ALERTED.clear()
        FIIDII_BRK_ALERTED.clear()
        FII_BB_ALERTED_TODAY.clear()   # daily reset — but FII_BB_ARMED persists
                                       # across days by design (continuous 2-3 day watch)

    # ── PRIMARY PASS ─────────────────────────────────────────────────────────
    # Old: only ran 09:20-09:25. Bot starting at 09:26 silently skipped ORB.
    # New: run primary pass any time between 09:20 and breakout window close,
    # as long as it hasn't run yet today. One-shot — process_first_candles
    # sets ORB_PROCESSED_TODAY=True so it never fires twice.
    if current_time >= "09:20" and now < cutoff and not ORB_PROCESSED_TODAY:
        if current_time >= "09:25":
            print(f"\n⚠️  ORB: Late start detected ({current_time}). "
                  f"Running primary ORB pass now — {int((now - market_920).total_seconds() / 60)}min "
                  f"into session. Signals use current candle data.")
        process_first_candles(access_token, live_data, late_pass=False)

    # ── LATE VOLUME PASS ─────────────────────────────────────────────────────
    # Retry zero-volume symbols from the primary pass until the window closes.
    elif (ORB_PROCESSED_TODAY
          and ORB_LATE_CHECKED
          and current_time >= "09:25"
          and now < cutoff):
        process_first_candles(access_token, live_data, late_pass=True)

def monitor_orb_breakouts(live_data, access_token='', trader=None):
    if not ENABLE_ORB_STRATEGY or not ORB_SIGNALS:
        return
    for symbol_key, data in live_data.items():
        try:
            symbol = ISIN_TO_SYMBOL.get(symbol_key, symbol_key)
            if symbol not in ORB_SIGNALS:
                continue
            ltp = data.get('ltp', 0)
            volume = data.get('volume', 0)
            if ltp == 0:
                continue
            breakout = check_orb_breakout(symbol, ltp, volume, data, access_token)
            if breakout:
                send_orb_alert(breakout, trader)
                continue   # already acting on continuation — skip reversal check

            # ── ORB Reversal check: price moving against original signal ──────
            if ORB_ENABLE_REVERSAL_TRADE and symbol not in ORB_REVERSAL_ALERTED:
                reversal = check_orb_reversal(symbol, ltp, volume, data, access_token, trader)
                if reversal:
                    send_orb_reversal_alert(reversal, trader)
        except Exception as e:
            if DEBUG_MODE:
                print(f"ORB monitor error {symbol_key}: {e}")

def print_orb_summary():
    if not ENABLE_ORB_STRATEGY:
        return
    print(f"\n{'='*100}")
    print("📊 ORB STRATEGY SUMMARY")
    print(f"{'='*100}")
    print(f"Total ORB Signals Generated:  {len(ORB_SIGNALS)}")
    print(f"ORB Alerts Triggered:         {len(ORB_ALERTED_STOCKS)}")
    print(f"ORB Orders Placed:            {ORB_ORDER_COUNT}")
    if ORB_SIGNALS:
        very_high = sum(1 for s in ORB_SIGNALS.values() if s['confidence'] == 'VERY_HIGH')
        high = sum(1 for s in ORB_SIGNALS.values() if s['confidence'] == 'HIGH')
        medium = sum(1 for s in ORB_SIGNALS.values() if s['confidence'] == 'MEDIUM')
        print(f"\nConfidence Breakdown:")
        print(f"  VERY HIGH: {very_high}")
        print(f"  HIGH:      {high}")
        print(f"  MEDIUM:    {medium}")
        bullish = sum(1 for s in ORB_SIGNALS.values() if s['is_bullish'])
        bearish = len(ORB_SIGNALS) - bullish
        print(f"\nDirection Breakdown:")
        print(f"  Bullish Setups:  {bullish}")
        print(f"  Bearish Setups:  {bearish}")
    print(f"{'='*100}\n")

# ══════════════════════════════════════════════════════════════════════════════
# OPENING-RANGE REVERSAL STRATEGY (reversal_strategy.py integration)
# ══════════════════════════════════════════════════════════════════════════════

def _reversal_candles_from_df(df):
    """Convert a 5min OHLCV DataFrame (date/open/high/low/close/volume) into the
    list[dict] shape that reversal_strategy.find_latest_reversal_signal expects."""
    if df is None or len(df) == 0:
        return []
    candles = []
    for _, row in df.iterrows():
        candles.append({
            "timestamp": str(row.get("date", "")),
            "open":   row.get("open", 0),
            "high":   row.get("high", 0),
            "low":    row.get("low", 0),
            "close":  row.get("close", 0),
            "volume": row.get("volume", 0),
        })
    return candles


def _log_reversal_signal(signal):
    """Append one reversal signal to REVERSAL_SIGNALS_FILE (own schema)."""
    header = ['Timestamp', 'Symbol', 'Signal_Type', 'Close', 'Strength',
              'Reason', 'OR_High', 'OR_Low']
    file_exists = os.path.exists(REVERSAL_SIGNALS_FILE)
    try:
        with open(REVERSAL_SIGNALS_FILE, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(header)
            writer.writerow([
                now_ist().strftime('%Y-%m-%d %H:%M:%S'),
                signal.get('symbol', ''),
                signal.get('signal_type', ''),
                f"{float(signal.get('close', 0)):.2f}",
                f"{float(signal.get('strength', 0)):.0f}",
                signal.get('reason', ''),
                f"{float(signal.get('or_high', 0)):.2f}",
                f"{float(signal.get('or_low', 0)):.2f}",
            ])
    except Exception as e:
        if DEBUG_MODE:
            print(f"⚠️ reversal log error: {e}")


def _place_reversal_order(signal, symbol, instrument_key, trader):
    """Place an option order for a reversal signal (REVERSAL_DOWN→PE, REVERSAL_UP→CE).
    Only invoked when ENABLE_REVERSAL_AUTO_TRADING is True."""
    global REVERSAL_ORDER_COUNT
    if REVERSAL_ORDER_COUNT >= MAX_ORDERS_PER_DAY:
        print(f"⏭️  Reversal {symbol}: daily order cap reached "
              f"({REVERSAL_ORDER_COUNT}/{MAX_ORDERS_PER_DAY})")
        return
    breakout_type = 'PE' if signal.get('signal_type') == 'REVERSAL_DOWN' else 'CE'
    print(f"\n📤 Placing REVERSAL {breakout_type} order for {symbol}...")
    order = place_breakout_order({
        'symbol':         symbol,
        'instrument_key': instrument_key,
        'breakout_type':  breakout_type,
        'strategy':       'REVERSAL',
        'entry_price':    signal.get('close', 0),
    }, trader)
    if order:
        REVERSAL_ORDER_COUNT += 1
        print(f"✅ Reversal order placed: {order.get('order_id')} | {symbol} {breakout_type}")
    else:
        print(f"⚠️ Reversal order failed for {symbol}")


def run_reversal_strategy_scan(access_token, live_data, trader=None):
    """STRATEGY=reversal/all — detect opening-range reversal signals on the live
    5min candles built by update_realtime_candle() and log them.

    Signal-only by default; order placement is gated behind ENABLE_REVERSAL_AUTO_TRADING.
    Each symbol fires at most once per day (REVERSAL_ALERTED)."""
    global REVERSAL_SIGNAL_COUNT
    if not ENABLE_REVERSAL_STRATEGY or not _REVERSAL_IMPORT_OK or not live_data:
        return

    params = {
        "opening_range_minutes":      REVERSAL_OPENING_RANGE_BARS,
        "reversal_threshold_percent": REVERSAL_THRESHOLD_PERCENT,
        "min_reversal_volume":        REVERSAL_MIN_VOLUME,
    }

    checked = 0
    for symbol_key in live_data:
        if checked >= REVERSAL_MAX_SYMBOLS:
            break
        symbol = ISIN_TO_SYMBOL.get(symbol_key, symbol_key)
        if symbol in REVERSAL_ALERTED:
            continue
        df = get_realtime_5min_df(symbol, min_bars=REVERSAL_MIN_BARS)
        if df is None:
            continue
        checked += 1
        try:
            signal = find_latest_reversal_signal(_reversal_candles_from_df(df), params=params)
        except Exception as e:
            if DEBUG_MODE:
                print(f"⚠️ reversal scan error {symbol}: {e}")
            continue
        if not signal:
            continue

        REVERSAL_ALERTED.add(symbol)
        REVERSAL_SIGNAL_COUNT += 1
        signal['symbol'] = symbol
        _log_reversal_signal(signal)
        print("\n" + "=" * 100)
        print(f"🔁 REVERSAL SIGNAL: {symbol} — {signal['signal_type']}")
        print(f"   {signal['reason']}")
        print(f"   Close ₹{float(signal['close']):.2f} | Strength {float(signal['strength']):.0f}/100")
        print("=" * 100)

        if ENABLE_REVERSAL_AUTO_TRADING and trader and is_order_time_allowed():
            _place_reversal_order(signal, symbol, symbol_key, trader)


def print_reversal_summary():
    if not ENABLE_REVERSAL_STRATEGY:
        return
    print(f"\n{'='*100}")
    print("🔁 REVERSAL STRATEGY SUMMARY")
    print(f"{'='*100}")
    print(f"Reversal Signals Generated:  {REVERSAL_SIGNAL_COUNT}")
    print(f"Reversal Symbols Alerted:    {len(REVERSAL_ALERTED)}")
    print(f"Reversal Orders Placed:      {REVERSAL_ORDER_COUNT}")
    print(f"{'='*100}\n")


def apply_strategy_selection():
    """Translate the STRATEGY env var (set by the GitHub Actions workflow dropdown)
    onto the per-strategy ENABLE_* flags so the selector actually takes effect.

    Supported values:
      all (default) → every strategy enabled, plus reversal-signal logging
      r3_s3 / box / range / gap / orb / reversal → run that strategy in isolation
    """
    g = globals()
    sel = os.environ.get("STRATEGY", "all").strip().lower() or "all"

    if sel == "all":
        g['ENABLE_REVERSAL_STRATEGY'] = True
        print("📊 STRATEGY=all → all strategies enabled (incl. reversal logging)")
        return

    groups = {
        "r3_s3":    ["ENABLE_AUTO_TRADING"],
        "box":      ["ENABLE_BOX_TRADING", "ENABLE_MIDDAY_BOX"],
        "range":    ["ENABLE_RANGE_TRADING"],
        "gap":      ["ENABLE_GAP_TRADING"],
        "orb":      ["ENABLE_ORB_STRATEGY"],
        "reversal": ["ENABLE_REVERSAL_STRATEGY"],
    }

    if sel not in groups:
        g['ENABLE_REVERSAL_STRATEGY'] = True
        print(f"⚠️  STRATEGY='{sel}' not recognised — defaulting to 'all'")
        return

    all_flags = ["ENABLE_AUTO_TRADING", "ENABLE_BOX_TRADING", "ENABLE_RANGE_TRADING",
                 "ENABLE_GAP_TRADING", "ENABLE_ORB_STRATEGY", "ENABLE_FAST_TRADING",
                 "ENABLE_FII_REVERSAL", "ENABLE_FII_REVERSAL_LONG",
                 "ENABLE_MIDDAY_BOX", "ENABLE_AFTERNOON_PIVOT", "ENABLE_REVERSAL_STRATEGY"]
    for flag in all_flags:
        g[flag] = False
    for flag in groups[sel]:
        g[flag] = True
    print(f"📊 STRATEGY='{sel}' → only {', '.join(groups[sel])} enabled")


def get_token_via_android_oauth() -> str:
    """
    Android-compatible Upstox token refresh using OAuth 2.0 Authorization Code flow.

    Selenium / ChromeDriver does NOT work on Pydroid3 (Android).
    This function replaces that with a simple browser-based flow:

      1. Opens the Upstox login URL in Chrome on your phone.
      2. You log in normally (OTP + PIN) — takes ~30 seconds.
      3. Upstox redirects to https://127.0.0.1/?code=XXXX
      4. You copy that full URL from the Chrome address bar and paste it here.
      5. The bot exchanges the code for an access token via Upstox API.
      6. Token is saved to upstox_token.txt for next run.

    Requires UPSTOX_API_KEY and UPSTOX_API_SECRET to be set above.
    Get them free at https://account.upstox.com/developer/apps

    HOW TO GET API KEY/SECRET (one-time setup, 5 minutes):
      1. Go to https://account.upstox.com/developer/apps
      2. Click "Create New App"
      3. App name: anything (e.g. "MyBot")
      4. Redirect URL: https://127.0.0.1/
      5. Copy API Key (Client ID) and Secret → paste in config above
    """
    import urllib.parse

    if UPSTOX_API_KEY == "YOUR_UPSTOX_API_KEY":
        print("\n❌ UPSTOX_API_KEY not set.")
        print("   Please follow these steps (one-time, 5 minutes):")
        print("   1. Go to https://account.upstox.com/developer/apps")
        print("   2. Create New App → Redirect URL: https://127.0.0.1/")
        print("   3. Copy API Key + Secret → paste in bot config (lines ~45-47)")
        return None

    print("\n" + "=" * 60)
    print("📱 ANDROID OAUTH TOKEN REFRESH")
    print("=" * 60)

    # ── Step 1: Build login URL ───────────────────────────────────────────────
    auth_url = (
        "https://api.upstox.com/v2/login/authorization/dialog"
        f"?response_type=code"
        f"&client_id={UPSTOX_API_KEY}"
        f"&redirect_uri={urllib.parse.quote(UPSTOX_REDIRECT_URI, safe='')}"
    )

    print("\n📋 STEP 1: Open this URL in Chrome on your phone:")
    print(f"\n   {auth_url}\n")

    # Try to open it automatically
    try:
        import webbrowser
        webbrowser.open(auth_url)
        print("   ✅ Chrome should have opened. If not, copy-paste the URL above.")
    except Exception:
        print("   ⚠️  Could not auto-open browser. Copy-paste the URL above into Chrome.")

    print("\n📋 STEP 2: Log in to Upstox (OTP + PIN — takes ~30 seconds)")
    print("   After login, Chrome will show a page like:")
    print("   ❌ This site can't be reached  — that's NORMAL!")
    print("   Look at the address bar — it will show something like:")
    print("   https://127.0.0.1/?code=XXXXXXXXXXXXXXXX&state=...")
    print("\n📋 STEP 3: Copy the FULL URL from the address bar and paste it below.")

    # ── Step 2: Wait for user to paste redirect URL ───────────────────────────
    for attempt in range(3):
        try:
            redirect_url = input("\n   Paste the full redirect URL here: ").strip()
        except EOFError:
            print("   ⚠️  Cannot read input in this environment.")
            return None

        if not redirect_url:
            print("   ⚠️  Empty input — try again.")
            continue

        # Parse the auth code from the URL
        try:
            parsed = urllib.parse.urlparse(redirect_url)
            params = urllib.parse.parse_qs(parsed.query)
            auth_code = params.get("code", [None])[0]
        except Exception:
            auth_code = None

        if not auth_code:
            print(f"   ❌ Could not find 'code=' in URL: {redirect_url[:80]}")
            if attempt < 2:
                print("   Make sure you copied the full URL from the address bar.")
            continue

        print(f"\n   ✅ Auth code found: {auth_code[:20]}...")

        # ── Step 3: Exchange code for access token ────────────────────────────
        print("\n🔄 Exchanging auth code for access token...")
        try:
            token_resp = requests.post(
                "https://api.upstox.com/v2/login/authorization/token",
                headers={
                    "accept":       "application/json",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={
                    "code":          auth_code,
                    "client_id":     UPSTOX_API_KEY,
                    "client_secret": UPSTOX_API_SECRET,
                    "redirect_uri":  UPSTOX_REDIRECT_URI,
                    "grant_type":    "authorization_code",
                },
                timeout=20,
            )
            if token_resp.status_code == 200:
                token_data   = token_resp.json()
                access_token = token_data.get("access_token", "")
                if access_token:
                    print("✅ New access token obtained!")
                    # Save token to file
                    try:
                        with open(UPSTOX_TOKEN_FILE, "w") as f:
                            f.write(access_token)
                        print(f"💾 Token saved to {UPSTOX_TOKEN_FILE}")
                    except Exception as e:
                        print(f"⚠️ Could not save token: {e}")
                    print("\n" + "=" * 60)
                    print("💡 NEXT TIME: Copy this token into HARDCODED_TOKEN in the bot.")
                    print(f"   Token preview: {access_token[:40]}...")
                    print("=" * 60)
                    return access_token
                else:
                    print(f"❌ No access_token in response: {token_resp.text[:200]}")
            else:
                print(f"❌ Token exchange failed ({token_resp.status_code}): {token_resp.text[:200]}")
                if token_resp.status_code == 400:
                    print("   ⚠️  Auth code may have expired (they expire in ~5 minutes).")
                    print("   Run the bot again to get a fresh code.")
                    return None
        except Exception as e:
            print(f"❌ Token exchange error: {e}")

    print("\n❌ OAuth token refresh failed after 3 attempts.")
    return None


def _refresh_upstox_token() -> str:
    """
    Try to refresh the Upstox access token using a saved refresh token.
    Returns new access_token string, or None if refresh fails / no token saved.
    """
    if not os.path.exists(UPSTOX_REFRESH_TOKEN_FILE):
        return None
    try:
        with open(UPSTOX_REFRESH_TOKEN_FILE, "r") as f:
            refresh_token = f.read().strip()
        if not refresh_token:
            return None
        print("🔄 Attempting token refresh via saved refresh_token…")
        resp = requests.post(
            "https://api.upstox.com/v2/login/authorization/token",
            headers={"accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type":    "refresh_token",
                "refresh_token": refresh_token,
                "client_id":     UPSTOX_API_KEY,
                "client_secret": UPSTOX_API_SECRET,
            },
            timeout=15,
        )
        if resp.status_code == 200:
            data         = resp.json()
            access_token = data.get("access_token")
            new_refresh  = data.get("refresh_token", refresh_token)
            if access_token:
                # Persist updated refresh token
                with open(UPSTOX_REFRESH_TOKEN_FILE, "w") as f:
                    f.write(new_refresh)
                with open(UPSTOX_TOKEN_FILE, "w") as f:
                    f.write(access_token)
                print("✅ Token refreshed successfully.")
                return access_token
        print(f"⚠️ Token refresh failed ({resp.status_code}): {resp.text[:100]}")
        return None
    except Exception as exc:
        print(f"⚠️ Token refresh error: {exc}")
        return None


def get_upstox_token():
    """
    Get Upstox access token with smart fallback:
    1. Try hardcoded token if USE_HARDCODED_TOKEN is True
    2. Try saved token from file
    3. Try refresh token (new — no browser needed)
    4. Headless Selenium OAuth (new — fully automated, no manual URL pasting)
    """
    print("=" * 60)
    print("UPSTOX TOKEN MANAGEMENT")
    print("=" * 60)
    print(f"Mobile: {MOBILE_NUMBER}")
    print(f"Email: {EMAIL}")
    print("=" * 60)
    print()

    # STEP 1: Try hardcoded token first if enabled
    if USE_HARDCODED_TOKEN and HARDCODED_TOKEN:
        print("🔑 Step 1: Checking HARDCODED token...")
        print(f"Token preview: {HARDCODED_TOKEN[:30]}...{HARDCODED_TOKEN[-20:]}")

        validation = verify_token(HARDCODED_TOKEN, verbose=True)

        if validation['valid']:
            print("✅ HARDCODED token is VALID - using it!")
            print("=" * 60)
            print()
            try:
                with open(UPSTOX_TOKEN_FILE, 'w') as f:
                    f.write(HARDCODED_TOKEN)
                print(f"💾 Backed up token to {UPSTOX_TOKEN_FILE}")
            except Exception as e:
                print(f"⚠️ Could not backup token: {e}")
            return HARDCODED_TOKEN
        else:
            print(f"❌ HARDCODED token is INVALID: {validation['message']}")
            print("⚠️ Will try other methods...\n")

    # STEP 2: Try saved token from file
    print("🔑 Step 2: Checking SAVED token from file...")
    if os.path.exists(UPSTOX_TOKEN_FILE):
        try:
            with open(UPSTOX_TOKEN_FILE, 'r') as f:
                saved_token = f.read().strip()
            if saved_token:
                print(f"Token preview: {saved_token[:30]}...{saved_token[-20:]}")
                validation = verify_token(saved_token, verbose=True)
                if validation['valid']:
                    print("✅ SAVED token is VALID - using it!")
                    print("=" * 60)
                    print()
                    return saved_token
                else:
                    print(f"❌ SAVED token is INVALID: {validation['message']}")
                    print("⚠️ Will try refresh token...\n")
            else:
                print("⚠️ Token file is empty")
        except Exception as e:
            print(f"❌ Error reading token file: {e}")
    else:
        print(f"⚠️ No saved token file found at {UPSTOX_TOKEN_FILE}")

    # STEP 3: Try refresh token (fast, no browser)
    print("\n🔑 Step 3: Attempting token refresh (no browser needed)...")
    refreshed = _refresh_upstox_token()
    if refreshed:
        validation = verify_token(refreshed, verbose=True)
        if validation['valid']:
            print("✅ Refreshed token is VALID — bot will start now.")
            return refreshed
        else:
            print("❌ Refreshed token failed validation.")

    # STEP 4: Headless Selenium OAuth (fully automated — no manual URL pasting)
    print("\n" + "=" * 60)
    print("🤖 Step 4: HEADLESS SELENIUM OAUTH (fully automated)")
    print("=" * 60)
    print("⚠️  No valid token found. Launching headless Chrome login…")
    print("    Chrome will log in silently — no browser window will appear.")
    print()

    if UPSTOX_API_KEY == "YOUR_UPSTOX_API_KEY":
        print("❌ UPSTOX_API_KEY not set.")
        print("   1. Go to https://account.upstox.com/developer/apps")
        print("   2. Create/open an app → Redirect URL: http://127.0.0.1:8080/")
        print("   3. Paste Client ID into UPSTOX_API_KEY and Client Secret into UPSTOX_API_SECRET")
        return None

    login = UpstoxLogin(
        mobile_number=MOBILE_NUMBER,
        email_address=EMAIL,
        email_password=EMAIL_PASSWORD,
        passcode=PASSCODE,
    )
    new_token = login.perform_oauth_headless()

    if new_token:
        validation = verify_token(new_token, verbose=True)
        if validation['valid']:
            # Persist for next run
            try:
                with open(UPSTOX_TOKEN_FILE, "w") as f:
                    f.write(new_token)
                print(f"💾 Token saved to {UPSTOX_TOKEN_FILE}")
            except Exception:
                pass
            print("✅ Headless token is VALID — bot will start now.")
            return new_token
        else:
            print("❌ Headless token failed validation.")

    print("\n" + "=" * 60)
    print("❌ ALL TOKEN METHODS FAILED")
    print("=" * 60)
    print("\nTo fix:")
    print("  1. Set UPSTOX_API_KEY and UPSTOX_API_SECRET in the bot config")
    print("     (get them at https://account.upstox.com/developer/apps)")
    print("  2. Ensure Chrome/ChromeDriver is installed (pip install webdriver-manager)")
    print("  3. Run the bot — it will log in headlessly and save the token automatically")
    print("  4. Copy the new token into HARDCODED_TOKEN to skip all steps next time")
    return None
# ========== BOLLINGER BAND FAST TRADING FUNCTIONS ==========
def calculate_bollinger_bands(df, period=20, std=2):
    """
    Calculate Bollinger Bands for given dataframe
    """
    if len(df) < period:
        return None, None, None, None, None

    # Only last 100 candles needed — BB uses a 20-period rolling window;
    # trimming avoids processing stale history on every scan.
    if len(df) > 100:
        df = df.tail(100)

    df_copy = df.copy()
    df_copy['MA'] = df_copy['close'].rolling(window=period).mean()
    df_copy['STD'] = df_copy['close'].rolling(window=period).std()
    
    df_copy['BB_UPPER'] = df_copy['MA'] + (df_copy['STD'] * std)
    df_copy['BB_LOWER'] = df_copy['MA'] - (df_copy['STD'] * std)
    df_copy['BB_MIDDLE'] = df_copy['MA']
    
    # Calculate bandwidth (squeeze indicator)
    df_copy['BB_WIDTH'] = (df_copy['BB_UPPER'] - df_copy['BB_LOWER']) / df_copy['BB_MIDDLE']
    
    # Calculate %B
    df_copy['BB_PERCENT_B'] = (df_copy['close'] - df_copy['BB_LOWER']) / (df_copy['BB_UPPER'] - df_copy['BB_LOWER'])
    
    return (df_copy['BB_UPPER'], df_copy['BB_MIDDLE'], df_copy['BB_LOWER'], 
            df_copy['BB_WIDTH'], df_copy['BB_PERCENT_B'])

def calculate_rsi(df, period=14):
    """
    Calculate RSI(period) on the 'close' column of df.
    Returns the last RSI value as a float, or None if insufficient data.
    """
    if len(df) < period + 1:
        return None
    delta = df['close'].diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, float('inf'))
    rsi = 100 - (100 / (1 + rs))
    val = rsi.iloc[-1]
    return float(val) if not np.isnan(val) else None

def detect_bollinger_squeeze(bb_width, threshold=0.15, lookback=10):
    """
    Detect Bollinger Band squeeze
    Returns True if bandwidth is at lowest in lookback period
    """
    if len(bb_width) < lookback:
        return False
    
    current_width = bb_width.iloc[-1]
    min_width = bb_width.iloc[-lookback:].min()
    
    # Check if current width is near minimum
    return current_width <= min_width * (1 + threshold/100)

# ============ CHARTINK 5MIN DATA FETCHER ============
# ChartInk is used as the PRIMARY source for 5-minute candle data.
# Upstox intraday/historical endpoints are used as FALLBACK only.
#
# To refresh cookies: chartink.com → DevTools → Network → any request → copy Cookie header

_CHARTINK_SESSION = None  # Reusable requests.Session for ChartInk

def _get_chartink_session():
    """Return a singleton requests.Session configured for ChartInk."""
    global _CHARTINK_SESSION
    if _CHARTINK_SESSION is None:
        _CHARTINK_SESSION = requests.Session()
        _CHARTINK_SESSION.headers.update({
            "accept": "application/json, text/plain, */*",
            "accept-language": "en-US,en;q=0.9",
            "content-type": "application/x-www-form-urlencoded",
            "origin": "https://chartink.com",
            "referer": "https://chartink.com/stocks-new",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "x-xsrf-token": CHARTINK_COOKIES.get("XSRF-TOKEN", ""),
        })
    return _CHARTINK_SESSION

def _get_upstox_session(access_token: str) -> requests.Session:
    """
    Return a persistent requests.Session for all Upstox REST calls.
    Re-creates session only when the access_token changes (daily rotation).
    Eliminates DNS + TLS handshake overhead on every request (~200-400 ms saved).
    """
    global _UPSTOX_SESSION, _UPSTOX_SESSION_TOKEN
    token = access_token or ""
    if _UPSTOX_SESSION is None or _UPSTOX_SESSION_TOKEN != token:
        _UPSTOX_SESSION = requests.Session()
        _UPSTOX_SESSION.headers.update({
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        })
        _UPSTOX_SESSION_TOKEN = token
    return _UPSTOX_SESSION

def _fetch_5min_from_chartink(symbol, bars=50):
    """
    PRIMARY: Fetch 5-minute OHLCV candles from ChartInk using robust parsing.

    Args:
        symbol: NSE symbol string e.g. 'RELIANCE'
        bars:   Number of bars to request (max ~200)

    Returns:
        pd.DataFrame with columns [date, open, high, low, close, volume] or None
    """
    try:
        session = _get_chartink_session()

        query = (
            f"select open as 'open', high as 'high', low as 'low', "
            f"close as 'close', volume as 'volume' "
            f"where symbol='{symbol}'"
        )

        payload = {
            "query": query,
            "use_live": "1",
            "limit": str(bars),                # <-- Fixed: was hardcoded "1"
            "size": "200",                      # Max candles per batch
            "widget_id": "-1",
            "end_time": "-1",
            "timeframe": "5 minutes",
            "symbol": symbol,
            "scan_link": "null",
        }

        resp = session.post(
            CHARTINK_BASE_URL,
            cookies=CHARTINK_COOKIES,
            data=payload,
            timeout=20,
        )

        if resp.status_code != 200:
            if DEBUG_MODE:
                print(f"⚠️ ChartInk HTTP {resp.status_code} for {symbol}")
            return None

        data = resp.json()

        # --- Robust parsing (inspired by ChartInkDataExtractor) ---
        if "metaData" not in data or not data["metaData"]:
            if DEBUG_MODE:
                print(f"⚠️ ChartInk missing metaData for {symbol}")
            return None

        # 1. timestamps
        trade_times_ms = data["metaData"][0].get("tradeTimes", [])
        if not trade_times_ms:
            if DEBUG_MODE:
                print(f"⚠️ ChartInk no tradeTimes for {symbol}")
            return None

        # tradeTimes are milliseconds in IST epoch.
        # Convert to IST-aware datetime, then strip tz for naive timestamps.
        timestamps = (
            pd.to_datetime(trade_times_ms, unit="ms", utc=True)
            .tz_convert("Asia/Kolkata")
            .tz_localize(None)
        )

        # 2. column data
        if "groupData" not in data or not data["groupData"]:
            if DEBUG_MODE:
                print(f"⚠️ ChartInk missing groupData for {symbol}")
            return None

        results = data["groupData"][0].get("results", [])
        if not results:
            if DEBUG_MODE:
                print(f"⚠️ ChartInk empty results for {symbol}")
            return None

        # Merge column dicts into one dict of lists
        combined = {}
        for col_dict in results:
            for key, values in col_dict.items():
                norm_key = key.strip().lower()
                # Normalize column names to standard OHLCV
                if norm_key in ("open", "o"):
                    norm_key = "open"
                elif norm_key in ("high", "h"):
                    norm_key = "high"
                elif norm_key in ("low", "l"):
                    norm_key = "low"
                elif norm_key in ("close", "c"):
                    norm_key = "close"
                elif norm_key in ("volume", "v"):
                    norm_key = "volume"
                else:
                    # Skip any extra columns
                    continue

                if norm_key not in combined:
                    combined[norm_key] = []
                combined[norm_key].extend(values)

        # Check we have at least the essential columns
        required = {"open", "high", "low", "close"}
        if not required.issubset(combined.keys()):
            if DEBUG_MODE:
                print(f"⚠️ ChartInk missing required columns for {symbol}: got {list(combined.keys())}")
            return None

        # Ensure all columns have the same length
        col_lens = {k: len(v) for k, v in combined.items()}
        if len(set(col_lens.values())) != 1:
            if DEBUG_MODE:
                print(f"⚠️ ChartInk column length mismatch for {symbol}: {col_lens}")
            return None

        # Build DataFrame
        df = pd.DataFrame(combined)
        df.insert(0, "date", timestamps)

        # Keep only OHLCV and sort
        df = df[["date", "open", "high", "low", "close", "volume"]].sort_values("date").reset_index(drop=True)

        # Ensure numeric types
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df.dropna(subset=["open", "high", "low", "close"], inplace=True)

        # ── Drop trailing stale bars (ChartInk ~5–6 min pipeline delay) ──────
        # bar[-1] = still-forming current bar with stale data → always drop
        # bar[-2] = last "complete" bar but often also delayed → drop too
        # The real-time candle builder fills these from live Upstox LTP ticks.
        if CK_BARS_TO_DROP > 0 and len(df) > CK_BARS_TO_DROP + 5:
            dropped_bars = df.tail(CK_BARS_TO_DROP)["date"].dt.strftime("%H:%M").tolist()
            df = df.iloc[:-CK_BARS_TO_DROP].reset_index(drop=True)
            if DEBUG_MODE:
                print(f"✂️  {symbol}: Dropped {CK_BARS_TO_DROP} stale CK bars "
                      f"({', '.join(dropped_bars)}) — RT builder will fill gap")

        # ── Lag warning: how old is the last bar we kept? ─────────────────────
        if len(df) > 0 and DEBUG_MODE:
            last_ts = df["date"].iloc[-1]
            if hasattr(last_ts, "to_pydatetime"):
                last_ts = last_ts.to_pydatetime().replace(tzinfo=None)
            lag_min = (now_ist() - last_ts).total_seconds() / 60
            if lag_min > CK_LAG_WARN_MIN:
                print(f"⚠️  CK LAG {symbol}: last kept bar={last_ts.strftime('%H:%M')}, "
                      f"lag={lag_min:.1f} min — RT builder must cover this gap")

        if DEBUG_MODE:
            print(f"✅ ChartInk 5min: {symbol} → {len(df)} bars (after lag trim)")

        return df if len(df) >= 5 else None

    except requests.exceptions.Timeout:
        if DEBUG_MODE:
            print(f"⏱️ ChartInk timeout for {symbol}")
        return None
    except Exception as e:
        if DEBUG_MODE:
            print(f"❌ ChartInk error for {symbol}: {e}")
        return None

def _record_5min_failure(instrument_key):
    """Track consecutive Upstox 5min data failures and blacklist after MAX_5MIN_FAILURES."""
    global FAST_TRADE_5MIN_BLACKLIST
    count = FAST_TRADE_5MIN_FAILURES.get(instrument_key, 0) + 1
    FAST_TRADE_5MIN_FAILURES[instrument_key] = count
    if count >= MAX_5MIN_FAILURES:
        if instrument_key not in FAST_TRADE_5MIN_BLACKLIST:
            FAST_TRADE_5MIN_BLACKLIST.add(instrument_key)
            if DEBUG_MODE:
                print(f"🚫 Blacklisted {instrument_key} for Upstox 5min data (failed {count} times)")


# ============ REAL-TIME 5MIN CANDLE BUILDER ============

def get_current_5min_slot():
    """Get the start time of the current 5-minute candle slot"""
    now = now_ist()
    minute = (now.minute // 5) * 5
    return now.replace(minute=minute, second=0, microsecond=0)

def update_realtime_candle(symbol, ltp, volume):
    """
    Feed a new tick into the real-time 5min candle builder.
    Call this every time you get a live price update.
    """
    if not ltp or ltp <= 0:
        return

    current_slot = get_current_5min_slot()

    with CANDLE_BUILDER_LOCK:
        if symbol not in CURRENT_CANDLE:
            CURRENT_CANDLE[symbol] = {
                'open': ltp,
                'high': ltp,
                'low': ltp,
                'close': ltp,
                'volume': volume or 0,
                'candle_start': current_slot
            }
            return

        candle = CURRENT_CANDLE[symbol]

        if current_slot > candle['candle_start']:
            # Close the previous candle and save it
            completed = {
                'date': candle['candle_start'],
                'open': candle['open'],
                'high': candle['high'],
                'low': candle['low'],
                'close': candle['close'],
                'volume': candle['volume']
            }
            REALTIME_CANDLES[symbol].append(completed)

            # Keep only last 100 candles to save memory
            if len(REALTIME_CANDLES[symbol]) > 100:
                REALTIME_CANDLES[symbol] = REALTIME_CANDLES[symbol][-100:]

            # Start new candle
            CURRENT_CANDLE[symbol] = {
                'open': ltp,
                'high': ltp,
                'low': ltp,
                'close': ltp,
                'volume': volume or 0,
                'candle_start': current_slot
            }
        else:
            # Update current candle
            candle['high'] = max(candle['high'], ltp)
            candle['low'] = min(candle['low'], ltp)
            candle['close'] = ltp
            # Volume from Upstox is cumulative day volume, store latest value
            candle['volume'] = volume or candle['volume']

def get_realtime_5min_df(symbol, min_bars=20):
    """
    Get completed 5min candles for a symbol as DataFrame.
    Returns None if insufficient data.
    """
    with CANDLE_BUILDER_LOCK:
        candles = REALTIME_CANDLES.get(symbol, [])

        if len(candles) < min_bars:
            if DEBUG_MODE:
                print(f"⚠️ {symbol}: Only {len(candles)} real-time candles built so far "
                      f"(need {min_bars})")
            return None

        df = pd.DataFrame(candles)
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date').reset_index(drop=True)

        # Convert cumulative volume to per-bar volume
        df['volume'] = df['volume'].diff().fillna(df['volume'].iloc[0])
        df['volume'] = df['volume'].clip(lower=0)

        return df


def compute_intraday_rvol(symbol, access_token='', instrument_key='', lookback=20):
    """Relative volume (RVOL) of the latest completed 5-min candle vs the
    trailing per-bar average.

    Returns (rvol, latest_vol, avg_vol). ``rvol`` is None when there is not
    enough candle history to judge (caller should then skip the volume gate
    rather than block).

    Why this exists: the old ORB volume gate compared the *cumulative* day
    volume (live feed) against the 20-day *daily* average (VOLUME_DATA). Those
    two quantities are never comparable intraday, so the ratio logged 0.00x and
    the gate was silently disabled. RVOL compares like-for-like 5-min bars.
    """
    df = None
    try:
        df = get_realtime_5min_df(symbol, min_bars=6)
    except Exception:
        df = None
    if (df is None or len(df) < 6) and access_token and instrument_key:
        try:
            df = fetch_5min_cached(access_token, instrument_key, bars=60, symbol=symbol)
        except Exception:
            df = None
    if df is None or 'volume' not in df.columns or len(df) < 3:
        return None, None, None
    vols = pd.to_numeric(df['volume'], errors='coerce').fillna(0.0)
    latest = float(vols.iloc[-1])
    base = vols.iloc[-(lookback + 1):-1]   # trailing bars, excluding the latest
    avg = float(base.mean()) if len(base) else 0.0
    if avg <= 0:
        return None, latest, avg
    return latest / avg, latest, avg


def _fetch_5min_upstox_intraday(access_token, instrument_key, timeframe="5minute"):
    """Upstox intraday endpoint — supports 5minute or 15minute."""
    url     = f"https://api.upstox.com/v2/historical-candle/intraday/{instrument_key}/{timeframe}"
    headers = {"Accept": "application/json", "Authorization": f"Bearer {access_token}"}
    try:
        resp = _get_upstox_session(access_token).get(url, timeout=15)
        if resp.status_code != 200:
            return None, headers
        data = resp.json()
        candles = data.get("data", {}).get("candles", [])
        if not candles or len(candles) < 5:
            return None, headers
        df = pd.DataFrame(candles, columns=["date", "open", "high", "low", "close", "volume", "oi"])
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        return df, headers
    except Exception:
        return None, headers


def _fetch_5min_upstox_historical(access_token, instrument_key, headers, timeframe="5minute"):
    """Upstox historical date-range endpoint — supports 5minute or 15minute."""
    end_date = now_ist()
    start_date = end_date - timedelta(days=10)
    from_date = start_date.strftime("%Y-%m-%d")
    to_date = end_date.strftime("%Y-%m-%d")
    url = f"https://api.upstox.com/v2/historical-candle/{instrument_key}/{timeframe}/{to_date}/{from_date}"
    try:
        resp = _get_upstox_session(access_token).get(url, timeout=15)
        if resp.status_code != 200:
            return None
        data = resp.json()
        candles = data.get("data", {}).get("candles", [])
        if not candles or len(candles) < 5:
            return None
        df = pd.DataFrame(candles, columns=["date", "open", "high", "low", "close", "volume", "oi"])
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        return df
    except Exception:
        return None


def _get_chartink_hist_base(symbol, bars=100):
    """
    Fetch (or return cached) ChartInk historical 5-min OHLCV for `symbol`.

    Called ONCE on first use per symbol; result is cached for _CK_HIST_CACHE_TTL
    seconds.  Gives ~50-100 clean bars spanning today + yesterday with no warmup
    period — available from 09:15 on day open.

    Returns DataFrame[date, open, high, low, close, volume] or None.
    """
    with _CK_HIST_CACHE_LOCK:
        now = now_ist()
        cached_ts = _CK_HIST_CACHE_TS.get(symbol)
        if (
            symbol in _CK_HIST_CACHE
            and cached_ts is not None
            and (now - cached_ts).total_seconds() < _CK_HIST_CACHE_TTL
        ):
            return _CK_HIST_CACHE[symbol]

        # Fetch fresh
        df = _fetch_5min_from_chartink(symbol, bars=bars)
        if df is not None and len(df) >= 5:
            _CK_HIST_CACHE[symbol] = df
            _CK_HIST_CACHE_TS[symbol] = now
            if DEBUG_MODE:
                print(f"💾 CK hist cached: {symbol} → {len(df)} bars")
        else:
            # Keep previous cache (stale) rather than returning None
            if symbol not in _CK_HIST_CACHE:
                _CK_HIST_CACHE[symbol] = None
            if DEBUG_MODE:
                print(f"⚠️ CK hist fetch failed for {symbol} — using stale cache")

        return _CK_HIST_CACHE.get(symbol)


def _merge_hist_and_realtime(hist_df, symbol):
    """
    Merge ChartInk historical base with real-time LTP data.

    Layers:
      1. ChartInk hist base  — clean OHLCV up to ~5-6 min ago
      2. REALTIME_CANDLES    — completed 5-min bars built from live LTP ticks
      3. CURRENT_CANDLE      — the still-open bar right now (appended as synthetic bar)

    Deduplication: real-time data wins on any overlapping 5-min slot.
    """
    frames = [hist_df]

    with CANDLE_BUILDER_LOCK:
        rt_candles = list(REALTIME_CANDLES.get(symbol, []))
        current    = dict(CURRENT_CANDLE.get(symbol, {}))

    if rt_candles:
        rt_df = pd.DataFrame(rt_candles)
        rt_df["date"] = pd.to_datetime(rt_df["date"])
        frames.append(rt_df)

    if current and current.get("open") is not None:
        cur_df = pd.DataFrame([{
            "date":   current["candle_start"],
            "open":   current["open"],
            "high":   current["high"],
            "low":    current["low"],
            "close":  current["close"],
            "volume": current.get("volume", 0),
        }])
        cur_df["date"] = pd.to_datetime(cur_df["date"])
        frames.append(cur_df)

    if len(frames) == 1:
        # No real-time data yet — the CK lag gap is uncovered, warn loudly
        if len(hist_df) > 0:
            last_ts = hist_df["date"].iloc[-1]
            if hasattr(last_ts, "to_pydatetime"):
                last_ts = last_ts.to_pydatetime().replace(tzinfo=None)
            lag_min = (now_ist() - last_ts).total_seconds() / 60
            if lag_min > CK_LAG_WARN_MIN:
                print(f"⚠️  {symbol}: CK hist ends at {last_ts.strftime('%H:%M')} "
                      f"({lag_min:.1f} min ago) and NO real-time bars yet — "
                      f"signals will use stale data until RT builder catches up!")
        return hist_df

    combined = pd.concat(frames, ignore_index=True)
    combined["date"] = pd.to_datetime(combined["date"])

    # Strip timezone if mixed
    if combined["date"].dt.tz is not None:
        combined["date"] = combined["date"].dt.tz_localize(None)

    # Deduplicate by 5-min slot: keep last (real-time wins over historical)
    combined = (
        combined
        .sort_values("date")
        .drop_duplicates(subset=["date"], keep="last")
        .reset_index(drop=True)
    )
    return combined


def fetch_5min_candle_data(access_token, instrument_key, bars=100, symbol=None):
    """
    Fetch 5-minute candle data for fast trading.

    HYBRID SOURCE PRIORITY:
      1. ChartInk historical base  +  Upstox real-time LTP  (HYBRID — PRIMARY)
         ChartInk gives clean OHLCV history from the previous session onward.
         Real-time LTP ticks (from update_realtime_candle) fill the gap to now.
         Result is a complete dataset from the very first scan at 09:15.

      2. Pure real-time candles only  (fallback if ChartInk fails, needs 20 bars)

      3. Upstox intraday endpoint  (LAST RESORT 1 — needs NSE_FO key)

      4. Upstox historical endpoint  (LAST RESORT 2)

    Args:
        access_token:   Upstox Bearer token
        instrument_key: NSE_EQ instrument_key (for blacklist + FO lookup)
        bars:           Historical bars to request from ChartInk (default 100)
        symbol:         NSE symbol string e.g. 'RELIANCE'
    """
    if symbol is None:
        symbol = ISIN_TO_SYMBOL.get(instrument_key, "")

    # ── SOURCE 1: ChartInk historical + real-time LTP (HYBRID) ──────────────
    if symbol:
        hist_df = _get_chartink_hist_base(symbol, bars=bars)
        if hist_df is not None and len(hist_df) >= 20:
            merged = _merge_hist_and_realtime(hist_df, symbol)
            FAST_TRADE_5MIN_FAILURES.pop(instrument_key, None)
            if DEBUG_MODE:
                rt_bars  = len(REALTIME_CANDLES.get(symbol, []))
                last_ts  = merged["date"].iloc[-1]
                if hasattr(last_ts, "to_pydatetime"):
                    last_ts = last_ts.to_pydatetime().replace(tzinfo=None)
                lag_min  = (now_ist() - last_ts).total_seconds() / 60
                print(
                    f"✅ Hybrid 5min: {symbol} → {len(merged)} bars "
                    f"(CK hist={len(hist_df)}, RT={rt_bars}) "
                    f"| last bar={last_ts.strftime('%H:%M')} lag={lag_min:.1f}min"
                )
            return merged

    # ── SOURCE 2: Pure real-time candles (ChartInk unavailable) ─────────────
    if symbol:
        df = get_realtime_5min_df(symbol, min_bars=20)
        if df is not None:
            FAST_TRADE_5MIN_FAILURES.pop(instrument_key, None)
            if DEBUG_MODE:
                print(f"✅ Real-time only 5min: {symbol} → {len(df)} bars")
            return df

    # ── SOURCE 3/4: Upstox endpoints (last resort) ────────────────────────────
    if instrument_key in FAST_TRADE_5MIN_BLACKLIST:
        if DEBUG_MODE:
            print(f"🚫 {instrument_key} blacklisted for Upstox 5min — skipping")
        return None

    fo_key = SYMBOL_TO_FO_KEY.get(symbol, instrument_key) if symbol else instrument_key

    df, headers = _fetch_5min_upstox_intraday(access_token, fo_key, timeframe="5minute")
    if df is not None:
        FAST_TRADE_5MIN_FAILURES.pop(instrument_key, None)
        if DEBUG_MODE:
            print(f"✅ Upstox intraday 5min: {fo_key} → {len(df)} bars")
        return df

    headers = {"Accept": "application/json", "Authorization": f"Bearer {access_token}"}
    df = _fetch_5min_upstox_historical(access_token, fo_key, headers, timeframe="5minute")
    if df is not None:
        FAST_TRADE_5MIN_FAILURES.pop(instrument_key, None)
        if DEBUG_MODE:
            print(f"✅ Upstox historical 5min: {fo_key} → {len(df)} bars")
        return df

    _record_5min_failure(instrument_key)
    return None


def fetch_15min_candle_data(access_token, instrument_key, symbol=None):
    """
    Fetch 15-minute candle data for SQUEEZE (LONG) signal detection.

    Source priority:
      1. ChartInk historical (tf=15) — primary, clean OHLCV
      2. Upstox intraday 15minute endpoint — fallback
      3. Upstox historical 15minute endpoint — last resort
      4. Resample from 5min data — emergency fallback

    Returns DataFrame with columns: date, open, high, low, close, volume
    or None if insufficient data.
    """
    if symbol is None:
        symbol = ISIN_TO_SYMBOL.get(instrument_key, "")

    # ── SOURCE 1: ChartInk 15min ─────────────────────────────────────────────
    if symbol:
        df15 = _fetch_15min_from_chartink(symbol, bars=60)
        if df15 is not None and len(df15) >= 10:
            if DEBUG_MODE:
                last_ts  = df15["date"].iloc[-1]
                lag_min  = (now_ist() - last_ts).total_seconds() / 60
                print(f"✅ ChartInk 15min: {symbol} → {len(df15)} bars "
                      f"| last bar={last_ts.strftime('%H:%M')} lag={lag_min:.1f}min")
            return df15

    # ── SOURCE 2: Upstox intraday 15min ─────────────────────────────────────
    fo_key = SYMBOL_TO_FO_KEY.get(symbol, instrument_key) if symbol else instrument_key
    df15, headers = _fetch_5min_upstox_intraday(access_token, fo_key, timeframe="15minute")
    if df15 is not None and len(df15) >= 10:
        if DEBUG_MODE:
            print(f"✅ Upstox intraday 15min: {fo_key} → {len(df15)} bars")
        return df15

    # ── SOURCE 3: Upstox historical 15min ────────────────────────────────────
    df15 = _fetch_5min_upstox_historical(access_token, fo_key, {}, timeframe="15minute")
    if df15 is not None and len(df15) >= 10:
        if DEBUG_MODE:
            print(f"✅ Upstox historical 15min: {fo_key} → {len(df15)} bars")
        return df15

    # ── SOURCE 4: Resample 5min → 15min (emergency fallback) ─────────────────
    df5 = fetch_5min_candle_data(access_token, instrument_key, bars=100, symbol=symbol)
    if df5 is not None and len(df5) >= 30:
        try:
            df5 = df5.tail(100).copy()   # limit input before resample — saves CPU
            df5['date'] = pd.to_datetime(df5['date'])
            df5 = df5.set_index('date')
            df15 = df5.resample('15min').agg({
                'open':   'first',
                'high':   'max',
                'low':    'min',
                'close':  'last',
                'volume': 'sum'
            }).dropna().reset_index()
            if len(df15) >= 10:
                if DEBUG_MODE:
                    print(f"✅ Resampled 5→15min: {symbol} → {len(df15)} bars")
                return df15
        except Exception as e:
            if DEBUG_MODE:
                print(f"⚠️ 15min resample failed for {symbol}: {e}")

    if DEBUG_MODE:
        print(f"⚠️ {symbol}: No 15min data available")
    return None


# ══════════════════════════════════════════════════════════════════════════════
# INTRADAY CANDLE CACHE WRAPPERS
# Wrap fetch_5min_candle_data / fetch_15min_candle_data with a short TTL cache
# so the same data is never fetched twice within a single 30s scan cycle.
# ══════════════════════════════════════════════════════════════════════════════

def fetch_5min_cached(access_token: str, instrument_key: str,
                      bars: int = 50, symbol: str = None) -> 'pd.DataFrame | None':
    """
    Cached wrapper around fetch_5min_candle_data.
    Returns a cached DataFrame if one was fetched within _5MIN_CACHE_TTL_S seconds.
    Thread-safe: uses _INTRADAY_CACHE_LOCK for reads/writes.
    """
    if symbol is None:
        symbol = ISIN_TO_SYMBOL.get(instrument_key, "")
    key = symbol or instrument_key
    now = now_ist()

    with _INTRADAY_CACHE_LOCK:
        entry = _5MIN_CACHE.get(key)
        if entry is not None:
            age = (now - entry['fetched_at']).total_seconds()
            if age < _5MIN_CACHE_TTL_S:
                return entry['df']   # cache hit — no network call

    # Cache miss — fetch
    df = fetch_5min_candle_data(access_token, instrument_key, bars=bars, symbol=symbol)

    with _INTRADAY_CACHE_LOCK:
        _5MIN_CACHE[key] = {'df': df, 'fetched_at': now}

    return df


def fetch_15min_cached(access_token: str, instrument_key: str,
                       symbol: str = None) -> 'pd.DataFrame | None':
    """
    Cached wrapper around fetch_15min_candle_data.
    Returns a cached DataFrame if one was fetched within _15MIN_CACHE_TTL_S seconds.
    Thread-safe: uses _INTRADAY_CACHE_LOCK for reads/writes.
    """
    if symbol is None:
        symbol = ISIN_TO_SYMBOL.get(instrument_key, "")
    key = symbol or instrument_key
    now = now_ist()

    with _INTRADAY_CACHE_LOCK:
        entry = _15MIN_CACHE.get(key)
        if entry is not None:
            age = (now - entry['fetched_at']).total_seconds()
            if age < _15MIN_CACHE_TTL_S:
                return entry['df']

    df = fetch_15min_candle_data(access_token, instrument_key, symbol=symbol)

    with _INTRADAY_CACHE_LOCK:
        _15MIN_CACHE[key] = {'df': df, 'fetched_at': now}

    return df


def clear_intraday_cache():
    """Flush both intraday caches. Called once per scan cycle by the main loop."""
    with _INTRADAY_CACHE_LOCK:
        _5MIN_CACHE.clear()
        _15MIN_CACHE.clear()


def prefetch_candles_parallel(access_token: str, symbols: list,
                               workers: int = None) -> None:
    """
    Pre-fetch 5min + 15min candles for all symbols in parallel using
    a ThreadPoolExecutor before the main scan loop processes them.

    This converts 20 sequential fetches (≈6s) into parallel fetches (≈400ms).
    Results are stored in _5MIN_CACHE / _15MIN_CACHE and returned from
    fetch_5min_cached / fetch_15min_cached instantly during the scan.

    Args:
        access_token: Upstox Bearer token
        symbols:      List of NSE symbol strings (e.g. fast-trade watchlist)
        workers:      Thread pool size (default: FAST_TRADE_FETCH_WORKERS)
    """
    n = workers or FAST_TRADE_FETCH_WORKERS

    def _fetch_one(sym: str):
        ikey = SYMBOL_TO_ISIN.get(sym, "")
        if not ikey:
            return
        # These calls write directly into _5MIN_CACHE / _15MIN_CACHE
        fetch_5min_cached(access_token, ikey, bars=50, symbol=sym)
        fetch_15min_cached(access_token, ikey, symbol=sym)

    with ThreadPoolExecutor(max_workers=n, thread_name_prefix="candle_prefetch") as pool:
        list(pool.map(_fetch_one, symbols))   # block until all done


def _fetch_15min_from_chartink(symbol: str, bars: int = 60) -> 'pd.DataFrame | None':
    """
    Fetch 15-minute historical OHLCV from ChartInk.
    Uses tf=15 parameter — same endpoint as 5min but with different timeframe.
    """
    try:
        url = f"{CHARTINK_BASE_URL}/chart_data/"
        params = {
            "symbol":    symbol,
            "tf":        "15",        # 15-minute timeframe
            "type":      "stock",
            "exchange":  "NSE",
            "bars":      str(bars),
        }
        ck_sess = _get_chartink_session()
        resp = ck_sess.get(
            url, params=params, cookies=CHARTINK_COOKIES,
            headers={"Referer": "https://chartink.com/"},
            timeout=15
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        # ChartInk returns arrays: t (timestamps), o, h, l, c, v
        t = data.get("t", [])
        if not t or len(t) < 5:
            return None
        df = pd.DataFrame({
            "date":   pd.to_datetime(t, unit="s", utc=True).tz_convert("Asia/Kolkata").tz_localize(None),
            "open":   data.get("o", []),
            "high":   data.get("h", []),
            "low":    data.get("l", []),
            "close":  data.get("c", []),
            "volume": data.get("v", []),
        })
        df = df.sort_values("date").reset_index(drop=True)
        return df
    except Exception:
        return None
def detect_fast_long_setup(df, klinger_data=None):
    """
    Detect fast LONG trade setup using 15-minute candles.
    1. Bollinger Band squeeze (threshold tuned for 15min width)
    2. First strong green candle closing above upper band
    3. Klinger turning up (soft or hard confirmation)
    Uses BOLLINGER_SQUEEZE_THRESHOLD (0.20) and MIN_BREAKOUT_VOLUME_RATIO (1.8)
    which are calibrated for 15min candle characteristics.
    """
    if len(df) < BOLLINGER_PERIOD + 10:
        return None
    
    # Calculate Bollinger Bands
    bb_upper, bb_middle, bb_lower, bb_width, bb_percent_b = calculate_bollinger_bands(
        df, period=BOLLINGER_PERIOD, std=BOLLINGER_STD
    )
    
    if bb_upper is None:
        return None
    
    # Get last few candles
    recent_candles = df.iloc[-5:].copy()
    last_candle = recent_candles.iloc[-1]
    prev_candle = recent_candles.iloc[-2] if len(recent_candles) > 1 else last_candle
    
    # 1. Check for squeeze
    is_squeeze = detect_bollinger_squeeze(bb_width.iloc[:-1], BOLLINGER_SQUEEZE_THRESHOLD)
    
    if not is_squeeze:
        return None
    
    # 2. Check for breakout candle
    avg_volume = df['volume'].tail(20).mean()
    if avg_volume <= 0:
        return None
    
    volume_ratio = last_candle['volume'] / avg_volume
    is_breakout = (last_candle['close'] > bb_upper.iloc[-1] and 
                   volume_ratio >= MIN_BREAKOUT_VOLUME_RATIO)
    
    if not is_breakout:
        return None
    
    # 3. Check Klinger confirmation
    klinger_confirmed = False
    klinger_status = "N/A"
    
    if klinger_data:
        ko = klinger_data.get('klinger', 0)
        signal = klinger_data.get('signal', 0)
        ko_prev = klinger_data.get('klinger_prev', 0)
        signal_prev = klinger_data.get('signal_prev', 0)
        
        # Klinger turning up and crossing above signal
        klinger_cross_up = (ko_prev <= signal_prev and ko > signal)
        klinger_rising = ko > ko_prev
        
        # Prefer Klinger coming from negative/oversold area
        from_oversold = ko_prev < 0 or (ko < 0 and klinger_rising)
        
        klinger_confirmed = (klinger_cross_up or klinger_rising) and from_oversold

        # ── SOFT CONFIRMATION (ONGC-type fix) ────────────────────────────────
        # When KO is large and positive and rising for 3+ bars, the crossover
        # requirement fails because both KO and Signal are large positives moving
        # together. Treat this as a soft confirmation so these stocks don't
        # repeatedly fall back to the secondary gate.
        if not klinger_confirmed and klinger_rising and ko > 0:
            # Check if KO has been rising for at least 3 consecutive bars
            ko_history = klinger_data.get('ko_history', [])
            if len(ko_history) >= 3:
                consistently_rising = all(
                    ko_history[i] < ko_history[i+1]
                    for i in range(len(ko_history)-3, len(ko_history)-1)
                )
                if consistently_rising:
                    klinger_confirmed = True
                    klinger_status = f"CONFIRMED (KO: {ko:.1f}↑ soft — positive+rising)"
        # ── END SOFT CONFIRMATION ─────────────────────────────────────────────

        if klinger_confirmed and not klinger_status.startswith("CONFIRMED"):
            klinger_status = f"CONFIRMED (KO: {ko:.1f}↑)"
        elif not klinger_confirmed:
            klinger_status = f"REJECTED (KO: {ko:.1f})"
    
    # Calculate setup strength
    candle_size = (last_candle['close'] - last_candle['open']) / last_candle['open'] * 100
    
    # Determine entry type
    if is_squeeze and is_breakout:
        entry_type = ENTRY_SQUEEZE
    elif is_breakout:
        entry_type = ENTRY_BREAKOUT
    else:
        entry_type = "UNKNOWN"

    entry_price = last_candle['close']
    # 15min candles have wider natural range — use 1.0% below candle low
    # (was 0.5% for 5min; PNB was stopped out by normal noise with 0.5%)
    stop_loss   = last_candle['low'] * 0.990

    # ── TARGET FIX ────────────────────────────────────────────────────────────
    # Original code used bb_middle as target. When price has already broken
    # ABOVE the upper band, bb_middle is BELOW entry — producing an inverted
    # (negative) R:R. Example: PNB entry ₹111.40, target ₹110.59 < stop ₹110.60.
    #
    # Correct logic:
    #   - Primary:  upper_band + (upper_band - middle_band)  — project same band
    #               width above the upper band (first extension target)
    #   - Fallback: entry + 2 × risk  — always at least 2:1 R:R
    #   - Safety:   ensure target > entry (never allow inverted target)
    risk = entry_price - stop_loss
    bb_ext_target = bb_upper.iloc[-1] + (bb_upper.iloc[-1] - bb_middle.iloc[-1])
    rr2_target    = entry_price + 2 * risk
    # Use whichever is higher — ext_target tends to be more generous on breakouts
    raw_target = max(bb_ext_target, rr2_target)
    # Safety clamp: target must always be above entry
    target = raw_target if raw_target > entry_price else entry_price + 2 * risk
    # ── END TARGET FIX ────────────────────────────────────────────────────────

    return {
        'signal': 'LONG',
        'entry_price': entry_price,
        'stop_loss': stop_loss,
        'target': target,
        'entry_type': entry_type,
        'candle_size_pct': candle_size,
        'volume_ratio': volume_ratio,
        'bb_upper': bb_upper.iloc[-1],
        'bb_middle': bb_middle.iloc[-1],
        'bb_lower': bb_lower.iloc[-1],
        'bb_width': bb_width.iloc[-1],
        'klinger_confirmed': klinger_confirmed,
        'klinger_status': klinger_status,
        'timestamp': now_ist(),
        'confidence': 'HIGH' if klinger_confirmed and volume_ratio > 2 else 'MEDIUM'
    }

def detect_fast_short_setup(df, klinger_data=None):
    """
    Detect fast SHORT pullback trade setup using 5-minute candles.
    1. Strong downtrend with price below lower band
    2. Pullback to middle band/EMA
    3. Strong red candle rejecting pullback
    4. Klinger below zero and turning down
    Uses MIN_PULLBACK_VOLUME_RATIO (1.2) calibrated for 5min candles.
    """
    if len(df) < BOLLINGER_PERIOD + 10:
        return None
    
    # Calculate Bollinger Bands
    bb_upper, bb_middle, bb_lower, bb_width, bb_percent_b = calculate_bollinger_bands(
        df, period=BOLLINGER_PERIOD, std=BOLLINGER_STD
    )
    
    if bb_upper is None:
        return None
    
    # Get last few candles
    recent_candles = df.iloc[-10:].copy()
    last_candle = recent_candles.iloc[-1]
    
    # Check for downtrend (price below middle band)
    if last_candle['close'] > bb_middle.iloc[-1]:
        return None
    
    # Check for pullback to middle band (within 1%)
    pullback_threshold = 0.01
    distance_to_middle = abs(last_candle['close'] - bb_middle.iloc[-1]) / bb_middle.iloc[-1]
    
    if distance_to_middle > pullback_threshold:
        return None
    
    # Check for strong red candle
    if last_candle['close'] >= last_candle['open']:
        return None  # Not a red candle
    
    candle_size = abs(last_candle['close'] - last_candle['open']) / last_candle['open'] * 100
    if candle_size < 0.5:  # Too small
        return None
    
    # Volume check
    avg_volume = df['volume'].tail(20).mean()
    if avg_volume <= 0:
        return None
    
    volume_ratio = last_candle['volume'] / avg_volume
    if volume_ratio < MIN_PULLBACK_VOLUME_RATIO:
        return None
    
    # Klinger confirmation
    klinger_confirmed = False
    klinger_status = "N/A"
    
    if klinger_data:
        ko = klinger_data.get('klinger', 0)
        signal = klinger_data.get('signal', 0)
        ko_prev = klinger_data.get('klinger_prev', 0)
        signal_prev = klinger_data.get('signal_prev', 0)
        
        # Klinger below zero and turning down
        klinger_below_zero = ko < 0
        klinger_cross_down = (ko_prev >= signal_prev and ko < signal)
        klinger_falling = ko < ko_prev
        
        klinger_confirmed = klinger_below_zero and (klinger_cross_down or klinger_falling)
        
        if klinger_confirmed:
            klinger_status = f"CONFIRMED (KO: {ko:.1f}↓)"
        else:
            klinger_status = f"REJECTED (KO: {ko:.1f})"
    
    short_entry = last_candle['close']
    short_stop  = last_candle['high'] * 1.005

    # ── SHORT TARGET FIX ──────────────────────────────────────────────────────
    # Original: bb_lower * 0.995  — this is usually below entry which is correct.
    # But add the same safety clamp: ensure target < entry (never inverted).
    short_risk       = short_stop - short_entry
    bb_ext_short     = bb_lower.iloc[-1] - (bb_middle.iloc[-1] - bb_lower.iloc[-1])
    rr2_short_target = short_entry - 2 * short_risk
    raw_short_target = min(bb_ext_short, rr2_short_target)
    short_target     = raw_short_target if raw_short_target < short_entry else short_entry - 2 * short_risk
    # ── END SHORT TARGET FIX ──────────────────────────────────────────────────

    return {
        'signal': 'SHORT',
        'entry_price': short_entry,
        'stop_loss': short_stop,
        'target': short_target,
        'entry_type': ENTRY_PULLBACK,
        'candle_size_pct': candle_size,
        'volume_ratio': volume_ratio,
        'bb_upper': bb_upper.iloc[-1],
        'bb_middle': bb_middle.iloc[-1],
        'bb_lower': bb_lower.iloc[-1],
        'klinger_confirmed': klinger_confirmed,
        'klinger_status': klinger_status,
        'timestamp': now_ist(),
        'confidence': 'HIGH' if klinger_confirmed and volume_ratio > 2 else 'MEDIUM'
    }

def detect_topping_reversal(df, klinger_data=None, strict=False):
    """
    Detect exhaustion SHORT at the upper Bollinger Band.
    Catches ONGC-type Doji + ETERNAL-type small-body wicks at highs.

    WHY THIS EXISTS:
    detect_fast_short_setup() has a hard gate: if price > bb_middle → return None.
    At a topping candle the price is at the UPPER band — well above the middle —
    so that function exits before checking anything. This function fills that gap.

    strict=True  → before 12:30: Klinger confirm mandatory, tighter RSI/vol
    strict=False → after 12:30:  normal thresholds, Klinger preferred not required
    """
    if len(df) < BOLLINGER_PERIOD + 5:
        return None

    bb_upper, bb_middle, bb_lower, bb_width, bb_percent_b = \
        calculate_bollinger_bands(df, BOLLINGER_PERIOD, BOLLINGER_STD)
    if bb_upper is None:
        return None

    last = df.iloc[-1]

    candle_range = last['high'] - last['low']
    if candle_range < 0.001:
        return None

    body     = abs(last['close'] - last['open'])
    body_pct = body / candle_range   # Doji = body < 45% of full range

    # ── Condition 1: candle HIGH touches / enters upper band zone ────────────
    # high must reach within EARLY_REVERSAL_BAND_TOL_PCT below the upper band
    # OR pierce above it (false breakout / wick rejection).
    dist_high_to_upper = (bb_upper.iloc[-1] - last['high']) / bb_upper.iloc[-1] * 100
    if dist_high_to_upper > EARLY_REVERSAL_BAND_TOL_PCT:
        if DEBUG_MODE:
            print(f"⛔ Topping check: high {last['high']:.2f} not near upper band "
                  f"{bb_upper.iloc[-1]:.2f} (gap {dist_high_to_upper:.2f}%)")
        return None

    # ── Condition 2: small body — exhaustion, not a strong breakout ──────────
    body_max = EARLY_REVERSAL_BODY_MAX_PCT if strict else 0.55
    if body_pct > body_max:
        if DEBUG_MODE:
            print(f"⛔ Topping check: body {body_pct:.2f} > max {body_max:.2f} — too strong")
        return None

    # ── Condition 3: close must NOT be above upper band ──────────────────────
    # A close firmly above the upper band = breakout still in progress
    if last['close'] > bb_upper.iloc[-1] * 1.002:
        if DEBUG_MODE:
            print(f"⛔ Topping check: close {last['close']:.2f} above upper band — breakout mode")
        return None

    # ── Condition 4: volume spike ─────────────────────────────────────────────
    avg_vol   = df['volume'].tail(20).mean()
    vol_min   = EARLY_REVERSAL_VOLUME_RATIO if strict else 1.3
    vol_ratio = last['volume'] / avg_vol if avg_vol > 0 else 0
    if vol_ratio < vol_min:
        if DEBUG_MODE:
            print(f"⛔ Topping check: vol ratio {vol_ratio:.2f} < min {vol_min:.2f}")
        return None

    # ── Condition 5: Klinger turning down ────────────────────────────────────
    klinger_confirmed = False
    klinger_status    = "N/A"
    if klinger_data:
        ko      = klinger_data.get('klinger', 0)
        ko_prev = klinger_data.get('klinger_prev', 0)
        sig     = klinger_data.get('signal', 0)
        ko_hist = klinger_data.get('ko_history', [])
        falling = ko < ko_prev
        # Soft confirm: KO declining 3 consecutive bars even if KO is still > 0
        # (mirrors the soft confirm already used in the SHORT secondary gate)
        soft    = (len(ko_hist) >= 3 and
                   all(ko_hist[i] > ko_hist[i + 1]
                       for i in range(len(ko_hist) - 3, len(ko_hist) - 1)))
        klinger_confirmed = falling or soft
        if klinger_confirmed:
            klinger_status = f"CONFIRMED (KO:{ko:.0f}↓)"
            if DEBUG_MODE and soft and ko > 0:
                print(f"✅ Topping soft confirm: KO declining "
                      f"{ko_hist[-3]:.0f}→{ko_hist[-2]:.0f}→{ko_hist[-1]:.0f} "
                      f"(still positive but falling)")
        else:
            klinger_status = f"REJECTED (KO:{ko:.0f})"

    # In strict (pre-12:30) mode Klinger confirmation is mandatory
    if strict and not klinger_confirmed:
        if DEBUG_MODE:
            print(f"⛔ Topping reversal (strict pre-12:30): Klinger not confirmed — skipped")
        return None

    # ── Build setup dict ──────────────────────────────────────────────────────
    entry  = last['close']
    stop   = last['high'] * 1.004          # just above the wick tip
    risk   = stop - entry
    if risk <= 0:
        return None
    target = entry - 2.5 * risk            # 2.5:1 minimum R:R

    confidence = 'HIGH' if (klinger_confirmed and vol_ratio > 1.8) else 'MEDIUM'

    return {
        'signal':            'SHORT',
        'entry_type':        'TOPPING_REVERSAL',
        'entry_price':       entry,
        'stop_loss':         stop,
        'target':            target,
        'candle_size_pct':   body_pct * 100,
        'volume_ratio':      vol_ratio,
        'bb_upper':          bb_upper.iloc[-1],
        'bb_middle':         bb_middle.iloc[-1],
        'bb_lower':          bb_lower.iloc[-1],
        'bb_width':          bb_width.iloc[-1],
        'klinger_confirmed': klinger_confirmed,
        'klinger_status':    klinger_status,
        'confidence':        confidence,
        'timestamp':         now_ist(),
    }

def manage_fast_trade_exit(trade, current_price, df, klinger_data=None):
    """
    Manage exit for fast trade based on multiple conditions
    """
    entry_price = trade['entry_price']
    signal = trade['signal']
    current_pnl = (current_price - entry_price) / entry_price * 100
    
    # 1. Stop Loss Hit
    if signal == 'LONG' and current_price <= trade['stop_loss']:
        return EXIT_STOP, f"Stop loss hit at {current_price:.2f}"
    
    if signal == 'SHORT' and current_price >= trade['stop_loss']:
        return EXIT_STOP, f"Stop loss hit at {current_price:.2f}"
    
    # 2. Target Reached (1.5-2x risk)
    risk = abs(entry_price - trade['stop_loss'])
    target_multiple = 1.5
    
    if signal == 'LONG' and (current_price - entry_price) >= risk * target_multiple:
        return EXIT_TARGET, f"Target reached ({current_pnl:.2f}%)"
    
    if signal == 'SHORT' and (entry_price - current_price) >= risk * target_multiple:
        return EXIT_TARGET, f"Target reached ({current_pnl:.2f}%)"
    
    # 3. Bollinger Band Exit (for longs)
    if signal == 'LONG':
        bb_upper, bb_middle, bb_lower, bb_width, bb_percent_b = calculate_bollinger_bands(
            df, BOLLINGER_PERIOD, BOLLINGER_STD
        )
        
        if bb_upper is not None and current_price >= bb_upper.iloc[-1] * 1.02:
            return EXIT_TRAILING, "Upper band extension reached"
        
        if bb_middle is not None and current_price < bb_middle.iloc[-1]:
            return EXIT_REVERSAL, "Price below middle band"
    
    # 4. Klinger Reversal
    if klinger_data:
        ko = klinger_data.get('klinger', 0)
        signal_line = klinger_data.get('signal', 0)
        
        if trade['signal'] == 'LONG' and ko < signal_line:
            return EXIT_REVERSAL, "Klinger crossed below signal"
        
        if trade['signal'] == 'SHORT' and ko > signal_line:
            return EXIT_REVERSAL, "Klinger crossed above signal"
    
    # 5. Trailing Stop (for profits > 1%)
    if abs(current_pnl) > 1:
        trailing_stop_pct = 0.5  # Trail by 0.5% from peak
        
        if 'peak_price' not in trade:
            trade['peak_price'] = current_price if signal == 'LONG' else current_price
        else:
            if signal == 'LONG':
                trade['peak_price'] = max(trade['peak_price'], current_price)
                if current_price <= trade['peak_price'] * (1 - trailing_stop_pct/100):
                    return EXIT_TRAILING, f"Trailing stop hit ({current_pnl:.2f}%)"
            else:
                trade['peak_price'] = min(trade['peak_price'], current_price)
                if current_price >= trade['peak_price'] * (1 + trailing_stop_pct/100):
                    return EXIT_TRAILING, f"Trailing stop hit ({current_pnl:.2f}%)"
    
    return None, None

# ========== ENHANCED OPTION SELECTION FUNCTIONS ==========

def get_cached_option_chain(trader, underlying_key):
    """Get option chain with caching to reduce API calls"""
    cache_key = underlying_key
    current_time = now_ist()
    
    # Check if valid cache exists
    if cache_key in OPTION_CHAIN_CACHE:
        cache_time, chain_data = OPTION_CHAIN_CACHE[cache_key]
        if (current_time - cache_time).seconds < OPTION_CHAIN_CACHE_EXPIRY:
            return chain_data
    
    # Fetch fresh data
    chain_data = trader.get_option_chain(underlying_key)
    
    # Cache the result
    if chain_data and chain_data.get("status") == "success":
        OPTION_CHAIN_CACHE[cache_key] = (current_time, chain_data)
    
    return chain_data

def select_strike_with_liquidity(nearest_contracts, spot_price, strike_offset_steps=0, max_attempts=3):
    """Try multiple strikes to find one with valid premium"""
    strikes = sorted({c["strike_price"] for c in nearest_contracts})
    if not strikes:
        return None
    
    # Try ATM ± N strikes
    offsets_to_try = [0, 1, -1, 2, -2, 3, -3]  # Try ATM first, then nearby
    
    for offset in offsets_to_try:
        atm_strike = min(strikes, key=lambda x: abs(x - spot_price))
        atm_index = strikes.index(atm_strike)
        target_index = max(0, min(len(strikes) - 1, atm_index + offset))
        target_strike = strikes[target_index]
        
        # Find contract with this strike
        for c in nearest_contracts:
            if c["strike_price"] == target_strike:
                return c
    return None

def get_option_premium_with_fallback(trader, contract, spot_price, max_retries):
    """Get option premium with retry and intelligent fallback."""
    premium = None
    instrument_key = contract["instrument_key"]
    
    # Try to get real LTP
    for attempt in range(max_retries):
        try:
            premium = trader.get_ltp(instrument_key, max_retries=1)
            if premium and premium > 0:
                return premium, False  # Real LTP
        except Exception as e:
            if DEBUG_MODE:
                print(f"⚠️ Premium fetch error (attempt {attempt + 1}): {e}")
        
        if attempt < max_retries - 1:
            time.sleep(1.5)
    
    # Fallback: Estimate premium
    print(f"⚠️ Using estimated premium for {contract.get('trading_symbol')}")
    
    strike = contract["strike_price"]
    option_type = contract["instrument_type"]
    
    # Intrinsic value
    if option_type == 'CE':
        intrinsic = max(0, spot_price - strike)
    else:  # PE
        intrinsic = max(0, strike - spot_price)
    
    # Time value estimation based on moneyness and volatility
    moneyness = abs(strike - spot_price) / spot_price
    
    # ATM options have more time value
    if moneyness < 0.02:  # Very near ATM
        time_value_pct = 0.05  # 5% of spot
    elif moneyness < 0.05:  # Near ATM
        time_value_pct = 0.03  # 3% of spot
    elif moneyness < 0.10:  # Slightly OTM
        time_value_pct = 0.02  # 2% of spot
    else:  # Deep OTM
        time_value_pct = 0.01  # 1% of spot
    
    time_value = spot_price * time_value_pct
    estimated_premium = intrinsic + time_value
    
    # Minimum floor
    estimated_premium = max(estimated_premium, spot_price * 0.015)  # At least 1.5%
    
    return estimated_premium, True  # Estimated premium

def validate_premium(premium, spot_price, symbol):
    """Validate premium is within reasonable bounds."""
    premium_as_pct = (premium / spot_price) * 100
    
    # Check minimum
    if premium < OPTION_PREMIUM_MIN_THRESHOLD:
        print(f"⚠️ Premium too low (₹{premium:.2f}, {premium_as_pct:.1f}%) for {symbol}")
        return False
    
    # Check maximum (unusually high premium might indicate error)
    if premium > OPTION_PREMIUM_MAX_THRESHOLD:
        print(f"⚠️ Premium too high (₹{premium:.2f}, {premium_as_pct:.1f}%) for {symbol}")
        return False
    
    # Premium should typically be 1-20% of spot for equity options
    if premium_as_pct > 30:
        print(f"⚠️ Premium suspiciously high ({premium_as_pct:.1f}%) for {symbol}")
        return False
    
    return True

def select_liquid_stock_option_contract(trader, underlying_key, symbol, option_type, 
                                       strike_offset_steps=0, max_retries=None):
    """Enhanced option selection with multiple fallback strategies."""
    if max_retries is None:
        max_retries = OPTION_LTP_RETRY_ATTEMPTS

    underlying_key = norm_key(underlying_key)
    
    # 1) Get spot price with fallback
    spot_price = trader.get_ltp(underlying_key)
    if not spot_price:
        info = R3_LEVELS.get(underlying_key)
        if info and info.get("yesterday_close"):
            spot_price = info["yesterday_close"]
            print(f"⚠️ Using yesterday close as proxy spot for {symbol}: {spot_price}")
        else:
            print(f"⚠️ Could not get spot price for {symbol}, skipping option trade.")
            return None
    
    # 2) Get option chain with caching
    option_chain = get_cached_option_chain(trader, underlying_key)
    if not option_chain or option_chain.get("status") != "success" or not option_chain.get("data"):
        print(f"❌ Failed to fetch option chain for {symbol}")
        return None
    
    contracts = option_chain["data"]
    
    # 3) Filter valid contracts with expiry dates
    # Skip contracts expiring TODAY — Upstox blocks same-day expiry stock options
    # due to physical settlement rules (RMS: NON-SQROFF block).
    today = now_ist().date()
    valid_contracts = []
    for c in contracts:
        expiry_str = c.get("expiry", "")
        if not expiry_str or c.get("instrument_type") != option_type:
            continue
        try:
            c["expiry_date"] = datetime.strptime(expiry_str, "%Y-%m-%d")
            # Skip same-day expiry — physical settlement block
            if c["expiry_date"].date() == today:
                if DEBUG_MODE:
                    print(f"⚠️ Skipping same-day expiry contract: {c.get('trading_symbol', expiry_str)} (physical settlement)")
                continue
            valid_contracts.append(c)
        except Exception:
            continue
    
    if not valid_contracts:
        print(f"❌ No {option_type} contracts for {symbol}")
        return None
    
    # 4) Group by expiry and select nearest
    valid_contracts.sort(key=lambda x: x["expiry_date"])
    nearest_expiry = valid_contracts[0]["expiry_date"]
    nearest_contracts = [c for c in valid_contracts if c["expiry_date"] == nearest_expiry]
    
    # 5) Try multiple strike selection strategies
    contract = select_strike_with_liquidity(nearest_contracts, spot_price, strike_offset_steps)
    if not contract:
        print(f"❌ No suitable {option_type} contract found for {symbol}")
        return None
    
    # 6) Get premium with retry and fallback
    premium, use_estimated = get_option_premium_with_fallback(
        trader, contract, spot_price, max_retries
    )
    
    if not premium or premium <= 0:
        print(f"❌ Could not determine premium for {contract.get('trading_symbol')}")
        return None
    
    # 7) Validate premium
    if not validate_premium(premium, spot_price, contract.get('trading_symbol')):
        return None
    
    print(f"\n✅ SELECTED OPTION for {symbol}:")
    print(f" Symbol: {contract['trading_symbol']}")
    print(f" Strike: {contract['strike_price']} | Type: {contract['instrument_type']}")
    print(f" Expiry: {contract['expiry']} | LotSize: {contract['lot_size']}")
    print(f" Premium: ₹{premium:.2f} ({'ESTIMATED' if use_estimated else 'LTP'})")
    print(f" Spot: ₹{spot_price:.2f} | Moneyness: {'ITM' if (option_type == 'CE' and spot_price > contract['strike_price']) or (option_type == 'PE' and spot_price < contract['strike_price']) else 'OTM'}")
    
    return (
        contract["instrument_key"],
        contract["trading_symbol"],
        contract["strike_price"],
        contract["lot_size"],
        premium,
        contract,
        use_estimated  # Add this to know if premium was estimated
    )

# ========== TRADING EXECUTION FUNCTIONS ==========

def get_available_margin(trader):
    """
    Return available cash/margin in the trading account.
    Result is cached for _MARGIN_CACHE_TTL_SECONDS to avoid flooding the API.
    Returns None if the API call fails.
    """
    global _CACHED_AVAILABLE_MARGIN, _MARGIN_CACHE_TIME
    with _MARGIN_CACHE_LOCK:
        now = now_ist()
        if (_CACHED_AVAILABLE_MARGIN is not None and
                _MARGIN_CACHE_TIME is not None and
                (now - _MARGIN_CACHE_TIME).total_seconds() < _MARGIN_CACHE_TTL_SECONDS):
            return _CACHED_AVAILABLE_MARGIN
        try:
            resp = trader.get_funds()
            # Upstox v2 response: data.equity.available_margin
            equity = resp.get("data", {}).get("equity", {})
            margin = float(equity.get("available_margin", 0))
            _CACHED_AVAILABLE_MARGIN = margin
            _MARGIN_CACHE_TIME = now
            return margin
        except Exception as e:
            print(f"⚠️ Could not fetch margin: {e}")
            return None


def place_fast_trade_order(setup, trader, symbol, instrument_key):
    """Place OPTION orders for fast trading setups"""
    global FAST_TRADE_ORDER_COUNT, LAST_ORDER_TIME, PLACED_ORDERS, ACTIVE_POSITIONS, TRADING_STOPPED, POSITION_TRAILING_SL

    if TRADING_STOPPED:
        print("⚠️ Trading stopped - no new orders")
        return None

    # Guard: block before option-chain lookup to avoid wasted API calls
    if not is_order_time_allowed():
        sig = setup.get('signal', '?')
        print(f"⏭️  {symbol} FAST {sig}: order skipped — outside Upstox service hours (05:30–23:59 IST)")
        add_to_ha_watchlist(symbol, sig, instrument_key,
                            "Outside Upstox service hours (05:30–23:59 IST)")
        return None

    option_type = 'CE' if setup['signal'] == 'LONG' else 'PE'

    # Select option contract
    selection = select_liquid_stock_option_contract(
        trader=trader,
        underlying_key=instrument_key,
        symbol=symbol,
        option_type=option_type,
        strike_offset_steps=0,
    )
    
    if not selection:
        print(f"⚠️ Skipping fast trade in {symbol} - no suitable {option_type} option.")
        return None

    option_key, option_symbol, strike, lot_size, premium, contract, is_premium_estimated = selection
    total_qty = lot_size * ORDER_QUANTITY

    # ── PRE-FLIGHT MARGIN CHECK ──────────────────────────────────────────────
    # Estimate required margin: ~1.5x premium × qty (conservative estimate)
    estimated_cost = premium * total_qty
    available = get_available_margin(trader)
    if available is not None and available < estimated_cost * 0.5:
        # Less than half the estimated premium cost → almost certainly not enough margin
        rejection_reason = (f"Insufficient margin: need ~₹{estimated_cost:.0f}, "
                            f"available ₹{available:.2f}")
        print(f"⚠️ {symbol} {option_type}: {rejection_reason} — skipping order")
        # Add to HA watchlist so we still track reversal signals for this symbol
        add_to_ha_watchlist(symbol, setup['signal'], instrument_key, rejection_reason)
        return None
    # ─────────────────────────────────────────────────────────────────────────

    print(f"\n📊 PLACING FAST TRADE OPTION ORDER for {symbol}")
    print(f" Underlying: {symbol}")
    print(f" Option: {option_symbol}")
    print(f" Signal: {setup['signal']} via {option_type}")
    print(f" Strike: {strike} | Expiry: {contract.get('expiry')}")
    print(f" Lots: {ORDER_QUANTITY} | Lot size: {lot_size} | Total Qty: {total_qty}")
    print(f" Approx premium: ₹{premium:.2f} ({'ESTIMATED' if is_premium_estimated else 'LTP'})")
    
    if setup.get('klinger_status'):
        print(f" 🔥 Klinger: {setup['klinger_status']}")

    try:
        # FIX 6: Use LIMIT orders instead of MARKET for options
        limit_price = round(premium * 1.02, 2)  # Add 2% buffer for slippage
        
        print(f" 💰 Order Type: LIMIT @ ₹{limit_price:.2f} (premium ₹{premium:.2f} + 2% buffer)")
        
        result = trader.place_order(
            instrument_key=option_key,
            quantity=total_qty,
            transaction_type='BUY',
            product=ORDER_PRODUCT,
            order_type='LIMIT',      # <-- changed from MARKET
            price=limit_price         # <-- limit price added
        )

        order_info = verify_order_result(trader, result, option_symbol)
        if order_info and order_info.get('order_id'):
            order_id = order_info['order_id']
            
            # Thread-safe counter updates
            with THREAD_LOCKS['FAST_TRADE_ORDER_COUNT']:
                FAST_TRADE_ORDER_COUNT += 1

            with THREAD_LOCKS['LAST_ORDER_TIME']:
                LAST_ORDER_TIME[symbol] = now_ist()

            filled_price = order_info.get('filled_price', premium)

            # Parse expiry date
            expiry_date = None
            try:
                expiry_date = datetime.strptime(contract.get('expiry'), "%Y-%m-%d")
            except:
                pass

            # Create position record
            position_record = {
                'order_id': order_id,
                'symbol': symbol,
                'option_symbol': option_symbol,
                'instrument_key': option_key,
                'underlying_key': instrument_key,
                'entry_price': filled_price,
                'quantity': total_qty,
                'breakout_type': option_type,
                'option_type': option_type,
                'trade_type': f'FAST_TRADE_{setup["entry_type"]}',
                'strategy': 'FAST_TRADE',
                'fast_trade_signal': setup['signal'],
                'fast_trade_entry_type': setup['entry_type'],
                'timestamp': now_ist(),
                'expiry_date': expiry_date,
                'klinger_confirmed': setup.get('klinger_confirmed', False),
                'setup_data': setup,
                'is_premium_estimated': is_premium_estimated
            }

            with THREAD_LOCKS['PLACED_ORDERS']:
                PLACED_ORDERS[order_id] = position_record
            
            # Add to active positions for exit management
            if order_info.get('status') == 'complete':
                with THREAD_LOCKS['ACTIVE_POSITIONS']:
                    ACTIVE_POSITIONS[order_id] = position_record.copy()
                with THREAD_LOCKS['FAST_TRADES']:
                    # Also add to fast trades tracking
                    trade_id = f"FAST_{order_id}"
                    FAST_TRADES[trade_id] = position_record
                with THREAD_LOCKS['ACTIVE_FAST_TRADES']:
                    trade_id = f"FAST_{order_id}"
                    ACTIVE_FAST_TRADES[trade_id] = position_record

            # Stop-loss
            if PLACE_STOPLOSS and order_info.get('status') == 'complete':
                sl_trigger = round(filled_price * (1 - STOPLOSS_PERCENTAGE / 100), 2)
                sl_limit = round(sl_trigger * 0.99, 2)

                print("\n🛡️ PLACING FAST TRADE STOP-LOSS")
                print(f" Trigger: ₹{sl_trigger:.2f} | Limit: ₹{sl_limit:.2f}")

                try:
                    sl_result = trader.place_order(
                        instrument_key=option_key,
                        quantity=total_qty,
                        transaction_type='SELL',
                        product=ORDER_PRODUCT,
                        order_type='SL_LIMIT',   # <-- changed from 'SL'
                        price=sl_limit,
                        trigger_price=sl_trigger
                    )
                    if sl_result.get('status_code') == 200:
                        sl_order_id = sl_result['response'].get('data', {}).get('order_id')
                        if sl_order_id:
                            print(f"✅ SL Order ID: {sl_order_id}")
                            PLACED_ORDERS[order_id]['sl_order_id'] = sl_order_id
                            ACTIVE_POSITIONS[order_id]['sl_order_id'] = sl_order_id
                            # Seed the trailing-SL tracker with the initial level
                            POSITION_TRAILING_SL[order_id] = sl_trigger
                except Exception as e:
                    print(f"⚠️ SL placement error: {e}")

            # Log the trade
            log_fast_trade_entry(symbol, setup, order_id, filled_price, is_premium_estimated)
            
            return order_id

    except Exception as e:
        print(f"❌ Fast trade order error: {e}")
        return None

def monitor_fast_trades(access_token, watchlist_symbols):
    """Monitor for fast trade setups"""
    if not ENABLE_FAST_TRADING:
        return
    
    trader = UpstoxTrader(access_token)
    print(f"\n⚡ FAST TRADING MONITOR: Watching {len(watchlist_symbols)} symbols")
    
    # No new ENTRY orders after this time (exits still managed)
    NO_NEW_ENTRY_AFTER = "15:15"
    
    while True:
        if not is_market_open():
            time.sleep(60)
            continue
        
        # ── LATE-SESSION ENTRY BLOCK ─────────────────────────────────────────
        current_time_str = now_ist().strftime("%H:%M")
        skip_new_entries = (current_time_str >= NO_NEW_ENTRY_AFTER)
        if skip_new_entries and DEBUG_MODE:
            # Only print once per minute to avoid log spam
            if now_ist().second < 35:
                print(f"⏰ Fast trade new entries blocked after {NO_NEW_ENTRY_AFTER} "
                      f"(current: {current_time_str}) — exits still managed")
        # ── END LATE-SESSION BLOCK ────────────────────────────────────────────

        # ── PARALLEL CANDLE PREFETCH ─────────────────────────────────────────
        # Flush stale entries from last cycle, then fetch all symbols in parallel.
        # Subsequent fetch_5min_cached / fetch_15min_cached calls in the loop below
        # return instantly from the cache — no repeated network calls.
        clear_intraday_cache()
        active_symbols = [s for s in watchlist_symbols
                          if not (SYMBOL_TO_ISIN.get(s, "") in FAST_TRADE_5MIN_BLACKLIST)]
        if active_symbols:
            prefetch_candles_parallel(access_token, active_symbols)
        # ── END PREFETCH ─────────────────────────────────────────────────────

        for symbol in watchlist_symbols:
            try:
                # Get instrument key
                instrument_key = SYMBOL_TO_ISIN.get(symbol)
                if not instrument_key:
                    continue
                
                # ── DIRECTION-AWARE SKIP LOGIC ───────────────────────────────────────
                # First half: skip if already alerted in either direction.
                # Second half (>= SECOND_HALF_START): stocks that fired a LONG alert
                # earlier are re-watched exclusively for SHORT — capturing the
                # breakout-then-reversal pattern (morning squeeze → afternoon fade).
                # A stock is only fully skipped if it has already taken its SHORT.
                #
                # Early reversal mode (ENABLE_EARLY_REVERSAL):
                # Fresh symbols (no prior alert) before 12:30 are now also eligible
                # for a topping SHORT via detect_topping_reversal(strict=True).
                # This is separate from the second-half re-watch — it catches
                # ONGC / ETERNAL type reversals that happen at 10:30–12:15.
                current_time_str_skip = now_ist().strftime("%H:%M")
                in_second_half   = (ENABLE_SECOND_HALF_SHORT_REWATCH
                                    and current_time_str_skip >= SECOND_HALF_START)
                in_early_session = (current_time_str_skip < SECOND_HALF_START)

                with THREAD_LOCKS['FAST_TRADE_LONG_ALERTED']:
                    already_long  = symbol in FAST_TRADE_LONG_ALERTED
                with THREAD_LOCKS['FAST_TRADE_SHORT_ALERTED']:
                    already_short = symbol in FAST_TRADE_SHORT_ALERTED

                _second_half_short_watch = False
                _second_half_long_watch  = False
                _early_reversal_watch    = False   # pre-12:30 topping reversal mode

                if in_second_half and already_long and not already_short:
                    # LONG fired this morning → watch for reversal SHORT only
                    _second_half_short_watch = True
                    _second_half_long_watch  = False
                elif in_second_half and already_short and not already_long:
                    # SHORT fired this morning → watch for reversal LONG only
                    _second_half_long_watch  = True
                    _second_half_short_watch = False
                elif in_early_session and ENABLE_EARLY_REVERSAL:
                    # Pre-12:30: only fresh symbols (no prior alert today) are eligible
                    if already_long or already_short:
                        continue   # already traded this symbol today — done
                    _early_reversal_watch = True
                else:
                    _second_half_short_watch = False
                    _second_half_long_watch  = False
                    # Standard skip: already alerted in any direction → done for the day
                    if already_long or already_short:
                        continue
                # ── END DIRECTION-AWARE SKIP LOGIC ───────────────────────────────────

                # ── DUAL TIMEFRAME DATA FETCH (served from cache — no network call) ──
                # LONG squeeze  → 15min candles (wider candles filter out 5min noise)
                # SHORT pullback → 5min candles (faster reaction to intraday reversals)
                df_15m = fetch_15min_cached(access_token, instrument_key, symbol=symbol)
                df_5m  = fetch_5min_cached(access_token, instrument_key, bars=50, symbol=symbol)

                # Need at least one valid dataset
                if df_15m is None and df_5m is None:
                    continue
                # ── END DUAL TIMEFRAME FETCH ─────────────────────────────────────────

                # Get Klinger data (daily-resolution, shared by both setups)
                klinger_data = None
                if ENABLE_KLINGER_FILTER:
                    klinger_data = R3_LEVELS.get(instrument_key, {}).get('klinger')

                # Check for setups — each on its own timeframe
                long_setup  = detect_fast_long_setup(df_15m, klinger_data)  if df_15m is not None and len(df_15m)  >= 15 else None
                short_setup = detect_fast_short_setup(df_5m, klinger_data)  if df_5m  is not None and len(df_5m)   >= 30 else None

                # ── TOPPING REVERSAL ──────────────────────────────────────────────────
                # detect_fast_short_setup() exits early when price > bb_middle, which
                # blocks ALL topping candles (they sit at the upper band, not the mid).
                # detect_topping_reversal() fills that gap for both early session and
                # second-half re-watch modes.
                #   strict=True  → pre-12:30: Klinger confirm mandatory + tighter filters
                #   strict=False → post-12:30 re-watch: normal thresholds
                topping_setup = None
                if df_5m is not None and len(df_5m) >= 30:
                    if _early_reversal_watch or _second_half_short_watch:
                        topping_setup = detect_topping_reversal(
                            df_5m, klinger_data,
                            strict=_early_reversal_watch   # strict only before 12:30
                        )
                        if topping_setup and DEBUG_MODE:
                            mode = "EARLY strict" if _early_reversal_watch else "2nd-half"
                            print(f"🔄 {symbol}: Topping reversal [{mode}] "
                                  f"KL={topping_setup['klinger_status']} "
                                  f"vol={topping_setup['volume_ratio']:.2f}x "
                                  f"body={topping_setup['candle_size_pct']:.1f}%")
                # Merge topping into short_setup only when short_setup is empty
                if short_setup is None and topping_setup is not None:
                    short_setup = topping_setup
                # ── END TOPPING REVERSAL ──────────────────────────────────────────────

                # In second-half short-watch mode for this symbol: suppress any
                # new LONG signal — we only want to catch the reversal SHORT.
                if _second_half_short_watch and long_setup is not None:
                    if DEBUG_MODE:
                        print(f"🔄 {symbol}: Second-half rewatch — LONG suppressed, "
                              f"watching for SHORT only")
                    long_setup = None

                # In early-reversal or second-half short-watch mode: also suppress
                # LONG signals — only topping SHORT is relevant in these modes.
                if _early_reversal_watch and long_setup is not None:
                    if DEBUG_MODE:
                        print(f"🔄 {symbol}: Early reversal watch — LONG suppressed, "
                              f"watching for topping SHORT only")
                    long_setup = None

                # In second-half long-watch mode for this symbol: suppress any
                # new SHORT signal — we only want to catch the reversal LONG.
                if _second_half_long_watch and short_setup is not None:
                    if DEBUG_MODE:
                        print(f"🔄 {symbol}: Second-half rewatch — SHORT suppressed, "
                              f"watching for LONG only")
                    short_setup = None

                # For secondary gate RSI on the right timeframe:
                # LONG secondary gate will use df_15m; SHORT uses df_5m
                # Store both on the setup dicts for later use
                if long_setup  is not None: long_setup['_df']  = df_15m
                if short_setup is not None: short_setup['_df'] = df_5m

                # ── CONFLICT SUPPRESSION ─────────────────────────────────────────────
                # If BOTH long and short fired for the same stock in the same scan,
                # suppress both — whipsaw avoidance (e.g. HDFCBANK LONG squeeze +
                # SHORT pullback within 30 seconds on opening day)
                if long_setup and short_setup:
                    if (long_setup['confidence'] in ['HIGH', 'MEDIUM'] and
                            short_setup['confidence'] in ['HIGH', 'MEDIUM']):
                        if DEBUG_MODE:
                            print(f"⛔ {symbol}: Conflicting LONG+SHORT signals this scan — both suppressed")
                        long_setup  = None
                        short_setup = None
                # ── END CONFLICT SUPPRESSION ─────────────────────────────────────────

                # ── FII/DII TREND FILTER (fast trading) ──────────────────────────────
                # Apply multi-day institutional stance to fast trade signals:
                #   • LONG setup + strong FII sell (score <= -2) → suppress CE entry
                #   • SHORT setup + strong FII buy  (score >= +2) → suppress PE entry
                #   • Otherwise attach score to setup for logging context
                if ENABLE_FII_DII_TREND_FILTER:
                    ft_trend_score = get_fii_dii_trend_score(symbol)
                    if long_setup and long_setup['confidence'] in ['HIGH', 'MEDIUM']:
                        if ft_trend_score <= -2:
                            if DEBUG_MODE:
                                print(f"⛔ {symbol} LONG suppressed by FII/DII trend "
                                      f"(score={ft_trend_score:+d} — institutional headwind)")
                            long_setup = None
                        else:
                            long_setup['fii_trend_score'] = ft_trend_score
                    if short_setup and short_setup['confidence'] in ['HIGH', 'MEDIUM']:
                        if ft_trend_score >= 2:
                            if DEBUG_MODE:
                                print(f"⛔ {symbol} SHORT suppressed by FII/DII trend "
                                      f"(score={ft_trend_score:+d} — institutional accumulation contradicts PE)")
                            short_setup = None
                        else:
                            short_setup['fii_trend_score'] = ft_trend_score
                # ── END FII/DII TREND FILTER ──────────────────────────────────────────

                # Process setups — skip new entries after 15:15
                for setup in [long_setup, short_setup]:
                    if setup and setup['confidence'] in ['HIGH', 'MEDIUM']:

                        # Block new entries after NO_NEW_ENTRY_AFTER time
                        if skip_new_entries:
                            # Still manage existing trades (handled below) but no new ones
                            continue

                        # ── SECONDARY GATE (Klinger REJECTED + MEDIUM confidence) ──────────
                        # When Klinger disagrees with the signal we apply extra checks.
                        # Fixes applied vs v7:
                        #   1. RSI threshold raised to 65 (was 55) for LONG to cut false entries
                        #   2. SHORT secondary gate now requires KO < 0 — prevents SHORT signals
                        #      when Klinger is strongly positive (e.g. ONGC +1.086B)
                        #   3. Conflict suppression: if BOTH long and short fired for same stock
                        #      in the same scan cycle, suppress both to avoid whipsaw
                        if (ENABLE_FAST_TRADE_SECONDARY_GATE
                                and setup['confidence'] == 'MEDIUM'
                                and not setup.get('klinger_confirmed', False)):

                            # Use the timeframe-specific df stored on the setup:
                            # LONG → df_15m,  SHORT → df_5m
                            gate_df = setup.get('_df')
                            if gate_df is None or len(gate_df) < 14:
                                continue  # no data to evaluate — suppress

                            current_rsi = calculate_rsi(gate_df, period=14)
                            rsi_ok    = False
                            cloud_ok  = True   # default pass when cloud check is disabled
                            ko_dir_ok = True   # KO direction guard

                            # Extract KO value for direction guard — use numeric klinger_data
                            # directly instead of parsing the klinger_status string (fragile).
                            # klinger_data is already in scope from the fetch above.
                            klinger_ko = klinger_data.get('klinger', 0) if klinger_data else 0

                            if setup['signal'] == 'LONG':
                                rsi_ok = (current_rsi is not None
                                          and current_rsi >= FAST_TRADE_KLINGER_REJECTED_RSI_MIN)
                                if FAST_TRADE_KLINGER_REJECTED_CLOUD_PCT > 0:
                                    if len(gate_df) >= 26:
                                        tenkan    = (gate_df['high'].tail(9).max()  + gate_df['low'].tail(9).min())  / 2
                                        kijun     = (gate_df['high'].tail(26).max() + gate_df['low'].tail(26).min()) / 2
                                        cloud_mid = (tenkan + kijun) / 2
                                        price     = setup['entry_price']
                                        cloud_ok  = price >= cloud_mid * (1 + FAST_TRADE_KLINGER_REJECTED_CLOUD_PCT / 100)
                                    else:
                                        cloud_ok = False
                                ko_dir_ok = True  # No block needed for LONG direction

                            else:  # SHORT
                                rsi_ok = (current_rsi is not None
                                          and current_rsi <= FAST_TRADE_KLINGER_REJECTED_RSI_MAX_SHORT)
                                if FAST_TRADE_SHORT_REQUIRE_NEGATIVE_KO:
                                    ko_dir_ok = (klinger_ko < 0)

                                    # ── SHORT SOFT CONFIRMATION (ONGC-type fix, mirror of LONG) ──────
                                    # Problem: ONGC-type stocks build a breakdown slowly. KO starts
                                    # large positive (e.g. +181k on 1H) and declines steadily over
                                    # several bars, only crossing zero well after the move started.
                                    # Requiring KO < 0 blocks the entire early decline phase.
                                    # Fix: if KO has been DECLINING for 3+ consecutive bars, treat as
                                    # soft bearish confirmation even if KO is still slightly positive.
                                    # This mirrors the LONG soft confirm added for ONGC crossover issue.
                                    if not ko_dir_ok and klinger_data:
                                        ko_history = klinger_data.get('ko_history', [])
                                        if len(ko_history) >= 3:
                                            consistently_falling = all(
                                                ko_history[i] > ko_history[i + 1]
                                                for i in range(len(ko_history) - 3, len(ko_history) - 1)
                                            )
                                            if consistently_falling:
                                                ko_dir_ok = True
                                                if DEBUG_MODE:
                                                    print(f"✅ {symbol} SHORT soft confirm: KO declining "
                                                          f"{ko_history[-3]:.0f}→{ko_history[-2]:.0f}→"
                                                          f"{ko_history[-1]:.0f} (still positive but falling)")
                                    # ── END SHORT SOFT CONFIRMATION ──────────────────────────────────

                                    if not ko_dir_ok and DEBUG_MODE:
                                        print(f"⛔ {symbol} SHORT blocked by KO direction guard "
                                              f"(KO={klinger_ko:.0f} > 0 and not declining — "
                                              f"Klinger bullish, SHORT contradicted)")

                            if not (rsi_ok and cloud_ok and ko_dir_ok):
                                if DEBUG_MODE and ko_dir_ok:  # ko_dir_ok False already printed above
                                    rsi_str = f"{current_rsi:.1f}" if current_rsi is not None else "N/A"
                                    threshold = FAST_TRADE_KLINGER_REJECTED_RSI_MIN if setup['signal'] == 'LONG' else FAST_TRADE_KLINGER_REJECTED_RSI_MAX_SHORT
                                    direction_sym = '≥' if setup['signal'] == 'LONG' else '≤'
                                    print(f"⛔ {symbol} {setup['signal']} suppressed by secondary gate "
                                          f"(Klinger rejected, RSI={rsi_str} "
                                          f"[need {direction_sym}{threshold}], "
                                          f"Cloud={'✅' if cloud_ok else '❌'})")
                                continue  # skip — secondary gate not passed
                            else:
                                if DEBUG_MODE:
                                    rsi_str = f"{current_rsi:.1f}" if current_rsi is not None else "N/A"
                                    print(f"✅ {symbol} {setup['signal']} passed secondary gate "
                                          f"(Klinger rejected but RSI={rsi_str} + Cloud={'✅' if cloud_ok else 'N/A'})")
                        # ── END SECONDARY GATE ────────────────────────────────────────────



                        # Check daily order limits - THREAD SAFE
                        with THREAD_LOCKS['DAILY_ORDER_COUNT']:
                            with THREAD_LOCKS['FAST_TRADE_ORDER_COUNT']:
                                total_orders = (DAILY_ORDER_COUNT + BOX_ORDER_COUNT +
                                               RANGE_ORDER_COUNT + GAP_ORDER_COUNT +
                                               FAST_TRADE_ORDER_COUNT)
                        
                        if total_orders >= MAX_ORDERS_PER_DAY:
                            print("⚠️ Daily order limit reached for fast trading")
                            # Still watch this symbol for HA reversal even though we can't trade
                            add_to_ha_watchlist(symbol, setup['signal'], instrument_key,
                                                f"Daily order limit reached ({total_orders}/{MAX_ORDERS_PER_DAY})")
                            break
                        
                        # Check if recently traded this symbol - THREAD SAFE
                        with THREAD_LOCKS['LAST_ORDER_TIME']:
                            if symbol in LAST_ORDER_TIME:
                                time_since = (now_ist() - LAST_ORDER_TIME[symbol]).seconds
                                if time_since < MIN_ORDER_GAP_SECONDS:
                                    if DEBUG_MODE:
                                        print(f"⚠️ {symbol}: Too soon for new trade ({time_since}s)")
                                    continue
                        
                        # Execute trade
                        print(f"\n{'='*80}")
                        print(f"⚡ FAST TRADE SIGNAL: {symbol} {setup['signal']}")
                        print(f"{'='*80}")
                        print(f"Entry Type: {setup['entry_type']}")
                        print(f"Timeframe: {'15min' if setup['signal'] == 'LONG' else '5min'}")
                        print(f"Price: ₹{setup['entry_price']:.2f}")
                        print(f"Stop: ₹{setup['stop_loss']:.2f}")
                        print(f"Target: ₹{setup['target']:.2f}")
                        print(f"Volume Ratio: {setup['volume_ratio']:.2f}x")
                        print(f"Confidence: {setup['confidence']}")
                        if setup.get('klinger_status'):
                            print(f"Klinger: {setup['klinger_status']}")
                        # FII/DII trend score context
                        fts = setup.get('fii_trend_score')
                        if fts is not None:
                            if fts >= 2:
                                fts_label = "Strong institutional support"
                            elif fts == 1:
                                fts_label = "FII leading buy"
                            elif fts == 0:
                                fts_label = "Neutral"
                            elif fts == -1:
                                fts_label = "FII distributing — caution"
                            else:
                                fts_label = "Institutional headwind"
                            print(f"FII/DII Trend: {fts:+d} ({fts_label})")
                        print(f"{'='*80}")

                        # Strip internal keys before passing to order function
                        setup.pop('_df', None)
                        setup.pop('fii_trend_score', None)

                        # Place order
                        order_id = place_fast_trade_order(setup, trader, symbol, instrument_key)
                        if order_id:
                            # Order succeeded — remove from HA watchlist if it was there
                            remove_from_ha_watchlist(symbol)
                            _sig = setup.get('signal', 'LONG')
                            if _sig == 'LONG':
                                with THREAD_LOCKS['FAST_TRADE_LONG_ALERTED']:
                                    FAST_TRADE_LONG_ALERTED.add(symbol)
                            else:
                                with THREAD_LOCKS['FAST_TRADE_SHORT_ALERTED']:
                                    FAST_TRADE_SHORT_ALERTED.add(symbol)
                            # Keep legacy alias in sync for summary/log functions
                            with THREAD_LOCKS['FAST_TRADE_ALERTED_STOCKS']:
                                FAST_TRADE_ALERTED_STOCKS.add(symbol)
                            log_fast_trade_alert(symbol, setup, order_id)

                # Manage existing fast trades — use 5min df for exit monitoring
                manage_existing_fast_trades(symbol, df_5m, trader, klinger_data)
                
            except Exception as e:
                if DEBUG_MODE:
                    print(f"⚠️ Fast trading error for {symbol}: {e}")
        
        time.sleep(FAST_TRADE_CHECK_INTERVAL)

def manage_existing_fast_trades(symbol, df, trader, klinger_data):
    """Manage existing fast trades for a symbol"""
    trades_to_exit = []
    
    for trade_id, trade in list(ACTIVE_FAST_TRADES.items()):
        if trade['symbol'] != symbol:
            continue
        
        # Get current option price
        current_price = trader.get_ltp(trade['instrument_key'])
        if not current_price:
            continue
        
        # Check exit conditions
        exit_type, exit_reason = manage_fast_trade_exit(trade, current_price, df, klinger_data)
        
        if exit_type:
            trades_to_exit.append((trade_id, current_price, exit_type, exit_reason))
    
    # Execute exits
    for trade_id, exit_price, exit_type, exit_reason in trades_to_exit:
        exit_fast_trade(trade_id, exit_price, exit_type, exit_reason, trader)

def exit_fast_trade(trade_id, exit_price, exit_type, exit_reason, trader):
    """Exit a fast trade"""
    if trade_id not in ACTIVE_FAST_TRADES:
        return False
    
    trade = ACTIVE_FAST_TRADES[trade_id]
    
    # Calculate P&L
    entry_price = trade['entry_price']
    position_size = trade['quantity']
    
    if trade['fast_trade_signal'] == 'LONG':
        pnl = (exit_price - entry_price) * position_size
        pnl_pct = (exit_price - entry_price) / entry_price * 100
    else:
        pnl = (entry_price - exit_price) * position_size
        pnl_pct = (entry_price - exit_price) / entry_price * 100
    
    print(f"\n🔚 FAST TRADE EXIT: {trade['symbol']} {trade['fast_trade_signal']}")
    print(f"   Entry: ₹{entry_price:.2f} | Exit: ₹{exit_price:.2f}")
    print(f"   P&L: ₹{pnl:+.2f} ({pnl_pct:+.2f}%)")
    print(f"   Reason: {exit_reason}")
    
    try:
        # Place market exit order
        result = trader.place_order(
            instrument_key=trade['instrument_key'],
            quantity=position_size,
            transaction_type='SELL',
            product=ORDER_PRODUCT,
            order_type='MARKET',
            price=0
        )
        
        if result.get('status_code') == 200:
            # Update trade record
            trade['exit_price'] = exit_price
            trade['exit_time'] = now_ist()
            trade['exit_type'] = exit_type
            trade['exit_reason'] = exit_reason
            trade['pnl'] = pnl
            trade['pnl_pct'] = pnl_pct
            trade['duration'] = (trade['exit_time'] - trade['timestamp']).total_seconds() / 60
            
            # Move to closed trades
            CLOSED_FAST_TRADES.append(trade.copy())
            del ACTIVE_FAST_TRADES[trade_id]
            
            # Also remove from active positions if exists
            for pos_id, position in list(ACTIVE_POSITIONS.items()):
                if position.get('order_id') == trade.get('order_id'):
                    # Update with exit info
                    position.update({
                        'exit_price': exit_price,
                        'exit_time': now_ist(),
                        'exit_reason': f"FAST_TRADE_{exit_reason}",
                        'pnl': pnl,
                        'pnl_pct': pnl_pct
                    })
                    CLOSED_POSITIONS.append(position.copy())
                    del ACTIVE_POSITIONS[pos_id]
                    break
            
            # Log exit
            log_fast_trade_exit(trade)
            
            return True
            
    except Exception as e:
        print(f"❌ Fast trade exit error: {e}")
    
    return False

def log_fast_trade_entry(symbol, setup, order_id, entry_price, is_premium_estimated=False):
    """Log fast trade entry to CSV"""
    filename = FAST_TRADE_ENTRY_FILE
    file_exists = os.path.exists(filename)
    
    with open(filename, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow([
                'timestamp', 'symbol', 'signal', 'entry_price', 'stop_loss',
                'target', 'entry_type', 'order_id', 'volume_ratio',
                'candle_size_pct', 'bb_width', 'klinger_confirmed',
                'klinger_status', 'confidence', 'premium_source',
                'fii_trend_score', 'timeframe'
            ])
        
        writer.writerow([
            now_ist().strftime('%Y-%m-%d %H:%M:%S'),
            symbol,
            setup['signal'],
            entry_price,
            setup['stop_loss'],
            setup['target'],
            setup['entry_type'],
            order_id,
            setup['volume_ratio'],
            setup['candle_size_pct'],
            setup.get('bb_width', ''),
            setup.get('klinger_confirmed', False),
            setup.get('klinger_status', 'N/A'),
            setup['confidence'],
            'ESTIMATED' if is_premium_estimated else 'LTP',
            setup.get('fii_trend_score', 0),         # institutional stance score
            '15min' if setup['signal'] == 'LONG' else '5min'  # timeframe used
        ])

def log_fast_trade_exit(trade):
    """Log fast trade exit to CSV"""
    filename = FAST_TRADE_EXIT_FILE
    file_exists = os.path.exists(filename)
    
    with open(filename, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow([
                'exit_time', 'symbol', 'signal', 'entry_price', 'exit_price',
                'stop_loss', 'target', 'pnl', 'pnl_pct', 'entry_time',
                'exit_time', 'duration_min', 'exit_type', 'exit_reason',
                'order_id', 'entry_type', 'premium_source'
            ])
        
        writer.writerow([
            trade['exit_time'].strftime('%Y-%m-%d %H:%M:%S'),
            trade['symbol'],
            trade['fast_trade_signal'],
            trade['entry_price'],
            trade['exit_price'],
            trade.get('stop_loss', 0),
            trade.get('target', 0),
            trade['pnl'],
            trade['pnl_pct'],
            trade['timestamp'].strftime('%Y-%m-%d %H:%M:%S'),
            trade['exit_time'].strftime('%Y-%m-%d %H:%M:%S'),
            trade['duration'],
            trade['exit_type'],
            trade['exit_reason'],
            trade.get('order_id', 'N/A'),
            trade.get('fast_trade_entry_type', 'N/A'),
            'ESTIMATED' if trade.get('is_premium_estimated', False) else 'LTP'
        ])

def log_fast_trade_alert(symbol, setup, order_id):
    """Log fast trade alert"""
    log_file = "fast_trading_alerts.txt"
    with open(log_file, 'a', encoding='utf-8') as f:
        f.write(f"\n{'='*100}\n")
        f.write(f"FAST TRADE ALERT: {symbol} {setup['signal']}\n")
        f.write(f"Time: {now_ist().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Entry Type: {setup['entry_type']}\n")
        f.write(f"Price: ₹{setup['entry_price']:.2f}\n")
        f.write(f"Stop: ₹{setup['stop_loss']:.2f}\n")
        f.write(f"Target: ₹{setup['target']:.2f}\n")
        f.write(f"Volume Ratio: {setup['volume_ratio']:.2f}x\n")
        f.write(f"Confidence: {setup['confidence']}\n")
        f.write(f"Order ID: {order_id}\n")
        f.write(f"{'='*100}\n")

# ========== DATA FETCHING ==========
def get_all_fno_equities(access_token):
    print("📥 Downloading F&O stock list...")
    url = "https://assets.upstox.com/market-quote/instruments/exchange/complete.csv.gz"
    try:
        df = pd.read_csv(url, compression='gzip')
        fo = df[df['exchange']=='NSE_FO']
        fo_symbols = fo['tradingsymbol'].str.replace(r'\d{2}[A-Z]{3}\d{2,4}.*','', regex=True).str.strip().unique()
        fo_symbols = set([s for s in fo_symbols if s])
        eq = df[(df['exchange']=='NSE_EQ') & (df['tradingsymbol'].isin(fo_symbols))].copy()
        eq = eq.drop_duplicates(subset=['tradingsymbol'])
        keys = eq['instrument_key'].tolist()
        sym = dict(zip(eq['instrument_key'], eq['tradingsymbol']))
        print(f"✅ Found {len(keys)} F&O stocks\n")
        return keys, sym
    except Exception as e:
        print(f"❌ Error: {e}")
        return [], {}

def fetch_historical_ohlc(access_token, instrument_key, target_date):
    """Fetch OHLC data for a specific date using v2 API.
    Retries once on 429 with a 5-second back-off."""
    date_str = (target_date.strftime('%Y-%m-%d')
                if isinstance(target_date, datetime) or hasattr(target_date, 'strftime')
                else str(target_date))
    url = f"https://api.upstox.com/v2/historical-candle/{instrument_key}/day/{date_str}/{date_str}"
    for attempt in range(2):   # 1 normal attempt + 1 retry on 429
        try:
            resp = _get_upstox_session(access_token).get(url, timeout=15)
            if resp.status_code == 200:
                data    = resp.json()
                candles = data.get("data", {}).get("candles", [])
                if not candles:
                    return None
                candle = candles[0]
                return {
                    "date":   target_date,
                    "open":   candle[1],
                    "high":   candle[2],
                    "low":    candle[3],
                    "close":  candle[4],
                    "volume": candle[5],
                }
            elif resp.status_code == 429:
                if attempt == 0:
                    if DEBUG_MODE:
                        print(f"⚠️ fetch_historical_ohlc 429 for {instrument_key} — waiting 5s")
                    time.sleep(5)
                    continue   # retry once
                return None
            else:
                return None
        except Exception as e:
            if DEBUG_MODE:
                print(f" OHLC fetch exception: {e}")
            return None
    return None

def fetch_volume_history(access_token, instrument_key, end_date, days=40):
    """Fetch volume history using cached candle data"""
    # Use cached candle fetching instead of direct API call
    symbol = instrument_key.split('|')[-1] if '|' in instrument_key else instrument_key.split(':')[-1]
    df = get_cached_or_fetch_candles(access_token, symbol, instrument_key)
    
    if df is None or len(df) < days:
        return None
    
    # Filter to requested date range
    df = df[df['date'] <= pd.Timestamp(end_date)]
    df = df.tail(days)
    
    return df

def get_live_prices_batch(access_token, instrument_keys):
    """Fetch live prices using ISIN keys and map responses back"""
    if not instrument_keys:
        return {}
    
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {access_token}"
    }
    
    url = "https://api.upstox.com/v2/market-quote/quotes"
    results = {}
    
    for i in range(0, len(instrument_keys), MAX_INSTRUMENTS_PER_BATCH):
        chunk = instrument_keys[i:i+MAX_INSTRUMENTS_PER_BATCH]
        params = [('instrument_key', key) for key in chunk]
        try:
            response = _get_upstox_session(access_token).get(url, params=params, timeout=30)
            if DEBUG_MODE and i == 0:
                print(f"📡 Batch API Call #{i//MAX_INSTRUMENTS_PER_BATCH + 1}: Status {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                if 'data' in data:
                    for response_key, quote in data['data'].items():
                        nk_response = norm_key(response_key)
                        if nk_response in R3_LEVELS:
                            isin_key = nk_response
                        else:
                            symbol = response_key.split('|')[-1] if '|' in response_key else response_key.split(':')[-1]
                            isin_key = SYMBOL_TO_ISIN.get(symbol)
                            if not isin_key:
                                for stored_key, stored_info in R3_LEVELS.items():
                                    if stored_info['symbol'] == symbol:
                                        isin_key = stored_key
                                        break
                        if isin_key and isin_key in R3_LEVELS:
                            ohlc_data = quote.get('ohlc', {})
                            results[isin_key] = {
                                'ltp': quote.get('last_price'),
                                'high': ohlc_data.get('high'),
                                'low': ohlc_data.get('low'),
                                'open': ohlc_data.get('open'),
                                'close': ohlc_data.get('close'),
                                'volume': quote.get('volume'),
                                'timestamp': now_ist()
                            }
            elif response.status_code == 429:
                print(" ⚡ Rate limit hit, waiting...")
                time.sleep(5)
                continue
        except Exception as e:
            if DEBUG_MODE:
                print(f" ❌ Batch fetch error: {e}")
        if i + MAX_INSTRUMENTS_PER_BATCH < len(instrument_keys):
            time.sleep(0.5)
    return results

# ========== CALCULATION FUNCTIONS ==========
def calc_r3(h, l, c):
    p = (h + l + c) / 3.0
    r3 = p + 2*(h - l)
    return p, r3

def calc_s3(h, l, c):
    """Calculate S3 (Support Level 3)"""
    p = (h + l + c) / 3.0
    s3 = p - 2*(h - l)
    return p, s3

def init_one(access_token, args):
    key, symbol, yday = args
    try:
        key = norm_key(key)

        # Small throttle: 150ms between worker calls prevents 429 burst
        # when all 3 workers fire simultaneously across 205 stocks.
        time.sleep(0.15)

        # Use per-symbol lock to prevent duplicate concurrent fetches
        with get_cache_lock(symbol):
            vh = get_cached_or_fetch_candles(access_token, symbol, key)
        
        if vh is None or vh.empty:
            return None, 'no_data'
        
        weekday_data = vh[vh['date'].dt.weekday < 5]
        if len(weekday_data) < VOLUME_LOOKBACK_DAYS:
            return None, 'insufficient_data'
        
        avg_vol = weekday_data['volume'].tail(VOLUME_LOOKBACK_DAYS).mean()
        if not pd.notna(avg_vol) or avg_vol <= 0 or avg_vol < MIN_AVG_VOLUME:
            return None, 'volume_filtered'

        # ── FIX #2: Try to get yesterday OHLC from the already-loaded vh first.
        # This avoids a separate Upstox API call that will silently fail with an
        # expired/invalid token, causing every stock to be dropped as 'no_ohlc'.
        yday_str = yday.strftime('%Y-%m-%d') if hasattr(yday, 'strftime') else str(yday)
        yday_ts  = pd.Timestamp(yday_str)

        # Look for an exact date match inside the cached daily candles
        yday_row = vh[vh['date'].dt.normalize() == yday_ts]
        if not yday_row.empty:
            row = yday_row.iloc[-1]
            ohlc = {
                'date':   yday,
                'open':   float(row['open']),
                'high':   float(row['high']),
                'low':    float(row['low']),
                'close':  float(row['close']),
                'volume': float(row['volume']),
            }
            if DEBUG_MODE:
                print(f"📋 {symbol}: OHLC sourced from cache (no API call needed)")
        else:
            # Fallback: fetch from Upstox API (requires valid token)
            ohlc = fetch_historical_ohlc(access_token, key, yday)
            if not ohlc:
                # Last resort: use the most recent candle in the cache
                if not vh.empty:
                    row = vh.iloc[-1]
                    ohlc = {
                        'date':   row['date'],
                        'open':   float(row['open']),
                        'high':   float(row['high']),
                        'low':    float(row['low']),
                        'close':  float(row['close']),
                        'volume': float(row['volume']),
                    }
                    if DEBUG_MODE:
                        print(f"⚠️ {symbol}: OHLC API failed — using latest cache row ({row['date'].date()})")
                else:
                    return None, 'no_ohlc'
        
        pivot, r3 = calc_r3(ohlc['high'], ohlc['low'], ohlc['close'])
        _, s3 = calc_s3(ohlc['high'], ohlc['low'], ohlc['close'])
        
        # Reuse already-loaded vh for Klinger (avoids second fetch)
        klinger_data = None
        if ENABLE_KLINGER_FILTER:
            if len(vh) >= MIN_CANDLES_FOR_KLINGER:
                klinger, signal_line, histogram = calculate_klinger_adaptive(vh, symbol)
                if klinger is not None and len(klinger) >= 2:
                    ko_history_len = min(5, len(klinger))
                    ko_history_init = [float(klinger.iloc[-(ko_history_len - i)]) for i in range(ko_history_len - 1, -1, -1)]
                    klinger_data = {
                        'klinger': float(klinger.iloc[-1]),
                        'signal': float(signal_line.iloc[-1]),
                        'histogram': float(histogram.iloc[-1]),
                        'klinger_prev': float(klinger.iloc[-2]),
                        'signal_prev': float(signal_line.iloc[-2]),
                        'ko_history': ko_history_init,
                        'last_update': now_ist(),
                        'candle_count': len(vh),
                        'adaptive_params': len(vh) < 90 if ADAPTIVE_KLINGER_LOOKBACK else False
                    }
                    if DEBUG_MODE:
                        adaptive_msg = " (Adaptive)" if klinger_data.get('adaptive_params') else ""
                        print(f" ✓ {symbol}: Klinger initialized (KO: {klinger_data['klinger']:.2f}{adaptive_msg})")
        
        return ({
            'key': key,
            'symbol': symbol,
            'r3': r3,
            's3': s3,
            'pivot': pivot,
            'yesterday_high': ohlc['high'],
            'yesterday_low': ohlc['low'],
            'yesterday_close': ohlc['close'],
            'avg_volume_20d': avg_vol,
            'box_high': ohlc['high'],
            'box_low': ohlc['low'],
            'klinger': klinger_data
        }, 'success')
    except Exception as e:
        if DEBUG_MODE:
            print(f"Init error for {symbol}: {e}")
        return None, 'error'

def reset_initialization():
    """Reset initialization state to allow retry"""
    global INITIALIZATION_RETRIES, R3_LEVELS, SYMBOL_TO_ISIN, ISIN_TO_SYMBOL, SYMBOL_TO_FO_KEY, VOLUME_DATA
    INITIALIZATION_RETRIES = 0
    R3_LEVELS.clear()
    SYMBOL_TO_ISIN.clear()
    ISIN_TO_SYMBOL.clear()
    SYMBOL_TO_FO_KEY.clear()
    VOLUME_DATA.clear()
    print("🔄 Initialization state reset")


def initialize_r3_levels(access_token, keys, symbols):
    global R3_LEVELS, SYMBOL_TO_ISIN, ISIN_TO_SYMBOL, SYMBOL_TO_FO_KEY, VOLUME_DATA, INITIALIZATION_RETRIES

    # Allow up to 3 retries
    if INITIALIZATION_RETRIES >= 3:
        print("❌ Max initialization retries reached")
        return False

    if INITIALIZATION_RETRIES > 0:
        print(f"\n🔄 Retry #{INITIALIZATION_RETRIES} of initialization...")
        time.sleep(5)  # Wait before retry

    INITIALIZATION_RETRIES += 1
    
    # Initialize cache directory
    if ENABLE_CANDLE_CACHE:
        init_cache_directory()
        load_cache_stats()
    
    ref = previous_trading_day()
    print(f"\n📊 Calculating R3/S3/Box levels + Klinger using {ref} data...")
    print(f"Using {MAX_WORKERS} workers | Min Volume: {MIN_AVG_VOLUME:,}")
    if ENABLE_KLINGER_FILTER:
        print(f"🔥 Klinger Oscillator: ENABLED (Fast={KLINGER_FAST}, Slow={KLINGER_SLOW}, Signal={KLINGER_SIGNAL})")
        if ADAPTIVE_KLINGER_LOOKBACK:
            print(f"   Adaptive Mode: ON (Short: Fast={KLINGER_FAST_SHORT}, Slow={KLINGER_SLOW_SHORT}, Signal={KLINGER_SIGNAL_SHORT})")
    if ENABLE_CANDLE_CACHE:
        print(f"💾 Candle Cache: ENABLED (Min candles: {MIN_CANDLES_FOR_KLINGER})")
    print()
    
    ok = volf = no_data = insufficient = no_ohlc = 0
    tasks = [(k, symbols.get(k) or symbols.get(norm_key(k)) or k.split('|')[-1].split(':')[-1], ref) for k in keys]
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {ex.submit(init_one, access_token, t): t for t in tasks}
        for i, f in enumerate(as_completed(futs), 1):
            if i % 25 == 0:
                print(f" Progress: {i}/{len(keys)} | Success: {ok}")
            res, status = f.result()
            if status == 'success' and res:
                nk = norm_key(res['key'])
                R3_LEVELS[nk] = {
                    'symbol': res['symbol'],
                    'r3': res['r3'],
                    's3': res['s3'],
                    'pivot': res['pivot'],
                    'yesterday_high': res['yesterday_high'],
                    'yesterday_low': res['yesterday_low'],
                    'yesterday_close': res['yesterday_close'],
                    'avg_volume_20d': res['avg_volume_20d'],
                    'box_high': res.get('box_high', res['yesterday_high']),
                    'box_low': res.get('box_low', res['yesterday_low']),
                    'klinger': res.get('klinger')
                }
                VOLUME_DATA[nk] = res['avg_volume_20d']
                ok += 1
            elif status == 'volume_filtered':
                volf += 1
            elif status == 'no_data':
                no_data += 1
            elif status == 'insufficient_data':
                insufficient += 1
            elif status == 'no_ohlc':
                no_ohlc += 1
    
    SYMBOL_TO_ISIN = {info['symbol']: isin_key for isin_key, info in R3_LEVELS.items()}
    ISIN_TO_SYMBOL = {isin_key: info['symbol'] for isin_key, info in R3_LEVELS.items()}

    # Build SYMBOL_TO_FO_KEY: map each symbol -> its NSE_FO continuous/spot instrument_key.
    # This is used as a fallback in fetch_5min_candle_data when Upstox intraday/historical
    # endpoints are tried (they require an NSE_FO key rather than an NSE_EQ key).
    try:
        _inst_url = "https://assets.upstox.com/market-quote/instruments/exchange/complete.csv.gz"
        _inst_df = pd.read_csv(_inst_url, compression='gzip')
        # Keep only NSE_FO rows; prefer EQ/XX (spot/index futures) instrument types
        _fo_df = _inst_df[_inst_df['exchange'] == 'NSE_FO'].copy()
        # Strip expiry suffix to get the base symbol (e.g. "RELIANCE24JUL25000CE" -> "RELIANCE")
        _fo_df['base_sym'] = (
            _fo_df['tradingsymbol']
            .str.replace(r'\d{2}[A-Z]{3}\d{2,4}.*', '', regex=True)
            .str.strip()
        )
        # For each base symbol keep the row whose instrument_key we prefer.
        # Priority: instrument_type == 'EQ' (equity futures spot) first, then first available.
        _fo_eq = _fo_df[_fo_df.get('instrument_type', pd.Series(dtype=str)) == 'EQ']
        if 'instrument_type' in _fo_df.columns:
            _fo_eq = _fo_df[_fo_df['instrument_type'] == 'EQ']
            _fo_other = _fo_df[~(_fo_df['instrument_type'] == 'EQ')]
        else:
            _fo_eq = _fo_df.iloc[0:0]  # empty
            _fo_other = _fo_df
        # Build mapping: first from EQ-type rows, then fill gaps from remaining rows
        _fo_key_map = {}
        for _df_part in [_fo_other, _fo_eq]:  # lower priority first so EQ wins
            for _, _row in _df_part.iterrows():
                _fo_key_map[_row['base_sym']] = _row['instrument_key']
        # Only populate for symbols we actually track
        SYMBOL_TO_FO_KEY = {sym: _fo_key_map[sym] for sym in SYMBOL_TO_ISIN if sym in _fo_key_map}
        print(f"✅ SYMBOL_TO_FO_KEY built: {len(SYMBOL_TO_FO_KEY)} symbols mapped to NSE_FO keys")
    except Exception as _e:
        print(f"⚠️ Could not build SYMBOL_TO_FO_KEY ({_e}); Upstox 5min fallback will use NSE_EQ keys")
    
    # Count Klinger success
    klinger_success = sum(1 for info in R3_LEVELS.values() if info.get('klinger') is not None)
    klinger_adaptive = sum(1 for info in R3_LEVELS.values() 
                          if info.get('klinger') and info['klinger'].get('adaptive_params'))
    
    print(f"\n{'='*100}")
    print(f"✅ Successfully initialized: {ok} stocks")
    if ENABLE_KLINGER_FILTER:
        print(f"🔥 Klinger data available: {klinger_success} stocks ({(klinger_success/ok*100):.1f}%)")
        if ADAPTIVE_KLINGER_LOOKBACK and klinger_adaptive > 0:
            print(f"   Adaptive parameters used: {klinger_adaptive} stocks")
    if ENABLE_CANDLE_CACHE:
        print(f"💾 Cache Statistics:")
        print(f"   Cache Hits: {CACHE_STATS['cache_hits']}")
        print(f"   Cache Misses: {CACHE_STATS['cache_misses']}")
        if CACHE_STATS['cache_hits'] + CACHE_STATS['cache_misses'] > 0:
            hit_rate = CACHE_STATS['cache_hits'] / (CACHE_STATS['cache_hits'] + CACHE_STATS['cache_misses']) * 100
            print(f"   Hit Rate: {hit_rate:.1f}%")
    total_filtered = volf + no_data + insufficient + no_ohlc
    print(f"⚠️ Filtered out: {total_filtered} stocks")
    if total_filtered > 0:
        print(f"   • Volume too low  : {volf}")
        print(f"   • No candle data  : {no_data}")
        print(f"   • Insufficient days: {insufficient}")
        print(f"   • No OHLC data    : {no_ohlc}")
    print(f"{'='*100}\n")
    
    # Save cache stats
    if ENABLE_CANDLE_CACHE:
        save_cache_stats()

    if ok == 0 and INITIALIZATION_RETRIES < 3:
        print("⚠️ No stocks initialized, will retry...")
        return False

    return ok > 0

# ========== R3/S3 BREAKOUT DETECTION ==========

# Staleness config: if first confirmation has not been followed by a second
# within MAX_SCANS_WITHOUT_PROGRESS scans, reset the counter entirely.
# This fixes AMBUJACEM-type scenarios where count never reaches 2/2.
MAX_SCANS_WITHOUT_PROGRESS = 3   # ~90 seconds at 30s per scan

def reset_stale_breach_states():
    """Clean up old breach states that weren't confirmed.
    Also resets counters that have been stuck at count=1 for too many scans
    (AMBUJACEM-type fix: confirmation counter resets after 3 scans with no progress).
    """
    current_time = now_ist()
    stale_keys = []
    for key, state in LAST_BREAKOUT_STATE.items():
        elapsed = (current_time - state['first_breach_time']).seconds
        # Standard: expired window
        if elapsed > BREACH_TIME_WINDOW:
            stale_keys.append(key)
            continue
        # New: stuck at count=1 with no second confirmation in 3 scans
        scans_since_last = state.get('scans_since_last_breach', 0) + 1
        state['scans_since_last_breach'] = scans_since_last
        if state['breach_count'] == 1 and scans_since_last >= MAX_SCANS_WITHOUT_PROGRESS:
            stale_keys.append(key)
            if DEBUG_MODE:
                symbol = ISIN_TO_SYMBOL.get(key, key)
                print(f"🔄 {symbol}: Confirmation counter reset (stuck at 1/{BREACH_CONFIRMATION_CYCLES} "
                      f"for {scans_since_last} scans)")
    for key in stale_keys:
        del LAST_BREAKOUT_STATE[key]

def reset_stale_box_states():
    """Clean stale box breach states"""
    current_time = now_ist()
    stale = [k for k, s in LAST_BOX_STATE.items() 
             if (current_time - s['first_breach_time']).seconds > BREACH_TIME_WINDOW]
    for k in stale:
        del LAST_BOX_STATE[k]

def reset_stale_bounce_states():
    """Clean stale bounce states"""
    current_time = now_ist()
    stale = [k for k, s in LAST_BOUNCE_STATE.items() 
             if (current_time - s['first_breach_time']).seconds > BREACH_TIME_WINDOW]
    for k in stale:
        del LAST_BOUNCE_STATE[k]

def check_breakout(key, live):
    """Enhanced R3 breakout check with false alert prevention"""
    info = R3_LEVELS.get(key)
    if not info:
        return None

    # ── SECOND-HALF REVERSE WATCH (R3 LONG) ─────────────────────────────────
    # Already fired R3 LONG → skip entirely.
    # Fired S3 SHORT earlier → allow R3 LONG re-entry only in 2nd half (reversal bounce).
    if info['symbol'] in R3_ALERTED_STOCKS:
        return None   # already took the R3 LONG today
    _in_second_half_r3 = (ENABLE_SECOND_HALF_SHORT_REWATCH
                          and now_ist().strftime("%H:%M") >= SECOND_HALF_START)
    if info['symbol'] in S3_ALERTED_STOCKS and not _in_second_half_r3:
        return None   # had S3 SHORT but too early for reverse LONG
    
    if live['high'] is None or info['r3'] is None or info['r3'] == 0:
        return None
    current_price = live['ltp']
    r3_level = info['r3']
    
    # VALIDATION 1: Basic Breach Check
    if live['high'] < r3_level:
        if key in LAST_BREAKOUT_STATE:
            del LAST_BREAKOUT_STATE[key]
        return None
    
    # VALIDATION 2: Price Sustainability
    # When ltp dips below threshold temporarily, preserve state — don't delete on noise.
    # Let BREACH_TIME_WINDOW handle expiry.
    sustainability_threshold = r3_level * (1 + PRICE_SUSTAINABILITY_PERCENT / 100)
    if current_price < sustainability_threshold:
        if DEBUG_MODE:
            print(f"⚠️ {info['symbol']}: Touched R3 but price not sustainable " 
                  f"(Current: ₹{current_price:.2f} vs Required: ₹{sustainability_threshold:.2f})")
        if key in LAST_BREAKOUT_STATE:
            LAST_BREAKOUT_STATE[key]['scans_since_last_breach'] = \
                LAST_BREAKOUT_STATE[key].get('scans_since_last_breach', 0) + 1
        return None
    
    # VALIDATION 3: Volume Check
    cur_vol = live.get('volume') or 0
    avg20 = info['avg_volume_20d']
    if avg20 <= 0:
        return None
    ratio = cur_vol / avg20
    thr = dynamic_volume_threshold()

    # ── FII/DII TREND RELIEF (LONG/CE) ───────────────────────────────────────
    # Volume threshold relaxation based on multi-day institutional stance:
    #   score >= 2 (strong accumulation / unusual reversal) → 10% relief
    #   score == 1 (FII leading buy / DII sell)             →  5% relief
    #   score <= 0                                          → label only, no relief
    fii_trend_score = 0
    fii_trend_label = ""
    if ENABLE_FII_DII_TREND_FILTER:
        fii_trend_score = get_fii_dii_trend_score(info['symbol'])
        if fii_trend_score >= 2:
            thr = thr * FII_DII_TREND_VOLUME_RELIEF          # 10% relief
            fii_trend_label = f" [FII score={fii_trend_score:+d} → vol thr relaxed to {thr:.2f}x]"
        elif fii_trend_score == 1:
            thr = thr * (1 - (1 - FII_DII_TREND_VOLUME_RELIEF) / 2)  # 5% relief
            fii_trend_label = f" [FII score={fii_trend_score:+d} → vol thr relaxed to {thr:.2f}x]"
        elif fii_trend_score < 0:
            fii_trend_label = f" [FII score={fii_trend_score:+d} headwind]"
    # ── END FII/DII TREND RELIEF ──────────────────────────────────────────────

    if ratio < thr:
        return None

    # VALIDATION 4: Consecutive Confirmation
    current_time = now_ist()
    if key not in LAST_BREAKOUT_STATE:
        LAST_BREAKOUT_STATE[key] = {
            'breach_count': 1,
            'first_breach_time': current_time,
            'last_breach_time': current_time,
            'breach_type': 'R3',
            'max_price': current_price,
            'volume_ratios': [ratio],
            'scans_since_last_breach': 0
        }
        if DEBUG_MODE:
            print(f"📊 {info['symbol']}: First R3 breach detected at ₹{current_price:.2f} "
                  f"(1/{BREACH_CONFIRMATION_CYCLES} confirmations){fii_trend_label}")
        return None
    
    state = LAST_BREAKOUT_STATE[key]
    time_since_first = (current_time - state['first_breach_time']).seconds
    if time_since_first > BREACH_TIME_WINDOW:
        LAST_BREAKOUT_STATE[key] = {
            'breach_count': 1,
            'first_breach_time': current_time,
            'last_breach_time': current_time,
            'breach_type': 'R3',
            'max_price': current_price,
            'volume_ratios': [ratio],
            'scans_since_last_breach': 0
        }
        if DEBUG_MODE:
            print(f"⏳ {info['symbol']}: Breach window expired, restarting confirmation")
        return None
    
    state['breach_count'] += 1
    state['last_breach_time'] = current_time
    state['max_price'] = max(state['max_price'], current_price)
    state['volume_ratios'].append(ratio)
    state['scans_since_last_breach'] = 0  # reset staleness counter on progress
    
    if state['breach_count'] >= BREACH_CONFIRMATION_CYCLES:
        # VALIDATION 5: Volume Persistence
        avg_volume_ratio = sum(state['volume_ratios']) / len(state['volume_ratios'])
        if avg_volume_ratio < thr * 0.9:
            if DEBUG_MODE:
                print(f"⚠️ {info['symbol']}: Volume not persistent " 
                      f"(Avg: {avg_volume_ratio:.2f}x vs Required: {thr*0.9:.2f}x)")
            del LAST_BREAKOUT_STATE[key]
            return None
        
        # VALIDATION 6: Price Momentum
        price_gain = ((current_price - r3_level) / r3_level) * 100
        if price_gain < 0.3:
            if DEBUG_MODE:
                print(f"⚠️ {info['symbol']}: Insufficient momentum above R3 (Gain: {price_gain:.2f}%)")
            return None
        
        # ✅ ALL VALIDATIONS PASSED
        print(f"\n✅ {info['symbol']}: R3 BREAKOUT CONFIRMED!")
        print(f" Confirmations: {state['breach_count']} | Time: {time_since_first}s")
        print(f" Max price: ₹{state['max_price']:.2f} | Avg volume: {avg_volume_ratio:.2f}x")
        del LAST_BREAKOUT_STATE[key]
        
        return {
            'symbol': info['symbol'],
            'instrument_key': key,
            'r3': r3_level,
            'current_price': current_price,
            'high': live['high'],
            'volume_ratio': ratio,
            'current_volume': cur_vol,
            'avg_volume': avg20,
            'timestamp': current_time,
            'yesterday_close': info['yesterday_close'],
            'volume_threshold_used': thr,
            'breakout_type': 'CE',
            'strategy': 'R3',
            'confirmation_cycles': state['breach_count'],
            'time_to_confirm': time_since_first
        }
    
    if DEBUG_MODE:
        print(f"📊 {info['symbol']}: R3 breach #{state['breach_count']}/{BREACH_CONFIRMATION_CYCLES}")
    return None

def check_breakdown(key, live):
    """Enhanced S3 breakdown check with false alert prevention"""
    info = R3_LEVELS.get(key)
    if not info:
        return None

    # ── SECOND-HALF REVERSE WATCH (S3) ───────────────────────────────────────
    # If already fired S3 SHORT, skip entirely.
    # If fired R3 LONG earlier and now in 2nd half → allow S3 SHORT re-entry.
    if info['symbol'] in S3_ALERTED_STOCKS:
        return None   # already took the S3 SHORT today
    _in_second_half_s3 = (ENABLE_SECOND_HALF_SHORT_REWATCH
                          and now_ist().strftime("%H:%M") >= SECOND_HALF_START)
    if info['symbol'] in R3_ALERTED_STOCKS and not _in_second_half_s3:
        return None   # had R3 LONG but too early for reverse SHORT
    
    if live['low'] is None or info.get('s3') is None or info['s3'] == 0:
        return None
    
    current_price = live['ltp']
    s3_level = info['s3']
    
    # VALIDATION 1: Basic Breach Check
    if live['low'] > s3_level:
        if key in LAST_BREAKOUT_STATE and LAST_BREAKOUT_STATE[key].get('breach_type') == 'S3':
            del LAST_BREAKOUT_STATE[key]
        return None
    
    # VALIDATION 2: Price Sustainability
    # KEY FIX: When ltp bounces above threshold temporarily, preserve state — don't
    # delete on noise. Bump staleness counter, let BREACH_TIME_WINDOW handle expiry.
    sustainability_threshold = s3_level * (1 - PRICE_SUSTAINABILITY_PERCENT / 100)
    if current_price > sustainability_threshold:
        if DEBUG_MODE:
            print(f"⚠️ {info['symbol']}: Touched S3 but price not sustainable " 
                  f"(Current: ₹{current_price:.2f} vs Required: ₹{sustainability_threshold:.2f})")
        if key in LAST_BREAKOUT_STATE and LAST_BREAKOUT_STATE[key].get('breach_type') == 'S3':
            LAST_BREAKOUT_STATE[key]['scans_since_last_breach'] = \
                LAST_BREAKOUT_STATE[key].get('scans_since_last_breach', 0) + 1
        return None
    
    # VALIDATION 3: Volume Check
    cur_vol = live.get('volume') or 0
    avg20 = info['avg_volume_20d']
    if avg20 <= 0:
        return None
    ratio = cur_vol / avg20
    thr = dynamic_volume_threshold()

    # ── FII/DII TREND RELIEF (SHORT/PE) ──────────────────────────────────────
    # Volume threshold relaxation for institutional distribution signals:
    #   score >= 2  → suppress PE entirely (FII accumulating = contradicts short)
    #   score == -1 → 5% relief  (FII distributing — moderate conviction)
    #   score <= -2 → 10% relief (strong distribution / unusual sell reversal)
    fii_trend_score_bd = 0
    fii_trend_label_bd = ""
    if ENABLE_FII_DII_TREND_FILTER:
        fii_trend_score_bd = get_fii_dii_trend_score(info['symbol'])
        if fii_trend_score_bd >= 2:
            # Strong institutional buying — suppress PE breakdown signal
            if DEBUG_MODE:
                print(f"⛔ {info['symbol']}: S3 breakdown suppressed — FII trend score "
                      f"{fii_trend_score_bd:+d} (strong accumulation contradicts PE)")
            return None
        elif fii_trend_score_bd <= -2:
            thr = thr * FII_DII_TREND_VOLUME_RELIEF           # 10% relief
            fii_trend_label_bd = f" [FII score={fii_trend_score_bd:+d} → vol thr relaxed to {thr:.2f}x]"
        elif fii_trend_score_bd == -1:
            thr = thr * (1 - (1 - FII_DII_TREND_VOLUME_RELIEF) / 2)  # 5% relief
            fii_trend_label_bd = f" [FII score={fii_trend_score_bd:+d} → vol thr relaxed to {thr:.2f}x]"
        elif fii_trend_score_bd > 0:
            fii_trend_label_bd = f" [FII score={fii_trend_score_bd:+d} headwind for PE]"
    # ── END FII/DII TREND RELIEF ──────────────────────────────────────────────

    if ratio < thr:
        return None

    # VALIDATION 4: Consecutive Confirmation
    current_time = now_ist()
    if key not in LAST_BREAKOUT_STATE or LAST_BREAKOUT_STATE[key].get('breach_type') != 'S3':
        LAST_BREAKOUT_STATE[key] = {
            'breach_count': 1,
            'first_breach_time': current_time,
            'last_breach_time': current_time,
            'breach_type': 'S3',
            'min_price': current_price,
            'volume_ratios': [ratio]
        }
        if DEBUG_MODE:
            print(f"📊 {info['symbol']}: First S3 breach detected at ₹{current_price:.2f} "
                  f"(1/{BREACH_CONFIRMATION_CYCLES} confirmations){fii_trend_label_bd}")
        return None
    
    state = LAST_BREAKOUT_STATE[key]
    time_since_first = (current_time - state['first_breach_time']).seconds
    if time_since_first > BREACH_TIME_WINDOW:
        LAST_BREAKOUT_STATE[key] = {
            'breach_count': 1,
            'first_breach_time': current_time,
            'last_breach_time': current_time,
            'breach_type': 'S3',
            'min_price': current_price,
            'volume_ratios': [ratio]
        }
        if DEBUG_MODE:
            print(f"⏳ {info['symbol']}: Breach window expired, restarting confirmation")
        return None
    
    state['breach_count'] += 1
    state['last_breach_time'] = current_time
    state['min_price'] = min(state['min_price'], current_price)
    state['volume_ratios'].append(ratio)
    
    if state['breach_count'] >= BREACH_CONFIRMATION_CYCLES:
        # VALIDATION 5: Volume Persistence
        avg_volume_ratio = sum(state['volume_ratios']) / len(state['volume_ratios'])
        if avg_volume_ratio < thr * 0.9:
            if DEBUG_MODE:
                print(f"⚠️ {info['symbol']}: Volume not persistent " 
                      f"(Avg: {avg_volume_ratio:.2f}x vs Required: {thr*0.9:.2f}x)")
            del LAST_BREAKOUT_STATE[key]
            return None
        
        # VALIDATION 6: Price Momentum
        price_drop = ((s3_level - current_price) / s3_level) * 100
        if price_drop < 0.3:
            if DEBUG_MODE:
                print(f"⚠️ {info['symbol']}: Insufficient momentum below S3 (Drop: {price_drop:.2f}%)")
            return None
        
        # ✅ ALL VALIDATIONS PASSED
        print(f"\n✅ {info['symbol']}: S3 BREAKDOWN CONFIRMED!")
        print(f" Confirmations: {state['breach_count']} | Time: {time_since_first}s")
        print(f" Min price: ₹{state['min_price']:.2f} | Avg volume: {avg_volume_ratio:.2f}x")
        del LAST_BREAKOUT_STATE[key]
        
        return {
            'symbol': info['symbol'],
            'instrument_key': key,
            's3': s3_level,
            'current_price': current_price,
            'low': live['low'],
            'volume_ratio': ratio,
            'current_volume': cur_vol,
            'avg_volume': avg20,
            'timestamp': current_time,
            'yesterday_close': info['yesterday_close'],
            'volume_threshold_used': thr,
            'breakout_type': 'PE',
            'strategy': 'S3',
            'confirmation_cycles': state['breach_count'],
            'time_to_confirm': time_since_first
        }
    
    if DEBUG_MODE:
        print(f"📊 {info['symbol']}: S3 breach #{state['breach_count']}/{BREACH_CONFIRMATION_CYCLES}")
    return None

# ========== BOX THEORY FUNCTIONS WITH KLINGER ==========
def check_box_top_breakout(key, live):
    """Box Theory: Breakout above previous day high (box top) → Buy CE with Klinger confirmation"""
    info = R3_LEVELS.get(key)
    if not info or not ENABLE_BOX_TRADING:
        return None

    # BOX_TOP already fired → skip entirely
    if info['symbol'] in BOX_TOP_ALERTED_STOCKS:
        return None
    # BOX_BOTTOM (SHORT) fired earlier → allow BOX_TOP LONG re-entry only in 2nd half
    _in_second_half_box_top = (ENABLE_SECOND_HALF_SHORT_REWATCH
                                and now_ist().strftime("%H:%M") >= SECOND_HALF_START)
    if info['symbol'] in BOX_BOTTOM_ALERTED_STOCKS and not _in_second_half_box_top:
        return None   # had BOX_BOTTOM SHORT but too early for reverse LONG

    box_top = info['box_high']
    if live['high'] < box_top:
        if key in LAST_BOX_STATE and LAST_BOX_STATE[key].get('breach_type') == 'BOX_TOP':
            del LAST_BOX_STATE[key]
        return None

    current_price = live['ltp']
    sustainability_threshold = box_top * (1 + PRICE_SUSTAINABILITY_PERCENT / 100)
    if current_price < sustainability_threshold:
        return None

    cur_vol = live.get('volume') or 0
    avg20 = info['avg_volume_20d']
    if avg20 <= 0:
        return None
    ratio = cur_vol / avg20
    thr = dynamic_volume_threshold() * BOX_VOLUME_THRESHOLD_MULTIPLIER
    if ratio < thr:
        return None

    # Klinger Confirmation Check — MANDATORY (no Klinger data = no trade)
    klinger_confirmed = False
    klinger_status = "N/A"
    
    if ENABLE_KLINGER_FILTER and ENABLE_KLINGER_FOR_BOX:
        if not info.get('klinger'):
            # No Klinger data — block trade (prevents buying CE when volume direction is unknown)
            if DEBUG_MODE:
                print(f"⚠️ {info['symbol']}: No Klinger data — blocking CE entry (safety rule)")
            return None

        klinger_data = info['klinger']
        ko = klinger_data['klinger']
        signal = klinger_data['signal']
        ko_prev = klinger_data.get('klinger_prev')
        signal_prev = klinger_data.get('signal_prev')
        
        if ko_prev is not None and signal_prev is not None:
            klinger_cross_up = (ko_prev <= signal_prev and ko > signal)
            klinger_below_zero = ko < 0
            klinger_histogram_positive = ko > signal
            
            klinger_confirmed = (klinger_cross_up or klinger_histogram_positive) and klinger_below_zero
            
            if not klinger_confirmed:
                klinger_status = f"REJECTED (KO: {ko:.1f}, Sig: {signal:.1f})"
                if DEBUG_MODE:
                    print(f"⚠️ {info['symbol']}: Box top breach but Klinger not confirming")
                    print(f"   KO: {ko:.2f} | Signal: {signal:.2f} | Cross: {klinger_cross_up} | Below 0: {klinger_below_zero}")
                
                if KLINGER_PAPER_MODE:
                    print(f"📝 PAPER MODE: Would have filtered {info['symbol']} box breakout")
                    klinger_confirmed = True
                else:
                    return None
            else:
                klinger_status = f"CONFIRMED (KO: {ko:.1f}↑)"
                if DEBUG_MODE:
                    print(f"✅ {info['symbol']}: Klinger CONFIRMS box breakout!")
        else:
            # Incomplete Klinger data — block trade
            if DEBUG_MODE:
                print(f"⚠️ {info['symbol']}: Incomplete Klinger data — blocking CE entry")
            return None

    current_time = now_ist()
    if key not in LAST_BOX_STATE or LAST_BOX_STATE[key].get('breach_type') != 'BOX_TOP':
        LAST_BOX_STATE[key] = {
            'breach_count': 1,
            'first_breach_time': current_time,
            'breach_type': 'BOX_TOP',
            'max_price': current_price,
            'volume_ratios': [ratio],
            'klinger_confirmed': klinger_confirmed
        }
        return None

    state = LAST_BOX_STATE[key]
    if (current_time - state['first_breach_time']).seconds > BREACH_TIME_WINDOW:
        state.update({
            'breach_count': 1,
            'first_breach_time': current_time,
            'max_price': current_price,
            'volume_ratios': [ratio],
            'klinger_confirmed': klinger_confirmed
        })
        return None

    state['breach_count'] += 1
    state['max_price'] = max(state['max_price'], current_price)
    state['volume_ratios'].append(ratio)

    if state['breach_count'] >= BOX_CONFIRMATION_CYCLES:
        avg_ratio = sum(state['volume_ratios']) / len(state['volume_ratios'])
        if avg_ratio < thr * 0.9:
            del LAST_BOX_STATE[key]
            return None

        price_gain = ((current_price - box_top) / box_top) * 100
        if price_gain < 0.3:
            return None

        # MAX ENTRY DISTANCE FILTER — skip if move already exhausted at confirmation time
        # e.g. BANDHANBNK was 2.13% above box top when confirmed → bought at peak → loss
        if price_gain > MAX_ENTRY_DISTANCE_PERCENT:
            print(f"\n⛔ {info['symbol']}: BOX TOP skipped — already {price_gain:.2f}% above level (max: {MAX_ENTRY_DISTANCE_PERCENT}%) — move likely exhausted!")
            del LAST_BOX_STATE[key]
            return None

        print(f"\n🚀 {info['symbol']}: BOX TOP BREAKOUT CONFIRMED!")
        print(f"   Box High: ₹{box_top:.2f} | Current: ₹{current_price:.2f}")
        print(f"   Gain: {price_gain:.2f}% | Volume: {avg_ratio:.2f}x")
        print(f"   🔥 Klinger: {klinger_status}")
        
        del LAST_BOX_STATE[key]

        return {
            'symbol': info['symbol'],
            'instrument_key': key,
            'level': box_top,
            'current_price': current_price,
            'high': live['high'],
            'volume_ratio': ratio,
            'timestamp': current_time,
            'yesterday_close': info['yesterday_close'],
            'breakout_type': 'CE',
            'strategy': 'BOX_TOP',
            'confirmation_cycles': state['breach_count'],
            'klinger_confirmed': klinger_confirmed,
            'klinger_status': klinger_status
        }
    return None

def check_box_bottom_breakdown(key, live):
    """Box Theory: Breakdown below previous day low (box bottom) → Buy PE with Klinger confirmation"""
    info = R3_LEVELS.get(key)
    if not info or not ENABLE_BOX_TRADING:
        return None

    # BOX_BOTTOM already fired → skip
    if info['symbol'] in BOX_BOTTOM_ALERTED_STOCKS:
        return None
    # BOX_TOP fired earlier → only allow if we're in the second half
    _in_second_half_box = (ENABLE_SECOND_HALF_SHORT_REWATCH
                           and now_ist().strftime("%H:%M") >= SECOND_HALF_START)
    if info['symbol'] in BOX_TOP_ALERTED_STOCKS and not _in_second_half_box:
        return None

    box_bottom = info['box_low']
    if live['low'] > box_bottom:
        if key in LAST_BOX_STATE and LAST_BOX_STATE[key].get('breach_type') == 'BOX_BOTTOM':
            del LAST_BOX_STATE[key]
        return None

    current_price = live['ltp']
    sustainability_threshold = box_bottom * (1 - PRICE_SUSTAINABILITY_PERCENT / 100)
    if current_price > sustainability_threshold:
        return None

    cur_vol = live.get('volume') or 0
    avg20 = info['avg_volume_20d']
    if avg20 <= 0:
        return None
    ratio = cur_vol / avg20
    thr = dynamic_volume_threshold() * BOX_VOLUME_THRESHOLD_MULTIPLIER
    if ratio < thr:
        return None

    # Klinger Bearish Confirmation — MANDATORY (no Klinger data = no trade)
    klinger_confirmed = False
    klinger_status = "N/A"
    
    if ENABLE_KLINGER_FILTER and ENABLE_KLINGER_FOR_BOX:
        if not info.get('klinger'):
            # No Klinger data — block trade (safety rule)
            if DEBUG_MODE:
                print(f"⚠️ {info['symbol']}: No Klinger data — blocking PE entry (safety rule)")
            return None

        klinger_data = info['klinger']
        ko = klinger_data['klinger']
        signal = klinger_data['signal']
        ko_prev = klinger_data.get('klinger_prev')
        signal_prev = klinger_data.get('signal_prev')
        
        if ko_prev is not None and signal_prev is not None:
            klinger_cross_down = (ko_prev >= signal_prev and ko < signal)
            klinger_above_zero = ko > 0
            klinger_histogram_negative = ko < signal
            
            klinger_confirmed = (klinger_cross_down or klinger_histogram_negative) and klinger_above_zero
            
            if not klinger_confirmed:
                klinger_status = f"REJECTED (KO: {ko:.1f}, Sig: {signal:.1f})"
                if DEBUG_MODE:
                    print(f"⚠️ {info['symbol']}: Box bottom breach but Klinger not confirming")
                
                if KLINGER_PAPER_MODE:
                    print(f"📝 PAPER MODE: Would have filtered {info['symbol']} box breakdown")
                    klinger_confirmed = True
                else:
                    return None
            else:
                klinger_status = f"CONFIRMED (KO: {ko:.1f}↓)"
                if DEBUG_MODE:
                    print(f"✅ {info['symbol']}: Klinger CONFIRMS breakdown!")
        else:
            # Incomplete Klinger data — block trade
            if DEBUG_MODE:
                print(f"⚠️ {info['symbol']}: Incomplete Klinger data — blocking PE entry")
            return None

    current_time = now_ist()
    if key not in LAST_BOX_STATE or LAST_BOX_STATE[key].get('breach_type') != 'BOX_BOTTOM':
        LAST_BOX_STATE[key] = {
            'breach_count': 1,
            'first_breach_time': current_time,
            'breach_type': 'BOX_BOTTOM',
            'min_price': current_price,
            'volume_ratios': [ratio],
            'klinger_confirmed': klinger_confirmed
        }
        return None

    state = LAST_BOX_STATE[key]
    if (current_time - state['first_breach_time']).seconds > BREACH_TIME_WINDOW:
        state.update({
            'breach_count': 1,
            'first_breach_time': current_time,
            'min_price': current_price,
            'volume_ratios': [ratio],
            'klinger_confirmed': klinger_confirmed
        })
        return None

    state['breach_count'] += 1
    state['min_price'] = min(state['min_price'], current_price)
    state['volume_ratios'].append(ratio)

    if state['breach_count'] >= BOX_CONFIRMATION_CYCLES:
        avg_ratio = sum(state['volume_ratios']) / len(state['volume_ratios'])
        if avg_ratio < thr * 0.9:
            del LAST_BOX_STATE[key]
            return None

        price_drop = ((box_bottom - current_price) / box_bottom) * 100
        if price_drop < 0.3:
            return None

        # MAX ENTRY DISTANCE FILTER — skip if move already exhausted at confirmation time
        if price_drop > MAX_ENTRY_DISTANCE_PERCENT:
            print(f"\n⛔ {info['symbol']}: BOX BOTTOM skipped — already {price_drop:.2f}% below level (max: {MAX_ENTRY_DISTANCE_PERCENT}%) — move likely exhausted!")
            del LAST_BOX_STATE[key]
            return None

        print(f"\n📉 {info['symbol']}: BOX BOTTOM BREAKDOWN CONFIRMED!")
        print(f"   Box Low: ₹{box_bottom:.2f} | Current: ₹{current_price:.2f}")
        print(f"   Drop: {price_drop:.2f}% | Volume: {avg_ratio:.2f}x")
        print(f"   🔥 Klinger: {klinger_status}")
        
        del LAST_BOX_STATE[key]

        return {
            'symbol': info['symbol'],
            'instrument_key': key,
            'level': box_bottom,
            'current_price': current_price,
            'low': live['low'],
            'volume_ratio': ratio,
            'timestamp': current_time,
            'yesterday_close': info['yesterday_close'],
            'breakout_type': 'PE',
            'strategy': 'BOX_BOTTOM',
            'confirmation_cycles': state['breach_count'],
            'klinger_confirmed': klinger_confirmed,
            'klinger_status': klinger_status
        }
    return None

# ========== RANGE TRADING FUNCTIONS WITH KLINGER ==========
def check_box_support_bounce(key, live):
    """Range Trading: Bounce near box bottom (within threshold) → Buy CE with Klinger confirmation"""
    info = R3_LEVELS.get(key)
    if not info or not ENABLE_RANGE_TRADING:
        return None

    # BOUNCE_BOTTOM already fired → skip entirely
    if info['symbol'] in RANGE_BOUNCE_ALERTED_STOCKS:
        return None
    # REJECT_TOP (SHORT) fired earlier → allow BOUNCE_BOTTOM LONG re-entry only in 2nd half
    _in_second_half_bounce = (ENABLE_SECOND_HALF_SHORT_REWATCH
                               and now_ist().strftime("%H:%M") >= SECOND_HALF_START)
    if info['symbol'] in RANGE_REJECT_ALERTED_STOCKS and not _in_second_half_bounce:
        return None   # had REJECT_TOP SHORT but too early for reverse LONG

    box_bottom = info['box_low']
    current_price = live['ltp']
    
    # Check if price is within bounce threshold of box bottom
    distance_from_bottom = ((current_price - box_bottom) / box_bottom) * 100
    if distance_from_bottom > RANGE_BOUNCE_THRESHOLD or distance_from_bottom < 0:
        return None

    cur_vol = live.get('volume') or 0
    avg20 = info['avg_volume_20d']
    if avg20 <= 0:
        return None
    ratio = cur_vol / avg20
    thr = dynamic_volume_threshold() * BOUNCE_VOLUME_MULTIPLIER
    if ratio < thr:
        return None

    # Klinger Bullish Divergence Check (for bounces at support)
    klinger_confirmed = False
    klinger_status = "N/A"
    
    if ENABLE_KLINGER_FILTER and ENABLE_KLINGER_FOR_RANGE and info.get('klinger'):
        klinger_data = info['klinger']
        ko = klinger_data['klinger']
        signal = klinger_data['signal']
        ko_prev = klinger_data.get('klinger_prev')
        signal_prev = klinger_data.get('signal_prev')
        
        if ko_prev is not None and signal_prev is not None:
            klinger_cross_up = (ko_prev <= signal_prev and ko > signal)
            klinger_below_zero = ko < 0
            klinger_rising = ko > ko_prev
            klinger_histogram_positive = ko > signal
            
            klinger_confirmed = ((klinger_cross_up or (klinger_rising and klinger_histogram_positive)) 
                               and klinger_below_zero)
            
            if not klinger_confirmed:
                klinger_status = f"REJECTED (KO: {ko:.1f}, Rising: {klinger_rising})"
                if DEBUG_MODE:
                    print(f"⚠️ {info['symbol']}: Support bounce but Klinger not confirming")
                
                if KLINGER_PAPER_MODE:
                    print(f"📝 PAPER MODE: Would have filtered {info['symbol']} support bounce")
                    klinger_confirmed = True
                else:
                    return None
            else:
                klinger_status = f"CONFIRMED (KO: {ko:.1f}↑ Bounce)"
                if DEBUG_MODE:
                    print(f"✅ {info['symbol']}: Klinger CONFIRMS support bounce!")

    current_time = now_ist()
    bounce_key = f"{key}_BOUNCE_BOTTOM"
    
    if bounce_key not in LAST_BOUNCE_STATE:
        LAST_BOUNCE_STATE[bounce_key] = {
            'breach_count': 1,
            'first_breach_time': current_time,
            'volume_ratios': [ratio],
            'klinger_confirmed': klinger_confirmed
        }
        if DEBUG_MODE:
            print(f"📊 {info['symbol']}: First support bounce detected at ₹{current_price:.2f}")
        return None

    state = LAST_BOUNCE_STATE[bounce_key]
    if (current_time - state['first_breach_time']).seconds > BREACH_TIME_WINDOW:
        state.update({
            'breach_count': 1,
            'first_breach_time': current_time,
            'volume_ratios': [ratio],
            'klinger_confirmed': klinger_confirmed
        })
        return None

    state['breach_count'] += 1
    state['volume_ratios'].append(ratio)

    if state['breach_count'] >= BOX_CONFIRMATION_CYCLES:
        avg_ratio = sum(state['volume_ratios']) / len(state['volume_ratios'])
        if avg_ratio < thr * 0.9:
            del LAST_BOUNCE_STATE[bounce_key]
            return None

        print(f"\n🎯 {info['symbol']}: BOX SUPPORT BOUNCE CONFIRMED!")
        print(f"   Box Bottom: ₹{box_bottom:.2f} | Current: ₹{current_price:.2f}")
        print(f"   Distance: {distance_from_bottom:.2f}% | Volume: {avg_ratio:.2f}x")
        print(f"   🔥 Klinger: {klinger_status}")
        
        del LAST_BOUNCE_STATE[bounce_key]

        return {
            'symbol': info['symbol'],
            'instrument_key': key,
            'level': box_bottom,
            'current_price': current_price,
            'low': live['low'],
            'volume_ratio': ratio,
            'timestamp': current_time,
            'yesterday_close': info['yesterday_close'],
            'breakout_type': 'CE',
            'strategy': 'BOUNCE_BOTTOM',
            'confirmation_cycles': state['breach_count'],
            'klinger_confirmed': klinger_confirmed,
            'klinger_status': klinger_status
        }
    return None

def check_box_resistance_rejection(key, live):
    """Range Trading: Rejection near box top (within threshold) → Buy PE with Klinger confirmation"""
    info = R3_LEVELS.get(key)
    if not info or not ENABLE_RANGE_TRADING:
        return None

    # REJECT_TOP already fired → skip
    if info['symbol'] in RANGE_REJECT_ALERTED_STOCKS:
        return None
    # BOUNCE_BOTTOM fired earlier → only allow if we're in the second half
    _in_second_half_range = (ENABLE_SECOND_HALF_SHORT_REWATCH
                             and now_ist().strftime("%H:%M") >= SECOND_HALF_START)
    if info['symbol'] in RANGE_BOUNCE_ALERTED_STOCKS and not _in_second_half_range:
        return None

    box_top = info['box_high']
    current_price = live['ltp']
    
    # Check if price is within rejection threshold of box top
    distance_from_top = ((box_top - current_price) / box_top) * 100
    if distance_from_top > RANGE_BOUNCE_THRESHOLD or distance_from_top < 0:
        return None

    cur_vol = live.get('volume') or 0
    avg20 = info['avg_volume_20d']
    if avg20 <= 0:
        return None
    ratio = cur_vol / avg20
    thr = dynamic_volume_threshold() * BOUNCE_VOLUME_MULTIPLIER
    if ratio < thr:
        return None

    # Klinger Bearish Divergence Check (for rejections at resistance)
    klinger_confirmed = False
    klinger_status = "N/A"
    
    if ENABLE_KLINGER_FILTER and ENABLE_KLINGER_FOR_RANGE and info.get('klinger'):
        klinger_data = info['klinger']
        ko = klinger_data['klinger']
        signal = klinger_data['signal']
        ko_prev = klinger_data.get('klinger_prev')
        signal_prev = klinger_data.get('signal_prev')
        
        if ko_prev is not None and signal_prev is not None:
            klinger_cross_down = (ko_prev >= signal_prev and ko < signal)
            klinger_above_zero = ko > 0
            klinger_falling = ko < ko_prev
            klinger_histogram_negative = ko < signal
            
            klinger_confirmed = ((klinger_cross_down or (klinger_falling and klinger_histogram_negative)) 
                               and klinger_above_zero)
            
            if not klinger_confirmed:
                klinger_status = f"REJECTED (KO: {ko:.1f}, Falling: {klinger_falling})"
                if DEBUG_MODE:
                    print(f"⚠️ {info['symbol']}: Resistance rejection but Klinger not confirming")
                
                if KLINGER_PAPER_MODE:
                    print(f"📝 PAPER MODE: Would have filtered {info['symbol']} resistance rejection")
                    klinger_confirmed = True
                else:
                    return None
            else:
                klinger_status = f"CONFIRMED (KO: {ko:.1f}↓ Rejection)"
                if DEBUG_MODE:
                    print(f"✅ {info['symbol']}: Klinger CONFIRMS resistance rejection!")

    current_time = now_ist()
    reject_key = f"{key}_REJECT_TOP"
    
    if reject_key not in LAST_BOUNCE_STATE:
        LAST_BOUNCE_STATE[reject_key] = {
            'breach_count': 1,
            'first_breach_time': current_time,
            'volume_ratios': [ratio],
            'klinger_confirmed': klinger_confirmed
        }
        if DEBUG_MODE:
            print(f"📊 {info['symbol']}: First resistance rejection detected at ₹{current_price:.2f}")
        return None

    state = LAST_BOUNCE_STATE[reject_key]
    if (current_time - state['first_breach_time']).seconds > BREACH_TIME_WINDOW:
        state.update({
            'breach_count': 1,
            'first_breach_time': current_time,
            'volume_ratios': [ratio],
            'klinger_confirmed': klinger_confirmed
        })
        return None

    state['breach_count'] += 1
    state['volume_ratios'].append(ratio)

    if state['breach_count'] >= BOX_CONFIRMATION_CYCLES:
        avg_ratio = sum(state['volume_ratios']) / len(state['volume_ratios'])
        if avg_ratio < thr * 0.9:
            del LAST_BOUNCE_STATE[reject_key]
            return None

        print(f"\n🎯 {info['symbol']}: BOX RESISTANCE REJECTION CONFIRMED!")
        print(f"   Box Top: ₹{box_top:.2f} | Current: ₹{current_price:.2f}")
        print(f"   Distance: {distance_from_top:.2f}% | Volume: {avg_ratio:.2f}x")
        print(f"   🔥 Klinger: {klinger_status}")
        
        del LAST_BOUNCE_STATE[reject_key]

        return {
            'symbol': info['symbol'],
            'instrument_key': key,
            'level': box_top,
            'current_price': current_price,
            'high': live['high'],
            'volume_ratio': ratio,
            'timestamp': current_time,
            'yesterday_close': info['yesterday_close'],
            'breakout_type': 'PE',
            'strategy': 'REJECT_TOP',
            'confirmation_cycles': state['breach_count'],
            'klinger_confirmed': klinger_confirmed,
            'klinger_status': klinger_status
        }
    return None

# ========== GAP TRADING FUNCTIONS ==========
def detect_gaps(live_data):
    """Detect gap-up and gap-down stocks with volume confirmation"""
    gap_stocks = {'gap_up': [], 'gap_down': []}
    
    for isin_key, live in live_data.items():
        if isin_key not in R3_LEVELS:
            continue
            
        info = R3_LEVELS[isin_key]
        symbol = info['symbol']
        yesterday_close = info['yesterday_close']
        current_price = live.get('ltp')
        open_price = live.get('open')
        
        if not current_price or not yesterday_close or not open_price:
            continue
            
        # Calculate gap percentage based on open vs yesterday close
        gap_percent = ((open_price - yesterday_close) / yesterday_close) * 100
        
        # Check if significant gap
        if abs(gap_percent) >= GAP_THRESHOLD_PERCENT and abs(gap_percent) <= MAX_GAP_PERCENT:
            # Volume confirmation
            cur_vol = live.get('volume', 0)
            avg_vol = info['avg_volume_20d']
            volume_ratio = cur_vol / avg_vol if avg_vol > 0 else 0
            
            # Only consider gaps with minimum volume
            if volume_ratio < GAP_MIN_VOLUME_RATIO:
                continue
                
            gap_info = {
                'symbol': symbol,
                'instrument_key': isin_key,
                'gap_percent': gap_percent,
                'yesterday_close': yesterday_close,
                'current_price': current_price,
                'volume_ratio': volume_ratio,
                'current_volume': cur_vol,
                'avg_volume': avg_vol,
                'timestamp': live['timestamp'],
                'open_price': open_price,
                'high': live.get('high', current_price),
                'low': live.get('low', current_price)
            }
            
            if gap_percent > 0:
                gap_stocks['gap_up'].append(gap_info)
            else:
                gap_stocks['gap_down'].append(gap_info)
                
    return gap_stocks

def calculate_gap_fill_percent(gap_info):
    """Calculate what percentage of the gap has been filled"""
    gap_percent = gap_info['gap_percent']
    current_price = gap_info['current_price']
    yesterday_close = gap_info['yesterday_close']
    open_price = gap_info['open_price']
    
    if gap_percent > 0:  # Gap up
        gap_size = open_price - yesterday_close
        filled = open_price - current_price
        if gap_size > 0:
            return (filled / gap_size) * 100
    else:  # Gap down
        gap_size = yesterday_close - open_price
        filled = current_price - open_price
        if gap_size > 0:
            return (filled / gap_size) * 100
    return 0

def analyze_gap_strength(gap_info):
    """Analyze gap strength and probability of continuation"""
    gap_percent = gap_info['gap_percent']
    volume_ratio = gap_info['volume_ratio']
    current_price = gap_info['current_price']
    open_price = gap_info['open_price']
    
    strength_score = 0
    
    # Volume strength (40% weight)
    if volume_ratio >= 2.0:
        strength_score += 40
    elif volume_ratio >= 1.5:
        strength_score += 30
    elif volume_ratio >= 1.2:
        strength_score += 20
    elif volume_ratio >= 1.0:
        strength_score += 10
        
    # Gap size strength (30% weight)
    gap_abs = abs(gap_percent)
    if gap_abs >= 3.0:
        strength_score += 30
    elif gap_abs >= 2.0:
        strength_score += 25
    elif gap_abs >= 1.5:
        strength_score += 20
    elif gap_abs >= 1.0:
        strength_score += 15
        
    # Price action strength (30% weight)
    if gap_percent > 0:  # Gap up
        if current_price > open_price:
            strength_score += 30
        elif current_price >= open_price * 0.995:
            strength_score += 20
        else:
            strength_score += 10
    else:  # Gap down
        if current_price < open_price:
            strength_score += 30
        elif current_price <= open_price * 1.005:
            strength_score += 20
        else:
            strength_score += 10
            
    return strength_score

def get_gap_trading_signal(gap_info):
    """Generate specific trading signals for gaps"""
    symbol = gap_info['symbol']
    gap_percent = gap_info['gap_percent']
    current_price = gap_info['current_price']
    yesterday_close = gap_info['yesterday_close']
    open_price = gap_info['open_price']
    
    gap_fill_percent = calculate_gap_fill_percent(gap_info)
    strength_score = analyze_gap_strength(gap_info)
    
    # Generate signals based on gap behavior
    if gap_percent > 0:  # Gap Up Scenarios
        if current_price > open_price and strength_score >= 70:
            return {
                'signal': "gap_and_go",
                'direction': 'LONG',
                'entry_price': current_price,
                'stop_loss': max(open_price * 0.99, yesterday_close),
                'target': current_price * (1 + abs(gap_percent)/100 * 0.5),
                'confidence': 'HIGH',
                'strength_score': strength_score
            }
        elif gap_fill_percent >= 70 and strength_score >= 50:
            return {
                'signal': "gap_fill",
                'direction': 'SHORT',
                'entry_price': current_price,
                'stop_loss': open_price * 1.01,
                'target': yesterday_close * 0.995,
                'confidence': 'MEDIUM',
                'strength_score': strength_score
            }
    else:  # Gap Down Scenarios
        if current_price < open_price and strength_score >= 70:
            return {
                'signal': "gap_and_go",
                'direction': 'SHORT',
                'entry_price': current_price,
                'stop_loss': min(open_price * 1.01, yesterday_close),
                'target': current_price * (1 - abs(gap_percent)/100 * 0.5),
                'confidence': 'HIGH',
                'strength_score': strength_score
            }
        elif gap_fill_percent >= 70 and strength_score >= 50:
            return {
                'signal': "gap_fill",
                'direction': 'LONG',
                'entry_price': current_price,
                'stop_loss': open_price * 0.99,
                'target': yesterday_close * 1.005,
                'confidence': 'MEDIUM',
                'strength_score': strength_score
            }
    
    return None

def should_place_gap_trade(gap_info, signal):
    """Enhanced validation for gap trades"""
    global GAP_ORDER_COUNT
    symbol = gap_info['symbol']
    
    # Direction-aware gap skip: allow opposite-direction re-entry in 2nd half
    gap_direction = signal.get('direction', '').upper()  # 'CE' or 'PE'
    already_up   = symbol in GAP_UP_ALERTED_STOCKS
    already_down = symbol in GAP_DOWN_ALERTED_STOCKS
    _in_second_half_gap = (ENABLE_SECOND_HALF_SHORT_REWATCH
                           and now_ist().strftime("%H:%M") >= SECOND_HALF_START)

    if gap_direction == 'CE':
        if already_up:
            return False   # already took gap-UP LONG today
        if already_down and not _in_second_half_gap:
            return False   # had gap-DOWN SHORT but too early for reverse LONG
    elif gap_direction == 'PE':
        if already_down:
            return False   # already took gap-DOWN SHORT today
        if already_up and not _in_second_half_gap:
            return False   # had gap-UP LONG but too early for reverse SHORT
    else:
        if symbol in GAP_ALERTED_STOCKS:
            return False   # fallback: no direction info

    if GAP_ORDER_COUNT >= MAX_ORDERS_PER_DAY:
        return False
        
    if symbol in LAST_ORDER_TIME:
        time_since_last = (now_ist() - LAST_ORDER_TIME[symbol]).seconds
        if time_since_last < MIN_ORDER_GAP_SECONDS:
            return False
            
    if signal['confidence'] == 'HIGH':
        return gap_info['volume_ratio'] >= 1.3
    elif signal['confidence'] == 'MEDIUM':
        return gap_info['volume_ratio'] >= 1.8
        
    return False

# ========== EXIT MANAGEMENT FUNCTIONS ==========
def check_exit_conditions(position, current_price, trader):
    """Check if any exit condition is met for a position"""
    global DAILY_PNL, POSITION_PEAK_PRICES, POSITION_TRAILING_SL
    
    if not ENABLE_EXIT_MANAGEMENT:
        return False, None
    
    position_id = position.get('order_id') or position.get('position_id')
    symbol = position['symbol']
    entry_price = position['entry_price']
    strategy = position.get('strategy', 'UNKNOWN')
    underlying_key = position.get('underlying_key')
    
    # Calculate current P&L
    pnl_per_unit = current_price - entry_price
    total_pnl = pnl_per_unit * position['quantity']
    pnl_percent = (pnl_per_unit / entry_price) * 100
    
    # Update position with current P&L
    position['current_price'] = current_price
    position['current_pnl'] = total_pnl
    position['pnl_percent'] = pnl_percent
    
    # 1. TIME-BASED EXIT (Most Important - Before Market Close)
    if ENABLE_TIME_BASED_EXIT:
        now = now_ist()
        current_time_str = now.strftime("%H:%M")
        
        # Regular end-of-day exit
        if current_time_str >= EXIT_START_TIME:
            return True, "END_OF_DAY"
        
        # 2. EXPIRY DAY EXIT (Exit earlier on expiry day)
        if ENABLE_EXPIRY_DAY_EXIT:
            expiry_date = position.get('expiry_date')
            if expiry_date:
                if isinstance(expiry_date, str):
                    expiry_date = datetime.strptime(expiry_date, "%Y-%m-%d")
                
                if expiry_date.date() == now.date():
                    if current_time_str >= EXPIRY_EXIT_TIME:
                        return True, "EXPIRY_DAY_EXIT"
    
    # 3. MAXIMUM DAILY LOSS CHECK
    if DAILY_PNL + total_pnl <= -MAX_DAILY_LOSS:
        return True, "MAX_DAILY_LOSS"
    
    # 4. MAXIMUM DAILY PROFIT CHECK
    if DAILY_PNL + total_pnl >= MAX_DAILY_PROFIT:
        return True, "MAX_DAILY_PROFIT"
    
    # 5. TARGET PROFIT REACHED (2x risk or configured multiplier)
    risk_amount = entry_price * (STOPLOSS_PERCENTAGE / 100)
    target_profit = risk_amount * TARGET_PROFIT_MULTIPLIER
    if pnl_per_unit >= target_profit:
        return True, "TARGET_PROFIT"
    
    # 6. TRAILING STOP-LOSS (Activate after specified profit %)
    #    Stage 1 – initial SL order is placed immediately after entry (see entry logic).
    #    Stage 2 – here we monitor price and MODIFY the live SL order on the broker
    #              every time price reaches a new peak, ratcheting the stop upward.
    if ENABLE_TRAILING_STOP and pnl_percent >= TRAILING_STOP_ACTIVATION:
        # --- update in-memory peak ---
        if position_id not in POSITION_PEAK_PRICES:
            POSITION_PEAK_PRICES[position_id] = current_price
        else:
            POSITION_PEAK_PRICES[position_id] = max(POSITION_PEAK_PRICES[position_id], current_price)

        peak_price            = POSITION_PEAK_PRICES[position_id]
        new_trailing_sl       = round(peak_price * (1 - TRAILING_STOP_PERCENTAGE / 100), 2)
        last_broker_sl        = POSITION_TRAILING_SL.get(position_id)
        sl_order_id           = position.get('sl_order_id')

        # --- push updated trigger to broker only when SL has moved up meaningfully ---
        MIN_SL_MOVE_PCT = 0.10   # only modify if SL shifted by ≥ 0.10 % (avoids API noise)
        should_modify = (
            sl_order_id is not None
            and (
                last_broker_sl is None                                        # first time activating
                or new_trailing_sl > last_broker_sl * (1 + MIN_SL_MOVE_PCT / 100)  # moved up
            )
        )
        if should_modify:
            modify_result = trader.modify_order(
                order_id      = sl_order_id,
                trigger_price = new_trailing_sl,
                price         = 0,                          # SL-M: execute at market when triggered
                quantity      = position.get('quantity'),
                order_type    = 'SL',                       # SL-M
            )
            if modify_result.get('status_code') == 200:
                POSITION_TRAILING_SL[position_id] = new_trailing_sl
                print(f"   🔒 Trailing SL updated → ₹{new_trailing_sl:.2f}  (peak ₹{peak_price:.2f})")
            else:
                # Broker modify failed – fall back to software-side check so we still exit
                print(f"   ⚠️ Broker SL modify failed; software-side guard still active.")

        # --- software-side safety net (catches the stop even if modify failed) ---
        effective_sl = POSITION_TRAILING_SL.get(position_id, new_trailing_sl)
        if current_price <= effective_sl:
            return True, f"TRAILING_STOP (Peak: ₹{peak_price:.2f}, SL: ₹{effective_sl:.2f})"
    
    # 7. STRATEGY-SPECIFIC EXITS
    if ENABLE_STRATEGY_EXITS and underlying_key:
        # BOX THEORY: Exit if price re-enters the box
        if strategy in ['BOX_TOP', 'BOX_BOTTOM']:
            underlying_price = trader.get_ltp(underlying_key)
            info = R3_LEVELS.get(underlying_key)
            
            if info and underlying_price:
                box_high = info['box_high']
                box_low = info['box_low']
                
                if strategy == 'BOX_TOP':
                    # Exit if underlying price drops back into box
                    reentry_threshold = box_high * (1 - BOX_REENTRY_EXIT_PERCENT / 100)
                    if underlying_price < reentry_threshold:
                        return True, f"BOX_REENTRY (Price: ₹{underlying_price:.2f} < ₹{reentry_threshold:.2f})"
                
                elif strategy == 'BOX_BOTTOM':
                    # Exit if underlying price rises back into box
                    reentry_threshold = box_low * (1 + BOX_REENTRY_EXIT_PERCENT / 100)
                    if underlying_price > reentry_threshold:
                        return True, f"BOX_REENTRY (Price: ₹{underlying_price:.2f} > ₹{reentry_threshold:.2f})"
        
        # RANGE TRADING: Exit if support/resistance breaks
        elif strategy in ['BOUNCE_BOTTOM', 'REJECT_TOP']:
            underlying_price = trader.get_ltp(underlying_key)
            info = R3_LEVELS.get(underlying_key)
            
            if info and underlying_price:
                if strategy == 'BOUNCE_BOTTOM':
                    # Exit if support breaks
                    if underlying_price < info['box_low'] * 0.995:
                        return True, f"SUPPORT_BROKEN (Price: ₹{underlying_price:.2f})"
                
                elif strategy == 'REJECT_TOP':
                    # Exit if resistance breaks
                    if underlying_price > info['box_high'] * 1.005:
                        return True, f"RESISTANCE_BROKEN (Price: ₹{underlying_price:.2f})"
        
        # GAP TRADING: Exit when gap fills significantly
        elif position.get('trade_type') == 'GAP_OPTION':
            gap_signal = position.get('gap_signal')
            if gap_signal == "gap_fill":
                # Check if gap has filled
                gap_info = GAP_LEVELS.get(symbol)
                if gap_info:
                    underlying_price = trader.get_ltp(underlying_key)
                    if underlying_price:
                        gap_info['current_price'] = underlying_price
                        fill_percent = calculate_gap_fill_percent(gap_info)
                        
                        if fill_percent >= GAP_FILL_EXIT_PERCENT:
                            return True, f"GAP_FILLED_{fill_percent:.0f}%"
    
    # 8. STOP-LOSS CHECK (Should be handled by broker SL order, but double-check)
    stop_loss_price = entry_price * (1 - STOPLOSS_PERCENTAGE / 100)
    if current_price <= stop_loss_price:
        return True, "STOP_LOSS_HIT"
    
    return False, None

def exit_position(trader, position_id, position, exit_price, reason):
    """Execute position exit and update tracking"""
    global ACTIVE_POSITIONS, DAILY_PNL, CLOSED_POSITIONS, POSITION_PEAK_PRICES, POSITION_TRAILING_SL
    
    symbol = position.get('option_symbol') or position['symbol']
    quantity = position['quantity']
    entry_price = position['entry_price']
    instrument_key = position['instrument_key']
    
    print(f"\n{'='*120}")
    print(f"🚨 EXITING POSITION: {symbol}")
    print(f"{'='*120}")
    print(f"   Strategy: {position.get('strategy', 'UNKNOWN')}")
    print(f"   Reason: {reason}")
    print(f"   Entry Price: ₹{entry_price:.2f}")
    print(f"   Exit Price: ₹{exit_price:.2f}")
    print(f"   Quantity: {quantity}")
    
    # Calculate P&L
    pnl_per_unit = exit_price - entry_price
    total_pnl = pnl_per_unit * quantity
    pnl_percent = (pnl_per_unit / entry_price) * 100
    
    print(f"   P&L per unit: ₹{pnl_per_unit:.2f}")
    print(f"   Total P&L: ₹{total_pnl:,.2f} ({pnl_percent:+.2f}%)")
    
    try:
        # Cancel any pending SL/Target orders first
        if 'sl_order_id' in position:
            print(f"   Cancelling SL order: {position['sl_order_id']}")
            try:
                trader.cancel_order(position['sl_order_id'])
            except Exception as e:
                if DEBUG_MODE:
                    print(f"   ⚡ SL cancel failed: {e}")
        
        if 'target_order_id' in position:
            print(f"   Cancelling Target order: {position['target_order_id']}")
            try:
                trader.cancel_order(position['target_order_id'])
            except Exception as e:
                if DEBUG_MODE:
                    print(f"   ⚡ Target cancel failed: {e}")
        
        # Place market exit order
        print(f"   Placing SELL order...")
        result = trader.place_order(
            instrument_key=instrument_key,
            quantity=quantity,
            transaction_type='SELL',
            product=ORDER_PRODUCT,
            order_type='MARKET',
            price=0
        )
        
        if result.get('status_code') == 200 and result.get('response', {}).get('status') == 'success':
            exit_order_id = result['response'].get('data', {}).get('order_id')
            
            print(f"   ✅ EXIT ORDER PLACED")
            print(f"   Exit Order ID: {exit_order_id}")
            
            # Update daily P&L
            DAILY_PNL += total_pnl
            print(f"   📊 Updated Daily P&L: ₹{DAILY_PNL:,.2f}")
            
            # Store closed position details
            closed_position = {
                **position,
                'exit_price': exit_price,
                'exit_time': now_ist(),
                'exit_reason': reason,
                'pnl': total_pnl,
                'pnl_percent': pnl_percent,
                'exit_order_id': exit_order_id
            }
            CLOSED_POSITIONS.append(closed_position)
            
            # Log the exit
            log_exit(closed_position)
            
            # Remove from active positions
            if position_id in ACTIVE_POSITIONS:
                del ACTIVE_POSITIONS[position_id]
            
            # Clear HA reversal alert state for this position
            clear_ha_alert(position_id)
            
            # Clean up peak price tracking
            if position_id in POSITION_PEAK_PRICES:
                del POSITION_PEAK_PRICES[position_id]
            if position_id in POSITION_TRAILING_SL:
                del POSITION_TRAILING_SL[position_id]
            
            print(f"{'='*120}\n")
            return True
            
        else:
            print(f"   ❌ EXIT FAILED")
            error_msg = result.get('response', {}).get('message', 'Unknown error')
            print(f"   Error: {error_msg}")
            print(f"{'='*120}\n")
            return False
            
    except Exception as e:
        print(f"   ❌ Exit error: {e}")
        if DEBUG_MODE:
            import traceback
            traceback.print_exc()
        print(f"{'='*120}\n")
        return False

def exit_all_positions(trader, reason="MANUAL_EXIT"):
    """Exit all active positions (emergency exit or end of day)"""
    global ACTIVE_POSITIONS
    
    if not ACTIVE_POSITIONS:
        print("ℹ️ No active positions to exit")
        return
    
    print(f"\n{'='*120}")
    print(f"🚨 EXITING ALL POSITIONS - Reason: {reason}")
    print(f"{'='*120}")
    print(f"Total positions to exit: {len(ACTIVE_POSITIONS)}")
    
    positions_to_exit = list(ACTIVE_POSITIONS.items())
    
    for position_id, position in positions_to_exit:
        instrument_key = position['instrument_key']
        current_price = trader.get_ltp(instrument_key)
        
        if current_price:
            exit_position(trader, position_id, position, current_price, reason)
            time.sleep(1)  # Brief delay between exits
        else:
            print(f"⚡ Could not get price for {position.get('symbol')}, skipping exit")
    
    print(f"{'='*120}\n")

def monitor_active_positions(trader):
    """Monitor and manage all active positions"""
    global ACTIVE_POSITIONS, DAILY_PNL, TRADING_STOPPED
    
    if not ACTIVE_POSITIONS:
        return
    
    positions_to_exit = []
    
    for position_id, position in ACTIVE_POSITIONS.items():
        instrument_key = position['instrument_key']
        
        # Get current option price
        current_price = trader.get_ltp(instrument_key)
        if not current_price:
            if DEBUG_MODE:
                print(f"⚡ Could not get price for {position.get('symbol')}")
            continue
        
        # Check exit conditions
        should_exit, reason = check_exit_conditions(position, current_price, trader)
        
        if should_exit:
            positions_to_exit.append((position_id, position, current_price, reason))
    
    # Execute exits
    for position_id, position, exit_price, reason in positions_to_exit:
        success = exit_position(trader, position_id, position, exit_price, reason)
        
        # Check if we should stop trading
        if reason in ["MAX_DAILY_LOSS", "MAX_DAILY_PROFIT"]:
            TRADING_STOPPED = True
            print(f"\n⚡ TRADING STOPPED: {reason} reached")
            print(f"Daily P&L: ₹{DAILY_PNL:,.2f}")
            exit_all_positions(trader, reason)
            break

# ═══════════════════════════════════════════════════════════════════════════════
# HEIKIN-ASHI REVERSAL ALERT — watches open positions for counter-trend signals
# ═══════════════════════════════════════════════════════════════════════════════

# Tracks which positions have already been alerted to avoid spam (one alert per
# position per HA flip event). Cleared when a position is exited.
_HA_ALERTED: set = set()   # position_id strings

# ── HA WATCHLIST FOR MISSED/REJECTED SIGNALS ──────────────────────────────────
# When a signal fires but the order is rejected (e.g. insufficient margin),
# the symbol is added here so we still watch for HA reversals and print alerts.
# Structure: { symbol: {'signal': 'LONG'|'SHORT', 'instrument_key': str,
#                        'added_at': datetime, 'reason': str} }
HA_WATCHLIST: dict = {}
HA_WATCHLIST_MAX_AGE_MINUTES = 60   # auto-expire entries older than 60 min
# ─────────────────────────────────────────────────────────────────────────────

def _compute_ha_candles(df: 'pd.DataFrame') -> 'pd.DataFrame':
    """
    Convert a standard OHLCV DataFrame into Heikin-Ashi candles.
    Returns a new DataFrame with columns: ha_open, ha_high, ha_low, ha_close.
    Needs at least 3 rows.
    """
    df = df.copy().reset_index(drop=True)
    n = len(df)
    ha_close = (df['open'] + df['high'] + df['low'] + df['close']) / 4
    ha_open  = pd.Series([0.0] * n)
    ha_open.iloc[0] = (df['open'].iloc[0] + df['close'].iloc[0]) / 2
    for i in range(1, n):
        ha_open.iloc[i] = (ha_open.iloc[i - 1] + ha_close.iloc[i - 1]) / 2
    ha_high  = pd.concat([df['high'], ha_open, ha_close], axis=1).max(axis=1)
    ha_low   = pd.concat([df['low'],  ha_open, ha_close], axis=1).min(axis=1)
    return pd.DataFrame({
        'ha_open':  ha_open,
        'ha_high':  ha_high,
        'ha_low':   ha_low,
        'ha_close': ha_close,
    })


def _ha_colour(ha_open: float, ha_close: float) -> str:
    """Return 'green' (bullish) or 'red' (bearish) for a single HA candle."""
    return 'green' if ha_close >= ha_open else 'red'


def _ha_analyse_symbol(access_token: str, symbol: str, ikey: str, signal: str):
    """
    Shared helper: fetch 5min candles, compute HA, return analysis dict or None.
    Returns:
      { 'ha': DataFrame, 'c_prev2', 'c_prev1', 'c_last',
        'is_doji', 'is_bearish_flip', 'is_bullish_flip',
        'needs_alert', 'last_body', 'last_range', 'underlying_ltp' }
    or None if data unavailable.
    """
    try:
        df5 = fetch_5min_cached(access_token, ikey, bars=50, symbol=symbol)
        if df5 is None or len(df5) < 5:
            return None
        df5 = df5.tail(30).reset_index(drop=True)
        ha  = _compute_ha_candles(df5)
    except Exception:
        return None

    if len(ha) < 3:
        return None

    c_prev2 = _ha_colour(ha['ha_open'].iloc[-3], ha['ha_close'].iloc[-3])
    c_prev1 = _ha_colour(ha['ha_open'].iloc[-2], ha['ha_close'].iloc[-2])
    c_last  = _ha_colour(ha['ha_open'].iloc[-1], ha['ha_close'].iloc[-1])

    last_range = ha['ha_high'].iloc[-1] - ha['ha_low'].iloc[-1]
    last_body  = abs(ha['ha_close'].iloc[-1] - ha['ha_open'].iloc[-1])
    is_doji    = (last_range > 0) and (last_body / last_range < 0.20)

    # A flip = previous candle is opposite colour AND last candle is the new colour.
    # Original code required c_prev1 AND c_last both same colour — that's "trend
    # continuation", not a "flip". A reversal signal needs a CHANGE of colour.
    is_bearish_flip = (c_prev1 == 'green' and c_last == 'red')
    is_bullish_flip = (c_prev1 == 'red'   and c_last == 'green')
    needs_alert     = (
        (signal == 'LONG'  and is_bearish_flip) or
        (signal == 'SHORT' and is_bullish_flip)
    )

    try:
        ltp_data       = get_live_prices_batch(access_token, [ikey])
        underlying_ltp = ltp_data.get(ikey, {}).get('ltp', 0) if ltp_data else 0
    except Exception:
        underlying_ltp = 0

    return {
        'ha': ha, 'c_prev2': c_prev2, 'c_prev1': c_prev1, 'c_last': c_last,
        'is_doji': is_doji, 'last_body': last_body, 'last_range': last_range,
        'is_bearish_flip': is_bearish_flip, 'is_bullish_flip': is_bullish_flip,
        'needs_alert': needs_alert, 'underlying_ltp': underlying_ltp,
    }


def _ha_klinger_check(access_token: str, ikey: str, symbol: str, signal: str):
    """
    Shared helper: check Klinger direction for HA reversal confirmation.
    Returns (klinger_confirms: bool, ko_desc: str).
    """
    try:
        kd = fetch_klinger_data_cached(access_token, ikey, symbol)
        if not kd:
            return False, "KO unavailable ⚠️"
        ko_value   = kd.get('klinger', 0)
        ko_history = kd.get('ko_history', [])

        if signal == 'LONG':   # reversal = bearish → want KO falling
            if ko_value < 0:
                return True, f"KO={ko_value:.0f} < 0 ✅"
            if len(ko_history) >= 3:
                falling = all(ko_history[i] > ko_history[i+1]
                              for i in range(len(ko_history)-3, len(ko_history)-1))
                if falling:
                    return True, (f"KO={ko_value:.0f} declining "
                                  f"{ko_history[-3]:.0f}→{ko_history[-2]:.0f}→{ko_history[-1]:.0f} ✅")
            return False, f"KO={ko_value:.0f} not yet falling ⚠️"
        else:   # SHORT reversal = bullish → want KO rising
            if ko_value > 0:
                return True, f"KO={ko_value:.0f} > 0 ✅"
            if len(ko_history) >= 3:
                rising = all(ko_history[i] < ko_history[i+1]
                             for i in range(len(ko_history)-3, len(ko_history)-1))
                if rising:
                    return True, (f"KO={ko_value:.0f} rising "
                                  f"{ko_history[-3]:.0f}→{ko_history[-2]:.0f}→{ko_history[-1]:.0f} ✅")
            return False, f"KO={ko_value:.0f} not yet rising ⚠️"
    except Exception:
        return False, "KO fetch error ⚠️"


def add_to_ha_watchlist(symbol: str, signal: str, instrument_key: str, reason: str = ""):
    """
    Add a symbol to the HA watchlist for monitoring after a rejected/missed signal.
    Called when an order cannot be placed (insufficient margin, order limit, etc.)
    """
    global HA_WATCHLIST
    HA_WATCHLIST[symbol] = {
        'signal':         signal,           # 'LONG' or 'SHORT'
        'instrument_key': instrument_key,
        'added_at':       now_ist(),
        'reason':         reason,
    }
    print(f"👁️  HA Watchlist: added {symbol} ({signal}) — {reason}")


def check_ha_reversal_alerts(access_token: str, trader=None):
    """
    Enhancement 1 — Active positions:
      Scans ACTIVE_POSITIONS for HA colour flip + Klinger confirmation.
      When Klinger CONFIRMS the flip, auto-exits the position via exit_position()
      instead of just printing an alert.  Unconfirmed flips still print a warning.

    Enhancement 2 — Missed/rejected signals (HA_WATCHLIST):
      Monitors symbols that fired a signal but whose order was rejected (e.g. margin).
      No position exists, so no P&L — just prints a directional reversal alert
      so you can act manually if circumstances change (e.g. funds added).
      Entries auto-expire after HA_WATCHLIST_MAX_AGE_MINUTES minutes.

    Doji early-warning applies to both pools.
    Alerts fire once per symbol/position per flip event (_HA_ALERTED suppressor).
    """
    global _HA_ALERTED, HA_WATCHLIST

    # ══════════════════════════════════════════════════════════════════════════
    # PART A — ACTIVE POSITIONS (Enhancement 1: auto-exit on confirmed flip)
    # ══════════════════════════════════════════════════════════════════════════
    for pos_id, position in list(ACTIVE_POSITIONS.items()):
        symbol         = position.get('symbol', '')
        signal         = position.get('fast_trade_signal', '')
        entry_price    = position.get('entry_price', 0)
        underlying_key = position.get('underlying_key', '')

        if not symbol or signal not in ('LONG', 'SHORT'):
            continue

        ikey = underlying_key or SYMBOL_TO_ISIN.get(symbol, '')
        res  = _ha_analyse_symbol(access_token, symbol, ikey, signal)
        if res is None:
            continue

        c_prev2        = res['c_prev2']
        c_prev1        = res['c_prev1']
        c_last         = res['c_last']
        is_doji        = res['is_doji']
        needs_alert    = res['needs_alert']
        last_body      = res['last_body']
        last_range     = res['last_range']
        underlying_ltp = res['underlying_ltp']

        # ── Doji early warning ───────────────────────────────────────────────
        if is_doji and not needs_alert:
            doji_key = f"{pos_id}_doji"
            if doji_key not in _HA_ALERTED:
                _HA_ALERTED.add(doji_key)
                print(
                    f"\n⚡ HA DOJI WARNING | {symbol} | {signal} position\n"
                    f"   Last HA candle is near-doji (body={last_body:.2f} / "
                    f"range={last_range:.2f} = {last_body/last_range*100:.0f}%) "
                    f"— possible reversal forming.\n"
                    f"   HA colours: [{c_prev2}] [{c_prev1}] [{c_last}] | "
                    f"Underlying LTP: ₹{underlying_ltp:.2f} | Entry: ₹{entry_price:.2f}"
                )
            continue

        if not needs_alert:
            _HA_ALERTED.discard(f"{pos_id}_doji")
            continue

        # ── Klinger confirmation ─────────────────────────────────────────────
        klinger_confirms, ko_desc = _ha_klinger_check(access_token, ikey, symbol, signal)

        flip_key = f"{pos_id}_flip"
        if flip_key in _HA_ALERTED:
            continue

        _HA_ALERTED.add(flip_key)

        confirmed_str = "CONFIRMED ✅" if klinger_confirms else "UNCONFIRMED ⚠️ (HA flip only)"
        counter       = "SHORT/PE" if signal == 'LONG' else "LONG/CE"
        arrow         = "🔴" if signal == 'LONG' else "🟢"

        # ── NEW: Check profit and trailing stop before auto‑exit ─────────────────
        # Get current P&L % from the position (already updated by monitor_active_positions)
        pnl_pct = position.get('pnl_percent', 0.0)
        pos_abs_pnl = abs(pnl_pct)

        # Minimum profit threshold: do not auto‑exit if profit is too small
        HA_AUTO_EXIT_MIN_PROFIT_PCT = 10.0   # configurable, can be adjusted
        if klinger_confirms and trader is not None and pos_abs_pnl < HA_AUTO_EXIT_MIN_PROFIT_PCT:
            print(
                f"\n⚡ HA reversal detected but AUTO-EXIT BLOCKED for {symbol} ({signal})\n"
                f"   Reason: Profit {pnl_pct:+.1f}% < {HA_AUTO_EXIT_MIN_PROFIT_PCT}% minimum.\n"
                f"   Flip will be logged but position will stay open."
            )
            # Still print the alert (so user sees it) but do NOT exit
            print(
                f"\n{'='*80}\n"
                f"{arrow} HA REVERSAL ALERT — {symbol} | {signal} position\n"
                f"{'='*80}\n"
                f"   HA flip:       [{c_prev2}] → [{c_prev1}] → [{c_last}] "
                f"(2 consecutive {c_last} candles)\n"
                f"   Klinger:       {ko_desc}\n"
                f"   Confirmation:  {confirmed_str}\n"
                f"   Entry price:   ₹{entry_price:.2f} | Underlying LTP: ₹{underlying_ltp:.2f}\n"
                f"   Current P&L:   {pnl_pct:+.1f}% (below minimum for auto-exit)\n"
                f"   Suggestion:    Consider exiting {signal} / entering {counter} manually\n"
                f"{'='*80}"
            )
            continue

        # Block auto‑exit if trailing stop is active and drawdown is small
        # We check: trailing stop active (profit >= TRAILING_STOP_ACTIVATION) AND
        #            position has a peak price recorded, and drawdown from peak < trailing percentage.
        HA_BLOCK_WHEN_TRAILING_ACTIVE = True
        if HA_BLOCK_WHEN_TRAILING_ACTIVE and pnl_pct >= TRAILING_STOP_ACTIVATION and pos_id in POSITION_PEAK_PRICES:
            peak = POSITION_PEAK_PRICES[pos_id]
            # Drawdown from peak (percentage)
            drawdown = (peak - current_price) / peak * 100 if current_price <= peak else 0.0
            if drawdown < TRAILING_STOP_PERCENTAGE:
                print(
                    f"\n⚡ HA reversal detected but AUTO-EXIT BLOCKED for {symbol} ({signal})\n"
                    f"   Reason: Trailing stop active (profit {pnl_pct:.1f}% >= {TRAILING_STOP_ACTIVATION}%),\n"
                    f"           drawdown from peak {drawdown:.1f}% < {TRAILING_STOP_PERCENTAGE}% trail.\n"
                    f"   Letting trailing stop manage exit instead."
                )
                # Still print the alert (so user sees it) but do NOT exit
                print(
                    f"\n{'='*80}\n"
                    f"{arrow} HA REVERSAL ALERT — {symbol} | {signal} position\n"
                    f"{'='*80}\n"
                    f"   HA flip:       [{c_prev2}] → [{c_prev1}] → [{c_last}]\n"
                    f"   Klinger:       {ko_desc}\n"
                    f"   Confirmation:  {confirmed_str}\n"
                    f"   Trailing stop active — auto-exit blocked (drawdown {drawdown:.1f}% < trail)\n"
                    f"   Entry: ₹{entry_price:.2f} | Peak: ₹{peak:.2f} | Current: ₹{current_price:.2f}\n"
                    f"{'='*80}"
                )
                continue

        # ── Enhancement 1: Auto-exit on confirmed flip ───────────────────────
        if klinger_confirms and trader is not None:
            print(
                f"\n{'='*80}\n"
                f"{arrow} HA REVERSAL — AUTO-EXITING {symbol} | {signal} position\n"
                f"{'='*80}\n"
                f"   HA flip:       [{c_prev2}] → [{c_prev1}] → [{c_last}]\n"
                f"   Klinger:       {ko_desc}\n"
                f"   Confirmation:  {confirmed_str}\n"
                f"   Entry price:   ₹{entry_price:.2f} | Underlying LTP: ₹{underlying_ltp:.2f}\n"
                f"   Action:        AUTO-EXITING position now ↓\n"
                f"{'='*80}"
            )
            try:
                # Get current option price for exit
                option_key   = position.get('instrument_key', '')
                current_price = trader.get_ltp(option_key) if option_key else None
                if current_price:
                    exit_position(trader, pos_id, position, current_price,
                                  reason="HA_REVERSAL_AUTO_EXIT")
                else:
                    print(f"   ⚠️ Could not fetch option LTP for auto-exit — manual exit needed.")
            except Exception as e:
                print(f"   ⚠️ Auto-exit error: {e} — manual exit needed.")
        else:
            # Unconfirmed flip or no trader — print alert only
            print(
                f"\n{'='*80}\n"
                f"{arrow} HA REVERSAL ALERT — {symbol} | {signal} position\n"
                f"{'='*80}\n"
                f"   HA flip:       [{c_prev2}] → [{c_prev1}] → [{c_last}] "
                f"(2 consecutive {c_last} candles)\n"
                f"   Klinger:       {ko_desc}\n"
                f"   Confirmation:  {confirmed_str}\n"
                f"   Entry price:   ₹{entry_price:.2f} | Underlying LTP: ₹{underlying_ltp:.2f}\n"
                f"   Suggestion:    Consider exiting {signal} / entering {counter}\n"
                f"{'='*80}"
            )
            if not klinger_confirms:
                print(f"   ℹ️  Klinger not yet confirming — watch next 1-2 candles before acting.")

    # ══════════════════════════════════════════════════════════════════════════
    # PART B — HA WATCHLIST: missed/rejected signals (Enhancement 2)
    # ══════════════════════════════════════════════════════════════════════════
    now = now_ist()
    expired = [sym for sym, w in HA_WATCHLIST.items()
               if (now - w['added_at']).total_seconds() / 60 > HA_WATCHLIST_MAX_AGE_MINUTES]
    for sym in expired:
        del HA_WATCHLIST[sym]
        _HA_ALERTED.discard(f"wl_{sym}_flip")
        _HA_ALERTED.discard(f"wl_{sym}_doji")
        if DEBUG_MODE:
            print(f"👁️  HA Watchlist: {sym} expired (>{HA_WATCHLIST_MAX_AGE_MINUTES}min)")

    for symbol, entry in list(HA_WATCHLIST.items()):
        signal = entry['signal']
        ikey   = entry['instrument_key'] or SYMBOL_TO_ISIN.get(symbol, '')
        reason = entry['reason']
        added  = entry['added_at'].strftime('%H:%M')

        res = _ha_analyse_symbol(access_token, symbol, ikey, signal)
        if res is None:
            continue

        c_prev2        = res['c_prev2']
        c_prev1        = res['c_prev1']
        c_last         = res['c_last']
        is_doji        = res['is_doji']
        needs_alert    = res['needs_alert']
        last_body      = res['last_body']
        last_range     = res['last_range']
        underlying_ltp = res['underlying_ltp']

        wl_id = f"wl_{symbol}"   # watchlist entries use symbol as key (no pos_id)

        # ── Doji early warning ───────────────────────────────────────────────
        if is_doji and not needs_alert:
            doji_key = f"{wl_id}_doji"
            if doji_key not in _HA_ALERTED:
                _HA_ALERTED.add(doji_key)
                print(
                    f"\n⚡ HA DOJI WARNING (WATCHLIST) | {symbol} | missed {signal} @ {added}\n"
                    f"   Rejection reason: {reason}\n"
                    f"   Last HA candle near-doji (body={last_body:.2f} / "
                    f"range={last_range:.2f} = {last_body/last_range*100:.0f}%) "
                    f"— possible reversal forming.\n"
                    f"   HA colours: [{c_prev2}] [{c_prev1}] [{c_last}] | "
                    f"Underlying LTP: ₹{underlying_ltp:.2f}"
                )
            continue

        if not needs_alert:
            _HA_ALERTED.discard(f"{wl_id}_doji")
            continue

        # ── Klinger confirmation ─────────────────────────────────────────────
        klinger_confirms, ko_desc = _ha_klinger_check(access_token, ikey, symbol, signal)

        flip_key = f"{wl_id}_flip"
        if flip_key in _HA_ALERTED:
            continue

        _HA_ALERTED.add(flip_key)

        confirmed_str = "CONFIRMED ✅" if klinger_confirms else "UNCONFIRMED ⚠️ (HA flip only)"
        counter       = "SHORT/PE" if signal == 'LONG' else "LONG/CE"
        arrow         = "🔴" if signal == 'LONG' else "🟢"

        print(
            f"\n{'='*80}\n"
            f"{arrow} HA REVERSAL ALERT (WATCHLIST) — {symbol} | missed {signal} signal @ {added}\n"
            f"{'='*80}\n"
            f"   Rejection:     {reason}\n"
            f"   HA flip:       [{c_prev2}] → [{c_prev1}] → [{c_last}] "
            f"(2 consecutive {c_last} candles)\n"
            f"   Klinger:       {ko_desc}\n"
            f"   Confirmation:  {confirmed_str}\n"
            f"   Underlying LTP: ₹{underlying_ltp:.2f}\n"
            f"   Note:          No position open — informational only.\n"
            f"{'='*80}"
        )
        if not klinger_confirms:
            print(f"   ℹ️  Klinger not yet confirming — watch next 1-2 candles.")


def clear_ha_alert(position_id: str):
    """Call when a position is exited — clears its HA alert state."""
    _HA_ALERTED.discard(f"{position_id}_flip")
    _HA_ALERTED.discard(f"{position_id}_doji")


def remove_from_ha_watchlist(symbol: str):
    """Remove a symbol from the HA watchlist (e.g. when funds are added and order succeeds)."""
    global HA_WATCHLIST
    if symbol in HA_WATCHLIST:
        del HA_WATCHLIST[symbol]
        _HA_ALERTED.discard(f"wl_{symbol}_flip")
        _HA_ALERTED.discard(f"wl_{symbol}_doji")
        if DEBUG_MODE:
            print(f"👁️  HA Watchlist: {symbol} removed")

# ═══════════════════════════════════════════════════════════════════════════════
# END HEIKIN-ASHI REVERSAL ALERT
# ═══════════════════════════════════════════════════════════════════════════════


def log_exit(closed_position):
    """Log exit details to CSV and text file"""
    try:
        # CSV log
        with open(EXIT_CSV_FILE, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                closed_position['exit_time'].strftime('%Y-%m-%d %H:%M:%S'),
                closed_position['symbol'],
                closed_position.get('strategy', 'UNKNOWN'),
                closed_position['entry_price'],
                closed_position['exit_price'],
                closed_position['quantity'],
                closed_position['pnl'],
                closed_position['pnl_percent'],
                closed_position['exit_reason'],
                closed_position.get('order_id', 'N/A')
            ])
        
        # Text log
        with open(EXIT_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(f"\n{'='*100}\n")
            f.write(f"EXIT: {closed_position['symbol']}\n")
            f.write(f"Time: {closed_position['exit_time'].strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Strategy: {closed_position.get('strategy', 'UNKNOWN')}\n")
            f.write(f"Entry: ₹{closed_position['entry_price']:.2f} | Exit: ₹{closed_position['exit_price']:.2f}\n")
            f.write(f"P&L: ₹{closed_position['pnl']:,.2f} ({closed_position['pnl_percent']:+.2f}%)\n")
            f.write(f"Reason: {closed_position['exit_reason']}\n")
            f.write(f"{'='*100}\n")
            
    except Exception as e:
        if DEBUG_MODE:
            print(f"⚡ Exit logging error: {e}")

def sync_positions_with_broker(trader):
    """Sync active positions with actual broker positions"""
    global ACTIVE_POSITIONS
    
    try:
        broker_positions = trader.get_positions()
        
        if broker_positions.get('status') != 'success':
            return
        
        positions_data = broker_positions.get('data', [])
        
        # Get instrument keys from broker positions
        broker_keys = set()
        for pos in positions_data:
            if pos.get('quantity', 0) != 0:  # Only open positions
                broker_keys.add(pos.get('instrument_token'))
        
        # Check if any of our tracked positions are no longer open
        closed_keys = []
        for position_id, position in ACTIVE_POSITIONS.items():
            if position['instrument_key'] not in broker_keys:
                # Position was closed outside our system (manual or SL hit)
                closed_keys.append(position_id)
        
        # Handle positions closed outside system
        for position_id in closed_keys:
            position = ACTIVE_POSITIONS[position_id]
            print(f"\n⚡ Position closed outside system: {position.get('symbol')}")
            
            # Try to get exit price from order history
            exit_price = position['entry_price']  # Default
            
            closed_position = {
                **position,
                'exit_price': exit_price,
                'exit_time': now_ist(),
                'exit_reason': 'EXTERNAL_CLOSE',
                'pnl': 0,
                'pnl_percent': 0
            }
            CLOSED_POSITIONS.append(closed_position)
            log_exit(closed_position)
            
            del ACTIVE_POSITIONS[position_id]
            
    except Exception as e:
        if DEBUG_MODE:
            print(f"⚡ Position sync error: {e}")

# ========== ORDER PLACEMENT FUNCTIONS ==========
def verify_order_result(trader, result, symbol):
    """Verify order placement result - FIXED VERSION"""
    if not result:
        print("❌ No order placed")
        return None
    
    status_code = result.get('status_code')
    response = result.get('response', {})
    
    print(f"\n📨 API Response:")
    print(f" Status Code: {status_code}")
    print(f" Status: {response.get('status')}")
    
    # FIX 2: Hard stop if order API failed
    if status_code != 200:
        print(f"❌ ORDER API FAILED (Status {status_code}): {response}")
        error_message = response.get('message', response.get('errors', 'Unknown error'))
        print(f"❌ Rejection Reason: {error_message}")
        return None
    
    if status_code == 200 and response.get('status') == 'success':
        order_id = response.get('data', {}).get('order_id')
        if order_id:
            print(f"\n🎉 ORDER PLACED SUCCESSFULLY!")
            print(f" Order ID: {order_id}")
            print(f"\n ⏳ Waiting {ORDER_VERIFICATION_DELAY} seconds...")
            time.sleep(ORDER_VERIFICATION_DELAY)
            print("\n 🔍 Checking order status...")
            order_details = trader.get_order_details(order_id)
            if order_details.get('status') == 'success' and 'data' in order_details:
                for order in order_details['data']:
                    status = order.get('status')
                    print(f"\n 📋 Order Status: {status.upper()}")
                    print(f" Symbol: {order.get('tradingsymbol')}")
                    print(f" Qty: {order.get('quantity')}")
                    avg_price = order.get('average_price', 0)
                    if avg_price > 0:
                        print(f" Filled Price: ₹{avg_price:.2f}")
                        total = avg_price * order.get('quantity', 0)
                        print(f" Total Value: ₹{total:,.2f}")
                    if status == 'complete':
                        print("\n ✅ ORDER EXECUTED!")
                        return {
                            'order_id': order_id,
                            'status': 'complete',
                            'filled_price': avg_price,
                            'quantity': order.get('quantity')
                        }
                    elif status == 'rejected':
                        print(f"\n ❌ REJECTED: {order.get('status_message')}")
                        return None
                    elif status in ['pending', 'open pending', 'trigger pending']:
                        print("\n ⏳ Order is PENDING")
                        return {
                            'order_id': order_id,
                            'status': 'pending',
                            'quantity': order.get('quantity')
                        }
            return {'order_id': order_id, 'status': 'unknown'}
        else:
            print("\n❌ ORDER FAILED")
            error_msg = response.get('message', 'Unknown error')
            print(f" Error: {error_msg}")
            if 'errors' in response:
                for error in response['errors']:
                    msg = error.get('message', error) if isinstance(error, dict) else str(error)
                    print(f" • {msg}")
            return None
    else:
        print("\n❌ ORDER FAILED")
        error_msg = response.get('message', 'Unknown error')
        print(f" Error: {error_msg}")
        return None

def place_breakout_order(breakout_data, trader):
    """Place OPTION orders for R3/S3/Box/Range breakouts"""
    global DAILY_ORDER_COUNT, BOX_ORDER_COUNT, RANGE_ORDER_COUNT, LAST_ORDER_TIME
    global PLACED_ORDERS, ACTIVE_POSITIONS, TRADING_STOPPED, POSITION_TRAILING_SL

    if TRADING_STOPPED:
        print("⚡ Trading stopped - no new orders")
        return None

    # Guard: Upstox rejects orders outside 05:30–23:59 with HTTP 423.
    # Check here (before option-chain lookup) to avoid wasted API calls.
    if not is_order_time_allowed():
        symbol   = breakout_data.get('symbol', '?')
        strategy = breakout_data.get('strategy', 'UNKNOWN')
        print(f"⏭️  {symbol} {strategy}: order skipped — outside Upstox service hours (05:30–23:59 IST)")
        return None

    symbol = breakout_data['symbol']
    underlying_key = breakout_data['instrument_key']
    breakout_type = breakout_data.get('breakout_type', 'CE')
    strategy = breakout_data.get('strategy', 'UNKNOWN')

    option_type = 'CE' if breakout_type == 'CE' else 'PE'

    # Select option contract
    selection = select_liquid_stock_option_contract(
        trader=trader,
        underlying_key=underlying_key,
        symbol=symbol,
        option_type=option_type,
        strike_offset_steps=0,
    )
    if not selection:
        print(f"⚡ Skipping {strategy} trade in {symbol} - no suitable {option_type} option.")
        return None

    option_key, option_symbol, strike, lot_size, premium, contract, is_premium_estimated = selection
    total_qty = lot_size * ORDER_QUANTITY

    print(f"\n📊 PLACING {option_type} OPTION ORDER for {symbol} ({strategy})")
    print(f" Underlying: {symbol}")
    print(f" Option: {option_symbol}")
    print(f" Strike: {strike} | Expiry: {contract.get('expiry')}")
    print(f" Lots: {ORDER_QUANTITY} | Lot size: {lot_size} | Total Qty: {total_qty}")
    print(f" Approx premium: ₹{premium:.2f} ({'ESTIMATED' if is_premium_estimated else 'LTP'})")
    
    # Show Klinger status if available
    if breakout_data.get('klinger_status'):
        print(f" 🔥 Klinger: {breakout_data['klinger_status']}")

    try:
        # FIX 6: Use LIMIT orders instead of MARKET for options
        limit_price = round(premium * 1.02, 2)  # Add 2% buffer for slippage
        
        print(f" 💰 Order Type: LIMIT @ ₹{limit_price:.2f} (premium ₹{premium:.2f} + 2% buffer)")
        
        result = trader.place_order(
            instrument_key=option_key,
            quantity=total_qty,
            transaction_type='BUY',
            product=ORDER_PRODUCT,
            order_type='LIMIT',      # <-- changed from MARKET
            price=limit_price         # <-- limit price added
        )

        order_info = verify_order_result(trader, result, option_symbol)
        if order_info and order_info.get('order_id'):
            order_id = order_info['order_id']
            
            # Update counters based on strategy
            if strategy in ['BOX_TOP', 'BOX_BOTTOM']:
                BOX_ORDER_COUNT += 1
            elif strategy in ['BOUNCE_BOTTOM', 'REJECT_TOP']:
                RANGE_ORDER_COUNT += 1
            else:
                DAILY_ORDER_COUNT += 1
                
            LAST_ORDER_TIME[symbol] = now_ist()
            filled_price = order_info.get('filled_price', premium)

            # Parse expiry date
            expiry_date = None
            try:
                expiry_date = datetime.strptime(contract.get('expiry'), "%Y-%m-%d")
            except:
                pass

            # Create position record
            position_record = {
                'order_id': order_id,
                'symbol': symbol,
                'option_symbol': option_symbol,
                'instrument_key': option_key,
                'underlying_key': underlying_key,
                'entry_price': filled_price,
                'quantity': total_qty,
                'breakout_type': breakout_type,
                'option_type': option_type,
                'trade_type': f'{strategy}_OPTION',
                'strategy': strategy,
                'timestamp': now_ist(),
                'expiry_date': expiry_date,
                'klinger_confirmed': breakout_data.get('klinger_confirmed', False),
                'is_premium_estimated': is_premium_estimated
            }

            PLACED_ORDERS[order_id] = position_record
            
            # Add to active positions for exit management
            if order_info.get('status') == 'complete':
                ACTIVE_POSITIONS[order_id] = position_record.copy()

            # Stop-loss
            if PLACE_STOPLOSS and order_info.get('status') == 'complete':
                sl_trigger = round(filled_price * (1 - STOPLOSS_PERCENTAGE / 100), 2)
                sl_limit = round(sl_trigger * 0.99, 2)

                print("\n🛡️ PLACING OPTION STOP-LOSS")
                print(f" Trigger: ₹{sl_trigger:.2f} | Limit: ₹{sl_limit:.2f}")

                try:
                    sl_result = trader.place_order(
                        instrument_key=option_key,
                        quantity=total_qty,
                        transaction_type='SELL',
                        product=ORDER_PRODUCT,
                        order_type='SL_LIMIT',   # <-- changed from 'SL'
                        price=sl_limit,
                        trigger_price=sl_trigger
                    )
                    if sl_result.get('status_code') == 200:
                        sl_order_id = sl_result['response'].get('data', {}).get('order_id')
                        if sl_order_id:
                            print(f"✅ SL Order ID: {sl_order_id}")
                            PLACED_ORDERS[order_id]['sl_order_id'] = sl_order_id
                            ACTIVE_POSITIONS[order_id]['sl_order_id'] = sl_order_id
                            POSITION_TRAILING_SL[order_id] = sl_trigger   # seed initial level
                except Exception as e:
                    print(f"⚡ SL placement error: {e}")

            return order_id

    except Exception as e:
        print(f"❌ Order error: {e}")
        return None

def place_gap_order(gap_info, signal, trader):
    """Place OPTION orders for gap trading signals"""
    global GAP_ORDER_COUNT, LAST_ORDER_TIME, PLACED_ORDERS, ACTIVE_POSITIONS, POSITION_TRAILING_SL
    global GAP_LEVELS, TRADING_STOPPED

    if TRADING_STOPPED:
        print("⚡ Trading stopped - no new orders")
        return None

    # Guard: same 05:30–23:59 window as all other strategies
    if not is_order_time_allowed():
        symbol = gap_info.get('symbol', '?')
        print(f"⏭️  {symbol} GAP: order skipped — outside Upstox service hours (05:30–23:59 IST)")
        return None

    symbol = gap_info['symbol']
    underlying_key = gap_info['instrument_key']
    direction = signal['direction']

    option_type = 'CE' if direction == 'LONG' else 'PE'

    selection = select_liquid_stock_option_contract(
        trader=trader,
        underlying_key=underlying_key,
        symbol=symbol,
        option_type=option_type,
        strike_offset_steps=0
    )
    if not selection:
        print(f"⚡ Skipping gap trade in {symbol} - no suitable {option_type} option.")
        return None

    option_key, option_symbol, strike, lot_size, premium, contract, is_premium_estimated = selection
    lots = int(max(1, ORDER_QUANTITY * GAP_POSITION_SIZE_MULTIPLIER))
    total_qty = lot_size * lots

    print(f"\n📊 PLACING GAP OPTION TRADE:")
    print(f" Symbol: {symbol}")
    print(f" Option: {option_symbol}")
    print(f" Strategy: {signal['signal']} | Direction: {direction} via {option_type}")
    print(f" Strike: {strike} | Expiry: {contract.get('expiry')}")
    print(f" Lots: {lots} | Lot size: {lot_size} | Total Qty: {total_qty}")
    print(f" Approx premium: ₹{premium:.2f} ({'ESTIMATED' if is_premium_estimated else 'LTP'})")

    try:
        # FIX 6: Use LIMIT orders instead of MARKET for options
        limit_price = round(premium * 1.02, 2)  # Add 2% buffer for slippage
        
        print(f" 💰 Order Type: LIMIT @ ₹{limit_price:.2f} (premium ₹{premium:.2f} + 2% buffer)")
        
        result = trader.place_order(
            instrument_key=option_key,
            quantity=total_qty,
            transaction_type='BUY',
            product=ORDER_PRODUCT,
            order_type='LIMIT',      # <-- changed from MARKET
            price=limit_price         # <-- limit price added
        )

        order_info = verify_order_result(trader, result, option_symbol)
        if order_info and order_info.get('order_id'):
            order_id = order_info['order_id']
            GAP_ORDER_COUNT += 1
            LAST_ORDER_TIME[symbol] = now_ist()
            filled_price = order_info.get('filled_price', premium)

            # Parse expiry date
            expiry_date = None
            try:
                expiry_date = datetime.strptime(contract.get('expiry'), "%Y-%m-%d")
            except:
                pass

            # Store gap info for exit management
            GAP_LEVELS[symbol] = gap_info

            position_record = {
                'order_id': order_id,
                'symbol': symbol,
                'option_symbol': option_symbol,
                'instrument_key': option_key,
                'underlying_key': underlying_key,
                'entry_price': filled_price,
                'quantity': total_qty,
                'trade_type': 'GAP_OPTION',
                'gap_signal': signal['signal'],
                'direction': direction,
                'timestamp': now_ist(),
                'expiry_date': expiry_date,
                'strategy': 'GAP',
                'is_premium_estimated': is_premium_estimated
            }

            PLACED_ORDERS[order_id] = position_record
            
            if order_info.get('status') == 'complete':
                ACTIVE_POSITIONS[order_id] = position_record.copy()

            if PLACE_STOPLOSS and order_info.get('status') == 'complete':
                sl_trigger = round(filled_price * (1 - STOPLOSS_PERCENTAGE / 100), 2)
                sl_limit = round(sl_trigger * 0.99, 2)

                gap_abs = abs(gap_info['gap_percent'])
                tp_pct = min(2.0 * gap_abs, 50.0) / 100.0
                target_price = round(filled_price * (1 + tp_pct), 2)

                print("\n🛡️ PLACING GAP OPTION SL & TARGET")
                print(f" SL Trigger: ₹{sl_trigger:.2f} | SL Limit: ₹{sl_limit:.2f}")
                print(f" Target: ₹{target_price:.2f}")

                try:
                    sl_result = trader.place_order(
                        instrument_key=option_key,
                        quantity=total_qty,
                        transaction_type='SELL',
                        product=ORDER_PRODUCT,
                        order_type='SL_LIMIT',   # <-- changed from 'SL'
                        price=sl_limit,
                        trigger_price=sl_trigger
                    )
                    target_result = trader.place_order(
                        instrument_key=option_key,
                        quantity=total_qty,
                        transaction_type='SELL',
                        product=ORDER_PRODUCT,
                        order_type='LIMIT',
                        price=target_price
                    )

                    if sl_result.get('status_code') == 200:
                        sl_order_id = sl_result['response'].get('data', {}).get('order_id')
                        if sl_order_id:
                            PLACED_ORDERS[order_id]['sl_order_id'] = sl_order_id
                            ACTIVE_POSITIONS[order_id]['sl_order_id'] = sl_order_id
                            POSITION_TRAILING_SL[order_id] = sl_trigger   # seed initial level
                            print(f" ✅ SL Order: {sl_order_id}")

                    if target_result.get('status_code') == 200:
                        target_order_id = target_result['response'].get('data', {}).get('order_id')
                        if target_order_id:
                            PLACED_ORDERS[order_id]['target_order_id'] = target_order_id
                            ACTIVE_POSITIONS[order_id]['target_order_id'] = target_order_id
                            print(f" ✅ Target Order: {target_order_id}")

                except Exception as e:
                    print(f"⚡ Exit orders error: {e}")

            return order_id

    except Exception as e:
        print(f"❌ Gap order error: {e}")
        return None

def send_alert(b, trader=None):
    """Send R3/S3/Box/Range breakout alerts"""
    global DAILY_ORDER_COUNT, BOX_ORDER_COUNT, RANGE_ORDER_COUNT, LAST_ORDER_TIME
    
    s = b['symbol']
    strategy = b.get('strategy', 'UNKNOWN')
    
    # ── DIRECTION-SPECIFIC ALERT REGISTRATION ───────────────────────────────
    # Write to the granular set so each direction can be re-watched independently.
    # Legacy aliases (ALERTED_STOCKS, BOX_ALERTED_STOCKS, RANGE_ALERTED_STOCKS)
    # kept in sync — all summary/log/order-limit code that reads them still works.
    if strategy == 'BOX_TOP':
        if s in BOX_TOP_ALERTED_STOCKS:
            return
        BOX_TOP_ALERTED_STOCKS.add(s)
        BOX_ALERTED_STOCKS.add(s)   # legacy alias
        csv_file = BOX_CSV_FILE
    elif strategy == 'BOX_BOTTOM':
        if s in BOX_BOTTOM_ALERTED_STOCKS:
            return
        BOX_BOTTOM_ALERTED_STOCKS.add(s)
        BOX_ALERTED_STOCKS.add(s)   # legacy alias
        csv_file = BOX_CSV_FILE
    elif strategy == 'BOUNCE_BOTTOM':
        if s in RANGE_BOUNCE_ALERTED_STOCKS:
            return
        RANGE_BOUNCE_ALERTED_STOCKS.add(s)
        RANGE_ALERTED_STOCKS.add(s) # legacy alias
        csv_file = RANGE_CSV_FILE
    elif strategy == 'REJECT_TOP':
        if s in RANGE_REJECT_ALERTED_STOCKS:
            return
        RANGE_REJECT_ALERTED_STOCKS.add(s)
        RANGE_ALERTED_STOCKS.add(s) # legacy alias
        csv_file = RANGE_CSV_FILE
    elif strategy == 'R3':
        if s in R3_ALERTED_STOCKS:
            return
        R3_ALERTED_STOCKS.add(s)
        ALERTED_STOCKS.add(s)       # legacy alias
        csv_file = ALERT_CSV_FILE
    elif strategy == 'S3':
        if s in S3_ALERTED_STOCKS:
            return
        S3_ALERTED_STOCKS.add(s)
        ALERTED_STOCKS.add(s)       # legacy alias
        csv_file = ALERT_CSV_FILE
    else:
        if s in ALERTED_STOCKS:
            return
        ALERTED_STOCKS.add(s)
        csv_file = ALERT_CSV_FILE
    
    day_gain = 100.0*(b['current_price'] - b['yesterday_close'])/b['yesterday_close'] if b['yesterday_close'] else 0.0
    
    is_pe = b.get('breakout_type') == 'PE'
    
    print("\n" + "="*120)
    print(f"🚀 {strategy} {'BREAKDOWN' if is_pe else 'BREAKOUT'} ALERT! 🚀")
    print("="*120)
    
    print(f"Stock: {s} | Time: {b['timestamp'].strftime('%H:%M:%S')}")
    print(f"Level: ₹{b.get('level', b.get('r3', b.get('s3', 0))):.2f} | Price: ₹{b['current_price']:.2f}")
    print(f"Volume: {b['volume_ratio']:.2f}x | Day Gain: {day_gain:+.2f}%")
    print(f"Strategy: {strategy} | Type: {b['breakout_type']}")
    
    # Show Klinger confirmation if available
    if b.get('klinger_confirmed'):
        print(f"🔥 Klinger: {b.get('klinger_status', 'CONFIRMED')}")
    
    # Automated order placement
    if (ENABLE_AUTO_TRADING or ENABLE_BOX_TRADING or ENABLE_RANGE_TRADING) and trader and not TRADING_STOPPED:
        print("\n" + "-"*120)
        total_orders = DAILY_ORDER_COUNT + BOX_ORDER_COUNT + RANGE_ORDER_COUNT + FAST_TRADE_ORDER_COUNT
        if total_orders >= MAX_ORDERS_PER_DAY:
            print("⚡ Daily order limit reached")
        elif s in LAST_ORDER_TIME:
            time_since = (now_ist() - LAST_ORDER_TIME[s]).seconds
            if time_since < MIN_ORDER_GAP_SECONDS:
                print(f"⚡ Too soon ({time_since}s)")
            else:
                place_breakout_order(b, trader)
        else:
            place_breakout_order(b, trader)
        print("-" * 120)

    print("="*120 + "\n")
    
    with open(csv_file, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            now_ist().strftime('%Y-%m-%d %H:%M:%S'),
            s,
            b.get('breakout_type', 'CE'),
            f"{b['current_price']:.2f}",
            f"{b['volume_ratio']:.2f}",
            f"{day_gain:.2f}%",
            strategy,
            b.get('klinger_status', 'N/A')
        ])

def print_position_summary():
    """Print summary of active positions"""
    global ACTIVE_POSITIONS, DAILY_PNL
    
    if not ACTIVE_POSITIONS:
        return
    
    print(f"\n{'='*120}")
    print(f"📊 ACTIVE POSITIONS SUMMARY ({len(ACTIVE_POSITIONS)} positions)")
    print(f"{'='*120}")
    
    total_unrealized_pnl = 0
    
    for position_id, position in ACTIVE_POSITIONS.items():
        symbol = position.get('option_symbol') or position['symbol']
        strategy = position.get('strategy', 'UNKNOWN')
        entry_price = position['entry_price']
        current_pnl = position.get('current_pnl', 0)
        pnl_percent = position.get('pnl_percent', 0)
        
        total_unrealized_pnl += current_pnl
        
        print(f"• {symbol} ({strategy})")
        print(f"  Entry: ₹{entry_price:.2f} | P&L: ₹{current_pnl:,.2f} ({pnl_percent:+.2f}%)")
    
    print(f"\n💰 Daily Realized P&L: ₹{DAILY_PNL:,.2f}")
    print(f"📈 Unrealized P&L: ₹{total_unrealized_pnl:,.2f}")
    print(f"📊 Total P&L: ₹{DAILY_PNL + total_unrealized_pnl:,.2f}")
    print(f"{'='*120}\n")

def print_final_stats():
    """Print session summary statistics"""
    global CLOSED_POSITIONS, CLOSED_FAST_TRADES
    
    print(f"\n{'='*100}")
    print("⚡ TRADING SESSION COMPLETE")
    print(f"{'='*100}")
    print(f"Time: {now_ist().strftime('%H:%M:%S')}")
    print(f"Total Stocks Monitored: {len(R3_LEVELS)}")
    print(f"\n📊 ALERTS SUMMARY:")
    print(f" • R3/S3 Alerts: {len(ALERTED_STOCKS)} (R3={len(R3_ALERTED_STOCKS)}, S3={len(S3_ALERTED_STOCKS)})")
    print(f" • Box Theory Alerts: {len(BOX_ALERTED_STOCKS)} (Top={len(BOX_TOP_ALERTED_STOCKS)}, Bottom={len(BOX_BOTTOM_ALERTED_STOCKS)})")
    print(f" • Range Trading Alerts: {len(RANGE_ALERTED_STOCKS)} (Bounce={len(RANGE_BOUNCE_ALERTED_STOCKS)}, Reject={len(RANGE_REJECT_ALERTED_STOCKS)})")
    print(f" • Gap Trading Alerts: {len(GAP_ALERTED_STOCKS)} (UP={len(GAP_UP_ALERTED_STOCKS)}, DOWN={len(GAP_DOWN_ALERTED_STOCKS)})")
    print(f" • Fast Trade Alerts: {len(FAST_TRADE_ALERTED_STOCKS)} "
          f"(LONG={len(FAST_TRADE_LONG_ALERTED)}, SHORT={len(FAST_TRADE_SHORT_ALERTED)})")
    if ENABLE_FII_REVERSAL:
        print(f" • FII Reversal Short Alerts: {len(FII_REVERSAL_ALERTED_STOCKS)}")
    if ENABLE_FII_REVERSAL_LONG:
        print(f" • FII Reversal Long  Alerts: {len(FII_REVERSAL_LONG_ALERTED_STOCKS)}")
    if ENABLE_ORB_STRATEGY:
        print(f" • ORB Alerts: {len(ORB_ALERTED_STOCKS)}")
    
    print(f"\n📈 ORDERS SUMMARY:")
    print(f" • R3/S3 Orders: {DAILY_ORDER_COUNT}")
    print(f" • Box Theory Orders: {BOX_ORDER_COUNT}")
    print(f" • Range Trading Orders: {RANGE_ORDER_COUNT}")
    print(f" • Gap Orders: {GAP_ORDER_COUNT}")
    print(f" • Fast Trade Orders: {FAST_TRADE_ORDER_COUNT}")
    if ENABLE_FII_REVERSAL:
        print(f" • FII Reversal Shorts: {len([o for o in PLACED_ORDERS.values() if o.get('strategy') == FII_REVERSAL_STRATEGY_NAME])}")
    if ENABLE_FII_REVERSAL_LONG:
        print(f" • FII Reversal Longs : {len([o for o in PLACED_ORDERS.values() if o.get('strategy') == FII_REVERSAL_LONG_STRATEGY_NAME])}")
    if ENABLE_ORB_STRATEGY:
        print(f" • ORB Orders: {ORB_ORDER_COUNT}")
    total_orders = DAILY_ORDER_COUNT + BOX_ORDER_COUNT + RANGE_ORDER_COUNT + GAP_ORDER_COUNT + FAST_TRADE_ORDER_COUNT + ORB_ORDER_COUNT
    print(f" • Total Orders: {total_orders}")
    
    if ENABLE_KLINGER_FILTER:
        klinger_confirmed_orders = sum(1 for order in PLACED_ORDERS.values() 
                                       if order.get('klinger_confirmed', False))
        print(f"\n🔥 KLINGER STATS:")
        print(f" • Orders with Klinger confirmation: {klinger_confirmed_orders}")
        if len(PLACED_ORDERS) > 0:
            print(f" • Klinger confirmation rate: {(klinger_confirmed_orders/len(PLACED_ORDERS)*100):.1f}%")
        if KLINGER_PAPER_MODE:
            print(f" • ✗ PAPER MODE: Logging only, not filtering")

    # Rejected signals summary
    if REJECTED_ORDER_SIGNALS:
        from collections import Counter
        reasons = Counter(r['reason'] for r in REJECTED_ORDER_SIGNALS)
        print(f"\n⚠️ REJECTED SIGNALS (signals fired but order not placed): {len(REJECTED_ORDER_SIGNALS)}")
        for reason, count in reasons.most_common():
            print(f"   • {reason}: {count} signal(s)")
    
    # Cache Stats
    if ENABLE_CANDLE_CACHE:
        print_cache_statistics()
    
    # Exit Management Stats
    print(f"\n🚨 EXIT MANAGEMENT STATS:")
    print(f" • Total Closed Positions: {len(CLOSED_POSITIONS)}")
    print(f" • Active Positions: {len(ACTIVE_POSITIONS)}")
    print(f" • Daily Realized P&L: ₹{DAILY_PNL:,.2f}")
    
    if CLOSED_POSITIONS:
        winning_trades = [p for p in CLOSED_POSITIONS if p['pnl'] > 0]
        losing_trades = [p for p in CLOSED_POSITIONS if p['pnl'] < 0]
        
        print(f" • Winning Trades: {len(winning_trades)}")
        print(f" • Losing Trades: {len(losing_trades)}")
        
        if len(CLOSED_POSITIONS) > 0:
            win_rate = (len(winning_trades) / len(CLOSED_POSITIONS)) * 100
            print(f" • Win Rate: {win_rate:.1f}%")
            
            avg_win = sum(p['pnl'] for p in winning_trades) / len(winning_trades) if winning_trades else 0
            avg_loss = sum(p['pnl'] for p in losing_trades) / len(losing_trades) if losing_trades else 0
            
            print(f" • Avg Win: ₹{avg_win:,.2f}")
            print(f" • Avg Loss: ₹{avg_loss:,.2f}")
            
            if avg_loss != 0:
                profit_factor = abs(avg_win / avg_loss) if avg_loss < 0 else 0
                print(f" • Profit Factor: {profit_factor:.2f}")
        
        # Exit reasons breakdown
        exit_reasons = {}
        for pos in CLOSED_POSITIONS:
            reason = pos['exit_reason']
            exit_reasons[reason] = exit_reasons.get(reason, 0) + 1
        
        print(f"\n 📋 Exit Reasons Breakdown:")
        for reason, count in sorted(exit_reasons.items(), key=lambda x: x[1], reverse=True):
            print(f"   • {reason}: {count}")
    
    # Fast Trading Stats
    if ENABLE_FAST_TRADING and CLOSED_FAST_TRADES:
        print(f"\n⚡ FAST TRADING STATS:")
        print(f" • Closed Fast Trades: {len(CLOSED_FAST_TRADES)}")
        print(f" • Active Fast Trades: {len(ACTIVE_FAST_TRADES)}")
        
        fast_winners = [t for t in CLOSED_FAST_TRADES if t['pnl'] > 0]
        fast_losers = [t for t in CLOSED_FAST_TRADES if t['pnl'] <= 0]
        
        if CLOSED_FAST_TRADES:
            fast_win_rate = (len(fast_winners) / len(CLOSED_FAST_TRADES)) * 100
            print(f" • Fast Trade Win Rate: {fast_win_rate:.1f}%")
            
            avg_fast_pnl = sum(t['pnl'] for t in CLOSED_FAST_TRADES) / len(CLOSED_FAST_TRADES)
            print(f" • Avg Fast Trade P&L: ₹{avg_fast_pnl:,.2f}")
            
            # Analyze by entry type
            entry_types = {}
            for trade in CLOSED_FAST_TRADES:
                entry_type = trade.get('fast_trade_entry_type', 'UNKNOWN')
                entry_types[entry_type] = entry_types.get(entry_type, 0) + 1
            
            print(f" • Entry Type Breakdown:")
            for entry_type, count in entry_types.items():
                print(f"   - {entry_type}: {count} trades")
    
    # ORB Stats
    if ENABLE_ORB_STRATEGY:
        print_orb_summary()

    # Reversal Stats
    if ENABLE_REVERSAL_STRATEGY:
        print_reversal_summary()
    
    if PLACED_ORDERS:
        print(f"\n📋 ALL ORDERS PLACED:")
        for order_id, order_info in PLACED_ORDERS.items():
            trade_type = order_info.get('trade_type', 'Unknown')
            symbol = order_info['symbol']
            strategy = order_info.get('strategy', '')
            klinger = "✓" if order_info.get('klinger_confirmed') else ""
            premium_source = "EST" if order_info.get('is_premium_estimated') else "LTP"
            print(f" • {symbol} ({trade_type} {strategy}) {klinger}[{premium_source}]: Order {order_id}")
            print(f"   Entry: ₹{order_info['entry_price']:.2f} | Qty: {order_info['quantity']}")
            if 'sl_order_id' in order_info:
                print(f"   SL: {order_info['sl_order_id']}")
            if 'target_order_id' in order_info:
                print(f"   Target: {order_info['target_order_id']}")
    
    if ACTIVE_POSITIONS:
        print(f"\n⚡ OPEN POSITIONS (Not Exited):")
        for position_id, position in ACTIVE_POSITIONS.items():
            symbol = position.get('option_symbol') or position['symbol']
            print(f" • {symbol}: {position.get('strategy', 'UNKNOWN')}")
            print(f"   Entry: ₹{position['entry_price']:.2f} | Current P&L: ₹{position.get('current_pnl', 0):,.2f}")
    
    print(f"{'='*100}\n")
    
    # Final log
    with open(ALERT_LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(f"\n{'='*100}\n")
        f.write(f"SESSION END: {now_ist().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"R3/S3 Alerts: {len(ALERTED_STOCKS)} | Orders: {DAILY_ORDER_COUNT}\n")
        f.write(f"Box Theory Alerts: {len(BOX_ALERTED_STOCKS)} | Orders: {BOX_ORDER_COUNT}\n")
        f.write(f"Range Trading Alerts: {len(RANGE_ALERTED_STOCKS)} | Orders: {RANGE_ORDER_COUNT}\n")
        f.write(f"Gap Alerts: {len(GAP_ALERTED_STOCKS)} | Orders: {GAP_ORDER_COUNT}\n")
        f.write(f"Fast Trade Alerts: {len(FAST_TRADE_ALERTED_STOCKS)} | Orders: {FAST_TRADE_ORDER_COUNT}\n")
        if ENABLE_FII_REVERSAL:
            fii_short_orders = len([o for o in PLACED_ORDERS.values() if o.get('strategy') == FII_REVERSAL_STRATEGY_NAME])
            f.write(f"FII Reversal Short Alerts: {len(FII_REVERSAL_ALERTED_STOCKS)} | Orders: {fii_short_orders}\n")
        if ENABLE_FII_REVERSAL_LONG:
            fii_long_orders = len([o for o in PLACED_ORDERS.values() if o.get('strategy') == FII_REVERSAL_LONG_STRATEGY_NAME])
            f.write(f"FII Reversal Long  Alerts: {len(FII_REVERSAL_LONG_ALERTED_STOCKS)} | Orders: {fii_long_orders}\n")
        if ENABLE_ORB_STRATEGY:
            f.write(f"ORB Alerts: {len(ORB_ALERTED_STOCKS)} | Orders: {ORB_ORDER_COUNT}\n")
        f.write(f"Total Orders: {DAILY_ORDER_COUNT + BOX_ORDER_COUNT + RANGE_ORDER_COUNT + GAP_ORDER_COUNT + FAST_TRADE_ORDER_COUNT + ORB_ORDER_COUNT}\n")
        f.write(f"Closed Positions: {len(CLOSED_POSITIONS)} | Daily P&L: ₹{DAILY_PNL:,.2f}\n")
        if ENABLE_KLINGER_FILTER:
            klinger_count = sum(1 for order in PLACED_ORDERS.values() 
                              if order.get('klinger_confirmed', False))
            f.write(f"Klinger Confirmed Orders: {klinger_count}\n")
        if ENABLE_FAST_TRADING:
            f.write(f"Closed Fast Trades: {len(CLOSED_FAST_TRADES)}\n")
        if ENABLE_CANDLE_CACHE:
            f.write(f"Cache Hits: {CACHE_STATS['cache_hits']} | Misses: {CACHE_STATS['cache_misses']}\n")
        f.write(f"{'='*100}\n\n")

# ========== MAIN MONITORING LOOP ==========

# ─────────────────────────────────────────────────────────────────────────────
# FII TREND REVERSAL — shared helper functions
# Resamples 5-min candles to 1-hour, computes Heikin-Ashi, and attaches EMAs.
# Both detect_fii_reversal() and detect_fii_reversal_long() rely on these.
# ─────────────────────────────────────────────────────────────────────────────

def resample_to_1h(df5: 'pd.DataFrame') -> 'pd.DataFrame | None':
    """
    Resample a 5-minute OHLCV DataFrame to 1-hour bars.
    Expects 'timestamp' column (or a DatetimeIndex) plus open/high/low/close/volume.
    Returns a new DataFrame indexed by hour-start timestamp, or None on failure.
    """
    try:
        import pandas as pd
        df = df5.copy()

        # Ensure a proper DatetimeIndex
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df = df.set_index('timestamp')
        elif not isinstance(df.index, pd.DatetimeIndex):
            return None

        ohlcv = df[['open', 'high', 'low', 'close', 'volume']].copy()
        df1h = ohlcv.resample('1h').agg({
            'open':   'first',
            'high':   'max',
            'low':    'min',
            'close':  'last',
            'volume': 'sum',
        }).dropna()
        return df1h.reset_index()
    except Exception as e:
        if DEBUG_MODE:
            print(f"⛔ resample_to_1h error: {e}")
        return None


def compute_ha_1h(df1h: 'pd.DataFrame') -> 'pd.DataFrame':
    """
    Add Heikin-Ashi columns (ha_open, ha_high, ha_low, ha_close, ha_color) to a
    1-hour OHLC DataFrame in-place and return it.
    """
    try:
        import numpy as np
        df = df1h.copy()
        ha_close = (df['open'] + df['high'] + df['low'] + df['close']) / 4.0

        ha_open = ha_close.copy()
        ha_open.iloc[0] = (df['open'].iloc[0] + df['close'].iloc[0]) / 2.0
        for i in range(1, len(df)):
            ha_open.iloc[i] = (ha_open.iloc[i - 1] + ha_close.iloc[i - 1]) / 2.0

        ha_high = pd.concat([df['high'], ha_open, ha_close], axis=1).max(axis=1)
        ha_low  = pd.concat([df['low'],  ha_open, ha_close], axis=1).min(axis=1)

        df['ha_open']  = ha_open
        df['ha_high']  = ha_high
        df['ha_low']   = ha_low
        df['ha_close'] = ha_close
        df['ha_color'] = np.where(ha_close >= ha_open, 'green', 'red')
        return df
    except Exception as e:
        if DEBUG_MODE:
            print(f"⛔ compute_ha_1h error: {e}")
        return df1h


def add_ema_indicators_1h(df1h: 'pd.DataFrame') -> 'pd.DataFrame':
    """
    Attach three EMA columns (ema_fast, ema_slow, ema_trend) to the 1-hour
    DataFrame using the FII_REVERSAL config periods (9 / 21 / 50).
    Works for both short and long configs — periods are identical.
    """
    try:
        df = df1h.copy()
        src = df['ha_close'] if 'ha_close' in df.columns else df['close']
        df['ema_fast']  = src.ewm(span=FII_REVERSAL_EMA_FAST,  adjust=False).mean()
        df['ema_slow']  = src.ewm(span=FII_REVERSAL_EMA_SLOW,  adjust=False).mean()
        df['ema_trend'] = src.ewm(span=FII_REVERSAL_EMA_TREND, adjust=False).mean()
        return df
    except Exception as e:
        if DEBUG_MODE:
            print(f"⛔ add_ema_indicators_1h error: {e}")
        return df1h


def detect_fii_reversal(access_token, live_data):
    """
    FII Trend Reversal SHORT Setup (Bearish).

    Scans stocks where FII is BUYING (STRONG_BUY / FII_BUY_DII_SELL) but price
    shows a 1-hour bearish reversal pattern — a 'distribution' setup where
    institutional buying is exhausting:

    Entry conditions (all must be true on the *completed* H1 bar, i.e. iloc[-2]):
      1. Break Low  : current H1 bar's low < previous H1 bar's low
      2. Red HA     : ha_color == 'red'
      3. EMA Bear X : ema_fast crosses below ema_slow (prev: fast >= slow, now: fast < slow)
      4. Below trend: ha_close < ema_trend
      5. Volume     : live volume ≥ FII_REVERSAL_MIN_VOLUME_RATIO × avg_volume_20d

    Each symbol alerts at most once per session (FII_REVERSAL_ALERTED_STOCKS).
    """
    global FII_REVERSAL_ALERTED_STOCKS
    if not ENABLE_FII_REVERSAL:
        return []

    signals  = []
    # Scan stocks where FII is accumulating (most likely to be exhausted / reversed)
    pool = list(FII_DII_STRONG_BUY.union(
        getattr(globals().get('FII_DII_TREND_FII_BUY_DII_SELL', set()), '__iter__', lambda: iter([]))()
    ))[:FII_REVERSAL_MAX_SYMBOLS]

    for key in pool:
        if key not in R3_LEVELS:
            continue
        if key in FII_REVERSAL_ALERTED_STOCKS:
            continue

        info   = R3_LEVELS[key]
        symbol = info.get('symbol', key)

        try:
            df5 = fetch_5min_cached(access_token, key, bars=300, symbol=symbol)
            if df5 is None or len(df5) < 60:
                continue

            df1h = resample_to_1h(df5)
            if df1h is None or len(df1h) < 8:
                continue

            df1h = compute_ha_1h(df1h)
            df1h = add_ema_indicators_1h(df1h)

            if len(df1h) < 3:
                continue

            c = df1h.iloc[-2]   # last completed bar
            p = df1h.iloc[-3]   # bar before that

            break_low   = c['low']      < p['low']
            ha_red      = c['ha_color'] == 'red'
            ema_cross   = (p['ema_fast'] >= p['ema_slow']) and (c['ema_fast'] < c['ema_slow'])
            below_trend = c['ha_close'] < c['ema_trend']

            live         = live_data.get(key, {})
            avg_vol      = info.get('avg_volume_20d') or info.get('avg_volume', 1) or 1
            volume_ratio = live.get('volume', 0) / avg_vol

            if break_low and ha_red and ema_cross and below_trend and volume_ratio >= FII_REVERSAL_MIN_VOLUME_RATIO:
                FII_REVERSAL_ALERTED_STOCKS.add(key)
                signals.append({
                    'symbol':            symbol,
                    'instrument_key':    key,
                    'current_price':     live.get('ltp'),
                    'level':             c['low'],
                    'breakout_type':     'PE',
                    'strategy':          FII_REVERSAL_STRATEGY_NAME,
                    'volume_ratio':      round(volume_ratio, 2),
                    'timestamp':         now_ist(),
                    'klinger_confirmed': True,
                })
                if DEBUG_MODE:
                    print(f"🔴 FII_REVERSAL_SHORT candidate: {symbol} | vol {volume_ratio:.2f}x")
        except Exception as e:
            if DEBUG_MODE:
                print(f"⛔ detect_fii_reversal [{symbol}]: {e}")

    return signals


def detect_fii_reversal_long(access_token, live_data):
    """
    FII Trend Reversal LONG Setup (Bullish counterpart).

    Scans stocks where FII is SELLING (STRONG_SELL / FII_SELL_DII_BUY) but price
    shows a 1-hour bullish reversal pattern — a 'capitulation low' or 'DII support'
    setup where institutional selling is exhausting:

    Entry conditions (all must be true on the *completed* H1 bar, i.e. iloc[-2]):
      1. Break High : current H1 bar's high > previous H1 bar's high
      2. Green HA   : ha_color == 'green'
      3. EMA Bull X : ema_fast crosses above ema_slow (prev: fast <= slow, now: fast > slow)
      4. Above trend: ha_close > ema_trend
      5. Volume     : live volume ≥ FII_REVERSAL_LONG_MIN_VOLUME_RATIO × avg_volume_20d

    Each symbol alerts at most once per session (FII_REVERSAL_LONG_ALERTED_STOCKS).
    """
    global FII_REVERSAL_LONG_ALERTED_STOCKS
    if not ENABLE_FII_REVERSAL_LONG:
        return []

    signals  = []
    # Scan stocks where FII is distributing — price reversal here = high-conviction long
    pool = list(FII_DII_STRONG_SELL.union(FII_DII_TREND_FII_SELL_DII_BUY))[:FII_REVERSAL_LONG_MAX_SYMBOLS]

    for key in pool:
        if key not in R3_LEVELS:
            continue
        if key in FII_REVERSAL_LONG_ALERTED_STOCKS:
            continue

        info   = R3_LEVELS[key]
        symbol = info.get('symbol', key)

        try:
            df5 = fetch_5min_cached(access_token, key, bars=300, symbol=symbol)
            if df5 is None or len(df5) < 60:
                continue

            df1h = resample_to_1h(df5)
            if df1h is None or len(df1h) < 8:
                continue

            df1h = compute_ha_1h(df1h)
            df1h = add_ema_indicators_1h(df1h)

            if len(df1h) < 3:
                continue

            c = df1h.iloc[-2]   # last completed bar
            p = df1h.iloc[-3]   # bar before that

            break_high  = c['high']     > p['high']
            ha_green    = c['ha_color'] == 'green'
            ema_cross   = (p['ema_fast'] <= p['ema_slow']) and (c['ema_fast'] > c['ema_slow'])
            above_trend = c['ha_close'] > c['ema_trend']

            live         = live_data.get(key, {})
            avg_vol      = info.get('avg_volume_20d') or info.get('avg_volume', 1) or 1
            volume_ratio = live.get('volume', 0) / avg_vol

            if break_high and ha_green and ema_cross and above_trend and volume_ratio >= FII_REVERSAL_LONG_MIN_VOLUME_RATIO:
                FII_REVERSAL_LONG_ALERTED_STOCKS.add(key)
                signals.append({
                    'symbol':            symbol,
                    'instrument_key':    key,
                    'current_price':     live.get('ltp'),
                    'level':             c['high'],
                    'breakout_type':     'CE',
                    'strategy':          FII_REVERSAL_LONG_STRATEGY_NAME,
                    'volume_ratio':      round(volume_ratio, 2),
                    'timestamp':         now_ist(),
                    'klinger_confirmed': True,
                })
                if DEBUG_MODE:
                    print(f"🟢 FII_REVERSAL_LONG candidate: {symbol} | vol {volume_ratio:.2f}x")
        except Exception as e:
            if DEBUG_MODE:
                print(f"⛔ detect_fii_reversal_long [{symbol}]: {e}")

    return signals

# ══════════════════════════════════════════════════════════════════════════════
#  SESSION-PHASE ENGINE
#  Phase 1 (09:15–10:30): ORB Momentum         ← already handled above
#  Phase 2 (10:30–13:00): Midday Box Breakout
#  Phase 3 (13:00–15:15): Afternoon Pivot Reversal (R3/S3 + VWAP + RSI)
# ══════════════════════════════════════════════════════════════════════════════

def calculate_session_vwap(symbol, access_token, ikey):
    """Compute session VWAP from merged hist+RT 5-min bars (09:15 onwards).

    Uses fetch_5min_cached so data is available from market open.
    Returns float or None.
    """
    try:
        df = fetch_5min_cached(access_token, ikey, bars=80, symbol=symbol)
        if df is None or len(df) < 3:
            return None
        # Filter to today's session only
        today = now_ist().date()
        df = df[pd.to_datetime(df['date']).dt.date == today].copy()
        if df.empty:
            return None
        tp = (df['high'] + df['low'] + df['close']) / 3.0
        vol = df['volume'].clip(lower=0)
        total_vol = vol.sum()
        return float((tp * vol).sum() / total_vol) if total_vol > 0 else None
    except Exception as e:
        if DEBUG_MODE:
            print(f"⚠️ VWAP calc error {symbol}: {e}")
        return None


def update_midday_box_state(live_data):
    """Track high/low of every symbol during 10:30–13:00 consolidation window.

    Called every scan during Phase 2.  Stores per-symbol box in MIDDAY_BOX_STATE.
    """
    global MIDDAY_BOX_STATE
    ct = now_ist()
    for ikey, data in live_data.items():
        symbol = ISIN_TO_SYMBOL.get(ikey, ikey)
        ltp = data.get('ltp', 0)
        if ltp <= 0:
            continue
        state = MIDDAY_BOX_STATE.get(symbol)
        if state is None:
            MIDDAY_BOX_STATE[symbol] = {
                'box_high': ltp, 'box_low': ltp,
                'candles': 1, 'sealed': False, 'start': ct
            }
        elif not state['sealed']:
            state['box_high'] = max(state['box_high'], ltp)
            state['box_low']  = min(state['box_low'],  ltp)
            state['candles'] += 1


def check_midday_box_breakout(symbol, ltp, volume, live_data):
    """Detect breakout from the 10:30–13:00 consolidation box after 13:00.

    Returns a signal dict or None.
    """
    global MIDDAY_BOX_STATE, MIDDAY_BOX_ORDER_COUNT, MIDDAY_BOX_ALERTED

    if not ENABLE_MIDDAY_BOX:
        return None
    if MIDDAY_BOX_ORDER_COUNT >= MIDDAY_BOX_MAX_ORDERS:
        return None
    if symbol in MIDDAY_BOX_ALERTED:
        return None

    state = MIDDAY_BOX_STATE.get(symbol)
    if not state or state['candles'] < 4:   # need at least 4 datapoints to form a box
        return None

    box_high = state['box_high']
    box_low  = state['box_low']
    box_range_pct = (box_high - box_low) / box_low * 100

    # Filter out boxes that are too tight (noise) or too wide (no consolidation)
    if box_range_pct < MIDDAY_BOX_MIN_RANGE_PCT or box_range_pct > MIDDAY_BOX_MAX_RANGE_PCT:
        if DEBUG_MODE:
            print(f"⛔ Midday box {symbol}: range {box_range_pct:.2f}% outside "
                  f"[{MIDDAY_BOX_MIN_RANGE_PCT},{MIDDAY_BOX_MAX_RANGE_PCT}]%")
        return None

    # Breakout: price clears box edge by buffer
    buffer_up   = box_high * (1 + MIDDAY_BOX_BREAKOUT_BUFFER / 100)
    buffer_down = box_low  * (1 - MIDDAY_BOX_BREAKOUT_BUFFER / 100)

    if ltp > buffer_up:
        direction = 'BUY'
    elif ltp < buffer_down:
        direction = 'SELL'
    else:
        return None     # still inside box

    # Volume confirmation
    avg_vol = (VOLUME_DATA.get(symbol, {}).get('avg_volume') or
               VOLUME_DATA.get(symbol, {}).get('avg_vol_20d') or
               live_data.get('avg_volume', 0))
    vol_ratio = volume / avg_vol if avg_vol > 0 else 0
    if avg_vol > 0 and vol_ratio < MIDDAY_BOX_VOLUME_MIN:
        if DEBUG_MODE:
            print(f"⛔ Midday box {symbol}: vol ratio {vol_ratio:.2f} < {MIDDAY_BOX_VOLUME_MIN}")
        return None

    # FII/DII alignment
    fii_signal = get_fii_dii_signal(symbol)
    if direction == 'BUY'  and fii_signal in ('STRONG_SELL', 'SELL'):
        if DEBUG_MODE:
            print(f"⛔ Midday box {symbol}: BUY blocked by FII/DII={fii_signal}")
        return None
    if direction == 'SELL' and fii_signal in ('STRONG_BUY', 'BUY'):
        if DEBUG_MODE:
            print(f"⛔ Midday box {symbol}: SELL blocked by FII/DII={fii_signal}")
        return None

    # Build signal
    if direction == 'BUY':
        stop   = box_low  * 0.997
        risk   = ltp - stop
        target = ltp + 2.0 * risk if risk > 0 else ltp * 1.01
    else:
        stop   = box_high * 1.003
        risk   = stop - ltp
        target = ltp - 2.0 * risk if risk > 0 else ltp * 0.99

    MIDDAY_BOX_ALERTED.add(symbol)

    return {
        'symbol':       symbol,
        'signal':       'MIDDAY_BOX_BREAKOUT',
        'direction':    direction,
        'entry_price':  ltp,
        'stop_loss':    stop,
        'target':       target,
        'box_high':     box_high,
        'box_low':      box_low,
        'box_range_pct': box_range_pct,
        'volume_ratio': vol_ratio,
        'fii_dii':      fii_signal,
        'timestamp':    now_ist(),
    }


def check_afternoon_pivot_reversal(symbol, ltp, access_token, ikey, trader=None):
    """Afternoon R3/S3 pivot reversal (13:00–15:15).

    Entry logic (mirroring the blueprint):
      SHORT: price >= R3 AND RSI >= AFTERNOON_RSI_OVERBOUGHT
             AND (VWAP confirm OFF or ltp < VWAP) — momentum exhausting at R3
      LONG:  price <= S3 AND RSI <= AFTERNOON_RSI_OVERSOLD
             AND (VWAP confirm OFF or ltp > VWAP) — buyers reclaiming S3

    Secondary gate: Klinger turning in the trade direction (if enabled).
    Returns signal dict or None.
    """
    global AFTERNOON_ORDER_COUNT, AFTERNOON_ALERTED

    if not ENABLE_AFTERNOON_PIVOT:
        return None
    if AFTERNOON_ORDER_COUNT >= AFTERNOON_MAX_ORDERS:
        return None
    if symbol in AFTERNOON_ALERTED:
        return None

    info = R3_LEVELS.get(ikey, {})
    if not info:
        return None

    r3    = info.get('r3')
    s3    = info.get('s3')
    pivot = info.get('pivot')
    if r3 is None or s3 is None:
        return None

    # Price proximity to R3 or S3
    dist_r3_pct = (ltp - r3) / r3 * 100   # positive = above R3
    dist_s3_pct = (s3 - ltp) / s3 * 100   # positive = below S3

    at_r3 = dist_r3_pct >= 0 and abs(dist_r3_pct) <= AFTERNOON_R3_BAND_PCT
    at_s3 = dist_s3_pct >= 0 and abs(dist_s3_pct) <= AFTERNOON_R3_BAND_PCT

    if not at_r3 and not at_s3:
        if DEBUG_MODE:
            print(f"⛔ Afternoon pivot {symbol}: not near R3({r3:.2f}) or S3({s3:.2f}) "
                  f"— ltp={ltp:.2f}")
        return None

    # RSI gate
    try:
        df = fetch_5min_cached(access_token, ikey, bars=60, symbol=symbol)
        if df is None or len(df) < 15:
            if DEBUG_MODE:
                print(f"⛔ Afternoon pivot {symbol}: insufficient bars for RSI")
            return None
        rsi = calculate_rsi(df, period=14)
    except Exception as e:
        if DEBUG_MODE:
            print(f"⛔ Afternoon pivot {symbol}: RSI error {e}")
        return None

    # VWAP
    vwap = calculate_session_vwap(symbol, access_token, ikey) if AFTERNOON_VWAP_CONFIRM else None

    # Klinger
    klinger_info = info.get('klinger')
    ko = klinger_info.get('klinger', 0) if klinger_info else 0
    ko_prev = klinger_info.get('klinger_prev', 0) if klinger_info else 0
    klinger_bearish = ko < ko_prev   # falling = bearish
    klinger_bullish = ko > ko_prev   # rising  = bullish

    direction = None

    if at_r3 and rsi is not None and rsi >= AFTERNOON_RSI_OVERBOUGHT:
        # SHORT setup: price stretched to R3, RSI overbought
        vwap_ok = (not AFTERNOON_VWAP_CONFIRM or vwap is None or ltp < vwap)
        klinger_ok = (not AFTERNOON_REQUIRE_KLINGER or klinger_bearish)
        if vwap_ok and klinger_ok:
            direction = 'SELL'
        elif DEBUG_MODE:
            print(f"⛔ Afternoon pivot {symbol} R3 SHORT: "
                  f"VWAP_ok={vwap_ok}(ltp={ltp:.1f} vwap={vwap}), "
                  f"Klinger_ok={klinger_ok}(KO={ko:.0f}↓={klinger_bearish})")

    elif at_s3 and rsi is not None and rsi <= AFTERNOON_RSI_OVERSOLD:
        # LONG setup: price exhausted at S3, RSI oversold
        vwap_ok = (not AFTERNOON_VWAP_CONFIRM or vwap is None or ltp > vwap)
        klinger_ok = (not AFTERNOON_REQUIRE_KLINGER or klinger_bullish)
        if vwap_ok and klinger_ok:
            direction = 'BUY'
        elif DEBUG_MODE:
            print(f"⛔ Afternoon pivot {symbol} S3 LONG: "
                  f"VWAP_ok={vwap_ok}(ltp={ltp:.1f} vwap={vwap}), "
                  f"Klinger_ok={klinger_ok}(KO={ko:.0f}↑={klinger_bullish})")

    if direction is None:
        return None

    # FII/DII alignment
    fii_signal = get_fii_dii_signal(symbol)
    if direction == 'SELL' and fii_signal in ('STRONG_BUY', 'BUY'):
        if DEBUG_MODE:
            print(f"⛔ Afternoon pivot {symbol}: SELL blocked by FII/DII={fii_signal}")
        return None
    if direction == 'BUY' and fii_signal in ('STRONG_SELL', 'SELL'):
        if DEBUG_MODE:
            print(f"⛔ Afternoon pivot {symbol}: BUY blocked by FII/DII={fii_signal}")
        return None

    # Risk/reward
    last_candle = df.iloc[-1]
    if direction == 'SELL':
        stop   = last_candle['high'] * 1.003
        risk   = stop - ltp
        target = ltp - AFTERNOON_RISK_REWARD_MIN * risk if risk > 0 else ltp * 0.985
    else:
        stop   = last_candle['low'] * 0.997
        risk   = ltp - stop
        target = ltp + AFTERNOON_RISK_REWARD_MIN * risk if risk > 0 else ltp * 1.015

    if risk <= 0:
        return None

    rr = abs(target - ltp) / risk

    # Confidence
    if fii_signal in ('STRONG_BUY', 'STRONG_SELL'):
        confidence = 'VERY_HIGH'
    elif fii_signal in ('BUY', 'SELL'):
        confidence = 'HIGH'
    else:
        confidence = 'MEDIUM'

    AFTERNOON_ALERTED.add(symbol)

    return {
        'symbol':       symbol,
        'signal':       'AFTERNOON_R3_SHORT' if direction == 'SELL' else 'AFTERNOON_S3_LONG',
        'direction':    direction,
        'entry_price':  ltp,
        'stop_loss':    stop,
        'target':       target,
        'risk_reward':  rr,
        'r3':           r3,
        's3':           s3,
        'pivot':        pivot,
        'rsi':          rsi,
        'vwap':         vwap,
        'klinger':      ko,
        'fii_dii':      fii_signal,
        'confidence':   confidence,
        'timestamp':    now_ist(),
    }


def send_afternoon_pivot_alert(signal, trader=None):
    """Log + optionally trade an afternoon pivot signal."""
    global AFTERNOON_ORDER_COUNT

    s   = signal['symbol']
    sig = signal['signal']
    d   = signal['direction']
    ep  = signal['entry_price']
    sl  = signal['stop_loss']
    tgt = signal['target']
    rr  = signal['risk_reward']
    rsi = signal.get('rsi', 0)
    vwap = signal.get('vwap')
    r3  = signal.get('r3', 0)
    s3  = signal.get('s3', 0)

    print(f"\n{'='*80}")
    print(f"🌆 AFTERNOON PIVOT ALERT: {sig}")
    print(f"{'='*80}")
    print(f"Stock: {s} | Direction: {d} | Time: {now_ist().strftime('%H:%M:%S')}")
    print(f"Entry: ₹{ep:.2f} | Stop: ₹{sl:.2f} | Target: ₹{tgt:.2f} | R:R {rr:.1f}x")
    print(f"R3: ₹{r3:.2f} | S3: ₹{s3:.2f} | RSI: {rsi:.1f}"
          + (f" | VWAP: ₹{vwap:.2f}" if vwap else ""))
    print(f"FII/DII: {signal.get('fii_dii')} | Confidence: {signal.get('confidence')}")
    print(f"{'='*80}")

    # CSV log
    try:
        import csv as _csv
        file_exists = os.path.exists(AFTERNOON_PIVOT_LOG_FILE)
        with open(AFTERNOON_PIVOT_LOG_FILE, 'a', newline='', encoding='utf-8') as f:
            w = _csv.writer(f)
            if not file_exists:
                w.writerow(['Timestamp','Symbol','Signal','Direction','Entry',
                            'Stop','Target','RR','RSI','VWAP','R3','S3',
                            'FII_DII','Confidence'])
            w.writerow([now_ist().strftime('%Y-%m-%d %H:%M:%S'),
                        s, sig, d, ep, sl, tgt, f"{rr:.2f}",
                        f"{rsi:.1f}", f"{vwap:.2f}" if vwap else '',
                        f"{r3:.2f}", f"{s3:.2f}",
                        signal.get('fii_dii'), signal.get('confidence')])
    except Exception as e:
        if DEBUG_MODE:
            print(f"⚠️ Afternoon pivot CSV log error: {e}")

    # Place order (CE for LONG, PE for SELL)
    if trader and is_order_time_allowed():
        try:
            option_type = 'CE' if d == 'BUY' else 'PE'
            order_result = place_option_order(
                trader, s, ep, option_type,
                strategy_tag='AFTERNOON_PIVOT',
                signal_confidence=signal.get('confidence', 'HIGH')
            )
            if order_result:
                AFTERNOON_ORDER_COUNT += 1
        except Exception as e:
            print(f"⚠️ Afternoon pivot order error for {s}: {e}")


def send_midday_box_alert(signal, trader=None):
    """Log + optionally trade a midday box breakout signal."""
    global MIDDAY_BOX_ORDER_COUNT

    s  = signal['symbol']
    d  = signal['direction']
    ep = signal['entry_price']
    sl = signal['stop_loss']
    tgt = signal['target']
    br = signal['box_range_pct']

    print(f"\n{'='*80}")
    print(f"📦 MIDDAY BOX BREAKOUT: {s} — {d}")
    print(f"{'='*80}")
    print(f"Entry: ₹{ep:.2f} | Stop: ₹{sl:.2f} | Target: ₹{tgt:.2f}")
    print(f"Box: ₹{signal['box_low']:.2f}–₹{signal['box_high']:.2f} "
          f"({br:.2f}% range) | Vol: {signal['volume_ratio']:.2f}x | FII/DII: {signal['fii_dii']}")
    print(f"{'='*80}")

    try:
        import csv as _csv
        file_exists = os.path.exists(MIDDAY_BOX_LOG_FILE)
        with open(MIDDAY_BOX_LOG_FILE, 'a', newline='', encoding='utf-8') as f:
            w = _csv.writer(f)
            if not file_exists:
                w.writerow(['Timestamp','Symbol','Direction','Entry','Stop','Target',
                            'BoxHigh','BoxLow','RangePct','VolRatio','FII_DII'])
            w.writerow([now_ist().strftime('%Y-%m-%d %H:%M:%S'),
                        s, d, ep, sl, tgt,
                        f"{signal['box_high']:.2f}", f"{signal['box_low']:.2f}",
                        f"{br:.2f}", f"{signal['volume_ratio']:.2f}", signal['fii_dii']])
    except Exception as e:
        if DEBUG_MODE:
            print(f"⚠️ Midday box CSV log error: {e}")

    if trader and is_order_time_allowed():
        try:
            option_type = 'CE' if d == 'BUY' else 'PE'
            order_result = place_option_order(
                trader, s, ep, option_type,
                strategy_tag='MIDDAY_BOX',
                signal_confidence='HIGH'
            )
            if order_result:
                MIDDAY_BOX_ORDER_COUNT += 1
        except Exception as e:
            print(f"⚠️ Midday box order error for {s}: {e}")


# ══════════════════════════════════════════════════════════════════════════════
#  THREE NEW REVERSAL STRATEGIES
#  S1. Resistance Reversal    — opening spike to 2-wk high → red rejection
#  S2. Dual-TF BB Middle Cross — 5-min AND 1-hr cross simultaneously
#  S3. FII/DII Multi-Confluence Breakout — weekly high + 2-candle confirm + vol
# ══════════════════════════════════════════════════════════════════════════════

def _get_historical_high_low(access_token, ikey, symbol, lookback_days=14):
    """Return (highest_high, lowest_low) over last `lookback_days` DAILY candles.

    Uses the cached 5-min bars resampled to daily as a fallback if a dedicated
    daily endpoint isn't available.  Returns (None, None) on failure.
    """
    try:
        df5 = fetch_5min_cached(access_token, ikey, bars=lookback_days * 78 + 80,
                                symbol=symbol)
        if df5 is None or len(df5) < 20:
            return None, None
        import pandas as pd
        df = df5.copy()
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df = df.set_index('timestamp')
        daily = df[['high', 'low', 'close', 'volume']].resample('D').agg(
            {'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}
        ).dropna()
        # Exclude today — we want the PREVIOUS resistance, not today's live action
        today = now_ist().date()
        daily = daily[daily.index.date < today]
        if len(daily) < 2:
            return None, None
        window = daily.tail(lookback_days)
        return float(window['high'].max()), float(window['low'].min())
    except Exception as e:
        if DEBUG_MODE:
            print(f"⛔ _get_historical_high_low {symbol}: {e}")
        return None, None


def _get_weekly_high_low_body(access_token, ikey, symbol, lookback_days=14):
    """Return (weekly_high_body, weekly_low_body) using candle CLOSE prices
    (no wick) over the lookback window.  This is the 'weekly high without wick'
    level that serves as the key resistance/support for the breakout strategy.
    """
    try:
        df5 = fetch_5min_cached(access_token, ikey, bars=lookback_days * 78 + 80,
                                symbol=symbol)
        if df5 is None or len(df5) < 20:
            return None, None
        import pandas as pd
        df = df5.copy()
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df = df.set_index('timestamp')
        weekly = df[['open', 'high', 'low', 'close']].resample('W').agg(
            {'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'}
        ).dropna()
        today = now_ist().date()
        # Exclude the current (incomplete) week
        weekly = weekly[weekly.index.date < today]
        if len(weekly) < 1:
            return None, None
        window = weekly.tail(max(1, lookback_days // 7))
        # "Without wick" = body high = max(open, close) per week
        body_highs = window[['open', 'close']].max(axis=1)
        body_lows  = window[['open', 'close']].min(axis=1)
        return float(body_highs.max()), float(body_lows.min())
    except Exception as e:
        if DEBUG_MODE:
            print(f"⛔ _get_weekly_high_low_body {symbol}: {e}")
        return None, None


def _candle_body_pct(candle) -> float:
    """Return candle body size as % of open price.  Safe against zero open."""
    o = candle.get('open', 0) if isinstance(candle, dict) else getattr(candle, 'open', 0)
    c = candle.get('close', 0) if isinstance(candle, dict) else getattr(candle, 'close', 0)
    if not o:
        return 0.0
    return abs(c - o) / o * 100


# ── Strategy 1: Big Opening Candle + Resistance Reversal ──────────────────────

def detect_resistance_reversal(access_token, live_data):
    """Opening-candle spike to 2-week resistance → 15-min red rejection → PE.
    Mirror for support → CE (LONG).

    Entry gates (SHORT/PE):
      1. Opening 15-min candle body ≥ RES_REVERSAL_BODY_MIN_PCT (big spike up)
      2. High of opening candle within RES_REVERSAL_BAND_PCT % of 2-week high
      3. Next completed 15-min candle: red body + high < opening candle high (failure)
      4. Volume on rejection candle ≥ RES_REVERSAL_VOLUME_MIN × 20-bar avg
      5. RSI ≤ RES_REVERSAL_RSI_OVERBOUGHT (not already deeply extended)
      6. Noise gate: rejection candle body ≥ RES_REVERSAL_NOISE_MIN_BODY_PCT

    Mirror conditions for LONG/CE (spike down to 2-week support → green rejection).
    """
    global RES_REVERSAL_ALERTED
    if not ENABLE_RESISTANCE_REVERSAL:
        return []

    signals = []

    for ikey, live in live_data.items():
        symbol = ISIN_TO_SYMBOL.get(ikey, ikey)
        if symbol in RES_REVERSAL_ALERTED:
            continue
        if ikey not in R3_LEVELS:
            continue

        try:
            ltp = live.get('ltp', 0)
            if not ltp:
                continue

            df5 = fetch_5min_cached(access_token, ikey, bars=120, symbol=symbol)
            if df5 is None or len(df5) < 25:
                continue

            # Resample to 15-min
            import pandas as pd
            df = df5.copy()
            if 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'])
                df = df.set_index('timestamp')
            df15 = df[['open', 'high', 'low', 'close', 'volume']].resample('15min').agg(
                {'open': 'first', 'high': 'max', 'low': 'min',
                 'close': 'last', 'volume': 'sum'}
            ).dropna().reset_index()
            if len(df15) < 4:
                continue

            open_c  = df15.iloc[-3]   # opening 15-min candle (3rd from end = 2 complete + current)
            next_c  = df15.iloc[-2]   # next completed 15-min candle
            # (df15.iloc[-1] is the still-building current candle — ignore)

            open_body  = abs(open_c['close'] - open_c['open'])
            open_body_pct = open_body / open_c['open'] * 100 if open_c['open'] else 0

            # ── Noise gate: opening candle must be a BIG candle ──────────────
            if open_body_pct < RES_REVERSAL_BODY_MIN_PCT:
                continue

            info      = R3_LEVELS[ikey]
            avg_vol   = df5['volume'].tail(20).mean() or 1
            vol_ratio = next_c['volume'] / avg_vol

            res_high, sup_low = _get_historical_high_low(
                access_token, ikey, symbol,
                lookback_days=RES_REVERSAL_LOOKBACK_DAYS
            )
            if res_high is None:
                continue

            rsi = calculate_rsi(df5.tail(20))

            # ── SHORT setup ──────────────────────────────────────────────────
            near_res  = res_high * (1 - RES_REVERSAL_BAND_PCT / 100)
            next_red  = next_c['close'] < next_c['open']
            no_break  = next_c['high'] < open_c['high']
            noise_ok  = abs(next_c['close'] - next_c['open']) / next_c['open'] * 100 >= RES_REVERSAL_NOISE_MIN_BODY_PCT if next_c['open'] else False
            open_near_res = open_c['high'] >= near_res
            rsi_ok    = rsi is None or rsi <= RES_REVERSAL_RSI_OVERBOUGHT

            if open_near_res and next_red and no_break and noise_ok and rsi_ok \
               and vol_ratio >= RES_REVERSAL_VOLUME_MIN:
                stop   = open_c['high'] * 1.003
                risk   = stop - ltp
                target = ltp - 2.0 * risk if risk > 0 else ltp * 0.985
                RES_REVERSAL_ALERTED.add(symbol)
                signals.append({
                    'symbol': symbol, 'ikey': ikey,
                    'signal': 'RES_REVERSAL_SHORT', 'direction': 'PE',
                    'entry': ltp, 'stop': stop, 'target': target,
                    'resistance': res_high, 'open_high': open_c['high'],
                    'open_body_pct': round(open_body_pct, 2),
                    'vol_ratio': round(vol_ratio, 2), 'rsi': rsi,
                    'timestamp': now_ist(),
                })
                if DEBUG_MODE:
                    print(f"🔴 RES_REVERSAL_SHORT: {symbol} | near ₹{res_high:.2f} | vol {vol_ratio:.2f}x")
                continue

            # ── LONG setup (mirror) ──────────────────────────────────────────
            if sup_low is None:
                continue
            near_sup  = sup_low * (1 + RES_REVERSAL_BAND_PCT / 100)
            next_green = next_c['close'] > next_c['open']
            no_break_dn = next_c['low'] > open_c['low']
            noise_ok_l  = abs(next_c['close'] - next_c['open']) / next_c['open'] * 100 >= RES_REVERSAL_NOISE_MIN_BODY_PCT if next_c['open'] else False
            open_near_sup = open_c['low'] <= near_sup
            rsi_ok_l  = rsi is None or rsi >= (100 - RES_REVERSAL_RSI_OVERBOUGHT)

            if open_near_sup and next_green and no_break_dn and noise_ok_l and rsi_ok_l \
               and vol_ratio >= RES_REVERSAL_VOLUME_MIN:
                stop   = open_c['low'] * 0.997
                risk   = ltp - stop
                target = ltp + 2.0 * risk if risk > 0 else ltp * 1.015
                RES_REVERSAL_ALERTED.add(symbol)
                signals.append({
                    'symbol': symbol, 'ikey': ikey,
                    'signal': 'RES_REVERSAL_LONG', 'direction': 'CE',
                    'entry': ltp, 'stop': stop, 'target': target,
                    'support': sup_low, 'open_low': open_c['low'],
                    'open_body_pct': round(open_body_pct, 2),
                    'vol_ratio': round(vol_ratio, 2), 'rsi': rsi,
                    'timestamp': now_ist(),
                })
                if DEBUG_MODE:
                    print(f"🟢 RES_REVERSAL_LONG: {symbol} | near ₹{sup_low:.2f} | vol {vol_ratio:.2f}x")

        except Exception as e:
            if DEBUG_MODE:
                print(f"⛔ detect_resistance_reversal [{symbol}]: {e}")

    return signals


# ── Strategy 2: Dual-TF Bollinger Band Middle Cross ───────────────────────────

def detect_dual_tf_bb_cross(access_token, live_data):
    """Close above/below BB middle on BOTH 5-min AND 1-hr simultaneously → CE/PE.

    Entry gates:
      1. 5-min: last COMPLETED candle crosses BB(20) middle from below (CE) / above (PE)
         i.e. prev_close was below/above middle, last_close is above/below
      2. 1-hr: same cross confirmed on the last completed 1-hr bar
      3. Volume spike on 5-min cross candle ≥ DUAL_TF_BB_VOLUME_MIN × 20-bar avg
      4. Band squeeze detected in the preceding DUAL_TF_BB_SQUEEZE_LOOKBACK bars
         on the 5-min (tight bands = coiled energy → higher probability on break)
      5. FII/DII alignment preferred (not mandatory — signal printed regardless,
         but confidence label reflects alignment)
      6. Noise gate: crossing candle body ≥ DUAL_TF_BB_NOISE_MIN_BODY_PCT
    """
    global DUAL_TF_BB_ALERTED
    if not ENABLE_DUAL_TF_BB:
        return []

    signals = []

    for ikey, live in live_data.items():
        symbol = ISIN_TO_SYMBOL.get(ikey, ikey)
        if symbol in DUAL_TF_BB_ALERTED:
            continue
        if ikey not in R3_LEVELS:
            continue

        try:
            ltp = live.get('ltp', 0)
            if not ltp:
                continue

            df5 = fetch_5min_cached(access_token, ikey, bars=120, symbol=symbol)
            if df5 is None or len(df5) < DUAL_TF_BB_PERIOD + 5:
                continue

            # ── 5-min BB ────────────────────────────────────────────────────
            up5, mid5, lo5, width5, _ = calculate_bollinger_bands(
                df5, period=DUAL_TF_BB_PERIOD)
            if mid5 is None:
                continue

            prev5  = df5.iloc[-3]   # last completed candle - 1
            last5  = df5.iloc[-2]   # last completed candle

            cross_up5   = prev5['close'] < mid5.iloc[-3] and last5['close'] > mid5.iloc[-2]
            cross_down5 = prev5['close'] > mid5.iloc[-3] and last5['close'] < mid5.iloc[-2]
            if not cross_up5 and not cross_down5:
                continue

            # Noise gate
            body5_pct = abs(last5['close'] - last5['open']) / last5['open'] * 100 if last5['open'] else 0
            if body5_pct < DUAL_TF_BB_NOISE_MIN_BODY_PCT:
                if DEBUG_MODE:
                    print(f"⛔ dual_tf_bb {symbol}: 5-min body too small ({body5_pct:.2f}%)")
                continue

            # Volume
            avg_vol5   = df5['volume'].tail(20).mean() or 1
            vol_ratio5 = last5['volume'] / avg_vol5
            if vol_ratio5 < DUAL_TF_BB_VOLUME_MIN:
                if DEBUG_MODE:
                    print(f"⛔ dual_tf_bb {symbol}: vol {vol_ratio5:.2f}x < {DUAL_TF_BB_VOLUME_MIN}")
                continue

            # Squeeze check
            squeeze = detect_bollinger_squeeze(
                width5, threshold=0.15,
                lookback=DUAL_TF_BB_SQUEEZE_LOOKBACK
            )

            # ── 1-hr BB (resample) ───────────────────────────────────────────
            df1h = resample_to_1h(df5)
            if df1h is None or len(df1h) < DUAL_TF_BB_PERIOD + 2:
                if DEBUG_MODE:
                    print(f"⛔ dual_tf_bb {symbol}: insufficient 1H bars")
                continue

            up1h, mid1h, lo1h, _, _ = calculate_bollinger_bands(
                df1h, period=DUAL_TF_BB_PERIOD)
            if mid1h is None:
                continue

            prev1h = df1h.iloc[-3]
            last1h = df1h.iloc[-2]

            cross_up1h   = prev1h['close'] < mid1h.iloc[-3] and last1h['close'] > mid1h.iloc[-2]
            cross_down1h = prev1h['close'] > mid1h.iloc[-3] and last1h['close'] < mid1h.iloc[-2]

            # Both TFs must agree
            if cross_up5 and not cross_up1h:
                if DEBUG_MODE:
                    print(f"⛔ dual_tf_bb {symbol}: 5m BULL cross but 1H not confirmed")
                continue
            if cross_down5 and not cross_down1h:
                if DEBUG_MODE:
                    print(f"⛔ dual_tf_bb {symbol}: 5m BEAR cross but 1H not confirmed")
                continue

            # FII/DII alignment (confidence tier)
            fii_sig    = get_fii_dii_signal(symbol)
            direction  = 'CE' if cross_up5 else 'PE'
            fii_aligned = (direction == 'CE' and fii_sig in ('STRONG_BUY', 'BUY')) or \
                          (direction == 'PE' and fii_sig in ('STRONG_SELL', 'SELL'))
            confidence = ('VERY_HIGH' if fii_aligned and squeeze else
                          'HIGH'      if fii_aligned or squeeze else
                          'MEDIUM')

            # Build signal
            if direction == 'CE':
                stop   = float(lo5.iloc[-2]) * 0.997
                risk   = ltp - stop
                target = ltp + 2.0 * risk if risk > 0 else ltp * 1.015
            else:
                stop   = float(up5.iloc[-2]) * 1.003
                risk   = stop - ltp
                target = ltp - 2.0 * risk if risk > 0 else ltp * 0.985

            DUAL_TF_BB_ALERTED.add(symbol)
            signals.append({
                'symbol': symbol, 'ikey': ikey,
                'signal': f'DUAL_TF_BB_{"BULL" if cross_up5 else "BEAR"}',
                'direction': direction,
                'entry': ltp, 'stop': stop, 'target': target,
                'mid5': float(mid5.iloc[-2]), 'mid1h': float(mid1h.iloc[-2]),
                'vol_ratio': round(vol_ratio5, 2),
                'squeeze': squeeze, 'fii_dii': fii_sig,
                'confidence': confidence, 'timestamp': now_ist(),
            })
            icon = '🟢' if direction == 'CE' else '🔴'
            if DEBUG_MODE:
                print(f"{icon} DUAL_TF_BB {direction}: {symbol} | "
                      f"vol {vol_ratio5:.2f}x | squeeze={squeeze} | FII={fii_sig}")

        except Exception as e:
            if DEBUG_MODE:
                print(f"⛔ detect_dual_tf_bb_cross [{symbol}]: {e}")

    return signals


# ── Strategy 3: FII/DII Multi-Confluence Breakout ─────────────────────────────

def detect_fiidii_confluence_breakout(access_token, live_data, mode='fii'):
    """Multi-confluence breakout for FII/DII stocks (and general pool).

    Mode 'general' (Mode A — all F&O symbols):
      • First 1-hr candle high WITH wick as resistance
      • Next 5-min or 15-min candle breaks and CLOSES above it
      • Last 1-week weekly high WITHOUT wick (body close) also broken
      • 2-candle confirmation: PREVIOUS close + NEW close both above level
      • Volume spike ≥ FIIDII_BRK_VOLUME_MIN × 20-bar average
      Mirror for SHORT: first 1H low, weekly low, 2 closes below.

    Mode 'fii' (Mode B — FII/DII watchlist, 2-week lookback):
      All of Mode A PLUS:
      • 1-hr candle crosses BB(20) middle (price moving into trend)
      • FII/DII must be net BUYING (for CE) or net SELLING (for PE)
      • Lookback extended to 14 days
      • Noise gate: candle body ≥ FIIDII_BRK_NOISE_MIN_BODY_PCT

    Mode 'fii_v2' (Mode C — rolling BB-cross + strong-close variant):
      Same FII/DII pool + weekly-high filter + volume spike as Mode B, but:
      • Breakout reference = ROLLING previous 1-hr candle (not fixed to the
        day's first 1H bar) — fires at any point in the day, not just once
        off the opening range.
      • The BB-cross candle itself must CLOSE STRONG in the trade direction
        (green for CE, red for PE) — quality filter on the arming candle,
        not required in Mode B.
      • 2-candle confirmation still required (stricter than the 1-candle
        break originally requested — kept as the noise filter).

    'If price reverses with small candles or small price changes → ignore
    and continue waiting.' — implemented via the noise gate and 2-candle confirm.
    """
    global FIIDII_BRK_ALERTED
    if not ENABLE_FIIDII_BREAKOUT:
        return []

    lookback  = FIIDII_BRK_LOOKBACK_DAYS_FII if mode in ('fii', 'fii_v2') else FIIDII_BRK_LOOKBACK_DAYS_GEN
    pool_keys = list(R3_LEVELS.keys())
    if mode in ('fii', 'fii_v2'):
        fii_symbols = FII_DII_STRONG_BUY | FII_DII_STRONG_SELL
        pool_keys   = [k for k in pool_keys
                       if R3_LEVELS[k].get('symbol') in fii_symbols]

    signals = []

    for ikey in pool_keys:
        info   = R3_LEVELS.get(ikey, {})
        symbol = info.get('symbol', ikey)
        tag    = (symbol, mode)
        if tag in FIIDII_BRK_ALERTED:
            continue

        live   = live_data.get(ikey, {})
        ltp    = live.get('ltp', 0)
        if not ltp:
            continue

        try:
            df5 = fetch_5min_cached(access_token, ikey, bars=lookback * 78 + 80,
                                    symbol=symbol)
            if df5 is None or len(df5) < 30:
                continue

            import pandas as pd

            # ── First 1-hr candle high (with wick) ──────────────────────────
            df = df5.copy()
            if 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'])
                df = df.set_index('timestamp')
            df1h = df[['open', 'high', 'low', 'close', 'volume']].resample('1h').agg(
                {'open': 'first', 'high': 'max', 'low': 'min',
                 'close': 'last', 'volume': 'sum'}
            ).dropna().reset_index()
            if len(df1h) < 3:
                continue

            first_1h_high = float(df1h.iloc[0]['high'])   # today's first 1-hr bar
            first_1h_low  = float(df1h.iloc[0]['low'])
            last_1h       = df1h.iloc[-2]   # last completed 1-hr bar

            # ── fii_v2: rolling previous-1H-candle anchor (not day's first bar) ──
            # Mode B anchors to the day's opening range; Mode C anchors to
            # whichever 1H candle most recently crossed the BB middle, so it
            # can fire at any point in the session, not just once at the open.
            rolling_1h_high = float(df1h.iloc[-3]['high']) if len(df1h) >= 3 else first_1h_high
            rolling_1h_low  = float(df1h.iloc[-3]['low'])  if len(df1h) >= 3 else first_1h_low

            anchor_high = rolling_1h_high if mode == 'fii_v2' else first_1h_high
            anchor_low  = rolling_1h_low  if mode == 'fii_v2' else first_1h_low

            # ── Weekly high/low WITHOUT wick (body only) ─────────────────────
            weekly_res, weekly_sup = _get_weekly_high_low_body(
                access_token, ikey, symbol, lookback_days=lookback)
            if weekly_res is None:
                continue

            # ── 5-min 2-candle confirmation ──────────────────────────────────
            prev5 = df5.iloc[-3]   # second-to-last completed 5-min bar
            last5 = df5.iloc[-2]   # last completed 5-min bar

            avg_vol   = df5['volume'].tail(20).mean() or 1
            vol_ratio = last5['volume'] / avg_vol

            # Noise gate: ignore tiny candles
            body5 = abs(last5['close'] - last5['open']) / last5['open'] * 100 if last5['open'] else 0
            if body5 < FIIDII_BRK_NOISE_MIN_BODY_PCT:
                if DEBUG_MODE:
                    print(f"⛔ fiidii_brk {symbol}({mode}): candle body too small {body5:.2f}%")
                continue

            # Volume
            if vol_ratio < FIIDII_BRK_VOLUME_MIN:
                if DEBUG_MODE:
                    print(f"⛔ fiidii_brk {symbol}({mode}): vol {vol_ratio:.2f}x < {FIIDII_BRK_VOLUME_MIN}")
                continue

            fii_sig = get_fii_dii_signal(symbol)

            # ── Mode B/C: BB middle cross on 1H ──────────────────────────────
            bb_ok_bull = True
            bb_ok_bear = True
            strong_close_bull = True   # only enforced for fii_v2
            strong_close_bear = True
            if mode in ('fii', 'fii_v2'):
                _, mid1h_s, _, _, _ = calculate_bollinger_bands(df1h, period=20)
                if mid1h_s is not None and len(df1h) >= 22:
                    prev_1h = df1h.iloc[-3]
                    last_1h_row = df1h.iloc[-2]
                    bb_ok_bull = (prev_1h['close'] < float(mid1h_s.iloc[-3]) and
                                  last_1h_row['close'] > float(mid1h_s.iloc[-2]))
                    bb_ok_bear = (prev_1h['close'] > float(mid1h_s.iloc[-3]) and
                                  last_1h_row['close'] < float(mid1h_s.iloc[-2]))

                    if mode == 'fii_v2':
                        # The BB-cross candle itself must close strong in the
                        # trade direction — quality filter not present in Mode B.
                        strong_close_bull = last_1h_row['close'] > last_1h_row['open']
                        strong_close_bear = last_1h_row['close'] < last_1h_row['open']

            # ── LONG (CE): break above anchor-high AND weekly-body-high ──────
            # "Previous candle AND new candle break" = 2-candle close confirmation
            long_level = max(anchor_high, weekly_res)
            two_close_bull = (prev5['close'] > long_level and
                              last5['close'] > long_level)
            fii_bull_ok = mode not in ('fii', 'fii_v2') or fii_sig in ('STRONG_BUY', 'BUY')

            if two_close_bull and bb_ok_bull and strong_close_bull and fii_bull_ok:
                stop   = anchor_low * 0.997
                risk   = ltp - stop
                target = ltp + 2.5 * risk if risk > 0 else ltp * 1.02
                confidence = ('VERY_HIGH' if fii_sig in ('STRONG_BUY',) else 'HIGH')
                FIIDII_BRK_ALERTED.add(tag)
                signals.append({
                    'symbol': symbol, 'ikey': ikey, 'mode': mode,
                    'signal': f'FIIDII_BRK_LONG_{mode.upper()}',
                    'direction': 'CE',
                    'entry': ltp, 'stop': stop, 'target': target,
                    'level': long_level,
                    'anchor_high': anchor_high, 'weekly_res': weekly_res,
                    'vol_ratio': round(vol_ratio, 2),
                    'fii_dii': fii_sig, 'confidence': confidence,
                    'timestamp': now_ist(),
                })
                if DEBUG_MODE:
                    print(f"🟢 FIIDII_BRK CE [{mode}]: {symbol} | level ₹{long_level:.2f} | vol {vol_ratio:.2f}x")
                continue

            # ── SHORT (PE): break below anchor-low AND weekly-body-low ───────
            short_level = min(anchor_low, weekly_sup)
            two_close_bear = (prev5['close'] < short_level and
                              last5['close'] < short_level)
            fii_bear_ok = mode not in ('fii', 'fii_v2') or fii_sig in ('STRONG_SELL', 'SELL')

            if two_close_bear and bb_ok_bear and strong_close_bear and fii_bear_ok:
                stop   = anchor_high * 1.003
                risk   = stop - ltp
                target = ltp - 2.5 * risk if risk > 0 else ltp * 0.98
                confidence = ('VERY_HIGH' if fii_sig in ('STRONG_SELL',) else 'HIGH')
                FIIDII_BRK_ALERTED.add(tag)
                signals.append({
                    'symbol': symbol, 'ikey': ikey, 'mode': mode,
                    'signal': f'FIIDII_BRK_SHORT_{mode.upper()}',
                    'direction': 'PE',
                    'entry': ltp, 'stop': stop, 'target': target,
                    'level': short_level,
                    'anchor_low': anchor_low, 'weekly_sup': weekly_sup,
                    'vol_ratio': round(vol_ratio, 2),
                    'fii_dii': fii_sig, 'confidence': confidence,
                    'timestamp': now_ist(),
                })
                if DEBUG_MODE:
                    print(f"🔴 FIIDII_BRK PE [{mode}]: {symbol} | level ₹{short_level:.2f} | vol {vol_ratio:.2f}x")

        except Exception as e:
            if DEBUG_MODE:
                print(f"⛔ detect_fiidii_confluence_breakout [{symbol}][{mode}]: {e}")

    return signals


def _log_and_place_new_reversal(signal, trader, csv_file, strategy_name):
    """Unified logger + order placer for all three new reversal strategies."""
    s   = signal['symbol']
    d   = signal['direction']
    ep  = signal['entry']
    sl  = signal['stop']
    tgt = signal['target']
    rr  = abs(tgt - ep) / abs(ep - sl) if abs(ep - sl) > 0 else 0

    icon = '🟢' if d == 'CE' else '🔴'
    print(f"\n{'='*80}")
    print(f"{icon} {strategy_name}: {signal['signal']}")
    print(f"{'='*80}")
    print(f"Stock: {s} | Direction: {d} | Time: {now_ist().strftime('%H:%M:%S')}")
    print(f"Entry: ₹{ep:.2f} | Stop: ₹{sl:.2f} | Target: ₹{tgt:.2f} | R:R {rr:.1f}x")
    extras = {k: v for k, v in signal.items()
              if k not in ('symbol','ikey','signal','direction','entry',
                           'stop','target','timestamp','mode')}
    for k, v in extras.items():
        if isinstance(v, float):
            print(f"  {k}: ₹{v:.2f}" if 'price' in k.lower() or 'level' in k.lower() or 'res' in k.lower() or 'sup' in k.lower() else f"  {k}: {v:.2f}")
        else:
            print(f"  {k}: {v}")
    print(f"{'='*80}")

    # CSV log
    try:
        import csv as _csv
        fe = os.path.exists(csv_file)
        with open(csv_file, 'a', newline='', encoding='utf-8') as f:
            w = _csv.writer(f)
            if not fe:
                w.writerow(['Timestamp', 'Symbol', 'Signal', 'Direction',
                            'Entry', 'Stop', 'Target', 'RR',
                            'VolRatio', 'Confidence', 'FII_DII'])
            w.writerow([
                now_ist().strftime('%Y-%m-%d %H:%M:%S'),
                s, signal['signal'], d,
                f'{ep:.2f}', f'{sl:.2f}', f'{tgt:.2f}', f'{rr:.2f}',
                signal.get('vol_ratio', ''),
                signal.get('confidence', ''),
                signal.get('fii_dii', ''),
            ])
    except Exception as e:
        if DEBUG_MODE:
            print(f"⚠️ CSV log error ({csv_file}): {e}")

    # Place order
    if trader and is_order_time_allowed():
        try:
            place_breakout_order(signal, trader)
        except Exception as e:
            print(f"⚠️ Order error for {s}: {e}")


# ── Strategy 4: FII/DII BB-Mid Cross + Live Continuation ──────────────────────

def scan_fii_bb_continuation(access_token, live_data):
    """Continuous FII/DII watchlist monitor: 1H BB-middle cross → arm →
    live intra-candle break of the armed candle's high/low → immediate entry.

    Unlike detect_fiidii_confluence_breakout (mode='fii'), this is a single,
    lightweight trigger with no weekly-high requirement and no 2-candle
    confirmation — designed to fire fast right after the BB cross.

    State (FII_BB_ARMED) persists across days: a stock arms today, may not
    break until tomorrow or the day after — matches the '2-3 days continuous
    monitoring' requirement. Un-arms automatically after FII_BB_ARM_MAX_HOURS
    of market time if the break never happens.

    Because entry is triggered on live LTP mid-candle, there is no "green
    candle" confirmation possible — the buffer (FII_BB_ARM_BUFFER_PCT) is the
    substitute noise filter, requiring price to clear the level meaningfully
    rather than just touch it.
    """
    global FII_BB_ARMED, FII_BB_ALERTED_TODAY

    if not ENABLE_FII_BB_CONTINUATION:
        return []

    signals = []
    fii_symbols = FII_DII_STRONG_BUY | FII_DII_STRONG_SELL
    pool_keys = [k for k in R3_LEVELS.keys()
                 if R3_LEVELS[k].get('symbol') in fii_symbols]

    now = now_ist()

    for ikey in pool_keys:
        info   = R3_LEVELS.get(ikey, {})
        symbol = info.get('symbol', ikey)
        live   = live_data.get(ikey, {})
        ltp    = live.get('ltp', 0)
        if not ltp:
            continue

        try:
            # ── Step 1: if armed, check for un-arm timeout first ────────────
            armed = FII_BB_ARMED.get(symbol)
            if armed:
                hours_armed = (now - armed['armed_at']).total_seconds() / 3600
                if hours_armed > FII_BB_ARM_MAX_HOURS:
                    del FII_BB_ARMED[symbol]
                    armed = None
                    if DEBUG_MODE:
                        print(f"⏱ FII_BB un-armed (timeout): {symbol}")

            # ── Step 2: if not armed, check for a fresh BB-middle cross ─────
            if not armed and symbol not in FII_BB_ALERTED_TODAY:
                df5 = fetch_5min_cached(access_token, ikey, bars=200, symbol=symbol)
                if df5 is None or len(df5) < 30:
                    continue

                df1h = resample_to_1h(df5)
                if df1h is None or len(df1h) < 22:
                    continue

                _, mid1h, _, _, _ = calculate_bollinger_bands(df1h, period=20)
                if mid1h is None:
                    continue

                prev1h = df1h.iloc[-3]   # candle before the cross candle
                last1h = df1h.iloc[-2]   # last COMPLETED 1H candle

                body_pct = abs(last1h['close'] - last1h['open']) / last1h['open'] * 100 \
                           if last1h['open'] else 0
                if body_pct < FII_BB_NOISE_MIN_BODY_PCT:
                    continue   # indecisive cross candle, skip arming

                cross_up   = prev1h['close'] < float(mid1h.iloc[-3]) and \
                             last1h['close'] > float(mid1h.iloc[-2])
                cross_down = prev1h['close'] > float(mid1h.iloc[-3]) and \
                             last1h['close'] < float(mid1h.iloc[-2])

                if cross_up:
                    FII_BB_ARMED[symbol] = {
                        'direction':  'CE',
                        'armed_high': float(last1h['high']),
                        'armed_low':  float(last1h['low']),
                        'armed_at':   now,
                        'ikey':       ikey,
                    }
                    if DEBUG_MODE:
                        print(f"🔫 FII_BB armed CE: {symbol} @ high ₹{last1h['high']:.2f}")
                elif cross_down:
                    FII_BB_ARMED[symbol] = {
                        'direction':  'PE',
                        'armed_high': float(last1h['high']),
                        'armed_low':  float(last1h['low']),
                        'armed_at':   now,
                        'ikey':       ikey,
                    }
                    if DEBUG_MODE:
                        print(f"🔫 FII_BB armed PE: {symbol} @ low ₹{last1h['low']:.2f}")
                continue   # armed this scan — wait for a later scan to check break

            # ── Step 3: if armed, check live LTP break (immediate, no wait) ──
            if armed:
                direction = armed['direction']

                if direction == 'CE':
                    trigger = armed['armed_high'] * (1 + FII_BB_ARM_BUFFER_PCT / 100)
                    if ltp > trigger:
                        stop   = armed['armed_low'] * 0.998
                        risk   = ltp - stop
                        target = ltp + 2.0 * risk if risk > 0 else ltp * 1.015
                        fii_sig = get_fii_dii_signal(symbol)
                        FII_BB_ALERTED_TODAY.add(symbol)
                        del FII_BB_ARMED[symbol]
                        signals.append({
                            'symbol': symbol, 'ikey': ikey,
                            'signal': 'FII_BB_CONTINUATION_CE', 'direction': 'CE',
                            'entry': ltp, 'stop': stop, 'target': target,
                            'armed_high': armed['armed_high'],
                            'fii_dii': fii_sig,
                            'confidence': 'HIGH' if fii_sig in ('STRONG_BUY','BUY') else 'MEDIUM',
                            'timestamp': now,
                        })
                        if DEBUG_MODE:
                            print(f"🟢 FII_BB_CONTINUATION CE: {symbol} broke ₹{armed['armed_high']:.2f} live @ ₹{ltp:.2f}")

                else:  # PE
                    trigger = armed['armed_low'] * (1 - FII_BB_ARM_BUFFER_PCT / 100)
                    if ltp < trigger:
                        stop   = armed['armed_high'] * 1.002
                        risk   = stop - ltp
                        target = ltp - 2.0 * risk if risk > 0 else ltp * 0.985
                        fii_sig = get_fii_dii_signal(symbol)
                        FII_BB_ALERTED_TODAY.add(symbol)
                        del FII_BB_ARMED[symbol]
                        signals.append({
                            'symbol': symbol, 'ikey': ikey,
                            'signal': 'FII_BB_CONTINUATION_PE', 'direction': 'PE',
                            'entry': ltp, 'stop': stop, 'target': target,
                            'armed_low': armed['armed_low'],
                            'fii_dii': fii_sig,
                            'confidence': 'HIGH' if fii_sig in ('STRONG_SELL','SELL') else 'MEDIUM',
                            'timestamp': now,
                        })
                        if DEBUG_MODE:
                            print(f"🔴 FII_BB_CONTINUATION PE: {symbol} broke ₹{armed['armed_low']:.2f} live @ ₹{ltp:.2f}")

        except Exception as e:
            if DEBUG_MODE:
                print(f"⛔ scan_fii_bb_continuation [{symbol}]: {e}")

    return signals


def monitor_session_phase(live_data, access_token, trader=None):
    """Dispatcher: routes to the correct strategy based on current session phase.

    Phase 1 (09:15–10:30): ORB — handled separately in enhanced_monitor
    Phase 2 (10:30–13:00): Midday Box — build the box and fire breakouts
    Phase 3 (13:00–15:15): Afternoon Pivot — R3/S3 + VWAP + RSI reversals
    """
    ct     = now_ist()
    ct_str = ct.strftime('%H:%M')

    # ── Phase 2: Midday Box ───────────────────────────────────────────────────
    if ENABLE_MIDDAY_BOX and MIDDAY_BOX_BUILD_START <= ct_str < MIDDAY_BOX_BUILD_END:
        update_midday_box_state(live_data)
        if DEBUG_MODE:
            sealed_ct = sum(1 for s in MIDDAY_BOX_STATE.values() if s.get('sealed'))
            print(f"📦 Midday box: tracking {len(MIDDAY_BOX_STATE)} symbols "
                  f"(sealed={sealed_ct})")

    elif ENABLE_MIDDAY_BOX and MIDDAY_BOX_BUILD_END <= ct_str < AFTERNOON_SESSION_START:
        # Seal all open boxes
        for sym_state in MIDDAY_BOX_STATE.values():
            sym_state['sealed'] = True
        # Check for breakouts
        for ikey, data in live_data.items():
            symbol = ISIN_TO_SYMBOL.get(ikey, ikey)
            ltp    = data.get('ltp', 0)
            volume = data.get('volume', 0)
            if ltp > 0:
                sig = check_midday_box_breakout(symbol, ltp, volume, data)
                if sig:
                    send_midday_box_alert(sig, trader)

    # ── Phase 3: Afternoon Pivot ─────────────────────────────────────────────
    elif ENABLE_AFTERNOON_PIVOT and AFTERNOON_SESSION_START <= ct_str <= AFTERNOON_SESSION_END:
        for ikey, data in live_data.items():
            symbol = ISIN_TO_SYMBOL.get(ikey, ikey)
            ltp    = data.get('ltp', 0)
            if ltp <= 0:
                continue
            try:
                sig = check_afternoon_pivot_reversal(
                    symbol, ltp, access_token, ikey, trader)
                if sig:
                    send_afternoon_pivot_alert(sig, trader)
            except Exception as e:
                if DEBUG_MODE:
                    print(f"⚠️ Afternoon pivot error {symbol}: {e}")

def enhanced_monitor(access_token, keys, symbols):
    """Main monitoring loop with all strategies including Klinger, Caching, and Exit Management"""
    print("📡 STARTING REAL-TIME MONITORING WITH INTELLIGENT CACHING...")

    # ── STARTUP ORDER-WINDOW WAIT ─────────────────────────────────────────────
    # Upstox rejects orders with HTTP 423 before 05:30 IST.
    # When TEST_MODE=True and WAIT_FOR_ORDER_WINDOW=True, wait here rather than
    # running scans that generate signals whose orders will all be rejected.
    # Set WAIT_FOR_ORDER_WINDOW=False to scan immediately (signals logged, no orders).
    if WAIT_FOR_ORDER_WINDOW and not is_order_time_allowed():
        now       = now_ist()
        opens_at  = now.replace(hour=5, minute=30, second=0, microsecond=0)
        if now > opens_at:          # already past 05:30 → means we're after midnight
            opens_at = opens_at + timedelta(days=1)
        wait_secs = int((opens_at - now).total_seconds())
        wait_mins = wait_secs // 60
        print(f"\n⏳ ORDER WINDOW WAIT: Upstox API opens at 05:30 IST.")
        print(f"   Current time: {now.strftime('%H:%M:%S')} | Opens in: {wait_mins}m {wait_secs%60}s")
        print(f"   (Set WAIT_FOR_ORDER_WINDOW=False to skip this wait and scan immediately)\n")
        while not is_order_time_allowed():
            remaining = int((opens_at - now_ist()).total_seconds())
            if remaining % 300 == 0 or remaining <= 60:  # print every 5 min + last minute
                print(f"   ⏳ Waiting for 05:30... {remaining//60}m {remaining%60}s remaining",
                      flush=True)
            time.sleep(30)
        print(f"\n✅ Order window open ({now_ist().strftime('%H:%M:%S')}) — starting scans.\n")
    # ─────────────────────────────────────────────────────────────────────────
    print(f"🔥 Klinger Filter: {'ENABLED ✓' if ENABLE_KLINGER_FILTER else 'DISABLED'}")
    if ENABLE_KLINGER_FILTER:
        print(f"   • Box Trading: {'ON' if ENABLE_KLINGER_FOR_BOX else 'OFF'}")
        print(f"   • Range Trading: {'ON' if ENABLE_KLINGER_FOR_RANGE else 'OFF'}")
        print(f"   • Adaptive Mode: {'ON' if ADAPTIVE_KLINGER_LOOKBACK else 'OFF'}")
        if KLINGER_PAPER_MODE:
            print(f"   • ✗ PAPER MODE: Logging only, not filtering")
    print(f"💾 Candle Cache: {'ENABLED ✓' if ENABLE_CANDLE_CACHE else 'DISABLED'}")
    print(f"⚡ Fast Trading: {'ENABLED ✓' if ENABLE_FAST_TRADING else 'DISABLED'}")
    if ENABLE_FAST_TRADING:
        print(f"   • Timeframe: {FAST_TRADE_TIMEFRAME}")
        print(f"   • Max Symbols: {FAST_TRADE_MAX_SYMBOLS}")
    print(f"📊 ORB Strategy: {'ENABLED ✓' if ENABLE_ORB_STRATEGY else 'DISABLED'}")
    print(f"🚨 Exit Management: {'ENABLED ✓' if ENABLE_EXIT_MANAGEMENT else 'DISABLED'}")
    print(f"Confirmation cycles required: {BREACH_CONFIRMATION_CYCLES}")
    print(f"Time window: {BREACH_TIME_WINDOW}s")
    print(f"Price sustainability: {PRICE_SUSTAINABILITY_PERCENT}%")
    print("Scanning every 30 seconds...\n")
    
    trader = None
    if ENABLE_AUTO_TRADING or ENABLE_GAP_TRADING or ENABLE_BOX_TRADING or ENABLE_RANGE_TRADING:
        trader = UpstoxTrader(access_token)

    # ── Start AI assistant (background thread, Groq free API) ─────────────────
    # Pass lambdas so the assistant always reads the CURRENT globals/trader,
    # not a snapshot captured at startup.
    print(f"\n{ai_status()}")
    start_ai_assistant(lambda: globals(), lambda: trader)
    # ─────────────────────────────────────────────────────────────────────────
    
    # Start fast trading thread if enabled
    fast_trade_thread = None
    if ENABLE_FAST_TRADING and trader:
        # Select top stocks by volume for fast trading
        sorted_symbols = sorted(
            R3_LEVELS.items(),
            key=lambda x: x[1].get('avg_volume_20d', 0),
            reverse=True
        )[:FAST_TRADE_MAX_SYMBOLS]
        
        watchlist_symbols = [info['symbol'] for _, info in sorted_symbols]
        
        print(f"⚡ Fast Trading Watchlist ({len(watchlist_symbols)} symbols):")
        for i, symbol in enumerate(watchlist_symbols[:10], 1):
            print(f"   {i}. {symbol}")
        if len(watchlist_symbols) > 10:
            print(f"   ... and {len(watchlist_symbols) - 10} more")
        
        # Start fast trading in separate thread
        fast_trade_thread = threading.Thread(
            target=monitor_fast_trades,
            args=(access_token, watchlist_symbols),
            daemon=True
        )
        fast_trade_thread.start()
        print("✅ Fast trading monitor started in background thread\n")
    
    scan_count = 0
    klinger_update_batch = []
    last_position_check = now_ist()
    last_position_sync = now_ist()
    last_summary_print = now_ist()
    last_cache_cleanup = now_ist()
    
    try:
        # Initialize FII/DII and ORB
        if ENABLE_FII_DII_FILTER:
            print("\n🔍 Initializing FII/DII data...")
            extract_fii_dii_data()
        
        if ENABLE_ORB_STRATEGY:
            initialize_orb_csv_files()

            # ── ORB STARTUP CATCHUP ───────────────────────────────────────────
            # If the bot starts between 09:20 and the breakout window close
            # (default 09:50), run the primary ORB pass immediately — before
            # the first scan fires. This ensures signals are built on the very
            # first scan rather than one 30-second cycle later.
            # check_orb_time_and_process handles the same logic on every scan,
            # but calling it here with empty live_data is harmless (it won't
            # process anything useful without live prices). We just prime the
            # state so scan #1 doesn't need to re-trigger the primary pass.
            _now = now_ist()
            _920 = _now.replace(hour=9, minute=20, second=0, microsecond=0)
            _cutoff = _920 + timedelta(minutes=ORB_BREAKOUT_WINDOW_MINUTES)
            _ct = _now.strftime("%H:%M")
            if ENABLE_ORB_STRATEGY and _ct >= "09:20" and _now < _cutoff and not ORB_PROCESSED_TODAY:
                print(f"\n🕘 ORB startup: bot started at {_ct}, within ORB window "
                      f"(09:20–{_cutoff.strftime('%H:%M')}). "
                      f"Will run primary ORB pass on first live-data scan.")
            # ── END ORB STARTUP CATCHUP ──────────────────────────────────────
        
        while True:
            scan_count += 1
            current_time = now_ist()

            # Clear intraday candle cache from previous scan cycle.
            # The fast-trade prefetch (in monitor_fast_trades thread) refills it
            # in parallel. Any main-loop fetch calls also benefit from the cache.
            clear_intraday_cache()
            
            # Heartbeat - always visible so you know the bot is alive
            # Determine active session phase for heartbeat
            _ct_str = current_time.strftime('%H:%M')
            if _ct_str < "10:30":
                _phase = "🔵 ORB"
            elif _ct_str < "13:00":
                _phase = "📦 MIDDAY-BOX"
            elif _ct_str <= "15:15":
                _phase = "🌆 AFTERNOON-PIVOT"
            else:
                _phase = "🔒 POST-MARKET"
            print(f"\n🔄 Scan #{scan_count} | {current_time.strftime('%H:%M:%S')} | {_phase} | Orders today: {DAILY_ORDER_COUNT+BOX_ORDER_COUNT+RANGE_ORDER_COUNT+GAP_ORDER_COUNT+FAST_TRADE_ORDER_COUNT+ORB_ORDER_COUNT}", flush=True)
            
            # Check if trading should be stopped
            if TRADING_STOPPED:
                print(f"\n⚡ Trading stopped. Reason: Daily limit reached")
                print("Continuing to monitor positions for exits...")
            
            # Update Klinger every 5 scans (2.5 minutes)
            if ENABLE_KLINGER_FILTER and scan_count % 5 == 0:
                if not klinger_update_batch:
                    # Prepare batch of stocks to update (top 30 by volume)
                    sorted_keys = sorted(
                        R3_LEVELS.keys(),
                        key=lambda k: R3_LEVELS[k].get('avg_volume_20d', 0),
                        reverse=True
                    )[:30]
                    klinger_update_batch = sorted_keys.copy()
                    if DEBUG_MODE:
                        print(f"\n📊 Preparing to update Klinger for {len(klinger_update_batch)} stocks...")
                
                # Update 5 stocks per scan to avoid blocking
                updated_count = 0
                for _ in range(min(5, len(klinger_update_batch))):
                    if klinger_update_batch:
                        key_to_update = klinger_update_batch.pop(0)
                        symbol = R3_LEVELS[key_to_update].get('symbol')
                        if symbol:
                            # Use cached Klinger update
                            klinger_data = fetch_klinger_data_cached(access_token, key_to_update, symbol)
                            if klinger_data:
                                R3_LEVELS[key_to_update]['klinger'] = klinger_data
                                updated_count += 1
                
                if DEBUG_MODE and updated_count > 0:
                    print(f"✓ Updated Klinger for {updated_count} stocks | Remaining: {len(klinger_update_batch)}")
            
            # Clean up stale states every 10 scans
            if scan_count % 10 == 0:
                reset_stale_breach_states()
                reset_stale_box_states()
                reset_stale_bounce_states()
            
            # Cache cleanup every hour
            if ENABLE_CANDLE_CACHE:
                time_since_cleanup = (current_time - last_cache_cleanup).seconds
                if time_since_cleanup >= 3600:  # 1 hour
                    print("\n🧹 Running cache cleanup...")
                    cleanup_old_cache()
                    save_cache_stats()
                    last_cache_cleanup = current_time
            
            # Monitor active positions (every POSITION_MONITORING_INTERVAL seconds)
            if ENABLE_EXIT_MANAGEMENT and trader and ACTIVE_POSITIONS:
                time_since_check = (current_time - last_position_check).seconds
                if time_since_check >= POSITION_MONITORING_INTERVAL:
                    if DEBUG_MODE:
                        print(f"\n🔍 Checking {len(ACTIVE_POSITIONS)} active positions...")
                    monitor_active_positions(trader)
                    # HA reversal check — runs every time monitor runs
                    check_ha_reversal_alerts(access_token, trader)
                    last_position_check = current_time
            
            # Sync positions with broker every 5 minutes
            if ENABLE_EXIT_MANAGEMENT and trader:
                time_since_sync = (current_time - last_position_sync).seconds
                if time_since_sync >= 300:  # 5 minutes
                    if DEBUG_MODE:
                        print(f"\n🔄 Syncing positions with broker...")
                    sync_positions_with_broker(trader)
                    last_position_sync = current_time
            
            # Print position summary every 2 minutes
            if ACTIVE_POSITIONS:
                time_since_summary = (current_time - last_summary_print).seconds
                if time_since_summary >= 120:  # 2 minutes
                    print_position_summary()
                    last_summary_print = current_time
            
            # Check if it's exit time
            if ENABLE_EXIT_MANAGEMENT and ENABLE_TIME_BASED_EXIT and is_exit_time():
                if ACTIVE_POSITIONS:
                    print(f"\n⏰ EXIT TIME REACHED - Closing all positions")
                    exit_all_positions(trader, "TIME_BASED_EXIT")
                    break
                
            if not is_market_open():
                # Before closing, exit any remaining positions
                if ACTIVE_POSITIONS and trader:
                    print(f"\n⏰ Market closing - Exiting remaining positions")
                    exit_all_positions(trader, "MARKET_CLOSE")
                
                print(f"💤 Market closed. Waiting... ({now_ist().strftime('%H:%M:%S')})", flush=True)
                time.sleep(60)
                continue
                
            # ── Fetch live prices + feed candle builder ALWAYS (even during stabilization) ──
            # This ensures real-time 5min candles accumulate from market open,
            # so fast trading has enough bars by the time stabilization ends.
            try:
                live_data = get_live_prices_batch(access_token, keys)
                if live_data:
                    for _rt_key, _rt_live in live_data.items():
                        _rt_symbol = ISIN_TO_SYMBOL.get(_rt_key, '')
                        if _rt_symbol:
                            update_realtime_candle(
                                _rt_symbol,
                                ltp=_rt_live.get('ltp'),
                                volume=_rt_live.get('volume', 0)
                            )
            except Exception as _candle_err:
                if DEBUG_MODE:
                    print(f"⚠️ Candle builder error: {_candle_err}")
                live_data = None

            if not is_market_stabilized():
                print(f"⏳ Market stabilizing... ({now_ist().strftime('%H:%M:%S')})", flush=True)
                time.sleep(30)
                continue
                
            try:
                # Re-use live_data fetched above (avoids duplicate API call)
                if not live_data:
                    live_data = get_live_prices_batch(access_token, keys)
                
                if not live_data:
                    print("⚡ No data received", flush=True)
                    time.sleep(10)
                    continue
                
                # ── Session-phase strategy dispatcher ────────────────────────
                # Phase 1 (09:15–10:30): ORB handled below
                # Phase 2 (10:30–13:00): Midday Box build + breakout
                # Phase 3 (13:00–15:15): Afternoon Pivot R3/S3 reversal
                monitor_session_phase(live_data, access_token, trader)

                # Check ORB time and process if needed (Phase 1 only)
                if ENABLE_ORB_STRATEGY:
                    check_orb_time_and_process(access_token, live_data)
                    monitor_orb_breakouts(live_data, access_token, trader)

                # Opening-range reversal scan (STRATEGY=reversal/all), throttled
                if ENABLE_REVERSAL_STRATEGY and scan_count % REVERSAL_SCAN_INTERVAL_SCANS == 0:
                    run_reversal_strategy_scan(access_token, live_data, trader)
                
                # Update FII/DII if needed
                if ENABLE_FII_DII_FILTER:
                    update_fii_dii_if_needed()
                
                # Show pending confirmations
                if (LAST_BREAKOUT_STATE or LAST_BOX_STATE or LAST_BOUNCE_STATE) and DEBUG_MODE:
                    total_pending = len(LAST_BREAKOUT_STATE) + len(LAST_BOX_STATE) + len(LAST_BOUNCE_STATE)
                    print(f"\n📊 Pending confirmations: {total_pending}")

                # Gap Trading Logic
                if ENABLE_GAP_TRADING and is_gap_trading_window() and not TRADING_STOPPED:
                    gaps = detect_gaps(live_data)
                    
                    for gap_type, gap_list in gaps.items():
                        for gap in gap_list:
                            signal = get_gap_trading_signal(gap)
                            
                            if signal and should_place_gap_trade(gap, signal):
                                symbol = gap['symbol']
                                # Write to direction-specific set + legacy alias
                                _gap_dir = signal.get('direction', '').upper()
                                if _gap_dir == 'CE':
                                    GAP_UP_ALERTED_STOCKS.add(symbol)
                                elif _gap_dir == 'PE':
                                    GAP_DOWN_ALERTED_STOCKS.add(symbol)
                                GAP_ALERTED_STOCKS.add(symbol)  # legacy alias
                                
                                print("\n" + "="*120)
                                print(f"⚡ GAP TRADING SIGNAL: {symbol} ⚡")
                                print("="*120)
                                print(f"Type: {gap_type.upper()} ({gap['gap_percent']:.2f}%)")
                                print(f"Strategy: {signal['signal'].upper()} | Direction: {signal['direction']}")
                                print(f"Price: {gap['current_price']} | Volume Ratio: {gap['volume_ratio']:.2f}")
                                print(f"Confidence: {signal['confidence']} | Strength: {signal['strength_score']}")
                                
                                if trader:
                                    place_gap_order(gap, signal, trader)
                                    
                                with open(GAP_CSV_FILE, 'a', newline='', encoding='utf-8') as f:
                                    writer = csv.writer(f)
                                    writer.writerow([
                                        now_ist().strftime('%Y-%m-%d %H:%M:%S'),
                                        symbol,
                                        gap_type,
                                        signal['signal'],
                                        signal['direction'],
                                        gap['gap_percent'],
                                        gap['volume_ratio']
                                    ])
                
                # R3/S3/Box/Range Logic (only if not stopped)
                if not TRADING_STOPPED:

                    # === FII TREND REVERSAL (Short + Long) ===
                    # Runs once per iteration; each symbol fires at most once per session.
                    if ENABLE_FII_REVERSAL:
                        reversal_signals = detect_fii_reversal(access_token, live_data)
                        for sig in reversal_signals:
                            print(f"\n{'='*80}")
                            print(f"🔴 FII REVERSAL SHORT ALERT → {sig['symbol']}")
                            print(f"   1H Break Low + Red HA + EMA Bearish | Vol {sig['volume_ratio']}x")
                            print(f"   Level: ₹{sig['level']:.2f} | LTP: ₹{sig.get('current_price') or 0:.2f}")
                            print(f"{'='*80}")
                            if trader:
                                place_breakout_order(sig, trader)

                    if ENABLE_FII_REVERSAL_LONG:
                        long_signals = detect_fii_reversal_long(access_token, live_data)
                        for sig in long_signals:
                            print(f"\n{'='*80}")
                            print(f"🟢 FII REVERSAL LONG ALERT → {sig['symbol']}")
                            print(f"   1H Break High + Green HA + EMA Bullish | Vol {sig['volume_ratio']}x")
                            print(f"   Level: ₹{sig['level']:.2f} | LTP: ₹{sig.get('current_price') or 0:.2f}")
                            print(f"{'='*80}")
                            if trader:
                                place_breakout_order(sig, trader)

                    # ── S4: FII/DII BB-mid cross + live continuation ──────────
                    # Runs EVERY scan (not throttled) — immediate live-break
                    # detection is the whole point of this strategy.
                    if ENABLE_FII_BB_CONTINUATION:
                        fii_bb_sigs = scan_fii_bb_continuation(access_token, live_data)
                        for sig in fii_bb_sigs:
                            _log_and_place_new_reversal(sig, trader, FII_BB_CSV, "FII/DII BB CONTINUATION")

                    # ── New Reversal Strategies (throttled: every 2 scans) ────
                    if scan_count % 2 == 0:

                        # S1: Big opening candle + resistance reversal
                        if ENABLE_RESISTANCE_REVERSAL:
                            res_sigs = detect_resistance_reversal(access_token, live_data)
                            for sig in res_sigs:
                                _log_and_place_new_reversal(sig, trader, RES_REVERSAL_CSV, "RESISTANCE REVERSAL")

                        # S2: Dual-TF BB middle cross (5-min + 1-hr)
                        if ENABLE_DUAL_TF_BB:
                            bb_sigs = detect_dual_tf_bb_cross(access_token, live_data)
                            for sig in bb_sigs:
                                _log_and_place_new_reversal(sig, trader, DUAL_TF_BB_CSV, "DUAL-TF BB")

                        # S3a: General universe — first-1H + weekly high/low breakout
                        if ENABLE_FIIDII_BREAKOUT:
                            gen_sigs = detect_fiidii_confluence_breakout(
                                access_token, live_data, mode='general')
                            for sig in gen_sigs:
                                _log_and_place_new_reversal(sig, trader, FIIDII_BREAKOUT_CSV, "CONFLUENCE BREAKOUT")

                        # S3b: FII/DII universe — same + 2-wk lookback + BB middle + 2-candle confirm
                        if ENABLE_FIIDII_BREAKOUT:
                            fii_sigs = detect_fiidii_confluence_breakout(
                                access_token, live_data, mode='fii')
                            for sig in fii_sigs:
                                _log_and_place_new_reversal(sig, trader, FIIDII_BREAKOUT_CSV, "FII/DII CONFLUENCE")

                        # S3c: FII/DII rolling-anchor + strong-close variant
                        if ENABLE_FIIDII_BREAKOUT_V2:
                            fii_v2_sigs = detect_fiidii_confluence_breakout(
                                access_token, live_data, mode='fii_v2')
                            for sig in fii_v2_sigs:
                                _log_and_place_new_reversal(sig, trader, FIIDII_BREAKOUT_CSV, "FII/DII BB-CROSS V2")

                    for key, live in live_data.items():
                        if key in R3_LEVELS:
                            # R3 Breakout
                            breakout = check_breakout(key, live)
                            if breakout:
                                send_alert(breakout, trader)
                            
                            # S3 Breakdown
                            breakdown = check_breakdown(key, live)
                            if breakdown:
                                send_alert(breakdown, trader)
                            
                            # Box Top Breakout with Klinger
                            box_top = check_box_top_breakout(key, live)
                            if box_top:
                                send_alert(box_top, trader)
                            
                            # Box Bottom Breakdown with Klinger
                            box_bottom = check_box_bottom_breakdown(key, live)
                            if box_bottom:
                                send_alert(box_bottom, trader)
                            
                            # Support Bounce with Klinger
                            bounce = check_box_support_bounce(key, live)
                            if bounce:
                                send_alert(bounce, trader)
                            
                            # Resistance Rejection with Klinger
                            rejection = check_box_resistance_rejection(key, live)
                            if rejection:
                                send_alert(rejection, trader)
                        
            except Exception as e:
                print(f"❌ Monitor loop error: {e}")
                if DEBUG_MODE:
                    import traceback
                    traceback.print_exc()
                
            time.sleep(30)
            
    except KeyboardInterrupt:
        print("\n\n⚡ Keyboard interrupt detected...")
        
        # Exit all open positions before stopping
        if ENABLE_EXIT_MANAGEMENT and trader and ACTIVE_POSITIONS:
            print(f"\n🚨 Exiting all open positions...")
            exit_all_positions(trader, "MANUAL_STOP")
        
        # Save final cache stats
        if ENABLE_CANDLE_CACHE:
            print("\n💾 Saving cache statistics...")
            save_cache_stats()
        
        print_final_stats()

# ========== MAIN EXECUTION ==========
def run_trading_bot(access_token):
    """Main execution function for trading bot"""
    banner()
    
    if not verify_token(access_token):
        print("❌ Cannot proceed without valid token")
        return
    
    # Get F&O stocks
    keys, symbols = get_all_fno_equities(access_token)
    if not keys:
        print("❌ No F&O stocks found")
        return
    
    # Initialize levels with retry
    max_init_attempts = 3
    init_success = False

    for attempt in range(max_init_attempts):
        print(f"\n📊 Initialization attempt {attempt + 1}/{max_init_attempts}")
        init_success = initialize_r3_levels(access_token, keys, symbols)

        if init_success:
            break
        elif attempt < max_init_attempts - 1:
            print(f"⏳ Waiting 10 seconds before retry {attempt + 2}...")
            time.sleep(10)
            reset_initialization()

    if not init_success:
        print("❌ Failed to initialize levels after multiple attempts")
        return
    
    # Create CSV files if needed
    csv_files_config = [
        (ALERT_CSV_FILE, ['Timestamp', 'Symbol', 'Type', 'Price', 'Volume_Ratio', 'Day_Gain', 'Strategy', 'Klinger_Status']),
        (GAP_CSV_FILE, ['Timestamp', 'Symbol', 'Gap_Type', 'Signal', 'Direction', 'Gap_Percent', 'Volume_Ratio']),
        (BOX_CSV_FILE, ['Timestamp', 'Symbol', 'Type', 'Price', 'Volume_Ratio', 'Day_Gain', 'Strategy', 'Klinger_Status']),
        (RANGE_CSV_FILE, ['Timestamp', 'Symbol', 'Type', 'Price', 'Volume_Ratio', 'Day_Gain', 'Strategy', 'Klinger_Status']),
        (EXIT_CSV_FILE, ['Exit_Time', 'Symbol', 'Strategy', 'Entry_Price', 'Exit_Price', 'Quantity', 'PnL', 'PnL_Percent', 'Exit_Reason', 'Order_ID']),
        (POSITION_LOG_FILE, ['Timestamp', 'Symbol', 'Strategy', 'Action', 'Price', 'Quantity', 'PnL', 'Details']),
        (FAST_TRADE_ENTRY_FILE, ['timestamp', 'symbol', 'signal', 'entry_price', 'stop_loss', 'target', 'entry_type', 'order_id', 'volume_ratio', 'candle_size_pct', 'bb_width', 'klinger_confirmed', 'klinger_status', 'confidence', 'premium_source', 'fii_trend_score', 'timeframe']),
        (FAST_TRADE_EXIT_FILE, ['exit_time', 'symbol', 'signal', 'entry_price', 'exit_price', 'stop_loss', 'target', 'pnl', 'pnl_pct', 'entry_time', 'exit_time', 'duration_min', 'exit_type', 'exit_reason', 'order_id', 'entry_type', 'premium_source']),
    ]
    
    if ENABLE_ORB_STRATEGY:
        csv_files_config.extend([
            (ORB_SIGNALS_FILE, ['Timestamp', 'Symbol', 'Signal_Type', 'Direction', 
                               'Breakout_Level', 'Stop_Level', 'Target_Level', 
                               'Body_Percent', 'Risk_Reward', 'FII_DII_Signal', 'Confidence']),
            (ORB_TRADES_FILE, ['Timestamp', 'Symbol', 'Action', 'Direction', 'Price', 
                              'Stop_Loss', 'Target', 'Volume_Ratio', 'Confidence', 'FII_DII_Signal'])
        ])

    if ENABLE_REVERSAL_STRATEGY:
        csv_files_config.append(
            (REVERSAL_SIGNALS_FILE, ['Timestamp', 'Symbol', 'Signal_Type', 'Close',
                                     'Strength', 'Reason', 'OR_High', 'OR_Low'])
        )
    
    for csv_file, headers in csv_files_config:
        if not os.path.exists(csv_file):
            with open(csv_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(headers)
    
    # Session log
    with open(ALERT_LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(f"\n{'='*100}\n")
        f.write(f"SESSION START: {now_ist().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Stocks: {len(R3_LEVELS)}\n")
        f.write(f"Strategies: R3/S3={'ON' if ENABLE_AUTO_TRADING else 'OFF'} | ")
        f.write(f"Box Theory={'ON' if ENABLE_BOX_TRADING else 'OFF'} | ")
        f.write(f"Range Trading={'ON' if ENABLE_RANGE_TRADING else 'OFF'} | ")
        f.write(f"Gap Trading={'ON' if ENABLE_GAP_TRADING else 'OFF'} | ")
        f.write(f"Fast Trading={'ON' if ENABLE_FAST_TRADING else 'OFF'} | ")
        f.write(f"ORB={'ON' if ENABLE_ORB_STRATEGY else 'OFF'}\n")
        f.write(f"🔥 Klinger Filter: {'ENABLED' if ENABLE_KLINGER_FILTER else 'DISABLED'}")
        if ENABLE_KLINGER_FILTER:
            f.write(f" (Fast={KLINGER_FAST}, Slow={KLINGER_SLOW}, Signal={KLINGER_SIGNAL})")
            f.write(f" Box={'ON' if ENABLE_KLINGER_FOR_BOX else 'OFF'} Range={'ON' if ENABLE_KLINGER_FOR_RANGE else 'OFF'}")
            f.write(f" Adaptive={'ON' if ADAPTIVE_KLINGER_LOOKBACK else 'OFF'}")
            if KLINGER_PAPER_MODE:
                f.write(f" - PAPER MODE")
        f.write(f"\n💾 Candle Cache: {'ENABLED' if ENABLE_CANDLE_CACHE else 'DISABLED'}")
        if ENABLE_CANDLE_CACHE:
            f.write(f" (Min candles: {MIN_CANDLES_FOR_KLINGER})")
        f.write(f"\n⚡ Fast Trading: {'ENABLED' if ENABLE_FAST_TRADING else 'DISABLED'}")
        if ENABLE_FAST_TRADING:
            f.write(f" (Timeframe: {FAST_TRADE_TIMEFRAME}, Max Symbols: {FAST_TRADE_MAX_SYMBOLS})")
        f.write(f"\n🚨 Exit Management: {'ENABLED' if ENABLE_EXIT_MANAGEMENT else 'DISABLED'}")
        if ENABLE_EXIT_MANAGEMENT:
            f.write(f" (Max Loss: ₹{MAX_DAILY_LOSS:,}, Max Profit: ₹{MAX_DAILY_PROFIT:,})")
        f.write(f"\n{'='*100}\n\n")
    
    print(f"\n✅ SYSTEM READY! Monitoring {len(R3_LEVELS)} high-volume F&O stocks")
    print(f"📊 Strategies: R3/S3 + Box Theory + Range Trading{' + Gap' if ENABLE_GAP_TRADING else ''}{' + Fast Trading' if ENABLE_FAST_TRADING else ''}{' + ORB' if ENABLE_ORB_STRATEGY else ''}")
    if ENABLE_KLINGER_FILTER:
        print(f"🔥 Klinger Oscillator: ACTIVE")
        print(f"   • Box Trading: {'ENABLED' if ENABLE_KLINGER_FOR_BOX else 'DISABLED'}")
        print(f"   • Range Trading: {'ENABLED' if ENABLE_KLINGER_FOR_RANGE else 'DISABLED'}")
        print(f"   • Adaptive Mode: {'ENABLED' if ADAPTIVE_KLINGER_LOOKBACK else 'DISABLED'}")
        if KLINGER_PAPER_MODE:
            print(f"   • ✗ PAPER MODE: Logging only, not filtering")
    if ENABLE_CANDLE_CACHE:
        print(f"💾 Candle Cache: ACTIVE")
        print(f"   • Directory: {CACHE_DIRECTORY}")
        print(f"   • Min Candles: {MIN_CANDLES_FOR_KLINGER}")
    if ENABLE_FAST_TRADING:
        print(f"⚡ Fast Trading: ACTIVE")
        print(f"   • Timeframe: {FAST_TRADE_TIMEFRAME}")
        print(f"   • Max Symbols: {FAST_TRADE_MAX_SYMBOLS}")
        print(f"   • Bollinger: Period={BOLLINGER_PERIOD}, Std={BOLLINGER_STD}")
    if ENABLE_ORB_STRATEGY:
        print(f"📊 ORB Strategy: ACTIVE")
        print(f"   • Timeframe: {ORB_TIMEFRAME_MINUTES} minutes")
        print(f"   • FII/DII Filter: {'ON' if ORB_ENABLE_FII_DII_FILTER else 'OFF'}")
    if ENABLE_FII_DII_FILTER:
        print(f"🔍 FII/DII Filter: ACTIVE")
        if FII_DII_STRONG_BUY:
            print(f"   • Strong Buy: {len(FII_DII_STRONG_BUY)} stocks")
        if FII_DII_STRONG_SELL:
            print(f"   • Strong Sell: {len(FII_DII_STRONG_SELL)} stocks")
        if ENABLE_FII_DII_TREND_FILTER:
            print(f"   • Multi-day Trend Filter: ACTIVE")
            with FII_DII_TREND_LOCK:
                n_acc = len(FII_DII_TREND_STRONG_ACCUMULATION)
                n_fbu = len(FII_DII_TREND_FII_BUY_DII_SELL)
                n_fse = len(FII_DII_TREND_FII_SELL_DII_BUY)
                n_unu = len(FII_DII_TREND_UNUSUAL_CHANGE)
            if n_acc:
                print(f"     Strong Accumulation: {n_acc} stocks")
            if n_fbu:
                print(f"     FII Buy / DII Sell : {n_fbu} stocks")
            if n_fse:
                print(f"     FII Sell / DII Buy : {n_fse} stocks")
            if n_unu:
                print(f"     Unusual Reversal   : {n_unu} stocks")
    if ENABLE_EXIT_MANAGEMENT:
        print(f"🚨 Exit Management: ACTIVE")
        print(f"   • Max Daily Loss: ₹{MAX_DAILY_LOSS:,}")
        print(f"   • Max Daily Profit: ₹{MAX_DAILY_PROFIT:,}")
        print(f"   • Trailing Stop: {TRAILING_STOP_PERCENTAGE}% (activates at {TRAILING_STOP_ACTIVATION}% profit)")
    print("🚀 Press Ctrl+C to stop\n")
    
    enhanced_monitor(access_token, keys, symbols)


def main():
    """Main entry point - get token and run trading bot"""
    print("="*120)
    print("UPSTOX AUTO-TRADING BOT WITH INTELLIGENT CACHING & ADVANCED STRATEGIES")
    print("="*120)
    print()

    # Step 0: Apply STRATEGY env selection (GitHub Actions workflow dropdown)
    apply_strategy_selection()

    # Step 1: Get Upstox access token (smart fallback)
    token = get_upstox_token()
    
    if not token:
        print("\n" + "="*60)
        print("❌ CRITICAL ERROR: Failed to get valid Upstox token")
        print("="*60)
        print("\nPlease check:")
        print("1. Your hardcoded token is correct and not expired")
        print("2. Your login credentials are correct")
        print("3. Your internet connection is stable")
        print("4. Upstox services are available")
        print("\nExiting...")
        return
    
    print("\n" + "="*60)
    print("✅ TOKEN ACQUIRED SUCCESSFULLY")
    print("="*60)
    print(f"Token: {token[:30]}...{token[-20:]}")
    print()
    
    # Step 2: Run trading bot with the token
    run_trading_bot(token)

if __name__ == "__main__":
    main()