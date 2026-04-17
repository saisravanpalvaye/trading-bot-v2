"""
brain.py — Master orchestrator for V6 N200c. Runs at 8 PM IST.

Flow:
  1. Check if tomorrow is a market day
  2. Check monthly loss floor (reads trade_log.csv)
  3. Check consecutive losses → size_multiplier
  4. Fetch all stock data + sector data + Nifty + VIX
  5. Run screener
  6. Write signals.json (always — even on error)

Nothing else. No Telegram. No paper_trades writes.
If it fails, signals.json gets an error key so alert.py always has something.
"""
import csv
import json
import os
import sys
from datetime import date, datetime, timezone, timedelta
from config import (
    SIGNALS_FILE, TRADE_LOG_FILE,
    NSE_HOLIDAYS_2026,
    MONTHLY_LOSS_FLOOR, CONSEC_LOSS_LIMIT,
    VIX_AVOID, VIX_REDUCE,
)

IST = timezone(timedelta(hours=5, minutes=30))


# ── Timezone helper ────────────────────────────────────────

def get_trade_date():
    """
    Calculate the next market day as a YYYY-MM-DD string.
    Uses IST timezone always (B10 fix — never uses date.today()).
    """
    now = datetime.now(IST)
    # If running between midnight and 6 AM IST, today may be the trade date
    # (handles GitHub Actions delays or manual late-night runs)
    if now.hour < 6:
        today_ist = now.date()
        if (today_ist.weekday() < 5 and
                today_ist.isoformat() not in NSE_HOLIDAYS_2026):
            return today_ist.isoformat()
    return _next_market_day(now).strftime("%Y-%m-%d")


def _next_market_day(from_dt):
    """Skip weekends and NSE holidays. Returns date object."""
    d = from_dt.date() + timedelta(days=1)
    while d.weekday() >= 5 or d.isoformat() in NSE_HOLIDAYS_2026:
        d += timedelta(days=1)
    return d


# ── Market day check ───────────────────────────────────────

def is_market_day(today_ist=None, force=False):
    """
    Check if tomorrow is a market day (brain runs at 8 PM to prep for tomorrow).
    Returns (bool, reason_string).
    """
    if force:
        return True, "Forced run"
    if today_ist is None:
        today_ist = datetime.now(IST).date()
    tomorrow = today_ist + timedelta(days=1)
    if tomorrow.weekday() >= 5:
        return False, f"Tomorrow {tomorrow.isoformat()} is weekend"
    if tomorrow.isoformat() in NSE_HOLIDAYS_2026:
        return False, f"Tomorrow {tomorrow.isoformat()} is NSE Holiday"
    return True, f"Market open tomorrow {tomorrow.isoformat()}"


# ── Risk management: monthly floor ────────────────────────

def get_monthly_pnl(trade_log_path=None):
    """
    Sum P&L of all trades closed in the current calendar month.
    Reads trade_log.csv — the archive of closed trades.
    Returns 0 if file missing (safe default).
    B5 fix: monthly floor check implemented here.
    """
    path = trade_log_path or TRADE_LOG_FILE
    if not os.path.exists(path):
        return 0
    try:
        now        = datetime.now(IST)
        month_str  = now.strftime("%Y-%m")
        total      = 0.0
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                exit_date = row.get("exit_date", "")
                if exit_date.startswith(month_str):
                    try:
                        total += float(row.get("pnl", 0) or 0)
                    except ValueError:
                        pass
        return round(total, 2)
    except Exception:
        return 0


def is_floor_hit(trade_log_path=None):
    """
    Returns True if this month's losses exceed MONTHLY_LOSS_FLOOR.
    B5 fix: stops new signals when monthly loss > Rs 30,000.
    """
    monthly = get_monthly_pnl(trade_log_path)
    return monthly < -abs(MONTHLY_LOSS_FLOOR)


# ── Risk management: consecutive losses ───────────────────

def count_consecutive_losses(trade_log_path=None):
    """
    Count consecutive losses from the most recent trades (newest first).
    Stops counting at first WIN.
    Returns 0 if file missing.
    B4 fix: consecutive loss tracking.
    """
    path = trade_log_path or TRADE_LOG_FILE
    if not os.path.exists(path):
        return 0
    try:
        with open(path, newline="") as f:
            rows = list(csv.DictReader(f))
        if not rows:
            return 0
        # Sort by exit_date descending (most recent first)
        rows_sorted = sorted(
            rows,
            key=lambda r: r.get("exit_date", ""),
            reverse=True,
        )
        count = 0
        for row in rows_sorted:
            result = row.get("result", "").upper()
            if result == "LOSS":
                count += 1
            elif result == "WIN":
                break   # streak ends at first WIN
        return count
    except Exception:
        return 0


def get_size_multiplier(trade_log_path=None):
    """
    Returns 0.5 if CONSEC_LOSS_LIMIT consecutive losses, else 1.0.
    B4 fix: automatic size reduction after losing streak.
    """
    consec = count_consecutive_losses(trade_log_path)
    if consec >= CONSEC_LOSS_LIMIT:
        return 0.5
    return 1.0


# ── signals.json validation ────────────────────────────────

def validate_signals(signals):
    """
    Validate signals dict has all required keys.
    B20 fix: alert.py reads validated schema only.
    Returns True if valid.
    """
    required = {
        "date", "regime", "vix", "vix_action",
        "nifty_rsi", "floor_hit", "consec_losses",
        "size_multiplier", "picks",
    }
    if not isinstance(signals, dict):
        return False
    if not required.issubset(signals.keys()):
        return False
    if not isinstance(signals.get("picks"), list):
        return False
    return True


def validate_pick(pick):
    """Validate a single pick dict has required fields."""
    required = {
        "ticker", "setup_type", "conf_label", "conf_score",
        "entry", "sl", "target", "partial_tgt", "rr",
        "qty", "capital", "ev_pct", "sector",
    }
    return isinstance(pick, dict) and required.issubset(pick.keys())


# ── signals.json helpers ───────────────────────────────────

def build_signals(data, floor_hit=False, picks=None, vix_val=None,
                  vix_action="normal", size_multiplier=1.0,
                  consec_losses=0, nifty_rsi=None, nifty_adx=None,
                  regime="NEUTRAL", regime_desc="", trade_date=None,
                  error=None):
    """Build a validated signals dict."""
    return {
        "date":            trade_date or get_trade_date(),
        "generated_at":    datetime.now(IST).strftime("%H:%M IST"),
        "market_open":     True,
        "regime":          regime,
        "regime_desc":     regime_desc,
        "nifty_rsi":       nifty_rsi,
        "nifty_adx":       nifty_adx,
        "vix":             vix_val,
        "vix_action":      vix_action,
        "floor_hit":       floor_hit,
        "consec_losses":   consec_losses,
        "size_multiplier": size_multiplier,
        "picks":           picks or [],
        "error":           error,
    }


def build_signals_from_vix(vix_val):
    """Build minimal signals dict based on VIX value only (for tests)."""
    from analyzer import get_vix_action
    action = get_vix_action(vix_val)
    mult   = 0.5 if action == "reduce" else 1.0
    return {
        "vix":             vix_val,
        "vix_action":      action,
        "size_multiplier": mult,
        "picks":           [],
        "floor_hit":       False,
        "consec_losses":   0,
    }


# ── File writer ────────────────────────────────────────────

def _write(payload):
    """Write signals.json. Cleans payload to JSON-safe types."""
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


# ── Main ───────────────────────────────────────────────────

def run(force=False):
    now        = datetime.now(IST)
    trade_date = get_trade_date()

    print(f"\n{'='*52}")
    print(f"  BRAIN  {now.strftime('%d %b %Y  %H:%M IST')}")
    print(f"  Trade date: {trade_date}")
    print(f"{'='*52}\n")

    # ── [0] Market day check ──────────────────────────────
    today_ist        = now.date()
    market_ok, reason = is_market_day(today_ist, force)
    if not market_ok:
        print(f"  {reason} — writing no-market signal")
        _write({
            "date": trade_date, "generated_at": now.strftime("%H:%M IST"),
            "market_open": False, "reason": reason,
            "regime": "CLOSED", "regime_desc": reason,
            "nifty_rsi": None, "nifty_adx": None,
            "vix": None, "vix_action": "normal",
            "floor_hit": False, "consec_losses": 0,
            "size_multiplier": 1.0, "picks": [], "error": None,
        })
        return

    # ── [1] Risk management checks ────────────────────────
    print("[1/4] Risk management checks...")

    floor_hit     = is_floor_hit()
    consec_losses = count_consecutive_losses()
    size_mult     = get_size_multiplier()

    print(f"  Monthly floor hit: {floor_hit}")
    print(f"  Consecutive losses: {consec_losses} → size_multiplier={size_mult}")

    if floor_hit:
        print("  FLOOR HIT — no new signals this month")
        _write(build_signals(
            {}, floor_hit=True, picks=[],
            trade_date=trade_date,
            regime="NEUTRAL", regime_desc="Monthly loss floor hit — no new signals",
        ))
        return

    # ── [2] Fetch data ────────────────────────────────────
    print("\n[2/4] Fetching market data...")
    try:
        from fetcher import fetch_all, fetch_sectors, fetch_nifty, fetch_vix
        all_data              = fetch_all()
        sector_data           = fetch_sectors()
        nifty_rsi, nifty_adx = fetch_nifty()
        vix_val, vix_lbl, vix_action = fetch_vix()
        print(f"  Nifty RSI: {nifty_rsi}  ADX: {nifty_adx}")
        print(f"  VIX: {vix_val} ({vix_lbl})")
    except Exception as e:
        print(f"  FETCH FAILED: {e}")
        _write(build_signals(
            {}, trade_date=trade_date,
            regime="UNKNOWN", regime_desc="Fetch failed",
            error=str(e),
        ))
        return

    # ── [3] Screen ────────────────────────────────────────
    print("\n[3/4] Screening stocks...")
    try:
        from analyzer import run_screener
        picks, regime, regime_desc = run_screener(
            all_data, sector_data, nifty_rsi, nifty_adx,
            vix_val, vix_action, size_mult,
        )
    except Exception as e:
        print(f"  SCREENER FAILED: {e}")
        _write(build_signals(
            {}, trade_date=trade_date,
            nifty_rsi=nifty_rsi, vix_val=vix_val, vix_action=vix_action,
            regime="UNKNOWN", regime_desc="Screener failed",
            error=str(e),
        ))
        return

    # ── [4] Write signals.json ────────────────────────────
    print("\n[4/4] Writing signals.json...")
    payload = build_signals(
        {},
        floor_hit=floor_hit,
        picks=picks,
        vix_val=vix_val,
        vix_action=vix_action,
        size_multiplier=size_mult,
        consec_losses=consec_losses,
        nifty_rsi=nifty_rsi,
        nifty_adx=nifty_adx,
        regime=regime,
        regime_desc=regime_desc,
        trade_date=trade_date,
    )
    _write(payload)

    print(f"\n  Done. {len(picks)} signal(s). Regime: {regime}")
    return payload


if __name__ == "__main__":
    force = "--force" in sys.argv
    run(force=force)
