"""
intraday/scout.py — SCOUT: Pre-9:15 AM candidate screen.

Run at 9:00 AM before the market opens.
Job: fetch prior-day data for all instruments, compute gap and 50-EMA,
     return a shortlist of stocks that COULD produce valid ORB setups today.

Output → candidates.json (loaded by FILTER at 9:31 AM)

SCOUT does NOT kill signals — it only computes observable facts.
FILTER kills. SCOUT informs.
"""

import pandas as pd
from datetime import date, timedelta, datetime, timezone
from config import (
    INSTRUMENTS, NIFTY50_KEY,
    GAP_MIN_PCT, GAP_MAX_PCT, TREND_FILTER,
    USE_NIFTY_FILTER, EARNINGS_BLOCK,
)
import logger
import upstox_api

IST = timezone(timedelta(hours=5, minutes=30))
OR_TIME = datetime.strptime("09:15", "%H:%M").time()

# FIX-1: 60 calendar days gave ~40 bars but the check needed 52 → every stock
# was skipped. 200 calendar days ≈ 135 trading days: enough for a settled 50-EMA.
DAILY_LOOKBACK_DAYS = 200
OR_VOL_LOOKBACK_DAYS = 28   # V3 15-min history: keep under 1 month per request


def _fetch_daily(instrument_key: str, as_of: date) -> pd.DataFrame | None:
    """Completed daily candles strictly BEFORE as_of (as_of's own bar is excluded,
    so prior_close is always the previous session's close)."""
    df = upstox_api.daily(instrument_key, as_of - timedelta(days=DAILY_LOOKBACK_DAYS),
                          as_of - timedelta(days=1))
    if df is None:
        return None
    df = df[df["date"] < as_of].reset_index(drop=True)
    return df if not df.empty else None


def _fetch_or_vol_avg(instrument_key: str, as_of: date) -> float | None:
    """20-day trailing average of the 9:15 OR-candle volume, using days before as_of.
    Returns None if data unavailable (vol filter will be skipped for this stock)."""
    df = upstox_api.minutes15(instrument_key, as_of - timedelta(days=OR_VOL_LOOKBACK_DAYS),
                              as_of - timedelta(days=1))
    if df is None:
        return None
    or_candles = df[(df["datetime"].dt.time == OR_TIME) & (df["date"] < as_of)]
    if len(or_candles) < 5:
        return None
    return float(or_candles["volume"].tail(20).mean())


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _nifty_ok(as_of: date) -> bool:
    """
    Nifty gate: Nifty 50 prior close > Nifty 50 20-EMA.
    Returns True if gate passes or if data unavailable (safe default = allow).
    """
    if not USE_NIFTY_FILTER:
        return True
    df = _fetch_daily(NIFTY50_KEY, as_of)
    if df is None or len(df) < 25:
        print("[SCOUT] Nifty data unavailable — skipping Nifty gate (safe default: allow)")
        return True
    closes = df["close"]
    ema20  = _ema(closes, 20)
    prior_close = float(closes.iloc[-1])
    prior_ema20 = float(ema20.iloc[-1])
    result = prior_close > prior_ema20
    status = "✓ PASS" if result else "✗ KILL"
    print(f"[SCOUT] Nifty gate: close={prior_close:.1f}  EMA20={prior_ema20:.1f}  → {status}")
    return result


def run(mode: str = "pre_market", as_of: date | None = None) -> list[dict]:
    """
    Screen all instruments. Return candidate list for FILTER.

    Each candidate dict:
      symbol, instrument_key, prior_close, day_open (None pre-9:15),
      ema50, gap_pct (None pre-9:15), or_vol_avg, nifty_ok, trend_ok,
      earnings_block
    """
    as_of = as_of or date.today()
    print(f"\n[SCOUT] Screening {len(INSTRUMENTS)} instruments for session {as_of}")

    nifty_gate = _nifty_ok(as_of)
    today_str  = as_of.strftime("%Y-%m-%d")
    candidates = []
    skipped    = 0

    for sym, ikey in INSTRUMENTS.items():
        # Earnings blocklist check
        blocked_dates = EARNINGS_BLOCK.get(sym, [])
        if today_str in blocked_dates:
            print(f"[SCOUT] {sym}: EARNINGS BLOCK — skipping")
            logger.log(sym, "SCOUT", "KILL", f"earnings block ({today_str})", mode=mode)
            skipped += 1
            continue

        df = _fetch_daily(ikey, as_of)
        if df is None or len(df) < 52:
            n = 0 if df is None else len(df)
            print(f"[SCOUT] {sym}: insufficient daily data ({n} bars, need 52)")
            skipped += 1
            continue

        closes   = df["close"]
        ema50    = _ema(closes, 50)
        prior_close = float(closes.iloc[-1])
        prior_ema50 = float(ema50.iloc[-1])
        trend_ok = prior_close > prior_ema50 if TREND_FILTER else True

        # OR volume average (20-day trailing)
        or_vol_avg = _fetch_or_vol_avg(ikey, as_of)

        candidate = {
            "symbol":         sym,
            "instrument_key": ikey,
            "prior_close":    round(prior_close, 2),
            "ema50":          round(prior_ema50, 2),
            "trend_ok":       trend_ok,
            "nifty_ok":       nifty_gate,
            "or_vol_avg":     round(or_vol_avg, 0) if or_vol_avg else None,
            "earnings_block": today_str in blocked_dates,
            "as_of":          today_str,   # session these facts are for (stale check)
        }
        candidates.append(candidate)

        status = "✓" if trend_ok else "✗ below 50-EMA"
        # FIX-2: conditional inside a format spec is invalid Python → crashed here
        vol_txt = f"{or_vol_avg:.0f}" if or_vol_avg else "N/A"
        print(f"[SCOUT] {sym:<14} close={prior_close:.2f}  EMA50={prior_ema50:.2f}  "
              f"or_vol_avg={vol_txt}  trend={status}")

        logger.log(sym, "SCOUT", "PASS", "ok", mode=mode,
                   trend_ok=trend_ok, nifty_ok=nifty_gate)

    print(f"\n[SCOUT] Done. {len(candidates)} candidates, {skipped} skipped.")
    logger.save_candidates(candidates)
    return candidates
