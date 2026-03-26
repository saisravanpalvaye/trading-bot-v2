"""
fetcher.py — Downloads price data for every stock in the watchlist.
One job: return clean OHLCV dataframes or None.
No logging. No Telegram. No logic. Just data.
"""
import yfinance as yf
import pandas as pd
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from config import WATCHLIST

FETCH_PERIOD   = "200d"   # enough for EMA200 + weekly RSI
FETCH_INTERVAL = "1d"
MIN_ROWS       = 60
BATCH_SIZE     = 4
BATCH_DELAY    = 2.0


def _parse(raw, ticker):
    """Parse raw yfinance output into clean OHLCV dataframe."""
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
        # Sanity check: last close should be within 4x of mean
        last  = float(df["close"].iloc[-1])
        mean  = float(df["close"].mean())
        if last <= 0 or last > mean * 4 or last < mean * 0.25:
            print(f"  [BAD DATA] {ticker}: last={last:.0f} vs mean={mean:.0f}")
            return None
        df.index = pd.to_datetime(df.index)
        return df
    except Exception:
        return None


def _fetch_one(ticker, delay=0.0):
    """Fetch a single ticker with retry."""
    if delay > 0:
        time.sleep(delay)
    for attempt in range(3):
        try:
            raw = yf.download(
                ticker, period=FETCH_PERIOD, interval=FETCH_INTERVAL,
                progress=False, auto_adjust=True, timeout=20
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
    Detect tickers sharing identical last close price — yfinance bug.
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


def fetch_all(watchlist=None):
    """
    Download all stocks in batches. Returns dict of {ticker: dataframe}.
    Failed tickers are silently dropped — analyzer handles missing data.
    """
    tickers = watchlist or WATCHLIST
    results = {}
    failed  = []

    print(f"  Fetching {len(tickers)} stocks...")

    for i in range(0, len(tickers), BATCH_SIZE):
        batch = tickers[i:i + BATCH_SIZE]
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
        if i + BATCH_SIZE < len(tickers):
            time.sleep(BATCH_DELAY)

    # Fix duplicates
    suspects = _check_duplicates(results)
    if suspects:
        print(f"  Re-fetching {len(suspects)} suspect tickers...")
        for ticker in suspects:
            results.pop(ticker, None)
            _, df = _fetch_one(ticker, delay=1.0)
            if df is not None:
                results[ticker] = df
                print(f"  Re-fetch OK: {ticker.replace('.NS', '')}")

    print(f"  Loaded {len(results)} / {len(tickers)} stocks")
    if failed:
        uniq = list(set(failed))[:8]
        print(f"  Failed: {', '.join(t.replace('.NS','') for t in uniq)}")

    return results


def fetch_nifty():
    """
    Fetch Nifty50 index for regime detection.
    Returns (rsi_value, adx_value) or (None, None) on failure.
    """
    import numpy as np
    try:
        raw = yf.download("^NSEI", period="60d", interval="1d",
                          progress=False, auto_adjust=True)
        if raw is None or len(raw) < 20:
            return None, None
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        close = raw["Close"].squeeze().astype(float).dropna()

        # RSI (Wilder EWM method)
        delta = close.diff()
        gain  = delta.clip(lower=0).ewm(com=13, adjust=False, min_periods=14).mean()
        loss  = (-delta.clip(upper=0)).ewm(com=13, adjust=False, min_periods=14).mean()
        rs    = gain / loss.replace(0, float("nan"))
        rsi   = round(float((100 - 100 / (1 + rs)).iloc[-1]), 1)

        # ADX
        hi = raw["High"].squeeze().astype(float)
        lo = raw["Low"].squeeze().astype(float)
        cl = close
        tr = pd.concat([
            (hi - lo),
            (hi - cl.shift()).abs(),
            (lo - cl.shift()).abs()
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


def fetch_vix():
    """
    Fetch India VIX. Returns (value, label, action).
    action: 'avoid' | 'reduce' | 'normal'
    """
    import requests as _req
    from config import VIX_AVOID, VIX_REDUCE

    def _classify(v):
        if v > VIX_AVOID:  return v, "Danger zone",  "avoid"
        if v > VIX_REDUCE: return v, "Elevated",     "reduce"
        return v, "Normal", "normal"

    # Method 1 — NSE direct API
    try:
        r = _req.get(
            "https://www.nseindia.com/api/allIndices",
            headers={"User-Agent": "Mozilla/5.0",
                     "Referer":    "https://www.nseindia.com"},
            timeout=8
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

    # Method 2 — yfinance fallback
    for sym in ["^INDIAVIX", "INDIAVIX.BO"]:
        try:
            raw = yf.download(sym, period="5d", interval="1d",
                              progress=False, auto_adjust=False)
            if raw is not None and len(raw) > 0:
                if isinstance(raw.columns, pd.MultiIndex):
                    raw.columns = raw.columns.get_level_values(0)
                v = round(float(raw["Close"].dropna().iloc[-1]), 1)
                if 8 <= v <= 80:
                    print(f"  VIX: {v} (yfinance)")
                    return _classify(v)
        except Exception:
            continue

    print("  VIX unavailable — assuming normal")
    return None, "Unknown", "normal"
