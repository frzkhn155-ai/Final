"""Jev AI (TypeSafe System One) decision gate. Key ONLY from env TYPESAFE_AI_API_KEY.
Fail-open: any error/missing key -> trade proceeds (gate never blocks on its own failure)."""
import os, csv, time, json, requests
from datetime import datetime, timezone, timedelta

_IST = timezone(timedelta(hours=5, minutes=30))

JEV_URL = os.environ.get("JEV_URL", "https://api.typesafe.ai/v1/systemone")
JEV_MODEL = os.environ.get("JEV_MODEL", "jev-latest")
JEV_TIMEOUT = float(os.environ.get("JEV_TIMEOUT", "6"))
JEV_LOG = "jev_decisions.csv"
_QUESTION = {"type": "noul", "text": "Should this trade signal be executed given current market state?"}


def _log(row):
    try:
        fe = os.path.exists(JEV_LOG)
        with open(JEV_LOG, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if not fe:
                w.writerow(["Timestamp", "Strategy", "Symbol", "Direction", "Probability",
                            "Threshold", "Decision", "LatencyMs", "Note"])
            w.writerow(row)
    except Exception:
        pass


def _extract_prob(data):
    """Tolerant parse of the response for the first yes-probability."""
    def walk(o):
        if isinstance(o, dict):
            for k in ("probability", "yes", "p", "value", "score"):
                if k in o and isinstance(o[k], (int, float)):
                    return float(o[k])
            for v in o.values():
                r = walk(v)
                if r is not None:
                    return r
        elif isinstance(o, list):
            for v in o:
                r = walk(v)
                if r is not None:
                    return r
        return None
    return walk(data.get("answers", data) if isinstance(data, dict) else data)


def jev_gate(signal, strategy="", threshold=0.6):
    """Return (should_fire, probability|None)."""
    key = os.environ.get("TYPESAFE_AI_API_KEY", "")
    ts = datetime.now(_IST).strftime("%Y-%m-%d %H:%M:%S")
    sym, d = signal.get("symbol", ""), signal.get("direction", "")
    if not key:
        _log([ts, strategy, sym, d, "", threshold, "FIRE", "", "no key (fail-open)"])
        return True, None
    state = {k: signal.get(k) for k in ("symbol", "direction", "entry", "stop", "target",
             "confidence", "fii_dii", "vol_ratio", "rsi") if signal.get(k) is not None}
    state["strategy"] = strategy
    try:
        e, s, t = signal["entry"], signal["stop"], signal["target"]
        state["risk_reward"] = round(abs(t - e) / abs(e - s), 2) if e != s else None
    except Exception:
        pass
    t0 = time.time()
    try:
        r = requests.post(JEV_URL, timeout=JEV_TIMEOUT,
                          headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                          json={"model": JEV_MODEL, "state": state, "questions": [_QUESTION]})
        ms = int((time.time() - t0) * 1000)
        r.raise_for_status()
        p = _extract_prob(r.json())
        if p is None:
            _log([ts, strategy, sym, d, "", threshold, "FIRE", ms, "unparsed (fail-open)"])
            return True, None
        ok = p >= threshold
        _log([ts, strategy, sym, d, f"{p:.3f}", threshold, "FIRE" if ok else "BLOCK", ms, ""])
        return ok, p
    except Exception as ex:
        _log([ts, strategy, sym, d, "", threshold, "FIRE", int((time.time() - t0) * 1000),
              f"error fail-open: {str(ex)[:80]}"])
        return True, None
