#!/usr/bin/env python3
"""
ORB (Opening Range Breakout) Trading Strategy - Full Standalone Script
======================================================================
This script implements the Opening Range Breakout strategy using the first 
15-minute candle (9:15 - 9:30) to identify breakout trades.

Key Features:
- First 15-minute candle analysis
- Klinger + RSI quality gates
- FII/DII alignment filter
- Volume confirmation
- Risk:Reward based target/stop
- Complete token acquisition
- Full order placement

Usage:
    python orb_only.py
"""

import os
import sys
import csv
import json
import time
import threading
import pickle
import re
import email
import imaplib
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import pandas as pd
import numpy as np
from urllib.parse import urlparse, parse_qs
from http.server import HTTPServer, BaseHTTPRequestHandler
from bs4 import BeautifulSoup

# AI Assistant
try:
    from ai_assistant import (
        start_ai_assistant, 
        ai_status, 
        ai_analyze_orb_breakout,
        ai_market_check,
        AI_ENABLED as _AI_ENABLED,
        quick_signal_check
    )
    _AI_AVAILABLE = True
except ImportError:
    _AI_AVAILABLE = False
    def start_ai_assistant(*a, **kw): pass
    def ai_status(): return "AI: module not found"
    def ai_analyze_orb_breakout(*a, **kw): return None
    def ai_market_check(): return "AI not available"
    def quick_signal_check(*a, **kw): return ("NEUTRAL", 3)

# ========== CONFIGURATION ==========
# Upstox Credentials - UPDATE THESE
EMAIL           = os.environ.get("UPSTOX_EMAIL",    "your_email@gmail.com")
EMAIL_PASSWORD  = os.environ.get("UPSTOX_PASSWORD", "your_gmail_app_password")
MOBILE_NUMBER   = os.environ.get("UPSTOX_MOBILE",   "9999999999")
PASSCODE        = os.environ.get("UPSTOX_PASSCODE",  "000000")

# API Credentials - GET FROM https://account.upstox.com/developer/apps
UPSTOX_API_KEY      = os.environ.get("UPSTOX_API_KEY",    "your_client_id")
UPSTOX_API_SECRET   = os.environ.get("UPSTOX_API_SECRET", "your_client_secret")
UPSTOX_REDIRECT_URI = "http://127.0.0.1:8080/"
HEADLESS_SERVER_PORT = 8080

# Token Files
UPSTOX_TOKEN_FILE = "upstox_token.txt"
UPSTOX_REFRESH_TOKEN_FILE = "upstox_refresh_token.txt"

# Trading Settings
ENABLE_AUTO_TRADING = True
ORDER_QUANTITY = 1
ORDER_PRODUCT = 'D'
MAX_ORDERS_PER_DAY = 10
MIN_ORDER_GAP_SECONDS = 300
ORDER_VERIFICATION_DELAY = 3

# Market Timing
MARKET_OPEN_TIME = "09:15"
MARKET_CLOSE_TIME = "15:30"
TEST_MODE = True
BYPASS_MARKET_CHECKS = TEST_MODE

# ORB Strategy Configuration
ENABLE_ORB_STRATEGY = True
ORB_TIMEFRAME_MINUTES = 15
ORB_MIN_CANDLE_BODY_PERCENT = 0.5
ORB_VOLUME_CONFIRMATION = 1.5
ORB_BREAKOUT_WINDOW_MINUTES = 60
ORB_TARGET_MULTIPLIER = 2.0
ORB_STOP_MULTIPLIER = 1.0
ORB_MIN_VOLUME = 500000
ORB_ENABLE_MARKET_ALIGNMENT = True
ORB_ENABLE_FII_DII_FILTER = True

# ORB Quality Gates
ORB_ENABLE_KLINGER_GATE   = True
ORB_ENABLE_RSI_GATE       = True
ORB_RSI_LONG_MIN          = 52
ORB_RSI_SHORT_MAX         = 48
ORB_MIN_CANDLE_BODY_LONG  = 0.6
ORB_MIN_CANDLE_BODY_SHORT = 0.6

# Logging Files
ORB_SIGNALS_FILE = "orb_signals.csv"
ORB_TRADES_FILE = "orb_trades.csv"
ORB_LOG_FILE = "orb_trading_log.txt"
ALERT_CSV_FILE = "orb_alerts.csv"

# AI Settings
ENABLE_AI_ANALYSIS = True  # Analyze signals with AI before trading
AI_BUY_THRESHOLD = 4       # Minimum score to proceed (0-5 scale)

# ========== FII/DII CONFIGURATION ==========
ENABLE_FII_DII_FILTER = True
FII_DII_URL = "https://munafasutra.com/nse/FIIDII/"
FII_DII_CACHE_FILE = "fii_dii_cache.json"
FII_DII_STRONG_BUY = set()
FII_DII_STRONG_SELL = set()
FII_DII_DATA = {}
FII_DII_LAST_UPDATE = None

# ========== KLINGER CONFIGURATION ==========
ENABLE_KLINGER_FILTER = True
KLINGER_FAST = 34
KLINGER_SLOW = 55
KLINGER_SIGNAL = 13
MIN_CANDLES_FOR_KLINGER = 60

# ========== VOLUME FILTER ==========
MIN_AVG_VOLUME = 500000
VOLUME_SPIKE_THRESHOLD = 1.3

# ========== GLOBALS ==========
R3_LEVELS = {}
SYMBOL_TO_ISIN = {}
ISIN_TO_SYMBOL = {}
VOLUME_DATA = {}
OPTIONS_CACHE = {}

ORB_CANDLES = {}
ORB_SIGNALS = {}
ORB_LATE_CHECKED = set()
ORB_ALERTED_STOCKS = set()
ORB_ORDER_COUNT = 0
ORB_PROCESSED_TODAY = False

DEBUG_MODE = True
DAILY_ORDER_COUNT = 0
LAST_ORDER_TIME = {}
PLACED_ORDERS = {}

# Persistent session
_UPSTOX_SESSION = None
_UPSTOX_SESSION_TOKEN = ""

# ========== CANDLE CACHE ==========
_CANDLE_CACHE = {}

# ========== NSE HOLIDAYS ==========
NSE_HOLIDAYS_2025 = {
    '2025-01-26', '2025-02-26', '2025-03-14', '2025-03-31',
    '2025-04-10', '2025-04-14', '2025-04-18', '2025-05-01',
    '2025-08-15', '2025-08-27', '2025-10-02', '2025-10-21',
    '2025-10-22', '2025-11-05', '2025-12-25',
}
NSE_HOLIDAYS_2026 = {
    '2026-01-26', '2026-03-03', '2026-03-25', '2026-04-02',
    '2026-04-10', '2026-04-14', '2026-05-01', '2026-08-15',
    '2026-09-02', '2026-10-02', '2026-10-19', '2026-11-08',
    '2026-11-09', '2026-11-19', '2026-12-25',
}
NSE_HOLIDAYS = NSE_HOLIDAYS_2025 | NSE_HOLIDAYS_2026


# ========== HELPER FUNCTIONS ==========
def norm_key(k: str) -> str:
    """Normalize instrument keys"""
    if isinstance(k, str):
        k = k.replace(':', '|')
        if '|' in k:
            parts = k.split('|')
            if len(parts) == 2:
                return f"{parts[0]}|{parts[1]}"
    return k


def is_order_time_allowed():
    """Check if Upstox API accepts orders"""
    now = datetime.now()
    order_start = now.replace(hour=5, minute=30, second=0, microsecond=0)
    order_end = now.replace(hour=23, minute=59, second=59, microsecond=0)
    return order_start <= now <= order_end


def is_market_open():
    """Check if market is open"""
    if BYPASS_MARKET_CHECKS:
        return True
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    current_time = now.strftime("%H:%M")
    return MARKET_OPEN_TIME <= current_time <= MARKET_CLOSE_TIME


def is_market_stabilized():
    """Check if market is stabilized"""
    if BYPASS_MARKET_CHECKS:
        return True
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    current_time = now.strftime("%H:%M")
    if current_time < MARKET_OPEN_TIME or current_time >= MARKET_CLOSE_TIME:
        return False
    market_open_dt = datetime.strptime(MARKET_OPEN_TIME, "%H:%M").replace(
        year=now.year, month=now.month, day=now.day
    )
    minutes_since_open = (now - market_open_dt).total_seconds() / 60
    return minutes_since_open >= 5


def previous_trading_day(max_lookback_days=15):
    """Get previous trading day"""
    today = datetime.now().date()
    for d in range(1, max_lookback_days + 1):
        target_date = today - timedelta(days=d)
        if target_date.weekday() >= 5:
            continue
        date_str = target_date.strftime('%Y-%m-%d')
        if date_str in NSE_HOLIDAYS:
            continue
        return target_date
    return today - timedelta(days=7)


# ========== UPSTOX SESSION ==========
def _get_upstox_session(access_token: str) -> requests.Session:
    """Get persistent Upstox session"""
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


# ========== TOKEN MANAGEMENT ==========
def verify_token(token, verbose=True):
    """Verify API token"""
    if verbose:
        print("🔍 Verifying API token...")
    
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}"
    }
    url = "https://api.upstox.com/v2/user/profile"
    try:
        response = _get_upstox_session(token).get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if verbose:
                print("✅ Token is VALID")
                if 'data' in data:
                    user_name = data['data'].get('user_name', 'N/A')
                    print(f" User: {user_name}")
            return {'valid': True, 'data': data.get('data', {}), 'message': 'Valid'}
        elif response.status_code == 401:
            if verbose:
                print("❌ Token is INVALID or EXPIRED")
            return {'valid': False, 'message': 'Invalid or expired', 'status_code': 401}
    except Exception as e:
        if verbose:
            print(f"❌ Token verification error: {e}")
        return {'valid': False, 'message': str(e)}


def _refresh_upstox_token() -> str:
    """Try to refresh token using saved refresh token"""
    if not os.path.exists(UPSTOX_REFRESH_TOKEN_FILE):
        return None
    try:
        with open(UPSTOX_REFRESH_TOKEN_FILE, "r") as f:
            refresh_token = f.read().strip()
        if not refresh_token:
            return None
        
        print("🔄 Attempting token refresh...")
        resp = requests.post(
            "https://api.upstox.com/v2/login/authorization/token",
            headers={"accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": UPSTOX_API_KEY,
                "client_secret": UPSTOX_API_SECRET,
            },
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            access_token = data.get("access_token")
            new_refresh = data.get("refresh_token", refresh_token)
            if access_token:
                with open(UPSTOX_REFRESH_TOKEN_FILE, "w") as f:
                    f.write(new_refresh)
                with open(UPSTOX_TOKEN_FILE, "w") as f:
                    f.write(access_token)
                print("✅ Token refreshed successfully.")
                return access_token
    except Exception as e:
        print(f"⚠️ Token refresh error: {e}")
    return None


def get_upstox_token():
    """Get Upstox access token with smart fallback"""
    print("="*60)
    print("UPSTOX TOKEN MANAGEMENT")
    print("="*60)
    
    # Try hardcoded token from file
    if os.path.exists(UPSTOX_TOKEN_FILE):
        try:
            with open(UPSTOX_TOKEN_FILE, 'r') as f:
                saved_token = f.read().strip()
            if saved_token:
                validation = verify_token(saved_token, verbose=True)
                if validation['valid']:
                    print("✅ SAVED token is VALID")
                    return saved_token
        except Exception as e:
            print(f"⚠️ Error reading token: {e}")
    
    # Try refresh token
    refreshed = _refresh_upstox_token()
    if refreshed:
        validation = verify_token(refreshed, verbose=True)
        if validation['valid']:
            return refreshed
    
    print("\n❌ No valid token available")
    print("Please ensure you have run the main trading bot at least once")
    print("to generate and save the access token.")
    return None


# ========== UPSTOX TRADER CLASS ==========
class UpstoxTrader:
    """Upstox trader with order placement"""
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
        self._session = requests.Session()
        self._session.headers.update(self.headers)
        self._order_session = requests.Session()
        self._order_session.headers.update(self.order_headers)
    
    def get_funds(self):
        endpoint = f"{self.base_url}/user/get-funds-and-margin"
        try:
            response = self._session.get(endpoint, timeout=10)
            return response.json()
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def get_ltp(self, instrument_key, max_retries=3):
        endpoint = f"{self.base_url}/market-quote/ltp"
        params = {"instrument_key": instrument_key}
        for attempt in range(max_retries):
            try:
                response = self._session.get(endpoint, params=params, timeout=15)
                if response.status_code == 200:
                    data = response.json()
                    inner = data.get('data', {})
                    ltp_data = (inner.get(instrument_key) or
                               inner.get(instrument_key.replace('|', ':')) or
                               (list(inner.values())[0] if inner else None))
                    if ltp_data:
                        ltp = ltp_data.get('last_price')
                        if ltp and ltp > 0:
                            return ltp
            except Exception as e:
                if attempt < max_retries - 1:
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
    
    def place_order(self, instrument_key, quantity, transaction_type, product, 
                    order_type, price=0, trigger_price=0):
        """Place an order"""
        if not is_order_time_allowed():
            return {
                "status_code": 423,
                "response": {"status": "error", "message": "Outside service hours"}
            }
        
        if not instrument_key or '|' not in instrument_key:
            return {
                "status_code": 400,
                "response": {"status": "error", "message": f"Invalid key: {instrument_key}"}
            }
        
        endpoint = f"{self.base_url}/order/place"
        payload = {
            "quantity": quantity,
            "product": product,
            "validity": "DAY",
            "price": price,
            "tag": "ORB_BOT",
            "instrument_token": instrument_key,
            "order_type": order_type.upper(),
            "transaction_type": transaction_type.upper(),
            "disclosed_quantity": 0,
            "trigger_price": trigger_price,
            "is_amo": False
        }
        
        try:
            print(f"📤 ORDER: {payload}")
            response = self._order_session.post(endpoint, json=payload, timeout=15)
            print(f"📥 RESPONSE ({response.status_code}): {response.text[:200]}")
            
            return {
                "status_code": response.status_code,
                "response": response.json() if response.text else {"status": "error"}
            }
        except Exception as e:
            print(f"❌ ORDER EXCEPTION: {e}")
            return {"status_code": 0, "response": {"status": "error", "message": str(e)}}
    
    def get_order_details(self, order_id):
        endpoint = f"{self.base_url}/order/history"
        params = {"order_id": order_id}
        try:
            response = self._session.get(endpoint, params=params, timeout=10)
            return response.json()
        except Exception as e:
            return {"status": "error", "message": str(e)}


# ========== DATA FETCHING ==========
def get_all_fno_equities(access_token):
    """Get F&O stock list"""
    print("📥 Downloading F&O stock list...")
    url = "https://assets.upstox.com/market-quote/instruments/exchange/complete.csv.gz"
    try:
        df = pd.read_csv(url, compression='gzip')
        fo = df[df['exchange'] == 'NSE_FO']
        fo_symbols = fo['tradingsymbol'].str.replace(r'\d{2}[A-Z]{3}\d{2,4}.*', '', regex=True).str.strip().unique()
        fo_symbols = set([s for s in fo_symbols if s])
        eq = df[(df['exchange'] == 'NSE_EQ') & (df['tradingsymbol'].isin(fo_symbols))].copy()
        eq = eq.drop_duplicates(subset=['tradingsymbol'])
        keys = eq['instrument_key'].tolist()
        sym = dict(zip(eq['instrument_key'], eq['tradingsymbol']))
        print(f"✅ Found {len(keys)} F&O stocks\n")
        return keys, sym
    except Exception as e:
        print(f"❌ Error: {e}")
        return [], {}


def get_live_prices_batch(access_token, instrument_keys):
    """Fetch live prices for multiple instruments"""
    if not instrument_keys:
        return {}
    
    url = "https://api.upstox.com/v2/market-quote/quotes"
    results = {}
    
    for i in range(0, len(instrument_keys), 50):
        chunk = instrument_keys[i:i+50]
        params = [('instrument_key', key) for key in chunk]
        try:
            response = _get_upstox_session(access_token).get(url, params=params, timeout=30)
            if response.status_code == 200:
                data = response.json()
                if 'data' in data:
                    for response_key, quote in data['data'].items():
                        nk = norm_key(response_key)
                        results[nk] = {
                            'ltp': quote.get('last_price'),
                            'high': quote.get('ohlc', {}).get('high'),
                            'low': quote.get('ohlc', {}).get('low'),
                            'open': quote.get('ohlc', {}).get('open'),
                            'close': quote.get('ohlc', {}).get('close'),
                            'volume': quote.get('volume'),
                            'timestamp': datetime.now()
                        }
        except Exception as e:
            if DEBUG_MODE:
                print(f"Batch fetch error: {e}")
    
    return results


def fetch_historical_ohlc(access_token, instrument_key, target_date):
    """Fetch OHLC for a specific date"""
    date_str = target_date.strftime('%Y-%m-%d') if hasattr(target_date, 'strftime') else str(target_date)
    url = f"https://api.upstox.com/v2/historical-candle/{instrument_key}/day/{date_str}/{date_str}"
    try:
        resp = _get_upstox_session(access_token).get(url, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            candles = data.get("data", {}).get("candles", [])
            if candles:
                candle = candles[0]
                return {
                    "date": target_date,
                    "open": candle[1],
                    "high": candle[2],
                    "low": candle[3],
                    "close": candle[4],
                    "volume": candle[5],
                }
    except Exception:
        pass
    return None


def get_cached_candles(access_token, symbol, instrument_key):
    """Get daily candle data"""
    if symbol in _CANDLE_CACHE:
        return _CANDLE_CACHE[symbol]
    
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=120)
    
    from_str = start_date.strftime('%Y-%m-%d')
    to_str = end_date.strftime('%Y-%m-%d')
    
    url = f"https://api.upstox.com/v2/historical-candle/{instrument_key}/day/{to_str}/{from_str}"
    
    try:
        resp = _get_upstox_session(access_token).get(url, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            candles = data.get("data", {}).get("candles", [])
            if candles:
                df = pd.DataFrame(candles, columns=['date', 'open', 'high', 'low', 'close', 'volume', 'oi'])
                df['date'] = pd.to_datetime(df['date'])
                df = df.sort_values('date').reset_index(drop=True)
                _CANDLE_CACHE[symbol] = df
                return df
    except Exception as e:
        if DEBUG_MODE:
            print(f"⚠️ Candle error {symbol}: {e}")
    return None


# ========== KLINGER CALCULATION ==========
def calculate_klinger_adaptive(df, symbol=None):
    """Calculate Klinger Oscillator"""
    if df is None or len(df) < MIN_CANDLES_FOR_KLINGER:
        return None, None, None
    
    if len(df) > 200:
        df = df.tail(200).reset_index(drop=True)
    
    fast, slow, signal = KLINGER_FAST, KLINGER_SLOW, KLINGER_SIGNAL
    
    try:
        if len(df) < max(fast, slow, signal) + 10:
            return None, None, None
        
        hlc = (df['high'] + df['low'] + df['close']) / 3
        hlc_prev = hlc.shift(1)
        trend = ((hlc > hlc_prev).astype(int) * 2 - 1).fillna(0)
        
        dm = df['high'] - df['low']
        dm = dm.replace(0, 0.001)
        
        cm = (dm * trend).cumsum()
        cm = cm.replace(0, 0.001).fillna(0.001)
        
        volume_force = df['volume'] * trend * (dm / cm) * 100
        volume_force = volume_force.clip(-1e12, 1e12)
        volume_force = volume_force.replace([float('inf'), float('-inf')], 0).fillna(0)
        
        vf_fast = volume_force.ewm(span=fast, adjust=False).mean()
        vf_slow = volume_force.ewm(span=slow, adjust=False).mean()
        
        klinger = (vf_fast - vf_slow).clip(-1e12, 1e12)
        signal_line = klinger.ewm(span=signal, adjust=False).mean()
        histogram = klinger - signal_line
        
        return klinger, signal_line, histogram
    except Exception as e:
        if DEBUG_MODE:
            print(f"❌ Klinger error {symbol}: {e}")
        return None, None, None


def fetch_klinger_data(access_token, instrument_key, symbol):
    """Fetch Klinger data for a symbol"""
    if not ENABLE_KLINGER_FILTER:
        return None
    
    df = get_cached_candles(access_token, symbol, instrument_key)
    if df is None or len(df) < MIN_CANDLES_FOR_KLINGER:
        return None
    
    klinger, signal_line, histogram = calculate_klinger_adaptive(df, symbol)
    if klinger is None or len(klinger) < 2:
        return None
    
    ko_history_len = min(5, len(klinger))
    ko_history = [float(klinger.iloc[-(ko_history_len - i)]) for i in range(ko_history_len - 1, -1, -1)]
    
    return {
        'klinger': float(klinger.iloc[-1]),
        'signal': float(signal_line.iloc[-1]),
        'histogram': float(histogram.iloc[-1]),
        'klinger_prev': float(klinger.iloc[-2]),
        'signal_prev': float(signal_line.iloc[-2]),
        'ko_history': ko_history,
        'last_update': datetime.now(),
        'candle_count': len(df)
    }


# ========== RSI CALCULATION ==========
def calculate_rsi(df, period=14):
    """Calculate RSI"""
    if len(df) < period + 1:
        return None
    delta = df['close'].diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, float('inf'))
    rsi = 100 - (100 / (1 + rs))
    val = rsi.iloc[-1]
    return float(val) if not np.isnan(val) else None


# ========== FII/DII FUNCTIONS ==========
def get_fii_dii_signal(symbol):
    """Get FII/DII signal for symbol"""
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


def extract_fii_dii_data():
    """Extract FII/DII data from MunafaSutra"""
    global FII_DII_DATA, FII_DII_LAST_UPDATE, FII_DII_STRONG_BUY, FII_DII_STRONG_SELL
    
    if not ENABLE_FII_DII_FILTER:
        return
    
    print(f"\n🔍 Extracting FII/DII data...")
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    try:
        response = requests.get(FII_DII_URL, headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        table = soup.find('table')
        if not table:
            print("⚠️ FII/DII table not found")
            return
        
        rows = table.find_all('tr')[1:100]
        for row in rows:
            cols = row.find_all('td')
            if len(cols) >= 5:
                symbol_cell = cols[0]
                link = symbol_cell.find('a')
                text = link.get_text(strip=True) if link else symbol_cell.get_text(strip=True)
                if '(' in text and ')' in text:
                    symbol = text.split('(')[-1].replace(')', '').strip()
                else:
                    continue
                
                stock = {
                    'Symbol': symbol,
                    'FII_DII_Cash': cols[1].get_text(strip=True),
                    'FII_DII_FNO': cols[2].get_text(strip=True),
                }
                FII_DII_DATA[symbol] = stock
        
        FII_DII_STRONG_BUY = set(
            s for s, d in FII_DII_DATA.items() 
            if d['FII_DII_Cash'] == 'Bought' and d['FII_DII_FNO'] == 'Bought'
        )
        FII_DII_STRONG_SELL = set(
            s for s, d in FII_DII_DATA.items() 
            if d['FII_DII_Cash'] == 'Sold' and d['FII_DII_FNO'] == 'Sold'
        )
        
        FII_DII_LAST_UPDATE = datetime.now()
        print(f"✅ FII/DII: {len(FII_DII_STRONG_BUY)} strong buy, {len(FII_DII_STRONG_SELL)} strong sell")
        
    except Exception as e:
        print(f"⚠️ FII/DII error: {e}")


# ========== INITIALIZATION ==========
def initialize_levels(access_token, keys, symbols):
    """Initialize R3 levels with volume and Klinger data"""
    global R3_LEVELS, SYMBOL_TO_ISIN, ISIN_TO_SYMBOL, VOLUME_DATA
    
    ref = previous_trading_day()
    print(f"\n📊 Initializing {len(keys)} stocks using {ref} data...")
    
    ok = volf = 0
    
    for i, key in enumerate(keys):
        if i % 50 == 0:
            print(f" Progress: {i}/{len(keys)}")
        
        symbol = symbols.get(key, key.split('|')[-1].split(':')[-1])
        
        # Get volume data
        df = get_cached_candles(access_token, symbol, key)
        if df is None or df.empty:
            volf += 1
            continue
        
        weekday_data = df[df['date'].dt.weekday < 5]
        if len(weekday_data) < 20:
            volf += 1
            continue
        
        avg_vol = weekday_data['volume'].tail(20).mean()
        if not pd.notna(avg_vol) or avg_vol <= 0 or avg_vol < MIN_AVG_VOLUME:
            volf += 1
            continue
        
        # Get OHLC
        ohlc = fetch_historical_ohlc(access_token, key, ref)
        if not ohlc:
            if not df.empty:
                row = df.iloc[-1]
                ohlc = {
                    'date': row['date'],
                    'open': float(row['open']),
                    'high': float(row['high']),
                    'low': float(row['low']),
                    'close': float(row['close']),
                }
            else:
                volf += 1
                continue
        
        # Get Klinger
        klinger_data = None
        if ENABLE_KLINGER_FILTER:
            klinger_data = fetch_klinger_data(access_token, key, symbol)
        
        nk = norm_key(key)
        R3_LEVELS[nk] = {
            'symbol': symbol,
            'yesterday_high': ohlc['high'],
            'yesterday_low': ohlc['low'],
            'yesterday_close': ohlc['close'],
            'avg_volume_20d': avg_vol,
            'klinger': klinger_data
        }
        VOLUME_DATA[nk] = avg_vol
        ok += 1
    
    SYMBOL_TO_ISIN = {info['symbol']: isin_key for isin_key, info in R3_LEVELS.items()}
    ISIN_TO_SYMBOL = {isin_key: info['symbol'] for isin_key, info in R3_LEVELS.items()}
    
    print(f"\n✅ Initialized: {ok} stocks | Filtered: {volf}")
    print(f"🔥 Klinger available: {sum(1 for r in R3_LEVELS.values() if r.get('klinger'))}")
    
    return ok > 0


# ========== ORB LEVELS CALCULATION ==========
def calculate_orb_levels(symbol, open_price, close_price, high_price, low_price, volume,
                         candle_df=None, instrument_key=None):
    """Calculate ORB levels with Klinger + RSI quality gate"""
    body_size = abs(close_price - open_price)
    body_percent = (body_size / open_price) * 100
    is_bullish = close_price > open_price
    is_bearish = close_price < open_price
    
    if not is_bullish and not is_bearish:
        return None
    
    min_body = ORB_MIN_CANDLE_BODY_LONG if is_bullish else ORB_MIN_CANDLE_BODY_SHORT
    if body_percent < min_body:
        return None
    
    if is_bullish:
        breakout_level = close_price
        stop_level = low_price
        target_level = close_price + (body_size * ORB_TARGET_MULTIPLIER)
        direction = 'BUY'
        signal_type = 'BULLISH_ORB'
    else:
        breakout_level = close_price
        stop_level = high_price
        target_level = close_price - (body_size * ORB_TARGET_MULTIPLIER)
        direction = 'SELL'
        signal_type = 'BEARISH_ORB'
    
    fii_dii_signal = get_fii_dii_signal(symbol)
    
    # FII/DII confidence
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
    
    # Klinger gate
    klinger_info = None
    if ORB_ENABLE_KLINGER_GATE:
        klinger_info = R3_LEVELS.get(instrument_key, {}).get('klinger')
        ko = klinger_info.get('klinger') if klinger_info else None
        if ko is not None:
            if is_bullish and ko < 0:
                if confidence != 'VERY_HIGH':
                    if DEBUG_MODE:
                        print(f"⛔ ORB KLINGER: {symbol} LONG suppressed (KO={ko:,.0f} < 0)")
                    return None
            elif not is_bullish and ko > 0:
                if confidence != 'VERY_HIGH':
                    if DEBUG_MODE:
                        print(f"⛔ ORB KLINGER: {symbol} SHORT suppressed (KO={ko:,.0f} > 0)")
                    return None
    
    # RSI gate
    rsi_value = None
    if ORB_ENABLE_RSI_GATE and candle_df is not None and len(candle_df) >= 15:
        try:
            rsi_value = calculate_rsi(candle_df, period=14)
        except Exception:
            rsi_value = None
    
    if ORB_ENABLE_RSI_GATE and rsi_value is not None:
        if is_bullish and rsi_value < ORB_RSI_LONG_MIN:
            if confidence != 'VERY_HIGH':
                return None
        elif not is_bullish and rsi_value > ORB_RSI_SHORT_MAX:
            if confidence != 'VERY_HIGH':
                return None
    
    risk = abs(breakout_level - stop_level)
    reward = abs(target_level - breakout_level)
    if risk <= 0:
        return None
    
    ko_snap = klinger_info.get('klinger') if klinger_info else None
    
    return {
        'symbol': symbol,
        'instrument_key': instrument_key,
        'timestamp': datetime.now(),
        'signal_type': signal_type,
        'direction': direction,
        'open': open_price,
        'close': close_price,
        'high': high_price,
        'low': low_price,
        'body_size': body_size,
        'body_percent': body_percent,
        'breakout_level': breakout_level,
        'stop_level': stop_level,
        'target_level': target_level,
        'volume': volume,
        'is_bullish': is_bullish,
        'risk': risk,
        'reward': reward,
        'risk_reward': reward / risk,
        'fii_dii_signal': fii_dii_signal,
        'confidence': confidence,
        'rsi_at_signal': rsi_value,
        'klinger_at_signal': ko_snap,
    }


# ========== ORB PROCESSING ==========
def process_first_candles(access_token, live_data, late_pass=False):
    """Build ORB signals from first 15-minute candle"""
    global ORB_SIGNALS, ORB_PROCESSED_TODAY, ORB_LATE_CHECKED
    
    if not late_pass:
        print(f"\n{'='*80}")
        print("📊 PROCESSING FIRST 15-MINUTE CANDLES FOR ORB")
        print(f"{'='*80}\n")
        ORB_LATE_CHECKED.clear()
    else:
        if not ORB_LATE_CHECKED:
            return
        print(f"\n🔄 ORB late pass — retrying {len(ORB_LATE_CHECKED)} symbols")
    
    orb_count = 0
    very_high = high = 0
    
    candidates = (
        {sk: live_data[sk] for sk in list(ORB_LATE_CHECKED) if sk in live_data}
        if late_pass else live_data
    )
    
    for symbol_key, data in candidates.items():
        try:
            symbol = ISIN_TO_SYMBOL.get(symbol_key, symbol_key)
            ltp = data.get('ltp', 0)
            volume = data.get('volume', 0)
            
            if volume == 0:
                if not late_pass:
                    ORB_LATE_CHECKED.add(symbol_key)
                continue
            
            ORB_LATE_CHECKED.discard(symbol_key)
            
            open_price = data.get('open', ltp)
            close_price = ltp
            high_price = data.get('high', ltp)
            low_price = data.get('low', ltp)
            
            # Get RSI from daily candles
            df = get_cached_candles(access_token, symbol, symbol_key)
            
            orb_signal = calculate_orb_levels(
                symbol, open_price, close_price, high_price, low_price, volume,
                candle_df=df, instrument_key=symbol_key
            )
            
            if orb_signal:
                ORB_SIGNALS[symbol] = orb_signal
                orb_count += 1
                if orb_signal['confidence'] == 'VERY_HIGH':
                    very_high += 1
                elif orb_signal['confidence'] == 'HIGH':
                    high += 1
                log_orb_signal(orb_signal)
                
                rsi_str = f"RSI={orb_signal['rsi_at_signal']:.1f}" if orb_signal['rsi_at_signal'] else "RSI=N/A"
                ko = orb_signal['klinger_at_signal']
                ko_str = f"KO={ko/1e6:.1f}M" if ko is not None else "KO=N/A"
                tag = " [LATE]" if late_pass else ""
                
                print(f"✅{tag} {symbol:12} | {orb_signal['signal_type']:15} | "
                      f"{orb_signal['confidence']:10} | FII: {orb_signal['fii_dii_signal']:12} | "
                      f"R:R {orb_signal['risk_reward']:.2f}:1 | {rsi_str} | {ko_str}")
        except Exception as e:
            if DEBUG_MODE:
                print(f"ORB Error {symbol_key}: {e}")
    
    ORB_PROCESSED_TODAY = True
    print(f"\n✅ Processed {orb_count} ORB signals | VERY HIGH: {very_high} | HIGH: {high}")


# ========== ORB BREAKOUT MONITORING ==========
def check_orb_breakout(symbol, current_price, current_volume, live_data):
    """Check if ORB signal has broken out"""
    if symbol not in ORB_SIGNALS or symbol in ORB_ALERTED_STOCKS:
        return None
    
    orb = ORB_SIGNALS[symbol]
    now = datetime.now()
    market_open_930 = now.replace(hour=9, minute=30, second=0, microsecond=0)
    minutes_since_930 = (now - market_open_930).total_seconds() / 60
    
    if minutes_since_930 < 0 or minutes_since_930 > ORB_BREAKOUT_WINDOW_MINUTES:
        return None
    
    avg_volume = VOLUME_DATA.get(symbol, {}).get('avg_volume') if isinstance(VOLUME_DATA.get(symbol), dict) else VOLUME_DATA.get(symbol, 0)
    if not avg_volume:
        avg_volume = live_data.get('avg_volume', 0)
    volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0
    
    if avg_volume > 0 and volume_ratio < ORB_VOLUME_CONFIRMATION:
        return None
    
    breakout_signal = None
    if orb['is_bullish'] and current_price > orb['breakout_level'] * 1.001:
        breakout_signal = {
            'symbol': symbol,
            'signal': 'ORB_BREAKOUT',
            'direction': 'BUY',
            'entry_price': current_price,
            'stop_loss': orb['stop_level'],
            'target': orb['target_level'],
            'orb_data': orb,
            'volume_ratio': volume_ratio,
            'confidence': orb['confidence'],
            'fii_dii_signal': orb['fii_dii_signal'],
            'risk': orb['risk'],
            'reward': orb['reward'],
            'risk_reward': orb['risk_reward'],
            'entry_type': 'ORB_BULLISH'
        }
    elif not orb['is_bullish'] and current_price < orb['breakout_level'] * 0.999:
        breakout_signal = {
            'symbol': symbol,
            'signal': 'ORB_BREAKDOWN',
            'direction': 'SELL',
            'entry_price': current_price,
            'stop_loss': orb['stop_level'],
            'target': orb['target_level'],
            'orb_data': orb,
            'volume_ratio': volume_ratio,
            'confidence': orb['confidence'],
            'fii_dii_signal': orb['fii_dii_signal'],
            'risk': orb['risk'],
            'reward': orb['reward'],
            'risk_reward': orb['risk_reward'],
            'entry_type': 'ORB_BEARISH'
        }
    
    return breakout_signal


# ========== OPTION SELECTION ==========
def select_option_contract(trader, underlying_key, symbol, option_type):
    """Select option contract for the trade"""
    underlying_key = norm_key(underlying_key)
    
    # Get spot price
    spot_price = trader.get_ltp(underlying_key)
    if not spot_price:
        info = R3_LEVELS.get(underlying_key)
        if info and info.get('yesterday_close'):
            spot_price = info['yesterday_close']
            print(f"⚠️ Using yesterday close: {spot_price}")
        else:
            print(f"⚠️ No spot for {symbol}")
            return None
    
    # Get option chain
    option_chain = trader.get_option_chain(underlying_key)
    if not option_chain or option_chain.get("status") != "success" or not option_chain.get("data"):
        print(f"❌ No option chain for {symbol}")
        return None
    
    contracts = option_chain["data"]
    today = datetime.now().date()
    valid_contracts = []
    
    for c in contracts:
        expiry_str = c.get("expiry", "")
        if not expiry_str or c.get("instrument_type") != option_type:
            continue
        try:
            c["expiry_date"] = datetime.strptime(expiry_str, "%Y-%m-%d")
            if c["expiry_date"].date() == today:
                continue
            valid_contracts.append(c)
        except:
            continue
    
    if not valid_contracts:
        print(f"❌ No {option_type} contracts for {symbol}")
        return None
    
    # Sort by expiry and select nearest
    valid_contracts.sort(key=lambda x: x["expiry_date"])
    nearest_contracts = [c for c in valid_contracts if c["expiry_date"] == valid_contracts[0]["expiry_date"]]
    
    # Select ATM strike
    strikes = sorted({c["strike_price"] for c in nearest_contracts})
    if not strikes:
        return None
    
    atm_strike = min(strikes, key=lambda x: abs(x - spot_price))
    
    for c in nearest_contracts:
        if c["strike_price"] == atm_strike:
            # Get premium
            premium = trader.get_ltp(c["instrument_key"])
            if not premium:
                premium = spot_price * 0.02  # Fallback estimate
            
            print(f"\n✅ Option: {c['trading_symbol']}")
            print(f"   Strike: {c['strike_price']} | Expiry: {c['expiry']}")
            print(f"   Premium: ₹{premium:.2f}")
            
            return {
                'instrument_key': c['instrument_key'],
                'symbol': c['trading_symbol'],
                'strike': c['strike_price'],
                'lot_size': c['lot_size'],
                'premium': premium,
                'expiry': c['expiry']
            }
    
    return None


# ========== ORDER PLACEMENT ==========
def place_orb_order(signal, trader):
    """Place ORB option order"""
    global ORB_ORDER_COUNT, DAILY_ORDER_COUNT, LAST_ORDER_TIME
    
    symbol = signal['symbol']
    underlying_key = signal.get('instrument_key')
    direction = signal['direction']
    
    option_type = 'CE' if direction == 'BUY' else 'PE'
    
    # Select option
    selection = select_option_contract(trader, underlying_key, symbol, option_type)
    if not selection:
        print(f"⚠️ No suitable option for {symbol}")
        return None
    
    option_key = selection['instrument_key']
    total_qty = selection['lot_size'] * ORDER_QUANTITY
    premium = selection['premium']
    
    print(f"\n📊 Placing ORB {direction} order:")
    print(f" Symbol: {symbol} | Option: {selection['symbol']}")
    print(f" Qty: {total_qty} | Premium: ₹{premium:.2f}")
    
    # Use LIMIT order
    limit_price = round(premium * 1.02, 2)
    
    result = trader.place_order(
        instrument_key=option_key,
        quantity=total_qty,
        transaction_type='BUY',
        product=ORDER_PRODUCT,
        order_type='LIMIT',
        price=limit_price
    )
    
    if result.get('status_code') == 200:
        order_id = result['response'].get('data', {}).get('order_id')
        if order_id:
            ORB_ORDER_COUNT += 1
            DAILY_ORDER_COUNT += 1
            LAST_ORDER_TIME[symbol] = datetime.now()
            
            # Place stop loss
            sl_trigger = round(premium * (1 - 0.15), 2)
            sl_limit = round(sl_trigger * 0.99, 2)
            
            print(f"✅ Order placed: {order_id}")
            print(f"🛡️ SL: Trigger ₹{sl_trigger:.2f} | Limit ₹{sl_limit:.2f}")
            
            try:
                trader.place_order(
                    instrument_key=option_key,
                    quantity=total_qty,
                    transaction_type='SELL',
                    product=ORDER_PRODUCT,
                    order_type='SL_LIMIT',
                    price=sl_limit,
                    trigger_price=sl_trigger
                )
            except:
                pass
            
            return order_id
    
    print(f"❌ Order failed: {result}")
    return None


# ========== LOGGING ==========
def log_orb_signal(signal):
    """Log ORB signal to CSV"""
    try:
        with open(ORB_SIGNALS_FILE, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
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
    """Log ORB trade to CSV"""
    try:
        with open(ORB_TRADES_FILE, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
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
    """Send ORB breakout alert with AI analysis"""
    global ORB_ALERTED_STOCKS
    
    symbol = signal['symbol']
    ORB_ALERTED_STOCKS.add(symbol)
    
    print("\n" + "="*80)
    print(f"⚡ ORB SIGNAL: {symbol} ⚡")
    print("="*80)
    print(f"Signal:       {signal['signal']}")
    print(f"Direction:    {signal['direction']}")
    print(f"Confidence:   {signal['confidence']}")
    print(f"FII/DII:      {signal['fii_dii_signal']}")
    print(f"Entry Price:  ₹{signal['entry_price']:.2f}")
    print(f"Stop Loss:    ₹{signal['stop_loss']:.2f}")
    print(f"Target:       ₹{signal['target']:.2f}")
    print(f"R:R Ratio:    {signal['risk_reward']:.2f}:1")
    print("="*80)
    
    # AI Analysis
    if ENABLE_AI_ANALYSIS and _AI_AVAILABLE:
        print("\n🤖 Running AI analysis...")
        ai_decision, ai_score = quick_signal_check(
            symbol,
            signal['direction'],
            signal['risk_reward'],
            signal['confidence']
        )
        print(f"   AI Decision: {ai_decision} (score: {ai_score}/{AI_BUY_THRESHOLD})")
        
        if ai_score < AI_BUY_THRESHOLD:
            print(f"⛔ AI blocked trade - score {ai_score} below threshold {AI_BUY_THRESHOLD}")
            print(f"   Skipping order for {symbol}")
            log_orb_trade(signal, 'SKIPPED_AI')
            return
    
    log_orb_trade(signal, 'ENTRY')
    
    # Place order
    if ENABLE_AUTO_TRADING and trader and ORB_ORDER_COUNT < MAX_ORDERS_PER_DAY:
        # Check order limit
        if symbol in LAST_ORDER_TIME:
            time_since = (datetime.now() - LAST_ORDER_TIME[symbol]).seconds
            if time_since < MIN_ORDER_GAP_SECONDS:
                print(f"⚠️ Too soon for {symbol}")
                return
        
        print(f"\n📤 Placing ORB order...")
        place_orb_order(signal, trader)
    elif ORB_ORDER_COUNT >= MAX_ORDERS_PER_DAY:
        print(f"⚠️ Order limit reached")


# ========== ORB TIME CHECK ==========
def check_orb_time_and_process(access_token, live_data):
    """Check time and process ORB"""
    global ORB_PROCESSED_TODAY, ORB_LATE_CHECKED
    
    if not ENABLE_ORB_STRATEGY:
        return
    
    now = datetime.now()
    current_time = now.strftime("%H:%M")
    market_930 = now.replace(hour=9, minute=30, second=0, microsecond=0)
    cutoff = market_930 + timedelta(minutes=ORB_BREAKOUT_WINDOW_MINUTES)
    
    if current_time < "09:15":
        ORB_PROCESSED_TODAY = False
        ORB_LATE_CHECKED.clear()
    
    # Primary pass
    if current_time >= "09:30" and now < cutoff and not ORB_PROCESSED_TODAY:
        process_first_candles(access_token, live_data, late_pass=False)
    
    # Late pass
    elif ORB_PROCESSED_TODAY and ORB_LATE_CHECKED and current_time >= "09:35" and now < cutoff:
        process_first_candles(access_token, live_data, late_pass=True)


def monitor_orb_breakouts(live_data, trader=None):
    """Monitor for ORB breakouts"""
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
            
            breakout = check_orb_breakout(symbol, ltp, volume, data)
            if breakout:
                send_orb_alert(breakout, trader)
        except Exception as e:
            if DEBUG_MODE:
                print(f"ORB monitor error {symbol_key}: {e}")


# ========== INITIALIZATION ==========
def initialize_orb_csv_files():
    """Initialize ORB CSV files"""
    files_config = [
        (ORB_SIGNALS_FILE, ['Timestamp', 'Symbol', 'Signal_Type', 'Direction', 
                           'Breakout_Level', 'Stop_Level', 'Target_Level', 
                           'Body_Percent', 'Risk_Reward', 'FII_DII_Signal', 'Confidence']),
        (ORB_TRADES_FILE, ['Timestamp', 'Symbol', 'Action', 'Direction', 'Price', 
                          'Stop_Loss', 'Target', 'Volume_Ratio', 'Confidence', 'FII_DII_Signal'])
    ]
    
    for csv_file, headers in files_config:
        if not os.path.exists(csv_file):
            with open(csv_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(headers)


def print_orb_summary():
    """Print ORB summary"""
    print(f"\n{'='*80}")
    print("📊 ORB STRATEGY SUMMARY")
    print(f"{'='*80}")
    print(f"Total ORB Signals: {len(ORB_SIGNALS)}")
    print(f"ORB Alerts:        {len(ORB_ALERTED_STOCKS)}")
    print(f"ORB Orders:         {ORB_ORDER_COUNT}")
    
    if ORB_SIGNALS:
        very_high = sum(1 for s in ORB_SIGNALS.values() if s['confidence'] == 'VERY_HIGH')
        high = sum(1 for s in ORB_SIGNALS.values() if s['confidence'] == 'HIGH')
        bullish = sum(1 for s in ORB_SIGNALS.values() if s['is_bullish'])
        
        print(f"\nConfidence: VERY HIGH={very_high}, HIGH={high}")
        print(f"Direction: Bullish={bullish}, Bearish={len(ORB_SIGNALS)-bullish}")
    print(f"{'='*80}\n")


# ========== MAIN MONITOR ==========
def run_orb_monitor(access_token, keys):
    """Run ORB monitoring loop"""
    global _AI_AVAILABLE
    
    print("\n" + "="*80)
    print("🚀 ORB (Opening Range Breakout) MONITOR STARTED")
    print("="*80)
    print(f"Strategy: First 15-min candle breakout")
    print(f"Breakout window: {ORB_BREAKOUT_WINDOW_MINUTES} min")
    print(f"Volume confirm: {ORB_VOLUME_CONFIRMATION}x")
    print(f"Klinger gate: {'ON' if ORB_ENABLE_KLINGER_GATE else 'OFF'}")
    print(f"RSI gate: {'ON' if ORB_ENABLE_RSI_GATE else 'OFF'}")
    print(f"FII/DII filter: {'ON' if ORB_ENABLE_FII_DII_FILTER else 'OFF'}")
    print(f"AI Analysis: {'ON' if ENABLE_AI_ANALYSIS else 'OFF'}")
    print("="*80 + "\n")
    
    # Initialize
    initialize_orb_csv_files()
    trader = UpstoxTrader(access_token) if ENABLE_AUTO_TRADING else None
    
    if ENABLE_FII_DII_FILTER:
        extract_fii_dii_data()
    
    # Start AI Assistant
    if ENABLE_AI_ANALYSIS and _AI_AVAILABLE:
        print(f"\n{ai_status()}")
        start_ai_assistant()
        
        # Get initial market sentiment
        print("\n📊 Fetching AI market sentiment...")
        sentiment = ai_market_check()
        if sentiment and len(sentiment) < 500:
            print(f"Market Sentiment:\n{sentiment}")
    
    scan_count = 0
    
    try:
        while True:
            scan_count += 1
            current_time = datetime.now()
            current_time_str = current_time.strftime("%H:%M:%S")
            
            print(f"\n🔄 ORB Scan #{scan_count} | {current_time_str}")
            
            # Market timing
            if current_time_str < "09:15":
                print("⏳ Before market open...")
                time.sleep(30)
                continue
            
            if current_time_str >= "15:30":
                print("💤 Market closed")
                print_orb_summary()
                break
            
            if not is_market_stabilized():
                print(f"⏳ Market stabilizing...")
                time.sleep(30)
                continue
            
            # Fetch live data
            try:
                live_data = get_live_prices_batch(access_token, keys)
            except Exception as e:
                print(f"⚠️ Data fetch error: {e}")
                time.sleep(30)
                continue
            
            # Process ORB
            if ENABLE_ORB_STRATEGY:
                check_orb_time_and_process(access_token, live_data)
                monitor_orb_breakouts(live_data, trader)
            
            time.sleep(30)
            
    except KeyboardInterrupt:
        print("\n\n⚡ Stopping ORB monitor...")
        print_orb_summary()


# ========== MAIN ENTRY ==========
def main():
    """Main entry point"""
    print("="*80)
    print("ORB (Opening Range Breakout) Trading Strategy")
    print("="*80)
    
    # Get token
    token = get_upstox_token()
    if not token:
        print("\n❌ No valid token. Run main trading bot first to generate token.")
        return
    
    print(f"\n✅ Token validated")
    
    # Get stock list
    keys, symbols = get_all_fno_equities(token)
    if not keys:
        print("❌ No stocks found")
        return
    
    # Initialize levels
    success = initialize_levels(token, keys, symbols)
    if not success:
        print("❌ Initialization failed")
        return
    
    # Run ORB monitor
    run_orb_monitor(token, keys)


if __name__ == "__main__":
    main()