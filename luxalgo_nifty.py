#!/usr/bin/env python3
"""
luxalgo_upstox_productionfinal.py  (patched)
============================================
Production Engine for NIFTY Options:
- Strategy 1: Trendline Breakouts (LuxAlgo "B" labels)
- Strategy 2: Support & Resistance Bounces (Mean Reversion)

Changes vs previous version
---------------------------
1. Signals are now evaluated on the CLOSED bar (candles[:-1]), not on the
   brand-new one-tick bar. Bounce strategies can now actually fire.
2. exit_trade only clears the position when the SELL is confirmed filled.
   Unfilled exits are retried with wider limit prices; partial fills reduce qty.
3. Force-exit (15:15) and stop-loss run BEFORE / independent of the spot fetch,
   so a spot-API outage cannot leave an open position unprotected.
4. Warm-up merges historical + intraday (today) 1-minute candles, and seeded
   bars are keyed by their slot start so the first live bar is not split.
5. Bars built across a data gap (>30s without ticks) are flagged stale and
   will not trigger entries.
6. Orders are verified via order-details; unfilled entries are cancelled.
   Ambiguous order state halts the bot loudly instead of guessing.
7. trades_today resets on a new date.
8. Token stays hard-coded in UPSTOX_ACCESS_TOKEN (env var / --token can override it).

Termux tips: run `termux-wake-lock` first and disable battery optimization
for Termux, otherwise Android can cut the network when the screen sleeps.
"""

from __future__ import annotations
import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, time as dtime, timedelta
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo
import requests

IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN = dtime(9, 15)
MARKET_CLOSE = dtime(15, 30)
FORCE_EXIT_TIME = dtime(15, 15)
ENTRY_CUTOFF = dtime(14, 30)

BASE_URL = "https://api.upstox.com/v2"
NIFTY_SPOT_KEY = "NSE_INDEX|Nifty 50"
STATE_FILE = Path("bot_state.json")

STALE_GAP_SEC = 30  # a bar with a tick gap larger than this is considered unreliable

# Upstox Access Token (hard-coded; paste the fresh token here each day)
UPSTOX_ACCESS_TOKEN = ""  # never hard-code: supplied via env UPSTOX_TOKEN / UPSTOX_ACCESS_TOKEN

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("luxalgo_live_production.log", encoding="utf-8")
    ]
)
logger = logging.getLogger("LuxProduction")

TRADES_CSV = "luxalgo_trades.csv"


def _log_trade(event: str, pos: dict, price: float, note: str = "", mode: str = ""):
    """Append an ENTRY/EXIT row (IST time) so results can be reviewed after the run."""
    import csv
    try:
        fe = os.path.exists(TRADES_CSV)
        with open(TRADES_CSV, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if not fe:
                w.writerow(["Timestamp_IST", "Mode", "Event", "Symbol", "Side", "Trigger",
                            "Qty", "Price", "Entry", "PnL_Rs", "Note"])
            entry = pos.get("entry", 0)
            pnl = round((price - entry) * pos.get("qty", 0), 2) if event == "EXIT" else ""
            w.writerow([datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S"), mode, event,
                        pos.get("symbol"), pos.get("side"), pos.get("trigger_type", ""),
                        pos.get("qty"), f"{price:.2f}", f"{entry:.2f}", pnl, note])
    except Exception as e:
        logger.warning(f"trade CSV error: {e}")


# ==========================================================================
# 1. LUXALGO INDICATOR ENGINE (BREAKOUTS + BOUNCES)
# ==========================================================================
def evaluate_trendlines(candles: list[dict], length: int = 14, mult: float = 1.0) -> dict:
    """Signals are evaluated on the LAST candle of `candles`, which must be a CLOSED bar."""
    n = len(candles)
    empty_result = {
        "upper": None, "lower": None,
        "up_break": False, "dn_break": False,
        "support_bounce": False, "resistance_reject": False,
        "new_upper": False, "new_lower": False,
        "upper_origin": None, "lower_origin": None
    }
    if n < (length * 2 + 1):
        return empty_result

    # 1. Wilder RMA ATR Calculation
    tr = [0.0] * n
    for i in range(n):
        c = candles[i]
        tr[i] = c["high"] - c["low"] if i == 0 else max(
            c["high"] - c["low"],
            abs(c["high"] - candles[i - 1]["close"]),
            abs(c["low"] - candles[i - 1]["close"])
        )
    atr = [None] * n
    if n >= length:
        a = sum(tr[:length]) / length
        atr[length - 1] = a
        for i in range(length, n):
            a = (a * (length - 1) + tr[i]) / length
            atr[i] = a

    upper = lower = None
    slope_ph = slope_pl = 0.0
    upos = dnos = 0
    up_break = dn_break = False
    support_bounce = resistance_reject = False
    new_upper = new_lower = False
    upper_origin = lower_origin = None

    for i in range(n):
        p = i - length
        # Pivot High
        ph = candles[p]["high"] if (p >= length and
            all(candles[k]["high"] <= candles[p]["high"] for k in range(p - length, p)) and
            all(candles[k]["high"] < candles[p]["high"] for k in range(p + 1, p + length + 1))) else None

        # Pivot Low
        pl = candles[p]["low"] if (p >= length and
            all(candles[k]["low"] >= candles[p]["low"] for k in range(p - length, p)) and
            all(candles[k]["low"] > candles[p]["low"] for k in range(p + 1, p + length + 1))) else None

        s = (atr[i] / length * mult) if atr[i] is not None else None

        # Upper Trendline updates
        if ph is not None and s is not None:
            slope_ph, upper = s, ph
            upos = 0
            if i == n - 1:
                new_upper = True
                upper_origin = {"time": candles[p]["time"], "price": ph, "slope": slope_ph}
        elif upper is not None:
            upper -= slope_ph

        # Lower Trendline updates
        if pl is not None and s is not None:
            slope_pl, lower = s, pl
            dnos = 0
            if i == n - 1:
                new_lower = True
                lower_origin = {"time": candles[p]["time"], "price": pl, "slope": slope_pl}
        elif lower is not None:
            lower += slope_pl

        upper_now = upper - slope_ph * length if upper is not None else None
        lower_now = lower + slope_pl * length if lower is not None else None

        c_open = candles[i]["open"]
        c_high = candles[i]["high"]
        c_low = candles[i]["low"]
        c_close = candles[i]["close"]

        # Only evaluate signals on the latest closed candle
        if i == n - 1:
            current_atr = atr[i] if atr[i] is not None else 15.0
            tol = max(4.0, current_atr * 0.20)  # Dynamic test tolerance

            # A. Breakouts
            if upper_now is not None and c_close > upper_now and upos == 0:
                up_break = True
            if lower_now is not None and c_close < lower_now and dnos == 0:
                dn_break = True

            # B. Support Bounce (CE Entry)
            if lower_now is not None and not dn_break and dnos == 0:
                tested_support = c_low <= (lower_now + tol)
                closed_green_above = (c_close > lower_now) and (c_close > c_open)
                if tested_support and closed_green_above:
                    support_bounce = True

            # C. Resistance Rejection (PE Entry)
            if upper_now is not None and not up_break and upos == 0:
                tested_resistance = c_high >= (upper_now - tol)
                closed_red_below = (c_close < upper_now) and (c_close < c_open)
                if tested_resistance and closed_red_below:
                    resistance_reject = True
        else:
            if upper_now is not None and c_close > upper_now:
                upos = 1
            if lower_now is not None and c_close < lower_now:
                dnos = 1

    return {
        "upper": upper_now,
        "lower": lower_now,
        "up_break": up_break,
        "dn_break": dn_break,
        "support_bounce": support_bounce,
        "resistance_reject": resistance_reject,
        "new_upper": new_upper,
        "new_lower": new_lower,
        "upper_origin": upper_origin,
        "lower_origin": lower_origin,
    }


# ==========================================================================
# 2. UPSTOX API ADAPTER
# ==========================================================================
class UpstoxClient:
    def __init__(self, token: str, mode: str = "paper", fill_timeout: int = 8):
        self.token = token
        self.mode = mode
        self.fill_timeout = fill_timeout
        self.headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        self._spot_fail_count = 0

    # ---------------- market data ----------------
    def _fetch_candles(self, url: str, label: str) -> dict:
        out: dict[datetime, dict] = {}
        try:
            r = requests.get(url, headers=self.headers, timeout=10)
            if r.status_code == 200:
                for c in r.json().get("data", {}).get("candles", []):
                    dt = datetime.fromisoformat(c[0])
                    if dt.tzinfo:
                        dt = dt.astimezone(IST).replace(tzinfo=None)
                    out[dt] = {
                        "time": dt, "open": float(c[1]), "high": float(c[2]),
                        "low": float(c[3]), "close": float(c[4])
                    }
            else:
                logger.error(f"Warm-up fetch ({label}) HTTP {r.status_code}: {r.text[:200]}")
        except Exception as e:
            logger.error(f"Warm-up fetch ({label}) failed: {e}")
        return out

    def fetch_warmup_candles(self, days_back: int = 3) -> list[dict]:
        """Historical (previous days) + intraday (today) 1-minute candles, merged and sorted."""
        key = quote(NIFTY_SPOT_KEY, safe="")
        now = datetime.now(IST)
        to_date = now.strftime("%Y-%m-%d")
        from_date = (now - timedelta(days=days_back)).strftime("%Y-%m-%d")

        hist = self._fetch_candles(f"{BASE_URL}/historical-candle/{key}/1minute/{to_date}/{from_date}", "historical")
        intra = self._fetch_candles(f"{BASE_URL}/historical-candle/intraday/{key}/1minute", "intraday")

        merged = dict(hist)
        merged.update(intra)  # intraday wins on overlap
        candles = [merged[k] for k in sorted(merged)]

        if candles:
            today_count = sum(1 for c in candles if c["time"].date() == now.date())
            logger.info(
                f"Loaded {len(candles)} 1-minute bars for pre-warming "
                f"(historical {len(hist)}, intraday {len(intra)}, today {today_count}). "
                f"Last bar: {candles[-1]['time'].strftime('%Y-%m-%d %H:%M')}"
            )
        return candles

    def _spot_ok(self):
        if self._spot_fail_count > 0:
            logger.info(f"✅ Connection restored after {self._spot_fail_count} failed spot polls.")
            self._spot_fail_count = 0

    def _spot_failed(self, msg: str):
        self._spot_fail_count += 1
        # Log the first failure, then every 10th, to keep outages readable
        if self._spot_fail_count == 1 or self._spot_fail_count % 10 == 0:
            logger.warning(f"{msg} (failed polls so far: {self._spot_fail_count})")

    def get_spot_ltp(self) -> float | None:
        url = f"{BASE_URL}/market-quote/ltp"
        try:
            r = requests.get(url, headers=self.headers, params={"instrument_key": NIFTY_SPOT_KEY}, timeout=5)
            if r.status_code == 200:
                data = r.json().get("data", {})
                for v in data.values():
                    self._spot_ok()
                    return float(v["last_price"])
                self._spot_failed("Spot LTP returned empty data")
            elif r.status_code == 401:
                self._spot_failed("Spot LTP HTTP 401: access token invalid or expired")
            else:
                self._spot_failed(f"Spot LTP HTTP {r.status_code}: {r.text[:200]}")
        except Exception as e:
            self._spot_failed(f"Network error in get_spot_ltp: {type(e).__name__}: {str(e)[:150]}")
        return None

    def get_option_ltp(self, instrument_key: str) -> float | None:
        url = f"{BASE_URL}/market-quote/ltp"
        try:
            r = requests.get(url, headers=self.headers, params={"instrument_key": instrument_key}, timeout=5)
            if r.status_code == 200:
                data = r.json().get("data", {})
                for v in data.values():
                    return float(v["last_price"])
            else:
                logger.warning(f"Option LTP HTTP {r.status_code}: {r.text[:200]}")
        except Exception as e:
            logger.warning(f"Network error in get_option_ltp ({instrument_key}): {type(e).__name__}: {str(e)[:150]}")
        return None

    def get_atm_contract(self, spot: float, opt_type: str) -> tuple[str, str] | None:
        strike = int(round(spot / 50.0) * 50)
        today = datetime.now(IST).strftime("%Y-%m-%d")
        try:
            r = requests.get(
                f"{BASE_URL}/option/contract",
                headers=self.headers,
                params={"instrument_key": NIFTY_SPOT_KEY},
                timeout=8,
            )
            if r.status_code == 200:
                contracts = []
                for c in r.json().get("data", []):
                    if int(round(float(c.get("strike_price", 0)))) != strike:
                        continue
                    if c.get("instrument_type") != opt_type:
                        continue
                    exp = c.get("expiry")
                    if isinstance(exp, str) and exp[:10] < today:
                        continue  # skip already-expired contracts
                    contracts.append(c)
                if contracts:
                    contracts.sort(key=lambda x: str(x.get("expiry")))
                    return contracts[0]["instrument_key"], contracts[0]["trading_symbol"]
            else:
                logger.error(f"Option lookup failed HTTP {r.status_code}: {r.text[:200]}")
        except Exception as e:
            logger.error(f"Option contract lookup error: {e}")
        return None

    # ---------------- orders ----------------
    def _order_details(self, order_id: str) -> dict | None:
        try:
            r = requests.get(f"{BASE_URL}/order/details", headers=self.headers,
                             params={"order_id": order_id}, timeout=5)
            if r.status_code == 200:
                return r.json().get("data") or None
            logger.warning(f"Order details HTTP {r.status_code}: {r.text[:200]}")
        except Exception as e:
            logger.warning(f"Order details error: {type(e).__name__}: {str(e)[:150]}")
        return None

    def _cancel_order(self, order_id: str):
        try:
            r = requests.delete(f"{BASE_URL}/order/cancel", headers=self.headers,
                                params={"order_id": order_id}, timeout=5)
            logger.info(f"Cancel order {order_id} -> HTTP {r.status_code}: {r.text[:200]}")
        except Exception as e:
            logger.warning(f"Cancel order error: {type(e).__name__}: {str(e)[:150]}")

    def _result_from_details(self, d: dict, qty: int, order_id: str) -> dict:
        filled = int(float(d.get("filled_quantity") or 0))
        avg = float(d.get("average_price") or 0.0)
        if filled >= qty:
            status = "SUCCESS"
        elif filled > 0:
            status = "PARTIAL"
        else:
            status = "FAILED"
        return {"status": status, "fill_price": avg, "filled_qty": min(filled, qty), "order_id": order_id}

    def _await_fill(self, order_id: str, qty: int) -> dict:
        """Poll order status. Cancel if not filled by the timeout. Returns SUCCESS/PARTIAL/FAILED/UNKNOWN."""
        deadline = time.time() + self.fill_timeout
        last = None
        terminal = False
        while time.time() < deadline:
            d = self._order_details(order_id)
            if d:
                last = d
                st = str(d.get("status", "")).lower()
                if st == "complete":
                    terminal = True
                    break
                if st in ("rejected", "cancelled"):
                    terminal = True
                    logger.error(f"❌ Order {order_id} {st}: {d.get('status_message')}")
                    break
            time.sleep(1.0)

        if last is None:
            logger.critical(f"Could not read status of order {order_id} at all.")
            return {"status": "UNKNOWN", "fill_price": 0.0, "filled_qty": 0, "order_id": order_id}

        if not terminal:
            logger.warning(f"Order {order_id} not filled within {self.fill_timeout}s "
                           f"(status: {last.get('status')}). Cancelling.")
            self._cancel_order(order_id)
            time.sleep(1.0)
            d = self._order_details(order_id)
            if d:
                last = d

        return self._result_from_details(last, qty, order_id)

    def place_order(self, instrument_key: str, side: str, qty: int, slippage_pct: float = 3.0) -> dict:
        """Returns {status: SUCCESS|PARTIAL|FAILED|UNKNOWN, fill_price, filled_qty, order_id}."""
        if self.mode == "paper":
            ltp = self.get_option_ltp(instrument_key) or 130.0
            logger.info(f"[PAPER] {side} {qty} qty of {instrument_key} @ ~₹{ltp:.2f}")
            return {"status": "SUCCESS", "fill_price": ltp, "filled_qty": qty, "order_id": "PAPER_ORDER"}

        ltp = self.get_option_ltp(instrument_key)
        if not ltp or ltp <= 0:
            logger.error(f"Cannot place order: Could not fetch LTP for {instrument_key}")
            return {"status": "FAILED", "fill_price": 0.0, "filled_qty": 0, "order_id": None}

        # Marketable Limit Order rounded to valid NSE 0.05 tick size
        factor = (1 + slippage_pct / 100.0) if side == "BUY" else (1 - slippage_pct / 100.0)
        raw_px = ltp * factor
        limit_price = max(0.05, round(round(raw_px / 0.05) * 0.05, 2))

        payload = {
            "quantity": qty,
            "product": "D",              # "D" Normal/Delivery avoids broker MIS option bans
            "validity": "DAY",
            "price": limit_price,        # Prevents exchange MARKET order rejection
            "tag": "luxalgo",
            "instrument_token": instrument_key,
            "order_type": "LIMIT",
            "transaction_type": side,
            "disclosed_quantity": 0,
            "trigger_price": 0.0,
            "is_amo": False
        }

        try:
            r = requests.post(f"{BASE_URL}/order/place", headers=self.headers, json=payload, timeout=8)
            res = r.json()
            logger.info(f"Upstox Order API Response [{r.status_code}]: {res}")

            if r.status_code == 200 and res.get("status") == "success":
                order_id = res.get("data", {}).get("order_id")
                if not order_id:
                    logger.critical("Order accepted but no order_id returned.")
                    return {"status": "UNKNOWN", "fill_price": 0.0, "filled_qty": 0, "order_id": None}
                out = self._await_fill(order_id, qty)
                if out["status"] in ("SUCCESS", "PARTIAL") and out["fill_price"] <= 0:
                    out["fill_price"] = self.get_option_ltp(instrument_key) or limit_price
                return out

            errors = res.get("errors", [])
            err_msg = errors[0].get("message") if errors else res.get("message", "Unknown error")
            logger.error(f"❌ Order Rejected by Upstox: {err_msg}")
        except requests.exceptions.ReadTimeout:
            # Request may have reached the exchange; we cannot know.
            logger.critical("Order request timed out after sending: order state UNKNOWN.")
            return {"status": "UNKNOWN", "fill_price": 0.0, "filled_qty": 0, "order_id": None}
        except Exception as e:
            logger.error(f"❌ Live order exception: {e}")

        return {"status": "FAILED", "fill_price": 0.0, "filled_qty": 0, "order_id": None}


# ==========================================================================
# 3. CONTINUOUS RESAMPLER & EXECUTION ENGINE
# ==========================================================================
class Resampler:
    def __init__(self, interval_sec: int, raw_candles: list[dict]):
        self.interval_sec = interval_sec
        self.candles: list[dict] = []
        self.last_tick: datetime | None = None
        self.bar_max_gap = 0.0
        self._seed(raw_candles)

    def _seed(self, raw: list[dict]):
        step = self.interval_sec
        grouped: dict = {}
        for c in raw:
            dt = c["time"]
            anchor = dt.replace(hour=9, minute=15, second=0, microsecond=0)
            if dt < anchor:
                continue
            slot = int((dt - anchor).total_seconds() // step)
            grouped.setdefault((dt.date(), slot), (anchor + timedelta(seconds=slot * step), []))[1].append(c)

        for _, (slot_start, grp) in sorted(grouped.items(), key=lambda x: x[0]):
            self.candles.append({
                "time": slot_start,  # slot start, so live ticks continue the same bar
                "open": grp[0]["open"],
                "high": max(x["high"] for x in grp),
                "low": min(x["low"] for x in grp),
                "close": grp[-1]["close"],
            })

    @staticmethod
    def _new_bar(slot_start: datetime, price: float) -> dict:
        return {"time": slot_start, "open": price, "high": price, "low": price, "close": price}

    def on_tick(self, dt: datetime, price: float) -> dict | None:
        anchor = dt.replace(hour=9, minute=15, second=0, microsecond=0)
        slot = int((dt - anchor).total_seconds() // self.interval_sec)
        slot_start = anchor + timedelta(seconds=slot * self.interval_sec)

        gap = (dt - self.last_tick).total_seconds() if self.last_tick else 0.0
        self.last_tick = dt

        if not self.candles:
            self.candles.append(self._new_bar(slot_start, price))
            self.bar_max_gap = 0.0
            return None

        last = self.candles[-1]
        if slot_start != last["time"]:
            completed = dict(last)
            completed["stale"] = max(self.bar_max_gap, gap) > STALE_GAP_SEC
            self.candles.append(self._new_bar(slot_start, price))
            self.bar_max_gap = 0.0
            return completed

        self.bar_max_gap = max(self.bar_max_gap, gap)
        last["high"] = max(last["high"], price)
        last["low"] = min(last["low"], price)
        last["close"] = price
        return None


class ProductionEngine:
    def __init__(self, args):
        self.args = args
        self.client = UpstoxClient(token=args.token, mode=args.mode, fill_timeout=args.fill_timeout)
        raw_warmup = self._load_warmup()
        self.resampler = Resampler(args.interval * 60, raw_warmup)
        self.state = self._load_state()
        self.next_exit_try = 0.0

    def _load_warmup(self) -> list[dict]:
        for attempt in range(1, 4):
            raw = self.client.fetch_warmup_candles(days_back=3)
            if raw:
                return raw
            logger.warning(f"Warm-up attempt {attempt}/3 returned no data.")
            time.sleep(3)
        logger.error("Warm-up failed: indicator will need ~30 live bars before it can signal.")
        return []

    # ---------------- state ----------------
    def _load_state(self) -> dict:
        today = str(datetime.now(IST).date())
        state = None
        if STATE_FILE.exists():
            try:
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    state = json.load(f)
            except Exception:
                state = None
        if not isinstance(state, dict):
            return {"position": None, "trades_today": 0, "date": today}
        state.setdefault("position", None)
        state.setdefault("trades_today", 0)
        if state.get("date") != today:
            state["trades_today"] = 0
            state["date"] = today
        if state.get("position"):
            p = state["position"]
            logger.warning(f"⚠️ Resuming with OPEN position from state file: {p.get('symbol')} "
                           f"qty {p.get('qty')} entry ₹{p.get('entry')}. Verify it exists at your broker.")
        return state

    def _save_state(self):
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=2)

    def _roll_date(self, now: datetime):
        today = str(now.date())
        if self.state.get("date") != today:
            logger.info(f"New trading day {today}: resetting trades_today.")
            self.state["date"] = today
            self.state["trades_today"] = 0
            self._save_state()

    def _halt(self, msg: str):
        logger.critical(f"🛑 HALTING BOT: {msg}")
        logger.critical("Check your Upstox app (orders + positions) before restarting. "
                        "State file keeps any recorded position.")
        self._save_state()
        sys.exit(2)

    # ---------------- main loop ----------------
    def run(self):
        logger.info(f"=== PRODUCTION BOT STARTED [{self.args.mode.upper()}] ===")
        logger.info("Strategies: BREAKOUTS + SUPPORT/RESISTANCE BOUNCES")
        logger.info(f"Timeframe: {self.args.interval}m | Lookback: {self.args.length} | Slope: ATR 1.0")

        last_heartbeat = time.time()

        while True:
            try:
                now = datetime.now(IST)
                t_now = now.time()

                if now.weekday() >= 5:
                    logger.info("Weekend: nothing to do. Exiting.")
                    break
                if t_now > MARKET_CLOSE:
                    logger.info("Market closed. Exiting.")
                    break
                if t_now < MARKET_OPEN:
                    time.sleep(5)
                    continue

                self._roll_date(now)

                # 1. Force EOD square-off FIRST: does not depend on the spot feed
                if self.state.get("position") and t_now >= FORCE_EXIT_TIME:
                    self.exit_trade("Market Close Force Exit")
                    time.sleep(2.0)
                    continue

                spot = self.client.get_spot_ltp()
                if spot is None:
                    # Spot feed is down, but the open position must still be protected
                    if self.state.get("position"):
                        self.manage_position()
                    time.sleep(2)
                    continue

                # 💓 30-Second Heartbeat confirmation
                if time.time() - last_heartbeat >= 30:
                    pos = self.state.get("position")
                    pos_txt = (f" | Pos: {pos['symbol']} x{pos['qty']} SL ₹{pos['current_sl']:.2f}"
                               if pos else " | Pos: flat")
                    logger.info(f"💓 [HEARTBEAT] Bot Active | Spot: ₹{spot:.2f} | "
                                f"Time: {now.strftime('%H:%M:%S')}{pos_txt}")
                    last_heartbeat = time.time()

                # 2. Dynamic Trailing Stop Management
                if self.state.get("position"):
                    self.manage_position()

                # 3. Check Candle Close & Trigger Signal
                completed_candle = self.resampler.on_tick(now, spot)
                if completed_candle:
                    # Ignore previous day's finalized candles
                    if completed_candle["time"].date() == now.date():
                        logger.info(
                            f"Closed {self.args.interval}m Bar [{completed_candle['time'].strftime('%H:%M')}]: "
                            f"O: {completed_candle['open']:.2f} H: {completed_candle['high']:.2f} "
                            f"L: {completed_candle['low']:.2f} C: {completed_candle['close']:.2f}"
                        )
                        self.process_signal(completed_candle, now)

                # 3-second cycle prevents API rate-limiting
                time.sleep(3.0)

            except KeyboardInterrupt:
                logger.info("Bot stopped by user.")
                break
            except Exception as e:
                logger.error(f"Runtime loop error: {e}")
                time.sleep(2)

    # ---------------- position management ----------------
    def manage_position(self):
        pos = self.state.get("position")
        if not pos:
            return

        opt_px = self.client.get_option_ltp(pos["instrument_key"])
        if not opt_px:
            return

        if opt_px > pos["peak_opt"]:
            pos["peak_opt"] = opt_px

        # Breakeven Rule
        gain = (pos["peak_opt"] / pos["entry"]) - 1.0
        if gain >= (self.args.be_at / 100.0) and pos["current_sl"] < pos["entry"]:
            pos["current_sl"] = pos["entry"]
            logger.info(f"🛡️ Stop moved to Breakeven @ ₹{pos['entry']:.2f}")

        # Trailing Rule
        if gain >= (self.args.trail_at / 100.0):
            profit = pos["peak_opt"] - pos["entry"]
            trail = pos["peak_opt"] - profit * (self.args.giveback / 100.0)
            if trail > pos["current_sl"]:
                pos["current_sl"] = trail
                logger.info(f"📈 Trailing SL raised to ₹{pos['current_sl']:.2f}")

        # Stop-Loss Hit
        if opt_px <= pos["current_sl"]:
            self.exit_trade(f"Stop-Loss Hit (Trigger @ ₹{opt_px:.2f} <= SL ₹{pos['current_sl']:.2f})")
            return

        self._save_state()

    # ---------------- entries ----------------
    def process_signal(self, candle: dict, now: datetime):
        # The resampler has already appended the NEW bar; the closed bar is the one before it.
        closed = self.resampler.candles[:-1]
        if not closed or closed[-1]["time"] != candle["time"]:
            logger.error("Closed-bar mismatch; skipping signal evaluation for this bar.")
            return

        res = evaluate_trendlines(closed, length=self.args.length, mult=1.0)

        # Notify on new trendline appearances
        if res["new_upper"]:
            orig = res["upper_origin"]
            logger.info(
                f"🔴 [NEW RED RESISTANCE LINE] Originated {orig['time'].strftime('%H:%M')} "
                f"@ ₹{orig['price']:.2f} | Current Level: ₹{res['upper']:.2f}"
            )
        if res["new_lower"]:
            orig = res["lower_origin"]
            logger.info(
                f"🟢 [NEW GREEN SUPPORT LINE] Originated {orig['time'].strftime('%H:%M')} "
                f"@ ₹{orig['price']:.2f} | Current Level: ₹{res['lower']:.2f}"
            )

        # Do not enter new trade if position already open
        if self.state.get("position") is not None:
            return

        side = None
        trigger_type = None

        # Prioritize Breakout, fallback to Bounce
        if res["up_break"]:
            side = "CE"
            trigger_type = "RESISTANCE BREAKOUT ('B')"
        elif res["support_bounce"]:
            side = "CE"
            trigger_type = "SUPPORT BOUNCE (GREEN LINE)"
        elif res["dn_break"]:
            side = "PE"
            trigger_type = "SUPPORT BREAKDOWN ('B')"
        elif res["resistance_reject"]:
            side = "PE"
            trigger_type = "RESISTANCE REJECTION (RED LINE)"

        if not side:
            return

        if candle.get("stale"):
            logger.warning(f"Signal {side} via {trigger_type} ignored: bar was built across a data gap.")
            return

        if not (MARKET_OPEN <= now.time() < ENTRY_CUTOFF):
            logger.info(f"Signal ignored: outside entry window ({now.time()})")
            return

        contract = self.client.get_atm_contract(candle["close"], side)
        if not contract:
            logger.error("No valid ATM option contract located.")
            return

        ikey, symbol = contract
        logger.info(f"🚀 ==> SIGNAL DETECTED: {side} via {trigger_type} | Contract: {symbol}")
        order = self.client.place_order(ikey, "BUY", self.args.qty, slippage_pct=3.0)

        if order["status"] == "UNKNOWN":
            self._halt(f"BUY order state unknown for {symbol} (order_id={order.get('order_id')}).")

        if order["status"] in ("SUCCESS", "PARTIAL"):
            fill_px = order["fill_price"]
            qty = int(order.get("filled_qty") or self.args.qty)
            if order["status"] == "PARTIAL":
                logger.warning(f"Partial entry fill: {qty}/{self.args.qty}. Managing the filled quantity only.")
            self.state["position"] = {
                "instrument_key": ikey,
                "symbol": symbol,
                "side": side,
                "trigger_type": trigger_type,
                "entry": fill_px,
                "qty": qty,
                "current_sl": fill_px * (1.0 - self.args.sl / 100.0),
                "peak_opt": fill_px,
            }
            self.state["trades_today"] += 1
            self._save_state()
            _log_trade("ENTRY", self.state["position"], fill_px, trigger_type, self.args.mode)
            logger.info(
                f"🎯 Position Opened: {symbol} x{qty} @ ₹{fill_px:.2f} | "
                f"Initial SL: ₹{self.state['position']['current_sl']:.2f}"
            )
        else:
            logger.error(f"❌ Order execution failed for {symbol}.")

    # ---------------- exits ----------------
    def exit_trade(self, reason: str):
        pos = self.state.get("position")
        if not pos:
            return
        if time.time() < self.next_exit_try:
            return  # short cooldown between failed exit rounds

        logger.info(f"<== EXITING POSITION: {pos['symbol']} | Reason: {reason}")

        # Progressively wider limit prices so a SELL actually gets filled
        for attempt, slip in enumerate((3.0, 6.0, 10.0), start=1):
            res = self.client.place_order(pos["instrument_key"], "SELL", pos["qty"], slippage_pct=slip)
            status = res["status"]

            if status == "UNKNOWN":
                self._halt(f"SELL order state unknown for {pos['symbol']} (order_id={res.get('order_id')}).")

            if status == "SUCCESS":
                logger.info(f"Closed {pos['symbol']} successfully @ ₹{res['fill_price']:.2f}")
                _log_trade("EXIT", pos, res["fill_price"], reason, self.args.mode)
                self.state["position"] = None
                self._save_state()
                return

            if status == "PARTIAL":
                filled = int(res.get("filled_qty") or 0)
                pos["qty"] -= filled
                self._save_state()
                logger.warning(f"Partial exit fill ({filled}); {pos['qty']} qty remaining.")
                continue

            logger.error(f"Exit attempt {attempt}/3 for {pos['symbol']} not filled.")

        # Position is still open: keep it in state and retry on a later cycle
        self.next_exit_try = time.time() + 5
        logger.error(f"❌ EXIT NOT CONFIRMED for {pos['symbol']} (qty {pos['qty']}). "
                     f"Position kept in state, will retry. CHECK YOUR BROKER APP.")


# ==========================================================================
# 4. ENTRY POINT
# ==========================================================================
def main():
    parser = argparse.ArgumentParser(description="LuxAlgo Dual Engine: Breaks & Bounces")
    parser.add_argument("--interval", type=int, default=3, help="Candle interval in minutes (3m)")
    parser.add_argument("--length", type=int, default=14, help="Pivot lookback (14)")
    parser.add_argument("--mode", default=os.environ.get("LUXALGO_MODE", "paper"), choices=["paper", "live"])
    parser.add_argument("--qty", type=int, default=65, help="NIFTY lot size")
    parser.add_argument("--sl", type=float, default=15.0, help="Initial Stop Loss %%")
    parser.add_argument("--be-at", type=float, default=6.0, help="Move to BE at +X%% gain")
    parser.add_argument("--trail-at", type=float, default=8.0, help="Start trailing at +X%% gain")
    parser.add_argument("--giveback", type=float, default=20.0, help="Trailing giveback %%")
    parser.add_argument("--fill-timeout", type=int, default=8, help="Seconds to wait for an order fill")
    parser.add_argument("--token", default=os.environ.get("UPSTOX_TOKEN") or os.environ.get("UPSTOX_ACCESS_TOKEN") or UPSTOX_ACCESS_TOKEN,
                        help="Upstox access token (default: the hard-coded UPSTOX_ACCESS_TOKEN constant)")

    args = parser.parse_args()
    if not args.token:
        parser.error("No Upstox token. Set UPSTOX_ACCESS_TOKEN in the script (or pass --token)")

    engine = ProductionEngine(args)
    engine.run()


if __name__ == "__main__":
    main()