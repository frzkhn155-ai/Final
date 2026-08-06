"""scanner/signal_scanner.py

Implements body-only 1-week (5-day) and 2-week (10-day) break scanner with:
 - body-only highs/lows (ignore wicks)
 - buffer (default 0.15%) to avoid whipsaws
 - confirmation over consecutive scans (default 2)
 - one alert per symbol per direction per day

This module is data-provider-agnostic. A simple yfinance-based provider is included for example only.

Usage:
  from scanner.signal_scanner import SignalScanner, YFinanceDataProvider, ConsoleAlertHandler
  scanner = SignalScanner(symbols=[...], data_provider=YFinanceDataProvider(), alert_handler=ConsoleAlertHandler())
  scanner.run_loop(interval_seconds=30)

State is persisted to scanner/alert_state.json by default.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, date
from typing import Any, Dict, List, Optional

import pandas as pd

# Optional runtime dependency. If not present, user should provide a DataProvider.
try:
    import yfinance as yf
except Exception:
    yf = None


DEFAULT_STATE_PATH = "scanner/alert_state.json"


@dataclass
class BreakResult:
    symbol: str
    timeframe: str  # '1w' or '2w'
    direction: str  # 'up' or 'down'
    level: float
    price: float
    confirmed: bool
    buffer_pct: float
    timestamp: str


class DataProvider:
    """Abstract data provider. Implement get_daily_bars and get_latest_intraday_bar."""

    def get_daily_bars(self, symbol: str, days: int = 20) -> pd.DataFrame:
        raise NotImplementedError

    def get_latest_intraday_bar(self, symbol: str, interval: str = "1m") -> Dict[str, float]:
        """Return a dict with keys 'open' and 'close' representing the most recent intraday candle.
        'close' should be the latest price.
        """
        raise NotImplementedError


class YFinanceDataProvider(DataProvider):
    """Example DataProvider using yfinance. Limited to how yfinance behaves (and may not work reliably for 1m history).

    This is provided as a convenience example. For production/F&O usage you should replace with a provider
    that supplies reliable intraday candles for the exchange you trade on.
    """

    def __init__(self):
        if yf is None:
            raise RuntimeError("yfinance is not installed. Install yfinance or provide your own DataProvider.")

    def get_daily_bars(self, symbol: str, days: int = 20) -> pd.DataFrame:
        # yfinance returns an index of timestamps; we return a DataFrame with Open, High, Low, Close columns
        df = yf.download(symbol, period=f"{days}d", interval="1d", progress=False)
        if df.empty:
            raise RuntimeError(f"No daily data for {symbol}")
        # Keep only the last 'days' rows
        return df.tail(days)[["Open", "High", "Low", "Close"]].copy()

    def get_latest_intraday_bar(self, symbol: str, interval: str = "1m") -> Dict[str, float]:
        # Request a short intraday history and take the last candle
        df = yf.download(symbol, period="2d", interval=interval, progress=False)
        if df.empty:
            raise RuntimeError(f"No intraday data for {symbol}")
        last = df.iloc[-1]
        return {"open": float(last["Open"]), "close": float(last["Close"])}


class AlertHandler:
    def send_alert(self, result: BreakResult) -> None:
        raise NotImplementedError


class ConsoleAlertHandler(AlertHandler):
    def send_alert(self, result: BreakResult) -> None:
        print(f"ALERT {result.timestamp} | {result.symbol} | {result.timeframe} | {result.direction} | level={result.level:.4f} | price={result.price:.4f} | buffer={result.buffer_pct*100:.3f}%")


class WebhookAlertHandler(AlertHandler):
    def __init__(self, webhook_url: str):
        import requests

        self.webhook_url = webhook_url
        self.requests = requests

    def send_alert(self, result: BreakResult) -> None:
        payload = {
            "symbol": result.symbol,
            "timeframe": result.timeframe,
            "direction": result.direction,
            "level": result.level,
            "price": result.price,
            "buffer_pct": result.buffer_pct,
            "timestamp": result.timestamp,
        }
        try:
            self.requests.post(self.webhook_url, json=payload, timeout=5)
        except Exception as e:
            print("Webhook send failed:", e)


class SignalScanner:
    def __init__(
        self,
        symbols: List[str],
        data_provider: DataProvider,
        alert_handler: AlertHandler,
        buffer_pct: float = 0.0015,
        confirm_required: int = 2,
        state_path: str = DEFAULT_STATE_PATH,
    ):
        """symbols: list of symbols to scan. If you want an automatic F&O universe loader, supply the list from outside.

        buffer_pct: fractional buffer beyond the level (0.0015 = 0.15%).
        confirm_required: number of consecutive scans the condition must hold for (default 2).
        state_path: where to persist state (alerts sent & confirmation counts).
        """
        self.symbols = symbols
        self.data_provider = data_provider
        self.alert_handler = alert_handler
        self.buffer_pct = buffer_pct
        self.confirm_required = confirm_required
        self.state_path = state_path

        self._load_state()

    # --- State persistence ---
    def _load_state(self) -> None:
        if os.path.exists(self.state_path):
            with open(self.state_path, "r") as f:
                self.state: Dict[str, Any] = json.load(f)
        else:
            self.state = {"alerts": {}, "last_scan": None}

    def _save_state(self) -> None:
        os.makedirs(os.path.dirname(self.state_path) or ".", exist_ok=True)
        with open(self.state_path, "w") as f:
            json.dump(self.state, f, indent=2, default=str)

    # --- Helpers ---
    @staticmethod
    def _body_high_low_from_df(df: pd.DataFrame) -> pd.DataFrame:
        # Expects df with Open and Close columns
        df = df.copy()
        df["body_high"] = df[["Open", "Close"]].max(axis=1)
        df["body_low"] = df[["Open", "Close"]].min(axis=1)
        return df

    def _get_prev_levels(self, symbol: str) -> Dict[str, float]:
        # Get daily bars including today so we can compute prev-days excluding today
        df = self.data_provider.get_daily_bars(symbol, days=22)  # a bit of headroom
        if df.empty or len(df) < 6:
            raise RuntimeError(f"Not enough daily bars to compute levels for {symbol}")
        df = self._body_high_low_from_df(df)
        # We assume the last row is the most recent close (yesterday or today depending on provider)
        # For rolling levels we want the previous N days excluding today's incomplete day.
        # To be conservative we exclude the last row and compute rolling over the previous rows.
        prev = df.iloc[:-1]  # exclude last row as 'today' placeholder
        result = {}
        # 5-day (1-week)
        last5 = prev.tail(5)
        result["5_high"] = float(last5["body_high"].max())
        result["5_low"] = float(last5["body_low"].min())
        # 10-day (2-week)
        last10 = prev.tail(10)
        result["10_high"] = float(last10["body_high"].max())
        result["10_low"] = float(last10["body_low"].min())
        return result

    def _get_current_body(self, symbol: str) -> Dict[str, float]:
        bar = self.data_provider.get_latest_intraday_bar(symbol)
        o = float(bar["open"])
        c = float(bar["close"])
        return {"body_high": max(o, c), "body_low": min(o, c), "price": c}

    # --- Core logic ---
    def _check_symbol(self, symbol: str) -> List[BreakResult]:
        try:
            levels = self._get_prev_levels(symbol)
            current = self._get_current_body(symbol)
        except Exception as e:
            print(f"Skipping {symbol}: {e}")
            return []

        now_ts = datetime.utcnow().isoformat()
        results: List[BreakResult] = []

        # Check 1-week (5-day)
        # Up break
        if current["body_high"] > levels["5_high"] * (1 + self.buffer_pct):
            results.append(
                BreakResult(
                    symbol=symbol,
                    timeframe="1w",
                    direction="up",
                    level=levels["5_high"],
                    price=current["price"],
                    confirmed=False,
                    buffer_pct=self.buffer_pct,
                    timestamp=now_ts,
                )
            )

        # Down break
        if current["body_low"] < levels["5_low"] * (1 - self.buffer_pct):
            results.append(
                BreakResult(
                    symbol=symbol,
                    timeframe="1w",
                    direction="down",
                    level=levels["5_low"],
                    price=current["price"],
                    confirmed=False,
                    buffer_pct=self.buffer_pct,
                    timestamp=now_ts,
                )
            )

        # Check 2-week (10-day)
        if current["body_high"] > levels["10_high"] * (1 + self.buffer_pct):
            results.append(
                BreakResult(
                    symbol=symbol,
                    timeframe="2w",
                    direction="up",
                    level=levels["10_high"],
                    price=current["price"],
                    confirmed=False,
                    buffer_pct=self.buffer_pct,
                    timestamp=now_ts,
                )
            )

        if current["body_low"] < levels["10_low"] * (1 - self.buffer_pct):
            results.append(
                BreakResult(
                    symbol=symbol,
                    timeframe="2w",
                    direction="down",
                    level=levels["10_low"],
                    price=current["price"],
                    confirmed=False,
                    buffer_pct=self.buffer_pct,
                    timestamp=now_ts,
                )
            )

        return results

    def _get_state_for(self, symbol: str) -> Dict[str, Any]:
        date_key = date.today().isoformat()
        alerts = self.state.setdefault("alerts", {})
        day_state = alerts.setdefault(date_key, {})
        return day_state.setdefault(symbol, {})

    def _process_breaks_for_symbol(self, symbol: str, breaks: List[BreakResult]) -> None:
        # For each break, update confirm_count and possibly send alert
        s = self._get_state_for(symbol)
        now = time.time()

        # Map keys as timeframe_direction e.g., '1w_up'
        seen_keys = set()
        for br in breaks:
            key = f"{br.timeframe}_{br.direction}"
            seen_keys.add(key)
            entry = s.setdefault(key, {"confirm_count": 0, "sent": False, "last_seen": None})
            # Increase confirm_count
            entry["confirm_count"] = int(entry.get("confirm_count", 0)) + 1
            entry["last_seen"] = now
            # If condition lasted for required consecutive scans and not sent today, send
            if entry["confirm_count"] >= self.confirm_required and not entry.get("sent", False):
                # send alert
                br.confirmed = True
                try:
                    self.alert_handler.send_alert(br)
                except Exception as e:
                    print(f"Error sending alert for {symbol} {key}: {e}")
                entry["sent"] = True

        # For keys that were not true this scan, reset their confirm_count to 0.
        # This enforces consecutive scans requirement.
        for key, entry in list(s.items()):
            if key not in seen_keys:
                entry["confirm_count"] = 0
                entry["last_seen"] = None

    def run_once(self) -> None:
        # Run one scan over symbols
        for symbol in self.symbols:
            breaks = self._check_symbol(symbol)
            if breaks:
                self._process_breaks_for_symbol(symbol, breaks)
        self.state["last_scan"] = datetime.utcnow().isoformat()
        self._save_state()

    def run_loop(self, interval_seconds: int = 30) -> None:
        print(f"Starting scan loop: {len(self.symbols)} symbols, interval={interval_seconds}s, buffer={self.buffer_pct*100:.3f}%")
        try:
            while True:
                start = time.time()
                self.run_once()
                elapsed = time.time() - start
                to_sleep = max(0, interval_seconds - elapsed)
                time.sleep(to_sleep)
        except KeyboardInterrupt:
            print("Scanner stopped by user")


if __name__ == "__main__":
    # Small demo if executed directly
    if yf is None:
        print("yfinance not installed — demo won't run. Install yfinance or import this module and provide a DataProvider.")
    else:
        dp = YFinanceDataProvider()
        ah = ConsoleAlertHandler()
        symbols = ["AAPL", "MSFT"]
        scanner = SignalScanner(symbols=symbols, data_provider=dp, alert_handler=ah)
        scanner.run_once()
