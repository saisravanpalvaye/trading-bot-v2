"""
intraday/upstox_api.py — Single place for Upstox candle fetches (V3 API).

Why this exists:
  - Upstox V2 historical-candle only supports 1minute / 30minute / day / week / month.
    The old code asked V2 for '15minute', which silently returned nothing.
  - V3 supports minutes/15 for history (max ~1 month per request) and has a
    separate intraday endpoint for TODAY's candles.
  - Errors are printed once (status + message) instead of being swallowed,
    so a bad/expired token is obvious instead of looking like "no data".
"""

from datetime import date
from urllib.parse import quote

import pandas as pd
import requests

import config

V3_HIST     = "https://api.upstox.com/v3/historical-candle"
V3_INTRADAY = "https://api.upstox.com/v3/historical-candle/intraday"
COLS = ["datetime", "open", "high", "low", "close", "volume", "oi"]

_reported_errors: set = set()


def _headers() -> dict:
    """Browser UA required — Cloudflare WAF (Error 1010) blocks Python default UA."""
    return {
        "Authorization": f"Bearer {config.UPSTOX_TOKEN}",
        "Accept":        "application/json",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    }


def _get(url: str) -> pd.DataFrame | None:
    try:
        r = requests.get(url, headers=_headers(), timeout=20)
    except Exception as e:
        key = f"EXC:{type(e).__name__}"
        if key not in _reported_errors:
            _reported_errors.add(key)
            print(f"[UPSTOX] request failed: {e}")
        return None

    if r.status_code != 200:
        key = f"HTTP:{r.status_code}"
        if key not in _reported_errors:
            _reported_errors.add(key)
            print(f"[UPSTOX] HTTP {r.status_code}: {r.text[:200]}")
            if r.status_code == 401:
                print("[UPSTOX] → token invalid/expired. Regenerate it and update .env")
        return None

    candles = r.json().get("data", {}).get("candles", [])
    if not candles:
        return None

    df = pd.DataFrame(candles, columns=COLS)
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.sort_values("datetime").reset_index(drop=True)
    num = ["open", "high", "low", "close", "volume"]
    df[num] = df[num].astype(float)
    df["date"] = df["datetime"].dt.date
    return df


def _k(instrument_key: str) -> str:
    # 'NSE_INDEX|Nifty 50' has '|' and a space — encode both
    return quote(instrument_key, safe="")


def daily(instrument_key: str, from_date: date, to_date: date) -> pd.DataFrame | None:
    """Completed daily candles between from_date and to_date (inclusive)."""
    url = f"{V3_HIST}/{_k(instrument_key)}/days/1/{to_date:%Y-%m-%d}/{from_date:%Y-%m-%d}"
    return _get(url)


def minutes15(instrument_key: str, from_date: date, to_date: date) -> pd.DataFrame | None:
    """Historical 15-min candles (completed days). Keep range ≤ ~28 days per call."""
    url = f"{V3_HIST}/{_k(instrument_key)}/minutes/15/{to_date:%Y-%m-%d}/{from_date:%Y-%m-%d}"
    return _get(url)


def intraday15(instrument_key: str) -> pd.DataFrame | None:
    """TODAY's 15-min candles so far (live session)."""
    url = f"{V3_INTRADAY}/{_k(instrument_key)}/minutes/15"
    return _get(url)


def candles_15m_for(instrument_key: str, day: date) -> pd.DataFrame | None:
    """15-min candles for one specific day. Today → intraday endpoint, else history.
    Never falls back to a different day (stale-bar suppression)."""
    if day == date.today():
        df = intraday15(instrument_key)
    else:
        df = minutes15(instrument_key, day, day)
    if df is None:
        return None
    df = df[df["date"] == day]
    return df if not df.empty else None
