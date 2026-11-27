"""
intraday/filter.py — FILTER: Kill signals with logged reasons.

Runs at 9:31 AM after the OR closes. Receives SCOUT candidates + live OR candle.
Applies all kill rules. Returns only stocks that passed every gate.

FILTER never guesses. Each kill has an exact reason string.
After 20 days you'll know which filter does the most work.
"""

import pandas as pd
from datetime import date, timedelta, datetime, timezone
from config import (
    OR_MIN_PCT, OR_MAX_PCT,
    GAP_MIN_PCT, GAP_MAX_PCT, USE_VOL_FILTER,
    VOL_FILTER_MIN_RATIO, TREND_FILTER, USE_NIFTY_FILTER,
)
import logger
import upstox_api

IST = timezone(timedelta(hours=5, minutes=30))


def _fetch_session_15m(instrument_key: str, session: date) -> pd.DataFrame | None:
    """
    FIX-3: 15-min candles via Upstox V3 (V2 never supported 15-minute).
    FIX-4: candles for EXACTLY `session` — no silent fallback to yesterday.
    If today's 9:15 candle isn't there, the stock is skipped, not traded on old data.
    """
    return upstox_api.candles_15m_for(instrument_key, session)


def _get_or_candle(df: pd.DataFrame) -> pd.Series | None:
    """Extract the 9:15 OR candle from intraday data."""
    or_time = datetime.strptime("09:15", "%H:%M").time()
    or_rows = df[df["datetime"].dt.time == or_time]
    if or_rows.empty:
        return None
    return or_rows.iloc[0]


def apply(candidates: list[dict], mode: str = "market_open",
          session: date | None = None) -> list[dict]:
    """
    Apply all filter gates to each candidate.
    Returns list of dicts that passed all gates (enriched with OR data).

    Each passing dict adds:
      or_high, or_low, or_width_pct, or_vol, rel_vol, gap_pct, day_open
    """
    session = session or date.today()
    session_str = session.strftime("%Y-%m-%d")
    print(f"\n[FILTER] Applying gates to {len(candidates)} candidates (session {session_str})")
    passed = []

    for c in candidates:
        sym  = c["symbol"]
        ikey = c["instrument_key"]

        # ── Gate 1: Trend (from SCOUT pre-computation) ─────────────────────────
        if TREND_FILTER and not c.get("trend_ok", True):
            reason = f"below 50-EMA (close={c['prior_close']:.2f} < EMA50={c['ema50']:.2f})"
            print(f"[FILTER] {sym:<14} KILL — {reason}")
            logger.log(sym, "FILTER", "KILL", reason, mode=mode,
                       trend_ok=False, nifty_ok=c.get("nifty_ok"))
            continue

        # ── Gate 2: Nifty macro gate (from SCOUT) ─────────────────────────────
        if USE_NIFTY_FILTER and not c.get("nifty_ok", True):
            reason = "Nifty 50 below 20-EMA — no long ORBs today"
            print(f"[FILTER] {sym:<14} KILL — {reason}")
            logger.log(sym, "FILTER", "KILL", reason, mode=mode,
                       trend_ok=c.get("trend_ok"), nifty_ok=False)
            continue

        # ── Stale-candidate guard: SCOUT facts must be for this session ───────
        if c.get("as_of") and c["as_of"] != session_str:
            reason = f"stale candidate (scouted for {c['as_of']}, session is {session_str})"
            print(f"[FILTER] {sym:<14} SKIP — {reason}")
            logger.log(sym, "FILTER", "SKIP", reason, mode=mode)
            continue

        # ── Fetch OR candle ────────────────────────────────────────────────────
        df_15m = _fetch_session_15m(ikey, session)
        if df_15m is None:
            reason = f"no 15m data for {session_str}"
            print(f"[FILTER] {sym:<14} SKIP — {reason}")
            logger.log(sym, "FILTER", "SKIP", reason, mode=mode)
            continue

        or_candle = _get_or_candle(df_15m)
        if or_candle is None:
            reason = "9:15 candle not found in 15m data"
            print(f"[FILTER] {sym:<14} SKIP — {reason}")
            logger.log(sym, "FILTER", "SKIP", reason, mode=mode)
            continue

        day_open = float(or_candle["open"])
        or_high  = float(or_candle["high"])
        or_low   = float(or_candle["low"])
        or_vol   = float(or_candle["volume"])

        # ── Gate 3: Overnight gap filter ──────────────────────────────────────
        prior_close = c["prior_close"]
        if prior_close > 0:
            gap_pct = (day_open - prior_close) / prior_close
            if gap_pct < GAP_MIN_PCT:
                reason = f"gap_pct={gap_pct*100:.2f}% < {GAP_MIN_PCT*100:.1f}% floor"
                print(f"[FILTER] {sym:<14} KILL — {reason}")
                logger.log(sym, "FILTER", "KILL", reason, mode=mode,
                           gap_pct=round(gap_pct*100,2))
                continue
            if gap_pct > GAP_MAX_PCT:
                reason = f"gap_pct={gap_pct*100:.2f}% > {GAP_MAX_PCT*100:.1f}% ceiling (exhausted gap-up)"
                print(f"[FILTER] {sym:<14} KILL — {reason}")
                logger.log(sym, "FILTER", "KILL", reason, mode=mode,
                           gap_pct=round(gap_pct*100,2))
                continue
        else:
            gap_pct = 0.0

        # ── Gate 4: OR width ───────────────────────────────────────────────────
        or_width     = or_high - or_low
        or_width_pct = or_width / day_open if day_open > 0 else 0
        if or_width_pct < OR_MIN_PCT:
            reason = f"or_width={or_width_pct*100:.3f}% < {OR_MIN_PCT*100:.1f}% (flat open)"
            print(f"[FILTER] {sym:<14} KILL — {reason}")
            logger.log(sym, "FILTER", "KILL", reason, mode=mode,
                       gap_pct=round(gap_pct*100,2), or_width_pct=round(or_width_pct*100,3))
            continue
        if or_width_pct > OR_MAX_PCT:
            reason = f"or_width={or_width_pct*100:.3f}% > {OR_MAX_PCT*100:.1f}% (gap day chaos)"
            print(f"[FILTER] {sym:<14} KILL — {reason}")
            logger.log(sym, "FILTER", "KILL", reason, mode=mode,
                       gap_pct=round(gap_pct*100,2), or_width_pct=round(or_width_pct*100,3))
            continue

        # ── Gate 5: Volume filter ──────────────────────────────────────────────
        or_vol_avg = c.get("or_vol_avg")
        if USE_VOL_FILTER and or_vol_avg and or_vol_avg > 0:
            rel_vol = or_vol / or_vol_avg
            if rel_vol < VOL_FILTER_MIN_RATIO:
                reason = f"rel_vol={rel_vol:.2f} < {VOL_FILTER_MIN_RATIO:.1f} (low participation)"
                print(f"[FILTER] {sym:<14} KILL — {reason}")
                logger.log(sym, "FILTER", "KILL", reason, mode=mode,
                           gap_pct=round(gap_pct*100,2), or_width_pct=round(or_width_pct*100,3),
                           rel_vol=round(rel_vol,2))
                continue
        else:
            rel_vol = or_vol / or_vol_avg if or_vol_avg else None

        # ── Passed all gates ───────────────────────────────────────────────────
        result = {
            **c,
            "day_open":      round(day_open, 2),
            "or_high":       round(or_high, 2),
            "or_low":        round(or_low, 2),
            "or_width_pct":  round(or_width_pct * 100, 3),
            "or_vol":        int(or_vol),
            "rel_vol":       round(rel_vol, 2) if rel_vol else None,
            "gap_pct":       round(gap_pct * 100, 2),
        }
        passed.append(result)
        # FIX-2: conditional inside a format spec is invalid Python → crashed here
        rv_txt = f"{rel_vol:.2f}" if rel_vol else "N/A"
        print(f"[FILTER] {sym:<14} PASS — gap={gap_pct*100:.2f}%  "
              f"or_width={or_width_pct*100:.2f}%  rel_vol={rv_txt}")
        logger.log(sym, "FILTER", "PASS", "all gates passed", mode=mode,
                   gap_pct=round(gap_pct*100,2), or_width_pct=round(or_width_pct*100,3),
                   rel_vol=round(rel_vol,2) if rel_vol else "",
                   nifty_ok=c.get("nifty_ok"), trend_ok=c.get("trend_ok"))

    print(f"[FILTER] {len(passed)}/{len(candidates)} passed all gates\n")
    return passed
