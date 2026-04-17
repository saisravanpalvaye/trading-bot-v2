"""
config.py — Single source of truth for V6 N200c.
Change CAPITAL here and everything adjusts automatically.
Never hardcode any number in any other file.

Strategy: V6 N200c
  ATR_SL_MULT=2.0, ATR_TGT_MULT=3.0, ATR_PARTIAL_MULT=2.0
  Fixed fractional risk: Rs 6,000 per trade
  Universe: 126 Nifty 200 stocks (4 weak removed)
  Backtest: Rs 20,468/mo, 55.8% WR, 8.1% max drawdown (10yr)
"""
import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── Capital ────────────────────────────────────────────────
CAPITAL = 600_000          # Rs 6,00,000 — change this one number only

# ── Fixed fractional risk sizing (V6 — replaces % sizing) ──
# Risk exactly Rs 6,000 per trade regardless of setup quality.
# Position size = RISK_PER_TRADE / (entry - sl)
# Position capped at MAX_POSITION regardless of calculated size.
RISK_PER_TRADE  = 6_000    # Rs 6,000 = 1% of Rs 6L capital
MAX_POSITION    = 150_000  # Rs 1,50,000 hard cap per position (25%)
MAX_DEPLOYED    = 360_000  # Rs 3,60,000 = 60% of capital max deployed

# ── V6 strategy parameters (LOCKED — do not change without backtest) ──
ATR_SL_MULT         = 2.0  # SL   = entry - 2.0 * ATR
ATR_TGT_MULT        = 3.0  # TGT  = entry + 3.0 * ATR  → RR = 1.5
ATR_PARTIAL_MULT    = 2.0  # Partial exit at entry + 2.0 * ATR (50% qty)
ATR_PERIOD          = 14
RSI_PERIOD          = 14
HOLD_DAYS           = 8    # trading days (not calendar days)

# ── Quality gates ──────────────────────────────────────────
MIN_RR              = 1.5  # minimum reward:risk — enforced by math (3.0/2.0=1.5)
MIN_EV_PCT          = 0.0  # minimum expected value %
MIN_SL_DIST_PCT     = 0.3  # SL must be >= 0.3% below entry (sanity gate)

# ── Setup detection thresholds ─────────────────────────────
TREND_RSI_MIN    = 52      # weekly RSI lower bound for TREND_PULLBACK
TREND_RSI_MAX    = 66      # weekly RSI upper bound
ADX_TREND_MIN    = 18      # structural filter — blocks whippy stocks
RSI_PULLBACK_MIN = 5       # RSI must have pulled back this much from recent peak
OVERSOLD_RSI_MAX = 38      # weekly RSI ceiling for OVERSOLD_EXHAUSTION (V6: was 50)
DIV_RSI_MAX      = 52      # weekly RSI ceiling for RSI_DIVERGENCE

# ── VIX gates (LOCKED) ────────────────────────────────────
VIX_AVOID   = 22           # above this → STAY IN CASH, zero signals
VIX_REDUCE  = 18           # above this → size_multiplier = 0.5

# ── Confidence scoring ─────────────────────────────────────
# 7 factors total (6 original + RVOL as 7th)
# BUY  = score >= 4
# WATCH = score < 4
BUY_MIN_SCORE   = 4        # V6 threshold (was 3 in old system)
MAX_CONF_SCORE  = 7        # max possible score (6 factors + RVOL)
RVOL_MIN        = 1.5      # volume must be 1.5x 20-day avg to score RVOL point

# ── Risk management rules (LOCKED) ────────────────────────
MONTHLY_LOSS_FLOOR  = 30_000   # stop new signals if month loss exceeds this
CONSEC_LOSS_LIMIT   = 3        # consecutive losses → size_multiplier = 0.5

# ── Win rate priors (from N200c 10yr backtest) ─────────────
# Updated automatically by calibration after 50 live trades
SETUP_WIN_RATE = {
    "TREND_PULLBACK":      0.56,   # N200c: 56% WR
    "OVERSOLD_EXHAUSTION": 0.66,   # N200c: 66% WR (Nifty50 only)
    "RSI_DIVERGENCE":      0.55,   # N200c: 55% WR
    "BREAKOUT_PULLBACK":   0.56,   # N200c: 56% WR
}

# ── Telegram ───────────────────────────────────────────────
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "5001387539")

# ── File paths ─────────────────────────────────────────────
SIGNALS_FILE      = "signals.json"
PAPER_TRADES_FILE = "paper_trades.csv"
TRADE_LOG_FILE    = "trade_log.csv"
CALIBRATION_FILE  = "calibration.json"

# ── NSE Holidays 2026 ──────────────────────────────────────
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

# ── Nifty 50 set — OVERSOLD_EXHAUSTION restricted to these ─
# OE on midcaps was 50% WR (noise). On Nifty50 it's 66% WR (signal).
NIFTY50 = {
    "HDFCBANK.NS", "ICICIBANK.NS", "AXISBANK.NS", "SBIN.NS",
    "KOTAKBANK.NS", "BAJFINANCE.NS", "INFY.NS", "WIPRO.NS",
    "HCLTECH.NS", "TCS.NS", "TECHM.NS", "SUNPHARMA.NS",
    "DRREDDY.NS", "DIVISLAB.NS", "CIPLA.NS", "MARUTI.NS",
    "EICHERMOT.NS", "HEROMOTOCO.NS", "BAJAJ-AUTO.NS", "M&M.NS",
    "HINDUNILVR.NS", "ITC.NS", "NESTLEIND.NS", "BRITANNIA.NS",
    "DABUR.NS", "LT.NS", "ABB.NS", "SIEMENS.NS", "HAVELLS.NS",
    "POLYCAB.NS", "DEEPAKNTR.NS", "PIDILITIND.NS", "ASIANPAINT.NS",
    "HINDALCO.NS", "TATASTEEL.NS", "JSWSTEEL.NS", "TATAPOWER.NS",
    "RELIANCE.NS", "TITAN.NS", "DMART.NS", "TRENT.NS",
    "ADANIPORTS.NS", "ULTRACEMCO.NS", "NTPC.NS", "POWERGRID.NS",
    "ONGC.NS", "COALINDIA.NS", "BHARATFORG.NS", "APOLLOTYRE.NS",
    "ADANIGREEN.NS",
}

# ── Sector proxy map ───────────────────────────────────────
# Maps sector name → yfinance index ticker for sector uptrend gate
# CHEMICAL and CONSUMER were WRONG in old system (used ^CNXINFRA) — fixed here
SECTOR_PROXY = {
    "BANKING":  "^NSEBANK",
    "IT":       "^CNXIT",
    "PHARMA":   "^CNXPHARMA",
    "AUTO":     "^CNXAUTO",
    "FMCG":     "^CNXFMCG",
    "METAL":    "^CNXMETAL",
    "CAPITAL":  "^CNXINFRA",
    "CHEMICAL": "^CNXFMCG",    # FIXED: was ^CNXINFRA — FMCG is closest available
    "CONSUMER": "^CNXCONSUMP", # FIXED: was ^CNXFMCG — Nifty India Consumption
    "ENERGY":   "^CNXENERGY",
    "INFRA":    "^CNXINFRA",
    "NBFC":     "^CNXFIN",     # Nifty Financial Services
    "PSU":      "^CNXPSE",     # Nifty PSE index
}

# ── N200c Watchlist — 126 stocks ──────────────────────────
# Nifty 200 universe with exclusions:
#   TELECOM: BHARTIARTL removed (29% WR in backtest)
#   HOSPITAL: APOLLOHOSP, MAXHEALTH removed (41% WR)
#   TATAMOTORS: delisted from Yahoo Finance
#   PSU weak: IRFC (50% WR), RAILTEL (43% WR) removed
#   NBFC weak: M&MFIN (44% WR), LICHSGFIN (48% WR) removed
WATCHLIST = [
    # BANKING (15)
    "HDFCBANK.NS", "ICICIBANK.NS", "AXISBANK.NS", "SBIN.NS",
    "KOTAKBANK.NS", "BAJFINANCE.NS", "FEDERALBNK.NS",
    "BANDHANBNK.NS", "IDFCFIRSTB.NS", "INDUSINDBK.NS",
    "AUBANK.NS", "CANBK.NS", "PNB.NS", "BANKBARODA.NS",
    "RBLBANK.NS",
    # IT (11)
    "INFY.NS", "WIPRO.NS", "HCLTECH.NS", "LTIM.NS",
    "COFORGE.NS", "MPHASIS.NS", "TCS.NS", "TECHM.NS",
    "PERSISTENT.NS", "OFSS.NS", "KPITTECH.NS",
    # PHARMA (9)
    "SUNPHARMA.NS", "DRREDDY.NS", "DIVISLAB.NS",
    "CIPLA.NS", "AUROPHARMA.NS", "TORNTPHARM.NS",
    "ALKEM.NS", "LUPIN.NS", "IPCALAB.NS",
    # AUTO (11 — TATAMOTORS excluded, delisted from Yahoo)
    "MARUTI.NS", "EICHERMOT.NS", "HEROMOTOCO.NS",
    "BAJAJ-AUTO.NS", "M&M.NS", "APOLLOTYRE.NS",
    "BALKRISIND.NS", "MOTHERSON.NS", "BOSCHLTD.NS",
    "EXIDEIND.NS", "BHARATFORG.NS",
    # FMCG (11)
    "HINDUNILVR.NS", "ITC.NS", "NESTLEIND.NS",
    "BRITANNIA.NS", "DABUR.NS", "MARICO.NS",
    "GODREJCP.NS", "EMAMILTD.NS", "COLPAL.NS",
    "TATACONSUM.NS", "VBL.NS",
    # CAPITAL (11)
    "LT.NS", "ABB.NS", "SIEMENS.NS", "HAVELLS.NS",
    "POLYCAB.NS", "BEL.NS", "HAL.NS", "BHEL.NS",
    "CUMMINSIND.NS", "THERMAX.NS", "GRINDWELL.NS",
    # CHEMICAL (8)
    "DEEPAKNTR.NS", "PIDILITIND.NS", "ASIANPAINT.NS",
    "AARTIIND.NS", "NAVINFLUOR.NS", "ATUL.NS",
    "GUJGASLTD.NS", "LINDEINDIA.NS",
    # METAL (9)
    "HINDALCO.NS", "TATASTEEL.NS", "JSWSTEEL.NS",
    "COALINDIA.NS", "NMDC.NS", "SAIL.NS",
    "VEDL.NS", "NATIONALUM.NS", "APLAPOLLO.NS",
    # ENERGY (12)
    "TATAPOWER.NS", "RELIANCE.NS", "ONGC.NS",
    "POWERGRID.NS", "NTPC.NS", "ADANIGREEN.NS",
    "TORNTPOWER.NS", "CESC.NS", "NHPC.NS",
    "ADANIPOWER.NS", "IOC.NS", "BPCL.NS",
    # CONSUMER (10)
    "TITAN.NS", "DMART.NS", "TRENT.NS",
    "PAGEIND.NS", "VOLTAS.NS", "DIXON.NS",
    "KAJARIACER.NS", "BATAINDIA.NS", "VGUARD.NS", "WHIRLPOOL.NS",
    # INFRA (8)
    "ADANIPORTS.NS", "ULTRACEMCO.NS", "SHREECEM.NS",
    "ACC.NS", "AMBUJACEM.NS", "DLF.NS",
    "GODREJPROP.NS", "OBEROIRLTY.NS",
    # NBFC (6 — M&MFIN and LICHSGFIN removed: weak WR)
    "BAJAJFINSV.NS", "CHOLAFIN.NS", "MUTHOOTFIN.NS",
    "SUNDARMFIN.NS", "SHRIRAMFIN.NS", "PIRAMALENT.NS",
    # PSU (5 — IRFC and RAILTEL removed: weak WR)
    "RVNL.NS", "PFC.NS", "RECLTD.NS", "HUDCO.NS", "NBCC.NS",
]

# ── Sector map — all 126 tickers ──────────────────────────
SECTOR_MAP = {
    # BANKING
    "HDFCBANK.NS":   "BANKING", "ICICIBANK.NS":  "BANKING",
    "AXISBANK.NS":   "BANKING", "SBIN.NS":       "BANKING",
    "KOTAKBANK.NS":  "BANKING", "BAJFINANCE.NS": "BANKING",
    "FEDERALBNK.NS": "BANKING", "BANDHANBNK.NS": "BANKING",
    "IDFCFIRSTB.NS": "BANKING", "INDUSINDBK.NS": "BANKING",
    "AUBANK.NS":     "BANKING", "CANBK.NS":      "BANKING",
    "PNB.NS":        "BANKING", "BANKBARODA.NS": "BANKING",
    "RBLBANK.NS":    "BANKING",
    # IT
    "INFY.NS":       "IT", "WIPRO.NS":     "IT",
    "HCLTECH.NS":    "IT", "LTIM.NS":      "IT",
    "COFORGE.NS":    "IT", "MPHASIS.NS":   "IT",
    "TCS.NS":        "IT", "TECHM.NS":     "IT",
    "PERSISTENT.NS": "IT", "OFSS.NS":      "IT",
    "KPITTECH.NS":   "IT",
    # PHARMA
    "SUNPHARMA.NS":  "PHARMA", "DRREDDY.NS":    "PHARMA",
    "DIVISLAB.NS":   "PHARMA", "CIPLA.NS":      "PHARMA",
    "AUROPHARMA.NS": "PHARMA", "TORNTPHARM.NS": "PHARMA",
    "ALKEM.NS":      "PHARMA", "LUPIN.NS":      "PHARMA",
    "IPCALAB.NS":    "PHARMA",
    # AUTO
    "MARUTI.NS":     "AUTO", "EICHERMOT.NS":  "AUTO",
    "HEROMOTOCO.NS": "AUTO", "BAJAJ-AUTO.NS": "AUTO",
    "M&M.NS":        "AUTO", "APOLLOTYRE.NS": "AUTO",
    "BALKRISIND.NS": "AUTO", "MOTHERSON.NS":  "AUTO",
    "BOSCHLTD.NS":   "AUTO", "EXIDEIND.NS":   "AUTO",
    "BHARATFORG.NS": "AUTO",
    # FMCG
    "HINDUNILVR.NS": "FMCG", "ITC.NS":       "FMCG",
    "NESTLEIND.NS":  "FMCG", "BRITANNIA.NS": "FMCG",
    "DABUR.NS":      "FMCG", "MARICO.NS":    "FMCG",
    "GODREJCP.NS":   "FMCG", "EMAMILTD.NS":  "FMCG",
    "COLPAL.NS":     "FMCG", "TATACONSUM.NS":"FMCG",
    "VBL.NS":        "FMCG",
    # CAPITAL
    "LT.NS":         "CAPITAL", "ABB.NS":       "CAPITAL",
    "SIEMENS.NS":    "CAPITAL", "HAVELLS.NS":   "CAPITAL",
    "POLYCAB.NS":    "CAPITAL", "BEL.NS":       "CAPITAL",
    "HAL.NS":        "CAPITAL", "BHEL.NS":      "CAPITAL",
    "CUMMINSIND.NS": "CAPITAL", "THERMAX.NS":   "CAPITAL",
    "GRINDWELL.NS":  "CAPITAL",
    # CHEMICAL
    "DEEPAKNTR.NS":  "CHEMICAL", "PIDILITIND.NS": "CHEMICAL",
    "ASIANPAINT.NS": "CHEMICAL", "AARTIIND.NS":   "CHEMICAL",
    "NAVINFLUOR.NS": "CHEMICAL", "ATUL.NS":       "CHEMICAL",
    "GUJGASLTD.NS":  "CHEMICAL", "LINDEINDIA.NS": "CHEMICAL",
    # METAL
    "HINDALCO.NS":   "METAL", "TATASTEEL.NS":  "METAL",
    "JSWSTEEL.NS":   "METAL", "COALINDIA.NS":  "METAL",
    "NMDC.NS":       "METAL", "SAIL.NS":       "METAL",
    "VEDL.NS":       "METAL", "NATIONALUM.NS": "METAL",
    "APLAPOLLO.NS":  "METAL",
    # ENERGY
    "TATAPOWER.NS":  "ENERGY", "RELIANCE.NS":   "ENERGY",
    "ONGC.NS":       "ENERGY", "POWERGRID.NS":  "ENERGY",
    "NTPC.NS":       "ENERGY", "ADANIGREEN.NS": "ENERGY",
    "TORNTPOWER.NS": "ENERGY", "CESC.NS":       "ENERGY",
    "NHPC.NS":       "ENERGY", "ADANIPOWER.NS": "ENERGY",
    "IOC.NS":        "ENERGY", "BPCL.NS":       "ENERGY",
    # CONSUMER
    "TITAN.NS":      "CONSUMER", "DMART.NS":      "CONSUMER",
    "TRENT.NS":      "CONSUMER", "PAGEIND.NS":    "CONSUMER",
    "VOLTAS.NS":     "CONSUMER", "DIXON.NS":      "CONSUMER",
    "KAJARIACER.NS": "CONSUMER", "BATAINDIA.NS":  "CONSUMER",
    "VGUARD.NS":     "CONSUMER", "WHIRLPOOL.NS":  "CONSUMER",
    # INFRA
    "ADANIPORTS.NS": "INFRA", "ULTRACEMCO.NS": "INFRA",
    "SHREECEM.NS":   "INFRA", "ACC.NS":        "INFRA",
    "AMBUJACEM.NS":  "INFRA", "DLF.NS":        "INFRA",
    "GODREJPROP.NS": "INFRA", "OBEROIRLTY.NS": "INFRA",
    # NBFC
    "BAJAJFINSV.NS": "NBFC", "CHOLAFIN.NS":   "NBFC",
    "MUTHOOTFIN.NS": "NBFC", "SUNDARMFIN.NS": "NBFC",
    "SHRIRAMFIN.NS": "NBFC", "PIRAMALENT.NS": "NBFC",
    # PSU
    "RVNL.NS":  "PSU", "PFC.NS":   "PSU",
    "RECLTD.NS":"PSU", "HUDCO.NS": "PSU",
    "NBCC.NS":  "PSU",
}

# ── Auto-calibration loader ────────────────────────────────
# scoreboard writes calibration.json after 50 closed trades
import json as _json
if os.path.exists(CALIBRATION_FILE):
    try:
        _cal = _json.load(open(CALIBRATION_FILE))
        _updated = _cal.get("setup_win_rate", {})
        if _updated:
            SETUP_WIN_RATE.update(_updated)
    except Exception:
        pass
