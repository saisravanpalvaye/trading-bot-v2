"""
config.py — Single source of truth.
Change CAPITAL here and everything adjusts automatically.
Never hardcode any number in any other file.
"""
import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── Your capital ───────────────────────────────────────────
CAPITAL = 600_000          # Rs 6,00,000 — change this one number only

# ── Position sizing (auto-calculated from CAPITAL) ─────────
SIZE_STRONG_BUY = 0.15     # 15% = Rs 90,000 when HIGH CONF
SIZE_BUY        = 0.10     # 10% = Rs 60,000 standard
SIZE_WATCH      = 0.05     # 5%  = Rs 30,000 if you choose to act
MAX_OPEN_TRADES = 4        # never more than 4 positions at once
MAX_DEPLOYED    = 0.60     # never deploy more than 60% of capital

# ── Risk parameters ────────────────────────────────────────
ATR_SL_MULT         = 1.5  # SL = entry - 1.5x ATR
ATR_TGT_MULT        = 2.5  # Target = entry + 2.5x ATR  (R:R = 1.67)
ATR_PERIOD          = 14
RSI_PERIOD          = 14
MAX_HOLD_DAYS       = 6    # trading days, not calendar days

# ── Signal quality thresholds ──────────────────────────────
MIN_RR              = 1.5  # minimum reward:risk to fire any signal
MIN_EV_PCT          = 0.0  # minimum expected value %

# ── Confidence gate thresholds ─────────────────────────────
STRONG_BUY_MIN_SCORE = 5   # out of 6 factors
BUY_MIN_SCORE        = 3   # out of 6 factors
# Below 3 = WATCH only

# ── Detector thresholds ────────────────────────────────────
TREND_RSI_MIN    = 52      # weekly RSI lower bound for TREND_PULLBACK
TREND_RSI_MAX    = 66      # weekly RSI upper bound
ADX_TREND_MIN    = 18      # structural filter — blocks whippy stocks
RSI_PULLBACK_MIN = 5       # RSI must have pulled back this much from recent high
OVERSOLD_RSI_MAX = 50      # weekly RSI ceiling for OVERSOLD_EXHAUSTION
DIV_RSI_MAX      = 52      # weekly RSI ceiling for RSI_DIVERGENCE

# ── VIX regime gates ───────────────────────────────────────
VIX_AVOID   = 22           # above this → STAY IN CASH, zero signals
VIX_REDUCE  = 18           # above this → halve position sizes

# ── Win rate priors (from 10yr backtest, updated after 50 live trades) ─
SETUP_WIN_RATE = {
    "TREND_PULLBACK":      0.55,
    "OVERSOLD_EXHAUSTION": 0.52,
    "RSI_DIVERGENCE":      0.54,
}

# ── Telegram ───────────────────────────────────────────────
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ── File paths ─────────────────────────────────────────────
SIGNALS_FILE     = "signals.json"
PAPER_TRADES_FILE = "paper_trades.csv"
CALIBRATION_FILE = "calibration.json"

# ── NSE Holidays 2026 ──────────────────────────────────────
# Source: NSE official calendar
# Update annually or add dynamic fetch in phase 2
NSE_HOLIDAYS_2026 = {
    "2026-01-26",  # Republic Day
    "2026-03-26",  # Ram Navami (Holi)
    "2026-04-03",  # Good Friday
    "2026-04-14",  # Dr. Ambedkar Jayanti
    "2026-05-01",  # Maharashtra Day
    "2026-08-15",  # Independence Day
    "2026-08-27",  # Ganesh Chaturthi
    "2026-10-02",  # Gandhi Jayanti
    "2026-10-20",  # Diwali Laxmi Puja
    "2026-10-21",  # Diwali Balipratipada
    "2026-11-04",  # Gurunanak Jayanti
    "2026-12-25",  # Christmas
}

# ── Watchlist — 50 quality stocks ─────────────────────────
# Organized by sector. ADX filter in analyzer handles whippy ones dynamically.
# Do NOT blacklist stocks here — let the model filter them.
WATCHLIST = [
    # Banking
    "HDFCBANK.NS", "ICICIBANK.NS", "AXISBANK.NS", "SBIN.NS",
    "KOTAKBANK.NS", "BAJFINANCE.NS", "FEDERALBNK.NS",
    # IT
    "INFY.NS", "WIPRO.NS", "HCLTECH.NS", "LTIM.NS",
    "COFORGE.NS", "MPHASIS.NS",
    # Pharma / Hospital
    "SUNPHARMA.NS", "DRREDDY.NS", "DIVISLAB.NS",
    "APOLLOHOSP.NS", "MAXHEALTH.NS",
    # Auto
    "MARUTI.NS", "EICHERMOT.NS", "HEROMOTOCO.NS",
    "BAJAJ-AUTO.NS", "M&M.NS", "TATAMOTORS.NS",
    # FMCG
    "HINDUNILVR.NS", "ITC.NS", "NESTLEIND.NS",
    "BRITANNIA.NS", "DABUR.NS",
    # Capital Goods / Infra
    "LT.NS", "ABB.NS", "SIEMENS.NS", "HAVELLS.NS", "POLYCAB.NS",
    # Chemicals
    "DEEPAKNTR.NS", "PIDILITIND.NS", "ASIANPAINT.NS",
    # Metals / Energy
    "HINDALCO.NS", "TATASTEEL.NS", "JSWSTEEL.NS", "TATAPOWER.NS",
    # Consumer
    "TITAN.NS", "DMART.NS", "TRENT.NS",
    # Others — proven in backtest
    "ADANIPORTS.NS", "BHARTIARTL.NS", "RELIANCE.NS",
    "ULTRACEMCO.NS", "APOLLOTYRE.NS",
]

# ── Sector map ─────────────────────────────────────────────
SECTOR_MAP = {
    "HDFCBANK.NS": "BANKING",   "ICICIBANK.NS": "BANKING",
    "AXISBANK.NS": "BANKING",   "SBIN.NS":      "BANKING",
    "KOTAKBANK.NS":"BANKING",   "BAJFINANCE.NS":"BANKING",
    "FEDERALBNK.NS":"BANKING",
    "INFY.NS":  "IT",   "WIPRO.NS":   "IT",   "HCLTECH.NS": "IT",
    "LTIM.NS":  "IT",   "COFORGE.NS": "IT",   "MPHASIS.NS": "IT",
    "SUNPHARMA.NS":"PHARMA",  "DRREDDY.NS": "PHARMA",
    "DIVISLAB.NS": "PHARMA",  "APOLLOHOSP.NS":"HOSPITAL",
    "MAXHEALTH.NS":"HOSPITAL",
    "MARUTI.NS":   "AUTO",  "EICHERMOT.NS": "AUTO",
    "HEROMOTOCO.NS":"AUTO",  "BAJAJ-AUTO.NS":"AUTO",
    "M&M.NS":      "AUTO",  "TATAMOTORS.NS":"AUTO",
    "HINDUNILVR.NS":"FMCG", "ITC.NS":       "FMCG",
    "NESTLEIND.NS": "FMCG", "BRITANNIA.NS": "FMCG",
    "DABUR.NS":     "FMCG",
    "LT.NS":"CAPITAL",  "ABB.NS":"CAPITAL",  "SIEMENS.NS":"CAPITAL",
    "HAVELLS.NS":"CAPITAL", "POLYCAB.NS":"CAPITAL",
    "DEEPAKNTR.NS":"CHEMICAL", "PIDILITIND.NS":"CHEMICAL",
    "ASIANPAINT.NS":"CHEMICAL",
    "HINDALCO.NS":"METAL",  "TATASTEEL.NS":"METAL",
    "JSWSTEEL.NS":"METAL",  "TATAPOWER.NS":"ENERGY",
    "TITAN.NS":"CONSUMER",  "DMART.NS":"CONSUMER",
    "TRENT.NS":"CONSUMER",  "ADANIPORTS.NS":"INFRA",
    "BHARTIARTL.NS":"TELECOM", "RELIANCE.NS":"ENERGY",
    "ULTRACEMCO.NS":"CEMENT",  "APOLLOTYRE.NS":"AUTO",
}

# ── Auto-calibration loader ─────────────────────────────────
# paper_trader writes calibration.json after 50 closed trades
# config reads it here so win rate priors stay current
import json as _json, os as _os
if _os.path.exists(CALIBRATION_FILE):
    try:
        _cal = _json.load(open(CALIBRATION_FILE))
        _updated = _cal.get("setup_win_rate", {})
        if _updated:
            SETUP_WIN_RATE.update(_updated)
    except Exception:
        pass
