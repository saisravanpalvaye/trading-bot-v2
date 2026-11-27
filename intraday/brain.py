"""
intraday/brain.py — Orchestrator. Runs the pipeline in order.

Modes:
  pre_market   — Run at 9:00 AM IST. Calls SCOUT. Saves candidates.json.
  market_open  — Run at 9:31 AM IST. Loads candidates. FILTER → ANALYST → RISK → EXECUTOR.
  paper_replay — Run any time. Uses last N completed trading days to simulate
                 what the system would have done. Great for testing without market hours.

Usage:
  python brain.py --mode pre_market   --token YOUR_UPSTOX_TOKEN
  python brain.py --mode market_open  --token YOUR_UPSTOX_TOKEN
  python brain.py --mode paper_replay --token YOUR_UPSTOX_TOKEN --days 5

  Or set UPSTOX_TOKEN in .env and omit --token.

Output every run:
  intraday/decisions.csv  — full audit log (all stages, all decisions)
  intraday/candidates.json — SCOUT output (overwritten each pre_market run)
"""

import argparse
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Add parent dir so we can import sibling modules cleanly
sys.path.insert(0, str(Path(__file__).parent))

IST = timezone(timedelta(hours=5, minutes=30))


def now_ist() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")


def run_pre_market(mode: str = "pre_market"):
    """9:00 AM pipeline: SCOUT → save candidates.json"""
    import scout
    import logger

    print(f"\n{'='*60}")
    print(f"  INTRADAY ORB — PRE-MARKET  [{now_ist()}]")
    print(f"{'='*60}")

    candidates = scout.run(mode=mode)

    print(f"\n[BRAIN] Pre-market complete.")
    print(f"  {len(candidates)} candidates saved to candidates.json")
    print(f"  Run market_open at 9:31 AM to continue the pipeline.\n")
    logger.print_summary()


def run_market_open(mode: str = "market_open", stop_mode: str = "midpoint"):
    """9:31 AM pipeline: load candidates → FILTER → ANALYST → RISK → EXECUTOR"""
    import logger, filter as orb_filter, analyst, risk, executor

    print(f"\n{'='*60}")
    print(f"  INTRADAY ORB — MARKET OPEN  [{now_ist()}]")
    print(f"{'='*60}")

    candidates = logger.load_candidates()
    if not candidates:
        print("[BRAIN] No candidates — did pre_market run this morning?")
        return

    # FILTER
    filtered = orb_filter.apply(candidates, mode=mode)
    if not filtered:
        print("[BRAIN] All candidates killed by FILTER — no trades today")
        logger.print_summary()
        return

    # ANALYST
    ranked = analyst.run(filtered, stop_mode=stop_mode)
    if not ranked:
        print("[BRAIN] ANALYST produced no ranked signals")
        logger.print_summary()
        return

    # RISK
    approved = risk.apply(ranked, mode=mode)

    # EXECUTOR
    executor.run(approved, mode=mode)

    # Summary
    logger.print_summary()


def _replay_session():
    """Pick the session to replay: today if its 9:15 OR candle exists (market open
    or closed for the day), otherwise the last completed trading day."""
    from datetime import date
    import upstox_api, config
    from datetime import time as dtime
    today = date.today()
    df = upstox_api.candles_15m_for(config.NIFTY50_KEY, today)
    if df is not None and (df["datetime"].dt.time == dtime(9, 15)).any():
        return today
    d = upstox_api.daily(config.NIFTY50_KEY, today - timedelta(days=10), today - timedelta(days=1))
    if d is None or d.empty:
        return None
    return d["date"].iloc[-1]


def run_paper_replay(stop_mode: str = "midpoint", days: int = 5):
    """
    Replay last N completed trading days through the full pipeline.
    No timing constraints — runs any time.
    Useful for testing before going live.
    """
    import scout
    import logger, filter as orb_filter, analyst, risk, executor

    print(f"\n{'='*60}")
    print(f"  INTRADAY ORB — PAPER REPLAY  [{now_ist()}]  ({days} days)")
    print(f"  stop_mode={stop_mode}")
    print(f"{'='*60}\n")

    session = _replay_session()
    if session is None:
        print("[BRAIN] Could not determine a session to replay — check token / Upstox errors above")
        return
    if days != 1:
        print(f"[BRAIN] Note: multi-day replay not built yet — replaying 1 session ({session})")
    print(f"[BRAIN] Replaying session {session}\n")

    # SCOUT uses bars strictly before `session`; FILTER uses `session`'s own OR candle
    candidates = scout.run(mode="paper_replay", as_of=session)

    if not candidates:
        print("[BRAIN] SCOUT returned no candidates")
        return

    filtered = orb_filter.apply(candidates, mode="paper_replay", session=session)
    if not filtered:
        print("[BRAIN] All candidates killed by FILTER")
        logger.print_summary()
        return

    ranked = analyst.run(filtered, stop_mode=stop_mode)
    if not ranked:
        print("[BRAIN] No ranked signals from ANALYST")
        logger.print_summary()
        return

    approved = risk.apply(ranked, mode="paper_replay")
    executor.run(approved, mode="paper_replay")
    logger.print_summary()


def main():
    parser = argparse.ArgumentParser(description="Intraday ORB Brain — 6-module pipeline")
    parser.add_argument("--mode", choices=["pre_market", "market_open", "paper_replay"],
                        default="paper_replay",
                        help="Run mode (default: paper_replay)")
    parser.add_argument("--token", default="",
                        help="Upstox API access token (overrides UPSTOX_TOKEN env var)")
    parser.add_argument("--stop", choices=["midpoint", "low"], default="midpoint",
                        help="Stop placement: midpoint (tighter) or low (wider). Default: midpoint")
    parser.add_argument("--days", type=int, default=5,
                        help="Days for paper_replay mode (default: 5)")
    args = parser.parse_args()

    # Token injection
    if args.token:
        os.environ["UPSTOX_TOKEN"] = args.token

    # Reload config after token is set
    import config
    errors = config.validate()
    if errors:
        for e in errors:
            print(f"[CONFIG ERROR] {e}")
        if any("UPSTOX_TOKEN" in e for e in errors):
            print("\nSet UPSTOX_TOKEN in .env or pass --token YOUR_TOKEN")
            sys.exit(1)

    if args.mode == "pre_market":
        run_pre_market()
    elif args.mode == "market_open":
        run_market_open(stop_mode=args.stop)
    elif args.mode == "paper_replay":
        run_paper_replay(stop_mode=args.stop, days=args.days)


if __name__ == "__main__":
    main()
