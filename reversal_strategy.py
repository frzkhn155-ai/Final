"""
Reversal-mode signal generator for integration with Both4withcache10_headless.py

This module provides:
- find_reversal_signals(candles, params=None) -> list[dict]
- write_signals_csv(signals, filename='reversal_signals.csv')

A reversal signal is generated when price action contradicts the opening range direction.
For example: if the market opened with bullish momentum (ORB_up), a reversal occurs when
price drops back below the opening range, signaling potential exhaustion and downside momentum.
"""

import csv
import os
from datetime import datetime
from typing import List, Dict, Optional


def find_reversal_signals(
    candles: List[Dict],
    params: Optional[Dict] = None
) -> List[Dict]:
    """
    Detect reversal signals from minute-level candles.
    
    A reversal signal is detected when:
    1. The market has established a clear opening range (first N minutes)
    2. Price subsequently moves in the opposite direction with sufficient force
    3. The reversal breaks below/above support/resistance established by the opening range
    
    Args:
        candles: List of candle dicts with keys: timestamp, open, high, low, close, volume
        params: Optional config dict with keys:
                - opening_range_minutes: int (default 15) — lookback window for opening range
                - reversal_threshold_percent: float (default 0.5) — % move required to confirm reversal
                - min_reversal_volume: float (default 0) — minimum volume threshold
    
    Returns:
        List of signal dicts: {timestamp, close, signal_type, reason, strength}
    """
    if not candles or len(candles) < 2:
        return []
    
    params = params or {}
    opening_range_minutes = params.get("opening_range_minutes", 15)
    reversal_threshold_pct = params.get("reversal_threshold_percent", 0.5)
    min_volume = params.get("min_reversal_volume", 0)
    
    signals = []
    
    # Ensure we have enough candles
    if len(candles) < opening_range_minutes + 5:
        return signals
    
    # Extract opening range (first N candles)
    or_candles = candles[:opening_range_minutes]
    or_high = max(c.get("high", c.get("close", 0)) for c in or_candles)
    or_low = min(c.get("low", c.get("close", float("inf"))) for c in or_candles)
    or_close = or_candles[-1].get("close", 0)
    
    # Determine opening range bias
    or_midpoint = (or_high + or_low) / 2
    or_bias = "bullish" if or_close >= or_midpoint else "bearish"
    or_range = or_high - or_low
    
    if or_range == 0:
        return signals
    
    # Scan post-opening-range candles for reversals
    for i in range(opening_range_minutes, len(candles)):
        candle = candles[i]
        current_close = candle.get("close", 0)
        current_low = candle.get("low", current_close)
        current_high = candle.get("high", current_close)
        current_volume = candle.get("volume", 0)
        candle_time = candle.get("timestamp", "")
        
        if current_volume < min_volume:
            continue
        
        # Check for downside reversal (after bullish OR)
        if or_bias == "bullish":
            distance_below_or = or_low - current_low
            pct_move = (distance_below_or / or_range) * 100 if or_range > 0 else 0
            
            if current_close < or_low and pct_move >= reversal_threshold_pct:
                signals.append({
                    "timestamp": candle_time,
                    "close": current_close,
                    "signal_type": "REVERSAL_DOWN",
                    "reason": f"Bearish reversal: broke below OR_LOW ({or_low:.2f}) by {pct_move:.2f}%",
                    "strength": min(100, pct_move * 2),  # simple strength metric
                    "or_high": or_high,
                    "or_low": or_low,
                })
        
        # Check for upside reversal (after bearish OR)
        if or_bias == "bearish":
            distance_above_or = current_high - or_high
            pct_move = (distance_above_or / or_range) * 100 if or_range > 0 else 0
            
            if current_close > or_high and pct_move >= reversal_threshold_pct:
                signals.append({
                    "timestamp": candle_time,
                    "close": current_close,
                    "signal_type": "REVERSAL_UP",
                    "reason": f"Bullish reversal: broke above OR_HIGH ({or_high:.2f}) by {pct_move:.2f}%",
                    "strength": min(100, pct_move * 2),
                    "or_high": or_high,
                    "or_low": or_low,
                })
    
    return signals


def write_signals_csv(
    signals: List[Dict],
    filename: str = "reversal_signals.csv"
) -> None:
    """
    Write reversal signals to a CSV file for logging and review.
    
    Args:
        signals: List of signal dicts from find_reversal_signals()
        filename: Output CSV filename (default: reversal_signals.csv)
    """
    if not signals:
        return
    
    fieldnames = [
        "timestamp",
        "close",
        "signal_type",
        "reason",
        "strength",
        "or_high",
        "or_low",
    ]
    
    # Check if file exists to decide on write mode
    file_exists = os.path.isfile(filename)
    
    try:
        with open(filename, "a" if file_exists else "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerows(signals)
        print(f"✅ Wrote {len(signals)} reversal signal(s) to {filename}")
    except Exception as e:
        print(f"❌ Error writing reversal signals to {filename}: {e}")


def append_to_orb_signals_csv(
    reversal_signal: Dict,
    filename: str = "orb_signals.csv"
) -> None:
    """
    Optional: append a reversal signal to the existing ORB signals CSV for unified logging.
    This preserves your existing ORB CSV format while merging reversal output.
    
    Args:
        reversal_signal: A single signal dict from find_reversal_signals()
        filename: Target CSV filename (should match your ORB signals CSV)
    """
    if not reversal_signal:
        return
    
    # Transform reversal signal to match ORB CSV schema (adapt fieldnames as needed)
    orb_row = {
        "timestamp": reversal_signal.get("timestamp", ""),
        "close": reversal_signal.get("close", ""),
        "signal_type": reversal_signal.get("signal_type", "REVERSAL"),
        "reason": reversal_signal.get("reason", ""),
        "strength": reversal_signal.get("strength", ""),
    }
    
    fieldnames = list(orb_row.keys())
    file_exists = os.path.isfile(filename)
    
    try:
        with open(filename, "a" if file_exists else "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerow(orb_row)
    except Exception as e:
        print(f"⚠️ Could not append reversal signal to {filename}: {e}")
