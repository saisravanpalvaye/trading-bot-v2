"""
backtest.py — 10-year backtest of the live signal engine.
Mirrors analyzer.py exactly so backtest results reflect live behaviour.
Run: python backtest.py
Time: ~30-40 minutes
Output: backtest_YYYYMMDD_HHMM.csv + console summary
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

from config import (
    WATCHLIST, CAPITAL, ATR_SL_MULT, ATR_TGT_MULT, MIN_RR,
    ADX_TREND_MIN, TREND_RSI_MIN, TREND_RSI_MAX, RSI_PULLBACK_MIN,
    OVERSOLD_RSI_MAX, DIV_RSI_MAX, SETUP_WIN_RATE,
    SIZE_STRONG_BUY, SIZE_BUY, SIZE_WATCH,
    STRONG_BUY_MIN_SCORE, BUY_MIN_SCORE,
)

START = "2015-01-01"
END   = date.today().isoformat()


# ── Indicator helpers (mirror analyzer.py exactly) ─────────

def _rsi(close, p=14):
    d  = close.diff()
    ag = d.clip(lower=0).ewm(com=p-1, adjust=False, min_periods=p).mean()
    al = (-d.clip(upper=0)).ewm(com=p-1, adjust=False, min_periods=p).mean()
    return 100 - 100 / (1 + ag / al.replace(0, np.nan))

def _ema(close, p):
    return close.ewm(span=p, adjust=False).mean()

def _atr(df, p=14):
    hi = df["high"]; lo = df["low"]; cl = df["close"]
    tr = pd.concat([(hi-lo), (hi-cl.shift()).abs(), (lo-cl.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(span=p, adjust=False).mean()

def _adx(df, p=14):
    hi = df["high"]; lo = df["low"]; cl = df["close"]
    tr   = pd.concat([(hi-lo), (hi-cl.shift()).abs(), (lo-cl.shift()).abs()], axis=1).max(axis=1)
    atr_ = tr.ewm(span=p, adjust=False).mean()
    up   = (hi - hi.shift()).clip(lower=0)
    dn   = (lo.shift() - lo).clip(lower=0)
    up   = up.where(up > dn, 0)
    dn   = dn.where(dn > up, 0)
    pdi  = up.ewm(span=p, adjust=False).mean() / atr_ * 100
    ndi  = dn.ewm(span=p, adjust=False).mean() / atr_ * 100
    dx   = (abs(pdi-ndi) / (pdi+ndi).replace(0, np.nan) * 100).fillna(0)
    return dx.ewm(span=p, adjust=False).mean()

def _to_weekly(daily_df):
    df = daily_df.copy()
    df.index = pd.to_datetime(df.index)
    return df.resample("W").agg({
        "open":"first","high":"max","low":"min","close":"last","volume":"sum"
    }).dropna()


# ── Setup detection (mirrors analyzer.py) ─────────────────

def _detect_weekly_setup(wdf_full):
    """Returns (setup_type, weekly_score) using completed weeks only."""
    wdf = wdf_full.iloc[:-1] if len(wdf_full) > 14 else wdf_full
    if len(wdf) < 14:
        return None, 0

    rsi_s  = _rsi(wdf["close"])
    rv     = float(rsi_s.iloc[-1])
    ema20  = _ema(wdf["close"], 20)

    # TREND_PULLBACK
    if TREND_RSI_MIN <= rv <= TREND_RSI_MAX:
        if float(wdf["close"].iloc[-1]) > float(ema20.iloc[-1]):
            rsi_max = float(rsi_s.iloc[-5:-1].max()) if len(rsi_s) >= 5 else rv
            if rv < rsi_max - RSI_PULLBACK_MIN:
                try:
                    adxv = float(_adx(wdf).iloc[-1])
                    if adxv >= ADX_TREND_MIN:
                        return "TREND_PULLBACK", (3 if adxv >= 25 else 2)
                except Exception:
                    return "TREND_PULLBACK", 2

    # OVERSOLD_EXHAUSTION
    if rv <= OVERSOLD_RSI_MAX:
        rp3 = float(rsi_s.iloc[-3]) if len(rsi_s) >= 3 else rv + 5
        if rv <= rp3 + 8:
            low_52   = float(wdf["close"].iloc[-min(52, len(wdf)):].min())
            near_low = float(wdf["close"].iloc[-1]) < low_52 * 1.20
            avg_vol  = float(wdf["volume"].iloc[-15:].mean())
            vol_dry  = float(wdf["volume"].iloc[-1]) < avg_vol * 0.95
            score    = sum([rv < 42, vol_dry, near_low]) + 1
            return "OVERSOLD_EXHAUSTION", min(int(score), 4)

    # RSI_DIVERGENCE
    if rv <= DIV_RSI_MAX:
        low_10w  = float(wdf["close"].iloc[-10:].min())
        near_low = float(wdf["close"].iloc[-1]) <= low_10w * 1.08
        if near_low and len(rsi_s) >= 5:
            rsi_4w = float(rsi_s.iloc[-5:-3].min())
            if rv - rsi_4w > 1:
                return "RSI_DIVERGENCE", 3

    return None, 0


def _daily_confirm(ddf, setup_type):
    """Daily confirmation — mirrors analyzer.py."""
    if len(ddf) < 20:
        return False
    rsi_d = _rsi(ddf["close"])
    rv    = float(rsi_d.iloc[-1])
    rp    = float(rsi_d.iloc[-2])

    if setup_type == "TREND_PULLBACK":
        e20 = _ema(ddf["close"], 20)
        e50 = _ema(ddf["close"], 50)
        ltp = float(ddf["close"].iloc[-1])
        if not (TREND_RSI_MIN <= rv <= 68):
            return False
        if not (ltp > float(e20.iloc[-1]) > float(e50.iloc[-1])):
            return False
        return any(
            float(ddf["low"].iloc[i]) <= float(e20.iloc[i]) * 1.005
            for i in [-3, -2, -1]
        )
    elif setup_type == "OVERSOLD_EXHAUSTION":
        if rv > 52 or rv <= rp:
            return False
        return float(ddf["close"].iloc[-1]) >= float(ddf["close"].iloc[-3:].min()) * 0.99
    elif setup_type == "RSI_DIVERGENCE":
        if rv > 50:
            return False
        rsi_low = float(rsi_d.iloc[-6:-3].min()) if len(rsi_d) >= 6 else rv
        return rv > rsi_low + 2

    return False


def _quality_gates(ddf):
    """Quality gates — mirrors analyzer.py."""
    cl  = ddf["close"]
    ltp = float(cl.iloc[-1])
    av  = float(_atr(ddf).iloc[-1])
    if np.isnan(av) or av <= 0:
        return False, 0, 0, 0, 0
    rv = float(_rsi(cl).iloc[-1])
    if rv > 68:
        return False, 0, 0, 0, 0
    if len(cl) >= 200:
        if ltp < float(_ema(cl, 200).iloc[-1]) * 0.95:
            return False, 0, 0, 0, 0
    sl  = ltp - ATR_SL_MULT * av
    tgt = ltp + ATR_TGT_MULT * av
    rr  = round((tgt - ltp) / (ltp - sl), 2) if ltp > sl else 0
    if rr < MIN_RR:
        return False, 0, 0, 0, 0
    return True, sl, tgt, rr, av


def _conf_score(ddf, wscore, rr):
    """Confidence score — mirrors analyzer.py."""
    rsi_d = _rsi(ddf["close"])
    e20   = _ema(ddf["close"], 20)
    e50   = _ema(ddf["close"], 50)
    adxv  = float(_adx(ddf).iloc[-1])
    rv    = float(rsi_d.iloc[-1])
    ltp   = float(ddf["close"].iloc[-1])

    factors = [
        wscore >= 3,
        TREND_RSI_MIN <= rv <= 65,
        ltp > float(e20.iloc[-1]) > float(e50.iloc[-1]),
        adxv >= 25,
        rr >= 1.8,
        True,  # regime assumed NEUTRAL in backtest
    ]
    score = sum(factors)
    if score >= STRONG_BUY_MIN_SCORE: return score, "STRONG BUY"
    if score >= BUY_MIN_SCORE:        return score, "BUY"
    return score, "WATCH"


# ── Trade simulation ───────────────────────────────────────

def _simulate(full_daily, entry_idx, sl, target, hold_days):
    """Simulate trade outcome over next hold_days candles."""
    future = full_daily.iloc[entry_idx+1: entry_idx+1+hold_days]
    if len(future) == 0:
        return "DAY_CAP", float(full_daily["close"].iloc[entry_idx])
    for _, row in future.iterrows():
        if float(row["low"])  <= sl:     return "SL",      sl
        if float(row["high"]) >= target: return "TARGET",  target
    return "DAY_CAP", float(future["close"].iloc[-1])


# ── Main backtest ──────────────────────────────────────────

def run_backtest():
    print("\n" + "="*60)
    print("  BACKTEST — 10 Years")
    print(f"  Period  : {START} → {END}")
    print(f"  Stocks  : {len(WATCHLIST)}")
    print(f"  Capital : Rs {CAPITAL:,.0f}")
    print("="*60)

    # ── Download ──────────────────────────────────────────
    print("\n[1/3] Downloading 10yr data...")
    all_daily = {}
    for i, ticker in enumerate(WATCHLIST, 1):
        try:
            raw = yf.download(ticker, start=START, end=END,
                              interval="1d", progress=False, auto_adjust=True)
            if raw is None or len(raw) < 60:
                continue
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
            if len(df) >= 60:
                all_daily[ticker] = df
            if i % 10 == 0:
                print(f"  Downloaded {i}/{len(WATCHLIST)}...")
            time.sleep(0.25)
        except Exception as e:
            print(f"  {ticker}: {e}")

    print(f"  Loaded {len(all_daily)} stocks")

    # ── Run ───────────────────────────────────────────────
    print("\n[2/3] Running backtest...")
    trades = []

    for ticker, ddf in all_daily.items():
        dates     = ddf.index.tolist()
        wdf_full  = _to_weekly(ddf)
        in_trade  = False
        trade_end = 0

        for di in range(250, len(dates)):
            if in_trade and di < trade_end:
                continue
            in_trade = False

            dt      = dates[di]
            ddf_to  = ddf.iloc[:di+1]
            wdf_to  = wdf_full[wdf_full.index <= dt]
            if len(wdf_to) < 14:
                continue

            # Weekly setup
            setup, wscore = _detect_weekly_setup(wdf_to)
            if setup is None:
                continue

            # Daily confirm
            if not _daily_confirm(ddf_to, setup):
                continue

            # Quality gates
            ok, sl, tgt, rr, av = _quality_gates(ddf_to)
            if not ok:
                continue

            entry = float(ddf_to["close"].iloc[-1])

            # Confidence
            score, conf_label = _conf_score(ddf_to, wscore, rr)

            # Sizing
            if conf_label == "STRONG BUY":
                size_pct = SIZE_STRONG_BUY
            elif conf_label == "BUY":
                size_pct = SIZE_BUY
            else:
                size_pct = SIZE_WATCH

            trade_cap = CAPITAL * size_pct
            qty       = max(1, int(trade_cap / entry))

            # EV
            p_win  = SETUP_WIN_RATE.get(setup, 0.52)
            ev_pct = round((p_win * (tgt-entry)/entry - (1-p_win) * (entry-sl)/entry) * 100, 2)

            hold = 6

            # Simulate
            exit_reason, exit_price = _simulate(ddf, di, sl, tgt, hold)
            pnl    = round((exit_price - entry) * qty, 2)
            result = "WIN" if exit_price > entry else "LOSS"

            trades.append({
                "ticker":       ticker,
                "entry_date":   dt.strftime("%Y-%m-%d"),
                "exit_date":    dates[min(di+hold, len(dates)-1)].strftime("%Y-%m-%d"),
                "setup_type":   setup,
                "conf_label":   conf_label,
                "conf_score":   score,
                "entry":        round(entry, 2),
                "exit":         round(exit_price, 2),
                "sl":           round(sl, 2),
                "target":       round(tgt, 2),
                "rr":           rr,
                "qty":          qty,
                "capital":      round(qty * entry, 0),
                "pnl":          pnl,
                "exit_reason":  exit_reason,
                "ev_pct":       ev_pct,
                "result":       result,
                "days_held":    hold,
                "weekly_score": wscore,
            })

            in_trade  = True
            trade_end = di + hold

        if len(trades) % 200 == 0 and len(trades) > 0:
            print(f"  Trades so far: {len(trades)}")

    print(f"  Total trades: {len(trades)}")

    if not trades:
        print("  No trades found.")
        return

    # ── Save CSV ──────────────────────────────────────────
    ts      = datetime.now().strftime("%Y%m%d_%H%M")
    outfile = f"backtest_{ts}.csv"
    df_out  = pd.DataFrame(trades)
    df_out.to_csv(outfile, index=False)
    print(f"\n  Saved: {outfile}")

    # ── Results ───────────────────────────────────────────
    _print_results(df_out)


def _print_results(df):
    print("\n[3/3] Results\n")
    CAPITAL_V = CAPITAL

    w   = df[df["result"] == "WIN"]
    l   = df[df["result"] == "LOSS"]
    wr  = len(w) / len(df) * 100
    tot = df["pnl"].sum()
    pf  = abs(w["pnl"].sum() / l["pnl"].sum()) if len(l) > 0 else 999
    ret = df["pnl"] / CAPITAL_V
    sh  = round(float(ret.mean() / ret.std() * (252 ** 0.5)), 2) if ret.std() > 0 else 0

    equity = CAPITAL_V + df["pnl"].cumsum()
    pk = CAPITAL_V; mdd = 0
    for v in equity:
        pk  = max(pk, v)
        mdd = max(mdd, (pk - v) / pk)

    yrs = (pd.to_datetime(df["exit_date"].max()) -
           pd.to_datetime(df["entry_date"].min())).days / 365

    print("="*60)
    print("  BACKTEST RESULTS — 10 YEARS")
    print("="*60)
    print(f"  Trades       : {len(df)}  ({len(df)/yrs:.0f}/year)")
    print(f"  Win rate     : {wr:.1f}%  ({len(w)}W / {len(l)}L)")
    print(f"  Total P&L    : Rs {tot:+,.0f}  ({tot/CAPITAL_V*100:+.1f}%)")
    print(f"  Annual return: {tot/CAPITAL_V/yrs*100:+.1f}% / year")
    print(f"  Monthly avg  : Rs {tot/(yrs*12):+,.0f} / month")
    print(f"  Avg win      : Rs {w['pnl'].mean():+,.0f}")
    print(f"  Avg loss     : Rs {l['pnl'].mean():+,.0f}")
    print(f"  Profit factor: {pf:.2f}x")
    print(f"  Sharpe ratio : {sh}")
    print(f"  Max drawdown : {mdd*100:.1f}%")

    # Exit breakdown
    print(f"\n  Exit breakdown")
    for r, g in df.groupby("exit_reason"):
        ww = len(g[g["result"] == "WIN"])
        print(f"    {r:10s}: {len(g):4d}  "
              f"wr={ww/len(g)*100:.0f}%  "
              f"avg=Rs {g['pnl'].mean():+,.0f}  "
              f"total=Rs {g['pnl'].sum():+,.0f}")

    # By confidence label — KEY OUTPUT
    print(f"\n  By confidence label")
    for lbl in ["STRONG BUY", "BUY", "WATCH"]:
        g = df[df["conf_label"] == lbl]
        if len(g) == 0:
            continue
        ww  = len(g[g["result"] == "WIN"])
        ll  = g[g["result"] == "LOSS"]
        pf2 = abs(g[g["result"]=="WIN"]["pnl"].sum() / ll["pnl"].sum()) if len(ll) > 0 else 999
        print(f"    {lbl:12s}: {len(g):4d} trades  "
              f"wr={ww/len(g)*100:.0f}%  "
              f"avg=Rs {g['pnl'].mean():+,.0f}  "
              f"pf={pf2:.2f}x  "
              f"total=Rs {g['pnl'].sum():+,.0f}")

    # By setup
    print(f"\n  By setup type")
    for s, g in df.groupby("setup_type"):
        ww = len(g[g["result"] == "WIN"])
        print(f"    {s:25s}: {len(g):4d}  "
              f"wr={ww/len(g)*100:.0f}%  "
              f"avg=Rs {g['pnl'].mean():+,.0f}")

    # Yearly P&L
    print(f"\n  Yearly P&L")
    df["year"] = pd.to_datetime(df["exit_date"]).dt.year
    for yr, g in df.groupby("year"):
        pct = g["pnl"].sum() / CAPITAL_V * 100
        wr_ = len(g[g["result"] == "WIN"]) / len(g) * 100
        bar = ("▲" if g["pnl"].sum() > 0 else "▼")
        print(f"    {yr}  {len(g):4d} trades  "
              f"{bar} Rs {g['pnl'].sum():+9,.0f}  "
              f"({pct:+.1f}%)  wr={wr_:.0f}%")

    # Top 10 tickers
    print(f"\n  Top 10 tickers (min 8 trades)")
    ticker_stats = []
    for t, g in df.groupby("ticker"):
        if len(g) < 8:
            continue
        wr_ = len(g[g["result"] == "WIN"]) / len(g)
        ticker_stats.append((t.replace(".NS", ""), len(g), wr_, g["pnl"].sum()))
    ticker_stats.sort(key=lambda x: -x[2])
    for t, n, wr_, tot_ in ticker_stats[:10]:
        bar = "█" * int(wr_ * 20)
        print(f"    {t:15s}: {n:3d} trades  wr={wr_*100:.0f}%  "
              f"Rs {tot_:+,.0f}  {bar}")

    print("\n" + "="*60)


if __name__ == "__main__":
    t0 = time.time()
    run_backtest()
    print(f"\n  Total time: {round(time.time()-t0)}s")
