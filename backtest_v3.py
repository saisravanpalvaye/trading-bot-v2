"""
backtest_v3.py — Backtest for 3 new strategies.

Strategy 1: MOMENTUM_BREAKOUT
  - Stock closes above 20-day high
  - Volume > 2x 20-day average
  - Stock above 50-day EMA
  - Sector above 20-day EMA

Strategy 2: BREAKOUT_PULLBACK
  - Stock had a valid breakout 5-15 days ago
  - Has pulled back 3-8% from breakout peak
  - Pullback volume LOW (< 1x average)
  - Still holding above breakout level
  - RSI still above 50

Strategy 3: SECTOR_ROTATION
  - Sector index breaks its own 20-day high on 1.5x volume
  - Pick strongest stock in sector by relative strength
  - Stock above 20-day EMA

Run: python backtest_v3.py
Time: ~45-60 minutes for 50 stocks
Output: backtest_v3_YYYYMMDD_HHMM.csv + console summary

Compare results against old system:
  Old: 52.1% WR, Rs 6,090/month avg, 18.4% annual
"""
import sys
import time
import warnings
warnings.filterwarnings("ignore")

try:
    import yfinance as yf
    import pandas as pd
    import numpy as np
    from datetime import date, timedelta, datetime
    print("Libraries OK")
except ImportError as e:
    print(f"Missing: {e}\nRun: pip install yfinance pandas numpy")
    sys.exit(1)

# ── Config ─────────────────────────────────────────────────
# Risk parameters
CAPITAL          = 600_000
RISK_PER_TRADE   = 6_000      # 1% of capital
MAX_POSITION     = 150_000    # 25% hard cap
HOLD_DAYS        = 8          # max hold trading days
MIN_RR           = 2.0        # minimum reward:risk

# Strategy 1 parameters
S1_VOLUME_MULT   = 2.0        # breakout needs 2x avg volume
S1_LOOKBACK      = 20         # 20-day high for breakout

# Strategy 2 parameters
S2_MIN_DAYS      = 5          # breakout at least 5 days ago
S2_MAX_DAYS      = 15         # breakout no more than 15 days ago
S2_PULLBACK_MIN  = 0.03       # min 3% pullback from peak
S2_PULLBACK_MAX  = 0.08       # max 8% pullback (else breakdown)
S2_VOL_THRESHOLD = 1.0        # pullback volume must be below avg

# Strategy 3 parameters
S3_SECTOR_VOL    = 1.5        # sector needs 1.5x volume

# SL / Target
SL_ATR_MULT      = 1.5        # SL = entry - 1.5 x ATR
TGT_ATR_MULT     = 3.0        # Target = entry + 3.0 x ATR (bigger wins)
PARTIAL_MULT     = 2.0        # partial exit at 2x ATR

START = "2015-01-01"
END   = date.today().isoformat()

# ── Watchlist (current 50 stocks) ──────────────────────────
WATCHLIST = [
    "HDFCBANK.NS", "ICICIBANK.NS", "AXISBANK.NS", "SBIN.NS",
    "KOTAKBANK.NS", "BAJFINANCE.NS", "FEDERALBNK.NS",
    "INFY.NS", "WIPRO.NS", "HCLTECH.NS", "LTIM.NS",
    "COFORGE.NS", "MPHASIS.NS",
    "SUNPHARMA.NS", "DRREDDY.NS", "DIVISLAB.NS",
    "APOLLOHOSP.NS", "MAXHEALTH.NS",
    "MARUTI.NS", "EICHERMOT.NS", "HEROMOTOCO.NS",
    "BAJAJ-AUTO.NS", "M&M.NS",
    "HINDUNILVR.NS", "ITC.NS", "NESTLEIND.NS",
    "BRITANNIA.NS", "DABUR.NS",
    "LT.NS", "ABB.NS", "SIEMENS.NS", "HAVELLS.NS", "POLYCAB.NS",
    "DEEPAKNTR.NS", "PIDILITIND.NS", "ASIANPAINT.NS",
    "HINDALCO.NS", "TATASTEEL.NS", "JSWSTEEL.NS", "TATAPOWER.NS",
    "TITAN.NS", "DMART.NS", "TRENT.NS",
    "ADANIPORTS.NS", "BHARTIARTL.NS", "RELIANCE.NS",
    "ULTRACEMCO.NS", "APOLLOTYRE.NS",
]

# Sector mapping
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
    "HEROMOTOCO.NS":"AUTO",  "BAJAJ-AUTO.NS":"AUTO", "M&M.NS":"AUTO",
    "HINDUNILVR.NS":"FMCG", "ITC.NS":"FMCG",
    "NESTLEIND.NS": "FMCG", "BRITANNIA.NS": "FMCG", "DABUR.NS":"FMCG",
    "LT.NS":"CAPITAL",  "ABB.NS":"CAPITAL",  "SIEMENS.NS":"CAPITAL",
    "HAVELLS.NS":"CAPITAL", "POLYCAB.NS":"CAPITAL",
    "DEEPAKNTR.NS":"CHEMICAL", "PIDILITIND.NS":"CHEMICAL",
    "ASIANPAINT.NS":"CHEMICAL",
    "HINDALCO.NS":"METAL",  "TATASTEEL.NS":"METAL",
    "JSWSTEEL.NS":"METAL",  "TATAPOWER.NS":"ENERGY",
    "TITAN.NS":"CONSUMER",  "DMART.NS":"CONSUMER", "TRENT.NS":"CONSUMER",
    "ADANIPORTS.NS":"INFRA", "BHARTIARTL.NS":"TELECOM",
    "RELIANCE.NS":"ENERGY",  "ULTRACEMCO.NS":"CEMENT",
    "APOLLOTYRE.NS":"AUTO",
}

# Defensive sectors allowed in Nifty downtrend
DEFENSIVE = {"PHARMA", "FMCG", "IT", "HOSPITAL"}

# Sector index proxies (using sector ETFs / indices available on yfinance)
SECTOR_PROXY = {
    "BANKING":  "^NSEBANK",
    "IT":       "^CNXIT",
    "PHARMA":   "^CNXPHARMA",
    "AUTO":     "^CNXAUTO",
    "FMCG":     "^CNXFMCG",
    "METAL":    "^CNXMETAL",
    "CAPITAL":  "^CNXINFRA",
    "CHEMICAL": "^CNXINFRA",
    "CONSUMER": "^CNXFMCG",
    "ENERGY":   "^CNXENERGY",
    "INFRA":    "^CNXINFRA",
    "TELECOM":  "^CNXINFRA",
    "CEMENT":   "^CNXINFRA",
    "HOSPITAL": "^CNXPHARMA",
}


# ── Indicator helpers ──────────────────────────────────────

def _ema(close, p):
    return close.ewm(span=p, adjust=False).mean()

def _rsi(close, p=14):
    d  = close.diff()
    ag = d.clip(lower=0).ewm(com=p-1, adjust=False, min_periods=p).mean()
    al = (-d.clip(upper=0)).ewm(com=p-1, adjust=False, min_periods=p).mean()
    return 100 - 100 / (1 + ag / al.replace(0, np.nan))

def _atr(df, p=14):
    hi = df["high"]; lo = df["low"]; cl = df["close"]
    tr = pd.concat([
        (hi - lo),
        (hi - cl.shift()).abs(),
        (lo - cl.shift()).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(span=p, adjust=False).mean()

def _vol_ratio(volume, window=20):
    """Today's volume / 20-day average volume."""
    avg = volume.rolling(window).mean()
    return volume / avg.replace(0, np.nan)


# ── SL / Target / Sizing ───────────────────────────────────

def _calc_sl_tgt(entry, atr_val):
    sl  = round(entry - SL_ATR_MULT * atr_val, 2)
    tgt = round(entry + TGT_ATR_MULT * atr_val, 2)
    partial = round(entry + PARTIAL_MULT * atr_val, 2)
    return sl, tgt, partial

def _calc_qty(entry, sl):
    """Fixed fractional: risk Rs 6,000, cap at Rs 1,50,000."""
    sl_dist = entry - sl
    if sl_dist <= 0 or sl_dist / entry < 0.003:
        return 0, 0
    qty = int(RISK_PER_TRADE / sl_dist)
    qty = max(1, qty)
    position = qty * entry
    if position > MAX_POSITION:
        qty = int(MAX_POSITION / entry)
    return qty, round(qty * entry, 0)

def _sanity(entry, sl, tgt):
    """Basic sanity checks on SL and target."""
    if sl >= entry: return False
    if tgt <= entry: return False
    if (entry - sl) / entry < 0.003: return False
    rr = (tgt - entry) / (entry - sl)
    if rr < MIN_RR: return False
    return True


# ── Trade simulator ────────────────────────────────────────

def _simulate(full_daily, entry_idx, sl, target, partial_tgt, hold_days):
    """
    Simulate trade with partial profit at 2x ATR.
    Returns (exit_reason, exit_price, partial_taken).
    """
    future = full_daily.iloc[entry_idx+1: entry_idx+1+hold_days]
    if len(future) == 0:
        return "DAY_CAP", float(full_daily["close"].iloc[entry_idx]), False

    partial_taken = False
    current_sl = sl

    for _, row in future.iterrows():
        lo = float(row["low"])
        hi = float(row["high"])
        cl = float(row["close"])

        # Partial profit at 2x ATR → move SL to breakeven
        if not partial_taken and hi >= partial_tgt:
            partial_taken = True
            current_sl = float(full_daily["close"].iloc[entry_idx])  # breakeven

        # Check SL (updated if partial taken)
        if lo <= current_sl:
            return "SL", current_sl, partial_taken

        # Check full target
        if hi >= target:
            return "TARGET", target, partial_taken

    return "DAY_CAP", float(future["close"].iloc[-1]), partial_taken


def _calc_pnl(entry, exit_price, qty, partial_taken, partial_price):
    """
    P&L with partial profit:
    - If partial taken: 50% closed at partial_price, 50% at exit_price
    - If not: 100% at exit_price
    """
    if partial_taken:
        half = qty // 2
        rest = qty - half
        pnl = (partial_price - entry) * half + (exit_price - entry) * rest
    else:
        pnl = (exit_price - entry) * qty
    return round(pnl, 2)


# ── Strategy 1: Momentum Breakout ─────────────────────────

def _s1_signal(ddf, sector_in_uptrend, nifty_in_uptrend, sector):
    """
    Returns True if MOMENTUM_BREAKOUT signal valid.
    Requirements:
      - Close > 20-day highest close (breakout)
      - Volume > 2x 20-day average
      - Stock above 50-day EMA
      - Sector in uptrend (or defensive in Nifty downtrend)
    """
    if len(ddf) < 60:
        return False

    # Regime check
    if not nifty_in_uptrend and sector not in DEFENSIVE:
        return False

    close  = ddf["close"]
    volume = ddf["volume"]

    # Breakout: today's close > highest close of last 20 days (excluding today)
    high_20 = float(close.iloc[-S1_LOOKBACK-1:-1].max())
    today_close = float(close.iloc[-1])
    if today_close <= high_20:
        return False

    # Volume confirmation
    vol_r = float(_vol_ratio(volume).iloc[-1])
    if np.isnan(vol_r) or vol_r < S1_VOLUME_MULT:
        return False

    # Stock above 50-day EMA
    ema50 = _ema(close, 50)
    if today_close < float(ema50.iloc[-1]):
        return False

    # Sector check
    if not sector_in_uptrend and sector not in DEFENSIVE:
        return False

    return True


# ── Strategy 2: Breakout Pullback ─────────────────────────

def _find_recent_breakout(ddf, lookback_max=20):
    """
    Find if there was a valid S1 breakout 5-15 days ago.
    Returns (breakout_idx, breakout_price) or (None, None).
    """
    if len(ddf) < 60:
        return None, None

    close  = ddf["close"]
    volume = ddf["volume"]
    vol_avg = volume.rolling(20).mean()

    # Check each day in the lookback window
    for days_ago in range(S2_MIN_DAYS, min(S2_MAX_DAYS + 1, len(ddf) - 20)):
        idx = len(ddf) - 1 - days_ago
        if idx < 25:
            continue

        # Was that day a breakout?
        high_20_before = float(close.iloc[idx-20:idx].max())
        day_close = float(close.iloc[idx])
        day_vol   = float(volume.iloc[idx])
        avg_vol   = float(vol_avg.iloc[idx])

        if day_close > high_20_before and avg_vol > 0:
            vol_r = day_vol / avg_vol
            if vol_r >= S1_VOLUME_MULT:
                return idx, day_close

    return None, None


def _s2_signal(ddf, sector_in_uptrend, nifty_in_uptrend, sector):
    """
    Returns True if BREAKOUT_PULLBACK signal valid.
    Requirements:
      - Valid breakout 5-15 days ago
      - Current price pulled back 3-8% from post-breakout peak
      - Still above the breakout level
      - Pullback volume below average (healthy retest)
      - RSI still above 50
    """
    if len(ddf) < 60:
        return False

    if not nifty_in_uptrend and sector not in DEFENSIVE:
        return False

    if not sector_in_uptrend and sector not in DEFENSIVE:
        return False

    # Find breakout
    breakout_idx, breakout_price = _find_recent_breakout(ddf)
    if breakout_idx is None:
        return False

    # Data since breakout
    since_breakout = ddf.iloc[breakout_idx:]
    if len(since_breakout) < 2:
        return False

    peak_since = float(since_breakout["close"].max())
    current    = float(ddf["close"].iloc[-1])

    # Must still be above breakout level
    if current < breakout_price:
        return False

    # Pullback depth: 3-8% from peak
    pullback = (peak_since - current) / peak_since
    if pullback < S2_PULLBACK_MIN or pullback > S2_PULLBACK_MAX:
        return False

    # Pullback volume must be LOW (healthy retest, not distribution)
    vol_r = float(_vol_ratio(ddf["volume"]).iloc[-1])
    if not np.isnan(vol_r) and vol_r >= S2_VOL_THRESHOLD:
        return False

    # RSI still above 50 (momentum intact)
    rsi_val = float(_rsi(ddf["close"]).iloc[-1])
    if rsi_val < 50:
        return False

    return True


# ── Strategy 3: Sector Rotation ───────────────────────────

def _s3_sector_breaking_out(sector_data, dt):
    """Check if a sector index broke its 20-day high on 1.5x volume."""
    if sector_data is None:
        return False

    sd = sector_data[sector_data.index <= dt]
    if len(sd) < 25:
        return False

    high_20 = float(sd["close"].iloc[-21:-1].max())
    today   = float(sd["close"].iloc[-1])
    vol_r   = float(_vol_ratio(sd["volume"]).iloc[-1])

    if np.isnan(vol_r):
        return False

    return today > high_20 and vol_r >= S3_SECTOR_VOL


def _s3_relative_strength(ddf, sector_data, dt, window=20):
    """
    Relative strength of stock vs sector over last 20 days.
    Higher = stronger stock vs sector.
    """
    if sector_data is None:
        return 0.0

    sd = sector_data[sector_data.index <= dt]
    dd = ddf[ddf.index <= dt]

    if len(sd) < window + 1 or len(dd) < window + 1:
        return 0.0

    stock_ret  = (float(dd["close"].iloc[-1]) / float(dd["close"].iloc[-window]) - 1) * 100
    sector_ret = (float(sd["close"].iloc[-1]) / float(sd["close"].iloc[-window]) - 1) * 100
    return round(stock_ret - sector_ret, 2)


# ── Nifty regime check ─────────────────────────────────────

def _nifty_uptrend(nifty_data, dt):
    """Nifty above 50-day EMA = uptrend."""
    if nifty_data is None:
        return True  # assume uptrend if no data

    nd = nifty_data[nifty_data.index <= dt]
    if len(nd) < 55:
        return True

    ema50 = float(_ema(nd["close"], 50).iloc[-1])
    return float(nd["close"].iloc[-1]) > ema50


def _sector_uptrend(sector_data, dt):
    """Sector index above 20-day EMA = uptrend."""
    if sector_data is None:
        return True

    sd = sector_data[sector_data.index <= dt]
    if len(sd) < 25:
        return True

    ema20 = float(_ema(sd["close"], 20).iloc[-1])
    return float(sd["close"].iloc[-1]) > ema20


# ── Data download ──────────────────────────────────────────

def _download(ticker, start, end):
    """Download and clean OHLCV data."""
    try:
        raw = yf.download(ticker, start=start, end=end,
                         interval="1d", progress=False, auto_adjust=True)
        if raw is None or len(raw) < 60:
            return None
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        df = pd.DataFrame({
            "open":   raw["Open"].squeeze().astype(float),
            "high":   raw["High"].squeeze().astype(float),
            "low":    raw["Low"].squeeze().astype(float),
            "close":  raw["Close"].squeeze().astype(float),
            "volume": raw["Volume"].squeeze().astype(float),
        }).dropna()
        df.index = pd.to_datetime(df.index)
        return df if len(df) >= 60 else None
    except Exception:
        return None


# ── Main backtest ──────────────────────────────────────────

def run_backtest():
    print("\n" + "="*60)
    print("  BACKTEST V3 — Three New Strategies")
    print(f"  Period  : {START} → {END}")
    print(f"  Stocks  : {len(WATCHLIST)}")
    print(f"  Capital : Rs {CAPITAL:,.0f}")
    print(f"  Risk/trade: Rs {RISK_PER_TRADE:,.0f} (1%)")
    print("="*60)
    print()
    print("  Strategies:")
    print("  S1 — MOMENTUM_BREAKOUT  (close > 20d high + 2x volume)")
    print("  S2 — BREAKOUT_PULLBACK  (retest of confirmed breakout)")
    print("  S3 — SECTOR_ROTATION    (sector breakout → strongest stock)")
    print()

    # ── Download Nifty ────────────────────────────────────
    print("[1/4] Downloading Nifty 50 for regime detection...")
    nifty_data = _download("^NSEI", START, END)
    if nifty_data is not None:
        print(f"  Nifty loaded: {len(nifty_data)} days")
    else:
        print("  Nifty failed — assuming uptrend throughout")

    # ── Download sector indices ───────────────────────────
    print("\n[2/4] Downloading sector indices...")
    sector_data = {}
    downloaded_proxies = set()
    for sector, proxy in SECTOR_PROXY.items():
        if proxy in downloaded_proxies:
            continue
        sd = _download(proxy, START, END)
        if sd is not None:
            sector_data[proxy] = sd
            downloaded_proxies.add(proxy)
            print(f"  {sector} ({proxy}): {len(sd)} days")
        else:
            print(f"  {proxy}: failed (sector check disabled for this sector)")
        time.sleep(0.3)

    # ── Download stocks ───────────────────────────────────
    print(f"\n[3/4] Downloading {len(WATCHLIST)} stocks...")
    all_daily = {}
    for i, ticker in enumerate(WATCHLIST, 1):
        df = _download(ticker, START, END)
        if df is not None:
            all_daily[ticker] = df
        if i % 10 == 0:
            print(f"  Downloaded {i}/{len(WATCHLIST)}...")
        time.sleep(0.25)
    print(f"  Loaded {len(all_daily)} / {len(WATCHLIST)} stocks")

    # ── Run strategies ────────────────────────────────────
    print(f"\n[4/4] Running backtest...")
    trades = []

    for ticker, ddf in all_daily.items():
        dates    = ddf.index.tolist()
        sector   = SECTOR_MAP.get(ticker, "UNKNOWN")
        s_proxy  = SECTOR_PROXY.get(sector)
        s_data   = sector_data.get(s_proxy) if s_proxy else None

        in_trade  = False
        trade_end = 0
        last_breakout_idx = {}  # track breakouts per ticker for S2

        for di in range(60, len(dates)):
            if in_trade and di < trade_end:
                continue
            in_trade = False

            dt     = dates[di]
            ddf_to = ddf.iloc[:di+1]

            # Regime checks
            nifty_up  = _nifty_uptrend(nifty_data, dt)
            sector_up = _sector_uptrend(s_data, dt)

            entry = float(ddf_to["close"].iloc[-1])
            atr_v = float(_atr(ddf_to).iloc[-1])
            if np.isnan(atr_v) or atr_v <= 0:
                continue

            sl, tgt, partial_tgt = _calc_sl_tgt(entry, atr_v)
            if not _sanity(entry, sl, tgt):
                continue

            qty, cap = _calc_qty(entry, sl)
            if qty == 0:
                continue

            # ── Try Strategy 1 ────────────────────────────
            strategy = None
            if _s1_signal(ddf_to, sector_up, nifty_up, sector):
                strategy = "MOMENTUM_BREAKOUT"

            # ── Try Strategy 2 ────────────────────────────
            elif _s2_signal(ddf_to, sector_up, nifty_up, sector):
                strategy = "BREAKOUT_PULLBACK"

            # ── Try Strategy 3 ────────────────────────────
            elif (s_data is not None and
                  _s3_sector_breaking_out(s_data, dt) and
                  sector_up):
                rs = _s3_relative_strength(ddf_to, s_data, dt)
                if rs > 0:  # stock outperforming sector
                    strategy = "SECTOR_ROTATION"

            if strategy is None:
                continue

            # ── Simulate trade ────────────────────────────
            exit_reason, exit_price, partial = _simulate(
                ddf, di, sl, tgt, partial_tgt, HOLD_DAYS
            )

            pnl    = _calc_pnl(entry, exit_price, qty, partial,
                               partial_tgt if partial else exit_price)
            result = "WIN" if pnl > 0 else "LOSS"
            rr     = round((tgt - entry) / (entry - sl), 2)

            trades.append({
                "ticker":       ticker,
                "strategy":     strategy,
                "sector":       sector,
                "entry_date":   dt.strftime("%Y-%m-%d"),
                "exit_date":    dates[min(di+HOLD_DAYS, len(dates)-1)].strftime("%Y-%m-%d"),
                "entry":        round(entry, 2),
                "exit":         round(exit_price, 2),
                "sl":           round(sl, 2),
                "target":       round(tgt, 2),
                "partial_tgt":  round(partial_tgt, 2),
                "partial_taken":partial,
                "rr":           rr,
                "qty":          qty,
                "capital":      cap,
                "pnl":          pnl,
                "exit_reason":  exit_reason,
                "result":       result,
                "nifty_uptrend":nifty_up,
                "sector_uptrend":sector_up,
            })

            in_trade  = True
            trade_end = di + HOLD_DAYS

            if len(trades) % 500 == 0 and len(trades) > 0:
                print(f"  Trades so far: {len(trades)}")

    print(f"  Total trades found: {len(trades)}")

    if not trades:
        print("\n  No trades found. Check strategy parameters.")
        return

    # ── Save ──────────────────────────────────────────────
    ts      = datetime.now().strftime("%Y%m%d_%H%M")
    outfile = f"backtest_v3_{ts}.csv"
    df_out  = pd.DataFrame(trades)
    df_out.to_csv(outfile, index=False)
    print(f"\n  Saved: {outfile}")

    # ── Print results ─────────────────────────────────────
    _print_results(df_out)


def _print_results(df):
    print("\n" + "="*60)
    print("  BACKTEST V3 RESULTS")
    print("="*60)

    w   = df[df["result"] == "WIN"]
    l   = df[df["result"] == "LOSS"]
    wr  = len(w) / len(df) * 100 if len(df) > 0 else 0
    tot = df["pnl"].sum()
    pf  = abs(w["pnl"].sum() / l["pnl"].sum()) if len(l) > 0 and l["pnl"].sum() != 0 else 999

    yrs = max(1, (pd.to_datetime(df["exit_date"].max()) -
               pd.to_datetime(df["entry_date"].min())).days / 365)

    equity = CAPITAL + df["pnl"].cumsum()
    pk = CAPITAL; mdd = 0
    for v in equity:
        pk  = max(pk, v)
        mdd = max(mdd, (pk - v) / pk)

    print(f"\n  OVERALL")
    print(f"  Trades       : {len(df)}  ({len(df)/yrs:.0f}/year, {len(df)/(yrs*12):.1f}/month)")
    print(f"  Win rate     : {wr:.1f}%  ({len(w)}W / {len(l)}L)")
    print(f"  Total P&L    : Rs {tot:+,.0f}  ({tot/CAPITAL*100:+.1f}%)")
    print(f"  Annual return: {tot/CAPITAL/yrs*100:+.1f}%/year")
    print(f"  Monthly avg  : Rs {tot/(yrs*12):+,.0f}/month")
    print(f"  Avg win      : Rs {w['pnl'].mean():+,.0f}")
    print(f"  Avg loss     : Rs {l['pnl'].mean():+,.0f}")
    print(f"  Profit factor: {pf:.2f}x")
    print(f"  Max drawdown : {mdd*100:.1f}%")

    # Compare to old system
    print(f"\n  COMPARISON TO OLD SYSTEM")
    print(f"  {'Metric':<20s} {'Old System':>15s} {'New System':>15s}")
    print(f"  {'-'*50}")
    print(f"  {'Win Rate':<20s} {'52.1%':>15s} {wr:.1f}%{''  :>10s}")
    print(f"  {'Monthly avg':<20s} {'Rs +6,090':>15s} Rs {tot/(yrs*12):+,.0f}")
    print(f"  {'Annual return':<20s} {'18.4%':>15s} {tot/CAPITAL/yrs*100:+.1f}%")
    print(f"  {'Max drawdown':<20s} {'4.2%':>15s} {mdd*100:.1f}%")
    print(f"  {'Profit factor':<20s} {'1.96x':>15s} {pf:.2f}x")

    # By strategy
    print(f"\n  BY STRATEGY")
    for s, g in df.groupby("strategy"):
        ww = len(g[g["result"] == "WIN"])
        ll = g[g["result"] == "LOSS"]
        pf2 = abs(g[g["result"]=="WIN"]["pnl"].sum() / ll["pnl"].sum()) if len(ll) > 0 and ll["pnl"].sum() != 0 else 999
        print(f"  {s:<25s}: {len(g):4d} trades  "
              f"wr={ww/len(g)*100:.0f}%  "
              f"avg=Rs {g['pnl'].mean():+,.0f}  "
              f"pf={pf2:.2f}x")

    # By exit reason
    print(f"\n  BY EXIT REASON")
    for r, g in df.groupby("exit_reason"):
        ww = len(g[g["result"] == "WIN"])
        print(f"  {r:<12s}: {len(g):4d}  "
              f"wr={ww/len(g)*100:.0f}%  "
              f"avg=Rs {g['pnl'].mean():+,.0f}  "
              f"total=Rs {g['pnl'].sum():+,.0f}")

    # Partial profit impact
    partial = df[df["partial_taken"] == True]
    no_partial = df[df["partial_taken"] == False]
    print(f"\n  PARTIAL PROFIT IMPACT")
    print(f"  Trades where partial taken : {len(partial)}")
    if len(partial) > 0:
        print(f"  Avg P&L with partial       : Rs {partial['pnl'].mean():+,.0f}")
    if len(no_partial) > 0:
        print(f"  Avg P&L without partial    : Rs {no_partial['pnl'].mean():+,.0f}")

    # Sector breakdown
    print(f"\n  BY SECTOR")
    for s, g in df.groupby("sector"):
        ww = len(g[g["result"] == "WIN"])
        print(f"  {s:<12s}: {len(g):4d}  "
              f"wr={ww/len(g)*100:.0f}%  "
              f"avg=Rs {g['pnl'].mean():+,.0f}")

    # Yearly
    print(f"\n  YEARLY P&L")
    df["year"] = pd.to_datetime(df["exit_date"]).dt.year
    for yr, g in df.groupby("year"):
        pct = g["pnl"].sum() / CAPITAL * 100
        wr_ = len(g[g["result"] == "WIN"]) / len(g) * 100
        bar = "▲" if g["pnl"].sum() > 0 else "▼"
        print(f"  {yr}  {len(g):4d} trades  "
              f"{bar} Rs {g['pnl'].sum():+9,.0f}  "
              f"({pct:+.1f}%)  wr={wr_:.0f}%")

    # Top tickers
    print(f"\n  TOP 10 TICKERS (min 5 trades)")
    ticker_stats = []
    for t, g in df.groupby("ticker"):
        if len(g) < 5:
            continue
        wr_ = len(g[g["result"] == "WIN"]) / len(g)
        ticker_stats.append((t.replace(".NS",""), len(g), wr_, g["pnl"].sum()))
    ticker_stats.sort(key=lambda x: -x[3])
    for t, n, wr_, tot_ in ticker_stats[:10]:
        bar = "█" * int(wr_ * 20)
        print(f"  {t:<15s}: {n:3d} trades  wr={wr_*100:.0f}%  "
              f"Rs {tot_:+,.0f}  {bar}")

    print("\n" + "="*60)
    print("  KEY NUMBERS TO COMPARE:")
    print(f"  New win rate:    {wr:.1f}%  (old: 52.1%)")
    print(f"  New monthly avg: Rs {tot/(yrs*12):+,.0f}  (old: Rs +6,090)")
    print(f"  New annual ret:  {tot/CAPITAL/yrs*100:+.1f}%  (old: 18.4%)")
    print(f"  New drawdown:    {mdd*100:.1f}%  (old: 4.2%)")
    print("="*60)


if __name__ == "__main__":
    t0 = time.time()
    run_backtest()
    elapsed = round(time.time() - t0)
    print(f"\n  Total time: {elapsed}s ({elapsed//60}m {elapsed%60}s)")
