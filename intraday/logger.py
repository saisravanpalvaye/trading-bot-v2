"""
intraday/logger.py — Decision audit trail. Writes EVERY decision.

One row per decision per stock per day. Includes kills — not just trades.
After 3 days you know more than 3 months of gut feel.

Schema:
  run_date, run_time, mode, symbol, stage, decision, reason,
  gap_pct, or_width_pct, rel_vol, entry, sl, target, qty,
  position_value, pnl_est (filled post-market manually or by scoreboard)
"""

import csv
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from config import DECISIONS_FILE

IST = timezone(timedelta(hours=5, minutes=30))

FIELDS = [
    "run_date",        # YYYY-MM-DD
    "run_time",        # HH:MM:SS IST
    "mode",            # pre_market | market_open | paper_replay
    "symbol",
    "stage",           # SCOUT | FILTER | ANALYST | RISK | EXECUTOR
    "decision",        # PASS | KILL | TRADE | SKIP
    "reason",          # human-readable kill reason or "ok"
    "gap_pct",         # overnight gap % (9:15 open vs prior close)
    "or_width_pct",    # (or_high - or_low) / or_low * 100
    "rel_vol",         # OR candle vol / 20d avg OR vol
    "nifty_ok",        # True/False — Nifty gate result
    "trend_ok",        # True/False — 50-EMA gate result
    "entry",           # Rs
    "sl",              # Rs
    "target",          # Rs
    "qty",             # shares
    "position_value",  # entry * qty
    "risk_amt",        # (entry - sl) * qty
    "pnl_est",         # filled post-market; leave blank at trade time
]


def _now_ist():
    now = datetime.now(IST)
    return now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S")


def log(symbol: str, stage: str, decision: str, reason: str = "ok",
        mode: str = "market_open", **kwargs):
    """
    Write one decision row to decisions.csv.

    Usage:
      logger.log("RELIANCE", "FILTER", "KILL", "gap_pct=2.3% > 2.0%",
                 gap_pct=2.3, or_width_pct=0.6)
      logger.log("INFY", "EXECUTOR", "TRADE", "ok",
                 entry=1800.0, sl=1791.0, target=1818.0, qty=22, position_value=39600)
    """
    run_date, run_time = _now_ist()
    row = {
        "run_date":       run_date,
        "run_time":       run_time,
        "mode":           mode,
        "symbol":         symbol,
        "stage":          stage,
        "decision":       decision,
        "reason":         reason,
        "gap_pct":        kwargs.get("gap_pct", ""),
        "or_width_pct":   kwargs.get("or_width_pct", ""),
        "rel_vol":        kwargs.get("rel_vol", ""),
        "nifty_ok":       kwargs.get("nifty_ok", ""),
        "trend_ok":       kwargs.get("trend_ok", ""),
        "entry":          kwargs.get("entry", ""),
        "sl":             kwargs.get("sl", ""),
        "target":         kwargs.get("target", ""),
        "qty":            kwargs.get("qty", ""),
        "position_value": kwargs.get("position_value", ""),
        "risk_amt":       kwargs.get("risk_amt", ""),
        "pnl_est":        kwargs.get("pnl_est", ""),
    }

    write_header = not DECISIONS_FILE.exists()
    with open(DECISIONS_FILE, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def save_candidates(candidates: list[dict]):
    """Persist SCOUT output to candidates.json for market_open to load."""
    from config import CANDIDATES_FILE
    with open(CANDIDATES_FILE, "w") as f:
        json.dump(candidates, f, indent=2, default=str)
    print(f"[LOGGER] {len(candidates)} candidates saved → {CANDIDATES_FILE.name}")


def load_candidates() -> list[dict]:
    """Load SCOUT output for market_open pipeline."""
    from config import CANDIDATES_FILE
    if not CANDIDATES_FILE.exists():
        print("[LOGGER] WARNING: candidates.json not found — run pre_market first")
        return []
    with open(CANDIDATES_FILE) as f:
        return json.load(f)


def today_trade_count() -> int:
    """Count TRADE decisions for today (for MAX_OPEN_POSITIONS check)."""
    if not DECISIONS_FILE.exists():
        return 0
    run_date, _ = _now_ist()
    count = 0
    with open(DECISIONS_FILE) as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["run_date"] == run_date and row["decision"] == "TRADE":
                count += 1
    return count


def print_summary(date_str: str = None):
    """Print today's decision summary to stdout."""
    if not DECISIONS_FILE.exists():
        print("[LOGGER] No decisions logged yet.")
        return

    run_date = date_str or _now_ist()[0]
    rows = []
    with open(DECISIONS_FILE) as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["run_date"] == run_date:
                rows.append(row)

    if not rows:
        print(f"[LOGGER] No decisions for {run_date}")
        return

    trades  = [r for r in rows if r["decision"] == "TRADE"]
    kills   = [r for r in rows if r["decision"] == "KILL"]
    passes  = [r for r in rows if r["decision"] == "PASS"]

    print(f"\n{'='*60}")
    print(f"  INTRADAY ORB — Decision Summary  {run_date}")
    print(f"{'='*60}")
    print(f"  Candidates screened : {len(passes) + len(kills) + len(trades)}")
    print(f"  Filter kills        : {len(kills)}")
    print(f"  Trades taken        : {len(trades)}")

    if kills:
        print(f"\n  Kill reasons:")
        for r in kills:
            print(f"    {r['symbol']:<14} [{r['stage']}] {r['reason']}")

    if trades:
        print(f"\n  Trades:")
        for r in trades:
            pv = f"Rs {float(r['position_value']):,.0f}" if r["position_value"] else "-"
            print(f"    {r['symbol']:<14} entry={r['entry']}  sl={r['sl']}  "
                  f"tgt={r['target']}  qty={r['qty']}  exposure={pv}")

    print(f"{'='*60}\n")
