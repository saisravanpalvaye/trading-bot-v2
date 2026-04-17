"""
fetcher.py — Downloads price data for all stocks and sector indices.
One job: return clean data dicts. No logic. No Telegram. No file writes.

Returns:
  fetch_all()    → {ticker: DataFrame}
  fetch_sectors() → {proxy: DataFrame | None}  (None if proxy fails — safe)
  fetch_nifty()  → (rsi, adx)
  fetch_vix()    → (value, label, action)
  sector_uptrend() → bool (True if data missing — safe default)
  to_weekly()    → weekly DataFrame with partial week excluded (B1 fix)
  get_today_ist() → date in IST timezone (B10 fix — never uses date.today())
"""
import yfinance as yf
import pandas as pd
import numpy as np
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from config import WATCHLIST, SECTOR_PROXY, VIX_AVOID, VIX_REDUCE

IST = timezone(timedelta(hours=5, minutes=30))

FETCH_PERIOD   = "2y"      # 2 years for EMA200 + weekly RSI (was 200d — too short)
FETCH_INTERVAL = "1d"
MIN_ROWS       = 60
BATCH_SIZE     = 4         # proven safe — avoids yfinance duplicate data bug
BATCH_DELAY    = 2.0       # seconds between batches


# ── Timezone helper ────────────────────────────────────────

def get_today_ist():
    """
    Return today's date in IST timezone.
    NEVER use date.today() — returns UTC on GitHub Actions runners.
    B10 fix: explicit IST timezone always.
    """
    return datetime.now(IST).date()


# ── Weekly candle builder ──────────────────────────────────

def to_weekly(daily_df):
    """
    Convert daily OHLCV to weekly candles.
    ALWAYS excludes the current partial week (B1 fix).
    Only completed weeks where the Friday close is known.
    """
    df = daily_df.copy()
    df.index = pd.to_datetime(df.index)
    weekly = df.resample("W").agg({
        "open":   "first",
        "high":   "max",
        "low":    "min",
        "close":  "last",
        "volume": "sum",
    }).dropna()
    # Drop the last row — it is the current incomplete week
    # Example: if today is Wednesday, the W bucket ending Sunday
    # contains only Mon/Tue/Wed data — not a valid completed week
    if len(weekly) > 1:
        weekly = weekly.iloc[:-1]
    return weekly


# ── Data parser ────────────────────────────────────────────

def _parse(raw, ticker):
    """Parse raw yfinance output into clean OHLCV DataFrame."""
    if raw is None or len(raw) == 0:
        return None
    try:
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        df = pd.DataFrame({
            "open":   raw["Open"].squeeze().astype(float),
            "high":   raw["High"].squeeze().astype(float),
            "low":    raw["Low"].squeeze().astype(float),
            "close":  raw["Close"].squeeze().astype(float),
            "volume": raw["Volume"].squeeze().astype(float),
        }).dropna()
        if len(df) < MIN_ROWS:
            return None
        # Sanity: last close should be within 4x of mean
        last = float(df["close"].iloc[-1])
        mean = float(df["close"].mean())
        if last <= 0 or last > mean * 4 or last < mean * 0.25:
            print(f"  [BAD DATA] {ticker}: last={last:.0f} vs mean={mean:.0f}")
            return None
        df.index = pd.to_datetime(df.index)
        return df
    except Exception:
        return None


def _fetch_one(ticker, delay=0.0):
    """Fetch a single ticker with retry. Returns (ticker, df | None)."""
    if delay > 0:
        time.sleep(delay)
    for attempt in range(3):
        try:
            raw = yf.download(
                ticker, period=FETCH_PERIOD, interval=FETCH_INTERVAL,
                progress=False, auto_adjust=True, timeout=20,
            )
            df = _parse(raw, ticker)
            if df is not None:
                return ticker, df
            if attempt < 2:
                time.sleep(0.5)
        except Exception as e:
            if attempt == 2:
                print(f"  [FAIL] {ticker}: {e}")
            time.sleep(0.5)
    return ticker, None


def _check_duplicates(results):
    """
    Detect tickers sharing identical last close — yfinance batch bug.
    Returns list of suspect tickers to re-fetch individually.
    """
    from collections import defaultdict
    groups = defaultdict(list)
    for ticker, df in results.items():
        key = round(float(df["close"].iloc[-1]), 2)
        groups[key].append(ticker)
    suspects = []
    for price, tickers in groups.items():
        if len(tickers) > 1:
            names = ", ".join(t.replace(".NS", "") for t in tickers)
            print(f"  [DUPLICATE] Rs{price} shared by: {names} — re-fetching")
            suspects.extend(tickers)
    return suspects


# ── Stock data ─────────────────────────────────────────────

def fetch_all(watchlist=None):
    """
    Download all stocks in batches of 4.
    Returns {ticker: DataFrame}. Failed tickers silently dropped.
    """
    tickers = watchlist or WATCHLIST
    results = {}
    failed  = []
    total   = len(tickers)
    batch_n = (total + BATCH_SIZE - 1) // BATCH_SIZE

    print(f"  Fetching {total} stocks ({batch_n} batches)...")

    for i in range(0, total, BATCH_SIZE):
        batch = tickers[i:i + BATCH_SIZE]
        n_done = i + len(batch)
        if n_done % 20 == 0 or n_done == total:
            print(f"  {n_done}/{total}...")
        with ThreadPoolExecutor(max_workers=4) as ex:
            futures = {
                ex.submit(_fetch_one, t, j * 0.25): t
                for j, t in enumerate(batch)
            }
            for future in as_completed(futures):
                ticker, df = future.result()
                if df is not None:
                    results[ticker] = df
                else:
                    failed.append(ticker)
        if i + BATCH_SIZE < total:
            time.sleep(BATCH_DELAY)

    # Fix yfinance duplicate data bug
    suspects = _check_duplicates(results)
    if suspects:
        print(f"  Re-fetching {len(suspects)} suspect tickers...")
        for ticker in suspects:
            results.pop(ticker, None)
            _, df = _fetch_one(ticker, delay=1.0)
            if df is not None:
                results[ticker] = df
                print(f"  Re-fetch OK: {ticker.replace('.NS', '')}")

    print(f"  Loaded {len(results)} / {total} stocks")
    if failed:
        uniq = list(set(failed))[:8]
        print(f"  Failed: {', '.join(t.replace('.NS','') for t in uniq)}")

    return results


# ── Sector index data ──────────────────────────────────────

def _fetch_single_proxy(proxy):
    """
    Fetch one sector index.
    Returns DataFrame or None — NEVER crashes (B8 fix).
    ^CNXCONSUMP may 404 — caller must handle None as sector_uptrend=True.
    """
    try:
        raw = yf.download(
            proxy, period="60d", interval="1d",
            progress=False, auto_adjust=True, timeout=15,
        )
        if raw is None or len(raw) < 20:
            print(f"  [PROXY FAIL] {proxy} — 404 or insufficient data")
            return None
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        df = pd.DataFrame({
            "close": raw["Close"].squeeze().astype(float),
        }).dropna()
        if len(df) < 20:
            return None
        df.index = pd.to_datetime(df.index)
        return df
    except Exception as e:
        print(f"  [PROXY FAIL] {proxy}: {e}")
        return None


def fetch_sectors():
    """
    Download all sector index proxies.
    Returns {proxy_ticker: DataFrame | None}.
    None means proxy download failed — sector_uptrend() returns True safely.
    """
    sector_data = {}
    proxies = list(set(SECTOR_PROXY.values()))
    print(f"  Fetching {len(proxies)} sector indices...")
    for proxy in proxies:
        df = _fetch_single_proxy(proxy)
        sector_data[proxy] = df  # may be None — that's OK
        status = "OK" if df is not None else "FAILED (safe fallback)"
        print(f"  {proxy}: {status}")
    return sector_data


def sector_uptrend(sector_df, as_of_date=None):
    """
    Returns True if sector index close > EMA20.
    Returns True if data is None or empty — safe default (B8 fix).
    Never crashes regardless of input.
    """
    try:
        if sector_df is None or len(sector_df) < 20:
            return True  # safe default: don't penalise stock for bad proxy
        df = sector_df.copy()
        if as_of_date is not None:
            df = df[df.index.date <= as_of_date]
        if len(df) < 20:
            return True
        ema20 = df["close"].ewm(span=20, adjust=False).mean()
        return float(df["close"].iloc[-1]) > float(ema20.iloc[-1])
    except Exception:
        return True  # safe default on any error


# ── Nifty 50 ───────────────────────────────────────────────

def fetch_nifty():
    """
    Fetch Nifty50 for regime detection.
    Returns (rsi, adx) or (None, None) on failure.
    """
    try:
        raw = yf.download(
            "^NSEI", period="60d", interval="1d",
            progress=False, auto_adjust=True,
        )
        if raw is None or len(raw) < 20:
            return None, None
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)

        close = raw["Close"].squeeze().astype(float).dropna()
        hi    = raw["High"].squeeze().astype(float)
        lo    = raw["Low"].squeeze().astype(float)

        # RSI
        delta = close.diff()
        gain  = delta.clip(lower=0).ewm(com=13, adjust=False, min_periods=14).mean()
        loss  = (-delta.clip(upper=0)).ewm(com=13, adjust=False, min_periods=14).mean()
        rs    = gain / loss.replace(0, float("nan"))
        rsi   = round(float((100 - 100 / (1 + rs)).iloc[-1]), 1)

        # ADX
        tr   = pd.concat([
            (hi - lo),
            (hi - close.shift()).abs(),
            (lo - close.shift()).abs(),
        ], axis=1).max(axis=1)
        atr_ = tr.ewm(span=14, adjust=False).mean()
        up   = (hi - hi.shift()).clip(lower=0)
        dn   = (lo.shift() - lo).clip(lower=0)
        up   = up.where(up > dn, 0)
        dn   = dn.where(dn > up, 0)
        pdi  = up.ewm(span=14, adjust=False).mean() / atr_ * 100
        ndi  = dn.ewm(span=14, adjust=False).mean() / atr_ * 100
        dx   = (abs(pdi - ndi) / (pdi + ndi).replace(0, float("nan")) * 100).fillna(0)
        adx  = round(float(dx.ewm(span=14, adjust=False).mean().iloc[-1]), 1)

        return rsi, adx
    except Exception as e:
        print(f"  [NIFTY] {e}")
        return None, None


# ── India VIX ──────────────────────────────────────────────

def fetch_vix():
    """
    Fetch India VIX. Returns (value, label, action).
    action: 'avoid' | 'reduce' | 'normal'
    """
    def _classify(v):
        if v > VIX_AVOID:  return v, "Danger zone",  "avoid"
        if v > VIX_REDUCE: return v, "Elevated",     "reduce"
        return v,               "Normal",         "normal"

    # Method 1: NSE direct API
    try:
        import requests as _req
        r = _req.get(
            "https://www.nseindia.com/api/allIndices",
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer":    "https://www.nseindia.com",
            },
            timeout=8,
        )
        if r.status_code == 200:
            for item in r.json().get("data", []):
                if "VIX" in item.get("index", "").upper():
                    v = round(float(item.get("last", 0)), 1)
                    if 8 <= v <= 80:
                        print(f"  VIX: {v} (NSE API)")
                        return _classify(v)
    except Exception:
        pass

    # Method 2: yfinance fallback
    for sym in ["^INDIAVIX", "INDIAVIX.BO"]:
        try:
            raw = yf.download(
                sym, period="5d", interval="1d",
                progress=False, auto_adjust=False,
            )
            if raw is not None and len(raw) > 0:
                if isinstance(raw.columns, pd.MultiIndex):
                    raw.columns = raw.columns.get_level_values(0)
                v = round(float(raw["Close"].dropna().iloc[-1]), 1)
                if 8 <= v <= 80:
                    print(f"  VIX: {v} (yfinance {sym})")
                    return _classify(v)
        except Exception:
            continue

    print("  VIX unavailable — assuming normal")
    return None, "Unknown", "normal"
