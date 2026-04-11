"""
analyzer.py — Signal detection engine.
Two-stage: weekly setup → daily confirmation → confidence gate.
Returns structured picks. No Telegram. No file writes. Pure logic.
"""
import pandas as pd
import numpy as np
from config import (
    CAPITAL, ATR_SL_MULT, ATR_TGT_MULT, ATR_PERIOD,
    MAX_HOLD_DAYS, MIN_RR, MIN_EV_PCT,
    TREND_RSI_MIN, TREND_RSI_MAX, ADX_TREND_MIN, RSI_PULLBACK_MIN,
    OVERSOLD_RSI_MAX, DIV_RSI_MAX,
    VIX_AVOID, VIX_REDUCE,
    SETUP_WIN_RATE, SECTOR_MAP,
    SIZE_STRONG_BUY, SIZE_BUY, SIZE_WATCH,
    STRONG_BUY_MIN_SCORE, BUY_MIN_SCORE,
)


# ── Indicator helpers ──────────────────────────────────────

def _rsi(close, period=14):
    delta = close.diff()
    gain  = delta.clip(lower=0).ewm(com=period-1, adjust=False, min_periods=period).mean()
    loss  = (-delta.clip(upper=0)).ewm(com=period-1, adjust=False, min_periods=period).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)

def _ema(close, period):
    return close.ewm(span=period, adjust=False).mean()

def _atr(df, period=14):
    hi = df["high"]; lo = df["low"]; cl = df["close"]
    tr = pd.concat([
        (hi - lo),
        (hi - cl.shift()).abs(),
        (lo - cl.shift()).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()

def _adx(df, period=14):
    hi = df["high"]; lo = df["low"]; cl = df["close"]
    tr   = pd.concat([(hi-lo), (hi-cl.shift()).abs(), (lo-cl.shift()).abs()], axis=1).max(axis=1)
    atr_ = tr.ewm(span=period, adjust=False).mean()
    up   = (hi - hi.shift()).clip(lower=0)
    dn   = (lo.shift() - lo).clip(lower=0)
    up   = up.where(up > dn, 0)
    dn   = dn.where(dn > up, 0)
    pdi  = up.ewm(span=period, adjust=False).mean() / atr_ * 100
    ndi  = dn.ewm(span=period, adjust=False).mean() / atr_ * 100
    dx   = (abs(pdi - ndi) / (pdi + ndi).replace(0, np.nan) * 100).fillna(0)
    return dx.ewm(span=period, adjust=False).mean()

def _to_weekly(daily_df):
    df = daily_df.copy()
    df.index = pd.to_datetime(df.index)
    return df.resample("W").agg({
        "open":  "first", "high": "max",
        "low":   "min",   "close": "last",
        "volume":"sum"
    }).dropna()

def _regime(nifty_rsi, nifty_adx, vix_val, vix_action):
    """Determine market regime from Nifty RSI, ADX and VIX."""
    if vix_action == "avoid":
        return "HIGH_VIX",  "Danger zone — stay in cash"
    if vix_action == "reduce":
        return "HIGH_VIX",  "Elevated VIX — sizes halved"
    if nifty_rsi is None:
        return "NEUTRAL",   "RSI unavailable — trading cautiously"
    if nifty_rsi > 55:
        return "BULLISH",   "Uptrend — full position sizes"
    if nifty_rsi < 35:
        return "OVERSOLD",  "Bounce zone — selective buys"
    if nifty_rsi < 43 and nifty_adx and nifty_adx > 22:
        return "BEARISH",   "Downtrend — defensive only"
    return "NEUTRAL",       "Mixed signals — selective trades"


# ── Stage 1: Weekly setup detectors ───────────────────────
# All receive COMPLETED weekly candles (current partial week skipped)

def _weekly_trend_pullback(wdf):
    """
    Healthy uptrend pulling back to EMA20.
    ADX > 18 structural filter blocks whippy stocks dynamically.
    """
    if len(wdf) < 20:
        return False, {}
    rsi   = _rsi(wdf["close"])
    ema20 = _ema(wdf["close"], 20)
    adx   = _adx(wdf)
    rv    = float(rsi.iloc[-1])
    adxv  = float(adx.iloc[-1])

    if not (TREND_RSI_MIN <= rv <= TREND_RSI_MAX):
        return False, {}
    if float(wdf["close"].iloc[-1]) < float(ema20.iloc[-1]):
        return False, {}
    rsi_max = float(rsi.iloc[-5:-1].max()) if len(rsi) >= 5 else rv
    if rv >= rsi_max - RSI_PULLBACK_MIN:
        return False, {}
    if adxv < ADX_TREND_MIN:
        return False, {}

    return True, {
        "setup":        "TREND_PULLBACK",
        "weekly_rsi":   round(rv, 1),
        "weekly_adx":   round(adxv, 1),
        "rsi_pullback": round(rsi_max - rv, 1),
        "weekly_score": 3 if adxv >= 25 else 2,
    }

def _weekly_oversold(wdf):
    """RSI below 50, selling slowing, near lows."""
    if len(wdf) < 10:
        return False, {}
    rsi = _rsi(wdf["close"])
    rv  = float(rsi.iloc[-1])
    if rv > OVERSOLD_RSI_MAX:
        return False, {}
    rp3 = float(rsi.iloc[-3]) if len(rsi) >= 3 else rv + 5
    if rv > rp3 + 8:
        return False, {}
    low_52   = float(wdf["close"].iloc[-min(52, len(wdf)):].min())
    near_low = float(wdf["close"].iloc[-1]) < low_52 * 1.20
    avg_vol  = float(wdf["volume"].iloc[-15:].mean())
    vol_dry  = float(wdf["volume"].iloc[-1]) < avg_vol * 0.95
    score    = sum([rv < 42, vol_dry, near_low]) + 1
    return True, {
        "setup":        "OVERSOLD_EXHAUSTION",
        "weekly_rsi":   round(rv, 1),
        "vol_dry":      bool(vol_dry),
        "near_52w_low": bool(near_low),
        "weekly_score": min(int(score), 4),
    }

def _weekly_rsi_divergence(wdf):
    """Price near 10-week low but RSI not at new low."""
    if len(wdf) < 12:
        return False, {}
    rsi     = _rsi(wdf["close"])
    rsi_now = float(rsi.iloc[-1])
    if rsi_now > DIV_RSI_MAX:
        return False, {}
    low_10w  = float(wdf["close"].iloc[-10:].min())
    near_low = float(wdf["close"].iloc[-1]) <= low_10w * 1.08
    if not near_low:
        return False, {}
    rsi_4w = float(rsi.iloc[-5:-3].min()) if len(rsi) >= 5 else rsi_now - 3
    if rsi_now - rsi_4w < 1:
        return False, {}
    return True, {
        "setup":          "RSI_DIVERGENCE",
        "weekly_rsi":     round(rsi_now, 1),
        "rsi_divergence": round(rsi_now - rsi_4w, 1),
        "weekly_score":   3,
    }


# ── Stage 2: Daily confirmation ────────────────────────────

def _daily_trend_confirm(df, _weekly):
    if len(df) < 20:
        return False, ""
    rsi   = _rsi(df["close"])
    ema20 = _ema(df["close"], 20)
    ema50 = _ema(df["close"], 50)
    rv    = float(rsi.iloc[-1])
    ltp   = float(df["close"].iloc[-1])
    if not (TREND_RSI_MIN <= rv <= 68):
        return False, ""
    if not (ltp > float(ema20.iloc[-1]) > float(ema50.iloc[-1])):
        return False, ""
    touched = any(
        float(df["low"].iloc[i]) <= float(ema20.iloc[i]) * 1.005
        for i in [-3, -2, -1]
    )
    if not touched:
        return False, ""
    return True, f"RSI {rv:.0f} pulling back to EMA20 · ADX structural"

def _daily_oversold_confirm(df, _weekly):
    if len(df) < 20:
        return False, ""
    rsi = _rsi(df["close"])
    rv  = float(rsi.iloc[-1])
    rp  = float(rsi.iloc[-2])
    if rv > 52 or rv <= rp:
        return False, ""
    ltp = float(df["close"].iloc[-1])
    if ltp < float(df["close"].iloc[-3:].min()) * 0.99:
        return False, ""
    return True, f"RSI {rv:.0f} turning up from oversold · volume drying"

def _daily_divergence_confirm(df, _weekly):
    if len(df) < 20:
        return False, ""
    rsi = _rsi(df["close"])
    rv  = float(rsi.iloc[-1])
    if rv > 50:
        return False, ""
    rsi_low = float(rsi.iloc[-6:-3].min()) if len(rsi) >= 6 else rv
    if rv <= rsi_low + 2:
        return False, ""
    return True, f"RSI divergence — price at low, RSI {rv:.0f} above recent low"

DAILY_CONFIRM = {
    "TREND_PULLBACK":      _daily_trend_confirm,
    "OVERSOLD_EXHAUSTION": _daily_oversold_confirm,
    "RSI_DIVERGENCE":      _daily_divergence_confirm,
}


# ── Stage 3: Quality gates + sizing ───────────────────────

def _quality_and_size(df, setup_type, regime, vix_action):
    """
    Final checks. Returns (ok, entry, sl, target, rr, qty, capital, atr_val).
    """
    cl  = df["close"]
    ltp = float(cl.iloc[-1])
    av  = float(_atr(df).iloc[-1])
    if np.isnan(av) or av <= 0:
        return False, *([0] * 6)

    rsi = _rsi(cl)
    rv  = float(rsi.iloc[-1])
    if rv > 68:
        return False, *([0] * 6)   # overbought

    # EMA200 quality check
    if len(cl) >= 200:
        ema200 = float(_ema(cl, 200).iloc[-1])
        if ltp < ema200 * 0.95:
            return False, *([0] * 6)   # deep below trend

    entry = ltp
    sl    = round(entry - ATR_SL_MULT * av, 2)
    tgt   = round(entry + ATR_TGT_MULT * av, 2)

    # ── Sanity checks — catch bad yfinance data ────────────
    # SL must be below entry (long trades only)
    if sl >= entry:
        print(f"  [SANITY] SL {sl} >= entry {entry} — bad ATR data, skipping")
        return False, *([0] * 5)
    # SL distance must be at least 0.3% of entry (not a phantom stop)
    if (entry - sl) / entry < 0.003:
        print(f"  [SANITY] SL too close: {round((entry-sl)/entry*100,3)}% — skipping")
        return False, *([0] * 5)
    # Target must be above entry
    if tgt <= entry:
        print(f"  [SANITY] Target {tgt} <= entry {entry} — bad data, skipping")
        return False, *([0] * 5)

    rr    = round((tgt - entry) / (entry - sl), 2) if entry > sl else 0
    if rr < MIN_RR:
        return False, *([0] * 5)

    return True, entry, sl, tgt, rr, av


# ── Stage 4: Confidence scoring ────────────────────────────

def _confidence_score(df, weekly_info, regime, rr, vix_val):
    """
    Score 0–6. Each factor is binary (green=1, not green=0).
    Returns (score, label, factor_detail_dict)
    """
    rsi   = _rsi(df["close"])
    ema20 = _ema(df["close"], 20)
    ema50 = _ema(df["close"], 50)
    adx   = _adx(df)
    rv    = float(rsi.iloc[-1])
    ltp   = float(df["close"].iloc[-1])
    adxv  = float(adx.iloc[-1])
    wscore = weekly_info.get("weekly_score", 1)

    factors = {}
    factors["Weekly setup"]    = wscore >= 3
    factors["RSI position"]    = TREND_RSI_MIN <= rv <= 65
    factors["Trend structure"] = ltp > float(ema20.iloc[-1]) > float(ema50.iloc[-1])
    factors["ADX strength"]    = adxv >= 25
    factors["R:R ratio"]       = rr >= 1.8
    factors["Market regime"]   = regime in ("BULLISH", "NEUTRAL", "OVERSOLD")

    score = sum(1 for v in factors.values() if v)

    if score >= STRONG_BUY_MIN_SCORE:
        label = "STRONG BUY"
    elif score >= BUY_MIN_SCORE:
        label = "BUY"
    else:
        label = "WATCH"

    return score, label, factors


# ── Main screener ──────────────────────────────────────────

def run_screener(all_data, nifty_rsi, nifty_adx, vix_val, vix_action):
    """
    Full pipeline: weekly → daily → quality → confidence.
    Returns list of pick dicts, sorted by confidence score.
    """
    regime, regime_desc = _regime(nifty_rsi, nifty_adx, vix_val, vix_action)

    # Hard block on VIX danger zone
    if vix_action == "avoid":
        print("  VIX DANGER ZONE — no picks")
        return [], regime, regime_desc

    weekly_detectors = [
        _weekly_trend_pullback,
        _weekly_oversold,
        _weekly_rsi_divergence,
    ]

    picks = []

    for ticker, df in all_data.items():
        if len(df) < 60:
            continue

        sector = SECTOR_MAP.get(ticker, "UNKNOWN")

        # In BEARISH regime only allow defensive sectors or oversold setups
        if regime == "BEARISH" and sector not in (
            "PHARMA", "FMCG", "IT", "HOSPITAL", "CHEMICAL"
        ):
            continue

        # Build weekly — skip current partial week
        wdf_full = _to_weekly(df)
        if len(wdf_full) < 14:
            continue
        wdf = wdf_full.iloc[:-1]   # completed weeks only

        # Stage 1: Weekly setup
        setup_type  = None
        weekly_info = {}
        for detector in weekly_detectors:
            found, info = detector(wdf)
            if found:
                setup_type  = info["setup"]
                weekly_info = info
                break
        if setup_type is None:
            continue

        # Stage 2: Daily confirmation
        confirm_fn = DAILY_CONFIRM.get(setup_type, _daily_trend_confirm)
        ok, reason = confirm_fn(df, weekly_info)
        if not ok:
            continue

        # Stage 3: Quality gates
        ok, entry, sl, tgt, rr, atr_val = _quality_and_size(
            df, setup_type, regime, vix_action
        )
        if not ok:
            continue

        # Stage 4: Confidence scoring
        score, conf_label, factors = _confidence_score(
            df, weekly_info, regime, rr, vix_val
        )

        # Position sizing based on confidence
        if vix_action == "reduce":
            size_pct = SIZE_BUY * 0.5
        elif conf_label == "STRONG BUY":
            size_pct = SIZE_STRONG_BUY
        elif conf_label == "BUY":
            size_pct = SIZE_BUY
        else:
            size_pct = SIZE_WATCH

        trade_capital = round(CAPITAL * size_pct, 0)
        qty           = max(1, int(trade_capital / entry))
        actual_capital = round(qty * entry, 0)

        # Expected value
        p_win   = SETUP_WIN_RATE.get(setup_type, 0.52)
        gain_r  = (tgt - entry) / entry
        loss_r  = (entry - sl)  / entry
        ev_pct  = round((p_win * gain_r - (1 - p_win) * loss_r) * 100, 2)
        if ev_pct < MIN_EV_PCT:
            continue

        # Gap detection
        gap_down = False
        try:
            if len(df) >= 2:
                gap_pct  = (float(df["open"].iloc[-1]) - float(df["close"].iloc[-2])) / float(df["close"].iloc[-2]) * 100
                gap_down = gap_pct < -0.5
        except Exception:
            pass

        setup_display = {
            "TREND_PULLBACK":      "Trend pullback to EMA20",
            "OVERSOLD_EXHAUSTION": "Oversold bounce setup",
            "RSI_DIVERGENCE":      "RSI divergence forming",
        }.get(setup_type, setup_type)

        picks.append({
            "ticker":       ticker,
            "name":         ticker.replace(".NS", ""),
            "sector":       sector,
            "entry":        round(entry, 2),
            "sl":           sl,
            "target":       tgt,
            "rr":           rr,
            "qty":          qty,
            "capital":      actual_capital,
            "atr":          round(atr_val, 2),
            "setup_type":   setup_type,
            "setup_display":setup_display,
            "conf_score":   score,
            "conf_label":   conf_label,
            "conf_factors": factors,
            "hold_days":    MAX_HOLD_DAYS,
            "ev_pct":       ev_pct,
            "p_win":        round(p_win * 100, 1),
            "weekly_info":  weekly_info,
            "reason":       reason,
            "gap_down":     gap_down,
            "vix_reduced":  vix_action == "reduce",
        })

    # Sort: STRONG BUY first, then by score desc, then by EV desc
    order = {"STRONG BUY": 0, "BUY": 1, "WATCH": 2}
    picks.sort(key=lambda x: (order.get(x["conf_label"], 3), -x["conf_score"], -x["ev_pct"]))

    print(f"  Signals found: {len(picks)}")
    for p in picks:
        print(f"    {p['name']:12s}  {p['conf_label']:12s}  "
              f"score={p['conf_score']}/6  EV={p['ev_pct']:.2f}%")

    return picks, regime, regime_desc
