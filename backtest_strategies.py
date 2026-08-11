#!/usr/bin/env python3
"""
backtest_strategies.py — Standalone historical backtest for the Final bot's
strategies, runnable ANYTIME (before/after market hours, weekends) against
a specific past date. Does NOT touch or import the live trading bot file —
fully self-contained, read-only, places no orders.

═══════════════════════════════════════════════════════════════════════════
IMPORTANT DATA LIMITATION (Upstox platform limit, not a bug in this script)
═══════════════════════════════════════════════════════════════════════════
  • Daily candles: unlimited history available (years back) — S5's SMA-200
    condition and S6's Daily-BB-cross condition can be checked for ANY date.
  • Intraday candles (5-min/15-min/1H, needed for S1-S4 and S6's momentum/
    execution stages): Upstox's historical-candle date-range endpoint only
    returns roughly the LAST 30 CALENDAR DAYS of intraday data. Requesting
    an older date will return an empty/short series — this script detects
    that and tells you plainly instead of pretending it worked.

Usage:
    python backtest_strategies.py --date 2026-08-01 --symbol RELIANCE
    python backtest_strategies.py --date 2026-08-01                # scan all F&O
    python backtest_strategies.py --date 2026-08-01 --strategy s6  # just S6
    python backtest_strategies.py --date 2026-08-01 --strategy all --out report.csv

Requires: UPSTOX_TOKEN env var (a valid, non-expired access token — this
script does NOT do OAuth login; grab a fresh token from a recent bot run
or generate one manually via the Upstox developer portal).
"""

import os
import sys
import csv
import time
import argparse
from datetime import datetime, timedelta

import requests
import pandas as pd

# ═══════════════════════════════════════════════════════════════════════════
#  CONFIG (mirrors the live bot's defaults — edit here to match your tuning)
# ═══════════════════════════════════════════════════════════════════════════

# S6: Multi-timeframe momentum
S6_BB_PERIOD           = 20
S6_RSI_PERIOD           = 14
S6_RSI_LONG_THRESHOLD   = 60
S6_RSI_SHORT_THRESHOLD  = 40
S6_MIN_DAILY_CANDLES    = 30

# S5: SMA-200 proximity + short-term high/low
SMA200_PERIOD           = 200
SMA200_PROXIMITY_PCT    = 2.0
SMA200_SHORT_HIGH_DAYS  = 3
SMA200_WEEK_HIGH_DAYS   = 5
SMA200_MIN_DAILY_CANDLES = 200

REQUEST_TIMEOUT = 15


# ═══════════════════════════════════════════════════════════════════════════
#  DATA FETCHING (thin, read-only wrappers around Upstox's historical API)
# ═══════════════════════════════════════════════════════════════════════════

def get_session(token):
    s = requests.Session()
    s.headers.update({
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
    })
    return s


def fetch_daily_candles(session, instrument_key, to_date, days_back=420):
    """Daily candles — no meaningful history limit on Upstox's side."""
    from_date = (to_date - timedelta(days=days_back)).strftime("%Y-%m-%d")
    to_str = to_date.strftime("%Y-%m-%d")
    url = f"https://api.upstox.com/v2/historical-candle/{instrument_key}/day/{to_str}/{from_date}"
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            return None
        candles = resp.json().get("data", {}).get("candles", [])
        if not candles:
            return None
        df = pd.DataFrame(candles, columns=["date", "open", "high", "low", "close", "volume", "oi"])
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
        df = df.sort_values("date").reset_index(drop=True)
        return df
    except Exception:
        return None


def fetch_intraday_candles(session, instrument_key, to_date, timeframe="5minute", days_back=5):
    """Intraday candles — Upstox limits this to roughly the last 30 calendar
    days from TODAY (not from `to_date`). If to_date is older than that
    window, this will return None or a very short series — the caller must
    check for that and report it, not silently proceed.
    """
    from_date = (to_date - timedelta(days=days_back)).strftime("%Y-%m-%d")
    to_str = to_date.strftime("%Y-%m-%d")
    url = f"https://api.upstox.com/v2/historical-candle/{instrument_key}/{timeframe}/{to_str}/{from_date}"
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            return None, resp.status_code
        candles = resp.json().get("data", {}).get("candles", [])
        if not candles:
            return None, 200   # request succeeded but Upstox has no data this far back
        df = pd.DataFrame(candles, columns=["date", "open", "high", "low", "close", "volume", "oi"])
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
        df = df.sort_values("date").reset_index(drop=True)
        return df, 200
    except Exception as e:
        return None, str(e)


def get_fo_stock_universe(session):
    """Same F&O universe logic as the live bot's get_all_fno_equities()."""
    url = "https://assets.upstox.com/market-quote/instruments/exchange/complete.csv.gz"
    try:
        df = pd.read_csv(url, compression="gzip")
        fo = df[df["exchange"] == "NSE_FO"]
        fo_symbols = (fo["tradingsymbol"]
                      .str.replace(r"\d{2}[A-Z]{3}\d{2,4}.*", "", regex=True)
                      .str.strip().unique())
        fo_symbols = set(s for s in fo_symbols if s)
        eq = df[(df["exchange"] == "NSE_EQ") & (df["tradingsymbol"].isin(fo_symbols))].copy()
        eq = eq.drop_duplicates(subset=["tradingsymbol"])
        return dict(zip(eq["tradingsymbol"], eq["instrument_key"]))
    except Exception as e:
        print(f"❌ Could not download F&O universe: {e}")
        return {}


# ═══════════════════════════════════════════════════════════════════════════
#  INDICATORS (same formulas as the live bot)
# ═══════════════════════════════════════════════════════════════════════════

def calculate_rsi(df, period=14):
    if df is None or len(df) < period + 1:
        return None
    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0.0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(period).mean()
    rs = gain / loss.replace(0, 1e-10)
    rsi = 100 - (100 / (1 + rs))
    val = rsi.iloc[-1]
    return float(val) if pd.notna(val) else None


def resample_to_tf(df5, rule):
    """Resample a date-indexed 5-min OHLCV df to a coarser timeframe."""
    if df5 is None or len(df5) < 2:
        return None
    d = df5.set_index("date")[["open", "high", "low", "close", "volume"]]
    out = d.resample(rule).agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum"
    }).dropna().reset_index()
    return out if len(out) else None


# ═══════════════════════════════════════════════════════════════════════════
#  STRATEGY LOGIC (self-contained reimplementations, matching the live bot)
# ═══════════════════════════════════════════════════════════════════════════

def check_s5_sma200(symbol, daily_df, backtest_date):
    """S5: SMA-200 proximity/cross + 3-day/1-week high-low breakout.
    Uses ONLY daily candles — works for any historical date, no limit.
    """
    if daily_df is None or len(daily_df) < SMA200_MIN_DAILY_CANDLES + 6:
        return None, "insufficient daily history"

    df = daily_df[daily_df["date"].dt.date <= backtest_date].copy()
    if len(df) < SMA200_MIN_DAILY_CANDLES + 6:
        return None, "insufficient daily history as-of this date"

    closes = df["close"]
    sma200 = closes.rolling(SMA200_PERIOD).mean()
    if pd.isna(sma200.iloc[-1]):
        return None, "SMA200 not yet computable"

    close_today = float(closes.iloc[-1])
    sma_today = float(sma200.iloc[-1])
    dist_pct = abs(close_today - sma_today) / sma_today * 100 if sma_today else 999
    near_sma = dist_pct <= SMA200_PROXIMITY_PCT
    if not near_sma:
        return None, f"not near SMA200 ({dist_pct:.2f}% away)"

    direction = "LONG" if close_today >= sma_today else "SHORT"
    last_3d = closes.tail(SMA200_SHORT_HIGH_DAYS + 1).iloc[:-1]
    last_5d = closes.tail(SMA200_WEEK_HIGH_DAYS + 1).iloc[:-1]

    if direction == "LONG":
        if close_today > last_3d.max():
            return {"strategy": "S5_SMA200", "symbol": symbol, "direction": "CE",
                    "trigger": "3-day high", "price": close_today, "sma200": sma_today}, None
        if close_today > last_5d.max():
            return {"strategy": "S5_SMA200", "symbol": symbol, "direction": "CE",
                    "trigger": "1-week high", "price": close_today, "sma200": sma_today}, None
    else:
        if close_today < last_3d.min():
            return {"strategy": "S5_SMA200", "symbol": symbol, "direction": "PE",
                    "trigger": "3-day low", "price": close_today, "sma200": sma_today}, None
        if close_today < last_5d.min():
            return {"strategy": "S5_SMA200", "symbol": symbol, "direction": "PE",
                    "trigger": "1-week low", "price": close_today, "sma200": sma_today}, None

    return None, f"near SMA200 but no 3d/5d {'high' if direction=='LONG' else 'low'} break"


def check_s6_mtf_momentum(symbol, daily_df, df5, backtest_date):
    """S6: Daily BB-mid cross + 1H RSI + 15-min body break of previous day.
    Needs intraday data — subject to the ~30-day Upstox history limit.
    """
    if daily_df is None or len(daily_df) < S6_MIN_DAILY_CANDLES + 2:
        return None, "insufficient daily history"

    ddf = daily_df[daily_df["date"].dt.date <= backtest_date].copy()
    if len(ddf) < S6_MIN_DAILY_CANDLES + 2:
        return None, "insufficient daily history as-of this date"

    closes = ddf["close"]
    mid_bb = closes.rolling(S6_BB_PERIOD).mean()
    if pd.isna(mid_bb.iloc[-1]) or pd.isna(mid_bb.iloc[-2]):
        return None, "Daily BB not yet computable"

    close_today, close_yday = float(closes.iloc[-1]), float(closes.iloc[-2])
    mid_today, mid_yday = float(mid_bb.iloc[-1]), float(mid_bb.iloc[-2])
    crossed_up = close_yday < mid_yday and close_today > mid_today
    crossed_down = close_yday > mid_yday and close_today < mid_today
    if not (crossed_up or crossed_down):
        return None, "no Daily BB-mid cross on this date"

    direction = "LONG" if crossed_up else "SHORT"
    prev_day = ddf.iloc[-1]
    body_high = max(float(prev_day["open"]), float(prev_day["close"]))
    body_low = min(float(prev_day["open"]), float(prev_day["close"]))

    if df5 is None or len(df5) < 20:
        return None, f"ARMED {direction} (Daily BB cross confirmed) — but no intraday " \
                     f"data available to check Stage 2 (likely older than Upstox's ~30-day intraday limit)"

    df1h = resample_to_tf(df5, "1h")
    if df1h is None or len(df1h) < S6_RSI_PERIOD + 2:
        return None, f"ARMED {direction} — insufficient 1H bars for RSI"
    rsi_1h = calculate_rsi(df1h, period=S6_RSI_PERIOD)
    if rsi_1h is None:
        return None, f"ARMED {direction} — RSI not computable"

    if direction == "LONG" and rsi_1h <= S6_RSI_LONG_THRESHOLD:
        return None, f"ARMED LONG but 1H RSI {rsi_1h:.1f} <= {S6_RSI_LONG_THRESHOLD} (momentum not confirmed)"
    if direction == "SHORT" and rsi_1h >= S6_RSI_SHORT_THRESHOLD:
        return None, f"ARMED SHORT but 1H RSI {rsi_1h:.1f} >= {S6_RSI_SHORT_THRESHOLD} (momentum not confirmed)"

    df15 = resample_to_tf(df5, "15min")
    if df15 is None or len(df15) < 2:
        return None, f"ARMED {direction}, RSI confirmed ({rsi_1h:.1f}) — insufficient 15-min bars"
    last15 = df15.iloc[-1]

    if direction == "LONG" and float(last15["close"]) > body_high:
        return {"strategy": "S6_MTF_MOMENTUM", "symbol": symbol, "direction": "CE",
                "trigger": "15M close > prev-day body high", "price": float(last15["close"]),
                "rsi_1h": round(rsi_1h, 1), "prev_day_body_high": body_high}, None
    if direction == "SHORT" and float(last15["close"]) < body_low:
        return {"strategy": "S6_MTF_MOMENTUM", "symbol": symbol, "direction": "PE",
                "trigger": "15M close < prev-day body low", "price": float(last15["close"]),
                "rsi_1h": round(rsi_1h, 1), "prev_day_body_low": body_low}, None

    return None, f"ARMED {direction}, RSI confirmed ({rsi_1h:.1f}) — 15M hasn't broken " \
                 f"prev-day body {'high' if direction=='LONG' else 'low'} yet"


# ═══════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(description="Backtest Final bot strategies against a historical date")
    ap.add_argument("--date", required=True, help="Date to backtest, YYYY-MM-DD")
    ap.add_argument("--symbol", help="Single symbol to test (e.g. RELIANCE). Default: scan all F&O")
    ap.add_argument("--strategy", default="all", choices=["all", "s5", "s6"],
                     help="Which strategy to backtest (default: all)")
    ap.add_argument("--out", help="Optional CSV file to write results to")
    ap.add_argument("--max-symbols", type=int, default=0,
                     help="Limit number of symbols scanned (0 = no limit, useful for a quick smoke test)")
    args = ap.parse_args()

    token = os.environ.get("UPSTOX_TOKEN", "")
    if not token:
        print("❌ UPSTOX_TOKEN environment variable not set.")
        print("   export UPSTOX_TOKEN='your-token-here'  (or set it in your shell profile)")
        sys.exit(1)

    try:
        backtest_date = datetime.strptime(args.date, "%Y-%m-%d").date()
    except ValueError:
        print("❌ --date must be in YYYY-MM-DD format")
        sys.exit(1)

    today = datetime.now().date()
    intraday_age_days = (today - backtest_date).days
    print(f"{'='*90}")
    print(f"BACKTEST — {backtest_date} | strategy={args.strategy}")
    print(f"{'='*90}")
    if intraday_age_days > 28:
        print(f"⚠️  {backtest_date} is {intraday_age_days} days ago — Upstox's intraday history "
              f"limit (~30 days) means S6's 1H/15M stages will likely have NO data.")
        print(f"    S5 (daily-only) is unaffected and will work normally.\n")

    session = get_session(token)
    to_dt = datetime.combine(backtest_date, datetime.min.time())

    # Build the symbol list
    if args.symbol:
        universe = get_fo_stock_universe(session)
        ikey = universe.get(args.symbol.upper())
        if not ikey:
            print(f"❌ Symbol '{args.symbol}' not found in F&O universe (or not currently F&O-listed)")
            sys.exit(1)
        symbols = {args.symbol.upper(): ikey}
    else:
        print("📥 Downloading F&O universe...")
        symbols = get_fo_stock_universe(session)
        if args.max_symbols > 0:
            symbols = dict(list(symbols.items())[:args.max_symbols])
        print(f"   {len(symbols)} symbols to scan\n")

    results = []
    no_data_count = 0

    for i, (symbol, ikey) in enumerate(symbols.items(), 1):
        if len(symbols) > 1 and i % 25 == 0:
            print(f"   ...scanned {i}/{len(symbols)}")

        daily_df = fetch_daily_candles(session, ikey, to_dt) if args.strategy in ("all", "s5", "s6") else None
        if daily_df is None:
            no_data_count += 1
            continue

        df5 = None
        if args.strategy in ("all", "s6"):
            df5, status = fetch_intraday_candles(session, ikey, to_dt, timeframe="5minute", days_back=3)

        if args.strategy in ("all", "s5"):
            sig, reason = check_s5_sma200(symbol, daily_df, backtest_date)
            if sig:
                results.append(sig)
                print(f"🟢 S5 SIGNAL: {symbol} {sig['direction']} — {sig['trigger']} "
                      f"@ ₹{sig['price']:.2f} (SMA200 ₹{sig['sma200']:.2f})")
            elif args.symbol:  # only print rejection reasons in single-symbol mode (avoid spam)
                print(f"   S5: {reason}")

        if args.strategy in ("all", "s6"):
            sig, reason = check_s6_mtf_momentum(symbol, daily_df, df5, backtest_date)
            if sig:
                results.append(sig)
                print(f"🟢 S6 SIGNAL: {symbol} {sig['direction']} — {sig['trigger']} @ ₹{sig['price']:.2f} "
                      f"(1H RSI {sig['rsi_1h']})")
            elif args.symbol:
                print(f"   S6: {reason}")

        time.sleep(0.15)   # gentle on the API — avoid rate limiting across a full universe scan

    print(f"\n{'='*90}")
    print(f"DONE — {len(results)} signal(s) found across {len(symbols)} symbol(s) "
          f"({no_data_count} had no daily data available)")
    print(f"{'='*90}")
    for r in results:
        print(f"  {r['strategy']:16} {r['symbol']:15} {r['direction']:3} {r['trigger']}")

    if args.out and results:
        with open(args.out, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=sorted({k for r in results for k in r}))
            w.writeheader()
            w.writerows(results)
        print(f"\n📄 Results written to {args.out}")


if __name__ == "__main__":
    main()
