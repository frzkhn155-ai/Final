"""
Integration patch for Reversal Strategy + STRATEGY environment variable dispatch

Add this snippet to Both4withcache10_headless.py in the main loop where 
strategies are decided. Find the section that decides which flows to run
(typically around the main entry point or strategy dispatch function) 
and insert this code.

Example location (search for this comment in your bot):
    # === STRATEGY DISPATCHER ===
    # or near: if current_time >= "09:30" and ...

Insert BEFORE or AROUND the existing strategy dispatch logic.
"""

import os

# At the very top of the file (after other imports):
try:
    from reversal_strategy import find_reversal_signals, write_signals_csv, append_to_orb_signals_csv
    _HAS_REVERSAL = True
except ImportError:
    _HAS_REVERSAL = False
    print("⚠️ reversal_strategy module not found — Reversal mode will be skipped")

# ============================================================================
# STRATEGY DISPATCH FUNCTION (insert into your main loop / strategy decider)
# ============================================================================

def run_strategy_dispatch(symbol, candles, trader=None, **kwargs):
    """
    Dispatch to appropriate strategy based on STRATEGY env var.
    
    Supported values:
      - "orb"       → Run ORB strategy only
      - "reversal"  → Run Reversal strategy only  
      - "all"       → Run both strategies (default)
      - ""          → Default to "all"
    """
    strategy = os.environ.get("STRATEGY", "all").strip().lower()
    
    print(f"📊 Running strategy: {strategy or 'all (default)'}")
    
    # =================================================================
    # ORB STRATEGY BLOCK
    # =================================================================
    if strategy in ("all", "orb"):
        print("🔷 ORB Strategy: Enabled")
        # Call your existing ORB logic here
        # Example:
        # run_orb_for_symbol(symbol, candles, trader)
        # or however your bot currently runs ORB
        pass
    
    # =================================================================
    # REVERSAL STRATEGY BLOCK (NEW)
    # =================================================================
    if strategy in ("all", "reversal"):
        if not _HAS_REVERSAL:
            print("⚠️ Reversal strategy requested but module not found — skipping")
        else:
            print("🔁 Reversal Strategy: Enabled")
            
            # Find reversal signals
            signals = find_reversal_signals(candles, params={
                "opening_range_minutes": 15,      # Match your ORB opening range
                "reversal_threshold_percent": 0.5,  # % move to trigger reversal
                "min_reversal_volume": 500000,    # Minimum volume threshold
            })
            
            if signals:
                print(f"✅ Found {len(signals)} reversal signal(s)")
                
                # Option 1: Write to dedicated reversal CSV
                write_signals_csv(signals, filename="reversal_signals.csv")
                
                # Option 2 (uncomment to merge into ORB signals file):
                # for sig in signals:
                #     append_to_orb_signals_csv(sig)
                
                # Process signals (e.g., place trades)
                for sig in signals:
                    print(f"  📌 {sig['signal_type']}: {sig['reason']} @ {sig['close']}")
                    # Your trade logic here
                    # trader.place_order(...)
            else:
                print("ℹ️ No reversal signals generated")


# ============================================================================
# EXAMPLE INTEGRATION INTO MAIN BOT LOOP
# ============================================================================

def main_bot_loop():
    """
    Example of how to call the strategy dispatcher from your main bot loop.
    Adapt the actual function/symbol/candle names to match your bot.
    """
    
    # Your existing setup...
    # trader = UpstoxTrader(access_token)
    # symbols = ["BANKNIFTY", "NIFTY", ...]
    
    # Get candles for symbol (reuse existing fetch logic)
    # candles = get_candles_for_symbol(symbol, minutes=5)
    
    # Dispatch strategy based on STRATEGY env var
    # run_strategy_dispatch(symbol, candles, trader=trader)


# ============================================================================
# ENVIRONMENT VARIABLE EXAMPLES
# ============================================================================

"""
Run your bot with different strategies:

# ORB only:
export STRATEGY=orb
python Both4withcache10_headless.py

# Reversal only:
export STRATEGY=reversal
python Both4withcache10_headless.py

# Both (default):
export STRATEGY=all
python Both4withcache10_headless.py

# In GitHub Actions workflow (run_bot.yml):
- name: Run Trading Bot
  env:
    STRATEGY: reversal        # or "orb" or "all"
    ...other env vars...
  run: python Both4withcache10_headless.py
"""
