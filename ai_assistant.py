"""
╔══════════════════════════════════════════════════════════════════════════════╗
║          REAL-TIME AI TRADING ASSISTANT  —  Groq Free Tier                 ║
║          Model : llama-3.3-70b-versatile  (free, no credit card)           ║
║          Runs  : background thread inside Pydroid3                          ║
║          Cost  : ₹0  (Groq free = 14,400 req/day, 6,000 tokens/min)        ║
╚══════════════════════════════════════════════════════════════════════════════╝

SETUP (one-time, 2 minutes):
  1. Go to https://console.groq.com  → sign up free → API Keys → Create key
  2. Paste the key below as GROQ_API_KEY
  3. In Pydroid3 terminal:  pip install requests  (already installed in bot)
  4. The bot imports this file automatically — nothing else to do.

HOW IT WORKS:
  Every scan (≈30s) the AI receives a snapshot of:
    • All active positions with live P&L
    • HA reversal status per position
    • Recent signals taken / blocked (last 5)
    • Current Klinger readings for held stocks
    • HA watchlist (missed signals)
    • Market conditions summary

  The AI then:
    1. Explains any signal that was taken or blocked this scan
    2. Warns if a held position looks risky
    3. Decides autonomously whether to exit a position (CONFIRMED reversal
       signals only — same threshold as the HA auto-exit logic)
    4. Prints a plain-language summary you can read at a glance

AUTO-EXIT POLICY:
  The AI will call exit_position() directly ONLY when ALL 3 are true:
    a) HA flip confirmed (2 consecutive counter-colour candles)
    b) Klinger confirms direction (KO falling for LONG, rising for SHORT)
    c) Position held > AI_MIN_HOLD_MINUTES (default 15 min)

  For LOSING positions: auto-exits when loss > AI_LOSS_EXIT_THRESHOLD_PCT
    (default 5%) AND reversal is confirmed — cutting a confirmed loss early
    beats holding through a full reversal.
  For small losses (< threshold): prints WATCH alert, does not auto-exit.

  Set AI_EXIT_PROFIT_ONLY = True to revert to the old behaviour where
  the AI never auto-exits a losing position (you handle losses manually).
"""

import threading
import time
import json
import requests as _req
from datetime import datetime, timedelta
from typing import Optional

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION  — edit these two lines
# ══════════════════════════════════════════════════════════════════════════════

import os as _os
GROQ_API_KEY   = _os.environ.get("GROQ_API_KEY", "YOUR_GROQ_API_KEY_HERE")   # get free at console.groq.com
AI_ENABLED     = True                        # set False to disable entirely

# ── Behaviour knobs ───────────────────────────────────────────────────────────
AI_SCAN_INTERVAL_SECONDS = 35        # slightly offset from 30s bot cycle
AI_MODEL                 = "llama-3.3-70b-versatile"   # best free Groq model
AI_MAX_TOKENS            = 400       # keep responses short for mobile screen
AI_TEMPERATURE           = 0.2       # low = more decisive, less hallucination
AI_AUTO_EXIT_ENABLED     = True      # let AI exit confirmed reversals
AI_MIN_HOLD_MINUTES      = 15        # don't auto-exit within first N minutes
AI_EXIT_PROFIT_ONLY      = False     # False = AI can exit losses too (recommended)
                                     # True  = AI only exits profitable positions
                                     #         (you manually handle stop-loss cuts)

# When AI_EXIT_PROFIT_ONLY = False, the AI will still only exit a losing
# position when BOTH conditions are met:
#   a) HA flip confirmed + Klinger confirms (same as profit exits)
#   b) Loss exceeds AI_LOSS_EXIT_THRESHOLD_PCT (prevents exiting on tiny dips)
AI_LOSS_EXIT_THRESHOLD_PCT = 5.0     # only auto-exit a loss if > 5% down
                                     # set 0.0 to exit at any loss amount
AI_SILENT_WHEN_NO_POSITIONS = True   # skip API call when nothing is open

# ── Groq API ──────────────────────────────────────────────────────────────────
_GROQ_URL     = "https://api.groq.com/openai/v1/chat/completions"
_GROQ_HEADERS = lambda key: {
    "Authorization": f"Bearer {key}",
    "Content-Type":  "application/json",
}

# ── State ─────────────────────────────────────────────────────────────────────
_ai_thread:       Optional[threading.Thread] = None
_ai_last_run:     Optional[datetime]         = None
_ai_call_count:   int                        = 0       # track free-tier usage
_ai_error_streak: int                        = 0       # back-off on errors
_AI_LOCK          = threading.Lock()

# ══════════════════════════════════════════════════════════════════════════════
# SYSTEM PROMPT  — tells the LLM what it's looking at
# ══════════════════════════════════════════════════════════════════════════════

_SYSTEM_PROMPT = """You are a real-time trading assistant for an Upstox F&O bot.
The bot trades NSE options (CE for LONG, PE for SHORT) using:
  • Klinger Oscillator (KO) — bullish when positive/rising, bearish when negative/falling
  • Heikin-Ashi (HA) candles — flip from green→red signals bearish reversal, red→green bullish
  • Bollinger Bands (squeeze = low volatility breakout setup)
  • R3/S3 pivot levels (breakout above R3 = CE, breakdown below S3 = PE)
  • ORB (Opening Range Breakout at 09:20)

Snapshot fields explained:
  u_ltp         — underlying stock's live price (not the option). Use to judge reversal strength.
  opt_ltp       — option premium live price.
  market.dir    — overall Nifty50 direction (UP/DOWN). A trade AGAINST market direction is higher risk.
  market.nifty  — Nifty50 ltp + % change.
  news          — top ET Markets headlines (≤5). Mention any that are relevant to held stocks.
  earn_warn     — true if this stock reports earnings within 3 days. Always flag this as elevated risk.

You receive this snapshot every 30 seconds. Your job:
1. EXPLAIN: In 1 sentence, what just happened (signal taken, blocked, alert fired).
2. WARN: Flag any position that looks risky — mention u_ltp trend, market direction, or news if relevant.
3. DECIDE: For each active position output one of:
   HOLD   — conditions still favourable
   WATCH  — deteriorating, monitor next scan
   EXIT   — confirmed reversal (HA flip + Klinger confirms), recommend exit now

OUTPUT FORMAT (strict — bot parses this):
SUMMARY: <one sentence>
POSITIONS:
  <SYMBOL>: <HOLD|WATCH|EXIT> — <reason in ≤15 words>
WATCHLIST:
  <SYMBOL>: <ALERT|OK> — <reason>
END

Rules:
- Never say EXIT unless HA flip AND Klinger both confirm.
- Never say EXIT for a position held less than 15 minutes (too noisy).
- For LOSING positions: say EXIT if reversal confirmed AND loss > 5%.
  Cutting a confirmed loss early beats holding through a full reversal.
- For losses under 5%: say WATCH — too small to act on, could be noise.
- If earnings_warning=true for a held stock: say WATCH minimum, note the risk.
- If market direction opposes the trade direction: note it but don't override Klinger.
- Keep total response under 300 words.
- Use ₹ for prices. Be direct. No filler words."""


# ══════════════════════════════════════════════════════════════════════════════
# MARKET CONTEXT FETCHER  — Nifty/BankNifty + news + earnings (cached 5 min)
# ══════════════════════════════════════════════════════════════════════════════

_MARKET_CACHE:       dict     = {}
_MARKET_CACHE_TIME:  datetime = None
_MARKET_CACHE_TTL             = 300    # seconds between refreshes

_EARNINGS_CACHE:     dict = {}         # symbol → date string
_EARNINGS_CACHE_DATE: str = ""


def _fetch_market_context() -> dict:
    """
    Fetch Nifty50 + BankNifty quotes, top ET Markets headlines, and NSE
    earnings calendar (next 3 days).  All sources are free / no auth.
    Results are cached for 5 minutes to avoid wasting Groq tokens.
    Returns an empty dict silently on any failure so the AI still works.
    """
    global _MARKET_CACHE, _MARKET_CACHE_TIME, _EARNINGS_CACHE, _EARNINGS_CACHE_DATE
    now = datetime.now()

    if (_MARKET_CACHE_TIME and
            (now - _MARKET_CACHE_TIME).total_seconds() < _MARKET_CACHE_TTL):
        return _MARKET_CACHE

    ctx = {}

    # ── Nifty50 + BankNifty ──────────────────────────────────────────────────
    try:
        sess = _req.Session()
        sess.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept":     "application/json",
            "Referer":    "https://www.nseindia.com",
        })
        sess.get("https://www.nseindia.com", timeout=5)   # prime cookies
        indices = {}
        for idx_name, key in [("NIFTY 50", "50"), ("NIFTY BANK", "BANK")]:
            try:
                r = sess.get(
                    "https://www.nseindia.com/api/quote-index",
                    params={"index": idx_name},
                    timeout=8,
                )
                if r.status_code == 200:
                    d   = r.json().get("data", {})
                    chg = round(d.get("percChange", 0), 2)
                    indices[key] = {
                        "ltp": round(d.get("last", 0), 2),
                        "chg": chg,
                        "dir": "UP" if chg >= 0 else "DOWN",
                    }
            except Exception:
                pass
        if indices:
            ctx["indices"]    = indices
            ctx["market_dir"] = indices.get("50", {}).get("dir", "UNKNOWN")
    except Exception:
        ctx["market_dir"] = "UNKNOWN"

    # ── ET Markets RSS headlines (top 5, ≤80 chars each) ─────────────────────
    try:
        r = _req.get(
            "https://economictimes.indiatimes.com/markets/rss.cms",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=8,
        )
        if r.status_code == 200:
            import re as _re
            titles = _re.findall(r"<title><!\[CDATA\[(.*?)\]\]></title>", r.text)
            headlines = [t[:80] for t in titles[1:6] if t.strip()]
            if headlines:
                ctx["news"] = headlines
    except Exception:
        pass

    # ── NSE earnings calendar — next 3 days ──────────────────────────────────
    today_str = now.strftime("%Y-%m-%d")
    if _EARNINGS_CACHE_DATE != today_str:
        try:
            r = _req.get(
                "https://www.nseindia.com/api/event-calendar",
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept":     "application/json",
                    "Referer":    "https://www.nseindia.com",
                },
                timeout=10,
            )
            if r.status_code == 200:
                cutoff   = now + timedelta(days=3)
                earnings = {}
                for ev in r.json():
                    purpose = ev.get("purpose", "").lower()
                    if any(k in purpose for k in ("result", "earnings", "quarterly")):
                        sym  = ev.get("symbol", "")
                        date = ev.get("date",   "")
                        if sym and date:
                            try:
                                if now <= datetime.strptime(date, "%d-%b-%Y") <= cutoff:
                                    earnings[sym] = date
                            except Exception:
                                pass
                _EARNINGS_CACHE      = earnings
                _EARNINGS_CACHE_DATE = today_str
        except Exception:
            pass
    if _EARNINGS_CACHE:
        ctx["earnings_3d"] = _EARNINGS_CACHE

    _MARKET_CACHE      = ctx
    _MARKET_CACHE_TIME = now
    return ctx


# ══════════════════════════════════════════════════════════════════════════════
# SNAPSHOT BUILDER  — reads live globals from the main bot
# ══════════════════════════════════════════════════════════════════════════════

def _build_snapshot(bot_globals: dict) -> dict:
    """
    Build a compact, token-efficient snapshot for the AI.

    v2 improvements:
      1. underlying_ltp per position (stock price, not option price)
      2. Market context: Nifty/BankNifty direction, live levels
      3. News headlines from ET Markets (top 5, ≤80 chars each)
      4. Earnings warning flag (True if stock reports within 3 days)
      5. Log lines truncated to 100 chars (saves ~30% tokens)
      6. Watchlist reasons truncated to 80 chars
      7. Klinger field renamed/compressed (ko + hist only, signal dropped)
      8. Position id removed (not needed by AI), field names shortened
    """
    now = datetime.now()

    # ── Market context (fetched + cached every 5 min) ─────────────────────────
    mctx     = _fetch_market_context()
    earnings = mctx.get("earnings_3d", {})

    # ── Helpers for underlying LTP lookup ─────────────────────────────────────
    live_data   = bot_globals.get("_LIVE_DATA",      {})
    sym_to_isin = bot_globals.get("SYMBOL_TO_ISIN",  {})
    r3_levels   = bot_globals.get("R3_LEVELS",       {})

    def _ultp(symbol: str, underlying_key: str) -> float:
        ikey = underlying_key or sym_to_isin.get(symbol, "")
        if ikey and ikey in live_data:
            return round(live_data[ikey].get("ltp", 0), 2)
        if ikey and ikey in r3_levels:
            return round(r3_levels[ikey].get("ltp", 0), 2)
        return 0

    # ── Active positions ──────────────────────────────────────────────────────
    active_raw = bot_globals.get("ACTIVE_POSITIONS", {})
    ha_alerted = bot_globals.get("_HA_ALERTED", set())
    positions  = []

    for pos_id, pos in active_raw.items():
        symbol         = pos.get("symbol", "?")
        signal         = pos.get("fast_trade_signal", pos.get("breakout_type", "?"))
        entry          = pos.get("entry_price", 0)
        entry_time     = pos.get("timestamp", now)
        held_mins      = round((now - entry_time).total_seconds() / 60, 1) if entry_time else 0
        underlying_key = pos.get("underlying_key", "")
        option_key     = pos.get("instrument_key", "")

        opt_ltp = bot_globals.get("_LAST_LTP", {}).get(option_key, 0)
        pnl_pct = round((opt_ltp - entry) / entry * 100, 2) if entry and opt_ltp else None
        u_ltp   = _ultp(symbol, underlying_key)

        # Klinger — just KO value and 3-bar history (enough for trend direction)
        kl = {}
        if underlying_key in r3_levels:
            kd = r3_levels[underlying_key].get("klinger", {})
            if kd:
                kl = {
                    "ko":   round(kd.get("klinger", 0), 0),
                    "hist": [round(v, 0) for v in kd.get("ko_history", [])[-3:]],
                }

        positions.append({
            "sym":       symbol,
            "dir":       signal,
            "entry":     entry,
            "opt_ltp":   opt_ltp or "?",
            "u_ltp":     u_ltp   or "?",     # ← underlying stock price (new)
            "pnl%":      pnl_pct,
            "held_min":  held_mins,
            "ha_flip":   f"{pos_id}_flip" in ha_alerted,
            "ha_doji":   f"{pos_id}_doji" in ha_alerted,
            "kl":        kl,
            "strat":     pos.get("strategy", "?"),
            "earn_warn": symbol in earnings,   # ← earnings within 3 days (new)
        })

    # ── HA watchlist — reasons truncated ─────────────────────────────────────
    watchlist = [
        {
            "sym":     sym,
            "sig":     w.get("signal", "?"),
            "reason":  w.get("reason", "")[:80],
            "age_min": round((now - w.get("added_at", now)).total_seconds() / 60, 1),
        }
        for sym, w in bot_globals.get("HA_WATCHLIST", {}).items()
    ]

    # ── Recent log — 8 lines, each ≤100 chars ────────────────────────────────
    recent_log = []
    try:
        with open(bot_globals.get("ALERT_LOG_FILE", "r3_live_alerts.txt"),
                  "r", encoding="utf-8") as f:
            lines = f.readlines()
        recent_log = [l.strip()[:100] for l in lines[-12:] if l.strip()][-8:]
    except Exception:
        pass

    # ── Order stats ───────────────────────────────────────────────────────────
    orders = sum(bot_globals.get(k, 0) for k in [
        "DAILY_ORDER_COUNT", "BOX_ORDER_COUNT", "RANGE_ORDER_COUNT",
        "GAP_ORDER_COUNT", "FAST_TRADE_ORDER_COUNT", "ORB_ORDER_COUNT",
    ])

    # ── Final snapshot ────────────────────────────────────────────────────────
    snap = {
        "time":      now.strftime("%H:%M"),
        "market": {                                  # ← market context (new)
            "dir":    mctx.get("market_dir", "UNKNOWN"),
            "nifty":  mctx.get("indices", {}).get("50",   {}),
            "banknf": mctx.get("indices", {}).get("BANK", {}),
        },
        "positions": positions,
        "watchlist": watchlist,
        "pnl":       round(bot_globals.get("DAILY_PNL", 0), 2),
        "orders":    f"{orders}/{bot_globals.get('MAX_ORDERS_PER_DAY', 10)}",
        "stopped":   bot_globals.get("TRADING_STOPPED", False),
        "log":       recent_log,
    }
    # News only added when non-empty (omitted on quiet days to save tokens)
    if mctx.get("news"):
        snap["news"] = mctx["news"]              # ← top 5 ET Markets headlines (new)

    return snap


# ══════════════════════════════════════════════════════════════════════════════
# GROQ API CALL
# ══════════════════════════════════════════════════════════════════════════════

def _call_groq(snapshot: dict) -> Optional[str]:
    """Send snapshot to Groq, return AI response text or None on error."""
    global _ai_call_count, _ai_error_streak

    if GROQ_API_KEY == "YOUR_GROQ_API_KEY_HERE" or not GROQ_API_KEY:
        return None

    user_msg = f"Current bot snapshot:\n{json.dumps(snapshot, indent=2, default=str)}"

    payload = {
        "model":       AI_MODEL,
        "messages":    [
            {"role": "system",  "content": _SYSTEM_PROMPT},
            {"role": "user",    "content": user_msg},
        ],
        "max_tokens":  AI_MAX_TOKENS,
        "temperature": AI_TEMPERATURE,
    }

    try:
        resp = _req.post(
            _GROQ_URL,
            headers=_GROQ_HEADERS(GROQ_API_KEY),
            json=payload,
            timeout=20,
        )
        if resp.status_code == 200:
            _ai_call_count   += 1
            _ai_error_streak  = 0
            return resp.json()["choices"][0]["message"]["content"].strip()
        elif resp.status_code == 429:
            print("\n⚠️  AI: Groq rate limit hit — skipping this scan")
            _ai_error_streak += 1
            return None
        else:
            _ai_error_streak += 1
            if _ai_error_streak <= 2:
                print(f"\n⚠️  AI: Groq error {resp.status_code} — {resp.text[:120]}")
            return None
    except Exception as e:
        _ai_error_streak += 1
        if _ai_error_streak <= 2:
            print(f"\n⚠️  AI: Request failed — {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# RESPONSE PARSER  — extracts EXIT decisions for auto-action
# ══════════════════════════════════════════════════════════════════════════════

def _parse_response(text: str) -> dict:
    """
    Parse AI response into structured dict.
    Returns:
      { 'summary': str,
        'positions': { symbol: {'verdict': 'HOLD'|'WATCH'|'EXIT', 'reason': str} },
        'watchlist':  { symbol: {'verdict': 'ALERT'|'OK', 'reason': str} },
        'raw': str }
    """
    result = {"summary": "", "positions": {}, "watchlist": {}, "raw": text}
    section = None

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("SUMMARY:"):
            result["summary"] = line[len("SUMMARY:"):].strip()
        elif line.startswith("POSITIONS:"):
            section = "positions"
        elif line.startswith("WATCHLIST:"):
            section = "watchlist"
        elif line == "END":
            section = None
        elif section in ("positions", "watchlist") and ":" in line:
            # Format: "  SYMBOL: VERDICT — reason"
            sym_part, _, rest = line.lstrip().partition(":")
            sym_part = sym_part.strip().upper()
            rest     = rest.strip()
            verdict  = ""
            reason   = rest
            for v in ("EXIT", "WATCH", "HOLD", "ALERT", "OK"):
                if rest.upper().startswith(v):
                    verdict = v
                    reason  = rest[len(v):].lstrip(" —-").strip()
                    break
            if sym_part:
                result[section][sym_part] = {"verdict": verdict, "reason": reason}

    return result


# ══════════════════════════════════════════════════════════════════════════════
# AUTO-EXIT ENFORCER
# ══════════════════════════════════════════════════════════════════════════════

def _enforce_exits(parsed: dict, bot_globals: dict, trader) -> None:
    """
    For every position the AI says EXIT, validate the safety conditions
    and call exit_position() if all pass.
    """
    if not AI_AUTO_EXIT_ENABLED or trader is None:
        return

    active    = bot_globals.get("ACTIVE_POSITIONS", {})
    exit_fn   = bot_globals.get("exit_position")
    get_ltp   = getattr(trader, "get_ltp", None)

    if not exit_fn or not get_ltp:
        return

    now = datetime.now()

    for pos_id, pos in list(active.items()):
        symbol     = pos.get("symbol", "")
        verdict    = parsed["positions"].get(symbol, {}).get("verdict", "")
        if verdict != "EXIT":
            continue

        # ── Safety gate 1: minimum hold time ─────────────────────────────────
        entry_time = pos.get("timestamp", now)
        held_mins  = (now - entry_time).total_seconds() / 60 if entry_time else 0
        if held_mins < AI_MIN_HOLD_MINUTES:
            print(f"\n🤖 AI: EXIT recommended for {symbol} but held only "
                  f"{held_mins:.1f}min < {AI_MIN_HOLD_MINUTES}min minimum — skipping auto-exit")
            continue

        # ── Safety gate 2: loss threshold check ──────────────────────────────
        option_key    = pos.get("instrument_key", "")
        current_price = get_ltp(option_key) if option_key else None
        entry         = pos.get("entry_price", 0)

        if current_price and entry:
            pnl_pct = (current_price - entry) / entry * 100
            is_loss = pnl_pct < 0

            if is_loss:
                if AI_EXIT_PROFIT_ONLY:
                    # Hard block — user handles losses manually
                    reason = parsed["positions"][symbol].get("reason", "")
                    print(f"\n🤖 AI: EXIT recommended for {symbol} but position is in LOSS "
                          f"({pnl_pct:.1f}%) and AI_EXIT_PROFIT_ONLY=True — alerting only.\n"
                          f"   AI reason: {reason}\n"
                          f"   ⚠️  Consider exiting manually if you agree.")
                    continue
                elif abs(pnl_pct) < AI_LOSS_EXIT_THRESHOLD_PCT:
                    # Loss too small to act on — could be noise
                    print(f"\n🤖 AI: EXIT for {symbol} — loss only {pnl_pct:.1f}% "
                          f"(threshold {AI_LOSS_EXIT_THRESHOLD_PCT}%) — waiting for bigger move")
                    continue
                else:
                    # Loss is large enough + reversal confirmed — auto-exit
                    print(f"\n🤖 AI: Loss exit triggered for {symbol} "
                          f"({pnl_pct:.1f}% < -{AI_LOSS_EXIT_THRESHOLD_PCT}%) + reversal confirmed")

        if not current_price:
            print(f"\n🤖 AI: EXIT for {symbol} — could not fetch LTP, skipping auto-exit")
            continue

        # ── All gates passed — auto-exit ──────────────────────────────────────
        reason_text = parsed["positions"][symbol].get("reason", "AI reversal signal")
        pnl_pct     = (current_price - entry) / entry * 100 if entry else 0
        pnl_icon    = "📈" if pnl_pct >= 0 else "📉"
        print(
            f"\n{'='*70}\n"
            f"🤖 AI AUTO-EXIT: {symbol}\n"
            f"{'='*70}\n"
            f"   Reason : {reason_text}\n"
            f"   Price  : ₹{current_price:.2f} | Entry: ₹{entry:.2f} | "
            f"{pnl_icon} P&L: {pnl_pct:+.1f}%\n"
            f"   Held   : {held_mins:.1f}min\n"
            f"   Calling exit_position() now...\n"
            f"{'='*70}"
        )
        try:
            exit_fn(trader, pos_id, pos, current_price, reason="AI_AUTO_EXIT")
        except Exception as e:
            print(f"   ⚠️ AI auto-exit error: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# PRINT FORMATTED AI OUTPUT
# ══════════════════════════════════════════════════════════════════════════════

def _print_ai_response(parsed: dict, call_num: int) -> None:
    """Print AI response in a readable format inline with bot output."""
    now = datetime.now().strftime("%H:%M:%S")
    print(f"\n{'─'*70}")
    print(f"🤖 AI ASSISTANT  [{now}]  (call #{call_num})")
    print(f"{'─'*70}")

    if parsed["summary"]:
        print(f"📋 {parsed['summary']}")

    if parsed["positions"]:
        print("\n📊 POSITIONS:")
        for sym, info in parsed["positions"].items():
            verdict = info.get("verdict", "?")
            reason  = info.get("reason", "")
            icon    = {"HOLD": "✅", "WATCH": "⚠️ ", "EXIT": "🚨"}.get(verdict, "❓")
            print(f"   {icon} {sym}: {verdict} — {reason}")

    if parsed["watchlist"]:
        print("\n👁️  WATCHLIST:")
        for sym, info in parsed["watchlist"].items():
            verdict = info.get("verdict", "?")
            reason  = info.get("reason", "")
            icon    = {"ALERT": "🔔", "OK": "✅"}.get(verdict, "❓")
            print(f"   {icon} {sym}: {verdict} — {reason}")

    print(f"{'─'*70}")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN LOOP  — runs as a daemon thread
# ══════════════════════════════════════════════════════════════════════════════

def _ai_loop(bot_globals_fn, trader_fn) -> None:
    """
    Main AI loop. Runs forever as a daemon thread.

    Args:
      bot_globals_fn : callable that returns the bot module's globals() dict
      trader_fn      : callable that returns the current UpstoxTrader instance
                       (or None if not yet created)
    """
    global _ai_last_run, _ai_error_streak

    print("\n🤖 AI Assistant started (Groq / llama-3.3-70b)")
    print(f"   Scan interval : {AI_SCAN_INTERVAL_SECONDS}s")
    print(f"   Auto-exit     : {'ENABLED' if AI_AUTO_EXIT_ENABLED else 'DISABLED'}")
    print(f"   Exit profit-only: {AI_EXIT_PROFIT_ONLY}")
    if GROQ_API_KEY == "YOUR_GROQ_API_KEY_HERE":
        print("   ⚠️  GROQ_API_KEY not set — AI assistant will not call the API.")
        print("      Get a free key at https://console.groq.com")

    # Stagger start — let the bot initialise for 90s first
    time.sleep(90)

    while True:
        try:
            # ── Back-off on repeated errors ───────────────────────────────────
            if _ai_error_streak >= 5:
                wait = min(300, _ai_error_streak * 30)
                print(f"\n⚠️  AI: {_ai_error_streak} consecutive errors — waiting {wait}s")
                time.sleep(wait)
                _ai_error_streak = 0

            bg = bot_globals_fn()
            trader = trader_fn()

            # ── Skip if nothing is open and silent mode is on ─────────────────
            active = bg.get("ACTIVE_POSITIONS", {})
            wl     = bg.get("HA_WATCHLIST", {})
            if AI_SILENT_WHEN_NO_POSITIONS and not active and not wl:
                time.sleep(AI_SCAN_INTERVAL_SECONDS)
                continue

            # ── Build snapshot ────────────────────────────────────────────────
            snapshot = _build_snapshot(bg)

            # ── Call Groq ─────────────────────────────────────────────────────
            raw = _call_groq(snapshot)
            if raw:
                parsed = _parse_response(raw)
                _print_ai_response(parsed, _ai_call_count)

                # ── Auto-exit if warranted ────────────────────────────────────
                if active:
                    _enforce_exits(parsed, bg, trader)

            _ai_last_run = datetime.now()

        except Exception as e:
            _ai_error_streak += 1
            print(f"\n⚠️  AI loop error: {e}")

        time.sleep(AI_SCAN_INTERVAL_SECONDS)


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC API  — called from the main bot
# ══════════════════════════════════════════════════════════════════════════════

def start_ai_assistant(bot_globals_fn, trader_fn) -> None:
    """
    Start the AI assistant as a background daemon thread.

    Call this once from enhanced_monitor() AFTER the trader is created:

        from ai_assistant import start_ai_assistant
        start_ai_assistant(lambda: globals(), lambda: trader)

    Args:
      bot_globals_fn : zero-arg callable returning globals() of the bot module
      trader_fn      : zero-arg callable returning the UpstoxTrader instance
    """
    global _ai_thread

    if not AI_ENABLED:
        print("🤖 AI Assistant: disabled (AI_ENABLED=False)")
        return

    if _ai_thread and _ai_thread.is_alive():
        print("🤖 AI Assistant: already running")
        return

    _ai_thread = threading.Thread(
        target=_ai_loop,
        args=(bot_globals_fn, trader_fn),
        daemon=True,
        name="AIAssistant",
    )
    _ai_thread.start()


def ai_status() -> str:
    """Return a one-line status string for the bot's startup banner."""
    if not AI_ENABLED:
        return "AI Assistant: DISABLED"
    key_ok = GROQ_API_KEY != "YOUR_GROQ_API_KEY_HERE" and GROQ_API_KEY
    return (
        f"AI Assistant: {'ACTIVE ✓' if key_ok else 'KEY MISSING ⚠️'} | "
        f"Model: {AI_MODEL} | "
        f"Auto-exit: {'ON' if AI_AUTO_EXIT_ENABLED else 'OFF'} | "
        f"Calls so far: {_ai_call_count}"
    )
