"""
ml_signal_filter.py — XGBoost signal filter for V6 N200c.

Pipeline:
  1. Pull & sanitize OHLCV (3 years, yfinance, point-in-time safe)
  2. Build features strictly from data available at alert trigger bar
  3. Join and label trades from trade_log.csv (WIN=1, LOSS=0)
  4. Walk-forward / purged validation (no lookahead)
  5. Train final model; save as ml_model.pkl + ml_scaler.pkl
  6. Shadow mode: p_win logged in alert.py without blocking (see integration note)

Usage:
  python ml_signal_filter.py --train      # train + validate, save model
  python ml_signal_filter.py --predict TICKER SETUP_TYPE  # score one signal
  python ml_signal_filter.py --shadow     # score today's signals.json
"""

import argparse
import json
import os
import sys
import warnings
from datetime import datetime, timedelta, date

import joblib
import numpy as np
import pandas as pd
import yfinance as yf
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, precision_recall_curve
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore", category=FutureWarning)

# ── Paths ──────────────────────────────────────────────────────
DIR         = os.path.dirname(os.path.abspath(__file__))
TRADE_LOG   = os.path.join(DIR, "trade_log.csv")
MODEL_PATH  = os.path.join(DIR, "ml_model.pkl")
SIGNALS_FILE = os.path.join(DIR, "signals.json")

# ── Constants ─────────────────────────────────────────────────
LOOKBACK_YEARS = 3        # years of OHLCV history to pull
MIN_BARS       = 60       # minimum daily bars required per ticker
P_WIN_THRESHOLD = 0.60    # above this → accept signal (shadow only for now)
EMBARGO_DAYS   = 5        # bars embargo between train/test splits

SETUP_ENCODE = {
    "TREND_PULLBACK":      0,
    "OVERSOLD_EXHAUSTION": 1,
    "RSI_DIVERGENCE":      2,
}
CONF_ENCODE = {"WATCH": 0, "BUY": 1}


# ══════════════════════════════════════════════════════════════
# 1. OHLCV fetch + sanitize
# ══════════════════════════════════════════════════════════════

def _fetch_ticker(ticker: str, start: str, end: str) -> pd.DataFrame | None:
    """
    Fetch adjusted daily OHLCV for one ticker.
    Returns None on failure or insufficient data.
    Sanitizes: drops zero/NaN volume bars, forward-fills sparse closes.
    """
    try:
        raw = yf.download(ticker, start=start, end=end, auto_adjust=True,
                          progress=False, threads=False)
    except Exception as e:
        print(f"  [FETCH] {ticker}: {e}")
        return None

    if raw is None or len(raw) < MIN_BARS:
        return None

    df = raw[["Open", "High", "Low", "Close", "Volume"]].copy()
    df.columns = ["open", "high", "low", "close", "volume"]
    df.index = pd.to_datetime(df.index)

    # Drop zero-volume bars (bad ticks, exchange halts)
    # Keep NaN volume as-is — may be a data gap, not a halt
    df = df[df["volume"].fillna(0) > 0]

    # Forward-fill sparse close (at most 2 consecutive)
    df["close"] = df["close"].ffill(limit=2)
    df = df.dropna(subset=["close"])

    if len(df) < MIN_BARS:
        return None
    return df


def fetch_all_ohlcv(tickers: list[str]) -> dict[str, pd.DataFrame]:
    """Batch-fetch with yfinance group download (≤4 per call per config.py)."""
    end   = datetime.today().strftime("%Y-%m-%d")
    start = (datetime.today() - timedelta(days=LOOKBACK_YEARS * 365 + 30)).strftime("%Y-%m-%d")

    print(f"[1/5] Fetching {len(tickers)} tickers ({start} → {end})...")
    result = {}
    batch_size = 4   # match fetcher.py convention
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i + batch_size]
        for t in batch:
            df = _fetch_ticker(t, start, end)
            if df is not None:
                result[t] = df
        print(f"  Fetched {min(i+batch_size, len(tickers))}/{len(tickers)} ...", end="\r")
    print(f"\n  OK — {len(result)}/{len(tickers)} tickers have usable data")
    return result


# ══════════════════════════════════════════════════════════════
# 2. Point-in-time feature engineering
# ══════════════════════════════════════════════════════════════

def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain  = delta.clip(lower=0).ewm(alpha=1/period, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(alpha=1/period, adjust=False).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift()).abs(),
        (df["low"]  - df["close"].shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False).mean()


def _ema(close: pd.Series, period: int) -> pd.Series:
    return close.ewm(span=period, adjust=False).mean()


def _adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Approximate ADX (trend strength)."""
    up   = df["high"].diff()
    down = -df["low"].diff()
    pdm  = up.where((up > down) & (up > 0), 0.0)
    ndm  = down.where((down > up) & (down > 0), 0.0)
    atr  = _atr(df, period)
    pdi  = 100 * pdm.ewm(alpha=1/period, adjust=False).mean() / atr.replace(0, np.nan)
    ndi  = 100 * ndm.ewm(alpha=1/period, adjust=False).mean() / atr.replace(0, np.nan)
    dx   = (100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan))
    return dx.ewm(alpha=1/period, adjust=False).mean()


def build_features_at_bar(df: pd.DataFrame, bar_date: date,
                           setup_type: str, conf_label: str) -> dict | None:
    """
    Compute features strictly using data available AT OR BEFORE bar_date.
    Returns None if insufficient history.
    """
    # Slice to point-in-time — only rows <= bar_date
    pit = df[df.index.date <= bar_date].copy()
    if len(pit) < 60:
        return None

    close  = pit["close"]
    rsi    = _rsi(close)
    atr    = _atr(pit)
    ema20  = _ema(close, 20)
    ema50  = _ema(close, 50)
    ema200 = _ema(close, 200)
    adx    = _adx(pit)

    ltp    = float(close.iloc[-1])
    rv     = float(rsi.iloc[-1])
    atr_v  = float(atr.iloc[-1])
    e20    = float(ema20.iloc[-1])
    e50    = float(ema50.iloc[-1])
    e200   = float(ema200.iloc[-1]) if len(close) >= 200 else ltp
    adx_v  = float(adx.iloc[-1])

    # Volume ratio (today vs 20-day avg)
    avg_vol    = float(pit["volume"].iloc[-20:].mean())
    today_vol  = float(pit["volume"].iloc[-1])
    rvol       = round(today_vol / avg_vol, 3) if avg_vol > 0 else 1.0

    # Normalize ATR as % of price so large-cap/mid-cap scale doesn't skew
    atr_pct = atr_v / ltp if ltp > 0 else 0.0

    # Price position relative to EMAs
    dist_ema20  = (ltp - e20)  / e20  if e20  > 0 else 0.0
    dist_ema50  = (ltp - e50)  / e50  if e50  > 0 else 0.0
    dist_ema200 = (ltp - e200) / e200 if e200 > 0 else 0.0

    # RSI momentum (1-week change)
    rsi_1w = float(rsi.iloc[-5]) if len(rsi) >= 5 else rv
    rsi_delta = rv - rsi_1w

    # Trend direction: 3-week return
    ret_3w = (ltp - float(close.iloc[-15])) / float(close.iloc[-15]) if len(close) >= 15 else 0.0

    # 10-day volatility (realized)
    ret_1d  = close.pct_change()
    vol_10d = float(ret_1d.iloc[-10:].std()) if len(ret_1d) >= 10 else 0.0

    return {
        # Technical features
        "rsi":          rv,
        "rsi_delta":    rsi_delta,
        "adx":          adx_v,
        "atr_pct":      atr_pct,
        "rvol":         rvol,
        "dist_ema20":   dist_ema20,
        "dist_ema50":   dist_ema50,
        "dist_ema200":  dist_ema200,
        "ret_3w":       ret_3w,
        "vol_10d":      vol_10d,
        # Setup metadata (encoded)
        "setup_type":   SETUP_ENCODE.get(setup_type, -1),
        "conf_label":   CONF_ENCODE.get(conf_label, 0),
    }


FEATURE_COLS = [
    "rsi", "rsi_delta", "adx", "atr_pct", "rvol",
    "dist_ema20", "dist_ema50", "dist_ema200",
    "ret_3w", "vol_10d", "setup_type", "conf_label",
]


# ══════════════════════════════════════════════════════════════
# 3. Join trades → feature matrix
# ══════════════════════════════════════════════════════════════

def build_training_set(trade_log: pd.DataFrame,
                       ohlcv: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """
    Map each trade to its entry-bar features and WIN/LOSS label.
    Skips trades where OHLCV is unavailable or history is too short.
    """
    print("[3/5] Building feature matrix from trade_log + OHLCV...")
    rows = []
    skipped = 0

    for _, row in trade_log.iterrows():
        ticker     = row["ticker"]
        entry_date = pd.to_datetime(row["date"]).date()
        setup_type = row["setup_type"]
        conf_label = row.get("conf_label", "BUY")
        label      = 1 if row["result"] == "WIN" else 0

        if ticker not in ohlcv:
            skipped += 1
            continue

        feats = build_features_at_bar(
            ohlcv[ticker], entry_date, setup_type, conf_label
        )
        if feats is None:
            skipped += 1
            continue

        feats["label"]      = label
        feats["date"]       = row["date"]
        feats["ticker"]     = ticker
        feats["setup_type_raw"] = setup_type
        feats["trade_id"]   = row.get("id", "")
        rows.append(feats)

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    print(f"  {len(df)} trades mapped ({skipped} skipped — no OHLCV or short history)")
    print(f"  WIN: {df['label'].sum()}  LOSS: {(df['label']==0).sum()}")
    return df


# ══════════════════════════════════════════════════════════════
# 4. Walk-forward / purged validation
# ══════════════════════════════════════════════════════════════

def walk_forward_validate(df: pd.DataFrame,
                          n_splits: int = 3,
                          embargo_days: int = EMBARGO_DAYS) -> dict:
    """
    Time-ordered walk-forward validation.
    Train on first k folds, test on k+1. Embargo = gap between train/test.
    Never trains on future data.
    """
    print(f"[4/5] Walk-forward validation ({n_splits} splits, {embargo_days}d embargo)...")
    df = df.sort_values("date").reset_index(drop=True)
    n  = len(df)
    fold_size = n // (n_splits + 1)

    all_preds  = []
    all_labels = []
    all_scores = []

    for fold in range(n_splits):
        train_end_idx  = fold_size * (fold + 1)
        test_start_idx = train_end_idx + embargo_days  # embargo gap
        test_end_idx   = min(train_end_idx + fold_size + embargo_days, n)

        if test_start_idx >= n:
            break

        train_df = df.iloc[:train_end_idx]
        test_df  = df.iloc[test_start_idx:test_end_idx]

        X_train = train_df[FEATURE_COLS].values
        y_train = train_df["label"].values
        X_test  = test_df[FEATURE_COLS].values
        y_test  = test_df["label"].values

        # Sanity check: at least 2 classes in train
        if len(np.unique(y_train)) < 2:
            print(f"  Fold {fold+1}: only one class in train — skipping")
            continue

        pipe = Pipeline([
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(C=0.1, max_iter=1000, random_state=42)),
        ])
        pipe.fit(X_train, y_train)
        proba  = pipe.predict_proba(X_test)[:, 1]
        preds  = (proba >= P_WIN_THRESHOLD).astype(int)

        all_preds.extend(preds.tolist())
        all_labels.extend(y_test.tolist())
        all_scores.extend(proba.tolist())

        train_period = f"{train_df['date'].min().date()} → {train_df['date'].max().date()}"
        test_period  = f"{test_df['date'].min().date()} → {test_df['date'].max().date()}"
        print(f"  Fold {fold+1}: train [{train_period}] | test [{test_period}] | "
              f"n_train={len(train_df)} n_test={len(test_df)}")

    if not all_labels:
        return {"error": "No folds completed"}

    all_labels = np.array(all_labels)
    all_preds  = np.array(all_preds)
    all_scores = np.array(all_scores)

    # Expected value across probability cutoffs
    print("\n  Precision/Recall at different p_win thresholds:")
    precisions, recalls, thresholds = precision_recall_curve(all_labels, all_scores)
    for t in [0.50, 0.55, 0.60, 0.65, 0.70]:
        idx = np.searchsorted(thresholds, t)
        p   = precisions[idx] if idx < len(precisions) else 0
        r   = recalls[idx]    if idx < len(recalls)    else 0
        n_signals = int((all_scores >= t).sum())
        print(f"    p_win>{t:.2f}: precision={p:.2f}  recall={r:.2f}  signals={n_signals}")

    print("\n  Classification report (threshold=0.60):")
    print(classification_report(all_labels, all_preds,
                                target_names=["LOSS", "WIN"], zero_division=0))

    return {
        "n_test_trades": len(all_labels),
        "precision_at_60": float(np.mean(all_preds[all_labels == 1])) if all_preds.sum() > 0 else 0,
        "recall_at_60":    float(np.mean(all_labels[all_preds == 1])) if all_preds.sum() > 0 else 0,
        "win_rate_filtered": float(all_labels[all_preds == 1].mean()) if all_preds.sum() > 0 else 0,
        "signals_blocked":   int((all_preds == 0).sum()),
        "signals_passed":    int((all_preds == 1).sum()),
    }


# ══════════════════════════════════════════════════════════════
# 5. Train final model on all data + save
# ══════════════════════════════════════════════════════════════

def train_final_model(df: pd.DataFrame) -> Pipeline:
    """Train on full dataset. Save model + scaler as ml_model.pkl."""
    print("[5/5] Training final model on all data...")
    X = df[FEATURE_COLS].values
    y = df["label"].values

    pipe = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(C=0.1, max_iter=1000, random_state=42)),
    ])
    pipe.fit(X, y)
    joblib.dump(pipe, MODEL_PATH)
    print(f"  Model saved → {MODEL_PATH}")
    print(f"  Coefficients:")
    coefs = dict(zip(FEATURE_COLS, pipe.named_steps["clf"].coef_[0]))
    for feat, coef in sorted(coefs.items(), key=lambda x: abs(x[1]), reverse=True):
        print(f"    {feat:20s}: {coef:+.3f}")
    return pipe


# ══════════════════════════════════════════════════════════════
# Predict: score a single signal (point-in-time safe)
# ══════════════════════════════════════════════════════════════

def predict_one(ticker: str, setup_type: str,
                conf_label: str = "BUY",
                bar_date: date | None = None) -> float:
    """
    Score one signal. Fetches OHLCV up to bar_date (default: today).
    Returns p_win ∈ [0, 1]. Returns 0.5 (neutral) on any failure.
    """
    if not os.path.exists(MODEL_PATH):
        print("  [WARN] No model found — run with --train first")
        return 0.5

    pipe     = joblib.load(MODEL_PATH)
    bar_date = bar_date or date.today()
    end      = (datetime.combine(bar_date, datetime.min.time()) + timedelta(days=1)).strftime("%Y-%m-%d")
    start    = (datetime.combine(bar_date, datetime.min.time()) - timedelta(days=LOOKBACK_YEARS * 365 + 30)).strftime("%Y-%m-%d")

    df = _fetch_ticker(ticker, start, end)
    if df is None:
        print(f"  [WARN] Could not fetch {ticker} — defaulting p_win=0.5")
        return 0.5

    feats = build_features_at_bar(df, bar_date, setup_type, conf_label)
    if feats is None:
        print(f"  [WARN] Insufficient history for {ticker} — defaulting p_win=0.5")
        return 0.5

    X = np.array([[feats[f] for f in FEATURE_COLS]])
    p_win = float(pipe.predict_proba(X)[0, 1])
    return round(p_win, 3)


# ══════════════════════════════════════════════════════════════
# Shadow mode: score today's signals.json
# ══════════════════════════════════════════════════════════════

def shadow_score(signals_path: str = SIGNALS_FILE) -> None:
    """
    Score every pick in signals.json and log p_win.
    Does NOT block any signal — shadow mode only.
    Prints a table; write p_win into signals.json for alert.py to pick up.
    """
    if not os.path.exists(signals_path):
        print(f"  [WARN] {signals_path} not found")
        return

    with open(signals_path) as f:
        signals = json.load(f)

    picks = signals.get("picks", [])
    if not picks:
        print("  No picks in signals.json")
        return

    print(f"\n{'─'*52}")
    print(f"  SHADOW SCORES  (threshold={P_WIN_THRESHOLD})")
    print(f"{'─'*52}")
    print(f"  {'Ticker':20s} {'Setup':22s} {'p_win':>6s}  {'Action':8s}")
    print(f"  {'─'*20} {'─'*22} {'─'*6}  {'─'*8}")

    for p in picks:
        ticker     = p.get("ticker", "")
        setup_type = p.get("setup_type", "TREND_PULLBACK")
        conf_label = p.get("conf_label", "BUY")

        p_win = predict_one(ticker, setup_type, conf_label)
        p["p_win"] = p_win  # attach to pick for alert.py

        action = "PASS ✅" if p_win >= P_WIN_THRESHOLD else "BLOCK ⛔"
        print(f"  {ticker:20s} {setup_type:22s} {p_win:>6.3f}  {action}")

    # Write p_win scores back to signals.json
    with open(signals_path, "w") as f:
        json.dump(signals, f, indent=2)
    print(f"\n  p_win scores written to {signals_path}")
    print(f"  (Shadow mode — no signals blocked yet)")


# ══════════════════════════════════════════════════════════════
# CLI entry point
# ══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="ML signal filter for V6 N200c")
    parser.add_argument("--train",   action="store_true", help="Train model from trade_log.csv")
    parser.add_argument("--predict", nargs="+", metavar=("TICKER", "SETUP"),
                        help="Score one signal: TICKER SETUP_TYPE [conf_label]")
    parser.add_argument("--shadow",  action="store_true", help="Score today's signals.json")
    args = parser.parse_args()

    if args.train:
        # Load trade log
        trade_log = pd.read_csv(TRADE_LOG)
        trade_log = trade_log[trade_log["result"].isin(["WIN", "LOSS"])].copy()
        print(f"  Trade log: {len(trade_log)} valid trades")

        # Fetch OHLCV
        tickers = trade_log["ticker"].unique().tolist()
        ohlcv   = fetch_all_ohlcv(tickers)

        # Build feature matrix
        df = build_training_set(trade_log, ohlcv)
        if len(df) < 20:
            print("  ERROR: Too few trades to train. Need ≥20 with OHLCV data.")
            sys.exit(1)

        # Walk-forward validation
        val_results = walk_forward_validate(df)
        print("\n  Validation summary:", val_results)

        # Final model
        train_final_model(df)
        print("\n✅ Done. Model ready for shadow mode (--shadow).")
        print("   Next step: add p_win logging to alert.py, monitor for 30 trades,")
        print(f"  then enable hard-blocking at p_win < {P_WIN_THRESHOLD}.")

    elif args.predict:
        ticker     = args.predict[0]
        setup_type = args.predict[1] if len(args.predict) > 1 else "TREND_PULLBACK"
        conf_label = args.predict[2] if len(args.predict) > 2 else "BUY"
        p_win = predict_one(ticker, setup_type, conf_label)
        action = "PASS ✅" if p_win >= P_WIN_THRESHOLD else "BLOCK ⛔"
        print(f"  {ticker} / {setup_type} / {conf_label}: p_win={p_win}  → {action}")

    elif args.shadow:
        shadow_score()

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
