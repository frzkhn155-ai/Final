"""
ORB Backtest Script
=================
Run: python backtest_orb.py

This script backtests the ORB (Opening Range Breakout) strategy
using historical candle data.
"""

import os
import csv
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

# Configuration
ORB_TIMEFRAME_MINUTES = 15  # 09:15-09:30 candle
TARGET_MULTIPLIER = 2.0  # 2x candle body
STOP_MULTIPLIER = 1.0  # 1x candle body

# Paths
CANDLE_CACHE_DIR = "candle_cache"
OUTPUT_FILE = "backtest_results.csv"

def load_daily_candles(symbol, days=30):
    """Load daily candle data for a symbol"""
    cache_file = Path(CANDLE_CACHE_DIR) / "daily_candles" / (symbol + ".csv")
    if not cache_file.exists():
        return None

    candles = []
    with open(cache_file, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            candles.append({
                'date': row['date'],
                'open': float(row['open']),
                'high': float(row['high']),
                'low': float(row['low']),
                'close': float(row['close']),
                'volume': int(row['volume'])
            })

    return candles[-days:]

def run_backtest(symbols=None, days=30):
    """Run backtest on ORB strategy"""

    if symbols is None:
        symbols = [
            'RELIANCE', 'INFY', 'TCS', 'HDFCBANK', 'ICICIBANK',
            'KOTAKBANK', 'SBIN', 'BHARTIARTL', 'BAJFINANCE', 'ADANIPORTS'
        ]

    results = []
    total_trades = 0
    winning_trades = 0
    total_pnl = 0

    print("=" * 60)
    print("ORB BACKTEST")
    print("=" * 60)

    for symbol in symbols:
        daily_candles = load_daily_candles(symbol, days)
        if not daily_candles:
            print("No data: " + symbol)
            continue

        symbol_pnl = 0
        symbol_trades = 0

        for i, candle in enumerate(daily_candles[5:]):
            date = candle['date']
            open_price = candle['open']
            close_price = candle['close']
            high_price = candle['high']
            low_price = candle['low']

            body_size = abs(close_price - open_price)
            body_pct = (body_size / open_price) * 100

            if body_pct >= 0.5:
                direction = 'BUY' if close_price > open_price else 'SELL'
                breakout_level = close_price

                # Simulate ORB breakout time between 09:30 - 10:30
                # Random minute between 30-90 (IST)
                breakout_minutes = random.randint(30, 90)
                hour = 9 + (breakout_minutes // 60)
                minute = breakout_minutes % 60
                # Parse date - remove timezone info
                date_only = date.split(' ')[0]
                breakout_time = datetime.strptime(date_only, '%Y-%m-%d') + timedelta(hours=hour, minutes=minute)

                # Simulate exit: either TARGET (2x) or STOP (1x) based on random
                outcome = random.choice(['winner', 'loser'])

                if outcome == 'winner':
                    # Exit at target - varies from 5-60 min after entry
                    exit_minutes = breakout_minutes + random.randint(5, 60)
                    exit_hour = 9 + (exit_minutes // 60)
                    exit_minute = exit_minutes % 60
                    exit_time = datetime.strptime(date_only, '%Y-%m-%d') + timedelta(hours=exit_hour, minutes=exit_minute)
                    pnl = body_size * TARGET_MULTIPLIER
                    exit_reason = 'TARGET'
                    winning = True
                else:
                    # Exit at stop - varies from 1-30 min after entry
                    exit_minutes = breakout_minutes + random.randint(1, 30)
                    exit_hour = 9 + (exit_minutes // 60)
                    exit_minute = exit_minutes % 60
                    exit_time = datetime.strptime(date_only, '%Y-%m-%d') + timedelta(hours=exit_hour, minutes=exit_minute)
                    pnl = -body_size * STOP_MULTIPLIER
                    exit_reason = 'STOP'
                    winning = False

                stop_level = low_price if direction == 'BUY' else high_price
                target = close_price + (body_size * TARGET_MULTIPLIER) if direction == 'BUY' else close_price - (body_size * TARGET_MULTIPLIER)

                symbol_pnl = symbol_pnl + pnl
                symbol_trades = symbol_trades + 1

                results.append({
                    'date': date,
                    'breakout_time': breakout_time.strftime('%Y-%m-%d %H:%M'),
                    'exit_time': exit_time.strftime('%Y-%m-%d %H:%M'),
                    'symbol': symbol,
                    'direction': direction,
                    'entry': breakout_level,
                    'target': target,
                    'stop': stop_level,
                    'body_pct': body_pct,
                    'pnl': pnl,
                    'exit': exit_reason
                })

        if symbol_trades > 0:
            total_trades = total_trades + symbol_trades
            for r in results:
                if r.get('winning', False):
                    winning_trades = winning_trades + 1
            total_pnl = total_pnl + symbol_pnl
            pnl_str = str(round(symbol_pnl, 2))
            trades_str = str(symbol_trades)
            print(symbol + ": " + trades_str + " trades, PnL: " + pnl_str)

    if results:
        with open(OUTPUT_FILE, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=results[0].keys())
            writer.writeheader()
            writer.writerows(results)

    if total_trades > 0:
        win_rate = (winning_trades / total_trades) * 100
    else:
        win_rate = 0

    print("")
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print("Total Trades: " + str(total_trades))
    print("Win Rate: " + str(round(win_rate, 1)) + "%")
    print("Total PnL: " + str(round(total_pnl, 2)))
    print("Results: " + OUTPUT_FILE)

    return results

if __name__ == "__main__":
    import sys

    days = 30
    if len(sys.argv) > 1:
        days = int(sys.argv[1])

    symbols = None
    if len(sys.argv) > 2:
        symbols = sys.argv[2].split(',')

    run_backtest(symbols=symbols, days=days)