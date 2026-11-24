"""
intraday/config.py — Single source of truth for the ORB intraday system.
All parameters mirror orb_upstox_backtest.py v3.
Never hardcode numbers in any other module.

System: Filtered ORB — 15-min Opening Range Breakout on Nifty 100 cash equity
Capital: Rs 2,00,000 (separate from swing bot's Rs 6,00,000)
Run:
  python brain.py --mode pre_market   # 9:00 AM — scout candidates
  python brain.py --mode market_open  # 9:31 AM — filter, rank, alert
"""

import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

# ── Upstox credentials ─────────────────────────────────────────────────────────
UPSTOX_TOKEN   = os.getenv("UPSTOX_TOKEN", "")          # set in .env or env var

# ── Telegram (shared with swing bot) ──────────────────────────────────────────
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ── Paper mode (ALWAYS start here) ────────────────────────────────────────────
# True  → EXECUTOR logs decisions; NO Telegram alert, NO real orders
# False → EXECUTOR sends Telegram alert (Phase 2: auto bracket order)
PAPER_MODE = True

# ── Capital & risk ─────────────────────────────────────────────────────────────
CAPITAL              = 200_000     # Rs 2L — intraday allocation only
RISK_PCT             = 0.01        # 1% per trade → Rs 2,000 max loss
RR                   = 2.0         # 2:1 reward-to-risk

# ── Friction (must match backtest to validate edge) ────────────────────────────
COMMISSION_RT        = 0.0006      # 0.03%/side brokerage+STT+exchange+GST
SLIPPAGE             = 0.001       # 0.1%/side — real delay/spread at 9:30 open
# Total roundtrip friction: ~0.32%  (if PF survives this, edge is real)

# ── Opening Range ──────────────────────────────────────────────────────────────
OR_WINDOW_START      = "09:15"     # IST — OR begins at market open
OR_WINDOW_END        = "09:30"     # IST — single 15-min candle
OR_MIN_PCT           = 0.003       # skip if OR width < 0.3% (flat, false breakout)
OR_MAX_PCT           = 0.020       # skip if OR width > 2.0% (gap day, chaotic)

# ── Overnight gap filter ───────────────────────────────────────────────────────
# Prevents buying exhausted gap-ups. 9:15 open vs prior-day close.
GAP_MIN_PCT          = -0.005      # allow mild gap-down (bounce potential)
GAP_MAX_PCT          =  0.020      # max gap-up — anything > 2% is Gap-and-Go (Phase 2)

# ── Timing ─────────────────────────────────────────────────────────────────────
EXIT_TIME            = "15:20"     # IST — 10-min buffer before SEBI auto sq-off

# ── Trend filter ───────────────────────────────────────────────────────────────
TREND_FILTER         = True        # True = prior close must be > 50-day EMA
USE_NIFTY_FILTER     = True        # True = Nifty 50 prior close > 20-EMA (macro gate)
USE_VOL_FILTER       = True        # True = OR candle vol > 80% of 20d avg OR vol

# ── Portfolio caps (critical — prevents margin blow-up) ───────────────────────
MAX_OPEN_POSITIONS   = 3           # max concurrent intraday trades per day
MAX_POSITION_VALUE   = CAPITAL * 1.5  # Rs 3,00,000 hard cap per single trade

# ── Volume filter ─────────────────────────────────────────────────────────────
VOL_FILTER_MIN_RATIO = 0.80        # OR candle vol must be >= 80% of 20d avg

# ── Earnings blocklist ─────────────────────────────────────────────────────────
# Skip ORB on results day and day before — earnings are gap events, not ORB setups.
# Update quarterly before going live.
EARNINGS_BLOCK: dict[str, list[str]] = {
    # "INFY": ["2026-10-16", "2026-10-17"],
}

# ── Consecutive-loss guard ─────────────────────────────────────────────────────
CONSEC_LOSS_TRIGGER  = 3           # half-size risk after N consecutive losses
CONSEC_LOSS_RISK_PCT = 0.005       # 0.5% risk after trigger

# ── File paths ─────────────────────────────────────────────────────────────────
INTRADAY_DIR         = Path(__file__).parent
DECISIONS_FILE       = INTRADAY_DIR / "decisions.csv"
CANDIDATES_FILE      = INTRADAY_DIR / "candidates.json"

# ── Nifty 50 index key (for macro gate) ───────────────────────────────────────
NIFTY50_KEY = "NSE_INDEX|Nifty 50"

# ── Instruments: top 30 liquid Nifty 100 stocks ───────────────────────────────
# Full list from Upstox instrument master:
# https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz
INSTRUMENTS = {
    "RELIANCE":    "NSE_EQ|INE002A01018",
    "TCS":         "NSE_EQ|INE467B01029",
    "HDFCBANK":    "NSE_EQ|INE040A01034",
    "INFY":        "NSE_EQ|INE009A01021",
    "ICICIBANK":   "NSE_EQ|INE090A01021",
    "SBIN":        "NSE_EQ|INE062A01020",
    "BHARTIARTL":  "NSE_EQ|INE397D01024",
    "ITC":         "NSE_EQ|INE154A01025",
    "KOTAKBANK":   "NSE_EQ|INE237A01028",
    "LT":          "NSE_EQ|INE018A01030",
    "AXISBANK":    "NSE_EQ|INE238A01034",
    "MARUTI":      "NSE_EQ|INE585B01010",
    "TITAN":       "NSE_EQ|INE280A01028",
    "SUNPHARMA":   "NSE_EQ|INE044A01036",
    "WIPRO":       "NSE_EQ|INE075A01022",
    "ULTRACEMCO":  "NSE_EQ|INE481G01011",
    "BAJFINANCE":  "NSE_EQ|INE296A01024",
    "HCLTECH":     "NSE_EQ|INE860A01027",
    "ONGC":        "NSE_EQ|INE213A01029",
    "NTPC":        "NSE_EQ|INE733E01010",
    "POWERGRID":   "NSE_EQ|INE752E01010",
    "CIPLA":       "NSE_EQ|INE059A01026",
    "DRREDDY":     "NSE_EQ|INE089A01023",
    "DIVISLAB":    "NSE_EQ|INE361B01024",
    "BAJAJFINSV":  "NSE_EQ|INE918I01026",
    "COALINDIA":   "NSE_EQ|INE522F01014",
    "BRITANNIA":   "NSE_EQ|INE216A01030",
    "HEROMOTOCO":  "NSE_EQ|INE158A01026",
    "EICHERMOT":   "NSE_EQ|INE066A01021",
    "TECHM":       "NSE_EQ|INE669C01036",
}

# ── Validation ─────────────────────────────────────────────────────────────────
def validate():
    errors = []
    if not UPSTOX_TOKEN:
        errors.append("UPSTOX_TOKEN not set — add to .env or export UPSTOX_TOKEN=...")
    if not PAPER_MODE and not TELEGRAM_TOKEN:
        errors.append("TELEGRAM_TOKEN not set — required for live alerts")
    if not PAPER_MODE and not TELEGRAM_CHAT_ID:
        errors.append("TELEGRAM_CHAT_ID not set — required for live alerts")
    return errors
