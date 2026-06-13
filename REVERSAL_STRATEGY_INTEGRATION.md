# Reversal Strategy Integration

The opening-range **reversal** strategy (`reversal_strategy.py`) is now wired directly
into `Both4withcache10_headless.py` and selectable via the `STRATEGY` environment
variable. This document describes how the integration works — no manual code edits
are required.

## What the reversal strategy does

A reversal signal fires when price breaks back through the **opening range** against
its initial bias (an exhaustion move):

- Bullish opening range, then price closes **below** `OR_LOW` → `REVERSAL_DOWN`
- Bearish opening range, then price closes **above** `OR_HIGH` → `REVERSAL_UP`

The opening range is the first `REVERSAL_OPENING_RANGE_BARS` candles (default `3`,
i.e. the first ~15 minutes of 5-minute bars). A move only counts once it exceeds
`REVERSAL_THRESHOLD_PERCENT` of the opening-range width.

## How it is wired in

| Piece | Location | Purpose |
|-------|----------|---------|
| `from reversal_strategy import find_latest_reversal_signal` | top of `Both4withcache10_headless.py` (guarded import) | pulls in the detector; degrades gracefully if the module is missing |
| `apply_strategy_selection()` | called at the start of `main()` | maps the `STRATEGY` env var onto the `ENABLE_*` flags |
| `run_reversal_strategy_scan()` | called inside the main loop in `enhanced_monitor()` | scans live candles, logs signals, optionally trades |
| `_reversal_candles_from_df()` | helper | converts the bot's live 5-minute `DataFrame` into the `list[dict]` the module expects |
| `print_reversal_summary()` | end-of-session summary | prints signal/order counts |

The scan reuses the real-time 5-minute candles already built by
`update_realtime_candle()` (via `get_realtime_5min_df`), so it adds **no extra API
calls**. It runs every `REVERSAL_SCAN_INTERVAL_SCANS` main-loop cycles, and each
symbol fires at most once per day (tracked in `REVERSAL_ALERTED`).

## Selecting the strategy

`apply_strategy_selection()` reads `STRATEGY` (default `all`) and toggles the
per-strategy flags. This also makes the existing GitHub Actions strategy dropdown
actually take effect.

| `STRATEGY` value | Effect |
|------------------|--------|
| `all` (default)  | every strategy enabled, **plus** reversal-signal logging |
| `reversal`       | run **only** the reversal strategy |
| `orb`            | run only ORB |
| `r3_s3`          | run only R3/S3 |
| `box`            | run only Box Theory + Midday Box |
| `range`          | run only Range trading |
| `gap`            | run only Gap trading |

Run locally:

```bash
# Reversal only
STRATEGY=reversal python Both4withcache10_headless.py

# Everything (incl. reversal logging) — default
python Both4withcache10_headless.py
```

In GitHub Actions, pick the value from the **"Trading strategy to run"** dropdown
when triggering `run_bot.yml` (the `reversal` option is now available).

## Configuration

All knobs live in the `OPENING-RANGE REVERSAL STRATEGY CONFIG` block in
`Both4withcache10_headless.py`:

```python
ENABLE_REVERSAL_STRATEGY      = False   # toggled on by STRATEGY=all/reversal
ENABLE_REVERSAL_AUTO_TRADING  = False   # default: signal-only (no live orders)
REVERSAL_OPENING_RANGE_BARS   = 3       # first 3 x 5min bars = ~15min opening range
REVERSAL_THRESHOLD_PERCENT    = 0.5     # % of OR range price must exceed to confirm
REVERSAL_MIN_VOLUME           = 0       # per-bar volume floor (0 = disabled)
REVERSAL_MIN_BARS             = 8       # candles required before scanning
REVERSAL_MAX_SYMBOLS          = 40      # cap symbols scanned per cycle
REVERSAL_SCAN_INTERVAL_SCANS  = 4       # scan every N main-loop cycles
REVERSAL_SIGNALS_FILE         = "reversal_signals.csv"
```

### Signal-only vs. live trading

By default `ENABLE_REVERSAL_AUTO_TRADING = False`, so the strategy **only logs
signals** (to `reversal_signals.csv` and the console). To let it place live option
orders (`REVERSAL_DOWN` → PE, `REVERSAL_UP` → CE) through the existing
`place_breakout_order()` pipeline, set:

```python
ENABLE_REVERSAL_AUTO_TRADING = True
```

Reversal orders respect the shared `MAX_ORDERS_PER_DAY` cap and Upstox order-window
guard, just like the other strategies.

## Output

`reversal_signals.csv` columns:

```
Timestamp, Symbol, Signal_Type, Close, Strength, Reason, OR_High, OR_Low
```

## Module API (`reversal_strategy.py`)

```python
find_reversal_signals(candles, params=None) -> list[dict]
find_latest_reversal_signal(candles, params=None) -> dict | None
write_signals_csv(signals, filename="reversal_signals.csv") -> None
append_to_orb_signals_csv(signal, filename="orb_signals.csv") -> None
```

`candles` is a list of dicts with keys `timestamp, open, high, low, close, volume`.
`params` accepts `opening_range_minutes` (measured in candles), `reversal_threshold_percent`
and `min_reversal_volume`.

> `append_to_orb_signals_csv()` is **schema-safe**: when the target file already
> exists it aligns the reversal row to that file's existing header, so it will not
> corrupt the bot's 11-column `orb_signals.csv`.
