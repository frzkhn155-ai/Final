"""
AI Assistant for ORB Trading Strategy
========================================
Uses Groq free tier for real-time signal analysis and market insights.

Setup:
1. Get free API key from https://console.groq.com/
2. Set GROQ_API_KEY environment variable or update below
3. The AI will analyze ORB signals and provide trading recommendations
"""

import os
import time
import requests
import json
from datetime import datetime
import threading

# Groq API Configuration
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "your_groq_api_key")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

# AI Settings
AI_ENABLED = True
AI_MODEL = "llama-3.1-70b-versatile"  # Free tier model
AI_MAX_TOKENS = 300
AI_TEMPERATURE = 0.3

# Global state
_ai_thread = None
_ai_queue = []
_ai_lock = threading.Lock()
_ai_running = False
_last_analysis = None


def ai_status():
    """Return AI assistant status"""
    if not AI_ENABLED:
        return "AI Assistant: DISABLED"
    if GROQ_API_KEY == "your_groq_api_key" or not GROQ_API_KEY:
        return "AI Assistant: API key not configured"
    return "AI Assistant: READY (Groq free tier)"


def _call_groq(prompt, system_prompt=None):
    """Call Groq API with prompt"""
    if GROQ_API_KEY == "your_groq_api_key" or not GROQ_API_KEY:
        return None
    
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    
    payload = {
        "model": AI_MODEL,
        "messages": messages,
        "max_tokens": AI_MAX_TOKENS,
        "temperature": AI_TEMPERATURE
    }
    
    try:
        response = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=30)
        if response.status_code == 200:
            data = response.json()
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"⚠️ Groq API error: {e}")
    return None


def analyze_orb_signal(orb_signal, market_data=None):
    """Analyze an ORB signal with AI"""
    if not AI_ENABLED:
        return None
    
    symbol = orb_signal.get('symbol', 'UNKNOWN')
    direction = orb_signal.get('direction', 'UNKNOWN')
    confidence = orb_signal.get('confidence', 'MEDIUM')
    rr_ratio = orb_signal.get('risk_reward', 0)
    body_pct = orb_signal.get('body_percent', 0)
    fii_dii = orb_signal.get('fii_dii_signal', 'NEUTRAL')
    rsi = orb_signal.get('rsi_at_signal')
    klinger = orb_signal.get('klinger_at_signal')
    klinger_str = f"{klinger/1e6:.2f}M" if klinger else 'N/A'
    
    # Build analysis prompt
    prompt = f"""Analyze this ORB (Opening Range Breakout) trading signal:

SYMBOL: {symbol}
DIRECTION: {direction}
CONFIDENCE: {confidence}
RISK:REWARD: {rr_ratio:.2f}:1
CANDLE BODY: {body_pct:.2f}%
FII/DII: {fii_dii}
RSI: {rsi if rsi else 'N/A'}
KLINGER: {klinger_str}

Provide:
1. Signal Quality (1-10): 
2. Key Observations:
3. Trade Recommendation (ENTER/SKIP/WAIT):
4. Risk Factors:

Keep response under 200 words."""

    system_prompt = """You are an expert trading analyst specializing in momentum 
and breakout strategies. Provide concise, actionable analysis. 
Use bullet points. Be decisive with recommendations."""

    return _call_groq(prompt, system_prompt)


def analyze_market_sentiment():
    """Get overall market sentiment analysis"""
    if not AI_ENABLED:
        return None
    
    prompt = """Provide a brief market analysis for NSE (India) equity:

1. Current market outlook (bullish/bearish/neutral)
2. Key sectors to watch
3. Important support/resistance levels
4. Risk assessment for new trades

Keep under 150 words. Be specific and actionable."""

    return _call_groq(prompt)


def analyze_stop_loss(symbol, entry_price, stop_price, target_price):
    """Analyze trade exit levels"""
    if not AI_ENABLED:
        return None
    
    risk = entry_price - stop_price
    reward = target_price - entry_price
    rr = reward / risk if risk > 0 else 0
    
    prompt = f"""Analyze this trade setup:

SYMBOL: {symbol}
ENTRY: ₹{entry_price:.2f}
STOP LOSS: ₹{stop_price:.2f}
TARGET: ₹{target_price:.2f}
RISK:REWARD: {rr:.2f}:1
RISK PER SHARE: ₹{risk:.2f}

Provide:
1. Stop loss appropriateness (too tight/good/loose)
2. Target feasibility
3. Position sizing suggestion
4. Any concerns

Keep under 150 words."""

    return _call_groq(prompt)


def get_trade_idea(symbol, direction, context=None):
    """Get AI trade idea for a symbol"""
    if not AI_ENABLED:
        return None
    
    prompt = f"""Generate a trading idea for:

SYMBOL: {symbol}
DIRECTION: {direction}
CONTEXT: {context or 'No additional context'}

Provide:
1. Entry rationale
2. Suggested entry price range
3. Stop loss level
4. Target price
5. Timeframe
6. Key catalysts

Keep under 200 words."""

    return _call_groq(prompt)


# ========== BACKGROUND AI PROCESSOR ==========
def _process_ai_queue():
    """Background thread to process AI requests"""
    global _ai_running, _last_analysis
    
    while _ai_running:
        with _ai_lock:
            if not _ai_queue:
                time.sleep(1)
                continue
            
            request = _ai_queue.pop(0)
        
        request_type = request.get('type')
        
        if request_type == 'signal_analysis':
            result = analyze_orb_signal(request.get('signal'), request.get('market_data'))
        elif request_type == 'market_sentiment':
            result = analyze_market_sentiment()
        elif request_type == 'stop_loss':
            result = analyze_stop_loss(
                request.get('symbol'),
                request.get('entry_price'),
                request.get('stop_price'),
                request.get('target_price')
            )
        elif request_type == 'trade_idea':
            result = get_trade_idea(
                request.get('symbol'),
                request.get('direction'),
                request.get('context')
            )
        else:
            result = None
        
        _last_analysis = {
            'type': request_type,
            'result': result,
            'timestamp': datetime.now()
        }
        
        # Small delay to avoid rate limits
        time.sleep(2)


def queue_ai_analysis(request_type, **kwargs):
    """Queue an AI analysis request"""
    if not AI_ENABLED:
        return None
    
    with _ai_lock:
        _ai_queue.append({
            'type': request_type,
            **kwargs
        })


def get_last_ai_analysis():
    """Get the last AI analysis result"""
    return _last_analysis


def start_ai_assistant(get_globals=None, get_trader=None):
    """Start the AI assistant background thread"""
    global _ai_running, _ai_thread
    
    if not AI_ENABLED:
        return
    
    if GROQ_API_KEY == "your_groq_api_key" or not GROQ_API_KEY:
        print("⚠️ AI: API key not configured - set GROQ_API_KEY")
        return
    
    if _ai_running:
        return
    
    _ai_running = True
    _ai_thread = threading.Thread(target=_process_ai_queue, daemon=True)
    _ai_thread.start()
    print("✅ AI Assistant started (Groq free tier)")


def stop_ai_assistant():
    """Stop the AI assistant"""
    global _ai_running
    _ai_running = False


# ========== QUICK AI FUNCTIONS ==========
def quick_signal_check(symbol, direction, rr_ratio, confidence):
    """Quick signal quality check - returns immediate assessment"""
    if not AI_ENABLED or not GROQ_API_KEY or GROQ_API_KEY == "your_groq_api_key":
        # Return basic logic-based assessment
        score = 0
        if rr_ratio >= 2.0:
            score += 3
        elif rr_ratio >= 1.5:
            score += 2
        else:
            score -= 1
        
        if confidence == 'VERY_HIGH':
            score += 4
        elif confidence == 'HIGH':
            score += 2
        else:
            score -= 1
        
        if direction == 'BUY':
            score += 1
        else:
            score += 0
        
        if score >= 5:
            return "STRONG BUY", score
        elif score >= 3:
            return "BUY", score
        elif score >= 1:
            return "NEUTRAL", score
        else:
            return "SKIP", score
    
    # Use AI if configured
    prompt = f"""Quick signal assessment:

Symbol: {symbol}
Direction: {direction}
Risk:Reward: {rr_ratio:.2f}:1
Confidence: {confidence}

Reply with only one word: BUY, SKIP, or NEUTRAL"""

    result = _call_groq(prompt)
    if result:
        result = result.strip().upper()
        if 'BUY' in result:
            return "BUY", 5
        elif 'SKIP' in result:
            return "SKIP", 1
    return "NEUTRAL", 3


# ========== ORB AI INTEGRATION ==========
def ai_analyze_orb_breakout(symbol, orb_data, trader=None):
    """Analyze ORB breakout with AI and return decision"""
    print(f"\n🤖 AI Analyzing ORB breakout for {symbol}...")
    
    # Get quick assessment first
    direction = orb_data.get('direction', 'BUY')
    rr = orb_data.get('risk_reward', 0)
    confidence = orb_data.get('confidence', 'MEDIUM')
    
    quick_decision, score = quick_signal_check(symbol, direction, rr, confidence)
    print(f"   Quick Check: {quick_decision} (score: {score})")
    
    # Queue detailed analysis
    queue_ai_analysis('signal_analysis', signal=orb_data)
    
    # Get last analysis
    time.sleep(1)  # Give AI time to process
    last = get_last_ai_analysis()
    
    if last and last.get('result'):
        print(f"\n📊 AI Detailed Analysis:")
        print(f"   {last['result']}")
        return last['result']
    
    return quick_decision


def ai_market_check():
    """Get AI market sentiment"""
    if not AI_ENABLED:
        return "AI not configured"
    
    queue_ai_analysis('market_sentiment')
    time.sleep(2)
    
    last = get_last_ai_analysis()
    if last and last.get('result'):
        return last['result']
    return "Analysis pending..."


# ========== EXAMPLE USAGE ==========
if __name__ == "__main__":
    print("="*60)
    print("AI Assistant Test")
    print("="*60)
    
    print(f"\nStatus: {ai_status()}")
    
    if AI_ENABLED and GROQ_API_KEY != "your_groq_api_key":
        # Test market sentiment
        print("\n📊 Testing market sentiment analysis...")
        sentiment = analyze_market_sentiment()
        if sentiment:
            print(f"Market Sentiment:\n{sentiment}")
        
        # Test signal analysis
        print("\n📊 Testing signal analysis...")
        test_signal = {
            'symbol': 'RELIANCE',
            'direction': 'BUY',
            'confidence': 'HIGH',
            'risk_reward': 2.5,
            'body_percent': 1.2,
            'fii_dii_signal': 'STRONG_BUY',
            'rsi_at_signal': 58,
            'klinger_at_signal': 50000000
        }
        analysis = analyze_orb_signal(test_signal)
        if analysis:
            print(f"Signal Analysis:\n{analysis}")
    else:
        print("\n⚠️ Configure GROQ_API_KEY to enable AI features")
        print("   Get free key at: https://console.groq.com/")
        
        # Test basic logic
        print("\n📊 Testing basic logic (no API)...")
        decision, score = quick_signal_check('RELIANCE', 'BUY', 2.5, 'HIGH')
        print(f"   Decision: {decision}, Score: {score}")