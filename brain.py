"""
brain.py — Master orchestrator. Runs at 8 PM IST.
Fetches data → detects signals → writes signals.json.
Nothing else. No Telegram. No logging to CSV.
If it fails, signals.json gets an error key so alert.py always has something to read.
"""
import json
import sys
from datetime import date, datetime, timezone, timedelta
from config import SIGNALS_FILE, NSE_HOLIDAYS_2026

IST = timezone(timedelta(hours=5, minutes=30))


def is_market_day(force=False):
    """
    Brain runs at 8 PM IST to prepare signals for TOMORROW's market open.
    So we check if TOMORROW is a market day, not today.
    """
    if force:
        return True, "Forced run"
    tomorrow = date.today() + timedelta(days=1)
    if tomorrow.weekday() >= 5:
        return False, f"Tomorrow is weekend — no signals needed"
    if tomorrow.isoformat() in NSE_HOLIDAYS_2026:
        return False, f"Tomorrow is NSE Holiday ({tomorrow.isoformat()})"
    return True, f"Scanning for tomorrow {tomorrow.isoformat()}"


def run(force=False):
    now   = datetime.now(IST)
    today = now.strftime("%Y-%m-%d")

    print(f"\n{'='*52}")
    print(f"  BRAIN  {now.strftime('%d %b %Y  %H:%M IST')}")
    print(f"{'='*52}\n")

    # ── Market day check ──────────────────────────────────
    market_open, reason = is_market_day(force)
    if not market_open:
        print(f"  {reason} — writing no-market signal")
        payload = {
            "date":         today,
            "market_open":  False,
            "reason":       reason,
            "regime":       "CLOSED",
            "regime_desc":  reason,
            "nifty_rsi":    None,
            "vix_val":      None,
            "vix_action":   "normal",
            "picks":        [],
            "error":        None,
        }
        _write(payload)
        return payload

    # ── Fetch data ────────────────────────────────────────
    print("[1/3] Fetching market data...")
    try:
        from fetcher import fetch_all, fetch_nifty, fetch_vix
        all_data              = fetch_all()
        nifty_rsi, nifty_adx = fetch_nifty()
        vix_val, vix_lbl, vix_action = fetch_vix()
        print(f"  Nifty RSI: {nifty_rsi}  ADX: {nifty_adx}")
        print(f"  VIX: {vix_val} ({vix_lbl})")
    except Exception as e:
        print(f"  FETCH FAILED: {e}")
        _write({
            "date": today, "market_open": True,
            "regime": "UNKNOWN", "regime_desc": "Fetch failed",
            "nifty_rsi": None, "vix_val": None, "vix_action": "normal",
            "picks": [], "error": str(e),
        })
        return

    # ── Screen ────────────────────────────────────────────
    print("\n[2/3] Screening stocks...")
    try:
        from analyzer import run_screener
        picks, regime, regime_desc = run_screener(
            all_data, nifty_rsi, nifty_adx, vix_val, vix_action
        )
    except Exception as e:
        print(f"  SCREENER FAILED: {e}")
        _write({
            "date": today, "market_open": True,
            "regime": "UNKNOWN", "regime_desc": "Screener failed",
            "nifty_rsi": nifty_rsi, "vix_val": vix_val,
            "vix_action": vix_action, "picks": [], "error": str(e),
        })
        return

    # ── Write signals.json ────────────────────────────────
    print("\n[3/3] Writing signals.json...")
    payload = {
        "date":         today,
        "generated_at": now.strftime("%H:%M IST"),
        "market_open":  True,
        "regime":       regime,
        "regime_desc":  regime_desc,
        "nifty_rsi":    nifty_rsi,
        "nifty_adx":    nifty_adx,
        "vix_val":      vix_val,
        "vix_label":    vix_lbl,
        "vix_action":   vix_action,
        "picks":        picks,
        "error":        None,
    }
    _write(payload)

    print(f"\n  Done. {len(picks)} signal(s) found.")
    print(f"  Regime: {regime} — {regime_desc}")
    return payload


def _write(payload):
    """Write signals.json. Makes picks serializable."""
    def _clean(obj):
        if isinstance(obj, dict):
            return {k: _clean(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_clean(v) for v in obj]
        if isinstance(obj, (bool, int, float, str, type(None))):
            return obj
        return str(obj)

    with open(SIGNALS_FILE, "w") as f:
        json.dump(_clean(payload), f, indent=2)
    print(f"  Written: {SIGNALS_FILE}")


if __name__ == "__main__":
    force = "--force" in sys.argv
    run(force=force)