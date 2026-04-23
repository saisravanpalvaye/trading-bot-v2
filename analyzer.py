"""
analyzer.py — Signal detection engine for V6 N200c.

Pipeline per ticker:
  1. Sector uptrend gate (sector close > EMA20)
  2. Weekly setup detection (completed weeks only — B1 fix)
  3. OE Nifty50 gate (OVERSOLD_EXHAUSTION blocked for non-Nifty50 — B15 fix)
  4. Daily confirmation
  5. Quality gates (SL sanity, RR check, EMA200)
  6. Fixed fractional sizing (Rs 6000 risk / SL distance — V6)
  7. Duplicate position check (reads paper_trades.csv — B3 fix)
  8. Confidence scoring 0-7 (6 factors + RVOL)
  9. EV check

Returns list of picks. No Telegram. No file writes. Pure logic.
"""
import os
import csv
import pandas as pd
import numpy as np
from config import (
    CAPITAL, RISK_PER_TRADE, MAX_POSITION,
    ATR_SL_MULT, ATR_TGT_MULT, ATR_PARTIAL_MULT, ATR_PERIOD,
    HOLD_DAYS, WATCH_HOLD_DAYS, MIN_RR, MIN_EV_PCT, MIN_SL_DIST_PCT,
    TREND_RSI_MIN, TREND_RSI_MAX, ADX_TREND_MIN, RSI_PULLBACK_MIN,
    OVERSOLD_RSI_MAX, DIV_RSI_MAX,
    VIX_AVOID, VIX_REDUCE,
    SETUP_WIN_RATE, SECTOR_MAP, SECTOR_PROXY, NIFTY50,
    BUY_MIN_SCORE, RVOL_MIN,
    PAPER_TRADES_FILE,
)
from fetcher import sector_uptrend, to_weekly


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
        (lo - cl.shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()

def _adx(df, period=14):
    hi = df["high"]; lo = df["low"]; cl = df["close"]
    tr   = pd.concat([
        (hi - lo),
        (hi - cl.shift()).abs(),
        (lo - cl.shift()).abs(),
    ], axis=1).max(axis=1)
    atr_ = tr.ewm(span=period, adjust=False).mean()
    up   = (hi - hi.shift()).clip(lower=0)
    dn   = (lo.shift() - lo).clip(lower=0)
    up   = up.where(up > dn, 0)
    dn   = dn.where(dn > up, 0)
    pdi  = up.ewm(span=period, adjust=False).mean() / atr_ * 100
    ndi  = dn.ewm(span=period, adjust=False).mean() / atr_ * 100
    dx   = (abs(pdi - ndi) / (pdi + ndi).replace(0, np.nan) * 100).fillna(0)
    return dx.ewm(span=period, adjust=False).mean()


# ── Regime ────────────────────────────────────────────────

def _regime(nifty_rsi, nifty_adx, vix_val, vix_action):
    if vix_action == "avoid":
        return "HIGH_VIX", "Danger zone — stay in cash"
    if vix_action == "reduce":
        return "HIGH_VIX", "Elevated VIX — sizes halved"
    if nifty_rsi is None:
        return "NEUTRAL",  "RSI unavailable — trading cautiously"
    if nifty_rsi > 55:
        return "BULLISH",  "Uptrend — full position sizes"
    if nifty_rsi < 35:
        return "OVERSOLD", "Bounce zone — selective buys"
    if nifty_rsi < 43 and nifty_adx and nifty_adx > 22:
        return "BEARISH",  "Downtrend — defensive only"
    return "NEUTRAL", "Mixed signals — selective trades"


# ── VIX action label ───────────────────────────────────────

def get_vix_action(vix_val):
    """Returns 'avoid' | 'reduce' | 'normal' based on VIX value."""
    if vix_val is None:
        return "normal"
    if vix_val > VIX_AVOID:
        return "avoid"
    if vix_val > VIX_REDUCE:
        return "reduce"
    return "normal"


# ── OE Nifty50 gate ───────────────────────────────────────

def oe_allowed(ticker):
    """
    OVERSOLD_EXHAUSTION only fires for Nifty 50 stocks.
    B15 fix: midcap OE was 50% WR (noise), Nifty50 OE is 66% WR (signal).
    """
    return ticker in NIFTY50

def setup_allowed(ticker, setup_type):
    """Returns True if this setup is allowed for this ticker."""
    if setup_type == "OVERSOLD_EXHAUSTION":
        return oe_allowed(ticker)
    return True


# ── Confidence scoring ─────────────────────────────────────

def confidence_score(signal_dict):
    """
    Score 0-7. 7 factors, each binary (1 or 0).
    Factor 7 (RVOL) added as per Phase 2 backlog recommendation.
    """
    score = 0
    if signal_dict.get("sector_uptrend", False):      score += 1
    if signal_dict.get("rr", 0) >= 1.5:               score += 1
    if signal_dict.get("ev_pct", 0) >= 2.0:           score += 1
    if signal_dict.get("capital", 0) >= 120_000:      score += 1
    setup = signal_dict.get("setup_type", "")
    if setup == "RSI_DIVERGENCE":
        score += 2
    elif setup in ("TREND_PULLBACK", "BREAKOUT_PULLBACK"):
        score += 1
    # Factor 7: RVOL (relative volume > 1.5x 20-day avg)
    if signal_dict.get("rvol", 0) >= RVOL_MIN:        score += 1
    return score

def conf_label(score):
    """Returns 'BUY' if score >= BUY_MIN_SCORE else 'WATCH'."""
    return "BUY" if score >= BUY_MIN_SCORE else "WATCH"


# ── Duplicate position check ───────────────────────────────

def _open_tickers():
    """
    Read paper_trades.csv and return set of tickers with open positions.
    B3 fix: analyzer blocks signals on already-open positions.
    Returns empty set if file missing — safe default.
    """
    if not os.path.exists(PAPER_TRADES_FILE):
        return set()
    try:
        with open(PAPER_TRADES_FILE, newline="") as f:
            rows = list(csv.DictReader(f))
        return {
            r["ticker"] for r in rows
            if r.get("status", "").lower() == "open"
            and r.get("ticker", "").strip()
        }
    except Exception:
        return set()


# ── Stage 1: Weekly setup detectors ───────────────────────
# All receive COMPLETED weekly candles (partial week already stripped by fetcher)

def _weekly_trend_pullback(wdf):
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
    if len(wdf) < 10:
        return False, {}
    rsi = _rsi(wdf["close"])
    rv  = float(rsi.iloc[-1])
    if rv > OVERSOLD_RSI_MAX:   # V6: 38 not 50
        return False, {}
    rp3 = float(rsi.iloc[-3]) if len(rsi) >= 3 else rv + 5
    if rv > rp3 + 8:
        return False, {}
    low_52   = float(wdf["close"].iloc[-min(52, len(wdf)):].min())
    near_low = float(wdf["close"].iloc[-1]) < low_52 * 1.20
    avg_vol  = float(wdf["volume"].iloc[-15:].mean())
    vol_dry  = float(wdf["volume"].iloc[-1]) < avg_vol * 0.95
    score    = sum([rv < 32, vol_dry, near_low]) + 1
    return True, {
        "setup":        "OVERSOLD_EXHAUSTION",
        "weekly_rsi":   round(rv, 1),
        "vol_dry":      bool(vol_dry),
        "near_52w_low": bool(near_low),
        "weekly_score": min(int(score), 4),
    }


def _weekly_rsi_divergence(wdf):
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

_DAILY_CONFIRM = {
    "TREND_PULLBACK":      _daily_trend_confirm,
    "OVERSOLD_EXHAUSTION": _daily_oversold_confirm,
    "RSI_DIVERGENCE":      _daily_divergence_confirm,
}


# ── Stage 3: Quality gates + fixed fractional sizing ───────

def _quality_and_size(df, setup_type, vix_action):
    """
    Quality gates + fixed fractional position sizing (V6).
    Returns (ok, entry, sl, target, partial_tgt, rr, qty, capital, atr_val)
    """
    cl  = df["close"]
    ltp = float(cl.iloc[-1])
    av  = float(_atr(df).iloc[-1])
    if np.isnan(av) or av <= 0:
        return False, 0, 0, 0, 0, 0, 0, 0, 0

    rsi = _rsi(cl)
    rv  = float(rsi.iloc[-1])
    if rv > 68:
        return False, 0, 0, 0, 0, 0, 0, 0, 0  # overbought

    # EMA200 quality check (skip for OE — oversold stocks can be below)
    if len(cl) >= 200 and setup_type != "OVERSOLD_EXHAUSTION":
        ema200 = float(_ema(cl, 200).iloc[-1])
        if ltp < ema200 * 0.95:
            return False, 0, 0, 0, 0, 0, 0, 0, 0

    entry      = ltp
    sl         = round(entry - ATR_SL_MULT * av, 2)
    tgt        = round(entry + ATR_TGT_MULT * av, 2)
    partial_tgt = round(entry + ATR_PARTIAL_MULT * av, 2)

    # ── Sanity checks (B-series fixes) ────────────────────
    if sl >= entry:
        print(f"  [SANITY] SL {sl} >= entry {entry} — bad ATR data, skip")
        return False, 0, 0, 0, 0, 0, 0, 0, 0
    if (entry - sl) / entry < MIN_SL_DIST_PCT / 100:
        print(f"  [SANITY] SL too close: {(entry-sl)/entry*100:.3f}% — skip")
        return False, 0, 0, 0, 0, 0, 0, 0, 0
    if tgt <= entry:
        print(f"  [SANITY] Target {tgt} <= entry {entry} — skip")
        return False, 0, 0, 0, 0, 0, 0, 0, 0
    if partial_tgt >= tgt:
        return False, 0, 0, 0, 0, 0, 0, 0, 0

    rr = round((tgt - entry) / (entry - sl), 2) if entry > sl else 0
    if rr < MIN_RR:
        return False, 0, 0, 0, 0, 0, 0, 0, 0

    # ── Fixed fractional position sizing (V6) ─────────────
    # Size from risk: how many shares can we buy so max loss = RISK_PER_TRADE
    sl_distance = entry - sl
    qty = int(RISK_PER_TRADE / sl_distance)
    if qty < 1:
        return False, 0, 0, 0, 0, 0, 0, 0, 0

    # Apply VIX reduce: halve position when VIX 18-22
    if vix_action == "reduce":
        qty = max(1, qty // 2)

    # Cap at MAX_POSITION (Rs 1,50,000)
    if qty * entry > MAX_POSITION:
        qty = int(MAX_POSITION / entry)
    if qty < 1:
        return False, 0, 0, 0, 0, 0, 0, 0, 0

    capital = round(qty * entry, 0)

    return True, entry, sl, tgt, partial_tgt, rr, qty, capital, av


# ── Main screener ──────────────────────────────────────────

def run_screener(all_data, sector_data, nifty_rsi, nifty_adx,
                 vix_val, vix_action, size_multiplier=1.0):
    """
    Full V6 N200c pipeline for all tickers.
    Returns (picks_list, regime, regime_desc).

    Args:
        all_data:        {ticker: DataFrame} from fetcher.fetch_all()
        sector_data:     {proxy: DataFrame|None} from fetcher.fetch_sectors()
        nifty_rsi:       float or None
        nifty_adx:       float or None
        vix_val:         float or None
        vix_action:      'avoid' | 'reduce' | 'normal'
        size_multiplier: 0.5 if consecutive losses, else 1.0
    """
    regime, regime_desc = _regime(nifty_rsi, nifty_adx, vix_val, vix_action)

    if vix_action == "avoid":
        print("  VIX DANGER ZONE — no picks")
        return [], regime, regime_desc

    # Load currently open positions to block duplicates (B3 fix)
    open_set = _open_tickers()
    if open_set:
        print(f"  Open positions blocked from new signals: "
              f"{', '.join(t.replace('.NS','') for t in open_set)}")

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

        # Bearish regime: only defensive sectors allowed
        if regime == "BEARISH" and sector not in (
            "PHARMA", "FMCG", "IT", "CHEMICAL"
        ):
            continue

        # ── Sector uptrend gate ────────────────────────────
        proxy      = SECTOR_PROXY.get(sector)
        sec_df     = sector_data.get(proxy) if proxy else None
        sec_uptrend = sector_uptrend(sec_df)

        # Block TREND_PULLBACK and BREAKOUT_PULLBACK on down-sectors
        # OE and RSI_DIVERGENCE can still fire (mean-reversion setups)
        # — enforced per-setup below after setup detection

        # ── Stage 1: Weekly setup ─────────────────────────
        wdf_full = to_weekly(df)     # partial week already stripped in fetcher
        if len(wdf_full) < 14:
            continue
        # to_weekly() already strips partial — wdf_full IS the completed weeks
        wdf = wdf_full

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

        # ── OE Nifty50 gate (B15 fix) ─────────────────────
        if not setup_allowed(ticker, setup_type):
            continue

        # ── Sector uptrend gate (per setup) ───────────────
        if not sec_uptrend and setup_type in ("TREND_PULLBACK", "BREAKOUT_PULLBACK"):
            continue

        # ── Stage 2: Daily confirmation ────────────────────
        confirm_fn = _DAILY_CONFIRM.get(setup_type, _daily_trend_confirm)
        ok, reason = confirm_fn(df, weekly_info)
        if not ok:
            continue

        # ── Stage 3: Quality + sizing ──────────────────────
        ok, entry, sl, tgt, partial_tgt, rr, qty, capital, atr_val = \
            _quality_and_size(df, setup_type, vix_action)
        if not ok:
            continue

        # Apply consecutive-loss size multiplier from brain.py
        if size_multiplier < 1.0:
            qty = max(1, int(qty * size_multiplier))
            capital = round(qty * entry, 0)

        # ── RVOL (7th confidence factor) ───────────────────
        try:
            avg_vol = float(df["volume"].iloc[-20:].mean())
            today_vol = float(df["volume"].iloc[-1])
            rvol = round(today_vol / avg_vol, 2) if avg_vol > 0 else 0.0
        except Exception:
            rvol = 0.0

        # ── Duplicate position check (B3 fix) ─────────────
        already_open = ticker in open_set

        # ── EV calculation ─────────────────────────────────
        p_win  = SETUP_WIN_RATE.get(setup_type, 0.55)
        gain_r = (tgt - entry) / entry
        loss_r = (entry - sl)  / entry
        ev_pct = round((p_win * gain_r - (1 - p_win) * loss_r) * 100, 2)
        if ev_pct < MIN_EV_PCT and not already_open:
            continue

        # ── Confidence scoring (0-7) ───────────────────────
        signal_dict = {
            "sector_uptrend": sec_uptrend,
            "rr":             rr,
            "ev_pct":         ev_pct,
            "capital":        capital,
            "setup_type":     setup_type,
            "rvol":           rvol,
        }
        score = confidence_score(signal_dict)
        label = conf_label(score)

        setup_display = {
            "TREND_PULLBACK":      "Trend pullback to EMA20",
            "OVERSOLD_EXHAUSTION": "Oversold bounce (Nifty50)",
            "RSI_DIVERGENCE":      "RSI divergence forming",
            "BREAKOUT_PULLBACK":   "Breakout pullback",
        }.get(setup_type, setup_type)

        picks.append({
            "ticker":        ticker,
            "name":          ticker.replace(".NS", ""),
            "sector":        sector,
            "entry":         round(entry, 2),
            "sl":            sl,
            "target":        tgt,
            "partial_tgt":   partial_tgt,
            "rr":            rr,
            "qty":           qty,
            "capital":       capital,
            "atr":           round(atr_val, 2),
            "setup_type":    setup_type,
            "setup_display": setup_display,
            "conf_score":    score,
            "conf_label":    label,
            "hold_days":     HOLD_DAYS if label == "BUY" else WATCH_HOLD_DAYS,
            "ev_pct":        ev_pct,
            "p_win":         round(p_win * 100, 1),
            "rvol":          rvol,
            "weekly_info":   weekly_info,
            "reason":        reason,
            "already_open":  already_open,
            "vix_reduced":   vix_action == "reduce",
            "sector_uptrend": sec_uptrend,
        })

    # Sort: BUY first, then score desc, then EV desc
    order = {"BUY": 0, "WATCH": 1}
    picks.sort(key=lambda x: (
        order.get(x["conf_label"], 2),
        -x["conf_score"],
        -x["ev_pct"],
    ))

    print(f"  Signals found: {len(picks)}")
    for p in picks[:10]:  # show top 10
        tag = "★BUY" if p["conf_label"] == "BUY" else "◎WATCH"
        print(f"    {p['name']:12s}  {tag:6s}  "
              f"score={p['conf_score']}/7  EV={p['ev_pct']:.2f}%"
              f"{'  [OPEN]' if p['already_open'] else ''}")

    return picks, regime, regime_desc
