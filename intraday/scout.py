"""
intraday/scout.py — SCOUT: Pre-9:15 AM candidate screen.

Run at 9:00 AM before the market opens.
Job: fetch prior-day data for all instruments, compute gap and 50-EMA,
     return a shortlist of stocks that COULD produce valid ORB setups today.

Output → candidates.json (loaded by FILTER at 9:31 AM)

SCOUT does NOT kill signals — it only computes observable facts.
FILTER kills. SCOUT informs.
"""

import requests
import pandas as pd
import numpy as np
from datetime import date, timedelta, datetime, timezone
from config import (
    INSTRUMENTS, NIFTY50_KEY, UPSTOX_TOKEN,
    GAP_MIN_PCT, GAP_MAX_PCT, TREND_FILTER,
    USE_NIFTY_FILTER, EARNINGS_BLOCK,
)
import logger

IST = timezone(timedelta(hours=5, minutes=30))
BASE_URL = "https://api.upstox.com/v2/historical-candle"


def _headers() -> dict:
    """Browser UA required — Cloudflare WAF (Error 1010) blocks Python default UA."""
    return {
        "Authorization": f"Bearer {UPSTOX_TOKEN}",
        "Accept":        "application/json",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    }


def _fetch_daily(instrument_key: str, days: int = 60) -> pd.DataFrame | None:
    """Fetch daily OHLCV for the last `days` calendar days."""
    to_date   = date.today().strftime("%Y-%m-%d")
    from_date = (date.today() - timedelta(days=days)).strftime("%Y-%m-%d")
    url = f"{BASE_URL}/{instrument_key}/day/{to_date}/{from_date}"
    try:
        r = requests.get(url, headers=_headers(), timeout=15)
        if r.status_code != 200:
            return None
        data = r.json().get("data", {}).get("candles", [])
        if not data:
            return None
        df = pd.DataFrame(data, columns=["datetime", "open", "high", "low", "close", "volume", "oi"])
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.sort_values("datetime").reset_index(drop=True)
        df[["open","high","low","close","volume"]] = df[["open","high","low","close","volume"]].astype(float)
        return df
    except Exception as e:
        print(f"[SCOUT] fetch_daily error {instrument_key}: {e}")
        return None


def _fetch_or_vol_avg(instrument_key: str, days: int = 25) -> float | None:
    """
    Fetch 20-day trailing average of the 9:15 AM OR-candle volume.
    Returns None if data unavailable (vol filter will be skipped for this stock).
    """
    to_date   = date.today().strftime("%Y-%m-%d")
    from_date = (date.today() - timedelta(days=days + 10)).strftime("%Y-%m-%d")
    url = f"{BASE_URL}/{instrument_key}/15minute/{to_date}/{from_date}"
    try:
        r = requests.get(url, headers=_headers(), timeout=15)
        if r.status_code != 200:
            return None
        data = r.json().get("data", {}).get("candles", [])
        if not data:
            return None
        df = pd.DataFrame(data, columns=["datetime", "open", "high", "low", "close", "volume", "oi"])
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.sort_values("datetime").reset_index(drop=True)
        df["volume"] = df["volume"].astype(float)

        # Keep only 9:15 candles (the OR candle)
        or_candles = df[df["datetime"].dt.time == datetime.strptime("09:15", "%H:%M").time()]
        if len(or_candles) < 5:
            return None
        return float(or_candles["volume"].tail(20).mean())
    except Exception as e:
        print(f"[SCOUT] fetch_or_vol_avg error {instrument_key}: {e}")
        return None


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _nifty_ok() -> bool:
    """
    Nifty gate: Nifty 50 prior close > Nifty 50 20-EMA.
    Returns True if gate passes or if data unavailable (safe default = allow).
    """
    if not USE_NIFTY_FILTER:
        return True
    df = _fetch_daily(NIFTY50_KEY, days=60)
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


def run(mode: str = "pre_market") -> list[dict]:
    """
    Screen all instruments. Return candidate list for FILTER.

    Each candidate dict:
      symbol, instrument_key, prior_close, day_open (None pre-9:15),
      ema50, gap_pct (None pre-9:15), or_vol_avg, nifty_ok, trend_ok,
      earnings_block
    """
    print(f"\n[SCOUT] Starting pre-market screen — {len(INSTRUMENTS)} instruments")

    nifty_gate = _nifty_ok()
    today_str  = date.today().strftime("%Y-%m-%d")
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

        df = _fetch_daily(ikey, days=60)
        if df is None or len(df) < 52:
            print(f"[SCOUT] {sym}: insufficient daily data")
            skipped += 1
            continue

        closes   = df["close"]
        ema50    = _ema(closes, 50)
        prior_close = float(closes.iloc[-1])
        prior_ema50 = float(ema50.iloc[-1])
        trend_ok = prior_close > prior_ema50 if TREND_FILTER else True

        # OR volume average (20-day trailing)
        or_vol_avg = _fetch_or_vol_avg(ikey, days=25)

        candidate = {
            "symbol":         sym,
            "instrument_key": ikey,
            "prior_close":    round(prior_close, 2),
            "ema50":          round(prior_ema50, 2),
            "trend_ok":       trend_ok,
            "nifty_ok":       nifty_gate,
            "or_vol_avg":     round(or_vol_avg, 0) if or_vol_avg else None,
            "earnings_block": today_str in blocked_dates,
        }
        candidates.append(candidate)

        status = "✓" if trend_ok else "✗ below 50-EMA"
        print(f"[SCOUT] {sym:<14} close={prior_close:.2f}  EMA50={prior_ema50:.2f}  "
              f"or_vol_avg={or_vol_avg:.0f if or_vol_avg else 'N/A'}  trend={status}")

        logger.log(sym, "SCOUT", "PASS", "ok", mode=mode,
                   trend_ok=trend_ok, nifty_ok=nifty_gate)

    print(f"\n[SCOUT] Done. {len(candidates)} candidates, {skipped} skipped.")
    logger.save_candidates(candidates)
    return candidates
